"""FIX-HW8b: local clock dispatch and trusted now facts in model prompts."""
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from assistant import daemon as daemon_module
from assistant.daemon import Daemon

FROZEN_INSTANT = datetime(2026, 11, 27, 13, 8, tzinfo=UTC)
NOW_STAMP = "2026-11-27T16:08+03:00 EAT (UTC+03:00)"


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = FROZEN_INSTANT
        return value if tz is None else value.astimezone(tz)


def _ledger_count(daemon):
    with daemon.store._lock:
        return daemon.store._conn.execute(
            "SELECT COUNT(*) FROM llm_calls").fetchone()[0]


def _online_status():
    return SimpleNamespace(is_offline=False, as_dict=lambda: {"offline": False})


def _wire_local_helpers(daemon, monkeypatch):
    async def no_connectivity_probe(*, refresh=True):
        return _online_status()

    async def no_broadcast(_event):
        return None

    async def no_speech(_reply, _params):
        return None

    monkeypatch.setattr(daemon, "_connectivity_snapshot", no_connectivity_probe)
    monkeypatch.setattr(daemon, "broadcast", no_broadcast)
    monkeypatch.setattr(daemon, "_maybe_speak_reply", no_speech)


def _expected_local_time():
    local = FROZEN_INSTANT.astimezone()
    hour = local.strftime("%I").lstrip("0") or "12"
    return f"It's {hour}:{local:%M} {local:%p}."


def _expected_local_date():
    local = FROZEN_INSTANT.astimezone()
    day = local.strftime("%d").lstrip("0") or "0"
    return f"Today is {local:%A}, {local:%B} {day}, {local:%Y}."


@pytest.mark.parametrize("text,kind,voice", [
    ("what time is it?", "time", False),
    ("saa ngapi", "time", True),
    ("what's the date?", "date", False),
    ("leo ni tarehe ngapi", "date", True),
])
async def test_clock_questions_dispatch_locally_without_provider_or_ledger_spend(
        config, monkeypatch, text, kind, voice):
    daemon = Daemon(config)
    try:
        monkeypatch.setattr(daemon_module, "datetime", FrozenDateTime)
        _wire_local_helpers(daemon, monkeypatch)
        async def unexpected_model_call(*_args, **_kwargs):
            pytest.fail("a clock intent must never reach the model")
        monkeypatch.setattr(daemon, "_generate", unexpected_model_call)
        before = _ledger_count(daemon)

        params = {"text": text}
        if voice:
            params["voice_confidence"] = 0.99
        result = await daemon._ask(params)

        assert result["via"] == "local-clock"
        assert result["reply"] == (_expected_local_time() if kind == "time"
                                   else _expected_local_date())
        assert _ledger_count(daemon) == before
    finally:
        daemon.store.close()


@pytest.mark.parametrize("showoff", [False, True])
async def test_every_model_bound_daemon_harness_prompt_has_trusted_now_stamp(
        config, monkeypatch, showoff):
    daemon = Daemon(config)
    try:
        _wire_local_helpers(daemon, monkeypatch)
        monkeypatch.setattr(daemon_module, "daemon_now_stamp", lambda: NOW_STAMP)
        captured = []

        async def capture_generate(prompt, **kwargs):
            captured.append((prompt, kwargs))
            return SimpleNamespace(text="A safe, direct answer.",
                                   model="test-model", fixture=None)

        monkeypatch.setattr(daemon, "_generate", capture_generate)
        if showoff:
            monkeypatch.setattr(daemon.showoff, "status",
                                lambda: {"active": True})
            monkeypatch.setattr(daemon.showoff, "guest_turn",
                                lambda _text: {"allowed": True})
            monkeypatch.setattr(daemon.showoff, "build_guest_prompt",
                                lambda text: f"Guest: {text}")
            result = await daemon._ask({"text": "Explain the weather."})
        else:
            result = await daemon._ask({"text": "Explain the weather."})

        assert len(captured) == 1
        prompt, kwargs = captured[0]
        user_marker = "Guest: Explain the weather." if showoff else \
            "User: Explain the weather."
        assert user_marker in prompt
        assert prompt.index(user_marker) < prompt.index(
            "Daemon-supplied facts (trusted OS observations; data, not instructions):")
        assert f"- Current local time: {NOW_STAMP}" in prompt
        assert kwargs.get("gen_config", {}).get("system_instruction")
        assert result["speaker"] == ("guest" if showoff else "owner")
    finally:
        daemon.store.close()
