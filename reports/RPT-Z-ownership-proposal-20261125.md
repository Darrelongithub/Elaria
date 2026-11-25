# RPT-Z — W-ownership proposal (Channel 3 / issue #92, agent 92)

Date: 2026-11-25 · Branch: `arena/ba0aa534-elaria` · Base: `71ed70a` (main)
Authority: `reports/DISPATCH-20261125.md` CHANNEL 3 + GitHub issue #92.
Lane: **paperwork only.** HARD RULE honoured: `OWNERS.yaml` and
`scripts/check_ownership.py` were **not edited** — this report carries a
ready-to-paste patch the owner applies. `git diff` on this branch touches
only this file.

No threshold was touched (`ecapa_high` 0.75, `keyword_threshold` 0.5,
`MIN_WINDOW_S` 1.75 untouched). No hardware claim is made; every number
below is a **sandbox** measurement.

---

## 1. Raw numbers (sandbox)

| run | result |
|---|---|
| `python3 scripts/check_ownership.py lint` (shipped map) | **497 paths; 60 zero-owner; 0 multi-owner** |
| proposed map, real matcher simulated (§5) | **497 paths; 0 zero-owner; 0 multi-owner**, lint rc **0** |
| `python3 scripts/check_ownership.py self-test` (shipped, untouched) | **Ran 11 tests … OK** |
| report-rule self-test vs proposal (§5) | all 24 clusters own `reports/RPT-<C>-r1-x.md`; `reports/unassigned.md` → `[]` |

The dispatch expected "~57 zero-owner"; the live tree measures **60**
(the manager board's 57 was at 491 paths; three files landed since).
Raw count reported, not the estimate.

`W` does not yet exist in `CLUSTERS` (`scripts/check_ownership.py:16`),
and no `W` entry exists in `OWNERS.yaml`. Both are added by the patch.

---

## 2. The ready-to-paste patch

### 2a. `scripts/check_ownership.py` — one line (line 16)

Replace:

```python
CLUSTERS = frozenset("ABCDEFGHIJKLMOPQRSTUVZ") | {"REL", "REACH"}
```

with:

```python
CLUSTERS = frozenset("ABCDEFGHIJKLMOPQRSTUVWZ") | {"REL", "REACH"}
```

(`W` inserted between `V` and `Z`; `N` remains absent exactly as today.)

### 2b. `OWNERS.yaml` — new `W` entry

```json
  "W": [
    "models/**",
    "reports/RPT-W-*",
    "scripts/wake_bench.py",
    "src/assistant/nus_surface.py",
    "tests/test_nus_overlay_capture_state.py",
    "tests/test_nus_surface_m1.py",
    "tests/test_w_*.py",
    "ui/quickshell/nus/shell.qml"
  ]
```

`models/**`, `tests/test_w_*.py`, `ui/quickshell/nus/shell.qml`,
`scripts/wake_bench.py` are the four claims the dispatch names explicitly.
`reports/RPT-W-*` is required so W can file its own reports (every cluster
has one; the guard self-test `test_own_report_accepted` iterates `CLUSTERS`
and would fail for W without it). The three NUS paths are the judgment call
in §4.1.

### 2c. `OWNERS.yaml` — remove four subsumed globs from `I`

W's `models/**` and `tests/test_w_*.py` are broader than four globs I holds
today. Leaving them in I would make every `models/*` file and
`tests/test_w_ecapa_speaker.py` **multi-owner**. Delete these four lines
from the `I` list:

```
"models/README.md",
"models/ecapa_eval_samples.npz",
"models/voxceleb_ECAPA512_LM.onnx",
"tests/test_w_ecapa_speaker.py",
```

They remain owned — by W, via the broader globs. This is the only removal
the proposal makes; no other cluster loses a path.

### 2d. `OWNERS.yaml` — per-cluster additions

Add these globs to the existing cluster lists (sorted insertions; the
matcher ignores order). Counts: A +21, C +2, D +2, E +1, F +10, H +2,
I +3, K +1, L +2, R +2, Z +7, W new +8.

```json
"A": [
  "docs/bug-reports/2026-10-31-gemini-live-transcribe-zero-output.md",
  "docs/packets/2026-11-15-capture-gain-reduction.md",
  "tests/test_ack_playback.py",
  "tests/test_capture_limiter_path.py",
  "tests/test_local_asr_degraded.py",
  "tests/test_response_extraction.py",
  "tests/test_scene3b_redo.py",
  "tests/test_script_help_smoke.py",
  "tests/test_stream_f_wire.py",
  "tests/test_stream_g7.py",
  "tests/test_stream_g_primary.py",
  "tests/test_stream_h_post_timeout.py",
  "tests/test_stream_h_sensors.py",
  "tests/test_stream_tts.py",
  "tests/test_task_j_ears.py",
  "tests/test_task_k_gateway.py",
  "tests/test_task_l_mouth.py",
  "tests/test_transcription_stump.py",
  "tests/test_voice_chain_resilience.py",
  "tests/test_voice_models_verification.py",
  "tests/test_wp0_call_counters.py"
],
"C": [
  "tests/test_notify_privacy.py",
  "tests/test_wp0_ladder.py"
],
"D": [
  "src/assistant/safety_journal.py",
  "tests/test_wp0_journal_schema.py"
],
"E": [
  "tests/test_phone_link_refusals.py"
],
"F": [
  "scripts/frame_probe.py",
  "scripts/frame_probe.py.sha256",
  "scripts/live_repro.py",
  "scripts/record_probe_take.py",
  "scripts/record_probe_take.py.sha256",
  "tests/test_file_leg_probe.py",
  "tests/test_frame_probe.py",
  "tests/test_gain_shape_fixture.py",
  "tests/test_live_repro_arm_b.py",
  "tests/test_record_probe_take.py"
],
"H": [
  "docs/dossiers/2026-10-31-hyprland-057-release-binds.md",
  "tests/test_task_m_followup.py"
],
"I": [
  "docs/scene-cards/**",
  "tests/test_model_registry.py",
  "tests/test_wp0_model_registry.py"
],
"K": [
  "console/capture-state-test.js"
],
"L": [
  "console/package-lock.json",
  "console/package.json"
],
"R": [
  "docs/design/2026-11-04-undo-consent-seam.md",
  "docs/design/2026-11-05-producer-seam-estimates.md"
],
"Z": [
  "HANDOFF.md",
  "reports/DISPATCH-*",
  "tests/test_capture_state_wire.py",
  "tests/test_producer_seams.py",
  "tests/test_undo_consent_guard.py",
  "tests/test_undo_review_pilot.py",
  "tests/test_wp0_watchdog.py"
]
```

### 2e. Whole-file paste (appendix)

§6 is the complete proposed `OWNERS.yaml`, byte-identical to the map the
simulation in §5 proved yields 0/0. The owner may replace the whole file
with it instead of applying 2b–2d by hand. JSON object key order is
irrelevant to the matcher; the appendix sorts keys and globs for a clean
diff. After pasting either form, run:

```
python3 scripts/check_ownership.py lint      # expect: N paths; 0 zero-owner; 0 multi-owner
python3 scripts/check_ownership.py self-test # expect: Ran 11 tests ... OK
```

(N grows as new files land; the invariant is **0 zero-owner; 0 multi-owner**.)

---

## 3. Assignment rationale — every zero-owner path → its cluster

Rule applied (dispatch): *each path goes to the cluster whose module it
tests/produces; test files follow the module they test.* Evidence is the
file's own docstring/imports, cross-checked against the shipped map.

| path | → | evidence (module it tests/produces) |
|---|---|---|
| `HANDOFF.md` | Z | manager cold-resume board; sibling of `README.md` (Z). §4.2 |
| `console/capture-state-test.js` | K | tests `ElariaShell.captureState` in `console/src/shell.js` (K); same `harness.js` family as K's `session-test.js` |
| `console/package-lock.json` | L | lockfile for the jsdom console-test harness; L owns `console/harness.js`, `build.py`, `ci.sh` |
| `console/package.json` | L | `"elaria-console-tests"` / `node --test *.js` harness config (L infra) |
| `docs/bug-reports/2026-10-31-gemini-live-transcribe-zero-output.md` | A | Google bug report on Live transcribe (`gemini_client.py`/`live_client.py` — A) |
| `docs/design/2026-11-04-undo-consent-seam.md` | R | dated twin of R's `docs/design/undo-consent-seam.md` |
| `docs/design/2026-11-05-producer-seam-estimates.md` | R | dated twin of R's `docs/design/producer-seam-estimates.md` |
| `docs/dossiers/2026-10-31-hyprland-057-release-binds.md` | H | Hyprland 0.57 release-bind defect evidence for `hypr_binds.py` (H) |
| `docs/packets/2026-11-15-capture-gain-reduction.md` | A | owner-run capture input-gain packet (`capture.py` — A) |
| `docs/scene-cards/2026-10-31-latency-scene.md` | I | design-chat scene card; I owns every scene order/phase-report (`docs/scene-cards/**`) |
| `docs/scene-cards/2026-10-31-scene7-followups.md` | I | scene-7 follow-up cards (I) |
| `docs/scene-cards/2026-11-02-voice-chain-resilience.md` | I | voice-chain resilience scene card (I) |
| `reports/DISPATCH-20261125.md` | Z | manager dispatch (`reports/DISPATCH-*`) |
| `scripts/frame_probe.py` | F | owner-run frame-level capture probe; F owns every diagnostic probe + `.sha256` (§4.4) |
| `scripts/frame_probe.py.sha256` | F | pin for `frame_probe.py` |
| `scripts/live_repro.py` | F | owner-run live-transcription repro instrument (scene-7 W2); F probe family |
| `scripts/record_probe_take.py` | F | owner-run production-path take recorder; F probe family |
| `scripts/record_probe_take.py.sha256` | F | pin for `record_probe_take.py` |
| `scripts/wake_bench.py` | W | dispatch explicit |
| `src/assistant/nus_surface.py` | W | headless half of `ui/quickshell/nus/shell.qml` (W per dispatch). §4.1 |
| `src/assistant/safety_journal.py` | D | docstring self-tags "(D-SAFETY)"; D owns `safety.py`, `journal_log.py` |
| `tests/test_ack_playback.py` | A | pins `tts.SpeechService` player chain (`tts.py` — A) |
| `tests/test_capture_limiter_path.py` | A | pins `capture.SoftLimiter` on the transcribe path (A); sibling of A's `test_capture_limiter.py` |
| `tests/test_capture_state_wire.py` | Z | pins `daemon._emit_capture_state` / `_emit_live_capture_state` producer (`daemon.py` — Z). §4.3 |
| `tests/test_file_leg_probe.py` | F | pins `scripts/file_leg_probe.py` harness (already F) |
| `tests/test_frame_probe.py` | F | pins `scripts/frame_probe.py` packet (F) |
| `tests/test_gain_shape_fixture.py` | F | freezes the owner take as a fixture for `frame_probe`'s verdict math (F) |
| `tests/test_live_repro_arm_b.py` | F | pins `scripts/live_repro.py` arm-B harness (F) |
| `tests/test_local_asr_degraded.py` | A | pins `asr.LocalWhisperBackend` named degradation (`asr.py` — A) |
| `tests/test_model_registry.py` | I | pins `model_registry`/`cost`/`model_pins` (I) |
| `tests/test_notify_privacy.py` | C | pins `initiative` knock-notification privacy (`initiative.py` — C) |
| `tests/test_nus_overlay_capture_state.py` | W | pins `nus_surface` → `shell.qml` wiring (both W). §4.1 |
| `tests/test_nus_surface_m1.py` | W | pins `nus_surface.py` (W). §4.1 |
| `tests/test_phone_link_refusals.py` | E | pins `phone_link.py` M2 refusals (E) |
| `tests/test_producer_seams.py` | Z | pins daemon/store producer receipts via `_remember(daemon,…)`/`_forget(daemon,…)` (`daemon.py`/`store.py` — Z). §4.3 |
| `tests/test_record_probe_take.py` | F | pins `scripts/record_probe_take.py` argv delegation (F) |
| `tests/test_response_extraction.py` | A | pins `gemini_client.extract_transcript` (A) |
| `tests/test_scene3b_redo.py` | A | stream-E final flush (`transcribe`/`live_client` — A) is 8/14 tests; stream-D binds touch C/H. §4.3 |
| `tests/test_script_help_smoke.py` | A | smokes `scripts/record_elaria_samples.py --help` (A's script) |
| `tests/test_stream_f_wire.py` | A | `live_client` wire sensors (A) |
| `tests/test_stream_g7.py` | A | `live_client` transcript-shape sensors (A) |
| `tests/test_stream_g_primary.py` | A | `live_client` + `tts` sensors (A) |
| `tests/test_stream_h_post_timeout.py` | A | `transcribe`/`asr` post-timeout fallback route (A) |
| `tests/test_stream_h_sensors.py` | A | `live_client`/`capture` sensors (A) |
| `tests/test_stream_tts.py` | A | `tts` streaming playback + `transcribe` early dispatch (A) |
| `tests/test_task_j_ears.py` | A | `capture`/`asr` VAD-gated dictation (A) |
| `tests/test_task_k_gateway.py` | A | `audio_gateway` arbitration (`audio_gateway.py` — A) |
| `tests/test_task_l_mouth.py` | A | `tts` cache / labelled-text (`tts.py` — A) |
| `tests/test_task_m_followup.py` | H | 7/12 tests pin `hypr_binds` Lua emit/detect (`hypr_binds.py` — H); 5 pin gateway claim (A). §4.3 |
| `tests/test_transcription_stump.py` | A | `transcribe`/`asr` stump sensor (A) |
| `tests/test_undo_consent_guard.py` | Z | pins `Daemon._undo` scoped refusal (`daemon.py` — Z). §4.3 |
| `tests/test_undo_review_pilot.py` | Z | pins the daemon undo-review route (`daemon.py` — Z). §4.3 |
| `tests/test_voice_chain_resilience.py` | A | `asr`/`gemini_client` resilience (A) |
| `tests/test_voice_models_verification.py` | A | `gemini_client` models.list verification stamp (A) |
| `tests/test_wp0_call_counters.py` | A | `asr`/`gemini_client` API-route call counters (A) |
| `tests/test_wp0_journal_schema.py` | D | `journal_log` stdout schema (`journal_log.py` — D) |
| `tests/test_wp0_ladder.py` | C | `ladder.py` hardware ladder (C) |
| `tests/test_wp0_model_registry.py` | I | `model_registry` + config quota rows (I) |
| `tests/test_wp0_watchdog.py` | Z | `daemon._watchdog_tick` (`daemon.py` — Z). §4.3 |
| `ui/quickshell/nus/shell.qml` | W | dispatch explicit |

All 60 zero-owner paths are covered; no path is assigned twice.

---

## 4. Judgment calls flagged for the owner

These are the places where the rule needs a decision rather than a
lookup. Each is reversible with a one-line move; the simulation proves
the proposal as written is 0/0.

### 4.1 The NUS surface goes to W as one unit (alternative: H)

The dispatch explicitly gives W `ui/quickshell/nus/shell.qml`.
`src/assistant/nus_surface.py` is, in its own words, "the headless half"
of that exact QML surface — it builds the show/hide commands the QML
`IpcHandler` consumes and knows nothing else. `tests/test_nus_surface_m1.py`
pins `nus_surface.py`; `tests/test_nus_overlay_capture_state.py` parses
`shell.qml` and drives it through `nus_surface`. Splitting the controller
(H) from the view (W) would make every surface change cross two clusters
and leave the eye-check test straddling two owners. Keeping the whole
surface (qml + controller + both tests) in W is the coherent reading of
"the cluster whose module it produces". **Alternative:** if the owner
wants the surface under H (the overlay lane that built it, per the
manager board Lane 5), move those three paths from W to H — but then the
dispatch's explicit `shell.qml → W` must be revised too, or the qml and
its controller split. The proposal follows the dispatch as written.

### 4.2 `HANDOFF.md` → Z (alternative: L)

`HANDOFF.md` is the manager/integrator's cold-resume board ("Read this
first after any interruption"), the sibling of `README.md` (Z) and the
manager reports (`RPT-Z-*`). L owns the read-first *product* docs
(`GETTING-STARTED.md`, `assistant-blueprint.md`, `bugs.md`, `change.md`).
HANDOFF is build *state*, not product docs → Z. If the owner prefers L's
docs-hygiene lane to keep it, move the one line; nothing else changes.

### 4.3 Multi-module tests → dominant module

A test file can only have one owner (0 multi-owner). Where a file spans
clusters, it goes to the module that carries its headline contract:

- `test_scene3b_redo.py` → **A**: stream E (final flush, `transcribe`/
  `live_client`) is 8 of 14 tests and the redo's stated purpose ("the last
  code wall before her voice"); stream D's release-bind tests touch
  `ladder` (C) / `hypr_binds` (H) but are the minority.
- `test_task_m_followup.py` → **H**: 7 of 12 tests pin `hypr_binds` Lua
  emission/detection/doctor/snippets/docs; the other 5 pin the gateway
  reply claim (A). Majority module wins.
- `test_capture_state_wire.py`, `test_producer_seams.py`,
  `test_undo_consent_guard.py`, `test_undo_review_pilot.py`,
  `test_wp0_watchdog.py` → **Z**: each pins a `daemon.py` producer
  (`_emit_capture_state`, remember/forget receipts, `_undo`, the
  undo-review route, `_watchdog_tick`). `daemon.py`/`store.py` are Z's,
  matching the shipped precedent (`test_daemon_cli.py`,
  `test_ipc_handler_integrity.py` → Z). R *designed* the undo seams and
  owns the console-side `undo-review-test.js`, but the daemon-side pins
  follow `daemon.py`, not the design author.

### 4.4 Probe scripts → F by shipped precedent

F already owns every owner-run diagnostic instrument and its `.sha256`
pin — `capture_source_check`, `limiter_readings`, `file_leg_probe`,
`player_probe`, `daemon_identity` — regardless of which module each
diagnoses (capture, playback, daemon). `frame_probe`, `record_probe_take`
and `live_repro` are the same family (owner-run, paste-safe, sha256-pinned
readers), so they and their harness tests follow F. `test_file_leg_probe.py`
was zero-owner while its script was already F's; this closes that gap.

### 4.5 I's model globs are subsumed, not deleted

The four I globs removed in §2c stay owned — by W's `models/**` and
`tests/test_w_*.py`. This is forced by the dispatch's explicit W claims;
keeping them in I would produce multi-owner matches. No coverage is lost.

---

## 5. Reproducible proof (real matcher, files untouched)

The script below imports the shipped `scripts/check_ownership.py`, extends
`CLUSTERS` with `"W"` **in memory only** (exactly the §2a patch), builds the
proposed map, and runs the real `read_map` / `lint` / `owners_for` over all
497 tracked paths. It also replicates the guard self-test
`test_own_report_accepted` core against the proposal. It writes nothing to
`OWNERS.yaml` or `scripts/check_ownership.py`. Save it anywhere and run
`python3 <file>` from the repo root.

```python
"""Simulate the W-ownership proposal against the REAL check_ownership matcher.

Does NOT edit OWNERS.yaml or scripts/check_ownership.py. It imports the shipped
module, extends CLUSTERS in memory with "W" (exactly the one-line patch the owner
pastes), builds the proposed map, and runs the real read_map/lint/owners_for.
"""
import importlib.util, json, subprocess, sys
from pathlib import Path

REPO = Path.cwd()  # run from the repo root
spec = importlib.util.spec_from_file_location("co", REPO / "scripts/check_ownership.py")
co = importlib.util.module_from_spec(spec); spec.loader.exec_module(co)

# --- the ONE-LINE patch to scripts/check_ownership.py (in-memory only) ---
co.CLUSTERS = co.CLUSTERS | {"W"}

current = json.loads((REPO / "OWNERS.yaml").read_text())

# --- proposed edits ---
remove_from_I = ["models/README.md", "models/ecapa_eval_samples.npz",
                 "models/voxceleb_ECAPA512_LM.onnx", "tests/test_w_ecapa_speaker.py"]
add = {
 "A": ["docs/bug-reports/2026-10-31-gemini-live-transcribe-zero-output.md",
       "docs/packets/2026-11-15-capture-gain-reduction.md",
       "tests/test_ack_playback.py","tests/test_capture_limiter_path.py",
       "tests/test_local_asr_degraded.py","tests/test_response_extraction.py",
       "tests/test_scene3b_redo.py","tests/test_script_help_smoke.py",
       "tests/test_stream_f_wire.py","tests/test_stream_g7.py",
       "tests/test_stream_g_primary.py","tests/test_stream_h_post_timeout.py",
       "tests/test_stream_h_sensors.py","tests/test_stream_tts.py",
       "tests/test_task_j_ears.py","tests/test_task_k_gateway.py",
       "tests/test_task_l_mouth.py","tests/test_transcription_stump.py",
       "tests/test_voice_chain_resilience.py","tests/test_voice_models_verification.py",
       "tests/test_wp0_call_counters.py"],
 "C": ["tests/test_notify_privacy.py","tests/test_wp0_ladder.py"],
 "D": ["src/assistant/safety_journal.py","tests/test_wp0_journal_schema.py"],
 "E": ["tests/test_phone_link_refusals.py"],
 "F": ["scripts/frame_probe.py","scripts/frame_probe.py.sha256","scripts/live_repro.py",
       "scripts/record_probe_take.py","scripts/record_probe_take.py.sha256",
       "tests/test_file_leg_probe.py","tests/test_frame_probe.py",
       "tests/test_gain_shape_fixture.py","tests/test_live_repro_arm_b.py",
       "tests/test_record_probe_take.py"],
 "H": ["docs/dossiers/2026-10-31-hyprland-057-release-binds.md","tests/test_task_m_followup.py"],
 "I": ["docs/scene-cards/**","tests/test_model_registry.py","tests/test_wp0_model_registry.py"],
 "K": ["console/capture-state-test.js"],
 "L": ["console/package-lock.json","console/package.json"],
 "R": ["docs/design/2026-11-04-undo-consent-seam.md","docs/design/2026-11-05-producer-seam-estimates.md"],
 "Z": ["HANDOFF.md","reports/DISPATCH-*","tests/test_capture_state_wire.py",
       "tests/test_producer_seams.py","tests/test_undo_consent_guard.py",
       "tests/test_undo_review_pilot.py","tests/test_wp0_watchdog.py"],
}
W_entry = ["models/**","reports/RPT-W-*","scripts/wake_bench.py",
           "src/assistant/nus_surface.py","tests/test_nus_overlay_capture_state.py",
           "tests/test_nus_surface_m1.py","tests/test_w_*.py","ui/quickshell/nus/shell.qml"]

proposed = {k: list(v) for k, v in current.items()}
proposed["I"] = [g for g in proposed["I"] if g not in remove_from_I]
for cluster, globs in add.items():
    proposed[cluster] = sorted(set(proposed[cluster]) | set(globs))
proposed["W"] = sorted(W_entry)
proposed = dict(sorted(proposed.items()))

proposed_bytes = (json.dumps(proposed, indent=2) + "\n").encode()
(REPO / ".git/proposed_owners.json").write_bytes(proposed_bytes)  # scratch, NOT tracked

# --- run the REAL matcher over ALL tracked paths ---
paths = co.git_paths(co.git("ls-files", "--cached", "-z", cwd=REPO))
rules = co.read_map(proposed_bytes)
print("=== PROPOSED lint (real read_map/lint, CLUSTERS extended with W in-memory) ===")
rc = co.lint(paths, rules)
print("lint return code:", rc)

# --- replicate guard self-test test_own_report_accepted core against proposal ---
print("\n=== report-rule self-test (each cluster owns its RPT path; unassigned stays empty) ===")
ok = True
for cluster in sorted(co.CLUSTERS):
    p = f"reports/RPT-{cluster}-r1-x.md"
    got = co.owners_for(p, rules)
    exp = [(cluster, f"reports/RPT-{cluster}-*")]
    if got != exp:
        ok = False; print("FAIL", cluster, got)
print("all clusters own their report path:", ok)
print("reports/unassigned.md owners (must be []):", co.owners_for("reports/unassigned.md", rules))

# --- baseline for the record ---
print("\n=== BASELINE lint (shipped map, shipped CLUSTERS) ===")
base_rules = co.read_map((REPO / "OWNERS.yaml").read_bytes())
co.lint(paths, base_rules)
```

Captured output (sandbox, 2026-11-25):

```
=== PROPOSED lint (real read_map/lint, CLUSTERS extended with W in-memory) ===
497 paths; 0 zero-owner; 0 multi-owner
lint return code: 0

=== report-rule self-test (each cluster owns its RPT path; unassigned stays empty) ===
all clusters own their report path: True
reports/unassigned.md owners (must be []): []

=== BASELINE lint (shipped map, shipped CLUSTERS) ===
497 paths; 60 zero-owner; 0 multi-owner
```

The shipped guard self-test was also run unchanged: `Ran 11 tests … OK`.

---

## 6. Appendix — complete proposed `OWNERS.yaml`

Byte-identical to the map proved in §5. Whole-file paste alternative to
§2b–2d.

```json
{
  "A": [
    "PROCESS-AUDIO-PROMPT.md",
    "VOICE-BUGTEST.md",
    "docs/bug-reports/2026-10-31-gemini-live-transcribe-zero-output.md",
    "docs/packets/2026-11-15-capture-gain-reduction.md",
    "docs/voice-audition*.md",
    "reports/RPT-A-*",
    "scripts/record_elaria_samples.py",
    "src/assistant/asr.py",
    "src/assistant/audio_gateway.py",
    "src/assistant/capture.py",
    "src/assistant/diarize.py",
    "src/assistant/gemini_client.py",
    "src/assistant/live_client.py",
    "src/assistant/transcribe.py",
    "src/assistant/tts.py",
    "src/assistant/voice_catalogue.py",
    "src/assistant/voice_catalogues.json",
    "src/assistant/voiceprint.py",
    "src/assistant/voicetest.py",
    "tests/measure_voice_latency.py",
    "tests/test_a_*.py",
    "tests/test_ack_playback.py",
    "tests/test_bug6_dictate_capture.py",
    "tests/test_bug6_live_duplex_and_stop.py",
    "tests/test_bug6d_ptt_result_orphans.py",
    "tests/test_bug6e_dictate_final_timeout.py",
    "tests/test_bug6f_live_final_and_startup_ack.py",
    "tests/test_bug_generate_worker_cancellation.py",
    "tests/test_bug_i4_speech_say_duplex.py",
    "tests/test_bug_i5_voiceprint_atomic_permissions.py",
    "tests/test_bug_ptt_infinite_wait.py",
    "tests/test_bug_record_elaria_samples.py",
    "tests/test_bughunt_k_ecapa_memfd.py",
    "tests/test_bughunt_k_language_assert.py",
    "tests/test_bughunt_k_record_mode.py",
    "tests/test_bughunt_k_transcript_integrity.py",
    "tests/test_bughunt_k_tts_timeout.py",
    "tests/test_bughunt_k_waits.py",
    "tests/test_bughunt_k_wpctl.py",
    "tests/test_capture_limiter.py",
    "tests/test_capture_limiter_path.py",
    "tests/test_local_asr_degraded.py",
    "tests/test_phase7_kiswahili.py",
    "tests/test_response_extraction.py",
    "tests/test_scene3b_redo.py",
    "tests/test_script_help_smoke.py",
    "tests/test_silence_hotfix.py",
    "tests/test_stage_a_voice.py",
    "tests/test_stream_f_wire.py",
    "tests/test_stream_g7.py",
    "tests/test_stream_g_primary.py",
    "tests/test_stream_h_post_timeout.py",
    "tests/test_stream_h_sensors.py",
    "tests/test_stream_tts.py",
    "tests/test_task_j_ears.py",
    "tests/test_task_k_gateway.py",
    "tests/test_task_l_mouth.py",
    "tests/test_transcription_stump.py",
    "tests/test_voice_bughunt.py",
    "tests/test_voice_chain_resilience.py",
    "tests/test_voice_models_verification.py",
    "tests/test_voicetest.py",
    "tests/test_wp0_call_counters.py"
  ],
  "B": [
    "reports/RPT-B-*",
    "src/assistant/embeddings.py",
    "src/assistant/indexer.py",
    "src/assistant/memory.py",
    "tests/test_b_*.py",
    "tests/test_embeddings_local.py",
    "tests/test_indexer_exclusions.py",
    "tests/test_memory_journal.py",
    "tests/test_memory_retrieval.py",
    "tests/test_memory_schema.py",
    "tests/test_phase5_memory.py"
  ],
  "C": [
    "humour.toml",
    "reports/RPT-C-*",
    "src/assistant/executor.py",
    "src/assistant/inbox.py",
    "src/assistant/initiative.py",
    "src/assistant/intents.py",
    "src/assistant/ladder.py",
    "src/assistant/meeting.py",
    "src/assistant/modes.py",
    "src/assistant/offline_queue.py",
    "src/assistant/organiser.py",
    "src/assistant/persona.py",
    "src/assistant/planner.py",
    "src/assistant/planner_llm.py",
    "src/assistant/showoff.py",
    "tests/test_bug_daemon_aclose_meeting_capture.py",
    "tests/test_bug_i7_xdg_inbox.py",
    "tests/test_bug_meeting_raw_collision.py",
    "tests/test_bug_meeting_stop_deadline.py",
    "tests/test_bug_meeting_stop_failure.py",
    "tests/test_bug_queue_timeout_duplicate.py",
    "tests/test_bughunt_k_executor.py",
    "tests/test_bughunt_k_plan_tasks.py",
    "tests/test_bughunt_k_symlink_hash.py",
    "tests/test_c_*.py",
    "tests/test_notify_privacy.py",
    "tests/test_phase3_organiser.py",
    "tests/test_phase4_executor.py",
    "tests/test_phase6_meeting.py",
    "tests/test_stage_c_initiative.py",
    "tests/test_stage_d_showoff.py",
    "tests/test_wp0_ladder.py"
  ],
  "D": [
    "INVARIANTS.md",
    "fixtures/*.json",
    "fixtures/README.md",
    "reports/RPT-D-*",
    "src/assistant/cleanup.py",
    "src/assistant/disclosure.py",
    "src/assistant/fixtures.py",
    "src/assistant/journal_log.py",
    "src/assistant/proc.py",
    "src/assistant/safety.py",
    "src/assistant/safety_journal.py",
    "tests/bughunt_fixtures/**",
    "tests/test_bughunt_safety.py",
    "tests/test_cleanup_hygiene.py",
    "tests/test_d_*.py",
    "tests/test_disclosure.py",
    "tests/test_disclosure_spec.py",
    "tests/test_fixtures_and_harness.py",
    "tests/test_journal_log.py",
    "tests/test_persona_safety_latency.py",
    "tests/test_wp0_journal_schema.py"
  ],
  "E": [
    "reports/RPT-E-*",
    "src/assistant/drafts.py",
    "src/assistant/phone_link.py",
    "tests/test_drafts.py",
    "tests/test_e_*.py",
    "tests/test_phone_link.py",
    "tests/test_phone_link_refusals.py"
  ],
  "F": [
    "docs/observability-readers.md",
    "reports/RPT-F-*",
    "scripts/capture_source_check.py",
    "scripts/capture_source_check.py.sha256",
    "scripts/capture_source_check.sha256",
    "scripts/daemon_identity.py",
    "scripts/daemon_identity.py.sha256",
    "scripts/file_leg_probe.py",
    "scripts/file_leg_probe.py.sha256",
    "scripts/file_leg_probe.sha256",
    "scripts/frame_probe.py",
    "scripts/frame_probe.py.sha256",
    "scripts/limiter_readings.py",
    "scripts/limiter_readings.py.sha256",
    "scripts/limiter_readings.sha256",
    "scripts/live_repro.py",
    "scripts/player_probe.py",
    "scripts/player_probe.py.sha256",
    "scripts/record_probe_take.py",
    "scripts/record_probe_take.py.sha256",
    "src/assistant/watcher.py",
    "tests/test_capture_source_check.py",
    "tests/test_daemon_identity.py",
    "tests/test_f_*.py",
    "tests/test_file_leg_probe.py",
    "tests/test_frame_probe.py",
    "tests/test_gain_shape_fixture.py",
    "tests/test_limiter_readings.py",
    "tests/test_live_repro_arm_b.py",
    "tests/test_player_probe.py",
    "tests/test_record_probe_take.py",
    "tests/test_watcher.py"
  ],
  "G": [
    "docs/EVENT-MODE-*",
    "docs/event-hardware-checklist.md",
    "docs/event-report*",
    "docs/event-spike.json",
    "docs/event-venue-card*",
    "reports/RPT-G-*",
    "scripts/event-console-fallback.sh",
    "src/assistant/event.py",
    "src/assistant/event_spike.py",
    "tests/test_event_*.py",
    "tests/test_g_*.py"
  ],
  "H": [
    "docs/dossiers/2026-10-31-hyprland-057-release-binds.md",
    "reports/RPT-H-*",
    "src/assistant/clipboard.py",
    "src/assistant/hypr_binds.py",
    "src/assistant/overlay.py",
    "src/assistant/presence.py",
    "src/assistant/waybar.py",
    "systemd/elaria-overlay.service",
    "tests/test_h_*.py",
    "tests/test_phase2_surfaces.py",
    "tests/test_task_m_followup.py",
    "ui/README.md",
    "ui/hyprland/**",
    "ui/quickshell/shell.qml",
    "ui/waybar/**"
  ],
  "I": [
    "docs/phase-reports/2026-10-25-phase0-model-id-audit.md",
    "docs/phase-reports/2026-10-25-wp0-eyes.md",
    "docs/phase-reports/2026-10-26-scene2-order.md",
    "docs/phase-reports/2026-10-26-scene3b-redo.md",
    "docs/phase-reports/2026-10-26-scene3b-triage.md",
    "docs/phase-reports/2026-10-26-stream-f-wire.md",
    "docs/phase-reports/2026-10-27-stream-g-primary.md",
    "docs/phase-reports/2026-10-27-stream-g7-pre-scene.md",
    "docs/phase-reports/2026-10-27-stream-h-scene6-verdict.md",
    "docs/phase-reports/2026-10-31-scene7-mini-order-m.md",
    "docs/phase-reports/2026-10-31-scene7-work-order.md",
    "docs/phase-reports/2026-11-02-voice-chain-resilience.md",
    "docs/phase-reports/2026-11-03-extraction-fix.md",
    "docs/phase-reports/2026-11-05-producer-seams-3-5-6.md",
    "docs/phase-reports/2026-11-05-undo-review-pilot.md",
    "docs/phase-reports/2026-11-14-tasks-j-k-l.md",
    "docs/phase-reports/2026-11-15-clipping-pop-vs-voice.md",
    "docs/phase-reports/2026-11-15-tasks-jkl-addendum.md",
    "docs/scene-cards/**",
    "reports/RPT-I-*",
    "src/assistant/cost.py",
    "src/assistant/model_pins.py",
    "src/assistant/model_registry.py",
    "tests/test_bughunt_k_quota.py",
    "tests/test_i_*.py",
    "tests/test_model_registry.py",
    "tests/test_wp0_model_registry.py"
  ],
  "J": [
    "HOTWORD-REVIEW.md",
    "docs/hotword-training-plan.md",
    "reports/RPT-J-*",
    "src/assistant/hotword.py",
    "src/assistant/wake_buffers.py",
    "src/assistant/wake_guard.py",
    "tests/test_bughunt_k_hotword_knock.py",
    "tests/test_bughunt_k_keyword_window.py",
    "tests/test_bughunt_k_knock_daemon_first.py",
    "tests/test_j_*.py",
    "tests/test_wake_knock_package.py",
    "tests/test_wake_runtime.py",
    "ui/sounds/knock.wav"
  ],
  "K": [
    "console/attribution-test.js",
    "console/capture-state-test.js",
    "console/draft-review-test.js",
    "console/elaria-visualizer.js",
    "console/hands-sidebar-test.js",
    "console/index.html",
    "console/labels-test.js",
    "console/layout-test.js",
    "console/session-test.js",
    "console/src/shell.css",
    "console/src/shell.html",
    "console/src/shell.js",
    "console/vendor/three.min.js",
    "docs/console-home/**",
    "reports/RPT-K-*",
    "systemd/elaria-console.service",
    "tests/test_console_home.py",
    "tests/test_k_*.py",
    "ui/quickshell/console/**"
  ],
  "L": [
    ".gitignore",
    "BUGHUNT*.md",
    "GETTING-STARTED.md",
    "assistant-blueprint.md",
    "bugs.md",
    "change.md",
    "config.toml.example",
    "console/BRIDGE.md",
    "console/CONSUMER-CONTRACT.md",
    "console/INTEGRATION.md",
    "console/audio-owner-test.js",
    "console/bridge-client.js",
    "console/bridge.py",
    "console/build.py",
    "console/ci.sh",
    "console/harness.js",
    "console/package-lock.json",
    "console/package.json",
    "console/requirements-bridge.txt",
    "console/run_bridge.py",
    "console/serve.py",
    "console/smoke.js",
    "console/wire-client-test.js",
    "console/wire-test.js",
    "reports/RPT-L-*",
    "systemd/assistant.service",
    "tests/conftest.py",
    "tests/test_bug_i5_private_storage_modes.py",
    "tests/test_bughunt_corpora.py",
    "tests/test_bughunt_k_authority.py",
    "tests/test_bughunt_systems.py",
    "tests/test_bugs_1_to_5_regressions.py",
    "tests/test_config_and_store.py",
    "tests/test_gate_fix_round.py",
    "tests/test_hardening_pass2.py",
    "tests/test_hardening_pass2b.py",
    "tests/test_hotword_and_reply_delivery.py",
    "tests/test_l_*.py",
    "tests/test_phase1_dictation.py",
    "tests/test_phase8_offline_voice.py",
    "tests/test_stage_abcd_bughunt.py",
    "tests/test_stage_b_console_class.py"
  ],
  "M": [
    "console/NATIVE-DEPLOYMENT.md",
    "console/bind-observer.sha256",
    "console/elaria-console-launch.sh",
    "console/install_native_launcher.py",
    "console/launch-link-test.js",
    "console/native-launcher.sha256",
    "console/native-webkit-test.py",
    "console/native-window.sha256",
    "console/native_launch.py",
    "console/native_window.py",
    "console/observe_native_bind.py",
    "console/verify-native-installer.sh",
    "reports/RPT-M-*",
    "tests/test_m_*.py"
  ],
  "O": [
    "reports/RPT-O-*",
    "src/assistant/hands/README.md",
    "src/assistant/hands/__init__.py",
    "src/assistant/hands/bridge.py",
    "src/assistant/hands/bridge_state.py",
    "src/assistant/hands/core.py",
    "src/assistant/hands/gate.py",
    "src/assistant/hands/injection.py",
    "src/assistant/hands/plan.py",
    "src/assistant/hands/planner.py",
    "src/assistant/hands/queue.py",
    "src/assistant/hands/registry.py",
    "src/assistant/hands/runner.py",
    "src/assistant/hands/sandbox.py",
    "src/assistant/hands/sink.py",
    "src/assistant/hands/verify.py",
    "tests/test_hands_core.py",
    "tests/test_hands_partial_sink.py",
    "tests/test_o_*.py"
  ],
  "P": [
    "docs/contracts/IF-3*",
    "reports/RPT-P-*",
    "src/assistant/hands/headless/__init__.py",
    "src/assistant/hands/headless/consent.py",
    "src/assistant/hands/headless/contract.py",
    "src/assistant/hands/headless/host.py",
    "src/assistant/hands/headless/instance.py",
    "src/assistant/hands/headless/worker.py",
    "tests/test_hands_headless_consent.py",
    "tests/test_hands_headless_contract.py",
    "tests/test_hands_headless_host.py",
    "tests/test_hands_headless_instance.py",
    "tests/test_hands_headless_worker.py",
    "tests/test_p_*.py"
  ],
  "Q": [
    "reports/RPT-Q-*",
    "src/assistant/hands/kitty/**",
    "tests/test_q_*.py"
  ],
  "R": [
    "console/undo-review-test.js",
    "docs/design/2026-11-04-undo-consent-seam.md",
    "docs/design/2026-11-05-producer-seam-estimates.md",
    "docs/design/hands-owner-ruling-transition.md",
    "docs/design/producer-seam-estimates.md",
    "docs/design/undo-consent-seam.md",
    "docs/hands-handoff.md",
    "docs/hands-headless.md",
    "docs/live-scene/pilot-*.md",
    "docs/phase-reports/hands-*.md",
    "fixtures/hands/**",
    "reports/RPT-R-*",
    "tests/test_r_*.py",
    "undo-review-test.js"
  ],
  "REACH": [
    "reports/RPT-REACH-*",
    "src/assistant/reach/**"
  ],
  "REL": [
    "docs/release/**",
    "reports/RPT-REL-*",
    "scripts/release/**"
  ],
  "S": [
    "reports/RPT-S-*",
    "src/assistant/sensors.py",
    "src/assistant/storage.py",
    "src/assistant/tiering.py",
    "tests/test_s_*.py",
    "tests/test_storage_policy.py"
  ],
  "T": [
    "docs/live-scene/op3-*.md",
    "docs/live-scene/op4-*.md",
    "docs/live-scene/op5-*.md",
    "reports/RPT-T-*",
    "scripts/storage-benchmark.sh",
    "scripts/warm-cold-transition.py",
    "src/assistant/backup.py",
    "src/assistant/backup_cli.py",
    "src/assistant/backup_triggers.py",
    "src/assistant/remote.py",
    "tests/test_storage_wiring_t.py",
    "tests/test_t_*.py"
  ],
  "U": [
    "docs/live-scene/sheet1-*.md",
    "reports/RPT-U-*",
    "src/assistant/drill.py",
    "src/assistant/preflight.py",
    "tests/test_u_*.py"
  ],
  "V": [
    "docs/phase-reports/0[0-9][0-9]-*",
    "docs/storage-handoff.md",
    "docs/wp7-accd33a-readback-findings.md",
    "reports/RPT-V-*",
    "scripts/storage-census-check.py",
    "tests/test_v_*.py"
  ],
  "W": [
    "models/**",
    "reports/RPT-W-*",
    "scripts/wake_bench.py",
    "src/assistant/nus_surface.py",
    "tests/test_nus_overlay_capture_state.py",
    "tests/test_nus_surface_m1.py",
    "tests/test_w_*.py",
    "ui/quickshell/nus/shell.qml"
  ],
  "Z": [
    "HANDOFF.md",
    "OWNERS.yaml",
    "README.md",
    "pyproject.toml",
    "reports/DISPATCH-*",
    "reports/RPT-Z-*",
    "scripts/check_ownership.py",
    "src/assistant/__init__.py",
    "src/assistant/cli.py",
    "src/assistant/config.py",
    "src/assistant/console.py",
    "src/assistant/daemon.py",
    "src/assistant/ipc.py",
    "src/assistant/store.py",
    "tests/test_bug7_cli_smoke.py",
    "tests/test_bug_i5_authority_ipc.py",
    "tests/test_bughunt_k_config.py",
    "tests/test_bughunt_k_doctor_drift.py",
    "tests/test_bughunt_k_error_surfacing.py",
    "tests/test_bughunt_k_param_coercion.py",
    "tests/test_bughunt_k_status_surface.py",
    "tests/test_bughunt_k_store.py",
    "tests/test_bughunt_k_subscribers.py",
    "tests/test_capture_state_wire.py",
    "tests/test_daemon_cli.py",
    "tests/test_default_sync.py",
    "tests/test_ipc_handler_integrity.py",
    "tests/test_producer_seams.py",
    "tests/test_undo_consent_guard.py",
    "tests/test_undo_review_pilot.py",
    "tests/test_wp0_watchdog.py",
    "tests/test_z_*.py",
    "uv.lock",
    "uv.toml"
  ]
}
```

---

## 7. Acceptance & rules honoured

- **Deliverable:** this single report; the PR contains only this file.
- **HARD RULE:** `OWNERS.yaml` and `scripts/check_ownership.py` unedited
  (owner applies the patch). Verified by `git diff --name-only`.
- **Acceptance (dispatch):** simulated `lint` prints
  `0 zero-owner; 0 multi-owner` using the real matcher — met (§5).
- **No threshold lowered; no hardware claim; no squatting** — every
  assignment cites the module it tests/produces (§3) or a flagged
  judgment call (§4).
- Agent merges its own PR (owner ruling, DISPATCH 20261125). Manager
  re-verifies after the fact: re-run §5, diff-grep thresholds, review the
  ownership-lint delta, then mark Channel 3 closed on
  `reports/RPT-Z-manager-20261125.md`.
