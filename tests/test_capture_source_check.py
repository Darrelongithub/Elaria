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

import pytest

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


def test_resolution_is_override_then_config_and_never_the_system_default():
    """F17: an unnamed node is a REFUSAL, not a fallback to the default source."""
    assert check.resolve_node("override", "configured") == ("override", "")
    assert check.resolve_node("", "configured") == ("configured", "")
    assert check.resolve_node("", "") == ("", "f17_no_node")


def test_the_gateway_and_this_probe_agree_that_an_unnamed_node_refuses():
    """The probe must mirror `audio_gateway.resolve_target`, not guess at it."""
    from assistant.audio_gateway import AudioGateway, GatewayRefused

    class _Cfg:
        def __init__(self, sections):
            self._sections = sections

        def section(self, name):
            return self._sections.get(name, {})

    gateway = AudioGateway(config=_Cfg({"capture": {"mic_target": ""}}))
    with pytest.raises(GatewayRefused) as refused:
        gateway.resolve_target()
    assert refused.value.refusal == "policy"
    # ...and the probe calls that state a refusal too, never a default source.
    assert check.resolve_node("", "")[1] == "f17_no_node"


# ---------------------------------------------------------------------------
# the reading
# ---------------------------------------------------------------------------
def test_without_a_configured_node_the_probe_reports_a_refusal(tmp_path):
    """`configured_node -1` must never be papered over with the default source.

    This is the 2026-11-17 Gate 1 defect: the first version fell back to the
    default and printed a node "capture would open", when F17 means capture
    would open NOTHING.
    """
    result = check.report("pactl", _config(tmp_path, ""), "",
                          sources=check.parse_json_sources(_json_fixture()),
                          default=MIC1)
    assert result["configured_node"] == check.UNKNOWN
    assert result["node"] == check.UNKNOWN
    assert result["capture_would_refuse"] == 1
    assert result["refusal"] == "f17_no_node"
    assert result["node_is_mic1"] == 0
    # The default source is still a fact about the machine — reported as one.
    assert result["default_source"] == MIC1
    assert result["default_volume_percent"] == "31.0"
    rendered = check.render(result)
    assert "capture_would_refuse 1" in rendered
    assert "refusal f17_no_node" in rendered


def test_config_path_and_found_are_reported_so_minus_one_is_readable(tmp_path):
    present = _config(tmp_path, MIC1)
    result = check.report("pactl", present, "",
                          sources=check.parse_json_sources(_json_fixture()),
                          default=MIC1)
    assert result["config_path"] == str(present)
    assert result["config_found"] == 1
    missing = check.report("pactl", tmp_path / "absent.toml", "",
                           sources=check.parse_json_sources(_json_fixture()),
                           default=MIC1)
    assert missing["config_found"] == 0
    assert missing["configured_node"] == check.UNKNOWN


def test_the_default_config_path_is_the_daemons_own(monkeypatch, tmp_path):
    monkeypatch.delenv("ASSIST_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert check.default_config_path() == (
        tmp_path / "xdg" / "assistant" / "config.toml")
    monkeypatch.setenv("ASSIST_CONFIG", str(tmp_path / "custom.toml"))
    assert check.default_config_path() == tmp_path / "custom.toml"


def test_pin_line_is_paste_exact_and_refuses_a_monitor(tmp_path):
    sources = check.parse_json_sources(_json_fixture())
    assert check.pin_line(MIC1, sources) == f'mic_target = "{MIC1}"'
    assert check.pin_line(MONITOR, sources) == check.UNKNOWN
    assert check.pin_line("", sources) == check.UNKNOWN


def test_pin_line_cli_prints_one_line_for_a_real_mic(tmp_path):
    (tmp_path / "sources.json").write_text(_json_fixture(), encoding="utf-8")
    out = subprocess.run([sys.executable, str(SCRIPT), "--pin-line",
                          "--node", MIC1,
                          "--pactl-json", str(tmp_path / "sources.json")],
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0
    assert out.stdout.strip() == f'mic_target = "{MIC1}"'
    monitor = subprocess.run([sys.executable, str(SCRIPT), "--pin-line",
                              "--node", MONITOR,
                              "--pactl-json", str(tmp_path / "sources.json")],
                             capture_output=True, text=True, timeout=60,
                             check=False)
    assert monitor.stdout.strip() == check.UNKNOWN


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


# ---------------------------------------------------------------------------
# the packet that uses this instrument (anti-drift pins on the operating doc)
# ---------------------------------------------------------------------------
PACKET = REPO / "docs" / "packets" / "2026-11-15-capture-gain-reduction.md"


def test_the_gain_packet_leads_with_its_reversibility_gate_and_its_acceptance():
    text = PACKET.read_text(encoding="utf-8")
    assert "Gate 1" in text and "volume_percent" in text
    assert "sha256sum -c scripts/frame_probe.py.sha256" in text
    assert "sha256sum -c scripts/capture_source_check.py.sha256" in text
    assert "scripts/capture_source_check.py --pin-line" in text      # Ask 13
    assert "after the next reboot" in text                           # Finding 1
    assert "--gain-check" in text
    for criterion in ("peak_steady", "rms_steady", "rms_variation",
                      "full_scale_share"):
        assert f"`{criterion}`" in text, criterion
    # The restored value is Gate 1's number, never a hard-coded one.
    assert "<gate1 volume>" in text
