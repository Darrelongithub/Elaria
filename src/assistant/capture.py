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
import re
import shutil
import struct
import subprocess
import wave
from collections import deque
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Protocol

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
    for line in text.splitlines():
        header = re.search(r"\b(Sinks|Sources|Sink endpoints|Source endpoints):\s*$", line)
        if header:
            current = header.group(1)
            sections.setdefault(current, [])
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


def live_level_check(target: str | None = None, seconds: float = 1.2,
                     runner=subprocess.run) -> dict:
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
    return {
        "available": True,
        "target": target or "(default source)",
        "seconds": round(len(data) / BYTES_PER_SAMPLE / SAMPLE_RATE, 2),
        "bytes": len(data),
        "peak": round(peak, 4),
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

    @property
    def seconds(self) -> float:
        return pcm_duration_s(b"x" * self._size)


class WavSink:
    """Raw-audio persistence: 'always save the raw audio' (§3.5/§12.5).
    Enables diarization post-pass, batch fallback and re-checks."""

    def __init__(self, path: Path, sample_rate: int = SAMPLE_RATE):
        self.path = Path(path)
        self.sample_rate = int(sample_rate)
        self.path.parent.mkdir(parents=True, exist_ok=True)
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
    """

    def __init__(self, target: str | None = None, *, sample_rate: int = SAMPLE_RATE,
                 frame_ms: int = 30, stall_timeout_s: float = 8.0):
        if not tool_available("pw-record"):
            raise RuntimeError(
                "pw-record not found (pipewire-utils) — live capture needs the "
                "Fedora target. Headless/test runs use SimulatedCapture."
            )
        self.target = target            # node.name/object.serial, or None = default
        self.stall_timeout_s = float(stall_timeout_s)
        self.stalled = False
        self._command = pw_record_pcm_stream_command(target, sample_rate=sample_rate)
        self._frame_bytes = sample_rate * frame_ms // 1000 * BYTES_PER_SAMPLE
        self._proc: asyncio.subprocess.Process | None = None

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
        while True:
            try:
                chunk = await asyncio.wait_for(
                    self._proc.stdout.readexactly(self._frame_bytes),
                    timeout=self.stall_timeout_s)
            except TimeoutError:
                # Dead capture: report it, end the stream, let the session
                # fail fast with "no speech captured" instead of hanging.
                self.stalled = True
                return
            except asyncio.IncompleteReadError as partial:
                if partial.partial:
                    yield partial.partial
                return
            yield chunk

    async def aclose(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()


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
        await self.mic.aclose()
        await self.system.aclose()


async def _next_or_silence(iterator, _silence):
    try:
        return await iterator.__anext__()
    except StopAsyncIteration:
        return None


def pw_record_pcm_stream_command(target: str | None, *, sample_rate: int = 16000) -> list[str]:
    """Raw s16le PCM to stdout — what assist-voice-test consumes live."""
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
