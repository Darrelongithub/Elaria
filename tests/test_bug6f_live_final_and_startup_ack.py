"""BUG 6f: real Live response shapes and the session-start speaker/mic race.

No SDK, network, API key, or audio hardware is required. The SDK double keeps
receive()'s one-model-turn scope and sends the transcription-only model's
separate interim/committed envelopes (no finished flag, no model turn).
"""

from __future__ import annotations

import asyncio
import json
import struct
import sys
import threading
import time
import wave
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

USER_TEXT = "Please save the user's complete sentence."
PREVIEW = "Please save an incorrect provisional hypothesis"
ACK_FRAME = struct.pack("<480h", *([3000] * 480))
TAIL_FRAME = struct.pack("<480h", *([4000] * 480))
USER_FRAME = struct.pack("<480h", *([6000] * 480))


def message(**content):
    return NS(server_content=NS(**content))


class SDKSession:
    """receive() ends at turn_complete, NOT at the end of the connection."""

    def __init__(self, on_end=()):
        self.on_end = list(on_end)
        self.queue = asyncio.Queue()
        self.sent = []
        self.receive_calls = 0
        self.preview_sent = False

    async def send_realtime_input(self, **kwargs):
        assert len(kwargs) == 1
        self.sent.append(kwargs)
        if "audio" in kwargs and not self.preview_sent:
            self.preview_sent = True
            await self.queue.put(message(interim_input_transcription=NS(text=PREVIEW)))
        if "activity_end" in kwargs:
            for response in self.on_end:
                await self.queue.put(response)

    async def receive(self):
        self.receive_calls += 1
        while True:
            response = await self.queue.get()
            if response is None:
                return
            yield response
            if getattr(response.server_content, "turn_complete", False):
                return


@pytest.fixture
def sdk_transport(monkeypatch):
    """Exercise the real constructor/connect/parser using stdlib SDK stand-ins."""
    def make(session, model="gemini-3.5-transcribe-live"):
        class Context:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *args):
                return None

        def connect(**kwargs):
            session.config = kwargs["config"]
            return Context()

        client = NS(aio=NS(live=NS(connect=connect)))
        types = NS(
            LiveConnectConfig=NS, AudioTranscriptionConfig=NS,
            RealtimeInputConfig=NS, AutomaticActivityDetection=NS,
            SessionResumptionConfig=NS, Modality=NS(TEXT="TEXT"),
            ActivityStart=NS, ActivityEnd=NS, Blob=NS,
        )
        genai = NS(Client=lambda **kwargs: client, types=types, __version__="test-sdk")
        monkeypatch.setitem(sys.modules, "google", NS(genai=genai))
        monkeypatch.setitem(sys.modules, "google.genai", genai)
        return GenaiLiveTransport("test-key-not-a-credential", model)

    return make


def service(config, tmp_path):
    config.raw["cleanup"]["enabled"] = False
    config.raw["transcribe"]["inbox_dir"] = str(tmp_path / "inbox")
    config.raw["transcribe"]["copy_to_clipboard"] = False
    store = Store(tmp_path / "bug6f.db")
    svc = DictationService(config, store, None)
    # The regression must fail quickly rather than spending a hardware timeout.
    svc.FINAL_TRANSCRIPT_TIMEOUT_S = 0.05
    return svc, store


def lifecycle(store):
    return [json.loads(row["detail"]) for row in store.list_persona_events(
        kind="dictate.lifecycle", limit=200)]


@pytest.mark.parametrize("model", [
    "gemini-3.5-transcribe-live", "models/gemini-3.5-transcribe-live-preview",
])
@pytest.mark.parametrize("finished", ["omitted", None, True])
def test_transcribe_live_committed_envelope_finishes_without_model_turn(
        config, tmp_path, monkeypatch, sdk_transport, model, finished):
    transcription = NS(text=USER_TEXT)
    if finished != "omitted":
        transcription.finished = finished
    session = SDKSession([message(input_transcription=transcription)])
    transport = sdk_transport(session, model)
    svc, store = service(config, tmp_path)
    fallback_calls = []
    events = []

    def fallback(*args, **kwargs):
        fallback_calls.append(args)
        return Transcript("WRONG batch path", "en", "gemini_batch")

    monkeypatch.setattr(asr, "transcribe_file", fallback)

    async def sink(event):
        events.append(event)

    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=356, silent_frames=0),
            transport_factory=lambda: transport, sink=sink))
        assert fallback_calls == [], "a committed input envelope is already a Live final"
        assert result.backend == "gemini_live"
        assert result.raw_text == USER_TEXT
        assert not result.no_final and not result.no_speech
        assert PREVIEW not in Path(result.inbox_path).read_text()
        assert store.recent_transcripts(1)[0]["raw_text"] == USER_TEXT
        assert any(e.get("event") == "transcript.interim" and e["text"] == PREVIEW
                   for e in events)
        assert len([s for s in session.sent if "audio" in s]) == 356
        assert list(session.sent[0]) == ["activity_start"]
        assert list(session.sent[-1]) == ["activity_end"]
        assert session.config.response_modalities == ["TEXT"]
        assert session.config.realtime_input_config.automatic_activity_detection.disabled
        steps = {row["step"] for row in lifecycle(store)}
        assert "dictate.transcript_final_wait_timeout" not in steps
        assert "dictate.live_no_final" not in steps
        assert "dictate.saved_wav_fallback_start" not in steps
        summary = next(row for row in lifecycle(store)
                       if row["step"] == "dictate.live_receive_summary")
        assert summary["event_counts"]["final"] == 1
        assert summary["transport"]["audio_frames_sent"] == 356
        assert summary["transport"]["receive_counts"]["input_transcription"] == 1
        assert USER_TEXT not in json.dumps(summary), "diagnostics must not log transcript text"
    finally:
        store.close()


def test_transcription_can_arrive_after_sdk_model_turn_ends(
        config, tmp_path, monkeypatch, sdk_transport):
    session = SDKSession([
        message(turn_complete=True),
        message(input_transcription=NS(text=USER_TEXT)),
    ])
    transport = sdk_transport(session)
    svc, store = service(config, tmp_path)
    monkeypatch.setattr(asr, "transcribe_file", lambda *a, **kw: Transcript(
        "WRONG batch path", "en", "gemini_batch"))
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=2, silent_frames=0),
            transport_factory=lambda: transport))
        assert result.backend == "gemini_live" and result.raw_text == USER_TEXT
        assert session.receive_calls >= 2, "receive() is scoped to a model turn"
    finally:
        store.close()


@pytest.mark.parametrize("finish_with_marker", [False, True])
def test_conversational_live_chunks_finalize_only_at_a_real_boundary(
        sdk_transport, finish_with_marker):
    chunks = [message(input_transcription=NS(text="Please save ")),
              message(input_transcription=NS(text="this sentence."))]
    if finish_with_marker:
        # The marker can have no text of its own.
        chunks.append(message(input_transcription=NS(text="", finished=True)))
    chunks.append(message(turn_complete=True))
    session = SDKSession(chunks)
    transport = sdk_transport(session, "gemini-live-2.5-flash")

    async def run():
        await transport.connect()
        try:
            await transport.activity_start()
            await transport.activity_end()
            return [event async for event in transport.events()]
        finally:
            await transport.close()

    events = asyncio.run(asyncio.wait_for(run(), timeout=1.0))
    assert [e.text for e in events if e.type == "final"] == ["Please save this sentence."]
    assert events[-1].type == "turn_complete"


def test_preview_only_still_uses_the_bounded_saved_wav_fallback(
        config, tmp_path, monkeypatch, sdk_transport):
    session = SDKSession()  # Accepts activity_end but never commits input text.
    svc, store = service(config, tmp_path)
    fallback_paths = []

    def fallback(_config, _client, path, **kwargs):
        fallback_paths.append(path)
        return Transcript(USER_TEXT, "en", "gemini_batch")

    monkeypatch.setattr(asr, "transcribe_file", fallback)
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=4, silent_frames=0),
            transport_factory=lambda: sdk_transport(session)))
        assert result.backend == "gemini_batch" and result.raw_text == USER_TEXT
        assert fallback_paths == [result.audio_path]
        assert "dictate.transcript_final_wait_timeout" in {
            row["step"] for row in lifecycle(store)}
    finally:
        store.close()


def test_one_response_can_contain_both_preview_and_committed_text(sdk_transport):
    session = SDKSession([message(
        interim_input_transcription=NS(text=PREVIEW),
        input_transcription=NS(text=USER_TEXT),
    )])
    transport = sdk_transport(session)

    async def run():
        await transport.connect()
        try:
            await transport.activity_end()
            events = transport.events()
            preview = await asyncio.wait_for(anext(events), timeout=0.2)
            final = await asyncio.wait_for(anext(events), timeout=0.2)
            return preview, final
        finally:
            await transport.close()

    preview, final = asyncio.run(run())
    assert (preview.type, preview.text) == ("interim", PREVIEW)
    assert (final.type, final.text) == ("final", USER_TEXT)


def test_empty_sdk_receive_is_an_explicit_error_not_a_silent_dead_producer(sdk_transport):
    session = SDKSession()
    session.queue.put_nowait(None)
    transport = sdk_transport(session)

    async def run():
        await transport.connect()
        try:
            return await asyncio.wait_for(anext(transport.events()), timeout=0.2)
        finally:
            await transport.close()

    event = asyncio.run(run())
    assert event.type == "error"
    assert "receive stream ended" in event.error


def test_model_text_and_output_transcription_cannot_stand_in_for_input_final(
        config, tmp_path, monkeypatch, sdk_transport):
    session = SDKSession([message(
        model_turn=NS(parts=[NS(text="Her own generated response.")]),
        output_transcription=NS(text="Her own output transcription.", finished=True),
    )])
    svc, store = service(config, tmp_path)
    monkeypatch.setattr(asr, "transcribe_file", lambda *a, **kw: Transcript(
        USER_TEXT, "en", "gemini_batch"))
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=4, silent_frames=0),
            transport_factory=lambda: sdk_transport(session)))
        assert result.backend == "gemini_batch" and result.raw_text == USER_TEXT
        summary = next(row for row in lifecycle(store)
                       if row["step"] == "dictate.live_receive_summary")
        assert summary["event_counts"]["output_final"] == 1
        assert summary["event_counts"].get("final", 0) == 0
    finally:
        store.close()


@pytest.mark.parametrize("tail_outcome", ["final", "timeout", "error"])
def test_an_earlier_segment_does_not_skip_waiting_for_the_released_activity(
        config, tmp_path, monkeypatch, tail_outcome):
    first_collected = asyncio.Event()
    svc, store = service(config, tmp_path)
    fallback_calls = []

    class Transport:
        def __init__(self):
            self.queue = asyncio.Queue()
            self.tail = None

        async def connect(self, resumption_handle=None):
            pass

        async def activity_start(self):
            pass

        async def send_audio(self, pcm):
            if not first_collected.is_set():
                await self.queue.put(LiveEvent("final", text="The first segment."))

        async def activity_end(self):
            if tail_outcome != "timeout":
                event = (LiveEvent("final", text="The final segment.")
                         if tail_outcome == "final" else LiveEvent("error", error="socket closed"))
                self.tail = asyncio.get_running_loop().call_later(
                    0.01, self.queue.put_nowait, event)

        async def events(self):
            while True:
                event = await self.queue.get()
                yield event
                first_collected.set()
                if event.type == "error":
                    return

        async def close(self):
            if self.tail is not None:
                self.tail.cancel()

    class Source:
        async def frames(self):
            yield USER_FRAME
            await first_collected.wait()
            yield USER_FRAME  # More speech after the first committed segment.

        async def aclose(self):
            pass

    def fallback(*args, **kwargs):
        fallback_calls.append(args)
        return Transcript("Both complete segments recovered from WAV.", "en", "gemini_batch")

    monkeypatch.setattr(asr, "transcribe_file", fallback)
    try:
        result = asyncio.run(svc.dictate(Source(), transport_factory=Transport))
        if tail_outcome == "final":
            assert not fallback_calls
            assert result.raw_text == "The first segment. The final segment."
            assert result.backend == "gemini_live"
        else:
            assert len(fallback_calls) == 1, "an unconfirmed tail must not be silently truncated"
            assert result.raw_text == "Both complete segments recovered from WAV."
            assert result.backend == "gemini_batch"
    finally:
        store.close()


class BlockingAck:
    """The player can run longer than any text-based duration estimate."""

    def __init__(self):
        self.started = threading.Event()
        self.finish = threading.Event()
        self.calls = []

    def __call__(self, kind):
        self.calls.append(kind)
        self.started.set()
        if not self.finish.wait(timeout=3.0):
            raise TimeoutError("test did not release ack player")
        return {"played": True}


def install_ack(daemon, monkeypatch, player):
    monkeypatch.setattr(daemon.speech, "cached_ack", lambda kind: "/cached/ack.wav")
    monkeypatch.setattr(daemon.speech, "route", lambda text: {"muted": False})
    monkeypatch.setattr(daemon.speech, "play_ack", player)


def test_ack_gate_is_reserved_before_queueing_and_tracks_actual_player_lifetime(
        config, monkeypatch):
    daemon = Daemon(config)
    player = BlockingAck()
    install_ack(daemon, monkeypatch, player)

    async def run():
        try:
            started = time.monotonic()
            ack = await daemon._ack({"kind": "on_it", "speak": True})
            assert time.monotonic() - started < 0.3, "ack must stay fire-and-forget"
            assert ack["speech"]["queued"]
            assert daemon.is_speaking(), "the gate must close before the worker is scheduled"
            assert await asyncio.to_thread(player.started.wait, 1.0)
            daemon._speaking_until = 0.0  # A duration estimate has expired.
            assert daemon.is_speaking(), "actual playback, not a text estimate, owns the gate"
            # Cancelling the waiter cannot stop a to_thread player. It must not
            # reopen the mic underneath the still-running audio either.
            waiters = list(daemon._background_tasks)
            for task in waiters:
                task.cancel()
            await asyncio.gather(*waiters, return_exceptions=True)
            assert daemon.is_speaking()
            player.finish.set()
            await asyncio.wait_for(asyncio.gather(*daemon._ack_playbacks), timeout=1.0)
            assert daemon.is_speaking(), "the room-reverb guard must survive playback completion"
            assert 0 < daemon.speaking_guard_remaining() <= 0.4
            daemon._speaking_until = 0.0  # Advance past the guard without a real sleep.
            assert not daemon.is_speaking()
        finally:
            player.finish.set()
            await daemon.aclose()

    asyncio.run(run())
    assert player.calls == ["on_it"]


@pytest.mark.parametrize("batch_fallback", [False, True])
def test_startup_ack_and_its_tail_reach_neither_live_nor_saved_wav(
        config, tmp_path, monkeypatch, batch_fallback):
    config.raw["cleanup"]["enabled"] = False
    config.raw["transcribe"]["inbox_dir"] = str(tmp_path / "inbox")
    config.raw["tts"]["speak_acks"] = True
    daemon = Daemon(config)
    player = BlockingAck()
    install_ack(daemon, monkeypatch, player)
    echo_read = asyncio.Event()
    after_playback = asyncio.Event()
    tail_read = asyncio.Event()
    user_ready = asyncio.Event()
    uploads = []
    fallbacks = []
    clipboard = []

    class Source:
        target = "startup-ack-mic"
        stalled = False

        def __init__(self, *args, **kwargs):
            pass

        async def frames(self):
            yield ACK_FRAME  # Mic is already open when the ack is queued.
            echo_read.set()
            await after_playback.wait()
            yield TAIL_FRAME  # Speakers stopped, but the 400 ms guard is active.
            tail_read.set()
            await user_ready.wait()
            for _ in range(4):
                yield USER_FRAME

        async def aclose(self):
            pass

    class Transport:
        def __init__(self):
            self.queue = asyncio.Queue()

        async def connect(self, resumption_handle=None):
            pass

        async def activity_start(self):
            pass

        async def send_audio(self, pcm):
            uploads.append(pcm)

        async def activity_end(self):
            if not batch_fallback:
                text = USER_TEXT if uploads == [USER_FRAME] * 4 else "On it. " + USER_TEXT
                await self.queue.put(LiveEvent("final", text=text))
            await self.queue.put(LiveEvent("turn_complete"))

        async def events(self):
            while True:
                event = await self.queue.get()
                yield event
                if event.type == "turn_complete":
                    return

        async def close(self):
            pass

    def fallback(_config, _client, path, **kwargs):
        with wave.open(path, "rb") as wav:
            pcm = wav.readframes(wav.getnframes())
        fallbacks.append(pcm)
        text = USER_TEXT if pcm == USER_FRAME * 4 else "On it. " + USER_TEXT
        return Transcript(text, "en", "gemini_batch")

    def copy(text):
        clipboard.append(text)
        return {"copied": True}

    monkeypatch.setattr("assistant.daemon.PipeWireCapture", Source)
    monkeypatch.setattr(asr, "make_live_transport", lambda config: Transport())
    monkeypatch.setattr(asr, "transcribe_file", fallback)
    monkeypatch.setattr("assistant.transcribe.copy_text", copy)

    async def run():
        try:
            started = await daemon._ptt_start({})
            ack_waiters = list(daemon._background_tasks - {daemon._dictation_task})
            await asyncio.wait_for(echo_read.wait(), timeout=1.0)
            player.finish.set()
            await asyncio.gather(*ack_waiters)
            after_playback.set()
            await asyncio.wait_for(tail_read.wait(), timeout=1.0)
            daemon._speaking_until = 0.0  # The real guard has now elapsed.
            user_ready.set()
            await asyncio.wait_for(asyncio.shield(daemon._dictation_task), timeout=2.0)
            stopped = await daemon._ptt_stop({"wait_s": 2.0})
            assert stopped["session_id"] == started["session_id"]
            result = stopped["result"]
            assert result["raw_text"] == USER_TEXT
            assert result["backend"] == ("gemini_batch" if batch_fallback else "gemini_live")
            assert result["clipboard"]["copied"]
            assert uploads == [USER_FRAME] * 4, "startup speaker audio leaked into Live"
            with wave.open(result["audio_path"], "rb") as wav:
                assert wav.readframes(wav.getnframes()) == USER_FRAME * 4, (
                    "the saved WAV must not reintroduce the ack through batch ASR")
            assert fallbacks == ([USER_FRAME * 4] if batch_fallback else [])
            assert clipboard == [USER_TEXT]
            assert USER_TEXT in Path(result["inbox_path"]).read_text()
            status = await daemon._status({})
            assert status["last_capture"]["node"] == "startup-ack-mic"
            assert status["last_capture"]["no_speech"] is False
        finally:
            player.finish.set()
            after_playback.set()
            user_ready.set()
            await daemon.aclose()

    asyncio.run(run())
    assert player.calls == ["on_it"], "release must not play a second ack"


@pytest.mark.parametrize("suppression", ["explicit", "class", "silent"])
def test_unplayed_ack_does_not_close_the_gate(config, monkeypatch, suppression):
    if suppression == "class":
        config.raw["presence"]["class_mode"] = True
    daemon = Daemon(config)
    plays = []
    monkeypatch.setattr(daemon.speech, "route", lambda text: {
        "muted": suppression == "silent"})
    monkeypatch.setattr(daemon.speech, "cached_ack", lambda kind: (
        None if suppression == "silent" else "/cached/ack.wav"))
    monkeypatch.setattr(daemon.speech, "play_ack", lambda kind: plays.append(kind))

    async def run():
        try:
            ack = await daemon._ack({"speak": suppression != "explicit"})
            assert not ack["speech"].get("queued")
            assert not daemon.is_speaking()
            assert daemon.speaking_guard_remaining() == 0
        finally:
            await daemon.aclose()

    asyncio.run(run())
    assert not plays


def test_failed_ack_player_releases_the_gate_and_reports_error(config, monkeypatch):
    daemon = Daemon(config)

    def fail(kind):
        raise RuntimeError("cached player failed")

    install_ack(daemon, monkeypatch, fail)
    events = []

    async def sink(event):
        events.append(event)

    monkeypatch.setattr(daemon, "broadcast", sink)

    async def run():
        try:
            await daemon._ack({"speak": True})
            assert daemon.is_speaking()
            await asyncio.gather(*daemon._background_tasks)
            assert not daemon._ack_playbacks
            assert daemon.is_speaking()  # Only the tail guard remains.
            daemon._speaking_until = 0.0
            assert not daemon.is_speaking()
            assert any(e.get("event") == "speech.error" for e in events)
        finally:
            await daemon.aclose()

    asyncio.run(run())


def test_cached_checkin_uses_the_same_gate(config, monkeypatch):
    config.raw["tts"]["speak_acks"] = False  # Isolate the in-session check-in.
    daemon = Daemon(config)
    player = BlockingAck()
    install_ack(daemon, monkeypatch, player)
    checkin_queued = asyncio.Event()

    class Dictation:
        async def dictate(self, source, *, sink, stop_event, is_playback_active, **kwargs):
            await sink({"event": "session.checkin", "prompt": "Is that all?"})
            assert is_playback_active(), "check-in playback bypassed the duplex gate"
            checkin_queued.set()
            await stop_event.wait()

    daemon.dictation = Dictation()

    async def run():
        try:
            await daemon._ptt_start({"source": "simulated"})
            await asyncio.wait_for(checkin_queued.wait(), timeout=1.0)
            assert daemon.is_speaking()
            player.finish.set()
            await asyncio.gather(*(daemon._background_tasks - {daemon._dictation_task}))
            assert daemon.is_speaking()
            daemon._speaking_until = 0.0
            assert not daemon.is_speaking()
        finally:
            player.finish.set()
            await daemon.aclose()

    asyncio.run(run())
    assert player.calls == ["checkin"]
