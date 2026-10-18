"""Fixture harness (§12.9) + reasoning harness escalation (§17)."""

import pytest

from assistant.fixtures import FixtureMiss, FixtureStore, fixture_key, synthetic_response
from assistant.gemini_client import GeminiClient, PerModelLimiter, RateLimitError
from assistant.store import Store


def test_fixture_key_is_stable_and_order_independent():
    a = fixture_key("m", {"x": 1, "y": 2})
    b = fixture_key("m", {"y": 2, "x": 1})
    assert a == b


def test_record_then_mock_replay_is_exact(tmp_path):
    store = FixtureStore(tmp_path)
    key = fixture_key("model-x", "hello")
    store.record(key, {"model": "model-x", "contents": "hello"},
                 {"text": "recorded!", "usage": {"tokens_in": 3, "tokens_out": 2}})
    replayed = store.replay(key, {"contents": "hello"})
    assert replayed["text"] == "recorded!"
    assert replayed["fixture"]["synthetic"] is False


def test_mock_miss_is_deterministic_and_flagged(tmp_path):
    store = FixtureStore(tmp_path)
    key = fixture_key("model-x", "unrecorded")
    first = store.replay(key, {"contents": "unrecorded"})
    second = store.replay(key, {"contents": "unrecorded"})
    assert first == second  # deterministic: same request, same reply, forever
    assert first["fixture"]["synthetic"] is True


def test_strict_mock_miss_raises(tmp_path):
    with pytest.raises(FixtureMiss):
        FixtureStore(tmp_path, strict=True).replay("nope", {})


def test_synthetic_never_pretends_to_be_model_output():
    assert "mock-synthetic" in synthetic_response("abc123", {"contents": "hi"})["text"]


def test_session_sequences_round_trip(tmp_path):
    store = FixtureStore(tmp_path)
    store.record_sequence("live-demo", [{"t": "interim"}, {"t": "final"}])
    assert store.replay_sequence("live-demo") == [{"t": "interim"}, {"t": "final"}]


class ScriptedTransport:
    """Returns queued answers; records which model each call used."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def generate(self, model, contents, config):
        self.calls.append(model)
        return {"text": self.answers.pop(0), "usage": {"tokens_in": 10, "tokens_out": 5}}


def _client(config, tmp_path, transport):
    return GeminiClient(config, Store(tmp_path / "t.db"), transport=transport,
                        sleep=lambda _: None)


def test_harness_uses_cheapest_model_when_unverified_work(config, tmp_path):
    client = _client(config, tmp_path, ScriptedTransport(["fine"]))
    result = client.generate("organise", "classify these")
    assert "lite" in result.model and result.attempts == 1 and not result.escalated


def test_escalates_only_on_verified_failure(config, tmp_path):
    # §17: two verified failures on Lite -> climb to Flash; ledger sees all.
    transport = ScriptedTransport(["bad", "bad", "good"])
    client = _client(config, tmp_path, transport)
    result = client.generate("organise", "do it right", verify=lambda t: t == "good")
    assert result.text == "good" and result.verified is True
    assert result.escalated and result.attempts == 3
    assert "lite" in transport.calls[0] and "lite" not in transport.calls[2]
    summary = client.store.llm_summary()
    assert summary["calls"] == 3  # a ledger row per attempt, no silent retries


def test_scaffold_cap_stops_thrift_theatre(config, tmp_path):
    transport = ScriptedTransport(["no"] * 50)
    client = _client(config, tmp_path, transport)
    result = client.generate("chat", "impossible", verify=lambda t: False)
    assert result.attempts == 6  # max_scaffold_calls from config
    assert result.verified is False


def test_every_mock_call_is_ledgered(config, tmp_path):
    client = _client(config, tmp_path, None) if False else GeminiClient(
        config, Store(tmp_path / "t.db"), sleep=lambda _: None)
    out = client.generate("chat", "hello Elaria")
    assert out.fixture and out.fixture["synthetic"] is True
    assert client.store.llm_summary()["calls"] == 1


def test_rate_limiter_blocks_beyond_rpm():
    limiter = PerModelLimiter(lambda model: 2)
    now = [1000.0]
    for _ in range(2):
        limiter.acquire("m", sleep=lambda s: None, now=lambda: now[0], max_wait_s=0.05)
    with pytest.raises(RateLimitError):
        limiter.acquire("m", sleep=lambda s: None, now=lambda: now[0], max_wait_s=0.05)
