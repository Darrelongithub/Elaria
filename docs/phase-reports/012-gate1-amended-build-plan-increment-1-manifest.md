# Phase report 012 — GATE 1 AMENDED; build plan; INCREMENT 1 LANDED (storage manifest)

**Date:** 2026-10-31
**Branch:** `arena/storage` @ `70f2b0f` → increment commit
**Trigger:** owner order, verbatim: *"lets start building the storage."*

---

## DONE

### 1. The Gate 1 amendment, recorded FIRST

Recorded as a dated append-only entry in `docs/storage-handoff.md` (RULING 33) **before
any other work this activation**, as instructed. The owner's Sheet numbers are re-scoped
from build-blocker to config-finalization and live-traffic gate. Machinery construction
begins now.

### 2. THE BUILD PLAN — machinery increment order

Eight increments, ordered so each one is testable before the next depends on it, and so
nothing needs a Sheet number to be *built* (only to be *tuned*):

| # | Increment | Why here | Depends on |
|---|---|---|---|
| **1** | **storage manifest** — append-only JSONL, five-state machine, fsync'd appends, `[backup]` config section | everything else reads or writes it; pure filesystem, no restic/rclone | nothing |
| 2 | reconcile-on-start + **crash-point tests** | the crash-consistency guarantees are the spec's hardest requirement | 1 |
| 3 | tiering engine (HOT window/GB) + **trim** (grace → purge, idempotent) | needs the state machine's ordering to be trustworthy | 1, 2 |
| 4 | remote abstraction (`LocalPathBackend` fixture + `RcloneBackend`) + restic-over-rclone wiring | cold read path is written against the abstraction, never MEGA | 1 |
| 5 | `assist backup` CLI (`fetch`/`status`/`verify`/`check`) + sensors `backup.*` / `storage.gauge` | the owner-facing surface and the observability | 1, 3, 4 |
| 6 | ladder chain #5 **"backup chain"** | additive chain; reads the machinery above | 1, 3, 4 |
| 7 | post-close hook (watcher, polling snapshot-diff) + nightly timer unit + WP5 monthly trigger shape | the triggers; daemon untouched by ruling | 1, 3 |
| 8 | monthly restore-drill scaffolding + quarterly `--read-data-subset` | the integrity rung of chain #5 | 1, 4, 6 |

**Not in this plan, by ruling:** FLAC (documented, not built), a second target, and any
live MEGA traffic.

### 3. SYNTHETIC FIXTURE INVENTORY (what the machinery is tested against)

No restic, no rclone, no MEGA, and **no real wav ever enters this sandbox.**

| Fixture | Shape | Used by |
|---|---|---|
| `synthetic-wav-*.bin` | random bytes, fixed size, known sha256 — never valid audio | manifest, tiering, trim, crash points |
| `local-path remote` | a temp dir standing in for the `rclone:` backend | remote abstraction, cold read path |
| `fake clock` | injectable `now`, no sleeps | grace-period expiry, nightly trigger |
| `fake dirs` | headless XDG roots from `conftest.py`'s `isolated_env` | everything |
| `journal buffer` | `conftest.py`'s `journal_stream` captures schema lines | sensors |

The manifest tests already use the first, second, fourth and fifth.

### 4. THE INTERIM-DEFAULTS TABLE — every Sheet-dependent value, labelled

All under `[backup]`, all carrying `INTERIM-PENDING-SHEETS` in the source. A test asserts
the label is present, so removing one is a caught defect rather than a cleanup:

| Key | Interim value | Status | Replaced by |
|---|---|---|---|
| `hot_window_days` | 14 | `INTERIM-PENDING-SHEETS` | Sheet 2 census |
| `hot_window_gb` | 2 | `INTERIM-PENDING-SHEETS` | Sheet 2 census |
| `trim_grace_days` | 14 | `INTERIM-PENDING-SHEETS` | Sheet 2 census |
| `capacity_floor_gb` | 2 | `INTERIM-PENDING-SHEETS` | Sheet 2 census |
| `restic_pack_size_mib` | 16 | `INTERIM-PENDING-SHEETS` | Sheet 1 benchmark |
| `restic_timeout` | `"5m"` | documented pin, not tuned | Sheet 1 benchmark |
| `watcher_poll_s` | 30 | ruled default (not Sheet-dependent) | — |
| `nightly_oncalendar` | `"03:17"` | operator choice | — |
| `defer_above_mb` | 100 | spec value | — |
| `rclone_remote` | `""` | **empty = refuse, never guess** | owner's machine only |

`rclone_remote` being empty is deliberate: every command that needs a remote refuses
rather than inventing one, so the machinery cannot accidentally aim at MEGA.

### 5. INCREMENT 1 LANDED — the storage manifest

`src/assistant/storage.py` (new) + `[backup]` in `DEFAULTS` + `config.toml.example` parity
+ 14 tests.

**The five states, and why the order is the safety property:**

```
local      only copy is on the HOT disk
uploaded   remote copy exists AND hot copy still in place        (2 copies)
flipped    authoritative home is now COLD; hot copy still there  (2 copies)  ← decision
trashed    hot copy in local trash, 14-day grace running         (2 copies)
purged     grace elapsed — remote is now the only copy           (1 copy)
```

The ordering exists to guarantee the spec's invariant: **no artifact ever has exactly one
copy the instant the flip lands.** Between `flipped` and `purged` there are always at
least two copies, so a bad flip is recoverable rather than fatal.

**The state machine enforces the ordering instead of trusting callers.** The transition
table refuses:
- `local -> trashed` — would trash the *only* copy,
- `uploaded -> trashed` — would trim without ever recording the flip decision,
- anything out of `purged` — it is terminal.

**Crash consistency, built in now so increment 2 tests against it:**
- every append is `fsync`'d before returning, so *readable* and *durable* are the same
  statement;
- a crash mid-append can only leave a trailing line with no newline, which `records()`
  **discards as not durable** — a half-state is never something the reconciler acts on;
- a malformed line is skipped, never fatal — the manifest is the audit trail and losing
  one line must not stop the reader;
- the flip-before-trim ordering is expressed as: the trim path calls `append(FLIPPED)`
  and proceeds only on `True`.

**Privacy fence, structural rather than procedural.** `summary()` returns counts, sizes,
states and tiers and is *blind to which artifact is which*. That blindness is the fence,
not a limitation of it — a test asserts no path fragment appears in the serialised
summary. The manifest file is 0600 in a 0700 directory, outside the repo, never
committed.

### 6. VERIFICATION

| Measurement | Result |
|---|---|
| Increment 1 tests | **14 passed** |
| Full suite on my branch + increment 1 | **1927 passed / 6 skipped / 0 errors** |
| Pristine `f915d8e` base, measured in a throwaway worktree | **1913 passed / 6 skipped / 0 errors** |
| Ruff (full repo) | **All checks passed** |

Delta: **+14 tests, 0 new errors, ruff clean.** Baseline holds.

---

## DEFECTS FOUND

**Three, all mine, all fixed in this activation:**

1. **`F401` unused imports** in `storage.py` — `dataclasses.field` and `cost.iso_now`.
   Fixed by making `iso_now` do real work as `ts`'s `default_factory`, so a caller can no
   longer forget to timestamp a record. Not just silenced.
2. **`RUF022 __all__` not sorted** — ruff's isort-style order wants constants before
   classes before functions (`TIER_COLD`, `TIER_HOT`, then the classes, then `redact`).
3. **`config.toml.example` parity drift** — `test_bh_h22_config_example_parity_and_validation`
   failed because `[backup]` existed in `DEFAULTS` but not in the example. Fixed by adding
   the section with the same keys. This test is doing exactly its job: it caught a real
   registration gap that would otherwise have shipped a doctor warning.

**One correction to my own record, and it matters:** report 005 recorded the pristine base
as *1913 passed / 6 skipped / **1 error** (D7)*. Measured again this activation in a
throwaway worktree on the same CPython 3.11.2, the pristine `f915d8e` base is
**1913 passed / 6 skipped / 0 errors** — **D7 did not fire.**

The defect is still *present*: my tree still carries the unguarded
`task.get_coro().__qualname__` at `tests/conftest.py:108`, and `tests/conftest.py` is the
mainline's file that the storage lane must not touch. So this is not "D7 was fixed" — it
is "D7 did not reproduce in this environment". The teardown error depends on an
`async_generator_athrow` task surviving into `asyncio.all_tasks()` at teardown, which
makes it sensitive to interpreter patch level and GC timing rather than strictly
deterministic.

**I am not re-baselining on this.** The recorded baseline stays as measured per
activation, and the honest statement is that D7 is present-but-not-firing here. If it
fires again, the earlier recording stands; if it never does, mainline's fix in `8a72939`
has already made the question moot for the merged line.

---

## NEXT GATE

**Increment 2 — reconcile-on-start + crash-point tests.** The crash points are the spec's
hardest requirement and increment 1 was shaped to make them testable:

1. kill between upload and flip → reconcile-on-start re-verifies then flips;
2. kill between flip and trim → trim idempotent;
3. flip fsync'd before any trim.

Each needs a fixture that *interrupts* the sequence — a manifest left mid-state plus a
filesystem left mid-operation — which increment 1's state machine now makes expressible.

**Still gated, unchanged:** live MEGA traffic (Sheet 1 go/no-go), final numeric defaults
(Sheet 2 census), merge (gate v2), the additive-only firewall, and the owner's real wavs.

---

## OPEN QUESTIONS

**Q22 — increment 3 needs a ruling on one point.** The trim moves an artifact to *local
trash*. The existing `executor.py` trash mechanism already writes a `trash/manifest.jsonl`
with a 14-day grace-then-purge shape. Two options:

- **(a)** reuse `executor.trash()` and let WP7's manifest record the state transition
  alongside it — one trash mechanism, two records;
- **(b)** WP7 owns its own trash dir and grace clock, independent of `executor.py`'s,
  because the backup trim has different recovery semantics (the remote copy already
  exists, so a purge failure is not data loss).

I lean (b) — the semantics differ and coupling them risks `executor.py`'s behaviour
changing when WP7's grace policy is tuned — but it is a design decision with a real
trade-off, so it goes to the owner rather than being assumed.

**Q23 — none blocking.** `rclone_remote` empty-by-default is deliberate and needs no
ruling.
