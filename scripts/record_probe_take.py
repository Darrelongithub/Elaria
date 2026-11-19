#!/usr/bin/env python3
"""Record one short take through the PRODUCTION capture path.

2026-11-17: the gain packet told the owner to produce a take with
`pw-record --target <node> … /tmp/gain-18.wav`. It exited 0 and wrote 5.95 s of
0.0003 rms — digital silence — while, in the same sitting at the same 18 % gain,
the assistant's own capture transcribed the same microphone verbatim. A silent
file is a CAPTURE-LINE failure, not a gain result, and it nearly became the
opposite conclusion ("18 % is too quiet").

So this tool does not spell `pw-record` itself. It calls
`assistant.capture.pw_record_pcm_stream_command` — the same function the daemon
and the doctor use — and writes its stdout into a WAV. Whatever the argv is,
this is the argv production uses; there is no second dialect to be wrong about.
A 16-bit 16 kHz mono WAV comes out, which is exactly what
`scripts/frame_probe.py` reads.

It also refuses to be clever: no node named is an F17 refusal (never the
default source), a numeric object.id is refused by production's own guard, and
a silent take exits 3 with `silent 1` so nothing downstream can read it as a
quiet voice.

`--compare` records the same seconds twice — through the production argv and
through the packet's old argv — in one sitting, and prints both peaks. That is
the experiment that says whether the silence was the invocation spelling or
something else. It is a diagnosis, not a claim.

Usage:
  record_probe_take.py /tmp/gain-18.wav --seconds 5
  record_probe_take.py /tmp/gain-18.wav --compare
  record_probe_take.py --checksum

Integrity: `scripts/record_probe_take.py.sha256` holds this file's digest under
its repository-relative name; verify from the repository root with
`sha256sum -c scripts/record_probe_take.py.sha256`.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:          # runnable without an install
    sys.path.insert(0, str(REPO / "src"))

from assistant import capture as prod


def production_command(target: str, rate: int) -> list[str]:
    """THE production argv — delegated, never re-spelled."""
    return prod.pw_record_pcm_stream_command(target, sample_rate=rate)


def legacy_command(target: str, path: Path, rate: int) -> list[str]:
    """The packet's 2026-11-17 line, kept only so `--compare` can reproduce it.

    It is deliberately NOT what `--out` uses. Two differences from production:
    `--target <node>` as a separate token instead of `--target=<node>`, and a
    file path instead of stdout. Which of those mattered is unproven.
    """
    return ["pw-record", "--target", target, "--rate", str(rate),
            "--channels", "1", "--format", "s16", str(path)]


def resolve_target(config) -> tuple[str, str]:
    """`[capture] mic_target` → `[meeting] mic_target`, else an F17 refusal."""
    try:
        capture = config.section("capture")
        target = (capture.get("mic_target")
                  or config.section("meeting").get("mic_target"))
    except Exception:                     # no config, no node — a refusal
        return "", "f17_no_node"
    return (str(target), "") if target else ("", "f17_no_node")


def record(command: list[str], seconds: float) -> bytes:
    """Run the recorder for `seconds`; the timeout IS the recording window."""
    try:
        proc = subprocess.run(command, capture_output=True,
                              timeout=float(seconds) + 2.0, check=False)
        return proc.stdout or b""
    except subprocess.TimeoutExpired as exc:
        return exc.stdout or b""
    except OSError:
        return b""


def write_wav(path: Path, pcm: bytes, rate: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(pcm[: len(pcm) - len(pcm) % 2])
    return path


def describe(pcm: bytes, rate: int) -> dict:
    """What the file contains, in the numbers the packet will quote."""
    peak = prod.pcm_peak(pcm) if pcm else 0.0
    rms = prod.frame_rms(pcm) if pcm else 0.0
    return {"bytes": len(pcm),
            "seconds": round(len(pcm) / 2 / rate, 2) if pcm else 0.0,
            "peak": round(peak, 4),
            "rms": round(rms, 4),
            # The same floor the probe's `no_signal` uses.
            "silent": 1 if (not pcm or rms < 0.005) else 0}


def checksum() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def manifest_name() -> str:
    here = Path(__file__).resolve()
    return f"{here.parent.name}/{here.name}"


def write_manifest(target: Path | None = None) -> Path:
    path = target or Path(__file__).with_suffix(".py.sha256")
    path.write_text(f"{checksum()}  {manifest_name()}\n")
    return path


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("usage: record_probe_take.py <out.wav> [--seconds N] [--target NODE] "
              "[--rate HZ] [--compare] | --checksum", file=sys.stderr)
        return 2
    if argv and argv[0] == "--checksum":
        print(write_manifest())
        return 0
    out: Path | None = None
    seconds = 5.0
    rate = 16000
    target_arg = ""
    compare = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--compare":
            compare = True
            index += 1
        elif token in ("--seconds", "--target", "--rate"):
            if index + 1 >= len(argv):
                print(f"error value_required {token}", file=sys.stderr)
                return 2
            value = argv[index + 1]
            if token == "--seconds":
                seconds = float(value)
            elif token == "--rate":
                rate = int(value)
            else:
                target_arg = value
            index += 2
        elif token.startswith("-"):
            print(f"error unknown_argument {token}", file=sys.stderr)
            return 2
        else:
            if out is not None:
                print(f"error unexpected_argument {token}", file=sys.stderr)
                return 2
            out = Path(token).expanduser()
            index += 1
    if out is None:
        print("error missing_output_wav", file=sys.stderr)
        return 2
    if not prod.tool_available("pw-record"):
        print("target -1\nrefusal pw-record_not_found")
        return 2

    target = target_arg
    if not target:
        try:
            from assistant.config import load_config
            target, refusal = resolve_target(load_config())
        except Exception as exc:            # no daemon config here
            print(f"target -1\nrefusal config_unreadable\nreason {type(exc).__name__}")
            return 2
        if not target:
            print(f"target -1\nrefusal {refusal}")
            return 2

    try:
        command = production_command(target, rate)
    except ValueError as exc:               # production's object.id guard
        print(f"target -1\nrefusal {exc}")
        return 2

    pcm = record(command, seconds)
    write_wav(out, pcm, rate)
    taken = describe(pcm, rate)
    print(f"take {out}")
    print(f"target {target}")
    print("argv production")
    for key in ("bytes", "seconds", "peak", "rms", "silent"):
        print(f"{key} {taken[key]}")
    if taken["silent"]:
        print("note silent_take_is_not_a_gain_reading")
        return 3
    if compare:
        legacy_path = out.with_suffix(".legacy.wav")
        legacy_pcm = record(legacy_command(target, legacy_path, rate), seconds)
        write_wav(legacy_path, legacy_pcm, rate)
        legacy_taken = describe(legacy_pcm, rate)
        print(f"legacy_take {legacy_path}")
        print(f"legacy_peak {legacy_taken['peak']}")
        print(f"legacy_rms {legacy_taken['rms']}")
        print(f"legacy_silent {legacy_taken['silent']}")
        print(f"same {int(legacy_taken['silent'] == taken['silent'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
