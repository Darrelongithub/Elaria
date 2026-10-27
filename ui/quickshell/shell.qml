// Elaria overlay — a floating dictation pill (§3.9, Phase 2).
//
// DUMB RENDERER BY DESIGN (§1.1): all state decisions live in
// assistant/overlay.py (tested headless). This file only binds:
//   visible ← state.visible · pulse ← state.pulsing · tone ← state.kind
//
// SIGNAL-ONLY SURFACE (notification privacy, owner order 2026-10-26):
// the pill shows a dot and a pulse — NEVER text. No caption, no check-in
// line, no error message, no topic or reason fragment. Content lives in
// the console (owner-raised), the journal and the inbox only. The feed's
// `text` field exists for those owner-raised consumers and is deliberately
// not bound here.
//
// WAYLAND NON-NEGOTIABLES (§3.3):
//   * layer-shell Overlay layer, passive — never exclusive, never modal
//   * keyboardFocus NONE — an overlay that steals focus mid-sentence is
//     worse than no overlay. Guarded by tests/test_phase2_surfaces.py.
//
// Feed: `assist events --overlay` (one JSON state per line).
// Run:  quickshell -p ui/quickshell   (or the elaria-overlay.service unit)
// STATUS: UNVERIFIED on real Quickshell/Hyprland — first run checklist is
// in ui/quickshell/README.md. If Process/SplitParser names differ in your
// Quickshell version, that's the only section that should need touching.

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    PanelWindow {
        id: pill

        // --- reactive state (bound from the JSON feed, see Process below) ---
        property bool stateVisible: false
        property string stateKind: "hidden"
        property bool statePulsing: false

        // --- layer-shell: present but never in the way ---
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "elaria-overlay"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusiveZone: -1

        anchors {
            bottom: true
        }
        margins.bottom: 28

        visible: stateVisible
        color: "transparent"
        implicitWidth: 56
        implicitHeight: 44

        Rectangle {
            anchors.fill: parent
            radius: 22
            color: pill.stateKind === "error" ? "#5a2230"
                 : pill.stateKind === "checkin" ? "#2c3550"
                 : "#1c1f2e"
            opacity: 0.92
            border.width: 1
            border.color: pill.stateKind === "listening" ? "#ff5555"
                        : pill.stateKind === "error" ? "#ff79c6"
                        : "#3b4261"

            // the signal: one dot, pulsing only while the mic is live
            Rectangle {
                id: dot
                width: 10; height: 10; radius: 5
                anchors.centerIn: parent
                color: pill.stateKind === "listening" || pill.stateKind === "checkin"
                     ? "#ff5555" : "#50fa7b"
                SequentialAnimation on opacity {
                    running: pill.statePulsing
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.25; duration: 550 }
                    NumberAnimation { to: 1.0; duration: 550 }
                }
            }
        }

        // --- the feed: one overlay-state JSON per line from the daemon CLI ---
        Process {
            id: feed
            running: true
            command: ["assist", "events", "--overlay"]
            stdout: SplitParser {
                onRead: line => {
                    try {
                        const state = JSON.parse(line);
                        pill.stateVisible = state.visible === true;
                        pill.stateKind = state.kind || "hidden";
                        pill.statePulsing = state.pulsing === true;
                        // the feed's text field is read nowhere: signal-only surface.
                    } catch (e) {
                        // Malformed line: ignore. The feed is trusted-local,
                        // but a partial line must never crash the shell.
                    }
                }
            }
            // Daemon restarts are normal (Restart=on-failure): reconnect.
            onExited: restartTimer.start()
        }
        Timer {
            id: restartTimer
            interval: 1500
            onTriggered: { feed.running = true; }
        }
    }
}
