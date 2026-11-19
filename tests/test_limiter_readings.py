"""The limiter's own numbers from the durable record (2026-11-17, Ask 18).

The journal grep `journalctl --user -u assistant … | grep capture.levels` came
back **empty**, which discriminates nothing by itself: a stale daemon, another
unit, or no session on that unit all look identical. The store cannot be stale —
every `dictate` writes a `capture.stats` persona event that carries the
limiter's `raw_peak`, `processed_peak` and `limited_samples`.

These pins prove the reader: newest first, the two peak readings kept apart, and
`limiter_effective` true only when something was actually limited.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "limiter_readings.py"
MANIFEST = REPO / "scripts" / "limiter_readings.py.sha256"

_spec = importlib.util.spec_from_file_location("limiter_readings", SCRIPT)
readings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(readings)

from assistant.store import Store


def _db(tmp_path: Path, events: list[dict]) -> Path:
    path = tmp_path / "assistant.db"
    store = Store(path)
    for event in events:
        store.log_persona_event(event["ts"], "capture.stats", json.dumps(event))
    store.close() if hasattr(store, "close") else None
    return path


HOT = {
    "ts": "2026-11-17T09:32:00+03:00", "kind": "capture.stats",
    "node": "alsa_input.pci-0000_00_1f.3.HiFi__Mic1__source",
    "peak_full": 1.0, "peak_steady": 1.0, "frames": 164, "no_speech": False,
    "raw_peak": 1.0, "processed_peak": 0.8554,
    "limiter": {"raw_peak": 1.0, "processed_peak": 0.8554,
                "limited_samples": 480, "frames": 164},
}

QUIET = {
    "ts": "2026-11-17T08:00:00+03:00", "kind": "capture.stats",
    "node": "alsa_input.pci-0000_00_1f.3.HiFi__Mic1__source",
    "peak_full": 0.23, "peak_steady": 0.23, "frames": 100, "no_speech": False,
    "raw_peak": 0.23, "processed_peak": 0.23,
    "limiter": {"raw_peak": 0.23, "processed_peak": 0.23,
                "limited_samples": 0, "frames": 100},
}


def test_reads_newest_first_and_keeps_both_peak_readings(tmp_path):
    db = _db(tmp_path, [QUIET, HOT])
    sessions, reason = readings.read_sessions(db, limit=3)
    assert reason == "" and len(sessions) == 2
    newest = readings.describe(sessions[0])
    assert newest["ts"] == HOT["ts"]
    assert newest["raw_peak"] == 1.0            # the danger, never hidden
    assert newest["processed_peak"] == 0.8554   # ...and what went out
    assert newest["limited_samples"] == 480


def test_limiter_effective_is_true_only_when_something_was_limited(tmp_path):
    db = _db(tmp_path, [QUIET, HOT])
    sessions, _ = readings.read_sessions(db, limit=3)
    assert [readings.describe(s)["limiter_effective"] for s in sessions] == [1, 0]


def test_the_nested_limiter_block_is_a_fallback_not_a_second_truth():
    flat = {"raw_peak": 1.0, "processed_peak": 0.8554, "limited_samples": 480}
    nested = {"limiter": {"raw_peak": 1.0, "processed_peak": 0.8554,
                          "limited_samples": 480}}
    for shaped in (flat, nested):
        described = readings.describe(shaped)
        assert described["processed_peak"] == 0.8554
        assert described["limiter_effective"] == 1


def test_render_is_key_value_only_and_says_read_only(tmp_path):
    db = _db(tmp_path, [HOT])
    sessions, _ = readings.read_sessions(db, limit=3)
    lines = readings.render([readings.describe(sessions[0])]).splitlines()
    assert lines[0] == "available 1"
    assert lines[1] == "sessions 1"
    assert "session_0.processed_peak 0.8554" in lines
    assert lines[-1] == "note read_only"
    for line in lines:
        assert " " in line


def test_a_missing_database_says_so_and_invents_nothing(tmp_path, capsys):
    code = readings.main(["--db", str(tmp_path / "absent.db")])
    out = capsys.readouterr().out
    assert code == 2
    assert out.splitlines()[0] == "available 0"
    assert "no database at" in out


def test_the_reader_is_read_only(tmp_path):
    """No writes, no DDL, no migrations — the store stays byte-identical."""
    import hashlib

    db = _db(tmp_path, [HOT])
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    readings.read_sessions(db, limit=3)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    source = SCRIPT.read_text(encoding="utf-8").upper()
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "DROP "):
        assert verb not in source, verb


def test_manifest_is_repo_relative_and_verifies_from_the_root():
    import hashlib

    digest, name = MANIFEST.read_text().split()
    assert name == "scripts/limiter_readings.py"
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == digest, (
        "limiter_readings.py changed without regenerating its manifest — run "
        "`python3 scripts/limiter_readings.py --checksum`")
    verified = subprocess.run(
        ["sha256sum", "-c", "scripts/limiter_readings.py.sha256"],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_the_cli_prints_the_last_sessions_from_a_real_store(tmp_path, capsys):
    db = _db(tmp_path, [QUIET, HOT])
    code = readings.main(["--db", str(db), "--limit", "2"])
    out = capsys.readouterr().out
    assert code == 0
    assert "session_0.raw_peak 1.0" in out
    assert "session_0.limiter_effective 1" in out
    assert "session_1.limiter_effective 0" in out
