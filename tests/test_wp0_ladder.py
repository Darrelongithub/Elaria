"""WP0 EYES: the productised hardware ladder (§4.8) — [TESTED-ONLY].

Every rung reads truth through its named mechanism and prints REACHED or
STUCK with evidence. Rung E of the console chain is the rewritten one (§3c):
a journal "Configuration Loaded" proxy PLUS a layer-namespace check — never
`hyprctl clients`, never a grep for "quickshell".
"""

from __future__ import annotations

import json
import subprocess

from assistant.ladder import CONSOLE_NAMESPACE, Ladder, main, render

BINDS = json.dumps([
    {"key": "F2", "mod": "SUPER"},
    {"key": "F2", "mod": "SUPER SHIFT"},
    {"key": "F12", "mod": "SUPER SHIFT"},
])
LAYERS = json.dumps({
    "DP-1": {
        CONSOLE_NAMESPACE: {"layer": "Top", "namespace": CONSOLE_NAMESPACE},
        "elaria-overlay": {"layer": "Overlay"},
    }
})
NO_LAYERS = json.dumps({"DP-1": {}})
JOURNAL_OK = "Configuration Loaded\n"
JOURNAL_ERR = ("Configuration Loaded\n"
               "QQmlApplicationEngine failed: shell.qml:616 TypeError\n")


def _router(responses: dict[str, tuple[int, str, str]]):
    """Fake subprocess.run keyed by 'argv[0] argv[1] …' (longest key wins)."""

    def run(argv, capture_output=True, text=True, timeout=10):
        key = " ".join(argv)
        best = None
        for name, value in responses.items():
            if (key == name or key.startswith(name + " ")) and (
                    best is None or len(name) > len(best[0])):
                best = (name, value)
        code, out, err = best[1] if best else (1, "", "no fixture")
        return subprocess.CompletedProcess(argv, code, out, err)

    return run


def _ladder(config, responses, status=None):
    return Ladder(
        config,
        runner=_router(responses),
        which=lambda name: f"/usr/bin/{name}",
        status=status or (lambda: {
            "dictation_active": False, "ptt_session_id": None,
            "session_holders": [], "hotword": {"armed": False},
            "session_ceiling_s": 300.0, "gemini_mode": "mock",
            "voice": {"voice_mode": "gemini-interim",
                      "cached_acks": ["on_it"],
                      "voice_identity": {"allowed": True},
                      "reason": "ok"},
        }))


def _console_responses(**overrides):
    base = {
        "hyprctl -j binds": (0, BINDS, ""),
        "hyprctl -j layers": (0, LAYERS, ""),
        "systemctl --user is-active": (0, "active\n", ""),
        "systemctl --user is-enabled": (0, "enabled\n", ""),
        "journalctl --user": (0, JOURNAL_OK, ""),
    }
    base.update(overrides)
    return base


def test_console_chain_reaches_e_when_the_surface_is_registered(config):
    ladder = _ladder(config, _console_responses())
    text, ok = render(ladder.run("console"))
    assert ok, text
    assert "REACHED" in text
    assert "she is on screen" in text
    assert f"layer namespace {CONSOLE_NAMESPACE}=present" in text


def test_rung_e_is_stuck_without_the_journal_proxy(config):
    responses = _console_responses()
    responses["journalctl --user"] = (0, "", "")
    text, ok = render(_ladder(config, responses).run("console"))
    assert not ok
    assert "STUCK" in text
    assert "Configuration Loaded'='no'" in text or "Configuration Loaded" in text


def test_rung_e_is_stuck_without_the_layer_namespace(config):
    responses = _console_responses()
    responses["hyprctl -j layers"] = (0, NO_LAYERS, "")
    text, ok = render(_ladder(config, responses).run("console"))
    assert not ok
    assert f"namespace {CONSOLE_NAMESPACE}=" in text
    assert "ABSENT" in text


def test_rung_e_is_stuck_on_a_qml_error(config):
    responses = _console_responses()
    responses["journalctl --user"] = (0, JOURNAL_ERR, "")
    text, ok = render(_ladder(config, responses).run("console"))
    assert not ok
    assert "QML error" in text


def test_rung_e_never_consults_hyprctl_clients(config):
    def run(argv, capture_output=True, text=True, timeout=10):
        assert "clients" not in argv, (
            "rung E must not consult hyprctl clients — quickshell panels are "
            "layer surfaces")
        return _router(_console_responses())(argv)

    ladder = _ladder(config, _console_responses())
    ladder._run = run
    ladder.run("console")


def test_bare_f2_bind_is_structurally_impossible_to_miss(config):
    bare = json.dumps([{"key": "F2", "mod": ""}])
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, bare, "")
    text, ok = render(_ladder(config, responses).run("console")
                      + _ladder(config, responses).run("wake"))
    assert not ok
    assert "bare-F2" in text
    assert "PRESENT (forbidden)" in text


def test_every_rung_prints_reached_or_stuck_with_evidence(config):
    text, _ok = render(_ladder(config, _console_responses()).run("all"))
    rung_lines = [line for line in text.splitlines()
                  if line[:2] in ("A ", "B ", "C ", "D ", "E ")]
    assert len(rung_lines) == 20, text   # 4 chains x 5 rungs
    for line in rung_lines:
        assert ("REACHED" in line) or ("STUCK" in line), line
        assert ": " in line, line
    for chain in ("console chain", "wake chain", "voice chain", "event chain"):
        assert chain in text


def test_missing_tools_stick_with_the_reason(config):
    ladder = Ladder(config, runner=_router({}), which=lambda _n: None,
                    status=lambda: {"a": 1})
    text, ok = render(ladder.run("wake"))
    assert not ok
    assert "not found" in text


def test_wake_chain_reads_status_fields(config):
    seen = {}

    def status():
        seen["called"] = True
        return {"dictation_active": True, "ptt_session_id": "abc",
                "session_holders": [{"kind": "ptt"}],
                "hotword": {"armed": True}, "session_ceiling_s": 300.0}

    text, ok = render(_ladder(config, _console_responses(),
                              status=status).run("wake"))
    assert ok, text
    assert seen["called"]
    assert "dictation_active=True" in text
    assert "session_holders" in text


def test_event_chain_reports_segment_and_marker_counts(config, monkeypatch):
    monkeypatch.setattr(
        "assistant.ipc.call",
        lambda socket, method, timeout=2.0: {
            "running": True, "segments_written": 3, "marker_count": 2,
            "document": __file__})
    ladder = _ladder(config, _console_responses(),
                     status=lambda: {"session_holders": [{"kind": "event"}]})
    text, ok = render(ladder.run("event"))
    assert ok, text
    assert "segments=3" in text
    assert "markers=2" in text
    assert "live document" in text


def test_cli_and_elaria_ladder_entry_points(config, capsys, monkeypatch):
    monkeypatch.setattr("assistant.config.load_config", lambda: config)
    assert main(["wake"]) in (0, 1)   # truth depends on the machine
    out = capsys.readouterr().out
    assert "wake chain" in out
    assert ("REACHED" in out) or ("STUCK" in out)
