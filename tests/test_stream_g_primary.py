"""Stream G (WP1 round 1, owner order 2026-10-27): sensors before fixes.

G.2 — ws.histogram sampling extended to ALL message types (text-only,
≤200 chars, never audio bytes) plus setup/voice_end/transcript_family
evidence, so the scene-6 dump shows the payloads themselves and can pick
the fork: (a) setup lacks whatever enables transcript emission for
gemini-3.5-transcribe-live, or (b) the messages ARE transcript-shaped
and land somewhere we do not parse.

G.6 — latency instrumentation: `audio.first_byte` (playback-start) and
the per-session `latency.table` (release→final, final→reply,
reply→synth, synth→audible, release→audible), so release→AUDIBLE is
measured, never inferred.

Fakes only — no live calls, $0.
"""

from __future__ import annotations

import asyncio
import io
import struct
import time
import types as pytypes

from assistant.daemon import Daemon
from assistant.journal_log import bind as bind_journal
from assistant.live_client import GenaiLiveTransport
from assistant.tts import MockTtsBackend, SpeechService


def _events_named(journal_stream, name: str) -> list[str]:
    return [ln for ln in journal_stream.getvalue().splitlines()
            if ln.split(" ", 6)[2] == name]


def _transport() -> GenaiLiveTransport:
    return GenaiLiveTransport(api_key="test-key-not-used",
                              model="gemini-3.5-transcribe-live")


def _resp(**fields):
    return pytypes.SimpleNamespace(**fields)


# ------------------------------------------------------------------ G.2
def test_histogram_samples_all_message_types_including_parsed():
    tr = _transport()
    tr._note_wire(_resp(
        server_content=pytypes.SimpleNamespace(
            input_transcription=pytypes.SimpleNamespace(text="Four."))))
    tr._note_wire(_resp(voice_activity=pytypes.SimpleNamespace(
        voice_activity_type="ACTIVITY_END", audio_offset="2.5")))
    samples = tr.wire_stats()["samples"]
    joined = " ".join(samples)
    assert "server_content.input_transcription:" in joined   # parsed type sampled
    assert "Four." in joined
    assert "voice_activity:" in joined                        # G.2 extension
    assert "ACTIVITY_END" in joined and "2.5" in joined


def test_voice_end_and_transcript_family_counters():
    tr = _transport()
    assert tr.wire_stats()["voice_end"] is False
    assert tr.wire_stats()["transcript_family"] == 0
    tr._note_wire(_resp(voice_activity=pytypes.SimpleNamespace(
        voice_activity_type="ACTIVITY_START")))
    assert tr.wire_stats()["voice_end"] is False
    tr._note_wire(_resp(voice_activity=pytypes.SimpleNamespace(
        voice_activity_type="ACTIVITY_END")))
    assert tr.wire_stats()["voice_end"] is True
    tr._note_wire(_resp(server_content=pytypes.SimpleNamespace(
        interim_input_transcription=pytypes.SimpleNamespace(text="he"))))
    tr._note_wire(_resp(server_content=pytypes.SimpleNamespace(
        input_transcription=pytypes.SimpleNamespace(text="Hello."))))
    stats = tr.wire_stats()
    assert stats["transcript_family"] == 2


def test_setup_evidence_sensor():
    tr = _transport()
    assert tr.wire_stats()["setup_complete"] is False
    tr._note_setup(pytypes.SimpleNamespace(
        setup_complete=pytypes.SimpleNamespace(session_id="abc123")))
    stats = tr.wire_stats()
    assert stats["setup_complete"] is True
    assert stats["wire_session_id"] == "abc123"
    # The SDK proceeds even when the first message is not setup_complete
    # — the sensor must say so, not crash.
    tr2 = _transport()
    tr2._note_setup(pytypes.SimpleNamespace(setup_complete=None))
    assert tr2.wire_stats()["setup_complete"] is False


def test_samples_never_carry_audio_bytes():
    tr = _transport()
    tr._note_wire(_resp(voice_activity=pytypes.SimpleNamespace(
        voice_activity_type="ACTIVITY_START",
        audio_offset="1.0", blob=b"\x00\x01" * 64)))
    sample = tr.wire_stats()["samples"][0]
    assert "\\x00" not in sample and "b'" not in sample
    assert len(sample) <= 220


# ------------------------------------------------------------------ G.6
class _OkResult:
    returncode = 0
    stdout = b""
    stderr = b""


def test_audio_first_byte_event_and_play_mark(config, journal_stream,
                                              monkeypatch):
    monkeypatch.setattr("assistant.tts.shutil.which",
                        lambda name: f"/usr/bin/{name}")
    config.raw["tts"]["online_voice"] = "local"

    def runner(argv, **kwargs):
        return _OkResult()

    service = SpeechService(config, backend=MockTtsBackend(),
                            player_runner=runner)
    result = service.speak("Four.", play=True, session_id="sess42")
    assert result.played is True
    assert result.synth_mark is not None and result.play_mark is not None
    assert result.play_mark >= result.synth_mark
    first = _events_named(journal_stream, "audio.first_byte")
    assert first, journal_stream.getvalue()
    assert "sess42" in first[0]
    assert "player=" in first[0] and "since_synth_s=" in first[0]
    # no session_id -> no event (acks keep their own events)
    journal_stream.truncate(0)
    journal_stream.seek(0)
    service.speak("Four.", play=True)
    assert not _events_named(journal_stream, "audio.first_byte")


def test_latency_table_stages_and_legs(config, journal_stream):
    daemon = Daemon(config)
    try:
        now = time.monotonic()
        daemon._stage("s1", "release", now)
        daemon._stage("s1", "final", now + 1.0)
        daemon._stage("s1", "reply", now + 1.5)
        daemon._stage("s1", "synth", now + 3.0)
        daemon._stage("s1", "audible", now + 3.4)
        daemon._emit_latency_table("s1")
        lines = _events_named(journal_stream, "latency.table")
        assert lines, journal_stream.getvalue()
        detail = lines[0]
        assert "release_to_final_s=1.0" in detail
        assert "final_to_reply_s=0.5" in detail
        assert "reply_to_synth_s=1.5" in detail
        assert "synth_to_audible_s=0.4" in detail
        assert "release_to_audible_s=3.4" in detail
        assert "missing=" not in detail
    finally:
        daemon.store.close()


def test_latency_table_waits_for_pending_reply_speech(config, journal_stream):
    daemon = Daemon(config)
    try:
        now = time.monotonic()
        daemon._stage("s2", "release", now)
        daemon._stage("s2", "final", now + 1.0)
        daemon._stage("s2", "reply", now + 1.5)
        daemon._emit_latency_table("s2")      # speech pending -> silent
        assert not _events_named(journal_stream, "latency.table")
        daemon._emit_latency_table("s2", final=True)   # speech done (muted)
        lines = _events_named(journal_stream, "latency.table")
        assert lines and "missing=synth,audible" in lines[0]
    finally:
        daemon.store.close()


def test_latency_table_backstop_for_no_reply_sessions(config, journal_stream):
    daemon = Daemon(config)
    try:
        now = time.monotonic()
        daemon._stage("s3", "release", now)
        daemon._stage("s3", "final", now + 12.0)
        daemon._emit_latency_table("s3")      # no reply ever -> emits
        lines = _events_named(journal_stream, "latency.table")
        assert lines and "release_to_final_s=12.0" in lines[0]
        assert "missing=reply,synth,audible" in lines[0]
    finally:
        daemon.store.close()


# ------------------------------------------------- final_mark rides the result
def test_final_mark_rides_the_dictation_result(config, journal_stream,
                                               tmp_path):
    """release→final must be measurable: the flush stamps final_mark on
    the SessionResult at final.received / final.timeout time."""
    from assistant.capture import SAMPLE_RATE
    from assistant.config import load_config
    from assistant.live_client import LiveEvent, ScriptedLiveTransport
    from assistant.store import Store
    from assistant.transcribe import DictationService

    class _WireTransport(ScriptedLiveTransport):
        async def activity_end(self) -> None:
            await self._queue.put(LiveEvent("final", text="Four."))
            await self._queue.put(LiveEvent("turn_complete"))

    journal = io.StringIO()
    bind_journal(journal)
    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {
        **config.raw.get("transcribe", {}),
        "inbox_dir": str(tmp_path / "inbox"),
        "final_wait_s": 0.5,
    }
    store = Store(tmp_path / "g6.db")
    service = DictationService(config, store, None)

    frame_samples = SAMPLE_RATE * 30 // 1000
    frame = struct.pack(f"<{frame_samples}h", *([6000] * frame_samples))

    class _Source:
        async def frames(self):
            for _ in range(20):
                yield frame

        async def aclose(self):
            return None

    before = time.monotonic()
    result = asyncio.run(service.dictate(
        _Source(), transport_factory=_WireTransport, mode="narration"))
    after = time.monotonic()
    assert result.final_mark is not None
    assert before <= result.final_mark <= after
    store.close()
