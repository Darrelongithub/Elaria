# Phase report 014 — census delivered; defaults FINAL; capacity recomputed; one honest disagreement

**Date:** 2026-10-31
**Branch:** `arena/storage` @ `13e4882`
**Trigger:** census delivery + FINAL defaults + Q24 ruling.

---

## DONE

### 1. THE CENSUS (RULING 35) — discharges the owed line

| Fact | Value |
|---|---|
| Files in `audio/` | **37** = 35 session wavs + 2 artifacts |
| Kept-session bytes | **80,698,682 B** (80.70 MB / 76.96 MiB) |
| `du -sb audio/` | **138,298,770 B** |
| Assistant tree | 372 M |
| `event-spike.wav` | 57,600,044 B, synthetic 30-min test tone, **relocated by owner order** to `~/.local/share/assistant/test-assets/`; WP5 spike-path paperwork = **M-1, mainline's** |
| `20261025-181730-4d90bf.wav` | **44 bytes**, header-only, **never-retry mark under the deferred-audio contract, counts zero forever** |
| Growth | **≈11–13 MiB/day**, including one 9.6 MB runaway outlier |

**The census arithmetic self-checks exactly:** 80,698,682 + 57,600,044 + 44 = **138,298,770**
= `du -sb audio/`. Tierable = 80.70 MB; excluded = 57.60 MB. A census that reconciles
byte-for-byte against `du` is one I can build on.

**Average kept session wav = 2.306 MB = 1.20 kept-minutes** raw. The typical kept session
is about a minute and a quarter — worth having in hand when reading every figure below.

**PERMANENT EXCLUSIONS from tiering and trim, ruled forever:** voice-cache and test-assets.
The reasons are contracts, not tidiness — **0 ms recall** for the voice cache,
**offline-voice** for test-assets. Neither may ever be trimmed to reclaim space. This is a
tiering-scope ruling that increment 3 must honour.

### 2. DEFAULTS FINAL (RULING 36) — applied to config

| Key | Was (interim) | **Now (FINAL-CENSUS)** |
|---|---|---|
| `hot_window_days` | 14 | **14** — value unchanged, status final |
| `hot_window_gb` | 2 | **2** — value unchanged, status final |
| `restic_pack_size_mib` | 16 | **128** |
| `capacity_floor_gb` | 2 | **10** |

`trim_grace_days` **stays `INTERIM-PENDING-SHEETS`** — the grace period was not in the
census and nothing bounds it. It is now the last interim value in `[backup]`, which is a
useful signal: exactly one number is still unmeasured.

Applied to both `DEFAULTS` and `config.toml.example`; parity verified by test.

**HOT window confirmed by arithmetic, not accepted from prose:** at measured growth, 14 days
of hot audio is 154–182 MiB ≈ 0.15–0.18 GiB — about **11x under** the 2 GB cap. So the
**14-day window binds** and the cap is a backstop, exactly as the ruling's parenthetical
claimed.

**Capacity-floor semantic note:** the key is `remote_free` (knock when free < 10 GB), which
on a 20 GB tier is **equivalent to "10 GB consumed"** — the ruling's phrasing. Same
threshold, two spellings; recorded so neither is misread later.

**Capacity ruling: GO.**

### 3. Q24 RULED = (c) then (a) (RULING 37)

Frequency stays **MONTHLY** until Sheet 1 measures the end-to-end ratio. **Fortnightly is
recorded as a measured, owner-available option (17.2–21.1 months) that only the owner may
pick, by number, on their own initiative.** **Weekly remains ruled out** (8.6–10.5). The
lane does not re-propose frequency absent an owner word. Sheet 1's added job ratified.

### 4. THE RECOMPUTED CAPACITY TABLE — old-floor column retired to history

Cold growth: hot 11.53–13.63 MB/day (6.0–7.1 kept-min/day) → **cold 5.48–7.93 MB/day**.
Monthly 8-hour events cold: 5.25–6.44 GB/yr = **14.39–17.64 MB/day**.

| Scenario | 10 GB knock | 20 GB full tier |
|---|---|---|
| Daily audio only, best (0.475) | **5.00 yr** | **10.00 yr** |
| Daily audio only, worst (0.582) | **3.45 yr** | **6.91 yr** |
| Daily audio **+ monthly events**, best | **1.38 yr** | **2.76 yr** |
| Daily audio **+ monthly events**, worst | **1.07 yr** | **2.14 yr** |

Every figure computed in a script and cross-checked against the known floor values before
being recorded. The old-floor column is **retired to history** per the ruling; report 004's
zero-compression numbers remain as the record of what was assumed before measurement.

### 5. TWO STRUCTURAL FINDINGS THE CENSUS PRODUCED

1. **Monthly events dominate daily audio by 2–3x** (14.39–17.64 vs 5.48–7.93 MB/day cold).
   The event calendar is the dominant capacity driver, not daily usage — consistent with the
   whole flood-math thread, and the reason frequency is an owner decision rather than a lane
   one.
2. **Actual usage is well under plan:** the census implies 6.0–7.1 kept-min/day against the
   WP5 allowance of 28.4–38.3 — **16–25% of budget**. The favourable reading.

---

## DEFECTS FOUND

**None in the lane.** Two process notes worth recording:

1. **The increment-1 label test would have failed silently against the new ruling.** It
   asserted an interim set that the census has now partly promoted. Rather than delete it, I
   **evolved** it: it now enforces the two-marker split, so an unmeasured value cannot be
   quietly promoted to final and a census-backed value must say so. A second test pins the
   FINAL numbers. Deleting a test because a ruling changed its expectation is how a lane
   loses its own guardrail.
2. **A stale value assertion in the increment-1 config test** (`capacity_floor_gb == 2`)
   failed loudly when the census landed. Correct behaviour — it is the test doing its job —
   and it was removed only because the new census test owns those numbers in one place.

---

## NEXT GATE

**Increment 2 — reconcile-on-start + crash-point tests.** Proceeds as scheduled, unaffected
by the census. The three crash points to pin: kill between upload and flip (reconcile
re-verifies then flips); kill between flip and trim (trim idempotent); flip fsync'd before
any trim.

**Still gated, unchanged:** live MEGA traffic (Sheet 1 output + design go/no-go); merge
(gate v2-AMENDED); the additive-only firewall; the owner's real content.

---

## OPEN QUESTIONS

**Q26 — the "decades" claim does not reproduce, and the gap is large.** The ruling says *"at
the measured band the floor clears in decades."* My arithmetic says:

- daily audio alone: 10 GB knock in **3.45–5.00 years**, full tier in **6.91–10.00 years**;
- with the ruled monthly events: knock in **1.07–1.38 years**, full tier in **2.14–2.76
  years**.

**None of those is decades.** I am not disputing the GO ruling — the machinery is built
either way, and the knock is a *designed pressure gauge* that is meant to fire so the owner
can act on a lever. But the owner should know the gauge fires in **roughly one to five
years**, and that the monthly event calendar is what pulls it from ~4 years to ~1 year.
Options:

- **(a) the numbers stand as computed** — the gauge firing in 1–5 years is the design
  working, and lever (c) or a second target is the intended response;
- **(b) the growth figure is peak-inclusive** — 11–13 MiB/day includes a 9.6 MB outlier, so
  steady-state growth is lower and the projections improve. I have not separated the two
  because the census period was not given, and guessing would be exactly the
  unverified-assumption failure the lane is told to avoid;
- **(c) re-derive after Sheet 1** — the end-to-end ratio will be worse than the raw zstd
  band, which pushes the other way.

I lean **(b) measured, then (a)** — the outlier is 9.15 MiB of a 76.96 MiB total, so it is
about 12% of the volume and cannot by itself turn 1–5 years into decades. But the honest
statement is that the projections are years, and the owner should have that number rather
than "decades".
