"""BH-K7/K9 — the always-on mic path and the knock signal.

K7: the hotword capture path was broken three ways on real hardware while
    tests (which replace the factory) stayed green:
    * `_hotword_capture_factory` passed `chunk_ms=` to a constructor that
      takes `frame_ms=` — TypeError before pw-record even spawned;
    * the loop's finally called a sync `close()` that PipeWireCapture does
      not have, so `hotword stop` left pw-record running (orphaned live mic);
    * a capture stall ends `frames()` silently, but the loop exited without
      disarming or broadcasting — status claimed "armed" with no audio.
    The [hotword] stall timeout was also never passed to the capture.
K9: KnockSignal.emit ran subprocess.run (notify-send + player, up to 5s
    each) synchronously inside async daemon handlers — freezing every IPC
    call, ptt.stop included — and played the knock outside the speaking
    gate, i.e. into an open microphone ungated.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

import pytest

from assistant import capture as capture_mod
from assistant.daemon import Daemon


@pytest.fixture
def daemon(config):
    d = Daemon(config)
    try:
        yield d
    finally:
        d.store.close()


# ---------------------------------------------------------------------------
# BH-K7
# ---------------------------------------------------------------------------

class FakeSource:
    def __init__(self, frames=(), *, hang=False):
        self._frames = list(frames)
        self._hang = hang
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame
        if self._hang:
            await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


def test_hotword_factory_builds_a_real_capture(daemon, config, monkeypatch):
    monkeypatch.setattr(capture_mod, "tool_available", lambda name: True)
    config.raw["capture"]["chunk_ms"] = 50
    source = daemon._hotword_capture_factory()  # TypeError pre-fix (chunk_ms)
    assert isinstance(source, capture_mod.PipeWireCapture)
    assert source._frame_bytes == 16000 * 50 // 1000 * 2, (
        "[capture] chunk_ms must map to the capture's frame_ms")
    assert source.stall_timeout_s == 2.0, (
        "the [hotword] stall timeout must reach the capture, not the 8s default")


def test_hotword_loop_stream_end_disarms_stalled_and_closes_source(daemon):
    daemon.wake_guard.arm(unsafe_energy_test=True)
    source = FakeSource(frames=[b"\x00" * 960] * 2)  # then the stream ends
    daemon._hotword_capture_factory = lambda: source
    events = []

    async def collect(event):
        events.append(event)

    daemon.broadcast = collect
    asyncio.run(daemon._hotword_loop())
    assert source.closed, "the capture process must be closed (aclose), not leaked"
    assert daemon.wake_guard.armed is False, (
        "a dead stream must not leave the guard claiming to be armed")
    assert any(e.get("event") == "hotword.stalled" for e in events)


def test_hotword_loop_cancellation_closes_source(daemon):
    daemon.wake_guard.arm(unsafe_energy_test=True)
    source = FakeSource(hang=True)
    daemon._hotword_capture_factory = lambda: source

    async def drive():
        task = asyncio.create_task(daemon._hotword_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)  # shielded close completes

    asyncio.run(drive())
    assert source.closed, "hotword stop (task cancel) must close the capture"


# ---------------------------------------------------------------------------
# BH-K9
# ---------------------------------------------------------------------------

class SlowSignal:
    """emit() that blocks like a slow notify-send + player would."""

    def __init__(self, daemon):
        self.daemon = daemon
        self.speaking_during = None
        self.calls = 0

    def emit(self, knock, *, class_mode):
        self.calls += 1
        self.speaking_during = self.daemon.is_speaking()
        time.sleep(1.2)
        return {"signal": "knock", "sound": True, "notification": False}


def test_knock_emit_does_not_block_the_event_loop_and_is_gated(daemon):
    slow = SlowSignal(daemon)
    daemon.knock_signal = slow
    daemon.initiative.raise_knock = lambda **kw: {
        "id": 1, "topic": kw.get("topic"), "reason": kw.get("reason")}

    async def drive():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.02)

        tick_task = asyncio.create_task(ticker())
        raise_task = asyncio.create_task(daemon._knock_raise(
            {"topic": "report", "reason": "the deadline you set is today"}))
        await asyncio.sleep(0.4)
        mid = ticks
        out = await raise_task
        tick_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tick_task
        return mid, out

    mid, out = asyncio.run(drive())
    assert mid >= 10, (
        f"event loop starved during knock emit (only {mid} ticks in 0.4s)")
    assert slow.speaking_during is True, (
        "the knock is speaker output: the speaking gate must be held "
        "while it plays so open capture gates it like any playback")
    assert out["signal"]["sound"] is True
