// Elaria · console — a dumb renderer over `assist console --follow`.
//
// No logic lives here: every verdict (class mode, knocks, plans, holding,
// show-off) comes from the daemon snapshot. Sending a line calls
// `assist talk <text>`, which is the SAME handler the voice path uses, so
// there is still exactly one conversation.
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    PanelWindow {
        id: panel
        property var snap: ({
            conversation: {id: null, messages: []},
            pending_plans: [], parked_items: [], job_progress: [],
            offline_queue: {counts: {}, jobs: []}, holding: [],
            knocks: [], class_mode: {enabled: false},
            showoff: {active: false},
            counts: {pending_plans: 0, parked: 0, queue: 0,
                     holding: 0, knocks: 0}
        })
        property string draft: ""
        property string sendStatus: ""
        property bool feedUp: false

        function messages() {
            return (panel.snap.conversation && panel.snap.conversation.messages) || []
        }
        function parseSnapshot(line) {
            if (!line || line.trim().length === 0) return
            try {
                panel.snap = JSON.parse(line)
                panel.feedUp = true
                scrollTimer.restart()
            } catch (e) {
                panel.sendStatus = "feed parse error"
            }
        }
        function send() {
            var text = panel.draft.trim()
            if (text.length === 0 || sendProcess.running) return
            sendProcess.command = ["assist", "talk", text]
            sendProcess.running = true
            panel.sendStatus = "sent"
        }
        function knock(action, id) {
            knockProcess.command = ["assist", "knock", action, String(id)]
            knockProcess.running = true
        }

        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.namespace: "elaria-console"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
        exclusiveZone: -1
        anchors { top: true; right: true }
        margins.top: 12
        margins.right: 12
        implicitWidth: 460
        implicitHeight: 680
        color: "transparent"

        Rectangle {
            anchors.fill: parent
            radius: 14
            color: "#161922"
            border.color: "#2b3040"
            border.width: 1

            Column {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8

                // Header: mode is visible, never implied.
                Row {
                    width: parent.width
                    spacing: 8
                    Text {
                        text: "Elaria · console"
                        color: "#e6e9f5"
                        font.pixelSize: 16
                        font.bold: true
                    }
                    Rectangle {
                        visible: panel.snap.class_mode && panel.snap.class_mode.enabled
                        radius: 5
                        color: "#4a3a15"
                        width: classBadge.width + 10; height: 20
                        Text { id: classBadge; anchors.centerIn: parent
                               text: "CLASS MODE"; color: "#ffcb6b"
                               font.pixelSize: 10; font.bold: true }
                    }
                    Rectangle {
                        visible: panel.snap.showoff && panel.snap.showoff.active
                        radius: 5
                        color: "#3a1540"
                        width: demoBadge.width + 10; height: 20
                        Text { id: demoBadge; anchors.centerIn: parent
                               text: "SHOW-OFF"; color: "#e08cff"
                               font.pixelSize: 10; font.bold: true }
                    }
                    Text {
                        text: panel.feedUp ? "" : "daemon down"
                        color: "#ff6b6b"
                        font.pixelSize: 11
                    }
                }

                Text {
                    width: parent.width
                    text: "conversation #" + (panel.snap.conversation.id || "—")
                        + " · holding " + (panel.snap.counts.holding || 0)
                        + " · parked " + (panel.snap.counts.parked || 0)
                        + " · queue " + (panel.snap.counts.queue || 0)
                        + " · knocks " + (panel.snap.counts.knocks || 0)
                    color: "#8f97ad"
                    font.pixelSize: 11
                    elide: Text.ElideRight
                }

                // The knock shelf, reason first.
                Column {
                    width: parent.width
                    spacing: 3
                    visible: (panel.snap.knocks || []).length > 0
                    Text { text: "wants to talk"; color: "#ffb86c"
                           font.pixelSize: 12; font.bold: true }
                    Repeater {
                        model: panel.snap.knocks || []
                        delegate: Column {
                            width: parent.width
                            spacing: 2
                            Text {
                                width: parent.width
                                text: "#" + modelData.id + " [" + modelData.urgency
                                    + "] " + modelData.reason
                                color: "#e6e9f5"
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                            Row {
                                spacing: 6
                                Button {
                                    text: "accept"
                                    onClicked: panel.knock("accept", modelData.id)
                                }
                                Button {
                                    text: "later"
                                    onClicked: panel.knock("later", modelData.id)
                                }
                                Button {
                                    text: "decline"
                                    onClicked: panel.knock("decline", modelData.id)
                                }
                            }
                        }
                    }
                }

                // The one conversation. Voice and console turns interleave.
                Flickable {
                    id: feedFlick
                    width: parent.width
                    height: parent.height - 210
                    clip: true
                    contentWidth: width
                    contentHeight: feedColumn.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    Column {
                        id: feedColumn
                        width: feedFlick.width
                        spacing: 6
                        Repeater {
                            model: panel.messages()
                            delegate: Text {
                                width: feedColumn.width
                                text: (modelData.role === "user" ? "you" : "elaria")
                                    + " [" + (modelData.channel || "voice") + "]  "
                                    + modelData.text
                                color: modelData.role === "user" ? "#9fd2ff" : "#e6e9f5"
                                font.pixelSize: 12
                                wrapMode: Text.WordWrap
                            }
                        }
                    }
                }

                Timer {
                    id: scrollTimer
                    interval: 40
                    repeat: false
                    onTriggered: feedFlick.contentY = Math.max(
                        0, feedFlick.contentHeight - feedFlick.height)
                }

                // Everything else the snapshot carries, compactly.
                Text {
                    width: parent.width
                    visible: (panel.snap.pending_plans || []).length > 0
                    text: "plans: " + (panel.snap.pending_plans || []).map(
                        p => "#" + p.id + " " + p.placed + "/" + p.total).join(" · ")
                    color: "#8f97ad"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: (panel.snap.job_progress || []).length > 0
                    text: "jobs: " + (panel.snap.job_progress || []).map(
                        j => j.label + " " + j.status).join(" · ")
                    color: "#8f97ad"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: (panel.snap.holding || []).length > 0
                    text: "holding: " + (panel.snap.holding || []).map(
                        h => h.title).join(" · ")
                    color: "#8f97ad"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: (panel.snap.offline_queue
                              && Object.keys(panel.snap.offline_queue.counts || {}).length > 0)
                    text: "offline queue: " + JSON.stringify(
                        panel.snap.offline_queue.counts || {})
                    color: "#8f97ad"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }

                Row {
                    width: parent.width
                    spacing: 6
                    TextField {
                        id: draftField
                        width: parent.width - sendButton.width - 8
                        placeholderText: "talk to her — same conversation as voice"
                        color: "#e6e9f5"
                        placeholderTextColor: "#6c7488"
                        background: Rectangle { color: "#1e2230"; radius: 6 }
                        text: panel.draft
                        onTextChanged: panel.draft = text
                        onAccepted: panel.send()
                    }
                    Button {
                        id: sendButton
                        text: "send"
                        enabled: panel.draft.trim().length > 0
                        onClicked: panel.send()
                    }
                }
                Text {
                    width: parent.width
                    text: panel.sendStatus
                    color: "#8f97ad"; font.pixelSize: 10
                }
            }
        }

        // The feed: one snapshot per daemon event, plus reconnects.
        Process {
            id: feedProcess
            command: ["assist", "console", "--follow"]
            running: true
            stdout: SplitParser { onRead: line => panel.parseSnapshot(line) }
            onExited: {
                panel.feedUp = false
                feedRetry.start()
            }
        }
        Timer {
            id: feedRetry
            interval: 1500
            repeat: false
            onTriggered: feedProcess.running = true
        }
        Process {
            id: sendProcess
            onExited: {
                panel.draft = ""
                draftField.text = ""
                panel.sendStatus = ""
            }
        }
        Process {
            id: knockProcess
            onExited: panel.sendStatus = ""
        }
    }
}
