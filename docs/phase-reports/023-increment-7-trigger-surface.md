# Report 023 - Increment 7 landed (the trigger surface), and a near-miss on mainline's `watcher.py`

**Date:** 2026-11-04 (Africa/Nairobi)
**Branch:** `arena/storage` @ increment 7
**PR:** #24 (base `arena/c2a7085d-elaria` @ `a6cc150`)
**Frozen branch (condition 3):** `origin arena/e7a1cca5-elaria = b181712563c1577f5faea4e59fe5f7e104a89ed1` - verified before and after this activation. Untouched.

---

## DONE

### Push resumed on the ruling, and report 022 went up first

Firing three occurred: a fresh clone followed by a forced checkout onto the frozen branch,
refspec still restricted. The canonical report-020 checklist was run **as a checklist, not
re-derived**: frozen-hash verify before; explicit-URL fetch; integrity check; local-only
checkout; verify after. All five steps passed.

Report 022 went up as its **own single commit** (`07586a6`) under the ruling's three
conditions:

1. **Explicit refspec URL only** - `+refs/heads/arena/storage:refs/heads/arena/storage`,
   never a bare push that could follow a harness-set upstream.
2. **Full-SHA verification, before and after, of both refs** - the frozen branch stayed at
   `b181712...` and my ref advanced to my local HEAD.
3. **Report 022 before increments 7/8** - the commit touched only report 022 and the
   handoff, no code.

**A defect in the checklist itself, self-caught.** The integrity check flagged
`docs/storage-handoff.md` as a mismatch - correctly, because the workspace held the
uncommitted report-022 append. The subsequent force checkout then **overwrote** it, and the
append had to be re-written verbatim. **The lesson: a flagged mismatch means preserve the
work BEFORE checking out, not after.** The checklist as written contains a step that can
destroy the thing it just detected.

### The merge note landed

The design chat's review item - the two argparse lines removed from `ladder.py` must not
retire a mainline interface - is answered with a behavioural proof and now lives in the PR
#24 description:

| Check | Result |
|---|---|
| every BASE choice still accepted | **True** |
| nothing REMOVED | **True** |
| the ONLY addition | `('backup',)` |
| the four chain names keep their relative order | True |
| description still names all four originals | **True** |
| all four BASE chain methods present on `Ladder` | **True** |
| `run_chain` still dispatches `"all"` | True |

`"backup"` is inserted immediately **before** the sentinel `"all"`, deliberately: `"all"`
means "every chain", so appending after it would retire the sentinel's contract while
leaving the command working. Pinned by `tests/test_wp0_ladder.py`, which fails if a chain
is dropped.

### Increment 7 - the trigger surface - LANDED

| File | What |
|---|---|
| `src/assistant/backup_triggers.py` (new) | the watcher: belt + suspenders + deferral |
| `tests/test_wp7_watcher_triggers.py` (new, 38 tests) | headless, no sleeps, no journalctl |
| `systemd/assistant-backup.service` (new) | nightly oneshot, runs `assist backup run` |
| `systemd/assistant-backup.timer` (new) | `OnCalendar=03:17`, `Persistent=true` |
| `systemd/assistant-backup-monthly.timer` (new) | WP5 monthly shape, `OnCalendar=*-*-01` |
| `src/assistant/cli.py` (+7/-0) | additive `backup watch` registration |
| `src/assistant/backup_cli.py` (+40/-0) | the `_watch` handler |
| `tests/test_bug7_cli_smoke.py` (+1) | smoke entry for the new leaf |

**The daemon is not touched**, per the trigger ruling. The module observes the audio root
and the journal and decides when a backup should wake; it never performs one. A one-line
daemon hook may be proposed only after the mainline PR merges.

**Belt/suspenders, polarity pinned by test.** The directory poll is **truth**; the journal
tail **corroborates and can never create a wake**.
`test_a_journal_post_close_alone_cannot_create_a_wake` feeds a journal full of
`session.close` lines into an unchanged directory and asserts a no-op. Inverting this would
let a log line manufacture work - the forbidden optimisation.

The poll is cheap by construction: `scandir` plus name/size/mtime, **no hashing** (pinned
by `test_no_hashing_is_performed`). The journal tail is incremental from a persisted
cursor, so a restart resumes rather than replays. §2.1 is honoured: dispatch keys on the
event **name** (`parts[2]`), never the verdict. The privacy fence holds: `WakeDecision`
carries counts and extension **labels** only, never names or paths.

**Deferral policy.** Uploads above `[backup] defer_above_mb` (100 MB) wait for AC/unmetered
power. The boundary itself does not defer, and a zero threshold disables the policy - both
pinned.

**The systemd units carry the T0 citation**, because it is counter-intuitive and
load-bearing: multiple elapses during **one continuous sleep collapse to a single
activation**. A laptop closed all month runs **one** drill, not thirty. That is correct
here - the manifest is a state machine and `reconcile_all()` runs to quiescence, so one
catch-up pass reaches the same state thirty would.

**No unit names a secret.** Pinned by a test that checks for **assignments**
(`Environment=PASSWORD`, `EnvironmentFile`), not for prose - a comment explaining that no
secret lives in the file is the policy, not a violation. The first draft of that test
failed against its own unit's explanatory comment, which is how the distinction got
pinned properly.

---

## DEFECTS FOUND

### A near-miss on mainline's file - the lane's most serious slip

**`src/assistant/watcher.py` is MAINLINE's, and I overwrote it.** I wrote my increment-7
module straight into that path with `write_file`, which creates-or-overwrites. The file was
already in my HEAD - 89 lines, `WatcherEvents`, `snapshot()`, `PollingWatcher` - and
`tests/test_bughunt_systems.py` and `tests/test_phase3_organiser.py` import
`PollingWatcher` from it.

**It was caught by mainline's own tests, not by me:**

```
ImportError: cannot import name 'PollingWatcher' from 'assistant.watcher'
```

**Recovery, byte-exact.** `git checkout HEAD -- src/assistant/watcher.py` restored
`17ce5430e835d02ceb4b47c6efc21501fae95760`, identical to the base. Mainline's 81 tests pass
again. **The clobber was never committed, so nothing was lost and nothing was pushed.**

**There was a real name collision, not just a path collision.** Mainline's
`snapshot(root) -> dict[str, tuple[int, float]]` walks recursively and keys by **full path
string**, for the voice-test/dictation pipeline. Mine is flat and keys by **name**, because
a backup trigger must not carry a path anywhere near its output. Same name, different
return type, different job. Mine is now `directory_snapshot()` in `backup_triggers.py`.

**This is the third mainline-owned file this lane has touched, and the first time it was an
accident.** `ladder.py` and `cli.py` were deliberate and documented. `watcher.py` was a
blind `write_file`. Three boundary tests now pin it: the on-disk file must equal `HEAD:`'s
version; this lane must not export a bare `snapshot`; and the two snapshots must not be
interchangeable.

**How it was missed, and the rule that prevents it.** I checked for a *ladder* collision
and never checked whether `watcher.py` existed before writing to that path. **Before
writing any new module, `git cat-file -e HEAD:<path>` first - and confirm the revision
resolves before trusting a negative.** That is the same rule recorded in report 022, and
this is the second time a git-plumbing shortcut has cost this lane real work.

### Four test defects of my own, all self-caught

1. **Hardcoded `/tmp` paths** in the first draft - the recorded pollution hazard. Now
   self-managed `TemporaryDirectory` per test class, because `tmp_path` does not inject
   into `unittest.TestCase` methods (which is itself worth recording).
2. **`deferred` carried filenames, not labels** - a privacy-fence violation in my own
   watcher. Caught by my own test asserting the wrong thing, then fixed properly.
3. **A 200 kB payload tested against a 1 MB deferral threshold** - asserted nothing.
4. **The secret test searched for prose**, failing against its own unit's explanatory
   comment. Now it checks assignments.

---

## Suite

| Tree | Passed | Skipped | Failed | Ruff |
|---|---|---|---|---|
| increment 6 (`07586a6`) | 2104 | 6 | 0 | clean |
| **increment 7** | **2142** | **6** | **0** | **clean** |

+38 = the new `test_wp7_watcher_triggers.py`.

**D7 fired in 2 of 4 full-suite runs** (the `tests/conftest.py:108` teardown
`AttributeError`). The clean runs are 2142/6/0. It is pre-existing, mainline-owned, and
unchanged by this increment - the design chat has ruled it mainline's and nothing further
is asked of this lane.

---

## Fifth base movement

`be9183c -> a6cc150`, four commits of voice-chain extraction work. Bare movement:
`journal_log.py` byte-identical, `audio kept at` still 4, Drift 2 does not recur, both §2
clauses re-verified, merge-base still `f915d8e` with no history rewrite. **GATE 1e
unchanged - this lane still consumes no journal shape, so the zero-migration-cost window is
still open.**

---

## NEXT GATE

**Increment 8 - monthly restore-drill scaffolding.** Authorized and unstarted. Nothing in
it needs a ruling first.

Gate 1 unchanged: **no live MEGA traffic, no merge.**

---

## OPEN QUESTIONS

1. **Does mainline want `assistant/watcher.py`'s `PollingWatcher` reused for backup
   triggering, or is the deliberate separation right?** I kept them separate because
   mainline's debounce semantics serve the voice-test pipeline and coupling backup
   triggering to them would be wrong. But it is a judgement, and mainline owns that file.
2. **Is `systemd/` the right home for the backup units?** It matches the existing
   convention (`assistant.service`, `elaria-console.service`, `elaria-overlay.service`),
   but those are all daemons, not oneshot timers. Flagging rather than assuming.
