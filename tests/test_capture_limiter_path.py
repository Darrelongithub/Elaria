"""Is the E5 capture limiter actually on the production path? (2026-11-17)

The design chat's question, verbatim in spirit: *"If a limiter were active,
nothing in the file could read 1.0000 at all — and 38 frames do. Either it is
not in the production path or its threshold is at/above full scale."*

The code says it is in the path and its ceiling is 0.89 — and, crucially, the
saved WAV is written **after** the limiter (`frame = limiter.apply(frame)` at
transcribe.py:857, `wav_sink.write(frame)` at :902). So a dictate-produced take
cannot contain a full-scale sample. This file proves that end to end with a
full-scale fake source, and pins the two strengths the ruling actually needs:

1. the limiter is wired, enabled and clamped below full scale (static curve,
   knee 0.6, ceiling 0.89 — no attack, so it cannot swallow an onset);
2. the take the owner probes IS the limited audio, so `peak_full 1.0000` in a
   saved take means that take did not come through this path — a question for
   the journal's `capture.levels` line (`raw_peak`, `processed_peak`), not for
   another guess about gain.

[TESTED-ONLY]: synthetic full-scale frames. The owner's take is the measurement.
"""

from __future__ import annotations

import asyncio
import struct
import wave
from pathlib import Path

from assistant.capture import SoftLimiter, pcm_peak
from assistant.store import Store
from assistant.transcribe import DictationService

FRAME_SAMPLES = 480          # 30 ms at 16 kHz
CEILING = SoftLimiter.CEILING


def _full_scale_frame() -> bytes:
    """±full scale, every sample — nothing leaves the limiter untouched."""
    return struct.pack(f"<{FRAME_SAMPLES}h",
                       *([32767 if i % 2 == 0 else -32768
                          for i in range(FRAME_SAMPLES)]))


def _speechish_frame() -> bytes:
    return struct.pack(f"<{FRAME_SAMPLES}h", *([6000] * FRAME_SAMPLES))


class FakeSource:
    def __init__(self, frames, *, target="alsa_input.test.Mic1__source"):
        self._frames = frames
        self.target = target
        self.stalled = False
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        self.closed = True


def _service_config(tmp_path):
    from assistant.config import load_config

    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {**config.raw.get("transcribe", {}),
                                "inbox_dir": str(tmp_path / "inbox")}
    config.raw.setdefault("voice", {})["silence_floor"] = 0.05
    return config


def _wav_peak(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        raw = wav.readframes(wav.getnframes())
    usable = raw[: len(raw) - len(raw) % 2]
    samples = struct.unpack(f"<{len(usable) // 2}h", usable)
    return max((abs(value) for value in samples), default=0) / 32768


def test_a_full_scale_frame_leaves_the_limiter_below_full_scale():
    limiter = SoftLimiter()
    processed = limiter.apply(_full_scale_frame())
    assert pcm_peak(processed) <= CEILING
    assert pcm_peak(processed) < 1.0
    stats = limiter.stats()
    assert stats["raw_peak"] == 1.0            # the truth is kept
    assert stats["processed_peak"] <= CEILING  # the audio is clamped
    assert stats["limited_samples"] == FRAME_SAMPLES
    assert stats["curve"]["lookahead"] is False  # static: no onset swallowing


def test_the_saved_take_is_post_limiter_so_it_cannot_hold_a_full_scale_sample(
        tmp_path):
    """The decisive pin: the wav the owner probes is the LIMITED audio."""
    config = _service_config(tmp_path)
    store = Store(tmp_path / "limiter.db")
    service = DictationService(config, store, None)

    from assistant.live_client import ScriptedLiveTransport

    frames = ([_full_scale_frame() for _ in range(30)]
              + [_speechish_frame() for _ in range(30)])
    source = FakeSource(frames)

    async def sink(_event):
        return None

    result = asyncio.run(service.dictate(
        source, transport_factory=ScriptedLiveTransport, sink=sink))

    limiter = result.capture["limiter"]
    assert limiter["raw_peak"] == 1.0, "the raw danger must not be hidden"
    assert limiter["processed_peak"] <= CEILING
    assert result.capture["peak_full"] == 1.0        # measured pre-limiter
    assert result.capture["processed_peak"] <= CEILING

    audio_path = Path(result.audio_path)
    assert audio_path.exists(), "the take must be on disk to be probed"
    assert _wav_peak(audio_path) <= CEILING, (
        "the saved take contains a full-scale sample — the limiter did not "
        "cover this path, which is the only way peak_full 1.0000 can appear in "
        "a dictate-produced wav")
