"""Watcher (§3.7) — notice new/changed files, debounce the bursts.

Blueprint names inotify via watchdog; this implementation is a polling
snapshot diff so Phase 3 stays stdlib-only and fully testable headless.
The interface (scan → debounced changed-paths) is what callers depend
on — an inotify backend can replace the innards on the Fedora box
without touching the organiser.

Rules from §3.7: files arrive in bursts (a download fires many events),
so changes settle for a debounce window; temp/partial extensions are
ignored; files modified in the last N minutes wait (they may still be
being written — the same 15-minute guard spirit as §4.1).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .indexer import TEMP_SUFFIXES


@dataclass
class WatcherEvents:
    created: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    settled_changed: list[str] = field(default_factory=list)  # debounce-survived

    @property
    def any(self) -> bool:
        return bool(self.created or self.modified or self.deleted)


def snapshot(root: Path) -> dict[str, tuple[int, float]]:
    """{path: (size, mtime)} for everything indexable-looking below root."""
    state: dict[str, tuple[int, float]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") or name.endswith(TEMP_SUFFIXES):
                continue
            path = Path(dirpath) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            state[str(path)] = (stat.st_size, stat.st_mtime)
    return state


class PollingWatcher:
    """Diff snapshots; a path is 'settled' only after it appears changed
    and then stays untouched for `debounce_s` (downloads still writing
    keep resetting their clock — exactly like a browser download should).
    """

    def __init__(self, root: Path, *, debounce_s: float = 30.0,
                 recent_guard_minutes: int = 0, now=time.time):
        self.root = Path(root)
        self.debounce_s = debounce_s
        self.recent_guard_s = recent_guard_minutes * 60
        self._now = now
        self._previous = snapshot(self.root)
        self._pending: dict[str, float] = {}  # path -> first-changed-at

    def scan(self) -> WatcherEvents:
        current = snapshot(self.root)
        created = sorted(set(current) - set(self._previous))
        deleted = sorted(set(self._previous) - set(current))
        modified = sorted(p for p in set(current) & set(self._previous)
                          if current[p] != self._previous[p])
        now = self._now()
        for path in created + modified:
            mtime = current[path][1]
            if now - mtime >= self.recent_guard_s:
                self._pending[path] = now
        settled = []
        for path, first_seen in list(self._pending.items()):
            if path not in current:
                del self._pending[path]
            elif now - first_seen >= self.debounce_s and path not in modified:
                settled.append(path)
                del self._pending[path]
        self._previous = current
        return WatcherEvents(created=created, modified=modified,
                             deleted=deleted, settled_changed=sorted(settled))
