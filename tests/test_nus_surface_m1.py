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

from assistant.nus_surface import (
    NUS_INPUT_MODE,
    NUS_KEYBOARD_FOCUS,
    NUS_LAYER,
    NUS_NAMESPACE,
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


def test_surface_is_wlr_layer_shell_not_a_normal_window():
    source = QML.read_text()
    assert "import Quickshell.Wayland" in source
    assert "PanelWindow {" in source
    assert "WlrLayershell.layer: WlrLayer.Overlay" in source
    assert f'WlrLayershell.namespace: "{NUS_NAMESPACE}"' in source
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


def test_show_and_hide_are_commands_that_toggle_visibility():
    source = QML.read_text()
    assert 'target: "nus"' in source
    for line in (
        "function show(): void { root.surfaceVisible = true }",
        "function hide(): void { root.surfaceVisible = false }",
        "function isVisible(): bool { return root.surfaceVisible }",
    ):
        assert line in source

    controller = NusSurfaceController()
    shown = controller.show(120, 40, 240, 80)
    assert shown.visible and (shown.x, shown.y, shown.width, shown.height) == (120, 40, 240, 80)
    hidden = controller.hide()
    assert not hidden.visible
    assert shown.as_dict()["keyboard_focus"] == "none"


def test_focus_unchanged_after_overlay_appears():
    window = {"address": "0x5566", "class": "org.mozilla.firefox", "title": "notes"}
    hyprctl = FakeHyprctl(window)
    before = active_window(runner=hyprctl)
    assert before == window

    compositor = FakeCompositor(focus=before)
    controller = NusSurfaceController()
    compositor.apply(controller.show(120, 40, 240, 80).as_dict())
    after_show = active_window(runner=hyprctl)
    assert after_show == before                     # address, class, title identical
    assert compositor.focus == before
    assert NUS_NAMESPACE in compositor.surfaces     # the surface did appear

    compositor.apply(controller.hide().as_dict())
    after_hide = active_window(runner=hyprctl)
    assert after_hide == before
    assert NUS_NAMESPACE not in compositor.surfaces  # and it disappeared
    assert len(hyprctl.calls) == 3                  # three reads, zero focus writes


def test_m1_does_not_capture_any_screen():
    sources = (QML.read_text() + (REPO / "src/assistant/nus_surface.py").read_text()).lower()
    for token in ("grim", "scrot", "ffmpeg", "screenshot", "screencopy", "framebuffer"):
        assert token not in sources
