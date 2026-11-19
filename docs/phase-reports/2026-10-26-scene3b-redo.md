# Phase report — scene 3b-REDO (streams D + E), 2026-10-26

Order: owner, 2026-10-26 16:27 evidence round. Two gate-blocking streams
on `arena/c2a7085d-elaria` (PR #23), sensors before fixes. Scope
discipline: what this order names is fixed; everything else is logged
under DEFECTS FOUND with an owning phase.

Tags: [HW-PROVEN] owner hardware evidence · [TESTED-ONLY] suite-pinned
in this sandbox · [UNVERIFIED] not yet observed · [BROKEN] fails where it
matters.

---

## DONE

### Stream D — release trigger (WP3-binds pull-forward, authorized)

1. **D.1 verified with citations before any fix.**
   - `bindri` (release + ignore_mods) **IS supported** in the 0.56.2
     legacy conf: Hyprland v0.56.2
     `src/config/legacy/ConfigManager.cpp` `handleBind` — `BINDARGS =
     command.substr(4)`, `case 'r': release = true;` `case 'i':
     ignoreMods = true;`; an unknown flag returns `"bind: invalid flag"`
     (typos surface at reload). [TESTED-ONLY, source-verified]
   - `hyprctl -j binds` does **NOT** expose `ignore_mods` in 0.56.2:
     `src/debug/HyprCtl.cpp` binds serializer emits exactly the owner's
     dumped field set (locked, mouse, release, repeat, longPress,
     non_consuming, auto_consuming, has_description, modmask, submap,
     submap_universal, key, keycode, catch_all, description,
     allow_input_capture, dispatcher, arg). [HW-PROVEN dump shape;
     source-verified]
   - Because the flag is supported, the Lua-migration fallback (D.3) is
     moot: the fix is the paste-safe append.
2. **D.2 — ONE paste-safe owner instruction** (no editor, no sed;
   HTML-escaping has bitten this project), leaving hyprland.conf line 213
   exactly in place:

   ```
   echo 'bindri = , F2, exec, assist ptt stop --stop-source bind' >> ~/.config/hypr/hyprland.conf && hyprctl reload
   ```

   The shipped repo fragments now carry the WP3 form as the reference:
   `ui/hyprland/elaria-binds.conf` release line is `bindri`, and
   `ui/hyprland/elaria-binds.lua` release bind carries
   `{ release = true, ignore_mods = true }` (the owner believed it was
   there; it was not). [TESTED-ONLY]
3. **D.4 — the ladder reads the flag truth from the dump OR the config.**
   (`src/assistant/ladder.py`.)
   - `BindEntry.ignore_mods: bool | None` — filled from the JSON field
     `ignore_mods` **if the compositor exposes it**; `None` = not
     exposed (0.56.2).
   - A config-text bind-line scan parses flag-combined keywords
     (`bindri`, `bindrl`, `bindl`, …) with the verified v0.56.2 flag
     table (`_BIND_FLAGS`; `c`/`g` imply release exactly as `handleBind`
     treats them). When hyprctl is unavailable, entries are rebuilt from
     the config text ("the truth from the dump OR the config either
     way"), with the same unresolvable-variable honesty as the JSON path.
   - Evidence now names the release form truthfully:
     `bare-F2 press bind=absent; WARN legacy release-stop bind (WP3
     replaces); release-stop ignore_mods present (bindri flag — WP3
     form, order-robust)`. The pinned substrings
     (`bare-F2 press bind=PRESENT (forbidden)` / `absent`, `WARN legacy
     release-stop bind (WP3 replaces)`) are untouched — scene 4 reads
     truth either way. [TESTED-ONLY]
4. **Double-stop idempotency** (the Win-first release fires both release
   binds): `assist ptt stop` on an already-closed session is a clean
   idempotent no-op **with its own schema line** — `stop.noop` (verdict
   `finish-in-flight` | `already-closed` | `no-active-session`) — and
   the response carries `noop: true`. Tested for the cold stop and the
   double-fire (two `stop.requested`, one `stop.noop`, one finisher).
   [TESTED-ONLY]

### Stream E — final flush ("the last code wall before her voice")

5. **E.2 — schema events that name the flush** (`src/assistant/` +
   `tests/test_scene3b_redo.py`):
   - `final.wait` (fields: `budget_s`, `collector=alive|done|none`,
     `activity_end_ok`) — **always emitted at flush**; its absence in a
     journal is the designed signal that we hung up before the flush
     arrived.
   - `final.received` (`text_chars`, `waited_s`) when the final text
     lands.
   - `final.timeout` (`waited_s`, `collector=…`) when it does not —
     naming the dead collector honestly (`collector ended with no final
     (live link died?)`, `budget expired after Ns`, `activity_end failed
     — final wait skipped`, …) instead of pretending to wait.
   - `reply.invocation` (`mode`, `text_chars`, `speak`) — the gate's
     "schema lines for each" needs the reply invocation as a journal
     fact, not only a persona-event line. [TESTED-ONLY]
6. **E.3 — the flush fix and the completed turn.**
   - The wait budget is named and configurable:
     `[transcribe] final_wait_s` (default 12.0, documented in
     `config.toml.example`); every `final.wait` line carries the budget,
     so a silent lengthening cannot hide. The old hidden constant
     (`FINAL_TRANSCRIPT_TIMEOUT_S = 2.5`) was too short and its
     `wait_for_live_terminal` returned instantly when the collector was
     already done — the same-second deferred↔close geometry.
   - **A clean stop with real text now completes the turn in every
     session mode**: reply invocation → (quota `user-turn` on the live
     path) → spoken reply. Command keeps its ladder/veto; conversation
     and narration get the same reply invocation. SILENCE HOTFIX rules
     1–5 are preserved: empty / below-floor / garbage sessions never
     reach the reply path (pinned test), and the narration pillar keeps
     its factual `Transcript saved …` narration line — her spoken answer
     rides in the reply. [TESTED-ONLY; the spoken half is gate-provable
     only on hardware]
7. **E.4 — "67 chars" clarified and recorded.** It was never transcript
   information: `session.close` detail computed
   `len(text or narration)`, and for a no_final close the text is empty,
   so it measured the fixed fallback narration ("No final transcript
   received; captured audio is retained for retry." — exactly 67
   characters). The detail is now honest:
   `text_chars=N (final|no_final|no_speech)`. [HW-PROVEN geometry;
   TESTED-ONLY fix]
8. **E.5 — kept-audio inventory** (recorded in HANDOFF §4; **WP5 owns
   the consumer — not built here**): 3 wavs with no retry consumer —
   `audio/20261026-120742-1beaea.wav` (12:07 watchdog session), session
   `714a2a8f37e6`'s wav (exact path in its `transcription.deferred`
   line; expected name form `20261026-122117-714a2a.wav` [UNVERIFIED
   name]), and session `05698335f231`'s wav (16:33 watchdog close;
   expected name form `20261026-163353-056983.wav` [UNVERIFIED name]).
   The deferred-audio contract stands: each either eventually
   transcribes + answers, or is explicitly marked never-retried — no
   third state.
9. **D.5 — the alias-causation RETRACTION** (HANDOFF §5.4 + §6.2). The
   `-latest`-alias theory is no longer the explanation and must not be
   re-asserted. Official cause of death: **release-never-fires +
   sever-without-final**. Model-ID pinning stands as hygiene on its own
   merits.

**Suite:** 1,880 passed, 6 skipped (was 1,866/6; +14 scene-3b-REDO
tests). Ruff clean on touched files. `uv sync` installs the base
runtime.

## DEFECTS FOUND

1. `transcription.landed` fires with `0 chars committed` on a
   silence-discarded session (the debug journal shows landed + silence
   verdict together). Semantically odd — a zero-char "landed" line next
   to `silence.verdict`. Owning phase: WP5 (transcription ledger
   semantics). [TESTED-ONLY observation]
2. `assist ptt stop --speak` is documented as an opt-in ("for command
   stop: speak the reply locally") while the reply path defaults
   `speak=True` when the flag is absent — the flag is effectively a
   no-op. Owning phase: WP6 (CLI help/behaviour parity). [TESTED-ONLY
   observation]
3. bug6 real-mic leak: status unchanged — **[BROKEN-laptop,
   main-parity]** until the owner's re-run says green. No report claims
   it fixed. (Pre-existing at `ed20344`.)
4. The expected wav name forms in the kept-audio inventory are derived
   from the `{YYYYMMDD-HHMMSS}-{sid[:6]}.wav` naming rule, not read from
   the journal lines. Scene 4 should read the exact paths from the
   `transcription.deferred` audio-kept detail. [UNVERIFIED]
5. Deferred-retry limbo (§6.8, WP5) unchanged — stream E only makes its
   decisions visible (`final.*` + honest close detail).

## NEXT GATE

**Scene 4 (owner, laptop) — the natural-cycle gate, still red.** The
checklist is prepared in HANDOFF §7 (pull + daemon restart FIRST; the
paste-safe bindri append above; one natural Win+F2 cycle reading
`stop.requested source=bind` as the probe (the bindr probe is RETIRED);
one deliberate Win-first release proving double-stop idempotency; the
journal tail). The gate is unchanged: a NATURAL Win+F2 hold-speak-release
cycle must produce earcon at press, session close AT RELEASE, final
transcript, spoken reply, and schema lines for each. WP1 stays parked.

## OPEN QUESTIONS

1. The owner's ear-confirmation of the session-open cue is still pending
   (the sensor says `ack.played player=pw-play`; the ear decides). The
   earcon is FIXED and sensor-proven [HW-PROVEN-sensor] — do NOT re-fix.
2. Line 213 (legacy `bindr`) stays in place by design (append-only). The
   ladder will keep WARNing `legacy release-stop bind (WP3 replaces)` on
   it until the owner chooses to remove it — is that the desired steady
   state, or does WP3 do the removal on the Lua switch?
3. Narration-mode replies are now on (the gate's spoken reply requires
   it). If the dictation pillar should stay mute and answer only in
   conversation/command modes, say so and the narration half reverts.
4. The third kept wav's exact path (owner-reported "one more") is not yet
   captured — please confirm the three paths at scene 4.
