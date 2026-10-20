"""BUG 6e: a Live transport that never finalizes must not swallow the WAV.

The hardware capture is already known to work. These regressions focus on the
Live receive/finalization path and on keeping capture.stats durable when a
close/final wait fails.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from pathlib import Path

from assistant import asr
from assistant.asr import Transcript
from assistant.capture import SAMPLE_RATE, wav_duration_s
from assistant.store import Store
from assistant.transcribe import DictationService

FRAME_SAMPLES = SAMPLE_RATE * 30 // 1000


def _speech_frame() -> bytes:
    return struct.pack(f"<{FRAME_SAMPLES}h", *([6000] * FRAME_SAMPLES))


class SpeechSource:
    def __init__(self, frames: int = 40, *, hang_on_close: bool = False):
        self.target = "test-speech-mic"
        self.stalled = False
        self._frames = frames
        self.hang_on_close = hang_on_close
        self.close_started = asyncio.Event()
        self.closed = False

    async def frames(self):
        frame = _speech_frame()
        for _ in range(self._frames):
            yield frame

    async def aclose(self):
        self.close_started.set()
        if self.hang_on_close:
            await asyncio.Event().wait()
        self.closed = True


class NeverFinalOnCloseTransport:
    """Accepts all audio, then ends without a final or turn_complete."""

    name = "never_final"

    def __init__(self):
        self.accepted_frames = 0
        self.activity_ended = False
        self.closed = False
        self._closed = asyncio.Event()

    async def connect(self, resumption_handle=None):
        return None

    async def activity_start(self):
        return None

    async def send_audio(self, pcm: bytes):
        self.accepted_frames += 1

    async def activity_end(self):
        self.activity_ended = True

    async def events(self):
        await self._closed.wait()
        if False:  # Keep this an async generator without yielding any event.
            yield None

    async def close(self):
        self.closed = True
        self._closed.set()


def test_live_close_without_final_falls_back_to_saved_wav_and_logs_capture(
        tmp_path, monkeypatch):
    from assistant.config import load_config

    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {
        **config.raw.get("transcribe", {}),
        "inbox_dir": str(tmp_path / "inbox"),
        "copy_to_clipboard": False,
    }
    store = Store(tmp_path / "bug6e.db")
    service = DictationService(config, store, None)
    transport = NeverFinalOnCloseTransport()
    # Exercise the exact post-transport cleanup gap from hardware: aclose is
    # wedged after transport_closed. capture.stats must already be durable.
    source = SpeechSource(hang_on_close=True)
    events: list[dict] = []
    fallback_paths: list[str] = []

    def fallback(_config, _client, audio_path, **_kwargs):
        path = Path(audio_path)
        fallback_paths.append(str(path))
        assert path.exists(), "the WAV must be closed before fallback transcription"
        return Transcript(
            text="Please save this complete hardware regression sentence.",
            language="en", backend="gemini_batch", confidence=0.94)

    monkeypatch.setattr(asr, "transcribe_file", fallback)

    async def sink(event: dict):
        events.append(event)

    async def run():
        return await service.dictate(
            source, transport_factory=lambda: transport, sink=sink,
            session_id="bug6e-test")

    started = time.monotonic()
    result = asyncio.run(run())
    elapsed = time.monotonic() - started

    assert elapsed < 6.0, f"no-final Live session took {elapsed:.2f}s to terminate"
    assert transport.accepted_frames == 40
    assert transport.activity_ended and transport.closed
    assert source.close_started.is_set()
    assert source.closed is False, "the intentionally wedged close should time out"
    assert fallback_paths == [result.audio_path]
    assert result.raw_text == "Please save this complete hardware regression sentence."
    assert result.backend == "gemini_batch"
    assert result.no_speech is False
    assert result.no_final is False, "saved-WAV transcription recovered the utterance"
    assert result.capture["node"] == "test-speech-mic"
    assert result.capture["bytes"] == 40 * FRAME_SAMPLES * 2
    assert wav_duration_s(Path(result.audio_path)) > 1.0

    # The service and status journal retain capture facts before cleanup can
    # fail; event delivery is in addition to, not instead of, the durable log.
    capture_events = [event for event in events if event.get("event") == "capture.stats"]
    assert len(capture_events) == 1
    assert capture_events[0]["bytes"] == result.capture["bytes"]
    stats_rows = store.list_persona_events(kind="capture.stats", limit=1)
    assert stats_rows
    stats = json.loads(stats_rows[0]["detail"])
    assert stats["node"] == "test-speech-mic"
    assert stats["bytes"] == result.capture["bytes"]
    assert stats["no_speech"] is False
    journal = store.list_persona_events(limit=100)
    source_close_start = next(
        row for row in journal
        if json.loads(row["detail"]).get("step") == "dictate.source_close_start")
    assert stats_rows[0]["id"] < source_close_start["id"], (
        "capture.stats must be durable before the potentially wedged aclose")

    lifecycle_rows = store.list_persona_events(kind="dictate.lifecycle", limit=100)
    steps = {json.loads(row["detail"]).get("step") for row in lifecycle_rows}
    assert "dictate.frame_loop_done" in steps
    assert "dictate.transcript_final_wait_timeout" in steps
    assert "dictate.capture_stats_logged" in steps
    assert "dictate.transport_closed" in steps
    assert "dictate.source_close_timeout" in steps
    assert "dictate.saved_wav_fallback_start" in steps
    assert "dictate.saved_wav_fallback_done" in steps
    store.close()


def test_failed_saved_wav_fallback_returns_explicit_no_final(
        tmp_path, monkeypatch):
    from assistant.config import load_config

    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {
        **config.raw.get("transcribe", {}),
        "inbox_dir": str(tmp_path / "inbox"),
        "copy_to_clipboard": False,
    }
    store = Store(tmp_path / "bug6e-no-final.db")
    service = DictationService(config, store, None)
    source = SpeechSource(frames=8)
    transport = NeverFinalOnCloseTransport()

    def fail_fallback(*_args, **_kwargs):
        raise RuntimeError("batch backend unavailable")

    monkeypatch.setattr(asr, "transcribe_file", fail_fallback)

    async def run():
        return await service.dictate(
            source, transport_factory=lambda: transport,
            session_id="bug6e-no-final")

    started = time.monotonic()
    result = asyncio.run(run())
    elapsed = time.monotonic() - started

    assert elapsed < 5.0
    assert result.no_speech is False
    assert result.no_final is True
    assert result.raw_text == ""
    assert any("no final transcript is available" in note for note in result.notes)
    terminal_events = store.list_persona_events(kind="capture.stats", limit=1)
    assert terminal_events
    lifecycle_rows = store.list_persona_events(kind="dictate.lifecycle", limit=100)
    steps = {json.loads(row["detail"]).get("step") for row in lifecycle_rows}
    assert "dictate.no_final_terminal" in steps
    store.close()
