# Console home — the owner's eyeball gate (hardware only, still open)

**Gate step 0 — run `elaria-ladder console` first, expect A–E (E: "surface registered - she is on screen").**

## Branch gate — before merge, not after

No PR touching ui/quickshell/** merges until the owner has run, on the PR branch itself:

```text
git checkout <branch> && uv sync
systemctl --user restart elaria-console
elaria-ladder console        # must reach E before merge
```

The sandbox has no Quickshell and no Wayland; renderings and static scans are aids, not proof. The ladder on the branch is the only QML truth.

For GATE-FIX 2, leave the PR **open, not merged** until the owner posts the
branch/commit tested and the A–E result. Also run plain `uv sync`, then
`systemctl --user restart assistant` and `systemctl --user is-active assistant`:
the result must be `active`. A green suite or a successful package sync in the
sandbox does not close either hardware gate. Re-run on the branch if QML changes
after the owner's test.

### Reference build

Reference build (owner, 2026-10-25), the build this round targets exactly:

| command | reported result |
| --- | --- |
| `quickshell --version` | quickshell 0.2.1 (revision dacfa9de, Fedora) |
| `rpm -q qt6-qtbase` | qt6-qtbase 6.11.2-3.fc44 |

Qt is >= 6.3, so the two inline `component` blocks are supported here. The
2026-10-25 D-rung failures were **not** inline-component parse errors:

- `Row.topMargin`: replaced with `anchors.topMargin` on the owning Item/Row
  anchor group (PR #21).
- `Text.leftPadding`: the conservative static scan replaced it with the
  owning item's `anchors.leftMargin` (PR #21).
- `TextArea.lineHeight` at 811:37: `TextArea` inherits `TextEdit`, not `Text`.
  The unfocused segment now renders through a plain `Text` with 1.5 leading.
  Focusing reveals the same plain-text editor with native caret/selection
  metrics; blurring restores the prose view using the editor's current text,
  including pending edits. No HTML conversion, new save path or timer change.

`tests/test_console_home.py` now fails closed on **every** declarative property
binding and unreviewed type, rather than just margin/padding/inset names.
The audit includes semicolon-packed bindings, grouped and attached members,
`Behavior on …` targets, and the `HomeButton: Button` / `NoteField: TextField`
inline inheritance. Its explicit inventory covers all 23 type names:
`ShellRoot`, `PanelWindow`, `Process`, `SplitParser`, `Item`, `Rectangle`, `Row`,
`Column`, `Text`, `TextArea`, `CheckBox`, `Flickable`, `Repeater`, `Gradient`,
`GradientStop`, `Timer`, `Behavior`, `NumberAnimation`, `ColorAnimation`,
`Button`, `TextField`, `HomeButton`, `NoteField`. Adding a member requires an
owner-map review, never an implicit pass. This is a deliberately conservative
reviewed subset, not a substitute QML engine. Hardware re-gate: the ladder
**on this PR branch** must reach E.

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
   ~1.5 leading, timestamps small and quiet. In a live event, click a segment:
   the native plain-text editor must focus, select and edit normally; walk away
   and confirm the 1.5-leading view shows the edits (including during autosave).
   If the measure or the leading is wrong for your eyes at your distance, say
   so — that is a typography change in
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

On the reference build above, **do not start by hoisting the inline components**:
Qt 6.11.2 supports them. Check `journalctl --user -u elaria-console -b` for the
QML property named in the error. Known failures were `Row.topMargin` at
`shell.qml:410` and `TextArea.lineHeight` at `shell.qml:811`; the static scan
also rejected `Text.leftPadding`. The replacements are owner-scoped anchor
margins and `Text`-owned leading, not another guessed Controls property.
The scan now rejects every unaudited type/member. If a future machine reports
a genuinely older Qt (< 6.3), then the mechanical fallback still applies:
hoist `HomeButton` and `NoteField` into
`ui/quickshell/console/HomeButton.qml` and `NoteField.qml`.

## After merge — on main (not a replacement for the branch gate)

- Hold `Win+F2`, speak, release: local earcon, then the Flare reply.
- A silence verdict must still say `she heard nothing`.
- In a terminal, `assist dictate` still uses Enter to stop.

## Deferred debt — unchanged by this fix

> **WP0 paid this list down (2026-10-25)** — `assist ladder` / `elaria-ladder`
> ship in `src/assistant/ladder.py` (chains console/wake/voice/event, rung E =
> journal "Configuration Loaded" proxy + `elaria-console` layer namespace);
> `assist doctor` gained the quickshell-binary check; the daemon writes the
> §4.8 schema lines to stdout (`ts level event session_id peak verdict
> detail`); a 5-minute PTT session watchdog auto-closes with a visible
> marker. The items below are kept as written for that PR's record.

- `assist ladder` productisation; upstream `%%` fix plus scripts `--help`
  smoke tests; `assist doctor` Quickshell-binary check.
- Structured plain-language daemon lifecycle lines to stdout (session
  open/close, verdicts, failures) so journald becomes a real sensor. Until
  then the ladder's wake chain must use `assist status` fields
  `dictation_active` / `ptt_session_id`, **not journal grep**; the owner's
  assistant journal was empty even during live sessions.
- PTT session watchdog: a missed release bind left the owner's mic open for
  about nine minutes. A configurable ceiling (suggested five minutes) and a
  visible auto-close marker belong to the debt round; this PR does not claim
  to implement a watchdog.

## Also worth an eye, since only you can see it

- the lamp gradient at the top of the page: too much, too little, or right;
- the amber accent: it now marks her name-adjacent state (mode words, the knock
  line, progress, focus rings). If it reads as a warning colour to you, that is
  the wrong instinct and the accent needs to move to the ink side;
- `Elaria · home` vs `Elaria · console` — the heading is one string at the top of
  the QML (`houseName`), so rename it if you prefer the other word;
- the owner's name is written into the QML as a display-only constant
  (`ownerName: "Darrel"`); it is not config, and this round did not add config.
