"""The first real take, frozen as a fixture (2026-11-17, addendum 3).

The owner's 18 % production take is the first genuine take ever measured:

    duration 8190 ms · 164 frames · peak_full 1.0000 · peak_steady 1.0000
    rms_steady 0.2311 · full_scale_after_start 37 (share 0.2284)
    rms_variation 1.6178 · verdict mixed · recommended_start_pop_ms 100

and it was transcribed **verbatim** while 22.8 % of its frames sat at full
scale. Two rulings rest on it:

1. the acceptance band is achievable by real speech (`rms_steady` mid-band,
   `rms_variation` ~6.5x the threshold), and
2. clipping is graded, not binary — partial clipping still transcribes.

The owner's own audio never enters this repo, so the SHAPE is synthesised here
from the published numbers (pop, two silent frames, quiet lead-in, loud passage
with full-scale hits, 2.4 s of room tone, a moderate unclipped passage, decay).
These pins keep the band pinned to a speech-shaped take instead of to a tone,
and record the room-tone arithmetic the next gain step depends on.

[TESTED-ONLY]: synthetic, built from the reported numbers, not the audio.
"""

from __future__ import annotations

import importlib.util
import math
import struct
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PACKET = REPO / "scripts" / "frame_probe.py"
_spec = importlib.util.spec_from_file_location("frame_probe_shape", PACKET)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)

RATE = 16000
FRAME = RATE * 50 // 1000          # samples per 50 ms frame


def _tone(amplitude: float, freq: float = 180.0) -> list[int]:
    return [int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / RATE))
            for i in range(FRAME)]


def _room_tone(amplitude: float = 0.06) -> list[int]:
    """Low-level, speech-shaped noise — the interior silence of a real take."""
    return [int(amplitude * 32767 * math.sin(2 * math.pi * 97 * i / RATE)
                + amplitude * 32767 * 0.5 * math.sin(2 * math.pi * 431 * i / RATE))
            for i in range(FRAME)]


def _production_take() -> list[int]:
    samples: list[int] = []
    pop = [32767, -32768] * 24
    samples += pop + [0] * (FRAME - len(pop))              # frame 0: the pop
    samples += [0] * (FRAME * 2)                           # frames 1-2: silence
    for _ in range(15):                                    # quiet lead-in
        samples += _tone(0.15)
    for index in range(64):                                # loud passage
        samples += _tone(0.999 if index % 5 == 0 else 0.20)
    for _ in range(53):                                    # 2.4 s room tone
        samples += _room_tone()
    for _ in range(13):                                    # moderate, unclipped
        samples += _tone(0.45)
    for _ in range(8):                                     # decay
        samples += _tone(0.22)
    return samples


def _write(tmp_path: Path) -> Path:
    path = tmp_path / "production-shape.wav"
    samples = _production_take()
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def test_the_band_is_achievable_by_a_speech_shaped_take(tmp_path):
    result = probe.analyse(_write(tmp_path))
    acceptance = probe.gain_acceptance(result)
    # Ruling: the band is validated, not miscalibrated.
    assert 0.15 <= result["rms_steady"] <= 0.30, result["rms_steady"]
    assert acceptance["checks"]["rms_steady"][0] is True
    assert acceptance["checks"]["rms_variation"][0] is True
    # ...and the take still clips on loud syllables — which is the open half.
    assert result["peak_steady"] >= 0.99
    assert result["full_scale_after_start"] > 10
    # The disclosed guard is what catches it: this take peaks at 0.999, so
    # `peak_steady < 1.0` alone passes, while 8 % of its frames sit at full
    # scale. `full_scale_share` is the criterion that says no.
    assert acceptance["checks"]["peak_steady"][0] is True
    share_ok, share = acceptance["checks"]["full_scale_share"]
    assert share_ok is False and share > 0.05
    assert acceptance["pass"] is False


def test_the_start_pop_is_pinned_in_a_take_that_is_otherwise_speech(tmp_path):
    result = probe.analyse(_write(tmp_path))
    frames = result["rows"]
    assert frames[0]["peak"] >= 0.99                 # the pop, one frame
    assert frames[1]["rms"] == 0.0 and frames[2]["rms"] == 0.0
    assert result["verdict"] == "mixed"
    # Fourth independent confirmation of the 100 ms default.
    assert result["recommended_start_pop_ms"] == 100


def test_the_interior_room_tone_sits_above_the_vad_floor():
    """The measured headroom the next gain step must not spend.

    Room tone at 18 % runs rms ~0.049-0.074 (owner numbers). The frame gate's
    threshold is `vad_rms_threshold` = 0.01. Halving the gain again would leave
    room tone ~0.025-0.037 — still above the gate, so the VAD is not the
    constraint on going lower; the peaks are. This pin records the arithmetic,
    not a recommendation.
    """
    from assistant.capture import frame_rms

    room = struct.pack(f"<{FRAME}h", *_room_tone())
    room_rms = frame_rms(room)
    assert room_rms > 0.01                       # above the shipped VAD floor
    assert room_rms / 2 > 0.01                   # survives a further halving
    assert room_rms < 0.10                       # and is not speech by level


def test_the_flat_rail_still_fails_the_variation_criterion(tmp_path):
    """The 20261102 shape against the same criterion, for contrast."""
    samples = [32767 if index % 3 == 0 else 0 for index in range(FRAME * 12)]
    path = tmp_path / "rail.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    result = probe.analyse(path)
    assert probe.gain_acceptance(result)["checks"]["rms_variation"][0] is False
