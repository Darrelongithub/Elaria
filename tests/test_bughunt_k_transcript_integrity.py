"""BH-K1/K2/K3 — transcript integrity: user words are never wiped or swapped.

K1: a post-persist FILLER_PHRASES substring check in DictationService.dictate
    replaced the returned SessionResult with an empty one AFTER the transcript
    had been stored. Dictating an email sign-off returned nothing.
K2: Daemon._is_echo returned True on TIMING alone (transcript finished while
    an ack was playing) or on filler substrings, and _finish_dictation wiped
    the text. Real protection is a textual comparison with what she actually
    said — strip her words, keep the user's.
K3: a Live session that committed all segments DURING speech, then answered
    activity_end with turn_complete (or nothing), was judged "terminal
    missing" and the saved-WAV batch result OVERWROTE the good Live finals.

The SDK double keeps receive()'s one-model-turn scope, like test_bug6f.
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from assistant import asr
from assistant.asr import Transcript
from assistant.capture import SimulatedCapture
from assistant.daemon import Daemon
from assistant.live_client import GenaiLiveTransport, LiveEvent
from assistant.store import Store
from assistant.transcribe import DictationService

FILLER_EMAIL = ("Dear team, the quarterly figures are attached. "
                "Let me know how I can help with the board pack.")
LIVE_TEXT = "Please save the user's complete sentence."
BATCH_TEXT = "WRONG batch redo text"


def message(**content):
    return NS(server_content=NS(**content))


class SDKSession:
    """receive() ends at turn_complete, NOT at the end of the connection."""

    def __init__(self, *, commit_during_speech=None, on_end=()):
        self.commit_during_speech = commit_during_speech
        self.on_end = list(on_end)
        self.queue = asyncio.Queue()
        self.sent = []
        self._committed = False

    async def send_realtime_input(self, **kwargs):
        self.sent.append(kwargs)
        if "audio" in kwargs and self.commit_during_speech and not self._committed:
            self._committed = True
            await self.queue.put(message(
                input_transcription=NS(text=self.commit_during_speech)))
        if "activity_end" in kwargs:
            for response in self.on_end:
                await self.queue.put(response)

    async def receive(self):
        while True:
            response = await self.queue.get()
            if response is None:
                return
            yield response
            if getattr(response.server_content, "turn_complete", False):
                return


@pytest.fixture
def sdk_transport(monkeypatch):
    def make(session, model="gemini-3.5-transcribe-live"):
        class Context:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *args):
                return None

        client = NS(aio=NS(live=NS(connect=lambda **kw: Context())))
        types = NS(
            LiveConnectConfig=NS, AudioTranscriptionConfig=NS,
            RealtimeInputConfig=NS, AutomaticActivityDetection=NS,
            SessionResumptionConfig=NS, Modality=NS(TEXT="TEXT"),
            ActivityStart=NS, ActivityEnd=NS, Blob=NS,
        )
        genai = NS(Client=lambda **kw: client, types=types, __version__="test-sdk")
        monkeypatch.setitem(sys.modules, "google", NS(genai=genai))
        monkeypatch.setitem(sys.modules, "google.genai", genai)
        return GenaiLiveTransport("test-key-not-a-credential", model)

    return make


def service(config, tmp_path):
    config.raw["cleanup"]["enabled"] = False
    config.raw["transcribe"]["inbox_dir"] = str(tmp_path / "inbox")
    config.raw["transcribe"]["copy_to_clipboard"] = False
    store = Store(tmp_path / "k.db")
    svc = DictationService(config, store, None)
    svc.FINAL_TRANSCRIPT_TIMEOUT_S = 0.05  # fail fast, never a hardware wait
    return svc, store


def no_batch(monkeypatch):
    calls = []

    def fallback(*args, **kwargs):
        calls.append(args)
        return Transcript(BATCH_TEXT, "en", "gemini_batch")

    monkeypatch.setattr(asr, "transcribe_file", fallback)
    return calls


# ---------------------------------------------------------------------------
# BH-K1 — dictating text that merely CONTAINS a filler phrase is the user's
# ---------------------------------------------------------------------------

def test_dictated_email_with_filler_signoff_is_kept(
        config, tmp_path, monkeypatch, sdk_transport):
    session = SDKSession(on_end=[message(
        input_transcription=NS(text=FILLER_EMAIL))])
    svc, store = service(config, tmp_path)
    calls = no_batch(monkeypatch)
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=60, silent_frames=0),
            transport_factory=lambda: sdk_transport(session)))
        # W6 (2026-10-31): at most the one discarded speculative voice-end
        # call may occur (the final arrives after voice-end here) — BH-K1
        # is proven by raw_text below surviving untouched.
        assert len(calls) <= 1
        assert result.raw_text == FILLER_EMAIL, (
            "the user's own words must survive a substring that resembles "
            "her filler — she never said them, he dictated them")
        assert result.transcript_id is not None
        assert result.inbox_path and FILLER_EMAIL in Path(result.inbox_path).read_text()
        assert store.recent_transcripts(1)[0]["raw_text"] == FILLER_EMAIL
        assert result.clipboard.get("reason") != "echo filtered"
    finally:
        store.close()


# ---------------------------------------------------------------------------
# BH-K3 — committed Live finals are never overwritten by the batch redo
# ---------------------------------------------------------------------------

def test_turn_complete_only_with_uncommitted_tail_recovers_via_batch(
        config, tmp_path, monkeypatch, sdk_transport):
    """Speech continues after the last committed segment; activity_end is
    answered with turn_complete only. On this model a committed segment
    can arrive AFTER turn_complete (test_bug6f), so the boundary does NOT
    certify the tail was transcribed: with speech unaccounted for, the
    saved-WAV recovery runs rather than silently truncating. The parser
    must still SURFACE the boundary (visible in diagnostics/fixtures)."""
    session = SDKSession(commit_during_speech=LIVE_TEXT,
                         on_end=[message(turn_complete=True)])
    svc, store = service(config, tmp_path)
    calls = no_batch(monkeypatch)
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=60, silent_frames=0),
            transport_factory=lambda: sdk_transport(session)))
        assert len(calls) == 1, (
            "speech after the last final + no post-release final = the "
            "Live text is provably incomplete; recover from the WAV")
        assert result.raw_text == BATCH_TEXT
        assert result.backend == "gemini_batch"
        assert any("may be incomplete" in n for n in result.notes)
        summary = next(json.loads(r["detail"]) for r in
                       store.list_persona_events(kind="dictate.lifecycle", limit=200)
                       if json.loads(r["detail"])["step"] == "dictate.live_receive_summary")
        assert summary["event_counts"].get("turn_complete") == 1, (
            "the boundary must be surfaced in diagnostics, not swallowed")
    finally:
        store.close()


def test_pause_then_release_silence_after_end_keeps_live(
        config, tmp_path, monkeypatch):
    """All speech committed BEFORE release (user paused, the segment
    landed, then release); the server answers activity_end with silence.
    A bare timeout is not evidence of incompleteness when no speech
    followed the last final: keep Live, no batch. (The converse — speech
    after the last final plus no terminal — stays a batch recovery; see
    test_bug6f's earlier-segment test.)"""
    first_collected = asyncio.Event()
    svc, store = service(config, tmp_path)
    calls = no_batch(monkeypatch)

    class Transport:
        def __init__(self):
            self.queue = asyncio.Queue()
            self._committed = False

        async def connect(self, resumption_handle=None):
            pass

        async def activity_start(self):
            pass

        async def send_audio(self, pcm):
            if not self._committed:
                self._committed = True
                await self.queue.put(LiveEvent("final", text=LIVE_TEXT))

        async def activity_end(self):
            pass  # the server says nothing more, ever

        async def events(self):
            while True:
                event = await self.queue.get()
                yield event
                first_collected.set()

        async def close(self):
            pass

    speech = struct.pack("<480h", *([6000] * 480))
    silence = b"\x00\x00" * 480

    class Source:
        async def frames(self):
            yield speech
            await first_collected.wait()
            for _ in range(5):  # trailing pause only; then release
                yield silence

        async def aclose(self):
            pass

    try:
        result = asyncio.run(svc.dictate(Source(), transport_factory=Transport))
        assert calls == [], (
            "no speech followed the last committed segment, so there is "
            "nothing for a batch redo to recover")
        assert result.raw_text == LIVE_TEXT
        assert result.backend == "gemini_live"
        assert any("no speech" in n and "kept" in n for n in result.notes), (
            "the anomaly must be stated, just not acted on destructively")
    finally:
        store.close()


def test_no_finals_at_all_still_uses_batch_fallback(
        config, tmp_path, monkeypatch, sdk_transport):
    """Control: with NO committed text, the saved-WAV fallback still runs."""
    session = SDKSession(commit_during_speech=None,
                         on_end=[message(turn_complete=True)])
    svc, store = service(config, tmp_path)
    calls = no_batch(monkeypatch)
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=60, silent_frames=0),
            transport_factory=lambda: sdk_transport(session)))
        assert len(calls) == 1
        assert result.raw_text == BATCH_TEXT
    finally:
        store.close()


# ---------------------------------------------------------------------------
# BH-K2 — echo judgement compares TEXT with what she said, never timing
# ---------------------------------------------------------------------------

@pytest.fixture
def daemon(config):
    d = Daemon(config)
    try:
        yield d
    finally:
        d.store.close()


def test_echo_requires_textual_match_not_timing(daemon):
    daemon._set_speaking(True, text="On it.")
    assert daemon.is_speaking()
    user = "Remind me to call the Nairobi office tomorrow morning"
    assert daemon._is_echo(user) is False, (
        "finishing while an ack plays is not evidence of echo")
    assert daemon._strip_self_echo(user) == user


def test_echo_prefix_is_stripped_user_words_kept(daemon):
    daemon._set_speaking(True, text="On it.")
    daemon._speaking_until = 0.0
    assert daemon._strip_self_echo(
        "On it. Remind me to call the clinic") == "Remind me to call the clinic"
    assert daemon._strip_self_echo("On it.") == ""
    assert daemon._is_echo("On it.") is True
    assert daemon._is_echo("On it. Remind me to call the clinic") is False


def test_filler_sounding_user_text_she_did_not_say_is_not_echo(daemon):
    daemon._set_speaking(True, text="Saved to your inbox.")
    daemon._speaking_until = 0.0
    user = "Let me know how I can reach you about the invoice"
    assert daemon._is_echo(user) is False
    assert daemon._strip_self_echo(user) == user


def test_partial_echo_of_her_sentence_is_echo_short_reply_is_not(daemon):
    daemon._set_speaking(True, text="No. Not at this hour.")
    daemon._speaking_until = 0.0
    assert daemon._is_echo("No. Not at this hour.") is True
    assert daemon._is_echo("not at this hour") is True
    # BH-I5 stays true: a one-word reply is the user's, even if she said it.
    assert daemon._is_echo("No.") is False


async def _finished(value):
    return value


def test_finish_dictation_keeps_text_that_lands_during_ack(daemon):
    session = NS(
        cleaned_text=None, flagged=False,
        raw_text="Call the clinic tomorrow morning",
        backend="gemini_live", inbox_path=None, audio_path=None,
        clipboard={"copied": False}, confidence=None,
        cloud_status="complete", queued_job_ids=[],
        connectivity_mode="online", notes=[], session_id="k2sess",
        duration_s=1.2, no_speech=False, no_final=False, capture=None)
    daemon._set_speaking(True, text="On it.")  # ack still playing at landing

    async def run():
        task = asyncio.create_task(_finished(session))
        await daemon._finish_dictation(task, {}, "k2sess", "narration")

    asyncio.run(run())
    result = daemon._ptt_results["k2sess"]
    assert result["text"] == "Call the clinic tomorrow morning", (
        "a real dictation must not be wiped because it finished inside "
        "the ack window")
    assert not result.get("echo_suppressed")


def test_finish_dictation_strips_only_her_words_from_prefix(daemon):
    session = NS(
        cleaned_text=None, flagged=False,
        raw_text="On it. Call the clinic tomorrow morning",
        backend="gemini_live", inbox_path=None, audio_path=None,
        clipboard={"copied": False}, confidence=None,
        cloud_status="complete", queued_job_ids=[],
        connectivity_mode="online", notes=[], session_id="k2sess2",
        duration_s=1.6, no_speech=False, no_final=False, capture=None)
    daemon._set_speaking(True, text="On it.")

    async def run():
        task = asyncio.create_task(_finished(session))
        await daemon._finish_dictation(task, {}, "k2sess2", "narration")

    asyncio.run(run())
    result = daemon._ptt_results["k2sess2"]
    assert result["text"] == "Call the clinic tomorrow morning"
    assert result["raw_text"] == "On it. Call the clinic tomorrow morning", (
        "raw_text is the ASR record (it matches the stored row); only the "
        "shown/routed text loses her words")
