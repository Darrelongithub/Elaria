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
import errno
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
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


def _safe_path(root: Path, path: Path) -> Path:
    """Return a non-symlink path lexically and physically contained by root."""
    root = Path(root).expanduser().resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(candidate))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes sample root: {candidate}") from exc

    current = root
    for part in relative.parts:
        if part in ("", ".", ".."):
            raise ValueError(f"unsafe path component under sample root: {part!r}")
        current = current / part
        if current.is_symlink():
            raise ValueError(f"refused symlink inside sample root: {current}")
        try:
            resolved = current.resolve(strict=False)
        except (OSError, RuntimeError) as exc:
            raise ValueError(f"cannot safely resolve sample path: {current}") from exc
        if not resolved.is_relative_to(root):
            raise ValueError(f"path escapes sample root: {current}")
    return current


def _validate_bucket(bucket: str) -> str:
    if not isinstance(bucket, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", bucket):
        raise ValueError("bucket must be a safe single path component")
    return bucket


def _ensure_directory(root: Path, path: Path, *, create: bool) -> Path:
    root = Path(root).expanduser().resolve()
    path = _safe_path(root, path)
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"expected a directory: {path}")
        return path
    if not create:
        return path

    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"refused symlink inside sample root: {current}")
        try:
            current.mkdir(mode=0o700)
        except FileExistsError:
            if current.is_symlink() or not current.is_dir():
                raise ValueError(f"expected a safe directory: {current}")
    return path


def _manifest_path(root: Path) -> Path:
    root = Path(root).expanduser().resolve()
    path = _safe_path(root, root / MANIFEST)
    if os.path.lexists(path) and not path.is_file():
        raise ValueError(f"manifest is not a regular file: {path}")
    return path


def _atomic_write_text(path: Path, text: str) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class _IncompleteMoveError(RuntimeError):
    """Both paths may exist; retain the freeze marker for manual recovery."""


def _move_without_overwrite(source: Path, destination: Path) -> None:
    """Move a file on one filesystem without ever replacing a destination."""
    if os.path.lexists(destination):
        raise FileExistsError(f"refusing to overwrite eval take: {destination}")
    try:
        os.link(source, destination, follow_symlinks=False)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            raise OSError(
                errno.EXDEV, "train and eval must be on the same filesystem",
                str(destination)) from exc
        raise
    try:
        source.unlink()
    except OSError:
        try:
            destination.unlink()
        except OSError as cleanup_exc:
            raise _IncompleteMoveError(
                f"could not remove {source} or roll back {destination}") from cleanup_exc
        raise


def append_manifest(root: Path, row: dict) -> None:
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = _manifest_path(root)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()


def read_manifest(root: Path) -> list[dict]:
    root = Path(root).expanduser().resolve()
    path = _manifest_path(root)
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def freeze_eval(root: Path, *, fraction: float = 0.2, seed: int = 1234) -> dict:
    """Freeze the tree split once, moving a fraction of train/ into eval/.

    The operation preflights every source and destination, uses no-overwrite
    moves, updates manifest paths atomically, and leaves an in-progress marker
    if interrupted after mutation so a second run cannot silently re-split.
    """
    try:
        fraction = float(fraction)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("fraction must be a finite value between 0 and 1") from exc
    if not math.isfinite(fraction) or not 0.0 <= fraction <= 1.0:
        raise ValueError("fraction must be a finite value between 0 and 1")

    root = Path(root).expanduser().resolve()
    moved: dict[str, int] = {}
    train = _safe_path(root, root / "train")
    eval_root = _safe_path(root, root / "eval")
    marker = _safe_path(root, eval_root / ".frozen")
    if os.path.lexists(marker):
        raise RuntimeError("eval split is already frozen")
    if not train.is_dir():
        if os.path.lexists(train):
            raise ValueError(f"train path is not a directory: {train}")
        return {"moved": moved, "note": "no train/ tree yet"}

    plans: list[tuple[Path, Path]] = []
    destination_dirs: set[Path] = set()
    for entry in sorted(train.iterdir(), key=lambda item: item.name):
        bucket_dir = _safe_path(root, entry)
        if not bucket_dir.is_dir():
            continue
        takes = []
        for take in sorted(bucket_dir.glob("*.wav"), key=lambda item: item.name):
            take = _safe_path(root, take)
            if not take.is_file():
                raise ValueError(f"expected a regular WAV take: {take}")
            takes.append(take)
        if not takes:
            continue

        if fraction == 0.0:
            chosen = []
        else:
            count = min(len(takes), max(1, round(len(takes) * fraction)))
            rng = random.Random(f"{seed}:{bucket_dir.name}")
            chosen = rng.sample(takes, count)
        moved[bucket_dir.name] = len(chosen)

        destination_dir = _safe_path(root, eval_root / bucket_dir.name)
        if os.path.lexists(destination_dir) and not destination_dir.is_dir():
            raise ValueError(f"eval bucket is not a directory: {destination_dir}")
        destination_dirs.add(destination_dir)
        for take in chosen:
            destination = _safe_path(root, destination_dir / take.name)
            if os.path.lexists(destination):
                raise FileExistsError(
                    f"refusing to overwrite eval take: {destination}")
            plans.append((take, destination))

    manifest = _manifest_path(root)
    manifest_exists = manifest.is_file()
    rows = read_manifest(root) if manifest_exists else []
    path_updates = {
        source.relative_to(root).as_posix(): destination.relative_to(root).as_posix()
        for source, destination in plans
    }
    updated_rows = []
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError("manifest rows must be JSON objects")
        updated = dict(row)
        recorded_path = updated.get("path")
        if isinstance(recorded_path, str) and recorded_path in path_updates:
            updated["path"] = path_updates[recorded_path]
        updated_rows.append(updated)
    manifest_text = "".join(
        json.dumps(row, sort_keys=True) + "\n" for row in updated_rows)

    eval_root = _ensure_directory(root, eval_root, create=True)
    for destination_dir in sorted(destination_dirs):
        _ensure_directory(root, destination_dir, create=True)
    marker = _safe_path(root, eval_root / ".frozen")
    marker_data = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                   "fraction": fraction, "seed": seed,
                   "status": "in_progress"}
    marker_created = False
    try:
        with marker.open("x", encoding="utf-8") as handle:
            marker_created = True
            handle.write(json.dumps(marker_data, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise RuntimeError("eval split is already frozen") from exc
    except BaseException:
        if marker_created:
            try:
                marker.unlink()
            except OSError as cleanup_exc:
                raise RuntimeError(
                    "could not initialize eval/.frozen; remove or inspect the "
                    "partial marker before retrying") from cleanup_exc
        raise

    moved_files: list[tuple[Path, Path]] = []
    manifest_update_started = False
    manifest_updated = False
    try:
        for source, destination in plans:
            _move_without_overwrite(source, destination)
            moved_files.append((source, destination))
        if manifest_exists:
            manifest_update_started = True
            _atomic_write_text(manifest, manifest_text)
            manifest_updated = True
        marker_data["status"] = "frozen"
        _atomic_write_text(marker,
                           json.dumps(marker_data, sort_keys=True) + "\n")
    except BaseException as exc:
        if manifest_update_started and not manifest_updated:
            try:
                manifest_updated = (
                    _manifest_path(root).read_text(encoding="utf-8") == manifest_text)
            except Exception:
                # The atomic replace may have completed before the failure;
                # keep the in-progress marker rather than risk a stale rollback.
                manifest_updated = True
        if manifest_updated:
            raise RuntimeError(
                "files and manifest may have been moved, but the freeze marker "
                "could not be finalized; inspect eval/.frozen before continuing") from exc
        rollback_errors = []
        for source, destination in reversed(moved_files):
            try:
                _move_without_overwrite(destination, source)
            except Exception as rollback_exc:
                rollback_errors.append(rollback_exc)
        if not rollback_errors and not isinstance(exc, _IncompleteMoveError):
            try:
                marker.unlink()
            except FileNotFoundError:
                pass
            except OSError as marker_exc:
                rollback_errors.append(marker_exc)
        if rollback_errors or isinstance(exc, _IncompleteMoveError):
            raise RuntimeError(
                "freeze failed and rollback was incomplete; eval/.frozen is "
                "retained to prevent a second split") from exc
        raise

    return {"moved": moved,
            "note": "eval/ is frozen — never retrained on, never merged back"}


def record_take(*, out_path: Path, seconds: float,
                mic_target: str) -> dict:
    """One take on the production mic path (pw-record + configured target)."""
    if not math.isfinite(seconds) or seconds <= 0:
        raise RuntimeError("refused: recording duration must be finite and positive")
    out_path = Path(out_path)
    if os.path.lexists(out_path):
        raise RuntimeError(f"refused: will not overwrite existing take {out_path}")
    if shutil.which("pw-record") is None:
        raise RuntimeError(
            "refused: pw-record not found (pipewire-utils) — the capture path "
            "is the production path; install it rather than substituting "
            "another recorder")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(out_path):
        raise RuntimeError(f"refused: will not overwrite existing take {out_path}")
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
    try:
        root = Path(root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        bucket = _validate_bucket(args.bucket)
        if not isinstance(args.takes, int) or isinstance(args.takes, bool) or args.takes <= 0:
            raise ValueError("takes must be a positive integer")
        seconds = float(args.seconds)
        if not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("seconds must be finite and positive")
        train = _ensure_directory(root, root / "train", create=True)
        bucket_dir = _ensure_directory(root, train / bucket, create=True)
        _manifest_path(root)
    except (OSError, TypeError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    mic_target = args.device or load_mic_target()
    print(f"Recording {args.takes} take(s) for {bucket!r} on "
          f"{mic_target or 'the default source'} (Ctrl-C stops cleanly).")
    for index in range(args.takes):
        name = (f"{bucket}-{time.strftime('%Y%m%d-%H%M%S')}"
                f"-{index:03d}-{uuid.uuid4().hex}.wav")
        out = _safe_path(root, bucket_dir / name)
        if os.path.lexists(out):
            print(f"refused: will not overwrite existing take {out}",
                  file=sys.stderr)
            return 2
        print(f"  take {index + 1}/{args.takes}: {out.name} — speak now "
              f"({seconds}s)")
        try:
            info = record_take(out_path=out, seconds=seconds,
                               mic_target=mic_target)
        except (OSError, RuntimeError, ValueError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        try:
            append_manifest(root, {
                "id": name, "phrase": args.phrase, "bucket": bucket,
                "path": f"train/{bucket}/{name}",
                "duration_s": seconds, "sample_rate": SAMPLE_RATE,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "device": info["device"], "bytes": info["bytes"]})
        except (OSError, TypeError, ValueError) as exc:
            print(f"recorded {out}, but manifest update failed: {exc}",
                  file=sys.stderr)
            return 2
        time.sleep(0.3)
    print("Done. Freeze the eval split ONCE, before tuning thresholds:")
    print(f"  {sys.argv[0]} freeze-eval")
    return 0


def cmd_status(root: Path) -> int:
    root = Path(root).expanduser().resolve()
    try:
        for split in ("train", "eval"):
            base = _safe_path(root, root / split)
            if not base.is_dir():
                if os.path.lexists(base):
                    raise ValueError(f"split path is not a directory: {base}")
                print(f"{split}/: (absent)")
                continue
            for entry in sorted(base.iterdir(), key=lambda item: item.name):
                bucket_dir = _safe_path(root, entry)
                if not bucket_dir.is_dir():
                    continue
                takes = [
                    _safe_path(root, take)
                    for take in bucket_dir.glob("*.wav")
                ]
                if any(not take.is_file() for take in takes):
                    raise ValueError(f"invalid WAV entry under {bucket_dir}")
                print(f"{split}/{bucket_dir.name}: {len(takes)} take(s)")
        rows = read_manifest(root)
        print(f"manifest: {len(rows)} row(s) at {root / MANIFEST} "
              "(no split field — the tree is the split)")
        frozen = _safe_path(root, root / "eval" / ".frozen")
        if frozen.is_file():
            print(f"eval frozen: {frozen.read_text(encoding='utf-8').strip()}")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
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
                            help="THE split: 20%%/bucket into eval/, once")
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
        try:
            result = freeze_eval(root, fraction=args.fraction, seed=args.seed)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0
    return cmd_status(root)


if __name__ == "__main__":
    sys.exit(main())
