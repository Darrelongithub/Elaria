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

import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .cost import estimate_tokens, iso_now, shadow_cost_usd
from .fixtures import FixtureStore, fixture_key


class Transport(Protocol):
    """One request/response round-trip. Implementations: SDK, fixtures, tests."""

    def generate(self, model: str, contents, config: dict) -> dict:
        """Return {"text": str, "usage": {"tokens_in": int, "tokens_out": int}}."""
        ...


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

    def generate(self, model: str, contents, config: dict) -> dict:
        key = fixture_key(model, contents, config)
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
        self._client = genai.Client(api_key=api_key)

    def generate(self, model: str, contents, config: dict) -> dict:
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

    def list_models(self) -> list[str]:
        return [m.name for m in self._client.models.list()]


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in ("429", "rate", "quota", "resource_exhausted", "503"))


class PerModelLimiter:
    """Sliding-window RPM limiter per model (§3.2, load-bearing on free tier)."""

    def __init__(self, rpm_by_model: Callable[[str], int], window_s: float = 60.0):
        self._rpm = rpm_by_model
        self._window = window_s
        self._stamps: dict[str, deque[float]] = {}

    def acquire(self, model: str, *, sleep: Callable[[float], None] = time.sleep,
                now: Callable[[], float] = time.monotonic, max_wait_s: float = 65.0) -> None:
        stamps = self._stamps.setdefault(model, deque())
        limit = max(1, self._rpm(model))
        waited = 0.0
        while True:
            current = now()
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

        def rpm_for(model: str) -> int:
            if "lite" in model:
                return int(quota.get("flash_lite_rpm", 15))
            return int(quota.get("flash_rpm", 10))

        self._limiter = PerModelLimiter(rpm_for)
        gemini = config.section("gemini")
        self._ladder: list[str] = list(gemini.get("escalation_ladder") or [gemini["model_default"]])
        self._escalate_after = int(gemini.get("escalate_after_failures", 2))
        self._max_scaffold = int(gemini.get("max_scaffold_calls", 6))
        self._daily_cap = int(quota.get("max_requests_per_day", 1200))

    # -- one raw call: limiter + backoff + ledger -----------------------------
    def _call_once(self, role: str, model: str, contents, gen_config: dict, *,
                   correlation_id: str, attempt: int, audio_seconds: float = 0.0) -> dict:
        key = fixture_key(model, contents, gen_config)
        request = {"model": model, "contents": contents, "config": gen_config}
        started = time.monotonic()
        response: dict | None = None
        error: str | None = None
        try:
            if self.mode != "mock":
                self._check_daily_cap()
                self._limiter.acquire(model, sleep=self._sleep)
                response = self._with_backoff(model, contents, gen_config)
                if self.mode == "record":
                    self._fixtures.record(key, request, response)
            else:
                response = self._transport.generate(model, contents, gen_config)
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
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=correlation_id, role=role, model=model,
            mode=self.mode, tokens_in=tokens_in, tokens_out=tokens_out,
            tokens_estimated=estimated, audio_seconds=audio_seconds,
            cost_usd=shadow_cost_usd(model, tokens_in, tokens_out, audio_seconds),
            latency_ms=latency_ms, ok=0 if error else 1, verified=None,
            attempt=attempt, fixture_key=key, error=error,
        )
        if error:
            raise RuntimeError(error)
        return response

    def _with_backoff(self, model: str, contents, gen_config: dict) -> dict:
        delay = 1.0
        last: Exception | None = None
        for try_no in range(4):
            try:
                return self._transport.generate(model, contents, gen_config)
            except Exception as exc:
                last = exc
                if not _is_retryable(exc) or try_no == 3:
                    raise
                self._sleep(delay)
                delay *= 2
        raise last  # pragma: no cover

    def _check_daily_cap(self) -> None:
        from .cost import day_start_iso

        used = self.store.calls_since(day_start_iso())
        if used >= self._daily_cap:
            raise QuotaExhausted(
                f"daily soft cap reached ({used}/{self._daily_cap} live calls). "
                "Queue and wait for the reset (midnight Pacific) — cascade "
                "instead of key rotation (§12.8)."
            )

    # -- the harness (§17): cheapest first, escalate on verified failure -------
    def generate(self, role: str, contents, *, gen_config: dict | None = None,
                 verify: Callable[[str], bool] | None = None,
                 audio_seconds: float = 0.0) -> HarnessResult:
        """Generate with verification-driven escalation.

        `verify` is deterministic code checking the proposal (schema,
        policy, exists?). Without a verifier there is nothing to escalate
        *on*, so a single cheapest-model call is made (§17.2).
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
        while attempts < self._max_scaffold:
            model = ladder[min(tier, len(ladder) - 1)]
            attempts += 1
            response = self._call_once(
                role, model, prompt, gen_config,
                correlation_id=correlation_id, attempt=attempts,
                audio_seconds=audio_seconds,
            )
            last_text = response.get("text", "")
            if verify is None:
                return HarnessResult(last_text, model, attempts, tier > 0, None,
                                     correlation_id, response.get("fixture"))
            last_verified = bool(verify(last_text))
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

    # -- batch transcription: second tier (§3.6) + Live fallback (§12.7) ------
    def transcribe_batch(self, audio_path, language: str = "en", *,
                         also_languages: list[str] | None = None,
                         preserve_code_switching: bool = False) -> dict:
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
        model = self.config.model_for_role("transcribe_batch")
        others = [lang for lang in (also_languages or []) if lang != language]
        if others and preserve_code_switching:
            prompt = (
                f"Transcribe this audio verbatim. The speaker's primary language "
                f"is {language} and they code-switch with {', '.join(others)}. "
                "Transcribe EVERY passage in the language actually spoken in it. "
                "Do NOT translate. Do NOT normalise mixed speech into one "
                "language. Return only the transcript.")
        else:
            prompt = (f"Transcribe this audio verbatim. The language is {language}; "
                      "transcribe in that language exactly as spoken. Do NOT "
                      "translate. Return only the transcript.")
        contents = {"audio_sha256": digest, "language": language,
                    "languages": [language, *others], "prompt": prompt}
        correlation_id = uuid.uuid4().hex[:12]
        if isinstance(self._transport, _SdkTransport) and self.mode != "mock":
            text = self._sdk_transcribe(path, model, prompt, correlation_id, duration)
            return {"text": text, "model": model, "duration_s": duration, "backend": "gemini_batch"}
        response = self._call_once(
            "transcribe_batch", model, contents, {},
            correlation_id=correlation_id, attempt=1, audio_seconds=duration,
        )
        return {"text": response.get("text", ""), "model": model,
                "duration_s": duration, "backend": "gemini_batch",
                "fixture": response.get("fixture")}

    def _sdk_transcribe(self, path, model, prompt, correlation_id, duration):  # pragma: no cover
        started = time.monotonic()
        try:
            uploaded = self._transport._client.files.upload(file=str(path))
            response = self._transport._client.models.generate_content(
                model=model, contents=[prompt, uploaded])
            text = response.text or ""
            error = None
        except Exception as exc:
            text, error = "", f"{type(exc).__name__}: {exc}"
        self.store.log_llm_call(
            ts=iso_now(), correlation_id=correlation_id, role="transcribe_batch",
            model=model, mode=self.mode, tokens_in=0, tokens_out=estimate_tokens(text),
            tokens_estimated=1, audio_seconds=duration,
            cost_usd=shadow_cost_usd(model, 0, estimate_tokens(text), duration),
            latency_ms=(time.monotonic() - started) * 1000, ok=0 if error else 1,
            verified=None, attempt=1, fixture_key=None, error=error)
        if error:
            raise RuntimeError(error)
        return text

    def list_models(self) -> dict:
        """For `assist doctor`: live list when possible, else configured set."""
        configured = sorted({self.config.model_for_role(r) for r in
                             ("default", "organise", "cleanup", "chat",
                              "transcribe_live", "transcribe_batch")})
        if isinstance(self._transport, _SdkTransport) and self.mode != "mock":
            try:
                live = self._transport.list_models()
                return {"verified": True, "models": live,
                        "configured_missing": [m for m in configured
                                               if not any(m in name for name in live)]}
            except Exception as exc:
                return {"verified": False, "models": configured,
                        "error": f"{type(exc).__name__}: {exc}"}
        return {"verified": False, "models": configured,
                "error": "mock/no-key — model IDs unverified until a live call (see §11)"}
