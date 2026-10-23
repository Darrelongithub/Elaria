"""Event transcriber (Blueprint v2, P0) — a field tool that cannot lose the day.

One laptop, room mic, ~10-hour event. Records continuously, chops into
segments, transcribes each closed segment shortly after it closes, and
appends text to one growing document the user can open in any editor.

PRIME DIRECTIVE, testable: transcription can fail, lag, or run out of
quota — CAPTURE MAY NOT. If audio exists, a transcript or an explicit
"audio kept: <path>" marker always comes back. No silent drops.

Mechanics (§3–§6):
  * rotation opens the NEXT segment BEFORE closing the previous one
    (gap < 1 s), raw WAVs retained permanently;
  * appends land in SEGMENT order — later results wait for earlier ones,
    a deferred marker unblocks the line, one bad segment never holds the
    document hostage;
  * the queue is concurrency-1, uses the active route's verified limits,
    splits live-route WAVs to fit the 70% TPM window, and counts every call;
    quota exhaustion defers — it never discards audio;
  * `systemd-inhibit` blocks sleep/idle/lid for the whole event;
  * per-segment `capture.stats` (node, bytes, peak) so a dead-mic hour is
    discoverable from the log, not at 6pm;
  * the state file + segments on disk are enough for `event stop` to
    assemble a complete document after a daemon kill (§5).

The recording is the truth; the live text is a convenience. The document
is always regenerable from segments + labels.json (P2 rename stays
lossless because labels.json is written DURING the event).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
import wave
from collections import deque
from datetime import UTC, datetime, timedelta
from datetime import time as datetime_time
from pathlib import Path
from zoneinfo import ZoneInfo

from .capture import WavSink, frame_rms
from .config import ensure_private_dir
from .cost import iso_now

# §3 queue rules / §0 table defaults (row 3 — see event_spike.decide).
SEGMENT_MIN_DEFAULT = 30.0          # row 3: batch route, 30-min segments
FLUSH_MIN_S = 20.0                  # live-route minimum flush length (§3)
TOKENS_PER_SECOND_DEFAULT = 32.0    # audio-token rate estimate (§3 quota math)
TPM_HEADROOM = 0.7                  # never submit past ~70% of the ceiling
DEFAULT_CALL_BUDGET = 25            # batch route: 25 calls/day (§3)
BYTES_PER_HOUR = 16000 * 2 * 3600   # 16 kHz mono s16 ≈ 115.2 MB/h (§6)
NO_SIGNAL_PEAK = 0.005              # near-zero peak → visible marker (§5)
DEFERRED_MARKER = ("[seg {index:03d} transcription failed/deferred — "
                   "audio kept: {wav}]")
NO_SIGNAL_MARKER = "[seg {index:03d}: no signal detected]"


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug or "event"


def events_root(config) -> Path:
    return ensure_private_dir(config.data_dir / "events")


def free_disk_bytes(root: Path) -> int:
    try:
        return int(shutil.disk_usage(Path(root)).free)
    except OSError:
        return int(shutil.disk_usage(Path(root).parent).free)


def event_dir_bytes(event_dir: Path) -> int:
    total = 0
    for path in Path(event_dir).rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def power_status() -> dict:
    """Battery posture from sysfs — warn on battery (§6), never a guess."""
    try:
        supplies = sorted(Path("/sys/class/power_supply").glob("*"))
        for supply in supplies:
            try:
                if (supply / "type").read_text().strip() != "Battery":
                    continue
                state = (supply / "status").read_text().strip()
                capacity = ""
                cap_file = supply / "capacity"
                if cap_file.exists():
                    capacity = f" {cap_file.read_text().strip()}%"
                return {"available": True, "on_battery": state == "Discharging",
                        "detail": f"{supply.name} {state}{capacity}"}
            except OSError:
                continue
        return {"available": False, "on_battery": False, "detail": "no battery found"}
    except OSError as exc:
        return {"available": False, "on_battery": False,
                "detail": f"{type(exc).__name__}: {exc}"}


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    ensure_private_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


def _hhmm(iso: str) -> str:
    if isinstance(iso, str) and len(iso) >= 16:
        return iso[11:16]
    return str(iso or "??:??")


def render_segment_block(rec: dict, text: str | None) -> str:
    """One segment's block. `text is None` means deferred — the marker must
    cite the audio path (the prime directive's visible half)."""
    index = int(rec.get("index", 0))
    header = (f"## {_hhmm(rec.get('opened_at') or '')} · "
              f"{rec.get('speaker') or 'Speaker 1'} · seg {index:03d}")
    if rec.get("recovered"):
        header += " (recovered)"
    lines = [header, ""]
    for marker in rec.get("markers") or []:
        lines.append(str(marker))
    if rec.get("no_signal"):
        lines.append(NO_SIGNAL_MARKER.format(index=index))
    if text is None:
        lines.append(DEFERRED_MARKER.format(index=index, wav=rec.get("wav", "")))
    else:
        stripped = text.strip()
        if stripped:
            lines.append(stripped)
    lines.append("")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Live document: atomic appends, mirrored .txt (§3 "Live document")
# --------------------------------------------------------------------------
class EventDocument:
    def __init__(self, md_path: Path, txt_path: Path | None = None):
        self.md_path = Path(md_path)
        self.txt_path = Path(txt_path) if txt_path else self.md_path.with_suffix(".txt")

    def write_header(self, title: str, started_at: str, meta: dict) -> None:
        route = meta.get("route", "batch")
        minutes = meta.get("segment_minutes", SEGMENT_MIN_DEFAULT)
        content = (f"# {title}\n\n"
                   f"_{started_at} · route {route} · segment {minutes} min_\n\n")
        for path in (self.md_path, self.txt_path):
            # Event start must never truncate an orphaned/edited document.
            with open(path, "xb") as handle:
                handle.write(content.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())

    def append_block(self, block: str) -> None:
        """Append + fsync (§3) — safe to sit open in an editor all day."""
        payload = block.encode("utf-8")
        for path in (self.md_path, self.txt_path):
            with open(path, "ab") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())

    def resolve_late(self, index: int, expected_block: str,
                     replacement_block: str, expected_suffix: str) -> dict[Path, bool]:
        """Replace a deferred block only when its displaced suffix is pristine.

        Otherwise append a labeled recovered block at EOF. Each mirror is
        checked independently so a touched .txt never gets silently changed.
        """
        outcomes: dict[Path, bool] = {}
        header_re = re.compile(
            rf"^## .* · seg {int(index):03d}(?: .*)?$", re.MULTILINE)
        first_line, _, remainder = replacement_block.partition("\n")
        fallback = (f"{first_line} (recovered)\n\n"
                    "[late transcript appended; earlier live text was preserved]\n"
                    f"{remainder.lstrip(chr(10))}")
        for path in (self.md_path, self.txt_path):
            content = path.read_text(encoding="utf-8")
            match = header_re.search(content)
            inserted = False
            if match:
                next_header = re.search(r"^## ", content[match.end():], re.MULTILINE)
                end = match.end() + next_header.start() if next_header else len(content)
                actual_block = content[match.start():end]
                suffix = content[end:]
                if actual_block == expected_block and suffix == expected_suffix:
                    _atomic_write(path, content[:match.start()] + replacement_block + suffix)
                    inserted = True
            if not inserted:
                with open(path, "ab") as handle:
                    handle.write(fallback.encode("utf-8"))
                    handle.flush()
                    os.fsync(handle.fileno())
            outcomes[path] = inserted
        return outcomes

    def edit_segment(self, index: int, base_text: str, new_text: str) -> dict:
        """Apply an owner edit only if the segment still matches the UI base.

        The `.txt` is the editable live document. A stale edit is preserved as
        an explicit tail copy instead of overwriting any newer landed/edited
        region. Capture and transcription never call this method.
        """
        index = int(index)
        edited = str(new_text).strip("\n")
        base = str(base_text).strip("\n")
        header_re = re.compile(
            rf"^## .* · seg {index:03d}(?: .*)?$", re.MULTILINE)
        clean_edits = 0
        for path in (self.md_path, self.txt_path):
            content = path.read_text(encoding="utf-8")
            match = header_re.search(content)
            if match is None:
                tail = (f"\n## ??:?? · Speaker {index} · seg {index:03d} (edited copy)\n\n"
                        "[edited copy saved because the original region was not found]\n"
                        f"{edited}\n\n")
                _atomic_write(path, content + tail)
                continue
            next_header = re.search(r"^## ", content[match.end():], re.MULTILINE)
            end = match.end() + next_header.start() if next_header else len(content)
            body = content[match.end():end].strip("\n")
            if body == base:
                replacement = "\n\n" + edited + "\n\n"
                _atomic_write(path, content[:match.end()] + replacement + content[end:])
                clean_edits += 1
                continue

            header = match.group(0)
            tail = (f"\n## {header[3:]} (edited copy)\n\n"
                    "[edited copy saved because the landed segment changed]\n"
                    f"{edited}\n\n")
            _atomic_write(path, content + tail)
        return {"state": "edited" if clean_edits == 2 else "conflict-appended",
                "index": index}

    def word_count(self) -> int:
        try:
            return len(self.md_path.read_text(encoding="utf-8").split())
        except OSError:
            return 0


class OrderedAppender:
    """Strict segment order: later results hold until earlier ones land.
    A deferred marker unblocks the line; one bad segment never holds the
    document hostage (§3)."""

    def __init__(self, document: EventDocument):
        self._document = document
        self._expected: set[int] = set()
        self._landed: set[int] = set()
        self._held: dict[int, str] = {}
        self._next = 1

    def expect(self, index: int) -> None:
        self._expected.add(int(index))

    def resolved(self, index: int, block: str) -> None:
        self._land(int(index), block)

    def deferred(self, index: int, block: str) -> None:
        self._land(int(index), block)

    def _land(self, index: int, block: str) -> None:
        if index in self._landed:
            return
        self._held[index] = block
        self._flush_contiguous()

    def _flush_contiguous(self) -> None:
        while self._next in self._held:
            self._document.append_block(self._held.pop(self._next))
            self._landed.add(self._next)
            self._next += 1

    def append_late(self, index: int, block: str, *, expected_block: str | None = None,
                    expected_suffix: str = "") -> dict[Path, bool] | None:
        """Resolve a deferred marker safely, falling back to a tail append."""
        if expected_block is None:
            self._document.append_block(block)
            return None
        return self._document.resolve_late(
            index, expected_block, block, expected_suffix)

    def force_pending(self, make_block) -> list[int]:
        """Stop-time flush: markers for everything unresolved, real blocks
        for anything held. Returns the marker-forced indexes."""
        missing = sorted(i for i in self._expected
                         if i not in self._landed and i not in self._held)
        for index in missing:
            self._held[index] = make_block(index)
        self._flush_contiguous()
        return missing


# --------------------------------------------------------------------------
# Speakers: roster + switching (§4)
# --------------------------------------------------------------------------
class SpeakerBook:
    def __init__(self, roster: list[str] | None = None):
        cleaned = [str(name).strip() for name in (roster or []) if str(name).strip()]
        self.roster: list[str] = cleaned or ["Speaker 1"]
        self.active: str = self.roster[0]

    @staticmethod
    def _generated(name: str) -> bool:
        return re.fullmatch(r"Speaker \d+", str(name)) is not None

    def _new_speaker_name(self) -> str:
        numbers = [int(m.group(1)) for name in self.roster
                   if (m := re.fullmatch(r"Speaker (\d+)", str(name)))]
        name = f"Speaker {max(numbers, default=0) + 1}"
        self.roster.append(name)
        return name

    def switch_next(self) -> str:
        if self.active in self.roster:
            position = self.roster.index(self.active)
            if position + 1 < len(self.roster):
                self.active = self.roster[position + 1]
            elif self._generated(self.active):
                self.active = self._new_speaker_name()   # created on switch (§4)
            else:
                self.active = self.roster[0]             # cycle the roster
        else:
            self.active = self.roster[0]
        return self.active

    def switch_to(self, name: str) -> str:
        name = str(name).strip()
        if name and name not in self.roster:
            self.roster.append(name)                     # unknown name joins (§4)
        if name:
            self.active = name
        return self.active


# --------------------------------------------------------------------------
# Sleep inhibition (§5) — the likeliest way to lose the day
# --------------------------------------------------------------------------
class SleepInhibitor:
    """Holds `systemd-inhibit --what=sleep:idle:handle-lid-switch --mode=block`
    for the whole event. Preflight verifies the lock is held (§6)."""

    def __init__(self, *, popen=subprocess.Popen):
        self._popen = popen
        self._proc = None
        self.detail = {"held": False, "reason": "not acquired"}

    @property
    def held(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def acquire(self) -> dict:
        if shutil.which("systemd-inhibit") is None:
            self.detail = {"held": False,
                           "reason": "systemd-inhibit not found — sleep inhibition "
                                     "unavailable on this box (container?)"}
            return self.detail
        try:
            from .proc import child_kwargs

            self._proc = self._popen(
                ["systemd-inhibit", "--what=sleep:idle:handle-lid-switch",
                 "--who=assist", "--why=Elaria event capture", "--mode=block",
                 "sleep", "infinity"],
                **child_kwargs())
            time.sleep(0.05)
            if self._proc.poll() is not None:
                self.detail = {"held": False,
                               "reason": f"systemd-inhibit exited {self._proc.returncode}"}
                self._proc = None
                return self.detail
            self.detail = {"held": True,
                           "reason": "sleep:idle:handle-lid-switch blocked (systemd-inhibit)"}
        except Exception as exc:
            self.detail = {"held": False, "reason": f"{type(exc).__name__}: {exc}"}
        return self.detail

    def release(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        self.detail = {"held": False, "reason": "released"}


# --------------------------------------------------------------------------
# Preflight (§6) — warn, don't block, except disk
# --------------------------------------------------------------------------
def preflight(config, *, segment_minutes, route, speaker, roster,
              inhibitor_held, inhibit_reason, power, level_check,
              disk_free_bytes, calls_used, budget) -> dict:
    warnings: list[str] = []
    refusals: list[str] = []

    if not level_check.get("signal"):
        warnings.append(
            f"mic: level check shows no signal ({level_check.get('reason') or level_check.get('target')}) "
            "— check the mic before the room fills")

    hours = disk_free_bytes / BYTES_PER_HOUR
    if disk_free_bytes < BYTES_PER_HOUR:
        refusals.append(
            f"disk: {disk_free_bytes / 1e6:.0f} MB free — under ONE HOUR of audio "
            f"({BYTES_PER_HOUR / 1e6:.0f} MB/h). Free space before starting.")
    elif hours < 10:
        warnings.append(
            f"disk: {hours:.1f} h of audio free ({disk_free_bytes / 1e9:.1f} GB) — "
            "a full 10 h day will not fit")

    if power.get("on_battery"):
        warnings.append(f"power: ON BATTERY ({power.get('detail')}) — plug in, "
                        "or confirm with --battery-ok")

    if not inhibitor_held:
        warnings.append(f"sleep inhibit: not held ({inhibit_reason}) — a laptop "
                        "that suspends at hour 3 is the likeliest way to lose the day")

    return {
        "mic": level_check,
        "disk": {"free_bytes": disk_free_bytes,
                 "estimate_bytes_per_hour": BYTES_PER_HOUR,
                 "hours_covered": round(hours, 2)},
        "power": power,
        "inhibit": {"held": bool(inhibitor_held), "reason": inhibit_reason},
        "route": route,
        "segment_minutes": segment_minutes,
        "budget": {"used": calls_used, "budget": budget},
        "speaker": speaker,
        "roster": list(roster or []),
        "warnings": warnings,
        "refusals": refusals,
    }


# --------------------------------------------------------------------------
# Durable quota-day ledger (provider calendar: America/Los_Angeles)
# --------------------------------------------------------------------------
class DailyQuotaLedger:
    """Append-only attempted-call log, counted by the provider's LA day."""

    def __init__(self, path: Path, *, route: str = "batch", now_fn=None):
        self.path = Path(path)
        self.route = str(route)
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._la = ZoneInfo("America/Los_Angeles")
        self._eat = ZoneInfo("Africa/Nairobi")

    def _now(self) -> datetime:
        value = self._now_fn()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def day_key(self) -> str:
        return self._now().astimezone(self._la).date().isoformat()

    def used_today(self) -> int:
        day = self.day_key()
        used = 0
        try:
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("day") == day and row.get("route") == self.route:
                        used += 1
        except OSError:
            pass
        return used

    def budget_remaining(self, budget: int) -> int | None:
        if int(budget) <= 0:
            return None
        return max(0, int(budget) - self.used_today())

    def record_call(self, *, segment: int) -> int:
        now = self._now()
        row = {"day": now.astimezone(self._la).date().isoformat(),
               "at": now.isoformat(), "route": self.route,
               "segment": int(segment)}
        ensure_private_dir(self.path.parent)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return self.used_today()

    def status(self, budget: int) -> dict:
        now = self._now().astimezone(self._la)
        next_day = now.date() + timedelta(days=1)
        reset_la = datetime.combine(next_day, datetime_time.min, tzinfo=self._la)
        reset_eat = reset_la.astimezone(self._eat)
        used = self.used_today()
        return {"day": now.date().isoformat(), "used_today": used,
                "budget": int(budget),
                "remaining": (max(0, int(budget) - used) if int(budget) > 0 else None),
                "next_reset_eat": reset_eat.strftime("%Y-%m-%d %H:%M EAT")}


# --------------------------------------------------------------------------
# The queue (§3) — concurrency 1, route pacing, capped retry, deferred pool
# --------------------------------------------------------------------------
class _BudgetExhausted(RuntimeError):
    pass


class SegmentQueue:
    def __init__(self, transcribe_fn, *, on_resolved, on_deferred,
                 tokens_per_second: float = TOKENS_PER_SECOND_DEFAULT,
                 tpm_ceiling: float | None = 20_000.0,
                 daily_call_budget: int = DEFAULT_CALL_BUDGET,
                 max_attempts: int = 3, deferred_retries: int = 0,
                 calls_used: int = 0, reserve_calls: int = 0,
                 used_today_fn=None, on_call=None, fake_transport: bool = False,
                 clock=time.monotonic, sleep=None):
        self._transcribe = transcribe_fn
        self._on_resolved = on_resolved
        self._on_deferred = on_deferred
        self._tokens_per_second = float(tokens_per_second)
        self._tpm_ceiling = (float(tpm_ceiling) if tpm_ceiling is not None
                             and float(tpm_ceiling) > 0 else None)
        self._budget = int(daily_call_budget) if daily_call_budget else 0
        self._max_attempts = min(3, max(1, int(max_attempts)))
        self._deferred_retries = 0  # retries are capped at two per segment
        self._reserve_calls = max(0, int(reserve_calls))
        self._used_today_fn = used_today_fn
        self._on_call = on_call
        self._fake_transport = bool(fake_transport)
        self._reserved_segments: set[int] = set()
        self._clock = clock
        self._sleep = sleep or asyncio.sleep

        self._pending: list[dict] = []
        self._retry: deque[dict] = deque()
        self._parked: list[dict] = []
        self._window: deque[tuple[float, float]] = deque()
        self._attempts: dict[int, int] = {}
        self._pool_tries: dict[int, int] = {}
        self._deferred_marked: set[int] = set()
        self._chunk_results: dict[int, dict[int, str]] = {}
        self._calls_used = max(0, int(calls_used))
        self._inflight = 0
        self._stopping = False
        self._wake = asyncio.Event()

    # -- intake -------------------------------------------------------------
    def submit(self, segment: dict) -> None:
        self._pending.append(segment)
        self._wake.set()

    @property
    def calls_used(self) -> int:
        return int(self._used_today_fn()) if self._used_today_fn else self._calls_used

    def allow_reserved_for(self, index: int) -> None:
        self._reserved_segments.add(int(index))
        self._wake.set()

    def counts(self) -> dict:
        return {"queued": len(self._pending), "retrying": len(self._retry),
                "deferred": len(self._parked) + len(self._retry),
                "calls_used": self.calls_used}

    # -- worker -------------------------------------------------------------
    async def run(self) -> None:
        while True:
            picked = self._pick_next()
            if picked is None:
                if self._stopping:
                    return
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=1.0)
                except TimeoutError:
                    pass
                continue
            self._inflight += 1
            try:
                await self._process(picked)
            finally:
                self._inflight -= 1

    def _pick_next(self):
        if self._pending:
            # newest-closed first for live feel (§3) — append order stays strict
            segment = max(self._pending, key=lambda s: int(s["index"]))
            self._pending.remove(segment)
            return segment
        if self._retry:
            return self._retry.popleft()
        for segment in self._parked:
            if segment.get("quota_deferred") and self._afford(segment):
                self._parked.remove(segment)
                segment.pop("quota_deferred", None)
                return segment
        return None

    def _used_today(self) -> int:
        return int(self._used_today_fn()) if self._used_today_fn else self._calls_used

    def _afford(self, segment: dict) -> bool:
        if self._budget <= 0:
            return True
        remaining = self._budget - self._used_today()
        if int(segment.get("index", -1)) in self._reserved_segments:
            return remaining > 0
        return remaining > self._reserve_calls

    def _estimate_tokens(self, segment: dict) -> float:
        explicit = segment.get("tokens")
        if explicit:
            return float(explicit)
        return float(segment.get("duration_s") or 0.0) * self._tokens_per_second

    async def _pace(self, estimate: float) -> None:
        if self._tpm_ceiling is None:
            return
        ceiling = self._tpm_ceiling * TPM_HEADROOM
        if estimate > ceiling:
            raise ValueError(f"request estimate {estimate:.0f} exceeds route window {ceiling:.0f}")
        while True:
            now = self._clock()
            while self._window and self._window[0][0] + 60.0 <= now:
                self._window.popleft()
            projected = sum(tokens for _, tokens in self._window) + estimate
            if projected > ceiling:
                wait = self._window[0][0] + 60.0 - now + 0.001
                await self._sleep(max(0.01, wait))
                continue
            break
        self._window.append((self._clock(), estimate))

    def _mark_deferred(self, segment: dict, error) -> None:
        index = int(segment["index"])
        segment["error"] = str(error)
        if index not in self._deferred_marked:
            self._deferred_marked.add(index)
            self._on_deferred(segment, error)

    async def _transcribe_segment(self, segment: dict) -> str:
        index = int(segment["index"])
        source = Path(segment["wav"])
        estimate = self._estimate_tokens(segment)
        ceiling = (self._tpm_ceiling * TPM_HEADROOM
                   if self._tpm_ceiling is not None else None)
        chunks: list[tuple[Path, float]] = []
        if ceiling is None or estimate <= ceiling:
            chunks.append((source, estimate))
            temp_context = None
        else:
            count = math.ceil(estimate / ceiling)
            temp_context = tempfile.TemporaryDirectory(prefix="event-chunks-",
                                                        dir=source.parent)
            with wave.open(str(source), "rb") as input_wav:
                params = input_wav.getparams()
                total_frames = input_wav.getnframes()
                if total_frames <= 0:
                    temp_context.cleanup()
                    raise ValueError("cannot split empty WAV")
                while (math.ceil(total_frames / count) * self._tokens_per_second
                       / params.framerate > ceiling):
                    count += 1
                frames_per_chunk = math.ceil(total_frames / count)
                for chunk_index in range(count):
                    pcm = input_wav.readframes(frames_per_chunk)
                    if not pcm:
                        break
                    chunk_path = Path(temp_context.name) / f"part-{chunk_index + 1:03d}.wav"
                    with wave.open(str(chunk_path), "wb") as output_wav:
                        output_wav.setparams(params)
                        output_wav.writeframes(pcm)
                    duration = len(pcm) / (params.sampwidth * params.nchannels * params.framerate)
                    chunks.append((chunk_path, duration * self._tokens_per_second))
        if not chunks:
            if temp_context is not None:
                temp_context.cleanup()
            raise ValueError("WAV produced no transcription chunks")

        completed = self._chunk_results.setdefault(index, {})
        try:
            for chunk_index, (chunk_path, chunk_estimate) in enumerate(chunks):
                if chunk_index in completed:
                    continue
                if not self._afford(segment):
                    raise _BudgetExhausted("daily call budget/reserve exhausted during segment")
                await self._pace(chunk_estimate)
                if self._on_call:
                    self._on_call(segment)  # durable count before any provider attempt
                self._calls_used += 1
                completed[chunk_index] = await self._transcribe(chunk_path)
            return "\n".join(completed[i] for i in range(len(chunks)))
        finally:
            if temp_context is not None:
                temp_context.cleanup()

    async def _process(self, segment: dict) -> None:
        index = int(segment["index"])
        if self._fake_transport:
            self._mark_deferred(segment, "fake transport (--no-transcribe); audio kept")
            return
        if not self._afford(segment):
            # Respect the final-call reserve while capture continues.
            segment["quota_deferred"] = True
            self._mark_deferred(segment, "daily call budget reserve; audio kept")
            self._parked.append(segment)
            return
        attempt = self._attempts.get(index, 0) + 1
        self._attempts[index] = attempt
        try:
            text = await self._transcribe_segment(segment)
        except _BudgetExhausted as exc:
            segment["quota_deferred"] = True
            self._mark_deferred(segment, exc)
            self._parked.append(segment)
            return
        except Exception as exc:
            if attempt < self._max_attempts:
                backoff = min(60.0, 2.0 * (2 ** (attempt - 1)))
                backoff += random.uniform(0.0, 0.3 * backoff)
                await self._sleep(backoff)
                self._pending.append(segment)
            else:
                self._mark_deferred(segment, exc)
            return
        self._on_resolved(segment, text)

    # -- lifecycle ----------------------------------------------------------
    async def drain(self, timeout: float | None = None) -> None:
        """Wait until no active work remains (parked budget items excluded)."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._pending or self._inflight or self._retry:
            if deadline is not None and time.monotonic() >= deadline:
                return
            await asyncio.sleep(0.005)

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        await asyncio.sleep(0)


# --------------------------------------------------------------------------
# Recovery: assemble the document from disk (§5)
# --------------------------------------------------------------------------
def _load_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def assemble_event_document(event_dir: Path) -> dict:
    """Rebuild the complete document from whatever exists on disk.

    A daemon kill leaves state.json + segments; this turns that into the
    full document: transcribed segments land as text, everything else gets
    the explicit "audio kept" marker. Nothing is discarded.
    """
    event_dir = Path(event_dir)
    state = _load_json(event_dir / "state.json")
    labels = _load_json(event_dir / "labels.json")
    seg_dir = event_dir / "segments"

    recs: dict[int, dict] = {}
    for rec in state.get("segments") or []:
        try:
            recs[int(rec["index"])] = dict(rec)
        except (KeyError, TypeError, ValueError):
            continue
    if seg_dir.exists():
        for wav in sorted(seg_dir.glob("seg-*.wav")):
            try:
                index = int(wav.stem.split("-")[1])
            except (IndexError, ValueError):
                continue
            rec = recs.get(index)
            if rec is None:
                mtime = datetime.fromtimestamp(
                    wav.stat().st_mtime).isoformat(timespec="seconds")
                recs[index] = {
                    "index": index, "wav": str(wav), "opened_at": mtime,
                    "speaker": (labels.get("segments") or {}).get(f"{index:03d}")
                               or "Speaker 1",
                    "status": "unknown", "txt": None, "markers": [],
                    "no_signal": False, "bytes": wav.stat().st_size,
                }
            else:
                rec.setdefault("wav", str(wav))

    title = state.get("title") or labels.get("title") or event_dir.name
    blocks: list[str] = []
    transcribed = 0
    deferred: list[dict] = []
    for index in sorted(recs):
        rec = recs[index]
        rec.setdefault("speaker", (labels.get("segments") or {}).get(f"{index:03d}")
                       or "Speaker 1")
        txt_path = seg_dir / f"seg-{index:03d}.txt"
        if txt_path.exists():
            text = txt_path.read_text(encoding="utf-8")
            rec["txt"] = str(txt_path)
            rec["status"] = "done"
            transcribed += 1
        else:
            text = None
            rec["status"] = "deferred"
            deferred.append({"index": index, "wav": rec.get("wav", ""),
                             "error": rec.get("error")})
        blocks.append(render_segment_block(rec, text))

    started = state.get("started_at") or ""
    route = state.get("route") or "batch"
    minutes = state.get("segment_minutes") or SEGMENT_MIN_DEFAULT
    header = (f"# {title}\n\n"
              f"_{started} · route {route} · segment {minutes} min · "
              f"{len(recs)} segment(s)_\n\n")
    content = header + "".join(blocks)

    md_path = event_dir.parent / f"{event_dir.name}.md"
    txt_path = event_dir.parent / f"{event_dir.name}.txt"

    # Recovery is append-only too. Existing editor bytes are never replaced;
    # only blocks absent from that particular copy are appended at its EOF.
    indexed_blocks = list(zip(sorted(recs), blocks))
    for output_path in (md_path, txt_path):
        if not output_path.exists():
            _atomic_write(output_path, header)
            existing = ""
        else:
            try:
                existing = output_path.read_text(encoding="utf-8")
            except OSError:
                existing = ""
        present = {int(value) for value in re.findall(
            r"^## .* · seg (\d+)", existing, flags=re.MULTILINE)}
        missing = [block for index, block in indexed_blocks if index not in present]
        if not existing and output_path.exists() and output_path.stat().st_size == 0:
            with open(output_path, "ab") as handle:
                handle.write(header.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
        if missing:
            with open(output_path, "ab") as handle:
                payload = "".join(missing).encode("utf-8")
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
    if state:
        state["segments"] = [recs[i] for i in sorted(recs)]
        _atomic_write(event_dir / "state.json", json.dumps(state, indent=2))

    return {"document": str(md_path), "txt_document": str(txt_path),
            "word_count": len(content.split()), "segments": len(recs),
            "transcribed": transcribed, "deferred": deferred,
            "event_dir": str(event_dir), "title": title,
            "state": state.get("status", "unknown")}


def rename_event_speaker(event_dir: Path, selector: str, new_name: str) -> dict:
    """Update label metadata only; never rename live document headers."""
    event_dir = Path(event_dir)
    new_name = str(new_name).strip()
    if not new_name or "\n" in new_name or "\r" in new_name:
        raise ValueError("speaker name must be a non-empty single line")
    labels_path = event_dir / "labels.json"
    labels = _load_json(labels_path)
    roster = [str(name) for name in labels.get("roster", [])]
    selector = str(selector).strip()
    match = re.fullmatch(r"S(\d+)", selector, flags=re.IGNORECASE)
    if match:
        position = int(match.group(1)) - 1
        if position < 0 or position >= len(roster):
            raise ValueError(f"speaker selector {selector!r} is not in the roster")
        old_name = roster[position]
    elif selector in roster:
        old_name = selector
    else:
        raise ValueError(f"speaker {selector!r} is not in the roster")
    if new_name in roster and new_name != old_name:
        raise ValueError(f"speaker name {new_name!r} is already in the roster")
    if old_name == new_name:
        return {"state": "renamed", "old_name": old_name, "new_name": new_name,
                "mapping": dict(labels.get("speaker_aliases") or {})}
    aliases = dict(labels.get("speaker_aliases") or {})
    for source, target in list(aliases.items()):
        if target == old_name:
            aliases[source] = new_name
    aliases[old_name] = new_name
    labels["speaker_aliases"] = aliases
    labels["roster"] = [new_name if name == old_name else name for name in roster]
    labels["segments"] = {
        key: new_name if value == old_name else value
        for key, value in (labels.get("segments") or {}).items()
    }
    _atomic_write(labels_path, json.dumps(labels, indent=2))

    state_path = event_dir / "state.json"
    state = _load_json(state_path)
    if state:
        state["roster"] = [new_name if name == old_name else name
                           for name in state.get("roster", [])]
        if state.get("active_speaker") == old_name:
            state["active_speaker"] = new_name
        for rec in state.get("segments") or []:
            if rec.get("speaker") == old_name:
                rec["speaker"] = new_name
        _atomic_write(state_path, json.dumps(state, indent=2))
    return {"state": "renamed", "old_name": old_name, "new_name": new_name,
            "mapping": aliases}


def export_event_document(event_dir: Path, format: str = "md") -> Path:
    """Write a renamed transcript copy; the live .md/.txt are read-only here."""
    event_dir = Path(event_dir)
    format = str(format).lower()
    if format not in {"md", "txt"}:
        raise ValueError("event export format must be md or txt")
    stem = event_dir.name
    source_path = event_dir.parent / f"{stem}.{format}"
    source = source_path.read_text(encoding="utf-8")
    aliases = _load_json(event_dir / "labels.json").get("speaker_aliases") or {}

    def rename_header(match):
        speaker = match.group(2)
        visited = set()
        while speaker in aliases and speaker not in visited:
            visited.add(speaker)
            speaker = str(aliases[speaker])
        return match.group(1) + speaker + match.group(3)

    copied = re.sub(r"^(## \d{2}:\d{2} · )(.+?)( · seg \d{3}.*)$",
                    rename_header, source, flags=re.MULTILINE)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = event_dir.parent / f"{stem}-export-{stamp}.{format}"
    suffix = 2
    while destination.exists():
        destination = event_dir.parent / f"{stem}-export-{stamp}-{suffix}.{format}"
        suffix += 1
    with open(destination, "xb") as handle:
        handle.write(copied.encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def latest_event_dir(root: Path, *, running_only: bool = False) -> Path | None:
    root = Path(root)
    if not root.exists():
        return None
    candidates = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir() or not (path / "state.json").exists():
            continue
        state = _load_json(path / "state.json")
        if running_only and state.get("status") not in ("running", "stopping"):
            continue
        candidates.append(path)
    return candidates[0] if candidates else None


def recover_event(config) -> dict:
    """Daemon-down `event stop` (§5): assemble the full document from disk."""
    root = config.data_dir / "events"
    event_dir = latest_event_dir(root, running_only=True)
    if event_dir is None:
        return {"state": "not-running"}
    summary = assemble_event_document(event_dir)
    state = _load_json(event_dir / "state.json")
    state["status"] = "recovered"
    state["stopped_at"] = iso_now()
    _atomic_write(event_dir / "state.json", json.dumps(state, indent=2))
    summary["state"] = "recovered"
    return summary


def status_from_disk(config) -> dict:
    """Post-mortem `event status` — works with the daemon gone."""
    root = config.data_dir / "events"
    event_dir = latest_event_dir(root)
    state = _load_json(event_dir / "state.json") if event_dir else {}
    route = state.get("route") or (config.section("event") or {}).get("route", "batch")
    quota = config.section("quota") or {}
    route_quota = (quota.get("models") or {}).get(
        "transcribe-live" if route == "transcribe-live" else "transcribe-batch", {})
    route_rpd = route_quota.get(
        "rpd", quota.get("transcribe_live_rpd" if route == "transcribe-live"
                          else "transcribe_batch_rpd"))
    budget = int(route_rpd) if route_rpd not in (None, 0, "unlimited") else int(
        (config.section("event") or {}).get("daily_call_budget", DEFAULT_CALL_BUDGET))
    quota_status = DailyQuotaLedger(
        root / "transcribe-calls.jsonl", route=route).status(budget)
    calls = {"used": quota_status["used_today"],
             "used_today": quota_status["used_today"], "budget": budget,
             "remaining": quota_status["remaining"]}
    quota_summary = {"day": quota_status["day"],
                     "next_reset_eat": quota_status["next_reset_eat"]}
    if event_dir is None:
        return {"state": "not-running", "running": False, "route": route,
                "calls": calls, "quota": quota_summary,
                "transport": "real transcription"}
    segments = state.get("segments") or []
    counts = {"opened": len(segments),
              "transcribed": sum(1 for s in segments if s.get("status") == "done"),
              "queued": sum(1 for s in segments
                            if s.get("status") in ("queued", "transcribing", "open")),
              "deferred": sum(1 for s in segments if s.get("status") == "deferred")}
    return {
        "state": state.get("status", "unknown"),
        "running": state.get("status") == "running",
        "title": state.get("title", ""),
        "active_speaker": state.get("active_speaker", ""),
        "roster": state.get("roster") or [],
        "segments": counts,
        "document": str(event_dir.parent / f"{event_dir.name}.md"),
        "event_dir": str(event_dir), "calls": calls, "quota": quota_summary,
        "transport": ("fake — no calls will be made"
                      if state.get("transport") == "fake" else "real transcription"),
        "route": route,
        "started_at": state.get("started_at", ""),
    }


# --------------------------------------------------------------------------
# The service
# --------------------------------------------------------------------------
class EventService:
    def __init__(self, config, store, *, transcribe_fn=None, client=None,
                 capture_factory=None, inhibitor=None, clock=time.monotonic,
                 now_fn=None, segment_minutes=None, route=None,
                 flush_min_s: float = FLUSH_MIN_S, max_attempts: int = 3,
                 deferred_retries: int = 2, daily_call_budget=None,
                 tpm_ceiling=None, tokens_per_second=None,
                 power_probe=None, level_checker=None, stop_grace_s=None,
                 quota_now_fn=None):
        settings = config.section("event") or {}
        self.config = config
        self.store = store
        self._client = client
        self._transcribe_fn = transcribe_fn or self._make_transcribe_fn()
        self._capture_factory = capture_factory
        self._inhibitor = inhibitor if inhibitor is not None else SleepInhibitor()
        self._clock = clock
        self._now_fn = now_fn or (lambda: datetime.now())
        self._segment_minutes = float(
            segment_minutes if segment_minutes is not None
            else settings.get("segment_minutes", SEGMENT_MIN_DEFAULT))
        self._route = str(route or settings.get("route", "batch"))
        self._quota_ledger = DailyQuotaLedger(
            config.data_dir / "events" / "transcribe-calls.jsonl",
            route=self._route, now_fn=quota_now_fn)
        self._fake_transport = False
        self._flush_min_s = float(flush_min_s)
        self._max_attempts = int(max_attempts)
        self._deferred_retries = int(deferred_retries)
        quota = config.section("quota") or {}
        quota_models = quota.get("models") or {}
        quota_key = ("transcribe-live" if self._route == "transcribe-live"
                     else "transcribe-batch")
        route_quota = quota_models.get(quota_key) or {}
        flat_prefix = quota_key.replace("-", "_")
        route_rpd = route_quota.get("rpd", quota.get(f"{flat_prefix}_rpd"))
        configured_budget = int(
            daily_call_budget if daily_call_budget is not None
            else settings.get("daily_call_budget", DEFAULT_CALL_BUDGET))
        if route_rpd not in (None, 0, "unlimited"):
            self._budget = min(int(route_rpd), configured_budget) \
                if configured_budget > 0 else int(route_rpd)
        else:
            self._budget = configured_budget
        route_tpm = route_quota.get("tpm", quota.get(f"{flat_prefix}_tpm"))
        if tpm_ceiling is not None:
            self._tpm_ceiling = float(tpm_ceiling) if float(tpm_ceiling) > 0 else None
        elif route_tpm not in (None, 0, "unlimited"):
            self._tpm_ceiling = float(route_tpm)
        elif self._route == "transcribe-live":
            fallback_tpm = settings.get("tpm_ceiling", 20_000.0)
            self._tpm_ceiling = float(fallback_tpm) if float(fallback_tpm) > 0 else None
        else:
            # Verified batch quota only publishes RPD; do not borrow Live TPM.
            self._tpm_ceiling = None
        self._tokens_per_second = float(
            tokens_per_second if tokens_per_second is not None
            else settings.get("tokens_per_second", TOKENS_PER_SECOND_DEFAULT))
        self._stop_grace_s = float(stop_grace_s if stop_grace_s is not None
                                   else settings.get("stop_grace_s", 120.0))
        self._inhibit_enabled = bool(settings.get("sleep_inhibit", True))
        self._power_probe = power_probe or power_status
        self._level_checker = level_checker

        self._state: dict | None = None
        self._segments: dict[int, dict] = {}
        self._speaker = SpeakerBook()
        self._speaker_aliases: dict[str, str] = {}
        self._document: EventDocument | None = None
        self._appender: OrderedAppender | None = None
        self._queue: SegmentQueue | None = None
        self._queue_task: asyncio.Task | None = None
        self._background_queues: set[asyncio.Task] = set()
        self._capture_task: asyncio.Task | None = None
        self._source = None
        self._current: dict | None = None
        self._current_sink = None
        self._event_dir: Path | None = None
        self._next_index = 1
        self._capture_ended = False
        self._calls_used = 0

    # -- defaults -----------------------------------------------------------
    def _make_transcribe_fn(self):
        async def transcribe(path) -> str:
            from . import asr
            from .gemini_client import GeminiClient

            client = self._client or GeminiClient(self.config, self.store)
            result = await asyncio.to_thread(
                asr.transcribe_file, self.config, client, str(path))
            return result.text
        return transcribe

    def _mic_target(self) -> str | None:
        return (self.config.section("event").get("mic_target")
                or self.config.section("meeting").get("mic_target")
                or self.config.section("capture").get("mic_target") or None)

    def _build_source(self, source_name=None):
        if self._capture_factory is not None:
            return self._capture_factory(source_name)
        from .capture import PipeWireCapture, SimulatedCapture

        if source_name == "simulated":
            return SimulatedCapture(speech_frames=100_000, frame_ms=30, realtime=True)
        try:
            return PipeWireCapture(self._mic_target(), frame_ms=30)
        except RuntimeError:
            return SimulatedCapture(speech_frames=100_000, frame_ms=30, realtime=True)

    def _level_check(self) -> dict:
        if self._level_checker is not None:
            return self._level_checker()
        from . import capture

        try:
            return capture.live_level_check(self._mic_target(), seconds=3.0)
        except Exception as exc:
            return {"available": False, "signal": False, "target": "mic",
                    "reason": f"{type(exc).__name__}: {exc}"}

    @property
    def _segment_seconds(self) -> float:
        return max(0.05, float(self._segment_minutes) * 60.0)

    # -- state persistence --------------------------------------------------
    def _write_state(self) -> None:
        if self._state is None or self._event_dir is None:
            return
        self._state["segments"] = [self._segments[i] for i in sorted(self._segments)]
        self._state["active_speaker"] = self._speaker.active
        self._state["roster"] = list(self._speaker.roster)
        self._state["segment_index"] = self._next_index
        self._state["calls_used"] = self._calls_used
        _atomic_write(self._event_dir / "state.json", json.dumps(self._state, indent=2))

    def _write_labels(self) -> None:
        if self._event_dir is None:
            return
        labels = {
            "title": (self._state or {}).get("title", ""),
            "roster": list(self._speaker.roster),
            "segments": {f"{index:03d}": rec.get("speaker", "")
                         for index, rec in sorted(self._segments.items())},
            "speaker_aliases": dict(self._speaker_aliases),
            "updated_at": self._now_fn().isoformat(timespec="seconds")
            if isinstance(self._now_fn(), datetime) else iso_now(),
        }
        _atomic_write(self._event_dir / "labels.json", json.dumps(labels, indent=2))

    # -- segments -----------------------------------------------------------
    def _open_segment(self) -> dict:
        when = self._now_fn()
        opened_at = when.isoformat(timespec="seconds") if isinstance(when, datetime) else str(when)
        index = self._next_index
        wav_path = self._event_dir / "segments" / f"seg-{index:03d}.wav"
        ensure_private_dir(wav_path.parent)
        sink = WavSink(wav_path)
        rec = {"index": index, "wav": str(wav_path), "speaker": self._speaker.active,
               "opened_at": opened_at, "closed_at": None, "duration_s": None,
               "bytes": 0, "peak": 0.0, "status": "open", "txt": None,
               "error": None, "markers": [], "no_signal": False,
               "opened_mono": self._clock()}
        self._segments[index] = rec
        self._current = rec
        self._current_sink = sink
        self._next_index = index + 1
        self._appender.expect(index)
        self._write_state()
        return rec

    def _close_segment(self, rec: dict, sink) -> dict:
        duration = sink.close()
        when = self._now_fn()
        rec["closed_at"] = (when.isoformat(timespec="seconds")
                            if isinstance(when, datetime) else str(when))
        rec["duration_s"] = round(float(duration), 3)
        rec["status"] = "queued"
        if rec["peak"] < NO_SIGNAL_PEAK:
            rec["no_signal"] = True
        if self.store is not None:
            # §5: a dead-mic hour is discoverable from the log, not at 6pm
            self.store.log_persona_event(iso_now(), "capture.stats", json.dumps({
                "segment": rec["index"], "node": getattr(self._source, "target", "unknown"),
                "bytes": rec["bytes"], "peak": round(rec["peak"], 4),
                "duration_s": rec["duration_s"], "wav": rec["wav"],
            }))
        self._write_labels()
        self._write_state()
        self._queue.submit(rec)
        return rec

    def _rotate(self) -> None:
        # §3: open the NEXT segment first, then close + enqueue the previous.
        old, old_sink = self._current, self._current_sink
        self._current = self._current_sink = None
        self._open_segment()
        if old is not None and old_sink is not None:
            self._close_segment(old, old_sink)

    # -- capture loop -------------------------------------------------------
    async def _capture_loop(self) -> None:
        try:
            async for frame in self._source.frames():
                if self._current is None:
                    continue
                now = self._clock()
                if now - self._current["opened_mono"] >= self._segment_seconds:
                    self._rotate()
                self._current_sink.write(frame)
                rec = self._current
                rec["bytes"] += len(frame)
                rec["peak"] = max(rec["peak"], frame_rms(frame))
        except Exception as exc:
            if self.store is not None:
                self.store.log_persona_event(
                    iso_now(), "capture.stats",
                    json.dumps({"segment": (self._current or {}).get("index"),
                                "node": getattr(self._source, "target", "unknown"),
                                "error": f"{type(exc).__name__}: {exc}"}))
        finally:
            self._capture_ended = True
            if self._current is not None and (self._state or {}).get("status") == "running":
                # unexpected capture end: close + enqueue, stay honest
                old, old_sink = self._current, self._current_sink
                self._current = self._current_sink = None
                self._close_segment(old, old_sink)

    async def wait_capture_idle(self, timeout: float = 30.0) -> bool:
        if self._capture_task is None:
            return True
        try:
            await asyncio.wait_for(asyncio.shield(self._capture_task), timeout)
            return True
        except TimeoutError:
            return False
        except asyncio.CancelledError:
            return True

    # -- callbacks ----------------------------------------------------------
    def _on_resolved(self, segment: dict, text: str) -> None:
        index = int(segment["index"])
        rec = self._segments.get(index, segment)
        late = rec.get("status") == "deferred"
        txt_path = self._event_dir / "segments" / f"seg-{index:03d}.txt"
        _atomic_write(txt_path, text or "")
        rec["txt"] = str(txt_path)
        rec["status"] = "done"
        self._write_state()
        if late:
            self._appender.append_late(
                index, render_segment_block({**rec, "recovered": True}, text))
        else:
            self._appender.resolved(index, render_segment_block(rec, text))

    def _on_deferred(self, segment: dict, error) -> None:
        index = int(segment["index"])
        rec = self._segments.get(index, segment)
        rec["status"] = "deferred"
        rec["error"] = str(error)
        self._write_state()
        self._appender.deferred(index, render_segment_block(rec, None))

    # -- lifecycle ----------------------------------------------------------
    async def start(self, *, title=None, speakers=None, segment_minutes=None,
                    source=None, battery_ok: bool = False,
                    no_transcribe: bool = False) -> dict:
        if self._state is not None and self._state.get("status") == "running":
            return {"state": "already-event", "title": self._state.get("title", ""),
                    "document": str(self._document.md_path) if self._document else "",
                    "event_dir": str(self._event_dir or "")}
        if segment_minutes is not None:
            self._segment_minutes = float(segment_minutes)
        self._fake_transport = bool(no_transcribe)

        power = self._power_probe()
        roster = [s.strip() for s in str(speakers or "").split(",") if s.strip()]
        self._speaker = SpeakerBook(roster or None)
        self._speaker_aliases = {}

        def build_report(inhibit_detail):
            return preflight(
                self.config, segment_minutes=self._segment_minutes,
                route=self._route, speaker=self._speaker.active,
                roster=self._speaker.roster,
                inhibitor_held=inhibit_detail.get("held", False),
                inhibit_reason=inhibit_detail.get("reason", ""),
                power=power, level_check=level,
                disk_free_bytes=free_disk_bytes(events_root(self.config)),
                calls_used=0, budget=self._budget)

        level = self._level_check()
        if power.get("on_battery") and not battery_ok:
            report = build_report({"held": False, "reason": "not acquired"})
            return {"state": "needs-battery-ok", "preflight": report}

        inhibit_detail = (self._inhibitor.acquire() if self._inhibit_enabled
                          else {"held": False,
                                "reason": "disabled in [event] sleep_inhibit"})
        report = build_report(inhibit_detail)
        if report["refusals"]:
            self._inhibitor.release()
            return {"state": "refused", "preflight": report}

        # event dir + state + labels + live document + segment 001
        when = self._now_fn()
        started_at = (when.isoformat(timespec="seconds")
                      if isinstance(when, datetime) else str(when))
        root = events_root(self.config)
        slug = slugify(title or f"event {started_at}")
        base = f"{getattr(when, 'date', lambda: '')() or ''}-{slug}".lstrip("-")
        name, suffix = base or slug, 2
        while (root / name).exists() or (root / f"{name}.md").exists() \
                or (root / f"{name}.txt").exists():
            name = f"{base}-{suffix}"
            suffix += 1
        self._event_dir = ensure_private_dir(root / name)
        self._title = str(title or name)
        self._state = {
            "title": self._title, "status": "running", "route": self._route,
            "transport": "fake" if self._fake_transport else "real",
            "segment_minutes": self._segment_minutes, "started_at": started_at,
            "stopped_at": None, "segments": [], "doc": None,
            "calls_used": self._quota_ledger.used_today(), "call_budget": self._budget,
        }
        self._document = EventDocument(
            root / f"{name}.md", root / f"{name}.txt")
        self._document.write_header(self._title, started_at,
                                    {"route": self._route,
                                     "segment_minutes": self._segment_minutes})
        self._state["doc"] = str(self._document.md_path)
        self._appender = OrderedAppender(self._document)
        self._segments = {}
        self._next_index = 1
        self._calls_used = self._quota_ledger.used_today()
        self._capture_ended = False

        # Queue callbacks are scoped to this event. Stop can return while this
        # queue drains in the background, and a later event cannot redirect
        # an old result into its document/state.
        event_dir = self._event_dir
        event_appender = self._appender
        event_segments = self._segments
        event_state = self._state
        event_queue: SegmentQueue | None = None

        def save_event_state() -> None:
            if event_queue is not None:
                event_state["calls_used"] = event_queue.calls_used
            event_state["segments"] = [event_segments[i]
                                       for i in sorted(event_segments)]
            _atomic_write(event_dir / "state.json",
                          json.dumps(event_state, indent=2))

        def record_event_call(segment: dict) -> None:
            self._calls_used = self._quota_ledger.record_call(
                segment=int(segment["index"]))
            event_state["calls_used"] = self._calls_used
            _atomic_write(event_dir / "state.json", json.dumps(event_state, indent=2))

        def on_resolved(segment: dict, text: str) -> None:
            index = int(segment["index"])
            rec = event_segments.get(index, segment)
            late = rec.get("status") == "deferred"
            expected_block = render_segment_block(rec, None) if late else None
            expected_suffix = ""
            if late:
                later_blocks = []
                for later_index, later_rec in sorted(event_segments.items()):
                    if later_index <= index:
                        continue
                    if later_rec.get("status") == "done":
                        later_path = later_rec.get("txt")
                        later_text = (Path(later_path).read_text(encoding="utf-8")
                                      if later_path and Path(later_path).exists() else "")
                        later_blocks.append(render_segment_block(later_rec, later_text))
                    elif later_rec.get("status") == "deferred":
                        later_blocks.append(render_segment_block(later_rec, None))
                expected_suffix = "".join(later_blocks)
            txt_path = event_dir / "segments" / f"seg-{index:03d}.txt"
            _atomic_write(txt_path, text or "")
            rec["txt"] = str(txt_path)
            block = render_segment_block(rec, text)
            if late:
                event_appender.append_late(index, block,
                                           expected_block=expected_block,
                                           expected_suffix=expected_suffix)
            else:
                event_appender.resolved(index, block)
            rec["status"] = "done"
            save_event_state()

        def on_deferred(segment: dict, error) -> None:
            index = int(segment["index"])
            rec = event_segments.get(index, segment)
            rec["status"] = "deferred"
            rec["error"] = str(error)
            save_event_state()
            event_appender.deferred(index, render_segment_block(rec, None))

        event_queue = SegmentQueue(
            self._transcribe_fn, on_resolved=on_resolved,
            on_deferred=on_deferred,
            tokens_per_second=self._tokens_per_second,
            tpm_ceiling=self._tpm_ceiling,
            daily_call_budget=self._budget,
            max_attempts=self._max_attempts,
            deferred_retries=0,
            calls_used=self._quota_ledger.used_today(),
            reserve_calls=2 if self._budget > 0 else 0,
            used_today_fn=self._quota_ledger.used_today,
            on_call=record_event_call,
            fake_transport=self._fake_transport,
            clock=self._clock)
        self._queue = event_queue
        self._queue_task = asyncio.create_task(event_queue.run())
        self._background_queues.add(self._queue_task)
        self._queue_task.add_done_callback(self._background_queues.discard)

        self._source = source if hasattr(source, "frames") else self._build_source(source)
        self._open_segment()                              # segment 001 + timer (§3)
        self._write_labels()
        self._write_state()
        self._capture_task = asyncio.create_task(self._capture_loop())
        return {"state": "event", "title": self._title,
                "document": str(self._document.md_path),
                "txt_document": str(self._document.txt_path),
                "event_dir": str(self._event_dir), "segment": 1,
                "transport": ("fake — no calls will be made" if self._fake_transport
                              else "real transcription"),
                "simulated_capture": getattr(self._source, "target", "") == "simulated",
                "preflight": report}

    async def stop(self) -> dict:
        if self._state is None or self._state.get("status") != "running":
            return {"state": "not-running"}
        self._state["status"] = "stopping"
        self._write_state()
        if self._source is not None:
            try:
                close_task = asyncio.create_task(self._source.aclose())
                _, pending = await asyncio.wait({close_task}, timeout=0.5)
                if pending:
                    close_task.cancel()
            except Exception:  # noqa: S110 - stop must survive capture close failure
                pass
        capture_idle = await self.wait_capture_idle(
            timeout=min(2.0, self._stop_grace_s))
        if not capture_idle and self._capture_task is not None:
            self._capture_task.cancel()
        if self._current is not None and self._queue is not None:
            self._queue.allow_reserved_for(int(self._current["index"]))
        if self._current is not None and self._current_sink is not None:
            old, old_sink = self._current, self._current_sink
            self._current = self._current_sink = None
            self._close_segment(old, old_sink)
        # Never wait for remote transcription in this IPC handler. First make
        # every captured segment safe on disk: already-landed text remains;
        # every unresolved segment gets its durable audio-kept marker.
        if self._appender is not None:
            self._appender.force_pending(
                lambda i: render_segment_block(self._segments.get(i, {"index": i,
                                                                      "wav": ""}), None))
        for rec in self._segments.values():
            if rec.get("status") not in ("done", "deferred"):
                rec["status"] = "deferred"
                rec["error"] = "stop: transcript queued for later"
        self._write_state()
        if self._queue is not None:
            # The queue drains in the background. All unresolved audio already
            # has a durable marker, so this does not extend the IPC call.
            await self._queue.stop()
        summary = {
            "document": str(self._document.md_path),
            "txt_document": str(self._document.txt_path),
            "word_count": self._document.word_count(),
            "segments": len(self._segments),
            "transcribed": sum(1 for s in self._segments.values()
                                if s.get("status") == "done"),
            "queued": sum(1 for s in self._segments.values()
                          if s.get("status") != "done"),
            "deferred": [{"index": i, "wav": s.get("wav", "")}
                         for i, s in sorted(self._segments.items())
                         if s.get("status") != "done"],
            "event_dir": str(self._event_dir), "title": self._title,
        }
        self._inhibitor.release()
        self._state["status"] = "stopped"
        self._state["stopped_at"] = iso_now()
        self._write_state()
        summary["state"] = "stopped"
        return summary

    async def close(self) -> None:
        """Daemon shutdown: durable stop, then bounded worker teardown."""
        try:
            await self.stop()
        except Exception:
            self._inhibitor.release()
        finally:
            tasks = {task for task in self._background_queues if not task.done()}
            for task in tasks:
                task.cancel()
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=0.2)
                for task in pending:
                    task.cancel()
                for task in done:
                    try:
                        task.exception()
                    except asyncio.CancelledError:
                        pass

    # -- speakers -----------------------------------------------------------
    def speaker_switch(self, name: str | None = None, *, next_: bool = False) -> dict:
        if self._state is None or self._state.get("status") != "running":
            return {"state": "not-running"}
        outgoing = self._speaker.active
        incoming = self._speaker.switch_next() if next_ else self._speaker.switch_to(name)
        when = self._now_fn()
        stamp = (when.strftime("%H:%M:%S") if isinstance(when, datetime) else str(when))
        marker = f"[→ {incoming} @ {stamp}]"
        elapsed = 0.0
        if self._current is not None:
            elapsed = self._clock() - self._current["opened_mono"]
        flushed = False
        if (self._route == "transcribe-live" and self._current is not None
                and elapsed >= self._flush_min_s):
            # live route: flush the segment under the outgoing label (§4)
            self._rotate()
            flushed = True
        elif self._current is not None:
            # batch route (or sub-flush live): inline marker, no flush (§3/§4)
            self._current["markers"].append(marker)
        self._write_labels()
        self._write_state()
        return {"state": "speaker", "outgoing_speaker": outgoing,
                "incoming_speaker": incoming, "marker": marker,
                "flushed": flushed, "active_speaker": self._speaker.active,
                "roster": list(self._speaker.roster)}

    def speaker_next(self) -> dict:
        return self.speaker_switch(next_=True)

    def speaker_status(self) -> dict:
        elapsed = 0.0
        if self._current is not None:
            elapsed = self._clock() - self._current["opened_mono"]
        return {"state": "speaker", "active_speaker": self._speaker.active,
                "roster": list(self._speaker.roster),
                "elapsed_s": round(elapsed, 1),
                "running": bool(self._state and self._state.get("status") == "running")}

    # -- status -------------------------------------------------------------
    def _latest_event_dir(self) -> Path | None:
        return (self._event_dir if self._event_dir is not None
                else latest_event_dir(events_root(self.config)))

    def rename_speaker(self, selector: str, new_name: str) -> dict:
        event_dir = self._latest_event_dir()
        if event_dir is None:
            return {"state": "not-running"}
        result = rename_event_speaker(event_dir, selector, new_name)
        if self._event_dir == event_dir:
            old_name = result["old_name"]
            self._speaker.roster = [result["new_name"] if name == old_name else name
                                    for name in self._speaker.roster]
            if self._speaker.active == old_name:
                self._speaker.active = result["new_name"]
            for rec in self._segments.values():
                if rec.get("speaker") == old_name:
                    rec["speaker"] = result["new_name"]
            self._speaker_aliases = dict(
                _load_json(event_dir / "labels.json").get("speaker_aliases") or {})
            self._write_state()
        result["export"] = str(export_event_document(event_dir, "md"))
        return result

    def export_document(self, format: str = "md") -> dict:
        event_dir = self._latest_event_dir()
        if event_dir is None:
            return {"state": "not-running"}
        path = export_event_document(event_dir, format)
        return {"state": "exported", "format": format, "path": str(path)}

    def edit_segment(self, index: int, base_text: str, new_text: str) -> dict:
        document = self._document
        if document is None:
            event_dir = latest_event_dir(events_root(self.config))
            if event_dir is None:
                return {"state": "not-running"}
            document = EventDocument(event_dir.parent / f"{event_dir.name}.md")
        return document.edit_segment(index, base_text, new_text)

    def status(self) -> dict:
        running = bool(self._state and self._state.get("status") == "running")
        segments = list(self._segments.values())
        counts = {
            "opened": len(segments),
            "transcribed": sum(1 for s in segments if s.get("status") == "done"),
            "queued": sum(1 for s in segments
                          if s.get("status") in ("queued", "transcribing")),
            "deferred": sum(1 for s in segments if s.get("status") == "deferred"),
        }
        elapsed = 0.0
        if self._current is not None:
            elapsed = self._clock() - self._current["opened_mono"]
        root = events_root(self.config)
        quota_status = self._quota_ledger.status(self._budget)
        return {
            "running": running,
            "state": ("running" if running
                      else (self._state or {}).get("status", "not-running")),
            "title": (self._state or {}).get("title", ""),
            "active_speaker": self._speaker.active,
            "roster": list(self._speaker.roster),
            "segment_index": (self._current or {}).get("index", self._next_index - 1),
            "segment_elapsed_s": round(elapsed, 1),
            "segments": counts,
            "calls": {"used": quota_status["used_today"],
                      "used_today": quota_status["used_today"],
                      "budget": self._budget,
                      "remaining": quota_status["remaining"],
                      "reserve": min(2, self._budget) if self._budget > 0 else 0},
            "quota": {"tpm_ceiling": self._tpm_ceiling,
                      "headroom": TPM_HEADROOM if self._tpm_ceiling else None,
                      "day": quota_status["day"],
                      "next_reset_eat": quota_status["next_reset_eat"]},
            "transport": ("fake — no calls will be made" if self._fake_transport
                          else "real transcription"),
            "disk": {"free_bytes": free_disk_bytes(root),
                     "used_bytes": event_dir_bytes(self._event_dir)
                     if self._event_dir else 0},
            "document": str(self._document.md_path) if self._document else "",
            "event_dir": str(self._event_dir or ""),
            "route": self._route,
            "segment_minutes": self._segment_minutes,
            "started_at": (self._state or {}).get("started_at", ""),
        }
