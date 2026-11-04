# Phase report 008 — GATE 1e re-verification: base MOVED, no schema drift, but verdict collides

**Date:** 2026-10-27
**Branch:** `arena/storage` @ `a02a844`
**Trigger:** the standing commitment in report 007 — *"every time the PR base moves,
the storage lane re-runs the §1 verification table and re-issues the §2 contract or
reports drift."* **The base moved. This is that re-verification.**

---

## DONE

### 1. The base moved — two Stream H commits landed

```
f915d8e396d3fed0b3c77af7b21b2031c09ede5b   <- canonical baseline (report 007 §2)
eae1d01b402dc2cef9d788956c0851ea1d38c14e   <- new base tip
  eae1d01 scene3b-REDO stream H: H.3 repro script + scene-7 run page + H.5 sizing (docs)
  8a72939 scene3b-REDO stream H: post-timeout route evidence + wire sampling + mic lifecycle (H.1 sensors/pins, H.2, H.4)
```

### 2. Re-verification table — re-run against the new base

| Check | Baseline `f915d8e` | New base `eae1d01` | Verdict |
|---|---|---|---|
| `journal_log.py` byte-identical | — | — | **IDENTICAL** — `git diff` empty |
| `split(" ", 6)` → 6 or 7 parts, `parts[6]` intact | verified | re-verified | **HOLDS** |
| `parts[4]`=peak, `parts[5]`=verdict | verified | re-verified | **HOLDS** |
| Detail absence = ABSENT, never `-` | verified | re-verified | **HOLDS** |
| `session_id` 12-hex / 32-hex / `-` | verified | re-verified | **HOLDS** |
| `session.close` emitted | `daemon.py:2317` | `daemon.py` (line shifted) | **HOLDS** |
| `transcription.landed` emitted | `transcribe.py:1390` | `transcribe.py` (line shifted) | **HOLDS** |
| `transcription.deferred` emitted | `transcribe.py:415/425/1378` | `transcribe.py` | **HOLDS** |
| `"audio kept at {path}"` phrasing | 4 sites | **4 sites, character-identical** | **HOLDS** |

**`audio kept at` sites, baseline → new base (line numbers shifted, text identical):**

| Baseline | New base | Text |
|---|---|---|
| `daemon.py:2327` | `daemon.py:2404` | `; audio kept at {(result or {}).get('audio_path')}` |
| `transcribe.py:418` | `transcribe.py:418` | `redo (job #{job_id}); audio kept at ` |
| `transcribe.py:1381` | `transcribe.py:1438` | `no final transcript returned — audio kept at ` |
| `transcribe.py:1394` | `transcribe.py:1451` | `; audio kept at {audio_path}` |

**No schema drift. No phrasing drift. The canonical contract in report 007 §2 stands
unchanged.**

*Correction to my own report 007 wording:* I wrote that `audio kept at` had gone "from
2 to 4 occurrences" between baseline and new base. That was my miscount — it is **4 on
both**. The correct statement is: 4 sites on the baseline, the same 4 sites on the new
base, character-identical, with only line numbers shifted. Corrected here rather than
left standing.

### 3. WHAT DID CHANGE — and it creates a trap the contract must now fence

The `+58/-1` in `transcribe.py` and `+79/-1` in `daemon.py` are **purely new, additive
`log_event` calls** for new Stream H sensors. None of them touch the WP7-relevant
events or the `audio kept at` phrasing:

```
capture.node_state      (new)
stream.closed           (new)
post_timeout_route      (new)
fallback.outcome        (new, x2 sites)
```

**The trap: two of the new events emit `verdict` values that collide with WP7's.**

| event (parts[2]) | verdict (parts[5]) | WP7-relevant? |
|---|---|---|
| `transcription.landed` | `landed` | **YES** |
| `fallback.outcome` **(NEW)** | `landed` / `empty` / `error` | no |
| `transcription.deferred` | `deferred` | **YES** |
| `post_timeout_route` **(NEW)** | `fallback` / `deferred` | no |

Proven by running `journal_log.py` on both shapes: `parts[5] == "landed"` matches
**both** `transcription.landed` and `fallback.outcome`; `parts[5] == "deferred"`
matches **both** `transcription.deferred` and `post_timeout_route`.

**Binding consequence, added to the canonical contract (report 007 §2.1):** the watcher
dispatches on the **event name** (`parts[2]`) and nothing else. A watcher keyed on
verdict would treat a fallback file-transcription leg as a WP7 cold-storage candidate —
a **silent misfire**, the exact failure class this whole design fences against. Verdict
may be read as corroborating state *after* the event has matched, never as the dispatch
key.

### 4. Canonical designation recorded

The design chat ruled report 007 §2 **CANONICAL** for the journal contract in both
lanes — superseding A.2-R, the original evidence-carrier contract, and all relay prose
including the chat's own prior statements. §2 now carries that designation in its
heading, and §2.1 carries the dispatch rule. Future consumers cite §2's reference
lines, never a summary.

---

## DEFECTS FOUND

**None in the schema.** `journal_log.py` is byte-identical; the four `audio kept at`
sites are character-identical.

**One latent defect, now fenced by contract rather than by luck:** the `verdict`
collision above. It is not a bug in Stream H's code — `fallback.outcome` legitimately
reports `landed` — but it is a **live hazard for any consumer that dispatches on
verdict**. Fenced by the new §2.1 dispatch rule.

**One self-correction:** my report 007 miscounted the `audio kept at` sites as "2 to
4". It is 4 on both bases. Corrected above.

---

## NEXT GATE

**GATE 1 — owner scenes. UNCHANGED. Still the real gate, still blocking all
machinery.** Scene Sheets 1 and 2 stand as issued. Nothing is built until the owner's
numbers arrive and the design chat rules go/no-go on the MEGA target and the
compression multiplier.

**GATE 1e — window OPEN.** The base moved but the schema did not, so the window stays
open on the same terms: the closing event (fixture authorship) is dated against the
canonical baseline `f915d8e`, and the contract as of that baseline is what §2 records.
The dispatch rule in §2.1 is part of that baseline and is **not** contingent on the
window.

**Standing commitment re-armed.** The next base movement triggers another full
re-run of the §1 table. This is the mechanism that keeps GATE 1e honest without
anyone having to remember to ask.

---

## OPEN QUESTIONS

**Q18 — none blocking.** The base movement was verified, produced no schema drift, and
produced one contract addition (the dispatch rule) that is now canonical.

**Note for Stream H, offered not demanded:** `post_timeout_route` emitting
`verdict="deferred"` and `fallback.outcome` emitting `verdict="landed"` are both
legitimate, but they now share verdict vocabulary with the WP7 events. If Stream H ever
wants to rename those verdicts to something non-colliding (`ok` / `empty` / `failed`,
`needs_fallback` / `punted`), the storage lane would welcome it — but it is **not**
required, because the dispatch rule already makes verdict irrelevant to correctness.
Recorded so the option is visible rather than lost.
