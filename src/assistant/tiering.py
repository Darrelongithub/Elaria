"""WP7 cold storage & backup — the tiering engine and the real trim mover (increment 3).

Two things live here, and they belong together because one triggers the other:

**The tiering engine** decides which artifacts leave HOT. The HOT window is
**14 days or 2 GB, whichever binds first** (FINAL-CENSUS 2026-10-31). At the measured
growth of 11–13 MiB/day the **age window binds** — 14 days of growth is ~0.15–0.18 GiB,
about 11x under the cap — so the 2 GB figure is a backstop, not the operative limit. Both
triggers are implemented anyway, and `TierDecision.binding` reports which one actually
fired, so a future census that changes the balance changes the report rather than the code.

**The trim mover** is the real implementation behind the seam increment 2 injected. It
moves an artifact into local trash with a **14-day grace**, and it never overwrites: two
artifacts with the same name land as two files, the way `executor.py`'s trash already
behaves. That never-overwrite property is what makes the trim idempotent in practice as
well as in the state machine — re-running a trim that already happened produces a new
trash entry, never a clobbered one.

**The grace clock lives in the manifest, not in the trash directory.** The `trashed`
record's timestamp is the single source of truth for when grace started, which is why
`TrashMover` has no clock of its own and why `plan_reconcile()` can decide a purge without
consulting the filesystem. One journal, one truth.

**PERMANENT EXCLUSIONS (census-ruled, forever):** voice-cache and test-assets are never
tiered and never trimmed. These are contracts, not tidiness — **0 ms recall** for the voice
cache, **offline-voice** for test-assets. They are expressed as non-removable defaults:
a config key may *add* exclusions, never remove these.

A third exclusion is structural rather than ruled: a WAV whose size equals its 44-byte
header carries **zero audio frames**. The census found one (`20261025-181730-4d90bf.wav`,
44 bytes) and ruled it a **never-retry mark that counts zero forever**. Tiering a file with
no audio in it would spend a remote object to store nothing, so it is excluded on that
basis.

PRIVACY FENCE: `TierDecision.summary()` is path-blind for the same reason the manifest's
and the reconcile plan's are. Counts, bytes and states may leave the laptop; names may not.

Evidence tags: [TESTED-ONLY] throughout — synthetic fixtures, a temp trash dir and an
injected clock. No restic, no rclone, no MEGA, and no real wav.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

__all__ = [
    "PERMANENT_EXCLUSIONS",
    "WAV_HEADER_BYTES",
    "Candidate",
    "TierDecision",
    "TrashMover",
    "classify",
    "is_excluded",
    "scan",
]

# A 16-bit PCM WAV's canonical header is 44 bytes. A file this size carries zero audio
# frames, which is what makes it a mark rather than a recording.
WAV_HEADER_BYTES = 44

# Census-ruled, forever. A config key may add to this list; it may not subtract from it.
PERMANENT_EXCLUSIONS: tuple[tuple[str, str], ...] = (
    ("voice-cache", "voice-cache — 0 ms recall contract"),
    ("test-assets", "test-assets — offline-voice contract"),
)

# Default HOT window (FINAL-CENSUS). Overridable per call so tests and the owner's config
# both drive it; these are the shipped values, not magic numbers scattered in the logic.
DEFAULT_WINDOW_DAYS = 14
DEFAULT_WINDOW_GB = 2


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def is_header_only_wav(path: Path) -> bool:
    """True when a WAV carries no audio frames — a mark, not a recording.

    Cheap by design: a stat and a 12-byte read, never a full parse. The tiering engine runs
    over every candidate, so this must not become the expensive part of a poll.
    """

    try:
        if path.stat().st_size > WAV_HEADER_BYTES:
            return False
        with path.open("rb") as handle:
            magic = handle.read(12)
    except OSError:
        return False
    return magic[:4] == b"RIFF" and magic[8:12] == b"WAVE"


def is_excluded(path: Path, *, data_dir: Path,
                extra: tuple[str, ...] = ()) -> str | None:
    """Why this artifact must never be tiered, or None if it is tierable.

    The permanent exclusions are checked first and cannot be overridden by `extra` — a
    config key adds exclusions, it never subtracts the census-ruled ones.
    """

    path = Path(path)
    for name, reason in PERMANENT_EXCLUSIONS:
        if _is_within(path, Path(data_dir) / name):
            return reason
    for name in extra:
        if name and _is_within(path, Path(data_dir) / name):
            return f"config exclusion [{name}]"
    if is_header_only_wav(path):
        return "never-retry mark — header-only WAV, counts zero forever"
    return None


@dataclass
class Candidate:
    """One artifact the tiering engine is looking at."""

    path: Path
    size: int
    mtime: datetime
    excluded_reason: str | None = None

    @property
    def excluded(self) -> bool:
        return self.excluded_reason is not None

    @classmethod
    def from_path(cls, path: Path, *, data_dir: Path,
                  extra: tuple[str, ...] = ()) -> Candidate:
        path = Path(path)
        stat = path.stat()
        # mtime is aware UTC: `now` is injected as aware, and subtracting a naive
        # local mtime from it raises on the very first candidate.
        return cls(path=path, size=stat.st_size,
                   mtime=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                   excluded_reason=is_excluded(path, data_dir=data_dir, extra=extra))


@dataclass
class TierDecision:
    """What the engine decided, and which limit actually bound."""

    keep_hot: list[Candidate] = field(default_factory=list)
    send_cold: list[Candidate] = field(default_factory=list)
    excluded: list[Candidate] = field(default_factory=list)
    binding: str = "none"          # "none" | "age" | "size"
    hot_bytes: int = 0
    hot_count: int = 0

    def summary(self) -> dict:
        """Path-blind aggregate. Counts, bytes and the binding limit — never names."""
        return {"keep_hot": len(self.keep_hot), "send_cold": len(self.send_cold),
                "excluded": len(self.excluded), "binding": self.binding,
                "hot_bytes": self.hot_bytes, "hot_count": self.hot_count}


def classify(candidates, *, now: datetime, window_days: int = DEFAULT_WINDOW_DAYS,
             window_gb: int = DEFAULT_WINDOW_GB) -> TierDecision:
    """Split candidates into HOT / COLD / excluded.

    Two triggers, evaluated in order of urgency:

    * **size** — the HOT set exceeds `window_gb`. The oldest artifacts go cold until the set
      is back under the cap. This is the urgent one: an over-cap HOT set is a problem now.
    * **age** — an artifact is older than `window_days`. Everything past the window goes.

    If neither fires, `binding` is "none" and nothing moves. `binding` reports which limit
    actually bound, so the operator can see the 2 GB backstop is not the live constraint
    without having to trust a comment.
    """

    decision = TierDecision()
    tierable: list[Candidate] = []
    for candidate in candidates:
        if candidate.excluded:
            decision.excluded.append(candidate)
        else:
            tierable.append(candidate)

    decision.hot_count = len(tierable)
    decision.hot_bytes = sum(c.size for c in tierable)
    window_bytes = window_gb * 1000 ** 3

    over_cap = decision.hot_bytes > window_bytes
    aged = [c for c in tierable if (now - c.mtime) >= timedelta(days=window_days)]

    if over_cap:
        decision.binding = "size"
        # oldest first, until back under the cap
        remaining = sorted(tierable, key=lambda c: c.mtime)
        budget = decision.hot_bytes
        for candidate in remaining:
            if budget <= window_bytes:
                break
            decision.send_cold.append(candidate)
            budget -= candidate.size
    elif aged:
        decision.binding = "age"
        decision.send_cold.extend(sorted(aged, key=lambda c: c.mtime))

    sent = {id(c) for c in decision.send_cold}
    decision.keep_hot = [c for c in tierable if id(c) not in sent]
    decision.hot_bytes = sum(c.size for c in decision.keep_hot)
    decision.hot_count = len(decision.keep_hot)
    return decision


def scan(root: Path, *, now: datetime, data_dir: Path,
         extra: tuple[str, ...] = (),
         window_days: int = DEFAULT_WINDOW_DAYS,
         window_gb: int = DEFAULT_WINDOW_GB) -> TierDecision:
    """Walk a directory and classify everything in it.

    This is the **belt**: the directory poll is truth, and the journal corroborates. A
    missing or unreadable entry degrades to "not a candidate" rather than raising — a poll
    that crashes on one odd file is a poll that stops protecting anything.
    """

    root = Path(root)
    candidates: list[Candidate] = []
    if not root.exists():
        return TierDecision()
    for path in sorted(root.rglob("*")):
        try:
            if not path.is_file() or path.is_symlink():
                continue
            candidates.append(Candidate.from_path(path, data_dir=data_dir,
                                                  extra=extra))
        except OSError:
            continue
    return classify(candidates, now=now, window_days=window_days,
                    window_gb=window_gb)


class TrashMover:
    """The real trim mover: HOT -> local trash, never overwriting.

    Passed to `reconcile()` as its `trim_mover`. `move()` returns the trash location so the
    caller can record it; `purge()` removes an artifact whose grace has elapsed.

    The grace clock is NOT here — it lives in the manifest's `trashed` record. This class
    moves and deletes files; it decides nothing.
    """

    def __init__(self, trash_dir: Path):
        self.trash_dir = Path(trash_dir)

    def move(self, path: Path) -> Path:
        """Move `path` into trash, never overwriting an existing entry.

        The stamp is second-resolution, so two same-name files in one second would collide;
        the counter resolves that the same way `executor.py`'s trash does, because a failed
        move while the manifest claims success is worse than a slightly ugly name.
        """

        path = Path(path)
        self.trash_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.trash_dir, 0o700)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self.trash_dir / f"{stamp}-{path.name}"
        counter = 2
        while os.path.lexists(dest):
            dest = self.trash_dir / f"{stamp}-{path.stem} ({counter}){path.suffix}"
            counter += 1
        shutil.move(str(path), str(dest))
        return dest

    def purge(self, trash_path: Path) -> bool:
        """Remove a trashed artifact whose grace has elapsed. True if it was there."""

        trash_path = Path(trash_path)
        try:
            if trash_path.is_dir() and not trash_path.is_symlink():
                shutil.rmtree(trash_path)
            else:
                trash_path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError:
            # A purge that cannot complete is reported, never swallowed: the artifact
            # still has its remote copy, so failing here is not data loss, but it must
            # not look like success either.
            raise
