"""A total chat deadline must cancel live generation without leaving a worker."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from assistant.daemon import ChatTimeout, Daemon
from assistant.gemini_client import PerModelLimiter, _SdkTransport


class _CancellableTransport:
    def __init__(self):
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.sync_calls = 0

    def generate(self, *_args, **_kwargs):
        self.sync_calls += 1
        raise AssertionError("live chat must not use the synchronous transport")

    async def generate_async(self, _model, _contents, _config, *,
                             on_first_token=None, deadline=None):
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def test_bug_generate_total_timeout_cancels_async_transport(config):
    daemon = Daemon(config)
    transport = _CancellableTransport()
    daemon.client._transport = transport
    daemon._chat_first_token_s = 0.02
    daemon._chat_timeout_s = 0.08

    try:
        async def drive():
            with pytest.raises(ChatTimeout) as caught:
                await daemon._generate("a request whose backend never returns")
            assert caught.value.reason == "total"
            assert transport.started.is_set(), "the async backend was not entered"
            assert transport.cancelled.is_set(), "the async backend did not receive cancellation"
            assert transport.sync_calls == 0, "live generation used a synchronous worker"
            assert not daemon._background_tasks, (
                "_generate returned at its deadline but retained the cancelled task")

        asyncio.run(drive())
    finally:
        daemon.store.close()


def test_async_model_quota_wait_obeys_the_same_total_deadline():
    limiter = PerModelLimiter(lambda _model: 1)
    limiter.acquire("chat-model")
    started = time.monotonic()

    async def drive():
        with pytest.raises(TimeoutError, match="chat deadline"):
            await limiter.acquire_async(
                "chat-model", deadline=time.monotonic() + 0.02)

    asyncio.run(drive())
    assert time.monotonic() - started < 0.3


class _SuccessfulAsyncTransport:
    def generate(self, *_args, **_kwargs):
        raise AssertionError("async chat must not use the synchronous transport")

    async def generate_async(self, _model, _contents, _config, *,
                             on_first_token=None, deadline=None):
        if on_first_token is not None:
            on_first_token()
        return {"text": "Four", "usage": {"tokens_in": 3, "tokens_out": 1}}


def test_async_generation_delivers_reply_and_keeps_ledger_semantics(config):
    daemon = Daemon(config)
    daemon.client._transport = _SuccessfulAsyncTransport()
    daemon._chat_first_token_s = 0.2
    daemon._chat_timeout_s = 0.5

    try:
        result = asyncio.run(daemon._generate(
            "What is two plus two?", verify=lambda text: text == "Four"))
        assert result.text == "Four"
        assert result.verified is True
        row = daemon.store._conn.execute(
            "SELECT ok, verified, purpose, is_user_turn FROM llm_calls "
            "ORDER BY rowid DESC LIMIT 1").fetchone()
        assert tuple(row) == (1, 1, "user_turn", 1)
        assert not daemon._background_tasks
    finally:
        daemon.store.close()


def test_bug_sdk_async_stream_cancellation_closes_the_pending_iteration():
    class _Models:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()
            self.request_config = None

        async def generate_content_stream(self, *, model, contents, config):
            self.request_config = config

            async def chunks():
                self.started.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    self.cancelled.set()
                    raise
                yield SimpleNamespace(text="unreachable", usage_metadata=None)

            return chunks()

    async def drive():
        models = _Models()
        transport = object.__new__(_SdkTransport)
        transport._client = SimpleNamespace(
            aio=SimpleNamespace(models=models))
        config = {"temperature": 0.1}
        deadline = time.monotonic() + 1.0
        task = asyncio.create_task(transport.generate_async(
            "test-model", "prompt", config, deadline=deadline))
        try:
            await asyncio.wait_for(models.started.wait(), timeout=0.2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert models.cancelled.is_set()
            assert config == {"temperature": 0.1}, "request timeout mutated caller config"
            request_timeout = models.request_config["http_options"]["timeout"]
            assert 0 < request_timeout <= 1000
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(drive())
