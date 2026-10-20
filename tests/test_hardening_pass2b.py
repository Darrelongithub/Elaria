"""Second-batch pins: guest history, loop survival, daemon lock, CLI honesty.

Written before the fixes; every test here failed on `25179c8` (see the
pre-fix notes on each one). All state lives in the pytest sandbox.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import subprocess
import sys
from pathlib import Path

import pytest

from assistant.cli import _forget_message, _refusal_text
from assistant.daemon import Daemon


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# BH-J1 — guest speech was written into the OWNER's conversation record
# --------------------------------------------------------------------------


def test_non_owner_voice_never_enters_owner_conversation(config):
    daemon = Daemon(config)
    try:
        out = _run(daemon._guest_turn_normal("what is your name?", {"speak": False}))
        assert out["speaker"] == "guest"
        assert out["conversation_id"] is None
        assert daemon.sessions.history()["messages"] == []
        assert daemon.store.latest_conversation() is None, (
            "a guest utterance must not create or extend the owner's conversation")
    finally:
        daemon.store.close()


def test_showoff_guest_turn_never_enters_owner_conversation(config, monkeypatch):
    import types

    daemon = Daemon(config)
    try:
        monkeypatch.setattr(daemon.showoff, "guest_turn",
                            lambda text: {"allowed": True})
        monkeypatch.setattr(daemon.showoff, "build_guest_prompt",
                            lambda text: "demo prompt")

        async def offline():
            return types.SimpleNamespace(is_offline=True)

        monkeypatch.setattr(daemon, "_connectivity_snapshot", offline)
        out = _run(daemon._guest_turn("what can you do?", {"speak": False},
                                      {"active": True}))
        assert out["speaker"] == "guest"
        assert out["conversation_id"] is None
        assert daemon.sessions.history()["messages"] == []
        assert daemon.store.latest_conversation() is None
    finally:
        daemon.store.close()


# --------------------------------------------------------------------------
# BH-J2 — one connectivity error killed the background loop for good
# --------------------------------------------------------------------------


def test_connectivity_loop_survives_a_failing_tick(config, monkeypatch):
    daemon = Daemon(config)
    config.raw["connectivity"]["health_check_interval_s"] = 0.01  # clamped to 1 s
    calls = {"n": 0}

    class Flaky:
        def refresh(self, force: bool = False):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("socket probe blew up")
            return daemon.mode_manager.status(refresh=False)

    monkeypatch.setattr(daemon, "mode_manager", Flaky())

    async def run():
        task = asyncio.create_task(daemon._connectivity_loop())
        await asyncio.sleep(2.2)          # two 1 s ticks; the first raises
        alive = not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return alive

    try:
        assert _run(run()) is True, (
            "the connectivity loop died on the first probe error")
        assert calls["n"] >= 2, "the loop did not retry after a failed tick"
    finally:
        daemon.store.close()


# --------------------------------------------------------------------------
# BH-J3 — a second `assistd` printed a traceback instead of one clear line
# --------------------------------------------------------------------------


def test_second_daemon_exits_cleanly_with_one_line(config, tmp_path):
    lock_path = config.socket_path.with_suffix(".sock.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        env = dict(os.environ)
        src = str(Path(__file__).resolve().parents[1] / "src")
        env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run([sys.executable, "-m", "assistant.daemon"],
                              capture_output=True, text=True, timeout=20, env=env,
                              check=False)
    assert proc.returncode == 1, proc.stderr
    assert "already running" in proc.stderr
    assert "Traceback" not in proc.stderr


# --------------------------------------------------------------------------
# BH-J4 — `assist forget <topic>` claimed "No argument, as designed."
# --------------------------------------------------------------------------


def test_forget_message_names_the_topic_it_searched():
    assert _forget_message("tax", 0) == (
        "Forgotten: 0 fact(s) matching 'tax'. No active fact matched.")
    assert _forget_message("tax", 2) == (
        "Forgotten: 2 fact(s) matching 'tax'.")


# --------------------------------------------------------------------------
# BH-J5 — daemon refusals printed "refused: refused: …"
# --------------------------------------------------------------------------


def test_refusal_text_does_not_double_the_prefix():
    assert _refusal_text(ValueError("no knock #99")) == "refused: no knock #99"
    assert _refusal_text(ValueError("refused: a reason must be citable")) == (
        "refused: a reason must be citable")
