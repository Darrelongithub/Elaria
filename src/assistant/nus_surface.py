"""M1 of the NUS surface: a command-driven wlr-layer-shell surface policy.

The rendered surface is `ui/quickshell/nus/shell.qml` — a Quickshell
`PanelWindow` backed by `zwlr_layer_shell_v1`, not a normal window. This
module is the headless half: it builds the show/hide commands the QML
`IpcHandler` consumes and exposes the Hyprland focus probe used by the
M1 test. It deliberately knows nothing about pixels, image files
or external recorders — capture is M3 and out of scope here.

Invariants (also statically guarded in tests/test_nus_surface_m1.py):

  * layer is `overlay`, namespace `elaria-nus`, keyboard focus `none`;
  * input is a POSITIVE allow list; M1 has no interactive rects, so the
    allow list is empty and every click passes through;
  * `show()`/`hide()` only change visibility/geometry — never focus.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass

NUS_NAMESPACE = "elaria-overlay"
NUS_LAYER = "overlay"
NUS_KEYBOARD_FOCUS = "none"
NUS_INPUT_MODE = "positive-allow"

# PanelWindow inherits show() from QQuickWindow, so an IpcHandler function
# named `show` never registers as a callable verb. `reveal` is the verb that
# actually dispatches (verified on Hyprland with `hyprctl layers`).
SHOW_COMMAND = "reveal"
HIDE_COMMAND = "hide"
VISIBLE_COMMAND = "isVisible"
CAPTURE_STATE_COMMAND = "setCaptureState"

#: daemon `capture.state` -> (visible, label). The overlay is a dumb
#: renderer: the daemon is the only source of truth, indicators change
#: on transitions only, and `released` hides the pill. Unknown states
#: hide rather than guess — a lying indicator is worse than none.
CAPTURE_STATE_VIEW: dict[str, tuple[bool, str]] = {
    "armed": (True, "idle"),
    "verifying": (True, "verifying"),
    "open": (True, "listening"),
    "muted": (True, "speaking"),
    "stalled": (True, "stalled"),
    "unavailable": (True, "unavailable"),
    "released": (False, "idle"),
}

Runner = Callable[[list[str]], str]


@dataclass(frozen=True)
class SurfaceCommand:
    """One command sent to the QML surface over `qs ipc call nus ...`."""

    visible: bool
    x: int = 0
    y: int = 0
    width: int = 1
    height: int = 1
    layer: str = NUS_LAYER
    namespace: str = NUS_NAMESPACE
    keyboard_focus: str = NUS_KEYBOARD_FOCUS
    input_mode: str = NUS_INPUT_MODE
    interactive_rects: tuple[()] = ()
    capture_state: str = "idle"

    def as_dict(self) -> dict:
        data = asdict(self)
        data["interactive_rects"] = list(self.interactive_rects)
        return data


class NusSurfaceController:
    """Builds show/hide/geometry commands without touching focus or input."""

    def show(self, x: int = 0, y: int = 0, width: int = 1, height: int = 1) -> SurfaceCommand:
        if x < 0 or y < 0:
            raise ValueError("target origin must be non-negative")
        if width <= 0 or height <= 0:
            raise ValueError("target size must be positive")
        return SurfaceCommand(True, x, y, width, height)

    def hide(self) -> SurfaceCommand:
        return SurfaceCommand(False)

    def capture_state(self, state: str, x: int = 24, y: int = 24,
                      width: int = 220, height: int = 56) -> SurfaceCommand:
        """Translate one daemon `capture.state` into a surface command."""
        visible, label = CAPTURE_STATE_VIEW.get(
            str(state or "").strip(), (False, "idle"))
        return SurfaceCommand(visible, capture_state=label,
                              x=x, y=y, width=width, height=height)


def active_window(runner: Runner | None = None) -> dict[str, str]:
    """Hyprland's idea of focus: `hyprctl activewindow -j`.

    A layer surface with keyboardFocus None must leave this triple
    (address, class, title) byte-for-byte unchanged when it is mapped or
    unmapped. The runner is injectable so the M1 test can prove that
    without a live compositor.
    """
    args = ["hyprctl", "activewindow", "-j"]
    if runner is None:
        raw = subprocess.run(args, capture_output=True, text=True, check=True, timeout=2).stdout
    else:
        raw = runner(args)
    payload = json.loads(raw)
    return {
        "address": str(payload["address"]),
        "class": str(payload.get("class", "")),
        "title": str(payload.get("title", "")),
    }
