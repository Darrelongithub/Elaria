"""PROVIDER-ENABLE-1: errand material calls divert safely and fall back honestly."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from assistant.cost import format_provider_report, provider_cost_report
from assistant.errand import ErrandBudget, ErrandRunner, PlannedStep
from assistant.provider_router import (
    CallbackAdapter,
    Capability,
    ProviderResult,
    ProviderRouter,
    RateLimited,
    create_provider_router,
)
from assistant.store import Store

MODEL = "openai/gpt-oss-20b"
GEMINI_MODEL = "gemini-3.5-flash-lite"


def _groq_row(*, enabled: bool = True) -> dict:
    return {
        "enabled": enabled,
        "verified": True,
        "verified_at": "2026-11-27",
        "verified_source": "fixture account limits page",
        "plan": "free",
        "no_card_required": True,
        "terms_reviewed_at": "2026-11-27",
        "data_use_policy": "fixture-reviewed",
        "models": {MODEL: {"rpm": 30, "tpm": 8000, "rpd": 100,
                            "billing_unit": "requests_tokens"}},
    }


class _FixtureGemini:
    """Existing Gemini organize fallback with a real local ledger receipt."""

    supports_cancellable_async = False

    def __init__(self, store):
        self.store = store
        self.calls = []

    def generate(self, role, contents, *, purpose, is_user_turn, max_attempts):
        self.calls.append((role, purpose, is_user_turn, max_attempts))
        self.store.log_llm_call(
            ts=datetime.now(UTC).isoformat(), correlation_id="fixture-gemini",
            role=role, model=GEMINI_MODEL, mode="mock", tokens_in=4,
            tokens_out=3, tokens_estimated=0, audio_seconds=0, cost_usd=0.0,
            latency_ms=1.0, ok=1, verified=0, attempt=1, fixture_key="",
            error="", purpose=purpose, is_user_turn=0,
        )
        return SimpleNamespace(
            text=json.dumps({"findings": ["fixture read"],
                             "candidate_inferences": [],
                             "clarifying_questions": []}),
            model=GEMINI_MODEL,
        )


def _runner(config, tmp_path, *, route_fn, enabled=True):
    store = Store(tmp_path / "ledger.db")
    config.raw.setdefault("organise", {})["material_provider"] = "groq"
    config.raw["organise"]["material_model"] = MODEL
    config.raw.setdefault("quota", {})["providers"] = {"groq": _groq_row(enabled=enabled)}
    adapter = CallbackAdapter("groq", route_fn, (Capability.MATERIAL,))
    router = ProviderRouter(
        config, store, adapters=[adapter], state_path=tmp_path / "router-state.json",
        clock=lambda: 1_000.0,
    )
    gemini = _FixtureGemini(store)
    runner = ErrandRunner(config, store, SimpleNamespace(), client=gemini, router=router)
    source = tmp_path / "fixture_material.txt"
    source.write_text("A fixture observation for errand routing.\n", encoding="utf-8")
    return store, router, gemini, runner, source


async def _run(runner, source):
    started = runner.start(
        "analyze this fixture file",
        roots=[str(source.parent)],
        custom_plan=[
            PlannedStep("file.read", {"target": str(source), "offset": 0,
                                       "max_bytes": 4096}),
            PlannedStep("content.analyze"),
        ],
        budget=ErrandBudget(max_steps=4, max_seconds=20, max_api_calls=4,
                            max_step_api_calls=2, max_read_bytes=4096,
                            allow_escalation=False),
    )
    return await runner.wait(started["errand_id"], timeout=10)


def _analyze_step(result):
    return next(s for s in result["steps"] if s["skill"] == "content.analyze")


async def test_errand_analysis_routes_to_groq_and_assist_cost_reports_it(config, tmp_path):
    def groq(req):
        return ProviderResult(
            text=json.dumps({
                "findings": ["DIVERTED_FINDING_MARKER"],
                "candidate_inferences": [{
                    "text": "DIVERTED_INFERENCE_MARKER",
                    "kind": "preference", "confidence": 0.9,
                    "evidence_quote": "A fixture observation for errand routing.",
                    "evidence_path": str(tmp_path / "fixture_material.txt"),
                }],
                "clarifying_questions": [{
                    "kind": "clarify", "question": "DIVERTED_QUESTION_MARKER",
                }],
            }),
            model=req.model, provider=req.provider,
            usage={"tokens_in": 10, "tokens_out": 5}, request_id="fixture-groq",
        )

    store, _router, gemini, runner, source = _runner(config, tmp_path, route_fn=groq)
    try:
        result = await _run(runner, source)
        step = _analyze_step(result)
        assert result["status"] == "completed"
        assert step["model"] == f"groq/{MODEL}"
        assert step["api_calls"] == 1
        assert step["result"]["provider_route"]["served_by"] == f"groq/{MODEL}"
        assert gemini.calls == []  # no Gemini call on the successful diverted leg
        assert "DIVERTED_" not in json.dumps(result["report"])
        assert "DIVERTED_" not in json.dumps(result["questions"])
        report = provider_cost_report(store)
        groq_rows = [r for r in report["rows"] if r["provider"] == "groq"]
        assert len(groq_rows) == 1 and groq_rows[0]["calls"] == 1
        assert groq_rows[0]["purpose"].endswith("content.analyze")
        assert "groq ·" in format_provider_report(report)  # same block surfaced by assist cost
    finally:
        await runner.aclose()
        store.close()


@pytest.mark.parametrize("failure,enabled,expected_reason,expected_calls", [
    ("rate_limited", True, "RateLimited", 2),
    ("disabled", False, "ProviderDisabledError", 1),
])
async def test_errand_groq_failure_falls_back_to_journaled_gemini(
    config, tmp_path, failure, enabled, expected_reason, expected_calls
):
    def groq(req):
        if failure == "rate_limited":
            raise RateLimited("fixture Groq 429", retry_after=30)
        raise AssertionError("disabled provider adapter must not be called")

    store, _router, gemini, runner, source = _runner(
        config, tmp_path, route_fn=groq, enabled=enabled,
    )
    try:
        result = await _run(runner, source)
        step = _analyze_step(result)
        route = step["result"]["provider_route"]
        assert result["status"] == "completed"
        assert step["model"] == GEMINI_MODEL
        assert route["served_by"] == f"gemini/{GEMINI_MODEL}"
        assert route["fallback_reason"] == expected_reason
        assert len(gemini.calls) == 1
        assert gemini.calls[0][0] == "organise" and gemini.calls[0][2] is False
        assert step["api_calls"] == expected_calls
        fallback_rows = [r for r in store.recent_llm_calls(limit=20)
                         if r["purpose"].endswith("content.analyze")
                         and r["role"] == "organise"]
        assert len(fallback_rows) == 1 and fallback_rows[0]["model"] == GEMINI_MODEL
        assert set(result["report"]) == {
            "errand_id", "instruction", "status", "done", "files_inspected",
            "inspections", "partially_read", "parse_failures", "inferred",
            "confirmed", "point_outcomes", "questions_answered",
            "unanswered_or_unasked", "injection_signals_seen", "budget_used",
            "summary",
        }
        if failure == "rate_limited":
            routed = [r for r in provider_cost_report(store)["rows"]
                      if r["provider"] == "groq"]
            assert routed and routed[0]["failures"] == 1
    finally:
        await runner.aclose()
        store.close()


def test_production_router_factory_registers_material_adapters_and_gates_dispatch(
    config, tmp_path, monkeypatch,
):
    store = Store(tmp_path / "factory.db")
    config.raw.setdefault("quota", {})["providers"] = {"groq": _groq_row(enabled=True)}
    monkeypatch.setenv("ELARIA_GROQ_API_KEY", "fixture-only-not-used")
    try:
        router = create_provider_router(config, store,
                                       state_path=tmp_path / "factory-router-state.json")
        adapters = router.adapters.report()
        assert adapters["groq"] == ["material"]
        assert adapters["openrouter"] == ["material"]
        assert adapters["cloudflare"] == ["material"]
        assert router.ladder_state()["material_diverted"] is True

        config.raw["quota"]["providers"]["groq"]["enabled"] = False
        disabled_router = create_provider_router(
            config, store, state_path=tmp_path / "factory-router-disabled.json")
        assert disabled_router.ladder_state()["material_diverted"] is False
    finally:
        store.close()
