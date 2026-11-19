"""Voice-models verification stamp (scene-2 closure, 2026-10-26) — [TESTED-ONLY].

`assist voice models` IS the verification step: a successful live
models.list records `configured_missing` + catalogue facts to
`state_dir/voice-models-verified.json`, and `assist doctor` consumes that
stamp to downgrade its "model ids unverified until a live models.list"
WARN (owner order 2026-10-26, optional small stream-3 item).
"""

from __future__ import annotations

import json

from assistant.gemini_client import GeminiClient
from assistant.store import Store


def _stamp(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return tmp_path


def test_mock_listing_never_stamps(config, tmp_path, monkeypatch):
    _stamp(tmp_path, monkeypatch)
    store = Store(tmp_path / "v.db")
    try:
        client = GeminiClient(config, store)
        result = client.list_models()
        assert result["verified"] is False
        assert not (config.state_dir / "voice-models-verified.json").exists()
    finally:
        store.close()


def test_live_verification_stamps_where_doctor_consumes_it(
        config, tmp_path, monkeypatch):
    _stamp(tmp_path, monkeypatch)
    store = Store(tmp_path / "v.db")
    try:
        client = GeminiClient(config, store)
        client._record_model_verification({
            "configured_missing": [],
            "models": ["gemini-3.5-flash-lite", "gemini-3.8-live"],
            "voice_model": "gemini-3.8-live",
            "catalogue": {"model": "gemini-3.8-live", "count": 40},
        })
        stamp_path = config.state_dir / "voice-models-verified.json"
        assert stamp_path.is_file()
        stamp = json.loads(stamp_path.read_text())
        assert stamp["configured_missing"] == []
        assert stamp["models_count"] == 2
        assert stamp["catalogue_count"] == 40
    finally:
        store.close()


def test_doctor_downgrades_the_model_ids_warn_with_the_stamp(
        config, tmp_path, monkeypatch):
    _stamp(tmp_path, monkeypatch)
    from assistant.cli import run_doctor

    before = {c["check"]: c for c in run_doctor(config)["checks"]}
    assert before["model ids"]["status"] != "ok"   # WARN until verified

    store = Store(tmp_path / "v.db")
    try:
        GeminiClient(config, store)._record_model_verification({
            "configured_missing": [], "models": ["gemini-3.8-live"],
            "voice_model": "gemini-3.8-live",
            "catalogue": {"model": "gemini-3.8-live", "count": 40},
        })
    finally:
        store.close()
    after = {c["check"]: c for c in run_doctor(config)["checks"]}
    assert after["model ids"]["status"] == "ok"
    assert "verified live" in after["model ids"]["detail"]
    assert "configured_missing=[]" in after["model ids"]["detail"]
