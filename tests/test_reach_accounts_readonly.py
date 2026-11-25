"""Eye-check 5: Accounts are strictly read-only by absence."""

from __future__ import annotations

import pytest

from assistant import reach
from assistant.reach import AccountRegistry, ReachAccount

FORBIDDEN_WRITE_VERBS = ("post", "send", "reply", "like", "follow", "dm", "publish", "delete", "edit")


def test_account_registry_is_read_only():
    reg = AccountRegistry()
    acc = ReachAccount(account_id="acc-1", platform="rss", handle="elaria-reader")
    reg.register(acc)
    assert reg.get("acc-1") == acc
    assert reg.list_accounts() == [acc]

    with pytest.raises(ValueError):
        ReachAccount(account_id="acc-2", platform="x", handle="elaria", read_only=False)


def test_no_write_verbs_exposed_on_reach_or_registry():
    for verb in FORBIDDEN_WRITE_VERBS:
        assert not hasattr(reach, verb), f"reach must not expose write verb {verb!r}"
        assert not hasattr(AccountRegistry, verb), f"AccountRegistry must not expose {verb!r}"
