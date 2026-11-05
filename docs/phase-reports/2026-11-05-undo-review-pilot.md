# Undo review pilot — prepare / apply seam

Date: 2026-11-05 · Branch: `arena/c2a7085d-elaria` · Grant: 2026-11-04 · Commit: **`e7316b9`**
Authority: owner grant of the pilot seam (2026-11-04) + design note `docs/design/2026-11-04-undo-consent-seam.md`
Evidence class: **[TESTED-ONLY]** — headless sandbox, no hardware in the loop, no key.

Baseline before this change: `uv run --no-sync pytest -q` → **2,036 passed, 6 skipped** at `f172d8b`.
After: **2,054 passed, 6 skipped** at `e7316b9` (2,036 + 18 new pins). `ruff check .` clean.

Diff: `src/assistant/daemon.py` **+165 / −0**, `tests/test_undo_review_pilot.py` **new, 362 lines**.

> **Estimate vs actual.** The estimate given before code was *~115 lines and ~20 pins*.
> Actual: **165 lines and 18 pins**. The code overran the estimate by ~50 lines; I am
> reporting that rather than trimming the seam to fit a number. The overrun is
> concentrated in `_undo_drift` and the terminal/lapse journal branches, not in any
> scope the grant did not cover.

---

## DONE

Two new RPCs on the daemon, registered beside the existing `"undo"`
(`daemon.py:793–794` at `e7316b9`):

| element | line (`e7316b9`) |
|---|---|
| `self._undo_asks` state (memory only) | `daemon.py:236` |
| `"undo.prepare"` / `"undo.apply"` registry | `daemon.py:793–794` |
| `UNDO_ASK_TTL_S = 600.0` | `daemon.py:2809` |
| `_undo_preverify` (mirrors `executor.py:462` orientation) | `daemon.py:2811` |
| `_undo_drift` | `daemon.py:2832` |
| `_undo_prepare` | `daemon.py:2844` |
| `_undo_apply` | `daemon.py:2899` |
| bare `_undo` (unchanged, guard at 2779–2786) | `daemon.py:2782` |

**Prepare** is owner-only, resolves a scope (`op_id`, `plan_id` or `since`) to exactly
one operation row, pre-verifies it (current home = `op["dst"]`, original = `op["src"]`,
mirroring the swap at `executor.py:462`), and only then raises an ask. It writes
nothing. The ask is a random 64-hex token mapped in memory to a canonical-JSON
snapshot (`sort_keys`, tight separators) whose sha256 is returned to the caller as
`ask_sha256`, so the console reviews a digest-bound card. Returns
`{token, ask_sha256, snapshot, prepared_at, age_s: 0.0, expires_in_s: 600.0}`.

**Apply** requires `decision` ∈ {`yes`,`no`} and an owner `IpcPrincipal`; the actor
recorded is `owner-ipc uid=… pid=…`. Branches, all terminal:

- **lapsed** (now > `expires_at`) → journal `verdict=lapsed`, the ask is dropped, the
  caller is told a lapsed ask needs a *fresh prepare, never a Yes*; nothing executes.
- **no** → journal `verdict=declined`, exactly one persona line
  `{"ack": "declined", "ask_sha256": …}` — no paths, no content echo — and the ask is
  kept marked used so a replay says *already answered*.
- **yes** → the operation row is re-read and compared against the snapshot over
  `plan_id, ts, op, src, dst, sha256_before, sha256_after, status`; then filesystem
  pre-verify runs again. Any difference at all → `verdict=drifted`, total refusal,
  nothing undone, ask marked used. Otherwise the token is consumed **before**
  `executor.undo(op_id=…)` runs (single use; a crash mid-undo can never re-arm it).

Bare `undo` was not touched: same 8-line guard above `parse_since`, same path into
`_undo_gated`. `cli.py` was not touched.

**Containment statement (as required by the grant).** Containment is
**console/daemon-route only, not global.** `cli.py`'s `DaemonUnavailable` fallback
calls `Executor.undo` directly in the CLI process and therefore bypasses prepare,
apply, pre-verification, expiry and the single-use token entirely. Until CLI parity
lands (deferred by the owner until after the pilot at the earliest), the pilot's
guarantees hold only for callers that arrive over the daemon RPC route.

### Pins — one per acceptance clause

All in `tests/test_undo_review_pilot.py`, [TESTED-ONLY].

| clause | pins |
|---|---|
| Yes offered only on a pre-verified scope | `test_prepare_refuses_without_a_scope`, `..._nothing_is_undoable`, `..._multi_operation_scope`, `..._source_is_gone`, `..._content_changed_since_the_operation`, `test_prepare_binds_the_snapshot_and_writes_nothing` |
| apply refuses totally on drift | `test_apply_refuses_totally_on_filesystem_drift`, `test_apply_refuses_on_row_drift` |
| No is terminal and edits stale it | `test_no_is_terminal_and_emits_one_plain_persona_line`, `test_apply_refuses_on_row_drift` |
| expiry lapses, never a Yes | `test_expired_ask_lapses_and_never_executes`, `test_prepare_purges_expired_asks` |
| single use | `test_single_use_token_is_consumed_before_execution` |
| bare undo byte-identical | `test_bare_undo_stays_byte_identical` |
| `cli.py` fallback untouched | `test_cli_direct_fallback_is_untouched` |
| refusals are legible | `test_unknown_tokens_are_refused`, `test_decision_must_be_yes_or_no` |
| Yes executes exactly one op | `test_yes_executes_exactly_one_operation` |

## DEFECTS FOUND

1. **Dead terminal branch (found in my own seam, fixed in `e7316b9`).** The first shape
   popped the ask on `yes`/`no`, which made the `used` guard unreachable: a replayed
   answer reported *"unknown undo ask — prepare a fresh one"*, which reads like a bad
   token and hides that a decision was already taken. Now consumed asks are kept until
   they expire, so a replay says *already answered*. No behaviour change to the
   execution path; the message is the whole fix.
2. **`src`/`dst` orientation is a trap.** `executor.py:462` swaps the operands, so
   `op["dst"]` is the CURRENT home. A pre-verify written the intuitive way refuses
   every genuine ask. Recorded because the same inversion will bite anyone extending
   this seam.
3. **The pilot is single-operation by construction.** A scope resolving to more than
   one row is refused with the count in the message rather than silently narrowed. The
   console must therefore present one operation per card. Whether batch apply follows
   the pilot is an owner decision (see OPEN QUESTIONS).
4. **The recently-modified guard makes fresh work un-undoable** (pre-existing,
   `executor.py:464–479`, not changed here). Right after a move or organise turn,
   targets are usually inside the guard window, so `prepare` legitimately answers
   *"nothing undoable in that scope"*. That is fail-closed and correct, but it means
   the pilot's first honest use is undoing older work; the console should not read that
   refusal as a fault. Pins age their fixtures by three days for exactly this reason.
5. **No version column** (deferred by the owner's answer 3). Drift is caught by
   re-reading the row and comparing `(id, ts, op, src, dst, sha256_before,
   sha256_after, status)` plus a filesystem re-check. A race that both hashes and
   status cannot catch would reopen that decision; none is demonstrated here.

Nothing else was touched: no `cli.py`, no `executor.py`, no `store.py`, no schema
change, no journal format change.

## NEXT GATE

**TASK 3 — producer-seam estimates, design only, no code.** Seven seams, one estimate
line each, additive producer fields only, no new RPC. This needs an owner grant that
*quotes the seven-seam list as its scope*; until that grant exists I write nothing.
The seam table lives in the console lane's Task A report
(`docs/phase-reports/console-2026-11-04-task-a-attribution.md`, commit `342fdd9`),
which **is not in this tree** — `git cat-file -t 342fdd9` → *not a valid object*. The
list must arrive from the order or that report; I will not reconstruct it from memory.

The console lane builds its review card against this commit (`e7316b9`) using
`docs/design/2026-11-04-undo-consent-seam.md` as the interface. No direct coordination.

## OPEN QUESTIONS

1. **Batch scope after the pilot?** Single-operation cards are a pilot limit, not a
   judgement. If the console's natural flow is "undo that turn's 12 moves", the pilot
   will refuse where the owner expects a review — say whether to plan a batch prepare
   (one ask, N operations, all-or-nothing drift check) before or after the pilot runs.
2. **Where does ask age come from on the card?** `prepare` returns `age_s: 0.0` at
   creation. A card rendered later must compute age from `prepared_at`/`expires_at`
   (or re-ask) — trusting the returned `0.0` would display a fresh ask that is nearly
   expired. The design note should state which is authoritative; the console lane owns
   the rendering.
3. **Journal shape for review events.** `undo.prepare`/`undo.apply` verdicts are bare
   tokens (`prepared`, `approved`, `declined`, `lapsed`, `drifted`) with the
   `ask_sha256` prefix inside `detail`. That follows the existing convention, but a
   later reader wanting structured fields would need a journal format decision.
4. **CLI parity timing.** Deferred by the owner. Until it exists, the containment
   statement above stands and the fallback stays an owner-typed G0-class direct action.
5. **Expiry boundary.** `UNDO_ASK_TTL_S = 600.0` is a class attribute measured on
   `time.monotonic()`; `prepared_at` in the response is wall-clock ISO. Both are pinned
   as returned, but if a future consumer compares them against each other it will be
   comparing two clocks — worth a note in the design doc if anyone does.
