"""Gemini Live transcription transport (§3.5) — manual VAD, resumption.

The Live API shape push-to-talk needs: explicit activity signalling.

    hotkey press → connect (or resume) → activityStart → pcm frames
    interim_input_transcription → overlay/events, live
    hotkey release → activityEnd → final input_transcription

Transports behind one async protocol so the dictation service never
knows which is underneath:

  GenaiLiveTransport    real google-genai Live session (lazy import).
                        UNVERIFIED against the live API until run with
                        the owner's key — Step 0 again (§11). Defensive
                        getattr parsing: Live response shapes churn.
  FixtureLiveTransport  replays a recorded seq-*.jsonl script (§12.9):
                        a streaming session is a message *sequence*, so
                        fixtures are scripts, not request/response pairs.
  RecordingTransport    wraps any transport, records the sequence.
                        Audio frames are recorded as byte-count + SHA-256
                        ONLY — raw audio never enters committed fixtures.
  ScriptedLiveTransport deterministic in-memory transport: builds the
                        'transcript' from utterance energy/duration so
                        mock dictation works end-to-end anywhere. Text it
                        returns is flagged mock, never passed off as ASR.
  SelfHearingLiveTransport
                        the BUG6 repro as a transport: model output audio
                        plays while the mic stays open, and every frame it
                        receives during that window is transcribed back as
                        "user" speech. Half-duplex is what breaks the loop.
  DuplexLiveTransport   wrapper enforcing half-duplex *inside* the Live
                        session (BUG 6): the mic uplink is closed while
                        output audio plays plus a ~400 ms guard, and output
                        transcription never surfaces as a user turn.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol

from .capture import frame_rms
from .fixtures import FixtureStore


@dataclass
class LiveEvent:
    type: str  # interim | final | go_away | resumption | error | turn_complete
               # | output_audio | output_interim | output_final | echo_suppressed
    text: str = ""
    handle: str | None = None  # session-resumption handle
    error: str | None = None
    # Live output audio (model_turn parts). Never a user transcript: the
    # half-duplex gate keys on it, and the dictation layer refuses to ledger it.
    audio: bytes = b""
    sample_rate: int = 24000
    duration_s: float = 0.0
    reason: str | None = None


class LiveTransport(Protocol):
    async def connect(self, resumption_handle: str | None = None) -> None: ...
    async def activity_start(self) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    async def activity_end(self) -> None: ...
    def events(self) -> AsyncIterator[LiveEvent]: ...
    async def close(self) -> None: ...


class LiveUnavailable(RuntimeError):
    """Live path failed in a way the §12.7 fallback chain should absorb."""


class LiveDuplexGate:
    """Half-duplex *inside* one Live session (BUG 6, owner repro 2026-10-20).

    The BUG5 guard wraps local playback (SpeechService/is_speaking) and mutes
    the capture wrapper, which is the right fix for TTS played through the
    speakers by the daemon. It is not sufficient for the Live path: model
    output audio arrives on the very same session whose mic uplink is open, and
    frames already inside that session can still be transcribed while she is
    talking. The result is the owner's loop — her own generic line comes back
    as a user turn.

    This gate lives on the transport, not around play_audio:

    * output audio (``LiveEvent(type="output_audio")``) opens playback for its
      own duration (estimated from the PCM), so the uplink closes immediately;
    * closing playback keeps the uplink closed for ``guard_s`` (~400 ms) — the
      speaker tail and room reverb are still audible after the last frame;
    * ``uplink_allowed()`` is the single decision the capture loop *and* the
      transport consult. A caller may also supply an external playback probe
      (local TTS), so both halves of the same rule agree.

    Time is injected so the regression can advance a fake clock deterministically
    instead of sleeping for 1.4 real seconds.
    """

    def __init__(self, *, guard_s: float = 0.4,
                 clock: Callable[[], float] | None = None):
        self.guard_s = max(0.0, float(guard_s))
        self._clock = clock or time.monotonic
        self._playing_until = 0.0
        self._guard_until = 0.0
        self._open_ended = False
        self.playbacks = 0
        self.output_audio_bytes = 0
        self.frames_dropped = 0
        self.echo_suppressed = 0
        self.output_texts: deque[str] = deque(maxlen=16)

    # -- playback state ----------------------------------------------------
    def begin_playback(self, duration_s: float | None = None) -> None:
        """Playback begins now for ``duration_s`` (unknown length => open)."""
        now = self._clock()
        if not self.playing():
            self.playbacks += 1
        if duration_s is None:
            # Unknown duration: stay closed until playback_ended() says otherwise.
            self._open_ended = True
            self._playing_until = max(self._playing_until, now)
        else:
            # Chunks queued for playback are sequential, even when the event
            # loop delivers them back-to-back. Extend from the current deadline
            # so a burst still reserves the full audio duration.
            self._playing_until = (max(now, self._playing_until)
                                   + max(0.0, float(duration_s)))
        self._guard_until = self._playing_until + self.guard_s

    def observe_output_audio(self, pcm: bytes, *, sample_rate: int = 24000,
                             duration_s: float | None = None) -> float:
        """One chunk of Live output audio: extend playback by its duration."""
        nbytes = len(pcm or b"")
        self.output_audio_bytes += nbytes
        seconds = (float(duration_s) if duration_s is not None
                   else nbytes / 2 / max(1, int(sample_rate)))
        now = self._clock()
        if not self.playing():
            self.playbacks += 1
        self._open_ended = False
        self._playing_until = (max(now, self._playing_until)
                               + max(0.0, seconds))
        self._guard_until = self._playing_until + self.guard_s
        return seconds

    def playback_ended(self) -> None:
        """The player finished. Guard starts at the end of what was scheduled."""
        now = self._clock()
        self._open_ended = False
        self._playing_until = max(self._playing_until, now)
        self._guard_until = self._playing_until + self.guard_s

    def playing(self) -> bool:
        return self._open_ended or self._clock() < self._playing_until

    def guard_remaining(self) -> float:
        if self._open_ended:
            return self.guard_s
        return max(0.0, self._playing_until + self.guard_s - self._clock())

    def gate_closed(self) -> bool:
        return self.playing() or self._clock() < self._guard_until

    def uplink_allowed(self) -> bool:
        return not self.gate_closed()

    def note_dropped_frame(self) -> None:
        self.frames_dropped += 1

    # -- output text: never a user turn ------------------------------------
    @staticmethod
    def _normalise(text: str) -> str:
        return " ".join(re.sub(r"[^\w\s']+", " ", (text or "").lower()).split())

    def note_output_text(self, text: str) -> None:
        norm = self._normalise(text)
        if norm:
            self.output_texts.append(norm)

    def is_self_audio(self, text: str) -> bool:
        """True when ``text`` is what she just said, heard through the mic."""
        norm = self._normalise(text)
        if not norm:
            return False
        for said in self.output_texts:
            if not said:
                continue
            if norm == said:
                return True
            shorter, longer = sorted((norm, said), key=len)
            # Substring containment only for phrases long enough to be more
            # than an accidental "yes"/"ok" collision.
            if len(shorter) >= 12 and shorter in longer:
                return True
            if len(shorter) >= 8 and SequenceMatcher(None, norm, said).ratio() >= 0.82:
                return True
        return False

    def reset(self) -> None:
        self._playing_until = 0.0
        self._guard_until = 0.0
        self._open_ended = False

    def snapshot(self) -> dict:
        return {
            "playing": self.playing(),
            "guard_remaining_s": round(self.guard_remaining(), 3),
            "playbacks": self.playbacks,
            "output_audio_bytes": self.output_audio_bytes,
            "frames_dropped": self.frames_dropped,
            "echo_suppressed": self.echo_suppressed,
        }


class DuplexLiveTransport:
    """Live transport whose uplink obeys the session's own duplex gate.

    Every transport fact stays the inner transport's: this wrapper only
    decides whether a mic frame may enter the session and whether an input
    transcription is really the user. Output audio and output transcription
    events are surfaced with their own types so no caller can mistake them for
    ``final``/``interim`` user speech (``_final_texts`` only reads ``final``).
    """

    name = "duplex"

    def __init__(self, inner: LiveTransport, *, guard_s: float = 0.4,
                 clock: Callable[[], float] | None = None,
                 external_playback: Callable[[], bool] | None = None):
        self._inner = inner
        self.gate = LiveDuplexGate(guard_s=guard_s, clock=clock)
        self._external_playback = external_playback

    def external_playing(self) -> bool:
        try:
            return bool(self._external_playback and self._external_playback())
        except Exception:  # a broken probe must never open the mic by accident
            return True

    def uplink_allowed(self) -> bool:
        return self.gate.uplink_allowed() and not self.external_playing()

    def _blocked_reason(self) -> str:
        if self.gate.playing():
            return "live_output_audio"
        if self.gate.gate_closed():
            return "live_output_guard"
        if self.external_playing():
            return "local_playback"
        return "open"

    async def connect(self, resumption_handle: str | None = None) -> None:
        await self._inner.connect(resumption_handle)

    async def activity_start(self) -> None:
        await self._inner.activity_start()

    async def send_audio(self, pcm: bytes) -> None:
        # Second line of defence: the capture loop checks the same gate, but a
        # frame can race a playback event that landed between check and send.
        if not self.uplink_allowed():
            self.gate.note_dropped_frame()
            return
        await self._inner.send_audio(pcm)

    async def activity_end(self) -> None:
        await self._inner.activity_end()

    async def events(self) -> AsyncIterator[LiveEvent]:
        async for event in self._inner.events():
            if event.type == "output_audio":
                seconds = event.duration_s or (
                    len(event.audio) / 2 / max(1, int(event.sample_rate)))
                self.gate.observe_output_audio(
                    event.audio, sample_rate=event.sample_rate,
                    duration_s=seconds)
                if not event.duration_s:
                    event.duration_s = seconds
                yield event
                continue
            if event.type == "playback_started":
                self.gate.begin_playback(event.duration_s or None)
                yield event
                continue
            if event.type == "playback_ended":
                self.gate.playback_ended()
                yield event
                continue
            if event.type in ("output_interim", "output_final"):
                # Her own words, transcribed from her own audio. Record them for
                # echo matching and pass them on with a type that cannot be
                # mistaken for user input.
                self.gate.note_output_text(event.text)
                yield event
                continue
            if (event.type in ("interim", "final")
                    and (self.gate.gate_closed()
                         or self.gate.is_self_audio(event.text))):
                self.gate.echo_suppressed += 1
                reason = ("heard during output playback" if self.gate.gate_closed()
                          else "matches live output text")
                yield LiveEvent("echo_suppressed", text=event.text, reason=reason)
                continue
            yield event

    async def close(self) -> None:
        self.gate.playback_ended()
        await self._inner.close()


class ScriptedLiveTransport:
    """Mock live ASR: emits an interim per ~0.5s of speech energy and a
    final on activity_end describing what it 'heard' (duration/energy).
    Deterministic given the same frames — the dictation pipeline's test
    double and headless demo engine."""

    name = "mock"

    def __init__(self, *, fail_connect: bool = False, drop_after_frames: int | None = None,
                 go_away_after_frames: int | None = None):
        self.fail_connect = fail_connect
        self.drop_after_frames = drop_after_frames
        self.go_away_after_frames = go_away_after_frames
        self._queue: asyncio.Queue[LiveEvent] = asyncio.Queue()
        self._frames = 0
        self._speech_s = 0.0
        self.frames_received = 0  # observable for replay assertions
        self.connected_with_handle: str | None = None

    async def connect(self, resumption_handle: str | None = None) -> None:
        if self.fail_connect:
            raise LiveUnavailable("scripted connect failure (429-shaped) — fallback should engage")
        self.connected_with_handle = resumption_handle
        self._frames = 0

    async def activity_start(self) -> None:
        self._speech_s = 0.0

    async def send_audio(self, pcm: bytes) -> None:
        self._frames += 1
        self.frames_received += 1
        if self.drop_after_frames and self._frames == self.drop_after_frames:
            raise LiveUnavailable("scripted mid-utterance disconnect")
        if self.go_away_after_frames and self._frames == self.go_away_after_frames:
            await self._queue.put(LiveEvent("go_away"))
            await self._queue.put(LiveEvent("resumption", handle="mock-handle-1"))
        if frame_rms(pcm) >= 0.01:
            self._speech_s += len(pcm) / 2 / 16000
            if self._frames % 16 == 0:  # ~0.5s at 30ms frames
                await self._queue.put(LiveEvent(
                    "interim", text=f"[mock interim: {self._speech_s:.1f}s of speech so far]"))

    async def activity_end(self) -> None:
        await self._queue.put(LiveEvent(
            "final",
            text=f"[mock transcript: {self._speech_s:.1f} seconds of dictated speech. "
                 "Record real behaviour with GEMINI_MODE=record where a key exists.]"))
        await self._queue.put(LiveEvent("turn_complete"))

    async def events(self) -> AsyncIterator[LiveEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.type == "turn_complete":
                return

    async def close(self) -> None:
        return None


class SelfHearingLiveTransport:
    """The BUG 6 repro as a Live transport (§12.9 simulation).

    At ``trigger_after_frames`` the "model" starts speaking: output audio
    chunks plus output transcription are queued, exactly as a Live session
    delivers them. For as long as that audio would take to play, the transport
    behaves like a microphone pointed at the speakers — every frame that
    actually reaches it is transcribed back as *user* speech.

    Without the duplex gate that produces a bogus user turn containing her own
    line. With it, no frame arrives during the window, so the echo cannot be
    recognised at all. ``frames_received`` / ``echo_finals`` make that
    observable from a regression.
    """

    name = "self_hearing"
    SELF_TEXT = "Understood, what are you working on that I can help with?"

    def __init__(self, *, trigger_after_frames: int = 4,
                 audio_chunk_ms: int = 200, chunks: int = 5,
                 clock: Callable[[], float] | None = None):
        self.trigger_after_frames = max(1, int(trigger_after_frames))
        self.audio_chunk_ms = max(1, int(audio_chunk_ms))
        self.chunks = max(1, int(chunks))
        self._clock = clock or time.monotonic
        self._queue: asyncio.Queue[LiveEvent] = asyncio.Queue()
        self._frames = 0
        self._playback_until_s = 0.0
        self._echoed_interim = False
        self.frames_received = 0
        self.echo_finals = 0
        self.output_audio_events = 0

    def _pcm_chunk(self) -> bytes:
        # 24 kHz s16le, non-silent: it is output audio, not a placeholder.
        samples = 24000 * self.audio_chunk_ms // 1000
        return b"\x10\x27" * samples

    def _begin_playback(self) -> None:
        # Output audio takes real (or injected) time to play, and the microphone
        # is pointed at the speakers for exactly that long.
        self._playback_until_s = (self._clock()
                                  + self.chunks * self.audio_chunk_ms / 1000)
        for _ in range(self.chunks):
            pcm = self._pcm_chunk()
            self.output_audio_events += 1
            self._queue.put_nowait(LiveEvent(
                "output_audio", audio=pcm, sample_rate=24000,
                duration_s=self.audio_chunk_ms / 1000))
        self._queue.put_nowait(LiveEvent("output_interim",
                                         text=self.SELF_TEXT[: len(self.SELF_TEXT) // 2]))
        self._queue.put_nowait(LiveEvent("output_final", text=self.SELF_TEXT))

    def _heard_during_playback(self) -> bool:
        return self._clock() < self._playback_until_s

    async def connect(self, resumption_handle: str | None = None) -> None:
        self._frames = 0

    async def activity_start(self) -> None:
        self._frames = 0
        self._playback_until_s = 0.0

    async def send_audio(self, pcm: bytes) -> None:
        self._frames += 1
        self.frames_received += 1
        if self._frames == self.trigger_after_frames:
            self._begin_playback()
            return
        if self._playback_until_s and self._heard_during_playback():
            # The mic is open while the speakers are: this is the loop.
            self._queue.put_nowait(LiveEvent(
                "interim", text=self.SELF_TEXT[: len(self.SELF_TEXT) // 2]))
            self._echoed_interim = True
            return
        if not self._echoed_interim and self._frames % 8 == 0:
            self._queue.put_nowait(LiveEvent("interim", text="[simulated user speech]"))

    async def activity_end(self) -> None:
        if self._echoed_interim and self.echo_finals == 0:
            self.echo_finals += 1
            await self._queue.put(LiveEvent("final", text=self.SELF_TEXT))
        await self._queue.put(LiveEvent("turn_complete"))

    async def events(self) -> AsyncIterator[LiveEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.type == "turn_complete":
                return

    async def close(self) -> None:
        return None


class RecordingTransport:
    """Wrap a transport and record its message sequence to fixtures/."""

    def __init__(self, inner: LiveTransport, store: FixtureStore, name: str):
        self._inner = inner
        self._store = store
        self._name = name
        self.sequence: list[dict] = []

    def _log(self, direction: str, kind: str, **extra) -> None:
        self.sequence.append({"dir": direction, "type": kind, **extra})

    async def connect(self, resumption_handle: str | None = None) -> None:
        self._log("out", "connect", resumption=bool(resumption_handle))
        await self._inner.connect(resumption_handle)

    async def activity_start(self) -> None:
        self._log("out", "activity_start")
        await self._inner.activity_start()

    async def send_audio(self, pcm: bytes) -> None:
        # Hash + size only. Raw audio stays in ~/.local/share, never in git.
        self._log("out", "audio", bytes=len(pcm),
                  sha256=hashlib.sha256(pcm).hexdigest()[:16])
        await self._inner.send_audio(pcm)

    async def activity_end(self) -> None:
        self._log("out", "activity_end")
        await self._inner.activity_end()

    async def events(self) -> AsyncIterator[LiveEvent]:
        async for event in self._inner.events():
            if event.type == "output_audio":
                # Same rule as mic audio: byte-count + hash, never raw PCM.
                # Duration is kept so a replayed fixture still drives the
                # duplex gate for as long as the audio actually played.
                self._log("in", "output_audio", bytes=len(event.audio),
                          sample_rate=event.sample_rate,
                          duration_s=event.duration_s,
                          sha256=hashlib.sha256(event.audio).hexdigest()[:16])
            else:
                self._log("in", event.type, text=event.text or None,
                          handle=event.handle, error=event.error,
                          reason=event.reason)
            yield event

    async def close(self) -> None:
        await self._inner.close()
        if self.sequence:
            self._store.record_sequence(self._name, self.sequence)


class FixtureLiveTransport:
    """Replay the 'in' side of a recorded sequence as a script (§12.9):
    steadies the non-deterministic streaming path for debugging."""

    name = "fixture"

    def __init__(self, store: FixtureStore, name: str):
        self._script = [m for m in store.replay_sequence(name) if m.get("dir") == "in"]
        self._queue: asyncio.Queue[LiveEvent] = asyncio.Queue()

    async def connect(self, resumption_handle: str | None = None) -> None:
        return None

    async def activity_start(self) -> None:
        return None

    async def send_audio(self, pcm: bytes) -> None:
        return None

    async def activity_end(self) -> None:
        for message in self._script:
            duration = message.get("duration_s")
            if message["type"] == "output_audio" and not duration:
                duration = ((message.get("bytes") or 0) / 2
                            / max(1, int(message.get("sample_rate") or 24000)))
            await self._queue.put(LiveEvent(
                type=message["type"], text=message.get("text") or "",
                handle=message.get("handle"), error=message.get("error"),
                duration_s=float(duration or 0.0),
                sample_rate=int(message.get("sample_rate") or 24000)))

    async def events(self) -> AsyncIterator[LiveEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.type in ("turn_complete", "error"):
                return

    async def close(self) -> None:
        return None


class GenaiLiveTransport:  # pragma: no cover - needs owner's key + network
    """Real Gemini Live session via google-genai (manual VAD, TEXT out).

    Response-shape parsing is defensive (getattr chains) because Live
    message types churn between SDK versions; anything unrecognised is
    ignored rather than fatal. Verify on first live run (§11).

    Language: Live input transcription has no explicit multi-language
    pin in this config surface (verify against current SDK at Step 0);
    the primary language steers it, and Phase 7 code-switch drift is
    caught downstream by cleanup's proportional marker gate + the
    batch re-transcription path, which prompts bilingual-faithfully."""

    name = "gemini_live"

    def __init__(self, api_key: str, model: str, language: str = "en"):
        try:
            from google import genai
        except ImportError as exc:
            raise LiveUnavailable(
                "live transcription needs the Gemini SDK: uv sync --extra live"
            ) from exc
        self._genai = genai
        self._client = genai.Client(api_key=api_key,
                                    http_options={"api_version": "v1beta"})
        self._model = model
        self._language = language
        self._session = None
        self._context = None
        self._queue: asyncio.Queue[LiveEvent] = asyncio.Queue()
        self._receiver: asyncio.Task | None = None

    async def connect(self, resumption_handle: str | None = None) -> None:
        from google.genai import types

        config = types.LiveConnectConfig(
            # ONE-VOICE RULE: Gemini Live is ears + text only. Native audio
            # output is never Elaria's voice; local TTS speaks returned text.
            response_modalities=[types.Modality.TEXT],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
            ),
            session_resumption=types.SessionResumptionConfig(handle=resumption_handle),
        )
        self._context = self._client.aio.live.connect(model=self._model, config=config)
        try:
            self._session = await self._context.__aenter__()
        except Exception as exc:
            raise LiveUnavailable(f"Live connect failed: {exc}") from exc
        self._receiver = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        try:
            async for response in self._session.receive():
                if getattr(response, "go_away", None) is not None:
                    await self._queue.put(LiveEvent("go_away"))
                update = getattr(response, "session_resumption_update", None)
                if update is not None and getattr(update, "resumable", False):
                    await self._queue.put(LiveEvent(
                        "resumption", handle=getattr(update, "new_handle", None)))
                content = getattr(response, "server_content", None)
                if content is None:
                    continue
                # BUG6: output audio and output transcription are HER OWN
                # speech. They are surfaced with output_* types (never
                # final/interim), which also drives the duplex gate.
                turn = getattr(content, "model_turn", None)
                for part in getattr(turn, "parts", None) or []:
                    inline = getattr(part, "inline_data", None)
                    data = getattr(inline, "data", None) if inline is not None else None
                    if data:
                        mime = str(getattr(inline, "mime_type", "") or "")
                        match = re.search(r"rate=(\d+)", mime)
                        rate = int(match.group(1)) if match else 24000
                        await self._queue.put(LiveEvent(
                            "output_audio", audio=data, sample_rate=rate,
                            duration_s=len(data) / 2 / max(1, rate)))
                output = getattr(content, "output_transcription", None)
                if output is not None and getattr(output, "text", None):
                    finished = getattr(output, "finished", False)
                    await self._queue.put(LiveEvent(
                        "output_final" if finished else "output_interim",
                        text=output.text))
                transcription = getattr(content, "input_transcription", None)
                if transcription is not None and getattr(transcription, "text", None):
                    finished = getattr(transcription, "finished", False)
                    await self._queue.put(LiveEvent(
                        "final" if finished else "interim", text=transcription.text))
                if getattr(content, "turn_complete", False):
                    await self._queue.put(LiveEvent("turn_complete"))
        except Exception as exc:
            await self._queue.put(LiveEvent("error", error=str(exc)))

    async def activity_start(self) -> None:
        from google.genai import types

        await self._session.send_realtime_input(activity_start=types.ActivityStart())

    async def send_audio(self, pcm: bytes) -> None:
        from google.genai import types

        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))

    async def activity_end(self) -> None:
        from google.genai import types

        await self._session.send_realtime_input(activity_end=types.ActivityEnd())

    async def events(self) -> AsyncIterator[LiveEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.type in ("turn_complete", "error"):
                return

    async def close(self) -> None:
        if self._receiver:
            self._receiver.cancel()
        if self._context is not None:
            await self._context.__aexit__(None, None, None)
