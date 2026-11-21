"""Tests for the draft store — the gate every phone send passes through.

Contract IF-1 (the signatures are the contract) plus the owner's 2026-11-17
amendment: four states (pending/approved/sent/failed), a repeat approve is
REFUSED, the sent body is the stored body, and the recipient is locked to its
conversation. IF-2 fixes the event envelope this module emits.
"""

from __future__ import annotations

import dataclasses

import pytest

from assistant.drafts import (
    APPROVED,
    DRAFT_STATES,
    EVENT_PENDING,
    EVENT_RESOLVED,
    FAILED,
    PENDING,
    SENT,
    DraftError,
    DraftNotFound,
    DraftRecord,
    DraftStateError,
    DraftStore,
    MemoryDraftBackend,
    SqliteDraftBackend,
)

RECIPIENT = "+254712345678"
OTHER_RECIPIENT = "+254700000000"
BODY = "On my way, ten minutes."


class Clock:
    """A clock the test moves by hand, so expiry is not a race."""

    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(clock: Clock) -> DraftStore:
    return DraftStore(MemoryDraftBackend(), clock=clock)


@pytest.fixture
def events() -> list[dict]:
    return []


@pytest.fixture
def journal() -> list[tuple[str, dict]]:
    return []


@pytest.fixture
def wired(clock: Clock, events: list, journal: list) -> DraftStore:
    def emit(envelope: dict) -> None:
        events.append(envelope)

    def journal_write(event: str, **fields) -> None:
        journal.append((event, fields))

    return DraftStore(
        MemoryDraftBackend(),
        clock=clock,
        emitter=emit,
        journal=journal_write,
    )


def _draft(store: DraftStore, **kwargs) -> str:
    params = {
        "conversation_id": "thread-7",
        "recipient": RECIPIENT,
        "body": BODY,
    }
    params.update(kwargs)
    return store.create_draft(**params)


# -- creation ----------------------------------------------------------------


def test_create_draft_makes_a_pending_draft(store: DraftStore) -> None:
    draft_id = _draft(store)
    record = store.get(draft_id)
    assert record is not None
    assert record.state == PENDING
    assert record.state in DRAFT_STATES
    assert record.conversation_id == "thread-7"
    assert record.recipient == RECIPIENT
    assert record.body == BODY
    assert record.outcome is None
    assert record.resolved_at is None


def test_create_draft_returns_the_draft_id(store: DraftStore) -> None:
    draft_id = _draft(store)
    assert isinstance(draft_id, str)
    assert store.get(draft_id) is not None


def test_create_draft_refuses_an_empty_recipient(store: DraftStore) -> None:
    with pytest.raises(DraftError):
        _draft(store, recipient="   ")


def test_create_draft_refuses_an_empty_body(store: DraftStore) -> None:
    with pytest.raises(DraftError):
        _draft(store, body="")


def test_list_pending_returns_the_if1_rows(store: DraftStore) -> None:
    draft_id = _draft(store)
    rows = store.list_pending()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {
        "draft_id",
        "conversation_id",
        "recipient",
        "body",
        "state",
        "created_at",
    }
    assert row["draft_id"] == draft_id
    assert row["state"] == "pending"
    assert row["recipient"] == RECIPIENT


def test_list_pending_is_empty_once_approved(store: DraftStore) -> None:
    draft_id = _draft(store)
    store.approve(draft_id)
    assert store.list_pending() == []


# -- the state machine --------------------------------------------------------


def test_approve_moves_pending_to_approved(store: DraftStore) -> None:
    draft_id = _draft(store)
    payload = store.approve(draft_id)
    assert payload == {"recipient": RECIPIENT, "body": BODY}
    record = store.get(draft_id)
    assert record is not None
    assert record.state == APPROVED
    assert record.resolved_at is not None


def test_repeat_approve_is_refused(store: DraftStore) -> None:
    draft_id = _draft(store)
    store.approve(draft_id)
    with pytest.raises(DraftStateError):
        store.approve(draft_id)
    record = store.get(draft_id)
    assert record is not None
    assert record.state == APPROVED


def test_approve_after_sent_is_refused(store: DraftStore) -> None:
    draft_id = _draft(store)
    store.approve(draft_id)
    store.mark_sent(draft_id)
    with pytest.raises(DraftStateError):
        store.approve(draft_id)
    record = store.get(draft_id)
    assert record is not None
    assert record.state == SENT


def test_approve_after_failure_is_refused(store: DraftStore) -> None:
    draft_id = _draft(store)
    store.reject(draft_id)
    with pytest.raises(DraftStateError):
        store.approve(draft_id)
    record = store.get(draft_id)
    assert record is not None
    assert record.state == FAILED


def test_mark_sent_needs_an_approved_draft(store: DraftStore) -> None:
    draft_id = _draft(store)
    with pytest.raises(DraftStateError):
        store.mark_sent(draft_id)
    store.approve(draft_id)
    store.mark_sent(draft_id)
    record = store.get(draft_id)
    assert record is not None
    assert record.state == SENT


def test_reject_records_the_rejected_cause(store: DraftStore) -> None:
    draft_id = _draft(store)
    store.reject(draft_id)
    record = store.get(draft_id)
    assert record is not None
    assert record.state == FAILED
    assert record.outcome == "rejected"
    assert record.resolved_at is not None


def test_reject_after_sent_is_refused(store: DraftStore) -> None:
    draft_id = _draft(store)
    store.approve(draft_id)
    store.mark_sent(draft_id)
    with pytest.raises(DraftStateError):
        store.reject(draft_id)


def test_mark_failed_records_the_send_error_cause(store: DraftStore) -> None:
    draft_id = _draft(store)
    store.approve(draft_id)
    store.mark_failed(draft_id, outcome="send-error", detail="peer refused")
    record = store.get(draft_id)
    assert record is not None
    assert record.state == FAILED
    assert record.outcome == "send-error"


def test_expire_sweeper_fails_pending_drafts(store: DraftStore, clock: Clock) -> None:
    draft_id = _draft(store)
    expired = store.expire_sweeper(clock.now + 901)
    assert expired == [draft_id]
    record = store.get(draft_id)
    assert record is not None
    assert record.state == FAILED
    assert record.outcome == "expired"


def test_expire_sweeper_leaves_fresh_drafts_alone(store: DraftStore, clock: Clock) -> None:
    draft_id = _draft(store)
    assert store.expire_sweeper(clock.now + 10) == []
    record = store.get(draft_id)
    assert record is not None
    assert record.state == PENDING


def test_unknown_draft_is_reported(store: DraftStore) -> None:
    with pytest.raises(DraftNotFound):
        store.approve("no-such-draft")


# -- immutability ------------------------------------------------------------


def test_body_is_immutable(store: DraftStore) -> None:
    draft_id = _draft(store)
    record = store.get(draft_id)
    assert record is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.body = "something else"
    stored = store.get(draft_id)
    assert stored is not None
    assert stored.body == BODY


def test_recipient_is_immutable(store: DraftStore) -> None:
    draft_id = _draft(store)
    record = store.get(draft_id)
    assert record is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.recipient = OTHER_RECIPIENT
    stored = store.get(draft_id)
    assert stored is not None
    assert stored.recipient == RECIPIENT


def test_there_is_no_retarget_operation(store: DraftStore) -> None:
    for name in ("retarget", "set_recipient", "redirect", "rewrite_body", "set_body"):
        assert not hasattr(store, name), f"{name} must not exist"
        assert not hasattr(DraftRecord, name), f"DraftRecord.{name} must not exist"


def test_approve_resolves_to_the_locked_recipient(store: DraftStore) -> None:
    draft_id = _draft(store)
    payload = store.approve(draft_id)
    assert payload["recipient"] == RECIPIENT
    record = store.get(draft_id)
    assert record is not None
    assert record.recipient == RECIPIENT
    assert record.conversation_id == "thread-7"


# -- persistence -------------------------------------------------------------


def test_drafts_round_trip_through_sqlite(tmp_path) -> None:
    backend = SqliteDraftBackend(tmp_path / "elaria.db")
    store = DraftStore(backend)
    draft_id = store.create_draft("thread-7", RECIPIENT, BODY)
    store.approve(draft_id)
    backend.close()

    reopened = DraftStore(SqliteDraftBackend(tmp_path / "elaria.db"))
    stored = reopened.get(draft_id)
    assert stored is not None
    assert stored.state == APPROVED
    assert stored.body == BODY
    assert stored.recipient == RECIPIENT
    assert stored.outcome is None


def test_state_transitions_are_persisted(tmp_path) -> None:
    path = tmp_path / "elaria.db"
    store = DraftStore(SqliteDraftBackend(path))
    draft_id = store.create_draft("c1", RECIPIENT, BODY)
    store.approve(draft_id)
    store.mark_sent(draft_id)

    reopened = DraftStore(SqliteDraftBackend(path))
    stored = reopened.get(draft_id)
    assert stored is not None
    assert stored.state == SENT
    assert reopened.list_pending() == []


def test_the_drafts_table_uses_the_agreed_columns(tmp_path) -> None:
    backend = SqliteDraftBackend(tmp_path / "elaria.db")
    backend.save(
        DraftRecord(
            draft_id="d1",
            conversation_id="c1",
            recipient=RECIPIENT,
            body=BODY,
            state=PENDING,
            created_at="2026-11-19T00:00:00+00:00",
        )
    )
    rows = backend._conn.execute("PRAGMA table_info(drafts)").fetchall()
    columns = {row[1] for row in rows}
    assert columns == {
        "draft_id",
        "conversation_id",
        "recipient",
        "body",
        "state",
        "created_at",
        "resolved_at",
        "outcome",
    }


# -- events (IF-2) ------------------------------------------------------------


def test_the_event_envelope_matches_if2(wired: DraftStore, events: list) -> None:
    _draft(wired)
    assert len(events) == 1
    envelope = events[0]
    assert set(envelope) == {"event", "draft"}
    assert envelope["event"] == EVENT_PENDING
    draft = envelope["draft"]
    for key in ("draft_id", "conversation_id", "recipient", "snippet", "state", "created_at"):
        assert key in draft, f"IF-2 requires {key} in the draft object"
    assert draft["state"] == "pending"


def test_pending_event_carries_the_full_number(wired: DraftStore, events: list) -> None:
    _draft(wired)
    draft = events[0]["draft"]
    assert draft["recipient"] == RECIPIENT
    assert draft["body"] == BODY
    assert draft["snippet"] == BODY


def test_resolved_event_carries_the_full_number(wired: DraftStore, events: list) -> None:
    draft_id = _draft(wired)
    wired.approve(draft_id)
    assert len(events) == 2
    envelope = events[1]
    assert envelope["event"] == EVENT_RESOLVED
    draft = envelope["draft"]
    assert draft["recipient"] == RECIPIENT
    assert draft["state"] == APPROVED
    assert draft["outcome"] is None


def test_a_failed_draft_reports_its_cause(wired: DraftStore, events: list) -> None:
    draft_id = _draft(wired)
    wired.reject(draft_id)
    draft = events[-1]["draft"]
    assert draft["state"] == FAILED
    assert draft["outcome"] == "rejected"


def test_events_are_emitted_for_every_outcome(wired: DraftStore, events: list) -> None:
    draft_id = _draft(wired)
    wired.approve(draft_id)
    wired.mark_sent(draft_id)
    names = [envelope["event"] for envelope in events]
    assert names == [EVENT_PENDING, EVENT_RESOLVED, EVENT_RESOLVED]
    assert events[-1]["draft"]["state"] == SENT


def test_the_journal_records_every_transition(wired: DraftStore, journal: list) -> None:
    draft_id = _draft(wired)
    wired.approve(draft_id)
    wired.mark_sent(draft_id)
    names = [event for event, _ in journal]
    assert "draft.created" in names
    assert "draft.approved" in names
    assert "draft.sent" in names
    assert all(fields["recipient"] == RECIPIENT for _, fields in journal)
