"""REACH account registry — read-only by absence.

No write verbs (post, send, reply, like, follow, dm, publish, delete, edit)
exist anywhere in ``assistant.reach``. Accounts registered here may only be
used for reading.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReachAccount:
    """A read-only external identity held by Elaria (never the owner)."""

    account_id: str
    platform: str
    handle: str
    read_only: bool = True

    def __post_init__(self):
        if not self.read_only:
            raise ValueError("REACH accounts are strictly read-only in Phase 0")
        if not str(self.account_id).strip() or not str(self.platform).strip():
            raise ValueError("account_id and platform must be non-empty")


class AccountRegistry:
    """In-memory registry of read-only REACH accounts."""

    def __init__(self):
        self._accounts: dict[str, ReachAccount] = {}

    def register(self, account: ReachAccount) -> ReachAccount:
        if not account.read_only:
            raise ValueError("cannot register a writable account in REACH")
        self._accounts[account.account_id] = account
        return account

    def get(self, account_id: str) -> ReachAccount | None:
        return self._accounts.get(account_id)

    def list_accounts(self) -> list[ReachAccount]:
        return list(self._accounts.values())
