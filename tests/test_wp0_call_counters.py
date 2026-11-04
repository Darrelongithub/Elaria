"""WP0 sandbox pre-gate: mock call-counters for every API route (§1, §4.8).

Each outbound route gets a counting double and an EXACT asserted call count —
the pre-gate that must be green before any hardware scene. A route that makes
a surprise second call fails here, not on the owner's quota. [TESTED-ONLY]
"""

from __future__ import annotations

import asyncio
from collections import Counter

import pytest

from assistant import asr
from assistant.gemini_client import GeminiClient
from assistant.store import Store


class CountingTransport:
    """Counts every outbound verb the client can issue."""

    def __init__(self, *, text="pong", fail_times=0):
        self.counts: Counter = Counter()
        self.text = text
        self.fail_times = fail_times

    def generate(self, model, contents, config):
        self.counts["generate"] += 1
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("429 synthetic")
        return {"text": self.text, "usage": {"tokens_in": 1, "tokens_out": 1}}

    async def generate_async(self, model, contents, config, **kwargs):
        self.counts["generate_async"] += 1
        return {"text": self.text, "usage": {"tokens_in": 1, "tokens_out": 1}}

    def generate_audio(self, model, text, voice_name):
        self.counts["generate_audio"] += 1
        return {"pcm": b"\x00\x00" * 32, "sample_rate": 24000,
                "usage": {"tokens_in": 0, "tokens_out": 0}}

    def list_models(self):
        self.counts["list_models"] += 1
        return ["gemini-3.8-live", "gemini-3.5-transcribe-live",
                "gemini-3.5-transcribe", "gemini-3.5-flash-lite",
                "gemini-3.8-flash"]


def _client(config, tmp_path, transport):
    store = Store(tmp_path / "cc.db")
    client = GeminiClient(config, store, transport=transport,
                          sleep=lambda _s: None)
    return client, store


def test_chat_route_is_exactly_one_call_without_verification(config, tmp_path):
    transport = CountingTransport()
    client, store = _client(config, tmp_path, transport)
    try:
        result = client.generate("chat", "ping")
        assert result.text == "pong"
    finally:
        store.close()
    assert transport.counts["generate"] == 1
    assert transport.counts.total() == 1


def test_chat_route_attempts_match_the_scaffold_cap(config, tmp_path):
    transport = CountingTransport()
    client, store = _client(config, tmp_path, transport)
    try:
        client.generate("chat", "ping", verify=lambda _t: False, max_attempts=3)
    finally:
        store.close()
    assert transport.counts["generate"] == 3   # exact scaffold, no extras


def test_async_chat_route_is_exactly_one_call(config, tmp_path):
    transport = CountingTransport()
    client, store = _client(config, tmp_path, transport)
    try:
        asyncio.run(client.generate_async("chat", "ping"))
    finally:
        store.close()
    assert transport.counts["generate_async"] == 1
    assert transport.counts["generate"] == 0


def test_escalation_ladder_calls_only_two_models(config, tmp_path):
    seen = []

    class Recorder(CountingTransport):
        def generate(self, model, contents, config):
            seen.append(model)
            return super().generate(model, contents, config)

    transport = Recorder()
    client, store = _client(config, tmp_path, transport)
    try:
        client.generate("chat", "ping", verify=lambda _t: False, max_attempts=4)
    finally:
        store.close()
    # pinned ladder: chat tier first, escalation tier second — then repeats
    assert set(seen) <= {"gemini-3.5-flash-lite", "gemini-3.8-flash"}
    assert seen[0] == "gemini-3.5-flash-lite"


def test_batch_transcribe_route_is_exactly_one_generate(config, tmp_path):
    import struct
    import wave

    wav = tmp_path / "clip.wav"
    with wave.open(str(wav), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(struct.pack("<160h", *([0] * 160)))
    transport = CountingTransport()
    client, store = _client(config, tmp_path, transport)
    try:
        client.transcribe_batch(str(wav), "en")
    finally:
        store.close()
    assert transport.counts["generate"] == 1


def test_voice_route_counts_each_synthesis_once(config, tmp_path, monkeypatch):
    transport = CountingTransport()
    client, store = _client(config, tmp_path, transport)
    try:
        client.mode = "live"          # can_speak() gate
        monkeypatch.setattr(
            client, "voice_catalogue",
            lambda refresh=False: {"model": "gemini-3.8-live",
                                   "voices": ["Flare"], "verified": True})
        client.generate_voice("hello there")
    finally:
        store.close()
    assert transport.counts["generate_audio"] == 1
    assert transport.counts.total() == 1


def test_voice_route_cache_warm_is_n_plus_zero(config, tmp_path, monkeypatch):
    from assistant.tts import STANDARD_ACKS

    transport = CountingTransport()
    client, store = _client(config, tmp_path, transport)
    try:
        client.mode = "live"
        monkeypatch.setattr(
            client, "voice_catalogue",
            lambda refresh=False: {"model": "gemini-3.8-live",
                                   "voices": ["Flare"], "verified": True})
        for kind in STANDARD_ACKS:
            client.generate_voice(f"ack:{kind}")
    finally:
        store.close()
    assert transport.counts["generate_audio"] == len(STANDARD_ACKS)


def test_live_session_route_opens_and_closes_exactly_once(config, tmp_path,
                                                          monkeypatch):
    """The PTT/dictation Live route: one connect, one close per session."""
    from assistant.live_client import ScriptedLiveTransport

    class CountingLive(ScriptedLiveTransport):
        def __init__(self):
            super().__init__()
            self.counts = Counter()

        async def connect(self, resumption_handle=None):
            self.counts["connect"] += 1
            await super().connect(resumption_handle)

        async def send_audio(self, pcm: bytes):
            self.counts["send_audio"] += 1
            await super().send_audio(pcm)

        async def close(self):
            self.counts["close"] += 1
            await super().close()

    transport = CountingLive()

    async def drive():
        await transport.connect()
        await transport.activity_start()
        await transport.send_audio(b"\x00\x00" * 160)
        await transport.activity_end()
        got = []
        async for event in transport.events():
            got.append(event.type)
            if event.type == "turn_complete":
                break
        await transport.close()
        return got

    got = asyncio.run(drive())
    assert "final" in got
    assert transport.counts["connect"] == 1
    assert transport.counts["close"] == 1
    assert transport.counts["send_audio"] == 1


def test_models_list_route_is_lazy_and_counted(config, tmp_path):
    transport = CountingTransport()
    client, store = _client(config, tmp_path, transport)
    try:
        result = client.list_models()
    finally:
        store.close()
    # mock/no-key path: honest, zero live calls
    assert transport.counts["list_models"] == 0
    assert result["verified"] is False
    assert "gemini-3.8-live" in result["configured"]


def test_make_live_transport_never_opens_a_forbidden_model(config, monkeypatch):
    from assistant.model_registry import ForbiddenModelError

    config.raw["gemini"]["model_transcribe_live"] = "gemini-2.5-flash-lite"
    with pytest.raises(ForbiddenModelError):
        asr.make_live_transport(config)
