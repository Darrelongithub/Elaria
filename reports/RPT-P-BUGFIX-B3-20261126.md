# RPT-P-BUGFIX-B3 — `BUG-B3` headless worker lifecycle (FIX-B3)

Owner: P · 2026-11-26 · base `c62015a` (main) · branch `arena/259d656e-elaria`

Scope: `reports/DISPATCH-BUGFIX-1.md` FIX-B3, `reports/BUGHUNT-B-20261126.md`
BUG-B3. Files touched — all P-owned:

- `src/assistant/hands/headless/worker.py`
- `tests/test_hands_headless_worker.py`
- `tests/test_hands_headless_host.py`

`OWNERS.yaml` untouched. Frozen thresholds untouched (the 60 s remote-control
timeout keeps its value; it is now a named constant `_RUN_TIMEOUT_S = 60`).

## What was wrong

`default_runner()` blocked in `proc.communicate(timeout=60)` and only then
returned `process=proc`; `Worker.execute()` appended that process to
`self._live` **after** the call returned. Consequences:

1. Every in-flight command (up to 60 s) was invisible to `terminate_all()`, so
   daemon death signalled **0** processes and left the worker running.
2. Finished `Popen` objects accumulated in `_live` for the host's lifetime
   (I10 violation), and `terminate_all()` guarded only on `pid is None` — it
   `killpg`-ed any tracked PID, including a reaped/recycled one.

## What changed

- **Track at spawn.** `Runner` now takes a fourth argument, `on_spawn`:
  `(argv, env, start_new_session, on_spawn) -> result`. `default_runner()`
  calls `on_spawn(proc)` immediately after `Popen` returns, *before*
  `communicate()`, so the worker is visible to `terminate_all()` for the whole
  life of the command. The contract is stated in the module docstring and in
  the `Runner` type alias.
- **Prune on exit.** `Worker.execute()` forgets every process it tracked in a
  `finally` block, so success, timeout and error paths all return the registry
  to baseline (I10). `Worker._live` is gone; the read-only
  `Worker.live_processes()` accessor is the only way to observe the set, which
  also removes the hand-append path the old tests used.
- **No unproven signals.** `ProcessTracker` (lock-guarded, identity-based
  removal) holds only processes that may still run. `terminate_all()` re-proves
  liveness per process (`poll() is None`; a process object that cannot report
  state, or reports exit, is pruned and skipped) before `killpg`, and forgets a
  process as soon as it has been signalled so a second death signal can never
  hit a recycled process group.

## Tests (regression, named after the bug ID, driving the real path)

`tests/test_hands_headless_worker.py`:

- `test_bug_b3_in_flight_process_is_tracked_and_terminated` — real
  `default_runner`, fake kitty `exec sleep 30`: `terminate_all()` mid-run
  returns 1, `execute()` returns `-15`, the registry is empty afterwards.
- `test_bug_b3_finished_process_is_pruned_after_execute` — no finished `Popen`
  retained; `terminate_all()` then returns 0.
- `test_bug_b3_terminate_all_does_not_signal_a_reaped_pid` — tracked object
  reports exit while its `pid` belongs to an unrelated live process: 0
  signalled, bystander survives.
- `test_bug_b3_terminate_all_skips_tracked_process_that_reports_exit` — same,
  called while the runner call is still in flight.
- `test_bug_b3_terminate_all_is_idempotent_with_no_processes`.

`tests/test_hands_headless_host.py`:

- `test_bug_b3_daemon_death_terminates_an_in_flight_worker` — `host.request()`
  through `default_runner` on a gated, blocking fake kitty; `on_daemon_dead()`
  returns 1, journals `daemon.death` with `processes_signalled=1`, registry
  empty afterwards.
- `test_bug_b3_stop_terminates_an_in_flight_worker` — same via `stop()`,
  `host.stop` row reports 1.

The two old masking tests (`test_daemon_death_terminates_workers_and_journals`,
`test_terminate_all_signals_tracked_process_groups`) are replaced: they
hand-appended to `worker._live`, which no longer exists.

## Evidence

Pre-fix (HEAD `c62015a` `worker.py`, new tests) — 6 failed, 1 passed:

```
FAILED tests/test_hands_headless_worker.py::test_bug_b3_in_flight_process_is_tracked_and_terminated
        AssertionError: execute() must track the process while it is still running  (0 == 1)
FAILED tests/test_hands_headless_worker.py::test_bug_b3_finished_process_is_pruned_after_execute
        AssertionError: a finished process must be pruned from the tracker  ([<Popen ...>] == [])
FAILED tests/test_hands_headless_worker.py::test_bug_b3_terminate_all_does_not_signal_a_reaped_pid
        assert worker.terminate_all() == 0  (1 == 0)   # bystander was SIGTERM-ed
FAILED tests/test_hands_headless_worker.py::test_bug_b3_terminate_all_skips_tracked_process_that_reports_exit
        assert worker.terminate_all() == 0  (1 == 0)
FAILED tests/test_hands_headless_host.py::test_bug_b3_daemon_death_terminates_an_in_flight_worker
        AssertionError: the host must see the worker while it is still running  ([])
FAILED tests/test_hands_headless_host.py::test_bug_b3_stop_terminates_an_in_flight_worker
        assert _wait_for_tracked(host.worker)  ([])
```

Post-fix: 23 passed (both files, 3 consecutive runs, no flakiness).

Slices green: `tests/test_hands_*.py tests/test_o_mouse_fixture.py
tests/test_o_typing_gate.py tests/test_nus_*.py tests/test_gate_fix_round.py
tests/test_task_k_gateway.py` → **385 passed**.

Full suite (sandbox, missing runtime deps): 3351 passed, 33 failed, 10 collection
errors — the identical 33/10 are present at unmodified HEAD
(`test_i_provider_routing`, `test_live_repro_arm_b`, `test_stream_*`,
`test_reach_*`, `test_j_*`, `test_capture_state_wire` all need `httpx` /
`google-genai`); none reference the headless worker. `ruff check` and
`ruff format --check` clean on all three files.

## Residual notes (not BUG-B3)

- `terminate_all()` reaps nothing itself: the `communicate()` call in the runner
  thread reaps the child, so no zombie is left behind. A signalled process is
  forgotten at signal time, so a later `stop()` after `on_daemon_dead()` reports
  0 signalled — intended, and it is what makes PID reuse unreachable.
- BUG-B7 (also P) covers the consent/journal ordering, watcher wiring and
  `runtime_dir` expansion in `consent.py` / `host.py` / `instance.py`; not
  touched here. Note for whoever fixes B7: with `daemon_alive` wired to the
  watcher, the BUG-B3 host tests keep the watcher inert (`daemon_alive=True`)
  and call `on_daemon_dead()` / `stop()` explicitly, so they stay deterministic.
