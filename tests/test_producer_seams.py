"""Producer seams 3, 5 and 6 — the "seams bite" grant (2026-11-05).

Design and estimates: docs/design/2026-11-05-producer-seam-estimates.md §9
(re-derived against the console table `342fdd9`; its mapping is authoritative).
Grant: seams 3 (causal message id), 5 (remember receipt) and 6 (forget receipt)
exactly as estimated — additive producer fields only, no new RPC, no schema
change, no cli.py change. Seams 1, 2, 4 and 7 remain design-only.

Acceptance clauses pinned here, clause by clause:
  1 the message id is THIS turn's append, and a second turn gets its own;
  2 a turn that writes no row declares a null, never a sample;
  3 remember's claim is contingent on the store's verified row;
  4 remember declares retention and restore semantics, and no API restores;
  5 forget's ids are knowable at decision time, with the state read back;
  6 forget reports the database's exact count, and the ids agree with it;
  7 forget declares what the schema cannot give (versions, durable receipt),
    and no receipts table exists — D4's convention, corr_id + corr_ts;
  8 the typed-intent paths name ids or say nothing matched — never prose
    asserting an effect;
  9 the fields are additive: every pre-existing key keeps its type, and no
    new RPC exists to reconstruct any of it.
[TESTED-ONLY] — real store, real socket daemon; no hardware, no model calls.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from assistant.daemon import Daemon
from assistant.embeddings import HashingEmbedder
from assistant.intents import route
from assistant.ipc import call
from assistant.memory import Memory
from assistant.store import Store

# ------------------------------------------------------------------ fixtures


def _memory(tmp_path):
    store = Store(tmp_path / "seams.db")
    return store, Memory(store, HashingEmbedder())


def _daemon(store, memory):
    """The three handlers on a stub carrying only what they touch."""
    daemon = object.__new__(Daemon)
    daemon.store = store
    daemon.memory = memory
    return daemon


def _remember(daemon, **params):
    return asyncio.run(daemon._memory_remember(params))


def _forget(daemon, **params):
    return asyncio.run(daemon._memory_forget(params))


def _fact(store, fact_id):
    rows = {int(r["id"]): r for r in store.list_facts(active_only=False)}
    return rows[int(fact_id)]


# ------------------------------------- clause 1: the id is this turn's append
def test_turn_message_id_is_this_turns_append(running_daemon):
    daemon, _server = running_daemon
    out = call(daemon.config.socket_path, "console.say", {"text": "status"})

    assert isinstance(out["message_id"], int)
    assert isinstance(out["user_message_id"], int)
    rows = {int(m["id"]): m for m in
            daemon.sessions.history(limit=5)["messages"]}
    # The id names the assistant row this turn wrote — read back by id, not by
    # taking the last row and hoping nobody appended since.
    assert rows[out["message_id"]]["role"] == "assistant"
    assert rows[out["message_id"]]["text"] == out["reply"]
    assert rows[out["user_message_id"]]["role"] == "user"
    assert rows[out["user_message_id"]]["text"] == "status"
    assert out["user_message_id"] < out["message_id"]


def test_second_turn_gets_its_own_message_id(running_daemon):
    daemon, _server = running_daemon
    socket = daemon.config.socket_path
    first = call(socket, "console.say", {"text": "status"})
    second = call(socket, "console.say", {"text": "queue status"})

    assert second["message_id"] > first["message_id"]
    assert second["user_message_id"] > first["message_id"]
    rows = {int(m["id"]): m for m in
            daemon.sessions.history(limit=8)["messages"]}
    # Each id still points at its own turn's text: the ids are causal, not a
    # shared tail sample that both turns would inherit.
    assert rows[first["message_id"]]["text"] == first["reply"]
    assert rows[second["message_id"]]["text"] == second["reply"]
    assert "Running" in rows[first["message_id"]]["text"]
    assert "Cloud queue" in rows[second["message_id"]]["text"]


# ------------------------- clause 2: a turn that writes no row declares a null
def test_guest_turn_declares_no_message_id(running_daemon):
    daemon, _server = running_daemon
    before = len(daemon.sessions.history(limit=200)["messages"])
    out = call(daemon.config.socket_path, "ask",
               {"text": "hello there", "speaker": "guest"})

    assert out["speaker"] == "guest"
    # BH-J1: a guest turn writes no conversation row, so there is no causal id.
    assert out["message_id"] is None
    assert out["user_message_id"] is None
    assert out["receipt"] is None
    assert len(daemon.sessions.history(limit=200)["messages"]) == before


# ------------------ clause 3: remember's claim is the verified store result
def test_remember_receipt_is_the_row(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        out = _remember(daemon, text="My accountant is Wanjiru", kind="profile")
        row = _fact(store, out["fact_id"])
        assert row["active"] == 1
        assert out["kind"] == row["kind"] == "profile"
        assert out["source"] == row["source"] == "stated"
        assert out["active"] is True
        assert str(out["fact_id"]) in out["stored"]
    finally:
        store.close()


def test_remember_does_not_claim_when_the_store_cannot_read_it_back(
        tmp_path, monkeypatch):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    monkeypatch.setattr(memory, "remember", lambda *a, **k: 99999)
    try:
        with pytest.raises(ValueError, match="no active fact reads back"):
            _remember(daemon, text="anything")
        # Nothing was written, so nothing is claimable.
        assert store.list_facts() == []
    finally:
        store.close()


def test_remember_does_not_claim_an_inactive_row(tmp_path, monkeypatch):
    """The row must read back ACTIVE. A deactivated id is not a store."""
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    store.add_fact(ts="2026-11-05T00:00:00+00:00", kind="profile", text="old")
    store.forget_facts("old")
    monkeypatch.setattr(memory, "remember", lambda *a, **k: 1)
    try:
        with pytest.raises(ValueError, match="no active fact reads back"):
            _remember(daemon, text="old")
    finally:
        store.close()


# ------------------- clause 4: retention and restore are declared, not implied
def test_remember_declares_retention_and_restore(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        out = _remember(daemon, text="Prefers morning briefings", kind="preference")
        assert out["retention"] == "until_forgotten"
        # Truthful form of "restorable": the row survives deactivation, and no
        # API restores it today — so the declaration must not promise one.
        assert out["restore"] == "row_preserved_no_api"
        store.forget_facts("morning briefings")
        row = _fact(store, out["fact_id"])
        assert row["active"] == 0 and row["text"] == "Prefers morning briefings"
    finally:
        store.close()


# --------------- clause 5: forget's ids are knowable, and the state is read back
def test_forget_names_exactly_the_deactivated_ids(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        a = _remember(daemon, text="Accountant is Wanjiru")["fact_id"]
        b = _remember(daemon, text="Wanjiru handles the March invoice")["fact_id"]
        c = _remember(daemon, text="Prefers tea over coffee")["fact_id"]

        out = _forget(daemon, topic="Wanjiru")

        assert out["forgotten"] == 2
        assert sorted(out["fact_ids"]) == sorted([a, b])
        assert {f["id"] for f in out["facts"]} == {a, b}
        assert all(f["state"] == "inactive" for f in out["facts"])
        assert all(f["kind"] for f in out["facts"])
        # The facts that were not matched are untouched — the receipt does not
        # over-claim by naming a wider set than the database deactivated.
        assert _fact(store, c)["active"] == 1
    finally:
        store.close()


def test_forget_by_id_deactivates_only_that_row(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        a = _remember(daemon, text="Accountant is Wanjiru")["fact_id"]
        b = _remember(daemon, text="Accountant is also Wanjiru")["fact_id"]
        out = _forget(daemon, topic=f"#{a}")
        assert out["fact_ids"] == [a]
        assert out["forgotten"] == 1
        assert _fact(store, b)["active"] == 1
    finally:
        store.close()


# ---------------------------------- clause 6: the count is the database's, and it agrees
def test_forget_count_matches_ids_and_zero_match_declares_nothing(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        _remember(daemon, text="Accountant is Wanjiru")
        out = _forget(daemon, topic="Wanjiru")
        assert out["forgotten"] == len(out["fact_ids"]) == 1

        empty = _forget(daemon, topic="nothing like this exists")
        assert empty["forgotten"] == 0
        assert empty["fact_ids"] == []
        assert empty["facts"] == []
    finally:
        store.close()


def test_forget_percent_stays_literal(tmp_path):
    """`forget %` deactivates nothing: the topic is text, not a pattern."""
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        _remember(daemon, text="Accountant is Wanjiru")
        out = _forget(daemon, topic="%")
        assert out["fact_ids"] == [] and out["forgotten"] == 0
        assert len(store.list_facts()) == 1
    finally:
        store.close()


# ------------- clause 7: declared absences, and D4's convention on the wire
def test_forget_declares_absent_versions_and_no_receipts_table(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        _remember(daemon, text="Accountant is Wanjiru")
        out = _forget(daemon, topic="Wanjiru")

        assert "absent" in out["declared"]["versions"]
        assert "no receipts table" in out["declared"]["durable_receipt"]
        # The declaration is true of the schema, not just of the string.
        tables = {r[0] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
        assert not [t for t in tables if "receipt" in t.lower()]
    finally:
        store.close()


def test_forget_corr_id_and_ts_bind_the_decision(tmp_path):
    """D4, ruled 2026-11-05: corr_id + ts is the decision identity."""
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        _remember(daemon, text="Accountant is Wanjiru")
        one = _forget(daemon, topic="Wanjiru")
        two = _forget(daemon, topic="Wanjiru")

        assert re.fullmatch(r"[0-9a-f]{32}", one["corr_id"])
        assert one["corr_id"] != two["corr_id"]
        assert one["corr_ts"] and one["corr_ts"] != ""
        assert one["forgotten"] == 1 and two["forgotten"] == 0
    finally:
        store.close()


# ------------------- clause 8: the typed-intent paths carry the receipts too
def test_remember_intent_names_the_fact_and_carries_its_receipt(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    intent = route("remember that my accountant is Wanjiru")
    assert intent is not None and intent.kind == "remember"
    try:
        reply, via, receipt = asyncio.run(daemon._run_intent(intent))
        assert via == "local-intent"
        assert receipt is not None and receipt["receipt"] == "remember"
        assert f"#{receipt['fact_id']}" in reply
        # The prose names the fact it stored — it no longer echoes the text
        # back as if echoing were storing.
        assert "Wanjiru" not in reply
        assert _fact(store, receipt["fact_id"])["active"] == 1
    finally:
        store.close()


def test_forget_intent_names_ids_or_says_nothing_matched(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    fid = _remember(daemon, text="Accountant is Wanjiru")["fact_id"]
    try:
        reply, via, receipt = asyncio.run(
            daemon._run_intent(route("forget Wanjiru")))
        assert receipt["receipt"] == "forget"
        assert via == "local-intent"
        assert f"#{fid}" in reply

        reply, _via, receipt = asyncio.run(
            daemon._run_intent(route("forget nothing like this exists")))
        assert receipt["fact_ids"] == []
        assert "Nothing matched" in reply
        assert "Forgotten" not in reply      # no count and no ids are claimed
    finally:
        store.close()


def test_other_intents_carry_no_receipt(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        _reply, via, receipt = asyncio.run(daemon._run_intent(route("queue status")))
        assert via == "local-intent"
        assert receipt is None
    finally:
        store.close()


# ------------- clause 9: additive only — old keys keep their types, no new RPC
def test_pre_existing_keys_keep_their_types(tmp_path):
    store, memory = _memory(tmp_path)
    daemon = _daemon(store, memory)
    try:
        remembered = _remember(daemon, text="Accountant is Wanjiru")
        assert isinstance(remembered["fact_id"], int)
        assert isinstance(remembered["stored"], str)

        forgotten = _forget(daemon, topic="Wanjiru")
        assert isinstance(forgotten["forgotten"], int)
        # cli.py reads `forgotten` and prints it; it never sees these keys.
        assert {"fact_ids", "facts", "corr_id", "corr_ts", "declared"} <= set(forgotten)
    finally:
        store.close()


def test_no_new_rpc_was_added_to_reconstruct_these_fields():
    daemon = object.__new__(Daemon)
    methods = set(daemon._handlers())
    # The seven seams are producer fields, not queries.
    assert not [m for m in methods
                if any(word in m for word in ("receipt", "corr", "attribut"))]
    assert {"memory.remember", "memory.forget"} <= methods
