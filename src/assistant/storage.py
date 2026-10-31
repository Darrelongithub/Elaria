"""WP7 cold storage & backup — the STORAGE MANIFEST (increment 1 of 8).

The manifest is the single record of intent and state per artifact. It is an
**append-only JSONL journal**: a state change never rewrites history, it appends
a new record. The current state of an artifact is the *last* record bearing its
path. Nothing here deletes a line — the manifest is the audit trail for every
decision the backup machinery ever made, which is why `restic forget`/`prune`
are recorded here rather than performed silently (auto-delete never exists).

The five states, and why they are ordered this way:

    local      the artifact's only copy is on the HOT disk
    uploaded   a remote copy exists AND the hot copy is still in place (2 copies)
    flipped    the authoritative home is now COLD; the hot copy is still in place
               (2 copies) — this is the durable DECISION point
    trashed    the hot copy has moved to local trash, 14-day grace running
               (2 copies: remote + trash)
    purged     grace elapsed, trash emptied — the remote is now the only copy

The ordering exists to guarantee the spec's invariant: **no artifact ever has
exactly one copy the instant the flip lands.** Between `flipped` and `purged`
there are always at least two copies, so a bad flip is recoverable rather than
fatal.

Crash consistency (the property increment 2's crash-point tests will pin):

  * every append is `fsync`'d before it returns, so a record that is readable
    is durable. A crash mid-append can only leave a trailing line with no
    newline, which `records()` discards as *not durable* — it never becomes a
    half-state the reconciler acts on.
  * the `flip` must be fsync'd **before** any trim. `append()` always fsyncs,
    so the trim path calls `append(FLIPPED)` and proceeds only on `True`.
  * the transition table refuses illegal moves. `local -> trashed` is refused
    because it would trash the only copy; `uploaded -> trashed` is refused
    because it would trim without ever recording the flip decision. The
    state machine enforces the ordering instead of trusting callers.

PRIVACY FENCE (report 006 §6, binding): the manifest stores the artifact path
as the record of intent and state, lives only on the owner's laptop at 0600
outside the repo, and is never committed. This module never writes a path to
stdout, a journal line, a sensor event, a phase report, a PR or a chat message.
`redact()` exists so callers have one obvious way to keep that promise; the
only thing that may leave this machine about an artifact is its **count**, its
**size**, its **class** and its **state** — never its name.

Evidence tags: [TESTED-ONLY] throughout — every number here comes from synthetic
fixtures and a local-path backend. Nothing has touched MEGA, and no real wav
has entered this sandbox.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .config import ensure_private_dir
from .cost import iso_now

__all__ = [
    "TIER_COLD",
    "TIER_HOT",
    "ManifestRecord",
    "ManifestState",
    "StorageManifest",
    "redact",
]

# -- states -----------------------------------------------------------------

LOCAL = "local"
UPLOADED = "uploaded"
FLIPPED = "flipped"
TRASHED = "trashed"
PURGED = "purged"


class ManifestState:
    """The five states, as names rather than bare strings.

    Ordering is load-bearing: it is the copy-count argument above. Anything
    that reorders these needs a design-chat entry, not a refactor.
    """

    LOCAL = LOCAL
    UPLOADED = UPLOADED
    FLIPPED = FLIPPED
    TRASHED = TRASHED
    PURGED = PURGED
    ALL = (LOCAL, UPLOADED, FLIPPED, TRASHED, PURGED)


# Legal transitions. A missing pair is a refusal, not a guess: the manifest
# refuses to record a move that would break the copy-count invariant.
_TRANSITIONS: dict[str, frozenset[str]] = {
    LOCAL: frozenset({UPLOADED}),
    UPLOADED: frozenset({FLIPPED}),
    FLIPPED: frozenset({TRASHED}),
    TRASHED: frozenset({PURGED}),
    PURGED: frozenset(),
}


TIER_HOT = "hot"
TIER_COLD = "cold"


@dataclass
class ManifestRecord:
    """One append-only line: intent + state for one artifact at one moment.

    `artifact` is the absolute path — the record of intent. It never leaves
    the laptop (see the module docstring's privacy fence). `detail` is free
    text and carries counts and identifiers only, never content.
    """

    artifact: str
    state: str
    ts: str = field(default_factory=iso_now)
    sha256: str | None = None
    size: int | None = None
    tier: str | None = None
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "artifact": self.artifact,
            "state": self.state,
            "ts": self.ts,
            "sha256": self.sha256,
            "size": self.size,
            "tier": self.tier,
            "detail": self.detail,
        }, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> ManifestRecord:
        row = json.loads(line)
        return cls(
            artifact=str(row["artifact"]),
            state=str(row["state"]),
            ts=str(row["ts"]),
            sha256=(None if row.get("sha256") is None else str(row["sha256"])),
            size=(None if row.get("size") is None else int(row["size"])),
            tier=(None if row.get("tier") is None else str(row["tier"])),
            detail=str(row.get("detail") or ""),
        )


def redact(value) -> str:
    """Collapse anything that could name a file into a safe token.

    The privacy fence in one function: sensors, logs and reports pass paths
    through here so a path can never escape by accident. Counts, sizes,
    classes and states are *not* redacted — they are the aggregates the owner
    is allowed to see.
    """

    return "<redacted>"


class StorageManifest:
    """Append-only JSONL manifest at 0600 outside the repo.

    The manifest is opened lazily and every append is fsync'd, so "the record
    is readable" and "the record is durable" are the same statement. That is
    what makes the flip-before-trim ordering enforceable rather than
    aspirational.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._parent_ensured = False

    # -- lifecycle ----------------------------------------------------------
    def _ensure_parent(self) -> None:
        if self._parent_ensured:
            return
        ensure_private_dir(self.path.parent)
        self._parent_ensured = True

    def exists(self) -> bool:
        return self.path.exists()

    # -- writing ------------------------------------------------------------
    def append(self, record: ManifestRecord, *,
               expect_from: str | None = None) -> bool:
        """Append one record, fsync'd. False = the move was refused.

        `expect_from` is the caller's claim about the artifact's current state.
        When given, the transition table is enforced against it, so a caller
        that has stale in-memory state cannot record an illegal move. When
        omitted the record is appended unconditionally — used only by
        reconcile-on-start, which is *repairing* a state the machine already
        decided and must be able to complete an interrupted sequence.
        """

        if record.state not in ManifestState.ALL:
            raise ValueError(f"unknown manifest state: {record.state!r}")
        if expect_from is not None and record.state not in _TRANSITIONS.get(
                expect_from, frozenset()):
            return False
        self._ensure_parent()
        line = record.to_json() + "\n"
        # One write() of a complete line, then fsync. A crash before the fsync
        # can leave a trailing fragment with no newline, which records()
        # discards — a half-state is never something the reconciler acts on.
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return True

    # -- reading ------------------------------------------------------------
    def records(self) -> list[ManifestRecord]:
        """Every durable record, oldest first.

        A trailing line without a newline is a crash-before-fsync fragment and
        is dropped, not parsed. Tolerating it is what makes a killed append
        safe rather than corrupting.
        """

        if not self.path.exists():
            return []
        out: list[ManifestRecord] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for raw in handle:
                if not raw.endswith("\n"):
                    break  # not durable — the fsync never landed
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(ManifestRecord.from_json(raw))
                except (ValueError, KeyError, TypeError):
                    # A malformed line is skipped, never fatal: the manifest
                    # is the audit trail and losing one line must not stop the
                    # reconciler from reading the rest.
                    continue
        return out

    def current(self) -> dict[str, ManifestRecord]:
        """artifact -> its latest record. The reconcile view.

        This is the "single record of intent/state per artifact": the journal
        is append-only and may hold many lines for one artifact, but exactly
        one of them is authoritative at any moment — the last.
        """

        latest: dict[str, ManifestRecord] = {}
        for record in self.records():
            latest[record.artifact] = record
        return latest

    def state_of(self, artifact: str) -> str | None:
        record = self.current().get(str(artifact))
        return record.state if record else None

    # -- aggregate views (the only shape that may leave the laptop) ---------
    def summary(self) -> dict:
        """Counts and sizes by state and tier. No paths, ever.

        Sensors, phase reports and PRs read this. It is deliberately blind to
        which artifact is which — that blindness IS the privacy fence, not a
        limitation of it.
        """

        by_state: dict[str, int] = {}
        by_tier: dict[str, int] = {}
        bytes_by_state: dict[str, int] = {}
        for record in self.current().values():
            by_state[record.state] = by_state.get(record.state, 0) + 1
            tier = record.tier or "unknown"
            by_tier[tier] = by_tier.get(tier, 0) + 1
            if record.size:
                bytes_by_state[record.state] = (bytes_by_state.get(record.state, 0)
                                                + int(record.size))
        return {"artifacts": len(self.current()), "by_state": by_state,
                "by_tier": by_tier, "bytes_by_state": bytes_by_state}
