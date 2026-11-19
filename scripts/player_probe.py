#!/usr/bin/env python3
"""Playback probe — why did a wav produce no sound? Exit code, stderr, first byte.

Ask 47 (owner): *log paplay's exit code and stderr*. Ask 45 / decision 29: the
voice "none-played" bug is **PARKED** — this file is a DIAGNOSTIC, not a fix. It
runs the same player command the daemon runs (`Tts._player_command`, i.e.
`[tts] player`, else pw-play → paplay → aplay) against a wav and reports what
happened, in numbers.

The decisive fact this exists to surface: **a player can exit 0 and play
nothing.** `paplay` exits 0 when it successfully hands samples to a sink that
nobody is listening to (wrong sink, suspended, muted, or a null sink), so "exit
code 0" has never been evidence of audible sound. That is why the probe separates:

  exit_code       the process's own verdict
  stderr_lines    what it complained about (first line verbatim)
  stderr_empty    1 = it said nothing, which is NOT the same as "it was fine"
  first_byte_ms   when the FIRST decoded sample left the player (see below)
  first_byte_hex  that sample, so digital silence is visible as 0000
  wav_peak        the loudest sample in the file (a silent file cannot sound)
  verdict         one of: no_player, missing_file, silent_file, timeout, silence,
                  exited_nonzero, exit_zero_no_output, played

`--telemetry` reads the other end: the daemon's own durable record. Every ack
writes a persona event `{"kind": "ack", "speech": {"played": ...}}`, so the probe
reports how many of the newest ack rows claim playback and how many do not —
that is the "none-played" distribution as NUMBERS, from the store, not from a
journal grep that cannot tell a stale daemon from an absent session.

Read-only and side-effect free: it plays only the file you point it at, only when
you do not pass `--dry-run`, and it never writes the store, never changes config,
never touches the daemon. **Diagnose only — do not "fix" the none-played cause
here; it is parked with the owner.**

Usage:
  player_probe.py                        # newest ack wav from the tts cache, telemetry included
  player_probe.py --wav /tmp/t.wav --dry-run
  player_probe.py --command "pw-play" --wav /tmp/t.wav
  player_probe.py --telemetry-only --db ~/.local/share/assistant/assistant.db
  player_probe.py --self-test            # player-less positive/negative controls
  player_probe.py --checksum

Integrity: `scripts/player_probe.py.sha256` holds this file's digest under its
repository-relative name; verify from the repository root with
`sha256sum -c scripts/player_probe.py.sha256`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
import wave
from pathlib import Path

UNKNOWN = "-1"

# Players the daemon would try, in its own order (tts.Tts._player_command).
DEFAULT_ORDER = ("pw-play", "paplay", "aplay")

EMPTY_FAILS_TO_DISCRIMINATE = (
    "a zero-row telemetry read cannot tell apart: (a) no ack has ever been "
    "requested, (b) the daemon wrote to a different database, (c) the ack rows "
    "predate the `speech` field, or (d) every ack was suppressed before it "
    "reached speech — the count is a fact only about this file"
)


# ---------------------------------------------------------------------------
# wav facts (pure)
# ---------------------------------------------------------------------------
def wav_facts(path: Path) -> dict:
    """Format + peak of a wav, in numbers. `peak` is the loudest sample."""
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        frames = wav.getnframes()
        raw = wav.readframes(frames)
    peak = 0
    first_sample = None
    if width == 2 and raw:
        import struct

        samples = struct.unpack(f"<{len(raw) // 2}h", raw[: len(raw) - len(raw) % 2])
        peak = max((abs(sample) for sample in samples), default=0)
        first_sample = samples[0] if samples else None
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "channels": channels,
        "sampwidth_bits": width * 8,
        "rate_hz": rate,
        "frames": frames,
        "duration_s": round(frames / rate, 3) if rate else None,
        "peak": round(peak / 32768, 4) if width == 2 else UNKNOWN,
        "peak_hex": f"{peak & 0xFFFF:04x}" if width == 2 else UNKNOWN,
        "first_sample_hex": (f"{first_sample & 0xFFFF:04x}"
                             if first_sample is not None else UNKNOWN),
    }


def resolve_player(setting: str = "auto") -> list[str] | None:
    """Exactly `Tts._player_command`: explicit setting, else first available."""
    if setting == "none":
        return None
    if setting != "auto":
        parts = shlex.split(setting)
        return parts if parts and shutil.which(parts[0]) else None
    for candidate in DEFAULT_ORDER:
        if shutil.which(candidate):
            return [candidate]
    return None


def classify(exit_code: int | None, timed_out: bool, stderr_text: str,
             first_byte_ms: float | None, wav_peak: float, *, player_missing: bool,
             file_missing: bool) -> tuple[str, str]:
    """`(verdict, why)` — the one-line reason a wav produced (or did not) sound."""
    if player_missing:
        return "no_player", "no player binary on PATH and none configured"
    if file_missing:
        return "missing_file", "the wav is not on disk"
    if timed_out:
        return "timeout", "the player did not exit before the deadline"
    if wav_peak != UNKNOWN and float(wav_peak) <= 0.0:
        return "silent_file", "every sample in the wav is zero — nothing to hear"
    if exit_code is None:
        return "silence", "no exit code was ever observed"
    if exit_code != 0:
        first = stderr_text.strip().splitlines()
        return ("exited_nonzero",
                f"player exited {exit_code}: {first[0] if first else '(no stderr)'}")
    if first_byte_ms is None:
        reason = ("exit 0 but no sample was observed leaving the player — the "
                  "sink accepted samples and this probe could not see one; that "
                  "is reported, not explained")
        return "exit_zero_no_output", reason
    return "played", f"exit 0 and the first sample left the player at {first_byte_ms:.0f} ms"


# ---------------------------------------------------------------------------
# the run (the only part that touches audio)
# ---------------------------------------------------------------------------
def probe(path: Path, command: list[str] | None, *, timeout_s: float = 30.0,
          dry_run: bool = False, runner=subprocess.run) -> dict:
    """Run the player once and report exit/stderr/first-byte. Never raises."""
    facts: dict = {"path": str(path)}
    file_missing = not path.exists()
    if not file_missing:
        try:
            detail = wav_facts(path)
            # Keep the wav's own peak under a name that is never confused with
            # the player's output, and carry it forward for classification.
            facts.update(detail)
        except (wave.Error, OSError, EOFError) as exc:
            facts["wav_error"] = f"{type(exc).__name__}: {exc}"
    wav_peak = facts.get("peak", UNKNOWN)
    first_sample_hex = facts.get("first_sample_hex", UNKNOWN)
    if command is not None:
        facts["command"] = " ".join([*command, str(path)])
    if dry_run or file_missing or command is None:
        verdict, why = classify(
            None, False, "", None, wav_peak,
            player_missing=command is None, file_missing=file_missing)
        if dry_run and not file_missing and command is not None:
            verdict, why = "dry_run", "not executed (--dry-run); wav facts only"
        return {**facts, "executed": 0, "exit_code": UNKNOWN,
                "stderr_lines": 0, "stderr_first": "", "stderr_empty": UNKNOWN,
                "first_byte_ms": UNKNOWN, "first_byte_hex": UNKNOWN,
                "first_sample_hex": first_sample_hex,
                "verdict": verdict, "why": why}
    argv = [*command, str(path)]
    # `-v` is aplay's verbose flag and paplay ignores it; the timeline is from
    # this probe's own clock either way, so no player-specific flags are passed.
    started = time.monotonic()
    timed_out = False
    exit_code: int | None = None
    stderr_text = ""
    # The first byte: a live player holds the sink open, so observing silence
    # through the wall clock is what separates "played" from "exited 0 early".
    try:
        proc = runner(argv, capture_output=True, text=True, timeout=timeout_s,
                      check=False)
        exit_code = getattr(proc, "returncode", None)
        stderr_text = proc.stderr or ""
        elapsed = time.monotonic() - started
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stderr_text = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        elapsed = time.monotonic() - started
    except (OSError, subprocess.SubprocessError) as exc:
        exit_code = None
        stderr_text = f"{type(exc).__name__}: {exc}"
        elapsed = time.monotonic() - started
    lines = [line for line in stderr_text.strip().splitlines() if line.strip()]
    # A player that exits before playing its own duration exited early: the
    # duration is the honest expectation, and the gap is a number worth printing.
    duration = facts.get("duration_s")
    first_byte_ms: float | None
    if exit_code == 0 and not timed_out:
        # A player that returns in well under half the audio's own length never
        # held the sink open: exit 0 bought silence, and the probe says so
        # instead of retyping the exit code as a verdict.
        if duration and elapsed < float(duration) * 0.5:
            first_byte_ms = None
        else:
            first_byte_ms = elapsed * 1000.0
    else:
        first_byte_ms = None
    # The sample that actually left the player: the wav's FIRST frame, not its
    # loudest. A leading run of 0000 is digital silence at the head of the file.
    first_hex = first_sample_hex if first_byte_ms is not None else UNKNOWN
    verdict, why = classify(
        exit_code, timed_out, stderr_text, first_byte_ms, wav_peak,
        player_missing=False, file_missing=False)
    return {**facts, "executed": 1, "elapsed_ms": round(elapsed * 1000.0, 1),
            "exit_code": exit_code if exit_code is not None else UNKNOWN,
            "stderr_lines": len(lines),
            "stderr_first": lines[0][:200] if lines else "",
            "stderr_empty": 1 if not lines else 0,
            "timed_out": 1 if timed_out else 0,
            "first_byte_ms": (UNKNOWN if first_byte_ms is None
                              else round(first_byte_ms, 1)),
            "first_byte_hex": first_hex,
            "first_sample_hex": first_sample_hex,
            "verdict": verdict, "why": why}


# ---------------------------------------------------------------------------
# telemetry: the daemon's own ack rows (the "none-played" distribution)
# ---------------------------------------------------------------------------
def default_db_path() -> Path:
    try:
        from assistant.config import load_config

        return Path(load_config().db_path)
    except Exception:
        data = os.environ.get("XDG_DATA_HOME", "")
        root = Path(data).expanduser() if data else Path.home() / ".local" / "share"
        return root / "assistant" / "assistant.db"


def read_ack_rows(db: Path, limit: int = 20) -> tuple[list[dict], str]:
    """Newest `ack` persona events, read-only. Never creates the file."""
    db = Path(db)
    if not db.exists():
        return [], f"no database at {db}"
    try:
        connection = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        return [], f"{type(exc).__name__}: {exc}"
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT ts, detail FROM persona_events WHERE kind = 'ack' "
            "ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    except sqlite3.Error as exc:
        return [], f"{type(exc).__name__}: {exc}"
    finally:
        connection.close()
    out = []
    for row in rows:
        try:
            detail = json.loads(row["detail"])
        except (TypeError, ValueError):
            continue
        if isinstance(detail, dict):
            out.append({"ts": row["ts"], **detail})
    return out, ""


def ack_telemetry(rows: list[dict]) -> dict:
    played = queued = suppressed = silent = no_speech_field = 0
    for row in rows:
        speech = row.get("speech")
        if not isinstance(speech, dict):
            no_speech_field += 1
            continue
        if speech.get("played"):
            played += 1
        if speech.get("queued"):
            queued += 1
        if speech.get("speak_suppressed") or speech.get("muted"):
            suppressed += 1
        if speech.get("cache_miss"):
            silent += 1
    return {"acks": len(rows), "played": played, "none_played": len(rows) - played,
            "queued": queued, "suppressed": suppressed, "cache_miss": silent,
            "no_speech_field": no_speech_field}


# ---------------------------------------------------------------------------
# the one cached ack wav the probe should default to
# ---------------------------------------------------------------------------
def default_wav() -> Path | None:
    """The daemon's ack cache dir, newest .wav — read-only discovery."""
    try:
        from assistant.config import load_config

        cache = load_config().section("tts").get("cache_dir")
        if cache:
            root = Path(cache).expanduser()
        else:
            data = os.environ.get("XDG_CACHE_HOME", "")
            base = Path(data).expanduser() if data else Path.home() / ".cache"
            root = base / "assistant" / "tts"
    except Exception:
        return None
    if not root.is_dir():
        return None
    wavs = sorted(root.rglob("*.wav"), key=lambda p: p.stat().st_mtime,
                  reverse=True)
    return wavs[0] if wavs else None


# ---------------------------------------------------------------------------
# self-test: player-less positive and negative controls
# ---------------------------------------------------------------------------
# 0.2 s of alternating samples: long enough that "held the sink" is a real
# claim, short enough that the controls stay instant.
SELF_TEST_TONE_SECONDS = 0.2

COMPLAINING_PLAYER = (
    "import sys; sys.stderr.write('Connection failure: refused'); "
    "raise SystemExit(1)"
)

SELF_TEST_CASES = (
    # (label, fake-player body, expected verdict)
    ("positive: exit 0 after the audio's real duration",
     "import time; time.sleep(0.25); raise SystemExit(0)", "played"),
    ("negative: exit 1 with a stderr complaint",
     COMPLAINING_PLAYER, "exited_nonzero"),
    ("negative: exit 0 but returns instantly (no sink held)",
     "raise SystemExit(0)", "exit_zero_no_output"),
)


def self_test(tmp: Path) -> list[dict]:
    """Run each control through `probe` with a REAL wav and a REAL process.

    The positive control must read `played` and the negatives must read their own
    verdicts, or the probe is measuring nothing. A control that passed for the
    wrong reason would be worse than no control.
    """
    wav = tmp / "tone.wav"
    frame_count = int(16000 * SELF_TEST_TONE_SECONDS)
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        # Alternating +/- amplitude: non-zero peak AND a non-zero first sample,
        # so a bug that reports the first frame wrongly cannot pass.
        samples = [(4000 if i % 2 else -4000) for i in range(frame_count)]
        handle.writeframes(b"".join(
            sample.to_bytes(2, "little", signed=True) for sample in samples))
    results = []
    for index, (label, body, expected) in enumerate(SELF_TEST_CASES):
        script = tmp / f"fake-player-{index}.py"
        script.write_text(body, encoding="utf-8")
        got = probe(wav, [sys.executable, str(script)], timeout_s=10.0)
        results.append({"label": label, "expected": expected,
                        "verdict": got["verdict"],
                        "exit_code": got["exit_code"],
                        "stderr_lines": got["stderr_lines"],
                        "pass": got["verdict"] == expected})
    # Negative control on the file itself: an all-zero wav plays nothing.
    silent = tmp / "silent.wav"
    with wave.open(str(silent), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 1600)
    got = probe(silent, [sys.executable, str(tmp / "fake-player-0.py")],
                timeout_s=10.0)
    results.append({"label": "negative: all-zero wav is silent_file, whatever the player says",
                    "expected": "silent_file", "verdict": got["verdict"],
                    "exit_code": got["exit_code"], "stderr_lines": got["stderr_lines"],
                    "pass": got["verdict"] == "silent_file"})
    return results


# ---------------------------------------------------------------------------
# pinning + cli
# ---------------------------------------------------------------------------
def checksum() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def manifest_name() -> str:
    here = Path(__file__).resolve()
    return f"{here.parent.name}/{here.name}"


def write_manifest(target: Path | None = None) -> Path:
    path = target or Path(__file__).with_suffix(".py.sha256")
    path.write_text(f"{checksum()}  {manifest_name()}\n")
    return path


PROBE_KEYS = ("path", "size_bytes", "rate_hz", "channels", "sampwidth_bits",
              "frames", "duration_s", "wav_peak", "peak_hex", "command",
              "executed", "elapsed_ms", "exit_code", "stderr_lines",
              "stderr_empty", "stderr_first", "timed_out", "first_byte_ms",
              "first_byte_hex", "verdict", "why")
TELEMETRY_KEYS = ("acks", "played", "none_played", "queued", "suppressed",
                  "cache_miss", "no_speech_field")


def render(probe_result: dict | None, telemetry: dict | None,
           reasons: list[str]) -> str:
    lines: list[str] = []
    if probe_result is not None:
        lines.append("available 1")
        for key in PROBE_KEYS:
            value = probe_result.get(key)
            if value is None:
                continue
            lines.append(f"probe.{key} {UNKNOWN if value is None else value}")
        lines.append("probe.fails_to_discriminate exit 0 with silent samples "
                     "cannot tell a live sink from a null one; only an eardrum "
                     "or a sink VU meter can")
    else:
        lines.append("available 0")
    if telemetry is not None:
        lines.append("telemetry.available 1")
        for key in TELEMETRY_KEYS:
            lines.append(f"telemetry.{key} {telemetry[key]}")
        if telemetry["acks"] == 0:
            lines.append(f"telemetry.fails_to_discriminate {EMPTY_FAILS_TO_DISCRIMINATE}")
    for reason in reasons:
        lines.append(f"reason {reason}")
    lines.append("note read_only")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("usage: player_probe.py [--wav PATH] [--command 'pw-play'] "
              "[--player auto|none|BIN] [--dry-run] [--telemetry-only] "
              "[--db PATH] [--limit N] [--self-test] | --checksum",
              file=sys.stderr)
        return 2
    if argv and argv[0] == "--checksum":
        print(write_manifest())
        return 0
    options: dict[str, str] = {}
    switches: set[str] = set()
    valued = {"--wav", "--command", "--player", "--db", "--limit"}
    flags = {"--dry-run", "--telemetry-only", "--self-test"}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in flags:
            switches.add(token)
            index += 1
            continue
        if token in valued:
            if index + 1 >= len(argv):
                print(f"error value_required {token}", file=sys.stderr)
                return 2
            options[token] = argv[index + 1]
            index += 2
            continue
        print(f"error unknown_argument {token}", file=sys.stderr)
        return 2

    if "--self-test" in switches:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            results = self_test(Path(tmp))
        passed = sum(1 for result in results if result["pass"])
        for item in results:
            print(f"control {'PASS' if item['pass'] else 'FAIL'} {item['verdict']} "
                  f"exit={item['exit_code']} stderr_lines={item['stderr_lines']} "
                  f"— {item['label']}")
        print(f"controls_passed {passed}")
        print(f"controls_total {len(results)}")
        return 0 if passed == len(results) else 1

    reasons: list[str] = []
    telemetry = None
    # Telemetry is cheap and read-only, so it always ships with a probe run:
    # the player's exit code and the ack rows are the two halves of "none played".
    rows, reason = read_ack_rows(
        Path(options["--db"]).expanduser() if "--db" in options
        else default_db_path(),
        int(options.get("--limit", 20)))
    if reason:
        reasons.append(f"telemetry {reason}")
    else:
        telemetry = ack_telemetry(rows)

    probe_result = None
    if "--telemetry-only" not in switches:
        path = Path(options["--wav"]).expanduser() if "--wav" in options else default_wav()
        if path is None:
            reasons.append("no wav given and none found in the tts cache")
        else:
            if "--command" in options:
                command: list[str] | None = shlex.split(options["--command"])
                if not command or not shutil.which(command[0]):
                    command = None
                    reasons.append(f"player not found: {options['--command']}")
            else:
                command = resolve_player(options.get("--player", "auto"))
                if command is None:
                    reasons.append("no player binary on PATH (pw-play/paplay/aplay) "
                                   "and [tts] player is not set — this is the "
                                   "`no_player` case, not a playback failure")
            probe_result = probe(path, command,
                                 dry_run="--dry-run" in switches)
    print(render(probe_result, telemetry, reasons))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
