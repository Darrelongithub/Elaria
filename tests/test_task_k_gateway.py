"""TASK K (GATEWAY) pins — one owner for the microphone and the speakers.

The gateway exists because capture was created in three places and playback in
four, so "who holds the mic" was answered by whoever asked. These pins are
fake-device pins on purpose: no microphone is opened, no speaker is used, and
every claim below is about a DECISION (which node, which state, which reply),
never about audio quality. Hardware remains the only audio acceptance.

Pinned here:
  F17  a configured node only; default-device grabbing is a refusal
  F28  PTT/live arbitration table + one utterance never yields two replies
  F16  whole-reply playback only (streaming deferred, named, unpromised)
  F30  cancel is answered by the gateway that owns the session
  wired  the daemon's PTT capture and both playback paths go through it
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from assistant import daemon as daemon_mod
from assistant.audio_gateway import Arbitration, AudioGateway, GatewayRefused
from assistant.capture import SAMPLE_RATE
from assistant.config import load_config
from assistant.daemon import Daemon
from assistant.ipc import call

FRAME = b"\x00\x00" * (SAMPLE_RATE * 30 // 1000)


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------
class FakeDevice:
    """A capture node that records what it was asked to open."""

    opened: ClassVar[list] = []

    def __init__(self, target=None, *, sample_rate=SAMPLE_RATE, frame_ms=30,
                 stall_timeout_s=8.0):
        FakeDevice.opened.append(target)
        self.target = target
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.stall_timeout_s = stall_timeout_s
        self.stalled = False
        self.closed = False

    async def frames(self):
        for _ in range(4):
            yield FRAME

    async def aclose(self):
        self.closed = True


class SilentDevice(FakeDevice):
    """No words, but a node was still opened through the same code path."""

    async def frames(self):
        for _ in range(4):
            yield FRAME


def _gateway(**overrides) -> AudioGateway:
    config = load_config()
    for section, values in overrides.items():
        config.raw.setdefault(section, {}).update(values)
    return AudioGateway(config)


def _fake_factory(seen: list):
    def factory(target, frame_ms, stall):
        seen.append((target, frame_ms, stall))
        return FakeDevice(target, frame_ms=frame_ms, stall_timeout_s=stall)
    return factory


@pytest.fixture(autouse=True)
def _clear_fake_devices():
    FakeDevice.opened.clear()
    yield
    FakeDevice.opened.clear()


@pytest.fixture
def running_daemon(config):
    """Real daemon, real socket, event loop in a thread (the BUG-6 harness)."""
    import threading

    from assistant.ipc import serve

    daemon = Daemon(config)
    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(serve(
        config.socket_path, daemon.handle,
        on_disconnect=daemon._subscribers.discard))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield daemon, server

    async def _shutdown():
        server.close()
        await daemon.aclose()
        await asyncio.wait_for(server.wait_closed(), timeout=3)

    asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=8)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=3)
    loop.close()


# ---------------------------------------------------------------------------
# F17 — the node policy
# ---------------------------------------------------------------------------
def test_f17_configured_node_is_used_verbatim_with_a_named_policy():
    seen: list = []
    gateway = _gateway(capture={"mic_target": "alsa_input.mic1"})
    gateway.capture_factory = _fake_factory(seen)

    opened = gateway.open_capture(frame_ms=30, stall_timeout_s=2.0)

    assert seen == [("alsa_input.mic1", 30, 2.0)], "the configured node, not a default"
    assert opened["simulated"] is False
    assert "configured" in opened["node_policy"]
    assert "alsa_input.mic1" in opened["node_policy"]


def test_f17_parameter_beats_capture_beats_meeting(monkeypatch):
    monkeypatch.setattr("assistant.audio_gateway.tool_available", lambda _t: False)
    gateway = _gateway(capture={"mic_target": "from-capture"},
                       meeting={"mic_target": "from-meeting"})

    assert gateway.resolve_target("explicit")[0] == "explicit"
    assert gateway.resolve_target(None)[0] == "from-capture"
    gateway.config.raw["capture"]["mic_target"] = ""
    assert gateway.resolve_target(None)[0] == "from-meeting"


def test_f17_refuses_a_default_device_when_a_device_could_be_opened(monkeypatch):
    # pw-record exists (the owner's laptop): an unnamed node is a REFUSAL, not
    # "whatever the system picked".
    monkeypatch.setattr("assistant.audio_gateway.tool_available", lambda _t: True)
    seen: list = []
    gateway = _gateway()
    gateway.capture_factory = _fake_factory(seen)

    with pytest.raises(GatewayRefused) as refusal:
        gateway.open_capture()

    assert "F17" in str(refusal.value)
    assert seen == [], "no device may be opened when the node is unnamed"
    assert gateway.status()["state"] == "idle"


def test_f17_without_any_device_the_question_does_not_arise(monkeypatch):
    # Containers/CI: no pw-record, so no default source can be grabbed; the
    # daemon's existing no-device fallback answers (and logs why).
    monkeypatch.setattr("assistant.audio_gateway.tool_available", lambda _t: False)
    gateway = _gateway()
    target, provenance = gateway.resolve_target(None)
    assert target is None
    assert "no device can be opened" in provenance


def test_f17_a_node_that_will_not_open_is_refused_by_name():
    def broken(target, frame_ms, stall):
        raise RuntimeError("pw-record: unknown target")

    gateway = _gateway(capture={"mic_target": "gone.mic"})
    gateway.capture_factory = broken

    with pytest.raises(GatewayRefused) as refusal:
        gateway.open_capture()
    assert "gone.mic" in str(refusal.value)
    assert "state" not in str(refusal.value)  # a refusal, not an arbitration


def test_simulated_capture_needs_no_configured_node(monkeypatch):
    monkeypatch.setattr("assistant.audio_gateway.tool_available", lambda _t: True)
    gateway = _gateway()

    opened = gateway.open_capture(source_kind="simulated")

    assert opened["simulated"] is True
    assert opened["target"] == "simulated"
    assert gateway.release_capture()["released"] is True
    assert gateway.release_capture()["released"] is False


# ---------------------------------------------------------------------------
# F28 — arbitration table
# ---------------------------------------------------------------------------
def test_f28_ptt_and_live_cannot_hold_the_mic_together():
    gateway = _gateway()

    assert gateway.request_ptt().allowed is True
    gateway.begin_ptt()
    assert gateway.state == "ptt"
    # A second press while listening is the DAEMON's "already listening" case
    # (no second ack, no second session) — the gateway answers only whether the
    # microphone may be taken at all, so that a finished session can be
    # superseded without the gateway inventing a refusal.
    assert gateway.request_ptt().allowed is True
    assert "interrupts playback" not in gateway.request_ptt().reason
    assert gateway.request_live().allowed is False
    assert "PTT holds the microphone" in gateway.request_live().reason

    gateway.end_ptt()
    assert gateway.state == "idle"

    assert gateway.request_live().allowed is True
    gateway.begin_live()
    assert gateway.state == "live"
    # F28: PTT is INERT during a live session — the reply lane owns the turn.
    refused = gateway.request_ptt()
    assert refused.allowed is False
    assert "live session active" in refused.reason
    assert isinstance(refused, Arbitration)

    gateway.end_live()
    assert gateway.state == "idle"
    assert gateway.request_ptt().allowed is True


def test_f28_pressing_the_key_interrupts_her_and_is_allowed():
    gateway = _gateway()

    async def playback():
        await asyncio.sleep(0.05)

    async def run():
        task = asyncio.ensure_future(playback())
        gateway.start_playback(task)
        assert gateway.state == "speaking"
        answer = gateway.request_ptt()
        assert answer.allowed is True
        assert "interrupts playback" in answer.reason
        await task

    asyncio.run(run())
    assert gateway.state == "idle"


def test_f28_one_utterance_never_yields_two_replies():
    gateway = _gateway()

    first, why = gateway.claim_reply("session-a")
    second, why2 = gateway.claim_reply("session-a")
    other, _ = gateway.claim_reply("session-b")

    assert (first, second, other) == (True, False, True)
    assert why == "claimed"
    assert isinstance(why2, str)
    empty, reason = gateway.claim_reply("")
    assert empty is False and "no session id" in reason
    assert len(gateway._reply_claimed) <= 256


def test_f28_the_claim_set_is_bounded_and_forgets_the_oldest():
    gateway = _gateway()
    for index in range(300):
        assert gateway.claim_reply(f"session-{index}")[0] is True
    assert len(gateway._reply_claimed) == 256
    assert gateway.claim_reply("session-299")[0] is False


# ---------------------------------------------------------------------------
# F16 — whole-reply playback, tracked not streamed
# ---------------------------------------------------------------------------
def test_f16_playback_is_whole_reply_and_named_as_deferred():
    gateway = _gateway()
    played: list = []

    async def one_reply():
        played.append("whole")
        await asyncio.sleep(0.02)

    async def run():
        task = asyncio.ensure_future(one_reply())
        gateway.start_playback(task)
        assert gateway.is_playing() is True
        await task
        await asyncio.sleep(0)
        assert gateway.is_playing() is False

    asyncio.run(run())
    assert played == ["whole"]
    status = gateway.status()
    assert "deferred" in status["streaming_playback"]
    assert "F16" in status["streaming_playback"]


def test_f16_stop_playback_cancels_what_is_playing():
    gateway = _gateway()

    async def run():
        task = asyncio.ensure_future(asyncio.sleep(10))
        gateway.start_playback(task)
        stopped = await gateway.stop_playback()
        return stopped, task.cancelled()

    stopped, cancelled = asyncio.run(run())
    assert stopped == 1
    assert cancelled is True
    assert gateway.is_playing() is False


# ---------------------------------------------------------------------------
# F30 — cancel belongs to the owner of the session
# ---------------------------------------------------------------------------
def test_f30_cancel_returns_to_idle_and_is_counted():
    gateway = _gateway()
    gateway.begin_ptt()
    gateway.end_ptt(cancelled=True)

    assert gateway.state == "idle"
    assert gateway.status()["cancels"] == 1
    assert gateway._transitions[-1] == {"from": "ptt", "to": "idle", "why": "cancel"}
    # An idle gateway is not moved by a stray release.
    gateway.end_ptt()
    assert gateway.status()["cancels"] == 1


# ---------------------------------------------------------------------------
# WIRED — the daemon really goes through the gateway
# ---------------------------------------------------------------------------
def test_ptt_start_opens_the_configured_node_through_the_gateway(
        config, running_daemon, monkeypatch):
    monkeypatch.delenv("ASSIST_CAPTURE", raising=False)
    daemon, _server = running_daemon
    daemon.config.raw.setdefault("capture", {})["mic_target"] = "alsa_input.mic1"
    monkeypatch.setattr(daemon_mod, "PipeWireCapture", FakeDevice)

    started = call(config.socket_path, "ptt.start", {}, timeout=5.0)
    assert started["listening"] is True

    assert FakeDevice.opened == ["alsa_input.mic1"], (
        "the PTT capture must open the node the Mic1 policy names")
    assert daemon.audio.state == "ptt"
    status = call(config.socket_path, "status", timeout=3.0)
    assert status["gateway"]["streaming_playback"].startswith("deferred")

    call(config.socket_path, "ptt.stop", {"wait_s": 10.0}, timeout=15.0)
    assert daemon.audio.state == "idle"


def test_ptt_start_refuses_instead_of_grabbing_a_default_device(
        config, running_daemon, monkeypatch):
    monkeypatch.delenv("ASSIST_CAPTURE", raising=False)
    daemon, _server = running_daemon
    # A machine that CAN open a device, with no node configured: refusal.
    monkeypatch.setattr("assistant.audio_gateway.tool_available", lambda _t: True)
    monkeypatch.setattr(daemon_mod, "PipeWireCapture", FakeDevice)
    daemon.config.raw.setdefault("capture", {})["mic_target"] = ""
    daemon.config.raw.setdefault("meeting", {})["mic_target"] = ""

    started = call(config.socket_path, "ptt.start", {}, timeout=5.0)

    assert started["listening"] is False
    assert "F17" in started["refused"]
    assert FakeDevice.opened == [], "F17: no unnamed device may be opened"
    assert daemon.audio.state == "idle"


def test_playback_paths_register_with_the_gateway(config, monkeypatch):
    daemon = Daemon(config)

    async def run():
        played: list = []

        def play_ack(kind):
            played.append(kind)
            return {"played": True}

        monkeypatch.setattr(daemon.speech, "play_ack", play_ack)
        daemon._set_speaking(True, text="")
        task = daemon._queue_ack_playback("session_open")
        assert daemon.audio.is_playing() is True, (
            "an ack playback must be visible to the one audio owner")
        await task
        await asyncio.sleep(0)
        assert daemon.audio.is_playing() is False
        assert played == ["session_open"]
        await daemon.aclose()

    asyncio.run(run())
