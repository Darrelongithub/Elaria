# Hotword training plan — wake-clip capture, evaluation bars, milestones

**Status:** plan + capture tooling only. Training (20k+ synthetic positives,
GPU) is out of scope for this repo. **No fabricated model ships here**: if no
real `.onnx` keyword model exists, `assist hotword start` refuses cleanly.
The ECAPA scorer is an external hardware-side command (see
`[hotword] ecapa_cmd`); it is never imitated in-tree.

This document pre-commits the evaluation bars **before** any threshold
tuning. Moving a bar later is a documented decision, not a quiet edit.

## Inference home — ONNX only (GATE-FIX 2, 2026-10-25)

**Decision: option (a), ONNX Runtime on the daemon's normal interpreter.** The
owner's wake word is **paused at 0 takes**, so there is no deployed model or
training corpus to migrate. The model artefact is `.onnx` already.

- `wake_guard.OnnxKeywordModel` is the one keyword-inference implementation;
  `voicetest.OnnxKeywordScorer` delegates to it. Remove the old openWakeWord
  package/adapter rather than setting its inference flag: openWakeWord 0.6
  declares `tflite-runtime` on Linux regardless of which model format is used.
  TFLite 2.14 has no CPython 3.14 wheel/source distribution for Fedora 44.
- `uv sync --extra voice` is the explicit optional wake command. It selects
  ONNX Runtime (CPU), **not** TFLite, SpeechBrain or a training stack. Plain
  `uv sync` selects the daemon runtime + dev group, not the wake extra; ONNX
  Runtime may also be installed transitively by Whisper/Piper. Having that
  library installed never arms wake. uv's universal lock includes optional
  metadata, but contains no openWakeWord/TFLite dependency at all.
- No wake-only Python 3.11 toolchain is needed. Model training/export and
  the external `[hotword] ecapa_cmd` scorer remain separate work; we do not
  install a GPU training environment into the assistant venv.
- With no configured model, no model file, or an unavailable ONNX Runtime
  (including a missing native library), `assist doctor` reports **wake word
  paused** as a warning. The daemon starts normally; `assist hotword start`
  refuses cleanly before opening capture. PTT/dictation still work. There is
  **no energy fallback** on the command-authority path.

**Model contract, before any future training:** 16 kHz mono s16le PCM,
normalized to float32 samples in a `(1, N)` window; one keyword-confidence
output. The configured trailing window is `[hotword] keyword_window_s` (1 s
by default, capped at the 2 s RAM ring). An exported model requiring mel
features must include its extractor, or the shared adapter must be deliberately
extended and tested before arming. An arbitrary openWakeWord `.onnx` file with
external feature models is **not** a drop-in substitute for this contract.
The `assist-voice-test run` CLI remains the labelled synthetic/energy plumbing
harness; its results are not trained-keyword accuracy. No sample counts or
hardware accuracy are claimed by this packaging fix.

The old emergency command
`uv sync --all-groups --all-extras --no-install-package tflite-runtime` is
historical recovery advice, not the supported installation path after this fix.
See [GETTING-STARTED.md](../GETTING-STARTED.md) for default install/update commands.

---

## 1. Phrases and buckets

| Phrase | Role |
|---|---|
| `Elaria` | primary wake phrase |
| `hey Elaria` | secondary wake phrase |

**Near-word negatives** (must NOT trigger): malaria, area, Larry, hilary,
scenario, and friends.

**ONE split mechanism** — the split is the *directory tree*, never a flag in
data:

```
~/elaria-wake-samples/          # NEVER added to any repo
  train/                        # training material only
    elaria-close-normal/…
    elaria-close-calling/…
    …
  eval/                         # frozen BEFORE any threshold tuning
    elaria-close-normal/…
    …
  manifest.jsonl                # one JSON per take; NO split field
```

Rules:

* ~20% of each bucket is frozen into `eval/` **before** any threshold is
  tuned (the capture script's `--freeze-eval` move is the single splitter).
* eval is **never** retrained on. Never merge the trees back.
* `manifest.jsonl` rows carry `path` relative to the root; the tree location
  (train/ vs eval/) is the split. A `split` field is deliberately absent.

## 2. Milestone A — ~120 takes

| Bucket | Takes | Notes |
|---|---|---|
| elaria close normal | 25 | seated, quiet room, normal voice |
| elaria close calling | 10 | raised "calling across a room" delivery |
| elaria arm normal | 12 | arm's length (~1–2 m) |
| elaria across normal | 12 | across the room (~3–4 m) |
| elaria tv_on | 12 | TV/radio at conversational level |
| hey elaria close normal | 15 | secondary phrase |
| near-words | 20 | malaria, area, Larry, hilary, scenario… |
| free speech | 2 × 30 s | continuous talking, NO wake phrase |
| ambient | 2 × 30 s | room tone, keyboard, traffic |

## 3. Milestone B — top-up to ~330 total

Tired and mid-conversation tones; music playing; kitchen noise; more
distances (hallway, next room); other-speaker negatives if a second voice is
available (their speech must never trigger — record it under
`otherspeaker-…`).

## 4. Evaluation bars — PRE-COMMITTED

### Stage A (keyword detector alone)

| Metric | Bar | Stretch |
|---|---|---|
| False accepts / hour, TV soak (4 h+) | **≤ 0.5 FA/h** | 0.2 FA/h |
| Recall, close + quiet | **≥ 90%** | |
| Recall, arm's length / across room | **≥ 75%** | |
| Recall, noisy (tv_on, kitchen, music) | **≥ 60%** | |
| Near-word false accept rate | **≤ 5%** | |

### Stage B (the COMMAND window as the primary input — round J, 2026-11-22)

**Verify the command, never the wake word.** Measured on the pinned model
(`voxceleb_ECAPA512_LM.onnx`, real 16 kHz corpus in
`models/ecapa_eval_samples.npz`):

| Window | Enrolled owner | Impostor |
|---|---|---|
| 0.6 s (wake length) | 0.341 / 0.588; **0/12** sliding windows reach 0.75 | 0.043 / 0.013 |
| 2.5 s (command length) | 0.793 / 0.842 | 0.043 / 0.013 |

A wake-length window is not a verification unit, so Stage B does not accept
one. The bars below are unchanged; only the input they are measured on is.

| Cohort | Bar |
|---|---|
| Owner, quiet close | **≥ 95%** |
| Owner, arm/across/noise | **≥ 90%** |
| Non-owner (other speakers) | **≥ 95% reject** |

Cohorts are measured on **command windows ≥ 1.75 s** (the in-code floor
`MIN_WINDOW_S`, `wake_guard.py` — not a config value). Below 1.75 s there is
**no scoring call at all**, so a short window can neither pass nor fail: it
does not enter the cohort, and it opens nothing.

The floor is measured, not chosen: at the pinned model's post-wake windows
the held-out owner utterance reaches +0.05 of margin over `ecapa_high` at
~1.56 s, but only at 1.75 s does every owner window in a 0.1 s sliding sweep
clear 0.75 (at 1.50–1.70 s, 1–2 of the 5–11 windows fall to 0.736–0.744).
Impostors stay ≤ 0.166 at every duration from 0.6 s to 2.0 s.

### Stage C (gate behaviour)

* high-confidence owner (≥ `ecapa_high` 0.75) on a command window →
  ATTENDING → listening, with the command window inherited as the head;
* anything below `ecapa_high` — including the `uncertain` band 0.50–0.75 —
  → **silent discard**: no knock, no reply, no acknowledgement, no speech,
  pending buffer zeroed, one metadata-only record, back to idle. The
  ambiguous band is never permissive, and neither threshold is lowered by
  data from this corpus (impostors at 0.04 would "justify" 0.55, and that
  change opens the microphone: forbidden);
* replayed / recorded / non-live windows → the `showoff.py` BH-H15 rule,
  i.e. the same silent discard;
* the wake-knock remains for an **owner-authentication prompt** only; an
  unrecognised voice never raises one, so an impostor cannot tell they were
  heard;
* **zero** Stage-A→command paths without Stage B: no trigger may reach
  command listening without a `≥ ecapa_high` verdict on command audio.

## 5. Capture tooling

`scripts/record_elaria_samples.py` records on the **production mic path**
(`pw-record`, the configured `[capture] mic_target`) — sample mismatch between
training capture and runtime capture is a silent killer, so there is exactly
one path.

```
python scripts/record_elaria_samples.py plan          # show the milestone schedule
python scripts/record_elaria_samples.py record --bucket elaria-close-normal \
        --takes 25 --phrase "Elaria"
python scripts/record_elaria_samples.py freeze-eval   # 20%/bucket, ONCE, before tuning
python scripts/record_elaria_samples.py status        # per-bucket counts
```

Samples live under `~/elaria-wake-samples/` (chmod 700), outside every repo.

## 6. Privacy invariants for the always-on path (carried by code, not this doc)

* Pre-wake ring ≤ 2.0 s, 16 kHz mono, RAM only, fixed circular overwrite.
* No pre-wake audio in any log. Ring + pending buffers request
  `MADV_DONTDUMP`; the systemd unit sets `LimitCORE=0`. Both are exposed by
  `assist hotword status` / `assist doctor` so "crash leaves nothing" is
  checkable.
* Wake clips off by default; opt-in saves ≤ 5 s, 0700 dir, 24 h purge;
  failed-verify audio is never saved unless the explicit debug flag is set.
* Watchdog: > 2 s without frames while armed → disarm, zero buffers, visible
  `stalled` state. Never a silent forever-recording.

## 7. Lane J-HEAD — the first trained head (2026-11-25)

`models/elaria_head.onnx` is the first real head for
`wake_guard.OpenWakeWordModel` (openWakeWord melspec + embedding → 4×96
embeddings → 256→64 MLP → sigmoid). It was trained **in a sandbox on
espeak-ng synthesis only**, because no human "Elaria" recordings exist
there. The recipe, sha256 and raw numbers live in
[`models/README.md`](../models/README.md); the eye-check is
`tests/test_j_elaria_head.py`.

**What changed in code (lane J):** `WakeGuard.arm()` now builds
`OpenWakeWordModel` when `[hotword] keyword_melspec_model` is set. Before
that, `arm()` only ever constructed `OnnxKeywordModel`, so the documented
melspec/embedding keys were read by nothing and a trained head was
unreachable from `assist hotword start`. `assist doctor` reports which of
the two pipelines is configured. A half-configured pipeline is a refusal
naming the missing keys, never a guess.

**What the numbers do and do not say.** At the frozen
`keyword_threshold = 0.5`: false-reject 6.0 %, false-accept 4.0 % on 780
held-out windows from 7 voices the head never heard (the reproducible recipe
trains on 34 of the 208 espeak timbres, because only those synthesise
byte-identically run to run). Those are *synthetic-to-synthetic* numbers.
They do **not** discharge the Stage-A bars above — no TV soak, no distance
sweeps, no real rooms, no other-speaker recordings — and **two of those bars
already fail here**: recall 94.0 % against the ≥95 % bar, and near-words
6.4 % against the ≤5 % bar (the residual false accepts are true homophones:
`Ilaria`, `Alaria`, `el area`, on unseen voices). The 208-voice variant of
the same recipe scored 2.0 % / 3.5 % (near-words 5.3 %); the difference is
recorded in `models/README.md` rather than traded for a quieter threshold.

**Reproducibility is part of the recipe.** Two runs of the documented
command produce byte-identical `models/elaria_head.onnx` and fixture.
That is why the trainer pins its own ONNX sessions to one thread and skips
the 174 espeak voices that synthesize differently every call — an artefact
nobody can re-derive makes every number above unverifiable.

**The next training round is the owner's corpus, not more espeak.**
Milestone A (~120 takes, section 2) is the missing ingredient: real
positives and real hard negatives. `scripts/train_elaria_head.py` already
takes its feature path from the runtime, so a future round can replay that
corpus through the same extractor with no code change. Never buy recall by
raising `keyword_threshold`; the ambiguity band is not a permission
(Stage C).
