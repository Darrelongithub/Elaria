#!/usr/bin/env python3
"""The capture limiter's own numbers, read from the daemon's durable record.

Ask 18 (2026-11-17): *"If a limiter were active, nothing in the file could read
1.0000 at all — and 38 frames do. Is it wired? Is it enabled at this gain? What
is its threshold?"*

A journal grep cannot answer that. `journalctl | grep capture.levels` coming back
empty **discriminates nothing**: a stale daemon, a different unit, a rotated
journal and "no session ran on this unit" all produce the same silence. The store
cannot be stale that way — every dictation writes a `capture.stats` persona event
on the way out.

So this reads those rows, newest first, and prints numbers. It writes nothing:
the connection is opened `mode=ro`, no DDL, no migration, no `CREATE TABLE`. The
database file is byte-identical before and after a read (pinned by test).

`limiter_effective` is THREE-valued on purpose:

  1   the limiter did something — processed_peak < raw_peak AND limited_samples > 0
  0   the limiter was measured and had nothing to do (the input was already under
      the knee) — this is a real, useful answer
 -1   the limiter was NOT MEASURED: the row carries no raw_peak / processed_peak /
      limited_samples, so nothing about its effectiveness may be claimed

That third state is the whole point. A reader that folded "no fields" into `0`
would report "the limiter did not fire" about audio it never saw, which is the
silence-as-proof-of-absence mistake this cluster exists to prevent.

Provenance note: on the current base tree the `SoftLimiter` counters
(`raw_peak` / `processed_peak` / `limited_samples`) are **not** emitted by
`transcribe.py` or `event.py`, so honest output today is `limiter_effective -1`
with `limiter_fields_present 0`. On a tree that carries the limiter, the same
reader returns 1/0. When those lines say `0`, the reader is telling you the
instrument is missing — not that the limiter is innocent.

Usage:
  limiter_readings.py                     # the last 3 measured sessions
  limiter_readings.py --limit 10
  limiter_readings.py --db /path/to/assistant.db
  limiter_readings.py --checksum          # regenerate this file's .sha256

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

# The counters the limiter would publish. Named once so "absent" and "zero"
# can never be confused by a typo.
LIMITER_FIELDS = ("raw_peak", "processed_peak", "limited_samples")

EMPTY_FAILS_TO_DISCRIMINATE = (
    "no capture.stats rows in this database cannot tell apart: (a) the daemon "
    "never ran against this file, (b) the daemon ran against a different file, "
    "(c) a session reached capture but exited before stats were written, or "
    "(d) the store is intact and simply has no dictation yet"
)


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
    db = Path(db)
    if not db.exists():
        return [], f"no database at {db}"
    uri = f"file:{db}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5.0)
    except sqlite3.Error as exc:
        return [], f"{type(exc).__name__}: {exc}"
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT ts, detail FROM persona_events "
            "WHERE kind = 'capture.stats' ORDER BY id DESC LIMIT ?",
            (int(limit),)).fetchall()
    except sqlite3.Error as exc:
        return [], f"{type(exc).__name__}: {exc}"
    finally:
        connection.close()
    sessions: list[dict] = []
    for row in rows:
        try:
            data = json.loads(row["detail"])
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            sessions.append({"ts": row["ts"], **data})
    return sessions, ""


def _value(session: dict, key: str) -> tuple[object, str]:
    """`(value, where)` — the flat key wins, the nested limiter block is the
    fallback. Returns `(None, "")` when neither carries the field."""
    for where, source in (("flat", session), ("nested", session.get("limiter"))):
        if isinstance(source, dict) and source.get(key) is not None:
            return source[key], where
    return None, ""


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def limiter_effective(session: dict) -> tuple[int, str]:
    """`(1|0|-1, reason)`. -1 means NOT MEASURED, never "did not fire"."""
    raw, _ = _value(session, "raw_peak")
    processed, _ = _value(session, "processed_peak")
    limited, _ = _value(session, "limited_samples")
    if raw is None and processed is None and limited is None:
        return -1, "fields_absent"
    if raw is None or processed is None:
        missing = "raw_peak" if raw is None else "processed_peak"
        return -1, f"partial_fields_missing_{missing}"
    raw_f, processed_f = _as_float(raw), _as_float(processed)
    if raw_f is None or processed_f is None:
        return -1, "unparseable_peaks"
    if limited is None:
        return -1, "limited_samples_absent"
    try:
        limited_i = int(limited)
    except (TypeError, ValueError):
        return -1, "unparseable_limited_samples"
    if processed_f < raw_f and limited_i > 0:
        return 1, "limited"
    if limited_i == 0:
        return 0, "nothing_to_limit"
    return 0, "count_only"


def describe(session: dict) -> dict:
    """The limiter's numbers for one session, and whether it did anything."""
    effective, reason = limiter_effective(session)
    _, raw_where = _value(session, "raw_peak")
    _, processed_where = _value(session, "processed_peak")
    _, limited_where = _value(session, "limited_samples")
    present = sum(1 for key in LIMITER_FIELDS if _value(session, key)[0] is not None)
    return {
        "ts": session.get("ts") or UNKNOWN,
        "node": session.get("node") or UNKNOWN,
        "peak_rms": session.get("peak_rms"),
        "peak": session.get("peak"),
        "raw_peak": _value(session, "raw_peak")[0],
        "processed_peak": _value(session, "processed_peak")[0],
        "limited_samples": _value(session, "limited_samples")[0],
        "frames": session.get("frames"),
        "no_speech": (1 if session.get("no_speech") else 0),
        "limiter_fields_present": present,
        "limiter_provenance": (f"{raw_where or '-'}/{processed_where or '-'}"
                              f"/{limited_where or '-'}"),
        "limiter_effective": effective,
        "limiter_effective_reason": reason,
    }


KEYS = ("ts", "node", "peak_rms", "peak", "raw_peak", "processed_peak",
        "limited_samples", "frames", "no_speech", "limiter_fields_present",
        "limiter_provenance", "limiter_effective", "limiter_effective_reason")


def render(readings: list[dict]) -> str:
    lines = [f"available {1 if readings else 0}", f"sessions {len(readings)}"]
    for index, reading in enumerate(readings):
        for key in KEYS:
            value = reading.get(key)
            lines.append(f"session_{index}.{key} {UNKNOWN if value is None else value}")
    if readings:
        measured = sum(1 for r in readings if r["limiter_effective"] != -1)
        lines.append(f"limiter_measured_sessions {measured}")
        if measured == 0:
            lines.append("note limiter_not_measured_in_any_row")
            lines.append("note this_is_a_missing_instrument_not_a_clean_verdict")
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
                try:
                    limit = int(argv[index + 1])
                except ValueError:
                    print("error limit_must_be_an_integer", file=sys.stderr)
                    return 2
            else:
                db = Path(argv[index + 1]).expanduser()
            index += 2
            continue
        print(f"error unknown_argument {token}", file=sys.stderr)
        return 2
    sessions, reason = read_sessions(db or default_db_path(), limit)
    if not sessions:
        print(f"available 0\nreason {reason or 'no capture.stats rows'}")
        print(f"note empty_fails_to_discriminate {EMPTY_FAILS_TO_DISCRIMINATE}")
        return 2
    print(render([describe(session) for session in sessions]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
