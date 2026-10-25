"""SILENCE HOTFIX (hardware report 2026-10-24) — she must never speak to silence.

Observed on hardware, ~01:20 EAT:

1. The owner pressed the wake key (an `assist dictate` session) and said
   NOTHING. After the endpointing window Elaria spoke the soft ladder line
   out loud — a mid-conversation nudge fired at an empty room.
2. A brushed bare F2 during a phone call opened a session that heard
   room/call audio and answered a canned greeting out loud, into the call.

One bug family: the voice reply path answers empty or garbage transcripts.
The rules pinned here (voice reply path only — the event path keeps its own
NO_SIGNAL_PEAK marker and is asserted untouched in (f)):

  rule 1  Silent close on silence: empty normalized transcript → no voice
          reply, no TTS call at all, no ladder; one plain-language line
          `she heard nothing` in the session journal and on console status.
  rule 2  Audio-energy floor: `[voice] silence_floor` (default 0.05) on the
          measured input peak (the capture.stats / doctor-peak mechanism;
          owner speech proven at peak 0.8624). Below floor = silence,
          whatever the transcriber hallucinated.
  rule 3  Ladder gating: the soft check-in fires only after at least one
          landed user utterance with at least one real word — silence at
          session start can never produce a ladder line; still at most
          once per segment.
  rule 4  No canned filler as reply fallback for empty / below-gate /
          below-floor transcripts; a real one-word transcript with a
          healthy peak ("Four.") keeps its normal reply path.
  rule 5  Quota hygiene: a silent close costs zero Flash-Lite / TTS calls.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from datetime import datetime
from pathlib import Path

import pytest

from assistant import asr
from assistant.capture import SAMPLE_RATE, pcm_peak
from assistant.config import DEFAULTS, load_config
from assistant.cost import day_start_iso
from assistant.ipc import call
from assistant.live_client import LiveEvent, ScriptedLiveTransport
from assistant.store import Store
from assistant.transcribe import DictationService, SilenceLadder
from assistant.tts import SpeechResult

REPO = Path(__file__).resolve().parents[1]
FRAME_SAMPLES = SAMPLE_RATE * 30 // 1000

LOUD = struct.pack(f"<{FRAME_SAMPLES}h", *([6000] * FRAME_SAMPLES))
SILENT = b"\x00\x00" * FRAME_SAMPLES
# Room/call noise: ABOVE the RMS gate (0.01) but BELOW the energy floor
# (peak 700/32768 ≈ 0.0214 < 0.05) — exactly the garbage-transcript case.
NOISE = struct.pack(f"<{FRAME_SAMPLES}h", *([700, -700] * (FRAME_SAMPLES // 2)))

GARBAGE_REPLY = "Understood, how may I help you?"


# --------------------------------------------------------------------------
# harness pieces (dictate-shaped, the BUG 6 test pattern)
# --------------------------------------------------------------------------
class FakeSource:
    def __init__(self, frames, *, target="fake-mic", stalled=False):
        self._frames = frames
        self.target = target
        self.stalled = stalled
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        self.closed = True


class GarbageFromNoiseTransport(ScriptedLiveTransport):
    """Failure #2 as a transport: hallucinated words from below-floor noise."""

    async def send_audio(self, pcm: bytes) -> None:
        self._frames += 1
        self.frames_received += 1
        if self._frames % 16 == 0:
            await self._queue.put(LiveEvent(
                "interim", text="thank you for calling, please hold the line"))

    async def activity_end(self) -> None:
        await self._queue.put(LiveEvent("final", text=GARBAGE_REPLY))
        await self._queue.put(LiveEvent("turn_complete"))


class OneWordTransport(ScriptedLiveTransport):
    """The proven `"Four."` case: one real word over healthy audio."""

    async def activity_end(self) -> None:
        await self._queue.put(LiveEvent("final", text="Four."))
        await self._queue.put(LiveEvent("turn_complete"))


def _service_config(tmp_path, **voice_overrides):
    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {**config.raw.get("transcribe", {}),
                                "inbox_dir": str(tmp_path / "inbox")}
    if voice_overrides:
        config.raw["voice"] = {**config.raw.get("voice", {}), **voice_overrides}
    return config


def _no_fallback(monkeypatch):
    def _must_not_run(*args, **kwargs):
        raise AssertionError(
            "batch fallback ran on a silence-verdict session — a silent "
            "close costs zero calls (rule 5)")
    monkeypatch.setattr(asr, "transcribe_file", _must_not_run)


def _journal_rows(store, kind="session.silent_close"):
    return [json.loads(row["detail"])
            for row in store.list_persona_events(kind=kind, limit=10)]


# --------------------------------------------------------------------------
# config surface: [voice] silence_floor is declared, documented, read
# --------------------------------------------------------------------------
def test_voice_silence_floor_is_declared_and_documented():
    assert DEFAULTS["voice"]["silence_floor"] == 0.05
    example = (REPO / "config.toml.example").read_text(encoding="utf-8")
    assert "silence_floor" in example, "[voice] silence_floor undocumented"
    config = load_config()
    assert float(config.section("voice").get("silence_floor")) == 0.05


def test_service_reads_the_floor_from_config(tmp_path):
    assert DictationService(_service_config(tmp_path), Store(tmp_path / "a.db"),
                            None).silence_floor == 0.05
    custom = _service_config(tmp_path, silence_floor=0.5)
    assert DictationService(custom, Store(tmp_path / "b.db"),
                            None).silence_floor == 0.5


# --------------------------------------------------------------------------
# rule 3, ladder unit level: silence from start earns nothing, ever
# --------------------------------------------------------------------------
def test_ladder_silence_from_start_never_fires_and_closes_silently():
    state = SilenceLadder(1.0, speech_rms=0.01, resume_s=0.4, grace_s=8.0,
                          floor_peak=0.05)
    fired = [state.observe(SILENT, 0.03) for _ in range(int(30 / 0.03))]
    assert not any(fired), "silence at session start produced a ladder line"
    # …but the microphone is still bounded (VB-6): window + grace, silently.
    assert state.close_due(), "a silent session must still close itself"
    assert not state.heard_speech


def test_ladder_below_floor_noise_is_silence_not_speech():
    state = SilenceLadder(1.0, speech_rms=0.01, resume_s=0.4, grace_s=8.0,
                          floor_peak=0.05)
    assert pcm_peak(NOISE) < 0.05, "test frame must sit below the floor"
    fired = [state.observe(NOISE, 0.03) for _ in range(int(30 / 0.03))]
    assert not any(fired), "below-floor room noise earned a ladder line"
    assert state.close_due(), "below-floor noise must still close the session"
    assert not state.heard_speech


def test_ladder_fires_once_after_landed_speech_and_rearms_only_for_real_speech():
    state = SilenceLadder(1.0, speech_rms=0.01, resume_s=0.4, grace_s=8.0,
                          floor_peak=0.05)
    loud_run = int(0.6 / 0.03)                       # landed speech
    assert not any(state.observe(LOUD, 0.03) for _ in range(loud_run))
    assert state.heard_speech
    fired = sum(1 for _ in range(int(3 / 0.03)) if state.observe(SILENT, 0.03))
    assert fired == 1, "the check-in must fire exactly once per segment"
    # a single loud blip does not re-arm (VB-5 preserved under the floor)
    state.observe(LOUD, 0.03)
    fired += sum(1 for _ in range(int(3 / 0.03)) if state.observe(SILENT, 0.03))
    assert fired == 1, "a blip re-armed the ladder inside the same pause"
    # sustained real speech starts a new segment and earns a new check-in
    for _ in range(int(state.resume_s / 0.03) + 1):
        state.observe(LOUD, 0.03)
    fired2 = sum(1 for _ in range(int(3 / 0.03)) if state.observe(SILENT, 0.03))
    assert fired2 == 1, "actual speech resumed but the ladder never re-armed"


# --------------------------------------------------------------------------
# (a) dictate fixture: silence → no TTS, no ladder, `she heard nothing`
# --------------------------------------------------------------------------
def test_a_silent_session_closes_without_ladder_and_marks_the_journal(
        tmp_path, monkeypatch):
    _no_fallback(monkeypatch)
    config = _service_config(tmp_path)
    store = Store(tmp_path / "silence.db")
    service = DictationService(config, store, None)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    source = FakeSource([SILENT] * 40)
    result = asyncio.run(service.dictate(
        source, transport_factory=ScriptedLiveTransport, sink=sink))

    kinds = [e.get("event") for e in events]
    assert "session.checkin" not in kinds, "the ladder spoke to an empty room"
    assert "session.silent_close" in kinds
    silent = next(e for e in events if e.get("event") == "session.silent_close")
    assert silent["message"] == "she heard nothing"

    assert result.no_speech is True
    assert result.raw_text == ""
    assert any("she heard nothing" in n for n in result.notes)
    rows = _journal_rows(store)
    assert rows and rows[0]["message"] == "she heard nothing", \
        "the session journal must carry the plain-language line"

    stats = result.capture
    assert stats["no_speech"] is True
    assert stats["peak"] == 0.0
    assert stats["silence_floor"] == 0.05

    # rule 5: a silent close costs zero Flash-Lite / TTS calls — the only
    # ledger row is the honest housekeeping row for the Live session itself.
    day = day_start_iso()
    assert store.calls_since(day, model="gemini-3.5-flash-lite") == 0
    assert store.user_turn_calls_since(day) == 0


# --------------------------------------------------------------------------
# (b) low-peak noise + garbage transcript → silent close, no voice
# --------------------------------------------------------------------------
def test_b_below_floor_noise_with_garbage_transcript_is_silence(
        tmp_path, monkeypatch):
    _no_fallback(monkeypatch)
    config = _service_config(tmp_path)
    store = Store(tmp_path / "noise.db")
    service = DictationService(config, store, None)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    source = FakeSource([NOISE] * 40, target="room-noise")
    result = asyncio.run(service.dictate(
        source, transport_factory=GarbageFromNoiseTransport, sink=sink))

    kinds = [e.get("event") for e in events]
    assert "session.checkin" not in kinds
    assert "session.silent_close" in kinds

    assert result.no_speech is True, \
        "below-floor audio is silence whatever the transcriber hallucinated"
    assert result.raw_text == "", "the hallucinated transcript must be discarded"
    assert GARBAGE_REPLY not in " ".join(result.notes)
    assert any("she heard nothing" in n for n in result.notes)
    assert _journal_rows(store), "silent close must reach the journal"

    stats = result.capture
    assert stats["peak"] == pytest.approx(pcm_peak(NOISE), abs=0.001)
    assert stats["peak"] < stats["silence_floor"]
    # the frames DID pass the old RMS gate — the floor is what decided this
    assert stats["peak_rms"] >= 0.01
    day = day_start_iso()
    assert store.calls_since(day, model="gemini-3.5-flash-lite") == 0


def test_b2_floor_is_configurable_and_decides_the_verdict(tmp_path, monkeypatch):
    """A floor above the session peak makes even loud-ish audio silence."""
    _no_fallback(monkeypatch)
    config = _service_config(tmp_path, silence_floor=0.5)
    store = Store(tmp_path / "floor.db")
    service = DictationService(config, store, None)
    result = asyncio.run(service.dictate(
        FakeSource([LOUD] * 20), transport_factory=OneWordTransport))
    assert pcm_peak(LOUD) < 0.5
    assert result.no_speech is True
    assert result.raw_text == "", "below the configured floor, words are not reports"


# --------------------------------------------------------------------------
# (c) one real word, healthy peak ("Four.") → normal reply path intact
# --------------------------------------------------------------------------
def test_c_one_real_word_with_healthy_peak_keeps_the_normal_path(tmp_path):
    config = _service_config(tmp_path)
    store = Store(tmp_path / "four.db")
    service = DictationService(config, store, None)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    result = asyncio.run(service.dictate(
        FakeSource([LOUD] * 40), transport_factory=OneWordTransport, sink=sink))

    assert result.no_speech is False
    assert result.raw_text == "Four."
    assert result.backend == "gemini_live"
    assert result.capture["peak"] >= result.capture["silence_floor"]
    kinds = [e.get("event") for e in events]
    assert "session.silent_close" not in kinds
    assert not _journal_rows(store), "a real word is not a silent close"


# --------------------------------------------------------------------------
# (d) mid-session silence after landed words → ladder fires exactly once
# --------------------------------------------------------------------------
def test_d_mid_session_silence_after_landed_words_fires_exactly_once(tmp_path):
    config = _service_config(tmp_path)
    store = Store(tmp_path / "ladder.db")
    service = DictationService(config, store, None)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    # conversation mode: check-in after 6 s of silence, grace 8 s (defaults).
    frames = [LOUD] * 20 + [SILENT] * 600
    result = asyncio.run(service.dictate(
        FakeSource(frames), transport_factory=ScriptedLiveTransport,
        sink=sink, mode="conversation"))

    checkins = [e for e in events if e.get("event") == "session.checkin"]
    assert len(checkins) == 1, \
        f"the ladder fired {len(checkins)} times after one landed utterance"
    assert any(e.get("event") == "session.grace_close" for e in events)
    assert any(e.get("event") != "session.silent_close" for e in events)
    assert not any(e.get("event") == "session.silent_close" for e in events)
    assert result.no_speech is False
    assert "mock transcript" in result.raw_text, "the landed words are kept"


def test_d2_checkin_withheld_while_no_word_has_landed(tmp_path):
    """Rule 3's transcript layer: online, above-floor sound with NOTHING
    transcribed is not a landed utterance — the check-in is withheld and the
    session closes on the grace instead of nagging."""

    class NoWordTransport(ScriptedLiveTransport):
        async def send_audio(self, pcm: bytes) -> None:
            self.frames_received += 1     # hears energy, transcribes nothing

        async def activity_end(self) -> None:
            await self._queue.put(LiveEvent("turn_complete"))

    config = _service_config(tmp_path)
    store = Store(tmp_path / "noword.db")
    service = DictationService(config, store, None)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    frames = [LOUD] * 20 + [SILENT] * 600
    asyncio.run(service.dictate(
        FakeSource(frames), transport_factory=NoWordTransport,
        sink=sink, mode="conversation"))
    assert not any(e.get("event") == "session.checkin" for e in events), \
        "a check-in fired with no landed word to check in about"


# --------------------------------------------------------------------------
# (e) two consecutive mid-session silences → ladder still at most once
# --------------------------------------------------------------------------
def test_e_two_consecutive_mid_session_silences_ask_at_most_once(tmp_path):
    config = _service_config(tmp_path)
    store = Store(tmp_path / "twice.db")
    service = DictationService(config, store, None)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    # landed speech, a pause long enough to ask once, one loud blip (not a
    # resumption), then the pause continues: still exactly one check-in.
    frames = [LOUD] * 20 + [SILENT] * 250 + [LOUD] + [SILENT] * 600
    asyncio.run(service.dictate(
        FakeSource(frames), transport_factory=ScriptedLiveTransport,
        sink=sink, mode="conversation"))
    checkins = [e for e in events if e.get("event") == "session.checkin"]
    assert len(checkins) == 1, \
        f"two consecutive silences asked {len(checkins)} times"


# --------------------------------------------------------------------------
# rules 1/4/5 at the daemon: the voice reply path stays shut, the press ack
# stays, console status carries the plain line, quota counters do not move
# --------------------------------------------------------------------------
def _online_posture(daemon) -> None:
    """Put the fixture daemon in the posture the failures happened in.

    In mock mode the connectivity probe is local and honest (modes.py); a
    forced refresh makes the session ONLINE, so dictation takes the Live
    path exactly as it did on hardware. (The speaking route itself stays
    muted in mock — `can_speak()` is False — so the observable voice-path
    signals here are the broadcast events and the spy counters: a fired
    check-in, a queued ack playback, a speak() attempt or an _ask() turn
    are each a failure of the hotfix rules.)
    """
    daemon.mode_manager.refresh(force=True)
    status = daemon.mode_manager.status(refresh=False)
    assert status.is_online, "the daemon test posture must be online"


def _instrument_daemon(daemon, monkeypatch) -> dict:
    """Spies: every spoken surface + every broadcast, recorded not played."""
    seen: dict = {"acks": [], "speaks": [], "play_acks": [], "asks": [],
                  "broadcasts": []}

    def record_ack(kind):
        seen["acks"].append(kind)

    def record_speak(text, *, play=True):
        seen["speaks"].append(text)
        return SpeechResult(text=str(text), backend="none", voice_id="none",
                            muted=True)

    def record_play_ack(kind):
        seen["play_acks"].append(kind)
        return {"played": False}

    async def record_ask(params):
        seen["asks"].append(dict(params))
        return {"reply": "a reply that must never be reached", "via": "test"}

    real_broadcast = daemon.broadcast

    async def record_broadcast(event):
        seen["broadcasts"].append(event)
        return await real_broadcast(event)

    monkeypatch.setattr(daemon, "_queue_ack_playback", record_ack)
    monkeypatch.setattr(daemon.speech, "speak", record_speak)
    monkeypatch.setattr(daemon.speech, "play_ack", record_play_ack)
    monkeypatch.setattr(daemon, "_ask", record_ask)
    monkeypatch.setattr(daemon, "broadcast", record_broadcast)
    return seen


class _ScriptedPW:
    """PipeWireCapture stand-in: N frames of one kind, then the node ends."""

    frame = SILENT

    def __init__(self, target=None, *, sample_rate=SAMPLE_RATE, frame_ms=30,
                 stall_timeout_s=8.0):
        self.target = target
        self.stalled = False
        self.closed = False

    async def frames(self):
        for _ in range(1200):
            yield type(self).frame

    async def aclose(self):
        self.closed = True


class _SilentPW(_ScriptedPW):
    frame = SILENT


class _NoisePW(_ScriptedPW):
    frame = NOISE


class _LoudPW(_ScriptedPW):
    frame = LOUD


def test_a2_daemon_silent_session_no_voice_no_popup_and_a_console_line(
        config, running_daemon, monkeypatch):
    daemon, _server = running_daemon
    _online_posture(daemon)
    seen = _instrument_daemon(daemon, monkeypatch)
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _SilentPW)

    started = call(config.socket_path, "ptt.start", {}, timeout=5.0)
    assert started["listening"] is True
    # let the session run to its own endpoint (window + grace ≈ 28 s of audio)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not (
            daemon._dictation_task is None or daemon._dictation_task.done()):
        time.sleep(0.05)
    stopped = call(config.socket_path, "ptt.stop", {"wait_s": 30.0}, timeout=35.0)
    result = stopped.get("result") or {}

    # rule 1/3: session-open earcon is okay; the silent close itself adds no
    # ladder line, verbal ack, reply, or TTS.
    kinds = [e.get("event") for e in seen["broadcasts"]]
    assert "session.checkin" not in kinds, "the ladder fired at an empty room"
    assert "session.silent_close" in kinds
    assert seen["acks"] == []  # this test posture has spoken acks disabled
    assert seen["speaks"] == [], "a silent close made a TTS call"
    assert seen["play_acks"] == []
    assert seen["asks"] == [], "an empty transcript reached the reply path"
    assert result.get("no_speech") is True
    assert (result.get("text") or "") == ""

    # rule 1: journal + console status carry the plain line
    rows = [json.loads(r["detail"]) for r in
            daemon.store.list_persona_events(kind="session.silent_close", limit=5)]
    assert rows and rows[0]["message"] == "she heard nothing"
    status = call(config.socket_path, "status", timeout=3.0)
    assert status["last_session_line"] == "she heard nothing"
    console_state = call(config.socket_path, "console.state", timeout=3.0)
    assert console_state["status_line"] == "she heard nothing"

    # rule 5: quota counters did not move
    day = day_start_iso()
    assert status["quota_today_live_calls"] == 0
    assert daemon.store.calls_since(day, model="gemini-3.5-flash-lite") == 0
    assert daemon.store.user_turn_calls_since(day) == 0


def test_b3_daemon_garbage_from_room_noise_never_reaches_a_reply(
        config, running_daemon, monkeypatch):
    """Failure #2 end to end: brushed key, room noise, hallucinated greeting.

    Command mode with speak requested — the exact posture in which the canned
    line went out into the phone call.
    """
    daemon, _server = running_daemon
    _online_posture(daemon)
    seen = _instrument_daemon(daemon, monkeypatch)
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _NoisePW)
    monkeypatch.setattr(asr, "make_live_transport",
                        lambda cfg, **kw: GarbageFromNoiseTransport())

    call(config.socket_path, "ptt.start", {"mode": "command"}, timeout=5.0)
    time.sleep(1.0)                      # the session hears ~1 s of "call audio"
    stopped = call(config.socket_path, "ptt.stop",
                   {"speak": True, "wait_s": 30.0}, timeout=35.0)
    result = stopped.get("result") or {}

    assert result.get("no_speech") is True
    assert (result.get("text") or "") == ""
    assert GARBAGE_REPLY not in json.dumps(result)
    assert seen["asks"] == [], "garbage below the floor reached the reply path"
    assert seen["speaks"] == [], "garbage below the floor was spoken"
    assert "checkin" not in seen["acks"]
    kinds = [e.get("event") for e in seen["broadcasts"]]
    assert "session.checkin" not in kinds
    assert "session.silent_close" in kinds
    day = day_start_iso()
    assert daemon.store.user_turn_calls_since(day) == 0
    assert daemon.store.calls_since(day, model="gemini-3.5-flash-lite") == 0


def test_c2_daemon_one_real_word_still_gets_its_reply_path(
        config, running_daemon, monkeypatch):
    daemon, _server = running_daemon
    _online_posture(daemon)
    seen = _instrument_daemon(daemon, monkeypatch)
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _LoudPW)
    monkeypatch.setattr(asr, "make_live_transport",
                        lambda cfg, **kw: OneWordTransport())

    call(config.socket_path, "ptt.start", {"mode": "command"}, timeout=5.0)
    time.sleep(0.6)                      # ~0.6 s of real speech, then release
    stopped = call(config.socket_path, "ptt.stop",
                   {"speak": True, "wait_s": 30.0}, timeout=35.0)
    result = stopped.get("result") or {}

    assert result.get("no_speech") is False
    assert (result.get("text") or "").strip() == "Four."
    assert len(seen["asks"]) == 1, "a healthy one-word transcript lost its reply"
    assert seen["asks"][0]["text"] == "Four."
    assert seen["asks"][0]["speak"] is True
    # …and the console line from an earlier silence does not stick around
    status = call(config.socket_path, "status", timeout=3.0)
    assert status["last_session_line"] is None


# --------------------------------------------------------------------------
# (f) the event path is untouched: its own peak mechanism, its own marker
# --------------------------------------------------------------------------
class _FakeClock:
    def __init__(self, start: float = 10_000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class _PumpSource:
    def __init__(self, clock: _FakeClock, *, frame_s: float = 1.0,
                 target: str = "fake-mic"):
        self.clock = clock
        self.frame_s = frame_s
        self.target = target
        self.stalled = False
        self.closed = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def frames(self):
        while True:
            frame = await self._queue.get()
            if frame is None:
                return
            self.clock.advance(self.frame_s)
            yield frame

    async def aclose(self):
        self.closed = True
        await self._queue.put(None)

    async def push(self, count: int = 1, frame: bytes = LOUD) -> None:
        for _ in range(count):
            await self._queue.put(frame)
            await asyncio.sleep(0)


class _TranscribeScript:
    def __init__(self):
        self.gates: dict[int, asyncio.Event] = {}
        self.calls: list[int] = []
        self.text_for = lambda index: f"transcript of segment {index:03d}"

    def gate(self, index: int) -> asyncio.Event:
        return self.gates.setdefault(index, asyncio.Event())

    async def __call__(self, path: Path) -> str:
        index = int(Path(path).stem.split("-")[1])
        self.calls.append(index)
        await self.gate(index).wait()
        return self.text_for(index)


async def test_f_event_path_ignores_the_voice_silence_floor(config):
    """Regression (rule f): a silence_floor that would swallow event speech
    (peak 0.183 < 0.9) changes NOTHING on the event path — its capture,
    transcription and no-signal marker keep their own mechanism."""
    from assistant.event import NO_SIGNAL_PEAK, EventService

    assert NO_SIGNAL_PEAK == 0.005, "the event no-signal threshold drifted"
    config.raw["voice"] = {**config.raw.get("voice", {}), "silence_floor": 0.9}

    # silence in → the event's OWN marker, unchanged
    script = _TranscribeScript()
    script.text_for = lambda index: ""
    clock = _FakeClock()
    service = EventService(config, store=None, transcribe_fn=script,
                           clock=clock,
                           now_fn=lambda: datetime(2026, 10, 22, 14, 30, 0),
                           segment_minutes=0.05)
    source = _PumpSource(clock)
    await service.start(source=source, title="Panel", battery_ok=True)
    await source.push(2, frame=SILENT)
    await source.aclose()
    await service.wait_capture_idle()
    script.gate(1).set()
    result = await service.stop()
    text = Path(result["document"]).read_text()
    assert "[seg 001: no signal detected]" in text

    # speech below the voice floor in → still transcribed, still no marker
    script2 = _TranscribeScript()
    clock2 = _FakeClock()
    service2 = EventService(config, store=None, transcribe_fn=script2,
                            clock=clock2,
                            now_fn=lambda: datetime(2026, 10, 22, 15, 0, 0),
                            segment_minutes=0.05)
    source2 = _PumpSource(clock2)
    await service2.start(source=source2, title="Panel", battery_ok=True)
    await source2.push(2, frame=LOUD)          # peak 0.183 — below 0.9 floor
    await source2.aclose()
    await service2.wait_capture_idle()
    script2.gate(1).set()
    result2 = await service2.stop()
    text2 = Path(result2["document"]).read_text()
    assert "transcript of segment 001" in text2
    assert "no signal detected" not in text2
    assert script2.calls == [1], "the event transcription call pattern changed"
