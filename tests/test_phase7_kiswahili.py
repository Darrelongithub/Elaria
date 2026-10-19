"""Phase 7 (§9/§12.4-5): Kiswahili flip + code-switching guards.

What's verifiable headless (and tested here): the config flip threads
sw+en into the batch prompt + fixture key, the cleanup guard rejects
normalised/translated rewrites proportionally, the intent ladder
answers Kiswahili commands locally, and doctor reports guard state.
What is NOT claimed: actual Swahili ASR accuracy — that's a live-key
Step-0 measurement on the owner's voice."""

import struct

import pytest

from assistant.asr import (
    Transcript,
    assert_output_language,
    code_switching_enabled,
    configured_languages,
    primary_language,
)
from assistant.cleanup import CleanupPass, language_mix_preserved, language_profile
from assistant.gemini_client import GeminiClient
from assistant.intents import route
from assistant.store import Store

RAW_MIXED = ("sasa leo nimepata invoice ya Kamau lakini bado sijui "
             "kama wameweka bei sahihi alafu kesho tutazungumza kabisa")
CLEANED_OK = ("Sasa leo nimepata invoice ya Kamau, lakini bado sijui kama "
              "wameweka bei sahihi. Alafu kesho tutazungumza kabisa.")
CLEANED_TRANSLATED = ("So today I received Kamau's invoice but I still don't know "
                      "if the price is right, then tomorrow we will talk fully.")
CLEANED_ONE_TOKEN = ("Sasa, today I received the invoice from Kamau but I still do "
                     "not know whether the price is correct and tomorrow we talk.")


def flip_to_bilingual(config):
    config.raw["asr"] = {**config.raw["asr"], "languages": ["sw", "en"],
                          "preserve_code_switching": True}
    return config


def test_config_flip_pins_sw_primary(config):
    flip_to_bilingual(config)
    assert configured_languages(config) == ["sw", "en"]
    assert primary_language(config) == "sw"
    assert code_switching_enabled(config) is True
    tag = Transcript(text="x", language="sw,en", backend="t")
    assert assert_output_language(tag, ["sw", "en"]) is True
    assert assert_output_language(tag, ["en"]) is False  # silent-drop caught


def test_marker_guard_is_proportional():
    assert language_profile(RAW_MIXED)["sw_markers"] >= 6
    assert language_mix_preserved(RAW_MIXED, CLEANED_OK) is True
    assert language_mix_preserved(RAW_MIXED, CLEANED_TRANSLATED) is False
    # The Phase-1-era gate (>=1 marker) would have PASSED this; the
    # proportional gate must not — one token 'sasa' is not preservation.
    assert language_mix_preserved(RAW_MIXED, CLEANED_ONE_TOKEN) is False
    assert language_mix_preserved("plain english text here", "anything") is True


class TranslatingTransport:
    """A 'helpful' model that translates — exactly what the gate exists for."""

    def generate(self, model, contents, config):
        return {"text": CLEANED_TRANSLATED, "usage": {"tokens_in": 10, "tokens_out": 10}}


def test_cleanup_rejects_translation_and_keeps_raw(config, tmp_path):
    flip_to_bilingual(config)
    store = Store(tmp_path / "t.db")
    client = GeminiClient(config, store, transport=TranslatingTransport(),
                          sleep=lambda _: None)
    result = CleanupPass(config, client).run(RAW_MIXED)
    assert result.flagged and "language gate" in result.reason


def test_batch_prompt_bilingual_only_when_flipped(config, tmp_path):
    """Via fixture key: the prompt is part of `contents`, so mock
    transport sees it. Language set changing must change the request."""
    seen = []

    class SnoopingTransport:
        def generate(self, model, contents, cfg):
            seen.append(contents)
            return {"text": "habari", "usage": {"tokens_in": 1, "tokens_out": 1}}

    wav = tmp_path / "a.wav"
    from assistant.capture import write_wav

    write_wav(wav, [struct.pack("<h", 100) * 1600], 16000)
    store = Store(tmp_path / "t.db")
    flip_to_bilingual(config)
    from assistant.asr import GeminiBatchBackend

    client = GeminiClient(config, store, transport=SnoopingTransport(),
                          sleep=lambda _: None)
    transcript = GeminiBatchBackend(client, config).transcribe(str(wav), "sw")
    assert transcript.language == "sw,en"
    prompt = seen[0]["prompt"]
    assert "code-switch" in prompt and "Do NOT translate" in prompt
    assert seen[0]["languages"] == ["sw", "en"]


@pytest.mark.parametrize("text,kind", [
    ("kumbuka kwamba ninapiga simu jioni", "remember"),
    ("sahau kuhusu mkutano", "forget"),
    ("iko wapi invoice ya Kamau", "where"),
    ("tafuta mikataba", "search"),
    ("simama", "halt"), ("hali", "status"), ("panga downloads", "organise"),
    ("rudisha tangu 2h", "undo"),
])
def test_kiswahili_intent_ladder(text, kind):
    intent = route(text)
    assert intent is not None and intent.kind == kind


def test_doctor_reports_guard_state(config):
    from assistant.cli import run_doctor

    checks = {c["check"]: c["detail"] for c in run_doctor(config)["checks"]}
    assert "English first" in checks["languages"]
    flip_to_bilingual(config)
    checks = {c["check"]: c["detail"] for c in run_doctor(config)["checks"]}
    assert "ARMED" in checks["languages"]


def test_dictation_language_recorded_honestly(config, tmp_path, running_daemon):
    """Flipped config: meeting/batch records carry the bilingual tag."""
    from assistant.capture import write_wav
    from assistant.gemini_client import GeminiClient as GC
    from assistant.meeting import MeetingService

    daemon, _server = running_daemon
    flip_to_bilingual(daemon.config)
    rate = 16000
    tone = struct.pack("<h", 8000) * (rate // 2)
    mic = write_wav(tmp_path / "m.wav", [tone], rate)
    sys_wav = write_wav(tmp_path / "s.wav", [tone], rate)
    store = Store(tmp_path / "t2.db")
    result = MeetingService(daemon.config, store,
                            GC(daemon.config, store)).transcribe_dual(mic, sys_wav)
    assert result.note_path.exists()
    record = store.recent_transcripts(1)[0]
    assert record["language"] == "sw,en"
