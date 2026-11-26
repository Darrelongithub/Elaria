"""BUG-HW1 [hardware, owner laptop 2026-11-26] — the raw-stdout capture differential.

Bug (bugs.md, BUG-HW1): daemon-captured audio plays back as explosive
static while the owner's manual `pw-record --target <node> --rate 16000
--channels 1 file.wav` from the SAME node is clean. Daemon path:
`pw-record --target=<node.name> --rate 16000 --channels 1 --format s16 -`
(raw s16le PCM over stdout), frames read with readexactly, passed through
the soft limiter into WavSink.

The owner A/B (bugs.md, PR #162) acquitted target resolution and showed the
same argv to a file is clean while the raw-stdout form explodes. pw-record
never reports the negotiated format on stdout, so the byte-rate of the pipe
vs the s16le/16k/mono label is the only in-band discriminator — the manager's
byte-count check (`~160KB = s16/16k at rate; ~320KB = s32/16k; ~480KB = s16/48k;
~960KB = f32/48k`) decides which mislabel the owner's machine delivered.

What this file proves in the sandbox, around the REAL
`assistant.capture.pw_record_pcm_stream_command` and the REAL
`PipeWireCapture` (a fake `pw-record` on PATH emits chosen bytes):

1. Pipe framing cannot be the cause: arbitrary write chunkings of the same
   stream reassemble byte-exactly through `readexactly` (suspect 2 refuted).
2. The processing chain cannot be the cause: the limiter only compresses —
   a full-scale-garbage input stays full-scale garbage and a loud clean
   input stays a clean take, end to end to the saved WAV (suspect 4 refuted).
3. A rate/width/format mislabel reproduces the static signature — peak at
   full scale, huge RMS, a large share of limited samples, ASR-emptying
   noise — while a rate-only mismatch (s16 at 48 kHz) does NOT (peak stays at
   the sine amplitude; it is chipmunk, not static). A byte-rate of 1.0x is
   blind to endianness (bswap is rate-identical), which is why the journal
   carries the argv AND the delivery facts instead of claiming to solve it.
4. The capture journals the exact argv at spawn and the measured facts at
   stream end (`stream_facts`: argv, expected vs measured bytes/s, delivery
   ratio, named class, `mismatch_suspect`), so the owner's next hardware
   report is self-diagnosing, and the dictation lifecycle/persona journals
   carry them through.
5. The 0-byte secondary: bytes sitting in the pipe when the child dies are
   counted (`dropped_tail_bytes`), never silently discarded.

Nothing here changes what is captured, the limiter, the VAD or any frozen
threshold (1.75/0.75/0.5, silence floor, limiter curve) — capture fidelity
is observed and journalled, never rewritten.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import stat
import struct
import sys
from pathlib import Path

import pytest

from assistant.capture import (
    SAMPLE_RATE,
    PipeWireCapture,
    SoftLimiter,
    WavSink,
    classify_delivery_rate,
    delivery_rate_class,
    frame_rms,
    pcm_peak,
    pw_record_pcm_stream_command,
    split_peak,
)

FRAME_SAMPLES = SAMPLE_RATE * 30 // 1000  # 480 samples = 960 bytes
FAKE_PW_RECORD = """#!{python}
import os
import sys
import time

def main():
    payload_path = os.environ.get("FAKE_PW_PAYLOAD")
    if not payload_path:
        sys.stderr.write("FAKE_PW_PAYLOAD not set\\n")
        sys.exit(2)
    data = open(payload_path, "rb").read()
    chunk = int(os.environ.get("FAKE_PW_CHUNK", "0"))
    delay = float(os.environ.get("FAKE_PW_DELAY", "0"))
    hold_s = float(os.environ.get("FAKE_PW_HOLD_S", "0"))
    sleep_after = os.environ.get("FAKE_PW_SLEEP_AFTER", "0") == "1"
    out = sys.stdout.buffer
    if chunk > 0:
        for off in range(0, len(data), chunk):
            out.write(data[off:off + chunk])
            out.flush()
            if delay:
                time.sleep(delay)
    else:
        out.write(data)
        out.flush()
    if sleep_after:
        time.sleep(hold_s or 30.0)

main()
"""


def _write_fake(tmp_path: Path) -> Path:
    binary = tmp_path / "bin" / "pw-record"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_text(FAKE_PW_RECORD.format(python=sys.executable),
                      encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
                 | stat.S_IXOTH)
    return binary.parent


@pytest.fixture()
def fake_pw_record(tmp_path, monkeypatch):
    bin_dir = _write_fake(tmp_path)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv("FAKE_PW_PAYLOAD", raising=False)
    monkeypatch.delenv("FAKE_PW_CHUNK", raising=False)
    monkeypatch.delenv("FAKE_PW_DELAY", raising=False)
    monkeypatch.delenv("FAKE_PW_HOLD_S", raising=False)
    monkeypatch.delenv("FAKE_PW_SLEEP_AFTER", raising=False)
    return bin_dir


def _payload(tmp_path: Path, payload: bytes, name: str = "payload.pcm") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


def _s16_sine(seconds: float, amp: float, rate: int = SAMPLE_RATE,
              freq: float = 220.0) -> bytes:
    n = int(seconds * rate)
    return struct.pack(f"<{n}h", *[int(amp * 32767 * math.sin(
        2 * math.pi * freq * i / rate)) for i in range(n)])


def _f32_sine(seconds: float, amp: float, rate: int = 48000,
              freq: float = 220.0) -> bytes:
    n = int(seconds * rate)
    return struct.pack(f"<{n}f", *[amp * math.sin(
        2 * math.pi * freq * i / rate) for i in range(n)])


def _s32_sine(seconds: float, amp: float, rate: int = SAMPLE_RATE,
              freq: float = 220.0) -> bytes:
    n = int(seconds * rate)
    return struct.pack(f"<{n}i", *[int(amp * 2147483647 * math.sin(
        2 * math.pi * freq * i / rate)) for i in range(n)])


def _stereo_s16_sine(seconds: float, amp: float, rate: int = SAMPLE_RATE) -> bytes:
    n = int(seconds * rate)
    interleaved = []
    for i in range(n):
        left = int(amp * 32767 * math.sin(2 * math.pi * 220.0 * i / rate))
        right = int(amp * 0.8 * 32767 * math.sin(2 * math.pi * 330.0 * i / rate))
        interleaved.extend((left, right))
    return struct.pack(f"<{len(interleaved)}h", *interleaved)


def _bswap_s16(data: bytes) -> bytes:
    words = struct.unpack(f"<{len(data) // 2}H", data)
    return struct.pack(f">{len(words)}H", *words)


class FakeClock:
    """Deterministic monotonic clock: advances `step` seconds per call."""

    def __init__(self, step: float):
        self.t = 1000.0
        self.step = float(step)

    def __call__(self) -> float:
        self.t += self.step
        return self.t


def _read_all(capture):
    async def _collect():
        frames = []
        async for frame in capture.frames():
            frames.append(frame)
        return b"".join(frames)
    return asyncio.run(_collect())


def _split(pcm: bytes) -> dict:
    return split_peak(pcm, SAMPLE_RATE)


# --------------------------------------------------------------------------
# 1. the argv under test — production's own command, no dialect to be wrong about
# --------------------------------------------------------------------------
def test_bug_hw1_production_argv_is_unchanged_and_journaled_verbatim(
        fake_pw_record, tmp_path):
    command = pw_record_pcm_stream_command("mic1-node", sample_rate=16000)
    assert command == ["pw-record", "--target=mic1-node", "--rate", "16000",
                       "--channels", "1", "--format", "s16", "-"]
    capture = PipeWireCapture("mic1-node", sample_rate=16000)
    assert capture.argv == command
    assert capture.argv is not command, "argv must be a defensive copy"


def test_bug_hw1_numeric_object_id_is_still_refused():
    with pytest.raises(ValueError):
        pw_record_pcm_stream_command("54")


# --------------------------------------------------------------------------
# 2. the byte-rate discriminator (pure) — what the pipe MUST be doing to lie
# --------------------------------------------------------------------------
def test_bug_hw1_delivery_rate_class_names_the_known_classes():
    assert "as labelled" in delivery_rate_class(32_000)
    assert "s32le/16000/mono" in delivery_rate_class(64_000)
    assert "44100" in delivery_rate_class(88_200)
    assert "48000" in delivery_rate_class(96_000)
    assert "44100" in delivery_rate_class(176_400)
    assert "f32le/48000/mono" in delivery_rate_class(192_000)
    assert "f32le/48000/stereo" in delivery_rate_class(384_000)
    assert delivery_rate_class(123_456) is None
    # within the ±5 % naming tolerance
    assert "48000" in delivery_rate_class(96_000 * 1.04)


def test_bug_hw1_delivery_rate_judges_only_with_evidence():
    honest = classify_delivery_rate(33_600, 1.05)
    assert honest["expected_bytes_per_s"] == 32_000
    assert honest["delivery_ratio"] == pytest.approx(1.0, abs=0.05)
    assert honest["mismatch_suspect"] is False

    tripled = classify_delivery_rate(100_800, 1.05)   # s16/48k delivered as labelled
    assert tripled["mismatch_suspect"] is True
    assert "48000" in tripled["class"]

    float_rate = classify_delivery_rate(201_600, 1.05)  # f32/48k mono
    assert float_rate["mismatch_suspect"] is True
    assert "f32le/48000/mono" in float_rate["class"]

    zero_bytes = classify_delivery_rate(0, 1.05)
    assert zero_bytes["mismatch_suspect"] is None
    assert "no bytes" in zero_bytes["evidence"]

    burst = classify_delivery_rate(33_600, None)
    assert burst["mismatch_suspect"] is None
    assert burst["delivery_ratio"] is None

    too_small = classify_delivery_rate(2_000, 0.1)
    assert too_small["mismatch_suspect"] is None
    assert "insufficient evidence" in too_small["evidence"]


# --------------------------------------------------------------------------
# 3. the differential: known-format deliveries through the real capture path
# --------------------------------------------------------------------------
def test_bug_hw1_honest_stream_reassembles_byte_exactly(fake_pw_record, tmp_path,
                                                        monkeypatch):
    """Suspect (2) refuted: arbitrary write chunkings survive readexactly."""
    payload = _s16_sine(1.05, 0.5)  # 33600 bytes = 35 exact frames
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    monkeypatch.setenv("FAKE_PW_CHUNK", "7")  # 7-byte flushes, not frame-aligned
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.03))
    data = _read_all(capture)
    assert data == payload
    # and the honest reading is reported as honest
    facts = capture.stream_facts
    assert facts["bytes"] == len(payload)
    assert facts["delivery"]["mismatch_suspect"] is False
    assert facts["delivery"]["expected_bytes_per_s"] == 32_000
    assert facts["dropped_tail_bytes"] == 0
    assert facts["argv"][:1] == ["pw-record"]


def test_bug_hw1_honest_stream_odd_tail_is_counted_not_lost(fake_pw_record,
                                                             tmp_path, monkeypatch):
    payload = _s16_sine(1.05, 0.5) + b"\x01"  # one extra odd byte at the end
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.03))
    data = _read_all(capture)
    assert data == payload             # the partial tail is yielded, not dropped
    assert capture.xruns >= 1          # short read: a dropped tail shape, counted


def test_bug_hw1_f32_stream_reproduces_the_static_signature(fake_pw_record,
                                                             tmp_path, monkeypatch):
    """The BUG-HW1 shape: full-scale 'audio' out of a healthy-looking argv."""
    payload = _f32_sine(0.96, 0.5)     # 184320 B = 192 exact frames
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.005))
    data = _read_all(capture)
    assert len(data) == len(payload)
    # static statistics, measured — this is what "mad explosion" looks like
    assert pcm_peak(data) > 0.95
    assert frame_rms(data) > 0.4
    assert _split(data)["peak_steady"] > 0.95
    limiter = SoftLimiter()
    limiter.apply(data)
    # the limiter compresses but can never restore a mislabelled stream,
    # and its own counters show the abuse the owner saw (4.6% limited, or more)
    assert limiter.raw_peak > 0.95
    assert limiter.limited_samples / (len(data) // 2) > 0.046
    # the byte-rate names the mislabel: ~192000 B/s against a 32000 B/s label
    delivery = capture.stream_facts["delivery"]
    assert delivery["mismatch_suspect"] is True
    assert delivery["delivery_ratio"] > 5.0
    assert "f32le/48000" in delivery["class"]


def test_bug_hw1_s32_quiet_input_explodes_in_the_s16_view(fake_pw_record,
                                                           tmp_path, monkeypatch):
    """16k s32 read as s16: quiet room tone becomes full-scale noise."""
    payload = _s32_sine(1.05, 0.05)    # 67200 B = 70 exact frames
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.015))
    data = _read_all(capture)
    assert pcm_peak(data) > 0.9
    delivery = capture.stream_facts["delivery"]
    assert delivery["mismatch_suspect"] is True
    assert "s32le/16000/mono" in delivery["class"]


def test_bug_hw1_s16_at_48k_is_chipmunk_not_static(fake_pw_record,
                                                    tmp_path, monkeypatch):
    """A rate-only mismatch does NOT reproduce the explosion."""
    payload = _s16_sine(1.0, 0.5, rate=48000)   # 96000 B = 100 exact frames
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.01))
    data = _read_all(capture)
    assert pcm_peak(data) == pytest.approx(0.5, abs=0.01)   # peaks unchanged
    limiter = SoftLimiter()
    limiter.apply(data)
    assert limiter.limited_samples == 0                     # nothing clipped
    delivery = capture.stream_facts["delivery"]
    assert delivery["mismatch_suspect"] is True             # but the rate lies
    assert "48000" in delivery["class"]


def test_bug_hw1_stereo_interleave_preserves_peak(fake_pw_record,
                                                   tmp_path, monkeypatch):
    payload = _stereo_s16_sine(1.05, 0.5)       # 67200 B = 70 exact frames
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.015))
    data = _read_all(capture)
    assert pcm_peak(data) == pytest.approx(0.5, abs=0.01)
    delivery = capture.stream_facts["delivery"]
    assert delivery["mismatch_suspect"] is True
    assert "stereo" in delivery["class"]


def test_bug_hw1_bswapped_s16_evades_the_rate_check(fake_pw_record,
                                                     tmp_path, monkeypatch):
    """Endianness lies at the labelled byte-rate — the rate test is blind to
    it. Documented here so nobody mistakes ratio=1.0 for 'clean'."""
    payload = _bswap_s16(_s16_sine(1.05, 0.5))
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.03))
    data = _read_all(capture)
    assert pcm_peak(data) > 0.9                            # static signature
    assert capture.stream_facts["delivery"]["mismatch_suspect"] is False


def test_bug_hw1_production_path_saves_the_mislabel_not_a_clean_take(
        fake_pw_record, tmp_path, monkeypatch):
    """End to end through limiter + WavSink: garbage in, garbage saved —
    the processing chain (suspect 4) is faithful, never the fix and never
    the cause."""
    payload = _f32_sine(0.96, 0.5)
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.005))
    limiter = SoftLimiter()
    sink_path = tmp_path / "hw1.wav"
    sink = WavSink(sink_path)
    async def _run():
        async for frame in capture.frames():
            sink.write(limiter.apply(frame))
    asyncio.run(_run())
    seconds = sink.close()
    assert seconds == pytest.approx(len(payload) / 2 / SAMPLE_RATE)
    with __import__("wave").open(str(sink_path), "rb") as wav:
        assert wav.getframerate() == SAMPLE_RATE
        archived = wav.readframes(wav.getnframes())
    assert pcm_peak(archived) > 0.8        # limiter pulled 0.997 down, still static
    assert limiter.raw_peak > 0.95         # raw truth is kept, never concealed


# --------------------------------------------------------------------------
# 4. the 0-byte secondary: bytes abandoned in the pipe are counted
# --------------------------------------------------------------------------
def test_bug_hw1_aclose_counts_bytes_the_session_never_saw(fake_pw_record,
                                                            tmp_path, monkeypatch):
    payload = _s16_sine(0.5, 0.5)          # 16000 bytes written, then the child holds
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    monkeypatch.setenv("FAKE_PW_SLEEP_AFTER", "1")
    monkeypatch.setenv("FAKE_PW_HOLD_S", "30")
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.03))

    async def _one_frame_then_close():
        async for frame in capture.frames():
            # mid-stream: consumer stops here (a fast PTT tap) and closes
            break
        await capture.aclose()
    asyncio.run(_one_frame_then_close())
    # the child dies on SIGTERM; whatever it wrote stays readable in the pipe
    assert capture.dropped_tail_bytes >= len(payload) - FRAME_SAMPLES - 960
    assert capture.stream_facts is not None
    assert capture.stream_facts["dropped_tail_bytes"] == capture.dropped_tail_bytes


def test_bug_hw1_clean_eof_close_counts_nothing(fake_pw_record,
                                                 tmp_path, monkeypatch):
    payload = _s16_sine(0.5, 0.5)
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.03))

    async def _read_and_close():
        async for _frame in capture.frames():
            pass
        await capture.aclose()
    asyncio.run(_read_and_close())
    assert capture.dropped_tail_bytes == 0


def test_bug_hw1_stream_facts_present_and_self_describing_after_eof(
        fake_pw_record, tmp_path, monkeypatch):
    payload = _s16_sine(1.05, 0.5)
    _payload(tmp_path, payload)
    monkeypatch.setenv("FAKE_PW_PAYLOAD", str(tmp_path / "payload.pcm"))
    capture = PipeWireCapture("mic1-node", clock=FakeClock(0.03))
    _read_all(capture)
    facts = capture.stream_facts
    assert facts["argv"] == pw_record_pcm_stream_command("mic1-node",
                                                         sample_rate=16000)
    assert facts["expected"] == {"format": "s16le", "sample_rate": 16000,
                                 "channels": 1, "bytes_per_s": 32_000}
    assert facts["bytes"] == len(payload)
    assert facts["first_frame_latency_ms"] is not None
    assert facts["delivery"]["delivery_ratio"] == pytest.approx(1.0, abs=0.1)
    assert "pw-record does not report the negotiated format" in facts["note"]


# --------------------------------------------------------------------------
# 5. the dictation journal carries the facts (owner-visible, self-diagnosing)
# --------------------------------------------------------------------------
def _loud_frames(count: int = 40) -> list[bytes]:
    frame = struct.pack(f"<{FRAME_SAMPLES}h", *([6000] * FRAME_SAMPLES))
    return [frame] * count


class _FactsSource:
    """A capture source carrying BUG-HW1 stream facts (a real measurement,
    delivered through the same attribute the production PipeWireCapture
    populates)."""

    def __init__(self, frames, *, target="mic1-node", facts=None, dropped=0):
        self._frames = frames
        self.target = target
        self.stalled = False
        self.xruns = 0
        self.stream_facts = facts
        self.dropped_tail_bytes = dropped
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        self.closed = True


def _mislabelled_facts():
    return {
        "argv": ["pw-record", "--target=mic1-node", "--rate", "16000",
                 "--channels", "1", "--format", "s16", "-"],
        "expected": {"format": "s16le", "sample_rate": 16000,
                     "channels": 1, "bytes_per_s": 32_000},
        "bytes": 184_320,
        "wall_seconds_since_spawn": 0.96,
        "first_frame_latency_ms": 1490.0,
        "delivery": {"expected_bytes_per_s": 32_000,
                     "measured_bytes_per_s": 192_000.0,
                     "delivery_ratio": 6.0,
                     "class": "192000 B/s — f32le/48000/mono, s32le/48000/mono, or s16le/48000/stereo",
                     "mismatch_suspect": True,
                     "evidence": "184320 bytes over 0.96s of delivery = 192000 B/s vs expected 32000 B/s (ratio 6.00x)"},
        "dropped_tail_bytes": 0,
        "note": "pw-record does not report the negotiated format on stdout",
    }


def _dictation_config(tmp_path):
    from assistant.config import load_config

    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {**config.raw.get("transcribe", {}),
                                "inbox_dir": str(tmp_path / "inbox")}
    return config


def test_bug_hw1_dictation_journal_carries_stream_facts_and_names_the_mislabel(
        tmp_path, monkeypatch):
    from assistant import asr
    from assistant.live_client import ScriptedLiveTransport
    from assistant.store import Store
    from assistant.transcribe import DictationService

    def _must_not_run(*args, **kwargs):
        raise AssertionError("batch fallback ran unexpectedly")

    monkeypatch.setattr(asr, "transcribe_file", _must_not_run)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    facts = _mislabelled_facts()
    store = Store(tmp_path / "hw1.db")
    service = DictationService(_dictation_config(tmp_path), store, None)
    source = _FactsSource(_loud_frames(60), facts=facts)
    result = asyncio.run(service.dictate(
        source, transport_factory=ScriptedLiveTransport, sink=sink))

    capture = result.capture
    assert capture["stream_facts"]["argv"][:1] == ["pw-record"]
    assert capture["stream_facts"]["delivery"]["mismatch_suspect"] is True
    # the mislabel is named in the session's own notes — visible in ptt.result,
    # never silently saved as if it were a clean take
    assert any("BUG-HW1" in note for note in result.notes)
    # and the persona journal row carries it too (assist events / --recent)
    rows = [json.loads(row["detail"]) for row in
            store.list_persona_events(kind="capture.stats", limit=1)]
    assert rows and rows[0]["stream_facts"]["argv"][:1] == ["pw-record"]
    assert rows[0]["stream_facts"]["delivery"]["delivery_ratio"] == 6.0


def test_bug_hw1_honest_facts_add_no_mislabel_note(tmp_path, monkeypatch):
    from assistant import asr
    from assistant.live_client import ScriptedLiveTransport
    from assistant.store import Store
    from assistant.transcribe import DictationService

    def _must_not_run(*args, **kwargs):
        raise AssertionError("batch fallback ran unexpectedly")

    monkeypatch.setattr(asr, "transcribe_file", _must_not_run)
    events: list[dict] = []

    async def sink(event):
        events.append(event)

    facts = _mislabelled_facts()
    facts["delivery"] = {**facts["delivery"], "mismatch_suspect": False,
                         "measured_bytes_per_s": 32_100.0, "delivery_ratio": 1.003,
                         "class": "s16le/16000/mono — as labelled",
                         "evidence": "33600 bytes over 1.05s of delivery"}
    store = Store(tmp_path / "hw1-ok.db")
    service = DictationService(_dictation_config(tmp_path), store, None)
    source = _FactsSource(_loud_frames(60), facts=facts)
    result = asyncio.run(service.dictate(
        source, transport_factory=ScriptedLiveTransport, sink=sink))

    assert result.capture["stream_facts"]["delivery"]["mismatch_suspect"] is False
    assert not any("BUG-HW1" in note for note in result.notes)
