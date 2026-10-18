"""Daemon + IPC + CLI end-to-end, no key, no network (Phase 0 done-when)."""

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from assistant.daemon import Daemon
from assistant.ipc import call, serve

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def running_daemon(config):
    import threading

    daemon = Daemon(config)
    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(serve(config.socket_path, daemon.handle))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield daemon, server
    loop.call_soon_threadsafe(server.close)
    loop.call_soon_threadsafe(loop.stop)


def test_socket_is_owner_only(config, running_daemon):
    assert config.socket_path.stat().st_mode & 0o777 == 0o600  # §3.1


def test_status_cost_ack_over_ipc(config, running_daemon):
    status = call(config.socket_path, "status")
    assert status["running"] and status["name"] == "Elaria"
    assert status["gemini_mode"] == "mock"

    started = time.monotonic()
    ack = call(config.socket_path, "ack")
    assert (time.monotonic() - started) * 1000 < 300  # §18 budget, incl. IPC
    assert ack["network"] is False

    cost = call(config.socket_path, "cost")
    assert cost["month"]["calls"] == 0  # ack made ZERO model calls (99% code)


def test_ask_flows_governor_then_harness(config, running_daemon):
    result = call(config.socket_path, "ask", {"text": "status of my chaos?"})
    assert result["mode"] == "mock"
    assert result["register"] in ("plain", "expressive-allowed")
    assert result["fixture"]["synthetic"] is True  # unrecorded => flagged synth
    cost = call(config.socket_path, "cost")
    assert cost["month"]["calls"] == 1  # and it was ledgered


def test_halt_and_resume(config, running_daemon):
    assert call(config.socket_path, "halt")["halted"] is True
    assert call(config.socket_path, "status")["halted"] is True
    assert call(config.socket_path, "resume")["halted"] is False


def test_ptt_acks_immediately(config, running_daemon):
    reply = call(config.socket_path, "ptt.start")
    assert reply["listening"] and reply["ack"] and reply["network"] is False


def test_unknown_method_is_an_error_not_a_crash(config, running_daemon):
    with pytest.raises(RuntimeError):
        call(config.socket_path, "plan.apply")  # Phase 4 — must refuse cleanly


# -- CLI as a subprocess: the Phase 0 definition of done ----------------------
def _cli(args, env_extra=None):
    import os
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"), **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "assistant.cli", *args],
                          check=False, capture_output=True, text=True, env=env, timeout=30)


def test_cli_doctor_reports_honest_facts():
    out = _cli(["doctor"])
    assert out.returncode == 0, out.stdout + out.stderr
    assert "UNVERIFIED" in out.stdout           # quota shape flagged (§11)
    assert "aistudio.google.com/rate-limit" in out.stdout
    assert "mock" in out.stdout                # no key => no network
    assert "hypr" in out.stdout.lower()        # version/syntax verdict present


def test_cli_doctor_json_is_machine_readable():
    out = _cli(["doctor", "--json"])
    report = json.loads(out.stdout)
    names = {c["check"] for c in report["checks"]}
    assert {"api key", "quota shape", "hyprland", "daemon"} <= names


def test_cli_cost_works_with_daemon_down():
    out = _cli(["cost"])
    assert out.returncode == 0
    assert "billed this month: $0.00" in out.stdout  # free tier, honestly


def test_cli_status_waybar_shape():
    out = _cli(["status", "--waybar"])
    payload = json.loads(out.stdout)
    assert {"text", "class", "tooltip"} <= payload.keys()
