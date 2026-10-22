"""Event transcriber — core contracts (Blueprint v2 §7), red-first.

Covers: next-segment-opens-first rotation, ordered appends under out-of-order
results, speaker switching (flush/merge/inline-marker per route), the
rate-limited queue (pacing, retry, quota-exhaustion deferral), state-file
recovery ("assemble from disk"), per-segment capture.stats, the no-signal
marker, preflight, and the prime directive: if audio exists, a transcript or
an explicit "audio kept: <path>" marker always comes back — no silent drops.
"""

from __future__ import annotations

import asyncio
import json
import struct
from datetime import datetime
from pathlib import Path

SPEECH_FRAME = struct.pack("<480h", *([6000] * 480))      # 30ms @16k, loud
SILENT_FRAME = b"\x00\x00" * 480                          # 30ms @16k, dead


class FakeClock:
    """Injectable monotonic clock the tests drive explicitly."""

    def __init__(self, start: float = 10_000.0):
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


class PumpSource:
    """Manually pumped frame source: the test decides when frames flow.

    Each consumed frame advances the fake clock by `frame_s`, so rotation is
    deterministic (segment_minutes=0.05 -> 3 fake-seconds -> 3 frames).
    """

    def __init__(self, clock: FakeClock, *, frame_s: float = 1.0,
                 target: str = "fake-mic"):
        self.clock = clock
        self.frame_s = frame_s
        self.target = target
        self.stalled = False
        self.closed = False
        self._queue: asyncio.Queue = asyncio.Queue()

    async def frames(self):
        while True:
            frame = await self._queue.get()
            if frame is None:
                return
            self.clock.advance(self.frame_s)
            yield frame

    async def aclose(self):
        self.closed = True
        await self._queue.put(None)

    async def push(self, count: int = 1, frame: bytes = SPEECH_FRAME) -> None:
        for _ in range(count):
            await self._queue.put(frame)
            await asyncio.sleep(0)          # let the capture loop consume it


class TranscribeScript:
    """Controllable async transcribe_fn.

    Each segment's result is gated on its own asyncio.Event: the test decides
    completion order (to force out-of-order results) and failure behaviour.
    """

    def __init__(self):
        self.gates: dict[int, asyncio.Event] = {}
        self.fail_times: dict[int, int] = {}
        self.fail_always: set[int] = set()
        self.calls: list[int] = []
        self.text_for = lambda index: f"transcript of segment {index:03d}"

    def gate(self, index: int) -> asyncio.Event:
        return self.gates.setdefault(index, asyncio.Event())

    async def __call__(self, path: Path) -> str:
        index = int(Path(path).stem.split("-")[1])
        self.calls.append(index)
        if self.fail_times.get(index, 0) > 0:
            self.fail_times[index] -= 1
            raise RuntimeError(f"synthetic failure for segment {index:03d}")
        if index in self.fail_always:
            raise RuntimeError(f"synthetic failure for segment {index:03d}")
        await self.gate(index).wait()
        return self.text_for(index)


def make_service(config, *, script=None, clock=None, **kwargs):
    from assistant.event import EventService

    kwargs.setdefault("transcribe_fn",
                      script if script is not None else TranscribeScript())
    kwargs.setdefault("clock", clock if clock is not None else FakeClock())
    kwargs.setdefault("now_fn", lambda: datetime(2026, 10, 22, 14, 30, 0))
    return EventService(config, store=kwargs.pop("store", None), **kwargs)


# --------------------------------------------------------------------------
# Ordered appender + document
# --------------------------------------------------------------------------
def test_document_appends_are_mirrored_and_atomic(config):
    from assistant.event import EventDocument

    root = config.data_dir / "events"
    root.mkdir(parents=True)
    doc = EventDocument(root / "2026-10-22-panel.md", root / "2026-10-22-panel.txt")
    doc.write_header("Panel", "2026-10-22T14:30:00",
                     {"route": "batch", "segment_minutes": 30})
    doc.append_block("## 14:30 · Amina · seg 001\n\nhello world\n")

    md = (root / "2026-10-22-panel.md").read_text()
    txt = (root / "2026-10-22-panel.txt").read_text()
    assert md == txt                      # mirrored .txt on every append
    assert md.startswith("# Panel")
    assert "hello world" in md
    assert doc.word_count() == len(md.split())


def test_ordered_appender_holds_later_results_until_earlier_resolve(config):
    from assistant.event import EventDocument, OrderedAppender

    root = config.data_dir / "events"
    root.mkdir(parents=True)
    doc = EventDocument(root / "e.md", root / "e.txt")
    doc.write_header("E", "2026-10-22T10:00:00", {})
    appender = OrderedAppender(doc)

    for i in (1, 2, 3):
        appender.expect(i)
    appender.resolved(3, "block three\n")
    appender.resolved(2, "block two\n")
    assert "block" not in doc.md_path.read_text()      # nothing landed yet
    appender.resolved(1, "block one\n")

    text = doc.md_path.read_text()
    assert text.index("block one") < text.index("block two") < text.index("block three")


def test_ordered_appender_deferred_marker_unblocks_later_segments(config):
    from assistant.event import EventDocument, OrderedAppender

    root = config.data_dir / "events"
    root.mkdir(parents=True)
    doc = EventDocument(root / "e.md", root / "e.txt")
    appender = OrderedAppender(doc)
    for i in (1, 2, 3):
        appender.expect(i)
    appender.resolved(1, "one\n")
    appender.deferred(2, "[seg 002 transcription failed/deferred — audio kept: /x/seg-002.wav]\n")
    appender.resolved(3, "three\n")

    text = doc.md_path.read_text()
    assert "audio kept: /x/seg-002.wav" in text
    assert text.index("one") < text.index("audio kept") < text.index("three")


def test_ordered_appender_force_pending_writes_markers_in_order(config):
    from assistant.event import EventDocument, OrderedAppender

    root = config.data_dir / "events"
    root.mkdir(parents=True)
    doc = EventDocument(root / "e.md", root / "e.txt")
    appender = OrderedAppender(doc)
    for i in (1, 2, 3):
        appender.expect(i)
    appender.resolved(2, "two\n")

    forced = appender.force_pending(
        lambda i: f"[seg {i:03d} transcription failed/deferred — audio kept: /x/seg-{i:03d}.wav]\n")
    assert forced == [1, 3]
    text = doc.md_path.read_text()
    assert text.index("seg 001") < text.index("two") < text.index("seg 003")


def test_ordered_appender_late_recovery_appends_after_marker(config):
    from assistant.event import EventDocument, OrderedAppender

    root = config.data_dir / "events"
    root.mkdir(parents=True)
    doc = EventDocument(root / "e.md", root / "e.txt")
    appender = OrderedAppender(doc)
    appender.expect(1)
    appender.deferred(1, "[seg 001 transcription failed/deferred — audio kept: /x/seg-001.wav]\n")
    appender.append_late(1, "## 10:01 · A · seg 001 (recovered)\n\nlate text\n")

    text = doc.md_path.read_text()
    assert "audio kept" in text
    assert "late text" in text
    assert text.index("audio kept") < text.index("late text")


# --------------------------------------------------------------------------
# Speakers
# --------------------------------------------------------------------------
def test_speaker_roster_cycling_and_named_jump():
    from assistant.event import SpeakerBook

    book = SpeakerBook(["Amina", "John", "Zuri"])
    assert book.active == "Amina"
    assert book.switch_next() == "John"
    assert book.switch_next() == "Zuri"
    assert book.switch_next() == "Amina"           # cycles the roster
    assert book.switch_to("Zuri") == "Zuri"        # direct jump
    assert book.switch_to("New Guest") == "New Guest"  # unknown name joins roster
    assert "New Guest" in book.roster


def test_speaker_generates_names_when_no_roster_given():
    from assistant.event import SpeakerBook

    book = SpeakerBook()
    assert book.active == "Speaker 1"
    assert book.switch_next() == "Speaker 2"       # created on first switch
    assert book.switch_next() == "Speaker 3"
    assert book.switch_to("Amina") == "Amina"
    assert book.switch_next() == "Speaker 1"       # cycles the generated roster


# --------------------------------------------------------------------------
# Rotation: next-segment-opens-first, capture.stats, no-signal marker
# --------------------------------------------------------------------------
async def test_next_segment_opens_before_prior_transcription_starts(config):
    events_dir = config.data_dir / "events"
    TranscribeScript()
    seen: list[tuple[str, bool]] = []

    async def transcribe(path: Path) -> str:
        index = int(Path(path).stem.split("-")[1])
        later = Path(path).parent / f"seg-{index + 1:03d}.wav"
        seen.append((Path(path).name, later.exists()))
        await asyncio.sleep(0)
        return f"transcript of segment {index:03d}"

    clock = FakeClock()
    service = make_service(config, clock=clock, transcribe_fn=transcribe,
                           segment_minutes=0.05)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", battery_ok=True)
    for _ in range(3):                       # 3 segments of 3 frames each
        await source.push(3)
        await asyncio.sleep(0.01)
    await source.aclose()
    await service.wait_capture_idle()
    result = await service.stop()

    assert result["segments"] >= 3
    assert result["transcribed"] == result["segments"]   # all actually ran
    assert len(seen) == result["segments"], (
        "transcribe must be called once per closed segment — a raising "
        "transcribe_fn must never pass this test vacuously")
    # when each segment was transcribed, the NEXT segment's WAV was already
    # on disk — opened first, then the previous one closed + enqueued
    for name, existed in seen[:-1]:
        assert existed, f"next segment not open before transcribe({name})"
    seg_dirs = list(events_dir.glob("*/segments"))
    assert seg_dirs, "segment WAVs must be written"
    assert len(list(seg_dirs[0].glob("seg-*.wav"))) >= 3


async def test_appends_land_in_order_even_when_results_return_out_of_order(config):
    script = TranscribeScript()
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=0.05)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", battery_ok=True)
    await source.push(8)                     # 3 segments (rotate every 3 frames)
    await source.aclose()
    await service.wait_capture_idle()

    # results arrive 3, 2, 1 — the document must still be ordered 1, 2, 3
    script.gate(3).set()
    script.gate(2).set()
    await asyncio.sleep(0.01)
    script.gate(1).set()
    result = await service.stop()

    text = Path(result["document"]).read_text()
    positions = [text.index(f"seg {i:03d}") for i in (1, 2, 3)]
    assert positions == sorted(positions)
    assert "transcript of segment 001" in text
    assert "transcript of segment 003" in text
    assert result["deferred"] == []


async def test_segment_capture_stats_logged_per_segment(config):
    from assistant.store import Store

    store = Store(config.db_path)
    script = TranscribeScript()
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock, store=store,
                           segment_minutes=0.05)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", battery_ok=True)
    await source.push(5)                     # 2 segments (rotate every 3 frames)
    await source.aclose()
    await service.wait_capture_idle()
    script.gate(1).set()
    script.gate(2).set()
    await service.stop()

    rows = store.list_persona_events(kind="capture.stats", limit=10)
    store.close()
    assert len(rows) >= 2
    for row in rows:
        detail = json.loads(row["detail"])
        assert {"segment", "node", "bytes", "peak"} <= set(detail)
        assert detail["bytes"] > 0
        assert detail["peak"] > 0                  # speech frames were fed
        assert detail["node"] == "fake-mic"


async def test_near_zero_peak_writes_no_signal_marker(config):
    script = TranscribeScript()
    script.text_for = lambda index: ""             # silence in, silence out
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=0.05)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", battery_ok=True)
    await source.push(2, frame=SILENT_FRAME)  # one segment, pure silence
    await source.aclose()
    await service.wait_capture_idle()
    script.gate(1).set()
    result = await service.stop()

    text = Path(result["document"]).read_text()
    assert "[seg 001: no signal detected]" in text


# --------------------------------------------------------------------------
# Speakers inside an event (route-dependent flush)
# --------------------------------------------------------------------------
async def test_batch_route_switch_writes_inline_marker_without_flush(config):
    script = TranscribeScript()
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=1.0, route="batch")
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", speakers="Amina,John",
                        battery_ok=True)
    await source.push(2)                       # segment 001 open, 2 frames
    result = service.speaker_switch("John")    # batch: inline marker only
    assert result["flushed"] is False
    assert "→ John @" in result["marker"]

    await source.push(4)                       # timer rotates once at 60s
    await source.aclose()
    await service.wait_capture_idle()
    for i in (1, 2, 3):
        script.gate(i).set()
    outcome = await service.stop()

    text = Path(outcome["document"]).read_text()
    assert "[→ John @" in text
    seg_dir = next((config.data_dir / "events").glob("*/segments"))
    # the switch itself never opened a new segment — only the timer did
    labels = json.loads((seg_dir.parent / "labels.json").read_text())
    assert labels["segments"]["001"] == "Amina"


async def test_live_route_flush_labels_outgoing_and_incoming(config):
    script = TranscribeScript()
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=5.0, route="transcribe-live",
                           flush_min_s=20.0)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", speakers="Amina,John",
                        battery_ok=True)
    await source.push(30)                      # 30 frames = 30 fake seconds
    result = service.speaker_switch("John")
    assert result["flushed"] is True
    assert result["outgoing_speaker"] == "Amina"
    assert result["incoming_speaker"] == "John"

    await source.push(2)
    await source.aclose()
    await service.wait_capture_idle()
    for i in (1, 2, 3):
        script.gate(i).set()
    await service.stop()

    seg_dir = next((config.data_dir / "events").glob("*/segments"))
    labels = json.loads((seg_dir.parent / "labels.json").read_text())
    assert labels["segments"]["001"] == "Amina"      # outgoing label on flushed seg
    assert labels["segments"]["002"] == "John"       # incoming on the new one


async def test_live_route_sub_20s_switch_merges_inline(config):
    script = TranscribeScript()
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=5.0, route="transcribe-live",
                           flush_min_s=20.0)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", speakers="Amina,John",
                        battery_ok=True)
    await source.push(5)                       # only 5s open — under 20s
    result = service.speaker_switch("John")
    assert result["flushed"] is False                # merged: no flush
    assert "→ John @" in result["marker"]

    await source.push(2)
    await source.aclose()
    await service.wait_capture_idle()
    for i in (1, 2):
        script.gate(i).set()
    await service.stop()
    seg_dir = next((config.data_dir / "events").glob("*/segments"))
    labels = json.loads((seg_dir.parent / "labels.json").read_text())
    assert labels["segments"]["001"] == "Amina"      # seg 001 never flushed early


# --------------------------------------------------------------------------
# Queue: pacing, retry, quota exhaustion
# --------------------------------------------------------------------------
async def test_queue_pacing_respects_tpm_budget_under_burst():
    from assistant.event import SegmentQueue

    clock = FakeClock()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)
        clock.advance(seconds)

    started: list[tuple[int, float]] = []

    async def transcribe(path: Path) -> str:
        index = int(Path(path).stem.split("-")[1])
        started.append((index, clock()))
        return f"t{index}"

    resolved: list[int] = []
    queue = SegmentQueue(
        transcribe, on_resolved=lambda seg, text: resolved.append(seg["index"]),
        on_deferred=lambda seg, err: resolved.append(-seg["index"]),
        tokens_per_second=100.0, tpm_ceiling=1000.0,  # 300 tokens/seg (3s)
        daily_call_budget=25, max_attempts=1,
        clock=clock, sleep=fake_sleep)

    worker = asyncio.create_task(queue.run())
    # three 3s segments (300 tokens each) with a 700-token/min budget:
    # 1 + 2 fit (600), the third must wait for the rolling minute to drain.
    for index in (1, 2, 3):
        queue.submit({"index": index, "wav": Path(f"/tmp/seg-{index:03d}.wav"),
                      "duration_s": 3.0})
    await asyncio.wait_for(queue.drain(), timeout=5)
    await queue.stop()
    await worker

    assert sorted(i for i, _ in started) == [1, 2, 3]
    assert sleeps, "third segment must wait for TPM headroom"
    assert started[-1][1] >= 60.0                    # waited out the window


async def test_queue_failure_retries_then_defers_with_marker():
    from assistant.event import SegmentQueue

    clock = FakeClock()

    async def fake_sleep(seconds: float):
        clock.advance(seconds)

    attempts = {"n": 0}

    async def transcribe(path: Path) -> str:
        attempts["n"] += 1
        raise RuntimeError("quota 429")

    resolved, deferred = [], []
    queue = SegmentQueue(
        transcribe,
        on_resolved=lambda seg, text: resolved.append(seg["index"]),
        on_deferred=lambda seg, err: deferred.append((seg["index"], err)),
        tokens_per_second=10.0, tpm_ceiling=100_000.0,
        daily_call_budget=25, max_attempts=3,
        clock=clock, sleep=fake_sleep)
    worker = asyncio.create_task(queue.run())
    queue.submit({"index": 1, "wav": Path("/tmp/seg-001.wav"), "duration_s": 3.0})
    await asyncio.wait_for(queue.drain(), timeout=5)

    assert attempts["n"] == 3                        # capped attempts
    assert resolved == []
    assert deferred and deferred[0][0] == 1
    assert "429" in str(deferred[0][1])
    await queue.stop()
    await worker


async def test_queue_retry_pool_drains_when_idle():
    from assistant.event import SegmentQueue

    clock = FakeClock()

    async def fake_sleep(seconds: float):
        clock.advance(seconds)

    fail_then_ok = {"fails": 2}

    async def transcribe(path: Path) -> str:
        if fail_then_ok["fails"] > 0:
            fail_then_ok["fails"] -= 1
            raise RuntimeError("transient")
        return "recovered text"

    resolved, deferred = [], []
    queue = SegmentQueue(
        transcribe,
        on_resolved=lambda seg, text: resolved.append((seg["index"], text)),
        on_deferred=lambda seg, err: deferred.append(seg["index"]),
        tokens_per_second=10.0, tpm_ceiling=100_000.0,
        daily_call_budget=25, max_attempts=1,       # defer after 1 try…
        deferred_retries=2,                          # …then the pool takes over
        clock=clock, sleep=fake_sleep)
    worker = asyncio.create_task(queue.run())
    queue.submit({"index": 1, "wav": Path("/tmp/seg-001.wav"), "duration_s": 3.0})
    await asyncio.wait_for(queue.drain(), timeout=5)

    assert deferred == [1]                           # marker landed…
    assert resolved and resolved[0][0] == 1          # …then the pool recovered it
    assert resolved[0][1] == "recovered text"
    await queue.stop()
    await worker


async def test_queue_quota_exhausted_defers_immediately_and_capture_continues():
    from assistant.event import SegmentQueue

    clock = FakeClock()

    async def fake_sleep(seconds: float):
        clock.advance(seconds)

    calls = []

    async def transcribe(path: Path) -> str:
        calls.append(Path(path).name)
        return "t"

    resolved, deferred = [], []
    queue = SegmentQueue(
        transcribe,
        on_resolved=lambda seg, text: resolved.append(seg["index"]),
        on_deferred=lambda seg, err: deferred.append(seg["index"]),
        tokens_per_second=10.0, tpm_ceiling=100_000.0,
        daily_call_budget=1, max_attempts=1,
        clock=clock, sleep=fake_sleep)
    worker = asyncio.create_task(queue.run())
    queue.submit({"index": 1, "wav": Path("/tmp/seg-001.wav"), "duration_s": 3.0})
    queue.submit({"index": 2, "wav": Path("/tmp/seg-002.wav"), "duration_s": 3.0})
    await asyncio.wait_for(queue.drain(), timeout=5)

    # newest-closed first (§3 queue rules): segment 2 spends the budget,
    # segment 1 is deferred — not dropped
    assert calls == ["seg-002.wav"]
    assert 2 in resolved
    assert 1 in deferred
    await queue.stop()
    await worker


# --------------------------------------------------------------------------
# Prime directive: transcription fails → "audio kept" marker, never silence
# --------------------------------------------------------------------------
async def test_transcription_failure_still_returns_audio_kept_marker(config):
    script = TranscribeScript()
    script.fail_always = {2}
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=0.05, max_attempts=1,
                           deferred_retries=0)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", battery_ok=True)
    await source.push(8)                     # 3 segments: 001 ok, 002 fails, 003 ok
    await source.aclose()
    await service.wait_capture_idle()
    script.gate(1).set()
    script.gate(3).set()
    result = await service.stop()

    text = Path(result["document"]).read_text()
    assert "transcript of segment 001" in text
    assert "transcript of segment 003" in text
    # seg 002's failure is explicit and cites its audio
    assert "[seg 002 transcription failed/deferred — audio kept: " in text
    assert result["deferred"] and result["deferred"][0]["index"] == 2
    seg_dir = next((config.data_dir / "events").glob("*/segments"))
    assert (seg_dir / "seg-002.wav").exists()        # capture may not fail
    for row in result["deferred"]:
        assert Path(row["wav"]).exists()             # every marker cites truth


# --------------------------------------------------------------------------
# Recovery: assemble from disk after a daemon kill
# --------------------------------------------------------------------------
async def test_stop_assembles_full_document_after_daemon_kill(config):
    from assistant.capture import write_wav
    from assistant.event import assemble_event_document, recover_event

    events_root = config.data_dir / "events"
    event_dir = events_root / "2026-10-22-panel"
    seg_dir = event_dir / "segments"
    seg_dir.mkdir(parents=True)
    # Disk state a killed daemon would leave: 3 segment WAVs, one transcribed,
    # one closed-but-untranscribed, one still open. Nothing else.
    for i in (1, 2, 3):
        write_wav(seg_dir / f"seg-{i:03d}.wav", [SPEECH_FRAME])
    (seg_dir / "seg-001.txt").write_text("the only transcript we got\n")
    (event_dir / "labels.json").write_text(json.dumps({
        "title": "Panel", "roster": ["Amina", "John"],
        "segments": {"001": "Amina", "002": "John", "003": "John"}}))
    (event_dir / "state.json").write_text(json.dumps({
        "title": "Panel", "status": "running", "route": "batch",
        "segment_minutes": 30, "active_speaker": "John",
        "roster": ["Amina", "John"], "segment_index": 4,
        "segments": [
            {"index": 1, "wav": str(seg_dir / "seg-001.wav"), "speaker": "Amina",
             "opened_at": "2026-10-22T14:30:00", "closed_at": "2026-10-22T15:00:00",
             "status": "done", "txt": str(seg_dir / "seg-001.txt"),
             "bytes": 100, "peak": 0.5, "markers": [], "no_signal": False},
            {"index": 2, "wav": str(seg_dir / "seg-002.wav"), "speaker": "John",
             "opened_at": "2026-10-22T15:00:00", "closed_at": "2026-10-22T15:30:00",
             "status": "queued", "txt": None,
             "bytes": 100, "peak": 0.5, "markers": [], "no_signal": False},
            {"index": 3, "wav": str(seg_dir / "seg-003.wav"), "speaker": "John",
             "opened_at": "2026-10-22T15:30:00", "closed_at": None,
             "status": "open", "txt": None,
             "bytes": 100, "peak": 0.5, "markers": [], "no_signal": False},
        ]}))

    summary = assemble_event_document(event_dir)
    text = Path(summary["document"]).read_text()
    assert "the only transcript we got" in text
    assert "[seg 002 transcription failed/deferred — audio kept: " in text
    assert "[seg 003 transcription failed/deferred — audio kept: " in text
    assert text.index("seg 001") < text.index("seg 002") < text.index("seg 003")
    assert summary["segments"] == 3
    assert {row["index"] for row in summary["deferred"]} == {2, 3}

    # recover_event is the daemon-down `event stop`: same assembly, marked
    recovered = recover_event(config)
    assert recovered["state"] == "recovered"
    assert Path(recovered["document"]).exists()
    state = json.loads((event_dir / "state.json").read_text())
    assert state["status"] == "recovered"


async def test_recover_event_reports_not_running_when_nothing_pending(config):
    from assistant.event import recover_event

    result = recover_event(config)
    assert result["state"] == "not-running"


# --------------------------------------------------------------------------
# Preflight + sleep inhibition
# --------------------------------------------------------------------------
async def test_preflight_warns_on_battery_and_start_requires_battery_ok(config):
    from assistant.event import EventService, preflight

    power = {"available": True, "on_battery": True, "detail": "BAT0 Discharging 81%"}
    report = preflight(
        config, segment_minutes=30, route="batch", speaker="Amina",
        roster=["Amina"], inhibitor_held=True, inhibit_reason="held",
        power=power,
        level_check={"available": False, "reason": "no pw-record",
                     "target": "mic", "signal": False},
        disk_free_bytes=10 * 1024 ** 3, calls_used=0, budget=25)
    assert any("battery" in w.lower() for w in report["warnings"])
    assert report["refusals"] == []

    service = EventService(config, store=None,
                           transcribe_fn=TranscribeScript(),
                           power_probe=lambda: power)
    result = await service.start(title="Panel", battery_ok=False)
    assert result["state"] == "needs-battery-ok"
    assert result["preflight"]["power"]["on_battery"] is True


async def test_preflight_hard_refuses_only_on_disk(config):
    from assistant.event import preflight

    report = preflight(
        config, segment_minutes=30, route="batch", speaker="A", roster=["A"],
        inhibitor_held=False, inhibit_reason="systemd-inhibit not found",
        power={"available": False, "on_battery": False, "detail": ""},
        level_check={"available": False, "reason": "container", "target": "mic",
                     "signal": False},
        disk_free_bytes=50 * 1024 ** 2, calls_used=0, budget=25)  # < 1 hour
    assert report["refusals"], "disk under one hour must refuse"
    assert any("disk" in r.lower() for r in report["refusals"])

    report2 = preflight(
        config, segment_minutes=30, route="batch", speaker="A", roster=["A"],
        inhibitor_held=False, inhibit_reason="systemd-inhibit not found",
        power={"available": False, "on_battery": False, "detail": ""},
        level_check={"available": False, "reason": "container", "target": "mic",
                     "signal": False},
        disk_free_bytes=10 * 1024 ** 3, calls_used=0, budget=25)
    assert report2["refusals"] == []
    assert len(report2["warnings"]) >= 2            # mic + inhibit only warn


async def test_inhibitor_acquired_for_event_and_released_on_stop(config):
    from assistant.event import EventService, SleepInhibitor

    class FakeInhibitor(SleepInhibitor):
        def __init__(self):
            self._held = False

        def acquire(self):
            self._held = True
            self.detail = {"held": True, "reason": "fake lock"}
            return self.detail

        def release(self):
            self._held = False

        @property
        def held(self):
            return self._held

    inhibitor = FakeInhibitor()
    service = EventService(config, store=None, transcribe_fn=TranscribeScript(),
                           inhibitor=inhibitor, segment_minutes=0.05)
    source = PumpSource(FakeClock())
    result = await service.start(source=source, title="Panel", battery_ok=True)
    assert result["preflight"]["inhibit"]["held"] is True
    assert inhibitor.held
    await source.push(2)
    await source.aclose()
    await service.wait_capture_idle()
    service._transcribe_fn.gate(1).set()
    await service.stop()
    assert not inhibitor.held, "the inhibit lock must be released on stop"


# --------------------------------------------------------------------------
# Status + stop contract (§3)
# --------------------------------------------------------------------------
async def test_stop_reports_document_word_count_and_deferred_paths(config):
    script = TranscribeScript()
    script.fail_always = {2}
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=0.05, max_attempts=1,
                           deferred_retries=0,
                           now_fn=lambda: datetime(2026, 10, 22, 18, 0, 0))
    source = PumpSource(clock)
    await service.start(source=source, title="Retrospective", battery_ok=True)
    await source.push(5)                     # 2 segments: 001 ok, 002 fails
    await source.aclose()
    await service.wait_capture_idle()
    script.gate(1).set()
    result = await service.stop()

    assert Path(result["document"]).exists()
    assert result["word_count"] > 0
    assert result["segments"] == 2
    assert result["transcribed"] >= 1
    assert result["deferred"] and result["deferred"][0]["index"] == 2
    assert result["deferred"][0]["wav"].endswith("seg-002.wav")

    status = service.status()
    assert status["running"] is False
    assert status["document"].endswith(".md")


async def test_status_shape_while_running(config):
    script = TranscribeScript()
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=1.0, daily_call_budget=25)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", speakers="Amina,John",
                        battery_ok=True)
    await source.push(2)                       # segment 001 still open
    status = service.status()

    assert status["running"] is True
    assert status["active_speaker"] == "Amina"
    assert status["segment_index"] >= 1
    assert "segment_elapsed_s" in status
    assert {"opened", "transcribed", "queued", "deferred"} <= set(status["segments"])
    assert status["calls"]["used"] == 0
    assert status["calls"]["budget"] == 25
    assert "disk" in status and "free_bytes" in status["disk"]
    assert status["document"].endswith(".md")

    await source.aclose()
    await service.wait_capture_idle()
    script.gate(1).set()
    await service.stop()


async def test_labels_json_written_during_event_for_lossless_rename(config):
    script = TranscribeScript()
    clock = FakeClock()
    service = make_service(config, script=script, clock=clock,
                           segment_minutes=0.05)
    source = PumpSource(clock)
    await service.start(source=source, title="Panel", speakers="Amina,John",
                        battery_ok=True)
    await source.push(2)
    await source.aclose()
    await service.wait_capture_idle()

    # labels.json exists DURING the event (P2 rename must be lossless later)
    event_dir = next(d for d in (config.data_dir / "events").iterdir() if d.is_dir())
    labels = json.loads((event_dir / "labels.json").read_text())
    assert labels["title"] == "Panel"
    assert labels["roster"] == ["Amina", "John"]
    assert labels["segments"]["001"] == "Amina"

    service._transcribe_fn.gate(1).set()
    await service.stop()
