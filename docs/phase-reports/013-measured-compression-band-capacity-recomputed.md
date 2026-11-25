# Phase report 013 — measured compression band; capacity table recomputed

**Date:** 2026-10-31
**Branch:** `arena/storage` @ `08358a1`
**Trigger:** design-chat ratio addendum — two measured real-voice zstd -19 ratios.

---

## DONE

### 1. THE MEASURED BAND (RULING 34)

| Measurement | Ratio | Source artifact |
|---|---|---|
| Watchdog capture | **0.475** | 9,637,484 B |
| Session wav | **0.582** | 330,284 B |

**Cold weighs 48–58% of hot.** This supersedes the expected 0.6–0.9, which was
conservative; the direction is favourable and the ruling raises no retune flag.

### 2. WHAT THIS DISCHARGES

Report 004's capacity model carried an explicit standing assumption:

> *"compression gain = 0 until Scene Sheet 2 measures one real restic/zstd ratio on a real
> kept wav."*

**That line is discharged.** Sheet 2's "one measured zstd ratio" obligation is met — and
met with two measurements rather than one. The census (`du` aggregates, kept-wav count) is
still owed and still gates the final numeric defaults.

Every WP7 number built on the zero-compression floor is recomputed below. The floor was
the conservative case; the measured band is the real one, and it is **1.7x–3.9x better**
depending on which figure you read.

### 3. EVIDENCE CLASS — recorded, not glossed

- **What was measured:** zstd -19 ratios on two real voice wavs. [TESTED-ONLY] — real
  audio, real measurement, reproducible.
- **What was NOT measured:** an end-to-end restic-over-MEGA round trip. restic's own
  compression is zstd, so the ratio is the right *shape*, but restic adds pack overhead,
  dedup metadata, and the rclone/MEGA transport on top — none of which is in these
  numbers.
- **Consequence:** the end-to-end cold weight will be **≥48% of hot, probably somewhat
  more.** Capacity planning uses the conservative end (**0.582**) as the working figure;
  the favourable end (**0.475**) is headroom, not a plan.
- **Dedup gain remains 0** for audio (unique streams) — that standing assumption is
  unchanged and unaffected.
- **Only Sheet 1's benchmark can close the restic-overhead gap.** Until it returns, no
  number in this report may be quoted as a tuned end-to-end figure.

### 4. A SIZE OBSERVATION WORTH CARRYING

The 9.6 MB watchdog capture compressed **better** (0.475) than the 330 KB session wav
(0.582). zstd's window means larger inputs compress better, so **the band is
size-dependent, not a single constant.** Two consequences:

- any future measurement should record the artifact size alongside the ratio;
- the band should be re-derived if the kept-wav census shows a size mix very different from
  these two samples.

This is the kind of detail that quietly invalidates a capacity model if it is not written
down, so it is written down.

### 5. THE RECOMPUTED TABLES

**Per-unit cold weights** (16 kHz mono 16-bit = 32,000 B/s = 1.92 MB per kept-minute raw):

| | @0.475 | @0.582 |
|---|---|---|
| 1 kept-minute | 0.9120 MB cold | 1.1174 MB cold |
| 1 hour | 54.72 MB cold | 67.05 MB cold |
| One 8-hour event | 437.8 MB cold | 536.4 MB cold |

**12-month bar** — daily budget that exactly fills 20 GB in 365 days (54.79 MB/day cold):

| | kept-min/day | vs floor |
|---|---|---|
| old floor (gain 0) | 28.5 | 1.00x |
| @0.475 | **60.1** | 2.11x |
| @0.582 | **49.0** | 1.72x |

Same against the 18 GB usable (2 GB knock floor, 49.32 MB/day cold): **44.1–54.1
kept-min/day** (floor: 25.7).

**WP5 daily allowance** — 18 GB minus monthly 8-hour events, per year. The headline number:

| | events | budget | MB/day | **kept-min/day** | vs floor |
|---|---|---|---|---|---|
| old floor | 11.06 GB/yr | 6.94 GB/yr | 19.02 | **9.9** | 1.00x |
| @0.475 | 5.25 GB/yr | 12.75 GB/yr | 34.92 | **38.3** | 3.87x |
| @0.582 | 6.44 GB/yr | 11.56 GB/yr | 31.68 | **28.4** | 2.86x |

**The owner's practical daily budget is roughly three times what the conservative floor
implied** — from ~10 kept-min/day to 28.4–38.3.

**Flood math** — one 8-hour event day against the 12-month daily bar:

| | days of budget consumed |
|---|---|
| old floor | 16.8 |
| @0.475 | **8.0** |
| @0.582 | **9.8** |

Still a heavy day, no longer catastrophic.

### 6. THE EVENT-FREQUENCY VERDICT TABLE, RECOMPUTED

Months to fill 20 GB with 8-hour events alone (921.6 MB raw each):

| Frequency | raw GB/yr | cold @0.475 | cold @0.582 | **mo @0.475** | **mo @0.582** | old floor |
|---|---|---|---|---|---|---|
| daily | 336.38 | 159.78 | 195.78 | 1.5 | 1.2 | 0.7 |
| 2x/week | 95.85 | 45.53 | 55.78 | 5.3 | 4.3 | 2.5 |
| weekly | 47.92 | 22.76 | 27.89 | 10.5 | 8.6 | 5.0 |
| fortnightly | 23.96 | 11.38 | 13.95 | **21.1** | **17.2** | 10.0 |
| **monthly (ruled target)** | 11.06 | 5.25 | 6.44 | **45.7** | **37.3** | 21.7 |
| quarterly | 3.69 | 1.75 | 2.15 | 137.1 | 111.9 | 65.1 |

**The ruled design target stands: MONTHLY**, now with **37.3–45.7 months** of headroom
against a 12-month requirement — roughly double the floor's 21.7, so comfortable rather
than marginal.

**One threshold genuinely moved, and it is recorded rather than smoothed over:**
**fortnightly now clears 12 months (17.2–21.1) where the floor said it did not (10.0).**
Weekly still does not clear (8.6–10.5). The "highest frequency that survives" line has
therefore shifted from monthly to fortnightly. Monthly remains the ruled target — the
ruling says compression is headroom, not a requirement — but the owner now has a measured
basis to choose fortnightly. Raised as **Q24**, not acted on.

### 7. CONFIG IMPACT

**No `[backup]` default changes.** The measured band informs the capacity model and the
capacity-floor knock threshold, both of which remain `INTERIM-PENDING-SHEETS` pending the
census. The `hot_window_days` / `hot_window_gb` pair governs how long audio stays HOT
before going cold and is unaffected by the compression ratio — a point worth stating
because it is an easy one to conflate.

---

## DEFECTS FOUND

**None in the lane.** One correction to my own arithmetic during this activation: my first
pass at the recomputation inverted two formulas (the kept-minutes division and the
months-to-fill factor), producing figures like "monthly = 45,687 months". Caught by
recomputing in a script and sanity-checking against the known floor values (monthly at
floor must be 21.7 months, and it was not). Corrected before anything was recorded. Worth
noting because the wrong numbers looked plausible in isolation.

---

## NEXT GATE

**Increment 2 — reconcile-on-start + crash-point tests.** Unchanged and unaffected by this
addendum; the manifest's state machine is what those tests exercise.

**Sheet 1** (MEGA in browser, owner-run rclone config, benchmark) now carries an added
job: it must measure the **end-to-end restic-over-MEGA ratio** so the restic overhead
between the measured zstd band and the real cold weight can be closed. Until then the
0.582 end of the band is the working figure.

**Sheet 2** census still owed: `du` aggregates and kept-wav count. The zstd-ratio line is
discharged.

---

## OPEN QUESTIONS

**Q24 — does the measured band re-open the event-frequency choice?** Fortnightly now
clears 12 months (17.2–21.1) where the zero-compression floor said it did not (10.0).
Monthly remains the ruled target and is comfortable at 37.3–45.7 months. Options:

- **(a) monthly stands** — the ruling says compression is headroom, not a requirement, and
  monthly keeps the largest safety margin against an unmeasured end-to-end ratio;
- **(b) fortnightly** — now clears 12 months on measured data, and would roughly halve the
  event volume while leaving a 17-month floor;
- **(c) hold the question until Sheet 1** — the end-to-end ratio will be worse than the
  raw zstd band, and choosing a denser calendar before that is measured is exactly the
  "unverified assumption in design-document clothes" the lane is told to avoid.

I lean **(c)** then **(a)** — but the fortnightly result is a real, measured change and the
owner should see it rather than have me file it under "headroom".

**Q25 — none blocking.** The size-dependence of the band is recorded for whoever runs the
census.
