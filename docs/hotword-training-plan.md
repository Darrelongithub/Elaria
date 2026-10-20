# Hotword training plan — wake-clip capture, evaluation bars, milestones

**Status:** plan + capture tooling only. Training (20k+ synthetic positives,
GPU) is out of scope for this repo. **No fabricated model ships here**: if no
real `.onnx` keyword model exists, `assist hotword start` refuses cleanly.
The ECAPA scorer is an external hardware-side command (see
`[hotword] ecapa_cmd`); it is never imitated in-tree.

This document pre-commits the evaluation bars **before** any threshold
tuning. Moving a bar later is a documented decision, not a quiet edit.

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

### Stage B (wake-clip + pending buffer as the primary input)

| Cohort | Bar |
|---|---|
| Owner, quiet close | **≥ 95%** |
| Owner, arm/across/noise | **≥ 90%** |
| Non-owner (other speakers) | **≥ 95% reject** |

Wake+post and wake-only cohorts are reported **SEPARATELY** — the dual-use
pending buffer inherits speechful post-trigger audio when there is any, and
the insufficient-speech branch scores the wake clip alone. A single blended
number hides which branch is failing.

### Stage C (gate behaviour)

* high-confidence owner → ATTENDING → listening;
* anything else → wake-knock (accept opens listening; decline/ignore sleeps);
* **zero** Stage-A→command paths without Stage B: no trigger may reach
  command listening without a verification verdict or a human accept.

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
