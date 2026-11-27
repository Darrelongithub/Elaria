"""PROVIDER-ENABLE-1 fixtures: production adapter registration and errand routing."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant.cost import provider_cost_report
from assistant.errand import ErrandRunner
from assistant.memory import Memory
from assistant.model_registry import CHAT_INTENT
from assistant.provider_router import (
    CallbackAdapter,
    Capability,
    ProviderRequest,
    ProviderResult,
    ProviderRouter,
    RateLimited,
    create_provider_router,
)
from assistant.store import Store

GROQ_MODEL = "openai/gpt-oss-20b"
GROQ_ROW = {
    "enabled": True,
    "verified": True,
    "verified_at": "2026-11-27",
    "verified_source": "fixture account limits page",
    "plan": "free",
    "no_card_required": True,
    "terms_reviewed_at": "2026-11-27",
    "data_use_policy": "fixture owner reviewed",
    "models": {GROQ_MODEL: {"rpm": 30, "rpd": 100, "tpm": 8000,
                            "billing_unit": "requests_tokens"}},
}


def _store(config) -> Store:
    return Store(config.db_path)


def _result(req: ProviderRequest, text: str) -> ProviderResult:
    return ProviderResult(
        text=text, model=req.model, provider=req.provider,
        request_id="fixture-request", usage={"tokens_in": 9, "tokens_out": 4},
        billing_unit="requests_tokens")


class _GeminiFixture:
    supports_cancellable_async = False

    def __init__(self, store):
        self.store = store
        self.calls = []

    def generate(self, role, prompt, *, purpose, is_user_turn, max_attempts):
        self.calls.append((role, max_attempts))
        self.store.log_llm_call(
            ts="2026-11-27T00:00:00+00:00", correlation_id="gemini-fixture",
            role=role, model=CHAT_INTENT, mode="mock", tokens_in=9, tokens_out=4,
            tokens_estimated=0, audio_seconds=0.0, cost_usd=0.0,
            latency_ms=1.0, ok=1, verified=1, attempt=1, purpose=purpose,
            is_user_turn=bool(is_user_turn))
        return SimpleNamespace(
            text='{"findings":[],"candidate_inferences":[],"clarifying_questions":[]}',
            model=CHAT_INTENT, correlation_id="gemini-fixture")


async def _run_errand(config, tmp_path: Path, *, route_mode: str):
    root = tmp_path / "Downloads"
    root.mkdir()
    (root / "notes.txt").write_text("A fixture document with a useful fact.\n")
    config.raw.setdefault("organise", {})["material_provider"] = "groq"
    config.raw["organise"]["material_model"] = GROQ_MODEL
    config.raw.setdefault("quota", {})["providers"] = {"groq": dict(GROQ_ROW)}
    store = _store(config)
    gemini = _GeminiFixture(store)

    def groq(req):
        if route_mode == "429":
            raise RateLimited("fixture Groq 429", retry_after=30)
        return _result(
            req, '{"findings":[],"candidate_inferences":[],"clarifying_questions":[]}')

    if route_mode == "disabled":
        config.raw["quota"]["providers"]["groq"]["enabled"] = False
    router = ProviderRouter(
        config, store,
        adapters=[CallbackAdapter("groq", groq, (Capability.MATERIAL,))],
        state_path=tmp_path / "router-state.json", clock=lambda: 1_800_000_000.0)
    runner = ErrandRunner(config, store, Memory(store, embedder=None),
                          client=gemini, router=router)
    started = runner.start(
        "errand: review all files", roots=[str(root)],
        budget={"max_steps": 12, "max_seconds": 30.0,
                "max_api_calls": 8, "max_step_api_calls": 2,
                "max_read_bytes": 4096},
    )
    outcome = await runner.wait(started["errand_id"], timeout=10)
    return outcome, gemini, store


@pytest.mark.parametrize(
    "route_mode,expected_model,expect_gemini",
    [
        ("success", f"groq/{GROQ_MODEL}", False),
        ("429", CHAT_INTENT, True),
        ("disabled", CHAT_INTENT, True),
    ],
)
async def test_errand_material_route_and_pinned_gemini_fallback(
    config, tmp_path, route_mode, expected_model, expect_gemini,
):
    outcome, gemini, store = await _run_errand(config, tmp_path, route_mode=route_mode)
    try:
        assert outcome["status"] == "completed"
        analyze = next(step for step in outcome["steps"]
                       if step["skill"] == "content.analyze")
        assert analyze["model"] == expected_model
        assert bool(gemini.calls) is expect_gemini
        assert all(call[0] == "organise" and call[1] == 1 for call in gemini.calls)
        if route_mode != "success":
            notes = outcome["report"]["unanswered_or_unasked"]
            assert any("material route unavailable" in note["reason"] for note in notes)
        else:
            rows = provider_cost_report(store, "2026-11-26T00:00:00+00:00")["rows"]
            assert any(row.get("provider") == "groq" for row in rows)
    finally:
        store.close()


def test_production_router_registers_material_adapters_and_ladder_checks_key(
    config, tmp_path, monkeypatch,
):
    store = _store(config)
    try:
        config.raw.setdefault("quota", {})["providers"] = {"groq": dict(GROQ_ROW)}
        monkeypatch.delenv("ELARIA_GROQ_API_KEY", raising=False)
        router = create_provider_router(config, store, state_path=tmp_path / "state.json")
        assert set(router.adapters.report()) >= {"groq", "openrouter", "cloudflare"}
        assert router.ladder_state()["material_diverted"] is False
        monkeypatch.setenv("ELARIA_GROQ_API_KEY", "fixture-only-not-used")
        assert router.ladder_state()["material_diverted"] is True
    finally:
        store.close()


def test_example_provider_config_is_disabled_and_caps_are_present():
    import tomllib

    example = Path(__file__).resolve().parents[1] / "config.toml.example"
    with example.open("rb") as fh:
        parsed = tomllib.load(fh)
    groq = parsed["quota"]["providers"]["groq"]
    cap = groq["models"][GROQ_MODEL]
    assert groq["enabled"] is False
    assert cap == {"rpm": 30, "tpm": 8000, "rpd": 100,
                   "billing_unit": "requests_tokens"}
    assert parsed["organise"]["material_provider"] == ""
    assert parsed["organise"]["material_model"] == ""
    assert parsed["reach"]["summarise_rpd_budget"] == 0
