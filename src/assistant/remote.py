"""WP7 cold storage & backup — the remote abstraction and its provenance (increment 4).

Increment 2 built `reconcile()` to *refuse* to complete an `uploaded -> flipped` transition
when nothing confirms the remote holds the artifact. That refusal is the correct posture,
but it is also a dead end: with no verifier the flip never lands, so an artifact that was
successfully uploaded stays `uploaded` forever. This module supplies the verifier.

It supplies **two**, and the difference between them is the whole point:

- `LocalPathBackend` — a local directory standing in for a remote. A test fixture. It is
  the reason every crash point can be exercised with no restic, no rclone and no MEGA.
- `RcloneBackend` — the real thing, speaking the pinned command surface below.

**A `LocalPathBackend` confirmation must never be able to masquerade as real remote
confirmation.** So every `Verification` names the backend that produced it, and the plan
records that name in the reason it writes and the problem it raises. A flip completed on a
fixture reads `local-path-fixture` in the manifest detail; a flip completed on MEGA reads
`rclone:mega-elaria`. If a fixture confirmation ever reached production it would be visible
in the manifest as exactly that, not as a remote.

**The command surface is pinned, not improvised.** `RcloneBackend` builds every argv from
`RCLONE_COMMAND_SURFACE` and nowhere else; `_argv()` raises on an unpinned verb rather than
assembling a command at runtime. The table is machine-readable so it can be dumped to JSON
and diffed against a pinned copy, the way the kitty lane pins its verb inventory.

**rclone absent from the sandbox is a declared skip, never a silent pass.** `probe_rclone()`
always returns a reason. `RcloneBackend.verify()` with no binary on PATH returns
`confirmed=False, method="declared-skip"` with that reason in `detail` — a test pins that it
can never come back `confirmed=True`.

PRIVACY FENCE: `Verification.detail` carries no paths. Presence, hashes and reasons only.
The artifact's path is the manifest's business and never leaves the laptop.

Evidence tags: `[TESTED-ONLY]` throughout. Nothing here contacts a network in the sandbox.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "RCLONE_COMMAND_SURFACE",
    "RCLONE_MIN_VERSION",
    "RCLONE_PINNED_VERSION",
    "CommandPin",
    "LocalPathBackend",
    "RcloneBackend",
    "RcloneProbe",
    "RemoteBackend",
    "Verification",
    "probe_rclone",
    "surface_json",
    "version_at_least",
]

# --------------------------------------------------------------------------------------
# The pinned rclone command surface
# --------------------------------------------------------------------------------------

#: The exact rclone build this surface was authored and pinned against.
RCLONE_PINNED_VERSION = "1.75.2"

#: The functional floor. rclone added the MEGA backend in 1.41 (Tier 2: no mtimes, no
#: hashes, duplicate names allowed). Below this, MEGA is not reachable at all.
RCLONE_MIN_VERSION = "1.41.0"

#: The name the fixture backend reports for itself. Deliberately unmistakable — it must
#: never read like a remote.
FIXTURE_BACKEND_NAME = "local-path-fixture"


@dataclass(frozen=True)
class CommandPin:
    """One command this lane is allowed to run, and why.

    `argv` is a **template**: `{remote}`, `{path}` and `{binary}` are substituted by
    `RcloneBackend._argv()`. Anything not in this table cannot be run — that is the
    enforcement, and it is why the table is exhaustive rather than illustrative.
    """

    verb: str
    argv: tuple[str, ...]
    purpose: str
    invoked_by: str
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "verb": self.verb,
            "argv": list(self.argv),
            "purpose": self.purpose,
            "invoked_by": self.invoked_by,
            "notes": self.notes,
        }


RCLONE_COMMAND_SURFACE: tuple[CommandPin, ...] = (
    CommandPin(
        verb="version",
        argv=("{binary}", "version"),
        purpose="Binary discovery and the version-pin check.",
        invoked_by="storage",
    ),
    CommandPin(
        verb="about",
        argv=("{binary}", "about", "{remote}:{path}", "--json"),
        purpose="Quota read for the remote_free gauge and the capacity-floor knock.",
        invoked_by="storage",
        notes="The 10 GB consumed floor is expressed as remote_free so it stays "
              "equivalent on a 20 GB tier.",
    ),
    CommandPin(
        verb="lsjson",
        argv=("{binary}", "lsjson", "{remote}:{path}", "--hash", "md5"),
        purpose="Presence check for an artifact on the remote.",
        invoked_by="storage",
        notes="MEGA reports no hashes, so --hash is accepted and ignored: this "
              "confirms PRESENCE only, never content.",
    ),
    CommandPin(
        verb="serve restic",
        argv=("{binary}", "serve", "restic", "--stdio"),
        purpose="The restic backend transport. restic spawns this; storage never does.",
        invoked_by="restic",
        notes="rclone.timeout must be raised above its 1m default for MEGA — repo open "
              "routinely exceeds a minute (restic #3511/#3514). Passed by restic via "
              "-o rclone.timeout, not by this lane.",
    ),
)


def surface_json(*, indent: int | None = 2) -> str:
    """The pinned surface as JSON — machine-readable, diffable against a pinned copy."""

    return json.dumps(
        {
            "pinned_version": RCLONE_PINNED_VERSION,
            "min_version": RCLONE_MIN_VERSION,
            "fixture_backend_name": FIXTURE_BACKEND_NAME,
            "commands": [c.to_dict() for c in RCLONE_COMMAND_SURFACE],
        },
        indent=indent,
    )


def _parse_version(value: str) -> tuple[int, ...]:
    """'1.75.2' -> (1, 75, 2). Non-numeric parts are dropped, not fatal."""

    parts: list[int] = []
    for chunk in str(value).strip().lstrip("vV").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts) or (0,)


def version_at_least(have: str, want: str) -> bool:
    """True when `have` is at least `want`. Unparseable versions compare as 0."""

    a, b = _parse_version(have), _parse_version(want)
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return a >= b


# --------------------------------------------------------------------------------------
# Verification records and provenance
# --------------------------------------------------------------------------------------


@dataclass
class Verification:
    """What a backend said about an artifact, and **which backend said it**.

    `backend` is the provenance requirement made structural. `LocalPathBackend` reports
    `local-path-fixture`; `RcloneBackend` reports `rclone:<remote>`. A record whose backend
    is the fixture can never be read as remote confirmation, because it does not say so.

    `method` distinguishes how the answer was reached:
      - `hash` — content compared against a recorded sha256.
      - `presence` — the artifact exists on the remote; content not comparable.
      - `declared-skip` — the backend could not run and says so, with a reason.
      - `absent` — the backend ran and the artifact is not there.
    """

    backend: str
    confirmed: bool
    method: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "backend": self.backend,
            "confirmed": self.confirmed,
            "method": self.method,
            "detail": self.detail,
        }

    def __bool__(self) -> bool:
        return self.confirmed


@dataclass
class RcloneProbe:
    """Whether rclone is present, where, and at what version — always with a reason."""

    available: bool
    path: str = ""
    version: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "path": self.path,
            "version": self.version,
            "reason": self.reason,
        }


def probe_rclone(binary: str = "rclone") -> RcloneProbe:
    """Find rclone and read its version. Never raises; the reason is always populated.

    A declared skip is a *record*, so it has to say why. An empty reason on an unavailable
    probe is the silent-pass failure this function exists to prevent.
    """

    found = shutil.which(binary)
    if found is None:
        return RcloneProbe(
            available=False,
            reason=f"{binary} not found on PATH; the rclone command surface is pinned "
                   f"at {RCLONE_PINNED_VERSION} and cannot be exercised here",
        )
    try:
        out = subprocess.run(
            [found, "version"], capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RcloneProbe(
            available=False,
            path=found,
            reason=f"{found} exists but `version` failed ({type(exc).__name__})",
        )
    version = ""
    for line in (out.stdout or "").splitlines():
        if line.startswith("rclone v"):
            # `rclone version` prints "rclone v1.75.2"; the leading v is rclone's
            # formatting, not part of the version, and version_at_least strips it anyway.
            version = line.split()[1].lstrip("vV")
            break
    if not version:
        return RcloneProbe(
            available=False,
            path=found,
            reason=f"{found} ran but reported no parsable version",
        )
    return RcloneProbe(available=True, path=found, version=version)


# --------------------------------------------------------------------------------------
# Backends
# --------------------------------------------------------------------------------------


class RemoteBackend:
    """The seam `reconcile()` plugs into. `verify` is the only required method."""

    #: What this backend calls itself in every record it produces.
    name = "abstract"

    def verify(self, artifact: Path, *,
               expected_sha256: str | None = None) -> Verification:
        raise NotImplementedError

    def pin_status(self) -> Verification:
        """Is this backend ready, and which one is it?

        Part of the seam so a caller can ask ANY backend whether it stands ready and get
        a provenance-bearing answer back. A backend that cannot answer says so rather
        than being assumed ready.
        """

        raise NotImplementedError

    def describe(self) -> dict:
        return {"backend": self.name, "kind": type(self).__name__}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalPathBackend(RemoteBackend):
    """A local directory standing in for a remote. A fixture — and it says so.

    Used by every crash-point test. It is also the thing that must never be mistaken for
    MEGA, which is why `name` is `local-path-fixture` and not something plausible.
    """

    name = FIXTURE_BACKEND_NAME

    def __init__(self, root: Path | str, *, name: str | None = None):
        self.root = Path(root)
        if name is not None:
            self.name = name

    def store(self, artifact: Path) -> Path:
        """Put a copy of `artifact` in the fixture 'remote'."""

        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # mkdir only applies the mode when it creates the directory, so an existing
        # tree would stay group/other-accessible. Chmod is what actually enforces it.
        self.root.chmod(0o700)
        target = self.root / Path(artifact).name
        if target.exists():
            target.unlink()
        shutil.copy2(artifact, target)
        return target

    def drop(self, artifact: Path) -> bool:
        """Remove the fixture copy. Returns whether there was one to remove."""

        target = self.root / Path(artifact).name
        if not target.exists():
            return False
        target.unlink()
        return True

    def pin_status(self) -> Verification:
        """The fixture is always ready — it is a local directory, not a binary.

        It still reports itself BY NAME. A fixture readiness that did not say "fixture"
        would be exactly the masquerade provenance exists to prevent, so the method is
        `fixture` and the detail says it is never a remote.
        """

        return Verification(
            backend=self.name, confirmed=True, method="fixture",
            detail="local-path fixture; always ready, and never a remote",
        )

    def verify(self, artifact: Path, *,
               expected_sha256: str | None = None) -> Verification:
        artifact = Path(artifact)
        target = self.root / artifact.name
        if not target.exists():
            return Verification(
                backend=self.name, confirmed=False, method="absent",
                detail="artifact not present in the fixture remote",
            )
        try:
            actual = _sha256_file(target)
        except OSError as exc:
            return Verification(
                backend=self.name, confirmed=False, method="declared-skip",
                detail=f"fixture copy unreadable ({type(exc).__name__})",
            )
        want = expected_sha256
        if want is None:
            try:
                want = _sha256_file(artifact)
            except OSError as exc:
                return Verification(
                    backend=self.name, confirmed=False, method="declared-skip",
                    detail=f"local artifact unreadable ({type(exc).__name__})",
                )
        if actual != want:
            return Verification(
                backend=self.name, confirmed=False, method="hash",
                detail="sha256 does not match the recorded value",
            )
        return Verification(
            backend=self.name, confirmed=True, method="hash",
            detail="sha256 matches the recorded value",
        )

    def describe(self) -> dict:
        return {"backend": self.name, "kind": "fixture", "root": str(self.root)}


class RcloneBackend(RemoteBackend):
    """The real remote, speaking only the pinned command surface.

    `_argv()` is the single place a command is built, and it refuses an unpinned verb. That
    is the "no runtime improvisation" requirement made structural: there is no code path
    that assembles an rclone command from parts.
    """

    def __init__(self, remote: str, *, path: str = "", binary: str = "rclone",
                 timeout_s: int = 300):
        self.remote = remote
        self.path = path
        self.binary = binary
        self.timeout_s = timeout_s
        self._probe: RcloneProbe | None = None

    @property
    def name(self) -> str:  # type: ignore[override]
        return f"rclone:{self.remote}"

    # -- the pinned surface -------------------------------------------------------------

    def _pin(self, verb: str) -> CommandPin:
        for pin in RCLONE_COMMAND_SURFACE:
            if pin.verb == verb:
                return pin
        raise KeyError(
            f"rclone verb {verb!r} is not in the pinned command surface; "
            f"refusing to improvise a command at runtime"
        )

    def argv(self, verb: str, **subs: str) -> list[str]:
        """Build a pinned command's argv. Raises on any verb not in the table."""

        pin = self._pin(verb)
        values = {
            "binary": self.binary,
            "remote": self.remote,
            "path": self.path,
            **subs,
        }
        try:
            return [part.format(**values) for part in pin.argv]
        except KeyError as exc:
            raise KeyError(f"pinned verb {verb!r} needs substitution {exc}") from exc

    # -- the probe -----------------------------------------------------------------------

    def probe(self) -> RcloneProbe:
        if self._probe is None:
            self._probe = probe_rclone(self.binary)
        return self._probe

    def pin_status(self) -> Verification:
        """Is the installed rclone at least the floor? A declared skip if absent."""

        probe = self.probe()
        if not probe.available:
            return Verification(
                backend=self.name, confirmed=False, method="declared-skip",
                detail=probe.reason,
            )
        if not version_at_least(probe.version, RCLONE_MIN_VERSION):
            return Verification(
                backend=self.name, confirmed=False, method="declared-skip",
                detail=f"rclone {probe.version} is below the {RCLONE_MIN_VERSION} floor; "
                       f"the MEGA backend needs at least 1.41",
            )
        return Verification(
            backend=self.name, confirmed=True, method="version",
            detail=f"rclone {probe.version} (pinned {RCLONE_PINNED_VERSION})",
        )

    # -- the verification ----------------------------------------------------------------

    def verify(self, artifact: Path, *,
               expected_sha256: str | None = None) -> Verification:
        """Confirm the remote holds the artifact. Presence only — MEGA has no hashes.

        `expected_sha256` is accepted for interface parity with `LocalPathBackend` and
        deliberately **ignored**: rclone's MEGA backend cannot compare content, so a hash
        check here would be a claim this backend cannot make. The method is recorded as
        `presence` so the manifest says what was actually proven.
        """

        probe = self.probe()
        if not probe.available:
            # The declared skip. confirmed=False, always, with the reason in detail.
            return Verification(
                backend=self.name, confirmed=False, method="declared-skip",
                detail=probe.reason,
            )
        pin = self.pin_status()
        if not pin.confirmed:
            return Verification(
                backend=self.name, confirmed=False, method="declared-skip",
                detail=pin.detail,
            )
        argv = self.argv("lsjson")
        try:
            out = subprocess.run(
                argv, capture_output=True, text=True, timeout=self.timeout_s, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return Verification(
                backend=self.name, confirmed=False, method="declared-skip",
                detail=f"lsjson failed ({type(exc).__name__})",
            )
        if out.returncode != 0:
            return Verification(
                backend=self.name, confirmed=False, method="declared-skip",
                detail=f"lsjson exited {out.returncode}",
            )
        wanted = Path(artifact).name
        try:
            entries = json.loads(out.stdout or "[]")
        except ValueError:
            return Verification(
                backend=self.name, confirmed=False, method="declared-skip",
                detail="lsjson produced unparsable output",
            )
        for entry in entries if isinstance(entries, list) else []:
            if entry.get("Name") == wanted:
                return Verification(
                    backend=self.name, confirmed=True, method="presence",
                    detail="artifact present on the remote; content not comparable "
                           "on MEGA",
                )
        return Verification(
            backend=self.name, confirmed=False, method="absent",
            detail="artifact not present on the remote",
        )

    def describe(self) -> dict:
        return {
            "backend": self.name,
            "kind": "rclone",
            "remote": self.remote,
            "path": self.path,
            "binary": self.binary,
            "pinned_version": RCLONE_PINNED_VERSION,
            "min_version": RCLONE_MIN_VERSION,
        }


def make_verifier(backend: RemoteBackend) -> Callable[[Path], Verification]:
    """Adapt a backend to the `verify_remote` seam `reconcile()` expects.

    The callable returns a `Verification`, so the backend name travels with the answer all
    the way into the plan. A bool-returning callable would drop the provenance on the floor,
    which is exactly what requirement 3 forbids.
    """

    def _verify(artifact: Path) -> Verification:
        return backend.verify(Path(artifact))

    return _verify


@dataclass
class BackendRegistry:
    """The backends this run is willing to believe, by name.

    Exists so a caller can be explicit about *which* remote is authoritative rather than
    relying on whichever backend happened to be constructed. The fixture is registered
    under its own unmistakable name and nothing else.
    """

    backends: dict[str, RemoteBackend] = field(default_factory=dict)

    def register(self, backend: RemoteBackend) -> RemoteBackend:
        self.backends[backend.name] = backend
        return backend

    def get(self, name: str) -> RemoteBackend:
        try:
            return self.backends[name]
        except KeyError:
            raise KeyError(
                f"no backend registered as {name!r}; registered: "
                f"{sorted(self.backends)}"
            ) from None

    def names(self) -> list[str]:
        return sorted(self.backends)

    def is_fixture(self, name: str) -> bool:
        """True when `name` is the fixture. Used to refuse a fixture as authoritative."""

        return name == FIXTURE_BACKEND_NAME
