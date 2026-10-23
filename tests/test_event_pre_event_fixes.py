"""Pre-event zero-cost soak and quota safeguards."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

EAT = ZoneInfo("Africa/Nairobi")


def test_daily_quota_ledger_survives_restart_and_resets_at_la_midnight(tmp_path):
    from assistant.event import DailyQuotaLedger

    now = [datetime(2026, 10, 24, 9, 0, tzinfo=EAT)]
    path = tmp_path / "events" / "transcribe-calls.jsonl"
    first = DailyQuotaLedger(path, route="batch", now_fn=lambda: now[0])
    first.record_call(segment=1)
    first.record_call(segment=2)

    restarted = DailyQuotaLedger(path, route="batch", now_fn=lambda: now[0])
    assert restarted.used_today() == 2
    assert restarted.budget_remaining(25) == 23
    assert restarted.status(25)["next_reset_eat"].startswith("2026-10-24 10:00")

    now[0] = datetime(2026, 10, 24, 10, 0, tzinfo=EAT)
    assert restarted.used_today() == 0
    assert restarted.budget_remaining(25) == 25

    now[0] = datetime(2026, 11, 2, 8, 30, tzinfo=EAT)
    assert restarted.status(25)["next_reset_eat"].startswith("2026-11-02 11:00")


def test_event_queue_reserves_last_two_calls_for_closing_segment():
    from assistant.event import SegmentQueue

    async def run():
        calls = []
        resolved, deferred = [], []

        async def transcribe(path):
            calls.append(Path(path).name)
            return "final transcript"

        queue = SegmentQueue(
            transcribe, on_resolved=lambda segment, text: resolved.append(segment["index"]),
            on_deferred=lambda segment, error: deferred.append(segment["index"]),
            daily_call_budget=25, calls_used=23, reserve_calls=2, max_attempts=3,
            tpm_ceiling=None)
        worker = asyncio.create_task(queue.run())
        queue.submit({"index": 1, "wav": "/tmp/seg-001.wav", "duration_s": 30})
        await asyncio.wait_for(queue.drain(), 2)
        assert calls == [] and deferred == [1]

        queue.allow_reserved_for(2)
        queue.submit({"index": 2, "wav": "/tmp/seg-002.wav", "duration_s": 30})
        await asyncio.wait_for(queue.drain(), 2)
        assert calls == ["seg-002.wav"]
        assert resolved == [2]
        assert queue.calls_used == 24
        await queue.stop()
        await worker

    asyncio.run(run())


def test_segment_queue_retries_at_most_twice_and_counts_each_real_attempt():
    from assistant.event import SegmentQueue

    async def run():
        calls, durable_call_log, deferred = [], [], []

        async def transcribe(_path):
            calls.append(1)
            raise RuntimeError("provider unavailable")

        async def no_wait(_delay):
            return None

        queue = SegmentQueue(
            transcribe, on_resolved=lambda *_: None,
            on_deferred=lambda segment, _error: deferred.append(segment["index"]),
            daily_call_budget=25, max_attempts=99, tpm_ceiling=None,
            on_call=lambda segment: durable_call_log.append(segment["index"]),
            sleep=no_wait)
        worker = asyncio.create_task(queue.run())
        queue.submit({"index": 1, "wav": "/tmp/seg-001.wav", "duration_s": 30})
        await asyncio.wait_for(queue.drain(), 2)
        await queue.stop()
        await worker
        assert len(calls) == 3  # first call plus no more than two retries
        assert len(durable_call_log) == 3
        assert deferred == [1]

    asyncio.run(run())


def test_fake_transport_is_explicit_and_never_calls_transcriber(config):
    from assistant.event import EventService

    async def forbidden(_path):
        raise AssertionError("fake transport must not invoke transcription")

    async def run():
        class Inhibitor:
            held = False

            def acquire(self):
                self.held = True
                return {"held": True, "reason": "test lock"}

            def release(self):
                self.held = False

        inhibitor = Inhibitor()
        service = EventService(config, None, transcribe_fn=forbidden,
                               inhibitor=inhibitor, max_attempts=3,
                               level_checker=lambda: {"signal": True})
        service._power_probe = lambda: {"on_battery": True, "detail": "Battery discharging"}
        result = await service.start(source="simulated", title="Soak", battery_ok=True,
                                    no_transcribe=True, segment_minutes=0.001)
        await asyncio.sleep(0.18)
        assert service.status()["segments"]["opened"] >= 2
        assert result["state"] == "event"
        assert any("ON BATTERY" in warning
                   for warning in result["preflight"]["warnings"])
        assert inhibitor.held
        assert service.status()["transport"] == "fake — no calls will be made"
        assert service.status()["calls"]["used_today"] == 0
        await service.stop()
        assert not inhibitor.held
        await asyncio.gather(*service._background_queues, return_exceptions=True)
        assert service._queue.calls_used == 0
        assert "audio kept:" in Path(result["document"]).read_text()

    asyncio.run(run())


def test_event_start_parser_exposes_no_transcribe_flag():
    from assistant.cli import build_parser

    args = build_parser().parse_args(["event", "start", "--no-transcribe"])
    assert args.no_transcribe is True


def test_cli_no_transcribe_soak_shows_zero_call_transport(running_daemon, capsys):
    from assistant.cli import main

    _daemon, _server = running_daemon
    rc = main(["event", "start", "--no-transcribe", "--battery-ok",
               "--source", "simulated", "--title", "Zero-cost soak"])
    output = capsys.readouterr().out
    assert rc == 0
    assert "transport: fake — no calls will be made" in output
    status_rc = main(["event", "status"])
    status = json.loads(capsys.readouterr().out)
    assert status_rc == 0
    assert status["transport"] == "fake — no calls will be made"
    assert status["calls"]["used_today"] == 0
    assert status["calls"]["budget"] == 25
    assert status["quota"]["next_reset_eat"].endswith("EAT")
    main(["event", "stop"])
    capsys.readouterr()
