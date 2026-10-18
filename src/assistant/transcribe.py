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
    """Adaptive endpointing (§13.8): listen → ONE soft 'Is that all?' →
    (user ends it). A thought is never nagged twice: after the check-in
    fires, only resumed speech re-arms the ladder for a new segment."""

    def __init__(self, checkin_after_s: float, speech_rms: float = 0.01):
        self.checkin_after_s = checkin_after_s
        self.speech_rms = speech_rms
        self._silent_s = 0.0
        self._asked = False

    def observe(self, frame: bytes, frame_s: float) -> bool:
        """True exactly once per segment: time for the soft check-in."""
        if frame_rms(frame) >= self.speech_rms:
            self._silent_s = 0.0
            self._asked = False  # resumed speech: check-in forgotten instantly
            return False
        self._silent_s += frame_s
        if not self._asked and self._silent_s >= self.checkin_after_s:
            self._asked = True
            return True
        return False


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


class DictationService:
    def __init__(self, config, store, client):
        self.config = config
        self.store = store
        self.client = client
        self.cleanup = CleanupPass(config, client)
        settings = config.section("transcribe")
        self.replay_s = float(settings.get("reconnect_replay_s", 30))
        self.session_max_s = float(settings.get("live_session_max_s", 540))
        self.save_audio = bool(settings.get("save_audio", True))
        self.inbox_dir = Path(settings.get("inbox_dir",
                                           "~/.local/share/assistant/inbox")).expanduser()
        self.copy_clipboard = bool(settings.get("copy_to_clipboard", True))
        self.vad_threshold = float(settings.get("vad_rms_threshold", 0.01))
        self.checkin_after = settings.get("checkin_after_s") or {}
        self.audio_dir = config.data_dir / "audio"

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
            float(self.checkin_after.get(mode, 20)), speech_rms=self.vad_threshold)
        notes: list[str] = []
        final_text = ""
        backend = "gemini_live"
        duration_s = 0.0
        transport: LiveTransport | None = None
        collector: asyncio.Task | None = None
        collected: list[LiveEvent] = []
        live_failed = False
        started = time.monotonic()
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

        try:
            transport = await open_session(None)
        except Exception as exc:
            live_failed = True
            notes.append(f"live connect failed ({exc}) — will batch-transcribe the saved audio")
            await emit({"event": "session.reconnecting", "reason": str(exc),
                        "fallback": "gemini_batch", "session_id": session_id})

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
                if transport is None or not gate.allows(frame):
                    continue
                try:
                    # Rotation: never ride a session into its lifetime cap.
                    if time.monotonic() - started > self.session_max_s:
                        raise LiveUnavailable("proactive rotation at session age cap")
                    if any(e.type == "go_away" for e in collected):
                        collected.clear()
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
                        transport = await open_session(resumption_handle)
                        tail = buffer.tail()
                        for i in range(0, len(tail), 960):  # 30ms frames
                            await transport.send_audio(tail[i:i + 960])
                        notes.append("session rotated; buffered tail replayed")
                    except Exception as retry_exc:
                        live_failed = True
                        transport = None
                        notes.append(f"reconnect failed ({retry_exc}) — batch fallback")
            # PTT released / source exhausted: close the utterance.
            if transport is not None:
                await transport.activity_end()
                if collector:
                    try:
                        await asyncio.wait_for(collector, timeout=15)
                    except (TimeoutError, asyncio.CancelledError):
                        notes.append("timed out waiting for final transcript")
                finals = [e.text for e in collected if e.type == "final" and e.text]
                final_text = " ".join(finals).strip()
        finally:
            if wav_sink:
                duration_s = wav_sink.close() or duration_s
            if transport is not None:
                await transport.close()
            await source.aclose()

        if live_failed or not final_text:
            if audio_path is not None:
                try:
                    fallback = await asyncio.to_thread(
                        asr.transcribe_file, self.config, self.client, str(audio_path))
                    final_text = fallback.text
                    backend = fallback.backend
                    notes.append(f"transcribed via fallback backend '{backend}'")
                except Exception as exc:
                    await emit({"event": "error", "error": str(exc), "session_id": session_id})
                    final_text = final_text or ""
                    notes.append(f"all backends failed: {exc}")
            if backend == "gemini_live" and live_failed:
                backend = "gemini_batch"

        result = await self._persist(
            session_id=session_id, when=when, raw=final_text, backend=backend,
            language=language, audio_path=audio_path, duration_s=duration_s,
            model=self.config.model_for_role(
                "transcribe_live" if backend == "gemini_live" else "transcribe_batch"),
            notes=notes)
        self._ledger_live_session(backend, duration_s, ok=bool(final_text))
        shown = result.cleaned_text if (result.cleaned_text and not result.flagged) else result.raw_text
        await emit({"event": "transcript.final", "text": shown,
                    "inbox_path": result.inbox_path, "session_id": session_id})
        await emit({"event": "session.ended", "session_id": session_id,
                    "backend": backend, "duration_s": round(duration_s, 2)})
        return result

    async def transcribe_file(self, audio_path: Path) -> SessionResult:
        """Post tier (§3.6): accurate pass on an existing recording."""
        session_id = uuid.uuid4().hex[:12]
        from .capture import wav_duration_s

        transcript = await asyncio.to_thread(
            asr.transcribe_file, self.config, self.client, str(audio_path))
        return await self._persist(
            session_id=session_id, when=datetime.now().astimezone(),
            raw=transcript.text, backend=transcript.backend,
            language=transcript.language, audio_path=Path(audio_path),
            duration_s=wav_duration_s(Path(audio_path)),
            model=self.config.model_for_role("transcribe_batch"), notes=[])

    # -- persistence: store → cleanup → inbox → clipboard -----------------------
    async def _persist(self, *, session_id, when, raw, backend, language,
                       audio_path, duration_s, model, notes) -> SessionResult:
        # Cleanup is a model call — off the event loop so acks/status on
        # other connections never wait behind it (§18).
        cleanup = await asyncio.to_thread(self.cleanup.run, raw) if raw else None
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
            inbox_path=str(inbox_path) if inbox_path else None)
        return SessionResult(
            session_id=session_id, raw_text=raw, cleaned_text=cleaned,
            backend=backend, language=language,
            audio_path=str(audio_path) if audio_path else None,
            inbox_path=str(inbox_path) if inbox_path else None,
            clipboard=clipboard, flagged=flagged, duration_s=duration_s,
            transcript_id=transcript_id, notes=notes)

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
