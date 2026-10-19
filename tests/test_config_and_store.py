"""Config resolution + cost ledger (Phase 0 items 1–2, §3.2/§12.9)."""

from pathlib import Path

from assistant.config import load_config
from assistant.cost import iso_now, month_start_iso, shadow_cost_usd
from assistant.store import Store


def test_no_key_means_mock_not_crash(config):
    # §12.9 guardrail: missing key => "no network", never an import crash.
    assert config.api_key_present is False
    assert config.gemini_mode == "mock"


def test_paths_are_xdg_never_hardcoded(config):
    assert config.db_path.name == "assistant.db"
    assert ".local/share/assistant" in str(config.db_path)
    assert config.socket_path.name == "assistant.sock"


def test_language_seam_english_first(config):
    # English first; Kiswahili Phase 7 is a config flip, not a refactor (§0).
    assert config.section("asr")["languages"] == ["en"]
    assert config.section("persona")["name"] == "Elaria"


def test_ledger_written_on_every_call(tmp_path):
    store = Store(tmp_path / "t.db")
    store.log_llm_call(
        ts=iso_now(), correlation_id="c1", role="chat", model="gemini-flash-lite-latest",
        mode="mock", tokens_in=100, tokens_out=50, tokens_estimated=0,
        audio_seconds=0, cost_usd=shadow_cost_usd("gemini-flash-lite-latest", 100, 50),
        latency_ms=12.0, ok=1, verified=None, attempt=1, fixture_key="k", error=None)
    summary = store.llm_summary(month_start_iso())
    assert summary["calls"] == 1
    assert summary["tokens_in"] == 100 and summary["tokens_out"] == 50
    assert summary["cost_usd"] > 0  # shadow cost even though free tier bills $0
    assert summary["by_model"][0]["model"] == "gemini-flash-lite-latest"


def test_shadow_cost_usescheapest_tier_rates():
    lite = shadow_cost_usd("gemini-flash-lite-latest", 1_000_000, 0)
    flash = shadow_cost_usd("gemini-flash-latest", 1_000_000, 0)
    assert lite == 0.25 and flash == 0.75  # §3.2 rates


def test_user_config_overrides_defaults(tmp_path, monkeypatch):
    cfg = Path(tmp_path) / "custom.toml"
    cfg.write_text('[persona]\ncandour = 0.3\n[asr]\nlanguages = ["en", "sw"]\n')
    monkeypatch.setenv("ASSIST_CONFIG", str(cfg))
    loaded = load_config()
    assert loaded.section("persona")["candour"] == 0.3
    assert loaded.section("persona")["name"] == "Elaria"  # deep-merge keeps rest
    assert loaded.section("asr")["languages"] == ["en", "sw"]  # Phase 7 flip works
