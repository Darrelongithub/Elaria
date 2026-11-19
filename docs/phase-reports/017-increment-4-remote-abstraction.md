# Phase Report 017 — Increment 4: remote abstraction + verifier (VERIFIED)

**Date:** 2026-11-02
**Branch:** `arena/storage`
**Base:** `arena/c2a7085d-elaria` (stacked PR #24)
**Head at report time:** `d77eeee` → this report's commit
**Increment:** 4 of 8 (remote abstraction: `LocalPathBackend` fixture + `RcloneBackend`)

---

## 1. DONE

1. **`src/assistant/remote.py` written and verified** — the remote abstraction and the
   verifier that retires the no-verifier posture. ~480 lines, one new module.
2. **`tests/test_wp7_remote_abstraction.py` written and executed** — 42 tests, all passing.
3. **`src/assistant/backup.py` amended** (2 changes, §5).
4. **`tests/test_wp7_reconcile_crash_points.py` amended** (2 test fixes, §5).
5. **Full suite measured, ruff clean.** See §2.

### The three requirements, and how each is enforced structurally rather than by prose

**Requirement 1 — the command surface is pinned.**

`RCLONE_COMMAND_SURFACE` is a tuple of frozen `CommandPin` records, and
`surface_json()` dumps it as JSON — machine-readable, diffable against a pinned copy, the
way the kitty lane pins its verb inventory. Four verbs:

| verb | invoked by | purpose |
|---|---|---|
| `version` | storage | binary discovery and the version-pin check |
| `about` | storage | quota read for `remote_free` and the capacity-floor knock |
| `lsjson` | storage | presence check for an artifact on the remote |
| `serve restic` | **restic** | the backend transport; storage never spawns it |

`RCLONE_PINNED_VERSION = "1.75.2"` (latest stable, published 2026-10-09) and
`RCLONE_MIN_VERSION = "1.41.0"` (rclone added the MEGA backend in 1.41, Tier 2: no
mtimes, no hashes, duplicate names allowed).

**The enforcement is that `RcloneBackend.argv()` builds every command from that table and
nowhere else.** An unpinned verb raises `KeyError: rclone verb 'delete' is not in the
pinned command surface; refusing to improvise a command at runtime`. A test tries six
plausible destructive verbs (`delete`, `purge`, `rm`, `moveto`, `sync`, `copyto`) and
asserts every one refuses. There is no code path in this module that assembles an rclone
command from parts.

`invoked_by` is pinned per verb because the ownership boundary is the point: restic spawns
`serve restic --stdio`, and this lane must never spawn it. The 1 m `rclone.timeout` problem
(restic #3511/#3514 — MEGA repo open routinely exceeds a minute) is recorded on the
transport pin where it belongs, not as a floating note.

**Requirement 2 — rclone absent is a declared skip.**

`probe_rclone()` returns an `RcloneProbe` whose `reason` is **always populated** when
unavailable. An empty reason on an unavailable probe *is* the silent-pass failure, so the
reason names what is pinned and what could not be reached:

```
rclone not found on PATH; the rclone command surface is pinned at 1.75.2 and cannot be
exercised here
```

`RcloneBackend.verify()` with no binary on PATH returns
`confirmed=False, method="declared-skip"` with that reason in `detail`. **A test asserts it
can never come back `confirmed=True`.** Three further skip paths are pinned: a binary
below the 1.41 floor, a nonzero `lsjson` exit (with the code recorded), and unparsable
`lsjson` output.

Because rclone is genuinely absent from this sandbox (D4), the rclone-backed paths are
driven by a **stub binary written onto `tmp_path`** — a shell script that answers `version`
and `lsjson`. This exercises the real subprocess plumbing, the real argv construction and
the real JSON parsing, with no rclone and no MEGA. It is a stub of the *binary*, not a
re-implementation of the logic.

**Requirement 3 — every verification record names the backend that produced it.**

`Verification` carries `backend`, and that field is the whole requirement made structural:

- `LocalPathBackend.name` is **`local-path-fixture`** — deliberately unmistakable. A test
  asserts it contains neither `mega` nor `rclone`.
- `RcloneBackend.name` is **`rclone:<remote>`**, e.g. `rclone:mega-elaria`.
- `plan_reconcile` reads the `Verification` and writes the backend name **into the action
  reason**, which `reconcile()` then writes into the manifest record's `detail`. So a flip
  completed on the fixture lands in the journal as
  `re-verified local hash and remote copy (local-path-fixture, hash); completing the flip`,
  and a real one as `… (rclone:mega-elaria, presence); …`.

**A fixture confirmation can therefore never masquerade as real remote confirmation** — not
because a reviewer might be careful, but because the journal says which one it was.
`BackendRegistry` reinforces it: backends are keyed by name, and `is_fixture()` exists so a
caller can refuse a fixture as authoritative.

### An honest limitation, recorded rather than papered over

`RcloneBackend.verify()` accepts `expected_sha256` for interface parity with
`LocalPathBackend` and **deliberately ignores it**. rclone's MEGA backend cannot compare
content — no hashes — so a hash check there would be a claim this backend cannot make. The
method is recorded as `presence`, not `hash`, and the detail says
`artifact present on the remote; content not comparable on MEGA`. A test passes a hash that
cannot possibly match anything and asserts the verification still confirms *presence*,
because that is all that was proven.

`LocalPathBackend` does compare hashes, and reports `method="hash"`. The two backends are
distinguishable in the record by design.

### What this retires

Increment 2 refused to complete `uploaded → flipped` without a confirmed remote copy. With
no verifier that refusal was permanent — an artifact that uploaded successfully stayed
`uploaded` forever. `make_verifier(backend)` adapts a backend to the `verify_remote` seam,
and the full transition now completes against the fixture.

---

## 2. VERIFIED GATES (verbatim)

```
$ ./.venv/bin/python -m pytest -q
........................................................................ [ 99%]
.......                                                                    [100%]
2017 passed, 6 skipped in 167.66s (0:02:47)

$ ./.venv/bin/ruff check .
All checks passed!
```

**Baseline at `d77eeee`:** 1975 passed / 6 skipped / 0 errors, ruff clean.
**Now:** **2017 passed / 6 skipped / 0 errors, ruff clean.** Delta **+42**.

Delta accounting: `test_wp7_remote_abstraction.py` is an entirely new file, 42 tests,
collected count confirmed by `--collect-only`. No `parametrize` in the file, so defs =
collected. Nothing else gained or lost a test. 42 + 0 = **42**. ✓

Both measured on CPython 3.11.2 in the sandbox `.venv`.

### Per-file

```
$ ./.venv/bin/python -m pytest tests/test_wp7_remote_abstraction.py -q
..........................................                              [100%]
42 passed in 0.21s
```

---

## 3. DIFFSTAT

```
 src/assistant/remote.py                    | 480 +++++++++++++++++++++++++++
 tests/test_wp7_remote_abstraction.py       | 555 +++++++++++++++++++++++++++++
 (untracked, new)

 src/assistant/backup.py                    |  38 +++++++++++--
 tests/test_wp7_reconcile_crash_points.py  |   5 ++-
 docs/phase-reports/016-…md                |  39 +++++++
 docs/storage-handoff.md                    |   8 ++
```

PR #24 totals after this commit: 29 files.

---

## 4. FIREWALL STATEMENT

```
$ git status --porcelain
 M docs/phase-reports/016-increment-3-tiering-engine-and-trim.md
 M docs/storage-handoff.md
 M src/assistant/backup.py
 M tests/test_wp7_reconcile_crash_points.py
?? src/assistant/remote.py
?? tests/test_wp7_remote_abstraction.py

$ git status --porcelain | grep -E "daemon\.py|transcribe\.py|live_client\.py|HANDOFF\.md|conftest\.py"
CLEAN

$ git status --porcelain | grep -E "cli\.py|config\.py|ladder\.py|pyproject\.toml"
CLEAN - increment 4 needed no registration point
```

**Zero edits to `daemon.py`, `transcribe.py`, `live_client.py`, `HANDOFF.md`,
`tests/conftest.py`. Zero edits to `cli.py`, `config.py`, `ladder.py`, `pyproject.toml`.**
One new module, one new test file, one amended module (mine, increment 2), one amended test
file (mine, increment 2), two docs.

Increment 4 needed no registration point: the remote abstraction is a new module consumed
by `backup.py`'s already-injected `verify_remote` seam. No new dependency either — rclone
is a system binary, per the $0 doctrine. A test asserts `requests`, `boto3`, `mega` and
`restic` are not imported.

---

## 5. DEFECTS SURFACED

### D13 — the fixture "remote" was group/other accessible [FIXED]

`LocalPathBackend.store()` used `mkdir(parents=True, exist_ok=True)` with no mode, so the
fixture directory came out **0755**. A directory holding copies of the owner's audio must
be as private as the real remote, and the 0600/0700 discipline is already lane law for the
manifest and the trash dir.

Worse, `mkdir(mode=…)` only applies the mode when it *creates* the directory — an existing
tree would stay accessible no matter what was passed. Fixed with `chmod(0o700)` after the
`mkdir`, which enforces it either way. A test asserts `mode & 0o077 == 0`.

### D14 — `probe_rclone()` left rclone's leading `v` in the version [FIXED]

`rclone version` prints `rclone v1.75.2`, and the parser took `line.split()[1]` verbatim,
so the recorded version was `v1.75.2`. `version_at_least()` strips a leading `v` and so
still compared correctly — which is exactly why this could have sat unnoticed: the bug was
masked by defensive code elsewhere. Fixed at the source so the record is clean.

### D15 — an absent clock was reported as an unreadable timestamp [FIXED]

`plan_reconcile(..., now=None)` reached `now - _parse_ts(record.ts)`, raised `TypeError`,
and was caught by the same handler as a genuinely malformed timestamp — reporting
`trashed: unreadable timestamp; purge deferred` when the timestamp was perfectly readable.
The fault was the missing clock.

This is the same class of misattribution the lane has been careful about elsewhere: a
diagnostic that sends the reader hunting a bug that does not exist. Fixed by testing
`now is None` first and reporting `no clock supplied; the grace cannot be measured`. A test
asserts the new message appears and the old one does not.

### D16 — three of my own test expectations were wrong [TESTS FIXED]

- `test_the_fixture_remote_dir_is_owner_only` — caught D13.
- `test_a_fixture_flip_is_written_through_with_the_name_recorded` — called
  `reconcile(..., verify_remote=...)`. `reconcile()` executes a plan; the verification
  already happened at plan time, so `verify_remote` is not its parameter. Removed.
- `test_reconcile_all_drives_the_fixture_to_quiescence` — expected `["flipped"]` only.
  `reconcile_all` correctly continues to `trashed`, because a durable flip makes the trim
  unconditional. Fixed to expect `["flipped", "trashed"]` and to supply a real `TrashMover`.

A fourth expectation, that `reconcile_all` with **no** trim mover would settle quietly, was
also wrong — and the code's behaviour was right: it re-plans the trim each pass, hits the
8-pass ceiling, and records `reconcile did not reach quiescence in 8 passes; stopping
rather than looping`. That is the correct safety property, so it is now pinned by its own
test rather than left as an accident.

---

## 6. OPEN QUESTIONS

- **Q13 — still open, still increment-4-plus work.** Reading `transcribe.py:1448` is
  permitted; editing it is not. Untouched by this increment.
- **No new questions raised.**

### One thing surfaced for the owner's awareness, not a question

`RcloneBackend.verify()` proves **presence, not content**, because MEGA reports no hashes.
This is a property of the backend, not a limitation of this increment, and it is recorded
in the `Verification.method` field so it is visible in the journal. It means a flip
completed against MEGA rests on presence alone. That is what the backend can prove, and
the record now says so rather than implying a content check that never happened.

---

## 7. WHAT INCREMENT 4 DOES NOT CLAIM

- **No live MEGA traffic.** No remote was contacted. Every rclone-backed path ran against a
  stub shell script on `tmp_path`.
- **`[TESTED-ONLY]` throughout.** The command surface, the skip postures and the
  provenance are proven. The behaviour against a real rclone 1.75.2 and a real MEGA
  account is `[UNVERIFIED]`.
- **rclone is absent from this sandbox (D4, unchanged).** The stub proves the plumbing, not
  the backend.
- **restic is still absent from this sandbox.** The `serve restic` pin is documentation of
  a command this lane does not run.
- **No credentials anywhere.** No `rclone.conf`, no passphrase file, no remote name that
  is the owner's.
- **No live-traffic gate movement.** Still stopped at Gate 1 for live traffic and merge.

---

## 8. NEXT

**Increment 5 — `assist backup` CLI + sensors.** The CLI surface
(`assist backup fetch <artifact>` and friends) and the `backup.started/done/failed/verify/
check` and `storage.gauge` sensors per report 007 §2. This is the first increment that
touches a registration point, so the additive-only firewall will be exercised for real.

Then increments 6–8. No merge until the design chat rules the mainline gate passed.

---

## 9. EVIDENCE TAGS

| Claim | Tag |
|---|---|
| Command surface pinned, unpinned verbs refuse | `[TESTED-ONLY]` |
| Version comparison numeric, floor enforced | `[TESTED-ONLY]` |
| Absent rclone → declared skip, never confirmed | `[TESTED-ONLY]` |
| Skip postures (floor, nonzero exit, unparsable output) | `[TESTED-ONLY]` |
| Provenance: backend name reaches the manifest detail | `[TESTED-ONLY]` |
| Fixture dir 0700 | `[TESTED-ONLY]` |
| Full `uploaded → flipped` transition on the fixture | `[TESTED-ONLY]` |
| Suite 2017 / 6 / 0, ruff clean | `[TESTED-ONLY]` |
| Against a real rclone 1.75.2 | `[UNVERIFIED]` |
| Against a real MEGA account | `[UNVERIFIED]` |
| Any live MEGA traffic | not performed |

---

## 10. ADDENDUM — the predicted second base movement (drift check run)

The design chat warned to expect mainline's window-findings order to land atop `0320c11`.
It did, and the ancestry guard caught it at push time: the PR base moved a second time,
`0320c11` → **`fdcdb47`** — 5 commits (F1 PyAV pin, F2 gemini-3.5-transcribe 3 RPM, F3
empty-leg semantics, plus the voice-chain resilience pins and scene card).

`journal_log.py` changed again (+52 lines), so the **sole early trigger** was checked
immediately, exactly as on the first movement:

```
$ git diff 0320c11..fdcdb47 -- src/assistant/journal_log.py
 src/assistant/journal_log.py | 52 ++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 52 insertions(+)
```

**The trigger did NOT fire — for the second time.** The change is purely additive:

- `log_event()`'s signature is **unchanged**; the diff appends new functions after it.
- The journal line format is **unchanged**: `ts SP level SP event SP session_id SP peak
  SP verdict [ SP detail ]`. `split(" ", 6)` still yields 6 or 7 parts.
- Two new event names, `transcription.backend` and `transcription.starvation`, both emitted
  through the same `log_event()`. Per §2.1's dispatch rule these add names to dispatch on
  and collide with nothing WP7 consumes.
- `session_id` handling unchanged.

**The §2 canonical contract is unchanged. No re-dating, no re-measure** — the
bare-movement clause applies for the second time.

Also re-checked:
- `audio kept at` on `fdcdb47`: **4** (1 in `daemon.py`, 3 in `transcribe.py`) — identical
  to the recorded count. **Drift 2 does not recur.**
- `cost.iso_now` present; `storage.py` is this lane's own increment-1 file and so absent
  from mainline by construction, not by deletion. No mainline file my increments 1–4 depend
  on was touched.

### A corroboration worth recording

Both new mainline helpers (`stump_verdict`'s sha16 and `backend_mark_detail`'s
`chars=…; sha16=…`) adopt the **same privacy pattern this lane's fence established** — the
class, the count and a hash prefix, never the raw text. Mainline is converging on report
006 §6's shape independently. That is corroboration of the fence, not drift from it.

`error_text(exc)` is also worth noting as a mainline convention: failure text is
**never empty**, because a message-less `TimeoutError` still names its class. This lane's
skip details already record `type(exc).__name__`, which is consistent with it — a
convention adopted here before it was named there.
