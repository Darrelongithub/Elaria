"""Console home (2026-10-25): the console reads as her home, not an admin panel.

This round changed *dress, posture and typography* in
``ui/quickshell/console/shell.qml`` and nothing else. The guards below are
therefore of two kinds, and both are load-bearing:

1. **The dress is the dress.** No field labels, no empty colon rows, prose
   transcript, plain-language failures, warm colour, fades. Where wording is
   generated from the snapshot, the panel's own phrasing functions are
   *executed* — extracted from the QML and run under node when node exists on
   the box — so the sentences are tested as data rather than grepped as vibes.
2. **Behaviour did not move.** Every process command, argument list, timer
   interval and layer-shell property the console had before this round is
   pinned here verbatim, so a future edit that is "only cosmetic" but changes
   what the console *does* has to fight this file first.

The QML cannot be rendered headless, which is why ``test_the_qml_is_
structurally_sane`` checks its bracket balance and why every hardware-facing
claim still lives in docs/console-home/hardware-gate.md instead of here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
QML = REPO / "ui" / "quickshell" / "console" / "shell.qml"

# The phrasing functions are pure display: they re-read the daemon snapshot and
# never decide anything about it.
PHRASING_FUNCTIONS = (
    "txtPath", "clockOf", "baseName", "speakerOf", "segmentHeading",
    "houseLines", "eventHeadline", "eventProgress", "eventFootnote", "plainNote",
)

EMPTY_SNAPSHOT = {
    "conversation": {"id": None, "messages": []},
    "pending_plans": [], "parked_items": [], "job_progress": [],
    "offline_queue": {"counts": {}, "jobs": []}, "holding": [],
    "knocks": [], "class_mode": {"enabled": False},
    "showoff": {"active": False}, "company": {"company": False},
    "counts": {"pending_plans": 0, "parked": 0, "queue": 0, "holding": 0, "knocks": 0},
}
IDLE_EVENT = {"running": False, "active_speaker": "", "document": "",
              "segments": {}, "calls": {}, "disk": {}, "quota": {}}

CODE, COMMENT, STRING, REGEX = 0, 1, 2, 3


def qml_source() -> str:
    return QML.read_text()


def _classify(source: str) -> list[int]:
    """Mark every character as code, comment, string or regex.

    Regex literals have to be tracked too: ``/\\.py"?,? line \\d+/`` carries a
    quote, and a checker that cannot tell a regex from a string cannot tell a
    balanced file from a broken one.
    """
    kinds = [CODE] * len(source)
    state, prev = CODE, ""
    index, length = 0, len(source)
    while index < length:
        char = source[index]
        nxt = source[index + 1] if index + 1 < length else ""
        if state == CODE:
            if char == "/" and nxt == "/" or char == "/" and nxt == "*":
                state = COMMENT
                kinds[index] = kinds[index + 1] = COMMENT
                index += 1
            elif char == "/" and prev in "([,:!&|?{;=":
                state = REGEX
                kinds[index] = REGEX
            elif char in "\"'":
                state, quote = STRING, char
                kinds[index] = STRING
            elif not char.isspace():
                prev = char
        elif state == STRING:
            kinds[index] = STRING
            if char == "\\":
                index += 1
                if index < length:
                    kinds[index] = STRING
            elif char == quote:
                state, prev = CODE, char
        elif state == REGEX:
            kinds[index] = REGEX
            if char == "\\":
                index += 1
                if index < length:
                    kinds[index] = REGEX
            elif char == "/":
                state, prev = CODE, char
        elif state == COMMENT:
            kinds[index] = COMMENT
            if char == "\n":
                state, prev = CODE, "\n"
                kinds[index] = CODE
            elif char == "*" and nxt == "/":
                kinds[index + 1] = CODE
                state, prev, index = CODE, "*", index + 1
        index += 1
    return kinds


def _views(source: str = "") -> tuple[str, str, list[int]]:
    """(comments gone, only structure, per-character kinds)."""
    text = source or qml_source()
    kinds = _classify(text)
    with_comments = "".join(c if k != COMMENT or c == "\n" else " " for c, k in zip(text, kinds))
    skeleton = "".join(c if k == CODE and c != "\n" else ("\n" if c == "\n" else " ")
                       for c, k in zip(text, kinds))
    return with_comments, skeleton, kinds


def without_comments(source: str = "") -> str:
    """Comments gone, strings kept: what the panel says and how it is wired."""
    return _views(source)[0]


def code_skeleton() -> str:
    """Comments and literals gone: only the QML's own structure."""
    return _views()[1]


def string_literals() -> list[str]:
    """Every quoted string in the file, comments excluded."""
    text = qml_source()
    kinds = _classify(text)
    runs, current = [], ""
    for char, kind in zip(text, kinds):
        if kind == STRING:
            current += char
        elif current:
            runs.append(current[1:-1] if len(current) > 1 else "")
            current = ""
    return runs


def displayed_literals() -> list[str]:
    """The strings this panel can put on the page: text/placeholder bindings."""
    source, _, _ = _views()
    found: list[str] = []
    for match in re.finditer(r'(?:text|placeholderText|toolTip)\s*:\s*', source):
        rest = source[match.end():]
        # A binding that opens with an expression (panel.x(), a ternary) is not
        # itself a literal; its quoted pieces are covered by string_literals().
        if not rest.startswith('"'):
            continue
        chunk = ""
        index = 0
        while index < len(rest):
            char = rest[index]
            if char == "\\":
                chunk += rest[index:index + 2]
                index += 2
                continue
            if char == '"':
                break
            chunk += char
            index += 1
        found.append(chunk)
    return found


def extract_function(name: str) -> str:
    """The source of one phrasing function, braces matched by code positions."""
    source = qml_source()
    kinds = _classify(source)
    match = re.search(rf"\bfunction {name}\s*\(", source)
    if match is None:
        raise AssertionError(f"{name}() is gone from the console QML")
    head_end = source.index("{", match.end())
    depth, index = 0, head_end
    while index < len(source):
        if kinds[index] == CODE:
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    break
        index += 1
    else:
        raise AssertionError(f"{name}() never closes — unbalanced QML")
    return source[match.start():index + 1]


def run_phrasing(panel_state: dict, expression: str, tmp_path: Path):
    """Execute the QML's own phrasing functions against a fake snapshot."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the phrasing harness cannot run here")
    parts = [f"var panel = {json.dumps(panel_state)};"]
    parts.append("panel.messages = function () {"
                 "  return (panel.snap.conversation && panel.snap.conversation.messages) || []; };")
    for name in PHRASING_FUNCTIONS:
        parts.append(f"panel.{name} = {extract_function(name)};")
    parts.append(f"process.stdout.write(JSON.stringify({expression}));")
    harness = tmp_path / "phrase-harness.js"
    harness.write_text("\n".join(parts), encoding="utf-8")
    result = subprocess.run([node, str(harness)], check=False, capture_output=True,
                              text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def panel_state(snap=None, event_snap=None, feed_up=True, daemon_quiet=None):
    snap = snap or EMPTY_SNAPSHOT
    if daemon_quiet is None:
        daemon_quiet = not feed_up or (snap.get("daemon") or {}).get("running") is False
    return {"snap": snap, "eventSnap": event_snap or IDLE_EVENT, "feedUp": feed_up,
            "ownerName": "Darrel", "daemonQuiet": daemon_quiet}


# -- the sentences the panel speaks (executed, not grepped) -------------------------
def test_an_empty_house_says_nothing_and_stays_quiet(tmp_path):
    assert run_phrasing(panel_state(), "panel.houseLines()", tmp_path) == []
    assert run_phrasing(panel_state(), "panel.eventProgress()", tmp_path) == ""
    # …and the QML puts one quiet sentence in that space, instead of a strip of
    # labelled fields standing there empty.
    assert '"nothing holding right now — the house is quiet."' in without_comments()


def test_plans_jobs_and_holding_are_sentences(tmp_path):
    snapshot = dict(EMPTY_SNAPSHOT)
    snapshot.update({
        "pending_plans": [
            {"id": 4, "status": "building", "total": 9, "placed": 3, "abstained": 0},
            {"id": 5, "status": "ready", "total": 6, "placed": 6, "abstained": 2},
        ],
        "job_progress": [{"kind": "cloud_transcription", "job_id": 7, "status": "running",
                          "attempts": 1, "done": 0, "total": 0,
                          "label": "job #7 · cloud_transcription"}],
        "holding": [{"id": 1, "title": "follow up with Amina"},
                    {"id": 2, "title": "the tax folder"}],
        "parked_items": [{"id": 9, "src": "/home/darrel/Docs/invoice.pdf", "dest": None,
                          "confidence": 0.4, "decision": "review", "reason": None}],
    })
    lines = run_phrasing(panel_state(snap=snapshot), "panel.houseLines()", tmp_path)
    assert len(lines) == 5
    joined = " ".join(lines)
    for fragment in ("plan #4 is still being thought about", "3 of 9 have their place",
                     "plan #5 is ready whenever you are", "2 she would rather you decided on",
                     "the cloud transcription job is going", "on attempt 2",
                     "she is holding 2 things for you", "follow up with Amina",
                     "1 thing is parked where only you can sort it", "invoice.pdf"):
        assert fragment in joined, fragment
    for line in lines:  # sentence shape, not `label:` rows
        assert line.endswith(".")
        assert not re.match(r"^[a-z_ ]{2,16}:", line), line


def test_a_building_plan_is_not_said_twice(tmp_path):
    """job_progress carries the building plan again, with the same numbers."""
    snapshot = dict(EMPTY_SNAPSHOT)
    snapshot["pending_plans"] = [{"id": 4, "status": "building", "total": 9, "placed": 3,
                                  "abstained": 0}]
    snapshot["job_progress"] = [{"kind": "plan", "plan_id": 4, "status": "building", "done": 3,
                                 "total": 9, "attempts": 0, "label": "plan #4 · /home/darrel/Docs"}]
    lines = run_phrasing(panel_state(snap=snapshot), "panel.houseLines()", tmp_path)
    assert len(lines) == 1
    assert "plan #4" in lines[0]


def test_event_status_reads_as_a_sentence(tmp_path):
    event = dict(IDLE_EVENT)
    event.update({"running": True, "active_speaker": "Amina", "segment_elapsed_s": 724.0,
                  "segment_minutes": 30,
                  "document": "/home/darrel/events/2026-10-24/transcript.md",
                  "segments": {"opened": 4, "transcribed": 3, "queued": 1, "deferred": 0}})
    state = panel_state(event_snap=event)
    assert run_phrasing(state, "panel.eventProgress()", tmp_path) == "3 parts written, 1 catching up."
    assert run_phrasing(state, "panel.eventHeadline()", tmp_path) == (
        "Elaria is listening — Amina, 12:04 into this part.")


def test_a_fresh_notebook_admits_that_nothing_has_landed(tmp_path):
    event = dict(IDLE_EVENT)
    event.update({"running": True, "document": "/tmp/x/transcript.md", "segment_minutes": 2,
                  "segments": {"opened": 0, "transcribed": 0, "queued": 0, "deferred": 0}})
    assert run_phrasing(panel_state(event_snap=event), "panel.eventProgress()", tmp_path) == (
        "nothing has landed yet — the first part closes after 2 minutes.")


def test_the_console_never_claims_she_is_listening_when_she_is_gone(tmp_path):
    """Hardware gate (iv): stop the daemon mid-event and the page must say so.

    `assist event status` degrades to disk assembly and keeps reporting
    running=true while state.json still says running; the console weighs that
    against the daemon-down snapshot and calls it what it is.
    """
    snap = dict(EMPTY_SNAPSHOT, daemon={"running": False, "reason": "socket gone"})
    event = dict(IDLE_EVENT)
    event.update({"running": True, "active_speaker": "Amina", "document": "/tmp/x/transcript.md",
                  "segments": {"opened": 4, "transcribed": 3, "queued": 1, "deferred": 0}})
    headline = run_phrasing(panel_state(snap=snap, event_snap=event),
                            "panel.eventHeadline()", tmp_path)
    assert "the mic went quiet" in headline
    assert "nothing new is being written" in headline
    assert "Elaria is listening" not in headline
    # With no event at all, the card admits it is shut rather than mourning.
    assert run_phrasing(panel_state(snap=snap), "panel.eventHeadline()", tmp_path) == (
        "the notebook is shut — nothing is being written.")


def test_the_footnote_keeps_the_numbers_without_the_table(tmp_path):
    event = dict(IDLE_EVENT)
    event.update({"running": True, "route": "batch",
                  "calls": {"used": 5, "budget": 25, "remaining": 20, "reserve": 2},
                  "quota": {"tpm_ceiling": None, "next_reset_eat": "2026-10-26 00:00 EAT"},
                  "disk": {"free_bytes": 118111600640},
                  "transport": "fake — no calls will be made"})
    footnote = run_phrasing(panel_state(event_snap=event), "panel.eventFootnote()", tmp_path)
    assert "5 of today's 25 calls used, 2 held back for the closing part" in footnote
    assert "this route publishes no per-minute ceiling" in footnote
    assert "110.0 GB free where the audio lives" in footnote
    assert "fake — no calls will be made" in footnote
    assert "{" not in footnote and "}" not in footnote  # no JSON on the page


def test_failures_are_plain_words_never_traces_or_codes(tmp_path):
    state = panel_state()
    machine = [
        'Traceback (most recent call last):\n  File "/usr/lib/python3/event.py", line 12, in x',
        "ValueError: battery is low and the charger is out",
        '{"ok": false, "code": 500}',
        "RuntimeError: the capture process died",
    ]
    for line in machine:
        note = run_phrasing(state, f"panel.plainNote({json.dumps(line)})", tmp_path)
        assert "that did not go through" in note, note
        assert "Traceback" not in note and ".py" not in note
        assert "ValueError" not in note and "RuntimeError" not in note
        assert "500" not in note
    assert run_phrasing(state, 'panel.plainNote("no event is running")', tmp_path) == (
        "no event is running")
    assert run_phrasing(state, 'panel.plainNote("")', tmp_path) == ""


def test_transcript_speakers_are_people(tmp_path):
    state = panel_state()
    for message, expected in (
            ({"role": "user", "channel": "voice"}, "Darrel said"),
            ({"role": "user", "channel": "console"}, "Darrel wrote"),
            ({"role": "assistant", "channel": "voice"}, "Elaria answered"),
            ({"role": "assistant", "channel": "console"}, "Elaria answered")):
        assert run_phrasing(state, f"panel.speakerOf({json.dumps(message)})", tmp_path) == expected
    assert run_phrasing(state, 'panel.clockOf("2026-10-25T09:12:33+03:00")', tmp_path) == "09:12"
    assert run_phrasing(state, 'panel.clockOf("")', tmp_path) == ""


def test_segment_headings_are_headings(tmp_path):
    state = panel_state()
    for header, expected in (
            ("## 09:32 · Amina · seg 004", "09:32 · Amina · part 4"),
            ("## 10:02 · Speaker 1 · seg 007 (recovered)", "10:02 · Speaker 1 · part 7, arrived late"),
            ("## ??:?? · Speaker 3 · seg 012 (edited copy)", "??:?? · Speaker 3 · part 12")):
        assert run_phrasing(state, f"panel.segmentHeading({json.dumps(header)})", tmp_path) == expected


def test_the_paths_the_editor_uses_are_untouched(tmp_path):
    state = panel_state()
    assert run_phrasing(state, 'panel.txtPath("/a/b/transcript.md")', tmp_path) == "/a/b/transcript.txt"
    # Pinned as inherited, not as ideal: the daemon's `document` is always the
    # .md path, and a path that already ends in .txt still gets the suffix
    # appended. That quirk predates the console-home round and a dress round
    # does not quietly change which file `Open .txt` opens.
    assert run_phrasing(state, 'panel.txtPath("/a/b/transcript.txt")', tmp_path) == (
        "/a/b/transcript.txt.txt")


# -- what the page shows, statically -------------------------------------------------
def test_no_field_labels_and_no_empty_colon_rows_are_rendered():
    rendered = displayed_literals() + string_literals()
    assert rendered, "no strings at all? the extractor is wrong, not the QML"
    for literal in rendered:
        assert not re.match(r"^[a-z][a-z_ ]{1,15}:\s*$", literal), literal
        assert not re.match(r"^(plans|jobs|holding|parked|queue|knocks|conversation)\s*#", literal), literal
    for forbidden in ("plans: ", "jobs: ", "holding: ", "offline queue: ", "conversation #"):
        assert not any(forbidden in literal for literal in rendered), forbidden


def test_the_transcript_is_set_as_prose():
    source = without_comments()
    assert 'font.family: "serif"' in source
    assert "lineHeight: 1.5" in source
    assert "lineHeight: 1.4" in source or "lineHeight: 1.35" in source
    assert "elide: Text.ElideMiddle" in source  # the path, kept quiet
    assert '" [" + ' not in source              # the old `[voice]` log tag is gone
    assert "font.pixelSize: 14" in source       # arm's length


def test_state_changes_fade_and_never_flash():
    source = code_skeleton()
    assert source.count("Behavior on opacity") >= 6
    assert source.count("Behavior on color") + source.count("Behavior on border.color") >= 4
    assert "NumberAnimation { duration: 0" not in source
    # A fade that only works one way is a flash with extra steps: every block
    # that fades in also fades out, because `visible` follows the opacity.
    assert source.count("visible: opacity > 0.001") >= 6


def test_the_palette_is_warm_with_one_accent():
    hexes = sorted(set(re.findall(r"#[0-9a-fA-F]{6}", without_comments())))
    assert hexes, "no colours?"
    accents = []
    for value in hexes:
        red, green, blue = (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))
        assert red > blue, f"{value} is a cool colour; the page is paper, not a terminal"
        if max(red, green, blue) - min(red, green, blue) > 90:
            accents.append(value)
    assert len(set(accents)) == 1, f"more than one accent hue: {sorted(set(accents))}"
    assert "daemon down" not in without_comments()
    assert not any(literal.startswith("#ff") for literal in string_literals())


def test_copy_is_plain_words_with_no_emoji():
    assert {c for c in qml_source() if ord(c) > 127} <= {"—", "·", "→", "…", "§"}
    for literal in displayed_literals():
        assert not re.search(r"[\U0001F000-\U0001FAFF]", literal), literal
        assert not re.search(r"[☀-➿]", literal), literal
        assert "\n" not in literal


def test_the_input_line_is_a_note_in_her_voice():
    source = without_comments()
    assert 'placeholderText: "say it here — I take this the same as your voice"' in source
    assert 'placeholderText: "talk to her — same conversation as voice"' not in source
    assert 'placeholderText: "Your event command — status, speaker next, stop event"' not in source
    # …in her voice, and still the same door the voice path uses.
    assert 'sendProcess.command = ["assist", "talk", text]' in source
    assert 'placeholderText: "write to her — status, speaker next, stop event"' in source


def test_the_silence_handoff_line_is_rendered_at_last():
    """The hotfix put `status_line` on the snapshot and left the rendering here."""
    source = without_comments()
    assert "panel.snap.status_line" in source
    assert re.search(r'text: String\(\(panel\.snap && panel\.snap\.status_line\) \|\| ""\)',
                     source)
    assert "lastWordLine" in source
    # No label in front of it: the daemon's line is already her sentence, so
    # the panel renders it and adds nothing.
    assert not any(lit.lower().startswith(("last session", "status:"))
                   for lit in string_literals())


def test_layer_shell_posture_is_untouched():
    source, skeleton, _ = _views()
    for line in ("WlrLayershell.layer: WlrLayer.Top",
                 'WlrLayershell.namespace: "elaria-console"',
                 "WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand",
                 "exclusiveZone: -1"):
        assert line in source
    assert re.search(r"anchors\s*\{\s*top: true; right: true\s*\}", skeleton)
    # The feed's own command and retry are the posture too: same CLI, same beat.
    assert 'command: ["assist", "console", "--follow"]' in source
    assert "running: true" in skeleton


# -- the frozen part: behaviour, command for command --------------------------------
FROZEN_COMMANDS = [
    'command: ["assist", "console", "--follow"]',
    'sendProcess.command = ["assist", "talk", text]',
    'knockProcess.command = ["assist", "knock", action, String(id)]',
    'eventProcess.command = ["assist"].concat(args)',
    'documentStatProcess.command = ["stat", "-c", "%s:%y", txt]',
    'documentProcess.command = ["cat", panel.activeDocumentPath]',
    'editorProcess.command = ["xdg-open",',
    '["event", "start", "--title",',
    'eventTitleField.text || "Live event", "--speakers",',
    'eventRosterField.text || "Speaker 1"]',
    'if (batteryConfirm.checked) args.push("--battery-ok")',
    'panel.eventAction(["event", "speaker", "next"])',
    'panel.eventAction(["event", "stop"])',
    'panel.eventAction(["event", "status"])',
    'panel.eventAction(["event", "speaker", text.trim()])',
    'panel.eventAction(["event", "speaker", newSpeakerField.text.trim()])',
    'panel.eventAction(["event", "speaker", modelData])',
    'panel.eventAction(["event", "rename",',
    'panel.eventAction(["event", "export", "--format", "md"])',
    'panel.eventAction(["event", "export", "--format", "txt"])',
    'editProcess.command = ["assist", "event", "edit",',
    '"--segment", String(modelData.index),',
    '"--base-text=" + segmentEditorDelegate.baseText,',
    '"--text=" + segmentEditorDelegate.pendingText]',
]


@pytest.mark.parametrize("command", FROZEN_COMMANDS)
def test_the_console_still_opens_the_same_doors(command):
    assert command in without_comments()


def test_the_feed_document_and_edit_loops_are_unchanged():
    source = without_comments()
    for timer in ("id: feedRetry", "id: editSaveTimer", "id: editRefresh",
                  "id: eventRefresh", "id: scrollTimer", "id: transcriptScroll"):
        assert timer in source
    assert re.search(r"id: feedRetry\s*\n\s*interval: 1500", source)
    assert re.search(r"id: editSaveTimer\s*\n\s*interval: 650", source)
    assert re.search(r"id: editRefresh\s*\n\s*interval: 120", source)
    assert re.search(r"id: eventRefresh\s*\n\s*interval: 1200", source)
    # The document is reloaded only when its fingerprint moves, so a live
    # append cannot reset her cursor mid-sentence; the editors keep the base
    # text they were loaded with, and a stale edit is never silently dropped.
    for guard in ("panel.editingDirty || panel.editorFocused",
                  "if (line !== panel.documentFingerprint && panel.activeDocumentPath)",
                  'panel.transcriptText = panel.transcriptLines.join("\\n") + "\\n"',
                  "segmentEditorDelegate.baseText = segmentEditorDelegate.pendingText",
                  "This segment changed; your edit was kept at the tail.",
                  "Saved to the live document.",
                  "if (editProcess.running) { restart(); return }",
                  "refreshAfterAction = args[1] !== \"status\""):
        assert guard in source, guard


def test_the_three_event_words_are_still_the_three_event_words():
    source = without_comments()
    for word in ('if (words === "speaker next")',
                 'else if (words === "stop event" || words === "event stop")',
                 'else if (words === "status" || words === "event status")'):
        assert word in source


def test_the_qml_is_structurally_sane():
    """QML cannot be executed headless, so at least its braces have to close."""
    text = qml_source()
    kinds = _classify(text)
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[tuple[str, int]] = []
    line = 1
    for index, (char, kind) in enumerate(zip(text, kinds)):
        if char == "\n":
            line += 1
        if kind != CODE:
            continue
        if char in "([{":
            stack.append((char, line))
        elif char in ")]}":
            assert stack, f"stray {char} on line {line}"
            opened, opened_line = stack.pop()
            assert opened == pairs[char], f"{opened} on line {opened_line} closed by {char} on {line}"
    assert stack == [], f"unclosed {stack[:3]}"
    assert text.count("ShellRoot {") == 1
    assert text.count("PanelWindow {") == 1
    for name in PHRASING_FUNCTIONS:
        assert f"function {name}(" in text


def test_the_readme_describes_the_page_she_actually_sees():
    readme = (REPO / "ui" / "README.md").read_text()
    assert "Elaria · home" in readme
    assert "nothing holding right now" in readme
    assert "Win+Shift+F2" in readme or "bind" in readme.lower()
