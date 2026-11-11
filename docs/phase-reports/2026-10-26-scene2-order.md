# Scene-2 order — three streams — phase report

Date: 2026-10-26 · Branch: `arena/c2a7085d-elaria` · PR #23 (merge gate
unchanged: truthful ladder A/C + a press producing schema lines with
`model_version`).
Evidence tags: [TESTED-ONLY] (sandbox), [UNVERIFIED] (needs the laptop),
[HW-PROVEN] (owner hardware), [BROKEN-laptop] (fails on the laptop until
re-run says otherwise).

## DONE

1. **STREAM 1 — notification privacy rule (owner-ordered, pulled forward).**
   Notifications are signals, not carriers.
   - Every knock notification via notify-send: title exactly "Elaria
     wants to talk"; body one fixed static sentence ("Open the console
     when you're free.") identical for every knock. No topic, no reason,
     no fragment, no dynamic string reaches argv. No config knob for
     content (`[initiative] notify_identity` removed; identity/title/body
     are frozen constants; identity keeps the knock's own channel name
     per §19.2). [TESTED-ONLY]
   - Urgent/class-mode variants change flags (urgency, silence, visual
     pulse) only — never content. [TESTED-ONLY]
   - Surface audit: content lives in console (owner-raised), journal,
     inbox only. The always-visible `elaria-overlay` pill is dot/pulse,
     never text (the caption label — live ASR words, check-in line, error
     text — removed from `ui/quickshell/shell.qml`; the feed's text field
     remains for owner-raised consumers). The console-fallback
     notification no longer carries the live-document path (journal via
     stderr keeps it). Waybar audited: already signal-only (count/state +
     "she has a stated reason" — existence, never content). voicetest
     `--notify`: static strings. [TESTED-ONLY]
   - **BH-H9 joined per owner authorisation** (logged as
     owner-pulled-forward, not scope creep): a silent knock (class mode
     OR `knock["silent"]`) emits zero audio AND zero subprocess —
     `KnockSignal.emit` never invokes the runner on that path. Shared
     tests in `tests/test_notify_privacy.py` (exact title equality; the
     leak property: distinctive topic/reason strings appear in NO argv
     element; static body pinned; urgent variant; class-mode + silent
     variants with a non-silent control contrast; no-content-knob guard;
     fallback-script and overlay signal-only guards). [TESTED-ONLY]
2. **STREAM 2 — bind rungs rebuilt on the truth dumps (WP0 gate
   remainder).** Scene-2 signature (SUPER binds ABSENT + one phantom bare
   -F2 press) root-caused: the real `hyprctl -j binds` payload carries no
   `mod`/`mods` field at all — only numeric `modmask` (64 = SUPER, 65 =
   SUPER+SHIFT on the dumped binds). Per the owner's rules:
   - the compositor-resolved modmask is TRUTH (read first; XKB bit layout
     verified against the dump); config-text `$variable` expansion is
     fallback only, never authority;
   - an unresolvable variable is named in the rung evidence; a variable
     expanding to empty is named AND its bind can never count as a bare
     key press (the rung-E disease is structurally forbidden);
   - bare-F2 semantics per ruling: bare-F2 press/dispatch forbidden;
     `bindr = , F2` release-stop = WARN "legacy release-stop bind (WP3
     replaces)", never STUCK; keycode-68 recognised when `key` is empty;
   - chords match exactly (SUPER+SHIFT+F2 never reads as SUPER+F2);
   - regression tests built from the owner's REAL dumped bind shape (the
     three F2 entries verbatim; F12 halt derived from the same shape +
     hyprland.conf:210), asserting the scene-3 gate directly. 25/25.
     [TESTED-ONLY — scene 3 turns this [HW-PROVEN].]
3. **STREAM 3 — corrections and evidence.**
   - **bug6 REOPENED and re-mechanised:** the silence_floor mechanism
     claim is retracted (no silence_floor in the live config). Real leak:
     the CLI-subprocess dictate test opens the REAL mic (~0 s captured →
     "no speech captured"). Fix: env-forced simulated-capture seam
     (`ASSIST_CAPTURE=simulated` at ptt.start + hotword factory; autouse
     in bug6-class tests; the capture-wiring tests opt out explicitly and
     still prove target wiring). 51/51 bug6-class green in sandbox.
     Status [BROKEN-laptop, main-parity] until the owner's re-run —
     pre-existing at ed20344, not gating PR #23. [TESTED-ONLY]
   - **docs/event-spike.json committed byte-identical** to the owner's
     dirty laptop copy (2026-10-23 live run); annotation lives ONLY in
     the commit message + HANDOFF §5; the raw record is never edited.
     WP5 cites it. [HW-PROVEN]
   - **scripts/record_elaria_samples.py diff judged:** the argparse
     `help=` `20%%` escape is deliberate and committed (argparse
     %-expands help strings; bare `20%` crashes `--help`); the plain
     `print()` `20%%` hunk is stray formatting and restored to `20%`.
     Paired `--help` smoke tests land with it — the deferred-debt pair
     "upstream %% fix plus scripts --help smoke tests" is closed.
     [TESTED-ONLY]
   - **HANDOFF §4/§5 updated:** scene-2 closures recorded (live pins
     applied, no -latest remains; doctor 39/41, registry OK, units match
     repo; voice models verified on account — configured_missing=[],
     Flare present in the gemini-3.8-live 40-voice catalogue, unknown #4
     live side CLOSED / TTS side stays WP1; wake D/E REACHED; event rung
     E N/A works; mic peak 1.0 clipping → WP1 input-gain review;
     models.list still lists retired IDs — listing ≠ callability).
   - **Optional small (done):** `assist voice models` records a live
     verification stamp (state_dir/voice-models-verified.json:
     configured_missing, catalogue facts); `assist doctor` consumes it
     and downgrades the "model ids unverified until live models.list"
     WARN to a pass citing the stamp. [TESTED-ONLY]
4. Suite after the streams: bug6-class 51/51, ladder 25/25, notify-privacy
   8/8, script-help smoke 2/2, voice-verification 3/3; full suite re-run
   green (see the commit). Ruff clean on touched files. [TESTED-ONLY]

## DEFECTS FOUND (logged, not fixed)

1. `eventSnap` unqualified references in `ui/quickshell/console/shell.qml`
   (~563–975) — WP2's named fix; qmllint pre-gate stays BLOCKED on it.
2. File-fallback *logic* not wired (ID pinned only) — WP5 territory.
3. Cached-TTS route (`gemini-3.8-flash-lite-tts`) not adopted — WP1 with
   the owner's ear (speech still rides `gemini-3.8-live` native audio).
4. Event-smoke `_wait_segments` 1≥2 — env-dependent timing under load
   (3-s segments vs a fixed 10-s wait); owning phase WP5. NOT patched.
   [TESTED-ONLY diagnosis.]
5. bug6 real-mic leak — seam applied; [BROKEN-laptop, main-parity] until
   the owner re-runs; no report may claim it fixed before that.
6. `docs/event-spike.json` records a hard API fact for WP5: a live
   transcription model refuses generateContent on closed WAVs (400) —
   the segment/Files-API route must keep batch/live separation.
7. Sandbox is CPython 3.11 vs the laptop's 3.14; `uv sync` on 3.14
   remains [UNVERIFIED].

## NEXT GATE

**Scene 3 (owner, laptop):** truth dumps already provided (2026-10-26) →
ladder rerun on branch code (restart the daemon FIRST — the stale-daemon
lesson) → **THE PRESS** (Win+F2, one sentence, release) → journalctl
tail.

Scene-3 gate (the rungs must read): Win+F2 press **PRESENT**, halt
**PRESENT**, raise **PRESENT**, bare-F2 press **ABSENT**, legacy
release-stop **WARN** retained; and the press's schema lines carry
`model_version=…` on the transcription line.

**Merge PR #23 when:** stream-1 tests green in sandbox (DONE) AND the
scene-3 ladder is truthful AND the press produces schema lines with
`model_version`. Then the `elaria-ladder` shim disposition (decision 2.5)
runs and WP1 opens (Flare TTS-side check, earcon-before-capture, AEC,
cache hit-ratio, mic-gain and silence-verdict review).

Both outcomes are decisions: a failed scene produces a log dump and a
diagnosis, never a retry loop.

## OPEN QUESTIONS

1. The truth dump shows the Elaria binds using literal `SUPER`/`SUPER SHIFT`
   (hyprland.conf:210–214) while the desktop binds use `$mainMod` — both
   forms are handled (mask authority + variable fallback); no question,
   recorded so scene 3 can spot drift if the config is edited later.
2. bug6 stays [BROKEN-laptop] until the owner's re-run — if it still
   fails there after the capture seam, the remaining variable is Python
   3.14 (the one sandbox fact that cannot be checked here) and the seam
   gets a scene-4 iteration. 
3. Mic input gain (peak 1.0, clipping) — WP1 scope, queued not urgent.
