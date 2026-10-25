# Console home — before and after (2026-10-25)

Owner requirement c — *the console is her home / notebook: warm, personal,
prose-readable.* (§19 is how `README.md` and `src/assistant/console.py` cite the
surfaces section; this checkout's copy of `assistant-blueprint.md` stops at §18,
so the wording of record for that requirement is the round brief itself, dated
2026-10-25.) The panel had drifted into a formal admin
surface: empty labelled fields, a counter strip of zeroes, `plans:` / `jobs:` /
`holding:` rows, machine status in admin red. This round changed the dress,
posture and typography of `ui/quickshell/console/shell.qml` and **no
behaviour at all**.

## Read this before believing any pixel here

These are **not screenshots**. They are offline renderings of the QML's own copy
and geometry, produced in a headless sandbox by [`render.py`](render.py). No
Quickshell, no Wayland, no compositor, and no font fallback from the owner's
Fedora box ever touched them. The panel has still never been rendered on her
hardware — that is the open gate in
[`hardware-gate.md`](hardware-gate.md), and it is the only thing that can close
it.

What makes them more than mock-ups:

* the **after** copy is executed, not typed. `render.py` extracts the panel's
  own phrasing functions (`houseLines`, `eventHeadline`, `eventProgress`,
  `eventFootnote`, `speakerOf`, `segmentHeading`, `plainNote`, `txtPath`,
  `clockOf`) out of the shipped QML, runs them under node against the fake
  snapshots in that script, and draws what comes back — so the sentences in
  these images are the sentences the panel produces;
* the **before** copy reproduces the previous file's inline bindings
  literally, and the script refuses to stay quiet if those probes no longer
  match it. `render.py::previous_qml()` asks git for `HEAD~1` of the QML and
  falls back to `HEAD`; this checkout has a single-commit history, so today the
  pre-round file *is* `HEAD` — the fallback is what runs, and it is what the
  images were checked against.
* sizes, colours, line heights and paddings are the QML's own numbers — 20 px
  serif heading, 16 px card headline, 14 px serif prose at 1.5 leading, 12 px
  house sentences, 11 px quiet timestamps, a 500×700 window, and `#e2a95f` as
  the single accent. The `before` pair uses the *previous* file's numbers and
  colours: a 17 px headline, cyan/teal chrome (`#7fe3d4`, `#9fd2ff`), a purple
  `SHOW-OFF` badge (`#e08cff`) and `#ff6b6b` — real admin red — for
  `daemon down`.

Where a rendering has to simplify, it is listed here:

* the row `a name to add · Add · Amina · Otieno · Speaker 3` is drawn as text;
  in the QML it is a field, a button and a scrollable strip of roster chips;
* the transcript and the prose feed are **scroll areas** in the real panel
  (`feedFlick` / `eventTranscript`, minimum 120 px, absorbing whatever the fixed
  700 px window leaves after the header, the notice, the knock shelf, the
  notebook card and the note row). `render.py` has no scroll, so states 03 and
  04 grow their canvas past 700 px instead of squeezing the scroll area — the
  content is complete, the height is not the window height;
* the card sizes itself off `implicitHeight` in QML and off measured ops here;
  both are self-measuring, but only one of them will be checked against a font
  that exists.

## The four states

| pair | what it is | what to look at |
| --- | --- | --- |
| `01-empty-*` | nothing said, nothing held, no event open | the before page is labels and zeroes; the after page is `nothing holding right now — the house is quiet.` and nothing else |
| `02-event-status-*` | a live fake (`--no-transcribe`) event, 3 parts landed, 1 still queued | status as a sentence — `3 parts written, 1 catching up.` — with quota, disk, reset and transport kept as a quiet footnote line, and the path on its own line |
| `03-transcript-*` | the one conversation, plus plans / jobs / holding / parked and a knock | prose paragraphs with `Darrel said` / `Darrel wrote` / `Elaria answered` and quiet timestamps; every count now inside a sentence |
| `04-daemon-down-*` | the daemon stopped mid-event | `the mic went quiet — she is not answering, so nothing new is being written on this page.` in warm amber, plus the hotfix hand-off line `she heard nothing` shown verbatim; no red, no code, no trace |

Regenerate (needs Pillow and node, and a checkout):

```bash
# from the repo root; Pillow + node, and the images land next to this file
python3 docs/console-home/render.py
```

One timing caveat: the `before` half is read out of git history, so this is only
reproducible from a checkout where `HEAD~1` still holds the pre-round panel —
i.e. the console-home commit itself. Run later than that, the probes fail on
purpose rather than drawing the wrong page; treat these PNGs as the record they
are. (Checked on 2026-10-25 from the round's own commit, where `HEAD~1` is the
pre-round panel: all eight files came back byte-identical. On another box the
font files differ, so expect the same sentences at the same sizes with different
letterforms — and therefore different wrapping and canvas heights.)

## What did not move

The feed and its 1500 ms retry, `assist talk` (the same handler voice uses —
still one conversation), the knock accept/later/decline actions, every event
control and its `assist event …` argument list, the append-only document mirror
(fingerprint → cat → parse → diff → reload only on change), the embedded segment
editors with their 650 ms autosave and stale-edit tail copy,
`WlrKeyboardFocus.OnDemand`, the Top layer and the `elaria-console` namespace,
and the systemd crash fallback. Those are pinned, command for command, by
`tests/test_console_home.py::FROZEN_COMMANDS`; a "cosmetic" edit that changes
what the console *does* has to go through that file.
