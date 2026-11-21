"""The limiter's own numbers, from the durable record (Ask 18).

A journal grep for `capture.levels` coming back empty **discriminates nothing**:
a stale daemon, another unit, a rotated journal and "no session on this unit" all
look the same. The store cannot be stale that way — a dictation writes a
`capture.stats` event on its way out.

These pins prove the reader on BOTH controls and, just as important, prove that a
row with no limiter counters reads as **NOT MEASURED (-1)** rather than as a
clean "the limiter did not fire". The current base tree's `transcribe.py` emits
exactly such a row, so the honest reading today is -1; folding that into 0 would
be silence-as-proof-of-absence, which is the one mistake this cluster exists to
prevent.
"""

from __future__ import annotations

import hashlib
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
        # `ts` is the reader's key, not the payload's: keep the row's stamp out
        # of the detail JSON exactly as the daemon does.
        store.log_persona_event(event.get("ts", "2026-11-17T07:00:00+03:00"),
                                "capture.stats", json.dumps(event))
    store.close()
    return path


# POSITIVE control: the raw input was hotter than what went out, and samples
# were actually limited.
HOT = {
    "ts": "2026-11-17T09:32:00+03:00",
    "node": "alsa_input.pci-0000_00_1f.3.HiFi__Mic1__source",
    "peak_rms": 0.72, "peak": 1.0, "frames": 164, "no_speech": False,
    "raw_peak": 1.0, "processed_peak": 0.8554,
    "limiter": {"raw_peak": 1.0, "processed_peak": 0.8554,
                "limited_samples": 480, "frames": 164},
}

# NEGATIVE control: measured, nothing to limit (input already under the knee).
QUIET = {
    "ts": "2026-11-17T08:00:00+03:00",
    "node": "alsa_input.pci-0000_00_1f.3.HiFi__Mic1__source",
    "peak_rms": 0.23, "peak": 0.23, "frames": 100, "no_speech": False,
    "raw_peak": 0.23, "processed_peak": 0.23,
    "limiter": {"raw_peak": 0.23, "processed_peak": 0.23,
                "limited_samples": 0, "frames": 100},
}

# NOT-MEASURED control: the shape the CURRENT tree actually writes
# (transcribe.py capture_stats) — no limiter counters at all.
UNMEASURED = {
    "session_id": "abc123", "node": "default", "bytes": 9600,
    "peak_rms": 0.0117, "frames": 100, "peak": 0.8624,
    "silence_floor": 0.003, "duration_s": 0.3, "gated_frames": 40,
    "stalled": False, "no_speech": False,
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


def test_limiter_effective_positive_and_negative_controls(tmp_path):
    db = _db(tmp_path, [QUIET, HOT])
    sessions, _ = readings.read_sessions(db, limit=3)
    pairs = [(readings.describe(s)["limiter_effective"],
              readings.describe(s)["limiter_effective_reason"]) for s in sessions]
    assert pairs == [(1, "limited"), (0, "nothing_to_limit")]


def test_a_row_without_counters_is_not_measured_not_a_clean_verdict(tmp_path):
    """The anti-vacuity pin: absent fields must never print 0."""
    db = _db(tmp_path, [UNMEASURED])
    sessions, _ = readings.read_sessions(db, limit=3)
    described = readings.describe(sessions[0])
    assert described["limiter_effective"] == -1
    assert described["limiter_effective_reason"] == "fields_absent"
    assert described["limiter_fields_present"] == 0
    assert described["raw_peak"] is None


def test_the_current_trees_real_emit_shape_reads_as_unmeasured(tmp_path):
    """Pin the reader against transcribe.py's ACTUAL capture_stats keys.

    If transcribe.py ever starts emitting the limiter counters this test goes
    red on purpose: the reader's honest answer would have changed from
    "instrument missing" to a real measurement, and that is a fact the owner
    must be told, not absorbed silently.
    """
    source = (REPO / "src" / "assistant" / "transcribe.py").read_text(encoding="utf-8")
    block = source.split("capture_stats = {", 1)[1].split("}", 1)[0]
    for key in readings.LIMITER_FIELDS:
        assert key not in block, (
            f"transcribe.py now emits {key!r} — regenerate the owner reading and "
            "update this pin instead of leaving the reader's answer stale")
    db = _db(tmp_path, [UNMEASURED])
    sessions, _ = readings.read_sessions(db, limit=3)
    assert readings.describe(sessions[0])["limiter_effective"] == -1


def test_partial_fields_report_which_one_is_missing():
    only_raw = {"raw_peak": 1.0}
    assert readings.limiter_effective(only_raw) == (-1, "partial_fields_missing_processed_peak")
    no_count = {"raw_peak": 1.0, "processed_peak": 0.8}
    assert readings.limiter_effective(no_count) == (-1, "limited_samples_absent")
    # Counters present but unparseable is still "not measured", never 0.
    junk = {"raw_peak": "loud", "processed_peak": 0.8, "limited_samples": 4}
    assert readings.limiter_effective(junk)[0] == -1


def test_the_nested_limiter_block_is_a_fallback_not_a_second_truth():
    flat = {"raw_peak": 1.0, "processed_peak": 0.8554, "limited_samples": 480}
    nested = {"limiter": {"raw_peak": 1.0, "processed_peak": 0.8554,
                          "limited_samples": 480}}
    for shaped in (flat, nested):
        described = readings.describe(shaped)
        assert described["processed_peak"] == 0.8554
        assert described["limiter_effective"] == 1


def test_both_shapes_agree_when_they_carry_the_same_numbers():
    both = {"raw_peak": 1.0, "processed_peak": 0.8554, "limited_samples": 480,
            "limiter": HOT["limiter"]}
    assert readings.describe(both)["limiter_effective"] == 1
    assert readings.describe(both)["limiter_provenance"] == "flat/flat/flat"


def test_render_is_key_value_only_and_says_read_only(tmp_path):
    db = _db(tmp_path, [HOT])
    sessions, _ = readings.read_sessions(db, limit=3)
    lines = readings.render([readings.describe(sessions[0])]).splitlines()
    assert lines[0] == "available 1"
    assert lines[1] == "sessions 1"
    assert "session_0.processed_peak 0.8554" in lines
    assert "session_0.limiter_effective 1" in lines
    assert "limiter_measured_sessions 1" in lines
    assert lines[-1] == "note read_only"
    for line in lines:
        assert " " in line


def test_an_unmeasured_run_says_missing_instrument_not_clean(tmp_path):
    db = _db(tmp_path, [UNMEASURED])
    sessions, _ = readings.read_sessions(db, limit=3)
    text = readings.render([readings.describe(sessions[0])])
    assert "session_0.limiter_effective -1" in text
    assert "limiter_measured_sessions 0" in text
    assert "note limiter_not_measured_in_any_row" in text
    assert "note this_is_a_missing_instrument_not_a_clean_verdict" in text


def test_a_missing_database_says_so_and_states_what_it_cannot_tell(tmp_path, capsys):
    code = readings.main(["--db", str(tmp_path / "absent.db")])
    out = capsys.readouterr().out
    assert code == 2
    assert out.splitlines()[0] == "available 0"
    assert "no database at" in out
    assert "note empty_fails_to_discriminate" in out


def test_bad_arguments_are_refused_without_tracebacks(tmp_path, capsys):
    assert readings.main(["--limit", "many"]) == 2
    assert readings.main(["--wat"]) == 2
    assert readings.main(["--limit"]) == 2
    assert readings.main(["--help"]) == 2


def test_the_reader_is_read_only_at_the_file_and_in_the_source(tmp_path):
    """No writes, no DDL, no migrations — the store stays byte-identical."""
    db = _db(tmp_path, [HOT, QUIET])
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    readings.read_sessions(db, limit=3)
    readings.read_sessions(db, limit=3)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert "mode=ro" in SCRIPT.read_text(encoding="utf-8")
    # Prove it from the AST, not from the prose: every SQL string the script
    # can hand to sqlite must be a SELECT, and nothing may commit.
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    statements = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", getattr(node.func, "id", ""))
            if name == "commit":
                raise AssertionError("a read-only reader must never commit")
            if name == "execute":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        statements.append(arg.value.strip().upper())
    assert statements, "expected the reader's sqlite calls to be visible to this pin"
    for statement in statements:
        assert statement.startswith("SELECT"), statement


def test_reading_never_creates_a_missing_database(tmp_path):
    target = tmp_path / "not-there.db"
    sessions, reason = readings.read_sessions(target, limit=3)
    assert sessions == [] and "no database at" in reason
    assert not target.exists(), "a reader must not materialise a store"


def test_manifest_is_repo_relative_and_verifies_from_the_root():
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
