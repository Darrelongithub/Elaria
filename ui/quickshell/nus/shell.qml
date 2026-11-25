// NUS surface — layer-shell, click-through, no focus, on command.
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
    property bool pillSuspended: false
    property string pointScreen: ""
    property rect pointBounds
    property string pointLabel: ""
    property bool staticPoint: false
    property real phase: 0
    property bool pointVisible: false

    Timer {
        id: expiry
        onTriggered: root.pointVisible = false
    }
    NumberAnimation on phase {
        running: root.pointVisible && !root.staticPoint
        from: 0; to: 6.283185; duration: 2639
        loops: Animation.Infinite
    }
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

        visible: root.surfaceVisible && !root.pillSuspended
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

    Variants {
        model: Quickshell.screens
        delegate: PanelWindow {
            required property var modelData
            screen: modelData
            visible: root.pointVisible && screen.name === root.pointScreen
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "elaria-pointer"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
            exclusiveZone: -1
            anchors { top: true; bottom: true; left: true; right: true }
            color: "transparent"
            mask: Region {}

            Item {
                id: marker
                readonly property rect bounds: root.pointBounds
                x: bounds.x + bounds.width / 2
                y: bounds.y + bounds.height / 2
                readonly property real radius: Math.max(20,
                    Math.hypot(bounds.width, bounds.height) / 2 + 10)
                readonly property real breath: root.staticPoint ? 1 : 1 + .05 * Math.sin(root.phase)

                Rectangle {
                    x: -marker.bounds.width / 2 - 4
                    y: -marker.bounds.height / 2 - 4
                    width: marker.bounds.width + 8
                    height: marker.bounds.height + 8
                    radius: 6
                    color: "transparent"
                    border.color: "#e4d4ff"
                    border.width: 2
                }
                Canvas {
                    id: ring
                    width: Math.ceil(marker.radius * 2.2 + 4)
                    height: width
                    x: -width / 2; y: x
                    property real breath: marker.breath
                    property bool dashed: root.pointLabel.indexOf("best guess") >= 0
                    onBreathChanged: requestPaint()
                    onDashedChanged: requestPaint()
                    onWidthChanged: requestPaint()
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.clearRect(0, 0, width, height)
                        ctx.beginPath()
                        ctx.setLineDash(dashed ? [6, 5] : [])
                        ctx.arc(width / 2, height / 2, marker.radius * breath, 0, Math.PI * 2)
                        ctx.lineWidth = 2
                        ctx.strokeStyle = "#ac79ff"
                        ctx.stroke()
                    }
                }
                Rectangle {
                    width: 22; height: 22; radius: 11
                    x: -width / 2; y: -marker.radius * marker.breath - height / 2
                    gradient: Gradient {
                        GradientStop { position: 0; color: "#cdaaff" }
                        GradientStop { position: .45; color: "#9b2bff" }
                        GradientStop { position: 1; color: "#3b11a8" }
                    }
                }
                Text {
                    visible: root.pointLabel !== "sure"
                    x: -width / 2; y: marker.radius + 10
                    text: root.pointLabel
                    color: "white"
                    style: Text.Outline
                    styleColor: "#20102f"
                }
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
        function setCaptureState(state: string): void {
            root.captureState = state
            root.surfaceVisible = state !== "released"
        }
        function suspendPill(suspended: int): void { root.pillSuspended = suspended !== 0 }
        function pointAt(output: string, x: real, y: real, w: real, h: real,
                         label: string, ttl: int, reducedMotion: int): void {
            root.pointScreen = output
            root.pointBounds = Qt.rect(x, y, w, h)
            root.pointLabel = label
            root.staticPoint = reducedMotion !== 0
            root.pointVisible = true
            expiry.interval = Math.max(1, Math.min(ttl, 12000))
            expiry.restart()
        }
        function clearPoint(): void {
            expiry.stop()
            root.pointVisible = false
        }

        // Geometry only — the target shape is data, never a capture.
        function setTarget(x: int, y: int, width: int, height: int): void {
            root.targetX = x
            root.targetY = y
            root.targetWidth = width
            root.targetHeight = height
        }
    }
}
