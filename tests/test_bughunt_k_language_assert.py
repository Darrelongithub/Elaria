"""BH-K19: `[asr] assert_output_language` was a dead promise.

The config key (default true, blueprint §12.4 "catches silent
translation") and the `asr.assert_output_language` tag-check helper
existed, but nothing ever called the helper: a backend reporting an
out-of-set language tag sailed through the whole pipeline unmarked.

Fix: the batch seam (`asr.transcribe_file`) enforces the tag check when
the flag is on — a flagged result is passed over for the next backend,
and if the chain exhausts it is returned degraded-but-marked
(`language_ok=False`) so the caller can surface it loudly instead of
silently trusting possibly-translated text.
"""

from __future__ import annotations

from assistant import asr
from assistant.asr import Transcript


class _Backend:
    def __init__(self, name: str, transcript: Transcript):
        self.name = name
        self._transcript = transcript
        self.calls = 0

    def transcribe(self, audio_path: str, language: str) -> Transcript:
        self.calls += 1
        return self._transcript


def _config(config, **asr_overrides):
    config.raw.setdefault("asr", {}).update(
        {"languages": ["en"], "assert_output_language": True, **asr_overrides})
    return config


def _drive(cfg, backends, monkeypatch):
    monkeypatch.setattr(asr, "batch_chain",
                        lambda *a, **k: list(backends))
    return asr.transcribe_file(cfg, client=None, audio_path="x.wav")


def test_out_of_set_language_prefers_next_backend(config, monkeypatch):
    cfg = _config(config)
    bad = _Backend("bad", Transcript("bonjour le monde", "fr", "bad"))
    good = _Backend("good", Transcript("hello world", "en", "good"))
    result = _drive(cfg, [bad, good], monkeypatch)
    assert result.backend == "good"
    assert result.language_ok is True


def test_out_of_set_language_only_backend_returns_marked(config, monkeypatch):
    cfg = _config(config)
    bad = _Backend("bad", Transcript("bonjour le monde", "fr", "bad"))
    result = _drive(cfg, [bad], monkeypatch)
    assert result.text == "bonjour le monde"   # degraded, not dropped
    assert result.language_ok is False          # but loudly marked


def test_flag_off_disables_the_assertion(config, monkeypatch):
    cfg = _config(config, assert_output_language=False)
    bad = _Backend("bad", Transcript("bonjour le monde", "fr", "bad"))
    good = _Backend("good", Transcript("hello world", "en", "good"))
    result = _drive(cfg, [bad, good], monkeypatch)
    assert result.backend == "bad"             # first result wins again
    assert good.calls == 0


def test_bilingual_tag_inside_the_pinned_set_passes(config, monkeypatch):
    cfg = _config(config, languages=["sw", "en"])
    both = _Backend("both", Transcript("sasa, file that invoice", "sw,en", "both"))
    result = _drive(cfg, [both], monkeypatch)
    assert result.language_ok is True
