"""BUG-HW1 — daemon capture is static on real hardware: sandbox differential.

THE BUG (owner's Fedora 44 laptop, 2026-11-26): daemon-captured audio played
back as explosive static (`20261126-165648-0f964a.wav`: raw_peak 1.0, 4.6%
limited, ASR empty on every backend) while the owner's manual
`pw-record --rate 16000 --channels 1 --format s16 file.wav` from the SAME node
was clean. The daemon's form writes raw PCM to stdout with `--format s16 -`.

THE ROOT CAUSE (upstream sources read: PipeWire `src/tools/pw-cat.c` 1.4.6 and
master, libsndfile `src/sndfile.c`): `-` without `--raw` is NOT a raw pipe.
pw-cat opens it through libsndfile (`sf_open("-", …)` binds stdio via
`psf_set_stdio`), and `format_from_filename()` maps the filename `-` to the
**AU container** (sunau) — a 24-byte `.snd` header followed by **big-endian**
PCM16. The daemon read those bytes as s16le: every sample byte-swapped (a
×256 gain with wraparound) is explosive full-scale static; the header misread
as samples is the historical "start pop" — word 9 of the header is the rate
field `0x00003E80`, which reads as s16le sample −32706 = **0.9981** full
scale: the exact peak of the 2026-11-15 mute test. The `.wav` form is clean
because that extension selects the WAV container, whose PCM16 is
little-endian. Byte count = 24 + the labelled count — the pending
`/tmp/raw.pcm` "~160KB/5s = samples corrupt" variant.

THE FIX under test: `pw_record_pcm_stream_command` passes `--raw`, forcing
pw-cat's raw path (the stream's own s16le bytes, no container), plus a
container-header tripwire (`detect_container_prefix`) that refuses a
mislabelled stream instead of recording it, `capture.stream_open` journaling
(argv + negotiated stream facts) and `capture.starved` for 0-byte captures.

THE HARNESS (the dispatch's method): a fake `pw-record` that behaves like
upstream pw-cat's dispatch — with `--raw` in its argv it dumps the prepared
s16le stream raw; without it, it wraps the same stream in the real AU form
(header + byte-swapped PCM). The REAL `PipeWireCapture` (real spawn, real
`readexactly` framing, the frozen `SoftLimiter`, the real `WavSink`) consumes
it. Measured signatures (5 s take, ~11% voiced, digital silence between —
`over-knee` = share of samples over the frozen 0.60 knee, `spikes` = isolated
full-scale samples per 1000):

  variant                bytes/5s   peak     over-knee  spikes   fits the bug
  clean s16le (raw)        160000   0.3535   0.0%       0.00/k   control
  AU mislabel (old `-`)    160024   1.0000   5.6%       0.59/k   ALL facts
  48k s16 mislabel         480000   0.3535   0.0%       0.00/k   refuted (ears)
  16k s32 mislabel         320000   1.0000   20.0%      10.02/k  count refutes
  48k f32 mislabel         960000   1.0000   2.6%       2.83/k   count refutes
  odd-shift framing        160001   1.0000   5.6%       0.59/k   refuted below

Only the AU form reproduces EVERY evidence fact at once: explosive static,
raw_peak exactly 1.0, a few-percent limited band (the owner's 4.6%), a
byte count of labelled-size + 24 (the "~160KB/5s" hint), and the 0.9981
start pop at a fixed position. A rate mismatch is slowed speech, not
static (the owner's ears settle that); s32/f32 mislabels double or sextuple
the byte count (the hints table's 320KB/960KB rows). An odd pipe-framing
shift ALSO reads as static — statistics alone cannot separate it from the
AU form — but it is excluded by fact: the owner's manual raw test exploded
with NO daemon framing anywhere in the loop, and the AU header names itself
(magic `.snd` + the 0.9981 word), which the tripwire keys on.

Only the owner's hardware can confirm: the byte count of `/tmp/raw.pcm`
(~160024/5 s = AU), the first 24 bytes of the evidence WAVs' PCM (the
byte-swapped header, peak 0.9981), and that `--raw` plays clean there.
The owner-runnable steps are in `reports/RPT-J-BUGFIX-HW1-20261126.md`.
"""

from __future__ import annotations

import asyncio
import math
import os
import random
import struct
import wave

import pytest

from assistant import capture as capture_mod
from assistant.capture import (
    BYTES_PER_SAMPLE,
    PipeWireCapture,
    SoftLimiter,
    WavSink,
    detect_container_prefix,
    frame_rms,
    negotiated_stream_facts,
    pcm_peak,
    pw_record_pcm_stream_command,
)

RATE = 16000
SECONDS = 5
LABEL_BYTES = RATE * SECONDS * BYTES_PER_SAMPLE   # 160000 — the "~160KB/5s" hint


# ---------------------------------------------------------------------------
# source audio + the byte forms each mislabel delivers
# ---------------------------------------------------------------------------
def _speech_pcm(seconds: float = SECONDS, rate: int = RATE, seed: int = 7,
                amp: float = 0.35) -> bytes:
    """A dictation-shaped take: short utterances, EXACT digital silence between.

    ~11% voiced — the occupancy of the owner's evidence takes, which is what
    puts the mislabel's limited-ratio in the evidence's few-percent band
    instead of a full-utterance take's 40%.
    """
    rnd = random.Random(seed)
    count = int(rate * seconds)
    samples = []
    for i in range(count):
        t = i / rate
        phase = t % 1.5
        if 0.25 < phase < 0.42:
            env = math.sin(math.pi * (phase - 0.25) / 0.17)
            s = amp * env * math.sin(2 * math.pi * 180 * t)
            s += 0.004 * (rnd.random() * 2 - 1)
            samples.append(max(-32768, min(32767, int(s * 32767))))
        else:
            samples.append(0)
    return struct.pack(f"<{count}h", *samples)


def _au_header(rate: int = RATE, channels: int = 1, encoding: int = 3,
               size: int = 0xFFFFFFFF) -> bytes:
    """The exact 24-byte header libsndfile writes for `-` in AU mode."""
    return struct.pack(">4s5I", b".snd", 24, size, encoding, rate, channels)


def _swap16(data: bytes) -> bytes:
    """What s16le PCM looks like after libsndfile's big-endian AU write."""
    buf = bytearray(data)
    buf[0::2], buf[1::2] = buf[1::2], buf[0::2]
    return bytes(buf)


def _static_stats(raw: bytes) -> dict:
    """The signature numbers this harness compares across variants."""
    count = len(raw) // 2
    samples = struct.unpack(f"<{count}h", raw[: count * 2])
    over_knee = sum(1 for x in samples if abs(x) > 0.6 * 32768)
    spikes = sum(1 for i in range(1, count - 1)
                 if abs(samples[i]) >= 0.98 * 32767
                 and abs(samples[i - 1]) < 0.5 * 32767
                 and abs(samples[i + 1]) < 0.5 * 32767)
    limiter = SoftLimiter()
    for offset in range(0, len(raw) - 959, 960):
        limiter.apply(raw[offset:offset + 960])
    limited = limiter.stats()
    return {
        "bytes": len(raw),
        "peak": pcm_peak(raw),
        "rms": frame_rms(raw),
        "over_knee": over_knee / max(1, count),
        "spikes_per_k": 1000 * spikes / max(1, count),
        "limiter": limited,
    }


# ---------------------------------------------------------------------------
# the fake pw-record: upstream pw-cat's dispatch, replayed faithfully
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_pw_record(tmp_path, monkeypatch):
    """A fake `pw-record` on PATH that behaves like upstream pw-cat.

    With `--raw` in its argv (what production now passes) it dumps the
    prepared s16le payload RAW to stdout — pw-cat's `setup_raw`/`setup_pipe`
    path. Without `--raw` (the daemon's old form) it wraps the same payload
    in the real AU form: the 24-byte `.snd` header + big-endian PCM, exactly
    what `sf_open("-", …)` wrote on the owner's laptop. `FAKE_PW_RECORD_MODE`
    overrides the dispatch (`raw` / `au` / `hold`).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    payload = tmp_path / "stream.bin"
    script = bin_dir / "pw-record"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import os, struct, sys, time\n"
        "payload = open(os.environ['FAKE_PW_RECORD_PAYLOAD'], 'rb').read()\n"
        "mode = os.environ.get('FAKE_PW_RECORD_MODE', 'auto')\n"
        "if mode == 'auto':\n"
        "    mode = 'raw' if '--raw' in sys.argv else 'au'\n"
        "if mode == 'au':\n"
        "    buf = bytearray(payload)\n"
        "    buf[0::2], buf[1::2] = buf[1::2], buf[0::2]\n"
        "    header = struct.pack('>4s5I', b'.snd', 24, 0xFFFFFFFF, 3, 16000, 1)\n"
        "    sys.stdout.buffer.write(header + bytes(buf))\n"
        "elif mode == 'raw':\n"
        "    sys.stdout.buffer.write(payload)\n"
        "sys.stdout.buffer.flush()\n"
        "os.close(1)\n"          # finished writing; the session stays claimed
        "time.sleep(3600)\n")
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_PW_RECORD_PAYLOAD", str(payload))

    def emit(data: bytes, mode: str | None = None) -> None:
        payload.write_bytes(data)
        if mode is not None:
            monkeypatch.setenv("FAKE_PW_RECORD_MODE", mode)

    return emit


async def _collect(target: str = "test-mic", *, stall_s: float = 2.0):
    """Run the real PipeWireCapture to stream end (the daemon's byte path)."""
    cap = PipeWireCapture(target, stall_timeout_s=stall_s)
    frames = []
    async for frame in cap.frames():
        frames.append(frame)
    await cap.aclose()
    return cap, b"".join(frames), frames


# ---------------------------------------------------------------------------
# 1. the differential: which mismatch reproduces the bug's statistics
# ---------------------------------------------------------------------------
async def test_bug_hw1_the_au_stdout_form_reproduces_the_hardware_signature(
        fake_pw_record, monkeypatch):
    """THE proof: the old argv's stream, through the daemon's own pipeline,
    reproduces every evidence fact at once."""
    source = _speech_pcm()
    fake_pw_record(source)
    # Pre-fix world: the argv without --raw (what the daemon ran on hardware),
    # and the tripwire not yet keyed to refuse it (the old code had none).
    monkeypatch.setattr(
        capture_mod, "pw_record_pcm_stream_command",
        lambda target, *, sample_rate=RATE: (
            ["pw-record", f"--target={target}", "--rate", str(sample_rate),
             "--channels", "1", "--format", "s16", "-"]))
    monkeypatch.setattr(capture_mod, "detect_container_prefix",
                        lambda _prefix: None)

    _cap, raw, _frames = await _collect()

    # Suspect 2, framing: the daemon's readexactly path is byte-faithful —
    # the static is IN the bytes, carried untouched, never manufactured here.
    assert raw == _au_header() + _swap16(source)

    stats = _static_stats(raw)
    # Evidence fact 1: raw_peak 1.0 as the evidence recorded it (the house's
    # 4-dp rounding: byte-swap drives samples to ±full scale, wraparound).
    assert round(stats["peak"], 4) == 1.0
    # Evidence fact 2: explosive static, not speech — a several-fold RMS jump
    # over the same take read as its true s16le self, plus isolated full-scale
    # spike texture the clean take has none of.
    clean = _static_stats(source)
    assert stats["rms"] > 3 * clean["rms"]
    assert clean["spikes_per_k"] == 0 and stats["spikes_per_k"] > 0
    # Evidence fact 3: "4.6% limited" — the frozen limiter fires on a few
    # percent of samples while raw_peak is 1.0 (a sparse take's band).
    assert stats["limiter"]["raw_peak"] == 1.0
    assert 0.02 <= stats["limiter"]["limited_ratio"] <= 0.10
    # Evidence fact 4: the pending byte count — labelled size + the 24-byte
    # header (5 s ≈ 160024 B, the "~160KB/5s = samples corrupt" row).
    assert stats["bytes"] == LABEL_BYTES + 24
    # Evidence fact 5: the mute-test "start pop" of exactly 0.9981 is the AU
    # header's rate field (word 9 = 0x00003E80 read as s16le = −32706).
    header_samples = struct.unpack("<12h", _au_header())
    assert header_samples[9] == -32706
    assert abs(header_samples[9]) / 32768 == pytest.approx(0.9981, abs=5e-5)
    assert pcm_peak(_au_header()) == pytest.approx(0.9981, abs=5e-5)


async def test_bug_hw1_the_raw_fix_form_passes_the_take_through_untouched(
        fake_pw_record):
    """The fix: production argv carries --raw, the fake's raw dispatch fires,
    and the same pipeline delivers the take byte-for-byte, clean."""
    source = _speech_pcm()
    fake_pw_record(source)

    cap, raw, _frames = await _collect()

    assert "--raw" in cap._command          # the argv that did this
    assert raw == source                    # byte-faithful end to end
    stats = _static_stats(raw)
    assert stats["peak"] < 0.5              # speech scale, never static
    assert stats["spikes_per_k"] == 0
    assert stats["limiter"]["limited_samples"] == 0  # frozen curve, below knee


async def test_bug_hw1_rate_mismatch_is_slowed_speech_not_static(fake_pw_record):
    """Suspect 1, rate half: 48 kHz s16 read at the 16 kHz label keeps clean
    samples (the owner hears a slow voice, never an explosion) and triples
    the byte count — the hint table's ~480KB/5s row."""
    fake_pw_record(_speech_pcm(seconds=SECONDS, rate=48000))

    _cap, raw, _frames = await _collect()

    assert len(raw) == 3 * LABEL_BYTES       # ~480KB/5s
    stats = _static_stats(raw)
    assert stats["peak"] < 0.5
    assert stats["spikes_per_k"] == 0
    assert stats["over_knee"] == 0.0


async def test_bug_hw1_width_mismatches_are_static_but_leave_their_count(
        fake_pw_record):
    """Suspect 1, width/format half: s32 and f32 mislabels ARE static-ish with
    raw_peak 1.0 — but each doubles or sextuples the byte count (the hints
    table's ~320KB and ~960KB rows) and neither carries the `.snd` header
    signature that names the AU form."""
    source = _speech_pcm()
    samples = struct.unpack(f"<{len(source) // 2}h", source)
    rnd = random.Random(99)
    s32 = b"".join(struct.pack("<i", x * 65536 + rnd.randint(-32767, 32767))
                   for x in samples)
    f32_48k = struct.pack(f"<{len(samples) * 3}f",
                          *([x / 32768 for x in samples] * 3))

    fake_pw_record(s32, mode="raw")
    _, raw_s32, _ = await _collect()
    fake_pw_record(f32_48k, mode="raw")
    _, raw_f32, _ = await _collect()

    assert len(raw_s32) == 2 * LABEL_BYTES   # ~320KB/5s = "16k s32"
    assert len(raw_f32) == 6 * LABEL_BYTES   # ~960KB/5s = "48k float"
    for raw in (raw_s32, raw_f32):
        stats = _static_stats(raw)
        assert round(stats["peak"], 4) == 1.0   # static scale ...
        assert stats["spikes_per_k"] > 0
        assert detect_container_prefix(raw) is None  # ... but no `.snd` name
    # The AU form is the only one that matches the pending ~160KB count AND
    # carries a self-describing header (asserted in the signature test).


async def test_bug_hw1_a_misaligned_source_stream_is_static_but_names_itself(
        fake_pw_record):
    """Suspect 2, residual: a 1-byte-offset stream ALSO reads as static, so
    spike statistics alone cannot convict the AU form. It is excluded by
    facts, not vibes: the owner's manual raw test exploded with no daemon
    framing anywhere (so the corruption predates any reader), and the AU
    form's count is labelled+24 vs labelled+1 with a `.snd` name the
    tripwire keys on. This test keeps that distinction honest."""
    source = _speech_pcm()
    fake_pw_record(b"\x2a" + source, mode="raw")

    _cap, raw, _frames = await _collect()

    assert len(raw) == LABEL_BYTES + 1       # +1: never +24
    stats = _static_stats(raw)
    assert round(stats["peak"], 4) == 1.0
    assert stats["spikes_per_k"] > 0             # static shape
    # But no container signature to mistake it for PCM or vice versa:
    assert detect_container_prefix(raw) is None


# ---------------------------------------------------------------------------
# 2. suspects 2 and 4: framing and processing are byte-faithful
# ---------------------------------------------------------------------------
async def test_bug_hw1_readexactly_framing_is_byte_faithful(fake_pw_record):
    """readexactly(960) neither drops, duplicates nor misaligns bytes: every
    frame is exactly one frame wide, the tail is counted as an xrun, and the
    concatenation is the stream. Whatever the bytes ARE, they pass through."""
    source = _speech_pcm()
    fake_pw_record(source)

    cap, raw, frames = await _collect()

    assert raw == source
    assert all(len(f) == 960 for f in frames[:-1])
    assert len(frames[-1]) <= 960
    assert cap.xruns == 1                    # the partial tail, counted


async def test_bug_hw1_the_sink_and_frozen_limiter_add_no_static_of_their_own(
        fake_pw_record, tmp_path, monkeypatch):
    """Suspect 4, processing between pipe and WavSink: the order the daemon
    uses (measure → frozen SoftLimiter → sink) is deterministic and
    byte-preserving — clean in, clean out; static in, static out (carried,
    never hidden, never manufactured)."""
    source = _speech_pcm(seconds=1)
    fake_pw_record(source, mode="raw")
    _cap, raw_clean, frames_clean = await _collect()

    def through_pipeline(frames, path):
        limiter = SoftLimiter()
        sink = WavSink(path)
        out = []
        for frame in frames:
            pcm_peak(frame)                  # the daemon's raw measurement
            kept = limiter.apply(frame)      # the frozen curve
            sink.write(kept)
            out.append(kept)
        sink.close()
        return b"".join(out)

    processed = through_pipeline(frames_clean, tmp_path / "clean.wav")
    assert processed == raw_clean            # below the knee: identity
    with wave.open(str(tmp_path / "clean.wav"), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == processed

    # The same pipeline on the AU static neither rescues nor worsens it: the
    # archive records exactly what the limiter passed — the static is the
    # stream's, and the journal (not the WAV) is where it gets named. (The
    # tripwire would refuse this stream outright; here we measure what the
    # pre-fix pipeline DID with it.)
    monkeypatch.setattr(capture_mod, "detect_container_prefix",
                        lambda _prefix: None)
    fake_pw_record(_au_header() + _swap16(source), mode="raw")
    _cap2, _raw_static, frames_static = await _collect()
    static_out = through_pipeline(frames_static, tmp_path / "static.wav")
    limiter = SoftLimiter()
    expected = b"".join(limiter.apply(f) for f in frames_static)
    assert static_out == expected
    # The frozen curve compresses the static toward its ceiling (0.89) — it
    # mitigates, it never conceals: the wav still carries the explosion.
    assert 0.85 <= pcm_peak(static_out) <= 0.90


# ---------------------------------------------------------------------------
# 3. the fix's guards: argv, tripwire, journaling
# ---------------------------------------------------------------------------
def test_bug_hw1_production_argv_asks_for_the_true_raw_stream():
    command = pw_record_pcm_stream_command("alsa_input.test.Mic1__source")
    assert command == ["pw-record", "--target=alsa_input.test.Mic1__source",
                       "--rate", "16000", "--channels", "1",
                       "--format", "s16", "--raw", "-"]
    # `--raw` is load-bearing: it is what selects pw-cat's raw stdout path
    # over libsndfile's AU-on-stdio. Keep the order: options before `-`.
    assert command.index("--raw") < command.index("-")
    with pytest.raises(ValueError, match="object\\.serial|node\\.name"):
        pw_record_pcm_stream_command("42")


async def test_bug_hw1_container_tripwire_refuses_a_mislabelled_stream(
        fake_pw_record, journal_stream):
    """Even if the argv regressed, a stream that opens as container bytes is
    refused and named — never recorded as if it were raw s16le."""
    fake_pw_record(_speech_pcm(seconds=1), mode="au")

    cap, raw, frames = await _collect()

    assert frames == [] and raw == b""
    assert cap.stream_mismatch == {"container": "au",
                                   "command": cap._command}
    logged = journal_stream.getvalue()
    assert "capture.format_mismatch" in logged
    assert " au container" in logged
    assert "capture.starved" not in logged, (
        "the mismatch line already explains the zero bytes — never two "
        "explanations for one fact")


async def test_bug_hw1_capture_start_journals_argv_and_stream_facts(
        fake_pw_record, journal_stream, monkeypatch):
    """capture.stream_open carries the exact argv and the negotiated stream
    facts at capture start — the next hardware report reads facts."""
    monkeypatch.setattr(
        capture_mod, "negotiated_stream_facts",
        lambda **_kw: {"available": True, "node_id": 77, "streams_visible": 1,
                       "format": "S16", "rate": 16000, "channels": 1})
    fake_pw_record(_speech_pcm(seconds=1), mode="raw")

    _cap, _raw, _frames = await _collect()

    line = next(line for line in journal_stream.getvalue().splitlines()
                if "capture.stream_open" in line)
    assert "argv=pw-record --target=test-mic --rate 16000 --channels 1" in line
    assert "--format s16 --raw -" in line
    assert "expected=format:s16le rate:16000 channels:1" in line
    assert "format=S16 rate=16000 channels=1 node_id=77" in line


async def test_bug_hw1_stream_open_journals_honest_unavailable_facts(
        fake_pw_record, journal_stream):
    """Off-hardware (no pw-dump): the line says so — never a guessed format."""
    fake_pw_record(_speech_pcm(seconds=1), mode="raw")

    _cap, _raw, _frames = await _collect()

    line = next(line for line in journal_stream.getvalue().splitlines()
                if "capture.stream_open" in line)
    assert "negotiated[not available:" in line


def test_bug_hw1_negotiated_stream_facts_parses_pw_dump_and_stays_honest(
        monkeypatch):
    dump = (
        '[{"id": 12, "type": "PipeWire:Interface:Node", "info": {"props": '
        '{"node.name": "alsa_input.test.Mic1__source"}}},'
        ' {"id": 77, "type": "PipeWire:Interface:Node", "info": {"props": '
        '{"node.name": "pw-record", "application.name": "pw-record"}, '
        '"params": {"Format": [{"mediaType": "audio", "mediaSubtype": "raw", '
        '"format": "S16", "rate": 16000, "channels": 1}]}}}]')

    class _Out:
        returncode = 0
        stdout = dump
        stderr = ""

    monkeypatch.setattr(capture_mod, "tool_available", lambda name: True)
    facts = negotiated_stream_facts(runner=lambda *a, **k: _Out(), attempts=1)
    assert facts == {"available": True, "node_id": 77, "streams_visible": 1,
                     "format": "S16", "rate": 16000, "channels": 1}

    def boom(*_a, **_k):
        raise OSError("no pipewire here")

    facts = negotiated_stream_facts(runner=boom, attempts=1)
    assert facts["available"] is False and facts["reason"]

    monkeypatch.setattr(capture_mod, "tool_available", lambda name: False)
    facts = negotiated_stream_facts(attempts=1)
    assert facts["available"] is False and "pw-dump" in facts["reason"]


# ---------------------------------------------------------------------------
# 4. the secondary symptom: 0-byte captures are named, not mysterious
# ---------------------------------------------------------------------------
async def test_bug_hw1_zero_byte_fast_stop_is_journaled_as_starved(
        fake_pw_record, journal_stream, monkeypatch):
    """First-frame latency (~1.5 s graph warmup) starves fast stops: the
    session ends with zero bytes. That is now a journal fact — argv, target
    and the warmup explanation — not a mystery empty take."""
    fake_pw_record(b"", mode="hold")         # stream open, never a sample

    cap = PipeWireCapture("test-mic", stall_timeout_s=0.2)
    task = asyncio.ensure_future(cap.frames().__aiter__().__anext__())
    await asyncio.sleep(0.1)                 # spawn + stream_open journal
    await cap.aclose()                       # the fast stop
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, StopAsyncIteration):
        pass

    logged = journal_stream.getvalue()
    assert "capture.starved" in logged
    assert "graph warmup" in logged
    assert "argv=pw-record --target=test-mic" in logged

    # And a capture that delivered bytes is never misreported as starved.
    journal_stream.seek(0)
    journal_stream.truncate()
    fake_pw_record(_speech_pcm(seconds=0.2), mode="raw")
    _cap, raw, _frames = await _collect()
    assert raw and "capture.starved" not in journal_stream.getvalue()


# ---------------------------------------------------------------------------
# 5. the tripwire's recognition is strict, not trigger-happy
# ---------------------------------------------------------------------------
def test_bug_hw1_detect_container_prefix_is_strict():
    assert detect_container_prefix(_au_header()) == "au"
    assert detect_container_prefix(_au_header() + b"\x00" * 100) == "au"
    assert detect_container_prefix(b"RIFF\x24\x00\x00\x00WAVEfmt ") == "wav"
    # Real audio that merely starts with similar bytes is never misjudged:
    assert detect_container_prefix(_speech_pcm(seconds=0.01)) is None
    assert detect_container_prefix(b".snd" + b"\xff" * 20) is None
    assert detect_container_prefix(struct.pack(">4s5I", b".snd", 24, 0, 3,
                                               0, 1)) is None
    assert detect_container_prefix(b"RIFF\x24\x00\x00\x00AVI fmt") is None
    assert detect_container_prefix(b".sn") is None      # short: undecided
