"""BUG 6 regressions — live dictation: ptt.stop must not hang, and the Live
session itself must be half-duplex.

Owner repro 2026-10-20 (after the Bug 1–5 fixes):

* ``assist dictate`` printed "Listening…", Enter was pressed, and the CLI
  blocked in the ``ptt.stop`` recv until its 90 s timeout (Ctrl-C required).
  Afterwards ``dictation_active=false``, ``last_transcript=null`` and no
  dictate turn was shown: the stop had queued behind the Live session.
* During the session she looped her generic line at herself through the
  SPEAKERS. The BUG5 guard covers local playback, but model output audio
  arrives on the *same* Live session whose mic uplink stays open — full-duplex
  self-hearing inside Live. Gating only around ``play_audio`` cannot fix that.

What this file asserts, in the order the owner asked for it:

1. ``ptt.stop`` returns in well under 2 s while a Live turn is still in flight,
   and the transcript then arrives asynchronously (``ptt.result`` + event).
2. In a simulated Live session that plays audio while "hearing" it, zero user
   turns and zero transcript segments are produced from her own audio; the
   uplink is closed for playback plus the ~400 ms guard.
3. Output transcription can never be promoted to a user final, and input text
   that matches what she just said is refused.
4. Cost failures carry purpose tags and the report distinguishes the known
   key/voice errors from a Live transport failure.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest

from assistant import asr
from assistant.cost import format_cost_report, summarise_failures
from assistant.live_client import (
    DuplexLiveTransport,
    LiveDuplexGate,
    LiveEvent,
    ScriptedLiveTransport,
    SelfHearingLiveTransport,
)
from assistant.store import Store
from assistant.transcribe import DictationService, SessionResult


# ---------------------------------------------------------------------------
# Deterministic clock: the gate is real-time in production, exact in tests.
# ---------------------------------------------------------------------------
class FakeClock:
    def __init__(self, start: float = 1_000.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


FRAME_S = 0.03


def frame_bytes() -> bytes:
    import struct

    samples = 16000 * 30 // 1000
    return struct.pack(f"<{samples}h", *([6000] * samples))


class ClockedSource:
    """Hands frames over and advances the fake clock with each one."""

    def __init__(self, clock: FakeClock, frames: int):
        self.clock = clock
        self.n_frames = frames
        self.yielded = 0
        self.closed = False

    async def frames(self):
        frame = frame_bytes()
        for _ in range(self.n_frames):
            self.clock.advance(FRAME_S)
            self.yielded += 1
            yield frame

    async def aclose(self):
        self.closed = True


# ===========================================================================
# 1. ptt.stop acks immediately while a Live turn is in flight
# ===========================================================================
def test_bug6_ptt_stop_returns_under_two_seconds_while_live_turn_in_flight(
        config, running_daemon):
    from assistant.ipc import call

    daemon, _server = running_daemon

    class SlowLiveDictation:
        """A Live turn in flight: it finishes 3 s *after* the release."""

        released = False

        async def dictate(self, source, *, mode="narration", sink=None,
                          stop_event=None, is_playback_active=None,
                          session_id=None):
            self.released = False
            if sink is not None:
                await sink({"event": "session.started", "session_id": session_id})
            await stop_event.wait()
            self.released = True
            await asyncio.sleep(3.0)   # final transcript + Live close
            return SessionResult(
                session_id=session_id or "slow", raw_text="async transcript",
                cleaned_text=None, backend="gemini_live", language="en",
                audio_path=None, inbox_path=None,
                clipboard={"copied": False, "reason": "none"},
                flagged=False, duration_s=1.2, notes=[])

    slow = SlowLiveDictation()
    daemon.dictation = slow

    started = call(config.socket_path, "ptt.start", {"source": "simulated"},
                   timeout=5.0)
    assert started["listening"] is True
    time.sleep(0.25)

    began = time.monotonic()
    stopped = call(config.socket_path, "ptt.stop", timeout=10.0)
    elapsed = time.monotonic() - began

    assert elapsed < 2.0, (
        f"ptt.stop blocked for {elapsed:.2f}s while a Live turn was in flight; "
        "a stop that queues behind transcription/speech is not a stop")
    assert stopped["listening"] is False
    assert stopped["processing"] is True
    assert stopped["result"] is None, "the result must not be awaited inline"
    assert stopped["session_id"]
    # No spoken ack on release: the caller asked to stop.
    assert stopped["speech"].get("queued") is not True

    # The transcript is delivered asynchronously, to the CLI and to subscribers.
    pending = call(config.socket_path, "ptt.result",
                   {"session_id": stopped["session_id"]}, timeout=3.0)
    assert pending["processing"] is True and pending["result"] is None

    delivered = call(config.socket_path, "ptt.result",
                     {"session_id": stopped["session_id"], "wait_s": 15.0},
                     timeout=20.0)
    assert delivered["processing"] is False
    assert delivered["result"]["text"] == "async transcript"

    status = call(config.socket_path, "status", timeout=3.0)
    assert status["dictation_processing"] is False
    assert status["dictation_active"] is False
    assert slow.released is True


# ===========================================================================
# 2. The gate itself: playback closes the uplink, and the 400 ms guard holds
# ===========================================================================
def test_bug6_gate_closes_uplink_for_playback_plus_guard_and_matches_self_audio():
    clock = FakeClock()
    gate = LiveDuplexGate(guard_s=0.4, clock=clock)

    assert gate.uplink_allowed(), "silence must leave the mic open"

    # 0.5 s of output audio (24000 Hz s16le = 24000 bytes).
    seconds = gate.observe_output_audio(b"\x01\x02" * 6000, sample_rate=24000)
    assert seconds == pytest.approx(0.25, abs=0.01)
    assert gate.playing() and not gate.uplink_allowed()

    clock.advance(0.25)                      # playback itself is over
    assert not gate.uplink_allowed(), "the guard must hold after playback"

    clock.advance(0.39)
    assert not gate.uplink_allowed(), "guard is 400 ms, not one frame"

    clock.advance(0.02)
    assert gate.uplink_allowed(), "the mic must reopen after playback + guard"

    # Unknown-length playback stays closed until the player says it ended.
    gate.begin_playback()
    clock.advance(30.0)
    assert not gate.uplink_allowed()
    gate.playback_ended()
    clock.advance(0.39)
    assert not gate.uplink_allowed()
    clock.advance(0.02)
    assert gate.uplink_allowed()

    # Self-audio matching is textual, and only for what she actually said.
    gate.note_output_text("Understood, what are you working on that I can help with?")
    assert gate.is_self_audio("understood what are you working on that I can help with")
    assert gate.is_self_audio("Understood — what are you working on?")
    assert not gate.is_self_audio("Organise the downloads folder into invoices")


def test_bug6_duplex_transport_never_sends_frames_while_output_plays():
    clock = FakeClock()
    inner = ScriptedLiveTransport()
    transport = DuplexLiveTransport(inner, clock=clock)

    async def run():
        await transport.connect()
        await transport.activity_start()
        await transport.send_audio(frame_bytes())
        assert inner.frames_received == 1
        # Playback begins: the very next frame must not reach the session.
        transport.gate.observe_output_audio(b"\x01\x02" * 12000, sample_rate=24000)
        await transport.send_audio(frame_bytes())
        await transport.send_audio(frame_bytes())
        assert inner.frames_received == 1, "half-duplex uplink leaked mic frames"
        clock.advance(0.5 + 0.4 + 0.01)
        await transport.send_audio(frame_bytes())
        assert inner.frames_received == 2, "the uplink never reopened"
        assert transport.gate.frames_dropped == 2

    asyncio.run(run())

    # Local TTS playback is the other half of the same rule.
    transport = DuplexLiveTransport(ScriptedLiveTransport(),
                                    external_playback=lambda: True)

    async def run_external():
        await transport.send_audio(frame_bytes())
        assert transport._inner.frames_received == 0

    asyncio.run(run_external())


def test_bug6_output_transcription_is_never_promoted_to_a_user_final():
    class OutputOnlyTransport:
        """Delivers her own words as output, then an input echo of them."""

        name = "output_only"

        def __init__(self):
            self._queue = asyncio.Queue()

        async def connect(self, resumption_handle=None):
            return None

        async def activity_start(self):
            await self._queue.put(LiveEvent(
                "output_final", text="I am now. What do you need?"))
            await self._queue.put(LiveEvent(
                "final", text="I am now. What do you need?"))
            await self._queue.put(LiveEvent("turn_complete"))

        async def send_audio(self, pcm):
            return None

        async def activity_end(self):
            return None

        async def events(self):
            while True:
                event = await self._queue.get()
                yield event
                if event.type == "turn_complete":
                    return

        async def close(self):
            return None

    transport = DuplexLiveTransport(OutputOnlyTransport())

    async def run():
        await transport.connect()
        await transport.activity_start()
        seen = [event async for event in transport.events()]
        return seen

    events = asyncio.run(run())
    kinds = [event.type for event in events]
    assert "output_final" in kinds
    assert "final" not in kinds, (
        "her own output transcription was surfaced as a user final")
    assert "echo_suppressed" in kinds
    assert transport.gate.echo_suppressed == 1


# ===========================================================================
# 3. The owner's repro as a full dictation session: zero self-audio turns
# ===========================================================================
def _bug6_config(tmp_path):
    from assistant.config import load_config

    config = load_config()
    config.raw["cleanup"] = {**config.raw["cleanup"], "enabled": False}
    config.raw["transcribe"] = {**config.raw["transcribe"],
                                "inbox_dir": str(tmp_path / "inbox")}
    return config


def test_bug6_simulated_live_session_playing_while_hearing_it_yields_zero_user_turns(
        tmp_path, monkeypatch):
    clock = FakeClock()
    config = _bug6_config(tmp_path)
    store = Store(tmp_path / "bug6.db")
    service = DictationService(config, store, None)

    # The fallback pass is not what this test is about; keep the saved WAV from
    # inventing a transcript after the Live path correctly produced none.
    monkeypatch.setattr(asr, "transcribe_file", lambda *a, **k: type(
        "T", (), {"text": "", "backend": "local", "confidence": None,
                  "language": "en"})())

    transport = SelfHearingLiveTransport(trigger_after_frames=4, clock=clock)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    source = ClockedSource(clock, frames=120)
    result = asyncio.run(service.dictate(
        source, transport_factory=lambda: transport, sink=sink, clock=clock))

    self_text = SelfHearingLiveTransport.SELF_TEXT

    # The simulated session really did play audio and really would have heard it.
    assert transport.output_audio_events == 5
    assert transport.frames_received < 120, "the gate never closed the uplink"
    assert source.closed is True
    # Self-audio must not reach the archive either: the saved WAV is the batch
    # fallback's source, so recording her own line would re-enter it as "user"
    # text on the next Live failure.
    from assistant.capture import wav_duration_s

    assert result.audio_path, "the session lost its audio record"
    assert result.duration_s == pytest.approx(
        transport.frames_received * FRAME_S, abs=0.1), (
        "the saved WAV still contains the frames the Live gate discarded")
    assert wav_duration_s(Path(result.audio_path)) == pytest.approx(
        transport.frames_received * FRAME_S, abs=0.1)

    # Zero user turns, zero transcript segments from her own audio.
    assert result.raw_text == "", (
        f"self-audio became a transcript: {result.raw_text!r}")
    assert transport.echo_finals == 0, "the fake session transcribed itself"
    finals = [event for event in events if event["event"] == "transcript.final"]
    assert [event for event in finals if self_text.lower() in event.get("text", "").lower()] == []
    assert not [event for event in finals if event.get("text")], finals
    assert not any(event["event"] == "transcript.interim"
                   and self_text.lower()[:20] in event.get("text", "").lower()
                   for event in events)

    # Her own words were surfaced as output, clearly labelled.
    output = [event for event in events if event["event"] == "live.output_transcript"]
    assert any(event["text"] == self_text for event in output)
    assert not any(event.get("session_id") != result.session_id for event in events)

    # The gate announced itself and the session recorded why frames were lost.
    states = [event["state"] for event in events if event["event"] == "live.uplink_gated"]
    assert "closed" in states and "open" in states
    duplex = [event for event in events if event["event"] == "live.duplex"]
    assert duplex and duplex[0]["gated_frames"] > 0
    assert any("half-duplex" in note for note in result.notes), result.notes
    store.close()


def test_bug6_without_the_gate_the_same_transport_does_echo_itself():
    """Control: the double is faithful, so the test above proves the fix."""
    clock = FakeClock()
    transport = SelfHearingLiveTransport(trigger_after_frames=2, clock=clock)
    events: list[LiveEvent] = []

    async def run():
        await transport.connect()
        await transport.activity_start()
        for _ in range(30):
            clock.advance(FRAME_S)
            await transport.send_audio(frame_bytes())
        await transport.activity_end()
        async for event in transport.events():
            events.append(event)
            if event.type == "turn_complete":
                break

    asyncio.run(run())
    assert transport.echo_finals >= 1
    assert any(event.type == "final" and event.text == transport.SELF_TEXT
               for event in events)


# ===========================================================================
# 4. Cost: failures are attributed, and Live failures are not hidden
# ===========================================================================
def test_bug6_failures_carry_purpose_tags_and_report_distinguishes_live(tmp_path):
    from assistant.cost import month_start_iso

    store = Store(tmp_path / "cost.db")
    since = month_start_iso()

    store.log_llm_call(
        ts=since, correlation_id="key-1", role="voice",
        model="gemini-3.8-live", mode="live", tokens_in=0, tokens_out=0,
        tokens_estimated=0, audio_seconds=0.0, cost_usd=0.0, latency_ms=12.0,
        ok=0, verified=None, attempt=0, fixture_key=None,
        error="RuntimeError: API key not valid. Please pass a valid API key.",
        purpose="housekeeping:voice_speech", is_user_turn=0)
    store.log_llm_call(
        ts=since, correlation_id="voice-1", role="voice",
        model="gemini-3.8-live", mode="live", tokens_in=0, tokens_out=0,
        tokens_estimated=0, audio_seconds=0.0, cost_usd=0.0, latency_ms=30.0,
        ok=0, verified=None, attempt=0, fixture_key=None,
        error='RuntimeError: Voice name "Flare" is not supported',
        purpose="housekeeping:voice_speech", is_user_turn=0)
    # A silent Live failure used to leave no row at all. Now it is a failure
    # with the same purpose as successful live sessions.
    store.log_llm_call(
        ts=since, correlation_id="live-1", role="transcribe_live",
        model="gemini-3.5-transcribe-live", mode="live", tokens_in=0,
        tokens_out=0, tokens_estimated=1, audio_seconds=0.0, cost_usd=0.0,
        latency_ms=0.0, ok=0, verified=None, attempt=1, fixture_key=None,
        error="live connect: LiveUnavailable: 429 RESOURCE_EXHAUSTED",
        purpose="housekeeping:transcribe_live", is_user_turn=0)

    rows = store.failure_summary_since(since)
    summary = summarise_failures(rows)
    assert summary["total"] == 3
    assert summary["untagged"] == 0
    assert summary["by_category"]["key"] == 1
    assert summary["by_category"]["voice"] == 1
    assert summary["live_failures"] == 1
    assert all(row["purpose"] for row in rows), "a failure row lost its purpose tag"

    report = format_cost_report(
        {**store.llm_summary(since), "failures_detail": rows},
        {**store.llm_summary(since), "live_calls": 0,
         "user_turn_calls": 0, "housekeeping_calls": 3,
         "by_purpose": {}},
        {}, "free")
    assert "Failures this month: 3" in report
    assert "LIVE failures: 1" in report
    assert "housekeeping:transcribe_live" in report
    assert "key" in report and "voice" in report
    store.close()


def test_bug6_every_ledger_call_site_carries_a_purpose():
    root = Path(__file__).resolve().parents[1] / "src" / "assistant"
    untagged: list[str] = []
    for path in root.glob("*.py"):
        source = path.read_text()
        for match in re.finditer(r"\.log_llm_call\(", source):
            tail = source[match.end():]
            # Look at the call's keyword arguments up to the matching close.
            depth, end = 1, 0
            for index, char in enumerate(tail):
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1
                    if depth == 0:
                        end = index
                        break
            call = tail[:end]
            if "purpose=" not in call:
                line = source[:match.start()].count("\n") + 1
                untagged.append(f"{path.name}:{line}")
    assert not untagged, f"ledger writes without a purpose tag: {untagged}"


def test_bug6_a_finished_previous_session_cannot_clobber_the_next_dictation(config):
    """Async finish must be generation-safe.

    The transcript is delivered in the background, so it can land after the
    owner has pressed the hotkey again. The old finisher may not set the mode
    to idle, clear the new session's processing flag, or release a parked mode
    switch while the new dictation is listening.
    """
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    old_id: dict[str, str] = {}

    class SlowDictation:
        async def dictate(self, source, *, mode="narration", sink=None,
                          stop_event=None, is_playback_active=None,
                          session_id=None):
            await stop_event.wait()
            await asyncio.sleep(0.3)
            return SessionResult(
                session_id=session_id or "slow", raw_text="first session",
                cleaned_text=None, backend="gemini_live", language="en",
                audio_path=None, inbox_path=None,
                clipboard={"copied": False, "reason": "none"},
                flagged=False, duration_s=0.4, notes=[])

    daemon.dictation = SlowDictation()

    async def scenario():
        first = await daemon._ptt_start({"source": "simulated"})
        old_id["value"] = first["session_id"]
        stopped = await daemon._ptt_stop({})
        assert stopped["processing"] is True
        # The owner presses again before the old transcript is delivered.
        second = await daemon._ptt_start({"source": "simulated"})
        assert second["session_id"] != old_id["value"]
        await asyncio.sleep(0.6)          # old finisher completes here
        try:
            assert daemon.mode == "listening", (
                "a finished previous session forced the new one out of listening")
            assert daemon._ptt_session_id == second["session_id"]
            assert daemon._ptt_processing is False
            assert daemon._ptt_results[old_id["value"]]["text"] == "first session"
        finally:
            await daemon._ptt_stop({})
            await asyncio.sleep(0.4)
            await daemon.aclose()

    asyncio.run(scenario())


def test_bug6_cli_dictate_prints_a_turn_and_never_blocks(config, running_daemon):
    """The exact owner command: Listening… → Enter → a dictate turn, quickly.

    Previously this blocked in the stop recv for 90 s and then printed nothing.
    Here the release is ack'd, the CLI asks `ptt.result` for the transcript, and
    the turn (narration + text + inbox) is printed.
    """
    import os
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo / "src"), "GEMINI_MODE": "mock"}
    began = time.monotonic()
    out = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "dictate"],
        input="\n", capture_output=True, text=True, env=env, timeout=60,
        check=False)
    elapsed = time.monotonic() - began

    assert out.returncode == 0, out.stderr
    assert out.stdout.strip(), "assist dictate printed no turn"
    assert "(no transcript)" not in out.stdout
    assert "mock transcript" in out.stdout.lower()
    assert "[inbox:" in out.stderr
    # The release path is not blocking behind Live/cleanup.
    assert elapsed < 20.0, f"assist dictate took {elapsed:.1f}s"
