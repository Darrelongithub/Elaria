"""BH-K18 — the quota the config states must be the quota enforced.

DEFAULTS carry BOTH a structured [quota.models.*] table (the owner's
verified AI Studio limits: flash is 5 RPM / 20 RPD) and flat aliases.
The client enforced only the flat RPM keys plus one global 1200/day
cap, so the structured per-model RPD — the limit actually hit in daily
use — was decorative: the 21st flash call went out, got a 429, and the
backoff machinery burned time before the user heard anything. Flat vs
structured disagreement also passed validation silently.
"""

from __future__ import annotations

import pytest

from assistant.config import validate_config
from assistant.cost import iso_now
from assistant.gemini_client import GeminiClient, QuotaExhausted, RateLimitError
from assistant.store import Store

FLASH = "gemini-flash-latest"
LITE = "gemini-flash-lite-latest"


def _client(config, tmp_path) -> tuple[GeminiClient, Store]:
    store = Store(tmp_path / "q.db")
    return GeminiClient(config, store, sleep=lambda _s: None), store


def _seed(store: Store, model: str, n: int) -> None:
    for i in range(n):
        store.log_llm_call(
            ts=iso_now(), correlation_id=f"seed-{model}-{i}", role="chat",
            model=model, mode="live", tokens_in=1, tokens_out=1,
            tokens_estimated=0, audio_seconds=0, cost_usd=0.0,
            latency_ms=1, ok=1, verified=None, attempt=0,
            fixture_key="seed", error=None, purpose="user_turn",
            is_user_turn=1)


def test_per_model_rpd_is_enforced_locally(config, tmp_path):
    config.raw["quota"]["models"]["flash"]["rpd"] = 3
    client, store = _client(config, tmp_path)
    try:
        _seed(store, FLASH, 3)
        with pytest.raises(QuotaExhausted, match="rpd|daily"):
            client._check_daily_cap(FLASH)
        client._check_daily_cap(LITE)  # a different family is unaffected
    finally:
        store.close()


def test_unlimited_rpd_row_never_caps(config, tmp_path):
    config.raw["quota"]["models"]["transcribe-live"]["rpd"] = 0  # unlimited
    client, store = _client(config, tmp_path)
    try:
        _seed(store, "gemini-3.5-transcribe-live", 50)
        client._check_daily_cap("gemini-3.5-transcribe-live")  # must not raise
    finally:
        store.close()


def test_limiter_uses_stricter_of_structured_and_flat_rpm(config, tmp_path):
    config.raw["quota"]["models"]["flash"]["rpm"] = 2
    config.raw["quota"]["flash_rpm"] = 5
    client, store = _client(config, tmp_path)
    try:
        ticks = iter(range(10_000))
        now = lambda: float(next(ticks)) * 0.001  # within one window
        client._limiter.acquire(FLASH, sleep=lambda s: None, now=now)
        client._limiter.acquire(FLASH, sleep=lambda s: None, now=now)
        with pytest.raises(RateLimitError):
            client._limiter.acquire(FLASH, sleep=lambda s: None, now=now,
                                    max_wait_s=0.0)
    finally:
        store.close()


def test_unlimited_rpm_row_disables_the_limiter(config, tmp_path):
    config.raw["quota"]["models"]["transcribe-live"]["rpm"] = 0  # not rate-limited
    client, store = _client(config, tmp_path)
    try:
        for _ in range(50):
            client._limiter.acquire(
                "gemini-3.5-transcribe-live",
                sleep=lambda s: None, now=lambda: 1000.0, max_wait_s=0.0)
    finally:
        store.close()


def test_validate_warns_when_flat_and_structured_quota_disagree(config):
    config.raw["quota"]["models"]["flash"]["rpm"] = 9
    config.raw["quota"]["flash_rpm"] = 5
    report = validate_config(config)
    assert any("flash" in w and "disagree" in w for w in report["warnings"]), (
        f"two sources of truth must not drift silently: {report['warnings']}")
