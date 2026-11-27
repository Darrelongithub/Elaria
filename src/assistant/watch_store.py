"""WATCH RAM store — multi-window live tree, never serialised (design §5.1).

Daemon-side, pure, testable without a bus. Holds Window/Node records in
memory only: no file I/O, no pickle, no JSON-to-disk, no database. A halt
clears it in milliseconds (BUILD-4 calls clear()).

Caps (proposals, measured in §10): ≤128 windows, ≤256 nodes per window,
≤20 000 nodes total, names ≤64 chars (enforced at ingest, §6).

Seq-gap → stale: deltas carry a per-window seq. A gap marks the window
stale (frozen until resync); duplicates/out-of-order are ignored. Age-based
staleness (2.0 s at draw time, §5.2) is enforced by the caller in BUILD-5;
this store only tracks synced_at so the caller can measure age.

Zero cloud API budget: no provider calls, ever. Imports only stdlib,
watch_ingest (record types) and journal_log (metadata lines).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import journal_log
from .watch_ingest import Node, Tombstone

MAX_WINDOWS = 128
MAX_NODES_PER_WINDOW = 256
MAX_TOTAL_NODES = 20_000

Rect = tuple[float, float, float, float]


@dataclass
class Window:
    """One tracked window. state: live | stale (dark = absent/cleared)."""

    key: str
    pid: int
    app: str
    title: str
    rect: Rect
    output: str
    workspace: int
    visible: bool
    focus_rank: int
    seq: int = 0
    synced_at: float = 0.0
    state: str = "live"


@dataclass
class _WindowBucket:
    window: Window
    nodes: list[Node | Tombstone] = field(default_factory=list)


class WatchStore:
    """RAM-only multi-window tree. Thread-safe via caller serialisation.

    The daemon owns the single writer (supervisor); readers (ask path) call
    view()/nodes_for_window() under the daemon's lock. No internal locking
    keeps the store pure and deterministic for tests.
    """

    def __init__(self, *, now=time.monotonic):
        self._now = now
        self._buckets: dict[str, _WindowBucket] = {}
        self._total_nodes = 0

    # -- window lifecycle -------------------------------------------------
    def upsert_window(self, window: Window) -> Window:
        """Insert or replace a window record. Enforces the 128 cap.

        On overflow the least-recently-synced window is evicted (its nodes
        dropped) and journaled as a count. Returns the stored window.
        """
        key = window.key
        existing = self._buckets.get(key)
        if existing is not None:
            existing.window = window
            return window
        if len(self._buckets) >= MAX_WINDOWS:
            victim_key = min(
                self._buckets,
                key=lambda k: (self._buckets[k].window.synced_at,
                               self._buckets[k].window.focus_rank),
            )
            victim = self._buckets.pop(victim_key)
            self._total_nodes -= len(victim.nodes)
            journal_log.log_event(
                "watch.store", level="warn", verdict="overflow",
                detail=f"windows={MAX_WINDOWS} evicted=1",
            )
        self._buckets[key] = _WindowBucket(window=window)
        return window

    def remove_window(self, key: str) -> bool:
        bucket = self._buckets.pop(key, None)
        if bucket is None:
            return False
        self._total_nodes -= len(bucket.nodes)
        return True

    def get_window(self, key: str) -> Window | None:
        bucket = self._buckets.get(key)
        return bucket.window if bucket is not None else None

    def all_windows(self) -> tuple[Window, ...]:
        return tuple(b.window for b in self._buckets.values())

    def window_count(self) -> int:
        return len(self._buckets)

    # -- node ingestion ---------------------------------------------------
    def apply_nodes(self, window_key: str, seq: int,
                    nodes: list[Node | Tombstone]) -> bool:
        """Apply one delta batch. Returns True when applied.

        - Unknown window → False (caller must upsert first).
        - seq <= last → duplicate/out-of-order, ignored (False).
        - seq > last+1 → gap: window marked stale, batch still applied
          best-effort but the window stays stale until mark_live().
        - seq == last+1 → applied, window stays live (unless already stale).

        Caps: per-window 256 (truncate + journal), total 20k (evict oldest
        windows' nodes + journal). synced_at is stamped on success.
        """
        bucket = self._buckets.get(window_key)
        if bucket is None:
            return False
        window = bucket.window
        if seq <= window.seq:
            return False
        gap = seq > window.seq + 1
        if gap:
            window.state = "stale"
            journal_log.log_event(
                "watch.store", level="warn", verdict="stale",
                detail=f"window={window_key} reason=seq-gap",
            )
        # Replace the window's nodes with this batch (full-tree delta) or
        # append? Deltas are per-window tree snapshots for BUILD-2's pure
        # contract: the batch IS the window's current node set. Replace.
        old_count = len(bucket.nodes)
        kept = list(nodes[:MAX_NODES_PER_WINDOW])
        if len(nodes) > MAX_NODES_PER_WINDOW:
            journal_log.log_event(
                "watch.store", level="warn", verdict="overflow",
                detail=f"window={window_key} per_window={MAX_NODES_PER_WINDOW}",
            )
        bucket.nodes = kept
        self._total_nodes += len(kept) - old_count
        # Total cap: evict nodes from oldest-synced windows (never the
        # window just written) until back under the cap.
        while self._total_nodes > MAX_TOTAL_NODES:
            candidates = [k for k in self._buckets if k != window_key]
            if not candidates:
                break
            victim_key = min(
                candidates,
                key=lambda k: self._buckets[k].window.synced_at,
            )
            victim = self._buckets[victim_key]
            self._total_nodes -= len(victim.nodes)
            victim.nodes = []
            victim.window.state = "stale"
            journal_log.log_event(
                "watch.store", level="warn", verdict="overflow",
                detail=f"total={MAX_TOTAL_NODES} evicted=1",
            )
        window.seq = seq
        window.synced_at = self._now()
        return True

    def nodes_for_window(self, key: str) -> tuple[Node | Tombstone, ...]:
        bucket = self._buckets.get(key)
        return tuple(bucket.nodes) if bucket is not None else ()

    def total_nodes(self) -> int:
        return self._total_nodes

    # -- state ------------------------------------------------------------
    def mark_stale(self, key: str) -> bool:
        bucket = self._buckets.get(key)
        if bucket is None:
            return False
        bucket.window.state = "stale"
        return True

    def mark_live(self, key: str) -> bool:
        """Resync success: window live again, synced_at stamped."""
        bucket = self._buckets.get(key)
        if bucket is None:
            return False
        bucket.window.state = "live"
        bucket.window.synced_at = self._now()
        return True

    def is_stale(self, key: str) -> bool:
        bucket = self._buckets.get(key)
        return bucket is None or bucket.window.state != "live"

    def clear(self) -> None:
        """Drop everything (halt path). RAM dies with the dicts."""
        self._buckets.clear()
        self._total_nodes = 0

    # -- materialised view (BUILD-5 will rewire _elements() to this) ------
    def view(self) -> tuple[Node | Tombstone, ...]:
        """All nodes from live windows, oldest-synced first.

        Stale windows are excluded — a ring must never be drawn from a
        stale tree (§5.2). BUILD-5 adds the draw-time age check + single-
        window revalidation on top of this view.
        """
        live = [b for b in self._buckets.values() if b.window.state == "live"]
        live.sort(key=lambda b: b.window.synced_at)
        out: list[Node | Tombstone] = []
        for bucket in live:
            out.extend(bucket.nodes)
        return tuple(out)
