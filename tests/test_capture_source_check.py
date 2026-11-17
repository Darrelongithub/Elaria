"""Capture-path source check (2026-11-15, D-B follow-up).

The 20261102 take's envelope never dips — peak pinned at full scale, rms in a
±0.07 band for all 9.93 s. Speech does not do that. Two candidate explanations,
in order: (a) gain so hot that even quiet passages saturate; (b) a steady loud
source in the capture path *beside* the voice (monitor/loopback of playback,
which the gateway's single-throat rule exists to prevent).

`scripts/capture_source_check.py` is the instrument for (b) and for the
gain packet's reversibility gate: which node capture would open, is it a
`.monitor`, are any monitor sources present, and what is that node's volume
percentage right now. Read-only, stdlib, no network, no credentials.

[TESTED-ONLY]: pactl is absent in this sandbox, so the parsers are pinned
against captured text and the live path is pinned to degrade honestly
(`available 0` + a reason), never to invent a reading.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "capture_source_check.py"
MANIFEST = REPO / "scripts" / "capture_source_check.py.sha256"

_spec = importlib.util.spec_from_file_location("capture_source_check", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

MIC1 = ("alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic."
        "HiFi__Mic1__source")
MONITOR = "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"

def _json_fixture() -> str:
    return json.dumps([
        {"name": MIC1,
         "volume": {"front-left": {"value_percent": "31%"},
                    "front-right": {"value_percent": "31%"}},
         "monitor_of_sink": None},
        {"name": MONITOR,
         "volume": {"front-left": {"value_percent": "100%"}},
         "monitor_of_sink": "alsa_output.pci-0000_00_1f.3.analog-stereo"},
    ])


TEXT_FIXTURE = f"""Source #54
\tState: RUNNING
\tName: {MIC1}
\tDescription: Built-in Audio
\tMonitor of Sink: n/a
\tVolume: front-left: 20316 /  31% / -30.60 dB,   front-right: 20316 /  31% / -30.60 dB

Source #61
\tState: IDLE
\tName: {MONITOR}
\tMonitor of Sink: alsa_output.pci-0000_00_1f.3.analog-stereo
\tVolume: front-left: 65536 / 100% / 0.00 dB
"""

INFO_FIXTURE = f"""Server Name: PulseAudio (on PipeWire 1.4.9)
Default Sink: alsa_output.pci-0000_00_1f.3.analog-stereo
Default Source: {MIC1}
"""


def _config(tmp_path: Path, node: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(f'[capture]\nmic_target = "{node}"\n', encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------
def test_json_sources_parse_names_volumes_and_monitor_flags():
    sources = check.parse_json_sources(_json_fixture())
    assert [src["name"] for src in sources] == [MIC1, MONITOR]
    assert sources[0]["volume_percent"] == 31.0
    # `monitor_of_sink: null` still means monitor: the name ends in `.monitor`.
    assert sources[0]["monitor"] is False
    assert sources[1]["monitor"] is True
    assert sources[1]["volume_percent"] == 100.0


def test_text_sources_parse_the_same_way_when_pactl_is_old():
    sources = check.parse_text_sources(TEXT_FIXTURE)
    assert [src["name"] for src in sources] == [MIC1, MONITOR]
    assert sources[0]["volume_percent"] == 31.0 and sources[0]["monitor"] is False
    assert sources[1]["volume_percent"] == 100.0 and sources[1]["monitor"] is True


def test_default_source_comes_from_pactl_info():
    assert check.parse_info_default(INFO_FIXTURE) == MIC1
    assert check.parse_info_default("no such line") == ""


def test_configured_node_reads_capture_mic_target_and_never_raises(tmp_path):
    assert check.configured_node_from(_config(tmp_path, MIC1)) == MIC1
    assert check.configured_node_from(tmp_path / "absent.toml") == ""
    broken = tmp_path / "broken.toml"
    broken.write_text("this is not toml {{{", encoding="utf-8")
    assert check.configured_node_from(broken) == ""


def test_resolution_order_is_override_then_config_then_default():
    assert check.resolve_node("override", "configured", "default") == "override"
    assert check.resolve_node("", "configured", "default") == "configured"
    assert check.resolve_node("", "", "default") == "default"


# ---------------------------------------------------------------------------
# the reading
# ---------------------------------------------------------------------------
def test_the_named_mic1_node_is_not_a_monitor_and_its_volume_is_recorded(tmp_path):
    result = check.report("pactl", _config(tmp_path, MIC1), "",
                          sources=check.parse_json_sources(_json_fixture()),
                          default=MIC1)
    assert result["node"] == MIC1
    assert result["node_found"] == 1
    assert result["node_is_mic1"] == 1
    assert result["node_is_monitor"] == 0          # answer to (b): not a loopback
    assert result["volume_percent"] == "31.0"      # the reversibility gate
    assert result["monitor_sources"] == 1          # one exists, on the sink
    assert result["monitor_names"] == [MONITOR]


def test_a_configured_monitor_node_is_named_as_one(tmp_path):
    """If capture were wired to a .monitor, (b) would be the answer, not (a)."""
    result = check.report("pactl", _config(tmp_path, MONITOR), "",
                          sources=check.parse_json_sources(_json_fixture()),
                          default=MIC1)
    assert result["node"] == MONITOR
    assert result["node_is_monitor"] == 1
    assert result["node_is_mic1"] == 0
    assert result["volume_percent"] == "100.0"


def test_an_unlisted_node_says_so_instead_of_inventing_a_volume(tmp_path):
    result = check.report("pactl", _config(tmp_path, "alsa_input.gone"), "",
                          sources=check.parse_json_sources(_json_fixture()),
                          default=MIC1)
    assert result["node_found"] == 0
    assert result["volume_percent"] == check.UNKNOWN
    assert "note node_not_listed_now" in check.render(result)


def test_render_is_key_value_only_and_says_read_only(tmp_path):
    result = check.report("pactl", _config(tmp_path, MIC1), "",
                          sources=check.parse_json_sources(_json_fixture()),
                          default=MIC1)
    lines = check.render(result).splitlines()
    assert lines[0] == "available 1"
    assert lines[-1] == "note read_only"
    for line in lines:
        assert " " in line
    assert any(line.startswith("monitor_source_0 ") for line in lines)


# ---------------------------------------------------------------------------
# the CLI: degrades honestly, replays captured text, is read-only
# ---------------------------------------------------------------------------
def test_missing_pactl_reports_unavailable_rather_than_a_number():
    out = subprocess.run([sys.executable, str(SCRIPT), "--pactl",
                          "/nonexistent/pactl-binary"],
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0
    assert out.stdout.splitlines()[0] == "available 0"
    assert out.stdout.splitlines()[1].startswith("reason ")
    assert "volume_percent" not in out.stdout


def test_replay_from_captured_files_prints_the_same_reading(tmp_path):
    (tmp_path / "sources.json").write_text(_json_fixture(), encoding="utf-8")
    (tmp_path / "info.txt").write_text(INFO_FIXTURE, encoding="utf-8")
    config = _config(tmp_path, MIC1)
    out = subprocess.run([sys.executable, str(SCRIPT),
                          "--config", str(config),
                          "--pactl-json", str(tmp_path / "sources.json"),
                          "--pactl-info", str(tmp_path / "info.txt")],
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    assert f"node {MIC1}" in out.stdout
    assert "volume_percent 31.0" in out.stdout
    assert "node_is_monitor 0" in out.stdout
    assert f"monitor_source_0 {MONITOR}" in out.stdout


def test_the_script_cannot_change_anything():
    """Read-only is the whole contract: no set/gain/mute verbs anywhere."""
    text = SCRIPT.read_text(encoding="utf-8").lower()
    for verb in ("set-source-volume", "set-sink-volume", "set-default",
                 "set-mute", "wpctl set-volume", "pactl set"):
        assert verb not in text, verb


def test_manifest_is_repo_relative_and_verifies_from_the_root(tmp_path):
    import hashlib

    digest, name = MANIFEST.read_text().split()
    assert name == "scripts/capture_source_check.py"
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == digest, (
        "capture_source_check.py changed without regenerating its manifest — "
        "run `python3 scripts/capture_source_check.py --checksum`")
    verified = subprocess.run(
        ["sha256sum", "-c", "scripts/capture_source_check.py.sha256"],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    assert verified.returncode == 0, verified.stdout + verified.stderr
