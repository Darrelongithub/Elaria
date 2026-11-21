"""Playback probe — exit code, stderr, first byte (Ask 47 / decision 29).

The parked "none-played" bug (ask 45) is diagnosed here and **not fixed**; the
owner unpark is theirs. The one fact the probe exists to make visible is that
**a player can exit 0 and play nothing**, so `exit 0` is not evidence of sound.

Controls in this file are real processes and real wavs — a player-shaped fake is
a script this test spawns. A control that could pass for the wrong reason would
be worse than no control, so the positive control is checked for exit 0 *and*
first-byte observation, and each negative for its specific verdict.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import struct
import subprocess
import sys
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "player_probe.py"
MANIFEST = REPO / "scripts" / "player_probe.py.sha256"

_spec = importlib.util.spec_from_file_location("player_probe", SCRIPT)
probe_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe_mod)

from assistant.store import Store


def write_wav(path: Path, seconds: float = 0.2, amplitude: int = 4000,
              rate: int = 16000) -> Path:
    frames = int(rate * seconds)
    samples = [(amplitude if i % 2 else -amplitude) for i in range(frames)]
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(s.to_bytes(2, "little", signed=True)
                                    for s in samples))
    return path


def fake_player(tmp_path: Path, name: str, body: str) -> list[str]:
    script = tmp_path / name
    script.write_text(body, encoding="utf-8")
    return [sys.executable, str(script)]


# ---------------------------------------------------------------------------
# wav facts
# ---------------------------------------------------------------------------
def test_wav_facts_are_numbers(tmp_path):
    path = write_wav(tmp_path / "tone.wav", seconds=0.5, amplitude=8000)
    facts = probe_mod.wav_facts(path)
    assert facts["rate_hz"] == 16000
    assert facts["channels"] == 1
    assert facts["sampwidth_bits"] == 16
    assert facts["frames"] == 8000
    assert facts["duration_s"] == 0.5
    assert facts["peak"] == round(8000 / 32768, 4)
    # The FIRST sample of this tone is negative-8000, not the peak: a probe that
    # reported the peak as the "first byte" could never show leading silence.
    assert facts["first_sample_hex"] == f"{(-8000) & 0xFFFF:04x}"


def test_a_leading_silence_gap_is_visible_in_the_first_sample(tmp_path):
    path = tmp_path / "lead-silent.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 800 + struct.pack("<h", 5000) * 800)
    facts = probe_mod.wav_facts(path)
    assert facts["first_sample_hex"] == "0000"
    assert facts["peak"] > 0


# ---------------------------------------------------------------------------
# classification: each verdict on a real process
# ---------------------------------------------------------------------------
def test_positive_control_a_player_that_runs_for_the_audio_reads_played(tmp_path):
    wav = write_wav(tmp_path / "tone.wav", seconds=0.2)
    player = fake_player(tmp_path, "good.py", "import time; time.sleep(0.25)")
    result = probe_mod.probe(wav, player, timeout_s=10.0)
    assert result["verdict"] == "played"
    assert result["exit_code"] == 0
    assert result["stderr_lines"] == 0
    assert result["first_byte_ms"] != "-1"
    assert result["first_byte_hex"] == probe_mod.wav_facts(wav)["first_sample_hex"]


def test_negative_control_exit_zero_but_instant_is_not_playback(tmp_path):
    """The whole point: exit 0 must not be retyped as 'it played'."""
    wav = write_wav(tmp_path / "tone.wav", seconds=0.2)
    player = fake_player(tmp_path, "early.py", "raise SystemExit(0)")
    result = probe_mod.probe(wav, player, timeout_s=10.0)
    assert result["exit_code"] == 0
    assert result["verdict"] == "exit_zero_no_output"
    assert result["first_byte_ms"] == "-1"
    assert "exit 0" in result["why"]


def test_negative_control_nonzero_exit_carries_stderr_verbatim(tmp_path):
    wav = write_wav(tmp_path / "tone.wav")
    player = fake_player(
        tmp_path, "bad.py",
        "import sys; sys.stderr.write('Connection failure: Connection refused\\n"
        "second line\\n'); raise SystemExit(3)")
    result = probe_mod.probe(wav, player, timeout_s=10.0)
    assert result["verdict"] == "exited_nonzero"
    assert result["exit_code"] == 3
    assert result["stderr_lines"] == 2
    assert result["stderr_first"].startswith("Connection failure")
    assert result["stderr_empty"] == 0


def test_a_silent_wav_is_a_silent_file_whatever_the_player_reports(tmp_path):
    wav = tmp_path / "silent.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 3200)
    player = fake_player(tmp_path, "good.py", "import time; time.sleep(0.4)")
    result = probe_mod.probe(wav, player, timeout_s=10.0)
    assert result["verdict"] == "silent_file"
    assert result["exit_code"] == 0      # the player was happy; the file was not


def test_a_hung_player_times_out_instead_of_blocking_forever(tmp_path):
    wav = write_wav(tmp_path / "tone.wav")
    player = fake_player(tmp_path, "hang.py", "import time; time.sleep(30)")
    result = probe_mod.probe(wav, player, timeout_s=0.5)
    assert result["verdict"] == "timeout"
    assert result["timed_out"] == 1


def test_no_player_and_missing_file_are_named_not_guessed(tmp_path):
    wav = write_wav(tmp_path / "tone.wav")
    assert probe_mod.probe(wav, None)["verdict"] == "no_player"
    missing = probe_mod.probe(tmp_path / "absent.wav", [sys.executable])
    assert missing["verdict"] == "missing_file"


def test_dry_run_plays_nothing_and_still_reports_the_wav(tmp_path):
    wav = write_wav(tmp_path / "tone.wav", amplitude=8000)
    player = fake_player(tmp_path, "never.py", "raise SystemExit(99)")
    result = probe_mod.probe(wav, player, dry_run=True)
    assert result["verdict"] == "dry_run"
    assert result["executed"] == 0
    assert result["exit_code"] == "-1"
    assert result["peak"] == round(8000 / 32768, 4)


def test_the_self_test_controls_pass_end_to_end(tmp_path):
    results = probe_mod.self_test(tmp_path)
    assert len(results) == 4
    failing = [r for r in results if not r["pass"]]
    assert not failing, failing
    assert {r["verdict"] for r in results} == {
        "played", "exited_nonzero", "exit_zero_no_output", "silent_file"}


def test_the_cli_self_test_exits_zero_only_when_every_control_passes(capsys):
    assert probe_mod.main(["--self-test"]) == 0
    out = capsys.readouterr().out
    assert "controls_passed 4" in out
    assert "controls_total 4" in out


# ---------------------------------------------------------------------------
# player resolution mirrors the daemon
# ---------------------------------------------------------------------------
def test_resolve_player_order_matches_the_daemon():
    source = (REPO / "src" / "assistant" / "tts.py").read_text(encoding="utf-8")
    for candidate in probe_mod.DEFAULT_ORDER:
        assert f'"{candidate}"' in source, candidate
    assert 'if setting == "none"' in source
    # `none` is a real configuration and must resolve to no player at all.
    assert probe_mod.resolve_player("none") is None


def test_resolve_player_uses_a_configured_binary_and_reports_absence():
    assert probe_mod.resolve_player(f"{sys.executable} --extra") == [
        sys.executable, "--extra"]
    assert probe_mod.resolve_player("/definitely/not/a/player") is None


# ---------------------------------------------------------------------------
# telemetry: the "none played" distribution from the durable record
# ---------------------------------------------------------------------------
def _ack_db(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "assistant.db"
    store = Store(path)
    for row in rows:
        store.log_persona_event("2026-11-17T09:00:00+03:00", "ack", json.dumps(row))
    store.close()
    return path


def test_telemetry_counts_played_and_none_played(tmp_path):
    played = {"kind": "ack", "speech": {"played": True, "queued": True}}
    silent = {"kind": "ack", "speech": {"played": False, "queued": True,
                                        "cache_miss": True}}
    suppressed = {"kind": "ack", "speech": {"played": False, "queued": False,
                                            "speak_suppressed": "class mode"}}
    db = _ack_db(tmp_path, [played, silent, suppressed])
    rows, reason = probe_mod.read_ack_rows(db, limit=10)
    assert reason == "" and len(rows) == 3
    stats = probe_mod.ack_telemetry(rows)
    assert stats["acks"] == 3
    assert stats["played"] == 1
    assert stats["none_played"] == 2
    assert stats["cache_miss"] == 1
    assert stats["suppressed"] == 1


def test_an_ack_row_without_a_speech_block_is_counted_as_such(tmp_path):
    db = _ack_db(tmp_path, [{"kind": "ack"}])
    rows, _ = probe_mod.read_ack_rows(db, limit=10)
    stats = probe_mod.ack_telemetry(rows)
    assert stats["no_speech_field"] == 1
    assert stats["played"] == 0
    assert stats["none_played"] == 1


def test_zero_rows_states_what_it_fails_to_discriminate(tmp_path):
    db = _ack_db(tmp_path, [])
    rows, reason = probe_mod.read_ack_rows(db, limit=10)
    assert rows == [] and reason == ""
    stats = probe_mod.ack_telemetry(rows)
    text = probe_mod.render(None, stats, [])
    assert "telemetry.acks 0" in text
    assert "telemetry.fails_to_discriminate" in text
    assert "cannot tell apart" in text


def test_a_missing_database_is_reported_not_created(tmp_path):
    target = tmp_path / "absent.db"
    rows, reason = probe_mod.read_ack_rows(target, limit=5)
    assert rows == []
    assert "no database at" in reason
    assert not target.exists()


def test_telemetry_is_read_only(tmp_path):
    db = _ack_db(tmp_path, [{"kind": "ack", "speech": {"played": True}}])
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    probe_mod.read_ack_rows(db, limit=10)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


# ---------------------------------------------------------------------------
# cli surface + pin
# ---------------------------------------------------------------------------
def test_cli_probe_run_is_key_value_and_always_says_read_only(tmp_path, capsys):
    wav = write_wav(tmp_path / "tone.wav")
    db = _ack_db(tmp_path, [{"kind": "ack", "speech": {"played": False}}])
    fake_player(tmp_path, "early.py", "raise SystemExit(0)")
    code = probe_mod.main(["--wav", str(wav), "--db", str(db),
                           "--command", f"{sys.executable} {tmp_path / 'early.py'}"])
    out = capsys.readouterr().out
    assert code == 0
    lines = out.splitlines()
    assert "probe.verdict exit_zero_no_output" in lines
    assert "probe.exit_code 0" in lines
    assert "probe.stderr_empty 1" in lines
    assert "telemetry.none_played 1" in lines
    assert lines[-1] == "note read_only"
    for line in lines:
        assert " " in line


def test_cli_telemetry_only_short_circuits_the_player(tmp_path, capsys):
    db = _ack_db(tmp_path, [{"kind": "ack", "speech": {"played": True}}])
    assert probe_mod.main(["--telemetry-only", "--db", str(db)]) == 0
    out = capsys.readouterr().out
    assert "probe." not in out
    assert "telemetry.played 1" in out


def test_cli_help_and_bad_arguments_are_refused_without_tracebacks():
    assert probe_mod.main(["--help"]) == 2
    assert probe_mod.main(["--nonsense"]) == 2
    assert probe_mod.main(["--wav"]) == 2


def test_manifest_is_repo_relative_and_verifies_from_the_root():
    digest, name = MANIFEST.read_text().split()
    assert name == "scripts/player_probe.py"
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == digest, (
        "player_probe.py changed without regenerating its manifest — run "
        "`python3 scripts/player_probe.py --checksum`")
    verified = subprocess.run(
        ["sha256sum", "-c", "scripts/player_probe.py.sha256"],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_the_probe_changes_no_playback_behaviour():
    """Diagnose only: the probe must not import or patch the playback path."""
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("import assistant.tts", "from assistant.tts import",
                      "monkeypatch", "play_audio(", "_player_command("):
        assert forbidden not in source, forbidden
    for module in ("tts", "daemon", "capture"):
        assert probe_mod.__dict__.get(module) is None
