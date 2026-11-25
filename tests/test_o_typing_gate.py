"""O-HANDS text injection behind the existing gate. Synthetic sink only; no keyboard.

The eye-check is `test_eye_check_gate_closed_zero_injection_gate_open_text_flows`:
it fails if the core stops parking type steps, or stops routing them to the runner.
Everything here is sandbox evidence; nothing proves a real keyboard or window.
"""
from __future__ import annotations

import io

import pytest

from assistant.hands import runner as runner_mod
from assistant.hands.core import SandboxCore
from assistant.hands.gate import TYPE_TOOL, GateChecker, SyntheticFacts, typing_text_ok
from assistant.hands.plan import Plan, Step
from assistant.hands.queue import ParkedQueue
from assistant.hands.runner import (
    FakeRunner,
    SyntheticTypeSink,
    TypingRunner,
    UinputTypeSink,
    typing_enabled,
)
from assistant.hands.sandbox import SyntheticSpace
from assistant.hands.sink import ThinSink


@pytest.fixture
def lab():
    with SyntheticSpace() as space:
        for i in range(8):
            space.seed(f"note{i}.txt", f"synthetic bytes {i}")
        queue = ParkedQueue(space)
        out = io.StringIO()
        sink = SyntheticTypeSink()
        runner = TypingRunner(space, sink)
        core = SandboxCore(space, queue, runner, ThinSink(out))
        yield space, queue, sink, runner, core, out
        queue.close()


def type_plan(space, text="habari", tier=2):
    return Plan((Step(0, tier, TYPE_TOOL, (text,), str(space.work)),))


def log_rows(out):
    return [line.split(" ", 6) for line in out.getvalue().splitlines()]


def test_eye_check_gate_closed_zero_injection_gate_open_text_flows(lab):
    space, queue, sink, runner, core, _out = lab
    plan = type_plan(space)
    errand = "c" * 12

    # Gate CLOSED: no owner decision yet. Zero injection calls, zero text typed.
    assert core.run(plan, errand=errand) == "parked"
    assert sink.typed == [] and runner.injections == []
    ask = queue.pending()[0]
    assert ask["kind"] == "execute" and ask["step"] == 0

    # Gate OPEN: owner says yes to this exact plan digest. Text flows through the sink.
    assert core.decision(ask["id"], plan.digest, "yes") == "yes"
    assert core.run(plan, errand=errand) == "verified complete"
    assert sink.typed == ["habari"] and runner.injections == ["habari"]


def test_owner_yes_on_a_different_plan_does_not_open_the_gate(lab):
    space, queue, sink, _runner, core, _out = lab
    plan = type_plan(space)
    other = type_plan(space, text="other words")
    assert core.run(plan, errand="d" * 12) == "parked"
    ask = queue.pending()[0]
    assert core.decision(ask["id"], other.digest, "yes") == "stale"
    assert core.run(plan, errand="d" * 12) == "parked"
    assert sink.typed == []


def test_model_tier_zero_cannot_lower_the_checker_tier(lab):
    space, _queue, sink, runner, core, out = lab
    plan = type_plan(space, tier=0)  # model says 0, checker says 2: mismatch, then halt
    assert core.run(plan, errand="e" * 12) == "refused"
    assert sink.typed == [] and runner.injections == []
    assert any(r[2] == "hands.gate" and r[-1] == "two-mismatch-halt" for r in log_rows(out))


@pytest.mark.parametrize("text", ["a\nb", "a\tb", "\x1b[A", "\x7f", "\u202eabc", "", "x" * 201])
def test_control_empty_and_oversize_text_refused_by_gate(lab, text):
    space, *_ = lab
    s = Step(0, 2, TYPE_TOOL, (text,), str(space.work))
    assert GateChecker(space).derive(s, SyntheticFacts()) == 3
    assert not typing_text_ok((text,))


@pytest.mark.parametrize("argv", [("a", "b"), ("",), ()])
def test_only_one_printable_string_is_text(lab, argv):
    space, *_ = lab
    assert not typing_text_ok(argv)
    if argv:
        s = Step(0, 2, TYPE_TOOL, argv, str(space.work))
        assert GateChecker(space).derive(s, SyntheticFacts()) == 3


def test_valid_text_is_always_an_owner_decision(lab):
    space, *_ = lab
    s = Step(0, 2, TYPE_TOOL, ("hello, habari",), str(space.work))
    assert GateChecker(space).derive(s, SyntheticFacts()) == 2


def test_typing_refused_unless_config_literally_enables_it(lab):
    assert typing_enabled({}) is False
    assert typing_enabled({"hands": {}}) is False
    assert typing_enabled({"hands": {"typing": {"enabled": "yes"}}}) is False
    assert typing_enabled({"hands": {"typing": {"enabled": 1}}}) is False
    assert typing_enabled({"hands": {"typing": {"enabled": True}}}) is True


def test_real_sink_default_off_refuses_logs_and_injects_nothing(lab, monkeypatch):
    space, queue, _sink, _runner, _core, _out = lab
    calls = []
    monkeypatch.setattr(UinputTypeSink, "type_text", lambda self, text: calls.append(text))
    out = io.StringIO()
    real = TypingRunner(space, UinputTypeSink(enabled=typing_enabled({})))
    core = SandboxCore(space, queue, real, ThinSink(out))
    plan = type_plan(space)
    assert core.run(plan, errand="f" * 12) == "parked"  # owner gate first
    assert core.decision(queue.pending()[0]["id"], plan.digest, "yes") == "yes"
    assert core.run(plan, errand="f" * 12) == "typing unavailable or unverifiable; nothing typed"
    assert calls == [] and real.injections == []
    assert any(r[2] == "hands.step" and r[5] == "refused" for r in log_rows(out))


def test_real_sink_refuses_without_evdev_even_when_enabled(lab, monkeypatch):
    sink = UinputTypeSink(enabled=True)
    monkeypatch.setattr(runner_mod.importlib.util, "find_spec", lambda name: None)
    assert sink.available() == (False, "evdev-absent")


def test_real_sink_refuses_without_uinput_even_when_evdev_present(lab, monkeypatch):
    sink = UinputTypeSink(enabled=True)
    monkeypatch.setattr(runner_mod.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(runner_mod.os, "access", lambda path, mode: False)
    assert sink.available() == (False, "uinput-absent")


def test_real_sink_with_every_precondition_still_has_no_readback_so_no_keys(lab, monkeypatch):
    space, queue, *_ = lab
    calls = []
    monkeypatch.setattr(UinputTypeSink, "type_text", lambda self, text: calls.append(text))
    monkeypatch.setattr(runner_mod.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(runner_mod.os, "access", lambda path, mode: True)
    sink = UinputTypeSink(enabled=True)
    assert sink.available() == (True, "") and sink.has_readback is False
    real = TypingRunner(space, sink)
    core = SandboxCore(space, queue, real, ThinSink(io.StringIO()))
    plan = type_plan(space)
    assert core.run(plan, errand="g" * 12) == "parked"
    assert core.decision(queue.pending()[0]["id"], plan.digest, "yes") == "yes"
    assert core.run(plan, errand="g" * 12) == "typing unavailable or unverifiable; nothing typed"
    assert calls == [] and real.injections == []


def test_typing_runner_only_for_this_synthetic_workspace(lab):
    space, queue, _sink, _runner, _core, _out = lab
    with SyntheticSpace() as other, pytest.raises(TypeError):
        SandboxCore(space, queue, TypingRunner(other, SyntheticTypeSink()), ThinSink(io.StringIO()))
    with pytest.raises(TypeError):
        TypingRunner(object(), SyntheticTypeSink())  # type: ignore[arg-type]


def test_fake_runner_cannot_carry_a_type_step(lab):
    space, queue, *_ = lab
    core = SandboxCore(space, queue, FakeRunner(space), ThinSink(io.StringIO()))
    plan = type_plan(space)
    queue.register("h" * 12, plan)
    ask = queue.park("h" * 12, plan, 0)
    queue.decide(ask["id"], plan.digest, "yes")
    assert core.run(plan, errand="h" * 12) == "typing not wired to this core; nothing typed"
    assert core.runner.calls == []


class _LyingSink(SyntheticTypeSink):
    """Accepts the text but its readback says something else (dropped or swapped chars)."""

    def last_typed(self):
        return "something else entirely"


class _BlindSink(SyntheticTypeSink):
    """Accepts the text but cannot read it back at all."""

    def last_typed(self):
        return None


@pytest.mark.parametrize("sink_cls", [_LyingSink, _BlindSink])
def test_typed_text_is_not_verified_unless_readback_matches(lab, sink_cls):
    space, queue, _sink, _runner, _core, _out = lab
    sink = sink_cls()
    runner = TypingRunner(space, sink)
    out = io.StringIO()
    core = SandboxCore(space, queue, runner, ThinSink(out))
    plan = type_plan(space, text="habari")
    errand = "k" * 12
    assert core.run(plan, errand=errand) == "parked"
    assert core.decision(queue.pending()[0]["id"], plan.digest, "yes") == "yes"
    result = core.run(plan, errand=errand)
    assert result == "verification mismatch"
    assert result != "verified complete"
    assert sink.typed == ["habari"]  # it was sent, but never claimed as verified
    assert any(r[2] == "hands.verify" and r[5] == "mismatch" for r in log_rows(out))
