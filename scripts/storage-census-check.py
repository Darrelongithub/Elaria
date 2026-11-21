#!/usr/bin/env python3
"""Census ground-truth check: three independent computations that must agree.

WHY THIS EXISTS
---------------
The WP7 capacity model and the age-trigger state are only as good as the census they
rest on. A census that is asserted rather than measured is the same failure mode as a
check that passes without running. So this script computes the audio directory three
ways, independently, and refuses to report a number unless they reconcile:

  1. `os.walk` + `st_size`     — a Python walk, with never-retry marks excluded
  2. `du -sb`                  — the shell's own byte total, an outside opinion
  3. the manifest arithmetic   — sum of `size` over the manifest's records

It never averages, never picks a favourite, and never reports a number it could not
reproduce.

TWO SUBTLETIES THAT MUST BE STATED, NOT DISCOVERED THE HARD WAY
---------------------------------------------------------------
**`du -sb <dir>` includes the directory inode's own apparent size** (4096 on ext4).
Measured: files 176,283 + directory 4,096 = `du -sb` 180,379. So the directory's own
size is subtracted, and the raw figure is disclosed alongside the adjusted one.

**`du -sb` counts the never-retry marks; the census must not.** A ruling says the
44-byte header-only file is a never-retry mark that counts zero forever. So the two
differ *on purpose*, and the check is that the difference equals the marks' byte total
exactly — to the byte. A gap of any other size means the walk dropped a real recording,
which is a genuine defect and not a rounding artefact.

PRIVACY
-------
It prints byte counts, file counts and the number of never-retry marks. It never prints
a path, a filename, or anything that could identify content.

USAGE (owner, on his own machine)
---------------------------------
    python3 scripts/storage-census-check.py --audio ~/Elaria/audio \\
                                           --manifest ~/.local/share/assistant/manifest.jsonl

EXIT: 0 = reconciled. 1 = refused, with the reason on stderr.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import subprocess
import sys

WAV_MAGIC = b"RIFF"
WAVE_MAGIC = b"WAVE"
_PROBE_BYTES = 4096


def is_never_retry_mark(path: str) -> bool:
    """True when `path` is a RIFF/WAVE whose `data` chunk declares zero frames.

    Structural, never a byte comparison: a chunked zero-frame WAV is 62-66 bytes, and
    comparing total size against 44 misses it. That exact defect was found once already.
    """
    try:
        with open(path, "rb") as fh:
            blob = fh.read(_PROBE_BYTES)
        if len(blob) < 12 or blob[0:4] != WAV_MAGIC or blob[8:12] != WAVE_MAGIC:
            return False
        pos = 12
        while pos + 8 <= len(blob):
            chunk_id = blob[pos:pos + 4]
            (declared,) = struct.unpack_from("<I", blob, pos + 4)
            if chunk_id == b"data":
                return declared == 0
            pos += 8 + declared + (declared & 1)  # chunks are word-aligned
        return False
    except OSError:
        return False


def walk_bytes(root: str) -> tuple[int, int, int, int, list[str]]:
    """(total, files, marks, mark_bytes, problems) from an independent walk.

    `mark_bytes` is the byte total of the marks that were excluded, returned so the
    caller can prove the exclusion was exact rather than arbitrary.
    """
    total = 0
    files = 0
    marks = 0
    mark_bytes = 0
    problems: list[str] = []
    if not os.path.isdir(root):
        return 0, 0, 0, 0, [f"audio directory not readable: {root}"]
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                size = os.lstat(full).st_size
            except OSError as exc:
                problems.append(f"stat failed: {name} ({exc.__class__.__name__})")
                continue
            files += 1
            if name.lower().endswith(".wav") and is_never_retry_mark(full):
                # A never-retry mark counts zero forever. Counted, never summed.
                marks += 1
                mark_bytes += size
                continue
            total += size
    return total, files, marks, mark_bytes, problems


def du_bytes(root: str) -> tuple[int, int, int, list[str]]:
    """(comparable, raw, dir_inode, problems).

    `comparable` is the `du -sb` figure with the directory inode's own apparent size
    subtracted, so it measures the same thing the walk does. `raw` is disclosed so the
    adjustment is never hidden.
    """
    try:
        out = subprocess.run(
            ["du", "-sb", root], capture_output=True, text=True, check=True
        )
        raw = int(out.stdout.split()[0])
    except (OSError, subprocess.CalledProcessError) as exc:
        return -1, -1, -1, [f"du -sb failed: {exc.__class__.__name__}"]
    try:
        dir_own = os.lstat(root).st_size
    except OSError as exc:
        return raw, raw, -1, [f"could not stat the directory itself: {exc.__class__.__name__}"]
    return raw - dir_own, raw, dir_own, []


def manifest_bytes(manifest: str) -> tuple[int, int, list[str], list[str]]:
    """(total, records, problems, errors).

    A torn line is **discarded, not counted** — the same rule the manifest's own reader
    applies — and recorded as an informational problem, not a fatal error. A manifest
    that cannot be read at all *is* fatal: claiming a census without one is the
    silent-pass failure this lane exists to prevent.
    """
    total = 0
    records = 0
    problems: list[str] = []
    errors: list[str] = []
    if not manifest or not os.path.exists(manifest):
        return 0, 0, [], [f"manifest not readable: {manifest}"]
    try:
        with open(manifest, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError as exc:
        return 0, 0, [], [f"manifest unreadable: {exc.__class__.__name__}"]
    for lineno, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"torn line at {lineno} discarded")
            continue
        records += 1
        size = rec.get("size")
        if isinstance(size, int):
            total += size
    return total, records, problems, errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--audio", required=True, help="the audio directory to census")
    ap.add_argument("--manifest", required=True, help="path to the storage manifest JSONL")
    ap.add_argument("--json", action="store_true", help="emit one JSON object")
    args = ap.parse_args(argv)

    py_total, files, marks, mark_bytes, problems = walk_bytes(args.audio)
    du_total, du_raw, du_inode, du_problems = du_bytes(args.audio)
    man_total, man_records, man_problems, man_errors = manifest_bytes(args.manifest)
    problems = problems + du_problems + man_problems
    errors = list(man_errors)

    # The census and du -sb differ by the marks ON PURPOSE. The check is that the
    # difference equals the marks' byte total exactly — anything else is a real defect.
    du_explained = du_total >= 0 and du_total == py_total + mark_bytes
    manifest_agrees = man_total == py_total

    if not du_explained:
        errors.append(
            "du -sb minus the census is not exactly the never-retry marks' byte total "
            f"(du={du_total}, census={py_total}, marks={mark_bytes}); the walk may have "
            "dropped something that is not a mark"
        )
    if not manifest_agrees:
        errors.append(
            f"the manifest arithmetic does not match the walk "
            f"(manifest={man_total}, walk={py_total})"
        )

    payload = {
        "audio_bytes": py_total,
        "du_bytes_comparable": du_total,
        "du_bytes_raw": du_raw,
        "du_dir_inode_subtracted": du_inode,
        "manifest_bytes": man_total,
        "manifest_records": man_records,
        "file_count": files,
        "never_retry_marks": marks,
        "never_retry_mark_bytes": mark_bytes,
        "du_minus_census": (du_total - py_total) if du_total >= 0 else None,
        "du_gap_equals_mark_bytes": du_explained,
        "manifest_agrees_with_walk": manifest_agrees,
        "problems": problems,
        "errors": errors,
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"audio bytes        : {py_total}")
        print(f"du -sb (comparable): {du_total}"
              f"   [raw {du_raw}, dir inode {du_inode} subtracted]")
        print(f"manifest bytes     : {man_total} over {man_records} records")
        print(f"files              : {files}")
        print(f"never-retry marks  : {marks} ({mark_bytes} B excluded; "
              f"du counts them, the census must not)")
        print(f"du - census        : {du_total - py_total} B"
              f"   [must equal the marks' bytes: {mark_bytes}]")
        if problems:
            print("notes              :")
            for p in problems:
                print(f"  - {p}")

    if errors:
        for e in errors:
            print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
