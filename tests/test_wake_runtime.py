"""GATE-FIX 2: optional wake inference never takes the daemon/doctor down.

Force missing/broken native dependencies even on a fully synced laptop. No
model, training takes, API calls or audio device is needed for these tests.
"""

from __future__ import annotations

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant.cli import run_doctor
from assistant.ipc import DaemonError, call
from assistant.wake_guard import KeywordModelUnavailable, OnnxKeywordModel


@pytest.fixture(params=[ImportError, OSError], ids=["missing-extra", "native-library-unavailable"])
def unavailable_onnx(request, monkeypatch):
    original = builtins.__import__

    def without_onnx(name, *args, **kwargs):
        if name == "onnxruntime" or name.startswith("onnxruntime."):
            raise request.param("test: ONNX Runtime is unavailable")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_onnx)


def test_missing_wake_runtime_is_a_paused_refusal(tmp_path, unavailable_onnx):
    model = tmp_path / "owner.onnx"
    model.touch()  # import availability only; never a pretend trained model
    with pytest.raises(KeywordModelUnavailable, match="wake word paused") as exc:
        OnnxKeywordModel.load(model)
    assert "uv sync --extra voice" in str(exc.value)
    assert "energy fallback" in str(exc.value)


def test_doctor_reports_paused_wake_without_crashing(config, tmp_path, unavailable_onnx):
    model = tmp_path / "owner.onnx"
    model.touch()
    config.raw["hotword"]["keyword_model"] = str(model)
    report = run_doctor(config)
    row = next(row for row in report["checks"] if row["check"] == "hotword keyword model")
    assert row["status"] == "warn"
    assert "wake word paused" in row["detail"]
    assert "uv sync --extra voice" in row["detail"]


def test_daemon_survives_missing_wake_and_never_opens_capture(
        config, tmp_path, unavailable_onnx, running_daemon, monkeypatch):
    daemon, _server = running_daemon
    model = tmp_path / "owner.onnx"
    model.touch()
    daemon.wake_guard.settings["keyword_model"] = str(model)
    monkeypatch.setattr(daemon, "_hotword_capture_factory",
                        lambda: pytest.fail("missing wake inference must not open the mic"))
    assert call(config.socket_path, "status")["running"] is True
    with pytest.raises(DaemonError, match="wake word paused"):
        call(config.socket_path, "hotword.start", timeout=5)
    assert daemon._hotword_task is None
    assert call(config.socket_path, "hotword.status")["hotword"]["armed"] is False
    assert call(config.socket_path, "status")["running"] is True
    assert call(config.socket_path, "ack")["network"] is False


def test_no_model_is_a_paused_wake_not_a_runtime_requirement(config):
    config.raw["hotword"]["keyword_model"] = ""
    row = next(row for row in run_doctor(config)["checks"]
               if row["check"] == "hotword keyword model")
    assert row["status"] == "warn"
    assert "wake word paused" in row["detail"]


def test_voice_test_and_daemon_share_one_onnx_keyword_implementation(monkeypatch):
    from assistant.voicetest import OnnxKeywordScorer

    loads, windows = [], []
    model = SimpleNamespace(score_window=lambda pcm: (windows.append(pcm), 0.75)[1])
    monkeypatch.setattr(OnnxKeywordModel, "load",
                        lambda path: (loads.append(path), model)[1])
    scorer = OnnxKeywordScorer("owner.onnx")
    assert scorer.name == "onnx"
    assert scorer.score(b"\x00\x00") == 0.75
    assert loads == ["owner.onnx"]
    assert windows == [b"\x00\x00"]


def test_runtime_has_no_openwakeword_or_tflite_import():
    import ast

    src = Path(__file__).resolve().parents[1] / "src" / "assistant"
    for path in src.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not {"openwakeword", "tflite_runtime"} & {
                name.split(".")[0] for name in names}, path
