#!/usr/bin/env python3
"""The capture limiter's own numbers, from the daemon's durable record.

Ask 18 (2026-11-17): *"If a limiter were active, nothing in the file could read
1.0000 at all — and 38 frames do. Is it wired? Is it enabled at this gain? What
is its threshold?"*

The code answers the first three (wired, unconditional, static curve knee 0.6 /
ceiling 0.89, applied **before** the take is written) and a pinned test proves a
full-scale source reads back from disk at <= 0.89. That means a
dictate-produced take cannot contain a 1.0000 sample — so the owner's take that
does needs its OWN numbers, not a fresh theory.

The journal grep came back empty, which discriminates nothing on its own: a
stale daemon, another unit, or no session on that unit all look the same. The
durable record is the store, and it cannot be stale — every `dictate` writes a
`capture.stats` persona event carrying the limiter's raw and processed peaks and
its limited-sample count.

This prints those numbers, read-only, one `key value` line per session,
newest first. `limiter_effective 1` means the raw input was hotter than what
went out (processed < raw with samples actually limited); `0` means either
nothing needed limiting or the limiter did not see that audio.

Usage:
  limiter_readings.py                 # the last 3 measured sessions
  limiter_readings.py --limit 10
  limiter_readings.py --db /path/to/assistant.db
  limiter_readings.py --checksum

Integrity: `scripts/limiter_readings.py.sha256` holds this file's digest under
its repository-relative name; verify from the repository root with
`sha256sum -c scripts/limiter_readings.py.sha256`.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

UNKNOWN = "-1"


def default_db_path() -> Path:
    """The daemon's database, resolved the way the daemon resolves it."""
    try:
        from assistant.config import load_config

        return Path(load_config().db_path)
    except Exception:
        data = os.environ.get("XDG_DATA_HOME", "")
        root = Path(data).expanduser() if data else Path.home() / ".local" / "share"
        return root / "assistant" / "assistant.db"


def read_sessions(db: Path, limit: int = 3) -> tuple[list[dict], str]:
    """Newest `capture.stats` rows, parsed. Read-only; never creates the file."""
    if not db.exists():
        return [], f"no database at {db}"
    uri = f"file:{db}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        return [], f"{type(exc).__name__}: {exc}"
    try:
        rows = connection.execute(
            "SELECT ts, detail FROM persona_events "
            "WHERE kind = 'capture.stats' ORDER BY id DESC LIMIT ?",
            (int(limit),)).fetchall()
    except sqlite3.Error as exc:
        return [], f"{type(exc).__name__}: {exc}"
    finally:
        connection.close()
    sessions = []
    for ts, detail in rows:
        try:
            data = json.loads(detail)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            sessions.append({"ts": ts, **data})
    return sessions, ""


def _value(session: dict, key: str):
    for source in (session, session.get("limiter") or {}):
        if isinstance(source, dict) and source.get(key) is not None:
            return source[key]
    return None


def describe(session: dict) -> dict:
    """The limiter's numbers for one session, and whether it did anything."""
    raw = _value(session, "raw_peak")
    processed = _value(session, "processed_peak")
    limited = _value(session, "limited_samples")
    effective = None
    try:
        if raw is not None and processed is not None:
            effective = int(float(processed) < float(raw)
                            and (limited or 0) > 0)
    except (TypeError, ValueError):
        effective = None
    return {
        "ts": session.get("ts") or UNKNOWN,
        "node": session.get("node") or UNKNOWN,
        "peak_full": _value(session, "peak_full"),
        "peak_steady": _value(session, "peak_steady"),
        "raw_peak": raw,
        "processed_peak": processed,
        "limited_samples": limited,
        "frames": session.get("frames"),
        "no_speech": (1 if session.get("no_speech") else 0),
        "limiter_effective": (UNKNOWN if effective is None else effective),
    }


def render(readings: list[dict]) -> str:
    lines = [f"available {1 if readings else 0}", f"sessions {len(readings)}"]
    for index, reading in enumerate(readings):
        for key in ("ts", "node", "peak_full", "peak_steady", "raw_peak",
                    "processed_peak", "limited_samples", "frames", "no_speech",
                    "limiter_effective"):
            value = reading[key]
            lines.append(f"session_{index}.{key} {UNKNOWN if value is None else value}")
    if readings:
        lines.append("note read_only")
    return "\n".join(lines)


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
        print("usage: limiter_readings.py [--limit N] [--db PATH] | --checksum",
              file=sys.stderr)
        return 2
    if argv and argv[0] == "--checksum":
        print(write_manifest())
        return 0
    limit = 3
    db: Path | None = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("--limit", "--db"):
            if index + 1 >= len(argv):
                print(f"error value_required {token}", file=sys.stderr)
                return 2
            if token == "--limit":
                limit = int(argv[index + 1])
            else:
                db = Path(argv[index + 1]).expanduser()
            index += 2
            continue
        print(f"error unknown_argument {token}", file=sys.stderr)
        return 2
    sessions, reason = read_sessions(db or default_db_path(), limit)
    if not sessions:
        print(f"available 0\nreason {reason or 'no capture.stats rows'}")
        return 2
    print(render([describe(session) for session in sessions]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
