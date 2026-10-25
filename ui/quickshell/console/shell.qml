// Elaria · home — the console she lives in (blueprint §19, owner requirement c).
//
// A DUMB RENDERER over `assist console --follow`, and deliberately so: every
// verdict (class mode, knocks, plans, holding, the event's own state, whether
// she heard anything) comes from the daemon snapshot. Nothing here decides
// anything. It only decides how what she already knows looks and reads.
//
// THE CONSOLE-HOME RULE (2026-10-25). This surface used to read like an admin
// panel: `plans:`, `jobs:`, `holding:`, a JSON blob, a command box, machine
// status in admin red. Now:
//
//   * no field labels and no empty colon rows — counts become sentences, and a
//     row with nothing in it is not on the page at all;
//   * the transcript is prose at book measure, the speakers named as people
//     ("Darrel said", "Elaria answered"), timestamps kept quiet;
//   * her input line is a passed note, not a command box;
//   * state changes fade, they never flash; failures are plain language —
//     never a stack trace, never a code, never admin red;
//   * warm paper, deep warm grey ink, one amber accent.
//
// Every phrase below that could have been a label is a sentence the snapshot
// supports: the silence hand-off line (`status_line`), which the hotfix put on
// the data surface and explicitly left for this round to render, is shown in
// her words verbatim and disappears the moment the daemon clears it.
//
// WHAT THIS ROUND DID NOT TOUCH — same wiring, command for command: the feed
// and its 1500 ms retry, `assist talk` (the SAME handler the voice path uses,
// so voice and text remain one conversation), the knock actions, every event
// control and its `assist event …` argument list, the append-only document
// mirror (stat fingerprint → cat → parse → diff → reload only on change), the
// embedded segment editors with their 650 ms autosave and stale-edit tail
// copy, `WlrKeyboardFocus.OnDemand`, and the systemd crash fallback. Dress,
// posture and typography only.
//
// REFERENCE BUILD (owner, 2026-10-25): Quickshell 0.2.1, revision dacfa9de,
// on Fedora with qt6-qtbase 6.11.2-3.fc44. Qt is >= 6.3, so the two inline
// `component` blocks below ARE supported. The gate failures were properties,
// not inline components: Row.topMargin, Text.leftPadding (static scan), then
// TextArea.lineHeight. Use anchor margins and Text-owned leading; TextArea
// inherits TextEdit, not Text. The fail-closed owner map covers EVERY type and
// binding here, but only the owner's ladder ON THE PR BRANCH proves loading.
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    PanelWindow {
        id: panel

        // ---- the page: paper, ink, one amber ---------------------------------
        readonly property color paper: "#211d15"
        readonly property color paperDeep: "#1b1811"
        readonly property color card: "#2a2418"
        readonly property color edge: "#443c2a"
        readonly property color ink: "#efe6d3"
        readonly property color inkSoft: "#cfc2a6"
        readonly property color quiet: "#9c9078"
        readonly property color faint: "#7d7360"
        readonly property color amber: "#e2a95f"

        // Her name and the word for this window, display only: the store keeps
        // role="user"/"assistant" and is never told either string.
        readonly property string ownerName: "Darrel"
        readonly property string houseName: "Elaria · home"

        // ---- what the daemon told us last (shapes unchanged) ------------------
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
        property string transcriptText: ""
        property var transcriptLines: []
        property string activeDocumentPath: ""
        property string documentFingerprint: ""
        property var transcriptBlocks: []
        property bool editingDirty: false
        property bool editorFocused: false
        property string editStatus: ""
        property bool refreshAfterAction: false

        // "Not answering" is reported, never inferred from a blank page: the
        // CLI keeps the feed alive and emits a daemon-down snapshot, and
        // feedUp only goes false if that process actually exits.
        readonly property bool daemonQuiet: !panel.feedUp
            || (panel.snap.daemon !== undefined && panel.snap.daemon.running === false)

        // ---- wiring: unchanged, all of it ------------------------------------
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
            else panel.sendStatus = "there are three things I can take here — status, "
                    + "speaker next, or stop event."
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
                // One JSON object per line; a torn line is a stutter, not a
                // fault of hers, and it is not her problem to read about.
                panel.sendStatus = "a line of her notes came through torn — the last "
                        + "whole one is still on the page."
            }
        }
        function send() {
            var text = panel.draft.trim()
            if (text.length === 0 || sendProcess.running) return
            sendProcess.command = ["assist", "talk", text]
            sendProcess.running = true
            panel.sendStatus = "she has it."
        }
        function knock(action, id) {
            knockProcess.command = ["assist", "knock", action, String(id)]
            knockProcess.running = true
        }

        // ---- phrasing only: every line below re-reads a fact the daemon ------
        // ---- already reported, and never adds a verdict ----------------------
        function clockOf(ts) {
            var match = String(ts || "").match(/(\d{2}:\d{2})/)
            return match ? match[1] : ""
        }
        function baseName(path) {
            var parts = String(path || "").split("/")
            return parts[parts.length - 1] || ""
        }
        function speakerOf(message) {
            if (message.role !== "user") return "Elaria answered"
            return panel.ownerName + (message.channel === "console" ? " wrote" : " said")
        }
        // `## 09:32 · Amina · seg 004 (recovered)` spoken as a heading, not a
        // log row. The raw header stays the parse key; only this display copy
        // is reworded.
        function segmentHeading(header) {
            var parts = String(header || "").replace(/^##\s*/, "").split(" · ")
            var last = parts.length > 0 ? String(parts[parts.length - 1]) : ""
            var seg = last.match(/seg 0*(\d+)/)
            var late = /recovered/.test(last) ? ", arrived late" : ""
            if (seg) {
                parts.pop()
                return parts.join(" · ") + " · part " + seg[1] + late
            }
            return parts.join(" · ") + late
        }

        // The shelf that used to be four labelled rows. One sentence per thing
        // worth saying; nothing to say means nothing on the page.
        function houseLines() {
            var s = panel.snap
            var out = []
            var plans = s.pending_plans || []
            for (var i = 0; i < plans.length; i++) {
                var p = plans[i]
                var progress = (p.placed || 0) + " of " + (p.total || 0) + " have their place"
                if (p.status === "building") {
                    out.push("plan #" + p.id + " is still being thought about — " + progress + ".")
                } else {
                    out.push("plan #" + p.id + " is ready whenever you are — " + progress
                             + ((p.abstained || 0) > 0
                                ? ", and " + p.abstained + " she would rather you decided on"
                                : "") + ".")
                }
            }
            var jobs = s.job_progress || []
            for (var j = 0; j < jobs.length; j++) {
                var job = jobs[j]
                // A plan that is still building arrives twice in the snapshot —
                // once in pending_plans, once in job_progress with the same
                // done/total. The plans sentence above says it; saying it twice
                // is the admin panel talking to itself.
                if (job.kind === "plan") continue
                var doing = job.status === "running" ? "is going"
                          : job.status === "awaiting_approval" ? "is waiting on a yes from you"
                          : job.status === "approved" ? "is queued and approved"
                          : "is next in line"
                out.push("the " + String(job.kind || "job").replace(/_/g, " ") + " job " + doing
                         + (job.total ? " — " + (job.done || 0) + " of " + job.total + " done" : "")
                         + (job.attempts > 0 ? ", on attempt " + (job.attempts + 1) : "") + ".")
            }
            var held = s.holding || []
            if (held.length > 0) {
                var titles = []
                for (var h = 0; h < held.length && h < 3; h++) titles.push(held[h].title)
                out.push("she is holding " + held.length
                         + (held.length === 1 ? " thing for you" : " things for you") + " — "
                         + titles.join(", ")
                         + (held.length > 3 ? ", and " + (held.length - 3) + " more" : "") + ".")
            }
            var parked = s.parked_items || []
            if (parked.length > 0) {
                out.push(parked.length + (parked.length === 1
                                          ? " thing is parked where only you can sort it"
                                          : " things are parked where only you can sort them")
                         + " — " + panel.baseName(parked[0].src)
                         + (parked.length > 1 ? ", and " + (parked.length - 1) + " others" : "") + ".")
            }
            return out
        }

        // The event notebook, spoken rather than reported.
        function eventHeadline() {
            var e = panel.eventSnap
            if (panel.daemonQuiet && (e.running || e.document))
                return "the mic went quiet — she is not answering, so nothing new is "
                        + "being written on this page."
            if (e.running) {
                var secs = Math.floor(e.segment_elapsed_s || 0)
                var into = Math.floor(secs / 60) + ":" + ("0" + (secs % 60)).slice(-2)
                return "Elaria is listening — " + (e.active_speaker || "no one has the floor yet")
                        + ", " + into + " into this part."
            }
            if (e.document) return "the event is closed — " + (e.title || "no title") + "."
            return "the notebook is shut — nothing is being written."
        }
        function eventProgress() {
            var e = panel.eventSnap
            var seg = e.segments || {}
            var written = seg.transcribed || 0
            var catching = seg.queued || 0
            var kept = seg.deferred || 0
            if (!e.running && !e.document) return ""
            if (written === 0 && catching === 0 && kept === 0)
                return "nothing has landed yet — the first part closes after "
                        + Math.round(e.segment_minutes || 30) + " minutes."
            var line = written + (written === 1 ? " part written" : " parts written")
            if (catching > 0) line += ", " + catching + " catching up"
            if (kept > 0) line += ", " + kept + " kept as audio for later"
            return line + "."
        }
        function eventFootnote() {
            var e = panel.eventSnap
            var bits = []
            var calls = e.calls || {}
            if (calls.budget) {
                bits.push(calls.used + " of today's " + calls.budget + " calls used"
                          + ((calls.reserve || 0) > 0
                             ? ", " + calls.reserve + " held back for the closing part" : ""))
            }
            var quota = e.quota || {}
            bits.push(quota.tpm_ceiling
                      ? "the route allows " + quota.tpm_ceiling + " tokens a minute, staying under "
                        + Math.round(quota.tpm_ceiling * (quota.headroom || 1))
                      : "this route publishes no per-minute ceiling")
            if (e.disk && e.disk.free_bytes)
                bits.push((e.disk.free_bytes / 1073741824).toFixed(1)
                          + " GB free where the audio lives")
            if (quota.next_reset_eat) bits.push("today's count resets at " + quota.next_reset_eat)
            if (e.transport) bits.push(e.transport)
            return bits.join(" · ")
        }
        // Machine noise never reaches her page. Plain words, or nothing.
        function plainNote(line) {
            var text = String(line || "").trim()
            if (text.length === 0) return ""
            if (/Traceback \(most recent call last\)/.test(text)
                    || /\.py"?,? line \d+/.test(text)
                    || /^[A-Za-z_.]*(Error|Exception)\b/.test(text)
                    || /^\s*[{[]/.test(text))
                return "that did not go through — the event itself is untouched. "
                        + "The detail is in her journal, not on this page."
            return text
        }

        // ---- the window: layer-shell posture is NOT dress, and is unchanged ---
        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.namespace: "elaria-console"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand
        exclusiveZone: -1
        anchors { top: true; right: true }
        margins.top: 12
        margins.right: 12
        implicitWidth: 500
        implicitHeight: 700
        color: "transparent"
        Component.onCompleted: eventRefresh.start()

        Rectangle {
            id: page
            anchors.fill: parent
            radius: 16
            color: panel.paper
            border.color: panel.edge
            border.width: 1

            // A lamp rather than a texture: the top of the page catches light.
            Rectangle {
                anchors.fill: parent
                radius: 16
                border.width: 0
                gradient: Gradient {
                    GradientStop { position: 0.0; color: "#2b2519" }
                    GradientStop { position: 0.55; color: panel.paper }
                    GradientStop { position: 1.0; color: panel.paperDeep }
                }
            }

            // Every conditional block carries an explicit height, so the prose
            // gets exactly the room that is left: no fixed arithmetic, no strip
            // of blank space where a sentence used to sit.
            readonly property real chrome: headerBlock.implicitHeight
                + lastWordLine.height + quietNotice.height + knockShelf.height
                + eventCard.height + eventLine.height + houseShelf.height
                + draftRow.height + statusLine.height + 9 * 10
            readonly property real proseHeight: Math.max(120, panel.height - page.chrome - 10)

            Column {
                anchors.fill: parent
                anchors.margins: 16
                spacing: 10

                // Header: her name as a heading, the modes as words. A mode
                // that is on is always visible — never implied by absence.
                Column {
                    id: headerBlock
                    width: parent.width
                    spacing: 3
                    Text {
                        text: panel.houseName
                        color: panel.ink
                        font.pixelSize: 20
                        font.family: "serif"
                        font.letterSpacing: 0.3
                        Behavior on color { ColorAnimation { duration: 240 } }
                    }
                    Text {
                        width: parent.width
                        text: "one conversation — said out loud or written here, the same to her"
                        color: panel.quiet
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }
                    Item {
                        width: parent.width
                        height: modeWords.implicitHeight + 2
                        Row {
                            id: modeWords
                            width: parent.width
                            anchors.top: parent.top
                            anchors.topMargin: 2
                            spacing: 10
                            Repeater {
                                model: [
                                    {show: panel.snap.class_mode && panel.snap.class_mode.enabled,
                                     word: "class mode · voice off"},
                                    {show: panel.snap.company && panel.snap.company.company,
                                     word: "company · mind what is said"},
                                    {show: panel.snap.showoff && panel.snap.showoff.active,
                                     word: "showing off · the room can hear"}
                                ]
                                delegate: Rectangle {
                                    radius: 7
                                    color: "#3b3220"
                                    border.color: "#554729"
                                    border.width: 1
                                    height: modeWord.implicitHeight + 6
                                    opacity: modelData.show ? 1.0 : 0.0
                                    visible: opacity > 0.001
                                    Behavior on opacity { NumberAnimation { duration: 280; easing.type: Easing.OutQuad } }
                                    Text {
                                        id: modeWord
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.left: parent.left
                                        anchors.leftMargin: 7
                                        anchors.right: parent.right
                                        anchors.rightMargin: 7
                                        text: modelData.word
                                        color: panel.amber
                                        font.pixelSize: 10
                                        elide: Text.ElideRight
                                    }
                                }
                            }
                        }
                    }
                }

                // The hotfix's hand-off: her own words about the last voice
                // session, kept exactly as she wrote them, gone when cleared.
                Text {
                    id: lastWordLine
                    width: parent.width
                    text: String((panel.snap && panel.snap.status_line) || "")
                    font.pixelSize: 12
                    font.family: "serif"
                    font.italic: true
                    wrapMode: Text.WordWrap
                    lineHeight: 1.35
                    color: panel.amber
                    opacity: text.length > 0 ? 1.0 : 0.0
                    visible: opacity > 0.001
                    height: visible ? implicitHeight : 0
                    Behavior on opacity { NumberAnimation { duration: 320; easing.type: Easing.OutQuad } }
                }

                // Failure, in her language. No red, no code, no stack.
                Text {
                    id: quietNotice
                    width: parent.width
                    text: panel.daemonQuiet
                          ? "she is not answering right now — nothing typed here goes anywhere, "
                            + "and this window keeps knocking on her door."
                          : ""
                    color: panel.amber
                    font.pixelSize: 11
                    font.family: "serif"
                    wrapMode: Text.WordWrap
                    lineHeight: 1.35
                    opacity: text.length > 0 ? 1.0 : 0.0
                    visible: opacity > 0.001
                    height: visible ? implicitHeight : 0
                    Behavior on opacity { NumberAnimation { duration: 340 } }
                }

                // The knock shelf, her reason first.
                Column {
                    id: knockShelf
                    width: parent.width
                    spacing: 4
                    opacity: (panel.snap.knocks || []).length > 0 ? 1.0 : 0.0
                    visible: opacity > 0.001
                    height: visible ? implicitHeight : 0
                    Behavior on opacity { NumberAnimation { duration: 280; easing.type: Easing.OutQuad } }
                    Text {
                        text: (panel.snap.knocks || []).length === 1
                              ? "she would like a word"
                              : "she would like a word — " + (panel.snap.knocks || []).length + " waiting"
                        color: panel.amber
                        font.pixelSize: 12
                        font.family: "serif"
                        font.bold: true
                    }
                    Repeater {
                        model: panel.snap.knocks || []
                        delegate: Column {
                            width: parent.width
                            spacing: 2
                            Text {
                                width: parent.width
                                text: (modelData.urgency === "urgent" ? "urgent — " : "")
                                    + modelData.reason
                                color: panel.ink
                                font.pixelSize: 13
                                font.family: "serif"
                                wrapMode: Text.WordWrap
                                lineHeight: 1.4
                            }
                            Text {
                                width: parent.width
                                text: (modelData.topic ? "about " + modelData.topic + " · " : "")
                                    + (modelData.referent ? modelData.referent + " · " : "")
                                    + "knock " + modelData.id
                                color: panel.faint
                                font.pixelSize: 10
                                elide: Text.ElideRight
                            }
                            Row {
                                spacing: 8
                                HomeButton {
                                    text: "accept"
                                    onClicked: panel.knock("accept", modelData.id)
                                }
                                HomeButton {
                                    text: "later"
                                    onClicked: panel.knock("later", modelData.id)
                                }
                                HomeButton {
                                    text: "decline"
                                    onClicked: panel.knock("decline", modelData.id)
                                }
                            }
                        }
                    }
                }

                // The event notebook: the same doors the CLI uses, in a quieter
                // voice. Every control below runs the identical `assist event …`
                // command it ran before this round; only its words changed.
                Rectangle {
                    id: eventCard
                    width: parent.width
                    radius: 12
                    color: panel.card
                    border.color: panel.edge
                    border.width: 1
                    // Self-measuring, so a longer sentence can never clip the
                    // buttons under it.
                    height: Math.max(eventSnap.running ? 150 : 74,
                                     eventCardColumn.implicitHeight + 26)
                    Behavior on color { ColorAnimation { duration: 300 } }

                    Column {
                        id: eventCardColumn
                        anchors.fill: parent
                        anchors.margins: 13
                        spacing: 7

                        Text {
                            width: parent.width
                            text: panel.eventHeadline()
                            color: panel.ink
                            font.pixelSize: 16
                            font.family: "serif"
                            wrapMode: Text.WordWrap
                            lineHeight: 1.3
                            Behavior on color { ColorAnimation { duration: 300 } }
                        }
                        Text {
                            width: parent.width
                            text: panel.eventProgress()
                            color: panel.amber
                            font.pixelSize: 12
                            font.family: "serif"
                            wrapMode: Text.WordWrap
                            lineHeight: 1.35
                            opacity: text.length > 0 ? 1.0 : 0.0
                            visible: opacity > 0.001
                            height: visible ? implicitHeight : 0
                            Behavior on opacity { NumberAnimation { duration: 280 } }
                        }
                        Text {
                            width: parent.width
                            text: "Open the .txt in your editor; edit freely above the tail; new text arrives at the bottom."
                            color: panel.inkSoft
                            font.pixelSize: 11
                            font.family: "serif"
                            wrapMode: Text.WordWrap
                            lineHeight: 1.35
                            opacity: eventSnap.document ? 1.0 : 0.0
                            visible: opacity > 0.001
                            height: visible ? implicitHeight : 0
                            Behavior on opacity { NumberAnimation { duration: 280 } }
                        }
                        Text {
                            width: parent.width
                            text: panel.eventFootnote()
                            color: panel.quiet
                            font.pixelSize: 10
                            wrapMode: Text.WordWrap
                            lineHeight: 1.35
                            opacity: text.length > 0 && (eventSnap.running || eventSnap.document) ? 1.0 : 0.0
                            visible: opacity > 0.001
                            height: visible ? implicitHeight : 0
                            Behavior on opacity { NumberAnimation { duration: 280 } }
                        }
                        Text {
                            width: parent.width
                            text: "the page she is writing on — " + panel.txtPath(eventSnap.document || "")
                            color: panel.faint
                            font.pixelSize: 10
                            elide: Text.ElideMiddle
                            opacity: eventSnap.document ? 1.0 : 0.0
                            visible: opacity > 0.001
                            height: visible ? implicitHeight : 0
                            Behavior on opacity { NumberAnimation { duration: 280 } }
                        }

                        // While nothing is running: two notes to fill in, in her words.
                        Row {
                            spacing: 8
                            visible: !eventSnap.running
                            height: visible ? 36 : 0
                            NoteField {
                                id: eventTitleField
                                width: 190
                                placeholderText: "what she is calling this event"
                            }
                            NoteField {
                                id: eventRosterField
                                width: 190
                                placeholderText: "who is speaking, in order"
                            }
                        }
                        // Opening an event: two notes and one confirmation.
                        Row {
                            spacing: 8
                            visible: !eventSnap.running
                            height: visible ? 34 : 0
                            CheckBox {
                                id: batteryConfirm
                                text: "the charger is in — battery confirmed"
                                contentItem: Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 4
                                    anchors.right: parent.right
                                    text: parent.text
                                    color: panel.inkSoft
                                    font.pixelSize: 11
                                    verticalAlignment: Text.AlignVCenter
                                }
                            }
                            HomeButton {
                                text: "Start event"
                                onClicked: {
                                    var args = ["event", "start", "--title",
                                        eventTitleField.text || "Live event", "--speakers",
                                        eventRosterField.text || "Speaker 1"]
                                    if (batteryConfirm.checked) args.push("--battery-ok")
                                    panel.eventAction(args)
                                }
                            }
                        }
                        // Running or not: these two are always within reach.
                        Row {
                            spacing: 6
                            HomeButton { text: "Next speaker"; visible: eventSnap.running
                                onClicked: panel.eventAction(["event", "speaker", "next"]) }
                            HomeButton { text: "Stop event"; visible: eventSnap.running
                                onClicked: panel.eventAction(["event", "stop"]) }
                            HomeButton { text: "Status"; onClicked: panel.eventAction(["event", "status"]) }
                            HomeButton {
                                text: "Open .txt"; visible: eventSnap.document
                                onClicked: {
                                    editorProcess.command = ["xdg-open",
                                        panel.txtPath(eventSnap.document || "")]
                                    editorProcess.running = true
                                }
                            }
                        }
                        Row {
                            spacing: 6
                            visible: eventSnap.document
                            height: visible ? 36 : 0
                            NoteField {
                                id: renameSelector
                                width: 60
                                placeholderText: "S2"
                            }
                            NoteField {
                                id: renameName
                                width: 116
                                placeholderText: "their new name"
                            }
                            HomeButton {
                                text: "Rename"; enabled: renameSelector.text.length > 0
                                    && renameName.text.trim().length > 0
                                onClicked: panel.eventAction(["event", "rename",
                                    renameSelector.text, renameName.text.trim()])
                            }
                            HomeButton { text: "MD copy";
                                onClicked: panel.eventAction(["event", "export", "--format", "md"]) }
                            HomeButton { text: "TXT copy";
                                onClicked: panel.eventAction(["event", "export", "--format", "txt"]) }
                        }
                        Row {
                            spacing: 5
                            visible: eventSnap.running
                            height: visible ? 36 : 0
                            NoteField {
                                id: newSpeakerField; width: 128
                                placeholderText: "a name to add"
                                onAccepted: {
                                    if (text.trim().length) {
                                        panel.eventAction(["event", "speaker", text.trim()])
                                        text = ""
                                    }
                                }
                            }
                            HomeButton {
                                text: "Add"; enabled: newSpeakerField.text.trim().length > 0
                                onClicked: {
                                    panel.eventAction(["event", "speaker", newSpeakerField.text.trim()])
                                    newSpeakerField.text = ""
                                }
                            }
                            Flickable {
                                width: Math.max(80, parent.width - 196); height: 34
                                clip: true; contentWidth: rosterButtons.implicitWidth
                                contentHeight: height
                                boundsBehavior: Flickable.StopAtBounds
                                Row {
                                    id: rosterButtons; spacing: 6
                                    Repeater {
                                        model: eventSnap.roster || []
                                        delegate: HomeButton {
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

                // During an event she still takes three words. A note, not a prompt.
                NoteField {
                    id: eventLine
                    width: parent.width
                    placeholderText: "write to her — status, speaker next, stop event"
                    visible: eventSnap.running
                    height: visible ? 38 : 0
                    onAccepted: { panel.runEventWords(text); text = "" }
                }

                // The live page, as prose. Segment bodies are the document's own
                // text and are never re-worded; only the heading above each one
                // is read back as a person, a time and a part.
                Flickable {
                    id: eventTranscript
                    width: parent.width
                    height: eventSnap.running ? page.proseHeight : 0
                    visible: eventSnap.running
                    clip: true
                    contentWidth: width
                    contentHeight: transcriptColumn.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    Column {
                        id: transcriptColumn; width: parent.width; spacing: 14
                        Repeater {
                            model: panel.transcriptBlocks
                            delegate: Column {
                                id: segmentEditorDelegate
                                property string baseText: modelData.text
                                property string pendingText: ""
                                width: transcriptColumn.width
                                spacing: 4
                                Text {
                                    width: parent.width
                                    text: panel.segmentHeading(modelData.header)
                                    color: panel.quiet
                                    font.pixelSize: 11
                                    font.family: "serif"
                                    elide: Text.ElideRight
                                }
                                TextArea {
                                    id: segmentEditor
                                    width: segmentEditorDelegate.width
                                    height: Math.max(68, activeFocus ? implicitHeight
                                        : segmentProse.implicitHeight + topPadding + bottomPadding)
                                    text: segmentEditorDelegate.baseText
                                    textFormat: TextEdit.PlainText
                                    wrapMode: TextEdit.Wrap
                                    selectByMouse: true
                                    color: activeFocus ? panel.ink : "transparent"
                                    font.pixelSize: 15
                                    font.family: "serif"
                                    // TextArea inherits TextEdit, not Text: no lineHeight
                                    // on the reference build. The unfocused page owns its
                                    // leading in Text; focus reveals the SAME plain-text
                                    // editor with native caret/selection line metrics.
                                    // Text handles no pointer events, so clicks still
                                    // reach the editor. No rich-text conversion or extra
                                    // save path; show pending edits, not a stale baseText.
                                    Text {
                                        id: segmentProse
                                        x: segmentEditor.leftPadding
                                        y: segmentEditor.topPadding
                                        width: segmentEditor.width - segmentEditor.leftPadding
                                            - segmentEditor.rightPadding
                                        visible: !segmentEditor.activeFocus
                                        text: segmentEditor.text
                                        textFormat: Text.PlainText
                                        font: segmentEditor.font
                                        color: panel.ink
                                        wrapMode: Text.Wrap
                                        lineHeight: 1.5
                                    }
                                    background: Rectangle {
                                        color: "#2f2919"; radius: 8
                                        border.width: 1
                                        border.color: segmentEditor.activeFocus ? panel.amber : panel.edge
                                        Behavior on border.color { ColorAnimation { duration: 240 } }
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
                                            } catch (e) { panel.editStatus = panel.plainNote(line) }
                                        }
                                    }
                                    stderr: SplitParser { onRead: line => panel.editStatus = panel.plainNote(line) }
                                }
                            }
                        }
                        Text {
                            visible: panel.editStatus.length > 0
                            height: visible ? implicitHeight : 0
                            text: panel.editStatus
                            color: panel.quiet
                            font.pixelSize: 10
                            font.family: "serif"
                        }
                    }
                }

                // The one conversation, set as prose. Voice turns and console
                // turns interleave here because they are the same store.
                Flickable {
                    id: feedFlick
                    width: parent.width
                    height: eventSnap.running ? 0 : page.proseHeight
                    visible: !eventSnap.running
                    clip: true
                    contentWidth: width
                    contentHeight: feedColumn.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    Column {
                        id: feedColumn
                        width: feedFlick.width
                        spacing: 13
                        Text {
                            width: feedColumn.width
                            text: "nothing said yet in this conversation — say something below, "
                                  + "or say it out loud. it lands here either way."
                            color: panel.quiet
                            font.pixelSize: 13
                            font.family: "serif"
                            font.italic: true
                            wrapMode: Text.WordWrap
                            lineHeight: 1.5
                            opacity: panel.messages().length === 0 ? 1.0 : 0.0
                            visible: opacity > 0.001
                            height: visible ? implicitHeight : 0
                        }
                        Repeater {
                            model: panel.messages()
                            delegate: Column {
                                width: feedColumn.width
                                spacing: 2
                                Row {
                                    spacing: 7
                                    Text {
                                        text: panel.speakerOf(modelData)
                                        color: modelData.role === "user" ? panel.inkSoft : panel.amber
                                        font.pixelSize: 11
                                        font.family: "serif"
                                    }
                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: panel.clockOf(modelData.ts)
                                        color: panel.faint
                                        font.pixelSize: 10
                                    }
                                }
                                Text {
                                    width: parent.width
                                    text: modelData.text
                                    color: modelData.role === "user" ? panel.inkSoft : panel.ink
                                    font.pixelSize: 14
                                    font.family: "serif"
                                    wrapMode: Text.WordWrap
                                    lineHeight: 1.5
                                }
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

                // Plans, jobs, the holding shelf, parked items — sentences, and
                // one quiet line when the house really is quiet.
                Column {
                    id: houseShelf
                    width: parent.width
                    spacing: 3
                    opacity: !eventSnap.running && panel.houseLines().length > 0 ? 1.0 : 0.0
                    visible: opacity > 0.001
                    height: visible ? implicitHeight : 0
                    Behavior on opacity { NumberAnimation { duration: 280; easing.type: Easing.OutQuad } }
                    Repeater {
                        model: !eventSnap.running ? panel.houseLines() : []
                        delegate: Text {
                            width: houseShelf.width
                            text: modelData
                            color: panel.inkSoft
                            font.pixelSize: 12
                            font.family: "serif"
                            wrapMode: Text.WordWrap
                            lineHeight: 1.4
                        }
                    }
                    Text {
                        width: parent.width
                        text: "nothing holding right now — the house is quiet."
                        color: panel.quiet
                        font.pixelSize: 12
                        font.family: "serif"
                        font.italic: true
                        wrapMode: Text.WordWrap
                        opacity: !eventSnap.running && panel.houseLines().length === 0 ? 1.0 : 0.0
                        visible: opacity > 0.001
                        height: visible ? implicitHeight : 0
                        Behavior on opacity { NumberAnimation { duration: 320 } }
                    }
                }

                // Her note, not a command box: the paper is the field.
                Row {
                    id: draftRow
                    width: parent.width
                    spacing: 8
                    height: eventSnap.running ? 0 : 44
                    visible: !eventSnap.running
                    NoteField {
                        id: draftField
                        width: parent.width - 84
                        placeholderText: "say it here — I take this the same as your voice"
                        font.pixelSize: 13
                        font.family: "serif"
                        leftPadding: 12
                        rightPadding: 12
                        topPadding: 10
                        bottomPadding: 10
                        text: panel.draft
                        onTextChanged: panel.draft = text
                        onAccepted: panel.send()
                    }
                    HomeButton {
                        text: "pass it"
                        enabled: panel.draft.trim().length > 0
                        onClicked: panel.send()
                    }
                }

                Text {
                    id: statusLine
                    width: parent.width
                    text: panel.sendStatus
                    color: panel.quiet
                    font.pixelSize: 10
                    font.family: "serif"
                    wrapMode: Text.WordWrap
                    opacity: text.length > 0 ? 1.0 : 0.0
                    visible: opacity > 0.001
                    height: visible ? implicitHeight : 0
                    Behavior on opacity { NumberAnimation { duration: 320 } }
                }
            }
        }

        // ---- the only two styling helpers; no state, no decisions ------------
        component HomeButton: Button {
            font.pixelSize: 11
            padding: 8
            topPadding: 6
            bottomPadding: 6
            // A button that is not applicable takes no room in its Row, whether
            // or not the positioner skips invisible children.
            width: visible ? implicitWidth : 0
            height: visible ? implicitHeight : 0
            background: Rectangle {
                radius: 8
                color: !parent.enabled ? "#262119"
                     : parent.down ? "#4d4127"
                     : parent.hovered ? "#3a3220" : "#2c261a"
                border.width: 1
                border.color: parent.highlighted ? panel.amber : "#4b4230"
                Behavior on color { ColorAnimation { duration: 160 } }
                Behavior on border.color { ColorAnimation { duration: 240 } }
            }
            contentItem: Text {
                text: parent.text
                color: !parent.enabled ? panel.faint
                     : parent.highlighted ? panel.amber : panel.inkSoft
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
        }
        component NoteField: TextField {
            color: panel.ink
            placeholderTextColor: panel.faint
            selectByMouse: true
            background: Rectangle {
                radius: 9
                color: parent.activeFocus ? "#312a1b" : "#282317"
                border.width: 1
                border.color: parent.activeFocus ? panel.amber : "#42392a"
                Behavior on color { ColorAnimation { duration: 180 } }
                Behavior on border.color { ColorAnimation { duration: 240 } }
            }
        }

        // ---- the feed: one snapshot per daemon event, plus reconnects --------
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
                    } catch (e) { panel.sendStatus = panel.plainNote(line) }
                }
            }
            stderr: SplitParser { onRead: line => panel.sendStatus = panel.plainNote(line) }
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
