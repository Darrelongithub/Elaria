# Report 024 - Increment 8 landed: the monthly restore-drill scaffolding. The WP7 build plan is complete.

**Date:** 2026-11-04 (Africa/Nairobi)
**Branch:** `arena/storage` @ increment 8
**PR:** #24 (base `arena/c2a7085d-elaria` @ `a6cc150`)
**Frozen branch (condition 3):** `origin arena/e7a1cca5-elaria = b181712563c1577f5faea4e59fe5f7e104a89ed1` - verified before and after this activation. Untouched.

---

## DONE

### Firing four, handled by the checklist

A fresh clone followed by a forced checkout onto the frozen branch, refspec still
restricted. The canonical checklist ran **as a checklist, not re-derived**: frozen-hash
verify before; explicit-URL fetch (`FETCH_HEAD = 8405ff7`); integrity check over 31 files;
local-only checkout; verify after. **All steps passed with 0 mismatches - nothing
uncommitted was lost**, because report 023's work was already committed and pushed.

The report-023 lesson - *a flagged mismatch means preserve the work BEFORE the checkout* -
was built into the checklist as a step this time. It did not need to fire, which is the
point of writing it down.

### Both rulings recorded

1. **Separation stands; no reuse of mainline's `PollingWatcher`.** The two snapshots serve
   different masters: recursive walk, debounce and full paths for the voice-test pipeline;
   flat, name-keyed and path-free for a backup trigger, because a path must never approach
   its output. Sharing would couple two lanes' evolution through a mainline-owned file,
   making every tweak for one purpose a cross-lane review. My three boundary tests are the
   enforceable form of the decision. If mainline ever wants unification, that is their
   request with its own ruling.
2. **`systemd/` is the right home.** The directory names a content type, not a unit type,
   and the convention co-locates a timer with the service it activates.
   All-existing-units-are-daemons is history's coincidence, not a rule.

### Increment 8 - the monthly restore-drill scaffolding - LANDED

| File | What |
|---|---|
| `src/assistant/drill.py` (new, ~340 lines) | the drill machinery |
| `tests/test_wp7_drill_scaffolding.py` (new, 30 tests) | headless, scripted restic |
| `systemd/assistant-backup-monthly.service` (new) | runs the monthly drill |
| `src/assistant/cli.py` (+9/-0) | additive `--record` and `--last` flags |
| `src/assistant/backup_cli.py` (+95/-0) | the drill seams, all optional |

**This closes the 8-increment build plan.** All eight are landed: 1 manifest, 2 reconcile +
crash points, 3 tiering + trim, 4 remote abstraction, 5 CLI + sensors, 6 ladder chain #5 +
refusal audit, 7 trigger surface, 8 drill scaffolding.

#### The four pieces

1. **`DrillJournal`** - an append-only, fsync'd, 0600 drill log outside the repo, mirroring
   `StorageManifest.append()`'s one-write-then-fsync discipline. The WP7 gate says "one live
   monthly drill passes", and **a pass nobody can look up afterwards is not evidence.**
2. **`read_data_subset()`** - the quarterly cap as the **smaller** of the percentage and the
   byte ceiling. **A percentage alone is not a bound: 5% of a 40 GB repository is 2 GB,
   four times the ruled ceiling.** With the repository size known, both bounds are computed
   and the smaller wins (40 GB -> `500M`; 2 GB -> `100M`). Without it, the percentage is
   passed and the byte ceiling is recorded as *unenforceable* rather than silently ignored -
   a cap nobody checked is not a cap.
3. **`ResticCheck`** - the seam that builds and runs `restic check` through the `rclone:`
   backend, with an **explicit** `rclone.timeout` (MEGA repo-open routinely exceeds restic's
   1m default - restic #3511/#3514, recorded on the increment-4 command pin) and a
   `--password-file` path that is passed and **never read**. The runner is injectable, so no
   restic binary is needed anywhere in the tests.
4. **`run_drill()`** - the orchestration.

#### Two load-bearing behaviours

**A missing restic is a DECLARED skip, not a pass and not a failure.** The restore and the
hash-verify are what prove the owner can get their audio back; `restic check` additionally
proves the repository is internally consistent. Reporting a drill that could only do the
first half as a full pass would be the silent-pass failure increment 4 exists to prevent.

**A failed drill is recorded, not just a successful one.** Every return path in `_check`
now writes a record: restore failure, hash mismatch, no restorer, no manifest record,
artifact not cold, and the "nothing cold to drill" correct no-op. **A journal that only ever
shows passes is not evidence.** A torn trailing line is discarded, so a crash mid-write can
never manufacture a drill that ran. An unwritable journal returns False rather than raising:
a drill that cannot be recorded still happened, and the caller must be able to see that the
record failed without the drill itself failing.

**The privacy fence holds on the record itself.** A drill record carries a kind, an outcome,
a backend name, a method and an artifact **label** (its extension) - never a name or a path.
`backend` names which backend confirmed, per increment 4's rule that every verification
record must name the backend that produced it.

### End-to-end verified through the real CLI

With a scripted restic runner and a local-path fixture backend:

```
monthly  -> exit 0; {'ok': True, 'backend': 'local-path-fixture',
                     'method': 'restore+hash', 'detail': 'restore=ok; hash=ok'}
fake hash-> exit 1; {'ok': False, ..., 'detail': 'restore=ok; hash=MISMATCH'}
--last   -> "last monthly drill FAILED at <ts> (backend=...; method=...)"  path-blind
quarterly-> exit 0; kind='quarterly'
```

The fake-hash case is worth naming: the drill **detected** the mismatch and recorded a
failure, which is the machinery doing its job on a deliberately wrong fixture.

---

## DEFECTS FOUND

Three of my own, all self-caught before commit:

1. **`read_data_subset(pct=-1, mb=-1)` does not raise** - my test asserted a `ValueError`
   against the wrong function. The `ValueError` belongs to `run_drill`, which refuses an
   unknown *kind*. Fixed by testing the right thing, and the disabled-cap case is now pinned
   as a configuration rather than a fault.
2. **A `dict()` call and a mutable class attribute** in the new test file - two ruff
   findings, both fixed.
3. **The end-to-end fixture used `sha256="0"*64`**, so the first run correctly failed. That
   was the test being wrong, not the code - and the fact that the drill caught it is the
   behaviour working.

---

## Suite

| Tree | Passed | Skipped | Failed | Ruff |
|---|---|---|---|---|
| increment 7 (`8405ff7`) | 2142 | 6 | 0 | clean |
| **increment 8** | **2172** | **6** | **0** | **clean** |

+30 = the new `test_wp7_drill_scaffolding.py`. D7 did not fire this run.

---

## NEXT GATE - the WP7 gate itself

**The build plan is complete; the gate is now the only thing standing between this lane and
its stop-and-report.** Its conditions:

1. Benchmark numbers ruled go - **Sheet 1 still owed** (MEGA in browser, owner-run rclone
   config, benchmark, plus the end-to-end restic-over-MEGA ratio).
2. A resolved kept-wav goes cold with manifest flip + grace-trash trim - **machinery built
   and crash-tested; not yet exercised against a live remote.**
3. Crash-point tests green - **done** (increment 2).
4. Owner re-listens via `assist backup fetch` inside the ruled latency budget - **built;
   needs the owner and a live remote.**
5. One live monthly drill passes - **scaffolded; needs a live remote.**
6. Ladder chain #5 including the integrity rung all REACHED - **built and tri-state
   verified.**
7. Zero credentials in repo or chat - **held.**

**Gate 1 unchanged: no live MEGA traffic, no merge.**

---

## OPEN QUESTIONS

1. **Should the quarterly drill have its own timer unit, or is it owner-initiated only?** I
   built it as owner-initiated (`--kind quarterly` by hand), because it reads up to 5%/500 MB
   of the repository *on purpose* and that is a deliberate act rather than a scheduled one.
   Flagging rather than assuming - if the owner wants it scheduled, it is a four-line unit.
2. **`trim_grace_days` is still the only `INTERIM-PENDING-SHEETS` value** in `[backup]`.
   Nothing in increments 7 or 8 bounded it, and the WP7 gate's grace-trash condition cannot
   be called final until it is measured.
