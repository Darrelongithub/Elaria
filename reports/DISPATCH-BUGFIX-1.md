# DISPATCH-BUGFIX-1 — P0 fixes from Hunter B (manager, 2026-11-26)

Hunter B (PR #146) reproduced three P0s in the hands/mouse safety
core. They are fixed BEFORE Hunter A lands and before any further
feature work — these gates are the load-bearing walls. Each fix:
a regression test **named after the bug ID** that fails before and
passes after, full hands/mouse slices green, frozen thresholds
untouched, merged PR or it didn't happen.

## FIX-B1 — Agent O · `BUG-B1` · gate tier misclassification

> You are Agent O. Fix `BUG-B1` in
> `reports/BUGHUNT-B-20261126.md` (`src/assistant/hands/gate.py`):
> `GateChecker.derive()` returns tier 2 for forbidden tier-3
> actions — (1) `argv[0]` skipped by `paths()` so control/credential
> paths pass and leak into disclosures; (2) relative shebang script
> paths skip the sandbox check; (3) wrapper binaries (`timeout`,
> `systemd-run`, …) and GNU long-flag forms (`rm
> --recursive=always`) evade the shell/recursive checks; (4) `curl`
> exfiltration shapes (`file://`, attached `-o/path`,
> `--data=@file`, `--data-binary @file`) evade upload detection.
> Rule for the fix: argument *shapes* are unbounded — classify on
> resolved semantics (canonicalised paths incl. argv[0], unwrapped
> launcher chains, normalised flag parsing), defaulting to tier 3
> on anything unrecognised, never tier 2 by omission. Every repro
> in the bug entry becomes a regression test (`test_bug_b1_*`).
> Sync main first. New `arena/*` branch, merged PR. Never edit
> OWNERS.yaml.

## FIX-B2 — Agent O · `BUG-B2` (+B4) · mouse digest replay & stale verification

> You are Agent O. Fix `BUG-B2` and `BUG-B4` in
> `reports/BUGHUNT-B-20261126.md`: (1) tier-3 `plan.digest` must
> bind errand + expiry — a digest is claimable exactly once,
> globally (not per-errand); the 12-click budget is per-digest,
> not per-errand; click counts reject `bool`/non-`int`;
> `run_mouse_fixture()` must check `queue.current(errand, digest)`
> before executing; parked asks get an enforced TTL. (2) Post-click
> verification must not pass on stale/cached frames (frame must be
> captured after the click it verifies), and loop detection must
> catch periods ≥ 4, not only `recent[-3:]`. Regression tests
> `test_bug_b2_*`, `test_bug_b4_*` from the repros. Sync main
> first. New `arena/*` branch, merged PR. Never edit OWNERS.yaml.

## FIX-B3 — Agent P · `BUG-B3` · headless worker lifecycle

> You are Agent P. Fix `BUG-B3` in
> `reports/BUGHUNT-B-20261126.md`
> (`src/assistant/hands/headless/worker.py`): subprocesses are
> tracked only AFTER exit, so daemon death leaves live workers
> unsignalled while `terminate_all()` can signal dead/recycled
> PIDs, and `_live` leaks finished `Popen` objects (I10). Track
> the process at spawn, prune on exit, never signal a PID whose
> process object hasn't proven liveness. ALSO fix the masking
> tests (`test_hands_headless_host.py`,
> `test_hands_headless_worker.py`): they hand-append to `_live`
> instead of exercising `execute()` — rewrite them to drive the
> real path, named `test_bug_b3_*`. Sync main first. New `arena/*`
> branch, merged PR. Never edit OWNERS.yaml.
