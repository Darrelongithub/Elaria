"""H · DESKTOP — step 1 (certified binds intact) and step 4 (no new autonomy).

Build order 1: prove the existing binds are intact and the certified hyprland
lines are untouched before anything else is dressed. The canonical set in this tree
is the PTT pair + F30 cancel + panic switch (the Lua/legacy forms the owner's 0.57
compositor reads). `Win+Space` is the *console-native* bind and lives in M's lane on
the console branch — it is NOT in this tree, and
`test_win_space_is_not_issued_here` pins that absence so a merge cannot land two
bindings for one key. It does not prove Win+Space opens the console cold; that is
M's owner-verified claim plus a hardware run.

Build order 4: introduce zero new autonomous actions and assert it. The assertion is
structural, not a vibe: the H modules may only reach the outside world through the
two subprocess sites that already existed at BASE (a read-only `hyprctl version` and
the dictation handoff `wl-copy`), may not import any action-bearing module, and
presence may write exactly the two documented state keys.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from assistant.hypr_binds import BINDS, LEGACY, LUA, detect, emit_binds, syntax_for_version

REPO = Path(__file__).resolve().parents[1]
H_MODULES = ("waybar.py", "hypr_binds.py", "overlay.py", "presence.py",
             "clipboard.py")
H_PATHS = [REPO / "src/assistant" / name for name in H_MODULES]

#: The certified set, verbatim, in emission order (provenance: scene 3b
#: 2026-10-26 for `ignore_mods`, F30 for the cancel, §4.4 for the halt).
CERTIFIED = (
    {"chord": "SUPER + grave", "command": "assist ptt start",
     "release": False, "note": "push-to-talk: press starts"},
    {"chord": "SUPER + grave", "command": "assist ptt stop --stop-source bind",
     "release": True, "note": "push-to-talk: release stops"},
    {"chord": "Escape", "command": "assist ptt cancel",
     "release": False, "note": "F30 cancel: stop + zeroize + release the node"},
    {"chord": "SUPER + SHIFT + F12", "command": "assist halt",
     "release": False, "note": "panic switch (§4.4)"},
)

#: Modules that can act. A dressing module importing one of these is a new
#: autonomy path wearing a costume.
ACTION_MODULES = frozenset({
    "executor", "planner", "planner_llm", "initiative", "safety", "proc",
    "phone_link", "drafts", "cleanup", "tiering", "backup", "hands",
})

#: What a dressing module is allowed to import, and nothing else.
H_IMPORT_ALLOWLIST = frozenset({
    "__future__", "json", "dataclasses", "datetime", "re", "shutil",
    "subprocess", "socket", "time", "assistant.ipc", "assistant.presence",
})


# ---------------------------------------------------------------------------
# step 1 · the certified bind lines are intact
# ---------------------------------------------------------------------------
def test_certified_bind_set_is_exact():
    assert tuple(BINDS) == CERTIFIED
    assert len(BINDS) == 4
    assert [b["command"] for b in BINDS] == [
        "assist ptt start", "assist ptt stop --stop-source bind",
        "assist ptt cancel", "assist halt"]


def test_lua_snippet_is_byte_identical_to_the_emitter():
    """The shipped snippet is generated output, pinned — documentation cannot
    drift from what the installer hands the compositor (2026-11-15 defect)."""
    shipped = (REPO / "ui/hyprland/elaria-binds.lua").read_text()
    for line in emit_binds(LUA).splitlines():
        assert line in shipped, f"emitted line missing from the shipped lua: {line}"
    assert shipped.count("hl.bind(") == 4


def test_legacy_snippet_keeps_the_bindri_release_form():
    shipped = (REPO / "ui/hyprland/elaria-binds.conf").read_text()
    for line in emit_binds(LEGACY).splitlines():
        assert line in shipped, f"emitted line missing from the shipped conf: {line}"
    assert "bindri = SUPER, grave, exec, assist ptt stop --stop-source bind" in shipped
    bind_lines = [ln for ln in shipped.splitlines()
                  if ln.startswith(("bind ", "bindri "))]
    assert len(bind_lines) == 4


def test_release_line_carries_the_order_robust_flags():
    """Scene 3b: without ignore_mods a Win-first release leaks the mic. That flag
    is a hardware finding, not a style choice — it must not be "tidied" away."""
    release_lines = [ln for ln in emit_binds(LUA).splitlines() if "ptt stop" in ln]
    assert len(release_lines) == 1
    assert "release = true" in release_lines[0]
    assert "ignore_mods = true" in release_lines[0]


@pytest.mark.parametrize("version,expected", [
    ((0, 57), LUA), ((0, 55), LUA), ((0, 54), LEGACY), (None, LUA),
])
def test_emitter_is_lua_first(version, expected):
    assert syntax_for_version(version) == expected


def test_detect_without_hyprctl_still_answers_lua():
    """No compositor (CI, container, SSH) is a stated reason, not a crash and not
    a fallback to the dialect 0.57 ignores."""
    info = detect()
    assert info["syntax"] == LUA
    assert info["detected"] is False
    assert "hyprctl" in info["detail"]


def test_win_space_is_not_issued_here():
    """NEGATIVE RESULT, stated as such: this proves only that this tree does not
    bind Space, so the console branch's Win+Space cannot be double-bound at merge.
    It fails to discriminate whether that bind works — cold verify on hardware is
    the owner's, and the bind itself is M's."""
    for path in (REPO / "ui/hyprland/elaria-binds.lua",
                 REPO / "ui/hyprland/elaria-binds.conf"):
        text = path.read_text().lower()
        assert "space" not in text, f"{path.name} binds a space chord; Win+Space is M's"
    assert all("space" not in b["chord"].lower() for b in BINDS)


def test_no_bind_targets_a_new_command():
    """Every bound command must still be a real subcommand of the CLI — a bind to
    a typo'd verb is an invisible dead key, the exact failure class this lane was
    created to stop repeating."""
    cli = (REPO / "src/assistant/cli.py").read_text()
    for bind in BINDS:
        verb = bind["command"].split()[1]
        assert f'"{verb}"' in cli or f"'{verb}'" in cli, f"{bind['command']} targets nothing"


# ---------------------------------------------------------------------------
# step 4 · zero new autonomy, asserted structurally
# ---------------------------------------------------------------------------
def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom):
            if node.level:                     # `from .ipc import ...` → assistant.ipc
                out.add(f"assistant.{node.module}" if node.module else "assistant")
            elif node.module:
                out.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                out.add(alias.name)
    return out


def _subprocess_sites(path: Path) -> list[str]:
    """Every call that hands argv to a process runner, as its literal argv head."""
    heads: list[str] = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in {"run", "Popen", "check_output", "check_call", "runner"}:
            continue
        if node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
            heads.append(str(getattr(node.args[0].elts[0], "value", "?")))
        else:
            heads.append("<non-literal>")
    return heads


def test_h_modules_import_no_action_bearing_module():
    offenders: list[str] = []
    for path in H_PATHS:
        modules = _imports(path)
        offenders += [f"{path.name}:{m}" for m in sorted(modules & ACTION_MODULES)]
        unknown = modules - H_IMPORT_ALLOWLIST
        assert not unknown, f"{path.name} imports outside the allowlist: {sorted(unknown)}"
    assert offenders == []


def test_h_presence_imports_nothing_new():
    """presence.py stays self-contained: it must not grow a dependency on E's
    phone modules to learn about the phone — the event carries the notion."""
    assert _imports(REPO / "src/assistant/presence.py") == {
        "__future__", "json", "dataclasses", "datetime"}


def test_h_modules_reach_the_outside_world_twice_only():
    """2 subprocess sites in the whole lane, both already present at BASE."""
    sites = [(path.name, head) for path in H_PATHS for head in _subprocess_sites(path)]
    assert sorted(sites) == sorted([("hypr_binds.py", "hyprctl"),
                                    ("clipboard.py", "wl-copy")])


def test_no_shell_true_and_no_new_state_key_in_the_lane():
    for path in H_PATHS:
        text = path.read_text()
        assert "shell=True" not in text, f"{path.name} shells out"
    presence = (REPO / "src/assistant/presence.py").read_text()
    assert presence.count("self.store.set_state(") == 2
    assert "STATE_KEY, json.dumps(bool(enabled))" in presence
    assert "DEVICE_STATE_KEY, json.dumps(payload)" in presence


def test_waybar_class_vocabulary_is_unchanged():
    """No new class token: device-presence rides the tooltip only, because this
    module's classes are a closed set mirrored in ui/waybar/style.css."""
    from assistant.waybar import format_waybar
    base = {"running": True, "mode": "idle", "gemini_mode": "live"}
    plain = format_waybar(base)
    with_phone = format_waybar({**base, "device_presence": {
        "phone_connected": True, "source": "event"}})
    assert plain["class"] == with_phone["class"] == ["idle"]
    assert "phone: connected" in with_phone["tooltip"]
    assert "phone:" not in plain["tooltip"]
    assert json.dumps(with_phone)          # still one serialisable line for Waybar
