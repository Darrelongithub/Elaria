"""Stage C — initiative / the knock (§19.2, as amended).

Offline and keyless. What is asserted here is the amendment itself:

* **No knock budget.** No counter, spacing rule or rate key exists, and many
  knocks in a row are all allowed. The reason gate is the only control.
* **Time is not a reason.** A knock that makes elapsed time the initiator is
  refused, and a snooze only fires when the *user's own commitment* is due.
* **Anti-psychosis, runtime-enforced.** Needy framing is refused in the reason
  and in every generated opener — not merely discouraged in a prompt.
* **Commitments are the user's.** A follow-up cannot cite an obligation she
  invented; `origin` is checked at creation.
* **The signal is hers alone.** `KnockSignal.emit` is reachable only from the
  knock handlers; errors, completions and system events never borrow it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from assistant import initiative as initiative_module
from assistant.config import DEFAULTS
from assistant.initiative import (
    CONSOLE_OPENER_PROMPT,
    INITIATIVE_PROMPT,
    KNOCK_OPENERS,
    InitiativeError,
    InitiativeService,
    KnockSignal,
    NeedinessError,
    ensure_not_needy,
    ensure_not_temporal,
    opener_for,
)
from assistant.ipc import call
from assistant.presence import PresenceService
from assistant.store import Store
from assistant.waybar import format_waybar

REPO = Path(__file__).resolve().parents[1]


def make_service(tmp_path, config, *, clock=None, name="knock.db"):
    store = Store(tmp_path / name)
    presence = PresenceService(config, store)
    service = InitiativeService(config, store, presence=presence, now=clock)
    return service, store, presence


def user_commitment(service, text="chase the tax office"):
    return service.create_commitment(text, origin="user-request")


# -- the reason gate ----------------------------------------------------------

def test_knock_without_a_reason_is_refused(tmp_path, config):
    service, store, _ = make_service(tmp_path, config)
    with pytest.raises(InitiativeError, match="citable reason"):
        service.raise_knock(topic="tax", reason="")
    with pytest.raises(InitiativeError, match="citable reason"):
        service.raise_knock(topic="tax", reason="   ")
    # The store refuses too, so no code path can insert a reasonless knock.
    with pytest.raises(ValueError, match="citable reason"):
        store.create_knock(ts="2026-10-20T09:00:00", topic="tax", reason=" ",
                           kind="finding")
    assert store.list_knocks() == []
    store.close()


def test_a_knock_always_carries_its_stored_reason_as_the_first_line(tmp_path, config):
    service, store, _ = make_service(tmp_path, config)
    commitment = user_commitment(service)
    reason = "You asked me to chase the tax office before Friday."
    knock = service.raise_knock(
        topic="tax office", reason=reason, kind="follow-up",
        commitment_id=commitment["commitment_id"])
    assert knock["reason"] == reason
    assert knock["first_line"] == reason
    assert store.get_knock(knock["id"])["reason"] == reason
    store.close()


def test_there_is_no_knock_budget(tmp_path, config):
    service, store, _ = make_service(tmp_path, config)
    for i in range(12):
        service.raise_knock(topic=f"topic {i}",
                            reason=f"While indexing folder {i}, I found a duplicate.",
                            kind="finding", referent=f"folder {i}")
    assert len(service.pending()) == 12          # no rationing, no spacing
    status = service.status()
    assert set(status) == {"pending", "latest", "budget",
                           "class_mode_urgent_only"}
    assert "none" in status["budget"]
    banned = ("per_day", "daily", "max_per", "rate", "quota", "budget",
              "cooldown", "spacing", "throttle")
    keys = DEFAULTS["initiative"].keys()
    assert [key for key in keys if any(token in key for token in banned)] == []
    store.close()


@pytest.mark.parametrize("reason", [
    "It's been three days since we spoke.",
    "It has been a while, so I thought I would check in.",
    "Long time no see — anything new?",
])
def test_time_passing_is_not_a_reason(tmp_path, config, reason):
    service, store, _ = make_service(tmp_path, config)
    # Some of these also trip the neediness lint ("been a while"); either way
    # the refusal is the point: time cannot be the initiator.
    with pytest.raises(InitiativeError):
        service.raise_knock(topic="anything", reason=reason, kind="checkin",
                            referent="the week")
    assert service.pending() == []
    store.close()


@pytest.mark.parametrize("reason", [
    "I miss you and wanted to check in.",
    "You haven't talked to me in days.",
    "I've been waiting for you.",
    "I get lonely when it's quiet.",
    "You're avoiding me, aren't you?",
    "Do you still care about me?",
])
def test_neediness_cannot_be_sent_at_all(tmp_path, config, reason):
    service, store, _ = make_service(tmp_path, config)
    with pytest.raises(NeedinessError):
        service.raise_knock(topic="feelings", reason=reason, kind="checkin",
                            referent="us")
    assert service.pending() == []
    store.close()


def test_every_opener_template_is_clean():
    for kind in KNOCK_OPENERS:
        line = opener_for(kind, topic="the tax form", referent="the tax form",
                          detail="the deadline moved")
        ensure_not_needy(line, where="knock opener")
        ensure_not_temporal(line, where="knock opener")
    # A model-supplied topic cannot smuggle neediness through a clean template.
    with pytest.raises(NeedinessError):
        opener_for("follow-up", topic="you haven't talked to me")


def test_generation_prompts_carry_the_prohibition():
    prompt = INITIATIVE_PROMPT.lower()
    for phrase in ("loneliness", "missing the user", "neglect",
                   "emotional need", "time passed", "stay silent"):
        assert phrase in prompt
    assert "no emotional framing" in CONSOLE_OPENER_PROMPT.lower()
    assert "no greeting before it" in CONSOLE_OPENER_PROMPT.lower()


# -- commitments are the user's ------------------------------------------------

def test_followup_requires_a_commitment_created_by_the_user(tmp_path, config):
    service, store, _ = make_service(tmp_path, config)
    with pytest.raises(InitiativeError, match="commitment"):
        service.raise_knock(topic="tax", reason="You asked me to chase the tax office.",
                            kind="follow-up")
    with pytest.raises(InitiativeError, match="cannot originate"):
        service.create_commitment("do her own idea", origin="her-invention")
    with pytest.raises(InitiativeError, match="does not exist"):
        service.raise_knock(topic="tax", reason="You asked me to chase the tax office.",
                            kind="follow-up", commitment_id=999)
    store.close()


@pytest.mark.parametrize("kind", ["finding", "checkin", "urgency"])
def test_other_kinds_need_a_concrete_referent(tmp_path, config, kind):
    service, store, _ = make_service(tmp_path, config)
    with pytest.raises(InitiativeError, match="concrete referent"):
        service.raise_knock(topic="something", reason="While working, I found a problem.",
                            kind=kind)
    store.close()


# -- decline / later / ignore ---------------------------------------------------

def test_decline_means_no_followup_on_that_topic(tmp_path, config):
    service, store, _ = make_service(tmp_path, config)
    first = service.raise_knock(topic="tax", reason="While indexing, I found a duplicate.",
                                kind="finding", referent="the tax folder")
    service.raise_knock(topic="tax", reason="The tax folder has a second duplicate.",
                        kind="finding", referent="the tax folder")
    result = service.decline(first["id"])
    assert result["no_followup"] is True
    assert all(k["status"] == "declined" for k in store.list_knocks("declined"))
    with pytest.raises(InitiativeError, match="declined"):
        service.raise_knock(topic="tax", reason="While indexing, I found a duplicate.",
                            kind="finding", referent="the tax folder")
    # A different topic is unaffected.
    other = service.raise_knock(topic="photos", reason="The photo import has 3 duplicates.",
                                kind="finding", referent="the photo import")
    assert other["status"] == "pending"
    store.close()


def test_later_snoozes_into_commitment_memory(tmp_path, config):
    now = {"at": datetime(2026, 10, 20, 9, 0)}
    service, store, _ = make_service(tmp_path, config, clock=lambda: now["at"])
    commitment = user_commitment(service)
    knock = service.raise_knock(
        topic="tax office", reason="You asked me to chase the tax office.",
        kind="follow-up", commitment_id=commitment["commitment_id"])
    snoozed = service.later(knock["id"], hours=24)
    assert snoozed["knock"]["status"] == "snoozed"
    assert snoozed["commitment"]["origin"] == "user-later"
    # "Later" is a promise: it cannot be re-raised on the same topic early.
    with pytest.raises(InitiativeError, match="snoozed"):
        service.raise_knock(topic="tax office",
                            reason="You asked me to chase the tax office.",
                            kind="follow-up",
                            commitment_id=commitment["commitment_id"])
    assert service.check_due() == []
    now["at"] += timedelta(hours=25)
    raised = service.check_due()
    assert len(raised) == 1
    assert "You asked me to chase" in raised[0]["reason"]
    # "Later" wrote its own commitment ("follow up with the user: …"); that is
    # the one the due knock cites. The original stays as the user's record.
    assert raised[0]["commitment_id"] == snoozed["commitment"]["commitment_id"]
    assert commitment["commitment_id"] in {
        f["id"] for f in store.list_facts(kind="commitment")}
    assert len(service.pending()) == 1
    store.close()


def test_three_ignores_retire_a_topic(tmp_path, config):
    service, store, _ = make_service(tmp_path, config)
    knock = service.raise_knock(topic="gym", reason="Your gym plan has an unpaid invoice.",
                                kind="finding", referent="the gym plan")
    for expected in (1, 2, 3):
        result = service.ignore(knock["id"])
        assert result["ignore_count"] == expected
        assert result["retired"] is (expected == 3)
    with pytest.raises(InitiativeError, match="retired"):
        service.raise_knock(topic="gym", reason="Your gym plan has an unpaid invoice.",
                            kind="finding", referent="the gym plan")
    store.close()


def test_raising_over_a_pending_knock_counts_as_ignoring_it(tmp_path, config):
    service, store, _ = make_service(tmp_path, config)
    first = service.raise_knock(topic="gym", reason="Your gym plan has an unpaid invoice.",
                                kind="finding", referent="the gym plan")
    service.raise_knock(topic="gym", reason="The gym invoice is now overdue.",
                        kind="finding", referent="the gym plan")
    assert store.get_knock(first["id"])["ignore_count"] == 1
    store.close()


# -- class mode ------------------------------------------------------------------

def test_class_mode_allows_only_urgent_knocks_and_they_do_not_speak(tmp_path, config):
    service, store, presence = make_service(tmp_path, config)
    presence.set_enabled(True)
    with pytest.raises(InitiativeError, match="urgent-only"):
        service.raise_knock(topic="photos", reason="The photo import has duplicates.",
                            kind="finding", referent="the photo import")
    urgent = service.raise_knock(topic="deadline",
                                 reason="The tax portal closes at midnight.",
                                 kind="urgency", urgency="urgent",
                                 referent="the tax portal")
    assert urgent["silent"] is True

    signal = KnockSignal(config, runner=lambda *a, **k: pytest.fail("must not play"))
    out = signal.emit(urgent, class_mode=True)
    assert out["signal"] == "visual-pulse"
    assert out["notification"] is False and out["sound"] is False
    store.close()


def test_the_knock_signal_has_its_own_identity_and_is_never_borrowed(config, monkeypatch):
    monkeypatch.setattr(initiative_module.shutil, "which",
                        lambda name: "/usr/bin/notify-send" if name == "notify-send" else None)
    calls: list[list[str]] = []
    signal = KnockSignal(config, runner=lambda argv, **kw: calls.append(argv))
    out = signal.emit({"reason": "You asked me to chase the tax office.",
                       "urgency": "normal"}, class_mode=False)
    assert out["notification"] is True
    assert calls and calls[0][0] == "notify-send"
    assert "-a" in calls[0] and "Elaria · knock" in calls[0]

    # The source makes abuse structural: `knock_signal.emit` exists only in the
    # two knock handlers, so no error/completion/system path can call it.
    source = (REPO / "src" / "assistant" / "daemon.py").read_text()
    owners, current = [], None
    for line in source.splitlines():
        match = re.match(r"    (?:async )?def (\w+)\(", line)
        if match:
            current = match.group(1)
        if "knock_signal.emit" in line:
            owners.append(current)
    assert sorted(owners) == ["_knock_due", "_knock_raise"]
    for path in (REPO / "src").rglob("*.py"):
        if path.name in ("initiative.py", "daemon.py"):
            continue
        assert "knock_signal.emit" not in path.read_text(), path

    # And `notify-send` in src/ is only the knock (voicetest is a separate
    # developer tool, never wired into the daemon's event path).
    for path in (REPO / "src" / "assistant").glob("*.py"):
        if path.name in ("voicetest.py", "cli.py"):
            continue
        text = path.read_text()
        if "notify-send" in text:
            assert path.name == "initiative.py", path


# -- surfaces --------------------------------------------------------------------

def test_waybar_knock_is_its_own_glyph_state():
    status = {"running": True, "mode": "idle", "gemini_mode": "mock",
              "class_mode": {"enabled": False},
              "knock": {"pending": 1}}
    loud = format_waybar(status)
    assert loud["text"].startswith("✦")
    assert "wants to talk" in loud["text"]
    assert "knock" in loud["class"] and "knock-loud" in loud["class"]
    assert "reason" in loud["tooltip"]

    status["class_mode"] = {"enabled": True}
    silent = format_waybar(status)
    assert "knock-silent" in silent["class"]
    assert "urgent-only" in silent["tooltip"]


def test_daemon_knock_opens_a_surface_with_the_reason_first(config, running_daemon):
    daemon, _ = running_daemon
    commitment = daemon.initiative.create_commitment(
        "chase the tax office", origin="user-request")
    reason = "You asked me to chase the tax office before Friday."
    raised = call(config.socket_path, "knock.raise", {
        "topic": "tax office", "reason": reason, "kind": "follow-up",
        "commitment_id": commitment["commitment_id"]})
    assert raised["knock"]["reason"] == reason
    assert raised["signal"]["signal"] in ("knock", "visual-pulse")

    status = call(config.socket_path, "status")
    assert status["knock"]["pending"] == 1
    assert "budget" in status["knock"] and "none" in status["knock"]["budget"]

    snapshot = call(config.socket_path, "console.state")
    assert [k["reason"] for k in snapshot["knocks"]] == [reason]

    accepted = call(config.socket_path, "knock.accept", {"id": raised["knock"]["id"]})
    assert accepted["open"] in ("console", "voice")
    assert accepted["first_line"] == reason
    messages = accepted["conversation"]["messages"]
    assert messages[-1]["text"] == reason
    assert messages[-1]["channel"] == accepted["open"]

    # The accepted turn is the same conversation the console already owns.
    turn = call(config.socket_path, "console.say", {"text": "tell me more"})
    assert turn["conversation_id"] == accepted["conversation_id"]


def test_daemon_class_mode_refuses_non_urgent_knocks(config, running_daemon):
    call(config.socket_path, "class.set", {"enabled": True})
    with pytest.raises(RuntimeError, match="urgent-only"):
        call(config.socket_path, "knock.raise", {
            "topic": "photos", "reason": "The photo import has duplicates.",
            "kind": "finding", "referent": "the photo import"})
    urgent = call(config.socket_path, "knock.raise", {
        "topic": "deadline", "reason": "The tax portal closes at midnight.",
        "kind": "urgency", "urgency": "urgent", "referent": "the tax portal"})
    assert urgent["knock"]["silent"] is True
    assert urgent["signal"]["notification"] is False
    accepted = call(config.socket_path, "knock.accept", {"id": urgent["knock"]["id"]})
    assert accepted["open"] == "console"
    assert accepted["first_line"] == "The tax portal closes at midnight."


def test_daemon_decline_blocks_the_topic(config, running_daemon):
    _daemon, _ = running_daemon
    first = call(config.socket_path, "knock.raise", {
        "topic": "gym", "reason": "The gym plan has an unpaid invoice.",
        "kind": "finding", "referent": "the gym plan"})["knock"]
    call(config.socket_path, "knock.decline", {"id": first["id"]})
    with pytest.raises(RuntimeError, match="declined"):
        call(config.socket_path, "knock.raise", {
            "topic": "gym", "reason": "The gym plan has an unpaid invoice.",
            "kind": "finding", "referent": "the gym plan"})
    assert call(config.socket_path, "knock.list")["knocks"] == []


def test_assist_knock_commands_work_without_the_daemon(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"),
           "GEMINI_MODE": "mock"}
    for path in ("cfg", "data", "state", "run"):
        (tmp_path / path).mkdir(parents=True, exist_ok=True)
    env.update({"XDG_CONFIG_HOME": str(tmp_path / "cfg"),
                "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_STATE_HOME": str(tmp_path / "state"),
                "XDG_RUNTIME_DIR": str(tmp_path / "run")})
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_API_KEY", None)

    commit = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "commitment", "add",
         "chase the tax office"],
        capture_output=True, text=True, env=env, timeout=30, check=False)
    assert commit.returncode == 0, commit.stdout + commit.stderr
    commitment_id = json.loads(commit.stdout)["commitment_id"]

    bad = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "knock", "raise",
         "--topic", "tax", "--reason", "I miss you"],
        capture_output=True, text=True, env=env, timeout=30, check=False)
    assert bad.returncode == 2
    assert "refused" in bad.stderr

    raised = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "knock", "raise",
         "--topic", "tax office",
         "--reason", "You asked me to chase the tax office before Friday.",
         "--kind", "follow-up", "--commitment", str(commitment_id), "--json"],
        capture_output=True, text=True, env=env, timeout=30, check=False)
    assert raised.returncode == 0, raised.stderr
    knock = json.loads(raised.stdout)["knock"]
    assert knock["reason"] == "You asked me to chase the tax office before Friday."

    listed = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "knock", "list", "--local"],
        capture_output=True, text=True, env=env, timeout=30, check=False)
    assert listed.returncode == 0, listed.stderr
    assert "tax office" in listed.stdout


# -- Wave-1 C round 1: the intent ladder, the trust rail, the autonomy gate ----
#
# Build order 2 and 3 live here, plus the capability/confirm rungs that make
# build order 1 answerable without a model. Nothing below changes an existing
# gate: everything new can only REFUSE, and the confidence floor is read.

from assistant import intents
from assistant.intents import Intent

MUTATING = sorted(intents.MUTATING_KINDS)
READ_ONLY = sorted(intents.READ_ONLY_KINDS - {intents.OBSERVATION_KIND})


@pytest.mark.parametrize("phrase, kind", [
    ("what can you do", "capability"),
    ("what can you do?", "capability"),
    ("what are your capabilities", "capability"),
    ("what are you able to do?", "capability"),
    ("unaweza kufanya nini", "capability"),
    ("confirm rn", "confirm"),
    ("confirm right now?", "confirm"),
    ("can you confirm", "confirm"),
    ("double-check rn", "confirm"),
    ("thibitisha sasa", "confirm"),
])
def test_capability_and_confirm_are_local_read_only_rungs(phrase, kind):
    intent = intents.route(phrase)
    assert intent is not None and intent.kind == kind
    assert intent.trusted is True and intent.dispatchable is True
    assert intent.mutating is False


@pytest.mark.parametrize("phrase", [
    "don't confirm rn", "he said: what can you do",
    "\"what can you do\" is what the speaker said",
])
def test_a_quoted_or_negated_question_never_routes(phrase):
    assert intents.route(phrase) is None


@pytest.mark.parametrize("source", list(intents.UNTRUSTED_SOURCES) + ["", "unknown-ish"])
def test_untrusted_input_never_yields_a_dispatchable_intent(source):
    """IF-6: a message/page/guest sentence is DATA. Same words, no action."""
    hostile = "organise downloads"
    trusted = intents.route(hostile)
    observed = intents.route(hostile, source=source)
    assert trusted is not None and trusted.dispatchable is True
    assert observed is not None
    assert observed.kind == intents.OBSERVATION_KIND
    assert observed.dispatchable is False
    assert observed.mutating is False
    assert observed.observed_kind == "organise", "the shape is kept as data"
    row = observed.as_journal()
    assert row["event"] == "intent.observation"
    assert row["dispatchable"] is False and row["trusted"] is False
    assert hostile not in json.dumps(row), "the payload is not echoed into the journal"


@pytest.mark.parametrize("source", list(intents.TRUSTED_SOURCES))
def test_owner_sources_still_route_normally(source):
    intent = intents.route("status", source=source)
    assert intent is not None and intent.kind == "status"
    assert intent.dispatchable is True and intent.trusted is True


@pytest.mark.parametrize("kind", MUTATING)
def test_every_mutating_intent_is_gated_with_all_three_legs_named(kind):
    """Build order 2: consent · attribution · journal, fail-closed."""
    gate = intents.authorise(Intent(kind), principal="", consent=None, journal=None)
    assert gate["allowed"] is False
    text = gate["reason"]
    assert "attribution" in text and "consent" in text and "journal" in text
    assert gate["journaled"] is False


@pytest.mark.parametrize("kind", MUTATING)
def test_mutating_intent_is_allowed_only_with_consent_attribution_and_journal(kind):
    rows = []
    gate = intents.authorise(
        Intent(kind), principal="owner-voice-verified",
        consent={"granted": True, "scope": "one reviewed plan"},
        journal=rows.append)
    assert gate["allowed"] is True, gate["reason"]
    assert gate["journaled"] is True and len(rows) == 1
    row = rows[0]
    assert row["event"] == "mutation.authorised"
    assert row["intent"] == kind and row["mutating"] is True
    assert row["principal"] == "owner-voice-verified"
    assert row["consent"] == "one reviewed plan"


@pytest.mark.parametrize("kind", READ_ONLY)
def test_read_only_intents_need_no_consent_or_journal(kind):
    gate = intents.authorise(Intent(kind), principal="owner-typed")
    assert gate["allowed"] is True
    assert gate["mutating"] is False


def test_an_untracked_kind_fails_closed_as_mutating():
    assert intents.is_mutating("a-kind-nobody-registered") is True
    gate = intents.authorise(Intent("a-kind-nobody-registered"),
                             principal="owner-typed")
    assert gate["allowed"] is False


def test_unknown_or_guest_principal_can_never_be_the_author_of_a_mutation():
    for principal in ("guest", "inbound", "web", "", "someone-else"):
        gate = intents.authorise(Intent("organise"), principal=principal,
                                 consent=True, journal=lambda row: None)
        assert gate["allowed"] is False
        assert "attribution" in gate["reason"] or "IF-6" in gate["reason"]


def test_untrusted_content_cannot_be_authorised_even_with_every_leg():
    observed = Intent(intents.OBSERVATION_KIND, raw="organise downloads",
                      source="inbound", trusted=False, observed_kind="organise")
    gate = intents.authorise(observed, principal="owner-typed", consent=True,
                             journal=lambda row: None)
    assert gate["allowed"] is False
    assert "IF-6" in gate["reason"]


def test_deny_beats_consent_and_the_refusal_is_journaled():
    rows = []
    gate = intents.authorise(Intent("organise"), principal="owner-hotkey",
                             consent=True, journal=rows.append, deny=True)
    assert gate["allowed"] is False
    assert "deny beats consent" in gate["reason"]
    assert rows and rows[0]["event"] == "mutation.refused"
    assert rows[0]["consent_granted"] is True, "the denial is recorded beside the grant"


def test_a_raising_consent_check_is_a_no_not_a_crash():
    def broken():
        raise RuntimeError("consent store offline")

    gate = intents.authorise(Intent("forget"), principal="owner-typed",
                             consent=broken, journal=lambda row: None)
    assert gate["allowed"] is False
    assert "consent" in gate["reason"]


def test_a_journal_that_refuses_the_row_refuses_the_mutation():
    def sink(row):
        raise OSError("journal disk full")

    gate = intents.authorise(Intent("undo"), principal="owner-typed",
                             consent=True, journal=sink)
    assert gate["allowed"] is False
    assert "journal" in gate["reason"]


def test_command_floor_report_states_the_asymmetry_and_moves_nothing(config):
    before = config.section("transcribe")["command_min_confidence"]
    report = intents.command_floor_report(config)
    after = config.section("transcribe")["command_min_confidence"]
    assert before == after == 0.85, "the gate is reported, never changed"
    assert report["changed"] is False
    assert report["observed"]["local_whisper_perfect_transcript"] == 0.6953
    assert report["observed"]["gemini_batch_confidence"] is None
    assert report["configured_floor"] == 0.85
    options = {option["id"] for option in report["options"]}
    assert options == {"A", "B", "C", "D"}
    assert len(report["options"]) == 4
    assert report["owner_decision"].startswith("the floor is the owner's call")


def test_floor_report_survives_a_config_that_cannot_answer():
    class Broken:
        def section(self, name):
            raise RuntimeError("no config")

    report = intents.command_floor_report(Broken())
    assert report["configured_floor"] == 0.85 and report["changed"] is False


def test_the_daemons_mutation_list_is_a_subset_of_the_canonical_set():
    """The daemon keeps its own tuple today (Z's file); it may never name a
    kind the canonical classification calls read-only. The GAP — kinds the
    canonical set calls mutating that the daemon tuple does not yet carry —
    is what HR-C-1 asks Z to close; it is recorded, not asserted here."""
    from assistant.daemon import Daemon

    assert set(Daemon.MUTATING_INTENTS) <= intents.MUTATING_KINDS
    gap = sorted(intents.MUTATING_KINDS - set(Daemon.MUTATING_INTENTS))
    assert "organise" in gap and "remember" in gap
