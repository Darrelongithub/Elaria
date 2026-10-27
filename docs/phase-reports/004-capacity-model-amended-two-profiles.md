# Phase report 004 — capacity model AMENDED: two usage profiles, compression as a multiplier

**Date:** 2026-10-27
**Amends:** `docs/phase-reports/000-environment-branch-t0-citations.md` §4
**Why:** the design chat ruled (2026-10-27) that the single-profile model in
report 000 was "correct doctrine and the wrong question shape", ordered two
profiles, ordered every runway number reported twice (pessimistic floor and
measured), and fixed the owner menu at four levers. Report 000 is not rewritten —
it is superseded here.

---

## 1. The arithmetic everything rests on

16 kHz mono 16-bit PCM:

```
16000 samples/s x 2 bytes = 32,000 B/s = 115.2 MB/hour
```

| Quantity | Value |
|---|---|
| 1 minute of audio | 1.92 MB |
| 1 hour of audio | 115.2 MB |
| One 8-hour event day | **921.6 MB** |
| 20 GB free tier ÷ 115.2 MB/h | **173.6 h ≈ 7.2 days** of continuous audio |
| Usable before the 2 GB knock floor | **18 GB** |

Dedup gain is **zero** for audio (unique streams) — that is a property of the
data, not an assumption to be revisited.

Compression is a **multiplier, not a footnote**. restic compresses at the pack
level (repository format v2, `--compression auto|fastest|better|max`), so a
measured ratio divides the remote footprint directly. Every number below is
therefore given three times:

- **floor** — compression gain 1.0× (report 000's pessimism, kept as the floor)
- **1.5×** and **2.0×** — the range zstd commonly reaches on 16-bit speech PCM,
  tagged **[UNVERIFIED-MODEL]**. This is exactly why Scene Sheet 2 *measures* the
  ratio on one real kept wav instead of assuming it. These two columns are a
  shape, not a promise.

---

## 2. PROFILE A — CURRENT usage (the owner's last 30 days)

Derived by Scene Sheet 2 from existing kept-wav sizes + mtimes — **aggregates
only, never content**. Runway in months on 20 GB:

| Kept audio per day | Raw GB/day | floor (1.0×) | 1.5× | 2.0× |
|---|---|---|---|---|
| 10 min | 0.0192 | 34.2 | 51.3 | 68.4 |
| 20 min | 0.0384 | 17.1 | 25.7 | 34.2 |
| **28.6 min** | **0.0548** | **12.0** | **18.0** | **24.0** |
| 45 min | 0.0864 | 7.6 | 11.4 | 15.2 |
| 60 min | 0.1152 | 5.7 | 8.6 | 11.4 |
| 120 min | 0.2304 | 2.9 | 4.3 | 5.7 |
| 8 h (one event) | 0.9216 | 0.7 | 1.1 | 1.4 |

The bold row is the 12-month bar: **28.6 minutes/day at the floor, 42.9 min/day
at 1.5×, 57.2 min/day at 2.0×.**

Formula, so the ruling can be recomputed the moment Scene Sheet 2 lands:

```
months = 20 / (GB_per_day x 30.44 / ratio)
```

---

## 3. PROFILE B — WP5-ERA usage (hours-long flight/event recordings)

This is the profile that matters. WP7 lands **before** WP5 on purpose, so the
runway WP7 must survive is WP5's, not the owner's current PTT habit.

### 3.1 The flood math, stated explicitly as the ruling demanded

One 8-hour event day at 115.2 MB/h:

```
8 x 115.2 MB = 921.6 MB
```

The 12-month budget at the floor is 54.8 MB/day × 365 = 20,002 MB ≈ 20 GB. So:

```
921.6 MB / 54.8 MB per day = 16.8 days
```

**One 8-hour flight recording consumes ~16.8 days of the entire 12-month budget
in a single afternoon.** That is the fact that makes the 29-min/day floor the
wrong question shape: it is not a rate the owner controls, it is a cliff a single
event walks off.

### 3.2 Runway by event frequency (8-hour events, 921.6 MB raw each)

| Event frequency | Events/yr | GB/yr | floor (1.0×) | 1.5× | 2.0× | 12-month bar at floor? |
|---|---|---|---|---|---|---|
| Daily | 365 | 336.4 | 0.7 mo | 1.1 mo | 1.4 mo | ✗ blown 17× |
| 2× per week | 104 | 95.8 | 2.5 mo | 3.7 mo | 5.0 mo | ✗ blown 4.8× |
| Weekly | 52 | 47.9 | 5.0 mo | 7.5 mo | 10.0 mo | ✗ blown 2.4× |
| **Fortnightly** | 26 | 23.96 | **10.0 mo** | **15.0 mo** | **20.1 mo** | ✗ blown 1.2× |
| Monthly | 12 | 11.06 | 21.7 mo | 32.6 mo | 43.5 mo | ✓ |
| Quarterly | 4 | 3.69 | 65.2 mo | 97.7 mo | 130.4 mo | ✓ |

**Reading the table honestly:**

- At the compression **floor**, even *monthly* 8-hour events are the only pattern
  that clears 12 months, and only just (21.7 months, with the 2 GB knock floor
  eating into that).
- At **2.0×** compression, fortnightly events clear 12 months (20.1 months) and
  weekly still does not (10.0 months).
- **Weekly 8-hour events never clear 12 months at any compression ratio in the
  1.5–2.0× band.** That is not a tuning problem; it is a capacity problem, and
  it is the single most important number in this report.
- If the owner's WP5 expectation is "I fly most weekends", the 20 GB free tier
  cannot hold a year of it, and no amount of restic tuning changes that. The
  honest answer is a lever from §5, chosen by the owner with these numbers in
  front of him.

---

## 4. What the hot window does and does not do

The hot window (resolved audio: **14 days or 2 GB, whichever first,
configurable**) controls how long a resolved artifact stays **HOT on the laptop**
before it becomes eligible for trim. It does **not** reduce what the remote must
hold: every kept artifact eventually goes cold and stays cold, because auto-delete
never exists and trim only moves to local trash with a 14-day grace window.

So the hot window is a *local disk* control, not a *remote capacity* control. It
appears nowhere in the runway math above, and any future proposal that claims it
does should be treated as a silent workaround.

---

## 5. THE OWNER MENU — four levers, presented with numbers, never chosen silently

The design chat fixed the menu at four. Levers (a)–(c) are recorded verbatim
from the ruling; lever (d) was **truncated mid-word in the ruling as received**
("(d) event/flight recordin…") and is recorded as incomplete rather than
guessed — see the open question at the end.

### (a) FLAC — cold-only, lossless

Lossless transcode of a resolved wav to FLAC before it goes cold. Allowed **only**
as a decode-back hash-verified, manifest-state-changed, cold-class-only,
never-silent conversion. FLAC on 16-bit speech PCM typically reaches ~50% of raw
(≈2.0×), which is the top of the band modelled above — and unlike zstd it is
*verified* on decode-back, so the hash-verified round trip is part of the
contract rather than a hope.

Status: **DOCUMENTED, NOT BUILT.** Builds only on an explicit owner go.

### (b) SECOND TARGET — an additional free-tier backend

Drive 15 GB / B2 10 GB / other. This is an **owner account decision**, not a
builder convenience — the owner opens the account, and the whole point of the
`rclone:` transport is that a second target is one more config line and zero code
change. Two 20 GB + 15 GB targets is 35 GB, which moves the fortnightly row from
10.0 to ~17.5 months at the floor.

Status: **DOCUMENTED, NOT BUILT.** Requires the owner to open the account.

### (c) RETENTION-CLASS PRUNE — an owner-visible recorded decision

Resolved PTT wavs whose transcripts have already landed, past an owner-set age,
removed via an **owner-visible recorded `restic forget` + `prune` decision with
numbers attached**. Auto-delete never exists; this lever exists only as a
decision the owner makes and the system records, never as a background policy.

Status: **DOCUMENTED, NOT BUILT.**

### (d) — INCOMPLETE IN THE RULING AS RECEIVED

The ruling's lever (d) begins "(d) event/flight recordin…" and was cut off. It is
**not** guessed at here. It is raised as an open question.

---

## 6. What this report does NOT do

It does not choose a lever. It does not build one. It does not soften the 12-month
bar. The design chat's own words govern: *"the spec says DOCUMENTED-NOT-BUILT
until the real aggregates fire the decision; pre-building either lever is the
silent workaround the capacity clause exists to prevent."*

Scene Sheet 2 supplies Profile A's real number and the measured compression
ratio. **When both land, this table is recomputed with the measured ratio
replacing the 1.5×/2.0× columns, and the owner chooses from the four levers with
the recomputed numbers in front of him.** Both outcomes are decisions.

---

# AMENDMENT, 2026-10-27 (design chat ruling, appended — the original text above is not rewritten)

## A.1 Lever (d) was a relay corruption; the menu is four levers, corrected verbatim

The fragment this report originally recorded as an incomplete "(d) event/flight
recordin…" was **lever (c)'s guard clause mis-fused onto (d)**. The corrected menu,
verbatim and complete:

- **(a) FLAC cold-only** — decode-back hash-verified, manifest-state-changed,
  never silent; build only on explicit owner go.
- **(b) Second target** — new free-tier account; owner account decision.
- **(c) Retention-class prune** — resolved PTT wavs with transcripts landed, past
  an owner-set age, as an owner-visible recorded restic forget/prune decision;
  **auto-delete never exists; event/flight recordings never pruned without
  explicit owner order.**
- **(d) Do nothing** — the `remote_free < 2 GB` knock is the designed pressure
  gauge; the owner picks among (a)/(b)/(c) when it fires, with real numbers in
  hand.

**A fifth idea was raised by me and rejected as a never-ruled non-lever:**
excluding event/flight recordings from the cold class entirely. It contradicts
audio-never-lost — flight recordings with no offsite copy are exactly the
single-copy risk class this whole design fences. If the measured numbers ever make
event-class isolation attractive, it goes to the owner as a decision with numbers,
not as a re-reading of a corrupted line.

## A.2 SIZING TARGET RULED: MONTHLY 8-hour events

> "DESIGN TARGET: MONTHLY 8-hour events (11.06 GB/yr raw). Rationale: monthly is
> the highest frequency that survives the zero-compression floor (21.7 months) —
> nothing unverified is load-bearing. The measured compression ratio from scene
> sheet 2 is HEADROOM, not a requirement."

**Combined-profile allowance (ruling's figure, independently verified, no drift):**

```
usable-before-knock = 20 GB − 2 GB gauge floor          = 18 GB
events at monthly   = 12 × 921.6 MB                     = 11.06 GB/yr
daily budget        = 18 − 11.06                        = 6.9 GB/yr
                    = 6.9 GB ÷ 365                      = 18.9 MB/day
                    = 18.9 MB ÷ 1.92 MB per kept-minute = 9.8 ≈ 10 kept-min/day
at 2× compression   = 19.6 ≈ 20 kept-min/day
```

The ruling's "~10 kept-min/day at floor, ~20 at 2×" checks out against my own
constants.

**Relief path if Scene Sheet 2's CURRENT profile measures above ~10 kept-min/day:
lever (c) only.** Auto-delete never exists; event/flight recordings never pruned
without explicit owner order.

**Standing rejections unchanged:** FLAC and second-target pre-build remain
rejected ("documented, not built") — monthly needs neither at the floor.
Event-class exclusion remains a rejected non-lever. If sheet-2 reality measures
fortnightly or worse, the menu re-opens **with numbers**, via the gauge or the
sheet — never before, never silently.

## A.3 What Scene Sheet 2 must therefore answer

Row 15 already asks for expected minutes/day of new kept audio. Against the ruled
target it now has a specific job: **compare the measured CURRENT profile to the
~10 kept-min/day allowance and the measured event frequency to monthly**, and
report the comparison. It is not an invitation to re-litigate the target.

---

## OPEN QUESTIONS

**Q10 — lever (d) is incomplete.** The ruling as received reads "(d) event/flight
recordin…" and stops. Options for what it was:
- (a) "event/flight recordings excluded from the cold class entirely" — i.e. WP5
  recordings stay local-only, so they never enter the 20 GB budget.
- (b) "event/flight recordings get their own target" — a variant of (b).
- (c) "event/flight recordings get a shorter hot window / earlier retention-class
  prune" — a variant of (c).
- (d) Something else — please complete the sentence.

**Q11 — WP5 event frequency.** Profile B's verdict swings on one number only the
owner knows. What frequency should the runway be sized for: weekly, fortnightly,
monthly, or quarterly 8-hour events? (Scene Sheet 2's row 15 asks this, but the
ruling should state the *design target* so the sizing is a decision rather than a
reaction.)
