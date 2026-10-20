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

Events (dicts) emitted to the caller's sink: session.started,
transcript.interim, session.checkin, session.reconnecting,
transcript.final, session.ended, error. The daemon forwards these over
IPC to Waybar/overlay subscribers (§3.1 event stream).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import asr
from .capture import FrameGate, RollingAudioBuffer, WavSink, frame_rms
from .cleanup import CleanupPass
from .clipboard import copy_text
from .cost import iso_now, shadow_cost_usd
from .inbox import write_inbox_note
from .live_client import LiveEvent, LiveTransport, LiveUnavailable

EventSink = Callable[[dict], Awaitable[None]]


class SilenceLadder:
    """Adaptive endpointing (§13.8): listen → ONE soft 'Is that all?' → grace →
    close.

    Two rules the owner stated, both enforced here rather than hoped for:

    * ONE check-in per thought (VB-5). "Speech resumed" used to mean *any* frame at
      or over the RMS gate, so a breath, a key click or a mic pop between two
      silences re-armed the ladder and she asked twice in one sentence. Re-arming
      now requires sustained speech (`resume_s`).
    * a grace close (VB-6). After the check-in, if nothing is said for
      `grace_s`, the thought is finished for them and the session ends — the
      microphone used to stay open until the user's hotkey, ~50 minutes in one
      headless repro.
    """

    def __init__(self, checkin_after_s: float, speech_rms: float = 0.01, *,
                 resume_s: float = 0.4, grace_s: float = 8.0):
        self.checkin_after_s = checkin_after_s
        self.speech_rms = speech_rms
        self.resume_s = resume_s
        self.grace_s = grace_s
        self._silent_s = 0.0
        self._speech_s = 0.0
        self._asked = False
        self._asked_at_s: float | None = None

    @property
    def asked(self) -> bool:
        return self._asked

    def observe(self, frame: bytes, frame_s: float) -> bool:
        """True exactly once per segment: time for the soft check-in."""
        if frame_rms(frame) >= self.speech_rms:
            self._silent_s = 0.0
            self._speech_s += frame_s
            if self._speech_s >= self.resume_s:
                # Actual speech resumed: a new segment, and a new check-in is
                # earned. One frame above the gate is not a resumption.
                self._asked = False
                self._asked_at_s = None
            return False
        self._speech_s = 0.0
        self._silent_s += frame_s
        if not self._asked and self._silent_s >= self.checkin_after_s:
            self._asked = True
            self._asked_at_s = self._silent_s
            return True
        return False

    def close_due(self) -> bool:
        """True once the grace period after the check-in has also run out."""
        return (self._asked and self._asked_at_s is not None
                and self._silent_s - self._asked_at_s >= self.grace_s)


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


class DictationService:
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
        self.inbox_dir = Path(settings.get("inbox_dir",
                                           "~/.local/share/assistant/inbox")).expanduser()
        self.copy_clipboard = bool(settings.get("copy_to_clipboard", True))
        self.vad_threshold = float(settings.get("vad_rms_threshold", 0.01))
        self.checkin_after = settings.get("checkin_after_s") or {}
        # How long speech must last before the ladder treats it as a resumption,
        # and how much silence after the one check-in closes the session (VB-5/6).
        self.resume_s = float(settings.get("speech_resume_s", 0.4))
        self.grace_s = float(settings.get("checkin_grace_s", 8.0))
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
        if (offline and skip_cleanup and self.queue_cleanup_offline
                and result.raw_text.strip()):
            job_id = self.offline_queue.enqueue_cleanup(result.transcript_id)
            result.queued_job_ids.append(job_id)
            result.notes.append(f"transcript cleanup queued for reconnect (job #{job_id})")
        return result

    # -- public entry points ---------------------------------------------------
    async def dictate(self, source, *, transport_factory=None,
                      mode: str = "narration",
                      sink: EventSink | None = None,
                      stop_event: asyncio.Event | None = None) -> SessionResult:
        session_id = uuid.uuid4().hex[:12]
        emit = sink or _noop_sink
        language = asr.primary_language(self.config)
        factory = transport_factory or (lambda: asr.make_live_transport(self.config))
        await emit({"event": "session.started", "session_id": session_id, "mode": mode})

        when = datetime.now().astimezone()
        wav_sink = None
        audio_path = None
        if self.save_audio:
            audio_path = self.audio_dir / f"{when:%Y%m%d-%H%M%S}-{session_id[:6]}.wav"
            wav_sink = WavSink(audio_path)

        buffer = RollingAudioBuffer(seconds=self.replay_s)
        gate = FrameGate(rms_threshold=self.vad_threshold)
        ladder = SilenceLadder(
            float(self.checkin_after.get(mode, 20)), speech_rms=self.vad_threshold,
            resume_s=self.resume_s, grace_s=self.grace_s)
        notes: list[str] = []
        final_text = ""
        confidence: float | None = None
        connectivity = self._connectivity()
        offline_at_start = bool(connectivity and connectivity.is_offline)
        network_drop = False
        backend = "local" if offline_at_start else "gemini_live"
        duration_s = 0.0
        transport: LiveTransport | None = None
        collector: asyncio.Task | None = None
        collected: list[LiveEvent] = []
        live_failed = False
        started = time.monotonic()
        rotations = 0
        resumption_handle: str | None = None

        async def collect_events(current: LiveTransport) -> None:
            nonlocal resumption_handle
            async for event in current.events():
                collected.append(event)
                if event.type == "interim":
                    await emit({"event": "transcript.interim", "text": event.text,
                                "session_id": session_id})
                elif event.type == "resumption" and event.handle:
                    resumption_handle = event.handle

        async def open_session(handle: str | None) -> LiveTransport:
            nonlocal collector
            current = factory()
            await current.connect(handle)
            await current.activity_start()
            collector = asyncio.create_task(collect_events(current))
            return current

        if offline_at_start:
            notes.append("offline mode: local ASR only; raw audio saved for any redo")
            await emit({"event": "session.offline", "backend": "local",
                        "connectivity": connectivity.effective_mode if connectivity else None,
                        "session_id": session_id})
        else:
            try:
                transport = await open_session(None)
            except Exception as exc:
                from .modes import looks_like_network_failure

                live_failed = True
                network_drop = looks_like_network_failure(exc)
                if network_drop and self.mode_manager is not None:
                    self.mode_manager.observe_failure(exc, "gemini_live")
                notes.append(f"live connect failed ({exc}) — will transcribe the saved audio")
                await emit({"event": "session.reconnecting", "reason": str(exc),
                            "fallback": "local" if network_drop else "gemini_batch",
                            "session_id": session_id})

        try:
            async for frame in source.frames():
                if stop_event and stop_event.is_set():
                    break
                frame_s = len(frame) / 2 / 16000
                duration_s += frame_s
                if wav_sink:
                    wav_sink.write(frame)
                buffer.push(frame)
                if ladder.observe(frame, frame_s):
                    await emit({"event": "session.checkin", "prompt": "Is that all?",
                                "session_id": session_id})
                elif ladder.close_due():
                    # VB-6: the thought ended. Release the microphone instead of
                    # holding it open until the hotkey; the words already heard
                    # are kept, which is exactly what the check-in was for.
                    notes.append(f"closed after the check-in grace ({ladder.grace_s:g}s "
                                 f"of continued silence)")
                    await emit({"event": "session.grace_close", "session_id": session_id,
                                "silence_after_checkin_s": round(ladder.grace_s, 3)})
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
                        raise LiveUnavailable("server GoAway — rotating session")
                    await transport.send_audio(frame)
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
                        await transport.close()
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
                        transport = None
                        notes.append(f"reconnect failed ({retry_exc}) — saved-audio fallback")
            # PTT released / source exhausted: close the utterance.
            if transport is not None:
                await transport.activity_end()
                if collector:
                    try:
                        await asyncio.wait_for(collector, timeout=15)
                    except (TimeoutError, asyncio.CancelledError):
                        notes.append("timed out waiting for final transcript")
                finals = _final_texts(collected)
                final_text = " ".join(finals).strip()
        finally:
            if wav_sink:
                duration_s = wav_sink.close() or duration_s
            if transport is not None:
                await transport.close()
            await source.aclose()

        use_offline_chain = offline_at_start or network_drop
        if live_failed or not final_text:
            if audio_path is not None:
                try:
                    fallback = await asyncio.to_thread(
                        asr.transcribe_file, self.config, self.client, str(audio_path),
                        offline=use_offline_chain, local_backend=self.local_backend)
                    final_text = fallback.text
                    backend = fallback.backend
                    confidence = fallback.confidence
                    language = fallback.language
                    notes.append(f"transcribed via fallback backend '{backend}'")
                except Exception as exc:
                    await emit({"event": "error", "error": str(exc), "session_id": session_id})
                    final_text = final_text or ""
                    backend = "local" if use_offline_chain else backend
                    notes.append(f"all backends failed: {exc}")
            if backend == "gemini_live" and live_failed:
                backend = "local" if use_offline_chain else "gemini_batch"

        cloud_status = self._cloud_status(
            backend=backend, confidence=confidence, raw=final_text,
            audio_path=audio_path, offline=use_offline_chain)
        result = await self._persist(
            session_id=session_id, when=when, raw=final_text, backend=backend,
            language=language, audio_path=audio_path, duration_s=duration_s,
            model=(self.config.model_for_role(
                "transcribe_live" if backend == "gemini_live" else "transcribe_batch")
                if backend != "local" else self.config.section("asr").get(
                    "offline_model", "small")),
            notes=notes, confidence=confidence, cloud_status=cloud_status,
            skip_cleanup=use_offline_chain,
            connectivity_mode=connectivity.effective_mode if connectivity else None)
        result = self._enqueue_offline_work(
            result, offline=use_offline_chain, skip_cleanup=use_offline_chain)
        self._ledger_live_session(backend, duration_s, ok=bool(final_text))
        shown = result.cleaned_text if (result.cleaned_text and not result.flagged) else result.raw_text
        await emit({"event": "transcript.final", "text": shown,
                    "inbox_path": result.inbox_path, "session_id": session_id})
        await emit({"event": "session.ended", "session_id": session_id,
                    "backend": backend, "duration_s": round(duration_s, 2)})
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
        result = await self._persist(
            session_id=session_id, when=datetime.now().astimezone(),
            raw=transcript.text, backend=transcript.backend,
            language=transcript.language, audio_path=Path(audio_path),
            duration_s=wav_duration_s(Path(audio_path)),
            model=(self.config.section("asr").get("offline_model", "small")
                   if transcript.backend == "local"
                   else self.config.model_for_role("transcribe_batch")),
            notes=[], confidence=transcript.confidence, cloud_status=cloud_status,
            skip_cleanup=offline,
            connectivity_mode=connectivity.effective_mode if connectivity else None)
        return self._enqueue_offline_work(result, offline=offline, skip_cleanup=offline)

    # -- persistence: store → cleanup → inbox → clipboard -----------------------
    async def _persist(self, *, session_id, when, raw, backend, language,
                       audio_path, duration_s, model, notes,
                       confidence=None, cloud_status="complete",
                       skip_cleanup=False, connectivity_mode=None) -> SessionResult:
        # Cleanup is a model call — off the event loop so acks/status on
        # other connections never wait behind it (§18). Offline it is queued,
        # never attempted against Gemini.
        cleanup = None
        if raw and not skip_cleanup:
            try:
                cleanup = await asyncio.to_thread(self.cleanup.run, raw)
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
            cloud_status=cloud_status, connectivity_mode=connectivity_mode)

    def _ledger_live_session(self, backend: str, duration_s: float, *, ok: bool) -> None:
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
            attempt=1, fixture_key=None, error=None if ok else "no transcript produced")


async def _noop_sink(event: dict) -> None:
    return None
