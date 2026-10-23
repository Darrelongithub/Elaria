"""Route-specific quota selection and safe oversized WAV splitting."""
import asyncio
import struct
import wave
from pathlib import Path

from assistant.event import EventService, SegmentQueue


def _write_wav(path: Path, seconds: float):
    rate = 16000
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, frames, "NONE", "not compressed"))
        output.writeframes(struct.pack(f"<{frames}h", *([1200] * frames)))


def test_batch_route_uses_batch_rpd_and_no_live_tpm_ceiling(config):
    service = EventService(config, None, route="batch")
    live = EventService(config, None, route="transcribe-live")
    assert service._budget == 25
    assert service._tpm_ceiling is None
    assert live._tpm_ceiling == 20_000


def test_oversized_live_segment_splits_under_headroom_and_counts_every_call(tmp_path):
    wav_path = tmp_path / "seg-001.wav"
    _write_wav(wav_path, 25)
    clock = [0.0]
    durations = []
    resolved = []

    async def transcribe(path):
        from assistant import capture
        duration = capture.wav_duration_s(path)
        durations.append(duration)
        return f"part-{len(durations)}"

    async def sleep(seconds):
        clock[0] += seconds

    queue = SegmentQueue(
        transcribe, on_resolved=lambda segment, text: resolved.append(text),
        on_deferred=lambda segment, error: (_ for _ in ()).throw(AssertionError(error)),
        tokens_per_second=10, tpm_ceiling=100, daily_call_budget=10,
        max_attempts=1, deferred_retries=0, clock=lambda: clock[0], sleep=sleep)

    async def run():
        await queue._process({"index": 1, "wav": str(wav_path), "duration_s": 25})

    asyncio.run(run())
    assert len(durations) == 4
    assert all(duration * 10 <= 70.01 for duration in durations)
    assert queue.calls_used == 4
    assert resolved == ["part-1\npart-2\npart-3\npart-4"]
