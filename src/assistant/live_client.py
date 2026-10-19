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
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from .capture import frame_rms
from .fixtures import FixtureStore


@dataclass
class LiveEvent:
    type: str  # interim | final | go_away | resumption | error | turn_complete
    text: str = ""
    handle: str | None = None  # session-resumption handle
    error: str | None = None


class LiveTransport(Protocol):
    async def connect(self, resumption_handle: str | None = None) -> None: ...
    async def activity_start(self) -> None: ...
    async def send_audio(self, pcm: bytes) -> None: ...
    async def activity_end(self) -> None: ...
    def events(self) -> AsyncIterator[LiveEvent]: ...
    async def close(self) -> None: ...


class LiveUnavailable(RuntimeError):
    """Live path failed in a way the §12.7 fallback chain should absorb."""


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
            self._log("in", event.type, text=event.text or None,
                      handle=event.handle, error=event.error)
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
            await self._queue.put(LiveEvent(
                type=message["type"], text=message.get("text") or "",
                handle=message.get("handle"), error=message.get("error")))

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
