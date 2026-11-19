"""M-4 streaming TTS (mini order M, 2026-10-31): G.7.3 authorized now.

The W6 whale (session 94129e: reply_to_synth 11.77 s) is synthesized-but-
unheard time. These pins cover the G.7.3(i) chunked playback queue (PCM
sliced ~50 ms / 2,400 B at 24 kHz into a raw-PCM player's stdin; playback
starts at the FIRST slice; interrupt = drain + flag + cutoff), the
first-audible-at-slice latency stage, and the G.7.3(ii) early dispatch
(chat starts the moment the transcription leg lands — the cleanup model
call and persist no longer sit between final text and reply generation).

Evidence: [TESTED-ONLY] — fake processes and fake voice clients; the
latency scene card (design chat) is the owner-ear proof. Player argvs are
[UNVERIFIED-argv] until hardware: spawn failure falls back to whole-wav
playback by construction (the wav is always written).
"""

from __future__ import annotations

import asyncio
import io

from assistant.asr import Transcript
from assistant.capture import SimulatedCapture
from assistant.journal_log import bind as bind_journal
from assistant.journal_log import reset as reset_journal
from assistant.live_client import ScriptedLiveTransport
from assistant.store import Store
from assistant.transcribe import DictationService, SessionResult
from assistant.tts import (
    SLICE_SECONDS,
    ChunkedPlayback,
    SpeechService,
    raw_stream_candidates,
)

RATE = 24000
SLICE = 2400  # bytes: 50 ms of s16le mono at 24 kHz (the G.7.3 brief)


# ------------------------------------------------------- fakes
class _FakeStdin:
    def __init__(self):
        self.written = bytearray()
        self.closed = False

    def write(self, data):
        if self.closed:
            raise ValueError("write to closed pipe")
        self.written.extend(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _FakeProc:
    def __init__(self, argv, **kwargs):
        self.argv = argv
        self.stdin = _FakeStdin()
        self.returncode = 0
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.stdin.close()

    def kill(self):
        self.killed = True


class _BrokenStdin(_FakeStdin):
    def write(self, data):
        raise BrokenPipeError("player died")


class _BrokenProc(_FakeProc):
    def __init__(self, argv, **kwargs):
        super().__init__(argv, **kwargs)
        self.stdin = _BrokenStdin()


class _DyingStdin(_FakeStdin):
    """Accepts the first slice (the ear gets it), then the pipe breaks."""

    def __init__(self):
        super().__init__()
        self.writes = 0

    def write(self, data):
        self.writes += 1
        if self.writes > 1:
            raise BrokenPipeError("player died mid-stream")
        super().write(data)


class _DyingProc(_FakeProc):
    def __init__(self, argv, **kwargs):
        super().__init__(argv, **kwargs)
        self.stdin = _DyingStdin()
        self.returncode = 1   # a dead player exits non-zero


def _player(candidates=None, *, popen=None, session_id="s1"):
    return ChunkedPlayback(
        candidates or [["paplay", "--raw"]], rate=RATE,
        session_id=session_id, popen_factory=popen or _FakeProc)


# ------------------------------------------------------- the slice queue
def test_slices_are_50ms_and_first_slice_marks_once():
    seen = []

    def popen(argv, **kwargs):
        proc = _FakeProc(argv, **kwargs)
        seen.append(proc)
        return proc

    player = _player(popen=popen)
    assert player.slice_bytes == SLICE == 2400
    assert SLICE_SECONDS == 0.05
    player.feed(b"\x01" * 1200)            # half a slice — nothing yet
    assert player.first_slice_mark is None
    assert not seen, "no slice completed — the player must not spawn yet"
    player.feed(b"\x02" * 1200)            # slice completes -> first write
    assert player.first_slice_mark is not None
    player.feed(b"\x03" * 2400)            # exact second slice
    detail = player.close()
    assert detail["played"] is True
    assert seen[0].stdin.written[:SLICE] == b"\x01" * 1200 + b"\x02" * 1200
    assert bytes(seen[0].stdin.written[SLICE:]) == b"\x03" * 2400
    assert seen[0].stdin.closed


def test_tail_slice_flushes_on_close():
    proc = _FakeProc([], stdin=None)

    def popen(argv, **kwargs):
        return proc

    player = _player(popen=popen)
    player.feed(b"\x01" * 3000)            # one full slice + 600 tail
    assert len(proc.stdin.written) == SLICE
    player.close()
    assert len(proc.stdin.written) == SLICE + 600, "tail must flush at close"


def test_close_reports_player_failure_honestly():
    def popen(argv, **kwargs):
        proc = _FakeProc(argv, **kwargs)
        proc.returncode = 1
        return proc

    player = _player(popen=popen)
    player.feed(b"\x01" * SLICE)
    detail = player.close()
    assert detail["played"] is False
    assert "exited 1" in detail["error"]


def test_interrupt_drains_flags_and_cuts_off_under_100ms():
    proc = _FakeProc([], stdin=None)
    player = _player(popen=lambda a, **k: proc)
    player.feed(b"\x01" * SLICE)
    assert player.first_slice_mark is not None
    result = player.interrupt()
    assert result["interrupted"] is True
    assert result["cutoff_ms"] < 100, \
        "the G.7.3(i) contract: a drained queue cuts off in < 100 ms"
    assert proc.stdin.closed
    assert proc.terminated or proc.killed
    # drained + flagged: further synthesis chunks are dropped, never played
    before = len(proc.stdin.written)
    player.feed(b"\x02" * SLICE * 4)
    assert len(proc.stdin.written) == before
    assert player.interrupted


def test_sink_never_raises_on_a_dead_player():
    player = _player(popen=_BrokenProc)
    player.feed(b"\x01" * SLICE)           # BrokenPipeError swallowed
    player.feed(b"\x02" * SLICE)           # dropped, still silent
    detail = player.close()
    assert detail["played"] is False
    assert detail["error"]


def test_first_byte_event_names_the_slice():
    from assistant.journal_log import bind, reset

    stream = io.StringIO()
    bind(stream)
    try:
        player = _player(session_id="sess7")
        player.feed(b"\x01" * SLICE)
        player.close()
        player2 = _player(session_id=None)
        player2.feed(b"\x01" * SLICE)
        player2.close()
    finally:
        reset()
    lines = stream.getvalue()
    assert "audio.first_byte" in lines
    assert "at=slice" in lines
    assert "sess7" in lines
    assert lines.count("audio.first_byte") == 1, \
        "acks (no session_id) keep their own events"


def test_raw_candidates_cover_the_known_stdin_contracts():
    paplay, pwcat, aplay = raw_stream_candidates(24000)
    assert paplay[0] == "paplay" and "--raw" in paplay
    assert pwcat[0] == "pw-cat" and pwcat[-1] == "-"
    assert aplay[0] == "aplay" and "raw" in aplay and "-t" in aplay


# ------------------------------------------------------- SpeechService
class _VoiceClient:
    """Fake cloud voice: streams 3 slices through on_chunk, returns full pcm."""

    def __init__(self):
        self.calls = []
        self.chunks = 3

    def can_speak(self):
        return True

    def voice_request(self, text, *, voice=None):
        return {"voice_allowed": True, "voice_name": "Flare",
                "voice_requested": "Flare", "canonical_voices": ["Flare"],
                "model": "gemini-3.8-live"}

    def generate_voice(self, text, *, correlation_id="-", on_chunk=None):
        self.calls.append({"text": text, "on_chunk": on_chunk})
        pcm = b"\x01\x00" * (SLICE // 2 * self.chunks)
        if on_chunk is not None:
            for i in range(0, len(pcm), SLICE):
                on_chunk(pcm[i:i + SLICE])
        return {"pcm": pcm, "sample_rate": RATE, "voice_name": "Flare",
                "usage": {}}


class _StrictVoiceClient(_VoiceClient):
    """Old-style fake: generate_voice has NO on_chunk parameter — proves the
    kwarg rides only when streaming is active (old fakes stay valid)."""

    def generate_voice(self, text, *, correlation_id="-"):
        return super().generate_voice(text, correlation_id=correlation_id)


def _service(config, monkeypatch, client, *, popen=None, which=True):
    if which:
        monkeypatch.setattr("assistant.tts.shutil.which",
                            lambda name: f"/usr/bin/{name}")
    return SpeechService(config, client=client, is_online=lambda: True,
                         popen_factory=popen or _FakeProc)


def _gemini_voice_config(config):
    config.raw.setdefault("tts", {})["online_voice"] = "gemini"
    config.raw.setdefault("gemini", {})["voice"] = "Flare"
    config.raw["gemini"]["allowed_voices"] = ["Flare"]
    config.raw["gemini"]["gemini_voice_model"] = "gemini-3.8-live"


def test_speak_streams_and_first_slice_is_first_audible(config, monkeypatch,
                                                        tmp_path):
    _gemini_voice_config(config)
    config.raw["tts"]["cache_dir"] = str(tmp_path / "cache")
    procs = []

    def popen(argv, **kwargs):
        proc = _FakeProc(argv, **kwargs)
        procs.append(proc)
        return proc

    client = _VoiceClient()
    service = _service(config, monkeypatch, client, popen=popen)
    result = service.speak("The streamed reply.", play=True,
                           session_id="sess9")
    assert result.streamed is True
    assert result.played is True
    assert result.first_slice_mark is not None
    assert result.play_mark == result.first_slice_mark, \
        "audible rides the first slice (first-audible-at-slice)"
    assert result.synth_mark >= result.first_slice_mark, \
        "synthesis completes AFTER the ear already has the first slice"
    assert procs and len(procs[0].stdin.written) == SLICE * 3
    # the wav is still written (cache + evidence), and no file replay ran
    assert result.audio_path and result.cached is False
    assert client.calls[0]["on_chunk"] is not None


def test_cache_hit_falls_back_to_whole_wav_playback(config, monkeypatch,
                                                    tmp_path):
    _gemini_voice_config(config)
    config.raw["tts"]["cache_dir"] = str(tmp_path / "cache")
    client = _VoiceClient()
    service = _service(config, monkeypatch, client)
    first = service.speak("Cached words here.", play=False)
    assert first.audio_path
    played_runs = []
    service._player_runner = lambda argv, **kw: played_runs.append(argv) \
        or type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
    result = service.speak("Cached words here.", play=True)
    assert result.streamed is False, "a cache hit feeds no stream"
    assert result.played is True and played_runs
    assert result.first_slice_mark is None


def test_stream_playback_switch_off_keeps_old_fakes_valid(config, monkeypatch,
                                                          tmp_path):
    _gemini_voice_config(config)
    config.raw["tts"]["cache_dir"] = str(tmp_path / "cache")
    config.raw["tts"]["stream_playback"] = False
    client = _StrictVoiceClient()   # no on_chunk parameter at all
    service = _service(config, monkeypatch, client)
    played = []
    service._player_runner = lambda argv, **kw: played.append(argv) \
        or type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
    result = service.speak("Unstreamed words.", play=True)
    assert result.streamed is False
    assert result.played is True and played, "whole-wav path unchanged"
    assert result.first_slice_mark is None


def test_midstream_failure_falls_back_to_the_whole_wav(config, monkeypatch,
                                                       tmp_path):
    _gemini_voice_config(config)
    config.raw["tts"]["cache_dir"] = str(tmp_path / "cache")

    def popen(argv, **kwargs):
        return _DyingProc(argv, **kwargs)

    client = _VoiceClient()
    service = _service(config, monkeypatch, client, popen=popen)
    played = []
    service._player_runner = lambda argv, **kw: played.append(argv) \
        or type("R", (), {"returncode": 0, "stdout": b"", "stderr": b""})()
    result = service.speak("Still must be heard.", play=True)
    assert result.streamed is True, "the first slice WAS streamed"
    assert result.first_slice_mark is not None
    assert result.played is True and played, \
        "audio is never lost: the wav reaches the ear on stream failure"


def test_interrupt_speech_logs_the_measured_cutoff(config, monkeypatch,
                                                   tmp_path, journal_stream):
    _gemini_voice_config(config)
    config.raw["tts"]["cache_dir"] = str(tmp_path / "cache")
    proc = _FakeProc([], stdin=None)
    service = _service(config, monkeypatch, _VoiceClient(),
                       popen=lambda a, **k: proc)
    player = service._stream_player("sess10")
    assert player is not None
    player.feed(b"\x01" * SLICE)           # playback is live
    outcome = service.interrupt_speech()
    assert outcome["interrupted"] is True
    assert outcome["cutoff_ms"] < 100
    assert proc.stdin.closed
    assert proc.terminated or proc.killed
    lines = journal_stream.getvalue()
    assert "tts.interrupted" in lines
    assert "cutoff_ms=" in lines
    assert service.interrupt_speech()["interrupted"] is False, \
        "nothing active — honest no-op (the turn-state reset is the daemon's)"


# ------------------------------------------------------- daemon marks
def test_latency_table_gains_first_audible_at_slice(config, journal_stream):
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    try:
        now = 1000.0
        daemon._stage("s1", "release", now)
        daemon._stage("s1", "final", now + 3.6)
        daemon._stage("s1", "reply", now + 3.7)
        daemon._stage("s1", "first_slice", now + 5.2)
        daemon._stage("s1", "audible", now + 5.2)   # rides the first slice
        daemon._stage("s1", "synth", now + 9.0)     # render completes later
        daemon._emit_latency_table("s1", final=True)
        detail = journal_stream.getvalue()
        assert "latency.table" in detail
        assert "release_to_first_slice_s=5.2" in detail, \
            "the M-4 target metric: release to first-audible"
        assert "reply_to_audible_s=1.5" in detail
        assert "first_slice_to_synth_s=3.8" in detail
        assert "audible_to_first_slice" not in detail, \
            "coincident marks never emit a zero leg"
        assert "missing=" not in detail
    finally:
        daemon.store.close()


def test_latency_table_without_streaming_is_unchanged(config, journal_stream):
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    try:
        now = 500.0
        daemon._stage("s2", "release", now)
        daemon._stage("s2", "final", now + 1.0)
        daemon._stage("s2", "reply", now + 1.5)
        daemon._stage("s2", "synth", now + 3.0)
        daemon._stage("s2", "audible", now + 3.4)
        daemon._emit_latency_table("s2")
        detail = journal_stream.getvalue()
        assert "release_to_final_s=1.0" in detail
        assert "final_to_reply_s=0.5" in detail
        assert "reply_to_synth_s=1.5" in detail
        assert "synth_to_audible_s=0.4" in detail
        assert "release_to_audible_s=3.4" in detail
        assert "first_slice" not in detail
    finally:
        daemon.store.close()


# ------------------------------------------------------- early dispatch
async def test_early_dispatch_fires_once_and_claims_single_fire(config):
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    try:
        calls = []

        async def fake_ask(params):
            calls.append(params)
            return {"reply": "Answer.", "via": "test"}

        daemon._ask = fake_ask
        daemon._dictation_session_mode = "conversation"
        assert daemon._early_dispatch_reply(
            "sess1", "Hello there", {"speak": True}) is True
        assert daemon._early_dispatch_reply(
            "sess1", "Hello there", {"speak": True}) is False, \
            "single-fire: one dispatch per session"
        task = daemon._claim_early_reply("sess1")
        assert task is not None
        assert daemon._claim_early_reply("sess1") is None, "one claim wins"
    finally:
        daemon.store.close()


def test_early_dispatch_is_mode_gated_and_echo_gated(config):
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    try:
        daemon._ask = lambda params: params
        daemon._dictation_session_mode = "command"
        assert daemon._early_dispatch_reply("s2", "Delete the logs",
                                            {}) is False, \
            "command mode waits for cleanup's flagged verdict"
        daemon._dictation_session_mode = "narration"
        daemon._speaking_text = "Hello there"
        assert daemon._early_dispatch_reply("s2", "Hello there", {}) is False, \
            "echo-to-empty never dispatches"
        assert daemon._claim_early_reply("s2") is None
    finally:
        daemon.store.close()


async def _finish_with(session, params, mode, daemon, sid):
    task = asyncio.create_task(asyncio.sleep(0, result=session))
    await daemon._finish_dictation(task, params, sid, mode)


def test_finish_dictation_reuses_the_early_reply_exactly_once(config,
                                                              journal_stream):
    from assistant.daemon import Daemon

    async def scenario():
        daemon = Daemon(config)
        try:
            calls = []

            async def fake_ask(params):
                calls.append(params)
                return {"reply": "Answer.", "via": "test"}

            daemon._ask = fake_ask
            daemon._dictation_session_mode = "conversation"
            sid = "sess42"
            assert daemon._early_dispatch_reply(sid, "Hello there",
                                                {"speak": True})
            session = SessionResult(
                session_id=sid, raw_text="Hello there", cleaned_text=None,
                backend="gemini_batch", language="en", audio_path=None,
                inbox_path=None,
                clipboard={"copied": False, "reason": "none"},
                flagged=False, duration_s=0.5, notes=[])
            await _finish_with(session, {"speak": True}, "conversation",
                               daemon, sid)
            assert len(calls) == 1, "exactly one reply per session"
            assert (daemon._ptt_last_result or {}).get("command", {}) \
                .get("reply") == "Answer."
            lines = journal_stream.getvalue()
            assert lines.count("reply.invocation") == 1, \
                "the early invocation is THE invocation — never doubled"
            assert "dictate.reply_generation_reused" not in lines  # persona row
        finally:
            daemon.store.close()

    asyncio.run(scenario())


def test_finish_dictation_cancels_the_early_reply_on_echo(config):
    from assistant.daemon import Daemon

    async def scenario():
        daemon = Daemon(config)
        try:
            calls = []

            async def fake_ask(params):
                calls.append(params)
                return {"reply": "Answer.", "via": "test"}

            daemon._ask = fake_ask
            daemon._dictation_session_mode = "conversation"
            sid = "sess43"
            # early dispatch sees a clean transcript (she had not spoken)...
            assert daemon._early_dispatch_reply(sid, "Hello there",
                                                {"speak": True})
            early_task, _mark = daemon._early_reply_tasks[sid]
            # ...then an ack plays during cleanup and the LATE echo check
            # (BH-K2, against the CURRENT speaking text) strips to empty:
            daemon._speaking_text = "Hello there"
            session = SessionResult(
                session_id=sid, raw_text="Hello there", cleaned_text=None,
                backend="gemini_batch", language="en", audio_path=None,
                inbox_path=None,
                clipboard={"copied": False, "reason": "none"},
                flagged=False, duration_s=0.5, notes=[])
            await _finish_with(session, {"speak": True}, "conversation",
                               daemon, sid)
            await asyncio.sleep(0)
            assert early_task.cancelled() or early_task.done(), \
                "a late echo verdict cancels the early reply"
            assert (daemon._ptt_last_result or {}).get("echo_suppressed") is True
        finally:
            daemon.store.close()

    asyncio.run(scenario())


def test_finish_dictation_cancels_orphaned_early_replies(config):
    from assistant.daemon import Daemon

    async def scenario():
        daemon = Daemon(config)
        try:
            daemon._ask = lambda params: params
            daemon._dictation_session_mode = "conversation"
            sid = "sess44"

            async def boom(params):
                return {"reply": "Answer."}

            daemon._ask = boom
            assert daemon._early_dispatch_reply(sid, "Hello there",
                                                {"speak": True})
            early_task, _mark = daemon._early_reply_tasks[sid]

            async def failing():
                raise RuntimeError("flow died after the leg landed")

            await _finish_with(asyncio.create_task(failing()), {"speak": True},
                               "conversation", daemon, sid)
            await asyncio.sleep(0)
            assert early_task.cancelled() or early_task.done()
            assert sid not in daemon._early_reply_tasks, \
                "no orphan survives the session"
        finally:
            daemon.store.close()

    asyncio.run(scenario())


# ------------------------------------------------------- the leg-land seam
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


def test_on_final_text_fires_at_leg_land_before_persist(config, tmp_path,
                                                        monkeypatch):
    """The early hook runs the moment the text is decided — before the
    cleanup model call and persist (the final_to_reply serial work)."""
    from assistant.journal_log import log_event

    config.raw["cleanup"]["enabled"] = False
    config.raw["transcribe"]["inbox_dir"] = str(tmp_path / "inbox")
    config.raw["transcribe"]["copy_to_clipboard"] = False
    store = Store(tmp_path / "early.db")
    svc = DictationService(config, store, None)
    svc.FINAL_TRANSCRIPT_TIMEOUT_S = 0.05
    svc.final_wait_s = 0.6
    svc.final_abandon_grace_s = 0.25
    monkeypatch.setattr(
        __import__("assistant").asr, "transcribe_file",
        lambda *a, **k: Transcript("Recovered words from the saved audio.",
                                   "en", "gemini_batch"))
    seen = []

    def on_final_text(text):
        seen.append(text)
        log_event("reply.invocation", session_id="hook", verdict="invoked",
                  detail="early=true hook-marker")

    stream = io.StringIO()
    bind_journal(stream)
    try:
        asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=100, silent_frames=0),
            transport_factory=lambda: _SilentTransport(),
            on_final_text=on_final_text))
    finally:
        reset_journal()
        store.close()
    lines = stream.getvalue()
    assert seen == ["Recovered words from the saved audio."]
    assert lines.index("hook-marker") < lines.index("transcription.landed"), \
        "chat starts the moment the leg lands — before persist completes"
