"""Persona governor (§13.2), safety spine (§4), latency budget (§18)."""

import socket
import time
from pathlib import Path

import pytest

from assistant.config import load_humour_profile
from assistant.persona import PersonaGovernor, TurnContext, read_tone
from assistant.safety import Journal, check_blast_radius, check_operation, is_halted, set_halt
from assistant.store import Store


@pytest.fixture
def governor(config):
    return PersonaGovernor.from_config(config, load_humour_profile(config))


# -- §13.2: governor, not joke bank ------------------------------------------
def test_serious_gates_come_from_humour_toml(config, governor):
    profile = load_humour_profile(config)
    assert "error-or-data-loss" in profile["serious_gates"]["no_jokes_when"]
    decision = governor.decide(TurnContext(error=True, real_opportunity=True))
    assert decision.register == "plain"
    assert decision.serious_gate == "error-or-data-loss"


@pytest.mark.parametrize("ctx", [
    TurnContext(user_stressed=True, real_opportunity=True),
    TurnContext(sensitive_topic=True, real_opportunity=True),
    TurnContext(direct_order_twice=True, real_opportunity=True),
    TurnContext(destructive_pending=True, real_opportunity=True),
])
def test_no_humour_behind_any_serious_gate(governor, ctx):
    assert governor.decide(ctx).register == "plain"


def test_restraint_is_the_default(governor):
    # No genuine opening => no expression attempted. The governor's most
    # frequent humour decision is "not now".
    decision = governor.decide(TurnContext(user_text="move the invoices please"))
    assert decision.register == "plain"
    assert "restraint" in decision.reason


def test_expression_is_a_permission_never_a_line(governor):
    governor.familiarity = 0.5
    decision = governor.decide(TurnContext(
        user_text="you ALWAYS file my chaos wrong???", real_opportunity=True))
    assert decision.register == "expressive-allowed"
    # The decision object carries register + evidence — no joke text field exists.
    assert not hasattr(decision, "text")
    assert decision.teasing_licence == "tease"


def test_roasting_is_earned_by_familiarity(governor):
    fresh = governor.decide(TurnContext(real_opportunity=True,
                                        user_text="IMAGINE doing that"))
    assert fresh.teasing_licence == "none"  # day one: careful, not roasting
    governor.familiarity = 0.8
    earned = governor.decide(TurnContext(real_opportunity=True,
                                         user_text="IMAGINE doing that"))
    assert earned.teasing_licence == "roast"


def test_repeated_overrides_withdraw_licence(governor):
    governor.familiarity = 0.9
    governor.note_user_reaction("overrode")
    governor.note_user_reaction("overrode")  # user quiet/overrides twice -> dial down
    decision = governor.decide(TurnContext(real_opportunity=True, user_text="hi"))
    assert decision.teasing_licence == "none"


def test_hard_no_ignores_everything_else(governor):
    decision = governor.decide(TurnContext(safety_refusal=True, real_opportunity=True))
    assert decision.pushback == "hard-no" and decision.register == "plain"


def test_factual_narration_uses_real_numbers(governor):
    line = governor.narrate_fact("organise.summary",
                                 {"filed": 32, "review": 4, "unsorted": 6})
    assert "32" in line and "4" in line and "6" in line


# -- tone from writing, emoji never a signal (humour.toml [tone]) -------------
def test_tone_read_from_writing():
    tone = read_tone("Imagine ALWAYS doing this… you never learn???")
    assert tone.playful_absolutes >= 2 and tone.ellipsis_pause
    assert tone.incredulous_challenge and tone.direct_address


def test_emoji_is_not_a_tone_signal():
    plain = read_tone("ok fine do it")
    loud = read_tone("ok fine do it 😭😭🔥💀")  # emoji must change nothing
    assert (plain.caps_burst, plain.banter_energy) == (loud.caps_burst, loud.banter_energy)


def test_codeswitch_beat_detected_without_full_sentences():
    assert read_tone("filed already, sasa what next").codeswitch_beat


# -- §18: nothing on the ack path touches the network -------------------------
def test_ack_is_local_and_inside_budget(governor, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network touched on the ack path (§18 violation)")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    started = time.monotonic()
    ack = governor.ack()
    elapsed_ms = (time.monotonic() - started) * 1000
    assert ack["network"] is False and elapsed_ms < 300


# -- §4 safety spine ------------------------------------------------------------
def test_protected_paths_are_untouchable():
    decision = check_operation("move", "~/.ssh/id_rsa", "~/elsewhere",
                               protected=["~/.ssh"])
    assert not decision.allowed and decision.action == "deny"


def test_there_is_no_delete():
    decision = check_operation("delete", "/tmp/x", None, protected=[])
    assert not decision.allowed and "no rm" in decision.reason


def test_never_overwrite_sends_conflicts(tmp_path):
    src, dst = tmp_path / "a.txt", tmp_path / "b.txt"
    src.write_text("new")
    dst.write_text("different")
    import os
    old = time.time() - 7200
    os.utime(src, (old, old))
    decision = check_operation("move", src, dst, protected=[])
    assert decision.action == "conflict"


def test_recently_modified_guard(tmp_path):
    fresh = tmp_path / "fresh.txt"
    fresh.write_text("just now")
    decision = check_operation("move", fresh, tmp_path / "dest.txt", protected=[])
    assert not decision.allowed and "guard" in decision.reason


def test_blast_radius_tripwire():
    decision = check_blast_radius(400, 1000, max_ops_per_run=200, tripwire_pct=25)
    assert not decision.allowed


def test_journal_is_write_ahead(tmp_path):
    store = Store(tmp_path / "t.db")
    op_id = Journal(store).begin("move", "/a", "/b")
    assert [o["id"] for o in store.outstanding_intents()] == [op_id]  # intent BEFORE act
    Journal(store).commit(op_id)
    assert store.outstanding_intents() == []


def test_halt_flag(tmp_path):
    assert not is_halted(tmp_path)
    set_halt(tmp_path)
    assert is_halted(tmp_path)
    assert (Path(tmp_path) / "assistant.halt").stat().st_mode & 0o077 == 0
