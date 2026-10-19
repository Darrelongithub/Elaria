# Elaria change log for the adversarial hunt

Every repository change made during the hunt is recorded here. Bug details
and expected-vs-actual state live in `bugs.md`; this file is the chronological
record of code, test, fixture, and documentation changes.

## 2026-10-19 — pushed checkpoint `6733f17`

### Safety/executor fixes

- Replaced executor `shutil.move()` with no-overwrite destination creation:
  atomic hard-link placement for regular files when supported, symlink
  recreation for links, and exclusive-create copy fallback for cross-device
  or hard-link-unsupported filesystems.
- Split cross-device moves into copy → hash-verify → journal `copied` →
  unlink source → journal `committed`.
- Added `Journal.mark_copied()` and taught the store that `copied` is an
  outstanding intent and counts toward recent operation caps.
- Reused the same journaled move path for undo.
- Added `safety.is_safe_filename()` and enforced it for model-supplied
  `new_name` values in `planner_llm._parse_batch()` and again in the executor.
- Added executor validation for relative, non-escaping `dest` values and for
  resolved destinations staying inside the resolved organise root.
- Made `_Conflicts/` rerun `check_operation()` for its own candidate
  destination, use `lexists()` for collision selection, and refuse symlink
  escapes outside the root.

### Tests and fixtures

- Added `tests/test_bughunt_safety.py` covering randomized hostile trees,
  duplicate collisions, TOCTOU destination creation, `new_name` traversal,
  taxonomy and `_Conflicts/` symlink escapes, cross-device copy ordering,
  corrupt-copy source preservation, and strict-xfail repros for Areas A–C.
- Added `tests/bughunt_fixtures/evil_inputs.json` with traversal model
  output, must-not-act phrases, hostile filenames, and secret markers.
- Verification at that checkpoint: 224 passed, 9 xfailed; ruff clean.

## 2026-10-19 — wider hunt continuation (in progress)

- Created `bugs.md` as the reproduced-bug ledger and this file as the
  hunt change ledger.
- Began Areas D–G probes across planner/intents/config, store/memory/queue,
  audio/meeting/TTS, and daemon/IPC/CLI/persona surfaces. Entries below are
  appended as each probe becomes a committed test or fix.

### Immediate data-loss/wrong-record fixes

- `src/assistant/store.py`: escaped SQL `LIKE` metacharacters in
  `forget_facts()` (`\`, `%`, `_`) with `ESCAPE '\'`, fixing BH-E1.
- `src/assistant/meeting.py`: added exclusive-create copies, independent
  mic/system canonicalization, collision-suffixed meeting stamps across
  mic/system/note artifacts, and exclusive-create meeting notes, fixing
  BH-F4 and BH-F5.

### New hunt tests

- `tests/test_bughunt_systems.py`: added state-based repros/pass checks for
  planner batch exactness, boolean confidence, intent over/under-matching,
  string-as-sequence config, shared config defaults, malformed humour TOML,
  memory wildcard forgetting, raw FTS syntax, local-vs-network error
  classification, queue history starvation, crashed `running` jobs,
  store-less mode switching, missing ledger verification, concurrent queue
  drains, ASR empty fallback, WAV sample-rate reporting, PipeWire target
  guarding, meeting overwrite/channel copies, Piper config availability,
  TTS destination cache reuse, Live rotation, cleanup persistence, IPC
  event/reply interleaving, watcher debounce, speaker-threshold selection,
  and daemon review decisions.
- `tests/test_bughunt_safety.py`: added executor/organiser repros for
  plan/root mismatch, outside-root sources, invented destinations,
  nested already-filed flattening, destination directories, empty
  `ApplyReport.op_ids`, unreadable directories, and missing-root plans.
- `tests/test_bughunt_corpora.py`: added 738 parameterized boundary cases
  across safe filenames, protected paths, LLM verifier mutations, Tier 0
  rules, English/Kiswahili intent grammar and negation wrappers, cleanup
  marker-retention thresholds, persona tone ratios, PCM/embeddings maths,
  meeting segmentation, store search/forget punctuation, relative-time
  parsing, overlay states, TTS cache keys, blast radius, confidence
  decisions, shadow-cost rates, token estimates, and diarization overlap.
- `tests/bughunt_fixtures/evil_inputs.json`: added unsafe filename forms,
  action bases, negation/quotation wrappers, malformed LLM payloads, and
  FTS syntax attacks. Corrected the NUL filename to a JSON `\u0000`
  escape after the first edit produced a literal control byte.
- Applied ruff's import/order fixes to the two new hunt test modules.

### Bug ledger

- Populated `bugs.md` with BH-A5–A10, BH-B7–B9, BH-C3, BH-D1–D6,
  BH-E1–E7, BH-F1–F9, and BH-G1–G3, including fixed/open status,
  severity, minimal test repro, and expected-vs-actual state.
- Added `BUGHUNT.md` as the final summary/report linking the detailed bug
  and change ledgers.

### Verification

- Full keyless/mock suite: **973 passed, 5 skipped, 52 xfailed** from
  **1,030 collected** tests.
- Ruff over `src/` and `tests/`: all checks passed.
- `git diff --check`: clean.

## 2026-10-19 — post-merge follow-up: Python 3.14 + BH-E2 + BH-C3

Trigger: the keyless suite was run on Fedora/Python 3.14 after PR #1 merged
and came back **14 failed, 965 passed, 5 skipped, 46 xfailed**. Eight
failures were one CLI crash, five were BH-E2 and one was BH-C3, the last two
as `XPASS(strict)`. All three are fixed at the root cause; no test was
deleted and no strict-xfail marker was dropped without a real fix.

### BH-G4 — argparse help `%` (8 CLI subprocess failures)

- `src/assistant/cli.py`: escaped the `--allow-tripwire` help as
  `>tripwire%%`; it renders to the user as one `%`.
- `src/assistant/cli.py`: extracted parser construction from `main()` into
  `build_parser()` so the whole command tree can be built and rendered
  without a subprocess. `main()` behaviour is unchanged.
- Audited every `help`/`description`/`epilog`/`usage`/`metavar`/`prog`
  literal in `src/` (including `assist-voice-test`, whose parser is built
  inside its own `main()`): the audit reports the original line 622 as the
  only offender and is clean after the fix.
- New tests in `tests/test_daemon_cli.py`: render all 47 parsers in-process
  (`test_cli_every_help_string_renders`), assert the rendered help shows a
  single `%` (`test_cli_plan_apply_help_renders_a_single_percent`), assert
  `--help` exits 0 for 9 command groups as subprocesses
  (`test_cli_help_exits_zero_for_every_command_group`), and a tree-wide
  static audit run in a fresh interpreter
  (`test_no_unescaped_percent_in_any_argparse_help_string`). The first three
  fail on 3.11+ at format time and on 3.14+ at construction time, so the bug
  is caught on every supported Python rather than only on the one that
  validates eagerly.
- Verified against the real CPython 3.14.0 `Lib/argparse.py`: the original
  `main(["doctor"])` raises `ValueError: badly formed help string` (cause
  `TypeError: %o format: an integer is required, not dict`) from
  `add_argument()`'s new `_check_help()`; the fixed source constructs the
  parser and renders all 47 help outputs.

### BH-E2 — FTS5 search treated user text as syntax

- `src/assistant/store.py`: added `_search_terms()`, `_fts_match_expression()`
  and `_like_patterns()`. Search input is tokenized the way FTS5's default
  `unicode61` tokenizer does, then every term is emitted as a quoted string,
  so operators/quotes/parentheses can never reach `MATCH` as syntax. A
  query that is only punctuation yields no terms and returns `[]`.
- `src/assistant/store.py`: `search_documents()` now delegates to a shared
  `_search()`; an FTS5 `OperationalError` degrades to the LIKE arm instead
  of propagating (the module's stated "never crash" contract). The LIKE
  fallback escapes `\`, `%`, `_` with `ESCAPE '\'` and compares
  case-insensitively to match FTS5.
- `src/assistant/store.py`: added `search_documents_any()` for the OR arm.
- `src/assistant/memory.py`: `recall()` uses `search_documents_any(terms)`
  instead of hand-building `" OR ".join(terms)` and handing it to
  `search_documents()`, so OR semantics survive the quoting change.
- `tests/test_bughunt_systems.py`: replaced the empty-store xfail with five
  tests built on `_indexed_store()` — a **populated** index, because an
  empty one lets SQLite skip `MATCH` evaluation entirely, which is exactly
  how this bug hid as an XPASS on Fedora. They cover no-crash for the five
  BH-E2 queries, punctuation-as-text expectations (`(invoice` now *finds*
  the invoice document), unchanged plain-keyword search, a direct check that
  every generated `MATCH` expression is all-quoted and accepted by a
  populated FTS5 index, and the escaped LIKE fallback.

### BH-C3 — concurrent drains ran one job twice

- `src/assistant/store.py`: added `claim_cloud_job()` — a single conditional
  `UPDATE` from `pending`/`approved` to the target status that increments
  `attempts` and reports success from `rowcount`.
- `src/assistant/offline_queue.py`: `drain()` claims instead of
  select-then-update, and `continue`s past any job it fails to claim; the
  `awaiting_approval` transition is claimed the same way so only the drain
  that moved the job reports it.
- `tests/test_bughunt_systems.py`: the concurrency test now barriers both
  drains at the candidate-list boundary so they always compete for the same
  job instead of depending on scheduler luck, and asserts the handler ran
  once, `done` counts are `1`/`0`, final status is `done` and `attempts == 1`.
  Added `test_claim_cloud_job_lets_exactly_one_caller_win` for the primitive
  itself.

### Verification

- Sandbox interpreter is Python 3.11.2 (CPython 3.14 could not be installed
  here — the standalone-build host is not reachable), so the eager-validation
  half of BH-G4 was verified by running the actual CPython 3.14.0
  `Lib/argparse.py` against this tree rather than by running 3.14 itself.
- Environment facts recorded for BH-E2: `python 3.11.2`,
  `sqlite3.sqlite_version 3.40.1`, `Store.fts5_available True`; the BH-E2
  queries raise `OperationalError` on a populated index before the fix.
- Before (this sandbox, Python 3.11): **1 failed, 973 passed, 5 skipped,
  51 xfailed** (the 1 failure was BH-C3 as `XPASS(strict)`).
- After: **1001 passed, 5 skipped, 46 xfailed, 0 failed** — `uv run pytest -q`.
  1030 collected before, 1052 after (+22 regression tests).
- Strengthened concurrency test: **20/20 failures** against the unfixed code,
  **20/20 passes** with the fix.
- `uv run ruff check .`: all checks passed.
- `uv run assist doctor`, `assist doctor --json`, `assist cost`,
  `assist status --waybar`, `assist plan apply --help` all work;
  `status --waybar` exits 1 while `assistd` is down, which is pre-existing
  intended behaviour (`return 0 if status.get("running") else 1`).
- Still open, unchanged and deliberately out of scope: the
  `PytestUnraisableExceptionWarning` asyncio-cleanup noise in
  `test_unknown_method_is_an_error_not_a_crash` and
  `test_500_files_round_trip`. Warnings, not failures.
