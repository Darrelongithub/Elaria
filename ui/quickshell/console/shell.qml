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
            showoff: {active: false}, company: {company: false},
            counts: {pending_plans: 0, parked: 0, queue: 0,
                     holding: 0, knocks: 0}
        })
        property string draft: ""
        property string sendStatus: ""
        property bool feedUp: false
        property var eventSnap: ({running: false, active_speaker: "", document: "",
                                  segments: {}, calls: {}, disk: {}, quota: {}})
        property string eventTitle: ""
        property string eventRoster: ""
        property string eventCommand: ""
        property string transcriptText: ""
        property var transcriptLines: []
        property string activeDocumentPath: ""
        property string documentFingerprint: ""
        property var transcriptBlocks: []
        property bool editingDirty: false
        property bool editorFocused: false
        property string editStatus: ""
        property bool refreshAfterAction: false

        function txtPath(path) {
            return path.endsWith(".md") ? path.slice(0, -3) + ".txt" : path + ".txt"
        }
        function checkDocument(path) {
            var txt = txtPath(path)
            if (txt !== activeDocumentPath) {
                activeDocumentPath = txt
                documentFingerprint = ""
                transcriptText = ""
                transcriptBlocks = []
            }
            if (!documentStatProcess.running) {
                documentStatProcess.command = ["stat", "-c", "%s:%y", txt]
                documentStatProcess.running = true
            }
        }
        function eventAction(args) {
            refreshAfterAction = args[1] !== "status"
            eventProcess.command = ["assist"].concat(args)
            eventProcess.running = true
        }
        function parseTranscript() {
            if (panel.editingDirty || panel.editorFocused) return
            var lines = panel.transcriptText.split("\n")
            var blocks = []
            var current = null
            function finish() {
                if (current) {
                    current.text = current.lines.join("\n").replace(/^\n+|\n+$/g, "")
                    delete current.lines
                    blocks.push(current)
                }
            }
            for (var i = 0; i < lines.length; i++) {
                var line = lines[i]
                var match = line.match(/^## .* · .* · seg (\d+)/)
                if (match) {
                    finish()
                    current = {index: parseInt(match[1]), header: line, lines: []}
                } else if (current) current.lines.push(line)
            }
            finish()
            var same = blocks.length === panel.transcriptBlocks.length
            if (same) {
                for (var j = 0; j < blocks.length; j++) {
                    if (blocks[j].index !== panel.transcriptBlocks[j].index
                            || blocks[j].header !== panel.transcriptBlocks[j].header
                            || blocks[j].text !== panel.transcriptBlocks[j].text) {
                        same = false; break
                    }
                }
            }
            if (!same) panel.transcriptBlocks = blocks
        }
        function runEventWords(text) {
            var words = text.trim().toLowerCase()
            if (words === "speaker next") eventAction(["event", "speaker", "next"])
            else if (words === "stop event" || words === "event stop")
                eventAction(["event", "stop"])
            else if (words === "status" || words === "event status")
                eventAction(["event", "status"])
            else panel.sendStatus = "Try: status, speaker next, or stop event."
        }

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
        Component.onCompleted: eventRefresh.start()

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
                        visible: panel.snap.company && panel.snap.company.company
                        radius: 5
                        color: "#153a3a"
                        width: companyBadge.width + 10; height: 20
                        Text { id: companyBadge; anchors.centerIn: parent
                               text: "COMPANY"; color: "#7fe3d4"
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

                // Event notebook: commands call the same assist/daemon IPC doors
                // used by the CLI. The document remains the durable transcript.
                Rectangle {
                    width: parent.width; height: eventSnap.running ? 260 : (eventSnap.document ? 215 : 110)
                    radius: 12; color: "#24251f"
                    border.color: "#454333"; border.width: 1
                    Column {
                        anchors.fill: parent; anchors.margins: 12; spacing: 7
                        Text {
                            text: eventSnap.running
                                ? "Elaria is listening · " + eventSnap.active_speaker
                                  + " · " + Math.floor((eventSnap.segment_elapsed_s || 0) / 60)
                                  + ":" + ("0" + Math.floor((eventSnap.segment_elapsed_s || 0) % 60)).slice(-2)
                                  + " into this part"
                                : (eventSnap.document ? "Event stopped · " + eventSnap.title
                                                       : "Your event notebook")
                            color: "#f1e7d4"; font.pixelSize: 17
                            font.family: "serif"
                        }
                        Text {
                            visible: eventSnap.document
                            text: "Open the .txt in your editor; edit freely above the tail; new text arrives at the bottom."
                            color: "#c7bda9"; font.pixelSize: 11; wrapMode: Text.WordWrap
                            width: parent.width
                        }
                        Text {
                            visible: eventSnap.document
                            text: (eventSnap.segments.transcribed || 0) + " parts written"
                                + ((eventSnap.segments.queued || 0) > 0
                                   ? ", " + eventSnap.segments.queued + " catching up" : "")
                                + " · calls " + (eventSnap.calls.used || 0) + "/"
                                + (eventSnap.calls.budget || 0)
                                + " · disk " + Math.round((eventSnap.disk.free_bytes || 0)
                                    / 1073741824 * 10) / 10 + " GB free"
                                + " · " + eventSnap.route + " TPM "
                                + ((eventSnap.quota || {}).tpm_ceiling || "not published")
                                + " · " + panel.txtPath(eventSnap.document || "")
                            color: "#c7bda9"; font.pixelSize: 12; elide: Text.ElideMiddle
                            width: parent.width
                        }
                        Row {
                            spacing: 6; visible: !eventSnap.running
                            TextField { id: eventTitleField; width: 185; placeholderText: "Event title" }
                            TextField { id: eventRosterField; width: 185; placeholderText: "Names, comma separated" }
                        }
                        Row {
                            spacing: 4
                            CheckBox {
                                id: batteryConfirm; visible: !eventSnap.running
                                text: "Confirm battery"
                            }
                            Button {
                                text: "Start event"; visible: !eventSnap.running
                                onClicked: {
                                    var args = ["event", "start", "--title",
                                        eventTitleField.text || "Live event", "--speakers",
                                        eventRosterField.text || "Speaker 1"]
                                    if (batteryConfirm.checked) args.push("--battery-ok")
                                    panel.eventAction(args)
                                }
                            }
                            Button { text: "Next speaker"; visible: eventSnap.running
                                onClicked: panel.eventAction(["event", "speaker", "next"]) }
                            Button { text: "Stop event"; visible: eventSnap.running
                                onClicked: panel.eventAction(["event", "stop"]) }
                            Button { text: "Status"; onClicked: panel.eventAction(["event", "status"]) }
                            Button {
                                text: "Open .txt"; visible: eventSnap.document
                                onClicked: {
                                    editorProcess.command = ["xdg-open",
                                        panel.txtPath(eventSnap.document || "")]
                                    editorProcess.running = true
                                }
                            }
                        }
                        Row {
                            spacing: 4; visible: eventSnap.document
                            TextField { id: renameSelector; width: 52; placeholderText: "S2" }
                            TextField { id: renameName; width: 86; placeholderText: "New name" }
                            Button {
                                text: "Rename"; enabled: renameSelector.text.length > 0
                                    && renameName.text.trim().length > 0
                                onClicked: panel.eventAction(["event", "rename",
                                    renameSelector.text, renameName.text.trim()])
                            }
                            Button { text: "MD copy";
                                onClicked: panel.eventAction(["event", "export", "--format", "md"]) }
                            Button { text: "TXT copy";
                                onClicked: panel.eventAction(["event", "export", "--format", "txt"]) }
                        }
                        Row {
                            spacing: 5; visible: eventSnap.running
                            TextField {
                                id: newSpeakerField; width: 112
                                placeholderText: "Add speaker name"
                                onAccepted: {
                                    if (text.trim().length) {
                                        panel.eventAction(["event", "speaker", text.trim()])
                                        text = ""
                                    }
                                }
                            }
                            Button {
                                text: "Add"; enabled: newSpeakerField.text.trim().length > 0
                                onClicked: {
                                    panel.eventAction(["event", "speaker", newSpeakerField.text.trim()])
                                    newSpeakerField.text = ""
                                }
                            }
                            Flickable {
                                width: Math.max(80, parent.width - 174); height: 38
                                clip: true; contentWidth: rosterButtons.implicitWidth
                                contentHeight: height
                                Row {
                                    id: rosterButtons; spacing: 4
                                    Repeater {
                                        model: eventSnap.roster || []
                                        delegate: Button {
                                            text: modelData
                                            highlighted: modelData === eventSnap.active_speaker
                                            onClicked: panel.eventAction(["event", "speaker", modelData])
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                TextField {
                    width: parent.width; visible: eventSnap.running
                    placeholderText: "Your event command — status, speaker next, stop event"
                    onAccepted: { panel.runEventWords(text); text = "" }
                }
                Flickable {
                    id: eventTranscript
                    width: parent.width; height: eventSnap.running ? 190 : 0
                    visible: eventSnap.running; clip: true
                    contentWidth: width; contentHeight: transcriptColumn.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    Column {
                        id: transcriptColumn; width: parent.width; spacing: 10
                        Repeater {
                            model: panel.transcriptBlocks
                            delegate: Column {
                                id: segmentEditorDelegate
                                property string baseText: modelData.text
                                property string pendingText: ""
                                width: transcriptColumn.width
                                spacing: 3
                                Text {
                                    text: modelData.header
                                    color: "#d8c8a9"; font.pixelSize: 12
                                    font.family: "sans-serif"
                                }
                                TextArea {
                                    id: segmentEditor
                                    width: segmentEditorDelegate.width
                                    height: Math.max(68, implicitHeight)
                                    text: segmentEditorDelegate.baseText
                                    wrapMode: TextEdit.Wrap
                                    selectByMouse: true
                                    color: "#eee5d4"
                                    font.pixelSize: 15; font.family: "serif"
                                    background: Rectangle {
                                        color: "#2a2922"; radius: 6
                                        border.color: segmentEditor.activeFocus ? "#b8a77f" : "#454333"
                                    }
                                    onActiveFocusChanged: {
                                        panel.editorFocused = activeFocus
                                        if (!activeFocus) {
                                            panel.parseTranscript()
                                            editRefresh.start()
                                        }
                                    }
                                    onTextChanged: {
                                        if (!activeFocus || text === segmentEditorDelegate.baseText) return
                                        panel.editingDirty = true
                                        editSaveTimer.restart()
                                    }
                                }
                                Timer {
                                    id: editSaveTimer
                                    interval: 650; repeat: false
                                    onTriggered: {
                                        if (editProcess.running) { restart(); return }
                                        segmentEditorDelegate.pendingText = segmentEditor.text
                                        editProcess.command = ["assist", "event", "edit",
                                            "--segment", String(modelData.index),
                                            "--base-text=" + segmentEditorDelegate.baseText,
                                            "--text=" + segmentEditorDelegate.pendingText]
                                        editProcess.running = true
                                    }
                                }
                                Process {
                                    id: editProcess
                                    stdout: SplitParser {
                                        onRead: line => {
                                            try {
                                                var result = JSON.parse(line)
                                                panel.editStatus = result.state === "edited"
                                                    ? "Saved to the live document."
                                                    : "This segment changed; your edit was kept at the tail."
                                                segmentEditorDelegate.baseText = segmentEditorDelegate.pendingText
                                                panel.editingDirty = segmentEditor.text !== segmentEditorDelegate.baseText
                                                if (panel.editingDirty) editSaveTimer.start()
                                                else editRefresh.start()
                                            } catch (e) { panel.editStatus = line }
                                        }
                                    }
                                    stderr: SplitParser { onRead: line => panel.editStatus = line }
                                }
                            }
                        }
                        Text {
                            visible: panel.editStatus.length > 0
                            text: panel.editStatus
                            color: "#c7bda9"; font.pixelSize: 11
                        }
                    }
                }
                // The one conversation. Voice and console turns interleave.
                Flickable {
                    id: feedFlick
                    width: parent.width
                    height: eventSnap.running ? 0 : parent.height - 210
                    visible: !eventSnap.running
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
                    visible: !eventSnap.running && (panel.snap.pending_plans || []).length > 0
                    text: "plans: " + (panel.snap.pending_plans || []).map(
                        p => "#" + p.id + " " + p.placed + "/" + p.total).join(" · ")
                    color: "#8f97ad"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: !eventSnap.running && (panel.snap.job_progress || []).length > 0
                    text: "jobs: " + (panel.snap.job_progress || []).map(
                        j => j.label + " " + j.status).join(" · ")
                    color: "#8f97ad"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: !eventSnap.running && (panel.snap.holding || []).length > 0
                    text: "holding: " + (panel.snap.holding || []).map(
                        h => h.title).join(" · ")
                    color: "#8f97ad"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }
                Text {
                    width: parent.width
                    visible: !eventSnap.running && (panel.snap.offline_queue
                              && Object.keys(panel.snap.offline_queue.counts || {}).length > 0)
                    text: "offline queue: " + JSON.stringify(
                        panel.snap.offline_queue.counts || {})
                    color: "#8f97ad"; font.pixelSize: 11; wrapMode: Text.WordWrap
                }

                Row {
                    width: parent.width
                    visible: !eventSnap.running
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
        Process {
            id: eventProcess
            stdout: SplitParser {
                onRead: line => {
                    try {
                        var parsed = JSON.parse(line)
                        if (parsed.running !== undefined) {
                            panel.eventSnap = parsed
                            if (parsed.running && parsed.document)
                                panel.checkDocument(parsed.document)
                        }
                    } catch (e) { panel.sendStatus = line }
                }
            }
            stderr: SplitParser { onRead: line => panel.sendStatus = line }
            onExited: {
                if (panel.refreshAfterAction) {
                    panel.refreshAfterAction = false
                    panel.eventAction(["event", "status"])
                } else eventRefresh.start()
            }
        }
        Process {
            id: documentStatProcess
            stdout: SplitParser {
                onRead: line => {
                    if (line !== panel.documentFingerprint && panel.activeDocumentPath) {
                        panel.documentFingerprint = line
                        panel.transcriptText = ""
                        panel.transcriptLines = []
                        documentProcess.command = ["cat", panel.activeDocumentPath]
                        documentProcess.running = true
                    }
                }
            }
        }
        Process {
            id: documentProcess
            stdout: SplitParser {
                onRead: line => panel.transcriptLines.push(line)
            }
            onExited: {
                panel.transcriptText = panel.transcriptLines.join("\n") + "\n"
                panel.parseTranscript()
                transcriptScroll.restart()
            }
        }
        Process { id: editorProcess }
        Timer {
            id: transcriptScroll
            interval: 60; repeat: false
            onTriggered: eventTranscript.contentY = Math.max(0,
                eventTranscript.contentHeight - eventTranscript.height)
        }
        Timer {
            id: editRefresh
            interval: 120; repeat: false
            onTriggered: {
                if (!eventProcess.running) panel.eventAction(["event", "status"])
            }
        }
        Timer {
            id: eventRefresh
            interval: 1200; repeat: false
            onTriggered: {
                if (!eventProcess.running) panel.eventAction(["event", "status"])
            }
        }
    }
}
