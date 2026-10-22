"""I5 socket regressions: IPC claims must not mint owner authority.

These tests deliberately use the real Unix socket. Each red case supplies
forged authority-bearing fields and asserts the daemon refuses or contains
the resulting privilege escalation. Test-only fakes set up pending state and
model output; the IPC authorization and disclosure decisions remain real.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

import pytest

from assistant.ipc import call


class _FixedScorer:
    """I5 test-only scorer used to create a real pending wake-knock state."""

    name = "test-fixed-scorer"

    def __init__(self, score: float):
        self.score = score

    def available(self):
        return True

    def score_owner(self, pcm: bytes):
        return self.score


def _pending_wake_knock(daemon, *, trigger_score: float = 0.55) -> int:
    daemon.wake_guard.scorer = _FixedScorer(trigger_score)
    daemon.wake_guard.trigger(keyword_score=0.9)
    outcome = daemon.wake_guard.verify()
    assert outcome["state"] == "wake_knock"
    assert outcome["knock_id"] is not None
    return outcome["knock_id"]


def _activate_showoff_for_test(daemon) -> None:
    """I5 test setup: activate in-memory show-off without vulnerable IPC entry."""
    now = daemon.showoff._now()
    daemon.showoff._session = {
        "id": 987654,
        "started": now,
        "ends_at": now + timedelta(minutes=5),
        "command": "test-only active show-off",
    }
    daemon.showoff._guests = 0
    daemon.showoff._declined = 0


def test_bug_i5_principal_is_kernel_peer_not_request_json(
        config, running_daemon, monkeypatch):
    """I5: authenticated identity comes from the connected Unix peer."""
    daemon, _server = running_daemon
    observed = {}

    async def inspect_peer(_params):
        observed["principal"] = daemon._ipc_principal.get()
        observed["method"] = daemon._ipc_method.get()
        return {"pong": True}

    monkeypatch.setattr(daemon, "_ping", inspect_peer)
    result = call(config.socket_path, "ping", {
        "principal": {"uid": 0, "role": "root"},
        "uid": 0,
        "role": "owner",
    }, timeout=5.0)

    assert result["pong"] is True
    assert observed["method"] == "ping"
    assert observed["principal"].pid == os.getpid()
    assert observed["principal"].uid == os.getuid()
    assert observed["principal"].gid == os.getgid()


def test_bug_i5_ipc_method_context_stays_task_local_under_concurrent_sockets(
        config, running_daemon, monkeypatch):
    """I5: concurrent request methods cannot inherit each other's authority label."""
    daemon, _server = running_daemon

    async def inspect_method(_params):
        method = daemon._ipc_method.get()
        await asyncio.sleep(0.02)
        return {"request_method": method}

    monkeypatch.setattr(daemon, "_ask", inspect_method)
    with ThreadPoolExecutor(max_workers=2) as pool:
        ask_future = pool.submit(
            call, config.socket_path, "ask", {"text": "hello"}, timeout=5.0)
        console_future = pool.submit(
            call, config.socket_path, "console.say",
            {"text": "hello", "channel": "voice"}, timeout=5.0)
        ask_result = ask_future.result(timeout=6.0)
        console_result = console_future.result(timeout=6.0)

    assert ask_result["request_method"] == "ask"
    assert console_result["request_method"] == "console.say"
    assert console_result["channel"] == "console"


def test_bug_i5_nonowner_peer_cannot_change_state_even_with_owner_json(
        config, running_daemon, monkeypatch):
    """I5: a forged JSON principal cannot replace the kernel peer UID."""
    from assistant import daemon as daemon_module
    from assistant.ipc import IpcPrincipal

    daemon, _server = running_daemon
    before = daemon.presence.status().enabled
    foreign = IpcPrincipal(pid=os.getpid(), uid=os.getuid() + 1,
                           gid=os.getgid())
    monkeypatch.setattr(daemon_module, "ipc_peer_principal",
                        lambda _writer: foreign)

    with pytest.raises(RuntimeError, match="peer UID"):
        call(config.socket_path, "class.set", {
            "enabled": not before,
            "principal": {"uid": os.getuid(), "role": "owner"},
        }, timeout=5.0)

    assert daemon.presence.status().enabled is before


def test_bug_i5_knock_accept_rejects_forged_high_voiceprint_score(
        config, running_daemon):
    """I5: a caller-supplied high score must not open wake listening."""
    daemon, _server = running_daemon
    knock_id = _pending_wake_knock(daemon)

    with pytest.raises(RuntimeError, match="refused"):
        call(config.socket_path, "knock.accept", {
            "id": knock_id,
            "channel": "voice",
            "voiceprint_score": 0.99,
        }, timeout=5.0)

    assert daemon.wake_guard.state == "wake_knock"


def test_bug_i5_knock_accept_rejects_voice_unavailable_bypass(
        config, running_daemon):
    """I5: voice-unavailable plus a low score cannot bypass the voice gate."""
    daemon, _server = running_daemon
    knock_id = _pending_wake_knock(daemon)

    with pytest.raises(RuntimeError, match="refused"):
        call(config.socket_path, "knock.accept", {
            "id": knock_id,
            "channel": "voice_unavailable",
            "voiceprint_score": 0.01,
        }, timeout=5.0)

    assert daemon.wake_guard.state == "wake_knock"


def test_bug_i5_showoff_entry_rejects_copied_centroid_and_capture_flags(
        config, running_daemon, tmp_path):
    """I5: a copied enrolled centroid and caller flags are not a fresh capture."""
    from assistant.voicetest import voiceprint_path

    daemon, _server = running_daemon
    voiceprint = tmp_path / "copied-owner-centroid.json"
    voiceprint.write_text(
        '{"model":"test-model","dimension":2,"centroid":[1.0,0.0]}',
        encoding="utf-8")
    daemon.config.raw.setdefault("voice_test", {})["voiceprint_path"] = str(voiceprint)

    with pytest.raises(RuntimeError, match="capture"):
        call(config.socket_path, "showoff.enter", {
            "command": "Elaria, show off",
            "embedding": [1.0, 0.0],
            "owner_present": True,
            "source": "mic",
            "replayed": False,
            "live_mic": True,
            "audio_sha256": None,
        }, timeout=5.0)

    assert daemon.showoff.active() is False
    # Keep the import/path check in the regression so this reproducer cannot
    # accidentally exercise a different template location from the service.
    assert voiceprint_path(daemon.config) == voiceprint


def test_bug_i5_owner_verified_ipc_flag_cannot_bypass_showoff_guest_gate(
        config, running_daemon, monkeypatch):
    """I5: owner_verified=True is a caller claim, not speaker evidence."""
    daemon, _server = running_daemon
    _activate_showoff_for_test(daemon)
    owner_fact = "The owner keeps a blue bicycle in the garage."
    daemon.store.add_fact(ts="2026-10-21T09:00:00", kind="stated",
                          text=owner_fact)
    monkeypatch.setattr(daemon.memory, "recall",
                        lambda *_args, **_kwargs: [])
    generated = []

    async def return_owner_fact(*_args, **_kwargs):
        generated.append(True)
        return SimpleNamespace(text=owner_fact, model="test-model", fixture=None)

    monkeypatch.setattr(daemon, "_generate", return_owner_fact)
    result = call(config.socket_path, "ask", {
        "text": "What can you do?",
        "speaker": "owner",
        "owner_verified": True,
        "embedding": [1.0, 0.0],
        "channel": "console",
    }, timeout=5.0)

    assert generated == [True]
    assert result["channel"] == "voice"
    assert result["speaker"] == "guest"
    assert "blue bicycle" not in result["reply"]
    assert result["withheld"]["kind"] == "behaviour"


def test_bug_i1_i5_showoff_activated_during_generation_hits_final_guard(
        config, running_daemon, monkeypatch):
    """I1/I5: a show-off race before delivery still activates the final guard."""
    daemon, _server = running_daemon
    owner_fact = "The owner keeps a blue bicycle in the garage."
    daemon.store.add_fact(ts="2026-10-21T09:00:00", kind="stated",
                          text=owner_fact)
    monkeypatch.setattr(daemon.memory, "recall", lambda *_args, **_kwargs: [])

    async def online_connectivity(*_args, **_kwargs):
        return SimpleNamespace(is_offline=False, as_dict=lambda: {"mode": "online"})

    async def activate_then_return_owner_fact(*_args, **_kwargs):
        _activate_showoff_for_test(daemon)
        return SimpleNamespace(text=owner_fact, model="test-model", fixture=None)

    monkeypatch.setattr(daemon, "_connectivity_snapshot", online_connectivity)
    monkeypatch.setattr(daemon, "_generate", activate_then_return_owner_fact)
    result = call(config.socket_path, "console.say", {
        "text": "What can you do?",
        "speak": False,
    }, timeout=5.0)

    assert result["speaker"] == "owner"
    assert "blue bicycle" not in result["reply"]
    assert result["withheld"]["kind"] == "behaviour"
    assert result["withheld"]["why"] == "owner fact quoted to a guest"


def test_bug_i5_showoff_activated_during_owner_turn_uses_guest_prompt(
        config, running_daemon, monkeypatch):
    """I5: a show-off race during recall must switch the model prompt to guest scope."""
    daemon, _server = running_daemon
    owner_fact = "The owner keeps a blue bicycle in the garage."
    daemon.store.add_fact(ts="2026-10-21T09:00:00", kind="stated",
                          text=owner_fact)

    def activate_during_recall(*_args, **_kwargs):
        _activate_showoff_for_test(daemon)
        return []

    monkeypatch.setattr(daemon.memory, "recall", activate_during_recall)

    async def online_connectivity(*_args, **_kwargs):
        return SimpleNamespace(is_offline=False, as_dict=lambda: {"mode": "online"})

    prompts = []

    async def answer_from_prompt(prompt, **_kwargs):
        prompts.append(prompt)
        if "THE SPEAKER IS NOT THE OWNER" in prompt:
            reply = "Let's keep the owner's personal details private."
        else:
            reply = "The owner stores a bicycle in the garage."
        return SimpleNamespace(text=reply, model="test-model", fixture=None)

    monkeypatch.setattr(daemon, "_connectivity_snapshot", online_connectivity)
    monkeypatch.setattr(daemon, "_generate", answer_from_prompt)
    result = call(config.socket_path, "console.say", {
        "text": "What can you do?",
        "speak": False,
    }, timeout=5.0)

    assert "bicycle" not in result["reply"]
    assert "THE SPEAKER IS NOT THE OWNER" in prompts[0]
    assert result["withheld"] is None


def test_bug_i1_i5_showoff_owner_reply_still_runs_outgoing_secret_guard(
        config, running_daemon, monkeypatch):
    """I1/I5: a model secret is withheld even on show-off's owner console path."""
    daemon, _server = running_daemon
    _activate_showoff_for_test(daemon)
    secret = "The password is hunter2."
    daemon.store.add_fact(ts="2026-10-21T09:00:00", kind="stated", text=secret)
    monkeypatch.setattr(daemon.memory, "recall", lambda *_args, **_kwargs: [])

    async def return_secret(*_args, **_kwargs):
        return SimpleNamespace(text=secret, model="test-model", fixture=None)

    monkeypatch.setattr(daemon, "_generate", return_secret)

    async def online_connectivity(*_args, **_kwargs):
        return SimpleNamespace(is_offline=False)

    monkeypatch.setattr(daemon, "_connectivity_snapshot", online_connectivity)
    result = call(config.socket_path, "console.say", {
        "text": "What can you do?",
        "speak": False,
    }, timeout=5.0)

    assert "hunter2" not in result["reply"]
    assert result["withheld"] is not None
    assert result["withheld"]["kind"] == "secret"
