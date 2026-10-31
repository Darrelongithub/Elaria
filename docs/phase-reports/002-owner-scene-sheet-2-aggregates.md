# Phase report 002 — OWNER SCENE SHEET 2: capacity aggregates (numbers only)

**Date:** 2026-10-27
**Purpose:** supply the one input the capacity model is missing — how much audio
the owner actually keeps. From these aggregates the design chat computes the
20 GB runway and, if it comes back under ~12 months, takes the FLAC /
second-target / tighter-hot-window options to the owner.

**Privacy contract.** Everything asked for here is a **count, a byte total, or a
ratio**. No file name, no transcript, no path that identifies a recording, no
database content, no journal line. If a command below would print anything else,
the sheet says to trim it before pasting.

---

## PART A — EARS STEPS (owner's ears; no terminal, no physical action)

**A1. Decide what "kept" means before measuring.** The COLD class is
*resolved* kept audio — a recording whose transcript has landed and which the
owner chose to keep. Unresolved kept audio is HOT and never leaves the laptop,
so it must not inflate the cold number. If a directory holds both, say so in the
return sheet rather than guessing.

**A2. Note the date the measurement was taken.** The runway is computed from a
dated snapshot; an undated one cannot be compared to a later re-measure.

**A3. Expect the answer to be uncomfortable.** The model in report 000 says a
12-month runway on 20 GB needs ≤ ~29 minutes a day of kept audio, before any
measured compression gain. If the real number is well above that, the honest
outcome is a decision, not a workaround.

---

## PART B — TERMINAL STEPS (paste-safe; owner runs these himself)

Replace `~/elaria-audio`, `~/elaria-journal` and `~/elaria-data` with the real
paths on the laptop. Adjust the `--exclude` lines if the journal archive lives
somewhere else.

### B1 — Total size of each data class (bytes and human-readable)

```bash
for d in ~/elaria-audio ~/elaria-journal ~/elaria-data; do
  [ -d "$d" ] && du -sb "$d"
done
```

### B2 — Kept-wav count and total size

```bash
find ~/elaria-audio -type f -name '*.wav' -printf '%s\n' \
  | awk '{ n++; b += $1 } END { printf "kept_wav_count=%d\nkept_wav_bytes=%d\n", n, b }'
```

### B3 — Split by resolved vs unresolved, if the layout distinguishes them

Only run this if the directory names make the distinction obvious (e.g.
`resolved/` and `unresolved/`). If they do not, skip B3 and say so in the return
sheet — do not guess.

```bash
for k in resolved unresolved; do
  d=~/elaria-audio/$k
  [ -d "$d" ] && du -sb "$d"
done
```

### B4 — Nightly DB snapshot size (these are tiny and live in both places)

```bash
du -sb ~/elaria-data/snapshots 2>/dev/null || echo "no snapshots dir"
```

### B5 — ONE measured restic/zstd compression ratio on a real kept wav

Pick ONE real kept wav. It stays on the laptop. The command compresses it into
`/tmp`, prints the two sizes, and removes the temporary file. Nothing is
uploaded and nothing is printed but two numbers.

```bash
w=~/elaria-audio/resolved/SOME-REAL-KEPT.wav
[ -f "$w" ] || { echo "edit the path first"; exit 1; }
orig=$(stat -c %s "$w")
zstd -q -k -19 -f -o /tmp/ratio-test.zst "$w"
comp=$(stat -c %s /tmp/ratio-test.zst)
rm -f /tmp/ratio-test.zst
awk -v o="$orig" -v c="$comp" 'BEGIN { printf "wav_bytes=%d\nzstd_bytes=%d\nratio=%.4f\nsaving_pct=%.1f\n", o, c, c/o, (1-c/o)*100 }'
```

**Paste the four output lines only.** Never paste the wav's path, its name, or
anything derived from its content. Note in the return sheet which of the four
compression tiers restic's `--compression` you want modelled: `auto` (default),
`fastest`, `better`, or `max` — `zstd -19` above is a proxy for `max`, and the
design chat should be told which one it is looking at.

---

## RETURN SHEET (numbers only)

| # | Measurement | Value |
|---|---|---|
| 1 | Date measured | |
| 2 | `du -sb` audio dir | |
| 3 | `du -sb` journal dir | |
| 4 | `du -sb` data/DB dir | |
| 5 | kept-wav count | |
| 6 | kept-wav total bytes | |
| 7 | kept-wav mean duration (min) — optional, from file count × typical length | |
| 8 | resolved vs unresolved split (if B3 ran) | |
| 9 | nightly DB snapshot bytes | |
| 10 | wav bytes (compression test) | |
| 11 | zstd bytes (compression test) | |
| 12 | ratio (zstd/wav) | |
| 13 | saving % | |
| 14 | which restic `--compression` tier to model | |
| 15 | how many minutes/day of NEW audio the owner expects to keep, going forward | |

Row 15 is the one that actually decides the runway: rows 2–14 describe the past,
row 15 describes the future the 20 GB has to hold. A rough honest estimate beats
a precise guess.

---

## WHAT THE DESIGN CHAT RULES FROM THIS SHEET

Runway in months, on 20 GB, with dedup gain = 0 for audio (unique streams) and
compression gain = the measured ratio from row 12:

```
months = 20 GB / (row_15_GB_per_day x 30.44 x ratio)
```

where `row_15_GB_per_day = minutes_per_day x 115.2 MB/hour / 60 / 1000`.

Decision rule from the WP7 spec, quoted so it cannot be drifted:

> FLAC is DOCUMENTED, NOT BUILT: if the runway math comes back under ~12 months,
> the design chat takes options to the owner (FLAC — lossless transcode allowed
> only as a decode-back hash-verified, manifest-state-changed, never-silent,
> cold-class-only conversion / a second target / a tighter hot window).

So: **under ~12 months ⇒ options to the owner, with these numbers attached.
At or above ~12 months ⇒ proceed, and record the measured runway in
`docs/storage-handoff.md` as the capacity baseline.** Either outcome is a
decision. Neither is a silent workaround.

Reference points already computed (see report 000 §4), assuming zero compression
gain, so every measured point of saving improves on them:

| Runway | Daily kept-audio budget |
|---|---|
| 12 months | ≤ 54.8 MB/day ≈ 28.6 min/day |
| 6 months | ≤ 109.6 MB/day ≈ 57 min/day |
| 3 months | ≤ 219 MB/day ≈ 114 min/day |
