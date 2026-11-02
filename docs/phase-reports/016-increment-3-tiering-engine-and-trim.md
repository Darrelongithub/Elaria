# Phase Report 016 — Increment 3: tiering engine + trim (VERIFIED)

**Date:** 2026-11-02
**Branch:** `arena/storage`
**Base:** `arena/c2a7085d-elaria` (stacked PR #24)
**Head at report time:** `344c867` → this report's commit
**Increment:** 3 of 8 (tiering engine + trim)

---

## 1. DONE

1. **`src/assistant/tiering.py` written and verified** — the tiering engine and the trim
   mover. 237 lines, one new module, no shared-registration edits.
2. **`tests/test_wp7_tiering_trim.py` written and executed** — 24 tests, all passing.
3. **`tests/test_wp7_reconcile_crash_points.py` amended and executed** — 23 tests
   (was 20), all passing. No test was deleted.
4. **`src/assistant/backup.py` amended** (2 changes, both described in §5).
5. **Full suite measured, ruff clean.** See §2.

### The census permanent exclusions are honoured structurally

`PERMANENT_EXCLUSIONS` is checked **before** any window arithmetic, and `is_excluded()`
checks it before anything config can add:

```
voice-cache/   — 0 ms recall contract
test-assets/   — owner-ordered relocation site for event-spike.wav
```

`is_excluded(path, *, data_dir, extra)` takes `extra` (config additions) but has no
parameter that can remove a permanent exclusion. A test pins that: adding
`voice-cache` to `extra` changes nothing. Voice-cache and test-assets are excluded from
tiering and trim forever, per the standing ruling.

### `is_header_only_wav()` — the never-retry mark

`WAV_HEADER_BYTES = 44`. The 44-byte file is a never-retry mark under the
deferred-audio contract and **counts zero forever** — it is excluded from tiering, so it
never goes cold, is never trimmed, and never occupies a byte of the capacity model.

### The two triggers, and which one binds

`classify()` fires on **size** or **age**, and `TierDecision.binding` reports which:

- **size** — HOT residency exceeds `window_gb` (2 GiB). Oldest go cold until under cap.
  Urgent: this is the backstop.
- **age** — everything past `window_days` (14). The steady-state trigger.
- **none** — inside the window and under the cap. Correct no-op.

The census finding is pinned as a test, not a comment: at 13 MiB/day the **age trigger
binds** and the size cap is ~11× away, so `binding == "age"` and the cap is recorded as
the not-live backstop. `hot_window_*` governs HOT residency independent of compression —
no conflation, as agreed.

### `scan()` — the belt

`scan(root, ...)` walks the tree and degrades unreadable entries to `not a candidate`
rather than raising. A test pins that a file that vanishes or refuses `stat()` between
the listing and the read survives as "not a candidate" and never aborts the pass.

### `TrashMover` — own the trash dir, not `executor.trash()`

**Q22 is answered by this increment, and the answer is (b) — own the trash dir and the
grace clock.** Raised for the owner, with reasoning: `executor.trash()` is the
destructive-action gate for *user-initiated* deletes and writes `trash/manifest.jsonl`
for the executor's own ledger. WP7's trim is a *retention* move with a grace clock and
a purge that must be re-drivable — different semantics, and reusing the executor's path
would couple a background retention pass to a user-action gate. The
never-overwrite stamp+counter pattern is mirrored, not shared.

`TrashMover.move()` stamps `YYYYMMDD-HHMMSS-{name}`, increments a counter rather than
overwriting on collision, and creates the trash dir at **0700**. `TrashMover.purge()`
**re-raises `OSError`** — it never swallows a failure, because a swallowed purge is a
file the manifest thinks is gone.

### The drop-in seam fits

A test drives `plan_reconcile` → `reconcile` with a real `TrashMover` against synthetic
fixtures, and the full HOT → trash → grace → purge lifecycle runs end to end with the
real mover. No shims.

---

## 2. VERIFIED GATES (verbatim)

```
$ ./.venv/bin/python -m pytest -q
........................................................................ [ 87%]
........................................................................ [ 90%]
...s.................................................................... [ 94%]
........................................................................ [ 98%]
............................................................................... [100%]
1975 passed, 6 skipped in 168.62s (0:02:48)

$ ./.venv/bin/ruff check .
All checks passed!
```

**Baseline at `344c867`:** 1948 passed / 6 skipped / 0 errors, ruff clean.
**Now:** **1975 passed / 6 skipped / 0 errors, ruff clean.** Delta **+27**.

Delta accounting: 24 new tests in `test_wp7_tiering_trim.py`, and
`test_wp7_reconcile_crash_points.py` 20 → 23 (three new purge tests; the rewritten
`test_grace_elapsed_purges` is a rewrite, not an addition). 24 + 3 = 27. ✓

Both measured on CPython 3.11.2 in the sandbox `.venv`.

### Per-file

```
$ ./.venv/bin/python -m pytest tests/test_wp7_tiering_trim.py \
      tests/test_wp7_reconcile_crash_points.py tests/test_wp7_storage_manifest.py -q
..............................................................          [100%]
62 passed in 0.20s
```

---

## 3. DIFFSTAT

```
 src/assistant/backup.py                  |  93 +++++++++++++++++++------
 tests/test_wp7_reconcile_crash_points.py |  57 ++++++++++++++++++++++--
 2 files changed, 132 insertions(+), 18 deletions(-)

 src/assistant/tiering.py                  | 237 +++++++++++++++++++++++++++
 tests/test_wp7_tiering_trim.py            | 402 +++++++++++++++++++++++++++++++
 (untracked, new)
```

PR #24 totals after this commit: 26 files.

---

## 4. FIREWALL STATEMENT

```
$ git status --porcelain
 M src/assistant/backup.py
 M tests/test_wp7_reconcile_crash_points.py
?? src/assistant/tiering.py
?? tests/test_wp7_tiering_trim.py

$ git status --porcelain | grep -E "daemon\.py|transcribe\.py|live_client\.py|HANDOFF\.md|conftest\.py"
CLEAN - no forbidden file touched

$ git status --porcelain | grep -E "cli\.py|config\.py|ladder\.py|pyproject\.toml"
CLEAN - no registration point touched
```

**Zero edits to `daemon.py`, `transcribe.py`, `live_client.py`, `HANDOFF.md`,
`tests/conftest.py`. Zero edits to `cli.py`, `config.py`, `ladder.py`,
`pyproject.toml`.** Two new modules, two modified files — both of them mine from
increment 2. Increment 3 needed no registration point at all, which is the expected
shape: tiering is pure logic and the trim is injected at the `reconcile()` seam.

---

## 5. DEFECTS SURFACED

### D9 — the tiering engine would have crashed on its first candidate [FIXED]

`Candidate.from_path` built `mtime` with `datetime.fromtimestamp(stat.st_mtime)` —
**naive local time** — while `classify()` subtracts it from an **aware UTC** `now`.
The first call would have raised
`TypeError: can't subtract offset-naive and offset-aware datetimes`.

This would never have surfaced in review. It surfaced because the tests inject `NOW`
and the suite was run. Fixed by making `mtime` aware UTC, with a comment recording why.

### D10 — the purge targeted a path the file no longer occupied [FIXED, and it is the important one]

This is a **design bug, not a test bug**, and it is the same defect class as the one I
fixed for the no-mover case in increment 2's amendment — it had simply moved.

The manifest keys each artifact under its **HOT path**. After a trim the file is in
trash under a **stamped name**. So the purge, told to act on `action.artifact`, went
looking for a file that was no longer there. `TrashMover.purge()` returns `False` for a
missing file rather than raising, so nothing stopped it: the manifest recorded
`purged` **while the trashed file was still sitting on disk**.

The manifest would have claimed a purge that never happened — the exact defect
increment 2's amendment existed to prevent, reintroduced through the back door.

**Fix, three parts:**
1. `ReconcileAction` gains `target: str = ""` — the filesystem path to act on, distinct
   from `artifact`, the manifest key. Default empty, so existing callers are unaffected.
2. `reconcile()` records where the trim mover put the file, in the `trashed` record's
   detail as `trashed_as=<path>`.
3. `plan_reconcile()` recovers it with `_trashed_as()` and sets `target` on the purge
   action.

The purge now removes the file that is actually there. A test asserts the trash dir is
**empty** after the grace, not merely that the manifest says `purged`.

A secondary hardening fell out of this: if the mover returns `False` — the target was
already absent — the goal is met, so the state still advances, but a problem is
recorded rather than passed over in silence.

### D11 — plan and append used different clocks [FIXED]

`plan_reconcile(..., now=...)` took an injected clock, but `reconcile()` stamped the
records it wrote with the **real** `iso_now()`. A grace period would have been measured
against one clock and recorded against another, so a 14-day grace could silently become
13 or 15 depending on when the pass ran.

Fixed by threading `now` from `reconcile_all()` into `reconcile()` and into
`_record_for()`. The real clock is still the default when no clock is injected, so the
production path is unchanged.

### D12 — my own test expectation was backwards [TEST FIXED, engine was right]

`test_size_cap_binds_and_oldest_go_first` asserted `paths[:2]` were sent cold, but the
fixtures made `paths[3]` the oldest. The engine correctly sent the oldest first. My test
was wrong, not the code.

I also could not express the size trigger with real files at all: `window_gb` is
GB-denominated and the fixtures are kilobytes, so `hot_bytes > window_bytes` could never
fire. Rewritten to build `Candidate` objects directly with GB-scale sizes — the
engine's job is the decision, not the filesystem, and a 2 GB fixture is not something a
test should create.

---

## 6. OPEN QUESTIONS

- **Q22 — CLOSED by this increment: (b), own the trash dir and the grace clock.**
  Reasoning in §1. Surfaced here for the owner's record; the semantics genuinely differ
  and the decision is now on the books.
- **Q13 — still open.** Read the third `transcription.deferred` site at
  `transcribe.py:1448` on the current tip (`1378` on the stale base) before finalising
  watcher fixtures. That is **increment 4+** work; it has not been touched.
- **No new questions raised this increment.**

---

## 7. WHAT INCREMENT 3 DOES NOT CLAIM

- **No remote was contacted.** No MEGA traffic, no restic invocation, no credentials.
  The whole pass runs against synthetic fixtures and a `tmp_path` trash dir.
- **`[TESTED-ONLY]` on the tiering logic.** The engine's decisions are proven against
  synthetic sizes and an injected clock. Its decisions against the owner's real wavs are
  unproven until a hardware scene runs.
- **No compression is applied by this increment.** `hot_window_*` governs HOT residency
  independent of compression, as ruled. The 0.475 / 0.582 band stays in the capacity
  model, not in the trim.
- **`trim_grace_days` remains the only `INTERIM-PENDING-SHEETS` config value.** Untouched
  by this increment; it is an owner word or a WP5 event shape away from final.
- **No live-traffic gate movement.** Still stopped at Gate 1 for live traffic and merge.
  Only the build blocker has been lifted.

---

## 8. NEXT

**Increment 4 — remote abstraction + verifier.** `LocalPathBackend` fixture and
`RcloneBackend`, which retires the no-verifier posture by supplying the real remote
confirmation that `plan_reconcile` currently refuses to act without. Still no live MEGA
traffic in sandbox — the local backend is the fixture.

Then increments 5–8. No merge until the design chat rules the mainline gate passed.

---

## 9. EVIDENCE TAGS

| Claim | Tag |
|---|---|
| Tiering engine decisions (age / size / none, oldest-first) | `[TESTED-ONLY]` |
| Permanent exclusions honoured structurally | `[TESTED-ONLY]` |
| Header-only never-retry mark counts zero | `[TESTED-ONLY]` |
| `TrashMover` move / never-overwrite / 0700 / purge re-raise | `[TESTED-ONLY]` |
| Purge removes the file the manifest is about to call purged | `[TESTED-ONLY]` |
| Full HOT → trash → grace → purge lifecycle | `[TESTED-ONLY]` |
| Suite 1975 / 6 / 0, ruff clean | `[TESTED-ONLY]` |
| Engine against the owner's real wavs | `[UNVERIFIED]` |
| restic / rclone end-to-end over MEGA | `[UNVERIFIED]` — Sheet 1 still owes it |
| Any live MEGA traffic | not performed |

---

## 10. ADDENDUM — base movement detected before the push (drift check run)

The ancestry guard fired at push time: the PR base has moved from `b3db316` to
**`0320c11`** — **12 new mainline commits** (mini order M / scene7 work).

Under the re-timed verification doctrine a bare base movement triggers nothing, but the
**sole early trigger** is a named shape/phrasing change from mainline. `journal_log.py`
did change, so it was checked immediately:

```
$ git diff --stat b3db316..0320c11 -- src/assistant/journal_log.py
 src/assistant/journal_log.py | 58 ++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 58 insertions(+)
```

**The trigger did NOT fire.** The change is purely additive:

- `log_event()`'s signature is **unchanged** — the diff adds 58 lines *after* the
  function's `return line`, plus two imports (`hashlib`, `re`).
- The journal line format is **unchanged**: `ts SP level SP event SP session_id SP peak
  SP verdict [ SP detail ]`. `split(" ", 6)` still yields 6 or 7 parts.
- One **new event name** was added, `transcription.stump`, emitted through the same
  `log_event()`. Its verdicts are `noise_token` / `short_stump`. Per §2.1's dispatch rule
  (key on the event name, never on verdict) this simply adds a name to dispatch on. It
  does not collide with any WP7 consumer and does not alter the verdict-collision set.
- `session_id` handling is unchanged — still `str(session_id)` passed through, so the
  12-hex / 32-hex / `-` variance and the "never regex-gate" ruling still hold.

**The §2 canonical contract is unchanged. No re-dating, no re-measure against the new
base** — the bare-movement clause applies.

Also checked:
- `audio kept at` sites on `0320c11`: **4** (1 in `daemon.py`, 3 in `transcribe.py`) —
  identical to the recorded count. Drift 2 does not recur.
- `cost.iso_now` still present; `src/assistant/storage.py` present and unmodified across
  the movement — my increment 1–3 seams are untouched.

**Consequence for the measured numbers:** the 1975 / 6 / 0 result was measured on
`arena/storage` @ `344c867`, which carries the *old* base. It is a true measurement of
this branch. `arena/storage` is now 12 commits behind the new PR base; that is the
expected shape for a long-lived stacked PR and does not change any increment-3 result,
since increment 3 consumes no journal code at all.

No owner action is owed. Recorded per the standing commitment to re-run the drift check
on every base movement.
