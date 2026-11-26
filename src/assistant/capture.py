"""PipeWire capture helpers (§3.4) — the Wayland-specific edge stays here.

Phase 0: detection + command construction (everything `assist doctor`
needs to report honest facts about the Fedora machine). Session-scoped
recording itself is Phase 1. One capture process per session when it
lands — never a process spawn per chunk.

The trap that costs people an evening (GETTING-STARTED Step 3):
`pw-record --target=` takes object.serial or node.name — NOT object.id.
Passing the ID silently records the default device. Node parsing below
keeps serial + name, and deliberately never uses the bare ID as a target.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import shutil
import struct
import subprocess
import time
import wave
from array import array
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

from .config import ensure_private_dir

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # s16le mono — what the Live API wants natively (§3.4)


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def parse_wpctl_status(text: str) -> dict[str, list[dict]]:
    """Extract {section: [{id, name, is_default}]} from `wpctl status`.

    Names here are display names; the record target must be resolved to
    node.name/object.serial via `wpctl inspect` on the real machine.

    BUG 7 follow-up: real `wpctl status` prefixes every line with tree
    glyphs (" │  *   53. …"), which the old line-anchored regexes never
    matched — the parser only worked on flat sample text. `search` + the
    section-name-at-end rule handle both shapes.
    """
    sections: dict[str, list[dict]] = {}
    current = None
    in_audio_group = False
    for line in text.splitlines():
        # BH-K13: real `wpctl status` has top-level Audio / Video /
        # Settings groups, EACH with Sinks/Sources of its own, plus
        # Devices, Streams and "Default Configured Devices" blocks whose
        # entries also look like `N. name`. The old parser keyed sections
        # by name alone and never reset on unknown headers, so the laptop
        # camera (Video → Sources) merged into the audio sources offered
        # as microphones, and Streams/Settings entries polluted whatever
        # section came last. Track the group; collect Audio only; any
        # header line that is not one of ours ends the current section.
        group = line.strip()
        if group in ("Audio", "Video", "Settings"):
            in_audio_group = group == "Audio"
            current = None
            continue
        header = re.search(r"\b(Sinks|Sources|Sink endpoints|Source endpoints):\s*$", line)
        if header:
            current = header.group(1) if in_audio_group else None
            if current:
                sections.setdefault(current, [])
            continue
        if line.rstrip().endswith(":"):
            current = None  # Devices / Streams / Clients / Default Configured…
            continue
        entry = re.search(r"([*]?)\s*(\d+)\.\s+(.+)", line)
        if entry and current:
            sections[current].append({
                "id": int(entry.group(2)),
                "is_default": entry.group(1) == "*",
                "display_name": entry.group(3).split("[")[0].strip(),
            })
    return sections


def list_nodes(runner=subprocess.run) -> dict:
    """Live node list on a Fedora box; structured 'unavailable' elsewhere."""
    if not tool_available("wpctl"):
        return {"available": False, "reason": "wpctl not found (wireplumber) — "
                "expected on the Fedora target, absent in containers"}
    try:
        out = runner(["wpctl", "status"], capture_output=True, text=True, timeout=10)
        return {"available": out.returncode == 0, "nodes": parse_wpctl_status(out.stdout)}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def list_pw_nodes(runner=subprocess.run) -> list[dict]:
    """Flattened node list for `assist meeting setup` (BUG 7, 2026-10-20).

    The CLI imports this helper (cli.py `_meeting_command`); a dead-code sweep
    removed it without seeing the late import, so `assist meeting setup` died
    with ImportError while 1,280 tests stayed green. Each node is
    {id, name, kind, is_default} — display names from `wpctl status`, exactly
    what meeting_setup_text() prints. An empty list is honest "nothing found"
    (container/absent wpctl), never an exception.
    """
    status = list_nodes(runner=runner)
    if not status.get("available"):
        return []
    out: list[dict] = []
    for section, kind in (("Sinks", "sink"), ("Sink endpoints", "sink"),
                          ("Sources", "source"), ("Source endpoints", "source")):
        for node in status.get("nodes", {}).get(section, []):
            out.append({"id": node["id"], "name": node["display_name"],
                        "kind": kind, "is_default": bool(node.get("is_default"))})
    return out


# --------------------------------------------------------------------------
# PCM utilities (Phase 1): energy, rolling buffer, WAV sink, VAD gate
# --------------------------------------------------------------------------
def frame_rms(pcm: bytes) -> float:
    """Normalised RMS of an s16le frame (0.0 silence … 1.0 clipping)."""
    if len(pcm) < 2:
        return 0.0
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[: len(pcm) - len(pcm) % 2])
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768


def pcm_peak(pcm: bytes) -> float:
    """Normalised peak amplitude of an s16le buffer (0.0 silence … 1.0 clip).

    The per-session level check (BUG 6 diagnostics): bytes tell you a process
    wrote something; peak tells you a human could have been heard in it.
    """
    if len(pcm) < 2:
        return 0.0
    samples = struct.unpack(f"<{len(pcm) // 2}h", pcm[: len(pcm) - len(pcm) % 2])
    return max((abs(s) for s in samples), default=0) / 32768


#: How long after stream open a sample can still be called a START transient
#: (owner measurement 2026-11-15). The mute test proved the full-scale sample
#: survives node mute — rms 0.007 with peak 0.9981 — so it is injected at or
#: after stream open, not carried by room sound. 100 ms is the synthetic
#: worst case (a one-frame pop at 50 ms) plus one frame of margin; the owner's
#: three kept takes re-derive it with `scripts/frame_probe.py`, whose
#: `recommended_start_pop_ms` is the number to set here. Changing it moves no
#: audio: it only decides which frames may be called "the first speech frame"
#: and which full-scale frames are transport rather than the owner.
START_POP_MS = 100


def split_peak(pcm: bytes, sample_rate: int = SAMPLE_RATE,
               skip_ms: int = START_POP_MS, *,
               full_scale: float = 0.99, frame_ms: int = 50) -> dict:
    """Peak of EVERYTHING vs peak with the start transient removed.

    A single `peak` cannot tell a start pop from a hot voice, and the mute test
    showed exactly that: rms said the node was silent, peak said full scale.
    Both readings are reported — the full one is never hidden, the steady one
    is the one a diagnosis may anchor on.

    "Steady" is deliberately not "everything after N ms": that would throw away
    a real first syllable and it would report a silent steady span for a take
    shorter than the window. It is **every frame that is not a start
    transient** — a full-scale frame inside the first `skip_ms`. Speech inside
    the window is kept, so the steady peak always describes the person, and a
    pop never describes anything.
    """
    frame_bytes = max(2, int(sample_rate * frame_ms / 1000) * BYTES_PER_SAMPLE)
    frame_bytes -= frame_bytes % BYTES_PER_SAMPLE
    steady_peak = 0.0
    steady_bytes = 0
    for start in range(0, len(pcm), frame_bytes):
        frame = pcm[start:start + frame_bytes]
        if len(frame) < 2:
            continue
        start_ms = start / BYTES_PER_SAMPLE / sample_rate * 1000
        is_transient = start_ms < skip_ms and pcm_peak(frame) >= full_scale
        if is_transient:
            continue
        steady_peak = max(steady_peak, pcm_peak(frame))
        steady_bytes += len(frame)
    return {
        "peak_full": round(pcm_peak(pcm), 4),
        "peak_steady": round(steady_peak, 4),
        "start_pop_ms": int(skip_ms),
        "steady_bytes": steady_bytes,
    }


class StartTransientGate:
    """Separates a stream-open transient from the person speaking.

    The gate exists because one full-scale sample at stream open persuaded the
    whole capture path that speech had begun: `first_speech_frame_s` read 0.0
    on real takes and the energy gate opened on a click. It answers both
    without touching the audio — every frame is still recorded (audio is never
    lost), and a SPEECH-LEVEL frame inside the hold-off is kept for the uplink,
    because a hold-off that costs a syllable is a worse bug than the pop:

    * no frame inside the hold-off can be the FIRST SPEECH FRAME;
    * a FULL-SCALE frame inside the hold-off is transport, not the owner, and
      is recorded but not uploaded;
    * nothing here changes `peak`/`rms` accounting: the limiter and the peaks
      still see the true signal, transient included.
    """

    FULL_SCALE = 0.99

    def __init__(self, *, sample_rate: int = SAMPLE_RATE,
                 holdoff_ms: int = START_POP_MS,
                 full_scale: float = FULL_SCALE) -> None:
        self.sample_rate = sample_rate
        self.holdoff_ms = max(0, int(holdoff_ms))
        self.full_scale = float(full_scale)
        self.holdoff_frames = 0
        self.transients = 0

    def classify(self, frame: bytes, start_ms: float) -> dict:
        """What this frame is, and whether the hold-off covers it."""
        in_holdoff = start_ms < self.holdoff_ms
        peak = pcm_peak(frame)
        transient = bool(in_holdoff and peak >= self.full_scale)
        if in_holdoff:
            self.holdoff_frames += 1
        if transient:
            self.transients += 1
        return {"in_holdoff": in_holdoff, "transient": transient, "peak": peak}

    def stats(self) -> dict:
        return {"holdoff_ms": self.holdoff_ms, "full_scale": self.full_scale,
                "holdoff_frames": self.holdoff_frames,
                "transients": self.transients}


def live_level_check(target: str | None = None, seconds: float = 1.2,
                     runner=subprocess.run, *,
                     skip_ms: int = START_POP_MS) -> dict:
    """Brief real-microphone level probe for `assist doctor` (BUG 6).

    Records ~`seconds` of raw PCM from the configured (or default) source and
    reports bytes + peak + RMS — the "speak now and watch it move" check that
    turns 'the mic should work' into facts. Structurally honest off-Fedora:
    no pw-record => {'available': False, reason}, never a guess.
    """
    if not tool_available("pw-record"):
        return {"available": False, "target": target or "(default source)",
                "argv": ["pw-record"],
                "reason": "pw-record not found (pipewire-utils) — level check "
                          "runs on the Fedora target, absent in containers"}
    command = pw_record_pcm_stream_command(target, sample_rate=SAMPLE_RATE)
    data = b""
    detail = ""
    try:
        # pw-record runs until killed; the timeout IS the recording window.
        proc = runner(command, capture_output=True, timeout=seconds + 2.0)
        data = proc.stdout or b""
        if proc.returncode not in (0, None) and not data:
            err = (proc.stderr or b"")[:200].decode("utf-8", "replace")
            return {"available": False, "target": target or "(default source)",
                    "argv": list(command),
                    "reason": f"pw-record exited {proc.returncode}: {err}"}
    except subprocess.TimeoutExpired as exc:
        data = exc.stdout or b""
        detail = f"recorded {seconds:.1f}s"
    except Exception as exc:
        return {"available": False, "target": target or "(default source)",
                "argv": list(command),
                "reason": f"{type(exc).__name__}: {exc}"}
    peak = pcm_peak(data)
    split = split_peak(data, SAMPLE_RATE, skip_ms)
    # BUG-HW1: the bytes-vs-label discriminator, for owners diagnosing a
    # "the mic captures static" report without re-running anything. The
    # wall window is the probe window (pw-record runs until the timeout).
    return {
        "available": True,
        "target": target or "(default source)",
        "argv": list(command),
        "seconds": round(len(data) / BYTES_PER_SAMPLE / SAMPLE_RATE, 2),
        "bytes": len(data),
        # `peak` stays for every existing reader; the split is the honest pair.
        "peak": round(peak, 4),
        "peak_full": split["peak_full"],
        "peak_steady": split["peak_steady"],
        "start_pop_ms": split["start_pop_ms"],
        "rms": round(frame_rms(data), 4),
        "delivery_rate": classify_delivery_rate(len(data), float(seconds),
                                                SAMPLE_RATE) if data else None,
        # Anything under the frame gate is digital silence / a dead node.
        "signal": bool(data) and peak >= 0.01,
        "detail": detail,
    }


def pcm_duration_s(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> float:
    return len(pcm) / BYTES_PER_SAMPLE / sample_rate


def wav_duration_s(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


class RollingAudioBuffer:
    """Last ~30s of PCM (§3.5). On an unexpected Live disconnect the tail
    is replayed into the resumed session — the difference between
    'feels solid' and 'drops words'. Memory only; the durable copy is
    the WAV sink below."""

    def __init__(self, seconds: float = 30.0, sample_rate: int = SAMPLE_RATE):
        self._max_bytes = int(seconds * sample_rate * BYTES_PER_SAMPLE)
        self._chunks: deque[bytes] = deque()
        self._size = 0

    def push(self, frame: bytes) -> None:
        self._chunks.append(frame)
        self._size += len(frame)
        while self._size > self._max_bytes and len(self._chunks) > 1:
            self._size -= len(self._chunks.popleft())

    def tail(self) -> bytes:
        return b"".join(self._chunks)

    def clear(self) -> None:
        self._chunks.clear()
        self._size = 0

    def zeroize(self) -> int:
        """Overwrite the held audio with zeros, then drop it (F30 cancel).

        `clear()` releases the reference and leaves the bytes in memory until
        the allocator reuses them. A cancelled dictation must not be able to
        leave recoverable speech behind, so the chunks are overwritten first.
        Returns the number of bytes zeroed (journal evidence, never content).
        """
        zeroed = 0
        for chunk in self._chunks:
            zeroed += len(chunk)
        for index, chunk in enumerate(self._chunks):
            self._chunks[index] = b"\x00" * len(chunk)
        self._chunks.clear()
        self._size = 0
        return zeroed

    @property
    def seconds(self) -> float:
        return pcm_duration_s(b"x" * self._size)


class WavSink:
    """Raw-audio persistence: 'always save the raw audio' (§3.5/§12.5).
    Enables diarization post-pass, batch fallback and re-checks."""

    def __init__(self, path: Path, sample_rate: int = SAMPLE_RATE):
        self.path = Path(path)
        self.sample_rate = int(sample_rate)
        ensure_private_dir(self.path.parent)
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self._wav = wave.open(str(self.path), "wb")  # noqa: SIM115 — sink owns lifecycle; close() is the API
        self._wav.setnchannels(1)
        self._wav.setsampwidth(BYTES_PER_SAMPLE)
        self._wav.setframerate(self.sample_rate)
        self._frames = 0

    def write(self, frame: bytes) -> None:
        self._wav.writeframes(frame)
        self._frames += len(frame) // BYTES_PER_SAMPLE

    def close(self) -> float:
        self._wav.close()
        return self._frames / self.sample_rate


def write_wav(path: Path, frames: list[bytes], sample_rate: int = SAMPLE_RATE) -> Path:
    """Persist collected PCM frames as a mono s16 WAV (returns path)."""
    sink = WavSink(Path(path), sample_rate)
    for frame in frames:
        sink.write(frame)
    sink.close()
    return Path(path)


class FrameGate:
    """Energy VAD: never stream empty audio (§8 — hallucinated transcripts
    on silence). Speech frames pass, plus a short hangover so word
    endings aren't clipped; deep silence is dropped and counted."""

    def __init__(self, rms_threshold: float = 0.01, hangover_frames: int = 10):
        self.threshold = rms_threshold
        self.hangover_frames = hangover_frames
        self._hangover = 0
        self.dropped_silent = 0
        self.passed = 0

    def allows(self, frame: bytes) -> bool:
        if frame_rms(frame) >= self.threshold:
            self._hangover = self.hangover_frames
            self.passed += 1
            return True
        if self._hangover > 0:
            self._hangover -= 1
            self.passed += 1
            return True
        self.dropped_silent += 1
        return False


class SoftLimiter:
    """Capture-side soft limiter (E5/F18/F27/F32/F35): a static curve.

    Deliberately simple: no lookahead, no state carried between chunks, no
    latency, one pass per frame. Samples below the knee pass untouched; above
    it the curve compresses toward a ceiling under full scale, so a loud room
    stops clipping the ADC and the ASR stops hearing distortion as phonemes.

    It MITIGATES, IT NEVER CONCEALS: raw peak and processed peak are both
    tracked forever and both are journalled, so a session that needed 12 dB of
    limiting is visible as exactly that, not as a mysteriously quiet take.

    `apply()` works in place on an `array('h')` built once per chunk and reuses
    a single buffer, so a 30 ms frame costs no per-sample allocation.
    """

    #: Full-scale-safe ceiling: below 1.0 so inter-sample peaks cannot clip.
    CEILING = 0.89
    #: Below the knee the curve is the identity — normal speech is untouched.
    KNEE = 0.60

    def __init__(self, ceiling: float = CEILING, knee: float = KNEE):
        if not 0.0 < knee < ceiling <= 1.0:
            raise ValueError("limiter needs 0 < knee < ceiling <= 1")
        self.ceiling = float(ceiling)
        self.knee = float(knee)
        self.raw_peak = 0.0
        self.processed_peak = 0.0
        self.frames = 0
        self.limited_samples = 0
        self.last_frame_levels: dict[str, float | int] = {}
        self._buf = array("h")

    def _curve(self, value: float) -> float:
        magnitude = abs(value)
        if magnitude <= self.knee:
            return value
        span = self.ceiling - self.knee
        compressed = self.knee + span * math.tanh((magnitude - self.knee) / span)
        return math.copysign(min(compressed, self.ceiling), value)

    def apply(self, pcm: bytes) -> bytes:
        """One chunk in, one chunk out — same length, never longer."""
        usable = len(pcm) - len(pcm) % 2
        if usable <= 0:
            self.last_frame_levels = {}
            return pcm
        self._buf = array("h")
        self._buf.frombytes(pcm[:usable])
        raw = 0
        processed = 0
        limited = 0
        for index in range(len(self._buf)):
            sample = self._buf[index]
            magnitude = sample if sample >= 0 else -sample
            raw = max(raw, magnitude)
            value = sample / 32768
            if abs(value) > self.knee:
                limited += 1
                mapped = round(self._curve(value) * 32767)
                self._buf[index] = max(-32768, min(32767, mapped))
                magnitude = abs(self._buf[index])
            processed = max(processed, magnitude)
        self.last_frame_levels = {
            "raw_peak": raw / 32768, "processed_peak": processed / 32768,
            "limited_samples": limited,
        }
        self.frames += 1
        self.limited_samples += limited
        self.raw_peak = max(self.raw_peak, raw / 32768)
        self.processed_peak = max(self.processed_peak, processed / 32768)
        return self._buf.tobytes()

    def stats(self) -> dict:
        """Both peaks, always — the doctor and the journal both read this."""
        return {
            "raw_peak": round(self.raw_peak, 4),
            "processed_peak": round(self.processed_peak, 4),
            "frames": self.frames,
            "limited_samples": self.limited_samples,
            "limited_ratio": (round(self.limited_samples /
                                    max(1, self.frames * (SAMPLE_RATE * 30 // 1000)), 4)),
            "curve": {"knee": self.knee, "ceiling": self.ceiling,
                      "lookahead": False},
        }


def strip_silence(pcm: bytes, *, rms_threshold: float = 0.01,
                  hangover_frames: int = 2, frame_ms: int = 30) -> tuple[bytes, dict]:
    """Trim leading and trailing silence BEFORE transcription (J2/E2).

    Reuses the capture path's existing energy gate (`FrameGate`) rather than
    introducing a second VAD. Interior silence is kept: pauses are speech
    rhythm, and cutting them changes what Whisper hears. Only the dead head
    and tail go — the part that hallucinates text on empty audio (§8).
    """
    frame_bytes = max(2, SAMPLE_RATE * frame_ms // 1000 * BYTES_PER_SAMPLE)
    frames = [pcm[offset:offset + frame_bytes]
              for offset in range(0, len(pcm) - len(pcm) % frame_bytes, frame_bytes)]
    stats = {"frames_in": len(frames), "dropped_head": 0, "dropped_tail": 0,
             "seconds_in": round(pcm_duration_s(pcm), 3),
             "seconds_out": 0.0, "gate": "energy-vad"}
    if not frames:
        return b"", stats
    gate = FrameGate(rms_threshold=rms_threshold, hangover_frames=hangover_frames)
    allowed = [gate.allows(frame) for frame in frames]
    if not any(allowed):
        stats["seconds_out"] = 0.0
        stats["empty"] = True
        return b"", stats
    first = allowed.index(True)
    last = len(allowed) - 1 - allowed[::-1].index(True)
    stats["dropped_head"] = first
    stats["dropped_tail"] = len(frames) - 1 - last
    kept = b"".join(frames[first:last + 1])
    stats["seconds_out"] = round(pcm_duration_s(kept), 3)
    stats["empty"] = False
    return kept, stats


class AsyncFrameSource(Protocol):
    def frames(self) -> AsyncIterator[bytes]: ...
    async def aclose(self) -> None: ...


# --------------------------------------------------------------------------
# BUG-HW1: the delivery-rate discriminator
# --------------------------------------------------------------------------
# pw-record never reports the format/rate the server actually negotiated on
# stdout — the stream label is whatever was REQUESTED. The only in-band
# signal of a misnegotiated stream is HOW FAST the bytes arrive: a stream
# delivered as s32le at 16 kHz arrives at 64000 B/s, s16le at 48 kHz at
# 96000 B/s, f32le at 48 kHz at 192000 B/s, and so on. The owner's hardware
# A/B (bugs.md, PR #162) shows exactly this shape: the same argv to a WAV
# file plays clean while the raw-stdout form explodes — the byte-rate of the
# raw pipe is the discriminator that names the mislabel. Anything above or
# below the expected rate means the pipe is delivering a format/rate other
# than the label, and every consumer reading s16le bytes is reading garbage.
_DELIVERY_RATE_CLASSES = (
    (32_000, "s16le/16000/mono — as labelled"),
    (64_000, "64000 B/s — s32le/16000/mono, or s16le/16000/stereo"),
    (88_200, "88200 B/s — s16le/44100/mono"),
    (96_000, "96000 B/s — s16le/48000/mono (rate tripled vs label)"),
    (176_400, "176400 B/s — f32le/44100/mono"),
    (192_000, "192000 B/s — f32le/48000/mono, s32le/48000/mono, or s16le/48000/stereo"),
    (384_000, "384000 B/s — f32le/48000/stereo"),
)
#: A known class must land within ±5 % of its nominal rate to be named.
_DELIVERY_CLASS_TOLERANCE = 0.05
#: The labelled rate may wobble by at most ±10 % before it is a suspect.
_DELIVERY_SUSPECT_BAND = (0.90, 1.10)
#: Judging needs ≥ 1 s of expected audio AND ≥ 0.5 s of delivery window.
_DELIVERY_MIN_BYTES = 32_000
_DELIVERY_MIN_WINDOW_S = 0.5


def delivery_rate_class(bytes_per_s: float) -> str | None:
    """Best-effort name for a delivery rate, or None if no class is close."""
    for nominal, label in _DELIVERY_RATE_CLASSES:
        if abs(bytes_per_s - nominal) <= nominal * _DELIVERY_CLASS_TOLERANCE:
            return label
    return None


def classify_delivery_rate(byte_count: int, wall_seconds: float | None,
                           sample_rate: int = SAMPLE_RATE) -> dict:
    """What the pipe's byte-rate says the delivered stream probably is.

    `byte_count` is the number of bytes delivered for this session;
    `wall_seconds` is the delivery WINDOW (first frame → last frame), not
    the spawn-to-exit wall time — PipeWire power-up latency must not count
    against the reading or every short take looks slow. A window of None or
    zero (one burst) cannot be judged and says so, never guesses.

    `mismatch_suspect` is True/False when there is enough evidence, else
    None. It never changes what is captured — it names the mislabel so the
    saved WAV and the journal stop pretending to be labelled audio.
    """
    expected = int(sample_rate) * BYTES_PER_SAMPLE
    byte_count = int(byte_count)
    result = {
        "expected_bytes_per_s": expected,
        "measured_bytes_per_s": None,
        "delivery_ratio": None,
        "class": None,
        "mismatch_suspect": None,
        "evidence": "",
    }
    if byte_count <= 0:
        result["evidence"] = ("no bytes delivered — the pipe was silent "
                              "(see stalled / first_frame_latency_ms)")
        return result
    window = float(wall_seconds) if wall_seconds and wall_seconds > 0 else None
    if window is None:
        result["class"] = delivery_rate_class(0.0) or "unjudged (single burst)"
        result["evidence"] = ("delivery window is zero — bytes arrived in one "
                              "burst; not judged")
        return result
    bps = byte_count / window
    ratio = bps / expected
    result["measured_bytes_per_s"] = round(bps, 1)
    result["delivery_ratio"] = round(ratio, 3)
    named = delivery_rate_class(bps)
    result["class"] = named or (
        f"unclassified ({bps:.0f} B/s) — too far from every known class")
    if byte_count >= _DELIVERY_MIN_BYTES and window >= _DELIVERY_MIN_WINDOW_S:
        low, high = _DELIVERY_SUSPECT_BAND
        result["mismatch_suspect"] = not (low <= ratio <= high)
        result["evidence"] = (f"{byte_count} bytes over {window:.2f}s of "
                              f"delivery = {bps:.0f} B/s vs expected "
                              f"{expected} B/s (ratio {ratio:.2f}x)")
    else:
        result["evidence"] = (f"insufficient evidence: {byte_count} bytes over "
                              f"{window:.2f}s — need >= {_DELIVERY_MIN_BYTES} "
                              f"bytes and >= {_DELIVERY_MIN_WINDOW_S}s to judge")
    return result


class PipeWireCapture:
    """One pw-record process per session (§3.4) — never per-chunk spawns.

    BUG 6 (2026-10-20): a wedged pw-record (spawned, delivering no bytes)
    left `readexactly` hanging forever — the dictation loop could not observe
    `stop_event`, so `ptt.result` sat its full 60 s on a dead session. Frames
    now come with a stall deadline: pw-record emits samples continuously even
    in digital silence, so NO bytes within `stall_timeout_s` means the capture
    is dead, and the stream ends (`stalled = True`) instead of hanging.

    BUG-HW1 (2026-11-26): on the owner's hardware the raw-stdout stream
    does not deliver the s16le/rate/mono label `--format s16 --rate 16000
    --channels 1` requests, and every consumer reads the bytes as s16le —
    the "explosive static". pw-record never reports the negotiated format,
    so this class measures what it CAN see: the exact argv spawned, the
    delivery byte-rate vs the label (`stream_facts`, finalized when the
    stream ends) and the bytes the child had already written into the pipe
    when it died (`dropped_tail_bytes`, counted in `aclose`, never silently
    discarded). It never changes the audio.
    """

    def __init__(self, target: str | None = None, *, sample_rate: int = SAMPLE_RATE,
                 frame_ms: int = 30, stall_timeout_s: float = 8.0, clock=None):
        if not tool_available("pw-record"):
            raise RuntimeError(
                "pw-record not found (pipewire-utils) — live capture needs the "
                "Fedora target. Headless/test runs use SimulatedCapture."
            )
        self.target = target            # node.name/object.serial, or None = default
        self.sample_rate = int(sample_rate)
        self.stall_timeout_s = float(stall_timeout_s)
        self.stalled = False
        # J5: xrun/underrun sensor. A stalled stream or a short read is audio
        # the server did not deliver; counting it keeps "the take sounded
        # choppy" a measured fact instead of an impression.
        self.xruns = 0
        self._clock = clock or time.monotonic
        self._command = pw_record_pcm_stream_command(target, sample_rate=sample_rate)
        self.argv = list(self._command)  # public: journaled verbatim at spawn
        self._frame_bytes = sample_rate * frame_ms // 1000 * BYTES_PER_SAMPLE
        self._proc: asyncio.subprocess.Process | None = None
        # BUG-HW1: delivery accounting. `stream_facts` is finalized once per
        # frames() run; a second call never overwrites the first reading.
        self.spawned_at: float | None = None
        self.first_frame_at: float | None = None
        self.last_frame_at: float | None = None
        self.bytes_delivered = 0
        self.dropped_tail_bytes = 0
        self.stream_facts: dict | None = None
        self._frames_done = False
        self._read_in_flight = 0

    def _note_delivery(self, count: int, now: float) -> None:
        if self.first_frame_at is None:
            self.first_frame_at = now
        self.last_frame_at = now
        self.bytes_delivered += int(count)

    def _finalize_delivery(self) -> None:
        if self.stream_facts is not None:
            return
        end = self._clock()
        spawned = self.spawned_at if self.spawned_at is not None else end
        latency = (self.first_frame_at - spawned
                   if self.first_frame_at is not None else None)
        if (self.first_frame_at is not None and self.last_frame_at is not None
                and self.last_frame_at > self.first_frame_at):
            window = self.last_frame_at - self.first_frame_at
        else:
            window = None
        delivery = classify_delivery_rate(self.bytes_delivered, window,
                                          self.sample_rate)
        self.stream_facts = {
            "argv": list(self.argv),
            "expected": {
                "format": "s16le",
                "sample_rate": self.sample_rate,
                "channels": 1,
                "bytes_per_s": self.sample_rate * BYTES_PER_SAMPLE,
            },
            # pw-record never reports the negotiated format on stdout; these
            # are the facts a hardware report needs to name the mislabel.
            "bytes": self.bytes_delivered,
            "wall_seconds_since_spawn": round(end - spawned, 3),
            "first_frame_latency_ms": (round(latency * 1000, 1)
                                       if latency is not None else None),
            "delivery": delivery,
            "dropped_tail_bytes": int(self.dropped_tail_bytes),
            "note": ("pw-record does not report the negotiated format on "
                     "stdout; the byte-rate vs the s16le label is the only "
                     "in-band discriminator (BUG-HW1)"),
        }

    async def frames(self) -> AsyncIterator[bytes]:
        # VB-10: `pw-record` must die with the daemon instead of keeping the
        # microphone claimed: PR_SET_PDEATHSIG in the child, in its own session
        # (see assistant.proc). The graceful path below still terminates it.
        from .proc import child_kwargs

        self.spawned_at = self._clock()
        self._frames_done = False
        self._proc = await asyncio.create_subprocess_exec(
            *self._command, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            **child_kwargs(),
        )
        assert self._proc.stdout is not None
        try:
            while True:
                try:
                    self._read_in_flight += 1
                    try:
                        chunk = await asyncio.wait_for(
                            self._proc.stdout.readexactly(self._frame_bytes),
                            timeout=self.stall_timeout_s)
                    finally:
                        self._read_in_flight -= 1
                except TimeoutError:
                    # Dead capture: report it, end the stream, let the session
                    # fail fast with "no speech captured" instead of hanging.
                    self.stalled = True
                    self.xruns += 1
                    return
                except asyncio.IncompleteReadError as partial:
                    if partial.partial:
                        self._note_delivery(len(partial.partial), self._clock())
                        self.xruns += 1      # short read: a dropped tail, counted
                        yield partial.partial
                    return
                self._note_delivery(len(chunk), self._clock())
                yield chunk
        finally:
            self._frames_done = True
            self._finalize_delivery()

    # BH-K6: SIGTERM grace before SIGKILL escalation in aclose().
    TERMINATE_TIMEOUT_S = 2.0
    #: How long the post-terminate pipe drain may take (BUG-HW1). The dictate
    #: close path budgets 1.5 s for source.aclose(), so the drain must return
    #: fast: EOF arrives as soon as the child dies, which is immediate for a
    #: default SIGTERM. The remainder of the 2 s budget is the SIGKILL wait.
    DRAIN_TIMEOUT_S = 0.8

    async def _drain_tail(self, proc: asyncio.subprocess.Process) -> int:
        """Bytes the child had written into the pipe and the session never saw.

        After terminate() the bytes already in the kernel pipe stay readable
        until the read end closes — they are audio the server delivered and
        the take is missing them. They cannot be re-fed (the session has
        moved on); counting them is the honest move. Never runs while a
        readexactly is in flight on the same stream (that would steal its
        bytes), and never errors the close.
        """
        if getattr(proc, "stdout", None) is None or getattr(self, "_read_in_flight", 0):
            return 0
        total = 0
        deadline = self._clock() + self.DRAIN_TIMEOUT_S
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(65536),
                                                    timeout=0.25)
                except TimeoutError:
                    break  # child is wedged — do not hold the close hostage
                except Exception:
                    break
                if not chunk:
                    break
                total += len(chunk)
                if self._clock() >= deadline:
                    break
        except asyncio.CancelledError:
            # Never leak a live mic because the caller stopped waiting:
            # the graceful-close contract still requires the kill.
            try:
                proc.kill()
            except Exception as kill_exc:  # best effort — the kill still goes down
                print(f"[assist] capture tail-drain kill failed: "
                      f"{type(kill_exc).__name__}: {kill_exc}", flush=True)
            raise
        return total

    async def aclose(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
        # BUG-HW1: count the pipe tail the session is abandoning (the
        # 0-byte-capture evidence: bytes in flight at a fast stop).
        dropped = await self._drain_tail(proc)
        if dropped:
            self.dropped_tail_bytes = getattr(self, "dropped_tail_bytes", 0) + dropped
            facts = getattr(self, "stream_facts", None)
            if facts is not None:
                facts["dropped_tail_bytes"] = int(self.dropped_tail_bytes)
        try:
            await asyncio.wait_for(proc.wait(), timeout=self.TERMINATE_TIMEOUT_S)
        except TimeoutError:
            # SIGTERM was ignored: SIGKILL cannot be. (The old code awaited
            # wait() with no bound and no escalation.)
            proc.kill()
            await proc.wait()
        except asyncio.CancelledError:
            # The caller stopped waiting (its own lifecycle timeout): a
            # live microphone must not outlive the close attempt.
            proc.kill()
            raise


class SimulatedCapture:
    """Deterministic frames for headless runs (no mic/PipeWire anywhere):
    bursts of synthetic 'speech' energy separated by silence. Proves the
    full dictation pipeline in mock mode; says nothing about acoustics."""

    def __init__(self, speech_frames: int = 20, silent_frames: int = 5, *,
                 frame_ms: int = 30, realtime: bool = False):
        self.speech_frames = speech_frames
        self.silent_frames = silent_frames
        self.frame_ms = frame_ms
        self.realtime = realtime
        self.target = "simulated"        # diagnostics: never a mystery node
        self.stalled = False
        self.xruns = 0                   # a simulated device cannot underrun
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        self._stopped.set()

    async def frames(self) -> AsyncIterator[bytes]:
        samples = SAMPLE_RATE * self.frame_ms // 1000
        speech = struct.pack(f"<{samples}h", *([6000] * samples))  # steady energy
        silence = b"\x00\x00" * samples
        for _ in range(self.speech_frames):
            if self._stopped.is_set():
                return
            yield speech
            if self.realtime:
                await asyncio.sleep(self.frame_ms / 1000)
        for _ in range(self.silent_frames):
            if self._stopped.is_set():
                return
            yield silence
            if self.realtime:
                await asyncio.sleep(self.frame_ms / 1000)

    async def aclose(self) -> None:
        self.stop()


def mix_pcm(a: bytes, b: bytes) -> bytes:
    """Sample-wise sum with clamp — the one-stream meeting mix (§3.4).
    Shorter input is zero-padded; overflow saturates instead of wrapping
    (wrap would turn loud speech into clicks)."""
    n = max(len(a), len(b)) // 2
    sa = struct.unpack(f"<{len(a) // 2}h", a[: len(a) - len(a) % 2])
    sb = struct.unpack(f"<{len(b) // 2}h", b[: len(b) - len(b) % 2])
    mixed = []
    for i in range(n):
        value = (sa[i] if i < len(sa) else 0) + (sb[i] if i < len(sb) else 0)
        mixed.append(max(-32768, min(32767, value)))
    return struct.pack(f"<{n}h", *mixed)


class DualCapture:
    """Two sources (mic + sink monitor) as synchronised pairs (§3.4/§9-6).

    Yields (mic_frame, system_frame) — kept SEPARATE, because separate
    channels are what makes channel diarization (You vs Them) exact;
    a mixed stream can be derived with mix_pcm when one stream is
    wanted (Live), but information thrown away can't be unmixed."""

    def __init__(self, mic_source, system_source):
        self.mic = mic_source
        self.system = system_source

    async def frames(self):
        mic_iter = self.mic.frames().__aiter__()
        sys_iter = self.system.frames().__aiter__()
        silence = b""
        while True:
            mic_frame = await _next_or_silence(mic_iter, silence)
            sys_frame = await _next_or_silence(sys_iter, silence)
            if mic_frame is None and sys_frame is None:
                return
            yield (mic_frame or silence, sys_frame or silence)

    async def aclose(self) -> None:
        results = await asyncio.gather(
            self.mic.aclose(), self.system.aclose(), return_exceptions=True)
        failures = [result for result in results if isinstance(result, BaseException)]
        if not failures:
            return
        cancelled = next((failure for failure in failures
                          if isinstance(failure, asyncio.CancelledError)), None)
        if cancelled is not None:
            other_failures = [failure for failure in failures if failure is not cancelled]
            error = RuntimeError("meeting capture source close was cancelled")
            if other_failures:
                error.add_note(
                    "additional capture close failure(s): "
                    + "; ".join(f"{type(err).__name__}: {err}"
                                 for err in other_failures))
            raise error from cancelled
        if len(failures) == 1:
            raise failures[0]
        raise BaseExceptionGroup("meeting capture sources failed to close", failures)


async def _next_or_silence(iterator, _silence):
    try:
        return await iterator.__anext__()
    except StopAsyncIteration:
        return None


def pw_record_pcm_stream_command(target: str | None, *, sample_rate: int = 16000) -> list[str]:
    """Raw s16le PCM to stdout — what assist-voice-test consumes live.

    BUG-HW1: pw-record never reports the negotiated format on stdout, so a
    stream delivered at any other width/rate/channel count than the label is
    silently misread by every consumer as s16le. `PipeWireCapture` measures
    and journals the delivery facts (`stream_facts`); this argv is pinned by
    tests and must stay byte-identical to what production spawns.
    """
    if target and str(target).isdigit() and len(str(target)) < 4:
        raise ValueError(
            f"'{target}' looks like an object.id. pw-record --target wants "
            "object.serial or node.name — an ID silently records the default "
            "device instead of erroring (GETTING-STARTED Step 3)."
        )
    command = ["pw-record", "--rate", str(sample_rate), "--channels", "1",
               "--format", "s16", "-"]
    if target:
        command.insert(1, f"--target={target}")
    return command
