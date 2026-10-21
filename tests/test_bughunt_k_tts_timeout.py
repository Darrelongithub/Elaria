"""BH-K25: playback had a flat 120 s subprocess timeout.

Wrong in both directions: a legitimately long utterance (>120 s, e.g. a
read-aloud summary) was killed mid-speech and reported as a player
failure, while a hung player on a one-second ack chirp blocked its
thread for the full 120 s. Piper synthesis had the same flat 120 s
regardless of text length.

Fix: the playback bound is derived from the WAV's own duration
(duration x 1.5 + 10 s, floored at 15 s) and the synth bound scales
with text length — finite, but proportional to the work.
"""

from __future__ import annotations

import wave
from types import SimpleNamespace

from assistant.tts import SpeechService


def _wav(path, seconds: float) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(seconds * 16000))


def _service(config, captured: dict):
    config.raw["tts"]["player"] = "cat"

    def runner(args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    return SpeechService(config, player_runner=runner)


def test_short_clip_gets_a_short_bound(config, tmp_path):
    captured: dict = {}
    speech = _service(config, captured)
    clip = tmp_path / "ack.wav"
    _wav(clip, 1.0)
    assert speech.play_audio(clip) is True
    assert captured["timeout"] <= 30, captured


def test_long_utterance_is_not_killed_at_120s(config, tmp_path):
    captured: dict = {}
    speech = _service(config, captured)
    clip = tmp_path / "long.wav"
    _wav(clip, 200.0)
    assert speech.play_audio(clip) is True
    assert captured["timeout"] > 200, captured


def test_unreadable_file_keeps_a_finite_fallback_bound(config, tmp_path):
    captured: dict = {}
    speech = _service(config, captured)
    bogus = tmp_path / "not-a.wav"
    bogus.write_bytes(b"nope")
    assert speech.play_audio(bogus) is True
    assert 0 < captured["timeout"] <= 300, captured
