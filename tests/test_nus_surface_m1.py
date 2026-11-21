"""M1 of the NUS surface: layer-shell posture, click-through, focus, commands.

The QML cannot run headless, so its dangerous properties are guarded
statically. The focus guarantee is then exercised against a fake Hyprland
compositor: `hyprctl activewindow -j` must return the same window before and
after the surface is mapped and unmapped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import ClassVar

from assistant.nus_surface import (
    HIDE_COMMAND,
    NUS_INPUT_MODE,
    NUS_KEYBOARD_FOCUS,
    NUS_LAYER,
    NUS_NAMESPACE,
    SHOW_COMMAND,
    VISIBLE_COMMAND,
    NusSurfaceController,
    active_window,
)

REPO = Path(__file__).resolve().parents[1]
QML = REPO / "ui/quickshell/nus/shell.qml"


class FakeHyprctl:
    """Answers only the read-only focus query Hyprland's IPC exposes."""

    def __init__(self, window: dict[str, str]) -> None:
        self.window = window
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, args: list[str]) -> str:
        assert tuple(args) == ("hyprctl", "activewindow", "-j")
        self.calls.append(tuple(args))
        return json.dumps(self.window)


class FakeCompositor:
    """wlr-layer-shell semantics relevant to M1: mapping never takes focus."""

    def __init__(self, focus: dict[str, str]) -> None:
        self.focus = focus
        self.surfaces: dict[str, dict] = {}

    def apply(self, command: dict) -> None:
        assert command["layer"] == "overlay"       # a layer surface, not a window
        assert command["keyboard_focus"] == "none"  # never takes keyboard focus
        assert command["input_mode"] == "positive-allow"
        assert command["interactive_rects"] == []
        if command["visible"]:
            self.surfaces[command["namespace"]] = command
        else:
            self.surfaces.pop(command["namespace"], None)
        # Deliberately no mutation of self.focus.


class FakeRoot:
    """QML root properties the parsed handler bodies are allowed to touch."""

    def __init__(self) -> None:
        self.surfaceVisible = False
        self.targetX = 0
        self.targetY = 0
        self.targetWidth = 1
        self.targetHeight = 1


class FakeQuickshellIpc:
    """Models `qs ipc call` against the REAL IpcHandler block in shell.qml.

    It reads the typed function declarations from the shipped QML and runs
    their bodies against a fake QML root. The name `show` is registered by
    Quickshell's `ipc show` metadata path, not dispatched as a handler
    function: calling it returns the member list and changes nothing. That
    is the exact hardware failure this fake must reproduce.
    """

    RESERVED: ClassVar[frozenset[str]] = frozenset({"show"})

    def __init__(self, source: str) -> None:
        match = re.search(r"IpcHandler\s*\{(.*?)^    \}", source, re.DOTALL | re.MULTILINE)
        assert match, "no IpcHandler block in the shipped QML"
        self.block = match.group(1)
        self.target = re.search(r'target:\s*"([^"]+)"', self.block).group(1)
        self.root = FakeRoot()
        self.functions: dict[str, tuple[list[str], str]] = {}
        for fn in re.finditer(
            r"function\s+(\w+)\s*\(([^)]*)\)\s*:\s*(\w+)\s*\{(.*?)\}", self.block, re.DOTALL
        ):
            name, args, _return_type, body = fn.groups()
            params = [part.split(":", 1)[0].strip() for part in args.split(",") if part.strip()]
            self.functions[name] = (params, body)

    def member_list(self) -> str:
        lines = [f"target {self.target}"]
        for name in sorted(self.functions):
            if name not in self.RESERVED:
                lines.append(f"  function {name}")
        return "\n".join(lines)

    def call(self, target: str, name: str, *args: str) -> str:
        if target != self.target:
            return "Target not found."
        if name in self.RESERVED or name not in self.functions:
            return self.member_list()  # the observed failure, not an invocation
        params, body = self.functions[name]
        bound = dict(zip(params, args))
        for raw in body.splitlines():
            stmt = raw.strip().rstrip(";")
            if not stmt or stmt.startswith("//"):
                continue
            if match := re.fullmatch(r"return\s+root\.(\w+)", stmt):
                value = getattr(self.root, match.group(1))
                return "true" if value is True else "false"
            if match := re.fullmatch(r"root\.(\w+)\s*=\s*(true|false)", stmt):
                setattr(self.root, match.group(1), match.group(2) == "true")
            elif match := re.fullmatch(r"root\.(\w+)\s*=\s*(\w+)", stmt):
                setattr(self.root, match.group(1), bound[match.group(2)])
        return ""


def test_surface_is_wlr_layer_shell_not_a_normal_window():
    source = QML.read_text()
    assert "import Quickshell.Wayland" in source
    assert "PanelWindow {" in source
    assert "WlrLayershell.layer: WlrLayer.Overlay" in source
    assert f'WlrLayershell.namespace = "{NUS_NAMESPACE}"' in source
    assert "Component.onCompleted" in source  # deferred: avoid Quickshell #1411
    assert "WlrLayershell.namespace:" not in source
    assert "WlrLayershell.keyboardFocus: WlrKeyboardFocus.None" in source
    assert "exclusiveZone: -1" in source
    assert not re.search(r"keyboardFocus:\s*WlrKeyboardFocus\.(Exclusive|OnDemand)", source)
    assert "HyprlandFocusGrab" not in source
    assert "focuswindow" not in source
    assert NUS_LAYER == "overlay" and NUS_KEYBOARD_FOCUS == "none"


def test_clickthrough_is_positive_allow_not_negative_hole():
    source = QML.read_text()
    # A non-null mask is a positive allow list: only listed rects are clickable.
    assert re.search(r"mask:\s*Region\s*\{\s*\}", source), source
    assert "Xor" not in source                       # no inverted hole
    assert not re.search(r"mask:\s*Region\s*\{[^}]*\bitem\s*:", source)
    assert NUS_INPUT_MODE == "positive-allow"
    assert NusSurfaceController().show().interactive_rects == ()


def test_is_visible_turns_true_after_show_through_the_ipc_handler_path():
    """This fails on the old `show` declaration: it returns the member list.

    No fake surface dict: the fake dispatches the typed functions actually
    declared in shell.qml and executes their bodies against a QML root.
    """
    ipc = FakeQuickshellIpc(QML.read_text())
    assert ipc.target == "nus"
    assert ipc.call("nus", VISIBLE_COMMAND) == "false"

    # Reproduces the hardware failure: `show` is metadata, not a call.
    assert ipc.call("nus", "show") == ipc.member_list()
    assert ipc.call("nus", VISIBLE_COMMAND) == "false"

    assert ipc.call("nus", SHOW_COMMAND) == ""
    assert ipc.call("nus", VISIBLE_COMMAND) == "true"

    assert ipc.call("nus", HIDE_COMMAND) == ""
    assert ipc.call("nus", VISIBLE_COMMAND) == "false"


def test_controller_commands_match_the_handler_names():
    source = QML.read_text()
    assert 'target: "nus"' in source
    for name in (SHOW_COMMAND, HIDE_COMMAND, VISIBLE_COMMAND):
        assert re.search(rf"function\s+{name}\s*\(", source)
    shown = NusSurfaceController().show(120, 40, 240, 80)
    assert shown.visible and (shown.x, shown.y, shown.width, shown.height) == (120, 40, 240, 80)
    assert shown.as_dict()["keyboard_focus"] == "none"
    assert not NusSurfaceController().hide().visible


def test_focus_unchanged_after_overlay_appears():
    window = {"address": "0x5566", "class": "org.mozilla.firefox", "title": "notes"}
    hyprctl = FakeHyprctl(window)
    before = active_window(runner=hyprctl)
    assert before == window

    compositor = FakeCompositor(focus=before)
    controller = NusSurfaceController()
    ipc = FakeQuickshellIpc(QML.read_text())

    assert ipc.call("nus", SHOW_COMMAND) == ""
    compositor.apply(controller.show(120, 40, 240, 80).as_dict())
    after_show = active_window(runner=hyprctl)
    assert ipc.call("nus", VISIBLE_COMMAND) == "true"
    assert after_show == before                     # address, class, title identical
    assert compositor.focus == before
    assert NUS_NAMESPACE in compositor.surfaces     # the surface did appear

    assert ipc.call("nus", HIDE_COMMAND) == ""
    compositor.apply(controller.hide().as_dict())
    after_hide = active_window(runner=hyprctl)
    assert ipc.call("nus", VISIBLE_COMMAND) == "false"
    assert after_hide == before
    assert NUS_NAMESPACE not in compositor.surfaces  # and it disappeared
    assert len(hyprctl.calls) == 3                  # three reads, zero focus writes


def test_m1_does_not_capture_any_screen():
    sources = (QML.read_text() + (REPO / "src/assistant/nus_surface.py").read_text()).lower()
    for token in ("grim", "scrot", "ffmpeg", "screenshot", "screencopy", "framebuffer"):
        assert token not in sources
