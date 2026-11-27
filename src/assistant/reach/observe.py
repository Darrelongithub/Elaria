"""Journal-first observation for REACH (built on ``safety_journal.JournalLog``).

Every request writes an fsynced ``action`` record BEFORE the socket opens.
If the journal write fails, no request is made (``JOURNAL_FAILED``).
Untrusted content is recorded via ``note_untrusted_input`` with hashes and
byte counts only — never content bytes.
"""

from __future__ import annotations

from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

from ..safety_journal import (
    OUTCOME_FAILED,
    OUTCOME_OK,
    OUTCOME_REFUSED,
    JournalLog,
)
from .contract import FetchedDoc, ReachError, TerminalOutcome


def journal_target(url: str) -> str | None:
    # Do not persist credentials, query tokens or fragments from owner URLs.
    try:
        parts = urlsplit(url)
        if parts.hostname:
            return urlunsplit((parts.scheme, parts.hostname, parts.path, "", ""))[:2048]
    except ValueError:
        pass
    return None


def begin_fetch(
    journal: JournalLog,
    *,
    url: str | None,
    channel: str,
    method: str,
    correlation_id: str | None = None,
    detail: dict | None = None,
) -> str:
    """Write the write-ahead ``reach.request`` action record before any socket opens."""
    payload = {"channel": channel, "method": method}
    if detail:
        payload.update(detail)
    try:
        return journal.begin(
            actor="reach",
            action="reach.request",
            target=url,
            correlation_id=correlation_id,
            consent_present=True,
            consent_via="reach.policy",
            detail=payload,
        )
    except Exception as exc:
        raise ReachError(
            TerminalOutcome.JOURNAL_FAILED,
            "could not record request intent",
        ) from exc


def finish_fetch(
    journal: JournalLog,
    action_id: str,
    *,
    terminal: TerminalOutcome,
    detail: dict | None = None,
) -> dict:
    """Write the single observation record for ``action_id``."""
    if terminal == TerminalOutcome.OK:
        outcome = OUTCOME_OK
    elif terminal in (
        TerminalOutcome.DENIED,
        TerminalOutcome.ROBOTS_DISALLOWED,
        TerminalOutcome.PLATFORM_BLOCKED,
        TerminalOutcome.NEED_LOGIN,
        TerminalOutcome.RATE_LIMITED,
    ):
        outcome = OUTCOME_REFUSED
    else:
        outcome = OUTCOME_FAILED
    payload = {"terminal": terminal.value}
    if detail:
        payload.update(detail)
    return journal.observe(action_id, outcome, actor="reach", detail=payload)


def record_untrusted_load(
    journal: JournalLog,
    doc: FetchedDoc,
    *,
    origin: str = "web",
    correlation_id: str | None = None,
) -> str:
    """Journal that untrusted web content was seen (hashes/lengths only, never bytes)."""
    return journal.note_untrusted_input(
        journal_target(doc.final_url) or "web",
        actor="reach",
        correlation_id=correlation_id,
        detail={
            "origin": origin,
            "channel": doc.channel,
            "sha256": doc.sha256,
            "bytes": len(doc.text.encode("utf-8")),
        },
    )


def is_request_action(row: dict) -> bool:
    return (row["kind"], row.get("actor"), row.get("action")) == ("action", "reach", "reach.request")


def request_actions(journal: JournalLog) -> Iterator[dict]:
    return (row for row in journal.records() if is_request_action(row))


def reconcile_outstanding(journal: JournalLog) -> list[dict]:
    """Close any crashed mid-flight ``reach.request`` actions in the journal."""
    reconciled: list[dict] = []
    for action in journal.outstanding():
        if action.get("actor") == "reach" and action.get("action") == "reach.request":
            obs = journal.observe(
                action["id"],
                OUTCOME_FAILED,
                actor="reach",
                detail={"terminal": "INTERRUPTED", "reconciled": True},
            )
            reconciled.append(obs)
    return reconciled
