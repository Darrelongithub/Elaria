"""WP0 EYES: the productised hardware ladder (§4.8) — [TESTED-ONLY].

Every rung reads truth through its named mechanism and prints REACHED, STUCK
or N/A with evidence (scene-1 semantics: N/A when the rung does not apply;
a bare-F2 *press* bind is forbidden, a legacy `bindr = , F2` release-stop is
WARN-tolerated until WP3; Hyprland `$mainMod`-style variables in binds are
resolved from the config-file definitions). Rung E of the console chain is
the rewritten one (§3c): a journal "Configuration Loaded" proxy PLUS a
layer-namespace check — never `hyprctl clients`, never a grep for
"quickshell".
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


def _ladder(config, responses, status=None, hypr_config=None):
    return Ladder(
        config,
        runner=_router(responses),
        which=lambda name: f"/usr/bin/{name}",
        hypr_config=hypr_config,
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


def test_bare_f2_press_bind_is_structurally_impossible_to_miss(config):
    bare = json.dumps([{"key": "F2", "mod": ""}])
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, bare, "")
    text, ok = render(_ladder(config, responses).run("console")
                      + _ladder(config, responses).run("wake"))
    assert not ok
    assert "bare-F2 press bind=PRESENT (forbidden)" in text


def test_bare_f2_release_stop_is_a_warn_never_stuck(config):
    # Scene-1 ruling: `bindr = , F2` release-stop is legacy-tolerated until
    # WP3 — WARN "legacy release-stop bind (WP3 replaces)", never STUCK.
    binds = json.dumps([
        {"key": "F2", "mod": "SUPER"},
        {"key": "F2", "mod": "SUPER SHIFT"},
        {"key": "F12", "mod": "SUPER SHIFT"},
        {"key": "F2", "mod": "", "release": True},
    ])
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, binds, "")
    text, ok = render(_ladder(config, responses).run("console")
                      + _ladder(config, responses).run("wake"))
    assert ok, text
    assert "WARN legacy release-stop bind (WP3 replaces)" in text
    assert "STUCK" not in text


def test_bare_f2_press_beats_the_release_tolerance(config):
    binds = json.dumps([
        {"key": "F2", "mod": "SUPER"},
        {"key": "F2", "mod": "SUPER SHIFT"},
        {"key": "F12", "mod": "SUPER SHIFT"},
        {"key": "F2", "mod": ""},                      # forbidden press
        {"key": "F2", "mod": "", "release": True},     # tolerated release
    ])
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, binds, "")
    text, ok = render(_ladder(config, responses).run("wake"))
    assert not ok
    assert "bare-F2 press bind=PRESENT (forbidden)" in text
    assert "WARN legacy release-stop bind (WP3 replaces)" in text


# -- Hyprland $variable binds (scene-1 fix) ---------------------------------

def _var_binds():
    return json.dumps([
        {"key": "F2", "mod": "$mainMod"},
        {"key": "F2", "mod": "$mainMod SHIFT"},
        {"key": "F12", "mod": "$mainMod SHIFT"},
    ])


def test_bind_variables_resolve_from_set_definitions(config, tmp_path):
    conf = tmp_path / "hyprland.conf"
    conf.write_text("# owner config\nset = mainMod, SUPER\n", encoding="utf-8")
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, _var_binds(), "")
    ladder = _ladder(config, responses, hypr_config=conf)
    text, ok = render(ladder.run("console") + ladder.run("wake"))
    assert ok, text
    assert "Win+F2 press=present" in text
    assert "Win+Shift+F2 raise bind=present" in text
    assert "Win+Shift+F12 halt=present" in text


def test_bind_variables_resolve_from_dollar_definitions_and_includes(
        config, tmp_path):
    # Legacy `$name = value` form, in a `source =`d include.
    include = tmp_path / "vars.conf"
    include.write_text("$mainMod = SUPER\n", encoding="utf-8")
    conf = tmp_path / "hyprland.conf"
    conf.write_text(f"source = {include}\n", encoding="utf-8")
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, _var_binds(), "")
    text, ok = render(_ladder(config, responses, hypr_config=conf).run("wake"))
    assert ok, text
    assert "Win+F2 press=present" in text


def test_unresolved_bind_variables_are_reported_not_hidden(config, tmp_path):
    conf = tmp_path / "hyprland.conf"
    conf.write_text("# no definitions at all\n", encoding="utf-8")
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, _var_binds(), "")
    text, ok = render(_ladder(config, responses, hypr_config=conf).run("wake"))
    assert not ok
    assert "Win+F2 press=ABSENT" in text
    assert "unresolved vars: $mainMod" in text


def test_mods_key_and_plus_separated_mods_also_tokenise(config, tmp_path):
    conf = tmp_path / "hyprland.conf"
    conf.write_text("set = mainMod, SUPER\n", encoding="utf-8")
    binds = json.dumps([
        {"key": "F2", "mods": "$mainMod"},
        {"key": "F2", "mods": ["$mainMod", "SHIFT"]},
        {"key": "F12", "mod": "$mainMod+SHIFT"},
    ])
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, binds, "")
    ladder = _ladder(config, responses, hypr_config=conf)
    entries, why = ladder._bind_entries()
    assert [e.token for e in entries] == ["superf2", "shiftsuperf2",
                                          "shiftsuperf12"], why


# -- the owner's real bind shape (scene-2 truth dump 2026-10-26) -----------
# Copied VERBATIM from the laptop's `hyprctl -j binds` output (F2 filter):
# the payload field is `modmask` (64 = SUPER, 65 = SUPER+SHIFT), `key` carries
# the name, `release` marks bindr. The F12 halt entry is derived from the same
# dumped shape and the real config line `bind = SUPER SHIFT, F12, exec,
# assist halt` (hyprland.conf:210) — modmask 65 as dumped for SUPER+SHIFT.

DUMP_F2_PRESS = {
    "locked": False, "mouse": False, "release": False, "repeat": False,
    "longPress": False, "non_consuming": False, "auto_consuming": False,
    "has_description": False, "modmask": 64, "submap": "",
    "submap_universal": "false", "key": "F2", "keycode": 0,
    "catch_all": False, "description": "", "allow_input_capture": False,
    "dispatcher": "exec", "arg": "assist ptt start"}
DUMP_F2_RELEASE = {
    "locked": False, "mouse": False, "release": True, "repeat": False,
    "longPress": False, "non_consuming": False, "auto_consuming": False,
    "has_description": False, "modmask": 0, "submap": "",
    "submap_universal": "false", "key": "F2", "keycode": 0,
    "catch_all": False, "description": "", "allow_input_capture": False,
    "dispatcher": "exec", "arg": "assist ptt stop"}
DUMP_F2_RAISE = {
    "locked": False, "mouse": False, "release": False, "repeat": False,
    "longPress": False, "non_consuming": False, "auto_consuming": False,
    "has_description": False, "modmask": 65, "submap": "",
    "submap_universal": "false", "key": "F2", "keycode": 0,
    "catch_all": False, "description": "", "allow_input_capture": False,
    "dispatcher": "exec",
    "arg": "/home/darrel/.local/bin/elaria-console-open"}
DUMP_F12_HALT = {
    "locked": False, "mouse": False, "release": False, "repeat": False,
    "longPress": False, "non_consuming": False, "auto_consuming": False,
    "has_description": False, "modmask": 65, "submap": "",
    "submap_universal": "false", "key": "F12", "keycode": 0,
    "catch_all": False, "description": "", "allow_input_capture": False,
    "dispatcher": "exec", "arg": "assist halt"}
DUMP_BINDS = json.dumps(
    [DUMP_F2_PRESS, DUMP_F2_RELEASE, DUMP_F2_RAISE, DUMP_F12_HALT])


def test_scene3_gate_truthful_rungs_from_the_owner_dump(config):
    """The scene-3 gate, asserted against the real dumped shape: Win+F2
    press PRESENT, halt PRESENT, raise PRESENT, bare-F2 press ABSENT, and
    the legacy release-stop WARN retained."""
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, DUMP_BINDS, "")
    ladder = _ladder(config, responses)
    text, ok = render(ladder.run("wake") + ladder.run("console"))
    assert ok, text
    assert "Win+F2 press=present" in text
    assert "Win+Shift+F12 halt=present" in text
    assert "Win+Shift+F2 raise bind=present" in text
    assert "bare-F2 press bind=absent" in text
    assert "WARN legacy release-stop bind (WP3 replaces)" in text
    assert "chain STUCK" not in text


def test_modmask_is_authority_mod_text_is_fallback_only(config):
    """Scene-2 phantom root cause: the real payload has NO mod/mods field —
    only `modmask`. When both exist, the compositor mask wins; when only mod
    text exists (fakes/config), variable expansion is the fallback (covered
    by test_variable_fallback_resolves_the_owner_dollar_form)."""
    entry = dict(DUMP_F2_PRESS)
    entry["mods"] = "$wrongVar SHIFT"
    responses = _console_responses()
    responses["hyprctl -j binds"] = (
        0, json.dumps([entry, DUMP_F2_RELEASE, DUMP_F2_RAISE, DUMP_F12_HALT]), "")
    text, ok = render(_ladder(config, responses).run("wake"))
    assert ok, text
    assert "Win+F2 press=present" in text


def test_variable_fallback_resolves_the_owner_dollar_form(config, tmp_path):
    # hyprland.conf:21 — the owner's exact definition form: `$mainMod = SUPER`
    conf = tmp_path / "hyprland.conf"
    conf.write_text("$mainMod = SUPER\n", encoding="utf-8")
    responses = _console_responses()
    responses["hyprctl -j binds"] = (
        0, json.dumps([{"key": "F2", "mods": "$mainMod"},
                       {"key": "F2", "mods": "$mainMod SHIFT"},
                       {"key": "F12", "mods": "$mainMod SHIFT"},
                       {"key": "F2", "mods": "", "release": True}]), "")
    text, ok = render(_ladder(config, responses, hypr_config=conf).run("wake"))
    assert ok, text
    assert "Win+F2 press=present" in text
    assert "Win+Shift+F12 halt=present" in text
    assert "WARN legacy release-stop bind (WP3 replaces)" in text


def test_unresolved_variable_never_makes_a_bare_f2_press(config, tmp_path):
    # The rung-E disease, forbidden: a bind whose $mainMod fails to resolve
    # must NOT collapse to a phantom bare-F2 press — it stays unresolved and
    # is NAMED in the evidence.
    conf = tmp_path / "hyprland.conf"
    conf.write_text("# no definitions at all\n", encoding="utf-8")
    responses = _console_responses()
    responses["hyprctl -j binds"] = (
        0, json.dumps([{"key": "F2", "mods": "$mainMod"}]), "")
    text, ok = render(_ladder(config, responses, hypr_config=conf).run("wake"))
    assert not ok
    assert "Win+F2 press=ABSENT" in text
    assert "bare-F2 press bind=absent" in text        # never a phantom
    assert "unresolved vars: $mainMod" in text


def test_empty_expanding_variable_never_makes_a_bare_f2_press(config, tmp_path):
    # Silently expanding to empty is the same disease: forbidden.
    conf = tmp_path / "hyprland.conf"
    conf.write_text("set = mainMod,\n", encoding="utf-8")
    responses = _console_responses()
    responses["hyprctl -j binds"] = (
        0, json.dumps([{"key": "F2", "mods": "$mainMod"}]), "")
    text, ok = render(_ladder(config, responses, hypr_config=conf).run("wake"))
    assert not ok
    assert "bare-F2 press bind=absent" in text
    assert "expands to empty" in text


def test_keycode_only_f2_is_still_recognised(config):
    # the owner's dump filter used keycode==68 (evdev KEY_F2) as well as key
    entry = {"modmask": 0, "key": "", "keycode": 68, "release": True}
    responses = _console_responses()
    responses["hyprctl -j binds"] = (0, json.dumps([entry]), "")
    text, _ok = render(_ladder(config, responses).run("wake"))
    assert "WARN legacy release-stop bind (WP3 replaces)" in text


def test_every_rung_prints_reached_stuck_or_na_with_evidence(config):
    text, _ok = render(_ladder(config, _console_responses()).run("all"))
    rung_lines = [line for line in text.splitlines()
                  if line[:2] in ("A ", "B ", "C ", "D ", "E ")]
    assert len(rung_lines) == 20, text   # 4 chains x 5 rungs
    for line in rung_lines:
        assert ("REACHED" in line) or ("STUCK" in line) or ("N/A" in line), line
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


def test_event_rung_e_is_na_when_no_event_is_running(config, monkeypatch):
    # Scene-1 ruling: N/A when no event is running — never STUCK.
    monkeypatch.setattr(
        "assistant.ipc.call",
        lambda socket, method, timeout=2.0: {
            "running": False, "segments_written": 0, "marker_count": 0,
            "document": None})
    text, ok = render(_ladder(config, _console_responses(),
                              status=lambda: {"session_holders": []}).run("event"))
    assert ok, text
    assert "E does the live document exist on disk? — N/A" in text
    assert "no event is running" in text
    assert "chain STUCK" not in text


def test_event_rung_e_is_stuck_only_when_running_and_document_unreadable(
        config, monkeypatch):
    monkeypatch.setattr(
        "assistant.ipc.call",
        lambda socket, method, timeout=2.0: {
            "running": True, "segments_written": 1, "marker_count": 0,
            "document": None})
    text, ok = render(_ladder(config, _console_responses(),
                              status=lambda: {"session_holders": [{"kind": "event"}]}).run("event"))
    assert not ok
    assert "event is running but no live document path is readable" in text
    assert "STUCK" in text


def test_cli_and_elaria_ladder_entry_points(config, capsys, monkeypatch):
    monkeypatch.setattr("assistant.config.load_config", lambda: config)
    assert main(["wake"]) in (0, 1)   # truth depends on the machine
    out = capsys.readouterr().out
    assert "wake chain" in out
    assert ("REACHED" in out) or ("STUCK" in out)
