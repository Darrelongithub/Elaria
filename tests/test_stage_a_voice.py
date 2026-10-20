"""Stage A — Flare speaks through a LIVE model, validated, and the ledger is honest.

No key, no network. The live transport is a fake with the same seam as
`_SdkTransport`, so every assertion is about OUR routing/validation code; the
one thing this sandbox cannot prove is Google's audio itself, which is exactly
what GATE A names as the user's-machine step.
"""

from __future__ import annotations

import struct
import wave

import pytest

from assistant import gemini_client as gc
from assistant.config import DEFAULT_VOICE_MODEL, DEFAULTS, quota_is_verified
from assistant.daemon import Daemon
from assistant.gemini_client import GeminiClient
from assistant.store import Store
from assistant.tts import STANDARD_ACKS, SpeechService, TtsUnavailable
from assistant.voice_catalogue import (
    VoiceCatalogueError,
    baseline_catalogue,
    validate_or_raise,
    validate_voice,
)


def make_config(tmp_path):
    from assistant.config import load_config

    config = load_config()
    config.raw["tts"] = {
        **config.raw["tts"], "backend": "mock", "voice_id": "elaria-test",
        "player": "none", "cache_dir": str(tmp_path / "cache"),
        "audition_dir": str(tmp_path / "auditions"),
    }
    return config


def make_store(tmp_path, name="stage-a.db"):
    return Store(tmp_path / name)


class FakeSdkTransport(gc._SdkTransport):
    """Same type the real client uses, so live-only paths are exercised."""

    def __init__(self, *, models=None, voices=None, pcm_seconds=0.05):
        self.models = models or [DEFAULT_VOICE_MODEL, "gemini-3.8-flash",
                                 "gemini-3.5-transcribe-live",
                                 "gemini-3.5-transcribe"]
        self.voices = voices if voices is not None else ["Flare", "Kore", "Puck"]
        self.audio_calls: list[tuple[str, str]] = []
        self.pcm = struct.pack("<800h", *[3000 if i % 2 else -3000 for i in range(800)])
        self.pcm_seconds = pcm_seconds

    def list_models(self):
        return list(self.models)

    def list_voices(self):
        return list(self.voices)

    def generate_audio(self, model, text, voice_name):
        self.audio_calls.append((model, voice_name))
        return {"pcm": self.pcm, "sample_rate": 24000, "voice_name": voice_name,
                "usage": {"tokens_in": 4, "tokens_out": 12}}

    def generate(self, model, contents, config):  # pragma: no cover - not used here
        return {"text": "", "usage": {"tokens_in": 0, "tokens_out": 0}}


def live_client(tmp_path, transport, *, voice="Flare", allowed=("Flare",)):
    config = make_config(tmp_path)
    config.gemini_mode = "live"
    config._api_key = "not-a-real-key"
    config.raw["gemini"] = {
        **config.section("gemini"),
        "gemini_voice_model": DEFAULT_VOICE_MODEL,
        "voice": voice,
        "allowed_voices": list(allowed),
    }
    return GeminiClient(config, make_store(tmp_path), transport=transport)


# ── defaults + the wrong-model regression ────────────────────────────────────

def test_voice_model_default_is_the_live_model_not_a_tts_preview():
    assert DEFAULTS["gemini"]["gemini_voice_model"] == "gemini-3.8-live"
    assert "tts" not in DEFAULTS["gemini"]["gemini_voice_model"]
    assert DEFAULTS["gemini"]["model_transcribe_batch"] == "gemini-3.5-transcribe"


def test_voice_request_names_the_live_model_and_the_live_api(tmp_path):
    transport = FakeSdkTransport()
    client = live_client(tmp_path, transport)
    request = client.voice_request("On it.")
    assert request["model"] == "gemini-3.8-live"
    assert request["api"] == "live"                     # not generateContent TTS
    assert request["voice_name"] == "Flare"
    assert request["voice_allowed"] is True


def test_generate_voice_uses_the_live_transport(tmp_path):
    transport = FakeSdkTransport()
    client = live_client(tmp_path, transport)
    audio = client.generate_voice("On it.")
    assert transport.audio_calls == [("gemini-3.8-live", "Flare")]
    assert audio["sample_rate"] == 24000 and audio["pcm"]


# ── real-catalogue validation ────────────────────────────────────────────────

def test_live_catalogue_is_fetched_and_cached(tmp_path):
    store = make_store(tmp_path, "catalogue.db")
    transport = FakeSdkTransport(voices=["Kore", "Puck", "Flare"])
    client = live_client(tmp_path, transport)
    client.store = store
    catalogue = client.voice_catalogue(refresh=True)
    assert catalogue["source"] == "live-api" and catalogue["verified"] is True
    assert {"Kore", "Puck", "Flare"} <= set(catalogue["voices"])
    cached = store.get_state("voice.catalogue")
    assert cached and "live-api" in cached


def test_model_id_is_checked_against_a_real_models_list(tmp_path):
    client = live_client(tmp_path, FakeSdkTransport())
    result = client.resolve_voice_model()
    assert result["verified"] is True
    assert result["model"] == "gemini-3.8-live"
    assert "gemini-3.8-live" in result["live_models"]

    transport = FakeSdkTransport(models=["gemini-3.8-flash",
                                         "gemini-3.5-transcribe"])
    bad = live_client(tmp_path, transport)
    with pytest.raises(RuntimeError) as excinfo:
        bad.resolve_voice_model()
    message = str(excinfo.value)
    assert "gemini-3.8-live" in message
    assert "not in the live model list" in message
    assert "gemini-3.1-flash-live-preview" not in message  # nothing invented


def test_unknown_voice_fails_with_the_allowed_list(tmp_path):
    client = live_client(tmp_path, FakeSdkTransport(voices=["Kore", "Puck"]),
                         voice="NotARealVoice", allowed=("NotARealVoice",))
    with pytest.raises(RuntimeError) as excinfo:
        client.generate_voice("On it.")
    message = str(excinfo.value)
    assert "not supported by model" in message
    assert "allowed (" in message and "Kore" in message and "Puck" in message
    assert message.count("NotARealVoice") >= 1


def test_baseline_lists_flare_and_names_its_source():
    catalogue = baseline_catalogue(DEFAULT_VOICE_MODEL)
    assert "Flare" in catalogue["voices"]
    assert catalogue["source"] == "baseline" and catalogue["verified"] is False
    assert validate_voice(DEFAULT_VOICE_MODEL, "Flare", catalogue)["ok"] is True


def test_validate_or_raise_carries_the_allowed_list():
    catalogue = baseline_catalogue(DEFAULT_VOICE_MODEL)
    with pytest.raises(VoiceCatalogueError) as excinfo:
        validate_or_raise(DEFAULT_VOICE_MODEL, "DefinitelyNotAVoice", catalogue)
    assert "Zephyr" in excinfo.value.allowed
    assert "allowed (" in str(excinfo.value)


# ── warm path through the daemon: GATE A evidence, offline ───────────────────

class WarmVoiceClient:
    """The exact client surface the warm path uses, with a real WAV result."""

    mode = "live"

    def __init__(self, pcm_seconds=0.05):
        self.pcm = struct.pack("<800h", *[2500 if i % 2 else -2500 for i in range(800)])
        self.calls: list[tuple[str, str]] = []
        self.validated = 0
        self.pcm_seconds = pcm_seconds

    def can_speak(self):
        return True

    def voice_request(self, text, *, voice=None):
        return {"model": "gemini-3.8-live", "voice_name": voice or "Flare",
                "voice_requested": "Flare", "voice_allowed": True,
                "canonical_voices": ["Flare"], "response_modalities": ["AUDIO"],
                "api": "live", "text": text}

    def validate_speech_config(self):
        self.validated += 1
        return {"model": {"model": "gemini-3.8-live", "verified": True},
                "catalogue": {"source": "live-api", "verified": True,
                              "voices": ["Flare", "Kore"]},
                "voice": {"ok": True, "voice": "Flare"}}

    def generate_voice(self, text, *, voice=None, correlation_id="-"):
        self.calls.append(("gemini-3.8-live", "Flare"))
        return {"pcm": self.pcm, "sample_rate": 24000, "voice_name": "Flare",
                "usage": {"tokens_in": 3, "tokens_out": 9}}


def test_gate_a_daemon_warm_completes_with_no_voice_error(tmp_path):
    config = make_config(tmp_path)
    daemon = Daemon(config)
    client = WarmVoiceClient()
    daemon.speech = SpeechService(config, daemon.store, client=client,
                                  is_online=lambda: True)

    import asyncio

    out = asyncio.run(daemon._speech_warm({}))

    assert client.validated == 1, "the warm path must validate before rendering"
    assert client.calls == [("gemini-3.8-live", "Flare")] * len(STANDARD_ACKS)
    assert out["voice"]["ack_cache"]["complete"] is True
    assert out["voice"]["voice_error"] is None
    assert out["voice"]["voice_identity"]["allowed"] is True
    assert out["voice"]["gemini_voice_model"] == "gemini-3.8-live"
    assert len(out["warmed"]) == len(STANDARD_ACKS)
    for entry in out["warmed"].values():
        assert entry["backend"] == "gemini-native-audio"
        assert entry["voice_id"] == "Flare"
    for kind in STANDARD_ACKS:                    # every ack is a real WAV
        path = daemon.speech.cached_ack(kind)
        assert path
        with wave.open(path) as wav:
            assert wav.getframerate() == 24000


def test_warm_fails_loudly_with_the_allowed_list(tmp_path):
    config = make_config(tmp_path)
    store = make_store(tmp_path, "warmfail.db")

    class BadClient(WarmVoiceClient):
        def validate_speech_config(self):
            raise VoiceCatalogueError(
                "voice 'Flare' is not supported by model 'gemini-3.8-live' — "
                "allowed (2): Kore, Puck",
                allowed=["Kore", "Puck"], model="gemini-3.8-live", source="live-api")

    speech = SpeechService(config, store, client=BadClient(), is_online=lambda: True)
    with pytest.raises(TtsUnavailable) as excinfo:
        speech.warm_ack_cache()
    assert "allowed (2): Kore, Puck" in str(excinfo.value)
    assert speech.last_voice_error and "validation failed" in speech.last_voice_error


# ── the confirmed voice_identity bug ─────────────────────────────────────────

REFUSAL_WORDS = ("refused", "not canonical", "will not speak", "unapproved",
                 "a mismatch", "rejected")


def test_allowed_true_never_contains_refusal_text(tmp_path):
    config = make_config(tmp_path)
    speech = SpeechService(config, make_store(tmp_path, "id-ok.db"),
                           client=WarmVoiceClient(), is_online=lambda: True)
    identity = speech.voice_identity()
    assert identity["allowed"] is True
    assert identity["effective"] == "Flare"
    lowered = identity["reason"].lower()
    assert not any(word in lowered for word in REFUSAL_WORDS), identity["reason"]
    assert "verified" in lowered and "flare" in lowered
    assert identity["model"] == "gemini-3.8-live"


def test_allowed_false_still_refuses_and_names_the_list(tmp_path):
    config = make_config(tmp_path)
    config.raw["gemini"] = {**config.section("gemini"), "voice": "Zephyr"}
    speech = SpeechService(config, make_store(tmp_path, "id-bad.db"),
                           client=WarmVoiceClient(), is_online=lambda: True)
    identity = speech.voice_identity()
    assert identity["allowed"] is False
    assert "refused" in identity["reason"].lower()
    assert "Flare" in identity["reason"]


# ── quota is read, not re-invented ───────────────────────────────────────────

def test_quota_verified_marker_and_rows():
    quota = DEFAULTS["quota"]
    assert quota_is_verified(quota) is True
    assert quota["models"]["flash"] == {"rpm": 5, "tpm": 250_000, "rpd": 20}
    assert quota["models"]["flash-lite"]["rpd"] == 500
    assert quota["models"]["transcribe-live"]["rpm"] == 0
    assert quota["models"]["transcribe-batch"]["rpd"] == 25


def test_doctor_reads_verified_quota_and_stops_crying_wolf(tmp_path):
    from assistant.cli import run_doctor

    config = make_config(tmp_path)
    report = {c["check"]: c for c in run_doctor(config)["checks"]}
    quota = report["quota shape"]
    assert quota["status"] == "ok"
    assert "VERIFIED 2026-10-20" in quota["detail"]
    assert "5 RPM" in quota["detail"] and "20 RPD" in quota["detail"]
    assert "ASSUMED" not in quota["detail"]
    assert "aistudio.google.com" not in quota["detail"]
    assert report["voice model"]["status"] == "ok"


def test_doctor_restores_the_warning_without_the_verified_marker(tmp_path):
    from assistant.cli import run_doctor

    config = make_config(tmp_path)
    config.raw["quota"] = {**config.section("quota"), "verified": False,
                           "verified_at": ""}
    report = {c["check"]: c["detail"] for c in run_doctor(config)["checks"]}
    assert "ASSUMED, UNVERIFIED" in report["quota shape"]
    assert "aistudio.google.com/rate-limit" in report["quota shape"]


def test_cost_report_uses_verified_quota():
    from assistant.cost import format_cost_report

    report = format_cost_report(
        {"cost_usd": 0.0, "calls": 0, "tokens_in": 0, "tokens_out": 0,
         "audio_seconds": 0.0, "failures": 0, "by_model": []},
        {"calls": 0, "live_calls": 0}, DEFAULTS["quota"], "free")
    assert "Quota: VERIFIED" in report and "5 RPM" in report
    assert "ASSUMED" not in report


def test_batch_transcribe_uses_the_dedicated_model(tmp_path):
    import wave as _wave

    audio = tmp_path / "a.wav"
    with _wave.open(str(audio), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    config = make_config(tmp_path)
    client = GeminiClient(config, make_store(tmp_path, "tx.db"))
    result = client.transcribe_batch(audio)
    assert result["model"] == "gemini-3.5-transcribe"
    assert result["backend"] == "gemini_batch"
