"""A hostile infinite PTT wait must not outlive the caller indefinitely."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid

import pytest

from assistant.ipc import DaemonError, call


@pytest.mark.parametrize("method", ["ptt.result", "ptt.stop"])
@pytest.mark.parametrize("wait_s", [float("inf"), float("nan"), -1.0, 91.0])
def test_bug_ptt_invalid_wait_budget_is_rejected_before_orphaning_handler(
        config, running_daemon, method, wait_s):
    daemon, server = running_daemon
    loop = server.get_loop()
    session_id = f"infinite-{uuid.uuid4().hex}"
    entered_wait = threading.Event()
    wait_finished = threading.Event()
    original_wait = daemon._ptt_wait_for

    async def tracked_wait(requested_id, wait_s):
        entered_wait.set()
        try:
            return await original_wait(requested_id, wait_s)
        finally:
            wait_finished.set()

    daemon._ptt_wait_for = tracked_wait

    async def prepare_session():
        daemon._ptt_session_id = session_id
        daemon._ptt_last_session_id = session_id
        daemon._ptt_finishing.add(session_id)
        daemon._ptt_released_at = time.monotonic()
        daemon._ptt_event_for(session_id)

    asyncio.run_coroutine_threadsafe(prepare_session(), loop).result(timeout=1)
    try:
        with pytest.raises(DaemonError, match="wait_s"):
            params = {"wait_s": wait_s}
            if method == "ptt.result":
                params["session_id"] = session_id
            call(config.socket_path, method, params, timeout=1.0)
        assert not entered_wait.is_set(), (
            "the daemon entered an unbounded wait instead of refusing Infinity")
    finally:
        async def clean_session():
            if entered_wait.is_set():
                daemon._ptt_mark_terminal(session_id, {
                    "session_id": session_id, "terminal": True, "text": ""})
                await asyncio.sleep(0.02)
            else:
                daemon._ptt_finishing.discard(session_id)
                daemon._ptt_result_events.pop(session_id, None)
            await asyncio.sleep(0.05)

        asyncio.run_coroutine_threadsafe(clean_session(), loop).result(timeout=1)
        if entered_wait.is_set():
            assert wait_finished.wait(1), (
                "test cleanup failed to release the orphaned handler")
