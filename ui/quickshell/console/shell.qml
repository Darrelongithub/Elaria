// Elaria — her console (§19.1).
//
// A dedicated surface, not a second assistant. DUMB RENDERER by design:
// every field below comes from `assistant/console.py::ConsoleService.snapshot()`.
// The one conversation is shared with voice turns in the daemon's store; this
// panel never keeps its own history, so starting by voice and continuing here
// cannot fork context.
//
// Feed:  `assist console --follow`  (one JSON snapshot per line, on every
//        daemon event plus a periodic refresh)
// Send:  `assist talk "<text>"`     (same `_ask` handler the voice path uses)
//
// WAYLAND: layer-shell Top (not Overlay) because a console may take keyboard
// focus — but only OnDemand, so it never steals a keystroke from your editor
// until you click into the input.
//
// STATUS: UNVERIFIED on real Quickshell/Hyprland. If Process/SplitParser names
// differ in your Quickshell version, only the feed block needs adjusting.

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    PanelWindow {
        id: panel

        // --- state bound from the JSON feed ---------------------------------
        property var snap: ({
            conversation: {id: null, messages: []},
            pending_plans: [], parked_items: [], job_progress: [],
            offline_queue: {counts: {}, jobs: []}, holding: [],
            knocks: [], class_mode: {enabled: false}, showoff: {active: false},
            counts: {pending_plans: 0, parked: 0, queue: 0, holding: 0, knocks: 0}
        })
        property string draft: ""
        property string sendStatus: ""

        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.namespace: "elaria-console"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
        exclusiveZone: -1
        anchors { top: true; right: true }
        margins.top: 12
        margins.right: 12
        implicitWidth: 460
        implicitHeight: 640
        color: "transparent"

        Rectangle {
            anchors.fill: parent
            radius: 14
            color: "#151824"
            opacity: 0.97
            border.width: 1
            border.color: panel.snap.class_mode.enabled ? "#8be9fd" : "#3b4261"

            Column {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                // --- header: who/which mode, at a glance -------------------
                Row {
                    spacing: 8
                    Text {
                        text: "Elaria — console"
                        color: "#e6e9f5"
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Rectangle {
                        visible: panel.snap.class_mode.enabled
                        radius: 8
                        color: "#1f3b45"
                        width: classLabel.implicitWidth + 14
                        height: 20
                        Text {
                            id: classLabel
                            anchors.centerIn: parent
                            text: "CLASS MODE"
                            color: "#8be9fd"
                            font.pixelSize: 11
                            font.bold: true
                        }
                    }
                    Rectangle {
                        visible: panel.snap.showoff.active === true
                        radius: 8
                        color: "#4a2e1f"
                        width: showLabel.implicitWidth + 14
                        height: 20
                        Text {
                            id: showLabel
                            anchors.centerIn: parent
                            text: "SHOW-OFF"
                            color: "#ffb86c"
                            font.pixelSize: 11
                            font.bold: true
                        }
                    }
                }

                Text {
                    visible: panel.snap.class_mode.suggested === true
                    text: panel.snap.class_mode.suggestion || ""
                    color: "#6272a4"
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                    width: parent.width
                }

                // --- one conversation, both channels ----------------------
                Rectangle {
                    width: parent.width
                    height: 250
                    radius: 8
                    color: "#10121c"

                    Flickable {
                        anchors.fill: parent
                        anchors.margins: 8
                        clip: true
                        contentHeight: thread.implicitHeight
                        ScrollBar.vertical: ScrollBar {}

                        Column {
                            id: thread
                            width: parent.width
                            spacing: 6
                            Repeater {
                                model: panel.snap.conversation.messages || []
                                delegate: Text {
                                    width: thread.width
                                    wrapMode: Text.WordWrap
                                    font.pixelSize: 12
                                    color: modelData.role === "user" ? "#e6e9f5" : "#8be9fd"
                                    text: (modelData.role === "user" ? "you " : "elaria ")
                                        + "[" + (modelData.channel || "voice") + "]: "
                                        + modelData.text
                                }
                            }
                        }
                    }
                }

                // --- the knock shelf: reason is the first line ------------
                Column {
                    width: parent.width
                    spacing: 4
                    visible: (panel.snap.knocks || []).length > 0
                    Text { text: "wants to talk — the reason comes first"; color: "#ffb86c"; font.pixelSize: 12; font.bold: true }
                    Repeater {
                        model: panel.snap.knocks || []
                        delegate: Text {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            font.pixelSize: 12
                            color: "#e6e9f5"
                            text: "#" + modelData.id + " [" + modelData.urgency + "] "
                                + modelData.topic + ": " + modelData.reason
                                + "   (accept/decline/later in `assist talk`)"
                        }
                    }
                }

                // --- plans, parked items, queue, holding ------------------
                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    font.pixelSize: 12
                    color: "#c8cee8"
                    text: {
                        const parts = [];
                        const plans = panel.snap.pending_plans || [];
                        if (plans.length)
                            parts.push("plans: " + plans.map(p =>
                                "#" + p.id + " " + p.status + " " + p.placed + "/" + p.total).join(" · "));
                        if ((panel.snap.parked_items || []).length)
                            parts.push("parked for review: " + panel.snap.parked_items.length);
                        const q = panel.snap.offline_queue || {};
                        if (q.counts && Object.keys(q.counts).length)
                            parts.push("queue: " + Object.keys(q.counts).map(k => k + "=" + q.counts[k]).join(", "));
                        const jobs = panel.snap.job_progress || [];
                        if (jobs.length)
                            parts.push("running: " + jobs.map(j => j.label).join(" · "));
                        return parts.join("\n");
                    }
                }

                Column {
                    width: parent.width
                    spacing: 4
                    visible: (panel.snap.holding || []).length > 0
                    Text { text: "holding for you"; color: "#6272a4"; font.pixelSize: 11; font.bold: true }
                    Repeater {
                        model: panel.snap.holding || []
                        delegate: Text {
                            width: parent.width
                            wrapMode: Text.WordWrap
                            font.pixelSize: 12
                            color: "#c8cee8"
                            text: "• [" + modelData.kind + "] " + modelData.title
                                + (modelData.detail ? " — " + modelData.detail : "")
                        }
                    }
                }

                // --- input: text works in class mode too ------------------
                Row {
                    width: parent.width
                    spacing: 8
                    TextField {
                        id: input
                        width: parent.width - sendButton.width - 8
                        placeholderText: panel.snap.class_mode.enabled
                            ? "class mode — voice off, text on"
                            : "say something (voice or text, one conversation)"
                        color: "#e6e9f5"
                        background: Rectangle { color: "#10121c"; radius: 6 }
                        onAccepted: sendProcess.send()
                    }
                    Button {
                        id: sendButton
                        text: "Send"
                        enabled: input.text.trim().length > 0
                        onClicked: sendProcess.send()
                    }
                }

                Text {
                    text: panel.sendStatus
                    color: "#6272a4"
                    font.pixelSize: 10
                    width: parent.width
                    wrapMode: Text.WordWrap
                }
            }
        }

        // --- feed: one snapshot per line ---------------------------------
        Process {
            id: feed
            running: true
            command: ["assist", "console", "--follow"]
            stdout: SplitParser {
                onRead: line => {
                    try {
                        panel.snap = JSON.parse(line);
                    } catch (e) {
                        // A partial/malformed line must never crash the panel.
                    }
                }
            }
            onExited: restartTimer.start()
        }

        Timer {
            id: restartTimer
            interval: 1500
            onTriggered: { feed.running = true; }
        }

        // --- send: same handler as the voice path ------------------------
        Process {
            id: sendProcess
            property string pendingText: ""
            running: false
            function send() {
                const text = input.text.trim();
                if (!text) return;
                pendingText = text;
                panel.sendStatus = "sent";
                command = ["assist", "talk", text];
                running = true;
                input.text = "";
            }
            onExited: {
                panel.sendStatus = "";
                // The daemon broadcasts console.message; if the feed is between
                // reconnects, this immediate nudge keeps the panel current.
                refresh.running = true;
            }
        }

        Process {
            id: refresh
            running: false
            command: ["assist", "console", "--json"]
            stdout: SplitParser {
                onRead: line => {
                    try { panel.snap = JSON.parse(line); } catch (e) {}
                }
            }
        }
    }
}
