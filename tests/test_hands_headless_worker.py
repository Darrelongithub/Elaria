"""P · HANDS-HEADLESS — worker remote-control surface tests."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from assistant.hands.headless.consent import ConsentFlow, Denied, InMemoryJournal
from assistant.hands.headless.contract import ContractViolationError, WorkerContract
from assistant.hands.headless.worker import RemoteRequest, Worker


class _DenyAll:
    def check(self, action):
        raise Denied("policy denies this verb")


def _worker(journal=None, runner=None, policy=None):
    journal = journal or InMemoryJournal()
    runner = runner or (
        lambda argv, env, start_new_session: SimpleNamespace(
            returncode=0, stdout="out", stderr="", process=None
        )
    )
    flow = ConsentFlow(journal, policy=policy)
    return Worker(
        contract=WorkerContract(),
        journal=journal,
        kitty_path="/usr/bin/kitty",
        env={"PATH": "/usr/bin"},
        runner=runner,
        consent_flow=flow,
    )


def test_build_argv_shapes_for_the_three_verbs():
    worker = _worker()
    assert worker.build_argv(RemoteRequest(verb="ls")) == ["/usr/bin/kitty", "+rc", "ls"]
    assert worker.build_argv(RemoteRequest(verb="get-text", options={"extent": "viewport"})) == [
        "/usr/bin/kitty",
        "+rc",
        "get-text",
        "--extent",
        "viewport",
    ]
    assert worker.build_argv(RemoteRequest(verb="send-text", payload="hello")) == [
        "/usr/bin/kitty",
        "+rc",
        "send-text",
        "--text",
        "hello",
    ]


def test_disallowed_verb_refused_before_runner_called():
    calls = []
    worker = _worker(runner=lambda argv, env, s: calls.append(argv) or None)
    with pytest.raises(ContractViolationError):
        worker.execute(RemoteRequest(verb="screenshot"))
    assert calls == []


def test_execute_journals_action_and_observation():
    journal = InMemoryJournal()
    result = SimpleNamespace(returncode=0, stdout="window list", stderr="", process=None)
    worker = _worker(journal=journal, runner=lambda argv, env, s: result)
    out = worker.execute(RemoteRequest(verb="ls"))
    assert out is result
    assert journal.kinds() == ["action", "observation"]
    assert journal.rows[0]["verb"] == "ls"
    assert journal.rows[1]["returncode"] == 0
    assert journal.rows[1]["stdout_bytes"] == len("window list")


def test_denied_request_never_executes():
    journal = InMemoryJournal()
    calls = []
    worker = _worker(
        journal=journal,
        runner=lambda argv, env, s: calls.append(argv),
        policy=_DenyAll(),
    )
    with pytest.raises(Denied):
        worker.execute(RemoteRequest(verb="send-text", payload="hi"))
    assert calls == []
    assert journal.kinds() == ["denial"]


def test_terminate_all_signals_tracked_process_groups():
    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        worker = _worker()
        worker._live.append(proc)
        signalled = worker.terminate_all()
        assert signalled == 1
        proc.wait(timeout=5)  # SIGTERM delivery is async; reap before asserting
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def test_terminate_all_tolerates_already_dead_processes():
    worker = _worker()
    dead = subprocess.Popen(["true"])
    dead.wait()
    worker._live.append(dead)
    assert worker.terminate_all() == 0
    assert worker._live == []
