"""M-5 stump sensor (mini order M, 2026-10-31): a landed transcript that
is a stump gets its own schema line — `transcription.stump` — carrying the
class, the char count and sha16 of the text, NEVER the text itself.

W1 root cause: both kept wavs landed the literal token `<noise>` (7 chars
of a 29-char sentence) and the journal only said "7 chars committed" —
nothing named the stump class. The sensor is the visibility half of the
fallback-as-primary chain: every landed transcript either answers or is
class-marked in one read.

Evidence: [TESTED-ONLY] — journal + dictate/file-service seams with fakes.
"""

from __future__ import annotations

import asyncio
import io
import wave

from assistant import asr
from assistant.asr import Transcript
from assistant.capture import SimulatedCapture
from assistant.journal_log import (
    STUMP_MAX_CHARS,
    bind as bind_journal,
    log_transcription_stump,
    reset as reset_journal,
    stump_verdict,
)
from assistant.live_client import ScriptedLiveTransport
from assistant.store import Store
from assistant.transcribe import DictationService


# -- the detector -----------------------------------------------------------

def test_noise_token_is_a_stump_of_the_noise_class():
    kind, chars, digest = stump_verdict("<noise>")
    assert kind == "noise_token"
    assert chars == 7
    assert len(digest) == 16
    # the hash is stable and content-derived (sha256 prefix of the text)
    assert digest == stump_verdict("<noise>")[2]
    assert stump_verdict("[Noise].")[0] == "noise_token"
    assert stump_verdict("  <SILENCE>  ")[0] == "noise_token"
    assert stump_verdict("music")[0] == "noise_token"
    assert stump_verdict("(background noise)")[0] == "noise_token"


def test_short_landed_text_is_a_short_stump():
    kind, chars, _ = stump_verdict("Yes.")
    assert kind == "short_stump" and chars == 4
    assert stump_verdict("OK, do it")[0] == "short_stump"   # 9 < 12
    assert stump_verdict("hi" * 5)[0] == "short_stump"      # 10 < 12
    assert STUMP_MAX_CHARS == 12


def test_real_sentences_and_empty_text_are_not_stumps():
    assert stump_verdict("Hello, Elaria.") is None            # 14 chars
    assert stump_verdict("Recovered words from the saved audio.") is None
    assert stump_verdict("") is None                          # deferred owns it
    assert stump_verdict("   ") is None


# -- the schema line --------------------------------------------------------

def test_stump_line_carries_class_chars_and_sha16_never_the_text(
        journal_stream):
    assert log_transcription_stump("sess1", "<noise>", source="dictate")
    line = journal_stream.getvalue()
    assert "transcription.stump" in line
    assert "sess1" in line
    assert "noise_token" in line.split()
    assert "chars=7" in line
    assert "sha16=" in line
    assert "source=dictate" in line
    assert "<noise>" not in line, "the text itself must never ride the line"


def test_healthy_transcript_logs_no_stump_line(journal_stream):
    text = "Recovered words from the saved audio."
    assert log_transcription_stump("sess2", text, source="dictate") is False
    assert journal_stream.getvalue() == ""


# -- wiring: the dictate land point ----------------------------------------

class _SilentTransport(ScriptedLiveTransport):
    name = "silent"

    def __init__(self):
        super().__init__()
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
            "setup_complete": True, "setup_retries": 0, "voice_end": False,
            "transcript_family": 0, "transcript_parts": 0,
            "transcript_commits": 0, "transcript_dupes": 0,
            "transcript_snapshots": 0, "transcript_commit_reasons": {},
            "types": {}, "samples": [],
            "audio_sent": {"chunks": self._sends, "bytes": self._sends * 960,
                           "format": "audio/pcm", "rate": 16000},
        }


def _dictate(config, tmp_path, monkeypatch, fallback_text):
    config.raw["cleanup"]["enabled"] = False
    config.raw["transcribe"]["inbox_dir"] = str(tmp_path / "inbox")
    config.raw["transcribe"]["copy_to_clipboard"] = False
    store = Store(tmp_path / "stump.db")
    svc = DictationService(config, store, None)
    svc.FINAL_TRANSCRIPT_TIMEOUT_S = 0.05
    svc.final_wait_s = 0.6
    svc.final_abandon_grace_s = 0.25
    monkeypatch.setattr(
        asr, "transcribe_file",
        lambda *a, **k: Transcript(fallback_text, "en", "gemini_batch"))
    stream = io.StringIO()
    bind_journal(stream)
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=100, silent_frames=0),
            transport_factory=lambda: _SilentTransport()))
    finally:
        reset_journal()
        store.close()
    return result, stream.getvalue()


def test_dictate_landing_a_stump_logs_the_sensor(config, tmp_path,
                                                 monkeypatch):
    result, lines = _dictate(config, tmp_path, monkeypatch, "<noise>")
    assert result.raw_text == "<noise>"
    assert "transcription.landed" in lines
    assert "transcription.stump" in lines
    assert "noise_token" in lines
    assert "chars=7" in lines


def test_dictate_landing_a_real_sentence_logs_no_stump(config, tmp_path,
                                                       monkeypatch):
    result, lines = _dictate(
        config, tmp_path, monkeypatch,
        "Recovered words from the saved audio.")
    assert "transcription.landed" in lines
    assert "transcription.stump" not in lines


# -- wiring: the file-service land point ------------------------------------

def _wav(path):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x01\x00" * 1600)
    return path


def test_transcribe_file_landing_a_stump_logs_the_sensor(config, tmp_path,
                                                         monkeypatch):
    config.raw["cleanup"]["enabled"] = False
    config.raw["transcribe"]["inbox_dir"] = str(tmp_path / "inbox")
    config.raw["transcribe"]["copy_to_clipboard"] = False
    store = Store(tmp_path / "stump2.db")
    svc = DictationService(config, store, None)
    monkeypatch.setattr(
        asr, "transcribe_file",
        lambda *a, **k: Transcript("<noise>", "en", "gemini_batch"))
    stream = io.StringIO()
    bind_journal(stream)
    try:
        result = asyncio.run(svc.transcribe_file(_wav(tmp_path / "x.wav")))
    finally:
        reset_journal()
        store.close()
    assert result.raw_text == "<noise>"
    lines = stream.getvalue()
    assert "transcription.stump" in lines
    assert "source=transcribe_file" in lines
    assert "noise_token" in lines
