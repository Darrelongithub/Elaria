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
- **Kept-audio manifest (owner 2026-10-27: 8 wavs, 6 unresolved — WP5
  owns the consumer, do NOT build it here):**
  - `audio/20261026-120742-1beaea.wav` (12:07) — UNRESOLVED
  - `audio/20261026-122117-714a2a.wav` (12:21, session 714a2a8f37e6) —
    UNRESOLVED [path verified from the deferred line]
  - `audio/20261026-163353-056983.wav` (16:33, session 05698335f231) —
    UNRESOLVED [UNVERIFIED name — read the deferred line]
  - `audio/20261027-064404-f03c11.wav` (06:44) — UNRESOLVED
    [UNVERIFIED name — read the deferred line]
  - `audio/20261027-085158-c9665b.wav` (08:51, session c9665bed27fc) —
    UNRESOLVED (scene 6: adaptive-abandon cycle; fallback outcome was
    invisible then — scene 7's `fallback.outcome` line answers)
  - `audio/20261027-085254-27c8ea.wav` (08:52, session 27c8ea99e82c) —
    UNRESOLVED (scene 6: second cycle, same shape)
  - `audio/20261026-191330-d297f1.wav` (19:13) — **RESOLVED = `<noise>`**
    (the stream-F diagnostic found no intelligible speech)
  - `audio/20261027-064450-77cc4e.wav` (06:45, session 77cc4efb1886)
    — **RESOLVED = replied** (fallback transcription answered the turn)
    [name per the stream-H order — the H.3 repro streams this one]
  The six unresolved either eventually transcribe+answer or are
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

### Scene 5 + Scene 6 (2026-10-26/27) — the wire is healthy; the MODEL is silent

- **Scene 5** (session 77cc4efb1886, stream-F code): release 06:45:01 →
  synth 06:45:29 = 28 s, recovered by the flash-lite file fallback +
  spoken reply. Decomposition (estimates from journal stamps): 12 s
  dead wait + ~7 s fallback + ~9 s reply/TTS. `types={"message":2,
  "voice_activity":2}` — zero transcript messages, and the fallback
  answered anyway. Gate red on the 8 s bar, but the user got words.
- **Scene 6** (sessions c9665bed27fc + 27c8ea99e82c, 2026-10-27
  08:51–08:53, stream G.7 code): `transcript_family=0 commits=0` in
  BOTH cycles — zero transcript messages on the wire, **not missed
  deltas** (the G.7 shape sensors did exactly their job). Everything we
  control exonerated by its own sensors: `setup=ok retries=0`; server
  VAD timestamps match `audio.sent` bytes exactly (3.900 s ↔ 124,800 B;
  6.810 s ↔ 217,920 B); adaptive abandon worked (3.5 s, not 12 s);
  first real `latency.table` rows (release_to_final 3.575/3.828,
  `missing=reply,synth,audible`). **Verdict: wire healthy, model
  silent** — and a fallback regression candidate (both cycles ended in
  `transcription.deferred` with, per the owner, no fallback attempt,
  where scene 5's timeout landed via fallback + reply). Stream H.1
  traces it; the trace verdict is §5.9.

### Scene 7 evidence bundle (2026-10-31) — work order W1–W7

Owner hardware evidence landed as a mainline work order (item verdicts:
`docs/phase-reports/2026-10-31-scene7-work-order.md`): W1 file-leg stump
(7 of 29 chars, session 94129e); W2 arm B rebuild ordered; W3 Python
3.14.8 local-ASR breakage; W4 the two release-bind incidents (dossier:
`docs/dossiers/2026-10-31-hyprland-057-release-binds.md`); W5 mic
warm-up ×4; W6 the measured end-to-end budget (release_to_audible
20.29 s); W7 cosmetics/paperwork. **Manifest reconciliation (W7b):**
the manifest above is a scene-record of kept wavs (8 entries / 6
unresolved — the deferred-audio contract governs those); the owner's
disk now holds 35+ wavs including `20261031-140217-3b5227.wav` (the
9.6 MB / 301 s watchdog capture) and `20261031-145603-94129e.wav`
(W1's stump). It is NOT a disk inventory; **reconcile-on-start is a
storage-lane design item that WP5's deferred-retry consumer inherits**
(storage lane untouched this round — the additive-only firewall held).
Scene cards (W3/W4/W5 owner proofs + W1/W2 run instructions):
`docs/scene-cards/2026-10-31-scene7-followups.md`.

### Scene 7 mini order M (2026-10-31) — fallback-as-primary build

Rulings that govern everything below: **H.5 = FALLBACK-AS-PRIMARY**
(arms A+B SILENT on a valid key — account-side output suppression spans
model families; side-channel re-pin is DEAD, never reopen) and **gate
v2-AMENDED**: previous chain proofs + fallback-as-primary final proven
whole-sentence + release→first-audible ≤ 8 s with streamed TTS on a
hardware scene + owner's ear conversational; sunrise clause restores
Live primary by config pin if Google fixes the account. **W1 root cause
named:** the 7 chars = literal `<noise>` on both wavs,
`finish_reason=STOP` (no truncation); production's leg ran
`gemini-3.5-flash-lite` (a chat model improvising sympathy at "&lt;noise&gt;")
while the registry pins the files route to `gemini-3.5-transcribe` —
registry drift closed by M-3.

Mini order M built (report:
`docs/phase-reports/2026-10-31-scene7-mini-order-m.md`; commits
M-2 `e19e78f` · M-3 `b1b7c5c` · M-5 `6b09d54` · M-4 `86d7e7c` + docs):
M-2 probe arm C (registry model on the production wire); M-3 re-pin
(config registry-pin resolution + doctor `registry role pins` hard-fail
+ pins); M-5 `transcription.stump` (class + chars + sha16, never the
text); M-4 G.7.3 streaming TTS (~50 ms slices, first-audible-at-slice,
interrupt cutoff < 100 ms wired to halt) + early dispatch (chat at leg
landing; exactly-one-reply pinned) + the `latency.table`
first-audible-at-slice stage (`release_to_first_slice_s` = the clause-3
metric); M-6 exhibit 2 in the Google bug draft. Suite **1,982/6**,
ruff clean. **LATENCY SCENE proposed** (owner schedules, never
self-certified): `docs/scene-cards/2026-10-31-latency-scene.md`.

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
8. **G.7 rulings (pre-scene guard + audit triage, 2026-10-27).** Stream
   G is approved as landed; scene 6 stays the next hardware step and
   G.7.1 was the only scene-blocking item (landed: `319cb37` →
   `2ed6661` → `32500b4`). Provenance rule for third-party audit
   material (the design-chat read of an unlicensed abandonware project):
   ideas only, ZERO code copied, every claim tagged [CODE-READ,
   third-party, UNVERIFIED against current docs], and G.1-class
   docs-first verification BINDS before anything is implemented — the
   delta-accumulation work moved only after the docs/types diff named
   both shapes. Rulings that follow: G.7.1's shape-tolerant parser is
   the standing collector (one-shot segments AND deltas both land as one
   clean final per segment; 6f's rule survives — `finished` is optional
   on transcribe-live and never gates a commit); the join-rule residual
   (sub-word deltas without whitespace join with a space) is pinned,
   named, and stays until evidence says otherwise. G.7.2: halt/stop
   does NOT stop mid-reply playback (mechanism named: nothing kills the
   player — the wav finishes; PR_SET_PDEATHSIG only fires when the
   daemon dies) — NOT fixed this round; it is a WP1 item beside
   streaming playback, sharing G.7.3's interrupt mechanism. G.7.3 is
   the WP1 streaming-playback design brief (attached to the stream-G.7
   phase report): chunked playback queue (~50 ms / 2,400 B slices at
   24 kHz, first-chunk start, interrupt = drain + flag + turn-state
   reset, cutoff <100 ms) + early-dispatch pipelining; sized from
   scene 6's latency.table split; target unchanged (≤ 8 s
   release→audible). G.7.4: the session.open reset contract is pinned
   (6d-era flags hold; the G.6 stage tables now prune at open). G.7.5
   is notes only: half-duplex mic gating → WP1 AEC decision (unknown
   #6) + WP4 wake-arming context; session_resumption → WP5
   flight/reconnect reference (G.1's handle-only sending stays);
   bounded queues + TaskGroup/BaseExceptionGroup → the WP1 1.4 GB
   profiled run.
9. **Stream H rulings (scene-6 verdict + H.1 trace, 2026-10-27).**
   Scene-6 verdict stands as §4 records it: wire healthy, model silent,
   `transcript_family=0 commits=0` both cycles. Defect candidate #1
   (the fallback regression) is TRACED AND PINNED: both timeout kinds
   share one post-timeout path and the saved-WAV file-transcription leg
   FIRES after an adaptive abandon — four fake-driven scenario pins
   prove it on unmodified behavior (abandon→fallback→landed-or-deferred
   with wav kept, budget→fallback→landed-or-deferred, with
   commit-reason assertions). The route decision and fallback outcome
   are now SCHEMA lines (`post_timeout_route … timeout_kind=…` /
   `fallback.outcome …`) — the scene-6 "no fallback attempt" reading is
   consistent with the attempt living only in persona lifecycle rows
   (`dictate.saved_wav_fallback_start`), which the schema journal never
   carried. **Contradiction surfaced, not resolved silently** (standing
   rule): if the scene-6 persona rows show `dictate.saved_wav_fallback_
   start`, the leg attempted and its OUTCOME (empty/error/5s-timeout) is
   the real delta vs scene 5; if those rows are ALSO absent, the code
   that ran was not this branch. Scene 7's `fallback.outcome` line
   answers in one read either way. H.2: the generic "message" payloads
   are the per-response TOTAL counter, not a type — sampling now covers
   every counted type incl. "message" (fields named), and genuinely
   unnamed shapes get `message.(no-populated-fields)`. H.4 sensors
   landed (press→first-frame ms, first-non-silent offset, `stream.
   closed`, `capture.node_state` mic-release probe ~5 s after close).
   H.3 is the owner-run repro (`scripts/live_repro.py`, arm A =
   gemini-3.5-transcribe-live with the docs' Manual-VAD verbatim, arm B
   = gemini-3.8-live side-channel) — it runs FIRST-HAND outside the
   daemon and its outcome picks the H.5 option. H.5 options are sized
   in the stream-H phase report; **Gate v2's 8 s bar stands unless the
   owner re-rules with those numbers in hand**. The double-stop proof
   is scene 7's FIRST physical step — it has been missed twice (scene 5
   and scene 6 both ran natural cycles only).
10. **Cross-lane re-verification protocol (ruled 2026-10-27, design-chat
    ride-along).** Standing re-verification targets the ORIGIN TIP AT
    ACTIVATION TIME: fetch and diff the then-tip against the lane's
    last verified baseline BEFORE authoring fixtures — never a fixed
    SHA from a notice. Cross-lane notices are conveniences, never
    gates; relay claims are verified, not trusted (007 §2) — including
    the notice that carried this rule. This activation (2026-10-27)
    verified by direct read: origin tip = `018d109` = last verified
    baseline (empty diff, `main` still at `ed20344`); `journal_log.py`
    untouched by scene-readiness (last touch `30abf30`, stream G);
   `log_event` is generic — "event is the caller's naming", no
   allowlist — so `capture.lifecycle` needed no journal-side change.
   The moving baseline SHA is carried in the lane's session memory,
   updated at the end of every activation.
11. **Scene-7 work-order rulings and outcomes (2026-10-31).** W5
   addendum (RULED): the always-active mic is rejected as a latency
   measure — it makes the 14:02 hot-mic class permanent, falsifies the
   `capture.node_state` suspended-after-close privacy proof,
   desensitizes the mic-in-use indicator, and contradicts settled
   hold-to-talk. WP1 scope named instead: (i) READY-EARCON, a distinct
   second cue at first audio frame (owner speaks on the blip; acceptance
   = audible within 50 ms of first frame, distinguishable from the
   session-open cue by ear), (ii) PRE-ROLL DISCARD, frames before
   first-frame dropped by construction. Always-on listening remains
   exclusively a WP4 wake-word-mode property; **no lane implements node
   pinning, manual PipeWire keep-warm, or any always-on capture outside
   WP4's future design**. W6 (implemented): the file leg now starts
   speculatively at voice-end (wav finalized at voice-end; budget
   `FALLBACK_TIMEOUT_S = 8.0` s measured from there — 5.0 s was landing
   at the boundary), overlapped with the final wait; the BH-K3 gate
   consumes it only when `needs_fallback` and DISCARDS it otherwise
   (never substituted — the scene-3b contract, now pinned). The
   speculative call is skipped when the primary already covers the
   audio (committed final, no trailing speech — the BH-K1 cost
   contract). **Open tradeoff for the design chat:** a discarded leg may
   still bill its tokens (the worker thread runs to completion); on the
   silent-wire reality (4/4 sessions) the leg is the de-facto primary,
   but if the primary recovers, every utterance pays one wasted
   file-transcription call. W7a: `assist status` `ptt_session_id` now
   names a live session only (holder's truth); history is
   `last_session_id`. W3: the local leg degrades BY NAME
   (`LocalAsrDegraded` + `local_asr.degraded` schema line + the exact
   `av` named in the diagnostic) instead of a raw TypeError on 3.14.8.

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

## 7. The next action — Scene 7: the repro + verdict run

Read the format rule first: **every step below is EITHER a TERMINAL
step (a paste-able block — nothing physical happens while it is on
screen) OR an EARS step (hands and ears only — no terminal involved).**
They are never mixed inside one block. Do the steps in order. Scene
budget: 30 min, daylight, laptop+phone in earshot; both outcomes are
decisions. This run feeds the H.1 evidence question and the H.5
ruling; GATE v2 (§5.6) stands and is NOT merged by anything here.

**The double-stop proof is FIRST this time.** It has been missed twice
(scene 5 and scene 6 both drifted straight into natural cycles). It is
a thirty-second step and the run does not continue until it has been
done.

### Step 0 — TERMINAL: get stream H and restart on branch code

```
cd ~/assistant && git fetch origin && git checkout arena/c2a7085d-elaria && git pull && uv sync && systemctl --user daemon-reload && systemctl --user restart assistant && sleep 2 && assist doctor | tail -12
```

Expect: doctor green (or only known markers). If it is not, STOP and
report — do not continue the run.

### Step 1 — EARS ONLY: the double-stop proof. FIRST. No terminal.

1. Hold Win+F2. Hear the press earcon.
2. Speak one short sentence at normal voice.
3. Release WIN first — while F2 is still down.
4. Then release F2.
5. Listen: there must be exactly ONE reply. The second release found
   nothing to stop. Write down what she said (or that nothing came).

### Step 2 — TERMINAL: the double-stop tail

```
journalctl --user -u assistant --since "2 minutes ago" -o cat | grep -E "stop\.|ptt.result|latency.table" | tail -8
```

Expect exactly: one `stop.requested` (source=bind), one `stop.noop`
(the second stop finding nothing), one `ptt.result`, and one
`latency.table` whose reply/synth/audible legs are present. One stop,
one reply, nothing jammed. Bare-F2 strictness stays as scene 1 ruled:
press/dispatch forbidden, release legacy-tolerated until WP3. If the
tail shows a second `stop.requested` with no `stop.noop`, the proof is
still missing — report it and continue anyway (the repro arms do not
depend on it).

### Step 3 — TERMINAL: H.3 repro arm A — the pin itself

The script needs the key from your notes (never paste it anywhere —
export it in the shell only):

```
export GEMINI_API_KEY=…   # from your notes; the script never prints it
cd ~/assistant && uv run python scripts/live_repro.py --arm A
```

This is one short housekeeping Live session, outside the daemon, the
docs' Manual-VAD setup verbatim, streaming `audio/20261027-064450-
77cc4e.wav` (the proven speech) in 100 ms chunks. It prints every raw
message unfiltered. Paste the final `=== arm A summary ===` block plus
any `MSG` lines that carried `input_transcription` or
`interim_input_transcription`.

### Step 4 — TERMINAL: H.3 repro arm B — the side-channel comparison

```
cd ~/assistant && uv run python scripts/live_repro.py --arm B
```

Same script, same wav, same Manual-VAD config — only the model changes
(`gemini-3.8-live`, the docs' example conversational model). Paste the
same summary block. Now read the ruling tree (it is in the script
header):

- transcripts in A AND B → live route works outside our stack →
  deep-dive the parse path with these transcripts as ground truth;
- zero in A, transcripts in B → the transcribe-live pin/transport
  combination is the deviation → design-chat ruling on re-pinning;
- zero in both → account/model gating (unknown #5) → AI Studio
  entitlement check + the bug-report evidence pack for Google (these
  two summaries ARE the evidence pack core).

### Step 5 — EARS ONLY: one natural cycle. Normal voice. No terminal.

1. Hold Win+F2, hear the earcon.
2. Speak ONE full sentence the way you actually talk to her.
3. Release F2 WHILE STILL HOLDING WIN (the ordinary shape — this cycle
   is for the sensors, not the stop proof).
4. Wait and listen. Reply or silence — both are data.
5. Write down what you heard AND how the start and stop FELT (the
   "microphone takes a minute" impression — was start slow? did the
   in-use indicator linger after the turn?).

### Step 6 — TERMINAL: the cycle dump — the stream-H sensors answer now

```
journalctl --user -u assistant --since "3 minutes ago" -o cat | grep -E "ws.histogram|audio.sent|final\.|transcription\.|post_timeout_route|fallback.outcome|latency.table|capture.lifecycle|stream.closed|capture.node_state" | tail -20
```

Quote the lot. What each line settles:

- `ws.histogram … transcript_family=N commits=M …` — N>0? the model
  spoke (gate question). M vs N tells the shape if it did.
- `post_timeout_route … needs_fallback=… timeout_kind=…` — **the H.1
  verdict in one line**: which route ran, and was it an adaptive
  abandon or a budget expiry.
- `fallback.outcome …` — **the regression question in one line**: the
  file-transcription leg's result (landed / empty / error). Scene 5
  recovered here; scene 6 could not say why it did not.
- `latency.table …` — the 8 s clock: release_to_final / reply_to_synth
  / synth_to_audible against GATE v2.
- `capture.lifecycle … first_frame_latency_ms=… first_speech_frame_s=…`
  — the mic-start numbers (aggregate only).
- `stream.closed …` + `capture.node_state …` (~5 s after close) — the
  mic-stop numbers; `state suspended/idle` = actually released,
  `running` = the indicator was telling the truth.

### Step 7 — EARS ONLY: the mic-lifecycle verdict

Compare the step-5 impressions against step-6's numbers. Which is
right: the felt minute or the measured milliseconds? This is an
observation, not a fix — the fix lands in WP1 with the playback work.

### After the run

Report in the PR thread with tags: the double-stop tail, both H.3
summaries and which ruling-tree branch they pick, the cycle dump lines
above, and the two EARS answers. Then the H.5 ruling (options and
numbers are in the stream-H phase report) — **Gate v2's 8 s bar stands
unless you re-rule with those numbers in hand**. Both red and green are
decisions. §5 order after the gate:
WP1→WP2→WP4→WP5→WP3 (jump if rpm hyprland ≥ 0.57)→WP6.

### After that — the 2026-10-31 scene cards

The work order's owner proofs are scheduled in
`docs/scene-cards/2026-10-31-scene7-followups.md`: SC-W3 (local ASR on
3.14.8 — transcribes OR named degradation, both results), SC-W4
(double-stop both release directions — the WP3 jump discriminator),
SC-W5 (ready-earcon ≤ 50 ms, after WP1 builds it), plus the W1 probe
run and the W2 arm A/B runs (paste-safe scripts, outputs feed the H.5
ruling and the Google bug report draft in
`docs/bug-reports/2026-10-31-gemini-live-transcribe-zero-output.md`).

Mini-order M adds the **LATENCY SCENE**
(`docs/scene-cards/2026-10-31-latency-scene.md`, proposed via design
chat): gate v2-AMENDED clause 3's instrument — `release→first-audible
≤ 8 s` with streamed TTS on the fallback-as-primary chain, owner's ear
as the instrument, `latency.table`'s `release_to_first_slice_s` as the
number. Same window doubles as the M-2/M-3 acceptance (probe arm C:
whole sentences on both standing wavs; `assist doctor` first — the
`registry role pins` check names any config drift). The M-2 quota note
rides the scene: transcribe-batch free tier 25 RPD vs one file-leg call
per silent-primary turn.
