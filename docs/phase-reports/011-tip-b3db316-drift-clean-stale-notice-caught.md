# Phase report 011 — GATE 1e re-dated to b3db316; the stale-notice catch; two-clause check clean

**Date:** 2026-10-27
**Branch:** `arena/storage` @ `bd4267c`
**Trigger:** design chat accepting report 009, adopting both flags as doctrine, and
restating the immediate test case: *"the base has moved again — mainline tip is 018d109
… verify, don't trust this relay."*

---

## DONE

### 1. THE TEST CASE FAILED ITS OWN TEST — THE NOTICE WAS STALE

The design chat's own notice named `018d109` as the current tip, and told me to verify
rather than trust it. I did. **The actual origin tip at this activation is
`b3db316914235caee40f4c650072c9e06fb0288c`** — one commit beyond what the notice said.

```
origin tip at activation (fetched): b3db316914235caee40f4c650072c9e06fb0288c
notice claimed:                     018d109
my last verified baseline:          018d109
```

This is not a criticism of Stream H. Their own `HANDOFF.md` record shows why: their
activation verified `origin tip = 018d109 = last verified baseline (empty diff)`, and
`b3db316` **is the commit that records that verification**. The notice I received was
accurate when written and had simply been overtaken by the very commit it described.

**But that is precisely the failure mode the doctrine exists to catch, and this is its
first real catch.** Had I accepted the notice's SHA, I would have re-dated GATE 1e to
`018d109` — already stale — and reported a clean check against a baseline that was no
longer the tip. Fetching the origin tip at activation time is not ceremony; it just paid
for itself on the first try.

### 2. WHAT MOVED

One commit since `018d109`: `b3db316 docs: cross-lane re-verification protocol ruling
(007 §2) + activation-time verification record`. **`HANDOFF.md` only, `+14/-0`.** No
`src/` change whatsoever — `git diff 018d109..b3db316 -- src/` is empty.

### 3. CLAUSE 1 — THE DRIFT CHECK

| Check | Result |
|---|---|
| `git diff 018d109..b3db316 -- src/assistant/journal_log.py` | **empty — untouched** |
| `git diff 018d109..b3db316 -- src/` | **empty — no source change at all** |
| `audio kept at` sites | **4, character-identical, same line numbers** (transcribe.py 418/1451/1464, daemon.py 2405) |
| `session.close` | **emitted** (daemon.py:2395) |
| `transcription.landed` | **emitted** (transcribe.py:1460) |
| `transcription.deferred` | **emitted** (transcribe.py:415, :425, :1448) |
| Full §2 verification table vs b3db316's **actual** module | **ALL 12 CHECKS PASS** |
| Pre-existing verdict collision | **still present** → §2.1 still load-bearing |

### 4. CLAUSE 2 — THE SUITE RE-MEASURE

Measured myself in a throwaway worktree at `b3db316` on CPython 3.11:

```
1925 passed, 6 skipped in 172.28s
ruff: All checks passed!
```

**Baseline holds: 1925 passed / 6 skipped / 0 errors, ruff clean.** Unchanged from
`018d109` and `462fa98`.

A docs-only commit could not have moved the suite, and it did not. I ran the measurement
anyway because the doctrine is unconditional — "every base movement requires the drift
check AND a suite re-measure at activation time" — and because A.1 taught that assuming
a change is inert is exactly how a baseline goes stale.

### 5. USEFUL FACT FROM STREAM H'S RECORD

`b3db316` records that `journal_log.py` was last touched by `30abf30` (stream G), and
that **`log_event` is generic — "event is the caller's naming", no allowlist**. That is
why `capture.lifecycle` needed no journal-side change, and it is a useful structural fact
for my lane: new schema events need no coordination with the journal machinery, so future
additive lines are inert by construction unless they collide on verdict.

---

## RULINGS RECORDED

1. **FLAG 1 ADOPTED AS DOCTRINE:** the standing commitment is two clauses — every base
   movement requires the drift check **and** a suite re-measure at activation time. A.1
   proved a baseline can move without the contract moving.
2. **FLAG 2 CONFIRMED:** the GATE 1e window re-dates and the full check re-runs on ANY
   further base movement before fixture authorship. **Immediate test case discharged in
   §1–§4.**
3. **NEW CANONICAL SUITE BASELINE (both lanes): 1,925 passed / 6 skipped / 0 errors,
   ruff clean** — my measurement supersedes the commit message and every prior report.
   The A.1 arc is recorded as the cross-lane doctrine's first full closed loop.
4. **Manifest path shape accepted; Q13 (`transcribe.py:1378`) confirmed as pre-fixture
   next-activation work, correctly flagged.**
5. **Posture unchanged: STOPPED AT GATE 1.** Sheets 1+2 numbers gate everything; PR #24
   stands as the durable record.

---

## DEFECTS FOUND

**None in the contract.** No schema drift, no phrasing drift, no new verdict collision,
baseline unchanged.

**One process finding, and it is the point of this report:** the design chat's own notice
was **stale at activation** — it named `018d109`, the tip was already `b3db316`. Caught
because the protocol requires fetching the origin tip rather than reading a SHA out of a
relay. Recorded so the next notice is treated the same way regardless of who sent it.

---

## NEXT GATE

**GATE 1 — owner scenes. UNCHANGED. Still the real gate.** Sheets 1 and 2 stand as issued;
the MEGA account/benchmark numbers and the aggregates gate all machinery.

**GATE 1e — window OPEN, re-dated to `b3db316914235caee40f4c650072c9e06fb0288c`,
drift-free.** The two-clause check re-runs on any further base movement before fixture
authorship.

**Standing commitment re-armed (two clauses, now doctrine):** on every base movement,
re-run the drift check **and** re-measure the suite, against the origin tip at activation
time.

---

## OPEN QUESTIONS

**Q21 — none blocking.** The stale notice is recorded as a process finding, not a defect.
