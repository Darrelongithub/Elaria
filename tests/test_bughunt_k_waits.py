"""BH-K5/K6/K8 — every wait must resolve: no unbounded joins, waits, polls.

K5: gemini_client._run_coroutine_sync ran the Live voice render with no
    timeout (both the asyncio.run branch and thread.join()). A wedged Live
    session occupied a worker thread forever; enough of them starve the
    shared to_thread executor the whole daemon relies on.
K6: PipeWireCapture.aclose awaited proc.wait() after SIGTERM with no kill
    escalation, and caller cancellation abandoned the wait — a pw-record
    that ignores SIGTERM (or a cancelled close) left a live microphone.
K8: `assist plan build` polled plan.show forever while a plan row stayed
    in "building" (the state a daemon restart mid-build leaves behind).
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from assistant import cli
from assistant.capture import PipeWireCapture
from assistant.gemini_client import _run_coroutine_sync

# ---------------------------------------------------------------------------
# BH-K5 — _run_coroutine_sync is bounded in both branches
# ---------------------------------------------------------------------------

async def _hangs_forever():
    await asyncio.Event().wait()
    return "unreachable"


async def _quick():
    return "done"


def test_run_coroutine_sync_no_loop_branch_times_out():
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        _run_coroutine_sync(_hangs_forever, timeout_s=0.2)
    assert time.monotonic() - started < 5, "the caller must unblock promptly"


def test_run_coroutine_sync_with_running_loop_branch_times_out():
    async def drive():
        # A loop is running here, so the private-thread branch is used.
        with pytest.raises(TimeoutError):
            _run_coroutine_sync(_hangs_forever, timeout_s=0.2)
        return True

    started = time.monotonic()
    assert asyncio.run(drive()) is True
    assert time.monotonic() - started < 5


def test_run_coroutine_sync_returns_value_when_fast():
    assert _run_coroutine_sync(_quick, timeout_s=5.0) == "done"

    async def drive():
        return _run_coroutine_sync(_quick, timeout_s=5.0)

    assert asyncio.run(drive()) == "done"


# ---------------------------------------------------------------------------
# BH-K6 — capture close escalates SIGTERM -> SIGKILL and survives cancel
# ---------------------------------------------------------------------------

class _StubbornProc:
    """Ignores SIGTERM; only SIGKILL ends it (a wedged pw-record)."""

    def __init__(self):
        self.returncode = None
        self.terminated = False
        self.killed = False
        self._dead = asyncio.Event()

    def terminate(self):
        self.terminated = True  # pointedly does NOT die

    def kill(self):
        self.killed = True
        self.returncode = -9
        self._dead.set()

    async def wait(self):
        await self._dead.wait()
        return self.returncode


def _capture_with(proc) -> PipeWireCapture:
    cap = object.__new__(PipeWireCapture)  # ctor needs pw-record; unit seam
    cap._proc = proc
    cap.TERMINATE_TIMEOUT_S = 0.05
    return cap


def test_aclose_escalates_to_kill_when_sigterm_is_ignored():
    proc = _StubbornProc()
    cap = _capture_with(proc)
    asyncio.run(asyncio.wait_for(cap.aclose(), timeout=5))
    assert proc.terminated and proc.killed
    assert cap._proc is None


def test_aclose_cancellation_still_kills_the_microphone():
    proc = _StubbornProc()
    cap = _capture_with(proc)
    cap.TERMINATE_TIMEOUT_S = 60.0  # cancellation lands long before timeout

    async def drive():
        task = asyncio.create_task(cap.aclose())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(drive())
    assert proc.killed, "a cancelled close must not leave a live capture process"


# ---------------------------------------------------------------------------
# BH-K8 — plan build polling has a total deadline
# ---------------------------------------------------------------------------

def test_plan_build_poll_gives_up_on_a_stuck_building_plan(monkeypatch, capsys):
    def fake_call(socket_path, method, params=None, timeout=None):
        if method == "plan.build":
            return {"started": [{"plan_id": 7, "root": "/does/not/matter"}]}
        if method == "plan.show":
            return {"plan": {"id": 7, "status": "building", "root": "/x",
                             "mode": "shadow", "shadow_log_path": None,
                             "stats_json": None, "error": None},
                    "items": []}
        raise AssertionError(f"unexpected call {method}")

    monkeypatch.setattr(cli, "call", fake_call)
    # Post-fix the deadline is a patchable constant; pre-fix it does not
    # exist and the loop below never returns (the thread stays alive).
    monkeypatch.setattr(cli, "_PLAN_BUILD_POLL_DEADLINE_S", 0.2, raising=False)

    box: dict = {}

    def run():
        box["rc"] = cli.main(["plan", "build"])

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive(), "plan build polling must be deadline-bounded"
    assert box["rc"] == 1
    assert "still 'building'" in capsys.readouterr().err
