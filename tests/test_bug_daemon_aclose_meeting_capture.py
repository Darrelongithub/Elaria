"""Daemon shutdown must close an active meeting capture and its collector."""

from __future__ import annotations

import asyncio

from assistant.daemon import Daemon


def test_bug_daemon_aclose_closes_active_meeting_capture_and_collector(config):
    daemon = Daemon(config)

    class Dual:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    async def run():
        dual = Dual()
        collecting = asyncio.Event()
        task = asyncio.create_task(_collect_forever(collecting))
        daemon._meeting = {
            "session_id": "shutdown-meeting",
            "dual": dual,
            "frames": {"mic": [], "sys": []},
            "task": task,
        }
        daemon.mode = "meeting"
        await collecting.wait()

        try:
            await daemon.aclose()
            failures = []
            if not dual.closed:
                failures.append("active dual capture was not closed")
            if not task.done():
                failures.append("meeting collector remained pending")
            if daemon._meeting is not None:
                failures.append("active meeting remained attached after shutdown")
            assert not failures, "; ".join(failures)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if not dual.closed:
                await dual.aclose()

    async def _collect_forever(started):
        started.set()
        await asyncio.Event().wait()

    asyncio.run(run())
