"""capture.state — the honest mic/orb signal over the wire.

Owner decision (2026-11): the mic is a READ of the daemon's own capture
state, never a browser-local microphone flag. The daemon emits capture.state
on ACTUAL transitions; the bridge validates it; the shell renders it.

This file pins the producer side: exact event shape, repeat suppression,
reason-slot normalization, honest live-state selection, and the fact that
a capture.state broadcast failure never kills a session.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "console"))

import bridge  # noqa: E402

from assistant.daemon import Daemon  # noqa: E402


@pytest.fixture
def daemon(config):
    d = Daemon(config)
    try:
        yield d
    finally:
        d.store.close()


def test_transition_emit_shape_and_repeat_suppression(daemon):
    events = []

    async def collect(event):
        events.append(event)

    daemon.broadcast = collect

    async def run():
        await daemon._emit_capture_state("armed")
        await daemon._emit_capture_state("armed")              # suppressed
        await daemon._emit_capture_state("armed", reason="stalled")  # new key
        await daemon._emit_capture_state("open")               # new state

    asyncio.run(run())

    assert [e["event"] for e in events] == ["capture.state"] * 3, (
        "each emission is a real state change, not a repeat")
    assert events[0] == {"event": "capture.state", "state": "armed"}
    assert events[1] == {"event": "capture.state", "state": "armed",
                        "reason": "stalled"}
    assert events[2] == {"event": "capture.state", "state": "open"}


def test_reason_is_stripped_and_empty_becomes_absent(daemon):
    events = []

    async def collect(event):
        events.append(event)

    daemon.broadcast = collect

    async def run():
        await daemon._emit_capture_state("stalled", reason="  ")
        await daemon._emit_capture_state("stalled", reason="  error  ")

    asyncio.run(run())

    assert events[0] == {"event": "capture.state", "state": "stalled"}, (
        "a whitespace-only reason is no reason, not a lie")
    assert events[1] == {"event": "capture.state", "state": "stalled",
                        "reason": "error"}


def test_live_state_is_open_armed_or_released(daemon):
    """The live pick is honest: open while a session is live, armed while the
    hotword guard is armed, released otherwise — never a guess."""
    events = []

    async def collect(event):
        events.append(event)

    daemon.broadcast = collect

    async def run():
        # Nothing live -> released
        await daemon._emit_live_capture_state(reason="session finished")
        # Hotword armed -> armed
        daemon.wake_guard.arm(unsafe_energy_test=True)
        await daemon._emit_live_capture_state(reason="closing")
        # A finishing PTT session -> open (live over armed)
        daemon._ptt_finishing = {"sess-x"}
        await daemon._emit_live_capture_state(reason="finishing")
        # Teardown for the fixture
        daemon._ptt_finishing.discard("sess-x")
        daemon.wake_guard.disarm(reason="test")

    asyncio.run(run())

    assert [e["state"] for e in events] == ["released", "armed", "open"], events
    assert [e.get("reason") for e in events] == ["session finished", "closing",
                                                  "finishing"]


def test_broadcast_failure_is_logged_not_raised(daemon, capsys):
    """capture.state is advisory: a watcher-side failure must never kill a
    session."""

    async def collect(event):
        raise RuntimeError("watcher dead")

    daemon.broadcast = collect

    async def run():
        await daemon._emit_capture_state("open")

    asyncio.run(run())  # must not raise

    assert "capture.state emit failed" in capsys.readouterr().out


def test_events_subscribe_advertises_capture_state(daemon):
    async def run():
        return await daemon.handle("events.subscribe", {}, None)

    resp = asyncio.run(run())
    assert resp.get("subscribed") is True
    assert "capture.state" in resp["events"], (
        "a console subscribing to events must be able to ask for capture.state")


# ---------------------------------------------------------------------------
# Bridge side: console_event validation for the wire frame
# ---------------------------------------------------------------------------

def _console_event(frame):
    return bridge.console_event(frame, False)


def test_bridge_forwards_valid_capture_state():
    assert _console_event({"event": "capture.state", "state": "armed"}) == {
        "t": "capture-state", "name": "armed"}
    assert _console_event(
        {"event": "capture.state", "state": "muted", "reason": "speaking"}
    ) == {"t": "capture-state", "name": "muted", "reason": "speaking"}


def test_bridge_rejects_unknown_states_and_extra_keys():
    with pytest.raises(ValueError):
        _console_event({"event": "capture.state", "state": "listening"})
    with pytest.raises(ValueError):
        _console_event({"event": "capture.state", "state": "armed", "extra": 1})
    with pytest.raises(ValueError):
        _console_event({"event": "capture.state", "state": "open",
                        "reason": "r", "unexpected": "x"})


def test_bridge_rejects_bad_reasons():
    with pytest.raises(ValueError):
        _console_event({"event": "capture.state", "state": "armed", "reason": ""})
    with pytest.raises(ValueError):
        _console_event({"event": "capture.state", "state": "armed", "reason": "   "})
    with pytest.raises(ValueError):
        _console_event({"event": "capture.state", "state": "armed",
                        "reason": "x" * 257})
    with pytest.raises(ValueError):
        _console_event({"event": "capture.state", "state": "armed", "reason": 42})
    # and the forwarded frame never carries an empty reason key
    frame = _console_event(
        {"event": "capture.state", "state": "open", "reason": "ok"})
    assert frame == {"t": "capture-state", "name": "open", "reason": "ok"}


# ---------------------------------------------------------------------------
# unavailable — capture cannot open or the speech path is dead
# ---------------------------------------------------------------------------

from assistant.audio_gateway import GatewayRefused  # noqa: E402


def test_ptt_policy_refusal_emits_unavailable(daemon, monkeypatch):
    events = []

    async def collect(event):
        events.append(event)

    daemon.broadcast = collect

    def refusal(*args, **kwargs):
        raise GatewayRefused("F17 refused: no configured node", refusal="policy")

    monkeypatch.setattr(daemon.audio, "open_capture", refusal)

    async def run():
        return await daemon._ptt_start({"mode": "narration"})

    out = asyncio.run(run())

    assert out["listening"] is False
    assert events and events[-1] == {
        "event": "capture.state", "state": "unavailable",
        "reason": "capture refused: F17 refused: no configured node"}


def test_hotword_factory_failure_emits_unavailable(daemon):
    events = []

    async def collect(event):
        events.append(event)

    daemon.broadcast = collect

    def factory():
        raise OSError("no capture node on this box")

    daemon.wake_guard.arm(unsafe_energy_test=True)
    daemon._hotword_capture_factory = factory

    asyncio.run(daemon._hotword_loop())

    states = [e["state"] for e in events if e.get("event") == "capture.state"]
    assert "unavailable" in states
    assert events[-1]["state"] == "unavailable"


def test_speech_failure_marks_the_path_dead_and_clears_on_success(daemon, monkeypatch):
    events = []

    async def collect(event):
        events.append(event)

    daemon.broadcast = collect

    from assistant.tts import SpeechResult

    def failed(text, *, play=True, session_id=None):
        return SpeechResult(text=text, backend="gemini", voice_id="v-1",
                            played=False, error="429 rate limited")

    monkeypatch.setattr(daemon.speech, "speak", failed)

    async def run():
        result = await daemon._speak_once("hello", {"muted": False, "session_id": None})
        return result

    result = asyncio.run(run())

    assert result.error == "429 rate limited"
    assert daemon._speech_path_dead is not None
    assert any(e.get("state") == "unavailable" and "429" in (e.get("reason") or "")
               for e in events)

    # live state emissions after the failure do NOT claim the voice works.
    async def live():
        await daemon._emit_live_capture_state(reason="closing")

    asyncio.run(live())
    assert events[-1].get("state") == "unavailable"

    # a successful reply clears the flag — the pipeline can speak again
    def ok(text, *, play=True, session_id=None):
        return SpeechResult(text=text, backend="gemini", voice_id="v-1",
                            played=True)

    monkeypatch.setattr(daemon.speech, "speak", ok)

    async def run_ok():
        result = await daemon._speak_once("again", {"muted": False, "session_id": None})
        return result

    asyncio.run(run_ok())
    assert daemon._speech_path_dead is None


def test_bridge_accepts_unavailable_and_verifying():
    import bridge
    assert bridge.console_event(
        {"event": "capture.state", "state": "unavailable", "reason": "capture cannot open"},
        False) == {"t": "capture-state", "name": "unavailable",
                   "reason": "capture cannot open"}
    assert bridge.console_event(
        {"event": "capture.state", "state": "verifying"},
        False) == {"t": "capture-state", "name": "verifying"}
