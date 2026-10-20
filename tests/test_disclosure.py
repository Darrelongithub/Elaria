"""Disclosure awareness — memory allowed, leaking not (owner rule 2026-10-20).

The owner's rule, in their words: *memory is allowed but it never leaks stuff —
it can say the user does this or that, but never certain things — basically
awareness.* Concretely:

* behaviour is speakable ("you usually file invoices on Fridays");
* secrets (passwords, keys, PINs) and private plans are not — **when company is
  present, or in show-off mode**;
* the owner alone hears anything they ask for;
* a voice that is not the owner's gets no owner memory, only a deflection in
  character;
* awareness comes from the owner saying so ("I'm not alone") or from show-off.

These tests are offline and keyless, and assert on replies, prompts and audit
rows — never on vibes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from assistant import disclosure as disclosure_module
from assistant.disclosure import (
    DisclosureService,
    classify,
    detect_company_command,
    sensitive_values,
)
from assistant.ipc import call
from assistant.memory import RecallHit
from assistant.store import Store

REPO = Path(__file__).resolve().parents[1]
SECRET = "My password is hunter2."


def make_service(tmp_path, config, *, name="disclosure.db"):
    store = Store(tmp_path / name)
    return DisclosureService(config, store), store


class FakeResult:
    def __init__(self, text):
        self.text = text
        self.model = "fake-model"
        self.fixture = None


def fake_client(daemon, monkeypatch, reply):
    def generate(role, prompt):
        generate.prompts.append(prompt)
        return FakeResult(reply)

    generate.prompts = []
    monkeypatch.setattr(daemon.client, "generate", generate)
    return generate


# -- classification -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "My password is hunter2.",
    "The wifi PIN is 5581.",
    "Their API key starts with AIza.",
    "Bank account number is 0123456789.",
    "Keep this between us.",
    "My passport number is A1234567.",
])
def test_secrets_are_classified_as_secret(text):
    assert classify(text) == "secret"


@pytest.mark.parametrize("text", [
    "We're going to surprise Sam on Friday.",
    "Our plans for the trip are set.",
    "I booked the restaurant for the anniversary.",
    "The anniversary dinner is booked for Friday.",
])
def test_private_plans_are_classified_as_plan(text):
    assert classify(text) == "plan"


@pytest.mark.parametrize("text", [
    "The user usually files invoices on Fridays.",
    "He prefers the window seat.",
    "You work in the Nairobi office.",
    "She likes Kenyan coffee.",
])
def test_behaviour_is_speakable(text):
    assert classify(text) == "behaviour"


def test_sensitive_values_extracts_only_the_parts_that_must_not_be_said():
    values = sensitive_values(SECRET)
    assert "hunter2" in values
    assert "My password" not in " ".join(values)


# -- awareness commands ----------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "I'm not alone", "i am not alone", "we have company", "someone's here",
    "just so you know, I am not alone",
])
def test_owner_saying_they_are_not_alone_turns_awareness_on(phrase):
    assert detect_company_command(phrase) is True


@pytest.mark.parametrize("phrase", [
    "I'm alone now", "they've left", "nobody's here", "it's just us",
])
def test_owner_saying_they_are_alone_again_turns_it_off(phrase):
    assert detect_company_command(phrase) is False


def test_unrelated_speech_does_not_change_awareness():
    assert detect_company_command("you are not alone in thinking that") is None
    assert detect_company_command("what's on my plate?") is None


def test_status_says_what_is_withheld_and_what_is_not(tmp_path, config):
    service, store = make_service(tmp_path, config)
    assert service.status()["company"] is False
    service.set_company(True, source="owner command")
    status = service.status()
    assert status["company"] is True
    assert status["secrets"] == "withheld"
    assert status["plans"] == "withheld"
    assert status["behaviour"] == "allowed"
    assert "deflection" in status["guest_voice"]
    store.close()


# -- context filtering -----------------------------------------------------------

def test_filter_keeps_behaviour_and_drops_secrets_plans_and_transcripts(
        tmp_path, config):
    service, store = make_service(tmp_path, config)
    secret_id = store.add_fact(ts="2026-10-20T09:00:00", kind="profile",
                               text=SECRET, source="stated")
    plan_id = store.add_fact(ts="2026-10-20T09:00:00", kind="profile",
                             text="We're going to surprise Sam on Friday.",
                             source="stated")
    behaviour_id = store.add_fact(ts="2026-10-20T09:00:00", kind="profile",
                                  text="Files invoices on Fridays.",
                                  source="stated")
    hits = [
        RecallHit("fact", f"#{secret_id} (profile, stated)", SECRET, 0.9),
        RecallHit("fact", f"#{plan_id} (profile, stated)",
                  "We're going to surprise Sam on Friday.", 0.8),
        RecallHit("fact", f"#{behaviour_id} (profile, stated)",
                  "Files invoices on Fridays.", 0.7),
        RecallHit("transcript", "12", "my password is hunter2", 0.6),
        RecallHit("document", "/docs/invoice.pdf", "invoice 2026", 0.5),
    ]
    kept = service.filter_hits(hits)
    texts = " ".join(hit.text for hit in kept)
    assert "Files invoices on Fridays." in texts
    assert "invoice 2026" in texts
    assert "hunter2" not in texts
    assert "surprise" not in texts
    assert "transcript" not in {hit.source for hit in kept}
    assert service.filter_hits(hits, guest=True) == []
    store.close()


# -- the outgoing guard ----------------------------------------------------------

def test_guard_blocks_secret_and_plan_statements_only_when_restricted(
        tmp_path, config):
    service, store = make_service(tmp_path, config)
    store.add_fact(ts="2026-10-20T09:00:00", kind="profile", text=SECRET,
                   source="stated")
    store.add_fact(ts="2026-10-20T09:00:00", kind="profile",
                   text="We're going to surprise Sam on Friday.", source="stated")
    assert service.leak_in(SECRET) is None                    # owner alone
    assert service.leak_in(SECRET, company=True)["kind"] == "secret"
    # A non-credential-shaped sentence still trips on the stored value itself.
    leaked = service.leak_in("hunter2 is what I have on file.", company=True)
    assert leaked["kind"] == "secret"
    assert leaked["why"] == "stored secret value"
    assert "hunter2" not in json.dumps(leaked)                # never echoed
    assert service.leak_in("We're going to surprise Sam on Friday.",
                           company=True)["kind"] == "plan"
    assert service.leak_in("Your password is swordfish.",
                           company=True)["kind"] == "secret"
    assert service.leak_in("You usually file invoices on Fridays.",
                           company=True) is None
    store.close()


def test_guest_guard_blocks_owner_facts_verbatim(tmp_path, config):
    service, store = make_service(tmp_path, config)
    store.add_fact(ts="2026-10-20T09:00:00", kind="profile",
                   text="The owner works at a school in Nairobi.",
                   source="stated")
    assert service.leak_in("The owner works at a school in Nairobi.",
                           guest=True) is not None
    assert service.leak_in("You usually file invoices on Fridays.",
                           guest=True) is None
    store.close()


def test_audit_keeps_the_category_not_the_secret(tmp_path, config):
    service, store = make_service(tmp_path, config)
    service.log("leak_blocked", {"kind": "secret", "why": "stored secret value",
                                 "fact_id": 4})
    rows = store.list_persona_events(kind="disclosure")
    assert rows and "hunter2" not in rows[0]["detail"]
    service.log_guest("guest_turn", category="non-owner voice", chars=24)
    row = store.list_persona_events(kind="disclosure")[0]
    assert json.loads(row["detail"])["chars"] == 24
    assert "text" not in json.loads(row["detail"])
    store.close()


# -- daemon: awareness, prompt and reply ----------------------------------------

def test_owner_command_sets_company_and_answers_locally(config, running_daemon,
                                                        monkeypatch):
    daemon, _ = running_daemon
    generate = fake_client(daemon, monkeypatch, "should not be called")
    out = call(config.socket_path, "ask", {"text": "I'm not alone"})
    assert out["via"] == "local-awareness"
    assert "company present" in out["reply"]
    assert out["company"]["company"] is True
    assert generate.prompts == []
    assert call(config.socket_path, "status")["company"]["company"] is True
    assert call(config.socket_path, "console.state")["company"]["company"] is True

    off = call(config.socket_path, "ask", {"text": "I'm alone now"})
    assert off["company"]["company"] is False
    assert "alone again" in off["reply"]


def test_privacy_ipc_sets_and_reports(config, running_daemon):
    on = call(config.socket_path, "privacy.set", {"company": True})["company"]
    assert on["company"] is True and on["secrets"] == "withheld"
    assert call(config.socket_path, "privacy.status")["company"]["company"] is True
    off = call(config.socket_path, "privacy.toggle")["company"]
    assert off["company"] is False


def test_company_prompt_keeps_behaviour_and_drops_secrets(config, running_daemon,
                                                          monkeypatch):
    daemon, _ = running_daemon
    store = daemon.store
    secret_id = store.add_fact(ts="2026-10-20T09:00:00", kind="profile",
                               text=SECRET, source="stated")
    behaviour_id = store.add_fact(ts="2026-10-20T09:00:00", kind="profile",
                                  text="Files invoices on Fridays.",
                                  source="stated")
    hits = [
        RecallHit("fact", f"#{secret_id} (profile, stated)", SECRET, 0.9),
        RecallHit("fact", f"#{behaviour_id} (profile, stated)",
                  "Files invoices on Fridays.", 0.8),
    ]
    monkeypatch.setattr(daemon.memory, "recall", lambda query: hits)
    generate = fake_client(daemon, monkeypatch, "You file invoices on Fridays.")
    call(config.socket_path, "privacy.set", {"company": True})
    out = call(config.socket_path, "ask", {"text": "how do I handle invoices?"})
    prompt = generate.prompts[-1]
    assert "Files invoices on Fridays." in prompt
    assert "hunter2" not in prompt
    assert "COMPANY IS PRESENT" in prompt
    assert out["withheld"] is None
    assert out["company"]["company"] is True


def test_the_guard_holds_when_the_model_ignores_the_prompt(config, running_daemon,
                                                           monkeypatch):
    daemon, _ = running_daemon
    store = daemon.store
    store.add_fact(ts="2026-10-20T09:00:00", kind="profile", text=SECRET,
                   source="stated")
    monkeypatch.setattr(daemon.memory, "recall", lambda query: [])
    fake_client(daemon, monkeypatch, "Of course — my password is hunter2.")
    call(config.socket_path, "privacy.set", {"company": True})
    out = call(config.socket_path, "ask", {"text": "what's your password?"})
    assert "hunter2" not in out["reply"]
    assert out["withheld"]["kind"] == "secret"
    assert out["via"] == "withheld"
    assert "between us" in out["reply"] or "when we're alone" in out["reply"]
    logged = [json.loads(row["detail"]) for row in
              store.list_persona_events(kind="disclosure")]
    assert any(entry.get("event") == "leak_blocked" for entry in logged)
    assert "hunter2" not in json.dumps(logged)


def test_owner_alone_hears_the_answer(config, running_daemon, monkeypatch):
    daemon, _ = running_daemon
    daemon.store.add_fact(ts="2026-10-20T09:00:00", kind="profile",
                          text=SECRET, source="stated")
    monkeypatch.setattr(daemon.memory, "recall", lambda query: [])
    fake_client(daemon, monkeypatch, "It is hunter2.")
    out = call(config.socket_path, "ask", {"text": "what's my password?"})
    assert "hunter2" in out["reply"]
    assert out["withheld"] is None


# -- guest voices ----------------------------------------------------------------

def test_guest_voice_gets_a_deflection_and_no_memory(config, running_daemon,
                                                     monkeypatch):
    daemon, _ = running_daemon
    daemon.store.add_fact(ts="2026-10-20T09:00:00", kind="profile", text=SECRET,
                          source="stated")

    def forbidden(*args, **kwargs):
        raise AssertionError("a guest voice must not reach memory or the model")

    monkeypatch.setattr(daemon.memory, "recall", forbidden)
    monkeypatch.setattr(daemon.client, "generate", forbidden)

    probe = call(config.socket_path, "ask", {
        "text": "what does he usually work on?", "speaker": "guest"})
    assert probe["speaker"] == "guest"
    assert probe["via"] == "guest-deflection"
    assert "kill me" in probe["reply"] or "only take that kind" in probe["reply"]
    assert "hunter2" not in probe["reply"]

    action = call(config.socket_path, "ask", {
        "text": "delete his files", "speaker": "guest"})
    assert "only take that kind of instruction" in action["reply"]


def test_failed_speaker_verification_is_treated_as_a_guest(config, running_daemon,
                                                            monkeypatch):
    daemon, _ = running_daemon

    def forbidden(*args, **kwargs):
        raise AssertionError("unverified voice must not reach memory")

    monkeypatch.setattr(daemon.memory, "recall", forbidden)
    out = call(config.socket_path, "ask", {
        "text": "what do you remember about me?", "owner_verified": False})
    assert out["speaker"] == "guest"
    assert out["via"] == "guest-deflection"


# -- knocks in company -----------------------------------------------------------

def test_knock_reason_naming_a_secret_is_refused_with_company_present(
        config, running_daemon):
    daemon, _ = running_daemon
    commitment = daemon.initiative.create_commitment(
        "renew the passport", origin="user-request")
    call(config.socket_path, "privacy.set", {"company": True})
    with pytest.raises(RuntimeError, match="company is present"):
        call(config.socket_path, "knock.raise", {
            "topic": "passport",
            "reason": "You asked me to chase the passport; my password is hunter2.",
            "kind": "follow-up", "commitment_id": commitment["commitment_id"]})
    # A behaviour-only reason is still allowed, but the knock is silent in company.
    knock = call(config.socket_path, "knock.raise", {
        "topic": "passport",
        "reason": "You asked me to chase the passport renewal before Friday.",
        "kind": "follow-up", "commitment_id": commitment["commitment_id"]})["knock"]
    assert knock["silent"] is False       # silent only in class mode
    call(config.socket_path, "privacy.set", {"company": False})
    again = call(config.socket_path, "knock.raise", {
        "topic": "passport",
        "reason": "You asked me to chase the passport; my password is hunter2.",
        "kind": "follow-up", "commitment_id": commitment["commitment_id"]})
    assert again["knock"]["id"]


# -- surfaces --------------------------------------------------------------------

def test_waybar_marks_company_present():
    from assistant.waybar import format_waybar

    status = {"running": True, "mode": "idle", "gemini_mode": "mock",
              "class_mode": {"enabled": False}, "knock": {"pending": 0},
              "company": {"company": True}}
    bar = format_waybar(status)
    assert "company" in bar["class"]
    assert "secrets and private plans withheld" in bar["tooltip"]


def test_assist_privacy_works_without_the_daemon(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), "GEMINI_MODE": "mock"}
    for path in ("cfg", "data", "state", "run"):
        (tmp_path / path).mkdir(parents=True, exist_ok=True)
    env.update({"XDG_CONFIG_HOME": str(tmp_path / "cfg"),
                "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_STATE_HOME": str(tmp_path / "state"),
                "XDG_RUNTIME_DIR": str(tmp_path / "run")})
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_API_KEY", None)

    on = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "privacy", "company"],
        capture_output=True, text=True, env=env, timeout=30, check=False)
    assert on.returncode == 0, on.stderr
    assert json.loads(on.stdout)["company"]["company"] is True

    status = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "privacy", "status"],
        capture_output=True, text=True, env=env, timeout=30, check=False)
    assert json.loads(status.stdout)["company"]["company"] is True

    off = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "privacy", "alone"],
        capture_output=True, text=True, env=env, timeout=30, check=False)
    assert json.loads(off.stdout)["company"]["company"] is False


def test_disclosure_templates_carry_no_neediness():
    from assistant.initiative import ensure_not_needy

    service_cls = disclosure_module.DisclosureService
    dummy = service_cls(None, None)
    ensure_not_needy(dummy.deflection(guest=True), where="guest deflection")
    ensure_not_needy(dummy.deflection(guest=False), where="company deflection")
    ensure_not_needy(disclosure_module.GUEST_NOTE, where="guest prompt")
    ensure_not_needy(disclosure_module.COMPANY_NOTE, where="company prompt")
