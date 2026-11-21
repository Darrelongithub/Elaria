"""P · HANDS-HEADLESS — host lifecycle tests (gate order, env, daemon tie)."""

from __future__ import annotations

import stat
import subprocess
import time
from types import SimpleNamespace

import pytest

from assistant.hands.headless.contract import ALLOWED_VERBS
from assistant.hands.headless.host import (
    ALLOWED_ENV_KEYS,
    HeadlessConfig,
    HeadlessConfigError,
    HeadlessHost,
)
from assistant.hands.headless.instance import VersionGateError, sha256_of
from assistant.hands.headless.worker import RemoteRequest

PINNED_OUTPUT = "kitty 0.49.2 created by Kovid Goyal\n"
WRONG_OUTPUT = "kitty 0.48.0 created by Kovid Goyal\n"


def _fake_kitty(tmp_path, output: str):
    path = tmp_path / "kitty"
    path.write_text(f'#!/bin/sh\necho "{output.rstrip()}"\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _config(tmp_path, output: str = PINNED_OUTPUT, **overrides) -> HeadlessConfig:
    kitty = _fake_kitty(tmp_path, output)
    # Distinct name: the repo conftest pre-creates tmp_path/"runtime" as
    # XDG_RUNTIME_DIR for every test.
    values = {
        "allow_remote_control": True,
        "remote_control_password": "pw",
        "kitty_path": str(kitty),
        "python_path": "/usr/bin/python3",
        "kitty_sha256": sha256_of(kitty),
        "python_sha256": sha256_of("/usr/bin/python3"),
        "runtime_dir": str(tmp_path / "headless-runtime"),
    }
    values.update(overrides)
    return HeadlessConfig(**values)


def _spy_runner(calls: list) -> callable:
    def runner(argv, env, start_new_session):
        calls.append({"argv": argv, "env": env, "start_new_session": start_new_session})
        return SimpleNamespace(returncode=0, stdout="ok", stderr="", process=None)

    return runner


@pytest.mark.parametrize(
    "overrides",
    [
        {"allow_remote_control": False},
        {"remote_control_password": ""},
        {"shell_integration": True},
        {"allowed_verbs": ALLOWED_VERBS | {"screenshot"}},
        {"allowed_verbs": frozenset({"ls"})},
        {"extent_subset": frozenset({"viewport", "alternate"})},
    ],
)
def test_config_fails_closed_on_bad_values(tmp_path, overrides):
    with pytest.raises(HeadlessConfigError):
        _config(tmp_path, **overrides)


def test_start_gates_before_mkdir_on_wrong_version(tmp_path):
    host = HeadlessHost(_config(tmp_path, output=WRONG_OUTPUT))
    with pytest.raises(VersionGateError):
        host.start()
    assert not (tmp_path / "headless-runtime").exists()


def test_start_prepares_dirs_after_gate_passes(tmp_path):
    host = HeadlessHost(_config(tmp_path)).start()
    assert (tmp_path / "headless-runtime").is_dir()
    assert (tmp_path / "headless-runtime" / "logs").is_dir()
    host.stop()


def test_restricted_env_filters_everything_else(tmp_path):
    host = HeadlessHost(_config(tmp_path))
    base = {"PATH": "/usr/bin", "GITHUB_TOKEN": "sekret", "HOME": "/root", "LC_ALL": "en_US"}
    restricted = host.build_restricted_env(base)
    assert set(restricted) <= ALLOWED_ENV_KEYS
    assert "GITHUB_TOKEN" not in restricted
    assert "HOME" not in restricted
    assert restricted["LC_ALL"] == "C"


def test_request_uses_restricted_env_and_new_session(tmp_path):
    calls: list = []
    config = _config(tmp_path)
    host = HeadlessHost(config, runner=_spy_runner(calls)).start()
    result = host.request(RemoteRequest(verb="ls"))
    assert result.returncode == 0
    assert calls[0]["start_new_session"] is True
    assert set(calls[0]["env"]) <= ALLOWED_ENV_KEYS
    assert calls[0]["argv"][:2] == [config.kitty_path, "+rc"]
    host.stop()


def test_daemon_death_terminates_workers_and_journals(tmp_path):
    journal_rows: list = []

    class _J:
        def record(self, kind, **fields):
            journal_rows.append({"kind": kind, **fields})

    host = HeadlessHost(_config(tmp_path), journal=_J(), daemon_alive=lambda: False).start()
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        host.worker._live.append(proc)
        signalled = host.on_daemon_dead()
        assert signalled == 1
        proc.wait(timeout=5)  # SIGTERM delivery is async; reap before asserting
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    assert any(row.get("kind_detail") == "daemon.death" for row in journal_rows)
    host.stop()


def test_watcher_fires_when_daemon_dies(tmp_path):
    host = HeadlessHost(_config(tmp_path, daemon_pid=999999), daemon_alive=lambda: False).start()
    deadline = time.monotonic() + 2.0
    fired = False
    while time.monotonic() < deadline:
        if any(r.get("kind_detail") == "daemon.death" for r in host.journal.rows):
            fired = True
            break
        time.sleep(0.01)
    host.stop()
    assert fired


def test_stop_journals_process_count(tmp_path):
    host = HeadlessHost(_config(tmp_path)).start()
    host.stop()
    row = host.journal.rows[-1]
    assert row["kind_detail"] == "host.stop"
    assert row["processes_signalled"] == 0
