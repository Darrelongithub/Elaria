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
import json
import math
import os
import re
import shlex
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
from .journal_log import log_event

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


def detect_container_prefix(prefix: bytes) -> str | None:
    """Container label when `prefix` is a file header instead of raw PCM.

    BUG-HW1 tripwire: pw-record's `-` without `--raw` writes an AU container
    (libsndfile stdio) whose bytes are NOT the s16le the caller labelled them.
    Recognition is STRICT — a container is only declared on its full magic
    plus sane header fields (for AU: magic `.snd`, a plausible data offset,
    PCM encoding, sane rate and channel count) — so a real s16le capture that
    merely starts with similar bytes is never misjudged. Returns `"au"`,
    `"wav"`, or None.
    """
    if len(prefix) >= 24 and prefix[:4] == b".snd":
        offset, _size, encoding, rate, channels = struct.unpack(
            ">5I", prefix[4:24])
        if (24 <= offset <= 4096 and 1 <= encoding <= 7
                and 4000 <= rate <= 384000 and 1 <= channels <= 64):
            return "au"
        return None
    if len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WAVE":
        return "wav"
    return None


def negotiated_stream_facts(runner=subprocess.run, *, attempts: int = 3,
                            retry_delay_s: float = 0.05) -> dict:
    """Best-effort PipeWire-side facts about the capture stream (`pw-dump`).

    Journalled at capture start (BUG-HW1) so the next hardware report is
    self-diagnosing: argv says what was ASKED for, these facts say what the
    server NEGOTIATED. The stream node appears only after pw-record connects,
    so the lookup retries briefly; a sandbox or a missing `pw-dump` gets the
    house honest-unavailable shape (`available: False, reason: …`), never a
    guess and never an exception into the capture path.
    """
    if not tool_available("pw-dump"):
        return {"available": False,
                "reason": "pw-dump not found (pipewire) — expected on the "
                          "Fedora target, absent in containers"}
    last_reason = "pw-dump produced no pw-record stream node"
    for attempt in range(max(1, attempts)):
        if attempt:
            time.sleep(retry_delay_s)
        try:
            out = runner(["pw-dump"], capture_output=True, text=True, timeout=10)
            if getattr(out, "returncode", 0) != 0:
                last_reason = (f"pw-dump exited {out.returncode}: "
                               f"{(getattr(out, 'stderr', '') or '')[:120]}")
                continue
            nodes = json.loads(out.stdout or "[]")
        except Exception as exc:
            last_reason = f"{type(exc).__name__}: {exc}"
            continue
        found = _pw_record_stream_nodes(nodes)
        if not found:
            continue
        node = found[-1]           # newest id: the stream this spawn created
        facts = _format_facts(node)
        return {"available": True, "node_id": node.get("id"),
                "streams_visible": len(found), **facts}
    return {"available": False, "reason": last_reason}


def _pw_record_stream_nodes(nodes) -> list[dict]:
    """pw-dump objects that are pw-record stream nodes (tolerant match)."""
    found = []
    for node in nodes if isinstance(nodes, list) else []:
        if not isinstance(node, dict):
            continue
        props = ((node.get("info") or {}).get("props") or {})
        named = " ".join(str(props.get(key, "")) for key in
                         ("node.name", "application.name",
                          "application.process.binary"))
        if "pw-record" in named:
            found.append(node)
    return found


def _format_facts(node: dict) -> dict:
    """First {format, rate, channels} triple in a node's params (tolerant)."""
    def walk(obj):
        if isinstance(obj, dict):
            if ("format" in obj and "rate" in obj and "channels" in obj
                    and isinstance(obj.get("rate"), int)):
                return obj
            for value in obj.values():
                hit = walk(value)
                if hit is not None:
                    return hit
        elif isinstance(obj, list):
            for value in obj:
                hit = walk(value)
                if hit is not None:
                    return hit
        return None

    fmt = walk((node.get("info") or {}).get("params") or {})
    if fmt is None:
        return {"format": "-", "rate": "-", "channels": "-"}
    return {"format": fmt.get("format", "-"), "rate": fmt.get("rate", "-"),
            "channels": fmt.get("channels", "-")}


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
                    "reason": f"pw-record exited {proc.returncode}: {err}"}
    except subprocess.TimeoutExpired as exc:
        data = exc.stdout or b""
        detail = f"recorded {seconds:.1f}s"
    except Exception as exc:
        return {"available": False, "target": target or "(default source)",
                "reason": f"{type(exc).__name__}: {exc}"}
    peak = pcm_peak(data)
    split = split_peak(data, SAMPLE_RATE, skip_ms)
    return {
        "available": True,
        "target": target or "(default source)",
        "seconds": round(len(data) / BYTES_PER_SAMPLE / SAMPLE_RATE, 2),
        "bytes": len(data),
        # BUG-HW1: a container header means the bytes are not the labelled
        # raw s16le — flag it so the peak below is never read unexamined.
        "container": detect_container_prefix(data) or "",
        # `peak` stays for every existing reader; the split is the honest pair.
        "peak": round(peak, 4),
        "peak_full": split["peak_full"],
        "peak_steady": split["peak_steady"],
        "start_pop_ms": split["start_pop_ms"],
        "rms": round(frame_rms(data), 4),
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


class PipeWireCapture:
    """One pw-record process per session (§3.4) — never per-chunk spawns.

    BUG 6 (2026-10-20): a wedged pw-record (spawned, delivering no bytes)
    left `readexactly` hanging forever — the dictation loop could not observe
    `stop_event`, so `ptt.result` sat its full 60 s on a dead session. Frames
    now come with a stall deadline: pw-record emits samples continuously even
    in digital silence, so NO bytes within `stall_timeout_s` means the capture
    is dead, and the stream ends (`stalled = True`) instead of hanging.

    BUG-HW1 (2026-11-26): the stream is journalled and VERIFIED at open.
    `capture.stream_open` carries the exact argv plus the negotiated stream
    facts (`pw-dump`), so a mislabelled stream names itself in the next
    hardware report. The first bytes are checked against known container
    headers (`detect_container_prefix`): a stream that opens as AU/WAV bytes
    is NOT the labelled raw s16le, and feeding it downstream would recreate
    the owner's explosive static — so the stream ends with
    `capture.format_mismatch` (and `stream_mismatch` set) instead. A capture
    that ends with zero bytes is journalled as `capture.starved` (the ~1.5 s
    first-frame graph warmup starves fast stops), not left as a mystery
    empty take.
    """

    def __init__(self, target: str | None = None, *, sample_rate: int = SAMPLE_RATE,
                 frame_ms: int = 30, stall_timeout_s: float = 8.0):
        if not tool_available("pw-record"):
            raise RuntimeError(
                "pw-record not found (pipewire-utils) — live capture needs the "
                "Fedora target. Headless/test runs use SimulatedCapture."
            )
        self.target = target            # node.name/object.serial, or None = default
        self.sample_rate = int(sample_rate)
        self.stall_timeout_s = float(stall_timeout_s)
        self.stalled = False
        # BUG-HW1: what the delivered stream turned out to be, when it is not
        # what the label says (None = label held or not yet checked).
        self.stream_mismatch: dict | None = None
        # J5: xrun/underrun sensor. A stalled stream or a short read is audio
        # the server did not deliver; counting it keeps "the take sounded
        # choppy" a measured fact instead of an impression.
        self.xruns = 0
        self._command = pw_record_pcm_stream_command(target, sample_rate=sample_rate)
        self._frame_bytes = sample_rate * frame_ms // 1000 * BYTES_PER_SAMPLE
        self._proc: asyncio.subprocess.Process | None = None
        self._opened = False
        self._bytes_yielded = 0
        self._starved_journaled = False

    def _journal(self, event: str, *, level: str = "info", verdict: str = "",
                 detail: str = "") -> None:
        """§4.8 schema line; never raises (journal_log already guards)."""
        log_event(event, level=level, verdict=verdict, detail=detail)

    def _journal_starved_once(self) -> None:
        # getattr defaults keep the K6 unit seam (object.__new__ without
        # __init__) safe: a stripped object has nothing to report.
        if (getattr(self, "_starved_journaled", True)
                or not getattr(self, "_opened", False)
                or getattr(self, "_bytes_yielded", 1) > 0):
            return
        self._starved_journaled = True
        if self.stream_mismatch is not None:
            return     # capture.format_mismatch already explains the zero bytes
        self._journal(
            "capture.starved", level="warn", verdict="starved",
            detail=(f"0 bytes delivered argv={shlex.join(self._command)} "
                    f"target={self.target or '(default)'} — stopped before "
                    "the first frame (PipeWire graph warmup is ~1.5 s) or "
                    "the stream never started"))

    def _check_head(self, data: bytes) -> bool:
        """First bytes: raw PCM, or a container wearing the s16le label?"""
        label = detect_container_prefix(data)
        if label is None:
            return True
        self.stream_mismatch = {"container": label,
                                "command": list(self._command)}
        self._journal(
            "capture.format_mismatch", level="error", verdict="mismatch",
            detail=(f"stream opens as a {label} container header, not the "
                    f"labelled raw s16le/{self.sample_rate}hz/1ch — refusing "
                    f"to record mislabelled bytes argv={shlex.join(self._command)} "
                    f"target={self.target or '(default)'}"))
        return False

    async def frames(self) -> AsyncIterator[bytes]:
        # VB-10: `pw-record` must die with the daemon instead of keeping the
        # microphone claimed: PR_SET_PDEATHSIG in the child, in its own session
        # (see assistant.proc). The graceful path below still terminates it.
        from .proc import child_kwargs

        self._proc = await asyncio.create_subprocess_exec(
            *self._command, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            **child_kwargs(),
        )
        assert self._proc.stdout is not None
        self._opened = True
        # BUG-HW1: journal what was asked AND what the server negotiated,
        # at capture start — the next hardware report reads facts, not vibes.
        facts = await asyncio.to_thread(negotiated_stream_facts)
        negotiated = ("not available: " + str(facts.get("reason", "?"))
                      if not facts.get("available") else
                      f"format={facts.get('format')} rate={facts.get('rate')} "
                      f"channels={facts.get('channels')} "
                      f"node_id={facts.get('node_id')} "
                      f"streams_visible={facts.get('streams_visible')}")
        self._journal(
            "capture.stream_open", verdict="opened",
            detail=(f"argv={shlex.join(self._command)} "
                    f"target={self.target or '(default)'} "
                    f"expected=format:s16le rate:{self.sample_rate} channels:1 "
                    f"negotiated[{negotiated}]"))
        head_checked = False
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self._proc.stdout.readexactly(self._frame_bytes),
                        timeout=self.stall_timeout_s)
                except TimeoutError:
                    # Dead capture: report it, end the stream, let the session
                    # fail fast with "no speech captured" instead of hanging.
                    self.stalled = True
                    self.xruns += 1
                    return
                except asyncio.IncompleteReadError as partial:
                    if partial.partial:
                        self.xruns += 1      # short read: a dropped tail, counted
                        if not head_checked:
                            head_checked = True
                            if not self._check_head(partial.partial):
                                return
                        self._bytes_yielded += len(partial.partial)
                        yield partial.partial
                    return
                if not head_checked:
                    head_checked = True
                    if not self._check_head(chunk):
                        return
                self._bytes_yielded += len(chunk)
                yield chunk
        finally:
            self._journal_starved_once()

    # BH-K6: SIGTERM grace before SIGKILL escalation in aclose().
    TERMINATE_TIMEOUT_S = 2.0

    async def aclose(self) -> None:
        # BUG-HW1: a fast stop before the first frame is a STARVED capture —
        # journaled here, because the frames() generator may never run again
        # to say so itself.
        self._journal_starved_once()
        proc, self._proc = self._proc, None
        if proc is None or proc.returncode is not None:
            return
        proc.terminate()
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

    BUG-HW1 (2026-11-26, owner hardware): `--raw` is load-bearing, not
    decoration. Without it the filename `-` is NOT a raw pipe — pw-cat opens
    it through libsndfile (`sf_open("-", …)` binds stdio), and
    `format_from_filename()` maps `-` to the **AU container** (sunau):
    a 24-byte `.snd` header followed by **big-endian** PCM. The daemon read
    those bytes as s16le and got explosive static (every sample byte-swapped:
    a ×256 gain with wraparound), a full-scale "start pop" from the header
    (peak 0.9981 = the rate field misread as s16le), and an ASR-empty take —
    while `pw-record … file.wav` from the same node was clean, because the
    `.wav` extension selects the WAV container whose PCM16 is little-endian.
    `--raw` forces pw-cat's raw path (`setup_pipe`/`setup_raw`): the stream's
    own s16le bytes on stdout, no container, no header, no byteswap. A build
    too old to know `--raw` exits with a usage error — fail-closed, never
    silent static.
    """
    if target and str(target).isdigit() and len(str(target)) < 4:
        raise ValueError(
            f"'{target}' looks like an object.id. pw-record --target wants "
            "object.serial or node.name — an ID silently records the default "
            "device instead of erroring (GETTING-STARTED Step 3)."
        )
    command = ["pw-record", "--rate", str(sample_rate), "--channels", "1",
               "--format", "s16", "--raw", "-"]
    if target:
        command.insert(1, f"--target={target}")
    return command
