#!/usr/bin/env python3
"""Wake-clip sample capture — the PRODUCTION mic path.

Records `Elaria` / `hey Elaria` takes (plus near-word negatives) through the
same `pw-record` + configured `[capture] mic_target` chain the daemon uses at
runtime: a mismatch between training capture and runtime capture is a
silent killer, so there is exactly one path.

ONE split mechanism: the tree. Takes live under
~/elaria-wake-samples/{train,eval}/<bucket>/; `freeze-eval` moves ~20% of
each bucket into eval/ ONCE, BEFORE any threshold tuning. The manifest is
JSONL with no split field — the directory is the split. Samples are never
added to any repo.

Milestones and pre-committed evaluation bars: docs/hotword-training-plan.md.
Training itself is out of scope; this is capture tooling only.

Usage:
  record_elaria_samples.py plan
  record_elaria_samples.py record --bucket elaria-close-normal --takes 25 --phrase "Elaria"
  record_elaria_samples.py freeze-eval
  record_elaria_samples.py status
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

SAMPLE_RATE = 16000
DEFAULT_ROOT = Path.home() / "elaria-wake-samples"
MANIFEST = "manifest.jsonl"

# Milestone A (~120 takes) — bucket, takes, phrase, seconds, note.
MILESTONE_A: list[tuple[str, int, str, float, str]] = [
    ("elaria-close-normal", 25, "Elaria", 2.5, "seated, quiet room, normal voice"),
    ("elaria-close-calling", 10, "Elaria", 2.5, "calling-across-a-room delivery"),
    ("elaria-arm-normal", 12, "Elaria", 2.5, "arm's length (~1-2 m)"),
    ("elaria-across-normal", 12, "Elaria", 2.5, "across the room (~3-4 m)"),
    ("elaria-tv_on", 12, "Elaria", 2.5, "TV/radio at conversational level"),
    ("heyelaria-close-normal", 15, "hey Elaria", 2.5, "secondary phrase"),
    ("nearwords", 20, "malaria / area / Larry / hilary / scenario", 2.5,
     "must NOT trigger"),
    ("freespeech", 2, "(free speech)", 30.0, "continuous talking, no wake phrase"),
    ("ambient", 2, "(room tone)", 30.0, "keyboard, traffic, silence"),
]

# Milestone B top-up to ~330 total.
MILESTONE_B: list[tuple[str, int, str, float, str]] = [
    ("elaria-tired", 15, "Elaria", 2.5, "tired / low-energy tones"),
    ("elaria-inconversation", 15, "Elaria", 2.5, "mid-sentence, talking to someone"),
    ("elaria-music", 15, "Elaria", 2.5, "music playing"),
    ("elaria-kitchen", 15, "Elaria", 2.5, "kitchen noise"),
    ("elaria-hallway", 10, "Elaria", 2.5, "hallway / next room"),
    ("heyelaria-mixed", 10, "hey Elaria", 2.5, "secondary phrase, varied distance"),
    ("nearwords-extra", 15, "near-word set", 2.5, "extended near-word negatives"),
    ("otherspeaker", 10, "(other voice)", 5.0,
     "other-speaker negatives: must never trigger"),
]


def load_mic_target(config_path: Path | None = None) -> str:
    """The configured production capture target ([capture] mic_target)."""
    import tomllib

    if config_path is None:
        base = Path(os.environ.get("XDG_CONFIG_HOME",
                                   Path.home() / ".config"))
        config_path = base / "assistant" / "config.toml"
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    capture = raw.get("capture") if isinstance(raw.get("capture"), dict) else {}
    meeting = raw.get("meeting") if isinstance(raw.get("meeting"), dict) else {}
    return str(capture.get("mic_target") or meeting.get("mic_target") or "")


def append_manifest(root: Path, row: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / MANIFEST).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")


def read_manifest(root: Path) -> list[dict]:
    path = root / MANIFEST
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def freeze_eval(root: Path, *, fraction: float = 0.2, seed: int = 1234) -> dict:
    """THE single split: move ~fraction of each train/ bucket into eval/.

    Deterministic per bucket (seeded), so re-runs after interruption move
    the same takes. Call ONCE, before any threshold tuning. Eval is never
    merged back and never trained on.
    """
    moved: dict[str, int] = {}
    train = root / "train"
    if not train.is_dir():
        return {"moved": moved, "note": "no train/ tree yet"}
    for bucket_dir in sorted(p for p in train.iterdir() if p.is_dir()):
        takes = sorted(bucket_dir.glob("*.wav"))
        if not takes:
            continue
        count = max(1, round(len(takes) * fraction))
        rng = random.Random(f"{seed}:{bucket_dir.name}")
        chosen = rng.sample(takes, min(count, len(takes)))
        dest = root / "eval" / bucket_dir.name
        dest.mkdir(parents=True, exist_ok=True)
        for take in chosen:
            take.rename(dest / take.name)
        moved[bucket_dir.name] = len(chosen)
    (root / "eval" / ".frozen").write_text(
        json.dumps({"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "fraction": fraction, "seed": seed}) + "\n",
        encoding="utf-8")
    return {"moved": moved,
            "note": "eval/ is frozen — never retrained on, never merged back"}


def record_take(*, out_path: Path, seconds: float,
                mic_target: str) -> dict:
    """One take on the production mic path (pw-record + configured target)."""
    if shutil.which("pw-record") is None:
        raise RuntimeError(
            "refused: pw-record not found (pipewire-utils) — the capture path "
            "is the production path; install it rather than substituting "
            "another recorder")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    command = ["pw-record", "--rate", str(SAMPLE_RATE), "--channels", "1",
               "--format", "s16"]
    if mic_target:
        command.append(f"--target={mic_target}")
    command.append(str(out_path))
    try:
        proc = subprocess.run(command, timeout=seconds + 5.0, check=False)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"pw-record did not finish: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"pw-record exited {proc.returncode}")
    return {"bytes": out_path.stat().st_size if out_path.is_file() else 0,
            "device": mic_target or "default source"}


def cmd_plan() -> int:
    print("Milestone A — ~120 takes (before ANY threshold tuning):")
    for bucket, takes, phrase, seconds, note in MILESTONE_A:
        print(f"  {bucket:24s} {takes:3d} × {seconds:4.1f}s  "
              f"phrase={phrase!r:12s} {note}")
    print("\nMilestone B — top-up to ~330 total:")
    for bucket, takes, phrase, seconds, note in MILESTONE_B:
        print(f"  {bucket:24s} {takes:3d} × {seconds:4.1f}s  "
              f"phrase={phrase!r:12s} {note}")
    print("\nThen: freeze-eval (20%/bucket, ONCE) — eval is never retrained on.")
    print("Bars: docs/hotword-training-plan.md (pre-committed).")
    return 0


def cmd_record(args, root: Path) -> int:
    mic_target = args.device or load_mic_target()
    print(f"Recording {args.takes} take(s) for {args.bucket!r} on "
          f"{mic_target or 'the default source'} (Ctrl-C stops cleanly).")
    for index in range(args.takes):
        name = (f"{args.bucket}-{time.strftime('%Y%m%d-%H%M%S')}"
                f"-{index:03d}.wav")
        out = root / "train" / args.bucket / name
        print(f"  take {index + 1}/{args.takes}: {out.name} — speak now "
              f"({args.seconds}s)")
        try:
            info = record_take(out_path=out, seconds=args.seconds,
                               mic_target=mic_target)
        except RuntimeError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        append_manifest(root, {
            "id": name, "phrase": args.phrase, "bucket": args.bucket,
            "path": f"train/{args.bucket}/{name}",
            "duration_s": args.seconds, "sample_rate": SAMPLE_RATE,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "device": info["device"], "bytes": info["bytes"]})
        time.sleep(0.3)
    print("Done. Freeze the eval split ONCE, before tuning thresholds:")
    print(f"  {sys.argv[0]} freeze-eval")
    return 0


def cmd_status(root: Path) -> int:
    for split in ("train", "eval"):
        base = root / split
        if not base.is_dir():
            print(f"{split}/: (absent)")
            continue
        for bucket_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            print(f"{split}/{bucket_dir.name}: "
                  f"{len(list(bucket_dir.glob('*.wav')))} take(s)")
    rows = read_manifest(root)
    print(f"manifest: {len(rows)} row(s) at {root / MANIFEST} "
          "(no split field — the tree is the split)")
    frozen = root / "eval" / ".frozen"
    if frozen.is_file():
        print(f"eval frozen: {frozen.read_text(encoding='utf-8').strip()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=str(DEFAULT_ROOT),
                        help="sample root (default: ~/elaria-wake-samples)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan", help="print the milestone schedule")
    record = sub.add_parser("record", help="record one bucket of takes")
    record.add_argument("--bucket", required=True)
    record.add_argument("--takes", type=int, default=1)
    record.add_argument("--phrase", default="Elaria")
    record.add_argument("--seconds", type=float, default=2.5)
    record.add_argument("--device", default="",
                        help="override [capture] mic_target (node.name)")
    freeze = sub.add_parser("freeze-eval",
                            help="THE split: 20%/bucket into eval/, once")
    freeze.add_argument("--fraction", type=float, default=0.2)
    freeze.add_argument("--seed", type=int, default=1234)
    sub.add_parser("status", help="per-bucket counts + manifest + freeze state")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(root, 0o700)
    except OSError:
        pass

    if args.cmd == "plan":
        return cmd_plan()
    if args.cmd == "record":
        return cmd_record(args, root)
    if args.cmd == "freeze-eval":
        result = freeze_eval(root, fraction=args.fraction, seed=args.seed)
        print(json.dumps(result, indent=2))
        return 0
    return cmd_status(root)


if __name__ == "__main__":
    sys.exit(main())
