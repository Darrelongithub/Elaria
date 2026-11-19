"""Pins for F's ownership: `watcher.py` and the reader scripts' contracts.

`watcher.py` arrives with this cluster (OWNERSHIP-MAP: F OBSERVABILITY) but shipped
with no test of its own. The debounce rules from §3.7 are load-bearing — a
download that fires twenty events must settle to one, and a file still being
written must never be called settled — so they are pinned here rather than left
to the polling loop's good behaviour.
"""

from __future__ import annotations

import os
from pathlib import Path

from assistant.watcher import PollingWatcher, snapshot


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def touch(path: Path, size: int = 10, mtime: float | None = None) -> None:
    path.write_bytes(b"x" * size)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_snapshot_skips_dotfiles_and_temp_suffixes(tmp_path):
    touch(tmp_path / "keep.txt")
    touch(tmp_path / ".hidden.txt")
    touch(tmp_path / "download.part")
    (tmp_path / ".git").mkdir()
    touch(tmp_path / ".git" / "config")
    state = snapshot(tmp_path)
    assert list(state) == [str(tmp_path / "keep.txt")]


def test_a_burst_of_changes_settles_to_one_entry_after_the_debounce(tmp_path):
    clock = FakeClock()
    target = tmp_path / "a.txt"
    touch(target, mtime=clock.now - 3600)  # old enough to clear the recent guard
    watcher = PollingWatcher(tmp_path, debounce_s=30.0, now=clock)

    touch(target, size=20, mtime=clock.now - 3600)
    first = watcher.scan()
    assert first.modified == [str(target)]
    assert first.settled_changed == []      # seen, not yet settled

    clock.advance(31)
    settled = watcher.scan()
    assert settled.settled_changed == [str(target)]

    clock.advance(31)
    assert watcher.scan().settled_changed == []   # settles exactly once


def test_a_file_still_being_written_never_settles(tmp_path):
    """The download case: each new write resets the clock."""
    clock = FakeClock()
    target = tmp_path / "big.iso"
    touch(target, mtime=clock.now - 3600)
    watcher = PollingWatcher(tmp_path, debounce_s=10.0, now=clock)
    for size in (10, 20, 30, 40):
        clock.advance(6)                    # always inside the debounce window
        touch(target, size=size, mtime=clock.now - 3600)
        assert watcher.scan().settled_changed == []
    clock.advance(11)
    assert watcher.scan().settled_changed == [str(target)]


def test_the_recent_guard_holds_back_files_modified_just_now(tmp_path):
    clock = FakeClock()
    fresh = tmp_path / "fresh.txt"
    touch(fresh, mtime=clock.now)           # modified "now"
    watcher = PollingWatcher(tmp_path, debounce_s=1.0, recent_guard_minutes=15,
                             now=clock)
    clock.advance(2)
    assert watcher.scan().settled_changed == []
    clock.advance(16 * 60)
    assert watcher.scan().settled_changed == []


def test_created_and_deleted_are_both_reported(tmp_path):
    clock = FakeClock()
    watcher = PollingWatcher(tmp_path, debounce_s=0.0, now=clock)
    new = tmp_path / "new.txt"
    touch(new, mtime=clock.now - 3600)
    events = watcher.scan()
    assert events.created == [str(new)]
    assert events.any is True
    new.unlink()
    clock.advance(1)
    assert watcher.scan().deleted == [str(new)]


def test_a_pending_file_that_disappears_is_dropped_not_settled(tmp_path):
    clock = FakeClock()
    target = tmp_path / "gone.txt"
    touch(target, mtime=clock.now - 3600)
    watcher = PollingWatcher(tmp_path, debounce_s=5.0, now=clock)
    watcher.scan()
    target.unlink()
    clock.advance(10)
    events = watcher.scan()
    assert events.settled_changed == []
    assert events.deleted == [str(target)]
