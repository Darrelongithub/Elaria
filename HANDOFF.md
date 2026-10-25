# HANDOFF — cold-resume state (Blueprint v2 wiring spec build)

Last updated: 2026-10-25 (WP0 EYES complete, awaiting the owner's WP0 hardware scene)
Branch: `arena/c2a7085d-elaria` · base `ed20344` (main)
Authority: MASTER BUILD PROMPT — ELARIA, BLUEPRINT V2 WIRING SPEC (2026-10-25)

Read this first after any interruption. Phase reports live in
`docs/phase-reports/` (DONE / DEFECTS FOUND / NEXT GATE / OPEN QUESTIONS in
each).

## Where the build is

| phase | state |
| --- | --- |
| Phase 0 (model-ID audit) | DONE — report `docs/phase-reports/2026-10-25-phase0-model-id-audit.md`. Owner approved the full §4.1 pin set (2026-10-25); applied in this round. |
| WP0 EYES | CODE COMPLETE — report `docs/phase-reports/2026-10-25-wp0-eyes.md`. **GATE OPEN: the owner runs `assist ladder` (all four chains) on the laptop** and every chain reports truthful rungs. STOP here per the execution plan. |
| WP1 VOICE AND IDENTITY | not started. First item is already done (pin fix applied); remainder: forbidden-ID scan is also done in doctor; reply-regression sensors; Flare audit (`client.voices.list()` + live probe — never auto-select a successor); earcon before capture; echo-cancel measurement; TTS cache hit-ratio split. |
| WP2 HOME | not started (fix eventSnap first: unqualified `eventSnap` in nested scopes of `ui/quickshell/console/shell.qml` lines ~563–975; qualify as `panel.eventSnap`. Then the qmllint pre-gate productised). |
| WP4 EARS | not started. Strictly additive; hotkey PTT is the proven wake mechanism. |
| WP5 FLIGHT | not started. `[event] segment_minutes` is still 30.0 — §4.7 wants 25 (range 10–30) + Files API transport + reserve of the last 2 calls of each LA-day. |
| WP3 COMPOSITOR | sixth position, trigger-based. PROMOTION TRIGGER: `rpm -q hyprland` or Bodhi shows 0.57 entering Fedora 44 repos → jumps the queue immediately (0.57 drops hyprlang; legacy binds die). |
| WP6 HYGIENE | not started. |

## Decisions the owner made (2026-10-25)

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

## Sandbox facts (this build environment — NOT the laptop)

- Headless container: no Hyprland, no PipeWire, no quickshell, no API key,
  no `rpm`. CPython 3.11 here; the laptop is CPython 3.14 — `uv sync` on 3.14
  is still [UNVERIFIED].
- Test baseline: **1,825 passed, 6 skipped** (was 1,780 + 45 new WP0/registry
  tests). Plain `uv sync` installs the base runtime; the ML/voice stack stays
  behind `--extra voice`. Ruff clean on touched files.
- `uv` had to be bootstrapped (`pip install --user --break-system-packages uv`).

## Known open defects (logged, not fixed — see phase reports)

1. `eventSnap` ReferenceErrors in `ui/quickshell/console/shell.qml` (~lines
   563–975 unqualified; WP2).
2. The reply-regression candidate cannot be proven from the sandbox: the
   retired ID `gemini-2.5-flash-lite` appears NOWHERE in the repo (0 hits),
   but the reply path ran on `-latest` aliases that can resolve server-side to
   it. Pinned now; proof needs a live call / `assist cost` failure rows on the
   laptop. If the owner's live `~/.config/assistant/config.toml` still names
   the retired ID, doctor now hard-fails on it.
3. `elaria-ladder` is referenced by docs/tests but shipped nowhere until this
   round — it is now `elaria-ladder` + `assist ladder` (`src/assistant/ladder.py`),
   rungs A–E per chain reconstructed from §4.8 + `docs/console-home/hardware-gate.md`.
   If the owner's ad-hoc script checked anything else, say so and we reconcile.
4. File-fallback *logic* (swapping to `gemini-3.5-flash-lite` when the STT
   primary is unavailable) is not wired yet — the ID is pinned
   (`model_file_fallback`); the swap belongs to WP5.
5. Cached-TTS model (`gemini-3.8-flash-lite-tts`) is registry-pinned but not
   adopted — speech still rides `gemini-3.8-live` native audio (interim owner
   decision 2026-10-20; voice-identity adjacent → WP1 with the owner's ear).
6. Machine facts to confirm on the laptop: `rpm -q hyprland` exact version
   (WP3 trigger watches for 0.57), quickshell 0.2.1 frozen (do not upgrade),
   Mic1 capture node non-silent (doctor now checks; run it there).

## The next action

The owner runs, on the laptop, in daylight:

```bash
git checkout arena/c2a7085d-elaria && uv sync && uv run assist doctor
uv run assist ladder          # or: elaria-ladder console  (expect A–E truthful)
```

Expected: every chain prints REACHED/STUCK with evidence; `assist doctor`
shows the new checks (forbidden model ids, model registry, capture node
(Mic1), quickshell, unit hardening ×2, quota counters). A crash-loop is
impossible by construction (`RestartSec=5`, `StartLimitIntervalSec=60`,
`StartLimitBurst=3` on both units). Every known unknown must be reproducible
from logs (`journalctl --user -u assistant -b` now carries the schema lines:
`ts level event session_id peak verdict detail`) or the ladder alone.

Both outcomes are decisions: a failed scene produces a log dump and a
diagnosis, never a retry loop.
