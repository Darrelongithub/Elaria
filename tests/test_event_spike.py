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
    assert "[LIVE]" in captured                       # labelled route
    # Synthesized-only run must NOT claim to have measured the batch route.
    assert "[BATCH]" not in captured
    assert "batch route" in captured                 # but tells the user how
    assert out.exists()
    saved = json.loads(out.read_text())
    assert saved["decision"]["row"] in (1, 2, 3)
    assert saved["route"] == "transcribe-live"       # the record is labelled


# ---------------------------------------------------------------------------
# Batch-route spike — the measurement the previous code never performed.
# ---------------------------------------------------------------------------
def test_run_batch_spike_uses_batch_model(config, tmp_path):
    from assistant.event_spike import run_batch_spike, synthesize_wav

    wav = synthesize_wav(tmp_path / "probe.wav", minutes=0.02)
    result = run_batch_spike(config, wav)
    # Batch route must use the dedicated transcribe-batch model — NOT the
    # transcribe-live model that the live spike uses.
    assert result["route"] == "batch"
    assert result["model"] == config.model_for_role("transcribe_batch")
    assert result["model"] != config.model_for_role("transcribe_live")
    assert result["accepted"] in (True, False)
    assert result["wav_size_mb"] > 0
    assert "call_math" in result
    # Size rejection must NOT be flagged for a tiny WAV that accepted.
    if result["accepted"]:
        assert result["size_rejection"] is False


def test_run_batch_spike_rejects_missing_wav(config, tmp_path):
    from assistant.event_spike import run_batch_spike

    missing = tmp_path / "nope.wav"
    try:
        run_batch_spike(config, missing)
    except FileNotFoundError as exc:
        assert str(missing) in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError for missing WAV")


def test_size_rejection_is_detected_and_restates_math():
    from assistant import event_spike as es

    # A 30-min WAV rejected for size must produce a halved suggestion
    # and a 10 h call-math record.
    math = es._restate_batch_math(30.0)
    assert math["calls_per_10h_event"] == 20        # 600/30
    assert math["fits_daily_budget"] is True         # 20 ≤ 25
    assert math["headroom_calls"] == 5

    math15 = es._restate_batch_math(15.0)
    assert math15["calls_per_10h_event"] == 40
    assert math15["fits_daily_budget"] is False      # 40 > 25

    assert es._largest_accepted_minutes(30) == 15
    assert es._largest_accepted_minutes(60) == 30

    assert es._looks_like_size_or_duration_error(
        "Request payload exceeds the maximum allowed size of 20 MB (file too large)")
    assert es._looks_like_size_or_duration_error(
        "audio exceeds maximum duration")
    assert es._looks_like_size_or_duration_error("413 Payload Too Large")
    assert not es._looks_like_size_or_duration_error(
        "Unauthorized: bad API key")
    assert not es._looks_like_size_or_duration_error("")


def test_run_both_labels_each_route(config, tmp_path):
    from assistant.event_spike import run_both, synthesize_wav

    wav = synthesize_wav(tmp_path / "probe.wav", minutes=0.02)
    result = run_both(config, wav_path=wav)
    assert "routes" in result
    assert "transcribe-live" in result["routes"]
    assert "batch" in result["routes"]
    live = result["routes"]["transcribe-live"]
    batch = result["routes"]["batch"]
    # Each record is explicitly labelled with its route.
    assert live["route"] == "transcribe-live"
    assert batch["route"] == "batch"
    assert live["model"] != batch["model"]            # different models!
    # Both ran against the exact same WAV.
    assert live["wav"] == batch["wav"] == str(wav)
    # Decision is present.
    assert result["decision"]["row"] in (1, 2, 3)


def test_cli_with_wav_reports_both_routes_labelled(config, capsys, tmp_path):
    from assistant import cli
    from assistant.event_spike import synthesize_wav

    wav = synthesize_wav(tmp_path / "probe.wav", minutes=0.02)
    out = tmp_path / "spike-out.json"
    rc = cli.main(["event", "spike", "--wav", str(wav), "--out", str(out)])
    captured = capsys.readouterr().out
    assert rc == 0
    # Both routes are reported and each line carries a tag.
    assert "[LIVE" in captured
    assert "[BATCH]" in captured
    assert out.exists()
    saved = json.loads(out.read_text())
    assert "routes" in saved
    assert saved["routes"]["transcribe-live"]["route"] == "transcribe-live"
    assert saved["routes"]["batch"]["route"] == "batch"
    # Different models — the old bug was that the "batch" confirmation was
    # actually the live model.
    assert (saved["routes"]["transcribe-live"]["model"]
            != saved["routes"]["batch"]["model"])


def test_batch_size_rejection_drops_segment_and_restates_math(config, tmp_path,
                                                              monkeypatch):
    """If the batch route rejects a 30-min WAV for size/duration, the spike
    must: (a) surface the error text verbatim, (b) suggest a shorter
    default segment length, (c) restate the 10 h call math."""
    import assistant.gemini_client as gc
    from assistant.event_spike import run_batch_spike, synthesize_wav

    class RejectingClient:
        def __init__(self, cfg, store):
            self._cfg = cfg
        def transcribe_batch(self, path, model=None, **kw):
            raise RuntimeError(
                "Request payload exceeds the maximum allowed size of 20 MB "
                "(file too large)")

    wav = synthesize_wav(tmp_path / "probe.wav", minutes=30.0)
    monkeypatch.setattr(gc, "GeminiClient", RejectingClient)

    # Run against a client that pretends the API rejected the WAV. We
    # bypass asr.transcribe_file's local-backend fallback to keep the
    # rejection surface clean.
    result = run_batch_spike(config, wav,
                             client=RejectingClient(config, None),
                             store=_NoopStore())
    assert result["accepted"] is False
    assert result["size_rejection"] is True
    assert result["error"] is not None
    assert "file too large" in result["error"].lower()
    # Suggestion must be shorter than the submitted WAV (halved).
    assert result["suggested_segment_minutes"] < result["minutes"]
    math = result["call_math"]
    assert math["segment_minutes"] == result["suggested_segment_minutes"]
    assert math["calls_per_10h_event"] > 0
    # 15 min is > 25/day, so a 30-min rejection must flag that the halved
    # length still needs verification (we can't bisect without real calls).
    assert "summary" in math


class _NoopStore:
    def recent_llm_calls(self, limit=1): return []
    def log_llm_call(self, **kw): pass
    def close(self): pass
