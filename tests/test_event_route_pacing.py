"""Route-specific quota selection, numeric safeguards, and spike records."""
import asyncio
import json
import struct
import wave
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from assistant import event_spike
from assistant.event import (
    BYTES_PER_HOUR,
    DEFAULT_CALL_BUDGET,
    NO_SIGNAL_PEAK,
    TPM_HEADROOM,
    DailyQuotaLedger,
    EventService,
    SegmentQueue,
    preflight,
    status_from_disk,
)

EAT = ZoneInfo("Africa/Nairobi")


def _write_wav(path: Path, seconds: float, *, amplitude: int = 1200):
    rate = 16000
    frames = int(rate * seconds)
    sample = struct.pack("<h", amplitude)
    with wave.open(str(path), "wb") as output:
        output.setparams((1, 2, rate, frames, "NONE", "not compressed"))
        output.writeframes(sample * frames)


def test_batch_route_uses_batch_rpd_and_no_live_tpm_ceiling(config):
    service = EventService(config, None, route="batch")
    live = EventService(config, None, route="transcribe-live")
    assert service._budget == DEFAULT_CALL_BUDGET == 25
    assert service._tpm_ceiling is None
    assert live._tpm_ceiling == 20_000
    assert TPM_HEADROOM == 0.7
    assert NO_SIGNAL_PEAK == 0.005
    assert BYTES_PER_HOUR == 115_200_000


def test_oversized_live_segment_splits_under_headroom_and_counts_every_call(tmp_path):
    wav_path = tmp_path / "seg-001.wav"
    _write_wav(wav_path, 25)
    clock = [0.0]
    durations = []
    resolved = []

    async def transcribe(path):
        from assistant import capture
        duration = capture.wav_duration_s(path)
        durations.append(duration)
        return f"part-{len(durations)}"

    async def sleep(seconds):
        clock[0] += seconds

    queue = SegmentQueue(
        transcribe, on_resolved=lambda segment, text: resolved.append(text),
        on_deferred=lambda segment, error: (_ for _ in ()).throw(AssertionError(error)),
        tokens_per_second=10, tpm_ceiling=100, daily_call_budget=10,
        max_attempts=1, deferred_retries=0, clock=lambda: clock[0], sleep=sleep)

    async def run():
        await queue._process({"index": 1, "wav": str(wav_path), "duration_s": 25})

    asyncio.run(run())
    assert len(durations) == 4
    assert all(duration * 10 <= 70.01 for duration in durations)
    assert queue.calls_used == 4
    assert resolved == ["part-1\npart-2\npart-3\npart-4"]


def test_live_route_20k_tpm_70_pct_headroom_splits_and_waits_60s_window(tmp_path):
    wav_path = tmp_path / "seg-live-long.wav"
    # 460 s * 32.0 tok/s = 14,720 est tokens > 14,000 ceiling (20,000 * 0.7)
    _write_wav(wav_path, 460)
    clock = [100.0]
    sleeps: list[float] = []
    chunk_durations: list[float] = []
    resolved: list[str] = []

    async def transcribe(path):
        from assistant import capture
        duration = capture.wav_duration_s(path)
        chunk_durations.append(duration)
        return f"chunk-{len(chunk_durations)}"

    async def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    queue = SegmentQueue(
        transcribe,
        on_resolved=lambda _seg, text: resolved.append(text),
        on_deferred=lambda _seg, err: (_ for _ in ()).throw(AssertionError(err)),
        tokens_per_second=32.0,
        tpm_ceiling=20_000.0,
        daily_call_budget=25,
        max_attempts=1,
        deferred_retries=0,
        clock=lambda: clock[0],
        sleep=sleep,
    )
    asyncio.run(queue._process({"index": 1, "wav": str(wav_path), "duration_s": 460}))
    assert len(chunk_durations) == 2
    assert all(dur * 32.0 <= 14_000.01 for dur in chunk_durations)
    assert len(sleeps) == 1
    assert sleeps[0] >= 60.0
    assert queue.calls_used == 2
    assert resolved == ["chunk-1\nchunk-2"]


def test_retry_cap_two_backoff_schedule_and_zero_deferred_retries(tmp_path):
    wav_path = tmp_path / "seg-fail.wav"
    _write_wav(wav_path, 2.0)
    sleeps: list[float] = []
    attempts = 0
    deferred: list[tuple[int, str]] = []

    async def always_fail(_path):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("transient 503")

    async def sleep(seconds):
        sleeps.append(seconds)

    queue = SegmentQueue(
        always_fail,
        on_resolved=lambda *_a: (_ for _ in ()).throw(AssertionError("unexpected resolve")),
        on_deferred=lambda seg, err: deferred.append((seg["index"], str(err))),
        tpm_ceiling=None,
        daily_call_budget=25,
        max_attempts=10,
        deferred_retries=5,
        sleep=sleep,
    )
    assert queue._max_attempts == 3
    assert queue._deferred_retries == 0

    async def run():
        worker = asyncio.create_task(queue.run())
        queue.submit({"index": 1, "wav": str(wav_path), "duration_s": 2.0})
        await asyncio.wait_for(queue.drain(), 2.0)
        await queue.stop()
        await worker

    asyncio.run(run())
    assert attempts == 3
    assert queue.calls_used == 3
    assert len(sleeps) == 2
    assert 2.0 <= sleeps[0] <= 2.6
    assert 4.0 <= sleeps[1] <= 5.2
    assert deferred == [(1, "transient 503")]


def test_reserve_two_blocks_at_23_opens_24_25_for_closing_and_stops_at_25(tmp_path):
    wav_a = tmp_path / "seg-024.wav"
    wav_b = tmp_path / "seg-025.wav"
    wav_c = tmp_path / "seg-026.wav"
    for p in (wav_a, wav_b, wav_c):
        _write_wav(p, 1.0)
    resolved: list[int] = []
    deferred: list[int] = []

    async def ok(_path):
        return "ok"

    queue = SegmentQueue(
        ok,
        on_resolved=lambda seg, _t: resolved.append(seg["index"]),
        on_deferred=lambda seg, _e: deferred.append(seg["index"]),
        tpm_ceiling=None,
        daily_call_budget=25,
        calls_used=23,
        reserve_calls=2,
        max_attempts=3,
    )

    async def run():
        worker = asyncio.create_task(queue.run())
        queue.submit({"index": 24, "wav": str(wav_a), "duration_s": 1.0})
        await asyncio.wait_for(queue.drain(), 2.0)
        assert queue.calls_used == 23
        assert deferred == [24]

        queue.allow_reserved_for(25)
        queue.submit({"index": 25, "wav": str(wav_b), "duration_s": 1.0})
        await asyncio.wait_for(queue.drain(), 2.0)
        assert queue.calls_used == 24
        assert resolved == [25]

        queue.allow_reserved_for(26)
        queue.submit({"index": 26, "wav": str(wav_c), "duration_s": 1.0})
        await asyncio.wait_for(queue.drain(), 2.0)
        assert queue.calls_used == 25
        assert resolved == [25, 26]

        queue.allow_reserved_for(27)
        queue.submit({"index": 27, "wav": str(wav_c), "duration_s": 1.0})
        await asyncio.wait_for(queue.drain(), 2.0)
        assert queue.calls_used == 25
        assert deferred == [24, 27]
        await queue.stop()
        await worker

    asyncio.run(run())


async def test_event_service_preflight_reads_actual_ledger_calls_and_disk_guards(config):
    now = datetime(2026, 11, 19, 12, 0, tzinfo=EAT)
    ledger_path = config.data_dir / "events" / "transcribe-calls.jsonl"
    batch_ledger = DailyQuotaLedger(ledger_path, route="batch", now_fn=lambda: now)
    live_ledger = DailyQuotaLedger(ledger_path, route="transcribe-live", now_fn=lambda: now)
    for seg in range(1, 24):
        batch_ledger.record_call(segment=seg)
    live_ledger.record_call(segment=1)
    assert batch_ledger.used_today() == 23
    assert live_ledger.used_today() == 1

    service = EventService(
        config, None,
        route="batch",
        quota_now_fn=lambda: now,
        level_checker=lambda: {"signal": True},
        power_probe=lambda: {"on_battery": False},
    )
    assert service.status()["calls"] == {
        "used": 23, "used_today": 23, "budget": 25, "remaining": 2, "reserve": 2,
    }

    disk_only = status_from_disk(config)
    assert disk_only["calls"]["reserve"] == 2

    # Preflight inside EventService.start() must reflect used_today=23, not 0.
    start_out = await service.start(source="simulated", title="QuotaCheck", battery_ok=True)
    assert start_out["preflight"]["budget"] == {"used": 23, "budget": 25}
    await service.stop()

    refuse_report = preflight(
        config, segment_minutes=30.0, route="batch", speaker="Speaker 1",
        roster=["Speaker 1"], inhibitor_held=True, inhibit_reason="ok",
        power={"on_battery": False}, level_check={"signal": True},
        disk_free_bytes=BYTES_PER_HOUR - 1, calls_used=23, budget=25,
    )
    assert len(refuse_report["refusals"]) == 1

    warn_report = preflight(
        config, segment_minutes=30.0, route="batch", speaker="Speaker 1",
        roster=["Speaker 1"], inhibitor_held=True, inhibit_reason="ok",
        power={"on_battery": False}, level_check={"signal": True},
        disk_free_bytes=BYTES_PER_HOUR * 5, calls_used=23, budget=25,
    )
    assert warn_report["refusals"] == []
    assert any("10 h" in w for w in warn_report["warnings"])


def test_historical_spike_record_preserved_and_batch_math_matches():
    spike_path = Path(__file__).parents[1] / "docs" / "event-spike.json"
    record = json.loads(spike_path.read_text(encoding="utf-8"))
    assert record["when"] == "2026-10-23T10:23:57"
    assert record["mode"] == "live"
    assert record["model"] == "gemini-3.5-transcribe-live"
    assert record["minutes"] == 30.0
    assert record["duration_s"] == 1800.0
    assert record["latency_s"] == 47.524
    assert record["live_ok"] is False
    assert "bidiGenerateContent" in record["error"]
    assert record["decision"]["row"] == 3
    assert record["decision"]["route"] == "batch"
    assert record["decision"]["segment_minutes"] == 30

    m30 = event_spike._restate_batch_math(30.0)
    assert m30["calls_per_10h_event"] == 20
    assert m30["fits_daily_budget"] is True
    assert m30["headroom_calls"] == 5

    m15 = event_spike._restate_batch_math(15.0)
    assert m15["calls_per_10h_event"] == 40
    assert m15["fits_daily_budget"] is False
    assert m15["headroom_calls"] == 0
