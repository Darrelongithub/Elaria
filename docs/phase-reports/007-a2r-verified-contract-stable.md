# Phase report 007 — A.2-R received and verified; contract stable; GATE 1e window still open

**Date:** 2026-10-27
**Branch:** `arena/storage` @ `909ba66` (base `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`)
**In response to:** Stream H addendum **A.2-R**, which *"supersedes A.2 entirely; A.1 stands unchanged."*

---

## DONE

### 1. A.2-R's own claims verified against the code, not accepted

A.2-R corrects A.2 by adopting the storage lane's findings. I verified every one of
its claims by running `journal_log.py` rather than trusting the relay:

| A.2-R claim | Verdict | Evidence |
|---|---|---|
| Seven fields `ts · level · event · session_id · peak · verdict · detail(optional)` | **VERIFIED** | `format_line()` f-string, 7 fields |
| `split(" ", 6)` → 6 parts (no detail) or 7 (detail present) | **VERIFIED** | all 7 test shapes matched, including the two REAL detail strings |
| `parts[6]` is the intact detail, spaces preserved | **VERIFIED** | `parts[6] == 'model_version=m; 412 chars committed; audio kept at /p/rec.wav'` → `True` |
| `parts[4]` is `peak`, `parts[5]` is `verdict` | **VERIFIED** | `parts[4]='0.42'`, `parts[5]='closed'` on a real `session.close` |
| Detail absence = ABSENT, never `-`; line ends at `verdict` | **VERIFIED** | 6-part lines on `session.close`, `quota.counter`, dash-session |
| Dash placeholders apply to `session_id`/`peak`/`verdict` only | **VERIFIED** | `_flat(detail, dash=False)` returns `""`, then `.rstrip()` |
| `session_id` 12-hex on PTT/dictation, 32-hex elsewhere, or `-` | **VERIFIED** | `daemon.py:1764` & `transcribe.py:1406` = `[:12]`; `daemon.py:2646` & `:2694` = full hex |
| Never regex-gate `^[0-9a-f]{12}$` | **AGREED** | would drop every Stream-F/G sensor line |
| `"audio kept at {path}"` phrasing | **CONFIRMED** | `transcribe.py:1390` and `:415` |
| PR #24 contains no watcher code | **CONFIRMED** | documents + one paste-safe script only |

**A.2-R is correct on every point.** No drift found in the correction itself. This is
the first relay in this exchange that survived verification unchanged, and it is
recorded as such rather than assumed.

### 2. THE VERIFIED BINDING CONTRACT (recorded for the integration round)

This is the contract the watcher's fixtures will be built against when the window
closes. Recorded here so it is never re-derived from a relay:

```
LINE   ::= ts SP level SP event SP session_id SP peak SP verdict [ SP detail ]
ts         RFC3339 with offset, e.g. 2026-10-27T07:04:44+00:00
level      one of info | warn | error
event      dotted name; falls back to the literal "event" if empty
session_id 12-hex (PTT/dictation) | 32-hex (daemon.py:2646/:2694) | "-"
peak       float | "-"
verdict    one plain word | "-"
detail     free text, may contain spaces, may be ABSENT
PARSE  ::= line.split(" ", 6)   ->  6 parts (no detail) | 7 parts (detail in parts[6])
```

Verified reference outputs, straight from `journal_log.py`:

```
6 parts  '2026-10-27T07:04:44+00:00 info session.close ptt-abc123 0.42 closed'
6 parts  '2026-10-27T07:04:44+00:00 info transcription.landed ptt-abc123 - landed'
6 parts  '2026-10-27T07:04:44+00:00 info quota.counter - - -'
7 parts  '2026-10-27T07:04:44+00:00 warn transcription.rejected ptt-3 - rejected /home/u/audio/rec.wav'
7 parts  '2026-10-27T07:04:44+00:00 warn transcription.deferred ptt-2 - deferred quota paused'
7 parts  '... info transcription.landed ptt-abc123 - landed model_version=gemini-x; 412 chars committed; audio kept at /home/u/audio/rec.wav'
```

### 3. GATE 1e — window confirmed OPEN, and the base has NOT moved

`git ls-remote origin refs/heads/arena/c2a7085d-elaria` → still
`f915d8e396d3fed0b3c77af7b21b2031c09ede5b`, and `git log f915d8e..FETCH_HEAD` is
**empty**. No Stream H or WP1 commit has landed on the PR base since my
verification.

**Therefore: no shape drift and no phrasing drift since the window opened. The
contract recorded in §2 above is current.** A.2-R's ask — *"Flag any shape/phrasing
change in your phase report regardless"* — is satisfied by this negative result: the
flag is "no change, contract stands as verified at `f915d8e`."

The window remains open and will close when the storage lane authors watcher
fixtures, which per the ruling happens **after the owner's scene numbers**. No
fixtures have been authored. Nothing in PR #24 consumes the contract yet.

### 4. A.1 — conftest defect: stood down, unchanged

`tests/conftest.py:108` remains Stream H's. The storage lane has not touched it and
will not. A.2-R's pointer — *"report 006 corrects 005's §3.3 — where they differ,
read 006"* — is accepted and recorded; report 006 is authoritative for that number.

**Baseline to hold, unchanged: 1913 passed / 6 skipped / 1 error (pre-existing,
CPython 3.11 only), ruff clean.**

---

## DEFECTS FOUND

**None new.** No defect in A.2-R, and no drift in the journal schema since the
window opened.

**One residual risk A.2-R does not address, carried forward from report 006
DRIFT 6 and still open:** `_flat()` normalises whitespace in *every* field, so a
kept-audio path containing a newline, tab, or repeated spaces is **not byte-faithful**
inside `detail`. A watcher that extracts the path from the journal and uses it as the
sole source of truth for addressing the artifact on disk can miss. This is not a
schema change, so A.2-R's "flag any shape/phrasing change" instruction does not
cover it — but it is a design consequence the integration round must honour.

Mitigation, already the design and restated so it is not "optimised" away: the
directory poll is the **belt**, the journal tail is the **suspenders**. The manifest
resolves artifacts from the filesystem scan and treats the journal as corroboration,
never as the authoritative path source.

---

## NEXT GATE

**GATE 1 — owner scenes. Unchanged, still the real gate, still blocking all
machinery.** Scene Sheets 1 and 2 stand as issued. The numbers come back before the
watcher's fixtures are authored, which is what closes the GATE 1e window.

**GATE 1e — journal-shape window: OPEN.** Stream H / WP1 may still change the line
shape or the `audio kept at {path}` phrasing at zero migration cost. This report is
the standing "no change detected" flag; it will be re-issued if the base moves.

**GATE 1d — build the WP7 machinery.** Still unblocked, still not started.

---

## OPEN QUESTIONS

**Q17 — none blocking.** A.2-R is adopted, verified, and consistent with reports 005
and 006. The only open item is the `_flat()` whitespace normalisation noted under
DEFECTS FOUND, which is recorded as a decision to honour rather than a question
needing a ruling before the owner's numbers land.

**Standing re-verification commitment.** Every time the PR base moves, the storage
lane re-runs the §1 verification table and re-issues the §2 contract or reports drift.
That is the mechanism that keeps GATE 1e honest without anyone having to remember to
ask.
