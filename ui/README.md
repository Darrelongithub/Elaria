# UI surfaces (Phase 2) — Waybar, overlay, Hyprland binds

All three are **dumb renderers** (§1.1): state logic lives in
`src/assistant/waybar.py` and `src/assistant/overlay.py` (headless-tested).
These files just display what the daemon already decided.

## Status: UNVERIFIED on real hardware

Built and logic-tested headless. Waybar/Wayland/Quickshell behaviour needs
one pass on the Fedora desktop — checklist below. Nothing here can break
the daemon; worst case a surface renders wrong while `assist` stays right.

## Waybar

```bash
# merge ui/waybar/module.json into ~/.config/waybar/config (modules-right += "custom/elaria")
cat ui/waybar/style.css >> ~/.config/waybar/style.css
pkill -SIGUSR2 waybar   # reload
```

- Uses **streaming** `assist status --waybar --follow` (Waybar re-renders per
  JSON line), so `● listening` lights within the ack, no 2s poll lag.
  If your Waybar build dislikes long-running exec, fall back to
  `"exec": "assist status --waybar", "interval": 2` — same JSON.
- Left-click toggles PTT; right-click is `assist halt` (panic, §4.4).
- `custom/elaria-voicetest` is the §13.10 LED: green the instant
  `assist-voice-test run` accepts your voice.

## Quickshell overlay

```bash
quickshell -p ui/quickshell            # try it in a terminal first
cp systemd/elaria-overlay.service ~/.config/systemd/user/
systemctl --user enable --now elaria-overlay
```

Feed: `assist events --overlay` (one JSON state/line). The pill shows
listening pulse → live partials → final (lingers ~4s) → hides; the silence
ladder's soft check-in renders as its own quiet state.

### First-run verification checklist (Fedora desktop)

1. `quickshell -p ui/quickshell` starts with no QML errors in the log.
2. `assist ptt start` → pill appears **without focus leaving your editor**
   (keep typing — characters must land in the editor, not the void).
3. `hyprctl layers` shows namespace `elaria-overlay` on the overlay layer.
4. Speak (or simulated capture) → partials update in the pill; release →
   final lingers, then pill hides.
5. Kill the daemon (`systemctl --user stop assistant`) → pill hides rather
   than freezing on “Listening…”.

If `Process`/`SplitParser` import names differ in your Quickshell version,
only the feed block at the bottom of `shell.qml` needs adjusting — everything
above it is property bindings.

## Elaria console (Stage B, §19.1)

```bash
quickshell -p ui/quickshell/console        # dedicated panel, same repo
cp systemd/elaria-console.service ~/.config/systemd/user/
systemctl --user enable --now elaria-console
```

A dedicated panel, not a second assistant: it renders
`assistant/console.py::ConsoleService.snapshot()` from
`assist console --follow` and sends turns with `assist talk "<text>"`. The
conversation is the daemon's single store, so voice→console continuity needs no
extra plumbing.

**It is her home, not an admin panel** (blueprint §19, owner requirement c;
console-home round, 2026-10-25). There are no field labels and no empty colon
rows: pending plans, job progress, parked review/unsorted items and the
holding shelf (follow-ups and findings that are hers to keep) each read as a
sentence, and when none of them has anything to say the page says
`nothing holding right now — the house is quiet.` instead of standing there
with blank labels. The transcript is prose — `Darrel said`, `Elaria answered`,
quiet timestamps, serif at book measure — and her input line is a passed note
with exactly the voice-path semantics, not a command box. State changes fade;
failures are plain language ("she is not answering right now…"), never a stack
trace, never a code, never admin red. Warm paper, one amber accent, and the
heading is `Elaria · home`.

Class mode, company and show-off stay visible in the header as words whenever
they are on — never implied by absence; text input keeps working while voice is
off. The event notebook in the same panel keeps every control it had (speaker
select/add, status, Start/Stop, `Open .txt`, the embedded segment editors and
their 650 ms autosave) running the identical `assist event …` commands; only
their dress changed. Any pending knock still arrives reason-first on its own
shelf. Before/after renderings and the owner's eyeball gate: `docs/console-home/`.

`WlrKeyboardFocus.OnDemand` only: clicking into the input focuses it, but the
panel never steals a keystroke you didn't give it.

### Console first-run checklist

1. `quickshell -p ui/quickshell/console` starts with no QML errors.
2. `assist talk "hello"` → the line appears in the panel within one event.
3. `assist class on` → the header line `class mode · voice off` appears, input
   still works, no audio, and a knock arrives as a silent Waybar pulse (no
   popup, no sound).
4. Kill/restart the daemon → the panel says "she is not answering right now" in
   warm text (no red, no code), then recovers on its own.
5. `assist knock raise --topic test --reason "While testing, I found the knock path." --kind finding --referent "the knock test"`
   → Waybar `✦ ·wants to talk`, one notification under `Elaria · knock`, one short
   sound. `assist knock decline <id>` → the notification state clears.
6. Enrol the voiceprint (`assist-voice-test enroll`), then say "Elaria, show
   off" with the owner present: the header shows `showing off · the room can
   hear`, the room hears the announcement, and `assist showoff status` shows
   `permissions: []` and the demo sandbox path. Say a guest command ("delete his
   files") → refusal, mode off, `assist showoff status` reports `never_list`.
7. Say "I'm not alone" → the header shows `company · mind what is said`; ask
   her for a stored password → deflection, not the value. Say "I'm alone now" →
   the line fades out and the answer returns.
8. If the sound is silent, install the asset somewhere permanent:
   `mkdir -p ~/.local/share/assistant/sounds && cp ui/sounds/knock.wav ~/.local/share/assistant/sounds/`
   (the config default points there; the code also falls back to `ui/sounds/`).
9. The console-home pass (empty-state sentence, status sentence during a
   `--no-transcribe` event, prose transcript at arm's length, one deliberate
   failure) is the owner's eyeball gate: `docs/console-home/hardware-gate.md`.
   Nothing in this round was rendered on real hardware, so that gate is open
   until she reports it.

## Hyprland binds

`assist doctor` prints your syntax. Lua (0.55+): append `ui/hyprland/elaria-binds.lua`.
Older: append `elaria-binds.conf`. `SUPER+grave` hold-to-talk, `SUPER+SHIFT+F12` halt.
