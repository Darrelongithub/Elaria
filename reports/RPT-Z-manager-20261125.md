# MANAGER BOARD — finish Elaria (2026-11-25)

Manager = this session. Job: verify, split, prompt, re-verify.
**Owner correction (2026-11-25): the manager delegates — it does not
build product lanes itself; parallel channels exist to cut time.
Dispatch prompts live in `reports/DISPATCH-20261125.md`.**
**2026-11-25 update (owner ruling): agents merge their own PRs** —
verify, then merge, don't wait. Nobody edits `OWNERS.yaml` but the
owner. Never lower a threshold. Voice lock in every wake plan.
Hardware claims are the owner's eyes/ears only — never report a
sandbox number as hardware. Owner currently cannot run voice tests:
hardware lanes are parked, never blocking.

## Verified baseline (this session, in the sandbox — not the laptop)

- Branch `arena/739b0fbc-elaria` @ `02ed8ba`, was clean.
- Suite: **2921 passed, 32 failed, 25 skipped**. All 32 failures are one
  environment cause: `google-genai` not installed in the sandbox
  (`LiveUnavailable` in `test_stream_*`) — not code failures. Re-run
  with `uv sync` before treating any stream test as red.
- Ownership lint: **491 paths, 57 zero-owner, 0 multi-owner.** No `W`
  cluster exists (`CLUSTERS` in `scripts/check_ownership.py` lacks `W`).
- Wake models: release-asset download is egress-blocked in the sandbox
  (redirect host not allowlisted) and the PyPI wheel bundles no models.
  **Fetching `melspectrogram.onnx` + `embedding_model.onnx` remains an
  owner action** (openWakeWord v0.5.1 release, into `models/`, sha256
  recorded in `models/README.md` next to the ECAPA pin).

## Lane status

| Lane | Scope | State |
|---|---|---|
| 1 J-DETECTOR | openWakeWord ONNX pipeline + energy gate + bench | **built by manager, needs models + head** |
| 2 W-OWNERSHIP | add `W`, claim 57 zero-owner paths | owner-only edit; proposal below |
| 3 J-HEAD | train "Elaria" head on ~1,500 synthetic clips | prompt ready, blocked on Lane 1 models |
| 4 Z-RING | audit pre-roll ring feed/use end-to-end | **DONE — `RPT-Z-ring-audit-20261125.md`: fed + used for detection, not inherited by pinned design** |
| 5 H-OVERLAY | draw `ui/quickshell/nus/shell.qml`, fake-runner harness | **built 2026-11-25: pill renders `capture.state` via `setCaptureState`; eye-check `tests/test_nus_overlay_capture_state.py`; rendering itself = owner's eyes, parked** |
| 6 O-HANDS | real typing path behind the existing gate | **DELEGATED — Channel 1 in `reports/DISPATCH-20261125.md` (manager does not build)** |
| 7 OWNER-HW | SUPER+F2 → speak → hear answer; then wake end-to-end | **PARKED — owner cannot run voice tests right now; not blocking any lane** |

## Lane 1 — done in this board's commit (manager-built, verified)

- `OpenWakeWordModel` in `src/assistant/wake_guard.py`: upstream
  melspec (`x/10 + 2`) → 76-frame embedding windows (step 8) → head over
  its fixed input length (else 16). ONNX Runtime, CPU, no network, no
  `openwakeword` package, no tflite. Fail-closed `load()`. A hit grants
  nothing — ECAPA still verifies the command window, unchanged.
- Energy gate (bug #26): silent frames are ring-buffered but never
  scored (`feed()` returns before `score_window` below `speech_rms`).
- Arm via config: set `[hotword] keyword_melspec_model` +
  `keyword_embedding_model` (+ `keyword_model` = head) in
  `config.toml.example` (documented there).
- `scripts/wake_bench.py`: prints frames/sec, realtime factor, peak
  RSS. **These three numbers, run on the laptop, are Lane 1's
  acceptance.** Not yet run anywhere — no models in the sandbox.
- One eye-check test: `tests/test_j_openwakeword_pipeline.py` (pipeline
  order/shapes, fail-closed load, silent frames never reach the
  spotter). Wake suite green: 67 passed, 18 skipped.

## Prompts — paste each to a fresh agent, one lane per agent

Each prompt is self-contained. Every agent: work on a new
`arena/*` branch, build first, ONE eye-check test that fails if the
wiring is removed, open a PR, never merge, never edit `OWNERS.yaml`,
never lower any threshold, report raw numbers not conclusions.

### Lane 3 — J-HEAD (start after owner drops the two shared models in)

> You are building ONE lane of Elaria (Fedora/Hyprland voice assistant,
> repo Darrelongithub/Elaria). Read `assistant-blueprint.md` §9/§13 and
> `reports/RPT-Z-manager-20261125.md` Lane 1 first. Task: train the
> "Elaria" wake-word head for the existing `OpenWakeWordModel` in
> `src/assistant/wake_guard.py` (it consumes melspectrogram.onnx +
> embedding_model.onnx from openWakeWord v0.5.1, both in `models/`).
> Generate ~1,500 synthetic positive clips of "Elaria" (varied TTS
> voices/pitch/tempo/noise) plus hard negatives (similar-sounding
> words, room noise, TV speech). Extract embeddings with the existing
> pipeline, train a small classifier head, export ONNX with fixed
> input shape [1, N, 96], save as `models/elaria_head.onnx`, record
> sha256 + training recipe in `models/README.md`. Acceptance: report
> (a) false-accept rate on negatives, (b) false-reject rate on held-out
> positives, (c) `scripts/wake_bench.py` output run in your sandbox —
> labelled sandbox, not hardware. Do NOT lower `keyword_threshold`
> below 0.5 to make numbers pass; if the head is weak, say so with the
> numbers. One eye-check test in `tests/test_j_*.py` proving the
> exported head loads through `OpenWakeWordModel.load` (skip if models
> absent). PR only; do not merge.

### Lane 4 — Z-RING (start now, no dependencies)

> You are building ONE lane of Elaria (repo Darrelongithub/Elaria).
> Read `src/assistant/wake_buffers.py` (`PreWakeRing`), the
> `_hotword_loop` in `src/assistant/daemon.py` (~line 1973, frames
> already reach `WakeGuard.feed`), and `WakeGuard.note_frame`. Audit
> question: is pre-hit audio actually USED anywhere (session head,
> command window, latency), or only buffered and discarded? The
> handoff claim "ring built, unfed" is stale at the guard level —
> verify, don't trust it. Deliverable: either (a) wire the ring's
> pre-roll into the wake session so a verified hit's audio starts at
> the phrase, not after it, or (b) a short report in
> `reports/RPT-Z-*` proving with file:line citations that it already
> is, naming the exact consumer. Hard rules: ring stays RAM-only,
> zeroed on every non-attending outcome, never persisted, never scored
> by ECAPA (the wake clip is never scored — that rule is absolute).
> One eye-check test that fails if your wiring is removed. PR only.

### Lane 5 — H-OVERLAY (start after Lane 2 claims the qml path)

> You are building ONE lane of Elaria (repo Darrelongithub/Elaria).
> `ui/quickshell/nus/shell.qml` has a working `reveal()` (layer-shell
> level 3, hardware-verified) but is never drawn in a real session.
> Task: make the overlay show Elaria's state (idle/listening/
> verifying/speaking) driven ONLY by the daemon's `capture.state`
> emissions — no browser mic, no second source of truth, indicators
> change on transition only. Build a fake-runner harness that feeds
> recorded `capture.state` sequences into the surface so the states
> are checkable without hardware, plus one eye-check test. Anything
> that draws needs the owner's eyes: end your PR with the exact
> on-laptop command the owner runs and what they should see, in
> order. Never claim it renders — claim the harness passes. PR only.

### Lane 6 — O-HANDS (start now; synthetic gate already exists)

> You are building ONE lane of Elaria (repo Darrelongithub/Elaria).
> `src/assistant/hands/` is synthetic-only by design (gate, runner,
> sandbox all refuse real dispatch). Task: add the real typing path
> BEHIND the existing gate — text injection only, no clicks, no
> arbitrary key chords, never `call PLUGIN ACTION`. The real sink
> must refuse until the same consent/authority checks the synthetic
> path enforces have passed, must be off by default in config, and
> every refusal must be logged. Do NOT install python-evdev and do
> NOT create uinput rules — the daemon boots without them; the real
> sink detects absence and refuses honestly. Acceptance: one
> eye-check test proving (a) gate closed → zero injection calls,
> (b) gate open + synthetic sink → text flows. Hardware typing is the
> owner's test, not yours. PR only.

## Lane 2 — ownership proposal (OWNER applies; agents never edit it)

Add `"W"` to `CLUSTERS` in `scripts/check_ownership.py`, add a `W`
entry to `OWNERS.yaml` claiming: `models/**`,
`tests/test_w_*.py`, `ui/quickshell/nus/shell.qml`,
`scripts/wake_bench.py`, and assign each of the other 53 zero-owner
paths from `python3 scripts/check_ownership.py lint` to its producing
cluster (test files follow the module they test). Acceptance:
`lint` prints `0 zero-owner; 0 multi-owner`. Until this lands, new
files in unclaimed paths (incl. `scripts/wake_bench.py` from Lane 1)
will show as unowned — expected, not an error to "fix" by squatting.

## Lane 7 — owner hardware checklist (in order, ~10 min)

1. `SUPER+F2` → speak a command → **do you hear an answer?** (This is
   the handoff's never-answered §31 question. Yes/no + what happened.)
2. Drop `melspectrogram.onnx` + `embedding_model.onnx` (openWakeWord
   v0.5.1) into `models/`; tell the manager the sha256s.
3. After Lane 3's head lands: set the three `[hotword]` model paths,
   run `python3 scripts/wake_bench.py --head models/elaria_head.onnx
   --melspec models/melspectrogram.onnx --embedding
   models/embedding_model.onnx` — paste the three numbers.
4. Say "Elaria" from across the room; then have someone else say it.
   Expected: she attends for you, total silence for them.

## Manager's next verification (on each PR)

Re-run the lane's eye-check test + the full suite (expect ≥2921
passed, failures only from missing sandbox deps), `check_ownership.py
lint` delta reviewed, thresholds diff-grepped (`ecapa_high`,
`keyword_threshold`, `MIN_WINDOW_S` must never decrease), then hand
to owner for merge.
