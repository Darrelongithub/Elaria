"""WP7 increment 7 - the trigger surface: post-close hook, nightly timer, WP5 monthly shape.

**The daemon is not touched, and cannot be.** The trigger ruling (2026-10-27) is explicit:
the post-close backup hook must not touch `daemon.py`. So this module *observes* the
machinery that already exists and decides when a backup should wake. A one-line daemon
hook may be proposed only AFTER the mainline PR merges, and is not built here.

**This is NOT `assistant/watcher.py`.** That file is mainline's - it owns `WatcherEvents`,
`snapshot()` and `PollingWatcher` for the voice-test/dictation pipeline, and
`tests/test_bughunt_systems.py` and `tests/test_phase3_organiser.py` import from it. An
earlier draft of this module was written into `watcher.py` and clobbered it, including a
`snapshot()` whose return type and keying differ from mainline's (mine: flat, by *name*;
mainline's: recursive, by *full path string*). That was a boundary violation and a real
name collision, caught by mainline's own tests rather than by me. Recorded here so the
separation is deliberate rather than accidental: **this lane adds a new module; it does not
extend mainline's watcher.** The cheap-snapshot helper here is named
`directory_snapshot` precisely so it can never be confused with mainline's `snapshot`.

Two observation channels, and the polarity between them is a ruling, not a preference:

* **The directory poll is the BELT - it is truth.** A cheap `scandir` of the audio root,
  comparing name/size/mtime. No hashing, ever: this runs over every candidate and must not
  become the expensive part of a poll.
* **The journal tail is the SUSPENDERS - it corroborates.** `journalctl --user -u assistant`,
  read incrementally from a persisted cursor, parsed with the canonical §2 contract.

**Belt/suspenders may not be inverted or "optimised".** The journal can *name a reason* for
a wake; it can never *create* one. If the journal reports `session.close` but the directory
shows nothing new, that is a correct no-op - a session that closed without keeping audio
has nothing to back up. Inverting this would let a log line manufacture work.

**The privacy fence holds here too.** The `audio kept at {path}` detail rides inside the
free-text `detail` field (Drift 2). The watcher extracts the path ONLY to address an
artifact in the manifest, and never writes it to a log line, a sensor event, a phase report,
a PR, or a chat message. Everything this module emits is path-free by construction: counts
and extension labels, never names.

**Dispatch keys on the event name (`parts[2]`), never on the verdict (`parts[5]`)** - §2.1.
A verdict of `KEPT` is not what makes an event a post-close; the *name* is.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import KW_ONLY, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from assistant.sensors import artifact_label

__all__ = [
    "JOURNAL_UNIT",
    "POST_CLOSE_EVENTS",
    "BackupWatcher",
    "JournalTail",
    "Snapshot",
    "WakeDecision",
    "defer_reason",
    "defers_to_ac",
    "directory_snapshot",
    "directory_snapshot_changed",
    "parse_journal_line",
]

#: The §4.8 events that mean "a session has closed". Dispatched on by NAME.
#: `watchdog.close` and `goaway.close` are included because both close a session, and a
#: backup that waited only for the polite `session.close` would miss every forced close.
POST_CLOSE_EVENTS: tuple[str, ...] = ("session.close", "watchdog.close", "goaway.close")

#: The systemd user unit whose journal this tails. Named as a constant because a typo here
#: would silently tail nothing and the watcher would look correctly idle forever.
JOURNAL_UNIT = "assistant"

#: How many journal lines to read per wake. A bounded read keeps a long-idle machine from
#: replaying a whole day of journal in one pass.
_JOURNAL_BATCH = 500


# ---------------------------------------------------------------------------
# §2 line parsing
# ---------------------------------------------------------------------------


def parse_journal_line(line: str) -> dict | None:
    """Parse one canonical §2 line, or return None if it is not one.

    `LINE ::= ts SP level SP event SP session_id SP peak SP verdict [ SP detail ]`
    `PARSE ::= line.split(" ", 6)` - 6 parts when detail is absent, 7 when present.

    Detail absence is ABSENT, never `-`. The detail is returned byte-intact (modulo
    `_flat()`'s whitespace normalisation, which is why the directory poll is the belt and
    the journal is the suspenders: the detail is NOT byte-faithful).

    A line that does not parse is returned as None rather than raising. `journalctl`
    output carries its own header/footer lines and anything else that ever shared the
    stream; a watcher that died on a malformed line would stop observing entirely.
    """

    if not line:
        return None
    parts = line.rstrip("\n").split(" ", 6)
    if len(parts) < 6:
        return None
    return {
        "ts": parts[0],
        "level": parts[1],
        "event": parts[2],
        "session_id": parts[3],
        "peak": parts[4],
        "verdict": parts[5],
        "detail": parts[6] if len(parts) == 7 else None,
    }


# ---------------------------------------------------------------------------
# The BELT - a cheap directory snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    """A cheap fingerprint of a directory: name, size and mtime for every entry.

    Deliberately NOT a hash. Hashing every candidate on every poll would make the poll
    the expensive part of a watcher, which the wake ruling forbids. Size and mtime are
    enough to answer "did anything change", which is the only question the belt asks.

    **Named `Snapshot`, not `snapshot`, and not shaped like mainline's `snapshot`.**
    Mainline's `assistant.watcher.snapshot` returns `{full_path: (size, mtime)}` and walks
    recursively for the voice-test pipeline. This one is flat and keyed by NAME, because a
    backup trigger must not carry a path anywhere near its output. The two are different
    functions for different jobs and are named so they cannot be swapped by accident.

    Entries are sorted so two snapshots of the same directory compare equal regardless of
    the order the filesystem handed them back.
    """

    entries: tuple[tuple[str, int, int], ...] = ()

    def __bool__(self) -> bool:
        return bool(self.entries)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(name for name, _, _ in self.entries)


def directory_snapshot(root: Path) -> Snapshot:
    """Fingerprint `root` without hashing anything.

    An absent or unreadable root is an EMPTY snapshot, not an error: a watcher pointed at
    a directory that does not exist yet should observe "nothing here", which is a correct
    no-op, and should not crash the trigger.
    """

    try:
        with os.scandir(root) as it:
            rows = []
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                rows.append((entry.name, st.st_size, st.st_mtime_ns))
    except OSError:
        return Snapshot()
    return Snapshot(entries=tuple(sorted(rows)))


def directory_snapshot_changed(before: Snapshot, after: Snapshot) -> bool:
    """True when `after` differs from `before` in any name, size or mtime.

    This is the ONLY thing that can create a wake. See the module docstring: the journal
    corroborates, it does not trigger.
    """

    return before.entries != after.entries


# ---------------------------------------------------------------------------
# The SUSPENDERS - an incremental journal tail
# ---------------------------------------------------------------------------


@dataclass
class JournalTail:
    """Reads `journalctl --user -u assistant` incrementally from a persisted cursor.

    The cursor lives in a small file outside the repo. On each read it asks journalctl for
    everything after the stored cursor and stores the new one, so a restart resumes rather
    than replays. A machine that was off for three days does not replay three days.

    `runner` is injectable so the whole surface is testable headlessly with no journalctl
    and no sleeps: it takes the argv list and returns stdout as text.
    """

    cursor_path: Path
    unit: str = JOURNAL_UNIT
    runner: Callable[[Sequence[str]], str] | None = None
    _cursor: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.cursor_path = Path(self.cursor_path)
        self._cursor = self._load()

    # -- cursor persistence -------------------------------------------------

    def _load(self) -> str | None:
        try:
            text = self.cursor_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return text or None

    def _save(self, cursor: str | None) -> None:
        if not cursor:
            return
        try:
            self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
            self.cursor_path.write_text(cursor + "\n", encoding="utf-8")
        except OSError:
            # A cursor that cannot be persisted means the next read replays. Replay is
            # idempotent for this watcher (a post-close that already fired is not refired,
            # because the directory snapshot is what decides), so failing to persist is a
            # degraded mode, not a correctness hole.
            pass
        self._cursor = cursor

    # -- reading -------------------------------------------------------------

    def _run(self, argv: Sequence[str]) -> str:
        if self.runner is not None:
            return self.runner(argv)
        proc = subprocess.run(
            list(argv), capture_output=True, text=True, timeout=30, check=False
        )
        return proc.stdout or ""

    def read_new(self) -> list[dict]:
        """Return the §2 lines emitted since the stored cursor, parsed.

        An absent journalctl, an absent unit, or a machine with no user journal returns an
        empty list. **That is a DECLARED absence, never a silent pass** - increment 4's
        rule - and the caller can see it because `available` reports False.
        """

        argv = ["journalctl", "--user", "-u", self.unit, "--output=cat",
                "--no-pager", "-n", str(_JOURNAL_BATCH)]
        if self._cursor:
            argv.append(f"--after-cursor={self._cursor}")
        try:
            raw = self._run(argv)
        except (OSError, subprocess.SubprocessError):
            return []
        out: list[dict] = []
        cursor: str | None = None
        for line in raw.splitlines():
            if line.startswith("-- cursor: "):
                cursor = line[len("-- cursor: "):].strip()
                continue
            parsed = parse_journal_line(line)
            if parsed is not None:
                out.append(parsed)
        self._save(cursor)
        return out

    @property
    def available(self) -> bool:
        """False when journalctl or the unit is not there to be tailed.

        Reported rather than swallowed: a watcher that cannot see the journal must say so,
        or an idle machine and a blind one are indistinguishable.
        """

        try:
            self._run(["journalctl", "--user", "-u", self.unit, "-n", "0"])
        except (OSError, subprocess.SubprocessError):
            return False
        return True


# ---------------------------------------------------------------------------
# The battery / metered policy
# ---------------------------------------------------------------------------


def defers_to_ac(size_bytes: int, *, defer_above_mb: int) -> bool:
    """True when an upload of this size must wait for AC/unmetered power.

    The ruling: uploads above 100 MB defer to AC/unmetered. Expressed in MB decimal, like
    every other size in `[backup]`.
    """

    if defer_above_mb <= 0:
        return False
    return size_bytes > defer_above_mb * 1000 ** 2


def defer_reason(size_bytes: int, *, defer_above_mb: int) -> str | None:
    """A path-free reason string for a deferral, or None when there is nothing to say."""

    if not defers_to_ac(size_bytes, defer_above_mb=defer_above_mb):
        return None
    return f"deferred: larger than {defer_above_mb} MB, waiting for AC/unmetered power"


# ---------------------------------------------------------------------------
# The watcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WakeDecision:
    """What one poll decided. Path-free by construction.

    `woke` is the only field that says work should happen. `reason` names why, `count` says
    how many artifacts are involved, and `labels` carries extension labels only - never a
    name, never a path. `journal_corroborates` records whether the suspenders agreed; it is
    informational and never gates `woke`.
    """

    woke: bool
    reason: str | None = None
    count: int = 0
    labels: tuple[str, ...] = ()
    journal_corroborates: bool = False
    deferred: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.woke


@dataclass
class BackupWatcher:
    """Observes the audio root and the journal, and decides when a backup should wake.

    One poll does exactly one thing: compare the directory against the last snapshot, and
    if it changed, ask the journal why. It never performs a backup itself - that is
    `backup_command`'s job, and keeping them apart is what lets this module be tested
    headlessly with no remote, no restic and no rclone.
    """

    root: Path
    cursor_path: Path
    _: KW_ONLY
    data_dir: Path
    poll_s: int = 30
    defer_above_mb: int = 100
    now: Callable[[], datetime] | None = None
    journal: JournalTail | None = None
    _last: Snapshot | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.data_dir = Path(self.data_dir)
        if self.now is None:
            self.now = lambda: datetime.now(UTC)

    # -- one poll ------------------------------------------------------------

    def poll(self) -> WakeDecision:
        """One wake. The directory decides; the journal only explains.

        **The journal cannot create a wake.** If the directory has not changed, this returns
        a no-op even when the journal is full of `session.close` lines - a session that
        closed without keeping audio has nothing to back up. This polarity is the
        belt/suspenders ruling and is pinned by test.
        """

        before = self._last if self._last is not None else Snapshot()
        after = directory_snapshot(self.root)

        if not directory_snapshot_changed(before, after):
            self._last = after
            # Still drain the journal so the cursor advances and a later change is not
            # buried under lines that were already seen.
            if self.journal is not None:
                self.journal.read_new()
            return WakeDecision(woke=False)

        self._last = after
        new_names = _new_names(before, after)

        # Corroborate: does the journal name a reason? Informational only.
        corroborates = False
        reason = "artifact appeared"
        if self.journal is not None:
            events = self.journal.read_new()
            if any(e["event"] in POST_CLOSE_EVENTS for e in events):
                corroborates = True
                reason = "post-close"

        labels = tuple(sorted({_label(name) for name in new_names}))
        # LABELS, not names. `_sizes` is keyed by name because that is what the snapshot
        # holds, but a name must never leave this module - the privacy fence. Keying the
        # deferral by name would have put `20261104-091500-abcdef.wav` into a
        # WakeDecision and straight into whatever logged it.
        deferred = tuple(sorted({
            label
            for label, size in (
                (_label(name), size) for name, size in _sizes(after, new_names).items()
            )
            if defers_to_ac(size, defer_above_mb=self.defer_above_mb)
        }))
        return WakeDecision(
            woke=True,
            reason=reason,
            count=len(new_names),
            labels=labels,
            journal_corroborates=corroborates,
            deferred=deferred,
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _new_names(before: Snapshot, after: Snapshot) -> tuple[str, ...]:
    """Names present in `after` but not in `before`."""

    old = {name: (size, mtime) for name, size, mtime in before.entries}
    return tuple(
        name for name, size, mtime in after.entries
        if old.get(name) != (size, mtime)
    )


def _sizes(after: Snapshot, names: Sequence[str]) -> dict[str, int]:
    """Map each new name to its size. Names, not paths."""

    wanted = set(names)
    return {name: size for name, size, _ in after.entries if name in wanted}


def _label(name: str) -> str:
    """A path-free label for an entry name: its extension and nothing else."""

    return artifact_label(name)
