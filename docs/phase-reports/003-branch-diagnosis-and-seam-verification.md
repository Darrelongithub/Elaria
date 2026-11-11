# Phase report 003 — branch diagnosis, seam verification, journal line contract

**Date:** 2026-10-27
**Trigger:** design-chat ruling on the branch question ordered an unconditional
diagnosis *before* any option could be chosen. This report is that diagnosis,
pasted first, plus the seam verification the second ruling required.

---

## PART 1 — THE ORDERED DIAGNOSIS (verbatim outputs, redacted)

### `git remote -v`

```
origin	https://github.com/Darrelongithub/Elaria.git (fetch)
origin	https://github.com/Darrelongithub/Elaria.git (push)
```

No token in either URL — plain HTTPS, no credentials embedded. Nothing to redact.

### `git config --get-all remote.origin.fetch`

```
+refs/heads/main:refs/remotes/origin/main
+refs/heads/arena/e7a1cca5-elaria*:refs/remotes/origin/arena/e7a1cca5-elaria*
```

**This is the root cause of defect D1.** The refspec is restricted to `main` plus
this session's own branch. That is why `git fetch origin --prune` — which I ran
first — reported only `main` and made `arena/c2a7085d-elaria` look absent. It was
never absent; it was simply outside the fetch refspec. My earlier conclusion that
"origin carries only main" was an artefact of the restricted refspec, and I am
correcting it here rather than letting it stand.

### `git ls-remote origin` (and the explicit URL — identical)

```
ed20344fc55806b8c83db756cd04984e86b89e5c	HEAD
eb203e46f2aec7e2630227a0cbcac4569fc461fe	refs/heads/arena/75729ceb-elaria
d19d43561caab09e5f039c02a986301f3b8dca42	refs/heads/arena/86223b1a-elaria
2ab680643bbd48838426670d0daa399573ebfd72	refs/heads/arena/8f088a3b-elaria
53c9c40c4600e095be55ec02cff23cdcc32dc95e	refs/heads/arena/933f020d-elaria
9e1549096ab7c360cb7a9183b499948b06843df6	refs/heads/arena/a1046a2f-elaria
8caae09b19c131c2c1ebddcf901bd7d5b3d0b8e2	refs/heads/arena/ab739a4c-elaria
abebb2b434ef8487e23a767a4b015c8e6e1689a9	refs/heads/arena/b9ff03ce-elaria
f915d8e396d3fed0b3c77af7b21b2031c09ede5b	refs/heads/arena/c2a7085d-elaria   <== THE BASE
185ff4a4041c5f66e8b936b06e24e1a6af5bbe4a	refs/heads/arena/dca11d17-elaria
6153b1235744c383208c6c958606b7c9d647b81c	refs/heads/arena/e57b6d8f-elaria
2320e1dfa119098d51a892b1d6d041d88417f35d	refs/heads/arena/e7a1cca5-elaria
e7c5e71828499bb9f4a2f7566f13db4aae7872a9	refs/heads/arena/ef0e665f-elaria
ed20344fc55806b8c83db756cd04984e86b89e5c	refs/heads/main
f915d8e396d3fed0b3c77af7b21b2031c09ede5b	refs/pull/23/head
642edf355ac6436c9cc02d7dd9cb78a269e70bd1	refs/pull/23/merge
```

`arena/c2a7085d-elaria` **is visible to `ls-remote`**, at
`f915d8e396d3fed0b3c77af7b21b2031c09ede5b`, and it is exactly PR #23's head.

### `gh pr list`

```
23  Phase 0 pin fix + WP0 EYES (wiring spec): registry, log schema, ladder,
    watchdog, unit hardening                        arena/c2a7085d-elaria  OPEN
22  GATE-FIX 2: console property audit…             arena/8f088a3b-elaria  MERGED
```

### `git fetch https://github.com/Darrelongithub/Elaria.git arena/c2a7085d-elaria`

```
From https://github.com/Darrelongithub/Elaria
 * branch            arena/c2a7085d-elaria -> FETCH_HEAD
```

**FETCH_HEAD = `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`** ← **the exact base SHA
to record, per the ruling.**

```
f915d8e scene3b-REDO stream G.7: phase report + HANDOFF (G.7 rulings, G.7.3 brief, scene-6 shape numbers)
32500b4 scene3b-REDO stream G.7: per-session transient pin + contained prune (G.7.4)
2ed6661 scene3b-REDO stream G.7: transcript delta accumulation + hygiene (G.7.1 fix)
319cb37 scene3b-REDO stream G.7: transcript-shape sensors before the delta fix (G.7.1 sensors)
3509818 scene3b-REDO stream G: phase report + HANDOFF (merge hold, GATE v2, Scene 6 run page)
```

### Ancestry check

`git merge-base --is-ancestor 0c08cb5 FETCH_HEAD` → **YES**.

The brief's `0c08cb5` is a genuine ancestor of the live tip, i.e. the ruling's
"the brief's 0c08cb5 is stale" is confirmed by git, not asserted. The live tip
`f915d8e` is four commits newer than the ruling's expected `3509818`, so Stream
G.7 has landed on top of Stream G as the ruling anticipated.

**Diagnosis verdict: STEP 2 of the ruling applies.** The PR branch is visible and
fetched; the base is `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`; PR #23 is open
and unmerged. No STOP condition from STEP 3 has triggered.

---

## PART 2 — SEAM VERIFICATION ON `f915d8e` (the second ruling's precondition)

The second ruling said the missing-foundations question was "premature — the
diagnosis was not reported" and that **if the fetch succeeded the question was
void**. It succeeded. The seams are therefore verified, not assumed.

### 2.1 `ladder.py` — PRESENT

`src/assistant/ladder.py` exists. Its own docstring:

> "Four chains — console, wake, voice, event — each a list of rungs."

So chain #5 "backup chain" is a genuinely additive fifth chain in an existing
`Ladder` class with an existing `Rung` / `ChainResult` / `_evaluate` model. This
is the concrete additive point the WP7 spec names.

### 2.2 The schema-event journal — PRESENT, and it is journald, not a file

`src/assistant/journal_log.py` (new in WP0, not present on `ed20344`). Its
docstring, verbatim:

> "Structured plain-language daemon log lines on stdout (§4.8, WP0 EYES).
>
> Schema, one line per event, space-separated:
>
>     ts level event session_id peak verdict detail
>
> - `ts`      ISO-8601 local time with offset.
> - `level`   info | warn | error.
> - `event`   dotted name from the §4.8 list (session.open, session.close,
>             silence.verdict, transcription.landed, transcription.deferred,
>             transcription.rejected, tts.cached, tts.synthesised, tts.failed,
>             quota.counter, watchdog.close, goaway.close — and the stream-F/G
>             sensors ws.histogram, audio.sent, audio.first_byte, latency.table,
>             final.wait, final.received, final.timeout).
> - `session_id`  the ptt/dictation/session id, or `-`.
> - `peak`    the measured input peak for the session, or `-`.
> - `verdict` one plain word (listening, silence, landed, deferred, rejected,
>             cached, synthesised, failed, counted, closed, …), or `-`.
> - `detail`  the rest of the line, plain words — the recording path on any
>             failure (prime directive: audio is never lost).
>
> Plain words on stdout — journald (StandardOutput=journal) captures them, so
> the assistant journal becomes a real sensor instead of an empty file. These
> lines are the live window only; the durable record is the store's journal
> (persona events, llm_calls, transcripts)."

**This closes the question the ruling flagged as "CONFIRMED IN THE INTEGRATION
ROUND, not guessed."** It is confirmed now, from the code:

- The tail mechanism is **journald**, via `journalctl --user -u assistant` on the
  unit the daemon runs under. It is **not** a file journal. There is no append-only
  file to `tail`; the append-only record is the systemd journal itself.
- The WP7 watcher must therefore read `journalctl --user -u assistant --output
  cat` (or `-o json`) incrementally from a **persisted cursor** — journald's own
  `--cursor` / `--after-cursor`, which is the journal-native equivalent of the
  "persisted offset, never re-read whole" rule the ruling already imposed.
- The WP7 brief's phrase "tail the existing append-only schema-event journal
  READ-ONLY" is therefore *satisfied literally*: journald is append-only, and
  `journalctl` is a read. Nothing is written, no daemon code changes, and the
  trigger ruling's "must NOT touch the daemon" holds exactly.

### 2.3 The three WP7 line names — ALL PRESENT

| Line name the WP7 brief requires | Status on `f915d8e` | Emitted from |
|---|---|---|
| `session.close` | PRESENT | `daemon.py:2317` |
| `transcription.landed` | PRESENT | `transcribe.py:1390` |
| `transcription.deferred` | PRESENT | `transcribe.py:415`, `:425`, `:1378` |

Plus, already in the schema and useful to WP7: `transcription.rejected`,
`watchdog.close`, `goaway.close`, `audio.sent`, `audio.first_byte`,
`latency.table`, `ws.histogram`, `final.wait`, `final.received`,
`final.timeout`, `quota.counter`.

### 2.4 Trash/manifest-era machinery — PRESENT

`executor.py` exists with `trash()` / `_trash_gated()` and the
`trash/manifest.jsonl` append. The grace-then-purge policy is additive there —
and `executor.py` is **not** on the forbidden list (`daemon.py`,
`transcribe.py`, `live_client.py` are).

### 2.5 Test surface

98 test files under `tests/` on `f915d8e`, vs 87 on `ed20344`. The ruling's
"1,901-test suite" is on the real base; the 1780 I measured on `ed20344` is the
stale number, and defect D3 from report 000 is now explained rather than merely
recorded.

---

## DEFECTS FOUND

**D1 — CORRECTED.** My report-000 claim that "origin carries only `main`" was
wrong. The restricted fetch refspec hid every other branch. The corrected fact:
`arena/c2a7085d-elaria` exists at `f915d8e396d3fed0b3c77af7b21b2031c09ede5b`
and is PR #23's open head. **The WP7 brief's base is real and reachable; only my
method of looking for it was wrong.**

**D6 — new.** `remote.origin.fetch` in this checkout is refspec-restricted to
`main` + the session branch. Any future `git fetch origin --prune` will keep
hiding the mainline PR branches. Every fetch of mainline work must use the
explicit-URL form
`git fetch https://github.com/Darrelongithub/Elaria.git <branch>`, or the
refspec must be widened by the owner. **Widening it is an owner decision, not a
builder convenience**, so the explicit-URL form is used and the restriction is
documented here.

**D2 — RESOLVED.** The "missing mainline foundations" defect from report 000 was
an artefact of D1: `ladder.py`, `journal_log.py`, the schema events, the trash
manifest and the 1,901-test suite are all present on the real base. WP7 does not
need a self-contained fallback. The design chat's contingency (amended option 1)
is therefore **not invoked**, and is recorded here only so the record shows it was
available and correctly declined.

---

## NEXT GATE

**GATE 1a — branch mechanics (BLOCKED on a ruling, see OPEN QUESTIONS).** The
design chat's ruling is to cut `arena/storage` from `f915d8e`, push it as a new
branch, and open the PR with base `arena/c2a7085d-elaria` (stacked; retarget to
`main` after PR #23 merges).

That instruction collides with the Arena harness constraint that governs this
sandbox: the session is pinned to `arena/e7a1cca5-elaria`, which must not be
switched away from, and no other branch may be created or pushed to. I am not
resolving that collision unilaterally in either direction — see OPEN QUESTIONS.

**GATE 1b — owner scenes (unchanged, still the real gate).** Scene Sheet 1
(account + benchmark) and Scene Sheet 2 (aggregates) are already issued and
unchanged by this report. The numbers still come back before the machinery gets
built.

---

## OPEN QUESTIONS

**Q8 — branch mechanics, needs a ruling because two instructions collide.**

- The design chat ruled: cut `arena/storage` from `f915d8e`, push it as a new
  branch, PR base `arena/c2a7085d-elaria`, never touch or force-push
  `arena/e7a1cca5-elaria`.
- The Arena harness requires: all work on `arena/e7a1cca5-elaria`, no other
  branch created or pushed, because work elsewhere is not attributed to this
  session.

Options:
- (a) Follow the design chat literally: create and push `arena/storage`. Cost —
  the harness may not attribute the WP7 work to this session; the ruling already
  anticipated this ("attribution lives in the PR and commits; note the harness
  session branch in the PR description").
- (b) Follow the harness: build on `arena/e7a1cca5-elaria`. Cost — the base is
  `ed20344`, which predates PR #23, so the WP7 PR cannot implement its own spec
  and could never merge cleanly. This is the "stale-base PR is wasted days"
  outcome the ruling rejected.
- (c) Hybrid: create `arena/storage` at `f915d8e` and push it as the PR branch
  (the ruling's instruction), **and** keep `arena/e7a1cca5-elaria` at its current
  commit `2320e1d` untouched, so the session branch retains the pre-flight work
  already pushed to it. Cost — the WP7 machinery commits exist only on
  `arena/storage`; the harness sees the pre-flight docs and the working tree but
  not the machinery commits.

**Q9 — journal tail cursor.** The watcher reads journald. Journald's native
incremental read is `--after-cursor=<saved cursor>`, persisted in WP7's own state
file (not in the repo). Confirm:
- (a) `journalctl --user -u assistant --after-cursor=<cursor> --output cat`, with
  the cursor persisted by WP7 and never written into the repo.
- (b) `journalctl --user -u assistant --since=<persisted ISO ts>` — simpler, but
  re-reads a window and can double-fire on clock skew.
