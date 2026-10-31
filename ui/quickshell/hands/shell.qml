// Standalone synthetic harness targeting Quickshell 0.2.1. NOT console mounting.
// No Process, socket, external URL, storage, notification, or execution bridge.
import QtQuick
import QtQuick.Controls
import Quickshell
import "harness.js" as Harness

ShellRoot {
    FloatingWindow {
        id: preview
        visible: true
        implicitWidth: 700
        implicitHeight: 820
        color: "#211d15"

        property var sample: Harness.scenario("idle")
        readonly property var askCard: Harness.privateCard(preview.sample)
        readonly property string notificationText: Harness.notificationPreview(preview.sample) || ""
        property string interaction: "No backend is connected."
        property string capturedText: ""

        ScrollView {
            id: scroll
            anchors.fill: parent
            anchors.margins: 24
            clip: true

            Column {
                width: scroll.availableWidth
                spacing: 18

                Text {
                    text: "Elaria · home"
                    textFormat: Text.PlainText
                    color: "#efe6d3"
                    font.pixelSize: 30
                }
                Text {
                    width: parent.width
                    text: "Synthetic hands rehearsal · TESTED-ONLY logic / UNVERIFIED QML runtime"
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#e2a95f"
                }
                Text {
                    width: parent.width
                    text: "Synthetic text only. No files, model calls, approvals or commands are sent."
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#cfc2a6"
                }
                ComboBox {
                    model: Harness.scenarioNames()
                    onActivated: {
                        preview.sample = Harness.scenario(currentText)
                        preview.interaction = "Fixture changed. No backend is connected."
                        preview.capturedText = ""
                        intent.text = ""
                    }
                }
                Text {
                    width: parent.width
                    text: ["normal", "company", "class"].indexOf(preview.sample.posture) < 0 ? "the private preview is hidden" : preview.sample.heading
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#efe6d3"
                    font.pixelSize: 22
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
                            text: preview.askCard ? preview.askCard.paths.join("\n") : ""
                            textFormat: Text.PlainText
                            wrapMode: Text.WrapAnywhere
                            color: "#efe6d3"
                        }
                        Text {
                            width: parent.width
                            text: preview.askCard ? preview.askCard.disclosure : ""
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
                                text: "Yes · preview"
                                onClicked: preview.interaction = Harness.buttonPreview("yes", preview.sample)
                            }
                            Button {
                                text: "No · preview"
                                onClicked: preview.interaction = Harness.buttonPreview("no", preview.sample)
                            }
                        }
                    }
                }
                Text {
                    visible: preview.notificationText.length > 0
                    width: parent.width
                    text: preview.notificationText
                    textFormat: Text.PlainText
                    wrapMode: Text.WordWrap
                    color: "#e2a95f"
                }
                TextArea {
                    id: intent
                    visible: ["normal", "company", "class"].indexOf(preview.sample.posture) >= 0
                    width: parent.width
                    placeholderText: "A synthetic hands intention, or yes/no to inspect as data…"
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    color: "#efe6d3"
                }
                Button {
                    visible: ["normal", "company", "class"].indexOf(preview.sample.posture) >= 0
                    text: "Capture locally · preview only"
                    onClicked: {
                        var result = Harness.inputPreview(intent.text)
                        preview.capturedText = result.rawText
                        preview.interaction = Harness.routeInput(intent.text, preview.askCard).notice
                    }
                }
                Text {
                    visible: ["normal", "company", "class"].indexOf(preview.sample.posture) >= 0
                    width: parent.width
                    text: preview.capturedText
                    textFormat: Text.PlainText
                    wrapMode: Text.WrapAnywhere
                    color: "#cfc2a6"
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
