"""Frame-level packet + peak split + start-transient gate (2026-11-15).

The owner's mute test (verbatim numbers): with the PipeWire node muted, doctor
reported **rms 0.007** and **peak 0.9981**. Speech gone, mute works, volume is
in the probe path — but a full-scale sample survives mute. So the historic
peak-1.0 readings include a transient injected at or after stream open
(start-pop / DSP power-up click), and any diagnosis anchored on `peak` was
anchored on that click.

Three things are pinned here:

1. **The packet** (`scripts/frame_probe.py`) — sandbox-verified against three
   synthetic takes: a clean sine, a sine with an added start-pop, and a
   sustained clip. **The owner's three takes answered on 2026-11-15: all three
   `mixed`, `full_scale_after_start` 127/158/197 — D-B confirmed** (sustained
   voice clipping, current config). The packet now also carries the
   gain-reduction acceptance test (`--gain-check`), which accepts on SHAPE:
   a lower peak with a flat envelope is a quieter rail, not a repaired voice.
2. **The split** — `peak_full` and `peak_steady`, so no future diagnosis
   anchors on a pop, in both doctor's live probe and a session's capture stats.
3. **The transient gate** — a full-scale frame inside the hold-off is recorded
   but never uploaded, and can never be the first speech frame; a speech-level
   frame inside the hold-off is kept (a hold-off that costs a syllable is worse
   than the pop). It is **hygiene, not the clipping fix**: D-B says the voice
   itself is at full scale, and a hold-off would have trimmed one 50 ms frame
   and left 7.5-10 s of clipped audio in place.

[TESTED-ONLY]: synthetic fixtures. The owner's takes are the measurement.
"""

from __future__ import annotations

import math
import struct
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from assistant.capture import (
    SAMPLE_RATE,
    StartTransientGate,
    split_peak,
)

REPO = Path(__file__).resolve().parents[1]
PACKET = REPO / "scripts" / "frame_probe.py"
MANIFEST = REPO / "scripts" / "frame_probe.py.sha256"
FRAME_SAMPLES = SAMPLE_RATE * 50 // 1000      # one 50 ms frame at 16 kHz


# ---------------------------------------------------------------------------
# synthetic takes (the three shapes the owner's wavs can turn out to be)
# ---------------------------------------------------------------------------
def _sine(seconds: float, amplitude: float, freq: float = 220.0) -> list[int]:
    count = int(SAMPLE_RATE * seconds)
    return [int(amplitude * 32767 * math.sin(2 * math.pi * freq * i / SAMPLE_RATE))
            for i in range(count)]


def _write(tmp_path: Path, name: str, samples: list[int]) -> Path:
    path = tmp_path / name
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def _clean(tmp_path) -> Path:
    """A human at a sane level: no sample anywhere near full scale."""
    return _write(tmp_path, "clean.wav", _sine(0.30, 0.25))


def _pop(tmp_path) -> Path:
    """The mute test's shape: one full-scale burst at stream open, then voice."""
    samples = [32767 if i % 2 == 0 else -32768 for i in range(48)]   # ~3 ms
    samples += _sine(0.30, 0.25)
    return _write(tmp_path, "pop.wav", samples)


def _clipped(tmp_path) -> Path:
    """The old narrative's shape: the voice itself at full scale, take-long."""
    samples = _sine(0.20, 0.25)          # a quiet lead-in, no start pop
    samples += _sine(0.40, 0.999)
    return _write(tmp_path, "clipped.wav", samples)


def _speechlike(tmp_path) -> Path:
    """A voice at a sane level: loud-ish, and the envelope MOVES."""
    amplitudes = (0.22, 0.45, 0.28, 0.50, 0.24, 0.40)   # per 100 ms block
    samples: list[int] = []
    for amplitude in amplitudes:
        samples += _sine(0.10, amplitude)
    return _write(tmp_path, "speech.wav", samples)


def _rail(tmp_path) -> Path:
    """The 20261102 shape: peak pinned at full scale, envelope never moves.

    A 1-in-3 duty pulse train is a caricature, but the readings it produces are
    the file's: peak 1.0000 every frame, rms ~0.577 every frame, no variation.
    """
    samples = [32767 if index % 3 == 0 else 0
               for index in range(int(SAMPLE_RATE * 0.60))]
    return _write(tmp_path, "rail.wav", samples)


def _run_gain(path: Path) -> tuple[dict, dict]:
    out = subprocess.run([sys.executable, str(PACKET), str(path), "--gain-check"],
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    summary: dict = {}
    accept: dict = {}
    for line in out.stdout.splitlines():
        if line.startswith("ACCEPT "):
            _, criterion, value, verdict = line.split()
            accept[criterion] = {"value": float(value), "verdict": verdict}
        elif line.startswith("gain_accept "):
            accept["overall"] = line.split()[1]
        elif line.startswith("FRAME "):
            continue
        elif line.strip():
            key, _, value = line.partition(" ")
            summary[key] = value
    return summary, accept


def _run_packet(path: Path) -> dict:
    out = subprocess.run([sys.executable, str(PACKET), str(path)],
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    summary: dict = {}
    frames: list = []
    for line in out.stdout.splitlines():
        if line.startswith("FRAME "):
            _, index, start_ms, peak, rms = line.split()
            if not start_ms.isdigit():
                continue                      # the table's own header row
            frames.append({"index": int(index), "start_ms": int(start_ms),
                           "peak": float(peak), "rms": float(rms)})
        elif line.strip():
            key, _, value = line.partition(" ")
            summary[key] = value
    summary["frames_table"] = frames
    return summary


# ---------------------------------------------------------------------------
# 1. the packet: numbers-only, and the numbers decide D-A vs D-B
# ---------------------------------------------------------------------------
def test_packet_is_a_committed_single_line_runner_with_a_matching_checksum():
    assert PACKET.exists() and MANIFEST.exists()
    digest, name = MANIFEST.read_text().split()
    # Repo-relative, so `sha256sum -c` works from the root like every other pin.
    assert name == "scripts/frame_probe.py"
    import hashlib

    assert hashlib.sha256(PACKET.read_bytes()).hexdigest() == digest, (
        "frame_probe.py changed without regenerating its manifest — run "
        "`python3 scripts/frame_probe.py --checksum`")
    assert PACKET.read_text().startswith("#!/usr/bin/env python3")
    # And it actually verifies from the root, which the bare name never did.
    check = subprocess.run(["sha256sum", "-c", "scripts/frame_probe.py.sha256"],
                           cwd=REPO, capture_output=True, text=True,
                           timeout=60, check=False)
    assert check.returncode == 0, check.stdout + check.stderr


def test_packet_output_is_numbers_only_and_has_one_row_per_frame(tmp_path):
    out = subprocess.run([sys.executable, str(PACKET), str(_clean(tmp_path))],
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0
    lines = [line for line in out.stdout.splitlines() if line.strip()]
    for line in lines:
        key = line.split()[0]
        assert key.islower() or key == "FRAME", f"prose leaked into the output: {line!r}"
        if key != "FRAME":
            # every summary value is a number, except the file name and verdict
            value = line.split(" ", 1)[1]
            assert (value.replace(".", "", 1).lstrip("-").isdigit()
                    or key in ("verdict", "file")), f"non-numeric value: {line!r}"
    summary = _run_packet(_clean(tmp_path))
    assert len(summary["frames_table"]) == int(summary["frames"])


def test_packet_says_clean_on_a_clean_sine(tmp_path):
    summary = _run_packet(_clean(tmp_path))
    assert summary["verdict"] == "clean"
    assert summary["full_scale_frames"] == "0"
    assert summary["first_full_scale_ms"] == "-1", "no full-scale sample: -1"
    assert summary["peak_full"] == summary["peak_steady"] == "0.2500"
    assert summary["recommended_start_pop_ms"] == "0"


def test_packet_says_pop_at_start_for_a_start_transient(tmp_path):
    summary = _run_packet(_pop(tmp_path))
    assert summary["verdict"] == "pop_at_start"          # D-A
    assert summary["first_full_scale_ms"] == "0"
    assert summary["last_full_scale_ms"] == "0"
    assert summary["full_scale_after_start"] == "0", (
        "the pop must not be counted as steady-state full scale")
    assert float(summary["peak_full"]) >= 0.999
    assert float(summary["peak_steady"]) <= 0.26, (
        "the steady reading exists to ignore the pop")
    assert summary["recommended_start_pop_ms"] == "50"


def test_packet_says_steady_clip_when_the_voice_is_at_full_scale(tmp_path):
    summary = _run_packet(_clipped(tmp_path))
    assert summary["verdict"] == "steady_clip"           # D-B
    assert int(summary["full_scale_after_start"]) > 3
    assert int(summary["first_full_scale_ms"]) >= 100, (
        "no start pop: the full-scale samples begin with the voice")
    assert float(summary["peak_steady"]) >= 0.99


def test_packet_reports_mixed_when_both_shapes_are_present(tmp_path):
    samples = [32767 if i % 2 == 0 else -32768 for i in range(48)]
    samples += _sine(0.30, 0.999)
    summary = _run_packet(_write(tmp_path, "mixed.wav", samples))
    assert summary["verdict"] == "mixed"
    assert int(summary["full_scale_after_start"]) > 0


# ---------------------------------------------------------------------------
# 2. the split: peak_full vs peak_steady, in both readings
# ---------------------------------------------------------------------------
def test_split_peak_keeps_full_and_ignores_the_holdoff():
    pop_frame = struct.pack(f"<{FRAME_SAMPLES}h", *([32767] * FRAME_SAMPLES))
    voice = struct.pack(f"<{FRAME_SAMPLES}h", *([8192] * FRAME_SAMPLES))
    # 100 ms hold-off = two frames, so the steady span needs a third.
    pcm = pop_frame + voice + voice + voice
    split = split_peak(pcm, SAMPLE_RATE, 100)
    assert split["peak_full"] == pytest.approx(1.0, abs=1e-4)
    assert split["peak_steady"] == pytest.approx(0.25, abs=1e-3)
    assert split["start_pop_ms"] == 100
    # Nothing is hidden: with a zero hold-off both readings agree.
    assert split_peak(pcm, SAMPLE_RATE, 0)["peak_steady"] == pytest.approx(1.0, abs=1e-4)


def test_doctor_probe_reports_both_peaks(monkeypatch):
    from assistant import capture as capture_mod

    pop_frame = struct.pack(f"<{FRAME_SAMPLES}h", *([32767] * FRAME_SAMPLES))
    voice = struct.pack(f"<{FRAME_SAMPLES}h", *([8192] * FRAME_SAMPLES))
    data = pop_frame + voice + voice + voice

    import subprocess as sp

    def runner(argv, capture_output=True, timeout=10):
        return sp.CompletedProcess(argv, -15, stdout=data, stderr=b"")

    monkeypatch.setattr(capture_mod, "tool_available", lambda _t: True)
    level = capture_mod.live_level_check("test-mic", seconds=0.1, runner=runner)
    assert level["available"] is True
    assert level["peak_full"] == pytest.approx(1.0, abs=1e-4)
    assert level["peak_steady"] == pytest.approx(0.25, abs=1e-3)
    assert level["start_pop_ms"] == 100
    assert level["peak"] == level["peak_full"], "the old reading stays addressable"


def test_config_declares_the_holdoff_and_the_template_documents_it():
    from assistant.config import DEFAULTS, load_config

    assert DEFAULTS["capture"]["start_pop_ms"] == 100
    example = (REPO / "config.toml.example").read_text()
    assert "start_pop_ms" in example
    assert "frame_probe.py" in example, "the derivation must be discoverable"
    assert load_config().section("capture").get("start_pop_ms") == 100


# ---------------------------------------------------------------------------
# 3. the transient gate: recorded, not uploaded; never "first speech"
# ---------------------------------------------------------------------------
def test_gate_calls_a_full_scale_holdoff_frame_a_transient():
    gate = StartTransientGate(holdoff_ms=100)
    loud = struct.pack(f"<{FRAME_SAMPLES}h", *([32767] * FRAME_SAMPLES))
    assert gate.classify(loud, 0.0)["transient"] is True
    assert gate.classify(loud, 50.0)["transient"] is True
    # After the hold-off the very same frame is the owner, not transport.
    assert gate.classify(loud, 150.0)["transient"] is False
    assert gate.stats()["transients"] == 2


def test_gate_never_swallows_speech_inside_the_holdoff():
    gate = StartTransientGate(holdoff_ms=100)
    speech = struct.pack(f"<{FRAME_SAMPLES}h", *([6000] * FRAME_SAMPLES))
    view = gate.classify(speech, 20.0)
    assert view["in_holdoff"] is True
    assert view["transient"] is False, (
        "a hot-but-real first syllable must still reach the uplink")
    assert gate.stats()["transients"] == 0


def test_the_holdoff_comes_from_config_and_zero_disables_it(config):
    from assistant.transcribe import DictationService

    service = DictationService(config, None, None)
    assert service.start_pop_ms == 100
    config.raw.setdefault("capture", {})["start_pop_ms"] = 0
    assert DictationService(config, None, None).start_pop_ms == 0
    # 0 means "no start transient exists" — the same frame is then speech.
    gate = StartTransientGate(holdoff_ms=0)
    loud = struct.pack(f"<{FRAME_SAMPLES}h", *([32767] * FRAME_SAMPLES))
    assert gate.classify(loud, 0.0)["transient"] is False


def test_doctor_prints_both_peaks_for_the_live_probe(monkeypatch):
    """The doctor line must never show a bare peak again."""
    from assistant import cli as cli_mod

    level = {"available": True, "target": "test-mic", "bytes": 38400,
             "seconds": 1.2, "peak": 0.9981, "peak_full": 0.9981,
             "peak_steady": 0.007, "start_pop_ms": 100, "rms": 0.007,
             "signal": True, "detail": ""}
    monkeypatch.setattr("assistant.capture.live_level_check",
                        lambda *a, **k: level)
    config = cli_mod.load_config()
    config.raw.setdefault("capture", {})["mic_target"] = "test-mic"
    report = cli_mod.run_doctor(config)
    mic = next(c for c in report["checks"] if c["check"] == "mic level")
    assert "peak full 0.9981" in mic["detail"]
    assert "peak steady 0.007" in mic["detail"]
    assert "first 100 ms excluded" in mic["detail"]


def test_session_stats_carry_the_split_and_the_transient_count(
        config, running_daemon, monkeypatch, journal_stream):
    """One real session through the daemon: both peaks, the count, the hold-off."""
    from assistant.ipc import call

    _daemon, _server = running_daemon
    pop = struct.pack(f"<{FRAME_SAMPLES // 5}h", *([32767] * (FRAME_SAMPLES // 5)))

    class PopThenSilence:
        target = "test-mic"
        stalled = False

        def __init__(self, *args, **kwargs):
            pass

        async def frames(self):
            yield pop                       # the start transient (~10 ms)
            for _ in range(6):
                yield b"\x00\x00" * FRAME_SAMPLES

        async def aclose(self):
            pass

    monkeypatch.setattr("assistant.daemon.PipeWireCapture", PopThenSilence)
    monkeypatch.setattr("assistant.asr.make_live_transport", lambda config: None)
    monkeypatch.setattr("assistant.asr.transcribe_file", lambda *a, **k: None)

    call(config.socket_path, "ptt.start", {}, timeout=5.0)
    import time as _time

    _time.sleep(0.4)          # burst source: let the pop and the silence land
    stopped = call(config.socket_path, "ptt.stop", {"wait_s": 20.0}, timeout=25.0)
    capture = (stopped.get("result") or {}).get("capture") or {}

    assert capture.get("peak_full", 0) >= 0.99, "the pop is reported, not hidden"
    assert capture.get("peak_steady", 1.0) < 0.05, "the steady reading ignores it"
    assert capture.get("start_pop_ms") == 100
    assert capture.get("start_transient", {}).get("transients") == 1
    assert capture.get("no_speech") is True, (
        "a take that is only a pop is SILENCE — the pop must not read as speech")
    assert capture.get("first_speech_frame_s") is None

    levels = [line for line in journal_stream.getvalue().splitlines()
              if "capture.levels" in line]
    assert levels, "capture.levels must be journalled"
    detail = levels[-1]
    assert "peak_full=" in detail and "peak_steady=" in detail
    assert "start_pop_ms=100" in detail
    assert "start_transients=" in detail


# ---------------------------------------------------------------------------
# 5. gain-reduction acceptance: shape, not a smaller number (D-B ruling)
# ---------------------------------------------------------------------------
def test_gain_check_accepts_a_speech_shaped_take(tmp_path):
    summary, accept = _run_gain(_speechlike(tmp_path))
    assert 0.15 <= float(summary["rms_steady"]) <= 0.30
    assert float(summary["peak_steady"]) < 1.0
    for criterion in ("peak_steady", "rms_steady", "rms_variation",
                      "full_scale_share"):
        assert accept[criterion]["verdict"] == "pass", (criterion, accept)
    assert accept["overall"] == "pass"


def test_gain_check_rejects_a_flat_rail_even_with_a_lower_number(tmp_path):
    """20261102's shape: nothing dips, nothing varies, the peak never leaves 1.0."""
    summary, accept = _run_gain(_rail(tmp_path))
    assert summary["peak_steady"] == "1.0000"
    assert accept["peak_steady"]["verdict"] == "fail"
    assert accept["rms_steady"]["verdict"] == "fail"        # 0.577 > 0.30
    assert accept["rms_variation"]["verdict"] == "fail"      # a rail does not vary
    assert accept["overall"] == "fail"


def test_gain_check_rejects_a_steady_tone_with_good_levels(tmp_path):
    """Levels can be perfect and the take still not be speech: no variation."""
    _summary, accept = _run_gain(_clean(tmp_path))
    assert accept["peak_steady"]["verdict"] == "pass"
    assert accept["rms_steady"]["verdict"] == "pass"
    assert accept["rms_variation"]["verdict"] == "fail"
    assert accept["overall"] == "fail"


def test_gain_check_is_opt_in_and_absent_from_the_plain_run(tmp_path):
    plain = subprocess.run([sys.executable, str(PACKET), str(_clean(tmp_path))],
                           capture_output=True, text=True, timeout=60, check=False)
    assert "ACCEPT " not in plain.stdout
    assert "gain_accept" not in plain.stdout


def test_gain_acceptance_thresholds_are_the_rulings_and_one_guard():
    import importlib.util

    spec = importlib.util.spec_from_file_location("frame_probe_pins", PACKET)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.ACCEPT_RMS_MIN, module.ACCEPT_RMS_MAX) == (0.15, 0.30)
    assert module.ACCEPT_VARIATION_MIN == 0.25
    # Not in the ruling: peak_steady < 1.0 alone would pass a take peaking at
    # 0.995 everywhere. The guard is disclosed in the script and here.
    assert module.ACCEPT_FULL_SCALE_SHARE_MAX == 0.05
