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

### Scene 3b-REDO (2026-10-26) — streams D + E; sensors before fixes

Owner hardware evidence (16:27–16:40) [HW-PROVEN]: earcon FIXED and
sensor-proven (`ack.played ack_kind=session_open player=pw-play` on the
press) — do NOT re-fix; release bind DEAD (the §7 bindr probe log absent
after a real cycle; no `stop.requested`; the session ran to its watchdog
close). Stream C NEGATIVE: the 12:25 manual stop closed session
`714a2a8f37e6` with `transcription.deferred` no_final in the same second
as `session.close`, quota 0 user-turn — "she has never answered anything,
from any path, all week". Both no_final closes reported "67 chars".

Verified facts (research, this order) [TESTED-ONLY, cited in the phase
report]:

- **`bindri` IS supported on 0.56.2 legacy conf.** v0.56.2
  `src/config/legacy/ConfigManager.cpp` `handleBind`: `BINDARGS =
  command.substr(4)`, `case 'r': release = true`, `case 'i': ignoreMods =
  true`; unknown flags return "bind: invalid flag" (typos surface at
  reload). ⇒ the paste-safe `bindri = , F2, …` line is valid.
- **`hyprctl -j binds` does NOT expose `ignore_mods` in 0.56.2.** v0.56.2
  `src/debug/HyprCtl.cpp` binds serializer emits exactly the owner's dump
  field set (locked, mouse, release, repeat, longPress, non_consuming,
  auto_consuming, has_description, modmask, submap, submap_universal,
  key, keycode, catch_all, description, allow_input_capture, dispatcher,
  arg). ⇒ the ladder reads the flag from the dump "if exposed", and from
  the config-text flag letters (`bindri` vs `bindr`) otherwise.
- **"67 chars" is NOT transcript information.** It is
  `len(text or narration)` in the `session.close` detail: for a no_final
  close the user text is empty, so it measured the fixed fallback
  narration "No final transcript received; captured audio is retained for
  retry." — 67 characters. The close detail now reports
  `text_chars=N (final|no_final|no_speech)` honestly.
- **The flush DID wait, but short and silent.** stop → close signals
  activity_end + a bounded final wait
  (`FINAL_TRANSCRIPT_TIMEOUT_S = 2.5`) — too short — and
  `wait_for_live_terminal` returns instantly when the collector is
  already done (the severed-link geometry: same-second deferred↔close).
  The wait budget is now `[transcribe] final_wait_s` (default 12.0,
  visible in every `final.wait` line) and the journal carries
  `final.wait` / `final.received` / `final.timeout` naming the dead
  collector honestly. `final.wait` always fires at flush — its absence
  means we hung up before the flush arrived.
- **Kept-audio manifest (owner 2026-10-27: 6 wavs, 4 unresolved — WP5
  owns the consumer, do NOT build it here):**
  - `audio/20261026-120742-1beaea.wav` (12:07) — UNRESOLVED
  - `audio/20261026-122117-714a2a.wav` (12:21, session 714a2a8f37e6) —
    UNRESOLVED [path verified from the deferred line]
  - `audio/20261026-163353-056983.wav` (16:33, session 05698335f231) —
    UNRESOLVED [UNVERIFIED name — read the deferred line]
  - `audio/20261027-064404-f03c11.wav` (06:44) — UNRESOLVED
    [UNVERIFIED name — read the deferred line]
  - `audio/20261026-191330-d297f1.wav` (19:13) — **RESOLVED = `<noise>`**
    (the stream-F diagnostic found no intelligible speech)
  - `audio/20261027-064450-77cc4efb.wav` (06:45, session 77cc4efb1886)
    — **RESOLVED = replied** (fallback transcription answered the turn)
    [UNVERIFIED name — read the deferred line]
  The four unresolved either eventually transcribe+answer or are
  explicitly marked never-retried — no third state (§6.8).

### Scene 4 (2026-10-26) — wall one falls; the final is on the wire

- **Release bind WORKS** [HW-PROVEN]: the owner's natural cycle logged
  `stop.requested source=bind` at release. **Wall one is fallen.**
- **Flush mechanism PROVEN-WORKING** [HW-PROVEN]: `final.wait
  collector=alive activity_end_ok=True → final.timeout waited_s=12.054 →
  deferred no_final, text_chars=0`. Quota 0 user-turn; silence rules
  respected. Wall two is refined, not fallen: the mechanics all run and
  the gate is still red — the FINAL TRANSCRIPT itself is missing, on the
  wire, four sessions running.
- 4th wav kept: `audio/20261026-191330-d297f1.wav` (backlog above).
- Owner ruling (this order): stream F asks why the Live API withholds
  the final — sensors before fixes, protocol citations before any fix,
  $0 spend except F.4's single diagnostic file call.

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
4. **Alias-causation for the silence week is RETRACTED (owner ruling
   2026-10-26, scene 3b-REDO stream D).** The theory that `-latest`
   model aliases resolving server-side to the retired
   `gemini-2.5-flash-lite` caused the reply regression is no longer the
   explanation and must not be re-asserted in any report. The **official
   cause of death** is the pair the hardware evidence proved:
   **release-never-fires** (the bindr trigger never fired on 0.56.2
   legacy conf in either modifier order — stream D fixes it with the
   `bindri`/ignore_mods form) **+ sever-without-final** (the flush either
   waited 2.5 s or returned instantly on a dead collector, closing the
   session with no final transcript so no reply invocation could ever
   exist — stream E fixes the flush and completes the turn). The model-ID
   pinning work stands on its own merits (§6.2) but is not the funeral.
5. **Scene-4 rulings (owner 2026-10-26) and the stream-F rules that
   follow them.** Wall one fallen / wall two refined (§4). Stream F is
   the wire question, and these rules are standing: commits ordered
   **sensors before fixes**; F.2 protocol citations REQUIRED before any
   fix; $0 budget — F.4's single file call is the only new API spend;
   sandbox tests use fakes, no live calls; no force-push; F.4 is a
   DIAGNOSTIC one-shot — do NOT build the retry consumer (WP5 owns it);
   the 1.4 GB watch item is report-finding only (profile in WP1 unless
   the fix is trivial — the cleanup-order swap was, and landed); F.5
   budget changes only after F.2 lands. And the run-page format rule the
   owner set after twice running the command and missing the cycle:
   **§7 separates EARS steps from TERMINAL steps strictly, and no
   physical action ever appears inside a paste-able block.**

6. **MERGE HOLD + GATE v2 (owner override 2026-10-27).** PR #23 stays
   OPEN. Session 77cc4efb1886 met the WRITTEN gate (full chain, first
   user-turn, spoken reply heard) but the owner holds the merge on
   latency: "that was so slow took like a minute." Journal: release
   06:45:01 → synth complete 06:45:29 = 28 s (12 s dead final-wait + 7 s
   fallback transcription + 9 s reply+TTS); playback-start was
   UNMEASURED. **GATE v2 is the standing gate**: the previous chain +
   the final from the PRIMARY route (`final.received`; the fallback path
   is a degraded mode, never a gate-passer) + release→first-audible
   ≤ 8 s + the owner's ear calls it conversational.
7. **Stream G rulings (WP1 round 1, 2026-10-27).** Docs-first with
   verbatim citations and the field-by-field diff BEFORE any fix; the
   setup deviations get named before they get changed. Sensors commit
   before fixes (kept). $0 — fakes only in the sandbox; no force-push;
   suite green; ruff clean. G.4's early-abandon never fires without
   wire sensors (no sensors, no abandon) and 12 s stays the ceiling.
   The kept-audio manifest is §4's truth (6 wavs, 4 unresolved; a
   resolved wav names HOW it resolved — `<noise>` is a resolution).
   Streaming playback is evaluated, not implemented: the native-audio
   path returns one PCM blob, so streamed first-audio is the named WP1
   item sized from the scene-6 latency table. And the run-page format
   rule stands twice over: §7 separates EARS from TERMINAL strictly and
   no physical action ever appears inside a paste-able block.

## 6. Known open defects (logged, not fixed — see phase reports)

1. `eventSnap` ReferenceErrors in `ui/quickshell/console/shell.qml` (~lines
   563–975 unqualified; WP2).
2. ~~The reply-regression candidate cannot be proven from the sandbox:
   the retired ID `gemini-2.5-flash-lite`…~~ **Alias-causation RETRACTED
   (§5.4).** The retired ID appears NOWHERE in the repo (0 hits) and the
   model pinning stands as hygiene (doctor hard-fails if the owner's live
   config still names it), but the reply regression's cause of death is
   release-never-fires + sever-without-final, not alias resolution.
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

## 7. The next action — Scene 6: the merge-gate run (GATE v2)

Read the format rule first: **every step below is EITHER a TERMINAL
step (a paste-able block — nothing physical happens while it is on
screen) OR an EARS step (hands and ears only — no terminal involved).**
They are never mixed inside one block. Do the steps in order. Scene
budget: 30 min, daylight, laptop+phone in earshot; both outcomes are
decisions. GATE v2 (§5.6) is what this run feeds — it does NOT itself
merge anything.

### Step 0 — TERMINAL: get stream G and restart on branch code

```
cd ~/assistant && git fetch origin && git checkout arena/c2a7085d-elaria && git pull && uv sync && systemctl --user daemon-reload && systemctl --user restart assistant && sleep 2 && assist doctor | tail -12
```

Expect: doctor green (or only known markers). If it is not, STOP and
report — do not continue the run.

### Step 1 — EARS ONLY. One full sentence, NORMAL VOICE. No terminal.

1. Hold Win+F2. Hear the press earcon the moment F2 lands.
2. Speak ONE full sentence at the voice you actually use with her —
   not a shout, not a mumble. The model's VAD filters non-speech, so a
   normal voice is part of the test, not a courtesy.
3. Release F2 WHILE STILL HOLDING WIN.
4. Wait and listen. The turn should feel like a turn: her reply at the
   end of a wait you did not have to count.
5. Write down WHAT SHE SAID before touching the terminal.

### Step 2 — TERMINAL: the cycle dump

```
journalctl --user -u assistant --since -6min -o cat | grep -E "ws.histogram|audio.sent|final.wait|final.received|final.timeout|audio.first_byte|reply.invocation|latency.table|quota.check|session.close|transcription.deferred" | tail -14
```

Expected lines (GATE v2's evidence — either outcome is a decision):

- `final.received … text_chars=N` with N > 0 — **from the PRIMARY
  route** (`backend=gemini_live` on the ptt.result). `final.timeout` or
  `transcription.deferred` means the fallback path answered: a degraded
  mode, never a gate-passer — report it as red.
- `ws.histogram … setup=ok retries=0 … transcript_family=N` with N > 0;
  `samples=[…]` now show the message payloads themselves (text-only) —
  quote them if anything is odd.
- `audio.sent … chunks=N bytes=M format=audio/pcm rate=16000` with
  `bytes/N ≈ 3200`.
- `latency.table …` with every leg measured: release_to_final_s
  (~1–3 s expected), final_to_reply_s, reply_to_synth_s,
  synth_to_audible_s, and **release_to_audible_s ≤ 8.0** (GATE v2's
  clock).
- `audio.first_byte … since_synth_s=…` — the playback-start sensor that
  makes the last leg measured, not inferred.
- quota: `user-turns (schema.expected)` = 1.

### Step 3 — EARS ONLY. The verdict that only you can give. No terminal.

Two words, both yours, written in the PR thread:

1. WHAT SHE SAID (her exact words, if you did not write them in Step 1).
2. **Did it feel conversational?** No number replaces this. The gate
   says "≤ 8 s" but the ear says fast/slow, present/absent — you are the
   instrument here.

### Step 4 — EARS ONLY. The double-stop proof. LAST. No terminal.

1. Hold Win+F2. Hear the press earcon.
2. Speak a SHORT phrase (a few words is enough).
3. Release WIN FIRST, then F2 (the opposite order from Step 1).
4. Listen: exactly ONE reply for the one utterance — no second turn, no
   jam.

### Step 5 — TERMINAL: the tail dump

```
journalctl --user -u assistant --since -3min -o cat | grep -E "stop.requested|stop.noop|reply.invocation|STUCK" | tail -6
```

Expected: `stop.requested` (source=bind) and `stop.noop` where a second
stop found nothing to do — one stop, one reply, nothing jammed. Bare-F2
strictness stays as scene 1 ruled: press/dispatch forbidden, release
legacy-tolerated until WP3.

### After the run

Report in the PR thread with tags: the `final.received` line (primary
or not), the histogram (setup/retries/transcript_family + samples), the
`latency.table` legs against the 8-second clock, the two EARS answers,
and the double-stop tail. Both red and green are decisions — a red run
with these sensors still names the next fix. §5 order after the gate:
WP1→WP2→WP4→WP5→WP3 (jump if rpm hyprland ≥ 0.57)→WP6.
