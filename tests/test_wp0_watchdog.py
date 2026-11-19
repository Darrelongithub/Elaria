"""WP0 EYES: the 5-minute session watchdog (§4.2) — [TESTED-ONLY].

A missed release bind once held the owner's mic about nine minutes. The
watchdog auto-closes a PTT/live session past the ceiling with a visible
marker in three places: the stdout schema line, the store journal, and
`assist status` (`last_watchdog_close`). GoAway closes gracefully plus a
marker (emission covered in test_wp0_journal_schema / transcribe tests).
"""

from __future__ import annotations

import asyncio
import json
import time

from assistant.capture import SimulatedCapture
from assistant.daemon import Daemon


class _HoldOpenCapture(SimulatedCapture):
    """A capture that keeps the session's feet (frames flow, mic is held)."""

    def __init__(self, target=None, frame_ms=30, stall_timeout_s=None, **kwargs):
        super().__init__(speech_frames=100_000, frame_ms=frame_ms, realtime=True)


def _daemon_with_session(config, monkeypatch):
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _HoldOpenCapture)
    daemon = Daemon(config)

    async def start():
        started = await daemon._ptt_start({})
        assert started["listening"] is True

    asyncio.run(start())
    return daemon


def _run(coro):
    """One loop per scenario: the session task lives in THIS loop only."""
    return asyncio.run(coro)


def test_watchdog_quiet_below_the_ceiling(config, monkeypatch):
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _HoldOpenCapture)
    daemon = Daemon(config)
    try:
        async def drive():
            started = await daemon._ptt_start({})
            assert started["listening"] is True
            return await daemon._watchdog_tick()

        closed = asyncio.run(drive())
        assert closed is False
        assert daemon._last_watchdog_close is None
    finally:
        daemon.store.close()


def test_watchdog_closes_a_session_past_the_ceiling(config, monkeypatch):
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _HoldOpenCapture)
    daemon = Daemon(config)
    try:
        async def drive():
            started = await daemon._ptt_start({})
            assert started["listening"] is True
            # pretend the session has been holding the mic for an hour
            daemon._ptt_started_at = time.monotonic() - 3600.0
            return await daemon._watchdog_tick()

        closed = asyncio.run(drive())
        sid = daemon._ptt_session_id
        assert sid is not None
        assert closed is True
        # visible marker #1: the store journal
        rows = daemon.store.list_persona_events(kind="watchdog.close", limit=5)
        assert rows, "the watchdog close must be journalled"
        detail = json.loads(rows[0]["detail"])
        assert detail["session_id"] == sid
        assert "recording is kept" in detail["message"]
        assert detail["ceiling_s"] == 300.0
        # visible marker #2: status
        assert daemon._last_watchdog_close is not None
        assert daemon._last_watchdog_close["session_id"] == sid
        # the graceful close path ran: the session was released
        assert daemon._ptt_released_at is not None or daemon._dictation_task is None
    finally:
        daemon.store.close()


def test_watchdog_marker_is_visible_in_status(config, monkeypatch):
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _HoldOpenCapture)
    daemon = Daemon(config)
    try:
        async def drive():
            await daemon._ptt_start({})
            daemon._ptt_started_at = time.monotonic() - 3600.0
            await daemon._watchdog_tick()
            return await daemon._status({})

        status = asyncio.run(drive())
        assert status["last_watchdog_close"] is not None
        assert status["session_ceiling_s"] == 300.0
    finally:
        daemon.store.close()


def test_session_holders_enumerate_live_slots(config, monkeypatch):
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _HoldOpenCapture)
    daemon = Daemon(config)
    try:
        async def drive():
            await daemon._ptt_start({})
            holders = daemon._session_holders()
            status = await daemon._status({})
            return holders, status

        holders, status = asyncio.run(drive())
        assert len(holders) == 1
        row = holders[0]
        assert row["kind"] == "ptt"
        assert row["live"] is True
        assert row["session_id"] == daemon._ptt_session_id
        assert row["age_s"] is not None
        assert status["session_holders"] == holders
        assert status["dictation_active"] is True
        assert status["ptt_session_id"] == daemon._ptt_session_id
    finally:
        daemon.store.close()


def test_session_holders_include_meeting_and_event_rows(config, monkeypatch):
    daemon = Daemon(config)
    try:
        assert daemon._session_holders() == []
        daemon._meeting = {"session_id": "m1", "task": None, "dual": None,
                           "frames": {}, "started_mono": time.monotonic() - 5,
                           "started_at": "2026-10-25T10:00:00"}
        daemon.event_service._state = {"status": "running",
                                       "session_id": "e1"}
        kinds = {r["kind"] for r in daemon._session_holders()}
        assert kinds == {"meeting", "event"}
    finally:
        daemon.store.close()


def test_ceiling_is_configurable_and_clamped_to_numbers(config, monkeypatch):
    daemon = Daemon(config)
    try:
        assert daemon._session_ceiling_s() == 300.0
        config.raw["transcribe"]["ptt_session_ceiling_s"] = 60
        assert daemon._session_ceiling_s() == 60.0
        config.raw["transcribe"]["ptt_session_ceiling_s"] = "nonsense"
        assert daemon._session_ceiling_s() == 300.0
    finally:
        daemon.store.close()
