# HANDOFF — cold-resume state (Blueprint v2 wiring spec build)

Last updated: 2026-10-26 (scene 1 RED-diagnosed; scene-1 fixes on branch; scene 2
pending, run by the owner in parallel)
Branch: `arena/c2a7085d-elaria` · base `ed20344` (main)
Authority: MASTER BUILD PROMPT — ELARIA, BLUEPRINT V2 WIRING SPEC (2026-10-25)

Read this first after any interruption. Phase reports live in
`docs/phase-reports/` (DONE / DEFECTS FOUND / NEXT GATE / OPEN QUESTIONS in
each).

## 1. Where the build is

| phase | state |
| --- | --- |
| Phase 0 (model-ID audit) | DONE — report `docs/phase-reports/2026-10-25-phase0-model-id-audit.md`. Owner approved the full §4.1 pin set (2026-10-25); applied. |
| WP0 EYES | CODE COMPLETE. Scene 1 (2026-10-26) was RED-diagnosed; its fixes are on this branch (ladder $variables, bare-F2 semantics, event rung E N/A, `model_version` on schema lines, bug6 test hermeticity). **GATE: scene 2 — units, live config pins, restart, press.** PR #23 merges only when the scene-2 ladder shows truthful rungs AND the press produces schema lines with `model_version`. |
| WP1 VOICE AND IDENTITY | **parked until the scene-2 report lands.** On its plate: reply-regression sensors; Flare audit (`client.voices.list()` + live probe — never auto-select a successor); earcon before capture; echo-cancel measurement; TTS cache hit-ratio split; BH-H9 silent-knock defect (see §5). |
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

## 5. Lessons and watch items

1. **Daemon-was-stale lesson (scene 1):** the scene ran status-dependent
   rungs against a daemon that was not restarted on branch code. **Scene
   checklists must restart the daemon on branch code BEFORE any
   status-dependent rung** — `systemctl --user daemon-reload && systemctl
   --user restart assistant` right after checkout/sync, before doctor,
   ladder, and the press. (The WP0 report checklist is reordered
   accordingly.)
2. **Mic peak 0.9981 — near-clipping watch.** The proven Mic1 input is
   running hot (peak 0.9981 of full scale on scene 1). Not a defect by
   itself; watch for clipping distortion in transcripts and consider input
   gain / a limiter in a later audio pass. Anything that reads `peak` on
   the schema lines should be read against this baseline.
3. **Suite triage (scene-1 failures), one verdict per test:**
   - `test_bug6_dictate_capture.py::test_real_signal_capture_source_produces_a_live_transcript`
     ("no speech captured" instead of the mock transcript): **env-dependent
     via ambient CONFIG** — `load_config()` merges the laptop's
     `~/.config/assistant/config.toml`, and `[voice] silence_floor` (read
     once at `DictationService` init) sits above the test signal's ~0.18
     peak there, so the scripted transcript is discarded as silence.
     Capture was already mocked (FakeSource); the leak was config.
     **Action taken:** bug6-class tests are now hermetic (pin the shipped
     `silence_floor = 0.05`) — the pre-authorized test-side fix.
     [TESTED-ONLY mechanism; the laptop's exact floor is [UNVERIFIED-laptop].]
   - `tests/test_event_cli_smoke.py` `_wait_segments ... 1 >= 2`:
     **env-dependent timing under load** — 3-second simulated segments
     (`--segment-minutes 0.05`) against a fixed 10-second wall-clock wait.
     **Logged to WP5** (event segment rotation owns the machinery); NOT
     patched here. [TESTED-ONLY diagnosis; failure observed on the laptop.]
   - `tests/test_stage_abcd_bughunt.py::test_bh_h9_...` (knock emitted sound
     despite `silent=True`): **env-exposed real defect** —
     `KnockSignal.emit()` checks only its `class_mode` parameter and never
     `knock["silent"]`; with `notify-send` and a player binary present
     (laptop) the runner is invoked, so `played_sounds == []` fails. The
     sandbox has no desktop binaries, which hides it. NOT a WP0 regression
     (`initiative.py` untouched). **Logged to WP1** (audio identity: a
     silent knock must emit zero audio/subprocess); if the master spec puts
     initiative/knocks under WP4, reassign there. NOT patched here.
     [TESTED-ONLY mechanism; the audible failure is the laptop's HW report.]

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
5. BH-H9 silent-knock defect (§5.3) — WP1 (or WP4 if the spec says so).
6. Event-smoke segment-rotation timing (§5.3) — WP5.
7. Machine facts to confirm on the laptop: `rpm -q hyprland` exact version
   (WP3 trigger watches for 0.57), quickshell 0.2.1 frozen (do not upgrade),
   Mic1 capture node non-silent (doctor now checks; run it there).

## 7. The next action

**Scene 2 — the owner runs, on the laptop** (in parallel with these fixes;
daylight, ≤30 min):

```bash
git checkout arena/c2a7085d-elaria && uv sync && uv run pytest -q
systemctl --user daemon-reload && systemctl --user restart assistant   # FIRST — never run status rungs against a stale daemon (§5.1)
uv run assist doctor
cat ~/.local/bin/elaria-ladder   # reconcile vs productised rungs (decision 2.5)
uv run assist ladder          # or: elaria-ladder console  (expect truthful REACHED/STUCK/N/A)
# then: one Win+F2 press round (live config pins checked by doctor above)
journalctl --user -u assistant -b | grep -E 'transcription|session\.|silence|quota'
# the press's schema lines must carry model_version=…
```

**Merge only when:** the ladder fixes are on the branch (they are, this
round) + scene 2's ladder shows truthful rungs + the press produces schema
lines with `model_version`. Then PR #23 merges, the `elaria-ladder` shim
disposition runs (decision 2.5), and only then does WP1 open.

Both outcomes are decisions: a failed scene produces a log dump and a
diagnosis, never a retry loop.
