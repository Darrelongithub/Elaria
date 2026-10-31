"""W1 probe harness tests (scene-7 work order, 2026-10-31).

The probe is the owner-run instrument for the 7-of-29-chars stump; these
pins prove the harness itself: it calls the file leg exactly as production
invokes it, prints the raw model text with its char count, prints
production's real prompt (the shared helper — never a reimplementation),
and never leaks the API key.
"""

from __future__ import annotations

import importlib.util
import os
import wave
from pathlib import Path

from assistant import asr
from assistant.asr import Transcript
from assistant.gemini_client import batch_transcription_prompt

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "file_leg_probe.py"
_spec = importlib.util.spec_from_file_location("file_leg_probe", _SCRIPT)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def _write_wav(path: Path, frames: int = 1600) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x01\x00" * frames)
    return path


def test_wav_facts_reads_the_header_and_checks_consistency(tmp_path):
    path = _write_wav(tmp_path / "sample.wav", frames=1600)
    facts = probe.wav_facts(str(path))
    assert facts["rate_hz"] == 16000
    assert facts["channels"] == 1
    assert facts["sampwidth_bits"] == 16
    assert facts["frames"] == 1600
    assert facts["duration_s"] == 0.1
    assert facts["consistent"] is True
    assert facts["size_bytes"] == 44 + 1600 * 2
    assert facts["header_hex"].startswith("52494646")  # "RIFF"


def test_run_calls_the_production_leg_and_prints_text_with_char_count(
        config, tmp_path, monkeypatch, capsys):
    path = _write_wav(tmp_path / "known.wav", frames=3200)
    calls = []

    def fake_leg(cfg, client, audio_path, **kwargs):
        calls.append((cfg, client, audio_path, kwargs))
        return Transcript("hello there", "en", "gemini_batch", confidence=0.9)

    monkeypatch.setattr(asr, "transcribe_file", fake_leg)
    lines = []
    rc = probe.run(config, object(), [str(path)], printer=lines.append,
                   raw_pass=False)
    out = "\n".join(lines)
    assert rc == 0
    assert len(calls) == 1, "the probe must call the file leg exactly once per wav"
    assert calls[0][2] == str(path)
    assert "raw model text (11 chars): 'hello there'" in out
    assert repr(batch_transcription_prompt("en")) in out, \
        "the printed prompt must be production's prompt (shared helper)"


def test_production_facts_report_model_chain_and_prompt(config):
    facts = probe.production_facts(config, object())
    assert facts["model"] == config.model_for_role("transcribe_batch")
    assert facts["chain"], "the fallback chain must be enumerated"
    assert facts["prompt"] == batch_transcription_prompt(
        asr.configured_languages(config)[0])


def test_raw_pass_prints_finish_reason_and_usage(config, tmp_path,
                                                monkeypatch):
    path = _write_wav(tmp_path / "raw.wav", frames=1600)

    class _Cand:
        def __init__(self):
            self.finish_reason = "MAX_TOKENS"
            self.content = type("C", (), {"parts": ["part-text"]})()

    class _Resp:
        def __init__(self):
            self.text = "He"
            self.candidates = [_Cand()]
            self.usage_metadata = type("U", (), {
                "prompt_token_count": 330,
                "candidates_token_count": 2})()

    class _Models:
        def generate_content(self, *, model, contents):
            assert contents[0] == batch_transcription_prompt("en")
            return _Resp()

    class _Files:
        def upload(self, *, file):
            return object()

    class _Sdk:
        files = _Files()
        models = _Models()

    class _Transport:
        _client = _Sdk()

    class _Client:
        _transport = _Transport()

    monkeypatch.setattr(asr, "transcribe_file",
                        lambda *a, **k: Transcript("He", "en", "gemini_batch"))
    lines = []
    rc = probe.run(config, _Client(), [str(path)], printer=lines.append,
                   raw_pass=True)
    out = "\n".join(lines)
    assert rc == 0
    assert "finish_reason=MAX_TOKENS" in out
    assert "usage_metadata" in out
    assert "raw model text (2 chars): 'He'" in out


# -- mini order M-2: arm C (registry files model, same wire) ---------------

def _armc_client(calls: list, texts: dict):
    """Fake SDK transport recording (model, path) per generate_content call."""

    class _Cand:
        finish_reason = "STOP"
        content = type("C", (), {"parts": []})()

    class _Resp:
        def __init__(self, text):
            self.text = text
            self.candidates = [_Cand()]
            self.usage_metadata = type("U", (), {
                "prompt_token_count": 300,
                "candidates_token_count": 20})()

    class _Models:
        def generate_content(self, *, model, contents):
            calls.append(model)
            return _Resp(texts.get(model, "a whole sentence of transcript"))

    class _Files:
        def upload(self, *, file):
            return object()

    class _Sdk:
        files = _Files()
        models = _Models()

    class _Transport:
        _client = _Sdk()

    class _Client:
        _transport = _Transport()

    return _Client()


def test_arm_c_uses_the_arm_c_model_while_section4_keeps_production(
        config, tmp_path, monkeypatch):
    """M-2: the causal discriminator — same wav, same wire, only the model
    differs. Section 4 (production) and section 5 (arm C) both run, in that
    order, each against its own model."""
    path = _write_wav(tmp_path / "armc.wav", frames=1600)
    monkeypatch.setattr(asr, "transcribe_file",
                        lambda *a, **k: Transcript("He", "en", "gemini_batch"))
    calls: list = []
    client = _armc_client(calls, {"gemini-3.5-transcribe":
                                  "the whole sentence came back fine"})
    lines = []
    rc = probe.run(config, client, [str(path)], printer=lines.append,
                   raw_pass=True, arm_c_model="gemini-3.5-transcribe")
    out = "\n".join(lines)
    assert rc == 0
    production_model = config.model_for_role("transcribe_batch")
    assert calls == [production_model, "gemini-3.5-transcribe"], \
        "section 4 must use production's resolved model; section 5 the arm C model"
    assert "section 5 — arm C" in out
    assert "the whole sentence came back fine" in out
    # same paste-safe shape as section 4: model, text+chars, finish_reason, usage
    armc_tail = out.split("section 5 — arm C", 1)[1]
    assert "model: gemini-3.5-transcribe" in armc_tail
    assert "raw model text (33 chars):" in armc_tail
    assert "finish_reason=STOP" in armc_tail
    assert "usage_metadata" in armc_tail


def test_arm_c_override_model_is_honoured(config, tmp_path, monkeypatch):
    path = _write_wav(tmp_path / "armc2.wav", frames=1600)
    monkeypatch.setattr(asr, "transcribe_file",
                        lambda *a, **k: Transcript("He", "en", "gemini_batch"))
    calls: list = []
    client = _armc_client(calls, {})
    probe.run(config, client, [str(path)], printer=lambda *_: None,
              raw_pass=True, arm_c_model="gemini-3.5-flash-lite")
    assert calls[-1] == "gemini-3.5-flash-lite"


def test_main_defaults_arm_c_to_the_registry_files_model(monkeypatch):
    """The arm C default is the REGISTRY pin (model_registry.EVENT_TRANSCRIPTION),
    never whatever production's config resolved — that is the whole point."""
    import assistant.config as config_mod
    import assistant.gemini_client as client_mod
    import assistant.store as store_mod

    monkeypatch.setenv("GEMINI_API_KEY", "SECRET-ARM-C-KEY")
    try:
        from types import SimpleNamespace

        monkeypatch.setattr(config_mod, "load_config",
                            lambda: SimpleNamespace(state_dir=Path("/tmp")))
        monkeypatch.setattr(store_mod, "Store",
                            lambda *_: type("S", (), {"close": lambda self: None})())
        monkeypatch.setattr(client_mod, "GeminiClient", lambda *_: object())
        captured = {}

        def fake_run(config, client, wavs, **kwargs):
            captured.update(kwargs)
            return 0

        monkeypatch.setattr(probe, "run", fake_run)
        assert probe.main(["--no-raw"]) == 0
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
    assert captured["arm_c_model"] == "gemini-3.5-transcribe"
    assert captured["raw_pass"] is False


def test_arm_c_never_leaks_the_key(config, tmp_path, monkeypatch):
    os.environ["GEMINI_API_KEY"] = "SECRET-ARM-C-KEY-456"
    try:
        path = _write_wav(tmp_path / "leak2.wav", frames=1600)
        monkeypatch.setattr(asr, "transcribe_file",
                            lambda *a, **k: Transcript("ok", "en",
                                                       "gemini_batch"))
        lines = []
        probe.run(config, _armc_client([], {}), [str(path)],
                  printer=lines.append, raw_pass=True,
                  arm_c_model="gemini-3.5-transcribe")
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
    assert "SECRET-ARM-C-KEY-456" not in "\n".join(lines)


def test_the_key_never_leaks(config, tmp_path, monkeypatch):
    # Set by hand (not monkeypatch): the suite's autouse guard asserts the
    # env carries no key at teardown, before monkeypatch would undo.
    os.environ["GEMINI_API_KEY"] = "SECRET-PROBE-KEY-123"
    try:
        path = _write_wav(tmp_path / "leak.wav", frames=1600)
        monkeypatch.setattr(asr, "transcribe_file",
                            lambda *a, **k: Transcript("ok", "en",
                                                       "gemini_batch"))
        lines = []
        rc = probe.run(config, object(), [str(path)], printer=lines.append,
                       raw_pass=False)
    finally:
        os.environ.pop("GEMINI_API_KEY", None)
    assert rc == 0
    out = "\n".join(lines)
    assert "SECRET-PROBE-KEY-123" not in out
    assert "GEMINI_API_KEY: present" in out


def test_main_refuses_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert probe.main(["--no-raw"]) == 2
