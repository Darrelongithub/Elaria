"""Model-tier pins (J6/F19): a downloaded tier is pinned at first fetch.

The rule this enforces: **a model that can change under us is not a model we
can attribute a transcript to.** The first successful fetch of a tier records
its revision and hash; every later fetch is compared against that record, and
a difference is a REFUSAL (`PinMismatch`), not a silent upgrade — a changed
hash means the thing that transcribes the owner's speech is no longer the
thing we measured.

Pins live in `data_dir/model-pins.json`, mode 0600, written atomically. They
are small, human-readable and safe to delete deliberately (an operator who
deletes the file is asking for a re-pin, and the next fetch re-records).

Nothing here downloads anything: the caller fetches, then pins. That keeps the
mechanism honest in a container with no network and no model cache.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PINS_FILE = "model-pins.json"
REPO_ROOT = Path(__file__).resolve().parents[2]
_PIN_SPEC_RE = re.compile(
    r"^(?P<artifact_id>[^@\s]+)@(?P<revision>[0-9a-f]{7,64})#sha256:(?P<sha256>[0-9a-f]{64})$"
)


class PinMismatch(RuntimeError):
    """A tier that was pinned at one hash came back at another."""


@dataclass(frozen=True)
class VerifiedArtifact:
    """Local model artifact whose on-disk bytes passed SHA-256 verification."""

    role: str
    artifact_id: str
    revision: str
    sha256: str
    path: Path
    data: bytes


def pins_path(config) -> Path:
    data_dir = Path(getattr(config, "data_dir", Path(".")))
    return data_dir / PINS_FILE


def load_pins(config) -> dict:
    path = pins_path(config)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        # A corrupt pin file is not "no pins": it is unreadable evidence.
        # Callers treat `{"__corrupt__": ...}` as a hard stop rather than
        # re-pinning over the top of it.
        return {"__corrupt__": str(path)}


def _write_pins(config, pins: dict) -> Path:
    from .config import ensure_private_dir

    path = pins_path(config)
    ensure_private_dir(path.parent)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(pins, indent=2, sort_keys=True).encode())
    finally:
        os.close(fd)
    os.replace(tmp, path)
    return path


def record_fetch(config, tier: str, *, revision: str, sha256: str,
                 source: str = "", now: float | None = None) -> dict:
    """Pin a tier on its first fetch; verify it on every later one.

    Returns `{"pinned": True, "first_fetch": True|False, ...}`. Raises
    `PinMismatch` when the tier is already pinned at a different revision or
    hash — an upgrade must be an explicit re-pin (delete the entry), never an
    accident of a fetch path.
    """
    tier = str(tier).strip()
    if not tier:
        raise ValueError("a model pin needs a tier name")
    if not sha256 or len(sha256) < 16:
        raise ValueError("a model pin needs the content hash it was fetched at")
    pins = load_pins(config)
    if "__corrupt__" in pins:
        raise PinMismatch(
            f"model pin file is unreadable ({pins['__corrupt__']}) — refusing to "
            f"pin over evidence that cannot be read")
    existing = pins.get(tier)
    if existing is None:
        pins[tier] = {
            "revision": str(revision),
            "sha256": str(sha256),
            "source": str(source),
            "first_fetch_ts": time.strftime("%Y-%m-%dT%H:%M:%S%z",
                                            time.localtime(now or time.time())),
            "verified_fetches": 0,
        }
        _write_pins(config, pins)
        return {"pinned": True, "first_fetch": True, "tier": tier,
                "revision": pins[tier]["revision"], "sha256": pins[tier]["sha256"]}
    if existing.get("revision") != str(revision) or existing.get("sha256") != str(sha256):
        raise PinMismatch(
            f"model tier {tier!r} is pinned at revision {existing.get('revision')!r} "
            f"sha256={str(existing.get('sha256'))[:16]}… but this fetch is "
            f"revision {str(revision)!r} sha256={str(sha256)[:16]}… — refusing it")
    existing["verified_fetches"] = int(existing.get("verified_fetches", 0)) + 1
    pins[tier] = existing
    _write_pins(config, pins)
    return {"pinned": True, "first_fetch": False, "tier": tier,
            "revision": existing["revision"], "sha256": existing["sha256"]}


def verify_pin(config, tier: str, *, sha256: str) -> tuple[bool, str]:
    """Check a hash against the pin without touching the file."""
    pins = load_pins(config)
    if "__corrupt__" in pins:
        return False, f"pin file unreadable: {pins['__corrupt__']}"
    pinned = pins.get(str(tier))
    if pinned is None:
        return False, f"tier {tier!r} is not pinned yet"
    if pinned.get("sha256") != str(sha256):
        return False, (f"tier {tier!r} pinned at sha256={str(pinned.get('sha256'))[:16]}… "
                       f"but this is {str(sha256)[:16]}…")
    return True, f"tier {tier!r} matches pin revision {pinned.get('revision')!r}"


def pinned_summary(config) -> dict:
    """Doctor view: what is pinned, and what still is not."""
    pins = load_pins(config)
    if "__corrupt__" in pins:
        return {"available": False, "reason": pins["__corrupt__"], "tiers": {}}
    return {"available": True, "path": str(pins_path(config)),
            "tiers": {tier: {"revision": data.get("revision"),
                             "sha256": str(data.get("sha256"))[:16] + "…",
                             "first_fetch_ts": data.get("first_fetch_ts")}
                      for tier, data in pins.items()}}


def validate_pin(pins: Mapping[str, str], slot: str, model_id: str) -> str:
    """Return the approved ID unchanged; never normalize or fall back."""
    if slot not in pins or not isinstance(model_id, str) or pins[slot] != model_id:
        raise PinMismatch(f"Model {model_id!r} does not match the exact pin for {slot!r}")
    return model_id


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    """Hex SHA-256 of a regular file, failing closed on missing/unreadable paths."""
    target = Path(path)
    try:
        if not target.is_file():
            raise PinMismatch(f"pinned artifact missing or not a regular file: {target}")
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise PinMismatch(f"cannot read pinned artifact {target}: {exc}") from exc


def parse_pinned_role_spec(spec: str) -> dict[str, str]:
    """Parse `<artifact_id>@<revision>#sha256:<hex64>` from `PINNED_ROLES`."""
    if not isinstance(spec, str):
        raise PinMismatch(f"invalid pinned role spec: {spec!r}")
    match = _PIN_SPEC_RE.match(spec.strip())
    if match is None:
        raise PinMismatch(
            f"pinned role spec {spec!r} must have form "
            "'<artifact_id>@<revision>#sha256:<64-hex>'"
        )
    return match.groupdict()


def resolve_pinned_artifact(
    role: str = "speaker",
    *,
    path: str | os.PathLike | None = None,
    repo_root: str | os.PathLike | None = None,
    expected_sha256: str | None = None,
    config=None,
) -> VerifiedArtifact:
    """Resolve a pinned local artifact by role, read its bytes, and verify SHA-256.

    Fails closed (`PinMismatch`) whenever:
      - `role` is missing or malformed in `model_registry.PINNED_ROLES` /
        `PINNED_ARTIFACTS`,
      - `expected_sha256` disagrees with the registry pin,
      - `config`'s `model-pins.json` is corrupt or records a conflicting pin,
      - the file does not exist, is not a regular file, cannot be read, or its
        computed SHA-256 differs by even a single bit from the pinned digest.

    Returns a `VerifiedArtifact` carrying the immutable `data: bytes` whose
    SHA-256 was verified so callers load the model directly from verified
    memory with no TOCTOU gap.
    """
    from .model_registry import PINNED_ARTIFACTS, PINNED_ROLES

    role_key = str(role or "").strip()
    if role_key not in PINNED_ROLES or role_key not in PINNED_ARTIFACTS:
        raise PinMismatch(f"unknown pinned artifact role {role_key!r}")

    parsed = parse_pinned_role_spec(PINNED_ROLES[role_key])
    meta = PINNED_ARTIFACTS[role_key]
    pinned_sha = str(meta.get("sha256") or "")
    pinned_rev = str(meta.get("revision") or "")
    pinned_id = str(meta.get("artifact_id") or "")
    if (
        not hmac.compare_digest(parsed["sha256"], pinned_sha)
        or parsed["revision"] != pinned_rev
        or parsed["artifact_id"] != pinned_id
    ):
        raise PinMismatch(
            f"registry pin drift for role {role_key!r}: PINNED_ROLES and "
            "PINNED_ARTIFACTS disagree"
        )

    if expected_sha256 is not None:
        caller_sha = str(expected_sha256).strip().lower()
        if not hmac.compare_digest(caller_sha, pinned_sha):
            raise PinMismatch(
                f"expected sha256 {caller_sha!r} does not match registry pin "
                f"{pinned_sha!r} for role {role_key!r}"
            )

    if config is not None:
        pins = load_pins(config)
        if "__corrupt__" in pins:
            raise PinMismatch(
                f"model pin file is unreadable ({pins['__corrupt__']})"
            )
        recorded = pins.get(role_key)
        if recorded is not None:
            rec_sha = str(recorded.get("sha256") or "")
            rec_rev = str(recorded.get("revision") or "")
            if not hmac.compare_digest(rec_sha, pinned_sha) or rec_rev != pinned_rev:
                raise PinMismatch(
                    f"recorded pin for {role_key!r} conflicts with registry pin"
                )

    root = Path(repo_root) if repo_root is not None else REPO_ROOT
    if path is not None:
        raw_path = Path(path).expanduser()
        target = raw_path if raw_path.is_absolute() else (root / raw_path)
    else:
        relpath = str(meta.get("relpath") or "").strip()
        if not relpath:
            raise PinMismatch(f"no artifact path configured for role {role_key!r}")
        target = root / relpath

    try:
        if not target.is_file():
            raise PinMismatch(
                f"pinned {role_key} artifact missing or not a regular file: {target}"
            )
        data = target.read_bytes()
    except OSError as exc:
        raise PinMismatch(
            f"cannot read pinned {role_key} artifact {target}: {exc}"
        ) from exc

    actual_sha = sha256_bytes(data)
    if not hmac.compare_digest(actual_sha, pinned_sha):
        raise PinMismatch(
            f"pinned {role_key} artifact sha256 mismatch at {target}: "
            f"expected {pinned_sha}, got {actual_sha}"
        )

    expected_bytes = meta.get("size_bytes")
    if isinstance(expected_bytes, int) and len(data) != expected_bytes:
        raise PinMismatch(
            f"pinned {role_key} artifact size mismatch at {target}: "
            f"expected {expected_bytes} B, got {len(data)} B"
        )

    return VerifiedArtifact(
        role=role_key,
        artifact_id=pinned_id,
        revision=pinned_rev,
        sha256=actual_sha,
        path=target,
        data=data,
    )
