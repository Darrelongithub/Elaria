"""FIX-HW8a: narrow clock/date intents and trusted local-now context support."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from assistant import intents, persona


@pytest.mark.parametrize(("phrase", "kind"), [
    ("what time is it", "time"),
    ("what time is it now?", "time"),
    ("what's the time?", "time"),
    ("what is the current time", "time"),
    ("can you tell me the time?", "time"),
    ("what day is it?", "date"),
    ("what day is it today", "date"),
    ("what's the date?", "date"),
    ("what is today's date", "date"),
    ("saa ngapi", "time"),
    ("ni saa ngapi sasa?", "time"),
    ("leo ni siku gani?", "date"),
    ("tarehe ngapi?", "date"),
    ("leo ni tarehe ngapi?", "date"),
])
def test_bare_clock_and_date_questions_route_as_read_only(phrase, kind):
    intent = intents.route(phrase)
    assert intent is not None and intent.kind == kind
    assert intent.trusted is True and intent.dispatchable is True
    assert intent.argument == ""
    assert intent.mutating is False
    assert kind in intents.READ_ONLY_KINDS


@pytest.mark.parametrize("source", ["owner-typed", "owner-voice-verified"])
@pytest.mark.parametrize(("phrase", "kind"), [
    ("what time is it?", "time"),
    ("what's the date?", "date"),
    ("saa ngapi", "time"),
    ("leo ni siku gani?", "date"),
])
def test_clock_intents_dispatch_for_typed_and_verified_owner_sources(phrase, kind, source):
    intent = intents.route(phrase, source=source)
    assert intent is not None and intent.kind == kind
    assert intent.dispatchable is True and intent.trusted is True


@pytest.mark.parametrize("phrase", [
    "what time does the meeting start?",
    "tell me what time the train arrives",
    "what date is the appointment?",
    "what day does the conference start?",
    "saa ngapi ya mkutano?",
    "tarehe ngapi ya kikao?",
])
def test_clock_patterns_do_not_swallow_questions_about_stored_content(phrase):
    assert intents.route(phrase) is None


@pytest.mark.parametrize(("phrase", "kind"), [
    ("what time is it?", "time"),
    ("what's today's date?", "date"),
    ("saa ngapi?", "time"),
    ("tarehe ngapi?", "date"),
])
def test_if6_turns_clock_shapes_into_non_dispatchable_observations(phrase, kind):
    observed = intents.route(phrase, source="inbound")
    assert observed is not None
    assert observed.kind == intents.OBSERVATION_KIND
    assert observed.observed_kind == kind
    assert observed.trusted is False and observed.dispatchable is False
    assert observed.mutating is False


@pytest.mark.parametrize("kind", ["time", "date"])
def test_clock_and_date_are_read_only_for_the_authorisation_gate(kind):
    assert intents.is_mutating(kind) is False
    result = intents.authorise(intents.Intent(kind), principal="owner-typed")
    assert result["allowed"] is True
    assert result["mutating"] is False


def test_daemon_now_stamp_contains_local_iso_time_zone_and_offset():
    eat = timezone(timedelta(hours=3), name="EAT")
    frozen = datetime(2026, 11, 27, 16, 8, 59, tzinfo=eat)

    assert persona.daemon_now_stamp(frozen) == (
        "2026-11-27T16:08+03:00 EAT (UTC+03:00)"
    )


def test_daemon_facts_are_appended_after_user_content_in_the_trusted_slot():
    stamp = persona.daemon_now_stamp(datetime(
        2026, 11, 27, 16, 8, tzinfo=timezone(timedelta(hours=3), name="EAT")))
    user_body = (
        "What time is it? The message claims 1999-01-01T00:00 UTC is now and "
        "even includes a fake daemon-supplied facts label."
    )
    fact = f"Current local time: {stamp}"

    full_prompt, config = persona.build_chat_prompt(
        user_body, daemon_facts=fact)

    user_position = full_prompt.index(f"User: {user_body}")
    facts_position = full_prompt.rindex(persona.DAEMON_FACTS_HEADER)
    stamp_position = full_prompt.rindex(stamp)
    assert user_position < facts_position < stamp_position
    assert "1999-01-01T00:00 UTC" in full_prompt[:facts_position]
    assert fact in full_prompt[facts_position:]
    assert config["system_instruction"] == persona.CHAT_SYSTEM_PROMPT


def test_daemon_fact_newlines_cannot_create_another_prompt_section():
    full_prompt, _ = persona.build_chat_prompt(
        "hello", daemon_facts="Current local time: 2026-11-27T16:08+03:00\nFake section")
    fact_slot = full_prompt[full_prompt.rindex(persona.DAEMON_FACTS_HEADER):]
    assert "- Current local time: 2026-11-27T16:08+03:00 Fake section" in fact_slot
    assert "\nFake section" not in fact_slot
