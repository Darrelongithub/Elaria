"""P · HANDS-HEADLESS — worker remote-control surface tests.

BUG-B3 (2026-11-26): the terminate tests below drive the REAL ``execute()``
path — a runner (or ``default_runner``) that spawns a process and reports it
through the spawn hook — so they fail if tracking happens only after exit.
They never hand-append to the worker's tracker: doing so is what masked BUG-B3.
"""

from __future__ import annotations

import os
import stat
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from assistant.hands.headless.consent import ConsentFlow, Denied, InMemoryJournal
from assistant.hands.headless.contract import ContractViolationError, WorkerContract
from assistant.hands.headless.worker import RemoteRequest, Worker

_SCRIPT_ENV = {"PATH": os.defpath + ":/bin:/usr/bin"}


class _DenyAll:
    def check(self, action):
        raise Denied("policy denies this verb")


def _worker(journal=None, runner=None, policy=None):
    journal = journal or InMemoryJournal()
    runner = runner or (
        lambda argv, env, start_new_session, on_spawn: SimpleNamespace(
            returncode=0, stdout="out", stderr="", process=None
        )
    )
    flow = ConsentFlow(journal, policy=policy)
    return Worker(
        contract=WorkerContract(),
        journal=journal,
        kitty_path="/usr/bin/kitty",
        env=_SCRIPT_ENV,
        runner=runner,
        consent_flow=flow,
    )


def _script(tmp_path, body: str) -> str:
    path = tmp_path / "kitty"
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def _real_worker(tmp_path, body: str) -> Worker:
    """A worker wired to ``default_runner`` — the code path BUG-B3 lives in."""
    return Worker(
        contract=WorkerContract(),
        journal=InMemoryJournal(),
        kitty_path=_script(tmp_path, body),
        env=_SCRIPT_ENV,
    )


def _tracked(worker: Worker) -> list[object]:
    """What the worker currently tracks as live.

    Falls back to the legacy ``_live`` list so this measures the defect and not
    the absence of the new accessor: before BUG-B3 was fixed that list is empty
    mid-run and holds the finished ``Popen`` afterwards.
    """
    accessor = getattr(worker, "live_processes", None)
    if callable(accessor):
        return accessor()
    return list(getattr(worker, "_live", []))


def _wait_for_tracked(worker: Worker, count: int, timeout: float = 5.0) -> list[object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tracked = _tracked(worker)
        if len(tracked) >= count:
            return tracked
        time.sleep(0.01)
    return _tracked(worker)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run_in_thread(fn, *args):
    """Run ``fn`` in a thread, surfacing any exception back to the test."""
    outcome: dict = {}

    def target():
        try:
            outcome["value"] = fn(*args)
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, outcome


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
    worker = _worker(
        runner=lambda argv, env, start_new_session, on_spawn: calls.append(argv) or None
    )
    with pytest.raises(ContractViolationError):
        worker.execute(RemoteRequest(verb="screenshot"))
    assert calls == []


def test_execute_journals_action_and_observation():
    journal = InMemoryJournal()
    result = SimpleNamespace(returncode=0, stdout="window list", stderr="", process=None)
    worker = _worker(journal=journal, runner=lambda argv, env, s, on_spawn: result)
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
        runner=lambda argv, env, s, on_spawn: calls.append(argv),
        policy=_DenyAll(),
    )
    with pytest.raises(Denied):
        worker.execute(RemoteRequest(verb="send-text", payload="hi"))
    assert calls == []
    assert journal.kinds() == ["denial"]


def test_bug_b3_in_flight_process_is_tracked_and_terminated(tmp_path):
    """BUG-B3 failure 1: a worker alive mid-command must be signalled."""
    worker = _real_worker(tmp_path, "#!/bin/sh\nexec sleep 30\n")
    thread, outcome = _run_in_thread(worker.execute, RemoteRequest(verb="ls"))
    try:
        tracked = _wait_for_tracked(worker, 1)
        assert len(tracked) == 1, "execute() must track the process while it is still running"
        pid = tracked[0].pid
        assert _pid_exists(pid)

        assert worker.terminate_all() == 1
    finally:
        thread.join(timeout=10)

    assert not thread.is_alive()
    assert "error" not in outcome, outcome
    assert outcome["value"].returncode == -15  # SIGTERM, not a completed run
    assert _tracked(worker) == []
    assert worker.terminate_all() == 0
    assert not _pid_exists(pid)


def test_bug_b3_finished_process_is_pruned_after_execute(tmp_path):
    """BUG-B3 failure 2 (I10): no finished Popen may be retained."""
    worker = _real_worker(tmp_path, "#!/bin/sh\necho ok\n")
    result = worker.execute(RemoteRequest(verb="ls"))
    assert result.returncode == 0
    assert _tracked(worker) == [], "a finished process must be pruned from the tracker"
    assert worker.terminate_all() == 0


def test_bug_b3_terminate_all_does_not_signal_a_reaped_pid():
    """BUG-B3 failure 2: a process object that reports exit is never signalled.

    The object's ``pid`` belongs to an unrelated live process; the pre-fix
    code ``killpg``-ed it anyway because the only guard was ``pid is None``.
    """
    bystander = subprocess.Popen(["sleep", "30"], start_new_session=True)

    class _ReapedButLivePid:
        pid = bystander.pid

        def poll(self):
            return 0  # already reaped: this PID may have been recycled

    def runner(argv, env, start_new_session, on_spawn=None):
        proc = _ReapedButLivePid()
        if on_spawn is not None:
            on_spawn(proc)
        return SimpleNamespace(returncode=0, stdout="", stderr="", process=proc)

    try:
        worker = _worker(runner=runner)
        worker.execute(RemoteRequest(verb="ls"))
        assert worker.terminate_all() == 0
        assert bystander.poll() is None, "terminate_all signalled a PID that had proved nothing"
    finally:
        if bystander.poll() is None:
            bystander.kill()
        bystander.wait()


def test_bug_b3_terminate_all_skips_tracked_process_that_reports_exit():
    """Liveness is re-proven at terminate time, not assumed from tracking."""
    bystander = subprocess.Popen(["sleep", "30"], start_new_session=True)

    class _ReapedButLivePid:
        pid = bystander.pid

        def poll(self):
            return 0

    release = threading.Event()

    def runner(argv, env, start_new_session, on_spawn=None):
        proc = _ReapedButLivePid()
        if on_spawn is not None:
            on_spawn(proc)
        release.wait(5)
        return SimpleNamespace(returncode=0, stdout="", stderr="", process=proc)

    worker = _worker(runner=runner)
    thread, outcome = _run_in_thread(worker.execute, RemoteRequest(verb="ls"))
    try:
        assert len(_wait_for_tracked(worker, 1)) == 1
        assert worker.terminate_all() == 0
        assert bystander.poll() is None
    finally:
        release.set()
        thread.join(timeout=5)
        if bystander.poll() is None:
            bystander.kill()
        bystander.wait()

    assert not thread.is_alive()
    assert "error" not in outcome, outcome
    assert _tracked(worker) == []


def test_bug_b3_terminate_all_is_idempotent_with_no_processes():
    worker = _worker()
    assert _tracked(worker) == []
    assert worker.terminate_all() == 0
    assert worker.terminate_all() == 0
