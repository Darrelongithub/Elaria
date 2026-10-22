"""Event transcriber — §0 Step 0 spike harness + decision table.

The spike is BLOCKING before queue tuning: one closed ~10-minute WAV pushed
through the transcribe-live route as a batch call, three numbers recorded,
one decision-table row applied. In mock mode (no key) the result is
ambiguous by construction and the table's default row applies.
"""

from __future__ import annotations

import json


def test_decision_row_1_live_under_12k():
    from assistant.event_spike import decide

    decision = decide({"live_ok": True, "full_transcript": True,
                       "tokens": 9_000, "tokens_measured": True})
    assert decision["row"] == 1
    assert decision["route"] == "transcribe-live"
    assert decision["segment_minutes"] == 10
    assert decision["switch_flush"] is True


def test_decision_row_2_live_but_tokens_high():
    from assistant.event_spike import decide

    decision = decide({"live_ok": True, "full_transcript": True,
                       "tokens": 18_000, "tokens_measured": True})
    assert decision["row"] == 2
    assert decision["route"] == "transcribe-live"
    assert decision["segment_minutes"] < 10          # shortened to fit 20K TPM
    assert decision["segment_minutes"] >= 1
    assert decision["switch_flush"] is True


def test_decision_row_3_live_cannot_batch_closed_wav():
    from assistant.event_spike import decide

    decision = decide({"live_ok": False, "full_transcript": False,
                       "tokens": None, "tokens_measured": False})
    assert decision["row"] == 3
    assert decision["route"] == "batch"
    assert decision["segment_minutes"] == 30
    assert decision["switch_flush"] is False


def test_decision_ambiguous_defaults_to_row_3():
    from assistant.event_spike import decide

    # estimated tokens are explicitly not the real figure → ambiguous
    decision = decide({"live_ok": True, "full_transcript": True,
                       "tokens": 8_000, "tokens_measured": False})
    assert decision["row"] == 3

    # missing tokens figure → ambiguous
    decision = decide({"live_ok": True, "full_transcript": True,
                       "tokens": None, "tokens_measured": True})
    assert decision["row"] == 3

    # no full transcript → ambiguous
    decision = decide({"live_ok": True, "full_transcript": False,
                       "tokens": 8_000, "tokens_measured": True})
    assert decision["row"] == 3


def test_synthesize_wav_produces_requested_duration(tmp_path):
    from assistant.event_spike import synthesize_wav

    path = tmp_path / "spike.wav"
    synthesize_wav(path, minutes=0.02)               # 1.2 seconds
    from assistant.capture import wav_duration_s

    duration = wav_duration_s(path)
    assert abs(duration - 1.2) < 0.05


def test_run_spike_mock_mode_records_ambiguous_row_3(config, tmp_path):
    from assistant.event_spike import run_spike, write_decision

    result = run_spike(config, minutes=0.02)
    assert result["mode"] == "mock"                  # no key: honest about it
    assert result["tokens_measured"] is False        # no real figure exists
    assert result["decision"]["row"] == 3            # ambiguous → proven engine
    assert result["latency_s"] >= 0
    assert result["duration_s"] > 0

    out = tmp_path / "event-spike.json"
    write_decision(result, out)
    saved = json.loads(out.read_text())
    assert saved["decision"]["row"] == 3
    assert saved["wav"].endswith(".wav")


def test_event_spike_cli_smoke(config, capsys, tmp_path):
    from assistant import cli

    out = tmp_path / "spike-out.json"
    rc = cli.main(["event", "spike", "--minutes", "0.02", "--out", str(out)])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "row" in captured.lower()
    assert out.exists()
    saved = json.loads(out.read_text())
    assert saved["decision"]["row"] in (1, 2, 3)
