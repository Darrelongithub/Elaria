"""A failed meeting transcription must still release the processing gate."""

from __future__ import annotations

import asyncio

import pytest

from assistant.daemon import Daemon
from assistant.modes import FORCED_OFFLINE


def test_bug_meeting_transcription_failure_restores_mode_and_unparks_switch(config):
    daemon = Daemon(config)

    class Dual:
        async def aclose(self):
            return None

    async def run():
        daemon._meeting = {
            "session_id": "failed-meeting",
            "dual": Dual(),
            "frames": {"mic": [b"\x11\x00" * 480],
                       "sys": [b"\x22\x00" * 480]},
            "task": asyncio.create_task(asyncio.sleep(60)),
        }
        daemon.mode_manager.request_preference("offline", active_session=True)

        def fail(*_args, **_kwargs):
            raise RuntimeError("synthetic ASR failure")

        daemon.meetings.transcribe_dual = fail
        try:
            with pytest.raises(RuntimeError, match="synthetic ASR failure"):
                await daemon._meeting_stop({"title": "failure case"})
            status = daemon.mode_manager.status(refresh=False)
            assert daemon.mode == "idle"
            assert not daemon._session_active()
            assert status.pending_preference is None
            assert status.effective_mode == FORCED_OFFLINE
        finally:
            await daemon.aclose()

    asyncio.run(run())
