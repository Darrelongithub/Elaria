"""WP7 cold storage & backup — the sensors (increment 5).

Six journal events, emitted through `journal_log.log_event()` and conforming to the
**canonical §2 contract** (report 007, designated canonical by design-chat ruling):

```
LINE   ::= ts SP level SP event SP session_id SP peak SP verdict [ SP detail ]
PARSE  ::= line.split(" ", 6)   ->  6 parts (no detail) | 7 parts (detail in parts[6])
DISPATCH ::= key on parts[2] (event) ONLY. NEVER key on parts[5] (verdict).
```

Three disciplines are load-bearing here, and each is pinned by a test rather than
asserted in prose:

**`session_id` is `-`.** A backup run is not a session. §2 permits `-` for `session_id`,
and using a real session id here would make a backup event look like a transcription
event to any consumer dispatching on the event name.

**No path ever reaches a detail.** The privacy fence (report 006 §6): counts, states,
sizes, hashes and backend names may leave the laptop; artifact names may not. Every
detail in this module is built from numbers and enumerations.

**Every verification names its backend.** `backup.verify` carries the backend that
produced the answer, so a `LocalPathBackend` confirmation can never be read as real
remote confirmation by whoever reads the journal later. This is the provenance
requirement from increment 4, carried through to the sensor surface.

Evidence tags: `[TESTED-ONLY]`. No sensor here touches a network.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .journal_log import log_event

__all__ = [
    "BACKUP_EVENTS",
    "StorageGauge",
    "backup_check",
    "backup_done",
    "backup_failed",
    "backup_started",
    "backup_verify",
    "scrub",
    "storage_gauge",
]

#: The event names this module emits. Nothing else is dispatched on verdict — §2.1.
BACKUP_EVENTS: tuple[str, ...] = (
    "backup.started",
    "backup.done",
    "backup.failed",
    "backup.verify",
    "backup.check",
    "storage.gauge",
)

#: `-` is the §2 placeholder for "not a session event". Every sensor here uses it.
NO_SESSION = "-"

#: Anything that looks like a filesystem path. The fence is STRUCTURAL, not caller
#: discipline: a caller that does `backup_failed(reason=str(exc))` will hand us a
#: `FileNotFoundError` whose message is an absolute path, and the fence must hold anyway.
_PATHLIKE = re.compile(r"(?:[\w.@+\-]*/)+[\w.@+\-]+")

#: What a redacted path becomes. Says something was removed without saying what.
_REDACTED = "<path>"


def scrub(text: str) -> str:
    """Remove anything that looks like a filesystem path from free text.

    Over-redaction is safe; under-redaction is not. A phrase like `read/write` is
    collapsed to `read<path>write`, which is a small price for a fence that holds when a
    caller is careless.
    """

    return _PATHLIKE.sub(_REDACTED, str(text if text is not None else ""))


def _emit(event: str, *, level: str, verdict: str, detail: str, stream=None) -> str:
    """Emit one sensor line. `session_id` is always `-` and `peak` is never set.

    The defaults exist so a future edit cannot accidentally attach a session id or a
    peak to a backup event without this function changing shape. `detail` is scrubbed on
    the way out, so no caller-supplied string can smuggle a path past the fence.
    """

    return log_event(event, level=level, session_id=NO_SESSION, verdict=verdict,
                     detail=scrub(detail), stream=stream)


# --------------------------------------------------------------------------------------
# The gauge
# --------------------------------------------------------------------------------------


@dataclass
class StorageGauge:
    """A snapshot of the storage picture, with no path in it.

    `hot_bytes` / `cold_bytes` are the two tiers; `remote_free_bytes` is what the remote
    reports as free. The capacity-floor knock is expressed as `remote_free < 10 GB`
    (50 % of the free tier) so it stays equivalent on a 20 GB tier.

    `floor_bytes` is carried so `below_floor()` is a comparison against the same number
    that was configured, rather than a constant re-derived at the call site.
    """

    hot_bytes: int = 0
    cold_bytes: int = 0
    hot_count: int = 0
    cold_count: int = 0
    remote_free_bytes: int | None = None
    floor_bytes: int = 10 * 1000 ** 3
    window_days: int = 14
    window_gb: int = 2

    @property
    def total_bytes(self) -> int:
        return self.hot_bytes + self.cold_bytes

    @property
    def remote_free_known(self) -> bool:
        """False when the remote could not be read. An unknown free figure is not zero."""

        return self.remote_free_bytes is not None

    def below_floor(self) -> bool:
        """True only when the remote free figure is known AND below the floor.

        An unread remote is **not** "below the floor" — it is unknown, and reporting
        unknown as below would raise a knock the design never asked for.
        """

        if self.remote_free_bytes is None:
            return False
        return self.remote_free_bytes < self.floor_bytes

    def detail(self) -> str:
        """The gauge as a path-free detail string."""

        free = "unknown" if self.remote_free_bytes is None else str(self.remote_free_bytes)
        return (
            f"hot={self.hot_bytes}; cold={self.cold_bytes}; "
            f"hot_n={self.hot_count}; cold_n={self.cold_count}; "
            f"remote_free={free}; floor={self.floor_bytes}; "
            f"below_floor={'yes' if self.below_floor() else 'no'}; "
            f"window_days={self.window_days}; window_gb={self.window_gb}"
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["total_bytes"] = self.total_bytes
        data["below_floor"] = self.below_floor()
        data["remote_free_known"] = self.remote_free_known
        return data


def storage_gauge(gauge: StorageGauge, *, stream=None) -> str:
    """Emit `storage.gauge`. `info` normally, `warn` when the floor is breached."""

    return _emit("storage.gauge",
                 level="warn" if gauge.below_floor() else "info",
                 verdict="below_floor" if gauge.below_floor() else "ok",
                 detail=gauge.detail(), stream=stream)


# --------------------------------------------------------------------------------------
# The run lifecycle
# --------------------------------------------------------------------------------------


def backup_started(*, reason: str, stream=None) -> str:
    """A backup run began. `reason` is a short phrase, never a path."""

    return _emit("backup.started", level="info", verdict="started",
                 detail=f"reason={reason}", stream=stream)


def backup_done(*, sent_cold: int = 0, kept_hot: int = 0, trimmed: int = 0,
                purged: int = 0, problems: int = 0, passes: int = 1,
                stream=None) -> str:
    """A backup run completed. Counts only."""

    return _emit(
        "backup.done", level="info", verdict="done",
        detail=(f"sent_cold={sent_cold}; kept_hot={kept_hot}; trimmed={trimmed}; "
                f"purged={purged}; problems={problems}; passes={passes}"),
        stream=stream)


def backup_failed(*, reason: str, stream=None) -> str:
    """A backup run failed. `reason` names the failure, never the artifact."""

    return _emit("backup.failed", level="error", verdict="failed",
                 detail=f"reason={reason}", stream=stream)


# --------------------------------------------------------------------------------------
# Verification and integrity
# --------------------------------------------------------------------------------------


def backup_verify(*, backend: str, method: str, confirmed: bool,
                  stream=None) -> str:
    """A verification happened.

    `backend` and `method` come straight from the `Verification` that produced the answer,
    so a fixture confirmation is recorded as `local-path-fixture` and a real one as
    `rclone:<remote>`. `warn` on a negative answer, because a verification that failed is
    something an operator should see.
    """

    return _emit(
        "backup.verify",
        level="info" if confirmed else "warn",
        verdict="confirmed" if confirmed else "unconfirmed",
        detail=f"backend={backend}; method={method}; "
               f"confirmed={'yes' if confirmed else 'no'}",
        stream=stream)


def backup_check(*, kind: str, ok: bool, detail: str = "", stream=None) -> str:
    """An integrity check. `kind` is `monthly` or `quarterly` (the drill cadence)."""

    body = f"kind={kind}; ok={'yes' if ok else 'no'}"
    if detail:
        body += f"; {detail}"
    return _emit("backup.check", level="info" if ok else "error",
                 verdict="passed" if ok else "failed", detail=body, stream=stream)


# --------------------------------------------------------------------------------------
# Helpers shared with the CLI
# --------------------------------------------------------------------------------------


def gauge_from_manifest(manifest, *, floor_bytes: int, window_days: int,
                        window_gb: int, remote_free_bytes: int | None = None,
                        now=None) -> StorageGauge:
    """Build a gauge from a manifest. Counts and bytes only — never a path.

    `remote_free_bytes` stays `None` unless the caller read it from a remote, so an
    unread remote is reported as unknown rather than as zero.
    """

    hot = cold = hot_n = cold_n = 0
    for record in manifest.current().values():
        size = int(record.size or 0)
        if record.state in {"local", "uploaded"}:
            hot += size
            hot_n += 1
        elif record.state in {"flipped", "trashed", "purged"}:
            cold += size
            cold_n += 1
    return StorageGauge(hot_bytes=hot, cold_bytes=cold, hot_count=hot_n,
                        cold_count=cold_n, remote_free_bytes=remote_free_bytes,
                        floor_bytes=floor_bytes, window_days=window_days,
                        window_gb=window_gb)


def artifact_label(path: Path | str) -> str:
    """A path-free label for an artifact: its extension and nothing else.

    Used where a CLI message must refer to an artifact without naming it. The extension
    is enough to recognise a shape (`wav`) and carries no information about the owner.
    """

    suffix = Path(path).suffix.lower()
    return suffix.lstrip(".") or "unknown"
