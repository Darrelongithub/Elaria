# Phase Report 019 — State confirmation, stale-relay finding, and a third base movement

**Date:** 2026-11-02
**Branch:** `arena/storage`
**Base:** `arena/c2a7085d-elaria` (stacked PR #24)
**Head:** `cb8d636`
**Type:** state confirmation + drift verification. No increment work performed.

---

## 1. STATE CONFIRMATION — as demanded, before anything else

The relay asked me to confirm my committed state plainly and to disclose any incident.
Here it is, measured not recalled:

| | |
|---|---|
| **Head SHA** | **`cb8d636`** — "WP7 INCREMENT 5: assist backup CLI + sensors (report 018)" |
| **Branch** | `arena/storage`, tree **clean** |
| **Origin `arena/storage`** | **`cb8d636`** — local and origin identical, nothing unpushed |
| **Suite** | **2062 passed / 6 skipped / 0 errors** |
| **ruff** | **All checks passed!** |
| **PR #24** | OPEN, 36 files, **10,929 insertions, 0 deletions**, 19 commits |
| **PR #24 base** | `arena/c2a7085d-elaria` |
| **Frozen branch** | `arena/e7a1cca5-elaria` @ `b181712` — **identical on local and origin**, zero new commits |

Last three commits:

```
cb8d636 WP7 INCREMENT 5: assist backup CLI + sensors (report 018)
dcb33d4 WP7 INCREMENT 4: remote abstraction + verifier, retiring no-verifier (report 017)
d77eeee WP7 INCREMENT 3: tiering engine + trim (report 016)
```

**I am not at `d77eeee` with 1,975 / 6 / 0.** I am two increments past it. Nothing was
lost, no re-clone, no reset. The work is on the books and pushed.

---

## 2. THE FINDING: THIS RELAY IS STALE, AND I DID NOT RE-PROCESS IT

The relay's own books stop at **increment 3 (`d77eeee`)** and it issues a **GO-AHEAD for
increment 4**. Both increments 4 and 5 are already landed, verified and pushed:

- **Increment 4** — `dcb33d4`, report 017, suite 2017 / 6 / 0 (+42). Remote abstraction,
  `LocalPathBackend` + `RcloneBackend`, all three requirements enforced structurally.
- **Increment 5** — `cb8d636`, report 018, suite 2062 / 6 / 0 (+45). `assist backup` CLI +
  sensors.

**The relay's GO-AHEAD for increment 4 is therefore already discharged**, and I have not
re-done it. Re-running increment 4 against a branch that already contains it would have
produced duplicate code and a rewritten history — both of which this lane is forbidden
from doing.

### On the specific question: did a lane of mine re-emit report 011 as fresh output?

**No.** Report 011 remains a historical file at its original date. My three most recent
reports are 016 (increment 3), 017 (increment 4) and 018 (increment 5), each written
against work actually performed in that activation. **The duplicate is the relay, not my
output** — the relay channel delivered report 011's content to the design chat out of
order, and the design chat correctly caught it by checking its own books rather than
trusting the relay.

I record the symmetry the design chat named, because it is the actual lesson and it is
worth writing down in this lane's own log: *the design chat caught a stale report by
refusing to trust a relay and checking the real books — the same failure mode and the same
cure this lane used to catch a stale SHA in a notice, one level up.* The relay channel is
a named staleness surface on both sides, and I will treat every relay — including this
one — as a claim to verify rather than an instruction to obey.

**Adopted permanently, as ruled:** fetch the origin tip at activation instead of trusting
a relayed SHA; run the suite re-measure unconditionally even when a commit is obviously
inert. Both were exercised in this activation (§4, §5).

---

## 3. CROSS-LANE HEADS-UP — verified, and it bites nothing here

The relay reported that mainline changed one existing journal detail string:
`fallback.outcome`'s error text now carries a type-name prefix (e.g. `TimeoutError`) where
the message used to be empty. I verified this rather than accepting it:

```
$ git diff --stat 0320c11..fdcdb47 -- src/assistant/journal_log.py
 src/assistant/journal_log.py | 52 ++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 52 insertions(+)
$ git diff 0320c11..fdcdb47 -- src/assistant/journal_log.py | grep -c "^-[^-]"
0
```

- `error_text(exc)` is a **new** function in `journal_log.py` — additive, +52 / 0
  deletions. Its docstring records the rule: failure text is never empty, and a
  message-less exception still names its class.
- Its call sites are `asr.py` and `gemini_client.py`. `fallback.outcome` is emitted from
  `transcribe.py:1411`, `:1430`, `:1451`, and `transcribe.py` changed 38 insertions /
  11 deletions across that movement — which is where the detail string gained its prefix.

**The relay's claim is accurate.** Event names, field counts and the §2 contract are
unchanged, and my early trigger does not fire.

**Does it bite this lane? No.**

```
$ grep -rn "fallback.outcome" tests/test_wp7_*.py src/assistant/{tiering,remote,sensors,
      backup_cli,backup,storage}.py
NONE — no storage-lane file or test references fallback.outcome
$ grep -rn "error_text|TimeoutError" tests/test_wp7_*.py
(no output)
```

No storage-lane test asserts on that detail string, so there is nothing to update.
Mainline files remain frozen to this lane.

---

## 4. A THIRD BASE MOVEMENT — checked, early trigger did not fire

The relay did not mention this. The ancestry guard found it:

```
base tip now: bf5ef2b483b79a8cb16927f989a6e21ead033c72
NEW MOVEMENT: fdcdb47 -> bf5ef2b
bf5ef2b scene card: uv run --no-sync rule + two spotted command defects
```

Checked against the sole early trigger:

```
$ git diff --stat fdcdb47..bf5ef2b -- src/assistant/journal_log.py
(empty = byte-identical)
$ git diff --name-only fdcdb47..bf5ef2b | grep -E "journal|event|sensor|quota"
NONE
```

`bf5ef2b` is **docs-only** — one phase-report file, 20 insertions / 7 deletions, and its
own message says *"Suite unchanged (docs-only)"*. `journal_log.py` is byte-identical.

**The early trigger did not fire. Bare-movement clause applies.** No re-dating.

### §2 re-verified directly, not assumed

I re-derived the canonical reference shapes against the current base rather than trusting
that a docs-only commit could not have mattered:

```
OK  6 parts  event=session.close            peak=0.42  verdict=closed
OK  6 parts  event=transcription.landed     peak=-     verdict=landed
OK  6 parts  event=quota.counter            peak=-     verdict=-
OK  7 parts  event=transcription.rejected   peak=-     verdict=rejected
OK  7 parts  event=transcription.deferred   peak=-     verdict=deferred
§2 LINE FORMAT AND PARSE UNCHANGED AT bf5ef2b: True
```

Every shape matches the canonical contract in report 007 §2 exactly. `split(" ", 6)`
yields 6 or 7 parts on every shape; the dispatch key is `parts[2]`, never `parts[5]`.

---

## 5. SUITE RE-MEASURED UNCONDITIONALLY

Per the doctrine adopted in this very relay — *run the suite re-measure unconditionally
even when a commit is obviously inert; assuming inertness is exactly how a baseline goes
stale* — I re-ran the full suite even though `bf5ef2b` is docs-only and even though
nothing in my lane changed:

```
$ ./.venv/bin/python -m pytest -q
........................................................................ [ 97%]
............................................................................ [100%]
2062 passed, 6 skipped in 167.28s (0:02:47)
$ ./.venv/bin/ruff check .
All checks passed!
```

**2062 / 6 / 0, ruff clean** — identical to the increment-5 landing number. The baseline
is confirmed current, not assumed.

---

## 6. HARNESS BRANCH LINE — re-checked, still reporting not enforcing

The harness line again names `arena/e7a1cca5-elaria` as the working branch. Per the
ruling this is a **status note, not an instruction**, and the safety addendum requires me
to check whether it has begun *enforcing* — a forced checkout, or a push aimed at it:

```
HEAD                          -> arena/storage @ cb8d636
arena/e7a1cca5-elaria (local)  -> b181712
arena/e7a1cca5-elaria (origin) -> b181712
tree                          -> clean
```

**No enforcement.** HEAD is on `arena/storage`, the frozen branch is byte-identical on
local and origin with zero new commits, and the tree is clean. The safety addendum does
not trigger.

---

## 7. WHAT WAS NOT DONE, AND WHY

- **Increment 4 was not re-run.** It is already landed at `dcb33d4`. Re-running it would
  duplicate code and require rewriting shared history.
- **Increment 6 was not started.** The relay's GO-AHEAD covers increment 4 only, and it
  is discharged. Increment 6 has no ruling in this relay.
- **No mainline file was touched.** `transcribe.py` is read, not edited, and only to
  verify the heads-up.
- **Nothing was committed to `arena/e7a1cca5-elaria`.**

---

## 8. OPEN QUESTIONS

- **Q13 — still open, still post-fixture work.** `transcribe.py:1448` read permitted,
  editing not. Untouched.
- **No new questions.**

---

## 9. EVIDENCE TAGS

| Claim | Tag |
|---|---|
| Head `cb8d636`, tree clean, origin identical | `[TESTED-ONLY]` — `git rev-parse`, `git status` |
| Suite 2062 / 6 / 0, ruff clean | `[TESTED-ONLY]` — measured this activation |
| PR #24: 36 files / 10,929 insertions / 0 deletions | `[TESTED-ONLY]` — `gh pr view` |
| Frozen branch unchanged at `b181712` | `[TESTED-ONLY]` — local and origin compared |
| Relay is stale; increments 4–5 already landed | `[TESTED-ONLY]` — `git log` |
| `fallback.outcome` error-text change is real | `[TESTED-ONLY]` — whole-file diff, 52/0 |
| No storage test asserts on that detail | `[TESTED-ONLY]` — grep across the lane |
| Third base movement `bf5ef2b` is docs-only | `[TESTED-ONLY]` — diff --stat |
| §2 contract unchanged at `bf5ef2b` | `[TESTED-ONLY]` — reference shapes re-derived |
| Any live MEGA traffic | not performed |
