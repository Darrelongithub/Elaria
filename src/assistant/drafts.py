"""Draft store — the approval gate between Elaria and the owner's phone.

Contract IF-1 (owner: E) plus the owner's 2026-11-17 amendment. A draft is
the unit of "a message that might reach the phone": it is created ``pending``,
approved exactly once by the owner, and only then may the phone adapter hand
it to the device. The states are exactly four: ``pending``, ``approved``,
``sent``, ``failed``. "rejected", "expired" and "send-error" are CAUSES,
recorded in ``outcome`` under the terminal ``failed`` state — they are not
states of their own.

The IF-1 signatures are the contract, so the public surface is exactly:

    create_draft(conversation_id, recipient, body, source) -> draft_id
    list_pending()  -> [{draft_id, conversation_id, recipient, body, state, created_at}]
    get(draft_id)   -> DraftRecord | None
    approve(draft_id) -> {recipient, body}
    reject(draft_id)  -> None
    mark_sent(draft_id) -> None
    expire_sweeper(now) -> [draft_id]

Binding rules, each covered by tests/test_drafts.py:

* a REPEAT APPROVE IS REFUSED — ``approve()`` only ever moves
  pending -> approved, exactly once, and raises on approved/sent/failed;
* the SENT BODY IS THE STORED BODY — ``DraftRecord`` is frozen and no API
  rewrites the body between creation and send; the adapter re-reads the
  stored draft and sends that, so the body cannot come from anywhere else;
* the RECIPIENT IS LOCKED TO ITS CONVERSATION — there is no retarget
  operation anywhere in this module;
* the approval payload carries the FULL recipient number (never masked) and
  the body, because cluster K renders the owner's approval card from it.

IF-2 owns the event envelope this module emits: {"event": ..., "draft": {...}}.
The console (cluster K) renders the four states and shows the cause of a
failure; the "snippet" is a bounded preview and the "body" travels beside it
so the owner approves the whole message.

Persistence sits behind a small backend protocol so the shared store can take
over later (hook request HR-E-1). The SQLite backend below already uses the
agreed column set (draft_id, conversation_id, recipient, body, state,
created_at, resolved_at, outcome), so the wire-integration is a table move
rather than a rewrite.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)

PENDING = "pending"
APPROVED = "approved"
SENT = "sent"
FAILED = "failed"

#: The four states. Nothing else is a state.
DRAFT_STATES: tuple[str, ...] = (PENDING, APPROVED, SENT, FAILED)

#: Causes of the terminal FAILED state (IF-1 owner amendment).
FAILURE_OUTCOMES: tuple[str, ...] = ("rejected", "expired", "send-error")

#: IF-2 event names. The console (cluster K) consumes these.
EVENT_PENDING = "draft.pending"
EVENT_RESOLVED = "draft.resolved"

#: A draft nobody approves within this many seconds is expired by the sweep.
DEFAULT_TTL_SECONDS = 900

#: How much of the body the "snippet" preview carries (IF-2).
SNIPPET_CHARS = 120

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    draft_id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    recipient TEXT NOT NULL,
    body TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    outcome TEXT
)
"""


class DraftError(RuntimeError):
    """Any draft refusal or misuse. The message names what was refused."""


class DraftNotFound(DraftError):
    """No draft carries that id."""


class DraftStateError(DraftError):
    """The requested transition is not legal from the current state."""


def _utc_iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


def _snippet(body: str, limit: int = SNIPPET_CHARS) -> str:
    """A bounded preview of the body. The full body travels beside it."""
    text = str(body)
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


@dataclass(frozen=True, slots=True)
class DraftRecord:
    """One draft. Frozen: body and recipient cannot change after creation."""

    draft_id: str
    conversation_id: str
    recipient: str
    body: str
    state: str
    created_at: str
    resolved_at: str | None = None
    outcome: str | None = None

    @property
    def approved(self) -> bool:
        return self.state == APPROVED

    def pending_row(self) -> dict[str, Any]:
        """The IF-1 list_pending() row."""
        return {
            "draft_id": self.draft_id,
            "conversation_id": self.conversation_id,
            "recipient": self.recipient,
            "body": self.body,
            "state": self.state,
            "created_at": self.created_at,
        }

    def event_payload(self) -> dict[str, Any]:
        """The IF-2 "draft" object. The recipient is the FULL number."""
        payload = {
            "draft_id": self.draft_id,
            "conversation_id": self.conversation_id,
            "recipient": self.recipient,
            "snippet": _snippet(self.body),
            "body": self.body,
            "state": self.state,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
            "outcome": self.outcome,
        }
        return payload


class DraftBackend(Protocol):
    """Where drafts live between calls. The shared store replaces this (HR-E-1)."""

    def save(self, draft: DraftRecord) -> None: ...

    def load_all(self) -> list[DraftRecord]: ...


class MemoryDraftBackend:
    """In-process backend. Used by tests and by callers that do not persist."""

    def __init__(self) -> None:
        self._rows: dict[str, DraftRecord] = {}

    def save(self, draft: DraftRecord) -> None:
        self._rows[draft.draft_id] = draft

    def load_all(self) -> list[DraftRecord]:
        return list(self._rows.values())


class SqliteDraftBackend:
    """SQLite backend using the HR-E-1 column set.

    The database file is created owner-only (0600): a draft body is the
    owner's private words and must not be world-readable.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(SCHEMA)
        self._conn.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:  # pragma: no cover - exotic filesystems only
            pass

    def save(self, draft: DraftRecord) -> None:
        self._conn.execute(
            "INSERT INTO drafts (draft_id, conversation_id, recipient, body, state,"
            " created_at, resolved_at, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(draft_id) DO UPDATE SET conversation_id=excluded.conversation_id,"
            " recipient=excluded.recipient, body=excluded.body, state=excluded.state,"
            " created_at=excluded.created_at, resolved_at=excluded.resolved_at,"
            " outcome=excluded.outcome",
            (
                draft.draft_id,
                draft.conversation_id,
                draft.recipient,
                draft.body,
                draft.state,
                draft.created_at,
                draft.resolved_at,
                draft.outcome,
            ),
        )
        self._conn.commit()

    def load_all(self) -> list[DraftRecord]:
        rows = self._conn.execute(
            "SELECT draft_id, conversation_id, recipient, body, state, created_at,"
            " resolved_at, outcome FROM drafts ORDER BY created_at, draft_id"
        ).fetchall()
        return [
            DraftRecord(
                draft_id=row["draft_id"],
                conversation_id=row["conversation_id"],
                recipient=row["recipient"],
                body=row["body"],
                state=row["state"],
                created_at=row["created_at"],
                resolved_at=row["resolved_at"],
                outcome=row["outcome"],
            )
            for row in rows
        ]

    def close(self) -> None:
        self._conn.close()


class DraftStore:
    """The draft state machine, its persistence and its IF-2 events.

    ``emitter`` receives one IF-2 envelope per event:
    ``emitter({"event": "draft.pending", "draft": {...}})``.
    ``journal`` receives audit lines as ``journal(event, **fields)`` and is
    owned by cluster D (hook request HR-E-4); both seams are optional so the
    store is usable on its own.
    """

    def __init__(
        self,
        backend: DraftBackend | None = None,
        *,
        emitter: Callable[[dict[str, Any]], None] | None = None,
        journal: Callable[..., None] | None = None,
        clock: Callable[[], float] | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._backend = backend if backend is not None else MemoryDraftBackend()
        self._emitter = emitter
        self._journal = journal
        self._clock = clock if clock is not None else time.time
        self._ttl = float(ttl_seconds)
        self._id_factory = id_factory if id_factory is not None else (lambda: uuid.uuid4().hex)
        self._rows: dict[str, DraftRecord] = {}
        for draft in self._backend.load_all():
            self._rows[draft.draft_id] = draft

    # -- the IF-1 surface -----------------------------------------------------

    def create_draft(
        self,
        conversation_id: str,
        recipient: str,
        body: str,
        source: str = "inbound_sms",
    ) -> str:
        """Create a pending draft. The body and recipient are fixed here."""
        recipient = str(recipient)
        body = str(body)
        if not recipient.strip():
            raise DraftError("refusing to create a draft with an empty recipient")
        if not body:
            raise DraftError("refusing to create a draft with an empty body")
        conversation = str(conversation_id).strip()
        if not conversation:
            raise DraftError("refusing to create a draft without a conversation")
        draft = DraftRecord(
            draft_id=self._id_factory(),
            conversation_id=conversation,
            recipient=recipient,
            body=body,
            state=PENDING,
            created_at=_utc_iso(self._clock()),
        )
        self._rows[draft.draft_id] = draft
        self._backend.save(draft)
        self._audit("draft.created", draft, source=str(source))
        self._emit(EVENT_PENDING, draft)
        return draft.draft_id

    def list_pending(self) -> list[dict[str, Any]]:
        """The IF-1 pending rows."""
        return [draft.pending_row() for draft in self._records(PENDING)]

    def get(self, draft_id: str) -> DraftRecord | None:
        return self._rows.get(str(draft_id))

    def approve(self, draft_id: str) -> dict[str, str]:
        """pending -> approved, exactly once. Anything else raises.

        Returns the IF-1 payload {recipient, body} — the FULL number and the
        stored body, so the console can render what it is approving.
        """
        draft = self._require(draft_id)
        if draft.state != PENDING:
            raise DraftStateError(
                f"approve refused: draft {draft.draft_id} is {draft.state}"
                " (approve is legal only once, from pending)"
            )
        approved = self._transition(draft, APPROVED)
        self._audit("draft.approved", approved)
        self._emit(EVENT_RESOLVED, approved)
        return {"recipient": approved.recipient, "body": approved.body}

    def reject(self, draft_id: str, *, reason: str = "rejected", detail: str | None = None) -> None:
        """pending|approved -> failed, cause "rejected"."""
        draft = self._require(draft_id)
        if draft.state in (SENT, FAILED):
            raise DraftStateError(
                f"reject refused: draft {draft.draft_id} is {draft.state} (terminal)"
            )
        if reason not in FAILURE_OUTCOMES:
            raise DraftError(f"unknown failure outcome {reason!r}")
        failed = self._transition(draft, FAILED, outcome=reason)
        self._audit("draft.rejected", failed, detail=detail)
        self._emit(EVENT_RESOLVED, failed)

    def mark_sent(self, draft_id: str) -> None:
        """approved -> sent. A draft that was never approved cannot be sent."""
        draft = self._require(draft_id)
        if draft.state != APPROVED:
            raise DraftStateError(
                f"send refused: draft {draft.draft_id} is {draft.state}"
                " (only an approved draft may be sent)"
            )
        sent = self._transition(draft, SENT)
        self._audit("draft.sent", sent)
        self._emit(EVENT_RESOLVED, sent)

    def expire_sweeper(self, now: float) -> list[str]:
        """pending older than the TTL -> failed/expired. Returns the draft ids."""
        moment = float(now)
        expired: list[str] = []
        for draft in self._records(PENDING):
            if moment - self._epoch(draft.created_at) <= self._ttl:
                continue
            failed = self._transition(draft, FAILED, outcome="expired")
            self._audit("draft.expired", failed)
            self._emit(EVENT_RESOLVED, failed)
            expired.append(failed.draft_id)
        return expired

    # -- additions (not in IF-1, but the same state machine) ------------------

    def mark_failed(
        self,
        draft_id: str,
        *,
        outcome: str = "send-error",
        detail: str | None = None,
    ) -> None:
        """approved -> failed, cause "send-error" (the transport refused)."""
        draft = self._require(draft_id)
        if draft.state in (SENT, FAILED):
            raise DraftStateError(
                f"failure refused: draft {draft.draft_id} is {draft.state} (terminal)"
            )
        if outcome not in FAILURE_OUTCOMES:
            raise DraftError(f"unknown failure outcome {outcome!r}")
        failed = self._transition(draft, FAILED, outcome=outcome)
        self._audit("draft.failed", failed, detail=detail)
        self._emit(EVENT_RESOLVED, failed)

    def list_records(self, state: str | None = None) -> list[DraftRecord]:
        """Every record, optionally filtered by state (rendering history)."""
        return self._records(state)

    # -- internals ------------------------------------------------------------

    def _records(self, state: str | None = None) -> list[DraftRecord]:
        rows = list(self._rows.values())
        if state is not None:
            rows = [d for d in rows if d.state == state]
        rows.sort(key=lambda d: (d.created_at, d.draft_id))
        return rows

    def _require(self, draft_id: str) -> DraftRecord:
        draft = self._rows.get(str(draft_id))
        if draft is None:
            raise DraftNotFound(f"no draft {draft_id!r}")
        return draft

    def _transition(
        self, draft: DraftRecord, state: str, *, outcome: str | None = None
    ) -> DraftRecord:
        if state not in DRAFT_STATES:
            raise DraftError(f"unknown state {state!r}")
        updated = DraftRecord(
            draft_id=draft.draft_id,
            conversation_id=draft.conversation_id,
            recipient=draft.recipient,
            body=draft.body,
            state=state,
            created_at=draft.created_at,
            resolved_at=_utc_iso(self._clock()),
            outcome=outcome,
        )
        self._rows[updated.draft_id] = updated
        self._backend.save(updated)
        return updated

    def _emit(self, event_type: str, draft: DraftRecord) -> None:
        if self._emitter is None:
            return
        envelope = {"event": event_type, "draft": draft.event_payload()}
        try:
            self._emitter(envelope)
        except Exception:  # a broken consumer must not corrupt the state machine
            log.exception("draft event consumer failed for %s", event_type)

    def _audit(self, event: str, draft: DraftRecord, **fields: Any) -> None:
        if self._journal is None:
            return
        payload = {
            "draft_id": draft.draft_id,
            "conversation_id": draft.conversation_id,
            "recipient": draft.recipient,
            "state": draft.state,
            "outcome": draft.outcome,
        }
        payload.update(fields)
        try:
            self._journal(event, **payload)
        except Exception:
            log.exception("journal write failed for %s", event)

    @staticmethod
    def _epoch(iso: str) -> float:
        try:
            return datetime.fromisoformat(iso).timestamp()
        except ValueError:
            return 0.0


def dumps_drafts(drafts: list[DraftRecord]) -> str:
    """JSON for the drafts, used by the console and by fixtures."""
    return json.dumps([d.event_payload() for d in drafts], ensure_ascii=False, indent=2)
