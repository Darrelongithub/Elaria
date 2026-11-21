"""P · HANDS-HEADLESS — consent-removed flow tests (act-first/journal-after)."""

from __future__ import annotations

import pytest

from assistant.hands.headless.consent import ConsentFlow, Denied, InMemoryJournal


class _DenyAll:
    def check(self, action):
        raise Denied(f"policy denies verb {action.get('verb')!r}")


class _DenyNothing:
    def check(self, action):
        return None


def test_allowed_action_journals_action_and_observation():
    journal = InMemoryJournal()
    flow = ConsentFlow(journal, policy=_DenyNothing())
    calls = []

    def operate():
        calls.append(True)
        return "result"

    result = flow.perform({"verb": "ls"}, operate, observe=lambda r: {"value": r})
    assert result == "result"
    assert calls == [True]
    assert journal.kinds() == ["action", "observation"]
    assert journal.rows[0]["verb"] == "ls"
    assert journal.rows[1]["value"] == "result"


def test_denial_beats_consent_and_is_journaled():
    journal = InMemoryJournal()
    flow = ConsentFlow(journal, policy=_DenyAll())
    calls = []

    with pytest.raises(Denied) as excinfo:
        flow.perform({"verb": "send-text"}, lambda: calls.append(True))

    assert calls == []  # the act was never performed
    assert journal.kinds() == ["denial"]
    row = journal.rows[0]
    assert row["action"] == {"verb": "send-text"}
    assert "send-text" in row["reason"]
    assert "send-text" in str(excinfo.value)


def test_denial_message_is_legible():
    journal = InMemoryJournal()
    flow = ConsentFlow(journal, policy=_DenyAll())
    with pytest.raises(Denied) as excinfo:
        flow.perform({"verb": "get-text"}, lambda: None)
    message = str(excinfo.value)
    assert "denies" in message
    assert "get-text" in message


def test_act_failure_is_journaled_then_reraised():
    journal = InMemoryJournal()
    flow = ConsentFlow(journal, policy=_DenyNothing())

    def operate():
        raise RuntimeError("remote call failed")

    with pytest.raises(RuntimeError, match="remote call failed"):
        flow.perform({"verb": "ls"}, operate)
    assert journal.kinds() == ["observation"]
    assert "remote call failed" in str(journal.rows[0]["error"])
    assert journal.rows[0]["performed"] is True
