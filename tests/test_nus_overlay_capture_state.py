"""Lane H-OVERLAY eye-check: daemon capture.state drives the pill.

Fake-runner harness: recorded capture.state sequences are translated by
NusSurfaceController and dispatched against the REAL IpcHandler verbs
parsed out of shell.qml. Fails if the wiring (verb, mapping, or the
rendered pill) is removed. Rendering itself is the owner's eyes.
"""
from __future__ import annotations

import re
from pathlib import Path

from assistant.nus_surface import (
    CAPTURE_STATE_COMMAND,
    CAPTURE_STATE_VIEW,
    NusSurfaceController,
)

REPO = Path(__file__).resolve().parents[1]
QML = REPO / "ui/quickshell/nus/shell.qml"


def _handler_verbs(source: str) -> set[str]:
    block = re.search(r"IpcHandler\s*\{(.*?)^    \}", source,
                      re.DOTALL | re.MULTILINE).group(1)
    return set(re.findall(r"function\s+(\w+)\s*\(", block))


def test_capture_state_sequence_drives_surface_transitions():
    source = QML.read_text()
    assert CAPTURE_STATE_COMMAND in _handler_verbs(source)
    assert "root.captureState" in source  # the pill actually renders it

    controller = NusSurfaceController()
    seen = []
    for state in ("armed", "verifying", "open", "muted", "released"):
        cmd = controller.capture_state(state)
        seen.append((cmd.visible, cmd.capture_state))
    assert seen == [(True, "idle"), (True, "verifying"), (True, "listening"),
                    (True, "speaking"), (False, "idle")]


def test_unknown_capture_state_hides_rather_than_lies():
    cmd = NusSurfaceController().capture_state("some-future-state")
    assert cmd.visible is False
    assert set(CAPTURE_STATE_VIEW) == {
        "armed", "verifying", "open", "muted",
        "stalled", "unavailable", "released"}
