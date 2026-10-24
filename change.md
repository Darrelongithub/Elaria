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

## 2026-10-20 — voice hunt fixes: Gates A–D

Trigger: the voice-pipeline hunt (`VOICE-BUGTEST.md`) reported 13 defects (plus
two unpinned observations). The owner ordered the fixes in mandatory gate order —
voice identity first, then "speaks when she should", then session behaviour, then
integrity and surfaces — with each strict-xfail pin converted into a passing
regression and no gate starting before the previous one was green.

### Gate A — voice identity (`3d2b9e5`)

- `tts.py`: `_cache_path(text, descriptor, backend, *, identity=None)` plus
  `_route_cache_path()` and `cloud_cache_identity()`. The cloud route keys on
  `[gemini] voice` + `model_voice` + `voice_sample_rate`; the dormant local route
  keeps voice/model/speaker/length_scale. Neither route can poison or invalidate
  the other (VB-1, and the key half of VB-2).
- `tts.py`: deleted `_ack_path`'s local-backend fallback and its
  "a warmed local copy beats silence" comment (VB-3). A miss now returns
  `cache_miss` + `warning` + `rewarm_needed`, and `ack_cache_state()` (new,
  surfaced as `status["ack_cache"]`) is the single source for "which of the four
  acks exist *for the identity that is live*" — so `cached_acks` can no longer
  call a Piper file healthy on a Gemini route.
- `config.py`: `canonical_voices()` / `resolve_voice()` and the new
  `[gemini] allowed_voices` default `["Flare"]` — the one-voice rule as data.
  Absent means the shipped answer (a typo in `voice` cannot widen the rule); an
  explicit empty list is honoured as "refuse everything".
- `tts.py`: `voice_identity()` + the gate at the top of `voice_route()`;
  `gemini_client.voice_request()` reports `voice_allowed` / `voice_requested` /
  `canonical_voices` and `generate_voice()` raises on a non-canonical voice, so
  no caller can bypass the pin (VB-4).
- `cli.py`: `voice routing` is now a **FAIL** (not a warning) with
  `VOICE IDENTITY REFUSED — … SILENT until that is fixed`, names the ack-cache
  state, and prints the legacy-`tts.selected_voice` precedence line; the summary
  counts failures.
- Docs: README gains "Her voice: one name, pinned, with documented precedence"
  and the stale phase-8 claims ("both online/offline spoken replies use the same
  configured local voice", "identical TTS backend+voice in both modes") are
  replaced with the amended contract; `config.toml.example` documents
  `allowed_voices`, `voice_sample_rate`, and the precedence order.

### Gate B — speaks when she should (`d63f0de`)

- `tts.py`: `request_rewarm()` / `take_rewarm_request()` / `warm_due()`; a miss
  from `cached_ack()` *is* the trigger. `play_ack()`'s miss branch keeps its
  budget (never synthesises) but reports the condition.
- `daemon.py`: `run()` creates the warm task **before** `serve(...)`; `_ack`
  queues a would-be miss behind the in-flight warm through `_await_ack_cache()`
  (bounded 2 s, pending-aware so a daemon driven without `run()` never waits);
  `_schedule_rewarm_if_requested()` turns a reported miss into one background
  cycle; `speech.warm` opens the gate so `assist voice warm` stays the cure
  (VB-13, and the healing half of VB-2).

### Gate C — session behaviour (`c1469cc`)

- `transcribe.py`: `SilenceLadder` gains `resume_s` (sustained speech before a
  re-arm) and `grace_s` + `close_due()`; `dictate()` closes on the grace, emits
  `session.grace_close` and notes why (VB-5, VB-6).
- `transcribe.py`: rotation consumes only the `go_away` markers and `_final_texts()`
  folds the replayed tail's immediately-repeated segment, so the head of a long
  dictation survives (VB-7, data-loss).
- `daemon.py`: the refused `_ptt_start` loser returns
  `suppressed: "already listening — no second ack"` with no ack queued (VB-11);
  `MUTATING_INTENTS` + `_command_gate()` sit between a command-mode transcript and
  `intents.route()` (VB-8).
- `config.py` / `config.toml.example`: `[transcribe] speech_resume_s`,
  `checkin_grace_s`, `command_min_confidence` (0.85), each commented with the
  finding it exists for.

### Gate D — integrity and surfaces (`b058ea2`)

- New `src/assistant/proc.py`: `child_kwargs()` (PR_SET_PDEATHSIG + own session),
  `audio_child_names(config)` (stock names **plus** the configured
  `[tts] player`), `orphaned_audio_children()`, `reap_orphans()`, `pid_alive()`.
- `tts.play_audio` and `capture.PipeWireCapture.frames` spawn through it; the
  daemon sweeps leaked audio children before it serves; `assist doctor` gained an
  `orphaned audio` **FAIL** check naming pids and the cure; `assist voice cleanup`
  is a local-only command (it must work with the daemon dead) and exits non-zero
  if anything survives. `systemd/assistant.service` states both mechanisms
  explicitly and warns against `KillMode=process`.
- `voicetest.py`: `voiceprint_health()` + `voiceprint_path(config)` +
  `BIOMETRIC_FILE_MODE`, and `enroll()` chmods 0600 as it writes; `[voice_test]`
  gains `voiceprint_path`, `embedding_dim` (192) and the optional
  `embedding_model` the doctor validates against (VB-9).
- `waybar.py`: `format_voice_line()` replaces the hardcoded `voice: local …`
  label (VB-14).

### Test-side changes (all deliberate, none deleted)

- 13 strict-xfail pins converted into passing regressions: `test_a3_…`,
  `test_b7_…`, `test_b7c_…`, `test_b5b_…`, `test_b5c_…` (VB-4, VB-1, VB-3, VB-2,
  VB-13) plus `test_c9_…`, `test_c9b_…`, `test_d11b_…`, `test_d13b_…`,
  `test_g19_…`, `test_e14_…`, `test_g18_…` (VB-5, VB-6, VB-7, VB-8, VB-11, VB-9,
  VB-10) and `test_a4c` (VB-14).
- New guards: `test_a3b` (transport-level refusal), `test_b5d`/`test_b5e`
  (self-heal within one warm cycle, service and daemon level), `test_b5cb`
  (real `Daemon._ack` with an injected slow warm: cached, waited, bounded),
  `test_g18b` (reaper names a planted parentless child under a private name so the
  suite never signals the owner's real audio processes), `test_e14c` (healthy
  template passes / absent warns / dimension+model mismatch fails / enroll lands
  0600), `test_b5f` (skipped needs-live placeholder for the online boot window).
- `test_g19_double_hotkey_acks_once` had carried the clock-jump/rotation body
  under the wrong name with the VB-11 marker attached — the mislabel hid a
  fixture too short to cross the age cap. It is now
  `test_g20_clock_jump_does_not_fire_and_the_rotation_cap_holds` with a cap it
  really crosses, and the real VB-11 double-press test exists.
- The file's `Session` fake now emits the `turn_complete` the real transport sends
  (`live_client.py:108-114`) and closes its event stream on it: every session test
  had been burning the full 15 s final-transcript timeout. Whole-suite wall time
  73 s → 32 s.
- Two existing contract tests updated, each commented at the assertion:
  `test_phase1_dictation.py::test_silence_ladder_asks_once_per_segment` (a single
  frame above the gate no longer re-arms — VB-5's rule) and
  `test_phase8_offline_voice.py::test_forced_offline_daemon_paths_make_zero_gemini_calls`
  (an offline command transcript at 0.30 confidence is now **refused**: transcript
  kept, cloud redo queued, nothing routed — VB-8's gate replaces "any local
  confidence climbs the ladder").
- `VoiceConfig`-adjacent helpers in `tests/test_voice_bughunt.py` gained
  `allowed_voices` handling; `EchoClient` now mirrors the real client's
  canonical-voice resolution, so an identity bypass at any call site surfaces.

### Verification

- Full suite, complete run: **1069 passed, 6 skipped, 46 xfailed, 0 failed**
  (`PYTHONPATH=src pytest -q tests/ --tb=line -p no:randomly`, 32 s). Baseline
  before this work: 1044 passed, 5 skipped, 59 xfailed. The known
  pytest-9.1.1/3.11 traceback-render crash did not recur once the strict-xfails
  were gone; `-p no:randomly` is still used because the crash was only ever
  triggered by xfail traceback rendering.
- `tests/test_voice_bughunt.py`: **59 passed, 1 skipped, 0 xfailed** — zero
  `xfail` markers left in the file.
- Every converted guard re-proved against pre-fix source: Gates A/B via a
  `git worktree` at `9b0e4dd` (10 failed / 1 passed), Gates C/D via `git stash`
  (5 failed / 0 passed and 10 failed / 1 passed respectively).
- `ruff check src tests`: all checks passed.
- Latency re-measured after the changes (`/home/user/measure_voice.py`, mock
  backend, real fork+exec player): warm ack median 1.394 ms (p95 1.642), after
  restart 1.387 ms, **after a dormant-only change 1.388 ms with a cache hit** —
  the number that used to be 0.063 ms of silence — cold miss 0.046 ms, re-warm of
  four acks 0.5 ms, end-to-end `ack` over a real Unix socket median 2.65 ms
  (p95 3.21 ms) against the 300 ms budget.
- Still needs-live, never faked: the ear-level confirmation that a widened
  `allowed_voices` really changes her sound, the online size of the boot-warm
  window, real PipeWire orphan behaviour after `kill -9`, and the comfort of
  `speech_resume_s` / `checkin_grace_s` on real narration. See the needs-live
  list in `VOICE-BUGTEST.md`.

---

## 2026-10-20 — Full-repo hardening pass (Stages A–D & Phases 0–8, `arena/86517426-elaria`)

### Part 1 — Hunt (`tests/test_stage_abcd_bughunt.py`, `BH-H1`..`BH-H22`)

Added 35 adversarial tests in `tests/test_stage_abcd_bughunt.py` covering Stage A
(voice), Stage B (console & class mode), Stage C (knock & initiative), Stage D
(show-off & disclosure), and cross-cutting invariants (executor tree-hash fuzzing
under collisions/nested dirs/Unicode, IPC malformed frames, two-daemon socket
protection, config schema parity, clock jumps, SQLite corrupt state & concurrent
WAL writes, `ENOSPC` disk-full atomic WAV recovery, clean daemon/collector
cancellation, and README CLI command verification).

### Part 2 — Strengthen Weak Code & Resolve All 39 Open `xfail` Bugs + `BH-H1`..`BH-H22`

Fixed in severity order across three commits:

1. **Class 1 (`0176d8d` — CRITICAL/HIGH: data-loss, security/privacy boundary, wrong-action)**:
   - `src/assistant/safety.py`: expanded `$VAR` in `expand()` (`BH-A4`); rejected
     directory-occupied destinations in `check_operation()` (`BH-A9`).
   - `src/assistant/executor.py`: enforced plan-root vs spec-root identity (`BH-A5`),
     source-within-root containment (`BH-A6`), frozen taxonomy validation (`BH-A7`),
     nested already-filed preservation (`BH-A8`), `ApplyReport.op_ids` tracking (`BH-A10`),
     crash-interrupted `intent`/`copied` undo reconciliation (`BH-B1`), partial copy
     unlink on error (`BH-B2`), mandatory scope on `Executor.undo()` (`BH-B3`),
     pre-syscall `is_halted()` check (`BH-C1`), and `is_halted()`/`is_protected()`
     enforcement in `trash()` (`BH-C2`). Added empty-taxonomy-dir cleanup on undo
     when a plan created the directory.
   - `src/assistant/planner_llm.py`: rejected duplicate/missing paths and `bool`
     confidence in `_parse_batch()` (`BH-D1`).
   - `src/assistant/showoff.py`, `src/assistant/disclosure.py`, `src/assistant/daemon.py`,
     `src/assistant/store.py`: hardened show-off entry against replayed/non-live
     owner recordings (`BH-H15`), required biometric verification for owner turns
     during show-off (`BH-H16`), made `exit_owner()`/`exit_hotkey()` idempotent
     across timeout races (`BH-H17`), blocked symlinks in `demo_target()` (`BH-H18`),
     expanded `sensitive_values()` to catch colon/paraphrase leaks (`BH-H19`), and
     persisted `guests_heard` incrementally while purging demo audio residue in
     `recover_unclosed()` (`BH-H20`).
2. **Class 2 (`810bab4` — HIGH/MEDIUM: crash-unsafe, resource/socket/DB recovery, races)**:
   - `src/assistant/indexer.py`, `src/assistant/organiser.py`, `src/assistant/watcher.py`:
     used `lstat()`/`is_symlink()` first to skip broken symlinks and FIFOs (`BH-B4`, `BH-B5`),
     refreshed `never_send` on unchanged files (`BH-B6`), preserved known documents
     under unreadable directories (`BH-B8`), failed plans on missing/unreadable
     roots (`BH-B9`), and restarted watcher debounce on subsequent writes (`BH-B7`).
   - `src/assistant/config.py`, `src/assistant/modes.py`, `src/assistant/offline_queue.py`,
     `src/assistant/gemini_client.py`: caught `TOMLDecodeError` in `load_humour_profile()`
     (`BH-D6`), excluded local filesystem `OSError`s from `looks_like_network_failure()`
     (`BH-E3`), queried `pending`/`approved` jobs directly and recovered crashed
     `running` jobs in `CloudQueue.drain()` (`BH-E4`, `BH-E5`), supported in-memory
     state in `ModeManager(store=None)` (`BH-E6`), and recorded `verified=1`/`0` on
     `llm_calls` (`BH-E7`).
   - `src/assistant/asr.py`, `src/assistant/capture.py`, `src/assistant/transcribe.py`,
     `src/assistant/tts.py`, `src/assistant/ipc.py`, `src/assistant/daemon.py`,
     `src/assistant/initiative.py`: continued ASR fallback on empty text (`BH-F1`),
     used `self.sample_rate` in `WavSink.close()` (`BH-F2`), rejected numeric
     `object.id` targets in `pw_record_pcm_stream_command()` (`BH-F3`), reset
     session-age clock on rotation (`BH-F6`), persisted raw transcript before
     cleanup (`BH-F7`), checked `.onnx.json` in `PiperTtsBackend.availability_error()`
     (`BH-F8`), avoided reusing explicit `dest` across different texts (`BH-F9`),
     validated review item existence in `_review_decide()` (`BH-G2`), skipped event
     lines in `ipc.call()` (`BH-G3`), wrote WAVs atomically and reported Live
     disconnects (`BH-H1`), injected active conversation history into `Daemon._ask()`
     (`BH-H5`), added read timeout in `subscribe_events()` and `await w.drain()` in
     `broadcast()` (`BH-H6`), re-checked `voice_route()` before `play_audio()`
     (`BH-H7`), respected `speech.status()["muted"]` and persisted openers in
     `InitiativeService.accept()` (`BH-H10`), and prevented a second daemon from
     unlinking a live socket while handling non-dict JSON frames (`BH-H21`).
3. **Class 3 (`e4108b5` — MEDIUM/LOW: wrong-behaviour, logic, catalogue TTL, config schema)**:
   - `src/assistant/intents.py`, `src/assistant/voicetest.py`, `src/assistant/asr.py`,
     `src/assistant/config.py`: narrowed `cost` intent regex (`BH-D2`), added polite/emphatic
     `halt` variants (`BH-D3`), normalized string `taxonomy`/`languages` (`BH-D4`),
     deep-copied `DEFAULTS` in `_deep_merge()` (`BH-D5`), and selected the separation
     midpoint in `suggest_threshold()` (`BH-G1`).
   - `src/assistant/voice_catalogue.py`, `src/assistant/tts.py`, `src/assistant/presence.py`,
     `src/assistant/initiative.py`, `src/assistant/cli.py`, `config.toml.example`:
     enforced catalogue cache TTL and upstream voice removal checks (`BH-H2`),
     canonicalized voice case and prevented unapproved voice leakage (`BH-H3`),
     stopped legacy `model_voice` default from shadowing `gemini_voice_model` (`BH-H4`),
     handled overnight schedules and rejected `bool` days (`BH-H8`), enforced
     `urgent_in_class_mode` and `knock["silent"]` (`BH-H9`), deactivated commitments
     (including `parent_commitment_id`) on `decline()` (`BH-H11`), normalized
     punctuation in `_topic_key()` and retired topics across 3 ignored knocks (`BH-H12`),
     expanded `NEEDY_PATTERNS` (`BH-H14`), and fixed `config.toml.example` `[quota]`
     scoping + added `validate_config()` in `run_doctor()` (`BH-H22`).

### Part 3 — Remove Dead Code

Removed 12 unused definitions across 10 modules (proven with 0 external references
and `vulture src/ --min-confidence 80` clean):
- `src/assistant/asr.py`: `PhasePending`
- `src/assistant/capture.py`: `pw_record_command`, `FileCapture`
- `src/assistant/disclosure.py`: `is_owner_probe`, `_PROBE_PATTERNS`, `DisclosureService.guest_prompt`
- `src/assistant/executor.py`: `Executor.assert_demo_path`
- `src/assistant/initiative.py`: `InitiativeService.find_commitment`
- `src/assistant/offline_queue.py`: `capability_for`
- `src/assistant/proc.py`: `supported`
- `src/assistant/store.py`: `Store.update_holding`
- `src/assistant/transcribe.py`: `SilenceLadder.asked`
- `src/assistant/voicetest.py`: `FrameSource`

### Final Verification

- `pytest -q --tb=line`: **1,275 passed, 6 skipped, 0 xfailed, 0 failed, 0 warnings**
  (baseline `36f0618`: 1,194 passed, 6 skipped, 46 xfailed, 9 warnings).
- `ruff check .`: **All checks passed!**
- `vulture src/ --min-confidence 80`: **0 unused definitions.**


## 2026-10-20 — BUG 6: live dictation stop hang + in-session echo loop

Trigger: owner repro after the Bug 1–5 pass. `assist dictate` → "Listening…" →
Enter blocked in the `ptt.stop` IPC recv for the 90 s client timeout (Ctrl-C
needed), leaving `dictation_active=false`, `last_transcript=null` and no dictate
turn. During the session she looped her generic line at herself: the BUG5 guard
mutes capture around *local* playback, but the Live session's own output audio
plays while the mic uplink into that same session stays open.

### Release path

- `daemon.py`: `_ptt_stop` no longer awaits dictation. It sets the stop event,
  clears `_dictation_task`, and returns immediately with `processing`, the
  `session_id`, and `result: null`. The slow half (final transcript, cleanup,
  command routing) moved to `_finish_dictation`, a tracked background task that
  broadcasts `ptt.result` and status when done. `wait_s` is an explicit,
  bounded opt-in for scripts/tests; the hotkey path never sets it.
- `daemon.py`: release emits **no spoken ack** (`speak=False`). It is a stop,
  not a request to be talked to, and it must not wait on the boot ack warm.
- `daemon.py`: new `ptt.result` IPC method (by session id, optional `wait_s`),
  `status.dictation_processing` / `status.ptt_session_id`; `_session_active()`
  includes the processing window so parked mode switches still wait. Session
  results are keyed by id (last 8), and a finisher from an older session cannot
  set the mode idle, clear the new session's processing flag, or release a
  parked mode switch under a newer dictation.
- `cli.py`: `assist dictate` acks the release, then asks `ptt.result` for the
  transcript, so the turn is printed without the stop call blocking. `assist
  ptt stop` stays immediate; `--wait` opts into the transcript.

### Live half-duplex (in the session, not around `play_audio`)

- `live_client.py`: `LiveDuplexGate` — output audio closes the uplink for its
  duration (chunks extend sequentially, so a burst still reserves the full
  audio) plus a 400 ms guard. Duration is injected-clock friendly; unknown
  length stays closed until `playback_ended`.
- `live_client.py`: `DuplexLiveTransport` wraps any transport. `send_audio`
  refuses frames while the gate is closed or while an external probe (the
  daemon's local-TTS `is_speaking`) reports playback. Output audio drives the
  gate; output transcription is surfaced as `output_interim`/`output_final`
  and recorded for echo matching; input `interim`/`final` during playback or
  matching her own words become `echo_suppressed`, never user turns.
- `live_client.py`: `GenaiLiveTransport` parses `model_turn` inline audio and
  `output_transcription` into `output_*` events. `RecordingTransport` records
  output audio as bytes/hash/duration only; fixtures replay the duration.
- `live_client.py`: `SelfHearingLiveTransport` — the owner repro as a fake
  session: plays output audio for its real duration and transcribes every frame
  it still receives during that window back as user speech.
- `transcribe.py`: dictation wraps its factory in `DuplexLiveTransport`,
  forwards the daemon's playback probe, and checks the same gate before adding
  a frame to the rolling replay buffer, the silence ladder or the uplink.
  Gated frames are discarded (not held: holding would upload the echo when
  playback ends) and are not written to the saved WAV — that file is the
  batch fallback's source, so recording her own line there would re-enter it
  as user text whenever Live failed. Only input events enter the transcript
  record, so output audio/text can never become a final. Emits
  `live.uplink_gated`, `live.output_audio`, `live.output_transcript`,
  `live.duplex`, and notes the dropped frames in the session result.

### Cost / failure attribution

- `transcribe.py`: Live connect and rotation failures now write their own
  ledger row (`housekeeping:transcribe_live`, `live <stage>: <error>`), and
  successful live sessions carry the collected failure text. Previously a
  failed Live connect that fell back to batch left no trace, which is exactly
  the "silent Live failure" the month's 5-failure count could not exclude.
- `store.py`: `log_llm_call` defaults a missing purpose to the role (never
  NULL); new `failure_summary_since` groups failed rows by purpose, role,
  model, mode and error.
- `cost.py`: `classify_failure` (key / voice / quota / network /
  live_transport / parse / unknown) and `summarise_failures`;
  `format_cost_report` prints "Failures this month: N (key …, voice …)" with
  one row per purpose+error and a loud `LIVE failures: N` line when any Live
  path failed. Untagged legacy rows are reported as a ledger bug.
- `daemon.py` / `cli.py`: `cost` includes `month.failures_detail`, daemon up or
  not, so the 5 failures can be confirmed as key/voice housekeeping by reading
  `assist cost` instead of trusting a count.

### Tests

- `tests/test_bug6_live_duplex_and_stop.py` (10 tests): `ptt.stop` < 2 s while
  a Live turn is in flight with async delivery; gate timing (playback + 400 ms,
  unknown-length playback); transport refuses frames during playback and local
  playback; output transcription never a user final; the simulated
  self-hearing session yields zero user turns / zero transcript segments and
  the same double does echo without the gate (control); a finished previous
  session cannot clobber the next dictation; the real `assist dictate`
  subprocess prints a turn; cost rows/purpose tags/report.
- Existing PTT round-trip tests use the explicit `wait_s` opt-in.
- `pytest -q`: **1,290 passed, 6 skipped**.

## 2026-10-20 — Hardening pass 2 (BH-I1…BH-I13, `arena/8952fe51-elaria`)

Baseline measured before any edit (`25179c8`): **1,280 passed, 6 skipped,
0 failed**; `ruff check .` **17 errors**; `vulture src/ --min-confidence 80`
**1 finding**.

### Config (BH-I1, BH-I2)

- `Config.explicit_keys` / `Config.explicit(section, key)`: `load_config()`
  records which keys the owner's TOML actually named, so precedence decisions
  can use intent instead of value equality. `voice_model()` now gives an
  explicit `gemini_voice_model` priority over a stale `model_voice`; the alias
  is still read when it is the only key. Removed the legacy default is named by
  a constant (`REMOVED_TTS_MODEL`) rather than an inline literal.
- `Config.section()` returns `{}` for a non-table section; `humour_profile_path()`
  no longer assumes `str`; `organise_roots()` validates every entry and raises a
  named `TypeError`/`ValueError` (`path` required, `mode` in shadow|live,
  taxonomy shape).
- `validate_config()` rewritten from scratch. It now enumerates the known
  sections/keys (unknown keys and deprecated keys are named warnings, not
  silence), rejects non-table sections, validates enums (`gemini.mode`,
  `connectivity.mode`, `tts.online_voice`, `tts.offline_voice`, `tts.backend`,
  `organise.mode`), types (`allowed_voices` list, booleans), ranges (speaker,
  length_scale, sample rates, chunk_ms, confidences, health_port,
  console.history_limit, snooze_hours, retire_after_ignores, showoff.timeout_s,
  transcribe timings), `[class_schedule]` days and `HH:MM` times, audition ids,
  and `[quota]` rows (`rpm|tpm|rpd` numeric or `"unlimited"`). The doctor's
  `config schema` check consumes the same function.
- Deleted `config._file_sections`: after the rewrite it had zero callers
  (`grep -rn _file_sections` → 0 hits outside git history).

### Daemon, speech, sessions (BH-I3, BH-I4, BH-I5, BH-I12)

- Daemon constructs `SessionService(..., history_limit=<console.history_limit>)`
  (poisoned value falls back to 200; `validate_config()` names the key).
- Replaced the duplicated speech paths with `_speak_once()` (one synthesis, one
  half-duplex flag, `finally` clears it) and made `_maybe_speak_reply()`
  `await asyncio.wait_for(asyncio.shield(task), 1.5)`, so a timeout keeps
  waiting on the same task instead of starting a second `speak()`.
  Deleted `_speak_reply_async()` — zero references remained after the merge.
- `_is_echo()` reverse containment now requires ≥3 words.
- Added `Daemon._chat_timeout_s = 4.0` and `_generate()`: every chat call
  (owner turn and guest turn) is bounded, and the test-double `TypeError`
  fallback lives in one place. `_guest_turn` returns a spoken fallback on
  timeout; `_ask` uses `_generate()` and raises `live.timeout`.
- `_broadcast` no longer swallows subscriber failures with `pass`: it drops the
  subscriber and prints why. Corrupt relationship-state rows print their error
  instead of vanishing.

### Store and initiative (BH-I7, BH-I7b)

- `Store.deactivate_facts(ids)`: one public transaction for declined
  commitments. `InitiativeService.decline()` no longer touches `store._lock` /
  `store._conn`.
- `initiative.status()["latest"]` is `pending[0]` (newest; the query is id DESC).
- A due knock that cannot be raised writes a `knock_due_refused` persona event
  (id, topic, reason) instead of `except InitiativeError: continue`.
- `snooze()` rejects non-finite/negative hours (`math.isfinite`), which could
  previously produce an unsatisfiable `until` or a past deadline.
- Added `math` import; removed the raw SQL that duplicated `deactivate_facts`.

### IPC, Waybar, console (BH-I8, BH-I9, BH-I13)

- `ipc.serve()` takes an exclusive `flock` on `<socket>.lock` (module-level
  `_acquire_daemon_lock`/`_release_daemon_lock`), releases it on any bind
  failure, and releases it from the server's `close()` wrapper. Second daemons
  raise `RuntimeError("another daemon is already running …")`; a stale lock file
  from a dead process is harmless because the kernel drops the lock.
- `call()` parses replies through `_parse_reply_frame()`, which raises
  `DaemonUnavailable` with the offending frame prefix instead of leaking
  `JSONDecodeError`/`AttributeError`. `_write_reply()` bounds `drain()` at 5 s
  and treats a missed deadline as a disconnect.
- Added `ipc.parse_event_line()`; `subscribe_events()`, `waybar.stream_waybar()`
  and `console.follow()` share it and skip non-object frames.
- Waybar module docstring class list now includes `company` and `showoff`
  (both emitted by `format_waybar()` and styled in `ui/waybar/style.css`).
- Removed now-unused `json` imports in `waybar.py` and `console.py` (ruff F401).

### Show-off (BH-I6)

- `_reconcile()` no longer globs `data_dir/audio`. It calls
  `_purge_sandbox_audio()`, which walks only `self.sandbox_path()` (never if it
  is a symlink), removes `DEMO_AUDIO_SUFFIXES`, logs `residue_purged` /
  `residue_purge_failed` persona events, and leaves dictation/meeting WAVs
  untouched.
- Corrected `test_bh_h20_showoff_crash_exit_residue_cleaned_on_restart`:
  the old test asserted deletion of `data_dir/audio/*.wav`, i.e. it encoded
  BH-I6 as the expected contract. It now plants a demo file in the sandbox and a
  meeting recording in `data_dir/audio`, and asserts the first is purged and the
  second survives. Corrected (not deleted) because the remaining BH-H20
  assertions — session closed, `exit_reason="daemon_restart"`, `audio_retained=0`,
  `guests_heard=1` — are still the contract.

### TTS and voice catalogue (BH-I2, BH-I9, BH-I10)

- `tts._as_int()` / `_as_float()` coerce descriptor fields with clamps
  (`speaker >= 0`, `length_scale > 0`, default 0.92) on both
  `VoiceDescriptor.from_dict()` and `descriptor()`; poisoned values no longer
  raise `ValueError: invalid literal for int()` inside status/speak.
- `play_audio()` catches `subprocess.TimeoutExpired` and `OSError`, records the
  reason in `last_voice_error`, and returns `False`.
- `voice_catalogue.load_cached()` refuses rows without `retrieved` when a max
  age is requested; `resolve_catalogue()` treats `refresh=True` with
  `fetched=None` as "attempted but failed" and returns the verified cache,
  annotating the baseline only when no cache exists.
- `initiative.NEEDY_PATTERNS` gained 8 paraphrases (BH-I11).
- One test was added *with* its tightening rather than before it:
  `test_catalogue_refresh_uses_stale_verified_cache_before_baseline`
  (BH-I10). The original BH-I10 contract ("a failed refresh must fall back
  to the verified cache") was pinned red-first; the stale-beyond-TTL case
  is a deliberate strengthening of that same contract.

### Dead code removed (proof: `ruff F401`, `vulture`, or `grep` = 0 references)

- `src/assistant/config.py`: `_file_sections` (0 callers after rewrite).
- `src/assistant/daemon.py`: `_speak_reply_async` (duplicate speech path; 0 refs),
  `is_simple_turn` import (ruff F401).
- `src/assistant/transcribe.py`: `from pathlib import Path as _P` inside
  `_finalize` (unused; vulture 90 %).
- `src/assistant/waybar.py`, `src/assistant/console.py`: `json` imports (F401).
- `tests/test_bugs_1_to_5_regressions.py`: 7 unused imports plus one unused
  unpack (ruff F401/RUF059). No assertions changed.
- `tests/test_hardening_pass2.py`: unused `os` import and a bare expression.

### Tests

- Added `tests/test_hardening_pass2.py` (28 cases, sandbox-only, fake UNIX
  sockets and fake transports; no real key, voiceprint, or user folder).
  Pre-fix run: **24 failed, 4 passed**.
- Suite after fixes: **1,308 passed, 6 skipped, 0 failed, 0 xfailed, 0 warnings**
  (`pytest -q --tb=line`, 45.2 s). `ruff check .`: **All checks passed!**
  `vulture src/ --min-confidence 80`: **0 findings**.

## 2026-10-20 — Hardening pass 2b (BH-J1…BH-J6)

Second batch after the pass-2 ledgers. Tests first:
`tests/test_hardening_pass2b.py` (5 cases; guest paths, loop survival, clean
second-daemon exit, and the two CLI message helpers).

### Fixed

- `src/assistant/daemon.py`
  - Guest turns (`_guest_turn_normal`, `_guest_turn`) no longer append to
    `SessionService`: no owner conversation row is created, guest speech is
    broadcast with `role: "guest"` and `conversation_id: null`, and every
    show-off guest turn now writes a `disclosure.log_guest` audit row (BH-J1).
  - `_connectivity_loop` body extracted to `_connectivity_tick()` and wrapped
    in try/except with a logged reason; one failed probe no longer ends posture
    tracking for the process lifetime (BH-J2).
  - `main()` catches the two-daemon `RuntimeError` and prints one line to
    stderr before `SystemExit(1)` (BH-J3); `import sys` added (the first version
    of the handler would itself have raised `NameError`).
- `src/assistant/cli.py`
  - `_forget_message(topic, count)` reports the searched topic and match count
    (BH-J4); `forget` help no longer claims the argument is optional.
  - `_refusal_text(exc)` avoids the `refused: refused:` duplication (BH-J5);
    used by both the knock and commitment handlers.
- `README.md`: `assist status && assist cost` → `assist status; assist cost`
  (BH-J6: `status` exits 1 when the daemon is down).

### Verification

- `pytest -q --tb=line`: **1,315 passed, 6 skipped, 0 failed, 0 xfailed**
  before the merge with `main` (pass-2 baseline in this checkout: 1,280
  passed / 6 skipped); **1,325 passed, 6 skipped** after merging PR #7's
  BUG 6 suite. No test or assertion changed in the merge.
- `ruff check .`: **All checks passed!**
- `vulture src/ --min-confidence 80`: **0 findings.**
- Documented commands re-run against a throwaway `HOME`/`XDG_*` sandbox:
  `doctor status cost voice status privacy status|company|alone class
  on|off|status knock status|list|accept|raise showoff status|exit|demo
  memory|forget console --json verify mode auto taxonomy suggest transcribe
  ask ptt start`, plus the new `forget`/`knock raise` messages.

## 2026-10-20 — BUG 6f: Live final-envelope parsing + startup ack self-capture

Owner hardware report after 6e: saved-WAV fallback now saves the transcript,
updates inbox/clipboard and populates `last_capture`, but every session logs
`transcript_final_wait_timeout -> live_no_final`; the opening speaker ack is
also prepended to the user's words.

### Cause and fix

- `live_client.py`: the default `gemini-3.5-transcribe-live` protocol separates
  **speculative** `interim_input_transcription` from **committed**
  `input_transcription`. The old parser ignored the first field and required
  `input_transcription.finished=True` for the second. That flag is optional;
  this transcription-only model does not need a model `turn_complete` either.
  Thus valid committed text was classified as an interim and discarded by
  `_final_texts`, forcing 6e's batch path. The parser now handles the two
  envelopes explicitly (including model resource prefixes / preview suffixes).
  This matches Google's [transcription-only protocol example](https://github.com/google-gemini/jot-gemini-transcribe-macOS/blob/main/JotCore/Sources/TranscriptionClient/Live/LiveProtocol.swift).
- Conversational Live models retain different semantics: their
  `input_transcription` text fragments are accumulated and only committed on
  `finished` (including a textless marker) or a real `turn_complete`. Neither
  arbitrary interims nor model/output text are promoted on timeout.
- SDK `session.receive()` is scoped to a model turn, not the whole connection.
  The receive worker re-enters it to read later input transcription, does not
  treat a model-turn marker as a transcription-only final, and surfaces an
  empty receive/EOF as an error rather than silently abandoning `events()`.
  Closing the transport now awaits the cancelled receive worker.
- `transcribe.py`: the activity-end wait is re-armed **before** sending
  `activity_end`, so a prefix committed while recording cannot skip waiting for
  the tail. A missing tail or receive error still tries the bounded WAV
  fallback, preserving already-committed text if that recovery also fails.
  Genuine no-final/close timeouts and 6e's durable capture diagnostics remain.
- New `dictate.live_receive_summary` lifecycle record: normalized event counts,
  actual audio frames sent, response-envelope counts, model, SDK version and
  receive-worker status. It contains **no transcript text or audio** and is
  logged for both successful and unsuccessful final waits.
- `daemon.py`: `_ack` previously scheduled `speech.play_ack` directly, without
  `_set_speaking`, so neither `_MutedCapture` nor Live's external playback probe
  knew the speakers were active. Cached opening acks and in-session check-ins
  now share `_queue_ack_playback`: reserve the gate synchronously before
  queueing, hold it for the actual playback worker's lifetime (even beyond a
  duration estimate or cancellation of its waiter), then retain the 400 ms
  speaker-tail guard. Acks stay fire-and-forget; release stays silent. Frames
  heard during the ack/guard reach neither Live nor the WAV/batch path. This is
  audio gating, not deleting matching words from the user's transcript.

### Verification

- Added `tests/test_bug6f_live_final_and_startup_ack.py`: **24 offline cases**.
  The first 13 cases were run against the old code: **12 failed, 1 passed**,
  including both observed state defects (batch fallback despite a committed
  envelope, and `On it.` prepended via Live and saved-WAV ASR). Added edge pins
  cover same-message preview/final, delayed final after a model turn, deltas /
  empty markers, preview-only fallback, early segment plus delayed/missing tail,
  receive EOF/error, output-text isolation, cancelled/failed ack playback,
  suppressed acks, and the cached check-in path.
- Real `google-genai 2.31.0` offline schema smoke: camelCase wire payload with
  `interimInputTranscription` + `inputTranscription` decodes and produces interim
  + final with `finished=None`, without contacting the API.
- Full suite: **1,417 passed, 6 skipped**. `ruff check .`: **All checks passed**.
  `git diff --check`: clean.
- No real Gemini call, microphone, or speakers were available for verification;
  this is a protocol-shaped offline reproduction, **not a claim of a new
  hardware pass**.

### Owner hardware recheck

After installing this checkout and restarting the daemon:

```sh
systemctl --user restart assistant.service
assist dictate
assist status
assist events --recent 120 --kind dictate.lifecycle
```

Use speakers (not headphones), let the opening ack finish, then dictate a new
sentence and release. Check that the transcript/inbox/clipboard contain only
that sentence and the WAV starts with the user's audio. For the same session,
expect `dictate.live_receive_summary.event_counts.final >= 1`, a nonzero
`transport.audio_frames_sent`, and no `dictate.transcript_final_wait_timeout`,
`dictate.live_no_final` or `dictate.saved_wav_fallback_start` on a healthy Live
response. Keep checking `last_capture` for the real mic node/bytes/peak. If Live
still stalls, the summary now distinguishes "no input envelope received" from
"input received but no commit", and reports the exact SDK/model in use.

## 2026-10-24 — SILENCE HOTFIX: she never answers an empty room (`arena/e57b6d8f-elaria`)

Two hardware observations (2026-10-24 ~01:20 EAT): (i) a wake-key dictate
session with no speech at all still spoke the endpointing ladder line ("that's
everything for now, is there something I can assist with") into an empty room;
(ii) a brushed F2 during a phone call answered canned filler ("Understood, how
may I help you?") out loud. Both are the same class of failure: the voice
reply path treated silence and room noise as something to answer. Five rules,
voice reply path only — event capture/transcription behaviour and markers are
untouched (regression-pinned below).

### Rule 1 — silent close on silence

Empty normalized transcript at session end ⇒ no voice reply, no TTS call, no
ladder. Instead a plain-language line `she heard nothing` is written to the
session journal (persona event `session.silent_close`, `transcribe.py`
`HEARD_NOTHING`) and surfaces on the console status line the next time it
opens (`daemon.py`: `_last_session_line` set by the dictation sink from the
`session.silent_close` event, reconciled in `_finish_dictation`'s finally,
exposed as `status.last_session_line` and `console.state.status_line`). No
notification popup.

Marker scope: silence-verdict sessions only. A session that captured speech
but whose transcript never arrived (`no_final`) keeps its existing honest
notes — "she heard nothing" would be factually wrong there, and the pinned
`no_final` wording in `test_bug6e` stays.

### Rule 2 — audio-energy floor

New config `[voice] silence_floor = 0.05` (`config.py` DEFAULTS +
`config.toml.example`, BH-H22 parity preserved). `DictationService.dictate()`
tracks a per-frame session peak with the same `pcm_peak` mechanism as
`capture.stats`/the doctor peak (owner's speech proven at peak 0.8624). A
session whose peak stays below the floor is treated as silence regardless of
what the transcript says — this is what catches hallucinated garbage from
room noise during a call. `capture.stats` gains `peak` and `silence_floor`
keys; the silence verdict is `captured_bytes == 0 or peak_rms < 0.003 or
session_peak < silence_floor`, then the rule-1 silent close applies.
`wake_guard.py` reads the same floor into its `SilenceLadder`
(`silence_floor` dataclass field, default from DEFAULTS) so the wake path
cannot nag at sub-floor rooms either; the observed failure flowed through
PTT/dictate, but both paths now share the gate.

### Rule 3 — ladder gating

The soft ladder ("Is that all?" / check-in acks) may fire only after at least
one landed user utterance with at least one real word. Two layers:

- **Audio layer (primary)**: `SilenceLadder` grows `floor_peak` and a sticky
  `heard_speech` flag. Frames below the energy floor count as silence for the
  ladder even when their RMS clears the speech gate; `_heard_speech` latches
  only after `resume_s` of sustained above-floor speech — the same
  accumulator that re-arms VB-5's "at most once per segment" rule, so
  existing behaviour is preserved exactly (`floor_peak=0` ⇒ legacy RMS
  semantics). Silence at session start can therefore never produce a ladder
  line: `close_due()` splits into grace-close (speech was heard ⇒ ask, then
  close after grace) and silent-close (nothing was heard ⇒ close quietly
  after window+grace).
- **Word layer (secondary, transport sessions only)**: the check-in event is
  emitted only when `transport is None or _landed_real_words(collected)` —
  `_has_real_word`/`_landed_real_words` in `transcribe.py` accept only
  interim/final transcript events containing a token with an alphanumeric
  character. Audio-only (offline/no-transport) sessions fall back to the
  audio layer. When withheld, a note records "check-in withheld: no word had
  landed to ask about".

### Rule 4 — no canned filler as reply fallback

Generic acks/greetings are never spoken when the transcript is empty, below
the confidence gate, or below the energy floor. Enforced upstream rather than
by extending `FILLER_PHRASES`: empty transcript ⇒ `_ask` is never reached;
low confidence ⇒ existing veto; below floor ⇒ text discarded before routing;
command-mode routing in `_finish_dictation` additionally requires
`result["text"].strip() and not no_speech`. Real short speech still works: a
one-word transcript with a healthy peak ("Four.") goes through the normal
reply path (test (c)/(c2)).

### Rule 5 — quota hygiene

A silent close costs zero Flash-Lite/TTS calls. Asserted with mock-transport
call counters and daemon spies in `tests/test_silence_hotfix.py`: no `speak`,
no `_ask`, no ack playback, no check-in broadcast; the day's quota counters
are unchanged across a silent session. Note for future daemon tests: under
`GEMINI_MODE=mock` `GeminiClient.can_speak()` is False ⇒ `voice_route()` is
permanently `"silent"` ⇒ the ack cache can never be seeded, so daemon-level
red signals are the wrapped-broadcast recorder plus speak/_ask/play-ack
spies, never `cached_ack()`.

### Journal/lifecycle surface (additive)

Silence-verdict sessions additionally emit persona event
`session.silent_close` {message, session_id, node, bytes, peak, peak_rms,
silence_floor} and lifecycle event `dictate.silent_close_emit` (ordered after
`capture.stats`, before `session.ended`). All existing `list_persona_events`
consumers are kind-filtered; no key-set equality pins exist on notes,
`_status`, or `console.state`, so the new fields are purely additive.

### Tests

New `tests/test_silence_hotfix.py` — 16 cases, written red first (14 failed /
2 passed pre-fix; the 2 pre-existing passes are the VB-5 regression pins):
config surface ×2; ladder units ×3 (silence-from-start never fires and closes
silently; below-floor noise counts as silence; loud run fires once, blip does
not re-arm, sustained speech re-arms); (a) service silence ⇒ no TTS, no
ladder string, `she heard nothing` in notes + journal + lifecycle, stats
peak/floor; (a2) daemon silence ⇒ no check-in broadcast, spies empty,
silent-close broadcast + journal, console line set, quota zero, and a real
session afterwards clears the line; (b) low-peak noise + garbage transcript
⇒ silent close, garbage discarded, peak_rms ≥ speech gate proves the floor
decided (not zero-capture); (b2) configurable floor 0.5 swallows loud frames;
(b3) daemon noise + command speak=True ⇒ asks/speaks empty; (c)/(c2) "Four."
one word + healthy peak ⇒ normal reply path intact (service transcript and
daemon `_ask`); (d) mid-session silence after landed words ⇒ ladder fires
exactly once + `session.grace_close`; (d2) no word ever landed ⇒ check-in
withheld; (e) two consecutive mid-session silences ⇒ ladder at most once;
(f) event path untouched: `EventService` with floor 0.9 still writes its own
`[seg 001: no signal detected]` markers with identical call counts.

Existing pins updated for the new rule-3 semantics (each with a comment
citing the rule): `test_voice_bughunt.py` c8, c8b, c9 (first block), c9b
(unit part), g20 now land a sustained utterance (`land_an_utterance` helper)
before their silence runs — a mid-conversation pause needs a conversation;
d11b's `indexed_frames` base amplitude moved 1000 → 6000 (peak ≈0.031 was
honest sub-floor silence under rule 2 — test speech must resemble real
speech); `test_phase1_dictation.py::test_silence_ladder_asks_once_per_segment`
prepends the sustained-speech run and now also asserts silence-from-start
produces no ask; `test_phase8_offline_voice.py` forced-offline ladder case
uses 20 loud frames instead of a 5-frame blip.

### Verification

- Full suite: **1,646 passed, 6 skipped** (baseline before this round:
  1,630 passed, 6 skipped; target ≥1,635).
- `ruff check .`: All checks passed. `shellcheck` (scripts/
  event-console-fallback.sh, untouched): clean. `git diff --check`: clean.
- Hardware definition-of-done (owner to report): silent room ⇒ she stays
  silent, journal shows `she heard nothing`, quota unchanged; one sentence ⇒
  normal reply.
