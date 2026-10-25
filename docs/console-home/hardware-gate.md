# Console home — the owner's eyeball gate (hardware only, still open)

Nothing in this round was rendered on the Fedora desktop. The suite can prove the
sentences are generated from the snapshot and that the wiring did not move; it
cannot prove the page looks like somewhere she wants to live. That is yours to
judge, at arm's length, on her monitor.

Raised the way you raise it (your `Win+Shift+F2` binding; there is no console
bind shipped in this repo, and binds were out of scope here — `systemctl --user
restart elaria-console` also works). Read the caveats in
[README.md](README.md) first: the images in this folder are renderings, not
captures, so judge the words and let these be the checklist for the look.

## Pass conditions

1. **Empty state, not empty fields.** Open the console with nothing said,
   nothing held and no event open. There must be no `plans:` / `jobs:` /
   `holding:` row and no counter strip of zeroes — instead the single sentence
   `nothing holding right now — the house is quiet.` Nothing on the page may be
   a label standing over nothing.
2. **Status as a sentence, during a real event.** Start a zero-call soak:
   `assist event start --no-transcribe --battery-ok --segment-minutes 2`
   (it costs 0 calls). The notebook must read `Elaria is listening — <speaker>,
   m:ss into this part.` and, once parts have landed, a sentence like
   `3 parts written, 1 catching up.` Calls/disk/reset/transport stay available
   as one quiet footnote line — no JSON, no bare `calls 2/25 · TPM` table feel.
   Stop it: `assist event stop`.
3. **Prose at arm's length.** With a few turns in the conversation (say something,
   then `assist talk "and now by hand"`), the transcript must read like a page:
   names as people (`Darrel said`, `Darrel wrote`, `Elaria answered`), serif,
   ~1.5 leading, timestamps small and quiet. If the measure or the leading is
   wrong for your eyes at your distance, say so — that is a one-line change in
   the QML, and it is the point of this round.
4. **One deliberate failure.** While an event is open, `systemctl --user stop
   assistant`. The console must say, in warm text and not in red: the event
   headline becomes `the mic went quiet — she is not answering, so nothing new
   is being written on this page.` and the notice line
   `she is not answering right now — nothing typed here goes anywhere, and this
   window keeps knocking on her door.` No traceback, no code. Then
   `systemctl --user start assistant` and watch it recover on its own. Capture
   belongs to the service, and the console never stops it — if stopping the
   service stopped capture *because of this panel*, that is a defect, not a
   cosmetic miss.
5. **Nothing functional moved.** Start/stop/speaker-next/add-speaker, `Status`,
   `Open .txt`, the rename + `MD copy` / `TXT copy` row, editing a landed segment
   in place and walking away (autosave after ~650 ms), and the daemon-down
   fallback script must all behave exactly as they did before this round.
6. **Posture.** No keystroke is stolen unless you click into the note; the panel
   stays anchored top-right, `elaria-console` on the Top layer, and mode words
   (`class mode · voice off`, `company · mind what is said`,
   `showing off · the room can hear`) only appear while the mode is on.

## If the panel is blank

One known-fragile thing was introduced here: the two inline `component` blocks
(`HomeButton`, `NoteField`) at the end of the PanelWindow need Qt 6.3+. Check
`journalctl --user -u elaria-console -b` for a QML parse error. If your
Quickshell is older than that, say so and the fix is mechanical: hoist those two
blocks into `ui/quickshell/console/HomeButton.qml` and `NoteField.qml` — nothing
else in the file uses syntax the previous version did not already use.

## Also worth an eye, since only you can see it

- the lamp gradient at the top of the page: too much, too little, or right;
- the amber accent: it now marks her name-adjacent state (mode words, the knock
  line, progress, focus rings). If it reads as a warning colour to you, that is
  the wrong instinct and the accent needs to move to the ink side;
- `Elaria · home` vs `Elaria · console` — the heading is one string at the top of
  the QML (`houseName`), so rename it if you prefer the other word;
- the owner's name is written into the QML as a display-only constant
  (`ownerName: "Darrel"`); it is not config, and this round did not add config.
