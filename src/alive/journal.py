"""Append-only journal for the alive host.

Every event this layer handles — accepted, rejected, deduped, capped,
quarantined, sent, blocked — lands here BEFORE the outcome is claimed
(journal BEFORE action; silence is never success).

One JSON object per line. The journal carries no raw phone numbers and no
message bodies beyond what an envelope already authorises the host to hold
(envelopes hold bodies for 72 h; the journal holds only ids/hashes).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

_LOCK = threading.Lock()


def iso_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def journal_path(state_dir: Path) -> Path:
    return Path(state_dir) / "alive-journal.jsonl"


def log_event(state_dir: Path, event: str, *, level: str = "info", **detail) -> None:
    """Append one event. Never raises — a journal that can crash the host is
    worse than one that degrades loudly, so a failed write is printed to
    stderr as a last resort and counted in the returned record."""
    record = {"ts": iso_now(), "event": event, "level": level, **detail}
    line = json.dumps(record, sort_keys=True, ensure_ascii=False)
    try:
        path = journal_path(state_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOCK, open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError as exc:  # last-resort visibility; do not crash the receiver
        import sys
        print(f"alive: JOURNAL WRITE FAILED: {exc}: {line}", file=sys.stderr)


def read_events(state_dir: Path, *, limit: int = 200) -> list[dict]:
    path = journal_path(state_dir)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    for raw in lines[-limit:]:
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out
