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

import json
import os
import time
from collections.abc import Mapping
from pathlib import Path

from .config import ensure_private_dir

PINS_FILE = "model-pins.json"


class PinMismatch(RuntimeError):
    """A tier that was pinned at one hash came back at another."""


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
