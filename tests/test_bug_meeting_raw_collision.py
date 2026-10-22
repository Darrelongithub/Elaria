"""Meeting daemon lifecycle: overlapping stops must not overwrite raw audio.

Both stop handlers may reach transcription concurrently. The daemon used a
second-resolution filename, then released its meeting slot before the first
transcriber had copied that file into the collision-safe archive.
"""

from __future__ import annotations

import asyncio
import datetime as datetime_module
import threading
from pathlib import Path

from assistant.daemon import Daemon
from assistant.meeting import read_pcm


def _meeting(session_id: str, value: int) -> dict:
    # One 30 ms frame per channel. Distinct bytes make replacement observable
    # after MeetingService copies the WAV into its archive.
    frame = bytes([value, 0]) * 480

    class Dual:
        async def aclose(self):
            return None

    return {
        "session_id": session_id,
        "dual": Dual(),
        "frames": {"mic": [frame], "sys": [frame]},
        "task": asyncio.create_task(asyncio.sleep(60)),
    }


def test_bug_meeting_overlapping_stops_keep_each_sessions_raw_wav(config,
                                                                   monkeypatch):
    fixed = datetime_module.datetime(2026, 10, 21, 12, 34, 56)

    class FrozenDateTime(datetime_module.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed.replace(tzinfo=tz)

    # _meeting_stop imports datetime locally; hold both stops in the same
    # second while MeetingService retains its real minute-stamp allocator.
    monkeypatch.setattr(datetime_module, "datetime", FrozenDateTime)
    daemon = Daemon(config)
    daemon.meetings._transcribe_channel = lambda *_args, **_kwargs: []
    original = daemon.meetings.transcribe_dual
    first_entered = threading.Event()
    release_first = threading.Event()
    calls: list[tuple[Path, Path]] = []
    calls_lock = threading.Lock()

    def delayed_first(mic_wav, sys_wav, **kwargs):
        with calls_lock:
            index = len(calls)
            calls.append((Path(mic_wav), Path(sys_wav)))
        if index == 0:
            first_entered.set()
            assert release_first.wait(5), "test did not release first transcriber"
        return original(mic_wav, sys_wav, **kwargs)

    daemon.meetings.transcribe_dual = delayed_first

    async def run():
        first_stop = None
        processing_while_first_pending = None
        try:
            daemon._meeting = _meeting("session-one", 0x11)
            first_stop = asyncio.create_task(
                daemon._meeting_stop({"title": "first"}))
            assert await asyncio.to_thread(first_entered.wait, 3), \
                "first transcriber did not reach its controlled pause"

            daemon._meeting = _meeting("session-two", 0x22)
            await daemon._meeting_stop({"title": "second"})
            processing_while_first_pending = bool(daemon._meeting_processing)
            release_first.set()
            first_result = await first_stop
            second_raw = calls[1][0]
            return first_result, second_raw, processing_while_first_pending
        finally:
            release_first.set()
            if first_stop is not None and not first_stop.done():
                await first_stop
            await daemon.aclose()

    first_result, second_raw, processing_while_first_pending = asyncio.run(run())
    note_text = Path(first_result["note_path"]).read_text(encoding="utf-8")
    mic_line = next(line for line in note_text.splitlines() if line.startswith("mic: "))
    first_archived_mic = Path(mic_line.removeprefix("mic: "))
    archived_pcm, _ = read_pcm(first_archived_mic)
    expected_first = bytes([0x11, 0]) * 480

    failures = []
    if calls[0][0] == second_raw:
        failures.append("overlapping stops reused the daemon raw WAV path")
    if archived_pcm != expected_first:
        failures.append("first archive contains later meeting bytes")
    if not processing_while_first_pending:
        failures.append("second stop cleared processing while first remained pending")
    assert not failures, (
        "; ".join(failures) +
        f"; raw paths were {calls[0][0]} and {second_raw}")
