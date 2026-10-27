# Phase report 010 — GATE 1e re-dated to 018d109; drift clean; `capture.lifecycle` verified non-colliding

**Date:** 2026-10-27
**Branch:** `arena/storage` @ `69e8954`
**Trigger:** cross-lane ride-along naming `018d109` and adding a new additive schema line.

**Protocol applied (ruled):** the standing re-verification targets the **origin tip at
activation time**, never a fixed SHA from a notice. I fetched the real tip before
checking anything, and the notice's SHA happened to match — but that was confirmed, not
assumed. Cross-lane notices are conveniences, never gates.

---

## DONE

### 1. TIP CONFIRMED BY FETCH, NOT BY NOTICE

```
origin tip at activation: 018d109437bba4a779c3293aa801c9e17465ec14
notice claimed:           018d109
```

One commit since my last verified baseline `462fa98`:
`018d109 scene3b-REDO stream H: capture.lifecycle schema line — the H.4 numbers must
reach journalctl (scene-7 support)`.

### 2. THE NOTICE'S OWN CLAIM, CHECKED FIRST

> *"journal_log.py believed untouched"*

**CLAIM HOLDS.** `git diff 462fa98..018d109 -- src/assistant/journal_log.py` is empty,
and a direct `diff` of the two blobs is byte-identical. The notice hedged with
"believed"; the hedge was unnecessary, but the check was still run rather than skipped.

### 3. WHAT ACTUALLY CHANGED

Three files, `+25/-4`. Only one is in `src/`:

- **`src/assistant/transcribe.py` (+13)** — adds `capture.lifecycle` to the schema
  journal, aggregate-only: `node`, `first_frame_latency_ms`, `first_speech_frame_s`,
  `frames`, `bytes`. Verdict is `ok` or `no-frames`.
- `tests/test_stream_h_sensors.py` (+10/-1) — Stream H's own sensor tests.
- `HANDOFF.md` (±3) — Stream H's own doc.

**No journal machinery change. No phrasing change.**

### 4. THE FULL DRIFT TABLE

| Check | Result |
|---|---|
| `journal_log.py` `462fa98..018d109` | **byte-identical** |
| `audio kept at` sites | **4, character-identical, same line numbers** (transcribe.py 418/1451/1464, daemon.py 2405) |
| `session.close` | **emitted** (daemon.py:2395) |
| `transcription.landed` | **emitted** (transcribe.py:1460) |
| `transcription.deferred` | **emitted** (transcribe.py:415, :425, :1448) |
| Full §2 verification table vs 018d109's **actual** module | **ALL 12 CHECKS PASS** |

### 5. THE NEW EVENT, CHECKED FOR THE COLLISION TRAP

This is the check that matters. Every additive schema line is a chance for another
verdict collision, so I ran the new shape rather than reasoning about it:

| `capture.lifecycle` verdict | `ok` | `no-frames` |
|---|---|---|
| Collides with WP7 verdicts (`landed`/`deferred`/`closed`/`rejected`)? | **NO** | **NO** |
| Detail carries content or a filesystem path? | **NO** | **NO** |
| Detail shape | `node=…; first_frame_latency_ms=…; first_speech_frame_s=…; frames=… bytes=…` — 7 parts, detail free text | same |

`capture.lifecycle` is **inert to the watcher**: it carries no kept-audio path, and its
verdicts sit nowhere near the WP7 set. It also confirms the notice's "aggregate-only,
never content" claim — verified in the detail string, not accepted from prose.

The **pre-existing collision is still present** (`fallback.outcome` and
`transcription.landed` both emit `landed`), so the §2.1 dispatch rule remains
load-bearing and unchanged.

### 6. BASELINE RE-MEASURED (standing commitment, clause 2)

Measured myself in a throwaway worktree at `018d109` on CPython 3.11:

```
1925 passed, 6 skipped in 167.65s
ruff: All checks passed!
```

**Unchanged from `462fa98`.** The corrected baseline — 1925 passed / 6 skipped /
0 errors, ruff clean — holds at the new tip.

---

## RULING RECORDED

**Protocol refinement (ruled):** standing re-verification targets the **origin tip at
activation time**, never a fixed SHA from a notice; cross-lane notices are conveniences,
never gates. At the next activation (scene numbers arrival), diff the then-tip against
the last verified baseline before authoring fixtures.

**Discharged in full by §1–§6.** The last verified baseline is now `018d109`.

---

## DEFECTS FOUND

**None.** No schema drift, no phrasing drift, no new verdict collision, no content in
the new aggregate line, and the suite baseline is unchanged. This is the third
consecutive drift check to come back clean, which is itself worth stating plainly rather
than treating as a surprise.

---

## NEXT GATE

**GATE 1 — owner scenes. UNCHANGED. Still the real gate.** Scene Sheets 1 and 2 stand as
issued; the MEGA account/benchmark numbers and the aggregates gate all machinery.

**GATE 1e — window OPEN, re-dated to `018d109`, drift-free.** The next base movement
triggers the full table in §4 **and** a fresh suite measurement, both now mechanical.

**Standing commitment re-armed**, both clauses, unchanged: on every base movement, re-run
the drift check *and* re-measure the suite.

---

## OPEN QUESTIONS

**Q20 — none blocking.** The additive line is inert to this lane and was verified rather
than trusted.
