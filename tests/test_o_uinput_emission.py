"""Agent O: real key emission in UinputTypeSink, proven with a fake evdev device.

Sandbox evidence only: no python-evdev install, no uinput rule, no hardware.
The eye-check is `test_eye_check_fake_evdev_open_gate_emits_exact_keys_closed_gate_emits_none`.
The core never claims a real keystroke as verified: this sink has no readback.
"""
from __future__ import annotations

import io
import logging
import string
from types import SimpleNamespace
from typing import ClassVar

import pytest

from assistant.hands import runner as runner_mod
from assistant.hands.core import SandboxCore
from assistant.hands.gate import TYPE_TOOL, GateChecker, SyntheticFacts, typing_text_ok
from assistant.hands.plan import Plan, Step
from assistant.hands.queue import ParkedQueue
from assistant.hands.runner import _ASCII_KEY_NAMES, TypingRunner, UinputTypeSink, typing_enabled
from assistant.hands.sandbox import SyntheticSpace
from assistant.hands.sink import ThinSink

EV_KEY, SHIFT, KEY_A, KEY_B, KEY_1 = 1, 42, 30, 48, 2


class _FakeUInput:
    """Records the exact evdev calls a trusted caller asked the sink to emit."""

    devices: ClassVar[list] = []

    def __init__(self, capabilities, name=""):
        self.capabilities = capabilities
        self.name = name
        self.events: list = []
        self.closed = False
        _FakeUInput.devices.append(self)

    def write(self, ev_type, code, value):
        self.events.append(("write", ev_type, code, value))

    def syn(self):
        self.events.append(("syn",))

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _fresh_fake_devices():
    _FakeUInput.devices.clear()
    yield


@pytest.fixture
def fake_evdev():
    """A factory returning an evdev-like module, plus a count of factory calls."""
    module = SimpleNamespace(
        ecodes=SimpleNamespace(EV_KEY=EV_KEY, KEY_LEFTSHIFT=SHIFT, KEY_A=KEY_A,
                               KEY_B=KEY_B, KEY_1=KEY_1),
        UInput=_FakeUInput,
    )
    calls = []

    def factory():
        calls.append(1)
        return module

    return factory, calls


@pytest.fixture
def lab():
    with SyntheticSpace() as space:
        for i in range(8):
            space.seed(f"note{i}.txt", f"synthetic bytes {i}")
        queue = ParkedQueue(space)
        yield space, queue
        queue.close()


def expected_events():
    """'Ab!': shift held across A and !, one SYN after every state change."""
    return [
        ("write", EV_KEY, SHIFT, 1), ("syn",),
        ("write", EV_KEY, KEY_A, 1), ("syn",),
        ("write", EV_KEY, KEY_A, 0), ("syn",),
        ("write", EV_KEY, SHIFT, 0), ("syn",),
        ("write", EV_KEY, KEY_B, 1), ("syn",),
        ("write", EV_KEY, KEY_B, 0), ("syn",),
        ("write", EV_KEY, SHIFT, 1), ("syn",),
        ("write", EV_KEY, KEY_1, 1), ("syn",),
        ("write", EV_KEY, KEY_1, 0), ("syn",),
        ("write", EV_KEY, SHIFT, 0), ("syn",),
    ]


def test_eye_check_fake_evdev_open_gate_emits_exact_keys_closed_gate_emits_none(lab, fake_evdev):
    space, queue = lab
    factory, factory_calls = fake_evdev
    # Config gate closed: literal-True only. Nothing may even reach the factory.
    closed_sink = UinputTypeSink(enabled=typing_enabled({}), evdev_factory=factory)
    closed_runner = TypingRunner(space, closed_sink)
    step = Step(0, 2, TYPE_TOOL, ("Ab!",), str(space.work))
    assert closed_runner.available(step) == (False, "disabled-by-config")
    with pytest.raises(PermissionError, match="disabled-by-config"):
        closed_runner.run(step)
    assert factory_calls == [] and _FakeUInput.devices == []

    # Owner gate closed, then owner says yes: the core still refuses the real
    # sink because a keyboard cannot read back what a window received.
    sink = UinputTypeSink(enabled=True, evdev_factory=factory)
    runner = TypingRunner(space, sink)
    core = SandboxCore(space, queue, runner, ThinSink(io.StringIO()))
    plan = Plan((step,))
    assert core.run(plan, errand="o" * 12) == "parked"
    assert factory_calls == [] and runner.injections == []
    assert core.decision(queue.pending()[0]["id"], plan.digest, "yes") == "yes"
    assert core.run(plan, errand="o" * 12) == "typing unavailable or unverifiable; nothing typed"
    assert factory_calls == [] and _FakeUInput.devices == []
    assert runner.injections == []

    # Emission itself: a trusted runner on the open path emits exactly the
    # consented string, never a readback claim.
    runner.run(step)
    assert len(_FakeUInput.devices) == 1
    device = _FakeUInput.devices[0]
    assert device.events == expected_events()  # 10 writes + 10 SYN
    assert device.name == "elaria-hands" and device.closed is True
    assert device.capabilities[EV_KEY] == [KEY_1, KEY_A, SHIFT, KEY_B]
    assert sink.has_readback is False and sink.last_typed() is None


def test_every_printable_ascii_character_has_a_key_and_no_control_byte_does():
    assert set(_ASCII_KEY_NAMES) == (set(string.printable) - set(string.whitespace)) | {" "}
    assert not any(char in _ASCII_KEY_NAMES for char in "\t\n\r\x0b\x0c\x7f")


def test_gate_still_requires_tier_2_and_one_printable_string(lab):
    space, _queue = lab
    good = Step(0, 2, TYPE_TOOL, ("habari",), str(space.work))
    assert GateChecker(space).derive(good, SyntheticFacts()) == 2
    assert typing_text_ok(good.argv)
    bad = Step(0, 2, TYPE_TOOL, ("a\nb",), str(space.work))
    assert GateChecker(space).derive(bad, SyntheticFacts()) == 3
    assert not typing_text_ok(bad.argv)


@pytest.mark.parametrize("text, reason", [("a\nb", "invalid-text"), ("é", "unsupported-character")])
def test_bad_text_is_refused_logged_and_emits_nothing(lab, fake_evdev, caplog, text, reason):
    _space, _queue = lab
    factory, factory_calls = fake_evdev
    sink = UinputTypeSink(enabled=True, evdev_factory=factory)
    with (caplog.at_level(logging.WARNING, logger="assistant.hands.runner"),
          pytest.raises(PermissionError, match=reason)):
        sink.type_text(text)
    assert f"typing refused: {reason}" in caplog.text
    assert factory_calls == [] and _FakeUInput.devices == []


def test_absence_refusals_stay_honest_and_logged(monkeypatch, caplog):
    sink = UinputTypeSink(enabled=True)
    monkeypatch.setattr(runner_mod.importlib.util, "find_spec", lambda name: None)
    with caplog.at_level(logging.WARNING, logger="assistant.hands.runner"):
        assert sink.available() == (False, "evdev-absent")
        with pytest.raises(PermissionError, match="evdev-absent"):
            sink.type_text("hi")
    assert caplog.text.count("typing refused: evdev-absent") >= 2

    caplog.clear()
    monkeypatch.setattr(runner_mod.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(runner_mod.os, "access", lambda path, mode: False)
    with caplog.at_level(logging.WARNING, logger="assistant.hands.runner"):
        assert sink.available() == (False, "uinput-absent")
        with pytest.raises(PermissionError, match="uinput-absent"):
            sink.type_text("hi")
    assert caplog.text.count("typing refused: uinput-absent") >= 2
    assert _FakeUInput.devices == []


def test_disabled_factory_cannot_be_driven_even_when_injected(fake_evdev, caplog):
    factory, factory_calls = fake_evdev
    sink = UinputTypeSink(enabled="yes", evdev_factory=factory)  # not literal True
    with caplog.at_level(logging.WARNING, logger="assistant.hands.runner"):
        assert sink.available() == (False, "disabled-by-config")
        with pytest.raises(PermissionError, match="disabled-by-config"):
            sink.type_text("habari")
    assert "typing refused: disabled-by-config" in caplog.text
    assert factory_calls == [] and _FakeUInput.devices == []


def test_evdev_import_is_lazy_and_import_failure_fails_closed(monkeypatch, caplog):
    sink = UinputTypeSink(enabled=True)
    monkeypatch.setattr(runner_mod.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(runner_mod.os, "access", lambda path, mode: True)

    def no_import(name):
        raise ImportError("evdev not installed")

    monkeypatch.setattr(runner_mod.importlib, "import_module", no_import)
    with (caplog.at_level(logging.WARNING, logger="assistant.hands.runner"),
          pytest.raises(PermissionError, match="evdev-absent")):
        sink.type_text("hi")
    assert "typing refused: evdev-absent" in caplog.text
    assert _FakeUInput.devices == []


def test_malformed_factory_and_uinput_open_failure_refuse_logged(fake_evdev, caplog):
    bad = UinputTypeSink(enabled=True, evdev_factory=lambda: object())
    with (caplog.at_level(logging.WARNING, logger="assistant.hands.runner"),
          pytest.raises(PermissionError, match="evdev-absent")):
        bad.type_text("hi")
    assert "typing refused: evdev-absent" in caplog.text

    _factory, _calls = fake_evdev

    def broken_module():
        return SimpleNamespace(ecodes=SimpleNamespace(EV_KEY=EV_KEY, KEY_LEFTSHIFT=SHIFT,
                                                      KEY_A=KEY_A),
                               UInput=lambda *a, **k: (_ for _ in ()).throw(OSError("no uinput")))

    sink = UinputTypeSink(enabled=True, evdev_factory=broken_module)
    caplog.clear()
    with (caplog.at_level(logging.WARNING, logger="assistant.hands.runner"),
          pytest.raises(PermissionError, match="uinput-absent")):
        sink.type_text("a")
    assert "typing refused: uinput-absent" in caplog.text
    assert _FakeUInput.devices == []
