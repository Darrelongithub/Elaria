"""D-SAFETY — cleanup pass hygiene (§12.5).

The cleanup pass may repair a transcript, never rewrite it into a different
document. Raw is the record. These tests pin the gates that enforce it:
the diff-gate, the language (code-switch) gate, the mock-synthetic refusal,
and the cheap skips — all with a fake client, no network.
"""

from __future__ import annotations

from assistant.cleanup import (
    CLEANUP_PROMPT,
    CleanupPass,
    divergence_pct,
    language_mix_preserved,
)

RAW = ("sasa um so I went to the shop alafu I got the I crème fraîche "
       "because it was cheaper kwa sasa hivi sijui what else I needed but "
       "that is the story ya leo and nothing else happened at all")
assert len(RAW) > 40


class FakeResult:
    def __init__(self, text, *, model="fake-cleanup-model", fixture=None):
        self.text = text
        self.model = model
        self.fixture = fixture


class FakeClient:
    """Returns a scripted reply; records the verify callback it was handed."""

    def __init__(self, reply_text, *, fixture=None):
        self.reply_text = reply_text
        self.fixture = fixture
        self.calls = 0

    def generate(self, role, prompt, *, purpose, is_user_turn, verify=None):
        self.calls += 1
        return FakeResult(self.reply_text, fixture=self.fixture)


def make_pass(config, client, **overrides):
    config.raw["cleanup"] = {**config.raw["cleanup"], **overrides}
    return CleanupPass(config, client)


# -- the cheap pins --------------------------------------------------------------

def test_divergence_of_identical_text_is_zero():
    assert divergence_pct("hello world", "hello world") == 0.0
    assert divergence_pct("", "") == 0.0


def test_prompt_forbids_translation_and_rewriting():
    assert "Do NOT translate" in CLEANUP_PROMPT
    assert "Preserve the language" in CLEANUP_PROMPT


def test_language_gate_catches_normalization():
    translated = "hello um so I went to the shop and I got the cream because it was cheaper right now I do not know what else"
    assert language_mix_preserved(RAW, translated) is False


def test_language_gate_tolerates_partial_filler_drop():
    repaired = "sasa so I went to the shop alafu I got the crème fraîche because it was cheaper kwa sijui what else I needed"
    assert language_mix_preserved(RAW, repaired) is True


# -- pass behaviour ----------------------------------------------------------------

def test_rewrote_instead_of_repaired_is_flagged_and_raw_wins(config):
    # Keeps enough code-switch markers to pass the language gate but shares
    # almost nothing else with RAW — so the diff-gate (not the language
    # gate) is what fires.
    rewritten = ("sasa hivi leo sijui alafu I attended a completely unrelated "
                 "gathering miles away from any shop or market, a long poem of "
                 "elegance and repetition crafted entirely for effect, with no "
                 "connection to the words originally spoken")
    client = FakeClient(rewritten)
    result = make_pass(config, client).run(RAW)
    assert language_mix_preserved(RAW, rewritten) is True
    assert result.flagged is True
    assert "diff-gate" in result.reason
    assert result.cleaned == rewritten          # surfaced for review, never silently kept
    assert result.divergence_pct > 35


def test_translation_is_flagged_by_language_gate(config):
    translated = "hello so I went to the shop and got the cream because it was cheap right now I don't know what else I needed but that is today's story and nothing else"
    client = FakeClient(translated)
    result = make_pass(config, client).run(RAW)
    assert result.flagged is True
    assert "language gate" in result.reason


def test_mock_synthetic_is_not_dressed_up_as_a_cleanup(config):
    client = FakeClient("[mock-synthetic deadbeef] no fixture",
                        fixture={"key": "deadbeef", "synthetic": True})
    result = make_pass(config, client).run(RAW)
    assert result.cleaned is None and result.flagged is False
    assert "mock mode" in result.reason


def test_within_gates_returns_cleaned(config):
    repaired = RAW.replace("um ", "")
    client = FakeClient(repaired)
    result = make_pass(config, client).run(RAW)
    assert result.flagged is False
    assert result.cleaned == repaired


def test_below_min_chars_never_calls_the_model(config):
    client = FakeClient("should not be called at all")
    result = make_pass(config, client).run("tiny utterance")
    assert client.calls == 0
    assert result.cleaned is None
    assert "not worth a model call" in result.reason


def test_disabled_in_config_never_calls_the_model(config):
    client = FakeClient("should not be called")
    result = make_pass(config, client, enabled=False).run(RAW)
    assert client.calls == 0
    assert result.cleaned is None
    assert result.reason == "cleanup disabled in config"
