"""Stream H.1 (2026-10-27): the post-timeout route is identical for BOTH
timeout kinds — scene-6 regression candidate #1.

Scene 5 (full-budget timeout) ended in `transcription.landed` via the
flash-lite file fallback + a spoken reply. Scene 6 (adaptive-abandon
timeouts) ended in `transcription.deferred`. The gate under test: after
either timeout kind, with empty Live finals and real speech captured,
the saved-WAV file-transcription leg MUST fire, and its outcome decides
landed (text recovered) or deferred (wav kept, marked for retry) —
never a silent skip. Commit-reason assertions distinguish the paths:
the `final.timeout` reason names "budget expired" vs "adaptive
abandon", and the fallback attempt is journal-visible either way.
"""

from __future__ import annotations

import asyncio
import io

from assistant import asr
from assistant.asr import Transcript
from assistant.capture import SimulatedCapture
from assistant.journal_log import bind as bind_journal
from assistant.journal_log import reset as reset_journal
from assistant.live_client import ScriptedLiveTransport
from assistant.store import Store
from assistant.transcribe import DictationService

RECOVERED = "Recovered words from the saved audio."


class SilentTransport(ScriptedLiveTransport):
    """The scene-6 wire shape: a healthy link that stays open while the
    model sends zero transcript-family messages. Nothing terminates the
    events() stream — a live session does not end with the turn."""

    name = "silent"

    def __init__(self, *, voice_end: bool = False, family: int = 0):
        super().__init__()
        self._voice_end = voice_end
        self._family = family
        self._sends = 0

    async def send_audio(self, pcm: bytes) -> None:
        self._frames += 1
        self.frames_received += 1
        self._sends += 1

    async def activity_end(self) -> None:
        return None

    async def events(self):
        while True:
            yield await self._queue.get()

    def wire_stats(self):
        return {
            "setup_complete": True, "setup_retries": 0,
            "voice_end": self._voice_end, "transcript_family": self._family,
            "transcript_parts": self._family, "transcript_commits": 0,
            "transcript_dupes": 0, "transcript_snapshots": 0,
            "transcript_commit_reasons": {},
            "types": {"voice_activity": 2, "message": 2}, "samples": [],
            "audio_sent": {"chunks": self._sends, "bytes": self._sends * 960,
                           "format": "audio/pcm", "rate": 16000},
        }


def _service(config, tmp_path):
    config.raw["cleanup"]["enabled"] = False
    config.raw["transcribe"]["inbox_dir"] = str(tmp_path / "inbox")
    config.raw["transcribe"]["copy_to_clipboard"] = False
    store = Store(tmp_path / "stream_h.db")
    svc = DictationService(config, store, None)
    svc.FINAL_TRANSCRIPT_TIMEOUT_S = 0.05
    svc.final_wait_s = 0.6
    svc.final_abandon_grace_s = 0.25
    return svc, store


def _run(config, tmp_path, monkeypatch, *, voice_end, fallback_text,
         fallback_delay_s=0.0, fallback_timeout_s=None):
    svc, store = _service(config, tmp_path)
    if fallback_timeout_s is not None:
        svc.FALLBACK_TIMEOUT_S = fallback_timeout_s
    transport = SilentTransport(voice_end=voice_end)
    fallback_calls = []

    def fallback(*args, **kwargs):
        fallback_calls.append((args, kwargs))
        if fallback_delay_s:
            import time
            time.sleep(fallback_delay_s)
        return Transcript(fallback_text, "en", "gemini_batch")

    monkeypatch.setattr(asr, "transcribe_file", fallback)
    stream = io.StringIO()
    bind_journal(stream)
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=100, silent_frames=0),
            transport_factory=lambda: transport))
    finally:
        reset_journal()
        store.close()
    lines = stream.getvalue()
    return result, lines, fallback_calls


# ------------------------------------------------- both paths, pinned
def test_budget_timeout_fires_the_fallback_and_lands(config, tmp_path,
                                                     monkeypatch):
    """Full-budget expiry (the scene-5 path): the file leg fires and the
    recovered text lands."""
    result, lines, calls = _run(config, tmp_path, monkeypatch,
                                voice_end=False, fallback_text=RECOVERED)
    assert len(calls) == 1, "the fallback leg must fire after a budget timeout"
    assert result.raw_text == RECOVERED
    assert "transcription.landed" in lines
    assert "budget expired" in lines or "timed out" in lines


def test_adaptive_abandon_fires_the_fallback_and_lands(config, tmp_path,
                                                       monkeypatch):
    """The scene-6 path, but with a fallback that answers: abandon →
    file leg → landed. The regression candidate is refuted at code
    level if this passes unchanged."""
    result, lines, calls = _run(config, tmp_path, monkeypatch,
                                voice_end=True, fallback_text=RECOVERED)
    assert len(calls) == 1, \
        "the fallback leg must fire after an adaptive abandon"
    assert result.raw_text == RECOVERED
    assert "transcription.landed" in lines
    assert "adaptive abandon" in lines, \
        "the commit reason must name the abandon, not a bare timeout"


def test_adaptive_abandon_with_empty_fallback_defers_and_keeps_audio(
        config, tmp_path, monkeypatch):
    """abandon-timeout → fallback → deferred: the attempt is made and
    journal-visible, the wav is kept under the deferred-audio contract
    (it must eventually transcribe+answer or be marked never-retried)."""
    result, lines, calls = _run(config, tmp_path, monkeypatch,
                                voice_end=True, fallback_text="")
    assert len(calls) == 1, "even an empty outcome must come from an attempt"
    assert "transcription.deferred" in lines
    assert result.no_final is True
    assert result.audio_path is not None, "the words are data too — keep the wav"
    assert any("fallback returned no transcript" in n for n in result.notes)


def test_budget_timeout_with_empty_fallback_defers_and_keeps_audio(
        config, tmp_path, monkeypatch):
    result, lines, calls = _run(config, tmp_path, monkeypatch,
                                voice_end=False, fallback_text="")
    assert len(calls) == 1
    assert "transcription.deferred" in lines
    assert result.audio_path is not None


def test_the_route_decision_is_journal_visible(config, tmp_path, monkeypatch):
    """H.1 sensor: the journal must say which post-timeout route ran —
    'attempt vs no attempt' is never an inference again."""
    _result, lines, _calls = _run(config, tmp_path, monkeypatch,
                                  voice_end=True, fallback_text=RECOVERED)
    route_line = next(ln for ln in lines.splitlines()
                      if "post_timeout_route" in ln)
    assert " fallback " in route_line
    assert "timeout_kind=adaptive_abandon" in route_line, \
        "the route line must carry the commit reason"
    assert "fallback.outcome" in lines


# --------------------------------------------- W6 (2026-10-31) contract
def test_the_leg_starts_at_voice_end_not_at_abandon(config, tmp_path,
                                                    monkeypatch):
    """W6: the file leg starts speculatively at voice-end — its start
    line must precede the post-timeout route decision (the old flow
    stacked leg-after-abandon: release_to_final 3.59 s wasted)."""
    _result, lines, _calls = _run(config, tmp_path, monkeypatch,
                                  voice_end=True, fallback_text=RECOVERED)
    start = lines.find("fallback.speculative_start")
    route = lines.find("post_timeout_route")
    assert start != -1, "the speculative start must be journal-visible"
    assert route != -1
    assert start < route, "the leg must start at voice-end, before the route"
    assert "fallback.outcome" in lines


def test_a_slow_leg_names_the_timeout_budget_from_voice_end(config, tmp_path,
                                                            monkeypatch):
    """W6 review of FALLBACK_TIMEOUT_S: a leg exceeding its budget names
    the timeout (verdict=timeout) — never a generic error — and the
    budget is documented as running from voice-end."""
    result, lines, calls = _run(
        config, tmp_path, monkeypatch,
        voice_end=True, fallback_text=RECOVERED,
        fallback_delay_s=0.5, fallback_timeout_s=0.1)
    assert len(calls) == 1
    outcome = next(ln for ln in lines.splitlines() if "fallback.outcome" in ln)
    assert "timeout" in outcome.split(), \
        "the outcome line's verdict token must name the timeout"
    assert "budget runs from voice-end" in outcome
    assert "saved-WAV fallback timed out after 0.1s" in " ".join(result.notes)
