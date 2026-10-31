"""Gemini client — models by role, rate-limited, ledgered, harness-wrapped.

Hard requirements (§3.2): a per-model rate limiter + exponential backoff,
and a cost-ledger write on EVERY call (including mock and failures).

Reasoning harness (§17): every call starts at the cheapest capable model.
Deterministic verification decides whether the answer is good; only a
*verified failure* earns a retry, and only repeated verified failures
escalate to the next model tier. Scaffolding is capped — if cheap calls
pile up past `max_scaffold_calls` we stop performing thrift theatre.

Modes (§12.9): live = real API; record = real API + fixtures saved;
mock = fixtures/synthetic only, zero network. No key => mock (config.py).
The google-genai SDK is imported lazily so this module — and the whole
test suite — works with no key and no SDK installed.

This client is NEVER on the ack path (§18): acks are local (persona.ack).
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .config import quota_rows
from .config import voice_model as configured_voice_model
from .cost import estimate_tokens, iso_now, shadow_cost_usd
from .fixtures import FixtureStore, fixture_key
from .journal_log import log_event
from .model_registry import assert_model_permitted
from .voice_catalogue import (
    live_catalogue,
    resolve_catalogue,
    validate_or_raise,
)


def _run_coroutine_sync(factory, timeout_s: float = 60.0):
    """Run an async SDK call from sync code, safely from any thread.

    TTS calls arrive on a worker thread (asyncio.to_thread), so there is no
    running loop there and asyncio.run() is correct. If a caller ever has a loop
    running, a private thread keeps the event loop contract intact instead of
    exploding with "asyncio.run() cannot be called from a running event loop".

    BH-K5: the wait is BOUNDED (TimeoutError past `timeout_s`). The voice
    render's receive() can wait forever on a wedged Live session; unbounded,
    each such call permanently occupied a worker thread — and TTS runs on
    the shared to_thread executor the whole daemon relies on.
    """

    async def bounded():
        return await asyncio.wait_for(factory(), timeout_s)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(bounded())

    box: dict = {}

    def runner():
        try:
            box["value"] = asyncio.run(bounded())
        except BaseException as exc:  # re-raised in the caller's thread
            box["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    # The inner wait_for should fire first; the join margin only guards a
    # thread that cannot even start its loop. daemon=True: an abandoned
    # render can never block interpreter exit.
    thread.join(timeout_s + 5.0)
    if thread.is_alive():
        raise TimeoutError(
            f"async SDK call did not finish within {timeout_s:g}s")
    if "error" in box:
        raise box["error"]
    return box.get("value")


class Transport(Protocol):
    """One request/response round-trip. Implementations: SDK, fixtures, tests."""

    def generate(self, model: str, contents, config: dict,
                 on_first_token: Callable[[], None] | None = None) -> dict:
        """Return {"text": str, "usage": {"tokens_in": int, "tokens_out": int}}.

        `on_first_token` (optional) is invoked the moment the first output
        token/chunk exists — the streaming first-token deadline (BUG F) hangs
        off it, so a transport that streams must call it early. A transport
        that cannot stream may ignore it (the caller treats completion as the
        first token) or omit the parameter entirely (older test doubles).
        """
        ...

    def generate_audio(self, model: str, text: str, voice_name: str, *,
                       on_chunk=None) -> dict:
        """Optional: native-audio speech for `text`.

        Returns {"pcm": bytes (s16le mono), "sample_rate": int, "voice_name": str,
        "usage": {...}}. A transport that cannot produce audio omits this method;
        the caller then reports silence with the reason (amendment 2026-10-20: the
        dormant local voice is NOT a fallback), never a bare absence.

        M-4 streaming: when `on_chunk` is given, every PCM chunk is handed
        to it AS IT ARRIVES (the slice queue plays it while synthesis
        continues); the full pcm is still assembled and returned. The sink
        must not raise (the tts slice queue honors that).
        """
        raise NotImplementedError


class RateLimitError(RuntimeError):
    pass


class QuotaExhausted(RuntimeError):
    pass


@dataclass
class HarnessResult:
    text: str
    model: str
    attempts: int
    escalated: bool
    verified: bool | None
    correlation_id: str
    fixture: dict | None = None


class _FixtureTransport:
    """Mock-mode transport: fixtures only. Structurally incapable of network."""

    def __init__(self, store: FixtureStore):
        self._store = store

    def generate(self, model: str, contents, config: dict,
                 on_first_token: Callable[[], None] | None = None) -> dict:
        key = fixture_key(model, contents, config)
        if on_first_token is not None:
            on_first_token()   # fixtures are instant: the first token is now
        return self._store.replay(key, {"model": model, "contents": contents, "config": config})


class _SdkTransport:
    """Live transport via google-genai. Imported lazily; needs a key."""

    def __init__(self, api_key: str):
        try:
            from google import genai
        except ImportError as exc:
            raise RuntimeError(
                "live mode needs the Gemini SDK: install with "
                "`uv sync --extra live` (or pip install 'assistant[live]'). "
                "Until then GEMINI_MODE=mock works fully offline."
            ) from exc
        from importlib import metadata

        try:
            sdk_version = metadata.version("google-genai")
            sdk_major = int(sdk_version.split(".", 1)[0])
        except (metadata.PackageNotFoundError, ValueError) as exc:
            raise RuntimeError(
                "live chat needs google-genai>=2.0.0 for cancellable async "
                "requests; run `uv sync --extra live` (or pip install -U "
                "'assistant[live]')."
            ) from exc
        if sdk_major < 2:
            raise RuntimeError(
                f"live chat needs google-genai>=2.0.0 for cancellable async "
                f"requests (found {sdk_version}); upgrade with `uv sync "
                f"--extra live` (or pip install -U 'assistant[live]')."
            )
        self._client = genai.Client(api_key=api_key)

    def generate(self, model: str, contents, config: dict,
                 on_first_token: Callable[[], None] | None = None) -> dict:
        if on_first_token is not None:
            # BUG F: stream so the first-token deadline can tell a slow-but-alive
            # transport from a dead one. A generation that starts is allowed its
            # full (generous) total bound and is delivered verbatim.
            chunks = []
            usage = None
            saw_text = False
            for chunk in self._client.models.generate_content_stream(
                    model=model, contents=contents, config=config or None):
                text = getattr(chunk, "text", "") or ""
                if text and not saw_text:
                    on_first_token()
                    saw_text = True
                chunks.append(text)
                if getattr(chunk, "usage_metadata", None) is not None:
                    usage = chunk.usage_metadata
            return {
                "text": "".join(chunks),
                "usage": {
                    "tokens_in": getattr(usage, "prompt_token_count", 0) or 0,
                    "tokens_out": getattr(usage, "candidates_token_count", 0) or 0,
                },
            }
        response = self._client.models.generate_content(
            model=model, contents=contents, config=config or None
        )
        usage = getattr(response, "usage_metadata", None)
        return {
            "text": response.text or "",
            "usage": {
                "tokens_in": getattr(usage, "prompt_token_count", 0) or 0,
                "tokens_out": getattr(usage, "candidates_token_count", 0) or 0,
            },
        }

    async def generate_async(self, model: str, contents, config: dict,
                             on_first_token: Callable[[], None] | None = None,
                             deadline: float | None = None) -> dict:
        """Stream chat on the SDK's native async HTTP transport.

        The SDK's 1.x async facade delegated requests to ``asyncio.to_thread``;
        cancelling it still left the synchronous request running. The live
        extra therefore requires the 2.x async HTTP implementation, and this
        path passes the remaining wall-clock budget as the request timeout too.
        """
        request_config = dict(config or {})
        if deadline is not None:
            remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
            options = request_config.get("http_options") or {}
            if not isinstance(options, dict):
                dump = getattr(options, "model_dump", None)
                options = dump() if callable(dump) else {
                    "timeout": getattr(options, "timeout", None)}
            else:
                options = dict(options)
            existing_timeout = options.get("timeout")
            if isinstance(existing_timeout, (int, float)) and existing_timeout > 0:
                remaining_ms = min(remaining_ms, int(existing_timeout))
            options["timeout"] = remaining_ms
            request_config["http_options"] = options

        stream = await self._client.aio.models.generate_content_stream(
            model=model, contents=contents, config=request_config or None)
        chunks: list[str] = []
        usage = None
        saw_text = False
        async for chunk in stream:
            text = getattr(chunk, "text", "") or ""
            if text and not saw_text:
                if on_first_token is not None:
                    on_first_token()
                saw_text = True
            chunks.append(text)
            if getattr(chunk, "usage_metadata", None) is not None:
                usage = chunk.usage_metadata
        return {
            "text": "".join(chunks),
            "usage": {
                "tokens_in": getattr(usage, "prompt_token_count", 0) or 0,
                "tokens_out": getattr(usage, "candidates_token_count", 0) or 0,
            },
        }

    def generate_audio(self, model: str, text: str, voice_name: str, *,
                       on_chunk=None) -> dict:
        """Native audio from a LIVE model (Stage A fix).

        The previous implementation used `models.generate_content` with a
        TTS-preview model. Flare is a Live voice, so that request failed with
        "Voice name Flare is not supported". A Live session is opened instead,
        the text is sent as one user turn, and the returned 24 kHz PCM parts are
        concatenated. The voice name is exactly the configured one — never a
        substitute.

        M-4 streaming: `on_chunk` receives each PCM part as the session
        emits it — the ear hears the first slice while the render continues
        (the W6 whale was synthesized-but-unheard time).
        """
        from google.genai import types

        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            output_audio_transcription=types.AudioTranscriptionConfig(),
        )

        async def render() -> dict:
            pcm = bytearray()
            rate = 24000
            tokens_in = 0
            tokens_out = 0
            async with self._client.aio.live.connect(model=model, config=config) as session:
                sent = False
                if hasattr(session, "send_client_content"):
                    try:
                        await session.send_client_content(
                            turns={"role": "user", "parts": [{"text": text}]},
                            turn_complete=True)
                        sent = True
                    except TypeError:
                        sent = False
                if not sent:
                    # Older SDK shape: realtime text input ends the turn itself.
                    await session.send_realtime_input(text=text)
                completed = False
                async for message in session.receive():
                    usage = getattr(message, "usage_metadata", None)
                    if usage is not None:
                        tokens_in = max(tokens_in,
                                        int(getattr(usage, "prompt_token_count", 0) or 0))
                        tokens_out = max(tokens_out,
                                         int(getattr(usage, "candidates_token_count", 0) or 0))
                    content = getattr(message, "server_content", None)
                    if content is None:
                        continue
                    turn = getattr(content, "model_turn", None)
                    for part in getattr(turn, "parts", None) or []:
                        inline = getattr(part, "inline_data", None)
                        data = getattr(inline, "data", None) if inline is not None else None
                        if data:
                            pcm.extend(data)
                            if on_chunk is not None:
                                try:
                                    on_chunk(data)
                                except Exception:  # noqa: S110 - the sink must not fail synthesis
                                    pass
                            mime = str(getattr(inline, "mime_type", "") or "")
                            match = re.search(r"rate=(\d+)", mime)
                            if match:
                                rate = int(match.group(1))
                    if getattr(content, "turn_complete", False):
                        completed = True
                        break
            return {"pcm": bytes(pcm), "sample_rate": rate,
                    "voice_name": voice_name,
                    "completed": completed,
                    "usage": {"tokens_in": tokens_in, "tokens_out": tokens_out}}

        result = _run_coroutine_sync(render, timeout_s=30.0)
        if not result.get("pcm"):
            raise RuntimeError(
                f"the Live model {model} returned no audio for voice {voice_name!r}; "
                "nothing is spoken rather than substituting another voice")
        if not result.get("completed"):
            raise RuntimeError(
                f"the Live session for {model} closed before turn_complete "
                "(truncated audio discarded rather than caching a partial clip)")
        return result

    def list_models(self) -> list[str]:
        return [str(getattr(m, "name", m)).removeprefix("models/")
                for m in self._client.models.list()]

    def list_voices(self) -> list[str]:
        """Ids from the Voices API (`voices.list`), prebuilt + stored.

        Prebuilt catalogue voices use the speaker name as their id (docs,
        2026-10-16), which is exactly the string `voice_name` expects. A project
        that has access to Flare through the Live roster returns it here; if the
        API does not expose it, the live catalogue honestly omits it and warm
        refuses with the allowed list instead of failing mid-sentence.
        """
        names: list[str] = []
        voices = getattr(self._client, "voices", None)
        for voice in voices.list() if voices is not None else []:
            for attr in ("id", "name", "display_name"):
                value = getattr(voice, attr, None)
                if value:
                    names.append(str(value).removeprefix("voices/"))
                    break
        return sorted({name for name in names if name})


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("429", "rate", "quota", "resource_exhausted", "503"))


def quota_family(model: str) -> str | None:
    """Map a model id to its [quota.models.*] row label (BH-K18).

    Order matters: transcribe-live before generic transcribe (batch),
    flash-lite before flash.
    """
    m = model.rsplit("/", 1)[-1].lower().replace("_", "-")
    if "transcribe-live" in m:
        return "transcribe-live"
    if "transcribe" in m:
        return "transcribe-batch"
    if "lite" in m:
        return "flash-lite"
    if "flash" in m:
        return "flash"
    return None


class PerModelLimiter:
    """Sliding-window RPM limiter per model (§3.2, load-bearing on free tier)."""

    def __init__(self, rpm_by_model: Callable[[str], int], window_s: float = 60.0):
        self._rpm = rpm_by_model
        self._window = window_s
        self._stamps: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def acquire(self, model: str, *, sleep: Callable[[float], None] = time.sleep,
                now: Callable[[], float] = time.monotonic, max_wait_s: float = 65.0) -> None:
        limit = self._rpm(model)
        if limit <= 0:
            return  # config says not rate-limited (BH-K18; was max(1, ...) = 1/min!)
        waited = 0.0
        while True:
            with self._lock:
                current = now()
                stamps = self._stamps.setdefault(model, deque())
                while stamps and current - stamps[0] > self._window:
                    stamps.popleft()
                if len(stamps) < limit:
                    stamps.append(current)
                    return
                wait = self._window - (current - stamps[0]) + 0.01
            if waited + wait > max_wait_s:
                raise RateLimitError(f"local RPM limiter: {model} at {limit}/min — queued, not sent")
            sleep(wait)
            waited += wait

    async def acquire_async(self, model: str, *, deadline: float | None = None,
                            max_wait_s: float = 65.0) -> None:
        """Quota wait on the event loop, cancellable by the chat deadline."""
        limit = self._rpm(model)
        if limit <= 0:
            return
        waited = 0.0
        while True:
            with self._lock:
                current = time.monotonic()
                stamps = self._stamps.setdefault(model, deque())
                while stamps and current - stamps[0] > self._window:
                    stamps.popleft()
                if len(stamps) < limit:
                    stamps.append(current)
                    return
                wait = self._window - (current - stamps[0]) + 0.01
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("chat deadline expired while waiting for model quota")
                wait = min(wait, remaining)
            if waited + wait > max_wait_s:
                raise RateLimitError(f"local RPM limiter: {model} at {limit}/min — queued, not sent")
            await asyncio.sleep(wait)
            waited += wait


def batch_transcription_prompt(language: str,
                               also_languages: list[str] | None = None,
                               *, preserve_code_switching: bool = False) -> str:
    """The exact transcription prompt the batch/file leg sends (§12.4/§12.5).

    Module-level so the W1 file-leg probe (scripts/file_leg_probe.py) can
    print what production sends without reimplementing the f-strings —
    one construction, one truth (scene-7 work order, 2026-10-31).
    """
    others = [lang for lang in (also_languages or []) if lang != language]
    if others and preserve_code_switching:
        return (
            f"Transcribe this audio verbatim. The speaker's primary language "
            f"is {language} and they code-switch with {', '.join(others)}. "
            "Transcribe EVERY passage in the language actually spoken in it. "
            "Do NOT translate. Do NOT normalise mixed speech into one "
            "language. Return only the transcript.")
    return (f"Transcribe this audio verbatim. The language is {language}; "
            "transcribe in that language exactly as spoken. Do NOT "
            "translate. Return only the transcript.")


class GeminiClient:
    def __init__(self, config, store, *, transport: Transport | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config
        self.store = store
        self.mode = config.gemini_mode
        self._sleep = sleep
        self._fixtures = FixtureStore(config.fixtures_dir)
        if transport is not None:
            self._transport = transport
        elif self.mode == "mock":
            self._transport = _FixtureTransport(self._fixtures)
        else:
            if not config.api_key:
                raise RuntimeError(
                    f"GEMINI_MODE={self.mode} needs an API key "
                    "(~/.config/assistant/gemini.env, 0600). Without one, use mock."
                )
            self._transport = _SdkTransport(config.api_key)
        quota = config.section("quota")
        # BH-K18: the structured [quota.models.*] rows are the owner's
        # verified limits; the flat keys are aliases. Enforcement takes
        # the STRICTER of the two wherever both speak (validate_config
        # warns when they disagree) — previously only the flat RPM keys
        # were enforced and per-model RPD was decorative.
        self._quota_by_family = {
            row["model"].lower().replace("_", "-"): row
            for row in quota_rows(quota)}

        def rpm_for(model: str) -> int:
            family = quota_family(model)
            flat = int(quota.get("flash_lite_rpm", 15)) if family == "flash-lite" \
                else int(quota.get("flash_rpm", 10))
            row = self._quota_by_family.get(family or "")
            if row is None:
                return flat
            if row.get("unlimited_rpm"):
                return 0  # limiter treats <= 0 as not rate-limited
            rpm = row.get("rpm")
            if isinstance(rpm, (int, float)) and rpm > 0:
                return min(int(rpm), flat) if flat > 0 else int(rpm)
            return flat

        self._limiter = PerModelLimiter(rpm_for)
        gemini = config.section("gemini")
        self._ladder: list[str] = list(gemini.get("escalation_ladder") or [gemini["model_default"]])
        self._escalate_after = int(gemini.get("escalate_after_failures", 2))
        self._max_scaffold = int(gemini.get("max_scaffold_calls", 6))
        self._daily_cap = int(quota.get("max_requests_per_day", 1200))
        self._catalogue_memo: dict | None = None

    # -- one raw call: limiter + backoff + ledger -----------------------------
    def _call_once(self, role: str, model: str, contents, gen_config: dict, *,
                   correlation_id: str, attempt: int, audio_seconds: float = 0.0,
                   purpose: str | None = None, is_user_turn: bool | None = None,
                   on_first_token: Callable[[], None] | None = None) -> dict:
        # §4.1: a forbidden model id never reaches the wire (Phase 0 pin fix).
        assert_model_permitted(model)
        key = fixture_key(model, contents, gen_config)
        request = {"model": model, "contents": contents, "config": gen_config}
        started = time.monotonic()
        response: dict | None = None
        error: str | None = None
        try:
            if self.mode != "mock":
                self._check_daily_cap(model)
                self._limiter.acquire(model, sleep=self._sleep)
                response = self._with_backoff(model, contents, gen_config,
                                              on_first_token)
                if self.mode == "record":
                    self._fixtures.record(key, request, response)
            else:
                response = self._transport_generate(model, contents, gen_config,
                                                    on_first_token)
        except Exception as exc:  # ledger must see failures too (§3.2)
            error = f"{type(exc).__name__}: {exc}"
            response = {"text": "", "usage": {"tokens_in": 0, "tokens_out": 0}}
        latency_ms = (time.monotonic() - started) * 1000
        usage = response.get("usage") or {}
        tokens_in = int(usage.get("tokens_in") or 0)
        tokens_out = int(usage.get("tokens_out") or 0)
        estimated = 0
        if not tokens_in and not tokens_out and error is None:
            tokens_in = estimate_tokens(str(contents))
            tokens_out = estimate_tokens(response.get("text", ""))
            estimated = 1
        # BUG3: attribute every live call by purpose
        purpose_val = purpose or role
        if purpose_val in ("user_turn", "user_chat"):
            is_user = 1
        elif purpose is not None and purpose.startswith("housekeeping"):
            is_user = 0
        elif is_user_turn is not None:
            is_user = 1 if is_user_turn else 0
        else:
            # default: chat with is_user_turn True is user, else housekeeping
            is_user = 1 if role == "chat" and purpose_val == "user_turn" else 0
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=correlation_id, role=role, model=model,
            mode=self.mode, tokens_in=tokens_in, tokens_out=tokens_out,
            tokens_estimated=estimated, audio_seconds=audio_seconds,
            cost_usd=shadow_cost_usd(model, tokens_in, tokens_out, audio_seconds),
            latency_ms=latency_ms, ok=0 if error else 1, verified=None,
            attempt=attempt, fixture_key=key, error=error,
            purpose=purpose_val, is_user_turn=is_user,
        )
        if error:
            raise RuntimeError(error)
        return response

    @property
    def supports_cancellable_async(self) -> bool:
        """Whether raw chat calls use a genuinely async transport."""
        return callable(getattr(self._transport, "generate_async", None))

    async def _call_once_async(self, role: str, model: str, contents,
                               gen_config: dict, *, correlation_id: str,
                               attempt: int, audio_seconds: float = 0.0,
                               purpose: str | None = None,
                               is_user_turn: bool | None = None,
                               on_first_token: Callable[[], None] | None = None,
                               deadline: float | None = None) -> dict:
        # §4.1: a forbidden model id never reaches the wire (Phase 0 pin fix).
        assert_model_permitted(model)
        key = fixture_key(model, contents, gen_config)
        request = {"model": model, "contents": contents, "config": gen_config}
        started = time.monotonic()
        response: dict | None = None
        error: str | None = None
        original_error: Exception | None = None
        cancelled: asyncio.CancelledError | None = None
        request_started = False
        try:
            if self.mode != "mock":
                self._check_daily_cap(model)
                await self._limiter.acquire_async(model, deadline=deadline)
                request_started = True
                response = await self._with_backoff_async(
                    model, contents, gen_config, on_first_token,
                    deadline=deadline)
                if self.mode == "record":
                    self._fixtures.record(key, request, response)
            else:
                request_started = True
                response = await self._transport_generate_async(
                    model, contents, gen_config, on_first_token,
                    deadline=deadline)
        except asyncio.CancelledError as exc:
            if not request_started:
                raise
            error = "CancelledError: chat generation cancelled before completion"
            cancelled = exc
        except Exception as exc:  # ledger must see failures too (§3.2)
            original_error = exc
            error = f"{type(exc).__name__}: {exc}"
            response = {"text": "", "usage": {"tokens_in": 0, "tokens_out": 0}}

        latency_ms = (time.monotonic() - started) * 1000
        usage = (response or {}).get("usage") or {}
        tokens_in = int(usage.get("tokens_in") or 0)
        tokens_out = int(usage.get("tokens_out") or 0)
        estimated = 0
        if not tokens_in and not tokens_out and error is None:
            tokens_in = estimate_tokens(str(contents))
            tokens_out = estimate_tokens((response or {}).get("text", ""))
            estimated = 1
        purpose_val = purpose or role
        if purpose_val in ("user_turn", "user_chat"):
            is_user = 1
        elif purpose is not None and purpose.startswith("housekeeping"):
            is_user = 0
        elif is_user_turn is not None:
            is_user = 1 if is_user_turn else 0
        else:
            is_user = 1 if role == "chat" and purpose_val == "user_turn" else 0
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=correlation_id, role=role, model=model,
            mode=self.mode, tokens_in=tokens_in, tokens_out=tokens_out,
            tokens_estimated=estimated, audio_seconds=audio_seconds,
            cost_usd=shadow_cost_usd(model, tokens_in, tokens_out, audio_seconds),
            latency_ms=latency_ms, ok=0 if error else 1, verified=None,
            attempt=attempt, fixture_key=key, error=error,
            purpose=purpose_val, is_user_turn=is_user,
        )
        if cancelled is not None:
            raise cancelled
        if error:
            if isinstance(original_error, TimeoutError):
                raise original_error
            raise RuntimeError(error)
        return response or {"text": "", "usage": {}}

    def voice_request(self, text: str, *, voice: str | None = None) -> dict:
        """The exact request that would go out - inspectable without a network call.

        The voice is resolved against `[gemini] allowed_voices` (the one-voice rule
        as data). `voice_allowed: False` means this request would be REFUSED: a
        voice name that is not canonical is never sent out, and never quietly
        replaced by another one.
        """
        from .config import canonical_voices, resolve_voice

        gemini = self.config.section("gemini")
        configured = str(voice or gemini.get("voice") or "Flare")
        effective, allowed = resolve_voice(self.config, configured)
        return {
            "model": self.voice_model(),
            "voice_name": effective or configured,
            "voice_requested": configured,
            "voice_allowed": allowed,
            "canonical_voices": list(canonical_voices(self.config)),
            "response_modalities": ["AUDIO"],
            "api": "live",
            "text": text,
        }

    def can_speak(self) -> bool:
        """Native audio needs a real transport; mock fixtures cannot synthesise it."""
        return self.mode != "mock" and hasattr(self._transport, "generate_audio")

    # -- Stage A: model + voice catalogue validation --------------------------
    def voice_model(self) -> str:
        """`[gemini] gemini_voice_model` — the Live model that offers Flare."""
        return configured_voice_model(self.config)

    def resolve_voice_model(self) -> dict:
        """Check the configured Live model against a REAL models.list.

        Live mode: one `models.list` call, filtered to the model the config
        names. A model that is absent is a refusal with the live model names in
        the error, never a guess. Mock: configured-only, honestly unverified.
        """
        configured = self.voice_model()
        if not isinstance(self._transport, _SdkTransport) or self.mode == "mock":
            return {
                "model": configured, "verified": False,
                "live_models": [], "reason": (
                    "mock/no-key — the Live model id is unverified until a live "
                    "models.list runs on the owner's machine (`assist voice models`)"),
            }
        try:
            names = self._transport.list_models()
        except Exception as exc:
            return {
                "model": configured, "verified": False, "live_models": [],
                "reason": f"models.list failed: {type(exc).__name__}: {exc}",
            }
        live_models = [name for name in names if "live" in name.lower()]
        matched = next((name for name in names
                        if name == configured or name.split("/")[-1] == configured), None)
        if matched is None:
            raise RuntimeError(
                f"[gemini] gemini_voice_model = {configured!r} is not in the live "
                f"model list. Live models this key can see: "
                f"{', '.join(live_models) or '(none)'}. Fix the key deliberately; "
                f"never fall back to a TTS-preview model (Flare is a Live voice).")
        return {"model": matched, "verified": True, "live_models": live_models,
                "reason": f"{matched!r} is present in the real models.list"}

    def voice_catalogue(self, *, refresh: bool = False) -> dict:
        """The real voice catalogue for the configured model, cached at warm.

        One live fetch per warm cycle, memoised for the rest of the process so a
        conversational turn does not spend an extra API call on every sentence.
        """
        model = self.voice_model()
        if (not refresh and self._catalogue_memo is not None
                and self._catalogue_memo.get("model") == model):
            return self._catalogue_memo
        fetched = None
        if isinstance(self._transport, _SdkTransport) and self.mode != "mock":
            try:
                voices = self._transport.list_voices()
            except Exception:
                voices = []
            if voices:
                from .voice_catalogue import _read_baseline

                fetched = live_catalogue(model, voices, baseline=_read_baseline())
        catalogue = resolve_catalogue(model, store=self.store, fetched=fetched,
                                     refresh=refresh)
        self._catalogue_memo = catalogue
        return catalogue

    def validate_speech_config(self) -> dict:
        """Warm-time gate: model in models.list AND voice in its catalogue.

        This is the check the user's machine was missing: it fails with the
        allowed list before any ack is rendered, so silence is explained and
        `assist doctor` can name the fix.
        """
        request = self.voice_request("warm")
        if not request["voice_allowed"]:
            raise RuntimeError(
                f"voice {request['voice_requested']!r} is not canonical "
                f"(allowed: {', '.join(request['canonical_voices'])}); refusing "
                f"to warm audio in an unapproved voice")
        model_check = self.resolve_voice_model()
        catalogue = self.voice_catalogue(refresh=True)
        validation = validate_or_raise(self.voice_model(), request["voice_name"],
                                       catalogue)
        return {"model": model_check, "catalogue": {
            "source": catalogue.get("source"),
            "verified": bool(catalogue.get("verified")),
            "retrieved": catalogue.get("retrieved"),
            "voices": catalogue.get("voices", []),
        }, "voice": validation}

    def generate_voice(self, text: str, *, voice: str | None = None,
                       correlation_id: str = "-",
                       on_chunk=None) -> dict:
        """One rate-limited, ledgered native-audio call. Interim online voice.

        M-4 streaming: `on_chunk` rides to the transport ONLY when given —
        older transport fakes with strict signatures stay valid."""
        request = self.voice_request(text, voice=voice)
        if not request["voice_allowed"]:
            # The pin, enforced at the last moment: no transport will ever be told
            # to speak a voice the owner did not approve (VB-4).
            raise RuntimeError(
                f"voice {request['voice_requested']!r} is not canonical "
                f"(allowed: {', '.join(request['canonical_voices'])}); refusing to "
                f"speak in an unapproved voice - set [gemini] voice back to a "
                f"canonical name or widen [gemini] allowed_voices deliberately"
            )
        if not self.can_speak():
            raise RuntimeError(
                f"GEMINI_MODE={self.mode} cannot produce native audio - nothing is "
                "spoken (the local voice is dormant by amendment 2026-10-20)"
            )
        model = request["model"]
        # §4.1: a forbidden model id never reaches the wire (Phase 0 pin fix).
        assert_model_permitted(model)
        # Validate before the transport sees a request. A wrong voice is a
        # refusal naming the allowed list, not a 400 halfway through a sentence.
        catalogue = self.voice_catalogue()
        validate_or_raise(model, request["voice_name"], catalogue)
        key = fixture_key(model, text, {"voice_name": request["voice_name"]})
        started = time.monotonic()
        error: str | None = None
        response: dict = {}
        try:
            self._check_daily_cap(model)
            self._limiter.acquire(model, sleep=self._sleep)
            delay = 1.0
            audio_kwargs = {"on_chunk": on_chunk} if on_chunk is not None else {}
            for try_no in range(4):
                try:
                    response = self._transport.generate_audio(
                        model, text, request["voice_name"], **audio_kwargs)
                    break
                except Exception as exc:  # same backoff posture as text calls
                    if try_no == 3 or not _is_retryable(exc):
                        raise
                    time.sleep(delay) if self._sleep is time.sleep else self._sleep(delay)
                    delay *= 2
            if self.mode == "record":
                self._fixtures.record(key, {"model": model, "text": text,
                                            "voice_name": request["voice_name"]},
                                      {"text": "", "usage": response.get("usage", {}),
                                       "note": "pcm audio is not stored in json fixtures"})
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            # The API's own rejection of a voice is the final word. Append the
            # catalogue so the operator sees the allowed list, not just "not
            # supported", and never substitute a different voice to get audio.
            if "voice" in str(exc).lower():
                try:
                    allowed = self.voice_catalogue(refresh=True).get("voices", [])
                except Exception:
                    allowed = []
                if allowed:
                    detail += (f" — allowed voices for {model}: "
                               f"{', '.join(allowed)}")
            error = detail
        latency_ms = (time.monotonic() - started) * 1000
        usage = response.get("usage") or {}
        seconds = len(response.get("pcm", b"")) / 2 / max(1, int(response.get("sample_rate", 24000)))
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=correlation_id, role="voice", model=model,
            mode=self.mode, tokens_in=int(usage.get("tokens_in") or 0),
            tokens_out=int(usage.get("tokens_out") or 0), tokens_estimated=0,
            audio_seconds=round(seconds, 3),
            cost_usd=shadow_cost_usd(model, int(usage.get("tokens_in") or 0),
                                     int(usage.get("tokens_out") or 0), seconds),
            latency_ms=latency_ms, ok=0 if error else 1, verified=None,
            attempt=0, fixture_key=key, error=error,
            purpose="housekeeping:voice_speech", is_user_turn=0,
        )
        if error:
            raise RuntimeError(error)
        return response

    def _with_backoff(self, model: str, contents, gen_config: dict,
                      on_first_token: Callable[[], None] | None = None) -> dict:
        delay = 1.0
        last: Exception | None = None
        for try_no in range(4):
            try:
                return self._transport_generate(model, contents, gen_config,
                                                on_first_token)
            except Exception as exc:
                last = exc
                if not _is_retryable(exc) or try_no == 3:
                    raise
                self._sleep(delay)
                delay *= 2
        raise last  # pragma: no cover

    async def _with_backoff_async(self, model: str, contents, gen_config: dict,
                                  on_first_token: Callable[[], None] | None = None,
                                  *, deadline: float | None = None) -> dict:
        delay = 1.0
        last: Exception | None = None
        for try_no in range(4):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("chat deadline expired before SDK request")
            try:
                return await self._transport_generate_async(
                    model, contents, gen_config, on_first_token,
                    deadline=deadline)
            except Exception as exc:
                last = exc
                if not _is_retryable(exc) or try_no == 3:
                    raise
                if deadline is None:
                    await asyncio.sleep(delay)
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("chat deadline expired during SDK retry") from exc
                    await asyncio.sleep(min(delay, remaining))
                    if time.monotonic() >= deadline:
                        raise TimeoutError("chat deadline expired during SDK retry") from exc
                delay *= 2
        raise last  # pragma: no cover

    async def _transport_generate_async(
            self, model: str, contents, gen_config: dict,
            on_first_token: Callable[[], None] | None = None, *,
            deadline: float | None = None) -> dict:
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("chat deadline expired before SDK request")
        generate_async = getattr(self._transport, "generate_async", None)
        if not callable(generate_async):
            raise TypeError("async chat selected without an async transport")
        return await generate_async(
            model, contents, gen_config, on_first_token=on_first_token,
            deadline=deadline)

    def _transport_generate(self, model: str, contents, gen_config: dict,
                            on_first_token: Callable[[], None] | None = None) -> dict:
        """One transport round-trip; tolerates doubles without the streaming kwarg.

        An older test double that predates `on_first_token` is retried without
        it (mirrors the daemon's _generate fallback). Its turns simply have no
        early first-token signal — completion still counts as progress.
        """
        if on_first_token is None:
            return self._transport.generate(model, contents, gen_config)
        try:
            return self._transport.generate(model, contents, gen_config,
                                            on_first_token=on_first_token)
        except TypeError as exc:
            if "unexpected keyword" not in str(exc):
                raise
            return self._transport.generate(model, contents, gen_config)

    def _check_daily_cap(self, model: str | None = None) -> None:
        from .cost import day_start_iso

        used = self.store.calls_since(day_start_iso())
        if used >= self._daily_cap:
            log_event("quota.counter", level="warn", verdict="rejected",
                      detail=(f"model_version={model}; " if model else "")
                             + (f"daily soft cap reached ({used}/{self._daily_cap} "
                                "live calls) — refused locally, queued for the "
                                "midnight Pacific reset"))
            raise QuotaExhausted(
                f"daily soft cap reached ({used}/{self._daily_cap} live calls). "
                "Queue and wait for the reset (midnight Pacific) — cascade "
                "instead of key rotation (§12.8)."
            )
        # BH-K18: the per-model RPD is the limit actually hit in daily use
        # (flash: 20/day). Enforce it locally with a clear refusal instead
        # of sending the call out to earn an opaque 429 + backoff burn.
        # Counted per exact model id (the ledger's grain).
        if model:
            family = quota_family(model)
            row = self._quota_by_family.get(family or "")
            if row and not row.get("unlimited_rpd"):
                rpd = row.get("rpd")
                # §4.1 config cap (`rpd_cap`): deliberately below the free
                # ceiling (chat/intent cap 400 under ~500 free). Enforcement
                # takes the stricter of the measured RPD and the config cap;
                # a cap still applies when the free row is unlimited.
                cap = row.get("rpd_cap")
                limits = [int(x) for x in (rpd, cap)
                          if isinstance(x, (int, float)) and x > 0]
                if limits:
                    allowed = min(limits)
                    used_model = self.store.calls_since(day_start_iso(), model=model)
                    if used_model >= allowed:
                        source = ("[quota.models.{}.{}]".format(
                            family, "rpd_cap" if allowed == cap and cap else "rpd"))
                        log_event("quota.counter", level="warn", verdict="rejected",
                                  detail=(f"model_version={model}; "
                                          f"per-model daily quota reached for "
                                          f"{model} ({used_model}/{allowed} today — "
                                          f"{source}) — refused locally"))
                        raise QuotaExhausted(
                            f"per-model daily quota reached for {model} "
                            f"({used_model}/{allowed} today — "
                            f"{source}). Resets midnight "
                            "Pacific; use another model or wait (§12.8).")

    # -- the harness (§17): cheapest first, escalate on verified failure -------
    def generate(self, role: str, contents, *, gen_config: dict | None = None,
                 verify: Callable[[str], bool] | None = None,
                 audio_seconds: float = 0.0,
                 purpose: str | None = None, is_user_turn: bool | None = None,
                 on_first_token: Callable[[], None] | None = None,
                 max_attempts: int | None = None) -> HarnessResult:
        """Generate with verification-driven escalation.

        `verify` is deterministic code checking the proposal (schema,
        policy, exists?). Without a verifier there is nothing to escalate
        *on*, so a single cheapest-model call is made (§17.2).

        `max_attempts` caps the scaffold (REJECT-2 / Bug 8: a chat reply is
        regenerated ONCE on a verification rejection; the best attempt is then
        DELIVERED, never silently binned — the caller logs the rule hit).
        `on_first_token` threads the streaming first-token signal (BUG F).
        """
        gen_config = gen_config or {}
        correlation_id = uuid.uuid4().hex[:12]
        start_model = self.config.model_for_role(role)
        # Climb UPWARD from the role's tier: organise starts at Lite and may
        # escalate to Flash; chat already starts at Flash (top free tier),
        # so verified failures retry there. Never de-escalate (§17).
        if start_model in self._ladder:
            ladder = self._ladder[self._ladder.index(start_model):]
        else:
            ladder = [start_model] + [m for m in self._ladder if m != start_model]
        attempts = 0
        failures_on_tier = 0
        tier = 0
        prompt = contents
        last_text, last_verified = "", None
        attempt_cap = self._max_scaffold if max_attempts is None else max(1, int(max_attempts))
        while attempts < attempt_cap:
            model = ladder[min(tier, len(ladder) - 1)]
            attempts += 1
            response = self._call_once(
                role, model, prompt, gen_config,
                correlation_id=correlation_id, attempt=attempts,
                audio_seconds=audio_seconds,
                purpose=purpose or ("user_turn" if role == "chat" and is_user_turn else role),
                is_user_turn=is_user_turn,
                on_first_token=on_first_token,
            )
            last_text = response.get("text", "")
            if verify is None:
                return HarnessResult(last_text, model, attempts, tier > 0, None,
                                     correlation_id, response.get("fixture"))
            last_verified = bool(verify(last_text))
            with self.store._lock:
                self.store._conn.execute(
                    "UPDATE llm_calls SET verified = ? WHERE correlation_id = ? AND attempt = ?",
                    (1 if last_verified else 0, correlation_id, attempts),
                )
                self.store._conn.commit()
            if last_verified:
                return HarnessResult(last_text, model, attempts, tier > 0, True,
                                     correlation_id, response.get("fixture"))
            failures_on_tier += 1
            # Retry with feedback, then climb a tier (§17.1).
            prompt = (f"{contents}\n\n[Your previous answer failed verification. "
                      f"Previous answer: {last_text[:400]}. Correct it.]")
            if failures_on_tier >= self._escalate_after and tier < len(ladder) - 1:
                tier += 1
                failures_on_tier = 0
        return HarnessResult(last_text, ladder[min(tier, len(ladder) - 1)],
                             attempts, tier > 0, last_verified, correlation_id)

    async def generate_async(self, role: str, contents, *,
                             gen_config: dict | None = None,
                             verify: Callable[[str], bool] | None = None,
                             audio_seconds: float = 0.0,
                             purpose: str | None = None,
                             is_user_turn: bool | None = None,
                             on_first_token: Callable[[], None] | None = None,
                             max_attempts: int | None = None,
                             deadline: float | None = None) -> HarnessResult:
        """Async twin of ``generate`` for cancellable daemon chat turns."""
        if not self.supports_cancellable_async:
            raise RuntimeError("this Gemini transport has no cancellable async path")
        gen_config = gen_config or {}
        correlation_id = uuid.uuid4().hex[:12]
        start_model = self.config.model_for_role(role)
        if start_model in self._ladder:
            ladder = self._ladder[self._ladder.index(start_model):]
        else:
            ladder = [start_model] + [m for m in self._ladder if m != start_model]
        attempts = 0
        failures_on_tier = 0
        tier = 0
        prompt = contents
        last_text, last_verified = "", None
        attempt_cap = self._max_scaffold if max_attempts is None else max(1, int(max_attempts))
        while attempts < attempt_cap:
            model = ladder[min(tier, len(ladder) - 1)]
            attempts += 1
            response = await self._call_once_async(
                role, model, prompt, gen_config,
                correlation_id=correlation_id, attempt=attempts,
                audio_seconds=audio_seconds,
                purpose=purpose or ("user_turn" if role == "chat" and is_user_turn else role),
                is_user_turn=is_user_turn,
                on_first_token=on_first_token, deadline=deadline,
            )
            last_text = response.get("text", "")
            if verify is None:
                return HarnessResult(last_text, model, attempts, tier > 0, None,
                                     correlation_id, response.get("fixture"))
            last_verified = bool(verify(last_text))
            with self.store._lock:
                self.store._conn.execute(
                    "UPDATE llm_calls SET verified = ? WHERE correlation_id = ? AND attempt = ?",
                    (1 if last_verified else 0, correlation_id, attempts),
                )
                self.store._conn.commit()
            if last_verified:
                return HarnessResult(last_text, model, attempts, tier > 0, True,
                                     correlation_id, response.get("fixture"))
            failures_on_tier += 1
            prompt = (f"{contents}\n\n[Your previous answer failed verification. "
                      f"Previous answer: {last_text[:400]}. Correct it.]")
            if failures_on_tier >= self._escalate_after and tier < len(ladder) - 1:
                tier += 1
                failures_on_tier = 0
        return HarnessResult(last_text, ladder[min(tier, len(ladder) - 1)],
                             attempts, tier > 0, last_verified, correlation_id)

    # -- batch transcription: second tier (§3.6) + Live fallback (§12.7) ------
    def transcribe_batch(self, audio_path, language: str = "en", *,
                         also_languages: list[str] | None = None,
                         preserve_code_switching: bool = False,
                         deadline: float | None = None,
                         model: str | None = None) -> dict:
        """generateContent on saved audio: accurate pass, same ledger rules.

        Mock/record keying uses the audio's SHA-256 (+ language set), so
        fixtures replay per-recording without embedding audio in the repo,
        and flipping languages never replays a stale-language fixture.
        Live mode uploads via the SDK Files API (lazy; UNVERIFIED without
        a key). The prompt pins languages and forbids translation
        (§12.4/§12.5); with also_languages + preserve_code_switching
        (Phase 7) it instructs passage-faithful bilingual transcription —
        the switch itself is content, normalising it away is the failure.
        """
        import hashlib
        from pathlib import Path

        from .capture import wav_duration_s

        path = Path(audio_path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        duration = wav_duration_s(path)
        # `model` override: the §0 spike pushes a closed WAV through the
        # transcribe-live route AS a batch call (event_spike.py). Default
        # stays the dedicated batch STT model.
        model = model or self.config.model_for_role("transcribe_batch")
        # §4.1: a forbidden model id never reaches the wire (Phase 0 pin fix).
        assert_model_permitted(model)
        others = [lang for lang in (also_languages or []) if lang != language]
        prompt = batch_transcription_prompt(
            language, others, preserve_code_switching=preserve_code_switching)
        contents = {"audio_sha256": digest, "language": language,
                    "languages": [language, *others], "prompt": prompt}
        correlation_id = uuid.uuid4().hex[:12]
        if isinstance(self._transport, _SdkTransport) and self.mode != "mock":
            text = self._sdk_transcribe(
                path, model, prompt, correlation_id, duration, deadline=deadline)
            return {"text": text, "model": model, "duration_s": duration, "backend": "gemini_batch"}
        response = self._call_once(
            "transcribe_batch", model, contents, {},
            correlation_id=correlation_id, attempt=1, audio_seconds=duration,
            purpose="housekeeping:transcribe_batch", is_user_turn=0,
        )
        return {"text": response.get("text", ""), "model": model,
                "duration_s": duration, "backend": "gemini_batch",
                "fixture": response.get("fixture")}

    async def transcribe_batch_async(self, audio_path, language: str = "en", *,
                                     also_languages: list[str] | None = None,
                                     preserve_code_switching: bool = False,
                                     deadline: float | None = None,
                                     model: str | None = None) -> dict:
        """Transcribe through the SDK's native async HTTP transport.

        Live meeting stop uses this path so its absolute deadline cancels the
        request coroutine instead of abandoning a synchronous worker thread.
        Fixture/mock transports remain on the existing deterministic path.
        """
        if not isinstance(self._transport, _SdkTransport) or self.mode == "mock":
            return self.transcribe_batch(
                audio_path, language, also_languages=also_languages,
                preserve_code_switching=preserve_code_switching,
                deadline=deadline, model=model)

        from pathlib import Path

        from .capture import wav_duration_s

        path = Path(audio_path)
        duration = wav_duration_s(path)
        model = model or self.config.model_for_role("transcribe_batch")
        # §4.1: a forbidden model id never reaches the wire (Phase 0 pin fix).
        assert_model_permitted(model)
        others = [lang for lang in (also_languages or []) if lang != language]
        prompt = batch_transcription_prompt(
            language, others, preserve_code_switching=preserve_code_switching)
        correlation_id = uuid.uuid4().hex[:12]
        started = time.monotonic()

        def request_config():
            if deadline is None:
                return None
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                raise TimeoutError("meeting transcription deadline expired")
            return {"http_options": {
                "timeout": max(1, int(remaining_s * 1000))}}

        error_exc = None
        cancelled_exc = None
        try:
            if deadline is None:
                uploaded = await self._transport._client.aio.files.upload(
                    file=str(path))
                response = await self._transport._client.aio.models.generate_content(
                    model=model, contents=[prompt, uploaded])
            else:
                async with asyncio.timeout_at(deadline):
                    upload_config = request_config()
                    uploaded = await self._transport._client.aio.files.upload(
                        file=str(path), config=upload_config)
                    generation_config = request_config()
                    response = await self._transport._client.aio.models.generate_content(
                        model=model, contents=[prompt, uploaded],
                        config=generation_config)
            text = response.text or ""
            error = None
        except asyncio.CancelledError as exc:
            error_exc = cancelled_exc = exc
            text, error = "", f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            error_exc = exc
            text, error = "", f"{type(exc).__name__}: {exc}"
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=correlation_id, role="transcribe_batch",
            model=model, mode=self.mode, tokens_in=0, tokens_out=estimate_tokens(text),
            tokens_estimated=1, audio_seconds=duration,
            cost_usd=shadow_cost_usd(model, 0, estimate_tokens(text), duration),
            latency_ms=(time.monotonic() - started) * 1000, ok=0 if error else 1,
            verified=None, attempt=1, fixture_key=None, error=error,
            purpose="housekeeping:transcribe_batch", is_user_turn=0)
        if cancelled_exc is not None:
            raise cancelled_exc
        if error:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    "meeting transcription deadline expired") from error_exc
            raise RuntimeError(error) from error_exc
        return {"text": text, "model": model, "duration_s": duration,
                "backend": "gemini_batch"}

    def _sdk_transcribe(self, path, model, prompt, correlation_id, duration,
                        *, deadline: float | None = None):  # pragma: no cover
        started = time.monotonic()

        def request_config():
            if deadline is None:
                return None
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                raise TimeoutError("meeting transcription deadline expired")
            return {"http_options": {
                "timeout": max(1, int(remaining_s * 1000))}}

        error_exc = None
        try:
            upload_config = request_config()
            if upload_config is None:
                uploaded = self._transport._client.files.upload(file=str(path))
            else:
                uploaded = self._transport._client.files.upload(
                    file=str(path), config=upload_config)
            generation_config = request_config()
            if generation_config is None:
                response = self._transport._client.models.generate_content(
                    model=model, contents=[prompt, uploaded])
            else:
                response = self._transport._client.models.generate_content(
                    model=model, contents=[prompt, uploaded],
                    config=generation_config)
            text = response.text or ""
            error = None
        except Exception as exc:
            error_exc = exc
            text, error = "", f"{type(exc).__name__}: {exc}"
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=correlation_id, role="transcribe_batch",
            model=model, mode=self.mode, tokens_in=0, tokens_out=estimate_tokens(text),
            tokens_estimated=1, audio_seconds=duration,
            cost_usd=shadow_cost_usd(model, 0, estimate_tokens(text), duration),
            latency_ms=(time.monotonic() - started) * 1000, ok=0 if error else 1,
            verified=None, attempt=1, fixture_key=None, error=error,
            purpose="housekeeping:transcribe_batch", is_user_turn=0)
        if error:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    "meeting transcription deadline expired") from error_exc
            raise RuntimeError(error) from error_exc
        return text

    def list_models(self) -> dict:
        """For `assist voice models`/doctor: the real list, with voice routing.

        The configured set now includes the voice role: a TTS-preview model here
        would reintroduce the Flare bug, so it is displayed alongside the Live
        model rather than hidden among chat models.
        """
        configured = sorted({self.config.model_for_role(r) for r in
                             ("default", "organise", "cleanup", "chat",
                              "transcribe_live", "transcribe_batch", "voice")})
        catalogue = self.voice_catalogue()
        request = self.voice_request("inspect")
        result = {
            "configured": configured,
            "voice_model": self.voice_model(),
            "voice": request["voice_name"],
            "voice_allowed_by_policy": request["voice_allowed"],
            "catalogue": {
                "model": catalogue.get("model"),
                "source": catalogue.get("source"),
                "verified": bool(catalogue.get("verified")),
                "retrieved": catalogue.get("retrieved"),
                "count": len(catalogue.get("voices") or []),
                "allowed": catalogue.get("voices") or [],
            },
        }
        if isinstance(self._transport, _SdkTransport) and self.mode != "mock":
            try:
                live = self._transport.list_models()
                missing = [m for m in configured
                           if not any(m == name or m in name for name in live)]
                payload = {**result, "verified": True, "models": live,
                           "live_models": [m for m in live if "live" in m.lower()],
                           "configured_missing": missing}
                self._record_model_verification(payload)
                return payload
            except Exception as exc:
                return {**result, "verified": False, "models": configured,
                        "error": f"{type(exc).__name__}: {exc}"}
        return {**result, "verified": False, "models": configured,
                "error": ("mock/no-key — model IDs unverified until a live "
                          "models.list (see §11)")}

    def _record_model_verification(self, payload: dict) -> None:
        """Stamp the live models.list verification where doctor can consume it.

        `assist voice models` IS the verification step (scene 2, 2026-10-26):
        a successful live listing records configured_missing and the voice
        catalogue facts, and `assist doctor` downgrades its "model ids
        unverified" WARN against this stamp. Never raises.
        """
        import json

        try:
            stamp = {
                "verified_at": iso_now(),
                "configured_missing": payload.get("configured_missing") or [],
                "models_count": len(payload.get("models") or []),
                "voice_model": payload.get("voice_model"),
                "catalogue_model": (payload.get("catalogue") or {}).get("model"),
                "catalogue_count": (payload.get("catalogue") or {}).get("count"),
            }
            state = self.config.state_dir
            state.mkdir(parents=True, exist_ok=True)
            (state / "voice-models-verified.json").write_text(
                json.dumps(stamp, indent=2) + "\n", encoding="utf-8")
        except Exception:  # noqa: S110 - a stamp write must never break the listing
            pass
