"""P · HANDS-HEADLESS — instance resolution + fail-closed version gate.

Build step 1 of P-HEADLESS.md: resolve and sha-pin ``/usr/bin/kitty`` +
python3, run ``kitty --version``, and raise BEFORE creating any directory when
the exact-string version gate fails.

The gate is fail-closed and exact-string: a mismatch stops the instance before
mkdir. The pinned version string is consumed from Q's re-pin (kitty 0.49.2);
P consumes the pin and never re-pins it (coordination ask 50 lives in the
report envelope, not in this code).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KITTY_PATH = "/usr/bin/kitty"
DEFAULT_PYTHON_PATH = "/usr/bin/python3"

# Q's re-pin (0.49.2). ``kitty --version`` prints e.g.
# "kitty 0.49.2 created by Kovid Goyal"; the gate matches this exact prefix,
# trailing space included. Do not loosen this gate.
DEFAULT_VERSION_PIN = "kitty 0.49.2 "

_VERSION_PROBE_TIMEOUT_S = 30
_READ_CHUNK = 65536


class InstanceError(RuntimeError):
    """Base class for instance failures; messages are deliberately legible."""


class VersionGateError(InstanceError):
    """The kitty version gate failed; raised BEFORE any directory is created."""


class PinMismatchError(InstanceError):
    """A binary's sha256 does not match the pin supplied for it."""


class PinNotConfiguredError(InstanceError):
    """A required sha256 pin was not supplied; the instance fails closed."""


def sha256_of(path: str | Path) -> str:
    """Return the hex sha256 of the file at ``path``."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_binary(path: str | Path) -> Path:
    """Resolve ``path`` to an executable regular file or raise legibly."""
    resolved = Path(path)
    if not resolved.exists():
        raise InstanceError(
            f"binary not found at {resolved}: the resolve step found no file at the configured path"
        )
    if not resolved.is_file():
        raise InstanceError(f"{resolved} is not a regular file; refusing to pin a non-file path")
    if not os.access(resolved, os.X_OK):
        raise InstanceError(f"{resolved} is not executable; refusing to pin a non-executable path")
    return resolved


@dataclass(frozen=True)
class InstanceCheck:
    """Result of a successful instance check (gate passed, nothing created)."""

    kitty_path: str
    python_path: str
    kitty_sha256: str
    python_sha256: str
    version_output: str
    version_pin: str


class KittyInstance:
    """Resolve, sha-pin and version-gate the kitty host binaries.

    ``check()`` never creates directories. Only ``prepare()`` — callable after
    a passed check — creates the runtime directory tree, so a gate failure
    provably happens before any mkdir.
    """

    def __init__(
        self,
        kitty_path: str = DEFAULT_KITTY_PATH,
        python_path: str = DEFAULT_PYTHON_PATH,
        kitty_sha256: str | None = None,
        python_sha256: str | None = None,
        version_pin: str = DEFAULT_VERSION_PIN,
    ) -> None:
        self.kitty_path = kitty_path
        self.python_path = python_path
        self.kitty_sha256 = kitty_sha256
        self.python_sha256 = python_sha256
        self.version_pin = version_pin

    def check(self) -> InstanceCheck:
        """Resolve, pin and gate. Raises before any directory is created."""
        if not self.version_pin:
            raise InstanceError("version pin is empty; refusing to run an open gate")
        if not self.kitty_sha256:
            raise PinNotConfiguredError(
                "kitten sha256 pin not configured; the instance fails CLOSED "
                "until Q's inventory pin is wired in via config (HR-P-1)"
            )
        if not self.python_sha256:
            raise PinNotConfiguredError(
                "python3 sha256 pin not configured; the instance fails CLOSED "
                "until the interpreter pin is wired in via config (HR-P-1)"
            )

        kitty = _require_binary(self.kitty_path)
        python = _require_binary(self.python_path)

        kitty_actual = sha256_of(kitty)
        if kitty_actual != self.kitty_sha256:
            raise PinMismatchError(
                f"kitten sha256 mismatch at {kitty}: expected pin "
                f"{self.kitty_sha256}, got {kitty_actual}"
            )
        python_actual = sha256_of(python)
        if python_actual != self.python_sha256:
            raise PinMismatchError(
                f"python3 sha256 mismatch at {python}: expected pin "
                f"{self.python_sha256}, got {python_actual}"
            )

        version_output = self._run_version_probe(kitty)
        if not version_output.startswith(self.version_pin):
            raise VersionGateError(
                "kitty version gate failed: expected exact prefix "
                f"{self.version_pin!r}, got {version_output.strip()!r}; the "
                "instance fails CLOSED before any directory is created"
            )

        return InstanceCheck(
            kitty_path=str(kitty),
            python_path=str(python),
            kitty_sha256=kitty_actual,
            python_sha256=python_actual,
            version_output=version_output,
            version_pin=self.version_pin,
        )

    def prepare(self, runtime_dir: str | Path) -> Path:
        """Create the runtime directory tree. Call ONLY after check() passes."""
        base = Path(runtime_dir)
        base.mkdir(parents=True, exist_ok=True)
        (base / "logs").mkdir(parents=True, exist_ok=True)
        return base

    def _run_version_probe(self, kitty: Path) -> str:
        try:
            proc = subprocess.run(
                [str(kitty), "--version"],
                check=False,
                capture_output=True,
                text=True,
                timeout=_VERSION_PROBE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired as exc:
            raise InstanceError(
                f"`kitty --version` at {kitty} timed out after "
                f"{_VERSION_PROBE_TIMEOUT_S}s; failing closed before mkdir"
            ) from exc
        except OSError as exc:
            raise InstanceError(f"could not execute `kitty --version` at {kitty}: {exc}") from exc
        if proc.returncode != 0:
            raise InstanceError(
                f"`kitty --version` at {kitty} exited {proc.returncode}; "
                f"stderr: {proc.stderr.strip()!r}; failing closed before mkdir"
            )
        return proc.stdout
