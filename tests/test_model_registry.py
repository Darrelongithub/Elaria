import json
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest

from assistant.cost import format_cost_report, shadow_cost_usd
from assistant.model_pins import PinMismatch
from assistant.model_registry import ModelRegistry


@pytest.mark.parametrize("slot, model_id", [
    ("voice", "Vendor/model-v2"), ("voice", "vendor/model-v1"),
    ("voice", "Vendor/model-v1 "), ("other", "Vendor/model-v1"),
])
def test_wrong_id_rejected_before_load(tmp_path, slot, model_id):
    registry = ModelRegistry(tmp_path / "pins.json")
    registry.register("voice", "Vendor/model-v1")
    loader = Mock()
    with pytest.raises(PinMismatch):
        registry.load_model(slot, model_id, loader)
    loader.assert_not_called()


def test_registration_persists_and_matches_load(tmp_path):
    path = tmp_path / "pins.json"
    registry = ModelRegistry(path)
    registry.register("voice", "Vendor/model-v1")
    registry.register("future", "Vendor/other-v1")
    registry.register("future", "Vendor/other-v1")
    with pytest.raises(PinMismatch):
        registry.register("future", "Vendor/other-v2")
    assert "Pinning the string is not pinning the model." in json.loads(
        path.read_text()
    )["__pinning_note__"]
    reopened = ModelRegistry(path)
    assert dict(reopened.pins) == {"voice": "Vendor/model-v1", "future": "Vendor/other-v1"}
    assert reopened.load_model("future", "Vendor/other-v1", str) == "Vendor/other-v1"


def test_corrupt_registry_is_not_overwritten(tmp_path):
    path = tmp_path / "pins.json"
    raw = '{"voice":"v1","voice":"v2"}'
    path.write_text(raw)
    with pytest.raises(PinMismatch):
        ModelRegistry(path).register("future", "v1")
    assert path.read_text() == raw


@pytest.mark.parametrize("rows, expected", [
    ([], "chat: 2 call(s)"),
    ([{"purpose": "chat", "calls": 2, "tokens": 42, "cost_usd": 0.001}],
     "chat: 2 call(s), 42 tokens, shadow $0.0010"),
])
def test_cost_purpose_row_shapes(rows, expected):
    month = {"calls": 2, "tokens_in": 40, "tokens_out": 2, "audio_seconds": 0, "failures": 0,
                 "cost_usd": 0.001, "by_model": [], "by_purpose": rows}
    assert expected in format_cost_report(month, {"calls": 2, "by_purpose": {"chat": 2}}, {})


def test_shadow_cost_audio_and_token_rates():
    assert shadow_cost_usd("gemini-3.5-transcribe-live", 100, 50, 2) == pytest.approx(0.0006)
    assert shadow_cost_usd("gemini-flash-lite-latest", 100, 50) == pytest.approx(0.0001)


def test_runtime_extras():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    extras = project["optional-dependencies"]
    assert "onnxruntime>=1.24,<2" in extras["voice"]
    assert extras["embeddings"] and extras["diarize"]
    lock = tomllib.loads((root / "uv.lock").read_text())
    assert not {p["name"] for p in lock["package"]} & {"openwakeword", "tflite-runtime"}
