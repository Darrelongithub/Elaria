"""Capture source check — the node capture would open, and the F17 refusal.

Decision 3 (CONTINUE→A/F) keeps the source check with this cluster; decision 4
keeps the F17 refusal in the probe. Those pull in opposite directions on the
current base tree, and the resolution is a printed flag rather than a quiet
assumption:

* `--policy as-built` says what THIS tree's daemon does. `daemon._ptt_start`
  resolves `mic_target` and falls back to the PipeWire default, so the honest
  reading is `fallback_to_default 1`.
* `--policy f17` says what the owner's ruling does: no default fallback,
  `refusal f17_no_node`.

A probe that asserted F17 while the checked-out code still falls back would be a
lie with a straight face. Both readings are pinned here, and
`f17_refusal_implemented` reports which one the probe believes it is standing in.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "capture_source_check.py"
MANIFEST = REPO / "scripts" / "capture_source_check.py.sha256"

_spec = importlib.util.spec_from_file_location("capture_source_check", SCRIPT)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

MIC1 = "alsa_input.pci-0000_00_1f.3.HiFi__Mic1__source"
MONITOR = "alsa_output.pci-0000_00_1f.3.HiFi__Speaker__sink.monitor"

PACTL_JSON = json.dumps([
    {"name": MIC1,
     "volume": {"front-left": {"value_percent": "100%"},
                "front-right": {"value_percent": "100%"}},
     "monitor_of_sink": None},
    {"name": MONITOR,
     "volume": {"mono": {"value_percent": "72%"}},
     "monitor_of_sink": "alsa_output.pci-0000_00_1f.3.HiFi__Speaker__sink"},
])

PACTL_TEXT = """Source #41
\tState: SUSPENDED
\tName: alsa_input.pci-0000_00_1f.3.HiFi__Mic1__source
\tMonitor of Sink: n/a
\tVolume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB

Source #52
\tName: alsa_output.pci-0000_00_1f.3.HiFi__Speaker__sink.monitor
\tMonitor of Sink: alsa_output.pci-0000_00_1f.3.HiFi__Speaker__sink
\tVolume: mono: 47186 /  72% / -8.52 dB
"""

PACTL_INFO = """Server Name: PulseAudio (on PipeWire 1.2.7)
Default Sink: alsa_output.pci-0000_00_1f.3.HiFi__Speaker__sink
Default Source: alsa_output.pci-0000_00_1f.3.HiFi__Speaker__sink.monitor
"""


# ---------------------------------------------------------------------------
# parsing controls
# ---------------------------------------------------------------------------
def test_json_sources_parse_names_volumes_and_monitor_state():
    sources = check.parse_json_sources(PACTL_JSON)
    assert [s["name"] for s in sources] == [MIC1, MONITOR]
    assert sources[0]["volume_percent"] == 100.0
    assert sources[0]["monitor"] is False        # a real Mic1 input
    assert sources[1]["volume_percent"] == 72.0
    assert sources[1]["monitor"] is True         # a loopback


def test_text_sources_agree_with_json_on_the_same_machine():
    """Both pactl shapes must produce the same facts, or one is lying."""
    json_rows = check.parse_json_sources(PACTL_JSON)
    text_rows = check.parse_text_sources(PACTL_TEXT)
    assert [(r["name"], r["volume_percent"], r["monitor"]) for r in json_rows] == \
           [(r["name"], r["volume_percent"], r["monitor"]) for r in text_rows]


def test_garbage_in_parses_to_nothing_rather_than_a_guess():
    assert check.parse_json_sources("not json at all") == []
    assert check.parse_json_sources('{"name": "one object"}') == []
    assert check.parse_json_sources("[]") == []
    assert check.parse_text_sources("") == []
    assert check.parse_info_default("no default here") == ""
    assert check.parse_info_default(PACTL_INFO) == \
        "alsa_output.pci-0000_00_1f.3.HiFi__Speaker__sink.monitor"


# ---------------------------------------------------------------------------
# policy: both readings, side by side
# ---------------------------------------------------------------------------
def test_as_built_reports_the_default_fallback_this_tree_really_has():
    result = check.report("pactl", None, "", sources=check.parse_json_sources(PACTL_JSON),
                          default=MONITOR, policy="as-built")
    assert result["node"] == "-1"                  # nothing named
    assert result["fallback_to_default"] == 1
    assert result["capture_would_refuse"] == 0     # it would capture *something*
    assert result["effective_node"] == MONITOR     # ...and names it
    assert result["f17_refusal_implemented"] == 0
    assert result["refusal"] == "-1"


def test_the_as_built_policy_matches_the_daemons_own_resolution_order():
    """The probe must not drift from daemon._ptt_start's stated order."""
    source = (REPO / "src" / "assistant" / "daemon.py").read_text(encoding="utf-8")
    start = source.split("async def _ptt_start", 1)[1]
    assert 'params.get("target")' in start
    assert 'capture_cfg.get("mic_target")' in start
    assert 'section("meeting").get("mic_target")' in start
    # ...and the fallback really is "no target" (= PipeWire default), not a refusal.
    assert "or None" in start.split("stall_timeout_s", 1)[0]


def test_f17_refuses_an_unnamed_node_and_never_presents_the_default():
    result = check.report("pactl", None, "", sources=check.parse_json_sources(PACTL_JSON),
                          default=MONITOR, policy="f17")
    assert result["capture_would_refuse"] == 1
    assert result["refusal"] == "f17_no_node"
    assert result["effective_node"] == "-1"        # the default is NOT a capture node
    assert result["fallback_to_default"] == 0
    assert result["f17_refusal_implemented"] == 1
    # The default source is still a fact about the machine, reported as such.
    assert result["default_source"] == MONITOR


def test_a_named_node_wins_under_both_policies():
    for policy in check.POLICIES:
        result = check.report("pactl", None, MIC1,
                              sources=check.parse_json_sources(PACTL_JSON),
                              default=MONITOR, policy=policy)
        assert result["node"] == MIC1
        assert result["effective_node"] == MIC1
        assert result["capture_would_refuse"] == 0
        assert result["volume_percent"] == "100.0"
        assert result["node_is_monitor"] == 0
        assert result["node_is_mic1"] == 1


def test_an_unknown_policy_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError):
        check.resolve_node("", "", "whatever")
    assert check.main(["--policy", "whatever"]) == 2


# ---------------------------------------------------------------------------
# loopback detection: the flat-envelope question
# ---------------------------------------------------------------------------
def test_a_monitor_node_is_flagged_as_a_loopback():
    result = check.report("pactl", None, MONITOR,
                          sources=check.parse_json_sources(PACTL_JSON),
                          default=MONITOR, policy="f17")
    assert result["node_is_monitor"] == 1
    assert check.pin_line(MONITOR, check.parse_json_sources(PACTL_JSON)) == "-1"


def test_pin_line_is_paste_exact_for_a_real_mic_and_refused_otherwise():
    sources = check.parse_json_sources(PACTL_JSON)
    assert check.pin_line(MIC1, sources) == f'mic_target = "{MIC1}"'
    assert check.pin_line("", sources) == "-1"                   # nothing to pin
    assert check.pin_line("alsa_input.unplugged", sources) == "-1"  # not listed


def test_the_monitor_count_is_a_number_not_a_comment():
    result = check.report("pactl", None, MIC1,
                          sources=check.parse_json_sources(PACTL_JSON),
                          default=MONITOR, policy="as-built")
    assert result["monitor_sources"] == 1
    assert result["sources"] == 2
    assert result["monitor_names"] == [MONITOR]


# ---------------------------------------------------------------------------
# config reading
# ---------------------------------------------------------------------------
def test_config_node_is_read_from_the_capture_table(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(f'[capture]\nmic_target = "{MIC1}"\n', encoding="utf-8")
    assert check.configured_node_from(config) == MIC1
    result = check.report("pactl", config, "",
                          sources=check.parse_json_sources(PACTL_JSON),
                          default=MONITOR, policy="f17")
    assert result["config_found"] == 1
    assert result["configured_node"] == MIC1
    assert result["node"] == MIC1


def test_a_missing_or_broken_config_reads_as_absent_never_as_a_value(tmp_path):
    assert check.configured_node_from(None) == ""
    assert check.configured_node_from(tmp_path / "absent.toml") == ""
    broken = tmp_path / "broken.toml"
    broken.write_text("this is [not toml", encoding="utf-8")
    assert check.configured_node_from(broken) == ""
    other = tmp_path / "other.toml"
    other.write_text('[meeting]\nmic_target = "x"\n', encoding="utf-8")
    assert check.configured_node_from(other) == ""   # only [capture] governs


def test_config_path_prefers_assist_config_then_xdg():
    assert check.default_config_path({"ASSIST_CONFIG": "/tmp/a.toml"}) == Path("/tmp/a.toml")
    resolved = check.default_config_path({"XDG_CONFIG_HOME": "/tmp/cfg"})
    assert resolved == Path("/tmp/cfg/assistant/config.toml")


# ---------------------------------------------------------------------------
# rendering: numbers, and what an empty result cannot tell you
# ---------------------------------------------------------------------------
def test_render_is_key_value_only_and_says_read_only():
    result = check.report("pactl", None, MIC1,
                          sources=check.parse_json_sources(PACTL_JSON),
                          default=MONITOR, policy="as-built")
    lines = check.render(result).splitlines()
    assert lines[0] == "available 1"
    assert f"node {MIC1}" in lines
    assert "volume_percent 100.0" in lines
    assert lines[-1] == "note read_only"
    for line in lines:
        assert " " in line


def test_unavailable_states_what_it_fails_to_discriminate():
    text = check.render({"available": False, "reason": "pactl exit 127"})
    assert text.splitlines()[0] == "available 0"
    assert "reason pactl exit 127" in text
    assert "note empty_fails_to_discriminate" in text


def test_the_fallback_note_appears_only_when_the_fallback_is_real():
    sources = check.parse_json_sources(PACTL_JSON)
    built = check.render(check.report("pactl", None, "", sources=sources,
                                      default=MONITOR, policy="as-built"))
    assert "note unset_mic_target_falls_back_to_default_source" in built
    ruled = check.render(check.report("pactl", None, "", sources=sources,
                                      default=MONITOR, policy="f17"))
    assert "note unset_mic_target_falls_back_to_default_source" not in ruled
    assert "note refusal_means_do_not_guess_a_node" in ruled


# ---------------------------------------------------------------------------
# cli + pin
# ---------------------------------------------------------------------------
def test_cli_replays_captured_pactl_text(tmp_path, capsys):
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(PACTL_JSON, encoding="utf-8")
    info_file = tmp_path / "info.txt"
    info_file.write_text(PACTL_INFO, encoding="utf-8")
    code = check.main(["--node", MIC1, "--pactl-json", str(sources_file),
                       "--pactl-info", str(info_file),
                       "--config", str(tmp_path / "absent.toml")])
    out = capsys.readouterr().out
    assert code == 0
    assert f"node {MIC1}" in out
    assert "node_found 1" in out
    assert "volume_percent 100.0" in out
    assert "default_source alsa_output" in out


def test_pin_line_mode_prints_the_line_or_says_not_listed(tmp_path, capsys):
    sources_file = tmp_path / "sources.json"
    sources_file.write_text(PACTL_JSON, encoding="utf-8")
    assert check.main(["--pin-line", "--node", MIC1,
                       "--pactl-json", str(sources_file)]) == 0
    assert capsys.readouterr().out.strip() == f'mic_target = "{MIC1}"'
    assert check.main(["--pin-line", "--node", "alsa_input.not_here",
                       "--pactl-json", str(sources_file)]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == "-1"
    assert 'mic_target = "alsa_input.not_here"' in captured.err


def test_help_and_bad_arguments_are_refused_without_tracebacks():
    assert check.main(["--help"]) == 2
    assert check.main(["--nonsense"]) == 2
    assert check.main(["--node"]) == 2


def test_manifest_is_repo_relative_and_verifies_from_the_root():
    digest, name = MANIFEST.read_text().split()
    assert name == "scripts/capture_source_check.py"
    assert hashlib.sha256(SCRIPT.read_bytes()).hexdigest() == digest, (
        "capture_source_check.py changed without regenerating its manifest — run "
        "`python3 scripts/capture_source_check.py --checksum`")
    verified = subprocess.run(
        ["sha256sum", "-c", "scripts/capture_source_check.py.sha256"],
        cwd=REPO, capture_output=True, text=True, timeout=60, check=False)
    assert verified.returncode == 0, verified.stdout + verified.stderr


def test_the_probe_is_read_only_by_construction():
    """The only write is the `.sha256` manifest; nothing sets or loads audio.

    Pinned structurally (AST + call names) rather than by grepping prose, so a
    docstring cannot satisfy the check on the script's behalf.
    """
    import ast

    source = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(source)
    writers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if name in {"write_text", "write_bytes", "open", "commit", "execute",
                    "mkdir", "unlink", "rename"}:
            writers.append(name)
    # write_text appears exactly once, inside write_manifest, for the pin file.
    assert writers.count("write_text") == 1, writers
    enclosing = [n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)
                 and any(isinstance(c, ast.Call)
                         and getattr(c.func, "attr", "") == "write_text"
                         for c in ast.walk(n))]
    assert [f.name for f in enclosing] == ["write_manifest"]
    # No database and no mutation verbs reach a subprocess.
    assert "sqlite3" not in source
    for verb in ("set-", "load-", "unload-", "suspend-", "set-default"):
        assert f'"{verb}' not in source and f"'{verb}" not in source, verb
