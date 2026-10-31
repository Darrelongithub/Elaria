// Standalone synthetic bridge, Quickshell 0.2.1; NEVER mounted in the frozen home.
// Socket/flush/SplitParser API checked against v0.2.1 upstream headers.
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import "harness.js" as Harness
import "bridge.js" as Bridge

ShellRoot {
    FloatingWindow {
        id: preview
        visible: true
        implicitWidth: 760
        implicitHeight: 900
        color: "#211d15"

        property var controller: Bridge.createController("c" + Date.now().toString(36)
            + Math.random().toString(36).slice(2, 10))
        property var sample: Bridge.disconnectedSnapshot()
        property string interaction: "Waiting for the synthetic bridge."
        property bool busy: false
        property bool ready: false
        readonly property var askCard: Harness.privateCard(preview.sample)
        readonly property bool privateVisible: ["normal", "company", "class"].indexOf(preview.sample.posture) >= 0
        readonly property string socketPath: Quickshell.env("ELARIA_HANDS_SOCKET")
            || (Quickshell.env("XDG_RUNTIME_DIR") ? Quickshell.env("XDG_RUNTIME_DIR") + "/elaria-hands.sock" : "")

        function sync() {
            preview.sample = preview.controller.snapshot
            preview.interaction = preview.controller.notice
            preview.busy = preview.controller.pending !== null
            preview.ready = preview.controller.connected && preview.controller.epoch !== null
            if (!preview.privateVisible) intent.text = ""
        }
        function send(frame) {
            if (frame && transport.connected) {
                transport.write(frame)
                transport.flush()
            }
            preview.sync()
        }
        function submit() {
            var dto = Harness.routeInput(intent.text, preview.askCard)
            preview.send(preview.controller.submit(dto, fixture.currentText, Date.now()))
            if (dto.kind !== "none") intent.text = ""
        }

        Socket {
            id: transport
            path: preview.socketPath
            connected: preview.socketPath.length > 0
            onConnectionStateChanged: {
                if (connected) preview.send(preview.controller.connect(Date.now()))
                else {
                    preview.controller.disconnect("The synthetic bridge disconnected; private content cleared.")
                    preview.sync()
                }
            }
            onError: {
                preview.controller.disconnect("The synthetic bridge is unavailable; no request was replayed.")
                preview.sync()
            }
            parser: SplitParser {
                onRead: data => {
                    preview.controller.receive(data)
                    preview.sync()
                    if (!preview.controller.connected) transport.connected = false
                }
            }
        }
        Timer {
            interval: 1000
            repeat: true
            running: true
            onTriggered: {
                if (!preview.controller.tick(Date.now())) transport.connected = false
                if (!transport.connected) transport.connected = preview.socketPath.length > 0
                else if (preview.ready && !preview.busy) preview.send(preview.controller.refresh(Date.now()))
                preview.sync()
            }
        }

        ScrollView {
            id: scroll
            anchors.fill: parent
            anchors.margins: 24
            clip: true
            Column {
                width: scroll.availableWidth
                spacing: 16
                Text {
                    text: "Elaria · home"
                    textFormat: Text.PlainText
                    color: "#efe6d3"
                    font.pixelSize: 30
                }
                Text {
                    width: parent.width
                    text: "Synthetic hands console · fake task runners · no live models or desktop notifications"
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#e2a95f"
                }
                Text {
                    width: parent.width
                    text: "Use synthetic text only. The fixture planner rehearses a fixed messy-folder errand, not arbitrary tasks."
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#cfc2a6"
                }
                Row {
                    spacing: 12
                    ComboBox {
                        id: posture
                        model: ["unknown", "normal", "company", "class", "locked"]
                        enabled: preview.ready && !preview.busy
                        onActivated: preview.send(preview.controller.posture(currentText, Date.now()))
                    }
                    ComboBox {
                        id: fixture
                        model: ["composite", "trap"]
                        enabled: preview.ready && !preview.busy && preview.privateVisible
                    }
                }
                Text {
                    width: parent.width
                    text: "Mock posture reported by bridge: " + preview.sample.posture
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#cfc2a6"
                }
                Text {
                    width: parent.width
                    text: preview.sample.heading
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#efe6d3"
                    font.pixelSize: 22
                }
                Repeater {
                    model: preview.privateVisible ? preview.sample.plan : []
                    delegate: Text {
                        required property var modelData
                        width: parent.width
                        text: "Step " + (modelData.i + 1) + " · T" + modelData.tier + " · " + modelData.tool
                            + "\nArgv: " + modelData.argv + "\nCwd: " + modelData.cwd
                            + "\nEnv diff: " + JSON.stringify(modelData.env_diff)
                        textFormat: Text.PlainText
                        wrapMode: Text.WrapAnywhere
                        color: "#cfc2a6"
                    }
                }
                Button {
                    text: "Start the disclosed synthetic plan"
                    visible: preview.privateVisible && preview.sample.phase === "ready"
                    enabled: preview.ready && !preview.busy
                    onClicked: preview.send(preview.controller.run(Date.now()))
                }
                Repeater {
                    model: Harness.visibleLines(preview.sample)
                    delegate: Text {
                        required property string modelData
                        width: parent.width
                        text: modelData
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        color: "#cfc2a6"
                    }
                }
                Repeater {
                    model: preview.privateVisible ? (preview.sample.events || []) : []
                    delegate: Text {
                        required property string modelData
                        width: parent.width
                        text: modelData
                        textFormat: Text.PlainText
                        wrapMode: Text.WordWrap
                        color: "#9c9078"
                    }
                }
                Rectangle {
                    visible: preview.askCard !== null
                    width: parent.width
                    height: cardContent.implicitHeight + 32
                    color: "#2a2418"
                    radius: 10
                    border.color: "#443c2a"
                    Column {
                        id: cardContent
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 16
                        spacing: 12
                        Text {
                            width: parent.width
                            text: preview.askCard ? Harness.ageLabel(preview.askCard.ageSeconds) : ""
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                            color: "#e2a95f"
                        }
                        Text {
                            width: parent.width
                            text: preview.askCard ? preview.askCard.disclosure : ""
                            textFormat: Text.PlainText
                            wrapMode: Text.WrapAnywhere
                            color: "#efe6d3"
                        }
                        Text {
                            width: parent.width
                            text: preview.askCard ? "Plan SHA-256: " + preview.askCard.planHash : ""
                            textFormat: Text.PlainText
                            wrapMode: Text.WrapAnywhere
                            color: "#cfc2a6"
                        }
                        Text {
                            width: parent.width
                            text: preview.askCard ? preview.askCard.warning : ""
                            textFormat: Text.PlainText
                            wrapMode: Text.WordWrap
                            color: "#cfc2a6"
                        }
                        Row {
                            spacing: 12
                            Button {
                                text: "Yes"
                                enabled: preview.ready && !preview.busy
                                onClicked: preview.send(preview.controller.button("yes", Date.now()))
                            }
                            Button {
                                text: "No"
                                enabled: preview.ready && !preview.busy
                                onClicked: preview.send(preview.controller.button("no", Date.now()))
                            }
                        }
                    }
                }
                Text {
                    width: parent.width
                    visible: !preview.privateVisible && preview.sample.askAgeSeconds !== null
                    text: "An ask remains parked. " + Harness.ageLabel(preview.sample.askAgeSeconds)
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#9c9078"
                }
                Text {
                    visible: preview.sample.notification !== null
                    width: parent.width
                    text: preview.sample.notification || ""
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#e2a95f"
                }
                TextArea {
                    id: intent
                    visible: preview.privateVisible
                    enabled: preview.ready && !preview.busy
                    width: parent.width
                    placeholderText: "A synthetic intention, or yes / no for the focused card…"
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    color: "#efe6d3"
                }
                Row {
                    visible: preview.privateVisible
                    spacing: 12
                    Button {
                        text: "Send to synthetic bridge"
                        enabled: preview.ready && !preview.busy
                        onClicked: preview.submit()
                    }
                    Button {
                        text: "Cancel at a step boundary"
                        enabled: preview.ready && !preview.busy
                        onClicked: preview.send(preview.controller.cancel(Date.now()))
                    }
                }
                Text {
                    width: parent.width
                    text: preview.interaction
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#9c9078"
                }
            }
        }
    }
}
