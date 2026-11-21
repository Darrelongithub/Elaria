"""P · HANDS-HEADLESS — consent-removed flow: act-first/journal-after.

Build step 4 of P-HEADLESS.md: consent is REMOVED, so actions run first and
are journaled after. ``deny-beats-consent`` survives the removal — a policy
denial preempts the act regardless of any consent token, and the denial itself
is recorded. Failure messages are legible, not mysterious (failure ask 48).

The journal interface here is the seam HR-P-2 files to Z for wiring to D's
real journal; until it lands, the in-memory and JSONL journals below are the
default implementations.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


class Journal(Protocol):
    """Sink for action/observation/denial records."""

    def record(self, kind: str, **fields: object) -> None: ...


class InMemoryJournal:
    """Default journal: keeps every record in a list (tests + substrate)."""

    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    def record(self, kind: str, **fields: object) -> None:
        self.rows.append({"kind": kind, **fields})

    def kinds(self) -> list[str]:
        return [row["kind"] for row in self.rows]  # type: ignore[misc]


class JsonlJournal:
    """Append-only JSONL journal on disk; one JSON object per line."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def record(self, kind: str, **fields: object) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"kind": kind, **fields}, sort_keys=True)
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


class Denied(RuntimeError):
    """A policy denial. Deny-beats-consent: recorded, never performed."""


class _AllowAll:
    """Default policy: nothing denied (the contract is the gatekeeper)."""

    def check(self, action: dict[str, object]) -> None:
        return None


class Policy(Protocol):
    """Governance gate. ``check`` raises ``Denied`` to preempt an action."""

    def check(self, action: dict[str, object]) -> None: ...


class ConsentFlow:
    """Consent-removed execution flow with deny-beats-consent precedence."""

    def __init__(self, journal: Journal, policy: Policy | None = None) -> None:
        self._journal = journal
        self._policy = policy or _AllowAll()

    def perform(
        self,
        action: dict[str, object],
        operate,
        observe=None,
    ):
        """Run ``operate`` act-first, journal action+observation after.

        A policy denial is journaled and raised WITHOUT performing the act,
        whatever consent token the caller might have attached — deny beats
        consent. If the act itself fails, the failure is journaled as an
        observation and re-raised with its original exception.
        """
        try:
            self._policy.check(action)
        except Denied as exc:
            self._journal.record("denial", action=action, reason=str(exc))
            raise
        try:
            result = operate()  # act-first
        except Exception as exc:
            self._journal.record("observation", action=action, error=str(exc), performed=True)
            raise
        self._journal.record("action", **action)  # journal-after
        observation = observe(result) if observe is not None else {"result": "ok"}
        self._journal.record("observation", action=action, **observation)
        return result
