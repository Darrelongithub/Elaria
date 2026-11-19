# Phase report 015 — Q26 ruled and "decades" retracted; census window; INCREMENT 2 LANDED (reconcile + crash points)

**Date:** 2026-10-31
**Branch:** `arena/storage` @ `4a89c75`
**Trigger:** Q26 ruling + census window + formal retraction; increment 2 proceeds as scheduled.

---

## DONE

### 1. Q26 CLOSED (RULING 38) — and a wrong word formally retracted

**The honest statement is YEARS, and it is now the lane's canonical number:**

| Scenario | 10 GB knock | 20 GB full tier |
|---|---|---|
| Daily audio only | **3.45–5.00 yr** | **6.91–10.00 yr** |
| Daily audio **+ ruled monthly events** | **1.07–1.38 yr** | **2.14–2.76 yr** |

**The design chat's "decades" wording is FORMALLY RETRACTED** — a months-versus-years
conflation, **60 months read as 60 years**. Recorded beside the ruling so no future
activation inherits the word. Any later figure quoting "decades" for this lane is wrong by
construction and should be treated as a **corrupted relay, not a datum**.

**GO ruling stands unchanged.** The knock is a designed pressure gauge and its levers are
enumerated for the owner: **event frequency** (owner's number, Q24 doctrine),
**`trim_grace_days`** (the last unmeasured `[backup]` value), and **cold retention policy**
(lever (c)).

### 2. THE CENSUS WINDOW (RULING 39) — discharging "the period wasn't given"

Kept-wav filenames span **2026-10-25 → 2026-10-31, six days** — oldest
`20261025-181730-4d90bf`, newest `20261031-145603-94129e`.

| Quantity | Computed | Ruling's figure |
|---|---|---|
| Observed total rate | 76.96 MiB / 6 d = **12.83 MiB/day** | 11–13 MiB/day |
| Outlier (9,637,484 B) | 9.19 MiB / 6 d = **1.53 MiB/day** | ≈1.6 MiB/day |
| **Steady state** | **11.29 MiB/day** | ≈9.5–11.5 MiB/day |
| Outlier share of volume | **11.9%** | — |

**Caveat carried verbatim in force:** the span is observed from filenames in this census
only. Wavs older than 10-25 may have existed and been trimmed before the census, so the
window is a **lower bound on the observation period**, not a claim about history.

### 3. THE CAPACITY TABLE, SPLIT BY COLUMN — and what the split settles

| Scenario | Column A: total, outlier **included** (11–13 MiB/d) | Column B: **steady-state** (9.5–11.5 MiB/d) |
|---|---|---|
| Cold growth | 5.48–7.93 MB/day | 4.73–7.02 MB/day |
| 10 GB knock, daily only | 3.45–5.00 yr | **3.90–5.79 yr** |
| 20 GB full, daily only | 6.91–10.00 yr | **7.81–11.58 yr** |
| 10 GB knock, + monthly events | 1.07–1.38 yr | **1.11–1.43 yr** |
| 20 GB full, + monthly events | 2.14–2.76 yr | **2.22–2.87 yr** |

**What the split settles is the real answer to Q26:** separating the outlier moves the
projections by **+13%** and changes nothing. The outlier is 11.9% of volume — it was
**never** the explanation for a decades/years gap. The gap was the conflation, and the
conflation is retracted. Q26 option (b) was the right instinct and the right order, but its
effect is a 13% improvement, not an order of magnitude.

**Column A remains the conservative planning column**; Column B is recorded because the
ruling asked for the separation and because it is the honest steady-state figure.

### 4. INCREMENT 2 LANDED — reconcile-on-start + crash-point tests

`src/assistant/backup.py` (new) + 20 tests. **All three spec crash points pinned:**

1. **Killed between upload and flip** → reconcile re-verifies (local file must exist and
   hash to the recorded sha256; the remote must confirm) **then** flips. A verification
   failure defers the flip and records a problem — it never guesses.
2. **Killed between flip and trim** → reconcile plans the trim. **Idempotency is
   structural**: the state machine has no `trashed -> trashed` edge, so once an artifact is
   trashed no further trim is ever planned. A test runs reconcile twice and asserts the
   mover fired exactly once.
3. **Flip fsync'd before any trim** → `append()` fsyncs before returning, and `reconcile()`
   appends the flip *before* calling the trim mover. A test has the mover record what the
   manifest says at the moment it runs; it must see `flipped`, not `uploaded`.

**The refusals are the important half.** Five tests assert reconcile *declines*: local hash
drifted, remote does not confirm, **no verifier configured**, local artifact vanished,
trim mover absent. The no-verifier case is the posture increment 2 must hold before
increment 4 supplies a real remote — without one, an `uploaded` artifact is left exactly
where the crash left it rather than being flipped on trust.

**One design decision worth surfacing:** a single reconcile pass advances each artifact by
**at most one state**, so `uploaded → trashed` takes two passes, driven by `reconcile_all()`
looping to quiescence. That is deliberate, and it is the safer semantics — advancing
several states in one pass would mean a single crash could skip a verification step. With
one step per pass, a crash mid-reconcile leaves every artifact at most one step further on,
each step separately verified before the next is attempted. A test pins this explicitly.

**Privacy fence held:** `ReconcilePlan.summary()` is path-blind, and a test asserts no path
fragment appears in it.

---

## DEFECTS FOUND

**One real defect in my own append discipline, found and recorded rather than hidden.**

`docs/storage-handoff.md` is append-only with newest at bottom, but **reports 013 and 014
landed mid-file** (lines ~929 and ~1017) instead of at the bottom, sitting *before*
chronologically earlier entries. Root cause: I appended using a **text anchor**, and
`edit_file` replaces the **first** match. The anchor "Standing commitment re-armed (two
clauses, now doctrine)" appears twice in the file — once ending report 011 mid-file, once
later — so the first match won and the entry landed in the middle. Report 014 then anchored
on report 013's tail and inherited the same position.

**Nothing was deleted, moved or rewritten** — the append-only rule is intact and both
entries are complete and correct in content. Only their physical position is wrong.
Recorded as a dated defect entry with the true chronological order spelled out, so a reader
hitting the log cannot be misled about sequence. **Corrective habit from this activation
forward: append with a shell append (`cat >>`), never with a text anchor.** A text anchor
can match mid-file; a shell append cannot.

**Three ruff findings, all mine, all fixed:** unused `pytest` import, `timezone.utc` where
the repo prefers the `UTC` alias, and an unused assignment. Nothing structural.

---

## NEXT GATE

**Increment 3 — tiering engine + trim.** Now unblocked in a specific way: increment 2
supplied the `trim_mover` seam, so increment 3 implements the real mover (grace clock,
trash dir, idempotency already structural). It must honour the census's **permanent
exclusions** — voice-cache and test-assets are never tiered or trimmed, forever.

**Still gated, unchanged:** live MEGA traffic (Sheet 1 output + design go/no-go); merge
(gate v2-AMENDED); the additive-only firewall; the owner's real content.

---

## OPEN QUESTIONS

**Q27 — none blocking.** The one-pass-per-state design is recorded with its reasoning; if
the owner prefers a single advancing pass, that is a design-chat entry rather than a lane
change.
