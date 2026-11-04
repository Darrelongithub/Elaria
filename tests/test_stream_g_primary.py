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


# ============================================================ G.3 (fix)
def test_build_config_matches_documented_manual_vad_shape():
    """G.1 named two setup deviations; G.3 removed them. The config is
    now field-for-field the docs' Manual VAD example (plus the optional
    rotation handle the docs' base example omits entirely)."""
    config = GenaiLiveTransport._build_config()
    assert [getattr(m, "value", m)
            for m in config.response_modalities] == ["TEXT"]
    aad = config.realtime_input_config.automatic_activity_detection
    assert aad.disabled is True
    assert config.input_audio_transcription.language_codes == []
    assert config.input_audio_transcription.mode is None   # VERBATIM default
    assert config.session_resumption is None               # was always-on {}
    # a rotation handle rides ONLY when one exists
    config2 = GenaiLiveTransport._build_config("handle-7")
    assert config2.session_resumption.handle == "handle-7"


def test_missing_setup_complete_takes_one_fresh_session():
    """The SDK proceeds when its first message is not setup_complete;
    the Enterprise docs say audio-before-setup yields empty
    transcriptions. Missing setup -> ONE retry, then proceed with the
    evidence recorded honestly."""
    class _Session:
        def __init__(self, setup):
            self.setup_complete = setup

    class _Ctx:
        def __init__(self, session):
            self._session = session
            self.entered = 0
            self.exited = False

        async def __aenter__(self):
            self.entered += 1
            return self._session

        async def __aexit__(self, *exc):
            self.exited = True

    class _Live:
        def __init__(self, ctxs):
            self._ctxs = list(ctxs)
            self.calls = 0

        def connect(self, model=None, config=None):
            self.calls += 1
            return self._ctxs.pop(0)

    def scenario(ctxs):
        tr = _transport()
        live = _Live(ctxs)
        aio = pytypes.SimpleNamespace(live=live)
        tr._client = pytypes.SimpleNamespace(aio=aio)

        async def drive():
            await tr.connect()
            stats = tr.wire_stats()
            await tr.close()
            return stats

        return asyncio.run(drive()), live

    good = _Ctx(_Session(pytypes.SimpleNamespace(session_id="ok1")))
    bad = _Ctx(_Session(None))
    stats, live = scenario([bad, good])
    assert stats["setup_complete"] is True
    assert stats["setup_retries"] == 1
    assert bad.entered == 1 and bad.exited is True
    assert good.entered == 1
    assert live.calls == 2

    # both sessions missing setup -> proceed on the retry, evidence says so
    first, second = _Ctx(_Session(None)), _Ctx(_Session(None))
    stats2, live2 = scenario([first, second])
    assert stats2["setup_complete"] is False
    assert stats2["setup_retries"] == 1
    assert live2.calls == 2


# ============================================================ G.4 (fix)
class _WireTransportDouble:
    def __init__(self, voice_end=True, family=0):
        self._stats = {"voice_end": voice_end, "transcript_family": family}

    def wire_stats(self):
        return dict(self._stats)


def _service(tmp_path, *, final_wait_s, grace_s):
    from assistant.config import load_config
    from assistant.store import Store
    from assistant.transcribe import DictationService

    config = load_config()
    config.raw["transcribe"] = {
        **config.raw.get("transcribe", {}),
        "inbox_dir": str(tmp_path / "inbox"),
        "final_wait_s": final_wait_s,
        "final_abandon_grace_s": grace_s,
    }
    store = Store(tmp_path / "g4.db")
    return DictationService(config, store, None), store


def test_adaptive_abandon_cuts_the_dead_wait(tmp_path):
    service, store = _service(tmp_path, final_wait_s=5.0, grace_s=0.3)
    try:
        async def drive():
            collector = asyncio.create_task(asyncio.sleep(999))
            terminal = asyncio.Event()   # never fires
            started = time.monotonic()
            try:
                await service._wait_final_adaptive(
                    collector, terminal, _WireTransportDouble())
            except TimeoutError as exc:
                return time.monotonic() - started, str(exc)
            finally:
                collector.cancel()
            raise AssertionError("expected TimeoutError")

        elapsed, message = asyncio.run(drive())
        assert "adaptive abandon" in message, message
        assert "no transcript family" in message, message
        assert elapsed < 2.0, f"grace 0.3s must not burn the 5s budget ({elapsed})"
    finally:
        store.close()


def test_adaptive_abandon_spared_while_transcripts_flow(tmp_path):
    service, store = _service(tmp_path, final_wait_s=0.6, grace_s=0.1)
    try:
        async def drive():
            collector = asyncio.create_task(asyncio.sleep(999))
            terminal = asyncio.Event()   # never fires
            started = time.monotonic()
            try:
                await service._wait_final_adaptive(
                    collector, terminal,
                    _WireTransportDouble(voice_end=True, family=2))
            except TimeoutError as exc:
                return time.monotonic() - started, str(exc)
            finally:
                collector.cancel()
            raise AssertionError("expected TimeoutError")

        elapsed, message = asyncio.run(drive())
        assert "budget expired after 0.6s" in message, message
        assert "adaptive" not in message
        assert elapsed >= 0.5, f"transcripts flowing keeps the budget ({elapsed})"
    finally:
        store.close()


def test_adaptive_wait_returns_when_the_final_arrives(tmp_path):
    service, store = _service(tmp_path, final_wait_s=5.0, grace_s=0.2)
    try:
        async def drive():
            collector = asyncio.create_task(asyncio.sleep(999))
            terminal = asyncio.Event()

            async def later():
                await asyncio.sleep(0.3)
                terminal.set()

            ticker = asyncio.create_task(later())
            started = time.monotonic()
            try:
                # transcripts are flowing (family>0) — the watcher stays
                # quiet and the arriving final returns the wait promptly.
                await service._wait_final_adaptive(
                    collector, terminal,
                    _WireTransportDouble(voice_end=True, family=1))
            finally:
                collector.cancel()
                ticker.cancel()
            return time.monotonic() - started

        elapsed = asyncio.run(drive())
        assert elapsed < 2.0, "a real final returns promptly, not after the budget"
    finally:
        store.close()
