// NUS surface — M1 only (layer-shell, click-through, no focus, on command).
//
// This is a zwlr_layer_shell_v1 layer surface, NOT a normal Xdg window:
// Quickshell's PanelWindow is backed by WlrLayershell when running on a
// wlroots compositor (Hyprland). It sits on the Overlay layer, reserves no
// exclusive zone, and takes keyboardFocus None — Hyprland keeps the active
// window exactly as it was before the surface was mapped.
//
// INPUT IS A POSITIVE ALLOW LIST, NOT A NEGATIVE HOLE: `mask` names the only
// clickable rectangles. M1 has no interactive children, so the allow list is
// empty and every click passes through to the window behind the surface.
// Do not invert the intersection mode — that would turn the allow list into
// a hole and swallow clicks everywhere else.
//
// Appearance is command-driven through `qs ipc call nus show|hide`. M1 does
// no capture and no egress: there is no image reader or recorder here.

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    property bool surfaceVisible: false
    property string captureState: "idle"
    property int targetX: 24
    property int targetY: 24
    property int targetWidth: 220
    property int targetHeight: 56

    PanelWindow {
        id: nusSurface

        // --- zwlr_layer_shell_v1 posture ---
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "elaria-overlay"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusiveZone: -1

        anchors {
            left: true
            top: true
        }
        margins.left: root.targetX
        margins.top: root.targetY
        implicitWidth: root.targetWidth
        implicitHeight: root.targetHeight

        visible: root.surfaceVisible
        color: "transparent"

        // Positive allow list with zero allowed rects: fully click-through.
        mask: Region {}

        // The pill: a dumb renderer of the daemon's capture.state.
        // No decision logic here — text and colour bind to the state
        // string the daemon last sent; transitions only.
        Rectangle {
            anchors.fill: parent
            radius: 16
            color: root.captureState === "listening" ? "#1d4ed8"
                 : root.captureState === "verifying" ? "#b45309"
                 : root.captureState === "speaking" ? "#047857"
                 : root.captureState === "stalled" ? "#b91c1c"
                 : root.captureState === "unavailable" ? "#b91c1c"
                 : "#111827"
            opacity: root.captureState === "idle" ? 0.55 : 0.92

            Text {
                anchors.centerIn: parent
                text: "Elaria · " + root.captureState
                color: "#f9fafb"
                font.pixelSize: 15
            }
        }
    }

    IpcHandler {
        target: "nus"

        // PanelWindow inherits show() from QQuickWindow: a handler verb named
        // `show` is shadowed by that native method and never dispatches here.
        function reveal(): void { root.surfaceVisible = true }
        function hide(): void { root.surfaceVisible = false }
        function isVisible(): bool { return root.surfaceVisible }
        function setCaptureState(state: string): void { root.captureState = state }

        // Geometry only — the target shape is data, never a capture.
        function setTarget(x: int, y: int, width: int, height: int): void {
            root.targetX = x
            root.targetY = y
            root.targetWidth = width
            root.targetHeight = height
        }
    }
}
