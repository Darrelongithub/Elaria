"""Commitment mirror — the only owner data the alive host may hold.

Written by the laptop (``assistant/alive_sync.py``), read here. Full
snapshot every time (no deltas), so a missed file can never desynchronise
anything. Verification on every read: name hash == bytes, mac valid,
envelope version known. A mirror that fails verification is treated as
ABSENT — the layer reminds about nothing rather than trusting forged data.

Staleness (B11): a snapshot older than ``stale_mirror_days`` stops firing;
the owner is told once, honestly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from . import envelope as envelope_mod
from .sync import SyncError


@dataclass
class MirrorItem:
    id: int
    topic: str
    due: str | None
    remind_at: list[str]
    origin: str
    knock_id: int | None
    content_free: bool


@dataclass
class Mirror:
    generated_at: datetime | None
    laptop_seq: int | None
    items: list[MirrorItem]
    source_file: str | None
    verified: bool
    error: str | None
    age_days: float | None


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def load_mirror(backend, commitments_prefix: str, mac_key: str, *,
                now: datetime | None = None) -> Mirror:
    """Read and verify the newest commitments snapshot."""
    now = now or datetime.now(UTC)
    try:
        names = backend.list(commitments_prefix)
    except SyncError as exc:
        return Mirror(None, None, [], None, False, f"remote unreachable: {exc}", None)

    candidates = []
    for name in names:
        if name == "LATEST":
            continue
        parsed = envelope_mod.parse_name(name)
        if parsed:
            candidates.append((parsed["ts"], name))
    if not candidates:
        return Mirror(None, None, [], None, False, "no snapshot in commitments/", None)
    candidates.sort()
    _, newest = candidates[-1]

    try:
        data = backend.get(commitments_prefix, newest)
    except SyncError as exc:
        return Mirror(None, None, [], newest, False, f"remote unreachable: {exc}", None)

    envelope, error = envelope_mod.load_verified(newest, data, mac_key)
    if envelope is None:
        return Mirror(None, None, [], newest, False, error, None)

    generated = _parse_ts(envelope.get("generated_at"))
    age_days = ((now - generated).total_seconds() / 86400) if generated else None
    items: list[MirrorItem] = []
    for raw in envelope.get("items", []):
        try:
            items.append(MirrorItem(
                id=int(raw["id"]),
                topic=str(raw.get("topic", ""))[:300],
                due=raw.get("due"),
                remind_at=[str(x) for x in raw.get("remind_at", [])][:10],
                origin=str(raw.get("origin", "")),
                knock_id=int(raw["knock_id"]) if raw.get("knock_id") is not None else None,
                content_free=bool(raw.get("content_free", False)),
            ))
        except (KeyError, TypeError, ValueError):
            continue  # a malformed item is skipped, never trusted
    return Mirror(generated, envelope.get("laptop_seq"), items, newest, True, None, age_days)


def is_stale(mirror: Mirror, stale_days: int, *, now: datetime | None = None) -> bool:
    return mirror.age_days is not None and mirror.age_days > stale_days


def busy_days(mirror: Mirror, *, weeks_ahead: int = 2,
              now: datetime | None = None) -> dict[int, int]:
    """Map weekday index (Mon=0) → number of mirrored commitments due that
    weekday within the horizon. Interval/day-count only — topics are never
    used, and never leave this function."""
    now = now or datetime.now(UTC)
    horizon = now + timedelta(days=7 * weeks_ahead)
    counts: dict[int, int] = {}
    for item in mirror.items:
        due = _parse_ts(item.due)
        if due is None or due > horizon:
            continue
        counts[due.weekday()] = counts.get(due.weekday(), 0) + 1
    return counts


def _load_kind(backend, commitments_prefix: str, mac_key: str, kind: str) -> dict | None:
    """Newest verified envelope of a given kind in the laptop prefix, or None."""
    best: dict | None = None
    best_name = ""
    for name in backend.list(commitments_prefix):
        parsed = envelope_mod.parse_name(name)
        if not parsed:
            continue
        try:
            data = backend.get(commitments_prefix, name)
        except SyncError:
            continue
        envelope, _error = envelope_mod.load_verified(name, data, mac_key)
        if envelope is None or envelope.get("kind") != kind:
            continue
        if name > best_name:
            best, best_name = envelope, name
    return best


def load_public_card(backend, commitments_prefix: str, mac_key: str) -> dict | None:
    """Read the laptop-exported public card, if any. Absent/invalid = nothing
    disclosed (L0)."""
    return _load_kind(backend, commitments_prefix, mac_key, "public_card")


def load_t1_hashes(backend, commitments_prefix: str, mac_key: str) -> set[str]:
    """Read the laptop-exported T1 approved-contact allowlist as salted
    hashes. Raw numbers never enter the sync folder."""
    envelope = _load_kind(backend, commitments_prefix, mac_key, "t1_allowlist")
    if not envelope:
        return set()
    hashes = envelope.get("hashes")
    if not isinstance(hashes, list):
        return set()
    return {str(x) for x in hashes[:50]}
    return None
