# HANDOFF — cold-resume state (Blueprint v2 wiring spec build)

Last updated: 2026-10-26 (scene-3b evidence triaged: streams A–C; the
release-path probe is the owner's next scene; merge gate RESTATED unchanged
and still red)
Branch: `arena/c2a7085d-elaria` · base `ed20344` (main)
Authority: MASTER BUILD PROMPT — ELARIA, BLUEPRINT V2 WIRING SPEC (2026-10-25)

Read this first after any interruption. Phase reports live in
`docs/phase-reports/` (DONE / DEFECTS FOUND / NEXT GATE / OPEN QUESTIONS in
each).

## 1. Where the build is

| phase | state |
| --- | --- |
| Phase 0 (model-ID audit) | DONE — report `docs/phase-reports/2026-10-25-phase0-model-id-audit.md`. Owner approved the full §4.1 pin set (2026-10-25); applied. |
| WP0 EYES | CODE COMPLETE. Scene 2 (2026-10-26) found the bind rungs still lying (root cause: the real `hyprctl -j binds` payload carries only `modmask` — stream-2 rebuild landed on the dumped shape). **GATE: scene 3 — ladder rerun (A/C truthful) + THE PRESS (Win+F2, one sentence, release) → journalctl tail with `model_version`.** PR #23 merges when stream-1 tests are green in sandbox AND the scene-3 ladder is truthful AND the press produces schema lines with `model_version`. |
| WP1 VOICE AND IDENTITY | **parked until the scene-3 report lands.** On its plate: Flare TTS-side check (live side of unknown #4 is CLOSED — Flare is in the gemini-3.8-live 40-voice catalogue); earcon before capture; echo-cancel (AEC) measurement; TTS cache hit-ratio split; mic input-gain review (mic peak 1.0 clipping); silence-verdict review. BH-H9 landed early in stream 1 (owner-joined). |
| WP2 HOME | not started (fix eventSnap first: unqualified `eventSnap` in nested scopes of `ui/quickshell/console/shell.qml` lines ~563–975; qualify as `panel.eventSnap`. Then the qmllint pre-gate productised). |
| WP4 EARS | not started. Strictly additive; hotkey PTT is the proven wake mechanism. |
| WP5 FLIGHT | not started. `[event] segment_minutes` is still 30.0 — §4.7 wants 25 (range 10–30) + Files API transport + reserve of the last 2 calls of each LA-day. Also owns the event-smoke segment-rotation timing defect (see §5). |
| WP3 COMPOSITOR | sixth position, trigger-based. PROMOTION TRIGGER: `rpm -q hyprland` or Bodhi shows 0.57 entering Fedora 44 repos → jumps the queue immediately (0.57 drops hyprlang; legacy binds die). Also replaces the legacy `bindr = , F2` release-stop (the ladder WARNs on it until then). |
| WP6 HYGIENE | not started. |

## 2. Decisions the owner made (2026-10-25/26)

1. **Pin fix: full §4.1 set applied.** Chat/intent + housekeeping +
   `model_file_fallback` = `gemini-3.5-flash-lite`; escalation ladder =
   `["gemini-3.5-flash-lite", "gemini-3.8-flash"]`; chat RPD config cap 400
   (`[quota.models.flash-lite] rpd_cap` / `flash_lite_rpd_cap`, stricter of
   rpd/cap enforced). Registry + forbidden list live in
   `src/assistant/model_registry.py`; the runtime guard refuses a forbidden ID
   at every API entry point.
2. **Forbidden-ID scan semantics:** hard-fail on IDs *configured or invoked*;
   guard constants, catalogue history, negative-test fixtures and prose
   mentions are exempt (reported as information). Doctor implements this.
3. **Pre-gates vs phase scope:** the qmllint pre-gate is recorded
   BLOCKED-known for the WP0 scene (eventSnap defect is WP2's named fix; this
   sandbox has no Qt toolchain). WP2 productises the pre-gate.
4. **HANDOFF.md created** as the running state document (this file).
5. **Ad-hoc `elaria-ladder` ruling (open-question 1 of the WP0 report):**
   the design-side record says the ad-hoc script carried console + wake
   chains only; its wake journal sensor was known-bad (fixed by WP0's
   schema lines) and its rung E was the known false-negative. No unique
   checks beyond the productised reconstruction — but that record is
   [UNVERIFIED-laptop], so the scene includes
   `cat ~/.local/bin/elaria-ladder`; a unique rung there ⇒ reconcile before
   merge. Disposition after scene green: replace `~/.local/bin/elaria-ladder`
   with a shim (`exec assist ladder "$@"`); `elaria-console-open` STAYS
   (SUPER+SHIFT+F2 targets it until WP3); `elaria-door` stays unused.
6. **Scene-1 rulings (2026-10-26):** ladder bind parser must resolve
   Hyprland `$variables` from config-file definitions (`set = name, value`
   and `$name = value`) and test both forms; bare-F2 forbidden =
   press/dispatch bind only (`bindr = , F2` release-stop is WARN
   "legacy release-stop bind (WP3 replaces)", never STUCK); event chain
   rung E = N/A when no event is running, STUCK only when running AND the
   document is unreadable; the merge gate adds "the press produces schema
   lines with `model_version`"; env-dependent test failures get logged with
   an owning phase, never silently patched (bug6-class tests may be made
   hermetic — that was the pre-authorized exception).

## 3. Sandbox facts (this build environment — NOT the laptop)

- Headless container: no Hyprland, no PipeWire, no quickshell, no API key,
  no `rpm`. CPython 3.11 here; the laptop is CPython 3.14 — `uv sync` on 3.14
  is still [UNVERIFIED].
- Test baseline: **1,825 passed, 6 skipped** before scene 1; the scene-1
  rounds add ladder/schema/bug6 tests (re-run the suite for the current
  count). Plain `uv sync` installs the base runtime; the ML/voice stack stays
  behind `--extra voice`. Ruff clean on touched files.
- `uv` had to be bootstrapped (`pip install --user --break-system-packages uv`).
  Sandbox resets between turns wipe `.git` history state and the venv —
  reconcile against `origin/arena/c2a7085d-elaria` before committing.

## 4. Scene log and findings

### Scene 1 (2026-10-26) — RED-diagnosed. PR #23 stays open; WP1 stays parked.

Findings (owner report), and the disposition now on this branch:

1. **Ladder claimed Win+F2 press, Win+Shift+F2 raise, Win+Shift+F12 halt all
   ABSENT while live.** Root cause: `hyprctl -j binds` reports mods as
   WRITTEN — the owner's config binds through `$mainMod`-style variables and
   the parser never resolved config-file variable definitions. **Fixed on
   branch:** `_bind_entries()` resolves `set = name, value` and
   `$name = value` (plus `source =` includes) and tokenises both forms;
   unresolvable variables are reported in the evidence, never hidden.
   [TESTED-ONLY — the laptop confirmation is scene 2.]
2. **Bare-F2 semantics corrected:** forbidden = a bare-F2 *press/dispatch*
   bind. A legacy `bindr = , F2` release-stop is tolerated until WP3:
   the rung reports `WARN legacy release-stop bind (WP3 replaces)` and
   never goes STUCK on it.
3. **Event chain rung E:** N/A when no event is running; STUCK only when an
   event IS running and the live document is unreadable. (Rung E prints
   REACHED / STUCK / N/A; only STUCK fails a chain.)
4. **Suite triage owed (3 laptop failures vs sandbox green)** — per-test
   verdicts in §5. None is a WP0 regression [TESTED-ONLY: the same code is
   green in the sandbox and none of the WP0 diffs touch those paths].
5. **Merge gate (scene 2):** the ladder fixes land + scene 2 ladder shows
   truthful rungs + the press produces schema lines with `model_version`.
   Schema lines now carry `model_version=<model of record>` on
   transcription.landed / transcription.deferred / transcription.rejected,
   quota.counter (rejected), tts.synthesised / tts.failed (gemini route),
   and session.close when the session names a model.

### Scene 2 (2026-10-26) — bind rungs still lied; owner ordered three streams

Findings (owner report) and dispositions now on this branch (separate
commits per stream):

1. **Wake A / console C reported Win+F2 press=ABSENT, halt=ABSENT,
   raise=ABSENT + a phantom bare-F2 press** while all three binds are live
   [HW-PROVEN]. Root cause from the owner's truth dumps: the real
   `hyprctl -j binds` payload has NO `mod`/`mods` field — only the numeric
   `modmask` (64 = SUPER, 65 = SUPER+SHIFT). **Stream 2 rebuilt the parser:**
   modmask is authority (XKB bit layout, verified against the dump);
   config-text `$variable` expansion is fallback only; unresolvable or
   empty-expanding variables are NAMED in the evidence and can never
   masquerade as a bare-F2 press; chords match exactly. Regression tests
   are built from the real dumped bind shape (the three F2 entries
   verbatim; the F12 halt entry derived from the same shape +
   hyprland.conf:210). [TESTED-ONLY pending scene 3.]
2. **Notification privacy rule (stream 1, owner-pulled-forward):** knock
   notifications are signals — fixed title "Elaria wants to talk", fixed
   static body, zero dynamic content in argv, no content knob. BH-H9
   joined per owner authorisation: a silent knock = zero audio AND zero
   subprocess. The always-visible overlay pill is dot/pulse only now
   (content lives in console/journal/inbox). Waybar audited: already
   signal-only.
3. **Suite triage corrections (stream 3):** bug6 REOPENED — see §5.3 for
   the retraction and the real mechanism. `docs/event-spike.json`
   committed as a measurement record (annotation below + commit message
   only; the raw record is never edited).
4. **Scene-2 closures (owner-reported facts):** live pins applied, no
   `-latest` remains; doctor 39/41, registry OK, units match repo; voice
   models verified on account — configured_missing=[], Flare present in
   the gemini-3.8-live 40-voice catalogue (unknown #4 live side CLOSED;
   TTS side stays WP1); wake D/E REACHED; event rung E N/A works; mic
   peak 1.0 clipping → WP1 input-gain review; models.list still lists
   retired IDs (listing ≠ callability).

**event-spike.json annotation (2026-10-23 live run; raw record never
edited):** a 30-minute event WAV offered to `gemini-3.5-transcribe-live`
was refused with 400 INVALID_ARGUMENT — that model only serves real-time
bidirectional streaming (bidiGenerateContent), never generateContent on
a closed WAV. The run fell back to the proven batch engine (decision row
3). This hardware-confirms the §4.1 batch/live model separation. **WP5
cites this record** when wiring the segment/Files-API route choice.
[HW-PROVEN]

### Scene 3b (2026-10-26) — release path is the regression; sensors first

Owner hardware evidence (12:07–12:26) [HW-PROVEN]:
- The press bind fires via hyprland exec (session.open at 12:07:42 and
  12:21:17). The release never stops: the 12:07 session ran to
  `watchdog.close` at 303.8 s with no stop from the bindr. A manual
  `assist ptt stop` WORKS (ack JSON: session, processing:true,
  result:null) — daemon/CLI/socket/Live-flush innocent; suspicion
  concentrates on the bindr trigger itself (probe in §7).
- The pasted ack object (`ack_kind:on_it, played:false, cached:true`) is
  `ptt.stop`'s ACK — `speak=False` by design on release ("no spoken ack
  on release") — so `played:false` there is honest. What the evidence
  exposes is the REPORTING hole: no surface anywhere says whether a
  queued playback actually played (Stream B fixes the player chain and
  adds `ack.played`/`ack.failed` schema events with argv + error).
- Deferred audio kept (`audio/20261026-120742-1beaea.wav`, "retained for
  retry") with 0 user-turn calls at 12:12 — audit found NO consumer for
  kept no-final audio (§6.8 defect, owning phase WP5).
- Stream A sensors landed before any fix: `stop.requested`
  (source=cli|bind|watchdog) at every stop entry.

## 5. Lessons and watch items

1. **Daemon-was-stale lesson (scene 1):** the scene ran status-dependent
   rungs against a daemon that was not restarted on branch code. **Scene
   checklists must restart the daemon on branch code BEFORE any
   status-dependent rung** — `systemctl --user daemon-reload && systemctl
   --user restart assistant` right after checkout/sync, before doctor,
   ladder, and the press. (The WP0 report checklist is reordered
   accordingly.)
2. **Mic peak 1.0 — clipping watch (scene 2).** The proven Mic1 input is
   now hitting full scale (scene 1: 0.9981; scene 2: 1.0, clipping).
   **WP1 owns the input-gain review.** Anything that reads `peak` on the
   schema lines should be read against this baseline.
3. **Suite triage (scene-1 failures), one verdict per test:**
   - bug6 dictate ("no speech captured" instead of the mock transcript):
     **REOPENED 2026-10-26 — the earlier silence_floor mechanism claim is
     RETRACTED** (the live config contains no silence_floor at all, so the
     claim was unconfirmed and is contradicted). Real leak per the owner's
     diagnosis: **the CLI-subprocess dictate test opens the REAL mic**
     (~0 s of room audio → below any floor → "no speech captured"); the
     sandbox hides it because PipeWireCapture falls back to
     SimulatedCapture without pw-record. **Fix applied (stream 3):** an
     env-forced simulated-capture seam (`ASSIST_CAPTURE=simulated`,
     consulted at ptt.start and the hotword factory; autouse fixture in
     bug6-class tests, with the capture-wiring tests explicitly opting
     out). Status stays **[BROKEN-laptop, main-parity]** until the
     owner's re-run says green — pre-existing at `ed20344` (the same 3
     failures), NOT a WP0 regression and NOT gating PR #23. No report may
     claim it fixed while laptop evidence says otherwise.
   - `tests/test_event_cli_smoke.py` `_wait_segments ... 1 >= 2`:
     **env-dependent timing under load** — 3-second simulated segments
     (`--segment-minutes 0.05`) against a fixed 10-second wall-clock wait.
     **Logged to WP5** (event segment rotation owns the machinery); NOT
     patched here. [TESTED-ONLY diagnosis; failure observed on the laptop.]
   - `tests/test_stage_abcd_bughunt.py::test_bh_h9_...` (knock emitted sound
     despite `silent=True`): **env-exposed real defect — FIXED in stream 1**
     (owner joined BH-H9 into the notification-privacy stream). `emit()`
     honours `knock["silent"]` now: zero audio AND zero subprocess. Shared
     tests live in `tests/test_notify_privacy.py`. [TESTED-ONLY; the laptop
     audible behaviour is scene-3's to confirm.]

## 6. Known open defects (logged, not fixed — see phase reports)

1. `eventSnap` ReferenceErrors in `ui/quickshell/console/shell.qml` (~lines
   563–975 unqualified; WP2).
2. The reply-regression candidate cannot be proven from the sandbox: the
   retired ID `gemini-2.5-flash-lite` appears NOWHERE in the repo (0 hits),
   but the reply path ran on `-latest` aliases that can resolve server-side to
   it. Pinned now; proof needs a live call / `assist cost` failure rows on the
   laptop. If the owner's live `~/.config/assistant/config.toml` still names
   the retired ID, doctor now hard-fails on it.
3. File-fallback *logic* (swapping to `gemini-3.5-flash-lite` when the STT
   primary is unavailable) is not wired yet — the ID is pinned
   (`model_file_fallback`); the swap belongs to WP5.
4. Cached-TTS model (`gemini-3.8-flash-lite-tts`) is registry-pinned but not
   adopted — speech still rides `gemini-3.8-live` native audio (interim owner
   decision 2026-10-20; voice-identity adjacent → WP1 with the owner's ear).
5. ~~BH-H9 silent-knock defect~~ — FIXED in stream 1 (owner-joined);
   [TESTED-ONLY] pending the scene-3 desktop confirm.
6. Event-smoke segment-rotation timing (§5.3) — WP5.
7. bug6 real-mic leak — seam applied (§5.3), status [BROKEN-laptop,
   main-parity] until the owner re-runs. Not gating PR #23.
8. **Deferred-retry limbo (scene-3b audit, 2026-10-26) — owning phase WP5.**
   "retained for retry" is a MESSAGE ONLY: the no-final path
   (`transcribe.py` → `transcription.deferred` verdict=no_final) keeps the
   wav and says "retained for retry", but NOTHING consumes it — the
   offline queue (`enqueue_transcription`) only covers
   `pending_cloud_transcription` (low-confidence offline), never the
   no-final/watchdog-severed case. Contract owed (owner order): the kept
   12:07 wav (`audio/20261026-120742-1beaea.wav`) is the standing test
   case — it either eventually transcribes and answers, or is explicitly
   marked never-retried. No third state. [TESTED-ONLY audit; the limbo is
   visible in the owner's ledger.]
8. Machine facts to confirm on the laptop: `rpm -q hyprland` exact version
   (WP3 trigger watches for 0.57), quickshell 0.2.1 frozen (do not upgrade),
   Mic1 capture node non-silent (doctor now checks; run it there).

## 7. The next action

**Scene 3b (owner, laptop) — the release-path probe.** The gate is
RESTATED unchanged and still red: a NATURAL Win+F2 hold-speak-release
cycle must produce earcon at press, session close at release, final
transcript, spoken reply, and schema lines for each. WP1 stays parked.

1. **The bindr probe (manual editor edit — NEVER sed; HTML-escaping has
   bitten this project).** Add directly below hyprland.conf line 213:

   ```
   bindr = , F2, exec, sh -c 'date >>/tmp/elaria-release-probe.log'
   ```

   then `hyprctl reload`, one Win+F2 hold-speak-release cycle, then
   `cat /tmp/elaria-release-probe.log`, then delete the probe line.

   - **Timestamp present** → the bindr fires; diff the bind-exec vs
     terminal environments (an `env -0` dump through the same probe if
     needed) and find why `assist ptt stop` no-ops from the bind while
     working from a shell.
   - **File absent/empty** → the bindr NEVER fires on 0.56.2 legacy
     conf. Escalation recommendation (owner decision): the structural
     fix is the Lua release bind with `ignore_mods` (WP3) — propose
     pulling WP3 forward for the BINDS ONLY. Interim stopgap (never
     final; hold-to-talk UX is the settled design): temporary
     `SUPER+SHIFT+F3 = assist ptt stop --stop-source bind`.
2. **A clean cycle** on the branch build (daemon restarted on branch
   code first — the stale-daemon lesson): press → earcon; release →
   `stop.requested` schema line; transcript + spoken reply +
   `model_version` on the transcription line. `stop.requested` absent =
   the bind never fired; present-but-failed = the stop arrived.
3. **paplay the ack wav directly** to verify it:
   `paplay ~/.local/share/assistant/voice-cache/speech-c3355e59132b6af3283d.wav`
4. **The journal tail** 60+ s after a manual `assist ptt stop` of a live
   session — expect `transcription.landed` with `model_version`, the
   reply invocation, `quota.counter` 1 user-turn, `session.close`, and
   whether Flare spoke. (This tail is Stream C's trigger: its landing
   closes the completion-evidence record in §5.)

Both outcomes are decisions: a failed scene produces a log dump and a
diagnosis, never a retry loop. <=30 min, daylight.
