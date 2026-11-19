"""P · HANDS-HEADLESS — worker contract tests (three verbs, extent subset)."""

from __future__ import annotations

import pytest

from assistant.hands.headless.contract import (
    ALLOWED_VERBS,
    DEFAULT_EXTENT_SUBSET,
    ContractViolationError,
    WorkerContract,
)


def test_only_three_verbs_are_reachable():
    contract = WorkerContract()
    assert contract.allows("ls")
    assert contract.allows("get-text")
    assert contract.allows("send-text")
    assert not contract.allows("screenshot")
    assert not contract.allows("ls-all")
    assert not contract.allows("get-text-all")
    assert set(contract.verbs) == set(ALLOWED_VERBS)


@pytest.mark.parametrize("extent", ["viewport", "all"])
def test_get_text_accepts_assessed_extent(extent):
    WorkerContract().check_request("get-text", {"extent": extent})


@pytest.mark.parametrize("extent", ["alternate", "alternate_scrollback"])
def test_get_text_refuses_0492_extent_additions(extent):
    contract = WorkerContract()
    with pytest.raises(ContractViolationError) as excinfo:
        contract.check_request("get-text", {"extent": extent})
    message = str(excinfo.value)
    assert extent in message
    assert "assessed subset" in message


def test_get_text_requires_extent():
    with pytest.raises(ContractViolationError) as excinfo:
        WorkerContract().check_request("get-text", {})
    assert "--extent" in str(excinfo.value)


def test_disallowed_option_refused():
    contract = WorkerContract()
    with pytest.raises(ContractViolationError) as excinfo:
        contract.check_request("ls", {"recursive": "1"})
    message = str(excinfo.value)
    assert "recursive" in message
    assert "not allowed" in message


def test_send_text_accepts_no_options():
    WorkerContract().check_request("send-text", {})


def test_unknown_verb_refused_legibly():
    with pytest.raises(ContractViolationError) as excinfo:
        WorkerContract().check_request("screenshot", {})
    message = str(excinfo.value)
    assert "screenshot" in message
    assert "ls" in message and "get-text" in message and "send-text" in message


def test_widening_extent_refused_at_construction():
    with pytest.raises(ContractViolationError) as excinfo:
        WorkerContract(extent_subset=DEFAULT_EXTENT_SUBSET | {"alternate"})
    assert "owner ruling" in str(excinfo.value)


def test_narrowing_extent_allowed_and_enforced():
    contract = WorkerContract(extent_subset=frozenset({"viewport"}))
    contract.check_request("get-text", {"extent": "viewport"})
    with pytest.raises(ContractViolationError):
        contract.check_request("get-text", {"extent": "all"})


def test_extra_verb_refused_at_construction():
    with pytest.raises(ContractViolationError) as excinfo:
        WorkerContract(verbs=ALLOWED_VERBS | {"screenshot"})
    assert "screenshot" in str(excinfo.value)


def test_empty_extent_subset_refused():
    with pytest.raises(ContractViolationError):
        WorkerContract(extent_subset=frozenset())
