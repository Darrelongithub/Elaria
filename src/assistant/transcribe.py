"""Dictation service (§3.5/§3.6) — one session of push-to-talk.

Pipeline: capture frames → WAV sink (always) + rolling 30s buffer +
VAD gate → Live transport (manual activity signalling) → interim/final
events → transcript store → cleanup pass → markdown inbox + clipboard.

Failure handling is the design, not an afterthought:
- Mid-utterance Live disconnect → reconnect with the resumption handle
  and replay the buffered tail, so words aren't lost (§3.5).
- GoAway / session-age rotation → proactive reconnect before the
  ~10min connection lifetime kills us mid-sentence.
- Live unrecoverable (429 storm, offline) → the saved WAV goes through
  the §12.7 batch chain; the user still gets text, a second later.
- Silence never hard-cuts (§13.8): the ladder emits ONE soft check-in
  event per segment at a per-mode threshold; PTT release is the user's
  own ending. Endpointing thresholds adapt to session mode because the
  owner's narration pauses (17/min) are not conversation pauses.
- Silence never SPEAKS (silence hotfix, hardware 2026-10-24): a check-in
  is earned only by a landed utterance, a session whose measured input
  peak stays below `[voice] silence_floor` is silence whatever the
  transcriber hallucinated, and a silence-verdict session closes with no
  voice reply, no TTS call, no ladder line — one plain line in the
  journal and on console status: "she heard nothing".

Events (dicts) emitted to the caller's sink: session.started,
transcript.interim, session.checkin, session.reconnecting,
transcript.final, session.ended, error, plus the BUG 6 duplex events
(live.uplink_gated, live.output_transcript, transcript.echo_suppressed).
The daemon forwards these over IPC to Waybar/overlay subscribers (§3.1).

Half-duplex lives INSIDE the Live session (BUG 6): output audio closes the
mic uplink for its duration plus a 400 ms guard, and output transcription is
never eligible to become a final. The BUG5 capture mute still applies around
local TTS; this is the other half of the same rule, not a replacement.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import asr
from .capture import (
    FrameGate,
    RollingAudioBuffer,
    WavSink,
    frame_rms,
    pcm_peak,
)
from .cleanup import CleanupPass
from .clipboard import copy_text
from .config import DEFAULTS
from .cost import iso_now, shadow_cost_usd
from .inbox import write_inbox_note
from .journal_log import log_event
from .live_client import (
    DuplexLiveTransport,
    LiveEvent,
    LiveTransport,
    LiveUnavailable,
)

EventSink = Callable[[dict], Awaitable[None]]

# SILENCE HOTFIX rule 1 (hardware 2026-10-24): the ONE plain-language line a
# silence-verdict session leaves behind — session journal, session notes,
# console status. Never a popup, never a voice reply, never a code.
HEARD_NOTHING = "she heard nothing"


class SilenceLadder:
    """Adaptive endpointing (§13.8): listen → ONE soft 'Is that all?' → grace →
    close.

    Three rules the owner stated, all enforced here rather than hoped for:

    * ONE check-in per thought (VB-5). "Speech resumed" used to mean *any* frame at
      or over the RMS gate, so a breath, a key click or a mic pop between two
      silences re-armed the ladder and she asked twice in one sentence. Re-arming
      now requires sustained speech (`resume_s`).
    * a grace close (VB-6). After the check-in, if nothing is said for
      `grace_s`, the thought is finished for them and the session ends — the
      microphone used to stay open until the user's hotkey, ~50 minutes in one
      headless repro.
    * SILENCE AT SESSION START EARNS NOTHING (silence hotfix, hardware
      2026-10-24): the check-in is a mid-conversation nudge, so it may fire
      only after the ladder has actually HEARD a landed utterance — sustained
      speech at or over the RMS gate and, when `floor_peak` is set, at or over
      the `[voice] silence_floor` energy floor (room/call noise below the
      floor counts as silence, not speech). A session that was never spoken
      into closes on the same bounded schedule (window + grace) WITHOUT any
      ladder line: she must never speak to silence.
    """

    def __init__(self, checkin_after_s: float, speech_rms: float = 0.01, *,
                 resume_s: float = 0.4, grace_s: float = 8.0,
                 floor_peak: float = 0.0):
        self.checkin_after_s = checkin_after_s
        self.speech_rms = speech_rms
        self.resume_s = resume_s
        self.grace_s = grace_s
        self.floor_peak = float(floor_peak)
        self._silent_s = 0.0
        self._speech_s = 0.0
        self._floor_speech_s = 0.0
        self._heard_speech = False
        self._asked = False
        self._asked_at_s: float | None = None

    @property
    def heard_speech(self) -> bool:
        """Whether at least one sustained, above-floor utterance ever landed.

        The session-level fact behind rule 3: with it, a close is a grace
        close after a check-in; without it, a close is silent.
        """
        return self._heard_speech

    def observe(self, frame: bytes, frame_s: float) -> bool:
        """True exactly once per segment: time for the soft check-in."""
        over_gate = frame_rms(frame) >= self.speech_rms
        # Below the energy floor the frame is NOT speech, even over the RMS
        # gate: it is room noise, a call on speaker, a fan (rule 2/3). With
        # floor_peak <= 0 the ladder keeps its exact pre-hotfix semantics.
        is_speech = over_gate and (self.floor_peak <= 0.0
                                   or pcm_peak(frame) >= self.floor_peak)
        if is_speech:
            self._silent_s = 0.0
            self._speech_s += frame_s
            self._floor_speech_s += frame_s
            if self._floor_speech_s >= self.resume_s:
                # A real utterance landed: from here the session may earn
                # check-ins, and this sustained run is a resumption — a new
                # segment, and a new check-in is earned. One frame above the
                # gate is not a resumption.
                self._heard_speech = True
                self._asked = False
                self._asked_at_s = None
            return False
        self._speech_s = 0.0
        self._floor_speech_s = 0.0
        self._silent_s += frame_s
        if not self._heard_speech:
            # Silence at session start can never produce a ladder line.
            return False
        if not self._asked and self._silent_s >= self.checkin_after_s:
            self._asked = True
            self._asked_at_s = self._silent_s
            return True
        return False

    def close_due(self) -> bool:
        """True once the session should close itself.

        Two schedules, one bound: after a check-in, the grace period running
        out ends the thought (VB-6). With NO utterance ever heard, the same
        window + grace closes the session SILENTLY (silence hotfix rule 1) —
        the microphone stays exactly as bounded as before, minus the voice.
        """
        if self._asked and self._asked_at_s is not None:
            return self._silent_s - self._asked_at_s >= self.grace_s
        return (not self._heard_speech
                and self._silent_s >= self.checkin_after_s + self.grace_s)


@dataclass
class SessionResult:
    session_id: str
    raw_text: str
    cleaned_text: str | None
    backend: str
    language: str
    audio_path: str | None
    inbox_path: str | None
    clipboard: dict
    flagged: bool
    duration_s: float
    transcript_id: int | None = None
    notes: list[str] = field(default_factory=list)
    confidence: float | None = None
    cloud_status: str = "complete"
    queued_job_ids: list[int] = field(default_factory=list)
    connectivity_mode: str | None = None
    # BUG 6 capture diagnostics (2026-10-20): the node, bytes and peak level
    # per session — "captured nothing" must be provable, not guessable.
    capture: dict | None = None
    no_speech: bool = False
    # A missing Live final is distinct from silence: the saved WAV may still
    # contain speech and is retained for a later retry/re-transcription.
    no_final: bool = False
    # The model of record for this session (scene-1 merge gate): rides into
    # the §4.8 schema lines as `model_version=…` so a press can be proven to
    # have been served, and by which model.
    model: str | None = None
    # G.6 latency sensor: monotonic mark at final.received / final.timeout,
    # so release→final is measured, never inferred.
    final_mark: float | None = None


def _final_texts(events) -> list[str]:
    """Final transcript segments in order, without the replayed tail's echoes.

    A rotation replays the buffered audio, so the new session can recognise the
    same words a second time. Dropping everything collected before the rotation
    (the old behaviour) destroyed the head of the dictation; suppressing only the
    immediately-repeated segment keeps every word and still reads cleanly.
    """
    out: list[str] = []
    for event in events:
        if event.type == "final" and event.text:
            text = " ".join(event.text.split())
            if out and out[-1] == text:
                continue
            out.append(text)
    return out


def _has_real_word(text: str) -> bool:
    """At least one real word: a token carrying an alphanumeric character.

    Silence-hotfix rule 3 — a punctuation-only or empty transcript is still
    silence, so it can never earn the soft check-in.
    """
    return any(any(ch.isalnum() for ch in token)
               for token in (text or "").split())


def _landed_real_words(events) -> bool:
    """Whether the Live stream has landed at least one real user word.

    The transcript-layer evidence for the check-in gate. Only INPUT
    interims/finals count: her own output transcription and echo-suppressed
    segments are not user utterances and are never in `collected` (BUG 6).
    """
    return any(event.type in ("interim", "final") and _has_real_word(event.text)
               for event in events)


class DictationService:
    # The Live path must have a terminal state even when the server omits
    # turn_complete/final after activity_end. Keep all shutdown/post-close
    # waits finite; capture diagnostics are persisted before these waits.
    ACTIVITY_END_TIMEOUT_S = 1.5
    FINAL_TRANSCRIPT_TIMEOUT_S = 2.5
    COLLECTOR_CANCEL_TIMEOUT_S = 0.5
    TRANSPORT_CLOSE_TIMEOUT_S = 1.5
    SOURCE_CLOSE_TIMEOUT_S = 1.5
    EVENT_EMIT_TIMEOUT_S = 1.0
    FALLBACK_TIMEOUT_S = 5.0
    CLEANUP_TIMEOUT_S = 3.0
    PERSIST_TIMEOUT_S = 6.0

    def __init__(self, config, store, client, *, mode_manager=None,
                 offline_queue=None, local_backend=None):
        self.config = config
        self.store = store
        self.client = client
        self.mode_manager = mode_manager
        self.offline_queue = offline_queue
        self.local_backend = local_backend
        self.cleanup = CleanupPass(config, client)
        settings = config.section("transcribe")
        asr_settings = config.section("asr")
        self.low_confidence_threshold = float(
            asr_settings.get("offline_low_confidence_threshold", 0.65))
        self.queue_cleanup_offline = bool(asr_settings.get("offline_queue_cleanup", True))
        self.replay_s = float(settings.get("reconnect_replay_s", 30))
        self.session_max_s = float(settings.get("live_session_max_s", 540))
        # Phase 8 restates §12.5 as a rule, not a preference: raw audio is
        # the truth that makes offline placeholders recoverable.
        self.save_audio = True
        self.inbox_dir = config.inbox_dir
        self.copy_clipboard = bool(settings.get("copy_to_clipboard", True))
        self.vad_threshold = float(settings.get("vad_rms_threshold", 0.01))
        # SILENCE HOTFIX rule 2: the audio-energy floor on measured input
        # peak ([voice] silence_floor). A session below it is silence
        # whatever the transcriber hallucinated — garbage-from-room-noise
        # transcripts included.
        self.silence_floor = float(
            config.section("voice").get(
                "silence_floor", DEFAULTS["voice"]["silence_floor"]))
        self.checkin_after = settings.get("checkin_after_s") or {}
        # How long speech must last before the ladder treats it as a resumption,
        # and how much silence after the one check-in closes the session (VB-5/6).
        self.resume_s = float(settings.get("speech_resume_s", 0.4))
        self.grace_s = float(settings.get("checkin_grace_s", 8.0))
        # Scene-3b-REDO stream E: the post-release wait for the final
        # transcript is a budget, named and configurable — never a magic
        # constant (the 2.5 s wall the reply regression died behind).
        self.final_wait_s = float(settings.get("final_wait_s", 12.0))
        self.audio_dir = config.data_dir / "audio"

    def _connectivity(self):
        """Mode snapshot for one session. A switch requested mid-session is
        parked by the daemon/manager, so this snapshot remains authoritative."""
        if self.mode_manager is None:
            return None
        # Snapshot only: the daemon monitor (or a one-shot CLI caller)
        # owns refreshes, so starting capture never waits on a probe.
        return self.mode_manager.status(refresh=False)

    def _cloud_status(self, *, backend: str, confidence: float | None,
                      raw: str, audio_path, offline: bool) -> str:
        local = backend == "local" or backend.startswith("local:")
        if audio_path is not None and (offline or local) and (
                not raw.strip() or confidence is None
                or confidence < self.low_confidence_threshold):
            return "pending_cloud_transcription"
        return "complete"

    def _enqueue_offline_work(self, result: SessionResult, *, offline: bool,
                              skip_cleanup: bool) -> SessionResult:
        if self.offline_queue is None or result.transcript_id is None:
            return result
        if result.cloud_status == "pending_cloud_transcription":
            job_id = self.offline_queue.enqueue_transcription(
                result.transcript_id, result.audio_path, result.language,
                result.session_id)
            result.queued_job_ids.append(job_id)
            result.notes.append(
                f"low-confidence offline transcript queued for Gemini redo (job #{job_id})")
            # §4.8: deferred work is visible, not silent — the audio path
            # ends in a queue row, and the marker names the job.
            log_event("transcription.deferred", session_id=result.session_id,
                      verdict="deferred",
                      detail=(f"low-confidence transcript queued for cloud "
                              f"redo (job #{job_id}); audio kept at "
                              f"{result.audio_path}"))
        if (offline and skip_cleanup and self.queue_cleanup_offline
                and result.raw_text.strip()):
            job_id = self.offline_queue.enqueue_cleanup(result.transcript_id)
            result.queued_job_ids.append(job_id)
            result.notes.append(f"transcript cleanup queued for reconnect (job #{job_id})")
            log_event("transcription.deferred", session_id=result.session_id,
                      verdict="deferred",
                      detail=f"cleanup queued for reconnect (job #{job_id})")
        return result

    # -- public entry points ---------------------------------------------------
    async def _next_frame(self, frame_iter, stop_event):
        """One frame, or None when PTT was released mid-read (BUG 6).

        The old loop only checked `stop_event` between frames; a wedged
        pw-record (readexactly never returning) meant Enter did nothing and
        `ptt.result` sat its full wait on a session that would never end.
        Racing the read against the release makes the release always win.
        """
        nxt = asyncio.ensure_future(frame_iter.__anext__())
        stop_wait = None
        if stop_event is not None:
            if stop_event.is_set():
                nxt.cancel()
                await asyncio.gather(nxt, return_exceptions=True)
                return None
            stop_wait = asyncio.ensure_future(stop_event.wait())
        try:
            await asyncio.wait({t for t in (nxt, stop_wait) if t is not None},
                               return_when=asyncio.FIRST_COMPLETED)
            if nxt.done():
                return nxt.result()      # StopAsyncIteration propagates = end
            return None                  # stop_event won: PTT released
        finally:
            for task in (nxt, stop_wait):
                if task is not None and not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    def _log(self, step: str, **fields) -> None:
        try:
            self.store.log_persona_event(
                iso_now(), "dictate.lifecycle",
                json.dumps({"step": step, **fields}))
        except Exception:
            return

    @staticmethod
    def _consume_task_result(task: asyncio.Future) -> None:
        """Retrieve late task failures after a bounded wait has returned."""
        if task.cancelled():
            return
        try:
            task.exception()
        except BaseException:
            return

    async def _await_lifecycle(self, step: str, awaitable, *, timeout_s: float,
                               session_id: str, **fields):
        """Name and bound a slow dictate await in the lifecycle journal.

        ``asyncio.wait`` is used instead of ``wait_for`` so a coroutine that
        ignores cancellation cannot keep the dictation task parked beyond its
        deadline. Timed-out work is cancelled and its eventual exception is
        consumed in the background; the caller can still construct a terminal
        result from the WAV.
        """
        timeout_s = max(0.0, float(timeout_s))
        started = time.monotonic()
        self._log(f"{step}_start", session_id=session_id,
                  timeout_s=timeout_s, **fields)
        task = asyncio.ensure_future(awaitable)
        timed_out = False
        try:
            done, _pending = await asyncio.wait(
                {task}, timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED)
            if not done:
                timed_out = True
                task.cancel()
                task.add_done_callback(self._consume_task_result)
                elapsed = round(time.monotonic() - started, 3)
                self._log(f"{step}_timeout", session_id=session_id,
                          timeout_s=timeout_s, elapsed_s=elapsed, **fields)
                raise TimeoutError(f"{step} timed out after {timeout_s:.1f}s")
            result = task.result()
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                task.add_done_callback(self._consume_task_result)
            self._log(f"{step}_cancelled", session_id=session_id,
                      elapsed_s=round(time.monotonic() - started, 3), **fields)
            raise
        except TimeoutError as exc:
            if not timed_out:
                self._log(f"{step}_failed", session_id=session_id,
                          elapsed_s=round(time.monotonic() - started, 3),
                          error=str(exc)[:200], **fields)
            raise
        except Exception as exc:
            self._log(f"{step}_failed", session_id=session_id,
                      elapsed_s=round(time.monotonic() - started, 3),
                      error=f"{type(exc).__name__}: {exc}"[:200], **fields)
            raise
        self._log(f"{step}_done", session_id=session_id,
                  elapsed_s=round(time.monotonic() - started, 3), **fields)
        return result

    async def dictate(self, source, *, transport_factory=None,
                      mode: str = "narration",
                      sink: EventSink | None = None,
                      stop_event: asyncio.Event | None = None,
                      is_playback_active: Callable[[], bool] | None = None,
                      session_id: str | None = None,
                      clock: Callable[[], float] | None = None) -> SessionResult:
        session_id = session_id or uuid.uuid4().hex[:12]
        emit = sink or _noop_sink
        self._log("dictate.enter", session_id=session_id, mode=mode, source_target=str(getattr(source, "target", None) or "default"))
        language = asr.primary_language(self.config)
        factory = transport_factory or (lambda: asr.make_live_transport(self.config))
        await emit({"event": "session.started", "session_id": session_id, "mode": mode})
        self._log("dictate.session_started", session_id=session_id)

        when = datetime.now().astimezone()
        wav_sink = None
        audio_path = None
        if self.save_audio:
            audio_path = self.audio_dir / f"{when:%Y%m%d-%H%M%S}-{session_id[:6]}.wav"
            wav_sink = WavSink(audio_path)
            self._log("dictate.wav_sink", session_id=session_id, audio_path=str(audio_path))

        buffer = RollingAudioBuffer(seconds=self.replay_s)
        gate = FrameGate(rms_threshold=self.vad_threshold)
        ladder = SilenceLadder(
            float(self.checkin_after.get(mode, 20)), speech_rms=self.vad_threshold,
            resume_s=self.resume_s, grace_s=self.grace_s,
            floor_peak=self.silence_floor)
        notes: list[str] = []

        async def emit_lifecycle_event(step: str, event: dict) -> None:
            try:
                await self._await_lifecycle(
                    step, emit(event), timeout_s=self.EVENT_EMIT_TIMEOUT_S,
                    session_id=session_id, event=event.get("event"))
            except Exception as exc:
                self._log(f"{step}_delivery_failed", session_id=session_id,
                          error=f"{type(exc).__name__}: {exc}"[:200])

        final_text = ""
        confidence: float | None = None
        connectivity = self._connectivity()
        offline_at_start = bool(connectivity and connectivity.is_offline)
        network_drop = False
        backend = "local" if offline_at_start else "gemini_live"
        duration_s = 0.0
        capture_stats: dict | None = None
        no_speech = False
        no_final = False
        live_terminal_missing = False
        final_mark: float | None = None   # G.6: set at final.* classification
        frame_loop_completed = False
        transport: LiveTransport | None = None
        collector: asyncio.Task | None = None
        collector_terminal_event: asyncio.Event | None = None
        collected: list[LiveEvent] = []
        live_event_counts: dict[str, int] = {}
        live_failed = False
        started = time.monotonic()
        rotations = 0
        resumption_handle: str | None = None
        # BUG6: frames the Live path refused (output playback or the local-TTS
        # guard). They reach neither the uplink, the replay buffer, the ladder
        # nor the archive: her own voice is not the user's dictation.
        gated_frames = 0
        gate_announced = False
        live_failures: list[str] = []
        # BH-K3 tail accounting, in AUDIO time (not wall clock, so burst
        # and realtime sources agree): seconds of speech-level audio sent,
        # and how much had been sent when the last committed final arrived.
        # Speech sent AFTER the last final is by construction not covered
        # by any committed segment.
        sent_speech_s = 0.0
        speech_s_at_last_final: float | None = None
        # BUG 6 capture diagnostics: what the mic actually delivered this
        # session (before any gate) — node, bytes, peak. Logged + reported.
        # SILENCE HOTFIX rule 2: `session_peak` is the measured INPUT PEAK
        # (capture.pcm_peak — the capture.stats/doctor-peak mechanism) that
        # the [voice] silence_floor verdict reads; `peak_rms` (the loudest
        # frame RMS) stays for the existing §8 near-zero-audio rule.
        captured_bytes = 0
        peak_rms = 0.0
        session_peak = 0.0
        frames_seen = 0
        capture_label = str(getattr(source, "target", None) or "default")

        def uplink_blocked(current: LiveTransport | None) -> str | None:
            """Why the mic must stay shut right now, or None when it may open."""
            if is_playback_active is not None:
                try:
                    if is_playback_active():
                        return "local_playback"
                except Exception:
                    return "local_playback_probe_failed"
            gate_ = getattr(current, "gate", None)
            if gate_ is None:
                return None
            if gate_.playing():
                return "live_output_audio"
            if gate_.gate_closed():
                return "live_output_guard"
            return None

        async def collect_events(current: LiveTransport,
                                 terminal_event: asyncio.Event) -> None:
            nonlocal resumption_handle, live_failed, speech_s_at_last_final
            try:
                async for event in current.events():
                    live_event_counts[event.type] = live_event_counts.get(event.type, 0) + 1
                    # BUG6: only transcribable INPUT belongs in the transcript
                    # record. Output audio/text from the session are her own voice
                    # and are deliberately never appended to `collected`, so they
                    # cannot become a final by any later path.
                    if event.type in ("interim", "final", "go_away", "resumption",
                                      "error", "turn_complete"):
                        collected.append(event)
                    # A final is sufficient to make the transcript terminal; Live
                    # implementations have also been observed to omit turn_complete.
                    # BH-K3: turn_complete is deliberately NOT a terminal here:
                    # on the transcription-only model a committed segment can
                    # arrive AFTER the boundary (test_bug6f), so treating it
                    # as terminal would close the wait just before the tail
                    # final lands. (Conversational models flush their final
                    # BEFORE the boundary, so they lose nothing.)
                    if event.type in ("final", "error"):
                        terminal_event.set()
                    if event.type == "final":
                        speech_s_at_last_final = sent_speech_s
                    if event.type == "interim":
                        await emit({"event": "transcript.interim", "text": event.text,
                                    "session_id": session_id})
                    elif event.type in ("output_interim", "output_final"):
                        await emit({"event": "live.output_transcript",
                                    "text": event.text,
                                    "final": event.type == "output_final",
                                    "session_id": session_id})
                    elif event.type == "output_audio":
                        await emit({"event": "live.output_audio",
                                    "seconds": round(event.duration_s, 3),
                                    "sample_rate": event.sample_rate,
                                    "session_id": session_id})
                    elif event.type == "echo_suppressed":
                        await emit({"event": "transcript.echo_suppressed",
                                    "reason": event.reason or "live echo",
                                    "text": event.text,
                                    "session_id": session_id})
                    elif event.type == "resumption" and event.handle:
                        resumption_handle = event.handle
                    elif event.type == "error":
                        live_failed = True
                        error = event.error or "Live receiver failed"
                        live_failures.append(f"receive: {error}")
                        self._ledger_live_failure(stage="receive", error=error)
            finally:
                # EOF/error is terminal too, even if no final text was emitted.
                terminal_event.set()

        async def wait_for_live_terminal(current_collector: asyncio.Task | None,
                                         terminal_event: asyncio.Event | None) -> None:
            if (terminal_event is None or terminal_event.is_set()
                    or current_collector is None or current_collector.done()):
                if current_collector is not None and current_collector.done():
                    current_collector.result()
                return
            terminal_wait = asyncio.create_task(terminal_event.wait())
            try:
                done, _pending = await asyncio.wait(
                    {current_collector, terminal_wait},
                    return_when=asyncio.FIRST_COMPLETED)
                if current_collector in done:
                    current_collector.result()
            finally:
                if not terminal_wait.done():
                    terminal_wait.cancel()
                    await asyncio.gather(terminal_wait, return_exceptions=True)

        def wrap_duplex(current: LiveTransport) -> LiveTransport:
            """One door for both the real and the fake transport (§12.9)."""
            if isinstance(current, DuplexLiveTransport):
                return current
            return DuplexLiveTransport(
                current, external_playback=is_playback_active, clock=clock)

        async def open_session(handle: str | None) -> LiveTransport:
            nonlocal collector, collector_terminal_event
            current = wrap_duplex(factory())
            await current.connect(handle)
            await current.activity_start()
            collector_terminal_event = asyncio.Event()
            collector = asyncio.create_task(
                collect_events(current, collector_terminal_event))
            return current

        self._log("dictate.transport_open_attempt", session_id=session_id, offline_at_start=str(offline_at_start))
        if offline_at_start:
            notes.append("offline mode: local ASR only; raw audio saved for any redo")
            await emit({"event": "session.offline", "backend": "local",
                        "connectivity": connectivity.effective_mode if connectivity else None,
                        "session_id": session_id})
            self._log("dictate.offline", session_id=session_id)
        else:
            try:
                transport = await open_session(None)
                self._log("dictate.transport_opened", session_id=session_id)
            except Exception as exc:
                from .modes import looks_like_network_failure

                live_failed = True
                network_drop = looks_like_network_failure(exc)
                if network_drop and self.mode_manager is not None:
                    self.mode_manager.observe_failure(exc, "gemini_live")
                # BUG6 cost audit: a Live failure is a ledger row with a
                # purpose tag, even when the fallback succeeds. A silent
                # failure is exactly what "5 failures, all key/voice" cannot
                # rule out by inspection.
                live_failures.append(f"connect: {exc}")
                self._ledger_live_failure(stage="connect", error=str(exc))
                notes.append(f"live connect failed ({exc}) — will transcribe the saved audio")
                await emit({"event": "session.reconnecting", "reason": str(exc),
                            "fallback": "local" if network_drop else "gemini_batch",
                            "session_id": session_id})

        try:
            # BUG 6: the release must win against a capture process that is
            # delivering nothing — see _next_frame. PTT released mid-read ends
            # the session now, not after the CLI's ptt.result wait expires.
            frame_iter = source.frames().__aiter__()
            while True:
                if stop_event and stop_event.is_set():
                    break
                try:
                    frame = await self._next_frame(frame_iter, stop_event)
                except StopAsyncIteration:
                    break
                if frame is None:
                    break                # PTT released mid-read
                frames_seen += 1
                captured_bytes += len(frame)
                level = frame_rms(frame)
                peak_rms = max(peak_rms, level)
                session_peak = max(session_peak, pcm_peak(frame))
                frame_s = len(frame) / 2 / 16000
                # BUG6: half-duplex inside the Live session. While her output
                # is playing (or inside the ~400 ms guard), a frame is her own
                # voice through the speakers. It is not buffered (a rotation
                # would replay it as "user" audio), not fed to the silence
                # ladder, and never uploaded. Discarded, not held: holding
                # would send the echo the moment playback ends.
                #
                # It does not reach the archive either: the saved WAV is the
                # source of the §12.7 batch fallback, so writing her own line
                # there would re-enter it as "user" text whenever Live fails —
                # the same bug through a slower door.
                blocked_reason = uplink_blocked(transport)
                if blocked_reason is not None:
                    gated_frames += 1
                    if not gate_announced:
                        gate_announced = True
                        await emit({"event": "live.uplink_gated", "state": "closed",
                                    "reason": blocked_reason,
                                    "session_id": session_id})
                    continue
                if gate_announced:
                    gate_announced = False
                    await emit({"event": "live.uplink_gated", "state": "open",
                                "dropped_frames": gated_frames,
                                "session_id": session_id})
                duration_s += frame_s
                if wav_sink:
                    wav_sink.write(frame)
                buffer.push(frame)
                if ladder.observe(frame, frame_s):
                    # SILENCE HOTFIX rule 3 — transcript layer: with a Live
                    # session running, the check-in is earned only once at
                    # least one real word has landed. (The ladder itself
                    # holds the audio layer: sustained speech at or over the
                    # energy floor.) Offline / Live-down sessions have no
                    # mid-session word source, so the ladder's audio
                    # evidence is the gate there.
                    if transport is None or _landed_real_words(collected):
                        await emit({"event": "session.checkin", "prompt": "Is that all?",
                                    "session_id": session_id})
                    else:
                        notes.append(
                            "check-in withheld: no word had landed to ask about")
                elif ladder.close_due():
                    if ladder.heard_speech:
                        # VB-6: the thought ended. Release the microphone instead of
                        # holding it open until the hotkey; the words already heard
                        # are kept, which is exactly what the check-in was for.
                        notes.append(f"closed after the check-in grace ({ladder.grace_s:g}s "
                                     f"of continued silence)")
                        await emit({"event": "session.grace_close", "session_id": session_id,
                                    "silence_after_checkin_s": round(ladder.grace_s, 3)})
                    else:
                        # SILENCE HOTFIX rule 1: a session nobody spoke into
                        # closes on the same bounded schedule (window +
                        # grace) — silently. No ladder line, no voice; the
                        # plain-language verdict lands with the capture
                        # stats below ("she heard nothing").
                        notes.append("closed by the endpointing window — "
                                     "no speech ever landed")
                    break
                if transport is None or not gate.allows(frame):
                    continue
                try:
                    # Rotation: never ride a session into its lifetime cap.
                    if rotations == 0 and time.monotonic() - started > self.session_max_s:
                        raise LiveUnavailable("proactive rotation at session age cap")
                    if any(e.type == "go_away" for e in collected):
                        # VB-7: finals are TRANSCRIBED TEXT and are not recoverable
                        # from the replay buffer, so clearing the list deleted the
                        # first words of any dictation longer than the buffer. Only
                        # the GoAway markers may be consumed (leaving them would
                        # spin the rotation); duplicates from the replayed tail are
                        # folded when the finals are joined.
                        collected[:] = [e for e in collected if e.type != "go_away"]
                        # §4.8: GoAway is a graceful close plus a visible marker,
                        # never a silent drop. The session rotates; captured audio
                        # is kept (prime directive).
                        log_event("goaway.close", level="warn",
                                  session_id=str(session_id or ""),
                                  verdict="closed",
                                  detail=("server GoAway — graceful close, session "
                                          "rotating; captured audio kept"))
                        raise LiveUnavailable("server GoAway — rotating session")
                    await transport.send_audio(frame)
                    if level >= self.vad_threshold:
                        sent_speech_s += frame_s
                    # Yield so the event collector can surface interims /
                    # GoAway promptly even with burst (non-realtime) sources.
                    await asyncio.sleep(0)
                except Exception as exc:
                    # Reconnect + replay the buffered tail (§3.5). One
                    # rotation is expected behaviour; repeated failure
                    # hands off to the batch chain instead of looping.
                    await emit({"event": "session.reconnecting", "reason": str(exc),
                                "session_id": session_id})
                    if collector:
                        collector.cancel()
                        try:
                            await self._await_lifecycle(
                                "dictate.rotation_collector_cancel_wait",
                                asyncio.gather(collector, return_exceptions=True),
                                timeout_s=self.COLLECTOR_CANCEL_TIMEOUT_S,
                                session_id=session_id)
                        except Exception as cleanup_exc:
                            notes.append(
                                f"rotated Live collector did not stop cleanly ({cleanup_exc})")
                    try:
                        await self._await_lifecycle(
                            "dictate.rotation_transport_close", transport.close(),
                            timeout_s=self.TRANSPORT_CLOSE_TIMEOUT_S,
                            session_id=session_id)
                        if rotations >= 1:
                            raise LiveUnavailable("rotation limit reached for this session")
                        transport = await open_session(resumption_handle)
                        rotations += 1
                        started = time.monotonic()
                        tail = buffer.tail()
                        for i in range(0, len(tail), 960):  # 30ms frames
                            await transport.send_audio(tail[i:i + 960])
                        notes.append("session rotated; buffered tail replayed")
                    except Exception as retry_exc:
                        from .modes import looks_like_network_failure

                        live_failed = True
                        network_drop = (network_drop or looks_like_network_failure(exc)
                                        or looks_like_network_failure(retry_exc))
                        if network_drop and self.mode_manager is not None:
                            self.mode_manager.observe_failure(retry_exc, "gemini_live")
                        live_failures.append(f"reconnect: {retry_exc}")
                        self._ledger_live_failure(stage="reconnect",
                                                  error=str(retry_exc))
                        transport = None
                        notes.append(f"reconnect failed ({retry_exc}) — saved-audio fallback")
            frame_loop_completed = True
            self._log("dictate.frame_loop_done", session_id=session_id,
                      frames_seen=frames_seen, bytes=captured_bytes,
                      duration_s=round(duration_s, 3))

            # PTT released / source exhausted: close the utterance. A Live
            # server may omit its final/turn_complete after activity_end, so
            # both the signal and the receive-loop wait are explicitly bounded.
            if transport is not None:
                # A committed segment received while the mic was still open
                # is not confirmation of the *last* activity. Do not let an
                # earlier final skip the wait for the tail after release (6f).
                # Clear BEFORE sending activity_end so an immediate final
                # delivered during the send cannot be lost.
                if collector_terminal_event is not None:
                    collector_terminal_event.clear()
                activity_end_ok = False
                try:
                    await self._await_lifecycle(
                        "dictate.activity_end",
                        transport.activity_end(),
                        timeout_s=self.ACTIVITY_END_TIMEOUT_S,
                        session_id=session_id)
                    activity_end_ok = True
                except Exception as exc:
                    live_failed = True
                    live_failures.append(f"activity_end: {exc}")
                    notes.append(f"Live activity_end failed ({exc}); will use committed text or saved-WAV fallback")

                collector_state = ("none" if collector is None
                                   else "done" if collector.done() else "alive")
                final_wait_started = time.monotonic()
                final_wait_note = ""
                # Stream E (2026-10-26): schema events that name the
                # flush. final.wait fires at EVERY flush of a live
                # session — its absence in a journal is the signal that
                # we hung up before the flush arrived. final.received /
                # final.timeout say what actually happened, naming a
                # dead collector honestly instead of pretending to wait.
                log_event("final.wait", session_id=session_id,
                          verdict="waiting",
                          detail=(f"budget_s={self.final_wait_s}; "
                                  f"collector={collector_state}; "
                                  f"activity_end_ok={activity_end_ok}"))
                if activity_end_ok and collector is not None:
                    try:
                        await self._await_lifecycle(
                            "dictate.transcript_final_wait",
                            wait_for_live_terminal(collector,
                                                   collector_terminal_event),
                            timeout_s=self.final_wait_s,
                            session_id=session_id)
                    except TimeoutError:
                        live_terminal_missing = True
                        final_wait_note = (f"budget expired after "
                                           f"{self.final_wait_s}s")
                        notes.append(
                            "Live final transcript timed out after activity_end; "
                            "will use committed text or saved-WAV fallback")
                    except Exception as exc:
                        live_terminal_missing = True
                        live_failed = True
                        final_wait_note = f"final wait failed ({exc})"
                        live_failures.append(f"final wait: {exc}")
                        notes.append(f"Live final wait failed ({exc}); "
                                     "will use committed text or saved-WAV fallback")
                elif collector is None:
                    final_wait_note = "no live collector — final wait skipped"
                elif not activity_end_ok:
                    final_wait_note = "activity_end failed — final wait skipped"
                diagnostics = {}
                try:
                    describe = getattr(transport, "diagnostics", None)
                    if callable(describe):
                        diagnostics = describe()
                except Exception:
                    diagnostics = {"unavailable": True}
                self._log("dictate.live_receive_summary", session_id=session_id,
                          activity_end_ok=activity_end_ok, frames_seen=frames_seen,
                          event_counts=dict(live_event_counts), transport=diagnostics)
                finals = _final_texts(collected)
                final_text = " ".join(finals).strip()
                waited_s = round(time.monotonic() - final_wait_started, 3)
                final_mark = time.monotonic()
                if final_text:
                    log_event("final.received", session_id=session_id,
                              verdict="received",
                              detail=(f"text_chars={len(final_text)}; "
                                      f"waited_s={waited_s}"
                                      + (f"; {final_wait_note}"
                                         if final_wait_note else "")))
                else:
                    live_terminal_missing = True
                    self._log("dictate.live_no_final", session_id=session_id,
                              activity_end_ok=activity_end_ok,
                              frames_seen=frames_seen)
                    note = final_wait_note
                    if not note:
                        # A collector that finished WITHOUT delivering a final
                        # is the sever: the link died mid-utterance. (A
                        # collector that finished AFTER its final is the
                        # healthy path — that lands in final.received.) The
                        # CURRENT state decides: death can come mid-wait.
                        collector_dead = (collector is None or collector.done())
                        note = ("collector ended with no final "
                                "(live link died?)"
                                if collector_dead
                                else "terminal reached with no final text")
                    log_event("final.timeout", level="warn",
                              session_id=session_id,
                              verdict="missing",
                              detail=(f"waited_s={waited_s}; "
                                      f"collector={collector_state}; "
                                      + note))
                # Stream F sensors (2026-10-26): the deciding fork lives on
                # the wire. ws.histogram counts every message type the Live
                # session received (unparsed shapes sampled, text-only);
                # audio.sent meters what we actually pushed to the socket.
                wire = None
                describe_wire = getattr(transport, "wire_stats", None)
                if callable(describe_wire):
                    try:
                        wire = describe_wire()
                    except Exception:  # a sensor never breaks close
                        wire = None
                if isinstance(wire, dict):
                    types = wire.get("types") or {}
                    samples = wire.get("samples") or []
                    setup_ok = bool(wire.get("setup_complete"))
                    log_event("ws.histogram", session_id=session_id,
                              verdict="wire",
                              detail=(f"setup={'ok' if setup_ok else 'missing'}"
                                      f"; voice_end={str(bool(wire.get('voice_end'))).lower()}"
                                      f"; transcript_family={int(wire.get('transcript_family') or 0)}"
                                      f"; types={json.dumps(types, sort_keys=True)}"
                                      + (f"; samples={json.dumps(samples)[:600]}"
                                         if samples else "")))
                    sent = wire.get("audio_sent") or {}
                    log_event("audio.sent", session_id=session_id,
                              verdict="sent",
                              detail=(f"chunks={int(sent.get('chunks') or 0)} "
                                      f"bytes={int(sent.get('bytes') or 0)} "
                                      f"format={sent.get('format') or '?'} "
                                      f"rate={sent.get('rate') or '?'}"))
            duplex = {}
            if transport is not None and getattr(transport, "gate", None) is not None:
                duplex = transport.gate.snapshot()
                gated_frames = max(gated_frames, int(duplex.get("frames_dropped", 0)))
            if gated_frames or duplex.get("echo_suppressed"):
                notes.append(
                    "Live half-duplex: "
                    f"{gated_frames} mic frame(s) not uploaded while output played; "
                    f"{int(duplex.get('echo_suppressed', 0))} self-audio segment(s) refused")
                await emit({"event": "live.duplex", "session_id": session_id,
                            "gated_frames": gated_frames,
                            "echo_suppressed": int(duplex.get("echo_suppressed", 0)),
                            "playbacks": int(duplex.get("playbacks", 0)),
                            "output_audio_bytes": int(duplex.get("output_audio_bytes", 0))})
        except Exception as exc:
            # A capture/source/event failure is still a terminal session. Keep
            # whatever final text was already collected and transcribe the WAV
            # below rather than letting ptt.result turn it into silence.
            final_text = " ".join(_final_texts(collected)).strip()
            live_failed = True
            live_terminal_missing = not bool(final_text)
            live_failures.append(f"dictate: {type(exc).__name__}: {exc}")
            notes.append(f"dictation pipeline failed ({exc}); will use committed text or saved-WAV fallback")
            self._log("dictate.pipeline_failed", session_id=session_id,
                      error=f"{type(exc).__name__}: {exc}"[:200])
        finally:
            self._log("dictate.cleanup_start", session_id=session_id)
            if not frame_loop_completed:
                self._log("dictate.frame_loop_incomplete", session_id=session_id,
                          frames_seen=frames_seen, bytes=captured_bytes)
            if wav_sink:
                self._log("dictate.wav_close_start", session_id=session_id)
                try:
                    duration_s = wav_sink.close() or duration_s
                    self._log("dictate.wav_closed", session_id=session_id,
                              duration_s=round(duration_s, 3))
                except Exception as exc:
                    self._log("dictate.wav_close_failed", session_id=session_id,
                              error=str(exc)[:120])

            # Persist capture.stats before ANY cleanup await. If a transport or
            # source close is wedged, status still reports the bytes/peak and
            # points at the WAV that contains the owner's speech.
            self._log("dictate.capture_diagnostics", session_id=session_id,
                      frames_seen=frames_seen, bytes=captured_bytes)
            try:
                stalled = bool(getattr(source, "stalled", False))
            except Exception:
                stalled = False
            # SILENCE HOTFIX rule 2: the audio-energy floor. `session_peak`
            # is the measured input peak (capture.pcm_peak — the same
            # mechanism capture.stats and the doctor level check report;
            # owner speech proven at 0.8624). Below [voice] silence_floor
            # the session IS silence, whatever the transcriber hallucinated
            # from room noise — garbage transcripts included. The §8
            # near-zero-RMS rule stays: it catches peaky ticks that clear
            # the floor but carry no audible speech.
            no_speech = (captured_bytes == 0 or peak_rms < 0.003
                         or session_peak < self.silence_floor)
            capture_stats = {
                "session_id": session_id,
                "node": capture_label, "bytes": captured_bytes,
                "peak_rms": round(peak_rms, 4), "frames": frames_seen,
                "peak": round(session_peak, 4),
                "silence_floor": round(self.silence_floor, 4),
                "duration_s": round(duration_s, 3), "gated_frames": gated_frames,
                "stalled": stalled, "no_speech": no_speech,
            }
            if stalled:
                notes.append("capture stalled — the capture process delivered no data")
            if no_speech:
                # §8: a transcript from ~zero audio is a hallucination, whatever
                # produced it. The words are not there to report.
                if final_text:
                    notes.append(
                        "transcript discarded: the session captured no usable audio (§8)")
                final_text = ""
                notes.append(
                    f"no speech captured (node={capture_label}, bytes={captured_bytes}, "
                    f"peak={peak_rms:.4f})")
                # Rule 1: the plain-language line, in the session's own words.
                notes.append(HEARD_NOTHING)
            try:
                self.store.log_persona_event(
                    iso_now(), "capture.stats", json.dumps(capture_stats))
                self._log("dictate.capture_stats_logged", **capture_stats)
            except Exception as exc:
                self._log("dictate.capture_stats_log_failed", session_id=session_id,
                          error=f"{type(exc).__name__}: {exc}"[:200])
            if no_speech:
                # Rule 1: the session journal carries the same plain line.
                # Durable before any close await, like capture.stats — a
                # wedged transport close cannot lose it. No popup, no voice.
                silent_close = {
                    "message": HEARD_NOTHING,
                    "session_id": session_id,
                    "node": capture_label,
                    "bytes": captured_bytes,
                    "peak": round(session_peak, 4),
                    "peak_rms": round(peak_rms, 4),
                    "silence_floor": round(self.silence_floor, 4),
                }
                try:
                    self.store.log_persona_event(
                        iso_now(), "session.silent_close", json.dumps(silent_close))
                    self._log("dictate.silent_close_logged", session_id=session_id)
                except Exception as exc:
                    self._log("dictate.silent_close_log_failed", session_id=session_id,
                              error=f"{type(exc).__name__}: {exc}"[:200])
                # §4.8 schema line: the silence verdict with the measured peak
                # — the sensor for "she heard nothing" (kept audio: none needed,
                # but the transcript journal still holds the empty session).
                log_event("silence.verdict", session_id=session_id,
                          peak=round(session_peak, 4), verdict="silence",
                          detail=(f"{HEARD_NOTHING} — node {capture_label}, "
                                  f"{captured_bytes} bytes, peak "
                                  f"{round(session_peak, 4)} under floor "
                                  f"{round(self.silence_floor, 4)}"))

            # Watch-item hardening (2026-10-26, stream F): close the
            # transport BEFORE cancelling the collector, so the receiver
            # stops producing into a queue nobody drains before its
            # consumer dies. WP1 owns the 1.4 GB daemon-run profile.
            if transport is not None:
                try:
                    await self._await_lifecycle(
                        "dictate.transport_close", transport.close(),
                        timeout_s=self.TRANSPORT_CLOSE_TIMEOUT_S,
                        session_id=session_id)
                    self._log("dictate.transport_closed", session_id=session_id)
                except Exception as exc:
                    notes.append(f"Live transport close did not finish cleanly ({exc})")
                    self._log("dictate.transport_close_failed", session_id=session_id,
                              error=f"{type(exc).__name__}: {exc}"[:200])

            if collector is not None and not collector.done():
                self._log("dictate.collector_cancel_start", session_id=session_id)
                collector.cancel()
                try:
                    await self._await_lifecycle(
                        "dictate.collector_cancel_wait",
                        asyncio.gather(collector, return_exceptions=True),
                        timeout_s=self.COLLECTOR_CANCEL_TIMEOUT_S,
                        session_id=session_id)
                    self._log("dictate.collector_cancelled", session_id=session_id)
                except Exception as exc:
                    notes.append(f"Live event collector did not stop cleanly ({exc})")
            try:
                await self._await_lifecycle(
                    "dictate.source_close", source.aclose(),
                    timeout_s=self.SOURCE_CLOSE_TIMEOUT_S,
                    session_id=session_id,
                    target=str(getattr(source, "target", None) or "default"))
                self._log("dictate.source_closed", session_id=session_id,
                          target=str(getattr(source, "target", None) or "default"))
            except Exception as exc:
                notes.append(f"capture source close did not finish cleanly ({exc})")
                self._log("dictate.source_close_failed", session_id=session_id,
                          error=f"{type(exc).__name__}: {exc}"[:200])

            # Store logging above is authoritative. Event delivery is best-effort
            # and bounded so a broken subscriber cannot hold ptt.result hostage.
            try:
                await self._await_lifecycle(
                    "dictate.capture_stats_emit",
                    emit({"event": "capture.stats", "session_id": session_id,
                          **capture_stats}),
                    timeout_s=self.EVENT_EMIT_TIMEOUT_S,
                    session_id=session_id)
            except Exception as exc:
                self._log("dictate.capture_stats_emit_failed", session_id=session_id,
                          error=f"{type(exc).__name__}: {exc}"[:200])
            if no_speech:
                # Rule 1: the verdict is also an event, so the daemon carries
                # the plain line into console status live. The overlay
                # ignores unknown events and session.ended hides the pill:
                # a silent close makes no popup and no sound.
                await emit_lifecycle_event(
                    "dictate.silent_close_emit",
                    {"event": "session.silent_close", "message": HEARD_NOTHING,
                     "session_id": session_id,
                     "peak": round(session_peak, 4),
                     "silence_floor": round(self.silence_floor, 4)})

        use_offline_chain = offline_at_start or network_drop
        # BH-K3: when may the saved-WAV batch result replace Live text?
        # Only with positive evidence the Live text is missing or
        # incomplete:
        #   * nothing was committed at all, or
        #   * speech-level audio was sent after the last committed final
        #     (no segment can cover it) AND the session did not reach a
        #     clean terminal after release (the wait resolved on a
        #     post-release final without timing out or failing).
        # A bare timeout after activity_end is NOT such evidence: when
        # every segment committed during speech and no speech followed
        # the last final, the old code still re-transcribed the WAV and
        # silently swapped the user's Live transcript for the batch one
        # (doubling the cost of every affected dictation).
        uncommitted_speech_s = (
            sent_speech_s - speech_s_at_last_final
            if speech_s_at_last_final is not None else 0.0)
        # The post-release wait ended because a terminal actually arrived
        # (not the timeout, not a failure). turn_complete alone does not
        # count: the collector no longer treats it as terminal (above).
        clean_terminal = not live_terminal_missing and not live_failed
        tail_unconfirmed = uncommitted_speech_s > 0 and not clean_terminal
        needs_fallback = (not final_text or tail_unconfirmed) and not no_speech
        if final_text and needs_fallback:
            notes.append(
                f"Live transcript may be incomplete: {uncommitted_speech_s:.2f}s "
                "of speech followed the last committed segment and no clean "
                "terminal arrived; recovering from saved audio")
        elif final_text and (live_failed or live_terminal_missing):
            notes.append(
                "Live session ended without a clean terminal, but no speech "
                "followed the last committed segment; committed Live "
                "transcript kept (batch re-transcription not substituted; "
                "saved audio retained)")
        if needs_fallback:
            if audio_path is not None:
                try:
                    fallback = await self._await_lifecycle(
                        "dictate.saved_wav_fallback",
                        asyncio.to_thread(
                            asr.transcribe_file, self.config, self.client,
                            str(audio_path), offline=use_offline_chain,
                            local_backend=self.local_backend),
                        timeout_s=self.FALLBACK_TIMEOUT_S,
                        session_id=session_id, audio_path=str(audio_path),
                        offline=use_offline_chain)
                    fallback_text = str(getattr(fallback, "text", "") or "").strip()
                    if fallback_text:
                        final_text = fallback_text
                        backend = str(getattr(fallback, "backend", backend))
                        confidence = getattr(fallback, "confidence", None)
                        language = str(getattr(fallback, "language", language))
                        notes.append(f"transcribed via fallback backend '{backend}'")
                        if not getattr(fallback, "language_ok", True):
                            notes.append(
                                f"language assertion failed: backend reported "
                                f"{language!r} outside the pinned set — "
                                "transcript may be silently translated (§12.4)")
                    else:
                        notes.append("saved-WAV fallback returned no transcript")
                except Exception as exc:
                    await emit_lifecycle_event(
                        "dictate.fallback_error_emit",
                        {"event": "error", "error": str(exc),
                         "session_id": session_id})
                    if not final_text:
                        backend = "local" if use_offline_chain else backend
                    notes.append(f"saved-WAV fallback failed: {exc}")
            else:
                notes.append("saved-WAV fallback unavailable: no audio file was saved")
            if backend == "gemini_live" and live_failed and not final_text:
                backend = "local" if use_offline_chain else "gemini_batch"

        no_final = bool(not final_text and not no_speech)
        if no_final:
            notes.append(
                "no final transcript is available; captured audio is retained for retry")
            self._log("dictate.no_final_terminal", session_id=session_id,
                      live_final_missing=live_terminal_missing,
                      audio_path=str(audio_path) if audio_path else None,
                      bytes=captured_bytes, duration_s=round(duration_s, 3))

        cloud_status = self._cloud_status(
            backend=backend, confidence=confidence, raw=final_text,
            audio_path=audio_path, offline=use_offline_chain)
        model = (self.config.model_for_role(
            "transcribe_live" if backend == "gemini_live" else "transcribe_batch")
            if backend != "local" else self.config.section("asr").get(
                "offline_model", "small"))
        try:
            result = await self._await_lifecycle(
                "dictate.persist",
                self._persist(
                    session_id=session_id, when=when, raw=final_text,
                    backend=backend, language=language, audio_path=audio_path,
                    duration_s=duration_s, model=model, notes=notes,
                    confidence=confidence, cloud_status=cloud_status,
                    skip_cleanup=use_offline_chain,
                    connectivity_mode=(connectivity.effective_mode
                                       if connectivity else None),
                    lifecycle_dictate=True),
                timeout_s=self.PERSIST_TIMEOUT_S, session_id=session_id,
                no_final=no_final)
        except Exception as exc:
            notes.append(f"transcript persistence failed ({exc}); raw audio retained")
            self._log("dictate.persist_terminal_fallback", session_id=session_id,
                      error=f"{type(exc).__name__}: {exc}"[:200])
            result = SessionResult(
                session_id=session_id, raw_text=final_text,
                cleaned_text=None, backend=backend, language=language,
                audio_path=str(audio_path) if audio_path else None,
                inbox_path=None,
                clipboard={"copied": False,
                           "reason": "transcript persistence failed"},
                flagged=False, duration_s=duration_s, transcript_id=None,
                notes=notes, confidence=confidence, cloud_status=cloud_status,
                connectivity_mode=(connectivity.effective_mode
                                   if connectivity else None),
                model=model)
        if final_mark is not None and getattr(result, "final_mark", None) is None:
            result.final_mark = final_mark
        try:
            result = self._enqueue_offline_work(
                result, offline=use_offline_chain,
                skip_cleanup=use_offline_chain)
        except Exception as exc:
            notes.append(f"offline follow-up could not be queued ({exc})")
            self._log("dictate.offline_queue_failed", session_id=session_id,
                      error=f"{type(exc).__name__}: {exc}"[:200])
        result.capture = capture_stats
        result.no_speech = no_speech
        result.no_final = no_final
        # BH-K1: there is deliberately NO post-hoc "filler echo" filter here.
        # The old BUG5 block ran AFTER _persist and, on any FILLER_PHRASES
        # substring, replaced the returned result with an empty one
        # (raw/cleaned/inbox/clipboard/transcript_id all falsified) while
        # the store row kept the real words — dictating an email ending in
        # "let me know how I can help" returned nothing at all. Echo defence
        # is upstream and evidence-based: frames captured while she plays
        # never reach the uplink or the WAV, DuplexLiveTransport refuses
        # self-audio finals, and the daemon strips by comparing against the
        # exact text she spoke (Daemon._strip_self_echo). A substring
        # resemblance to her filler is not evidence about user speech.
        self._ledger_live_session(
            backend, duration_s, ok=bool(final_text),
            error=(" | ".join(live_failures) if live_failures else None))
        shown = result.cleaned_text if (result.cleaned_text and not result.flagged) else result.raw_text
        if no_final:
            await emit_lifecycle_event(
                "dictate.no_final_emit",
                {"event": "transcript.no_final",
                 "message": ("No final transcript was returned; captured audio "
                             "is retained for retry."),
                 "audio_path": str(audio_path) if audio_path else None,
                 "session_id": session_id})
            # §4.8: a failure in the audio path is a visible marker line that
            # keeps the recording, referenced by path (prime directive).
            log_event("transcription.deferred", level="warn",
                      session_id=session_id, verdict="no_final",
                      detail=(f"model_version={getattr(result, 'model', None) or model}; "
                              "no final transcript returned — audio kept at "
                              f"{audio_path if audio_path else '(memory only)'}, "
                              "retained for retry"))
        else:
            await emit_lifecycle_event(
                "dictate.transcript_final_emit",
                {"event": "transcript.final", "text": shown,
                 "inbox_path": result.inbox_path, "session_id": session_id})
            # §4.8: the transcription landed — text committed, audio kept.
            log_event("transcription.landed", session_id=session_id,
                      verdict="landed",
                      detail=(f"model_version={getattr(result, 'model', None) or model}; "
                              f"{len(shown)} chars committed"
                              + (f"; audio kept at {audio_path}" if audio_path
                                 else "")))
        await emit_lifecycle_event(
            "dictate.session_ended_emit",
            {"event": "session.ended", "session_id": session_id,
             "backend": backend, "duration_s": round(duration_s, 2),
             "no_speech": no_speech, "no_final": no_final,
             "capture": capture_stats})
        return result

    async def transcribe_file(self, audio_path: Path) -> SessionResult:
        """Post tier (§3.6): accurate pass online, local pass offline."""
        session_id = uuid.uuid4().hex[:12]
        from .capture import wav_duration_s

        connectivity = self._connectivity()
        offline = bool(connectivity and connectivity.is_offline)
        transcript = await asyncio.to_thread(
            asr.transcribe_file, self.config, self.client, str(audio_path),
            offline=offline, local_backend=self.local_backend)
        cloud_status = self._cloud_status(
            backend=transcript.backend, confidence=transcript.confidence,
            raw=transcript.text, audio_path=audio_path, offline=offline)
        notes = []
        if not getattr(transcript, "language_ok", True):
            notes.append(
                f"language assertion failed: backend reported "
                f"{transcript.language!r} outside the pinned set — "
                "transcript may be silently translated (§12.4)")
        result = await self._persist(
            session_id=session_id, when=datetime.now().astimezone(),
            raw=transcript.text, backend=transcript.backend,
            language=transcript.language, audio_path=Path(audio_path),
            duration_s=wav_duration_s(Path(audio_path)),
            model=(self.config.section("asr").get("offline_model", "small")
                   if transcript.backend == "local"
                   else self.config.model_for_role("transcribe_batch")),
            notes=notes, confidence=transcript.confidence, cloud_status=cloud_status,
            skip_cleanup=offline,
            connectivity_mode=connectivity.effective_mode if connectivity else None)
        return self._enqueue_offline_work(result, offline=offline, skip_cleanup=offline)

    # -- persistence: store → cleanup → inbox → clipboard -----------------------
    async def _persist(self, *, session_id, when, raw, backend, language,
                       audio_path, duration_s, model, notes,
                       confidence=None, cloud_status="complete",
                       skip_cleanup=False, connectivity_mode=None,
                       lifecycle_dictate=False) -> SessionResult:
        # Cleanup is a model call — off the event loop so acks/status on
        # other connections never wait behind it (§18). Offline it is queued,
        # never attempted against Gemini.
        cleanup = None
        if raw and not skip_cleanup:
            try:
                cleanup_work = asyncio.to_thread(self.cleanup.run, raw)
                if lifecycle_dictate:
                    cleanup = await self._await_lifecycle(
                        "dictate.cleanup_generation", cleanup_work,
                        timeout_s=self.CLEANUP_TIMEOUT_S,
                        session_id=session_id)
                else:
                    cleanup = await cleanup_work
            except Exception as exc:
                cleanup = None
                notes.append(f"cleanup failed ({exc}); raw transcript preserved")
        elif raw and skip_cleanup:
            notes.append("cleanup skipped offline; raw transcript is the record")
        cleaned = cleanup.cleaned if cleanup else None
        flagged = bool(cleanup and cleanup.flagged)
        if cleanup and cleanup.flagged:
            notes.append(cleanup.reason)
        inbox_path = None
        clipboard = {"copied": False, "reason": "empty transcript"}
        if raw.strip():
            inbox_path = write_inbox_note(
                self.inbox_dir, when=when, raw=raw, cleaned=cleaned, backend=backend,
                language=language, audio_path=str(audio_path) if audio_path else None,
                flagged=flagged, session_id=session_id)
            if self.copy_clipboard:
                clipboard = copy_text(cleaned if (cleaned and not flagged) else raw)
        transcript_id = self.store.log_transcript(
            ts=iso_now(), session_id=session_id,
            audio_path=str(audio_path) if audio_path else None,
            raw_text=raw, cleaned_text=cleaned, language=language, backend=backend,
            model=(cleanup.model if cleanup and cleanup.model else model),
            duration_s=duration_s,
            divergence_pct=(cleanup.divergence_pct if cleanup else None),
            flagged=1 if flagged else 0,
            inbox_path=str(inbox_path) if inbox_path else None,
            confidence=confidence, cloud_status=cloud_status)
        return SessionResult(
            session_id=session_id, raw_text=raw, cleaned_text=cleaned,
            backend=backend, language=language,
            audio_path=str(audio_path) if audio_path else None,
            inbox_path=str(inbox_path) if inbox_path else None,
            clipboard=clipboard, flagged=flagged, duration_s=duration_s,
            transcript_id=transcript_id, notes=notes, confidence=confidence,
            cloud_status=cloud_status, connectivity_mode=connectivity_mode,
            model=(cleanup.model if cleanup and cleanup.model else model))

    def _ledger_live_session(self, backend: str, duration_s: float, *, ok: bool,
                             error: str | None = None) -> None:
        """Live sessions are calls too (§3.2): audio-second accounting at
        25 tokens/s (§7), one row per session so `assist cost` sees them."""
        if backend != "gemini_live":
            return  # batch path already ledgered inside the client
        model = self.config.model_for_role("transcribe_live")
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=uuid.uuid4().hex[:12],
            role="transcribe_live", model=model, mode=self.config.gemini_mode,
            tokens_in=int(duration_s * 25), tokens_out=0, tokens_estimated=1,
            audio_seconds=duration_s,
            cost_usd=shadow_cost_usd(model, 0, 0, duration_s),
            latency_ms=duration_s * 1000, ok=1 if ok else 0, verified=None,
            attempt=1, fixture_key=None,
            error=error or (None if ok else "no transcript produced"),
            purpose="housekeeping:transcribe_live", is_user_turn=0)

    def _ledger_live_failure(self, *, stage: str, error: str) -> None:
        """A Live connect/rotation failure is never silent (BUG 6 cost note).

        The batch fallback is recorded by the client, and the session row is
        only written when the live path produced a transcript — so without this
        row a 429/key/transport failure looks like a quiet, cheap day. Tagged
        with the same purpose as successful live sessions, so `assist cost` can
        say what failed and not merely how many.
        """
        model = self.config.model_for_role("transcribe_live")
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=uuid.uuid4().hex[:12],
            role="transcribe_live", model=model, mode=self.config.gemini_mode,
            tokens_in=0, tokens_out=0, tokens_estimated=1, audio_seconds=0.0,
            cost_usd=0.0, latency_ms=0.0, ok=0, verified=None, attempt=1,
            fixture_key=None, error=f"live {stage}: {error}",
            purpose="housekeeping:transcribe_live", is_user_turn=0)


async def _noop_sink(event: dict) -> None:
    return None
