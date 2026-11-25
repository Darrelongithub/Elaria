"""Eye-check 1: Journal-first ordering, failure abort, and crash reconciliation."""

from __future__ import annotations

import httpx

from assistant.reach import ReachConfig, TerminalOutcome, fetch, reconcile_outstanding
from assistant.safety_journal import JournalLog


def _public_resolver(_host: str, _port: int = 443) -> list[str]:
    return ["93.184.216.34"]


def test_journal_written_before_http_transport_runs(tmp_path):
    journal = JournalLog(tmp_path / "journal.jsonl")
    seen_outstanding_during_request: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        # At the moment the HTTP request runs, the action record MUST already be on disk.
        seen_outstanding_during_request.append(len(journal.outstanding()))
        return httpx.Response(200, headers={"content-type": "text/plain"}, text="hello world")

    res = fetch(
        "https://example.com/page",
        journal=journal,
        config=ReachConfig(enabled=True),
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )
    assert res.ok is True
    assert res.terminal == TerminalOutcome.OK
    assert seen_outstanding_during_request == [1]
    assert journal.outstanding() == []
    assert journal.verify()["ok"] is True


def test_journal_failure_aborts_before_socket_opens(tmp_path):
    class BrokenJournal(JournalLog):
        def begin(self, *args, **kwargs):
            raise OSError("disk full")

    journal = BrokenJournal(tmp_path / "journal.jsonl")
    transport_called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal transport_called
        transport_called = True
        return httpx.Response(200, text="should not happen")

    res = fetch(
        "https://example.com/page",
        journal=journal,
        config=ReachConfig(enabled=True),
        resolver=_public_resolver,
        transport=httpx.MockTransport(handler),
    )
    assert res.ok is False
    assert res.terminal == TerminalOutcome.JOURNAL_FAILED
    assert transport_called is False


def test_reconcile_outstanding_closes_crashed_reach_request(tmp_path):
    journal = JournalLog(tmp_path / "journal.jsonl")
    journal.begin(actor="reach", action="reach.request", target="https://example.com/crashed")
    assert len(journal.outstanding()) == 1

    closed = reconcile_outstanding(journal)
    assert len(closed) == 1
    assert closed[0]["detail"]["terminal"] == "INTERRUPTED"
    assert journal.outstanding() == []
    assert journal.verify()["ok"] is True
