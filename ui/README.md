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
extra plumbing. It shows pending plans, parked items, offline queue, job
progress, the holding shelf and any pending knock (reason first). Class mode is
in the header; text input keeps working while voice is off.

`WlrKeyboardFocus.OnDemand` only: clicking into the input focuses it, but the
panel never steals a keystroke you didn't give it.

### Console first-run checklist

1. `quickshell -p ui/quickshell/console` starts with no QML errors.
2. `assist talk "hello"` → the line appears in the panel within one event.
3. `assist class on` → header badge appears, input still works, no audio.
4. Kill/restart the daemon → panel shows a daemon-down snapshot, then recovers.

## Hyprland binds

`assist doctor` prints your syntax. Lua (0.55+): append `ui/hyprland/elaria-binds.lua`.
Older: append `elaria-binds.conf`. `SUPER+grave` hold-to-talk, `SUPER+SHIFT+F12` halt.
