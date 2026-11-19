"""Event-transport contract tests (IF-4 stub interface + emitted shapes).

Verifies that EventService and recover_event emit documented transport frames
for every lifecycle transition, enforce simulate=False fail-closed, and reject
unknown states, unknown routes, missing fields, and non-finite floats.
"""

from __future__ import annotations

import asyncio
import json
import math
import struct
from datetime import datetime
from pathlib import Path

import pytest

from assistant.event import (
    EVENT_ROUTES,
    EVENT_STATES,
    EVENT_TRANSPORT_MODES,
    EVENT_TRANSPORT_SCHEMAS,
    EventService,
    build_event_transport_frame,
    recover_event,
    validate_event_route,
    validate_event_state,
)

SPEECH_FRAME = struct.pack("<480h", *([6000] * 480))


class _FakeClock:
    def __init__(self, start: float = 1000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _PumpSource:
    def __init__(self, clock: _FakeClock, *, frame_s: float = 1.0, fail_on_frame: int | None = None):
        self.clock = clock
        self.frame_s = frame_s
        self.fail_on_frame = fail_on_frame
        self.target = "fake-mic"
        self._queue: asyncio.Queue = asyncio.Queue()

    async def frames(self):
        seen = 0
        while True:
            frame = await self._queue.get()
            if frame is None:
                return
            seen += 1
            if self.fail_on_frame is not None and seen >= self.fail_on_frame:
                raise OSError("usb mic disconnected")
            self.clock.advance(self.frame_s)
            yield frame

    async def aclose(self):
        await self._queue.put(None)

    async def push(self, count: int = 1, frame: bytes = SPEECH_FRAME) -> None:
        for _ in range(count):
            await self._queue.put(frame)
            await asyncio.sleep(0)


def _assert_valid_frame(frame: dict) -> None:
    name = frame["event"]
    assert name in EVENT_TRANSPORT_SCHEMAS
    schema = EVENT_TRANSPORT_SCHEMAS[name]
    assert frame["simulate"] is False
    assert frame["state"] in EVENT_STATES
    assert frame["state"] in schema["states"]
    assert schema["required"] <= set(frame)
    if "transport" in frame:
        assert frame["transport"] in EVENT_TRANSPORT_MODES
    if "route" in frame:
        assert frame["route"] in EVENT_ROUTES
    encoded = json.dumps(frame)
    assert json.loads(encoded) == frame


def test_documented_transport_schemas_roundtrip_all_ten_event_types():
    samples = {
        "event.started": ("running", {
            "title": "Panel", "route": "batch", "segment_minutes": 30.0,
            "active_speaker": "Speaker 1", "document": "/tmp/a.md",
            "txt_document": "/tmp/a.txt", "event_dir": "/tmp/a",
            "transport": "real transcription",
        }),
        "event.segment.opened": ("running", {
            "segment": 1, "speaker": "Speaker 1",
            "wav": "/tmp/seg-001.wav", "document": "/tmp/a.md",
        }),
        "event.segment.closed": ("running", {
            "segment": 1, "duration_s": 3.0, "bytes": 960,
            "peak": 0.18, "no_signal": False, "wav": "/tmp/seg-001.wav",
        }),
        "event.segment.transcribed": ("running", {
            "segment": 1, "late": False, "status": "done", "txt": "/tmp/seg-001.txt",
        }),
        "event.segment.deferred": ("running", {
            "segment": 1, "wav": "/tmp/seg-001.wav",
            "error": "quota reserve", "status": "deferred",
        }),
        "event.speaker.changed": ("running", {
            "outgoing_speaker": "Speaker 1", "incoming_speaker": "Speaker 2",
            "marker": "[→ Speaker 2 @ 10:00:05]", "flushed": False,
            "active_speaker": "Speaker 2",
        }),
        "event.stopping": ("stopping", {
            "event_dir": "/tmp/a", "document": "/tmp/a.md",
        }),
        "event.stopped": ("stopped", {
            "title": "Panel", "document": "/tmp/a.md", "txt_document": "/tmp/a.txt",
            "event_dir": "/tmp/a", "segments": 1, "transcribed": 1, "queued": 0,
            "deferred": [], "word_count": 12, "transport": "real transcription",
        }),
        "event.recovered": ("recovered", {
            "title": "Panel", "document": "/tmp/a.md", "txt_document": "/tmp/a.txt",
            "event_dir": "/tmp/a", "segments": 1, "transcribed": 0,
            "deferred": [{"index": 1, "wav": "/tmp/seg-001.wav", "error": None}],
            "word_count": 10,
        }),
        "event.error": ("running", {"error": "OSError: capture ended"}),
    }
    assert set(samples) == set(EVENT_TRANSPORT_SCHEMAS)
    for event_name, (state, fields) in samples.items():
        frame = build_event_transport_frame(event_name, state=state, **fields)
        _assert_valid_frame(frame)


def test_simulate_off_and_unknown_states_fail_closed(config):
    with pytest.raises(ValueError, match="simulate is OFF"):
        build_event_transport_frame(
            "event.stopping", state="stopping", simulate=True,
            event_dir="/tmp/a", document="/tmp/a.md",
        )

    with pytest.raises(ValueError, match="simulate is OFF"):
        EventService(config, None, simulate=True)

    with pytest.raises(ValueError, match="unknown event state"):
        validate_event_state("phantom-state")

    with pytest.raises(ValueError, match="unknown event state"):
        build_event_transport_frame(
            "event.stopping", state="phantom-state",
            event_dir="/tmp/a", document="/tmp/a.md",
        )

    with pytest.raises(ValueError, match="invalid state"):
        build_event_transport_frame(
            "event.stopped", state="running",
            title="X", document="/tmp/a.md", txt_document="/tmp/a.txt",
            event_dir="/tmp/a", segments=0, transcribed=0, queued=0,
            deferred=[], word_count=0, transport="real transcription",
        )

    with pytest.raises(ValueError, match="unknown event route"):
        validate_event_route("magic-route")

    with pytest.raises(ValueError, match="unknown event route"):
        EventService(config, None, route="magic-route")

    with pytest.raises(ValueError, match="unknown event transport type"):
        build_event_transport_frame("event.does.not.exist", state="running")

    with pytest.raises(ValueError, match="missing required fields"):
        build_event_transport_frame("event.stopping", state="stopping", event_dir="/tmp/a")

    with pytest.raises(ValueError, match="non-finite"):
        build_event_transport_frame(
            "event.segment.closed", state="running",
            segment=1, duration_s=math.nan, bytes=10, peak=0.1,
            no_signal=False, wav="/tmp/seg-001.wav",
        )


async def test_event_service_start_rejects_simulate_and_unknown_state_mutation(config):
    service = EventService(config, None, level_checker=lambda: {"signal": True},
                           power_probe=lambda: {"on_battery": False})
    with pytest.raises(ValueError, match="simulate is OFF"):
        await service.start(source="simulated", title="SimCheck", simulate=True)

    with pytest.raises(ValueError, match="simulate is OFF"):
        recover_event(config, simulate=True)

    clock = _FakeClock()
    svc = EventService(
        config, None,
        transcribe_fn=lambda _p: asyncio.sleep(0, result="ok"),
        clock=clock,
        now_fn=lambda: datetime(2026, 11, 19, 10, 0, 0),
        level_checker=lambda: {"signal": True},
        power_probe=lambda: {"on_battery": False},
        segment_minutes=0.05,
    )
    source = _PumpSource(clock)
    await svc.start(source=source, title="StateFail", battery_ok=True)
    svc._state["status"] = "corrupted-unknown-state"
    with pytest.raises(ValueError, match="unknown event state"):
        svc._emit_event("event.error", state=svc._state["status"], error="probe")
    svc._state["status"] = "running"
    await svc.stop()


async def test_event_service_emits_documented_lifecycle_shapes_to_async_transport(config):
    emitted: list[dict] = []

    async def broadcast(frame: dict) -> None:
        await asyncio.sleep(0)
        emitted.append(frame)

    async def transcribe(path: Path) -> str:
        index = int(Path(path).stem.split("-")[1])
        return f"transcript {index}"

    clock = _FakeClock()
    service = EventService(
        config, None,
        transcribe_fn=transcribe,
        clock=clock,
        now_fn=lambda: datetime(2026, 11, 19, 10, 0, 0),
        level_checker=lambda: {"signal": True},
        power_probe=lambda: {"on_battery": False},
        segment_minutes=0.05,
        on_event=broadcast,
    )
    source = _PumpSource(clock)
    start_out = await service.start(
        source=source, title="Keynote", speakers="Amina,John", battery_ok=True,
    )
    assert start_out["state"] == "event"

    # 3 frames rotate segment 1 -> opens segment 2, closes & transcribes segment 1
    await source.push(3)
    assert service._queue is not None
    await asyncio.wait_for(service._queue.drain(), timeout=2.0)
    switch_out = service.speaker_switch("John")
    assert switch_out["active_speaker"] == "John"

    await source.push(1)
    await source.aclose()
    await service.wait_capture_idle()
    stop_out = await service.stop()
    assert stop_out["state"] == "stopped"
    await asyncio.gather(*service._background_queues, return_exceptions=True)

    assert len(emitted) == len(service.recent_events())
    names = [frame["event"] for frame in emitted]
    assert names[0] == "event.started"
    assert names[1] == "event.segment.opened"
    assert "event.segment.closed" in names
    assert "event.speaker.changed" in names
    assert "event.segment.transcribed" in names
    assert "event.stopping" in names
    assert names[-1] == "event.stopped"
    assert names.index("event.started") < names.index("event.segment.opened")
    assert names.index("event.stopping") < names.index("event.stopped")
    for frame in emitted:
        _assert_valid_frame(frame)


async def test_event_service_emits_deferred_error_and_recovered_shapes(config):
    emitted: list[dict] = []

    async def always_fail(_path: Path) -> str:
        raise RuntimeError("provider 503")

    clock = _FakeClock()
    service = EventService(
        config, None,
        transcribe_fn=always_fail,
        clock=clock,
        now_fn=lambda: datetime(2026, 11, 19, 11, 0, 0),
        level_checker=lambda: {"signal": True},
        power_probe=lambda: {"on_battery": False},
        segment_minutes=0.05,
        max_attempts=1,
        on_event=emitted.append,
    )
    source = _PumpSource(clock, fail_on_frame=2)
    await service.start(source=source, title="FailurePath", battery_ok=True)
    await source.push(2)
    await service.wait_capture_idle()
    await service.stop()
    await asyncio.gather(*service._background_queues, return_exceptions=True)

    names = [frame["event"] for frame in emitted]
    assert "event.error" in names
    assert "event.segment.closed" in names
    assert "event.segment.deferred" in names
    assert "event.stopped" in names
    for frame in emitted:
        _assert_valid_frame(frame)

    # Simulate daemon-down state on disk and verify recover_event emission
    event_dir = Path(service.status()["event_dir"])
    state_path = event_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["status"] = "running"
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    recovered_frames: list[dict] = []
    summary = recover_event(config, on_event=recovered_frames.append)
    assert summary["state"] == "recovered"
    assert len(recovered_frames) == 1
    assert recovered_frames[0]["event"] == "event.recovered"
    _assert_valid_frame(recovered_frames[0])


async def test_simulated_source_never_invokes_pipewire_even_when_pw_record_present(
    config, monkeypatch,
):
    """Regression guard for owner Fedora hosts with pw-record installed:
    `source='simulated'` must bypass both PipeWireCapture and live_level_check."""
    import assistant.capture as capture_mod
    from assistant.event import EventService

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("PipeWire / live_level_check must not run under source='simulated'")

    monkeypatch.setattr(capture_mod, "PipeWireCapture", fail_if_called)
    monkeypatch.setattr(capture_mod, "live_level_check", fail_if_called)

    service = EventService(
        config, None,
        transcribe_fn=lambda _p: asyncio.sleep(0, result="ok"),
        power_probe=lambda: {"on_battery": False},
    )
    out = await service.start(
        source="simulated", title="SimulatedSafe", battery_ok=True, no_transcribe=True,
    )
    assert out["state"] == "event"
    assert out["preflight"]["mic"]["reason"] == "simulated source"
    await service.stop()
    await asyncio.gather(*service._background_queues, return_exceptions=True)
