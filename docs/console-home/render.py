#!/usr/bin/env python3
"""Before/after renderings of the console panel, for the record (console-home round).

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This is an *offline rendering of the QML's own copy and geometry*, built in a
headless sandbox. It is not a screenshot of a live desktop: no Quickshell, no
Wayland, no compositor, no font fallback from the owner's Fedora box, and no
guarantee that a `Row` of buttons fits her width. The panel has still never
been rendered on her machine; that eyeball gate stays open and lives in
`hardware-gate.md` next to these images. Do not read these as "verified".

They are still worth having, and they are not hand-doodled:

* the **after** copy is executed out of `ui/quickshell/console/shell.qml` — the
  panel's own phrasing functions are extracted, run under node against the fake
  snapshots in this file, and drawn exactly as returned;
* the **before** copy is the previous file's inline bindings reproduced
  literally (read from `git show HEAD~1`, falling back to the recorded strings
  here when the checkout has moved on);
* sizes, colours, line heights and paddings are the QML's own numbers; the
  font is DejaVu Serif/Sans, which is what a serif/sans family resolves to in
  this sandbox.

Run:  python3 docs/console-home/render.py      (needs Pillow + node + a checkout)
Out:  docs/console-home/NN-state-{before,after}.png
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[2]
QML = REPO / "ui" / "quickshell" / "console" / "shell.qml"
FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

# --------------------------------------------------------------------------- QML
CODE, COMMENT, STRING, REGEX = 0, 1, 2, 3
PHRASING = ("txtPath", "clockOf", "baseName", "speakerOf", "segmentHeading",
            "houseLines", "eventHeadline", "eventProgress", "eventFootnote", "plainNote")


def _classify(source: str) -> list[int]:
    """Mark each char as code/comment/string/regex so braces can be matched."""
    kinds = [CODE] * len(source)
    state, prev, quote = CODE, "", ""
    i, n = 0, len(source)
    while i < n:
        c, nxt = source[i], source[i + 1] if i + 1 < n else ""
        if state == CODE:
            if c == "/" and nxt == "/" or c == "/" and nxt == "*":
                state = COMMENT
                kinds[i] = kinds[i + 1] = COMMENT
                i += 1
            elif c == "/" and prev in "([,:!&|?{;=":
                state = REGEX
                kinds[i] = REGEX
            elif c in "\"'":
                state, quote = STRING, c
                kinds[i] = STRING
            elif not c.isspace():
                prev = c
        elif state == STRING:
            kinds[i] = STRING
            if c == "\\":
                i += 1
                kinds[i] = STRING
            elif c == quote:
                state, prev = CODE, c
        elif state == REGEX:
            kinds[i] = REGEX
            if c == "\\":
                i += 1
                kinds[i] = REGEX
            elif c == "/":
                state, prev = CODE, c
        elif state == COMMENT:
            kinds[i] = COMMENT
            if c == "\n":
                state, prev = CODE, "\n"
                kinds[i] = CODE
            elif c == "*" and nxt == "/":
                kinds[i + 1] = CODE
                state, prev, i = CODE, "*", i + 1
        i += 1
    return kinds


def extract_function(source: str, name: str) -> str:
    kinds = _classify(source)
    match = re.search(rf"\bfunction {name}\s*\(", source)
    if match is None:
        return ""
    start = source.index("{", match.end())
    depth, i = 0, start
    while i < len(source):
        if kinds[i] == CODE:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
                if depth == 0:
                    break
        i += 1
    return source[match.start():i + 1]


def speak(state: dict, expressions: dict) -> dict:
    """Evaluate the panel's own phrasing functions against a fake snapshot."""
    source = QML.read_text(encoding="utf-8")
    parts = [f"var panel = {json.dumps(state)};",
             ("panel.messages = function () {"
             "  return (panel.snap.conversation && panel.snap.conversation.messages) || []; };")]
    for name in PHRASING:
        body = extract_function(source, name)
        if body:
            parts.append(f"panel.{name} = {body};")
    assignments = "\n".join(f"out[{json.dumps(key)}] = {expr};" for key, expr in expressions.items())
    parts.append("var out = {};\n" + assignments + "\nprocess.stdout.write(JSON.stringify(out));")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write("\n".join(parts))
        path = handle.name
    result = subprocess.run(["node", path], check=False, capture_output=True, text=True,
                     timeout=60)
    Path(path).unlink()
    if result.returncode:
        raise SystemExit("the node harness failed:\n" + result.stderr[-2000:])
    return json.loads(result.stdout)


def previous_qml() -> str:
    for rev in ("HEAD~1", "HEAD"):
        done = subprocess.run(["git", "-C", str(REPO), "show",
                               f"{rev}:ui/quickshell/console/shell.qml"],
                              check=False, capture_output=True, text=True)
        if done.returncode == 0 and "plans: " in done.stdout:
            return done.stdout
    return ""


# --------------------------------------------------------------------------- data
def snapshot(**changes) -> dict:
    base = {"conversation": {"id": 7, "messages": []}, "pending_plans": [], "parked_items": [],
            "job_progress": [], "offline_queue": {"counts": {}, "jobs": []}, "holding": [],
            "knocks": [], "class_mode": {"enabled": False}, "showoff": {"active": False},
            "company": {"company": False}, "status_line": None,
            "counts": {"pending_plans": 0, "parked": 0, "queue": 0, "holding": 0, "knocks": 0}}
    base.update(changes)
    return base


def event(**changes) -> dict:
    base = {"running": False, "state": "not-running", "title": "", "active_speaker": "",
            "roster": [], "document": "", "segments": {}, "calls": {}, "disk": {}, "quota": {},
            "transport": "", "route": "batch", "segment_minutes": 30}
    base.update(changes)
    return base


LIVE_EVENT = event(running=True, state="running", title="Venue day", segment_minutes=2,
                   active_speaker="Amina", segment_elapsed_s=724.0,
                   roster=["Amina", "Otieno", "Speaker 3"],
                   document="/home/darrel/.local/share/assistant/events/2026-10-25/transcript.md",
                   segments={"opened": 5, "transcribed": 3, "queued": 1, "deferred": 0},
                   calls={"used": 5, "budget": 25, "remaining": 20, "reserve": 2},
                   quota={"tpm_ceiling": None, "next_reset_eat": "2026-10-26 00:00 EAT"},
                   disk={"free_bytes": 118111600640},
                   transport="fake — no calls will be made")
DOWN_EVENT = {**LIVE_EVENT, "running": True}

MESSAGES = [
    {"id": 1, "role": "user", "channel": "voice", "ts": "2026-10-25T09:12:33+03:00",
     "text": "Put the invoice with the tax things and tell me what else is loose."},
    {"id": 2, "role": "assistant", "channel": "voice", "ts": "2026-10-25T09:12:41+03:00",
     "text": "Filed. Two others are still unsorted and one of them I would rather you decided "
             "on yourself, so I left it where it was and parked it for you instead."},
    {"id": 3, "role": "user", "channel": "console", "ts": "2026-10-25T09:15:02+03:00",
     "text": "Good. Keep the follow-up with Amina on the shelf until Monday."},
    {"id": 4, "role": "assistant", "channel": "console", "ts": "2026-10-25T09:15:09+03:00",
     "text": "On the shelf it is. I will bring it back on Monday morning and not before."},
]

BUSY_SNAPSHOT = snapshot(
    pending_plans=[{"id": 4, "status": "building", "total": 9, "placed": 3, "abstained": 0},
                   {"id": 5, "status": "ready", "total": 6, "placed": 6, "abstained": 2}],
    job_progress=[{"kind": "cloud_transcription", "job_id": 7, "status": "running",
                   "attempts": 1, "done": 0, "total": 0,
                   "label": "job #7 · cloud_transcription"},
                  # as the daemon really emits it: a building plan shows up in
                  # job_progress too, with the same numbers as pending_plans
                  {"kind": "plan", "plan_id": 4, "status": "building", "done": 3, "total": 9,
                   "attempts": 0, "label": "plan #4 · /home/darrel/Docs"}],
    holding=[{"id": 1, "title": "follow up with Amina"}, {"id": 2, "title": "the tax folder"}],
    parked_items=[{"id": 9, "src": "/home/darrel/Docs/invoice.pdf", "decision": "review"}],
    offline_queue={"counts": {"pending": 2, "done": 41}, "jobs": []},
    class_mode={"enabled": True},
    counts={"pending_plans": 2, "parked": 1, "queue": 1, "holding": 2, "knocks": 1},
    knocks=[{"id": 12, "urgency": "urgent", "topic": "tax",
             "reason": "The invoice you mentioned is in Downloads, not in Docs — I would "
                       "rather you saw that before Friday.",
             "referent": "the invoice in Downloads"}],
    status_line="she heard nothing",
    conversation={"id": 7, "messages": MESSAGES})

DOWN_SNAPSHOT = {**BUSY_SNAPSHOT, "daemon": {"running": False, "reason": "socket gone"}}

SEGMENTS = [
    {"index": 3, "header": "## 09:32 · Amina · seg 004",
     "text": "We said the water would be on at eight and it is not on yet, so anyone waiting "
             "for water is waiting for nothing. I have asked the grounds office twice and "
             "nobody is picking up."},
    {"index": 4, "header": "## 10:02 · Otieno · seg 005 (recovered)",
     "text": "The generator is holding. If it drops we stop the music, not the talks — "
             "Elaria keeps writing either way, so keep talking."},
]


# --------------------------------------------------------------------------- paint
# One primitive per kind of thing on the page, each `(draw, args, x, y, width,
# palette) -> height`, and each drawing nothing when `draw` is None. That is how
# a card measures its own sentences before sizing its background, and how the
# page is measured before the window height is picked — the same code path in
# both passes, so nothing can drift between them.
_METRIC = ImageDraw.Draw(Image.new("RGB", (8, 8), "white"))


def _fnt(px: int, serif: bool = True, bold: bool = False):
    name = ("DejaVuSerif" if serif else "DejaVuSans") + ("-Bold" if bold else "") + ".ttf"
    return ImageFont.truetype(str(FONT_DIR / name), px)


def _wrap(text, font, width):
    lines, current = [], ""
    for word in str(text).split(" "):
        trial = f"{current} {word}".strip()
        if current and _METRIC.textlength(trial, font=font) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


def p_text(draw, args, x, y, width, pal):
    value, px, color = args[0], args[1], args[2]
    opts = args[3] if len(args) > 3 else {}
    font = _fnt(px, opts.get("serif", True), opts.get("bold", False))
    step = opts.get("line_height") or round(px * opts.get("spacing", 1.35))
    lines = _wrap(value, font, width - opts.get("indent", 0))
    if draw is not None:
        for index, line in enumerate(lines):
            draw.text((x, y + index * step), line, font=font, fill=color)
    return len(lines) * step


def p_row(draw, args, x, y, width, pal):
    """One line of small pieces — a speaker and a time, a name and a chip."""
    cursor, tallest = x, 0
    for value, px, color, extra in args:
        font = _fnt(px, extra.get("serif", False), extra.get("bold", False))
        span = _METRIC.textlength(value, font=font) if value else 0
        if draw is not None and value:
            draw.text((cursor, y), value, font=font, fill=color)
        cursor += span + 10
        tallest = max(tallest, px + 5)
    return tallest or 14


def p_buttons(draw, args, x, y, width, pal):
    labels, px = args[0], args[1]
    font = _fnt(px, False)
    cursor, height, lit = x, px + 14, pal.get("lit", ())
    for label in labels:
        span = _METRIC.textlength(label, font=font) + 18
        if draw is not None:
            on = label in lit
            draw.rounded_rectangle((cursor, y, cursor + span, y + height), radius=8,
                                   fill=pal["button"],
                                   outline=pal["amber"] if on else pal["button_edge"], width=1)
            draw.text((cursor + 9, y + 7), label, font=font,
                      fill=pal["amber"] if on else pal["button_ink"])
        cursor += span + 6
    return height


def p_field(draw, args, x, y, width, pal):
    placeholder, px, span = args[0], args[1], args[2]
    height = px + 20
    if draw is not None:
        draw.rounded_rectangle((x, y, x + span, y + height), radius=9, fill=pal["field"],
                               outline=pal["field_edge"], width=1)
        draw.text((x + 12, y + 10), placeholder, font=_fnt(px), fill=pal["faint"])
    return height


def p_fields(draw, args, x, y, width, pal):
    specs, px = args[0], args[1]
    cursor = x
    for placeholder, span in specs:
        p_field(draw, (placeholder, px, span), cursor, y, width, pal)
        cursor += span + 8
    return px + 20


def p_checkbox(draw, args, x, y, width, pal):
    label, px = args[0], args[1]
    if draw is not None:
        draw.rounded_rectangle((x, y + 2, x + 12, y + 14), radius=2, outline=pal["field_edge"],
                               width=1)
        draw.text((x + 19, y), label, font=_fnt(px, False), fill=pal["ink_soft"])
    return px + 8


def p_chips(draw, args, x, y, width, pal):
    labels, px = args[0], args[1]
    font = _fnt(px, False)
    cursor, height = x, px + 10
    for label in labels:
        span = _METRIC.textlength(label, font=font) + 14
        if draw is not None:
            draw.rounded_rectangle((cursor, y, cursor + span, y + height), radius=7,
                                   fill=pal["chip"], outline=pal["chip_edge"], width=1)
            draw.text((cursor + 7, y + 5), label, font=font, fill=pal["amber"])
        cursor += span + 10
    return height


def p_editor(draw, args, x, y, width, pal):
    """A landed segment, drawn as the document holds it: body, unstyled."""
    body, px, minimum = args[0], args[1], args[2]
    step = round(px * 1.5)
    font = _fnt(px)
    lines = _wrap(body, font, width - 24)
    height = max(minimum, len(lines) * step + 16)
    if draw is not None:
        draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill=pal["editor"],
                               outline=pal["editor_edge"], width=1)
        for index, line in enumerate(lines):
            draw.text((x + 12, y + 8 + index * step), line, font=font, fill=pal["ink"])
    return height


def p_fieldrow(draw, args, x, y, width, pal):
    """Her note and the one word that passes it: one line, as the QML Row has it."""
    placeholder, px, button = args[0], args[1], args[2]
    font = _fnt(px, False)
    label = _METRIC.textlength(button, font=font) + 18
    span = max(120, width - label - 8)
    height = max(p_field(draw, (placeholder, px, span), x, y, width, pal), px + 15)
    p_buttons(draw, ([button], px - 2), x + span + 8, y, width, pal)
    return height


def p_gap(draw, args, x, y, width, pal):
    return args if isinstance(args, int) else args[0]


PRIMITIVES = {"text": p_text, "row": p_row, "buttons": p_buttons, "field": p_field,
              "fields": p_fields, "checkbox": p_checkbox, "chips": p_chips,
              "fieldrow": p_fieldrow,
              "editor": p_editor, "gap": p_gap}


def paint(ops, x, y, width, pal, draw=None, spacing=10):
    for op in ops:
        kind, args = op[0], op[1]
        if kind == "card":
            height = block_height(args, width - 26, pal, spacing) + 26
            if draw is not None:
                draw.rounded_rectangle((x, y, x + width, y + height), radius=12,
                                       fill=pal["card"], outline=pal["card_edge"], width=1)
            if draw is not None:
                paint(args, x + 13, y + 13, width - 26, pal, draw, spacing)
        else:
            height = PRIMITIVES[kind](draw, args, x, y, width, pal)
        y += height + spacing
    return y - spacing


def block_height(ops, width, pal, spacing=10) -> int:
    return paint(ops, 0, 0, width, pal, None, spacing)


def render(path: Path, ops: list, *, width: int, palette: dict, minimum_height: int,
           lamp: bool = False, spacing: int = 10):
    pad = palette["pad"]
    content = block_height(ops, width - pad * 2, palette, spacing)
    height = max(minimum_height, content + pad * 2 + 6)
    image = Image.new("RGB", (width, height), palette["paper"])
    draw = ImageDraw.Draw(image, "RGBA")
    if lamp:
        for row in range(height):
            ratio = row / height
            lift = 0.16 * (1 - ratio / 0.55) if ratio < 0.55 else 0.0
            base = palette["paper_rgb"]
            tone = tuple(int(min(255, c + (46 - c) * lift)) for c in base)
            draw.line((0, row, width, row), fill=tone)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=palette["radius"],
                           outline=palette["border"], width=1)
    paint(ops, pad, pad, width - pad * 2, palette, draw, spacing)
    image.save(path)
    return height


# --------------------------------------------------------------------------- copy
# Which of these blocks exist is the whole point of the round: the after list is
# built from sentences that vanish when the snapshot has nothing in them, the
# before list is the previous file's rows, labels and all.
def after_ops(copy: dict, snap: dict, ev: dict) -> list:
    ops: list = [
        ("text", ("Elaria · home", 20, "#efe6d3", {"bold": True, "line_height": 25})),
        ("text", ("one conversation — said out loud or written here, the same to her",
                  11, "#9c9078", {"serif": False, "line_height": 15})),
    ]
    if copy["badges"]:
        ops.append(("chips", (copy["badges"], 10)))
    if copy["status_line"]:
        ops.append(("text", (copy["status_line"], 12, "#e2a95f", {})))
    if copy["notice"]:
        ops.append(("text", (copy["notice"], 11, "#e2a95f", {})))
    for knock in copy["knocks"]:
        ops.append(("text", (knock["head"], 12, "#e2a95f", {"bold": True})))
        ops.append(("text", (knock["reason"], 13, "#efe6d3", {"spacing": 1.4})))
        ops.append(("text", (knock["meta"], 10, "#7d7360", {"serif": False})))
        ops.append(("buttons", (["accept", "later", "decline"], 11)))
    card: list = [("text", (copy["headline"], 16, "#efe6d3", {"spacing": 1.3}))]
    if copy["progress"]:
        card.append(("text", (copy["progress"], 12, "#e2a95f", {})))
    if ev.get("document"):
        card.append(("text", (("Open the .txt in your editor; edit freely above the tail; new text "
                              "arrives at the bottom."), 11, "#cfc2a6", {})))
    if copy["footnote"] and (ev.get("running") or ev.get("document")):
        card.append(("text", (copy["footnote"], 10, "#9c9078", {"serif": False})))
    if ev.get("document"):
        card.append(("text", ("the page she is writing on — " + copy["txt_path"], 10, "#7d7360",
                              {"serif": False})))
    if ev.get("running"):
        card.append(("buttons", (["Next speaker", "Stop event", "Status", "Open .txt"], 11)))
        card.append(("field", ("write to her — status, speaker next, stop event", 11, 436)))
        card.append(("row", ([("a name to add", 11, "#7d7360", {}),
                              ("Add", 11, "#cfc2a6", {"serif": False}),
                              ("Amina", 11, "#e2a95f", {"serif": False}),
                              ("Otieno", 11, "#cfc2a6", {"serif": False}),
                              ("Speaker 3", 11, "#cfc2a6", {"serif": False})])))
    else:
        card.append(("fields", ([("what she is calling this event", 190),
                                 ("who is speaking, in order", 190)], 11)))
        card.append(("checkbox", ("the charger is in — battery confirmed", 11)))
        card.append(("buttons", (["Start event", "Status", "Open .txt"], 11)))
        if ev.get("document"):
            card.append(("row", ([("S2", 11, "#7d7360", {}),
                                  ("their new name", 11, "#7d7360", {}),
                                  ("Rename", 11, "#cfc2a6", {"serif": False}),
                                  ("MD copy", 11, "#cfc2a6", {"serif": False}),
                                  ("TXT copy", 11, "#cfc2a6", {"serif": False})])))
    ops.append(("card", card))
    for heading, body in copy["segments"]:
        ops.append(("text", (heading, 11, "#9c9078", {"line_height": 15})))
        ops.append(("editor", (body, 15, 74)))
    if not ev.get("running") and not copy["messages"]:
        ops.append(("text", (("nothing said yet in this conversation — say something below, or "
                              "say it out loud. it lands here either way."), 13, "#9c9078",
                              {"spacing": 1.5})))
    if not ev.get("running"):
        for who, clock, body in copy["messages"]:
            ops.append(("row", ([(who, 11, "#e2a95f" if who.startswith("Elaria") else "#cfc2a6", {}),
                                 (clock, 10, "#7d7360", {})])))
            ops.append(("text", (body, 14, "#efe6d3", {"spacing": 1.5})))
        for line in copy["house"]:
            ops.append(("text", (line, 12, "#cfc2a6", {"spacing": 1.4})))
        if not copy["house"]:
            ops.append(("text", ("nothing holding right now — the house is quiet.", 12,
                                 "#9c9078", {"spacing": 1.4})))
        ops.append(("fieldrow", ("say it here — I take this the same as your voice", 13,
                                 "pass it")))
    if copy["send_status"]:
        ops.append(("text", (copy["send_status"], 10, "#9c9078", {})))
    return ops


def before_ops(snap: dict, ev: dict) -> list:
    """The previous file's inline bindings, reproduced literally."""
    counts = snap["counts"]
    down = "daemon" in snap
    ops: list = [("row", ([("Elaria · console", 16, "#e6e9f5", {"serif": False, "bold": True}),
                           ("CLASS MODE", 10, "#ffcb6b", {"bold": True})
                           if snap["class_mode"]["enabled"] else ("", 10, "#000", {}),
                           ("daemon down", 11, "#ff6b6b", {}) if down else ("", 11, "#000", {})]))]
    strip = (f'conversation #{snap["conversation"]["id"] or "—"} · '
              f'holding {counts["holding"]} · parked {counts["parked"]} · '
              f'queue {counts["queue"]} · knocks {counts["knocks"]}')
    ops.append(("text", (strip, 11, "#8f97ad", {"serif": False, "line_height": 15})))
    if snap["knocks"]:
        ops.append(("text", ("wants to talk", 12, "#ffb86c", {"serif": False, "bold": True})))
        for knock in snap["knocks"]:
            ops.append(("text", (f'#{knock["id"]} [{knock["urgency"]}] {knock["reason"]}',
                                 12, "#e6e9f5", {"serif": False, "spacing": 1.25})))
        ops.append(("buttons", (["accept", "later", "decline"], 11)))
    card: list = []
    if ev.get("running"):
        secs = int(ev.get("segment_elapsed_s", 0))
        card.append(("text", (("Elaria is listening · "
                               f'{ev["active_speaker"]} · {secs // 60}:{secs % 60:02d} '
                               "into this part"), 17, "#f1e7d4")))
    else:
        card.append(("text", (("Event stopped · " + ev["title"]) if ev.get("document")
                              else "Your event notebook", 17, "#f1e7d4")))
    if ev.get("document"):
        card.append(("text", (("Open the .txt in your editor; edit freely above the tail; new text "
                              "arrives at the bottom."), 11, "#c7bda9", {})))
        seg, calls, disk = ev["segments"], ev["calls"], ev["disk"]
        path_shown = re.sub(r"\.md$", ".txt", ev["document"])
        catching = f', {seg["queued"]} catching up' if seg["queued"] else ""
        status_line = (f'{seg["transcribed"]} parts written{catching} · '
                       f'calls {calls["used"]}/{calls["budget"]} · '
                       f'disk {disk["free_bytes"] / 1073741824:.1f} GB free · '
                       f'{ev["route"]} TPM {ev["quota"].get("tpm_ceiling") or "not published"} · '
                       f'{path_shown}')
        card.append(("text", (status_line, 12, "#c7bda9", {"serif": False})))
    if ev.get("running"):
        card.append(("buttons", (["Next speaker", "Stop event", "Status", "Open .txt"], 11)))
        card.append(("field", ("Your event command — status, speaker next, stop event", 11, 404)))
    else:
        card.append(("fields", ([("Event title", 185), ("Names, comma separated", 185)], 11)))
        card.append(("checkbox", ("Confirm battery", 11)))
        card.append(("buttons", (["Start event", "Status", "Open .txt"], 11)))
        if ev.get("document"):
            card.append(("row", ([("[S2]", 11, "#6c7488", {}), ("[New name]", 11, "#6c7488", {}),
                                  ("Rename", 11, "#d7def0", {}), ("MD copy", 11, "#d7def0", {}),
                                  ("TXT copy", 11, "#d7def0", {})])))
    ops.append(("card", card))
    if ev.get("running"):
        for block in SEGMENTS:
            ops.append(("text", (block["header"], 12, "#d8c8a9", {"serif": False,
                                                                   "line_height": 17})))
            ops.append(("editor", (block["text"], 15, 68)))
    else:
        for message in snap["conversation"]["messages"]:
            ops.append(("text", ("{} [{}]  {}".format("you" if message["role"] == "user" else "elaria",
                                                   message["channel"], message["text"]),
                                 12, "#9fd2ff" if message["role"] == "user" else "#e6e9f5",
                                 {"serif": False, "spacing": 1.25})))
    if not ev.get("running"):
        if snap["pending_plans"]:
            ops.append(("text", ("plans: " + " · ".join(
                f'#{p["id"]} {p["placed"]}/{p["total"]}' for p in snap["pending_plans"]),
                11, "#8f97ad", {"serif": False, "line_height": 15})))
        if snap["job_progress"]:
            ops.append(("text", ("jobs: " + " · ".join(
                "{} {}".format(j["label"], j["status"]) for j in snap["job_progress"]),
                11, "#8f97ad", {"serif": False, "line_height": 15})))
        if snap["holding"]:
            ops.append(("text", ("holding: " + " · ".join(h["title"] for h in snap["holding"]),
                                 11, "#8f97ad", {"serif": False, "line_height": 15})))
        if snap["offline_queue"]["counts"]:
            ops.append(("text", ("offline queue: " + json.dumps(snap["offline_queue"]["counts"]),
                                 11, "#8f97ad", {"serif": False, "line_height": 15})))
        ops.append(("fieldrow", ("talk to her — same conversation as voice", 11, "send")))
    return ops


AFTER_PALETTE = {"paper": "#211d15", "paper_rgb": (33, 29, 21), "border": "#443c2a",
                 "radius": 16, "pad": 16, "card": "#2a2418", "card_edge": "#443c2a",
                 "button": "#2c261a", "button_edge": "#4b4230", "button_ink": "#cfc2a6",
                 "field": "#282317", "field_edge": "#42392a", "faint": "#7d7360",
                 "ink": "#efe6d3", "ink_soft": "#cfc2a6", "amber": "#e2a95f",
                 "chip": "#3b3220", "chip_edge": "#554729", "editor": "#2f2919",
                 "editor_edge": "#443c2a", "lit": ("Amina",)}
BEFORE_PALETTE = {**AFTER_PALETTE, "paper": "#161922", "paper_rgb": (22, 25, 34),
                  "border": "#2b3040", "radius": 14, "pad": 14, "card": "#24251f",
                  "card_edge": "#454333", "button": "#242a3a", "button_edge": "#2b3040",
                  "button_ink": "#d7def0", "field": "#1e2230", "field_edge": "#2b3040",
                  "faint": "#6c7488", "ink": "#e6e9f5", "ink_soft": "#e6e9f5",
                  "amber": "#ffcb6b", "chip": "#242a3a", "chip_edge": "#2b3040",
                  "editor": "#2a2922", "editor_edge": "#454333", "lit": ("Amina",)}


def validate(ops: list, where: str) -> None:
    """Catch the one failure mode a hand-built op list has: a malformed tuple.

    Adjacent string literals inside a tuple concatenate, so `("text", ("a" "b", 17,
    color))` can quietly become an op with no size or colour. Every op is checked
    here rather than discovered as a blank strip in a picture.
    """
    for op in ops:
        if len(op) != 2:
            raise SystemExit(f"{where}: op tuple has {len(op)} elements, not (kind, args): {op[:2]}")
        kind, args = op
        if kind == "card":
            validate(args, where + "/card")
        elif kind == "text":
            if not isinstance(args, tuple) or not 3 <= len(args) <= 4:
                raise SystemExit(f"{where}: text op must be (value, px, color[, opts]): {args}")
            if not isinstance(args[1], int) or not isinstance(args[2], str):
                raise SystemExit(f"{where}: text op size/colour are the wrong types: {args}")
            if len(args) == 4 and not isinstance(args[3], dict):
                raise SystemExit(f"{where}: text op opts must be a dict: {args[3]!r}")
        elif kind not in PRIMITIVES:
            raise SystemExit(f"{where}: no primitive named {kind!r}")


# --------------------------------------------------------------------------- states
def main() -> int:
    out = Path(__file__).resolve().parent
    previous = previous_qml()
    if previous:
        for probe in ('plans: ', 'holding: ', '"daemon down"', "Your event command",
                      "Elaria · console"):
            if probe not in previous:
                print(f"warning: the before copy no longer matches the previous file ({probe})",
                      file=sys.stderr)
    states = {
        "01-empty": (snapshot(), event(), "empty"),
        "02-event-status": (snapshot(), LIVE_EVENT, "live"),
        "03-transcript": (BUSY_SNAPSHOT, event(), "busy"),
        "04-daemon-down": (DOWN_SNAPSHOT, DOWN_EVENT, "down"),
    }
    for stem, (snap, ev, key) in states.items():
        state = {"snap": snap, "eventSnap": ev, "feedUp": "daemon" not in snap,
                 "ownerName": "Darrel", "daemonQuiet": "daemon" in snap}
        headings = ("[" + ",".join("panel.segmentHeading({})".format(json.dumps(b["header"]))
                                   for b in SEGMENTS) + "]" if ev.get("running") else "[]")
        expressions = {
            "headline": "panel.eventHeadline()", "progress": "panel.eventProgress()",
            "footnote": "panel.eventFootnote()", "house": "panel.houseLines()",
            "headings": headings,
            "txt_path": "panel.txtPath({})".format(json.dumps(ev.get("document") or "")),
        }
        copy = speak(state, expressions)
        copy["badges"] = (["class mode · voice off"] if snap["class_mode"]["enabled"] else [])
        if snap.get("company", {}).get("company"):
            copy["badges"].append("company · mind what is said")
        if snap.get("showoff", {}).get("active"):
            copy["badges"].append("showing off · the room can hear")
        copy["knocks"] = [{"head": ("she would like a word" if len(snap["knocks"]) == 1 else
                                     f'she would like a word — {len(snap["knocks"])} waiting'),
                           "reason": (("urgent — " if k["urgency"] == "urgent" else "")
                                      + k["reason"]),
                           "meta": f'about {k["topic"]} · {k["referent"]} · knock {k["id"]}'}
                          for k in snap["knocks"]]
        copy["notice"] = ("she is not answering right now — nothing typed here goes anywhere, and "
                          "this window keeps knocking on her door.") if state["daemonQuiet"] else ""
        copy["status_line"] = snap.get("status_line") or ""
        note = "panel.plainNote(" + json.dumps(
            "OSError: the daemon died while the part was open") + ")"
        copy["send_status"] = speak(state, {"n": note})["n"] if key == "down" else ""
        copy["segments"] = list(zip(copy["headings"], [b["text"] for b in SEGMENTS]))
        copy["messages"] = [[speak(state, {"s": f"panel.speakerOf({json.dumps(message)})"})["s"],
                             speak(state, {"c": "panel.clockOf({})".format(json.dumps(message["ts"]))})["c"],
                             message["text"]]
                            for message in snap["conversation"]["messages"]]
        after = after_ops(copy, snap, ev)
        before = before_ops(snap, ev)
        validate(after, f"{stem}/after")
        validate(before, f"{stem}/before")
        after_height = render(out / f"{stem}-after.png", after, width=500,
                              palette=AFTER_PALETTE, minimum_height=700, lamp=True)
        before_height = render(out / f"{stem}-before.png", before, width=460,
                               palette=BEFORE_PALETTE, minimum_height=680)
        print(f"{stem}: after 500×{after_height}, before 460×{before_height}"
              f"{'  (before copy verified against the previous file)' if previous else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
