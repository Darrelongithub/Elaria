# Phase Report 018 — Increment 5: `assist backup` CLI + sensors (VERIFIED)

**Date:** 2026-11-02
**Branch:** `arena/storage`
**Base:** `arena/c2a7085d-elaria` (stacked PR #24)
**Head at report time:** `dcb33d4` → this report's commit
**Increment:** 5 of 8 (`assist backup` CLI + sensors)

---

## 1. DONE

1. **`src/assistant/sensors.py` written and verified** — the six journal events and the
   storage gauge.
2. **`src/assistant/backup_cli.py` written and verified** — the `assist backup` command
   surface: `status`, `fetch`, `run`, `check`.
3. **`src/assistant/cli.py` amended — the first registration-point edit in this lane.**
   Additive only: **23 lines added, 0 removed.**
4. **`tests/test_bug7_cli_smoke.py` amended** — the Bug 7 smoke table extended. Additive
   only: **8 lines added, 0 removed.** See §5 D17 for why this was necessary.
5. **`tests/test_wp7_backup_cli_sensors.py` written and executed** — 45 tests.
6. **Full suite measured, ruff clean.** See §2.

### The sensors conform to the canonical §2 contract

Six events, all emitted through `journal_log.log_event()`:

| event | level | verdict |
|---|---|---|
| `backup.started` | info | `started` |
| `backup.done` | info | `done` |
| `backup.failed` | error | `failed` |
| `backup.verify` | info / warn | `confirmed` / `unconfirmed` |
| `backup.check` | info / error | `passed` / `failed` |
| `storage.gauge` | info / warn | `ok` / `below_floor` |

Every line satisfies the canonical contract, and a test proves it rather than asserting it:

```
LINE   ::= ts SP level SP event SP session_id SP peak SP verdict [ SP detail ]
PARSE  ::= line.split(" ", 6)   ->  6 parts (no detail) | 7 parts (detail in parts[6])
```

- `session_id` is **`-`** on every sensor. A backup run is not a session, and using a real
  session id would make a backup event look like a transcription event to any consumer
  dispatching on the event name.
- `peak` is **`-`** on every sensor. It is meaningless for a backup event.
- Dispatch keys on the event name (`parts[2]`), never the verdict — §2.1.

`backup.verify` carries `backend=` and `method=` straight from the `Verification` that
produced the answer, so **provenance reaches the journal**: a fixture confirmation reads
`backend=local-path-fixture; method=hash` and a real one `backend=rclone:mega-elaria;
method=presence`. Requirement 3 from increment 4, carried through to the sensor surface.

### The gauge, and the capacity floor

`StorageGauge` carries `hot_bytes`/`cold_bytes`, counts, `remote_free_bytes` and
`floor_bytes`. The floor is **10 GB consumed, expressed as `remote_free`** so it stays
equivalent on a 20 GB tier.

**An unread remote is `unknown`, not zero.** `remote_free_known` is False and
`below_floor()` is False when the figure was never read — reporting unknown as zero would
suppress the knock the design asked for, and reporting unknown as below-the-floor would
raise one it never asked for. Both are refused.

### The CLI surface

```
assist backup status              manifest summary + storage gauge (path-blind)
assist backup fetch <artifact>    cold read path: manifest lookup, restore, hash-verify
assist backup run [--dry-run]     one pass: tier, plan, reconcile
assist backup check [artifact] [--kind monthly|quarterly]
                                  integrity drill: restore a cold artifact to tmp, hash-verify
```

Every edge is injected — manifest, verifier, movers, restorer, clock — so the whole
surface runs against synthetic fixtures with no restic, no rclone and no MEGA. The command
logic lives in `backup_cli.py`; the `cli.py` edit is a subparser block plus one dispatch
line and nothing else.

### The cold read path refuses rather than guesses

- An artifact the manifest never saw → **exit 2**, `no manifest record for that artifact`.
- An artifact that is not cold (`local`/`uploaded`) → **exit 2**, `that artifact is
  uploaded, not cold; nothing to restore`.
- No restorer configured → **exit 2**.
- A restore that cannot happen → **exit 1** and `backup.failed`.
- A restore whose hash does not match the manifest → **exit 1** and `backup.verify
  confirmed=no`, with `refusing to call this a restore` on the terminal. **A restore that
  does not hash-verify is not a restore.**

`run` refuses without a verifier — increment 2's posture, still standing at the CLI layer.
`run --dry-run` reports the plan and changes nothing; a test asserts the manifest summary
is byte-identical before and after.

---

## 2. VERIFIED GATES (verbatim)

```
$ ./.venv/bin/python -m pytest -q
........................................................................ [ 97%]
............................................................................ [100%]
2062 passed, 6 skipped in 167.28s (0:02:47)

$ ./.venv/bin/ruff check .
All checks passed!
```

**Baseline at `dcb33d4`:** 2017 passed / 6 skipped / 0 errors, ruff clean.
**Now:** **2062 passed / 6 skipped / 0 errors, ruff clean.** Delta **+45**.

Delta accounting: `test_wp7_backup_cli_sensors.py` is an entirely new file, 45 tests,
collected count confirmed. No `parametrize` in the file, so defs = collected. The smoke
table gained 4 *entries*, which are not new tests — they extend two existing tests.
45 + 0 = **45**. ✓

Both measured on CPython 3.11.2 in the sandbox `.venv`.

---

## 3. DIFFSTAT

```
 src/assistant/cli.py                 |  23 +++++++++++++++++++  (additive only)
 tests/test_bug7_cli_smoke.py         |   8 ++++++++             (additive only)

 src/assistant/sensors.py             | 300 +++++++++++++++++++++++++++++++
 src/assistant/backup_cli.py          | 400 +++++++++++++++++++++++++++++++
 tests/test_wp7_backup_cli_sensors.py | 560 ++++++++++++++++++++++++++++++++
 (untracked, new)
```

PR #24 totals after this commit: 34 files.

---

## 4. FIREWALL STATEMENT

```
$ git status --porcelain
 M src/assistant/cli.py
 M tests/test_bug7_cli_smoke.py
?? src/assistant/backup_cli.py
?? src/assistant/sensors.py
?? tests/test_wp7_backup_cli_sensors.py

$ git diff --numstat
 src/assistant/cli.py            |  23    0
 tests/test_bug7_cli_smoke.py    |   8    0
$ git diff --numstat | awk '{r+=$2} END {print r" removed"}'
0 removed
```

**Zero edits to `daemon.py`, `transcribe.py`, `live_client.py`, `HANDOFF.md`,
`tests/conftest.py`. Zero edits to `config.py`, `ladder.py`, `pyproject.toml`.**

Two registration-point-adjacent files were touched, both **purely additive**:

- **`src/assistant/cli.py`** — 23 added, 0 removed. A `backup` subparser block and one
  dispatch line. No existing line was modified.
- **`tests/test_bug7_cli_smoke.py`** — 8 added, 0 removed. See D17.

**The whole increment removed 0 lines.** This is the first increment to touch a shared
registration point, and it did so without modifying anything that already existed.

---

## 5. DEFECTS SURFACED

### D17 — the Bug 7 smoke table refused my new subcommands [FIXED, and it is the interesting one]

`tests/test_bug7_cli_smoke.py::test_every_parser_leaf_has_a_smoke_invocation` failed:

```
subcommand(s) with no smoke entry in tests/test_bug7_cli_smoke.py::_smoke_table:
backup status, backup fetch, backup run, backup check
```

This is a **mainline test enforcing a mainline discipline**, and it did exactly its job:
the table rots loudly when a subcommand is added without a smoke invocation. The test's own
docstring says so — *"a new subcommand without a smoke argv fails here — the table rots
loudly, which is the whole point of the Bug 7 exercise."*

**This is the designed extension point, and extending it is what a mainline contributor
adding a subcommand is supposed to do.** The file is not on the lane's forbidden list, and
the edit is purely additive. Recorded prominently because it is the first mainline test
file this lane has touched.

Two judgement calls in the entries themselves:

- **`fetch` is given a wav that is deliberately not in the manifest.** The smoke assertion
  is that the entry point is *alive and answers*, and an honest exit-2 refusal is an
  answer. Inventing a manifest record to make it return 0 would have been a fixture built
  to flatter the test.
- **`run` is dry-run only.** A smoke invocation must change nothing. `assist backup run`
  without `--dry-run` would plan and reconcile against the real config.

All four entries were verified to actually run before being added: `0`, `2`, `0`, `2`.

### D18 — the privacy fence was caller discipline, not structure [FIXED]

`backup_started(reason=...)` and `backup_failed(reason=...)` passed the caller's string
straight through to `log_event()`. A caller doing `backup_failed(reason=str(exc))` would
hand us a `FileNotFoundError` whose message is an absolute path, and **the path would have
reached the journal**.

A test proved it:

```
AssertionError: a path reached a sensor:
2026-11-02T09:48:44+00:00 info backup.started - - started
reason=/home/owner/.local/share/assistant/audio/20261031-abcdef.wav
```

This is the same defect class as D10 from increment 4 — the fence held only because
callers were careful, and a fence that depends on caller discipline is not a fence.

Fixed with `scrub()`, applied inside `_emit()` so **every** sensor line is scrubbed on the
way out regardless of which emitter or which caller produced it. Anything path-like becomes
`<path>`. Over-redaction is accepted: a phrase like `read/write` collapses to
`read<path>write`, which is a small price for a fence that holds when a caller is careless.

### D19 — `scan()` was called twice, and the second call classified a decision [FIXED]

`_run()` called `classify(scan(...))`. `scan()` already walks the tree **and** classifies —
it is the belt, and the directory poll is truth. Passing its `TierDecision` into
`classify()` raised `TypeError: 'TierDecision' object is not iterable`.

Fixed by calling `scan()` once with the window parameters. Also removed a reference to
`decision.problems`, a field `TierDecision` does not have.

### D20 — `_check()` answered the wrong question when given a named artifact [FIXED]

With no cold artifacts, `_check()` returned `nothing cold to drill` **before** looking at
the artifact the caller named. A caller who named an artifact deserves an answer about
*that* artifact, not a summary of the whole set.

Restructured: a named artifact is validated first, and `nothing cold to drill` is only
reached when nothing was named and nothing is cold.

### D21 — three of my own test fixtures and expectations were wrong [TESTS FIXED]

- **An 18-byte payload is a header-only never-retry mark.** My `_wav()` stub was
  18 bytes, under `WAV_HEADER_BYTES = 44`, so `scan()` **correctly** excluded it as a
  never-retry mark — and every test that needed `send_cold` to be non-empty silently
  asserted nothing. Fixed with an 82-byte payload and a comment recording why. This is the
  third time a fixture has been quietly wrong in a way that made a test assert nothing.
- **A fresh fixture is inside the window.** Two tests needed something to go cold; the
  artifact had just been written and was correctly HOT. Fixed with an `_age()` helper.
- **`assist queue` legitimately requires a sub-action.** My shadowing test included it;
  mainline's `queue` has `required=True` subparsers, so a bare `assist queue` has always
  been a usage error. Excluded it with a comment, and the test now covers six commands that
  do parse.

---

## 6. OPEN QUESTIONS

- **Q13 — still open, still increment-4-plus work.** `transcribe.py:1448` read is
  permitted, editing is not. Untouched by this increment.
- **D17 raises one thing for the owner's awareness, not a question:** the Bug 7 smoke
  table is a mainline test file this lane has now extended. It is the designed extension
  point and the edit is additive, but it is the first time this lane has touched a mainline
  test file, and it is recorded here rather than buried.

---

## 7. WHAT INCREMENT 5 DOES NOT CLAIM

- **No live MEGA traffic, no restic invocation, no rclone invocation.** Every command ran
  against fixtures. `assist backup run --dry-run` was invoked once against the real config
  during smoke verification and changed nothing.
- **`[TESTED-ONLY]` throughout.** The CLI surface, the sensors and the refusals are proven.
  Against a real remote, `[UNVERIFIED]`.
- **`restic check` and `--read-data-subset` are not implemented.** `backup check` is the
  *shape* of the drill — restore a cold artifact to tmp and hash-verify it. The restic
  `check` rung and the quarterly `--read-data-subset` ≤5%/≤500 MB rung are increment 8.
- **The nightly timer and the post-close hook are not built.** Increment 7.
- **The ladder chain #5 rung is not built.** Increment 6.
- **No credentials anywhere.**
- **No live-traffic gate movement.** Still stopped at Gate 1 for live traffic and merge.

---

## 8. NEXT

**Increment 6 — ladder chain #5 "backup chain"**, additive, per the WP5 monthly trigger
shape. Then increment 7 (post-close hook + nightly timer) and increment 8 (monthly
restore-drill scaffolding with `restic check` and the quarterly `--read-data-subset`).

No merge until the design chat rules the mainline gate passed.

---

## 9. BASE MOVEMENT — no new movement this activation

The ancestry guard fired at push time, but on the **standing** condition rather than a new
one: the PR base is still `fdcdb47`, unchanged since report 017. My branch was cut when
the base was `b3db316`, and the base has advanced twice since (`0320c11`, then `fdcdb47`),
so the base tip is not an ancestor of my branch and will not be until the lane rebases —
which it does not do, by ruling.

**No new movement, therefore no new drift check, therefore no re-dating and no
re-measure.** The §2 contract was verified unchanged at `fdcdb47` in report 017 §10 and
nothing has moved since.

---

## 10. EVIDENCE TAGS

| Claim | Tag |
|---|---|
| Every sensor line satisfies the §2 contract | `[TESTED-ONLY]` |
| No sensor detail carries a path (scrubbed structurally) | `[TESTED-ONLY]` |
| Provenance reaches the journal via `backup.verify` | `[TESTED-ONLY]` |
| An unread remote is `unknown`, not zero | `[TESTED-ONLY]` |
| Capacity floor 10 GB consumed, expressed as `remote_free` | `[TESTED-ONLY]` |
| The cold read path's five refusals | `[TESTED-ONLY]` |
| A restore that does not hash-verify is refused | `[TESTED-ONLY]` |
| `run` refuses without a verifier | `[TESTED-ONLY]` |
| `run --dry-run` changes nothing | `[TESTED-ONLY]` |
| CLI registration is additive (23/0, 8/0, 0 removed total) | `[TESTED-ONLY]` |
| Suite 2062 / 6 / 0, ruff clean | `[TESTED-ONLY]` |
| Against a real remote / restic / rclone | `[UNVERIFIED]` |
| Any live MEGA traffic | not performed |
