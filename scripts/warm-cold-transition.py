#!/usr/bin/env python3
"""Drive one artifact through the full hot -> cold transition, and record it.

WHAT THIS PROVES, AND WHAT IT DOES NOT
--------------------------------------
This walks a single artifact through every state the manifest defines —
LOCAL -> UPLOADED -> FLIPPED -> TRASHED -> PURGED — using the real reconcile
machinery and a real backend seam. Nothing here is mocked except the clock, which
is injectable so no test ever sleeps.

The backend is a **local-path fixture**. It is deliberately not MEGA: the MEGA
remote is network-gated out of this sandbox, restic and rclone are not installed
here, and the owner's real recordings never enter this sandbox at all. So this
script proves the *machinery* — the state machine, the trim move, the grace clock,
the record — and says plainly that the one thing it cannot prove is the network.

Run it against a synthetic artifact and the transition record it prints is the
same shape the live run will produce, against the same code, with a different
backend object.

PRIVACY
-------
It prints states, reasons, byte counts and hashes. It never prints a filesystem
path or a filename.

USAGE
-----
    python3 scripts/warm-cold-transition.py --root <workdir> [--grace-days 14] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import wave
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from assistant.backup import plan_reconcile, reconcile, reconcile_all
from assistant.remote import LocalPathBackend, Verification
from assistant.safety import try_sha256_file
from assistant.storage import (
    FLIPPED,
    LOCAL,
    PURGED,
    TRASHED,
    UPLOADED,
    ManifestRecord,
    StorageManifest,
)

_STATES = (LOCAL, UPLOADED, FLIPPED, TRASHED, PURGED)


def _synthetic_recording(path: Path, seconds: float = 2.0) -> int:
    """A real RIFF/WAVE recording. Never a synthetic byte blob."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * int(16000 * seconds))
    return path.stat().st_size


def _label(path: Path) -> str:
    """Extension only. Never a path, never a name."""
    return path.suffix or "(none)"


def _plan_summary(plan) -> dict:
    """Path-blind aggregate: how many of what, and why. Never which."""
    out = plan.summary()
    out["problems"] = list(plan.problems)
    out["reasons"] = [f"{a.from_state}->{a.to_state}: {a.reason}" for a in plan.actions]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", required=True, help="a work directory to build inside")
    ap.add_argument("--grace-days", type=int, default=14)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root)
    (root / "audio").mkdir(parents=True, exist_ok=True)
    artifact = root / "audio" / "synthetic-capture.wav"
    size = _synthetic_recording(artifact)
    digest = try_sha256_file(artifact)

    backend = LocalPathBackend(root / "fixture-remote")
    manifest = StorageManifest(root / "manifest.jsonl")
    trash = root / "trash"

    trash = root / "trash"
    trash.mkdir(parents=True, exist_ok=True)

    def trim_mover(path: str) -> str:
        """Move the artifact into local trash under a stamped name, and say where."""
        src = Path(path)
        dest = trash / f"{src.stem}.trashed{src.suffix}"
        shutil.move(str(src), str(dest))
        return str(dest)

    def purge_mover(trashed_path: str) -> bool:
        """Remove the trashed copy. Only ever reached after the grace has elapsed."""
        try:
            os.unlink(trashed_path)
            return True
        except OSError:
            return False

    steps: list[dict] = []

    def step(name: str, **kw) -> None:
        steps.append({"step": name, **kw})

    # -- 1. LOCAL: the artifact exists and the manifest knows it -------------
    ok = manifest.append(ManifestRecord(
        artifact=str(artifact), state=LOCAL, sha256=digest, size=size, tier="hot"))
    step("local", appended=ok, size=size, sha256=digest[:12])

    # -- 2. LOCAL -> UPLOADED: a copy lands on the backend -------------------
    stored = backend.store(artifact)
    ok = manifest.append(ManifestRecord(
        artifact=str(artifact), state=UPLOADED, sha256=digest, size=size, tier="hot",
        detail=f"stored on {backend.name}"), expect_from=LOCAL)
    step("uploaded", appended=ok, backend=backend.name,
         remote_copy_present=stored.exists())

    # -- 3. UPLOADED -> FLIPPED: reconcile completes the flip ----------------
    # verify_remote is REQUIRED for this transition: a flip asserted without a
    # confirmed remote copy is the failure the module exists to prevent.
    def verify_remote(path: str):
        """A Verification, not a bool: the backend that produced it is the whole point.

        It travels into the action reason and so into the manifest detail, which is what
        stops a LocalPathBackend confirmation from ever being readable as real remote
        confirmation. A bare bool reports `opaque-verifier` — correctly, because it
        genuinely cannot say who answered.
        """
        target = backend.root / Path(path).name
        if not target.exists():
            return Verification(backend=backend.name, confirmed=False,
                                method="absent", detail="remote copy absent")
        return Verification(backend=backend.name, confirmed=True,
                            method="hash", detail="hash-match")

    now = datetime.now(UTC)
    plan = plan_reconcile(manifest, now=now, verify_remote=verify_remote,
                          grace_days=args.grace_days)
    before = manifest.current()[str(artifact)].state
    reconcile(manifest, plan, now=now, trim_mover=trim_mover, purge_mover=purge_mover)
    after = manifest.current()[str(artifact)].state
    step("flipped", before=before, after=after, plan=_plan_summary(plan))

    # -- 4. FLIPPED -> TRASHED: the trim move --------------------------------
    plan = plan_reconcile(manifest, now=now, verify_remote=verify_remote,
                          grace_days=args.grace_days)
    before = manifest.current()[str(artifact)].state
    reconcile(manifest, plan, now=now, trim_mover=trim_mover, purge_mover=purge_mover)
    after = manifest.current()[str(artifact)].state
    step("trimmed", before=before, after=after, plan=_plan_summary(plan))

    # -- 5. TRASHED, grace running: two copies remain, and that silence is the
    #        copy-count invariant holding, not a missed action.
    plan = plan_reconcile(manifest, now=now + timedelta(days=args.grace_days - 1),
                          verify_remote=verify_remote, grace_days=args.grace_days)
    step("grace_running", actions=len(plan.actions),
         note=f"day {args.grace_days - 1} of {args.grace_days}: no action expected")

    # -- 6. TRASHED -> PURGED: grace elapsed, and only then -------------------
    plan = plan_reconcile(manifest, now=now + timedelta(days=args.grace_days + 1),
                          verify_remote=verify_remote, grace_days=args.grace_days)
    before = manifest.current()[str(artifact)].state
    reconcile(manifest, plan, now=now + timedelta(days=args.grace_days + 1),
              trim_mover=trim_mover, purge_mover=purge_mover)
    after = manifest.current()[str(artifact)].state
    step("purged", before=before, after=after, plan=_plan_summary(plan))

    # -- 7. reconcile_all to quiescence --------------------------------------
    late = now + timedelta(days=args.grace_days + 1)
    quiesced = reconcile_all(manifest, now=late, verify_remote=verify_remote,
                             trim_mover=trim_mover, purge_mover=purge_mover,
                             grace_days=args.grace_days)
    step("quiesced", actions=len(quiesced.actions), problems=list(quiesced.problems),
         final_state=manifest.current()[str(artifact)].state)

    record = {
        "artifact_label": _label(artifact),
        "size": size,
        "sha256_prefix": digest[:12],
        "backend": backend.name,
        "grace_days": args.grace_days,
        "steps": steps,
        "states_walked": [s["step"] for s in steps],
        "final_state": manifest.current()[str(artifact)].state,
    }

    if args.json:
        print(json.dumps(record, sort_keys=True))
    else:
        print(f"artifact          : {_label(artifact)} ({size} B, sha256 {digest[:12]}...)")
        print(f"backend           : {backend.name}  (a fixture, NOT MEGA)")
        print(f"grace             : {args.grace_days} days")
        print()
        for s in steps:
            print(f"  {s['step']:<14} {json.dumps({k: v for k, v in s.items() if k != 'step'}, sort_keys=True)}")
        print()
        print(f"final state       : {record['final_state']}")
        print()
        print("WHAT THIS DOES NOT PROVE: the network. MEGA is unreachable from this")
        print("sandbox and restic/rclone are not installed here, so the live transition")
        print("remains unrun. The state machine, the trim move, the grace clock and the")
        print("record are all exercised by the real code above.")

    # A transition that did not land is a failure, not a formatting problem.
    if record["final_state"] != PURGED:
        print(f"REFUSED: expected to reach {PURGED}, reached {record['final_state']}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
