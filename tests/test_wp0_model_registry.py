"""Phase 0 pin fix (owner-approved 2026-10-25): §4.1 registry + forbidden scan.

Evidence level: [TESTED-ONLY] — mock/counted transports, no network, no
hardware. The registry table itself is asserted so the doctor scan and the
runtime guard cannot drift apart.
"""

from __future__ import annotations

import pytest

from assistant.config import DEFAULTS, quota_rows
from assistant.cost import iso_now
from assistant.gemini_client import GeminiClient, QuotaExhausted
from assistant.model_registry import (
    ALLOWED_IDS,
    FORBIDDEN_IDS,
    PINNED_ROLES,
    ForbiddenModelError,
    assert_model_permitted,
    registry_report,
    scan_config_values,
)
from assistant.store import Store

# -- the registry table ----------------------------------------------------

def test_pinned_roles_are_the_wire_spec_41_ids():
    assert PINNED_ROLES["voice"] == "gemini-3.8-live"
    assert PINNED_ROLES["transcribe_live"] == "gemini-3.5-transcribe-live"
    assert PINNED_ROLES["transcribe_batch"] == "gemini-3.5-transcribe"
    assert PINNED_ROLES["file_fallback"] == "gemini-3.5-flash-lite"
    assert PINNED_ROLES["chat"] == "gemini-3.5-flash-lite"
    assert PINNED_ROLES["escalation"] == "gemini-3.8-flash"
    assert PINNED_ROLES["cached_tts"] == "gemini-3.8-flash-lite-tts"


def test_forbidden_ids_are_exactly_the_wire_spec_list():
    assert FORBIDDEN_IDS == frozenset({
        "gemini-2.5-flash-preview-tts",
        "gemini-2.5-flash-native-audio-preview-12-2025",
        "gemini-3.1-flash-live-preview",
        "gemini-2.5-flash-lite",
    })
    assert not (FORBIDDEN_IDS & ALLOWED_IDS)


def test_default_config_is_fully_registered(config):
    report = registry_report(config)
    assert report["forbidden"] == []
    assert report["unregistered"] == [], (
        f"shipped defaults must be registry-clean: {report['unregistered']}")
    assert report["ladder_unregistered"] == []
    assert report["ok"] is True


def test_defaults_use_pinned_ids_not_aliases():
    gemini = DEFAULTS["gemini"]
    for key in ("model_default", "model_organise", "model_cleanup",
                "model_chat", "model_file_fallback"):
        assert gemini[key] == "gemini-3.5-flash-lite", key
        assert not gemini[key].endswith("-latest"), f"{key} is an alias"
    assert gemini["escalation_ladder"] == ["gemini-3.5-flash-lite",
                                           "gemini-3.8-flash"]
    for model in gemini["escalation_ladder"]:
        assert not model.endswith("-latest")


# -- the forbidden scan (owner decision: configured/invoked only) ----------

def test_scan_flags_forbidden_alias_and_registered(config):
    config.raw["gemini"]["model_chat"] = "gemini-2.5-flash-lite"
    config.raw["gemini"]["model_organise"] = "gemini-flash-lite-latest"
    findings = {f["id"]: f["verdict"] for f in scan_config_values(config)}
    assert findings["gemini-2.5-flash-lite"] == "forbidden"
    assert findings["gemini-flash-lite-latest"] == "unregistered"
    assert findings["gemini-3.5-flash-lite"] == "registered"
    report = registry_report(config)
    assert report["ok"] is False
    assert [f["id"] for f in report["forbidden"]] == ["gemini-2.5-flash-lite"]


def test_ladder_entries_are_registry_checked(config):
    config.raw["gemini"]["escalation_ladder"] = ["gemini-3.5-flash-lite",
                                                "gemini-flash-latest"]
    report = registry_report(config)
    assert report["ladder_unregistered"] == ["gemini-flash-latest"]
    assert report["ok"] is False


def test_forbidden_guard_refuses_the_wire(config, tmp_path):
    store = Store(tmp_path / "g.db")
    try:
        client = GeminiClient(config, store)
        with pytest.raises(ForbiddenModelError, match="forbidden"):
            client._call_once("chat", "gemini-2.5-flash-lite", "hi", {},
                              correlation_id="x", attempt=1)
        with pytest.raises(ForbiddenModelError):
            assert_model_permitted("models/gemini-3.1-flash-live-preview")
        assert assert_model_permitted("gemini-3.5-flash-lite") == "gemini-3.5-flash-lite"
    finally:
        store.close()


# -- the chat RPD config cap (§4.1: 400 under the ~500 free) --------------

def test_rpd_cap_is_stricter_than_measured_rpd(config, tmp_path):
    quota = config.raw["quota"]
    quota["models"]["flash-lite"]["rpd"] = 500
    quota["models"]["flash-lite"]["rpd_cap"] = 3
    config.raw["gemini"]["model_default"] = "gemini-3.5-flash-lite"
    store = Store(tmp_path / "c.db")
    try:
        client = GeminiClient(config, store)
        for i in range(3):
            store.log_llm_call(
                ts=iso_now(), correlation_id=f"cap-{i}", role="chat",
                model="gemini-3.5-flash-lite", mode="live", tokens_in=1,
                tokens_out=1, tokens_estimated=0, audio_seconds=0,
                cost_usd=0.0, latency_ms=1, ok=1, verified=None, attempt=0,
                fixture_key="k", error=None, purpose="user_turn", is_user_turn=1)
        with pytest.raises(QuotaExhausted, match="40|rpd_cap|3"):
            client._check_daily_cap("gemini-3.5-flash-lite")
    finally:
        store.close()


def test_rpd_cap_survives_quota_rows_normalisation(config):
    rows = {r["model"]: r for r in quota_rows(config.raw["quota"])}
    assert rows["flash-lite"]["rpd_cap"] == 400
    assert rows["flash-lite"]["rpd"] == 500


def test_flat_and_structured_rpd_cap_disagree_warns(config):
    from assistant.config import validate_config

    config.raw["quota"]["flash_lite_rpd_cap"] = 250
    report = validate_config(config)
    assert any("rpd_cap" in w and "disagree" in w for w in report["warnings"]), (
        report["warnings"])
