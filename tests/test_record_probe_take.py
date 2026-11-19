"""The production-path take recorder (2026-11-17 Gate 3 failure).

The gain packet told the owner to produce a take with
`pw-record --target <node> … /tmp/gain-18.wav`. It exited 0 and wrote 5.95 s of
rms 0.0003 — digital silence — while, in the same sitting at the same 18 %, the
assistant's own capture transcribed the same microphone verbatim. A silent take
nearly became "18 % is too quiet".

So the recorder delegates its argv to `capture.pw_record_pcm_stream_command`,
the function production actually uses, and writes its stdout into a WAV. These
pins prove that delegation (not a re-spelling), that the failed line is still
reproducible for `--compare`, and that silence fails closed with its own
message and exit code.
"""

from __future__ import annotations

import importlib.util
import math
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "record_probe_take.py"
MANIFEST = REPO / "scripts" / "record_probe_take.py.sha256"
PROBE = REPO / "scripts" / "frame_probe.py"

_spec = importlib.util.spec_from_file_location("record_probe_take", SCRIPT)
rec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rec)

_spec2 = importlib.util.spec_from_file_location("frame_probe_for_take", PROBE)
probe = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(probe)

MIC1 = ("alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic."
        "HiFi__Mic1__source")


def _sine(seconds: float, amplitude: float, rate: int = 16000) -> bytes:
    import struct

    count = int(rate * seconds)
    samples = [int(amplitude * 32767 * math.sin(2 * math.pi * 220 * i / rate))
               for i in range(count)]
    return struct.pack(f"<{len(samples)}h", *samples)


# ---------------------------------------------------------------------------
# verified by construction: the recorder cannot have its own dialect
# ---------------------------------------------------------------------------
def test_the_recorder_uses_productions_own_argv():
    assert rec.production_command(MIC1, 16000) == rec.prod.pw_record_pcm_stream_command(
        MIC1, sample_rate=16000)
    # The production shape: --target=NAME, raw s16 to stdout.
    assert rec.production_command(MIC1, 16000) == [
        "pw-record", f"--target={MIC1}", "--rate", "16000", "--channels", "1",
        "--format", "s16", "-"]


def test_the_failed_packet_line_is_still_reproducible_for_compare(tmp_path):
    """Not what we use — what we measure against. The two differences are the
    whole reason `--compare` exists."""
    legacy = rec.legacy_command(MIC1, tmp_path / "gain-18.wav", 16000)
    assert legacy == ["pw-record", "--target", MIC1, "--rate", "16000",
                      "--channels", "1", "--format", "s16",
                      str(tmp_path / "gain-18.wav")]
    production = rec.production_command(MIC1, 16000)
    assert f"--target={MIC1}" in production          # one token, `=`
    assert MIC1 not in production                    # ...and never a bare token
    assert production[-1] == "-"                     # stdout, not a file path


def test_a_numeric_object_id_is_refused_by_productions_own_guard():
    with pytest.raises(ValueError):
        rec.production_command("54", 16000)


def test_an_unnamed_node_is_an_f17_refusal_never_the_default():
    class _Cfg:
        def section(self, _name):
            return {}

    assert rec.resolve_target(_Cfg()) == ("", "f17_no_node")

    class _Named:
        def section(self, name):
            return {"mic_target": MIC1} if name == "meeting" else {}

    assert rec.resolve_target(_Named()) == (MIC1, "")


# ---------------------------------------------------------------------------
# the take it writes is what the probe reads
# ---------------------------------------------------------------------------
def test_describe_separates_a_voice_from_silence():
    voice = rec.describe(_sine(0.5, 0.25), 16000)
    assert voice["peak"] == pytest.approx(0.25, abs=0.01)
    assert voice["silent"] == 0
    silence = rec.describe(b"\x00\x00" * 16000, 16000)
    assert silence["silent"] == 1
    assert silence["peak"] == 0.0


def test_the_written_take_round_trips_through_the_frame_probe(tmp_path):
    path = rec.write_wav(tmp_path / "take.wav", _sine(0.5, 0.25), 16000)
    result = probe.analyse(path)
    assert result["sample_rate"] == 16000
    assert result["channels"] == 1
    assert result["verdict"] == "clean"
    assert result["rms_steady"] > 0.15


def test_a_silent_take_is_no_signal_and_never_a_partial_pass(tmp_path):
    path = rec.write_wav(tmp_path / "silent.wav", b"\x00\x00" * 16000 * 5, 16000)
    result = probe.analyse(path)
    assert result["verdict"] == "no_signal"
    rendered = probe.render_acceptance(result)
    assert "gain_accept no_signal" in rendered
    assert "note silent_take_is_not_a_gain_reading" in rendered
    assert "ACCEPT " not in rendered          # no criterion can read as a pass


# ---------------------------------------------------------------------------
# the CLI fails closed
# ---------------------------------------------------------------------------
def test_silence_exits_three_with_its_own_message(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(rec.prod, "tool_available", lambda _name: True)
    monkeypatch.setattr(rec, "record", lambda _cmd, _seconds: b"\x00\x00" * 32000)
    code = rec.main([str(tmp_path / "silent.wav"), "--target", MIC1])
    out = capsys.readouterr().out
    assert code == 3
    assert "silent 1" in out
    assert "note silent_take_is_not_a_gain_reading" in out


def test_no_target_exits_two_with_the_refusal(monkeypatch, capsys, tmp_path):
    from assistant import config as config_module

    class _Cfg:
        def section(self, _name):
            return {}

    monkeypatch.setattr(rec.prod, "tool_available", lambda _name: True)
    monkeypatch.setattr(config_module, "load_config", lambda: _Cfg())
    code = rec.main([str(tmp_path / "x.wav")])
    out = capsys.readouterr().out
    assert code == 2
    assert "refusal f17_no_node" in out


def test_manifest_is_repo_relative_and_verifies_from_the_root():
    import hashlib

    digest, name = MANIFEST.read_text().split()
    assert name == "scripts/record_probe_take.py"
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == digest, (
        "record_probe_take.py changed without regenerating its manifest — run "
        "`python3 scripts/record_probe_take.py --checksum`")
    verified = subprocess.run(
        ["sha256sum", "-c", "scripts/record_probe_take.py.sha256"],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    assert verified.returncode == 0, verified.stdout + verified.stderr
