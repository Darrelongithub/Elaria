"""assist-voice-test harness (§13.10): maths, privacy, report, thresholds."""

import json
import math

import pytest

from assistant.voicetest import (
    EnergyScorer,
    EventLog,
    LedIndicator,
    RingBuffer,
    Runner,
    ScoredEvent,
    SyntheticSource,
    build_report,
    centroid,
    corpus_check,
    cosine,
    enroll,
    load_voiceprint,
    mean_pairwise_cosine,
    purge_near_miss_clips,
    speaker_score,
    suggest_threshold,
)


def test_cosine_basics():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_consistency_of_identical_voice_is_one():
    vectors = [[1.0, 2.0, 3.0]] * 4
    assert mean_pairwise_cosine(vectors) == pytest.approx(1.0)


def test_centroid_is_unit_and_scores_high_against_members():
    members = [[1.0, 0.1], [0.9, 0.2], [1.1, 0.0]]
    centre = centroid(members)
    assert math.sqrt(sum(x * x for x in centre)) == pytest.approx(1.0)
    assert all(cosine(m, centre) > 0.99 for m in members)


def test_ring_buffer_discards_beyond_two_seconds():
    ring = RingBuffer(seconds=2.0, frame_ms=30)
    for i in range(200):  # 6s of audio pushed
        ring.push(bytes([i % 256]) * 4)
    assert len(ring) <= 67  # ~2s held — older audio is gone, continuously


def _runner(tmp_path):
    return Runner(
        keyword_scorer=EnergyScorer(),
        voiceprint=None,
        keyword_threshold=0.5,
        speaker_threshold=0.75,
        log=EventLog(tmp_path / "events.jsonl"),
        led=LedIndicator(tmp_path / "led.json"),
    )


def test_synthetic_run_logs_scores_only_and_lights_led(tmp_path):
    runner = _runner(tmp_path)
    source = SyntheticSource(keyword_events=[
        (0.92, 0.97),   # owner → accept + LED
        (0.88, 0.41),   # impostor → rejected-speaker
        (0.20, 0.99),   # normal speech → below threshold, NOT logged
    ])
    events = runner.run_synthetic(source)
    assert [e.decision for e in events] == ["accepted", "rejected-speaker"]
    logged = runner.log.read_all()
    assert set(logged[0]) == {"ts", "keyword_score", "speaker_score",
                              "latency_ms", "decision", "label"}  # no audio, ever
    led = json.loads((tmp_path / "led.json").read_text())
    assert led["class"] in ("voice-test-lit", "voice-test-idle")  # waybar shape
    assert not list(tmp_path.glob("*.wav"))  # ring buffer never hit disk


def test_one_key_labelling_and_report_rates(tmp_path):
    runner = _runner(tmp_path)
    runner.run_synthetic(SyntheticSource(keyword_events=[
        (0.92, 0.97), (0.90, 0.95), (0.93, 0.96)]))
    log = EventLog(tmp_path / "events.jsonl")
    assert log.label_last("correct")
    events = log.read_all()
    events[0]["label"] = "false-trigger"
    events[1]["label"] = "missed-me"
    (tmp_path / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    report = build_report(log.read_all(), window_hours=2.0)
    assert report["false_triggers"] == 1
    assert report["false_triggers_per_day"] == 12.0  # 1 in 2h
    assert report["deliberate_caught_pct"] == 50.0   # 1 correct of 1 correct + 1 missed
    assert report["targets"]["false_per_day"] == "<1"
    assert sum(b["count"] for b in report["keyword_score_distribution"]) == 3


def test_threshold_comes_from_the_gap_not_from_vibes():
    events = (
        [{"speaker_score": s, "label": "correct"} for s in (0.91, 0.94, 0.89)]
        + [{"speaker_score": s, "label": "false-trigger"} for s in (0.40, 0.55)])
    suggestion = suggest_threshold(events)
    assert 0.55 < suggestion["suggested"] <= 0.89
    assert suggestion["gap"] == pytest.approx(0.34)


def test_threshold_refuses_without_impostor_data():
    # 0.96 consistency alone cannot set a threshold (§13.10) — say so.
    events = [{"speaker_score": 0.97, "label": "correct"}]
    assert suggest_threshold(events)["suggested"] is None


def _write_sidecars(directory, vectors, seconds_each=3600.0):
    directory.mkdir(parents=True, exist_ok=True)
    for i, vector in enumerate(vectors):
        (directory / f"note{i}.embedding.json").write_text(
            json.dumps({"embedding": vector, "speech_seconds": seconds_each}))


def test_corpus_check_and_enroll_round_trip(tmp_path):
    sidecars = tmp_path / "emb"
    _write_sidecars(sidecars, [[1.0, 0.05], [0.98, 0.08], [1.02, 0.02]],
                    seconds_each=4680.0)  # 3 × 1.3h ≈ 3.9h negative corpus
    check = corpus_check(sidecars)
    assert check["mean_pairwise_cosine"] > 0.99
    assert check["negative_corpus_hours"] == pytest.approx(3.9, abs=0.05)
    summary = enroll(sidecars, tmp_path / "voiceprint.json", "ECAPA-TDNN (VoxCeleb2, 192-d)")
    assert summary["file_count"] == 3 and "centroid" not in summary  # never echoed
    voiceprint = load_voiceprint(tmp_path / "voiceprint.json")
    assert speaker_score([1.0, 0.05], voiceprint) > 0.99
    assert speaker_score([-1.0, 0.0], voiceprint) < 0.0  # impostor direction


def test_voiceprint_shape_is_validated(tmp_path):
    bad = tmp_path / "vp.json"
    bad.write_text(json.dumps({"model": "x", "dimension": 3, "centroid": [1.0, 2.0]}))
    with pytest.raises(ValueError):
        load_voiceprint(bad)


def test_near_miss_clips_purge_after_24h(tmp_path):
    clips = tmp_path / "near-miss"
    clips.mkdir()
    old, new = clips / "old.wav", clips / "new.wav"
    old.write_bytes(b"x")
    new.write_bytes(b"x")
    import os
    import time
    past = time.time() - 25 * 3600
    os.utime(old, (past, past))
    assert purge_near_miss_clips(clips) == 1
    assert new.exists() and not old.exists()


def test_event_shape_matches_spec():
    event = ScoredEvent(ts="2026-10-18T00:00:00", keyword_score=0.9,
                        speaker_score=0.96, latency_ms=42.0, decision="accepted")
    payload = json.loads(json.dumps(event.__dict__))
    assert payload["speaker_score"] == 0.96  # §13.10: {time, keyword_score, speaker_score, latency_ms}
