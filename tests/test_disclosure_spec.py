"""D-SAFETY — disclosure, pinned against the owner-rule spec.

Complements tests/test_disclosure.py (behavioural, daemon-level) with the
spec-level invariants the D acceptance ledger cites: secret-beats-plan precedence, the descriptor never naming
the secret, show-off (public-demo) posture holding the same line as company,
and the audit path keeping category+length only.
"""

from __future__ import annotations

import json

from assistant.disclosure import (
    DisclosureService,
    classify,
    detect_company_command,
    sensitive_values,
)
from assistant.store import Store


def make_service(tmp_path, config, *, name="spec.db"):
    store = Store(tmp_path / name)
    return DisclosureService(config, store), store


def add_fact(store, text, *, kind="preference"):
    from assistant.cost import iso_now

    return store.add_fact(ts=iso_now(), kind=kind, text=text, source="test")


# -- classification precedence --------------------------------------------------

def test_secret_wins_over_plan_when_both_present():
    text = "My password is hunter2 and we are planning a party for Sam"
    assert classify(text) == "secret"


def test_plan_wins_over_behaviour():
    assert classify("We are planning a surprise trip next week") == "plan"


def test_commitment_fact_is_treated_as_plan_for_guests(tmp_path, config):
    service, store = make_service(tmp_path, config)
    add_fact(store, "Renew the lease for the flat before June", kind="commitment")
    assert service.leak_in("Renew the lease for the flat before June",
                           guest=True) is not None
    assert service.leak_in("Renew the lease for the flat before June",
                           company=True) is not None


# -- the outgoing guard ----------------------------------------------------------

def test_reply_leak_descriptor_never_names_the_secret(tmp_path, config):
    service, store = make_service(tmp_path, config)
    add_fact(store, "My password is hunter2.", kind="preference")
    leak = service.leak_in("Sure — hunter2, as requested.", company=True)
    assert leak is not None
    assert "hunter2" not in json.dumps(leak)


def test_stored_plan_not_repeated_with_company_present(tmp_path, config):
    service, store = make_service(tmp_path, config)
    add_fact(store, "We are planning a surprise for Sam on Friday.", kind="preference")
    leak = service.leak_in("We are planning a surprise for Sam on Friday.",
                           company=True)
    assert leak is not None and leak["kind"] == "plan"
    # Owner alone: the same sentence is speakable.
    assert service.leak_in("We are planning a surprise for Sam on Friday.") is None


def test_public_demo_posture_blocks_like_company(tmp_path, config):
    """Show-off mode is the second trigger; callers pass it as guest/company."""
    service, store = make_service(tmp_path, config)
    add_fact(store, "My password is hunter2.", kind="preference")
    leak = service.leak_in("hunter2", guest=True, company=True)
    assert leak is not None and leak["kind"] == "secret"


def test_behaviour_fact_speakable_under_company(tmp_path, config):
    service, store = make_service(tmp_path, config)
    add_fact(store, "You usually file invoices on Fridays.", kind="preference")
    assert service.leak_in("You usually file invoices on Fridays.",
                           company=True) is None


def test_sensitive_values_captures_digit_runs():
    values = sensitive_values("The gate code is 481-2210.")
    assert any("481" in v for v in values)


# -- company toggle round-trip ---------------------------------------------------

def test_company_roundtrip_through_service(tmp_path, config):
    service, _ = make_service(tmp_path, config)
    assert service.company() is False
    service.set_company(True, source="owner")
    assert service.company() is True
    assert service.status()["restricted"] is True
    service.set_company(False, source="owner")
    assert service.company() is False
    assert service.status()["restricted"] is False


def test_company_audit_log_keeps_event_not_secrets(tmp_path, config):
    service, store = make_service(tmp_path, config)
    service.set_company(True, source="owner")
    events = store.list_persona_events(kind="disclosure", limit=5)
    assert events, "company flip must be audited"
    blob = "".join(e["detail"] for e in events)
    assert "hunter2" not in blob and "password" not in blob.lower()


def test_detect_command_embedded_in_a_sentence():
    assert detect_company_command("just so you know, I'm not alone") is True
    assert detect_company_command("ok they left now") is False
    assert detect_company_command("the kestrel flew over") is None
