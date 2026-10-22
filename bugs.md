# Elaria bug ledger

This is the reproduced-bug ledger for the adversarial hunt. A bug is listed
only when a sandbox test or minimal script demonstrates the expected and
actual **state** (files, journal/store rows, queue rows, returned routing
state—not merely an exit code).

Severity vocabulary:

- **data-loss** — user content or durable memory can be destroyed, overwritten,
  deactivated wholesale, or made unrecoverable.
- **wrong-action** — Elaria performs, routes, reports, or persists the wrong
  thing while the underlying content remains recoverable.
- **crash-with-safe-state** — the operation crashes/hangs but no user content
  is silently destroyed.
- **cosmetic** — misleading text/reporting with no state-changing effect.

Status vocabulary: **fixed**, **open-xfail** (a strict-xfail regression test is
the repro), **open-reproduced** (minimal repro exists and is being converted
into a regular hunt test).

## Fixed during the hunt

### BH-A1 — Destination created after policy check could be overwritten

- **Severity:** data-loss
- **Status:** fixed in `6733f17`
- **Repro:** `test_destination_appearing_after_policy_check_is_never_overwritten`
- **Expected:** a file racing into the destination after `check_operation()`
  remains untouched and the source remains in place.
- **Was:** `shutil.move()` could replace the raced destination.
- **Fix:** atomic no-overwrite destination creation in the executor.

### BH-A2 — Model/plan `new_name` could escape the root

- **Severity:** data-loss
- **Status:** fixed in `6733f17`
- **Repro:** `test_schema_valid_llm_output_cannot_escape_with_new_name`, with
  `tests/bughunt_fixtures/evil_inputs.json`
- **Expected:** `../../escaped.txt`, absolute paths, and embedded separators
  fail verification and cannot move a file outside `root / dest`.
- **Was:** schema-valid LLM output could traverse out of the taxonomy folder.
- **Fix:** `is_safe_filename()` in planner verification and again in the
  executor, plus executor destination/root containment checks.

### BH-A3 — Taxonomy symlink could smuggle a file outside the root

- **Severity:** data-loss
- **Status:** fixed in `6733f17`
- **Repro:** `test_taxonomy_symlink_cannot_smuggle_file_outside_root`
- **Expected:** if `Finance/` is a symlink outside the watched root, the file
  stays put.
- **Was:** the executor followed the taxonomy symlink outside the root.
- **Fix:** resolved-destination containment checks for normal and
  `_Conflicts/` moves.

## Fixed in the full-repo hardening pass (`arena/86517426-elaria`)

### BH-A4 — Protected paths ignore `$VAR` spelling

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_protected_path_env_var_spelling_is_honoured`
- **Expected:** `$HOME/secret` protects the expanded directory.
- **Actual:** only `~` expansion is honoured; `$HOME/...` is treated as a
  literal relative path.

### BH-B1 — Move completed before journal commit is not undoable

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_kill_after_move_before_commit_can_be_undone`
- **Expected:** after restart, an outstanding intent whose bytes are at the
  destination can be reconciled/undone.
- **Actual:** undo only considers `committed` operations, so the moved file is
  stranded outside the normal undo path.

### BH-B2 — Partial cross-device copy is left at the destination

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_disk_full_mid_move_leaves_no_partial_destination`
- **Expected:** disk-full during a cross-device copy leaves the source and no
  misleading partial destination.
- **Actual:** the source is preserved, but a partial destination remains for
  inspection. This follows the never-delete bias, but is not yet reconciled
  into a named partial/quarantine state.

### BH-B3 — Executor-level bare undo unwinds all committed history

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_bare_undo_refuses_without_scope`
- **Expected:** `Executor.undo()` without op/plan/since refuses.
- **Actual:** it unwinds every committed operation. The CLI guards this, but
  daemon/intent paths can still reach the executor surface.

### BH-B4 — Broken symlink crashes indexing

- **Severity:** crash-with-safe-state
- **Status:** fixed in `810bab4`
- **Repro:** `test_broken_symlink_is_skipped_not_fatal`
- **Expected:** the dangling symlink is counted/skipped and ordinary files
  still index.
- **Actual:** `Path.stat()` raises and aborts the root indexing pass.

### BH-B5 — FIFO/special file can hang the indexer

- **Severity:** crash-with-safe-state
- **Status:** fixed in `810bab4`
- **Repro:** `test_fifo_is_skipped_instead_of_blocking_indexer`
- **Expected:** non-regular files are skipped by type before any read.
- **Actual:** the indexer attempts to read the FIFO and blocks.

### BH-B6 — Later `never_send` policy does not reflag unchanged files

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_never_send_added_later_reflags_unchanged_documents`
- **Expected:** adding a root to `never_send_to_cloud` updates existing
  unchanged document rows on the next index pass.
- **Actual:** unchanged size/mtime short-circuits before the privacy flag is
  refreshed.

### BH-C1 — Halt landing after policy check does not stop the imminent move

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_halt_landing_after_policy_check_prevents_the_move`
- **Expected:** halt is honoured immediately before the filesystem syscall.
- **Actual:** halt is checked between plan items, but a halt landing after an
  item's policy check can still allow that item to move.

### BH-C2 — `trash()` bypasses protected-path and halt policy

- **Severity:** data-loss
- **Status:** fixed in `0176d8d`
- **Repro:** `test_trash_refuses_protected_paths_and_halt`
- **Expected:** protected paths and an active halt refuse trash just as they
  refuse moves.
- **Actual:** `trash()` goes straight to the journaled move. The file is
  recoverable from trash, but a protected file can be displaced against the
  stated policy.

## Fixed in the wider Areas D–G pass

### BH-E1 — `forget %` / `forget _` deactivated unintended memories

- **Severity:** data-loss
- **Status:** fixed in the working tree during this continuation
- **Repros:** `test_forget_percent_is_a_literal_topic_not_a_wildcard`,
  `test_forget_underscore_is_a_literal_topic_not_a_wildcard`, and the
  punctuation corpus `test_forget_topics_are_literal_for_punctuation`
- **Expected:** a topic is literal user text. `forget %` removes only facts
  containing a percent sign; `forget _` only facts containing an underscore.
- **Was:** the topic was interpolated into SQL `LIKE %...%`, so `%` matched
  every active fact and `_` matched every non-empty fact.
- **Fix:** escape `\`, `%`, and `_` and use `ESCAPE '\'` in
  `Store.forget_facts()`.

### BH-F4 — Two meetings in one minute overwrote each other's records

- **Severity:** data-loss
- **Status:** fixed in the working tree during this continuation
- **Repro:** `test_same_minute_meetings_never_overwrite_raw_audio_or_notes`
- **Expected:** each meeting keeps distinct mic WAV, system WAV, work
  directory, note, and transcript session ID.
- **Was:** names had only minute resolution and were written with
  `write_bytes`/`write_text`, so the second meeting replaced the first
  meeting's raw audio and note.
- **Fix:** allocate a collision suffix across the complete artifact set and
  copy/write with exclusive-create semantics.

### BH-F5 — Meeting system channel copy depended on the mic path

- **Severity:** wrong-action
- **Status:** fixed in the working tree during this continuation
- **Repro:**
  `test_meeting_system_channel_is_copied_even_when_mic_is_canonical`
- **Expected:** mic and system channels are canonicalized independently.
- **Was:** both copies were inside `if mic_wav != mic_dest`, so passing the
  canonical mic WAV with a new system WAV silently retained/stale-read the
  old system destination.
- **Fix:** independent no-overwrite copies for each channel.

## Fixed after merge — Python 3.14 follow-up

Found by running the keyless suite on Fedora/Python 3.14 after PR #1 merged:
**14 failed, 965 passed, 5 skipped, 46 xfailed**. Eight failures were one CLI
crash (BH-G4), five were BH-E2 and one was BH-C3 — the latter two surfacing as
`XPASS(strict)` because they passed *for the wrong reason* on that build.

### BH-G4 — One unescaped `%` in a help string broke the entire CLI on Python 3.14

- **Severity:** crash-with-safe-state
- **Status:** fixed
- **Repros:** `test_cli_every_help_string_renders`,
  `test_cli_plan_apply_help_renders_a_single_percent`,
  `test_cli_help_exits_zero_for_every_command_group`,
  `test_no_unescaped_percent_in_any_argparse_help_string`
- **Expected:** `pyproject.toml` declares `requires-python = ">=3.11"`, so
  every `assist` command must at least construct its argument parser on any
  supported interpreter.
- **Was:** `plan apply`'s `--allow-tripwire` help read
  `"explicitly allow moving >tripwire% of the tree (§4.4)"`. argparse
  `%`-formats every help string; `% o` is an invalid conversion.
  - On Python 3.11–3.13 that only raised when `assist plan apply --help`
    was formatted, so one subcommand's help was broken.
  - On Python 3.14, `add_argument()` calls the new `_check_help()`, which
    formats help **eagerly**, so `build_parser()` raised
    `ValueError: badly formed help string` (caused by
    `TypeError: %o format: an integer is required, not dict`) — every
    `assist` command died before its own logic ran, including
    `doctor`, `cost` and `status --waybar`.
- **Evidence (CPython 3.14.0 `Lib/argparse.py`, run against this tree):**
  original `main(["doctor"])` → `ValueError: badly formed help string` /
  cause `TypeError: %o format: an integer is required, not dict`; fixed
  source constructs the parser and renders all 47 help outputs.
- **Fix:** escape it as `>tripwire%%`; rendered help still shows one `%`
  (`>tripwire% of the tree (§4.4)`). Audited every `help=`/`description=`/
  `epilog=`/`usage=`/`metavar=`/`prog=` literal in `src/` — no other
  unescaped `%` exists, including `assist-voice-test`. Parser construction
  moved out of `main()` into `build_parser()` so the whole command tree can
  be rendered in-process on every supported Python.

### BH-E2 — Raw user search text is interpreted as FTS5 syntax

- **Severity:** crash-with-safe-state
- **Status:** fixed (was open-xfail)
- **Repros:** `test_search_documents_treats_user_text_as_text_not_fts_syntax`,
  `test_search_documents_punctuation_is_text_not_operator`,
  `test_search_documents_still_finds_plain_keywords`,
  `test_fts5_match_expression_is_always_well_formed`,
  `test_like_fallback_is_literal_and_wildcard_safe`
- **Expected:** quotes/parentheses/operators are searched as text, or safely
  return no hits.
- **Was:** `Store.search_documents()` passed raw user text straight to
  SQLite FTS5 `MATCH ?`, so `"`, `NEAR(`, `invoice OR`, `(invoice` and
  `invoice)` raised `sqlite3.OperationalError`.
- **Why it XPASSed on Fedora, and why that was not a fix:** the old test
  searched an **empty** store, so no rows were scanned and the malformed
  `MATCH` was never evaluated (and on a SQLite build without FTS5 the LIKE
  fallback never parses `MATCH` at all). Repopulated, the same five queries
  raise on every build. Environment measured while fixing this:
  Python 3.11.2, `sqlite3.sqlite_version` 3.40.1,
  `Store.fts5_available` `True`.
- **Fix:** search input is reduced to literal terms first
  (`_search_terms()`, mirroring FTS5's `unicode61` tokenization), then each
  term is emitted as a quoted string by `_fts_match_expression()`, so no
  operator can survive into `MATCH`. A punctuation-only query yields no
  terms and returns `[]`. Punctuation is now *text*, so `(invoice` finds the
  invoice document instead of erroring.
  - `Memory.recall()`'s OR arm moved to the new
    `Store.search_documents_any()` — same literal quoting, OR semantics —
    so recall keeps matching any term instead of losing its `OR`.
  - The non-FTS5 LIKE fallback escapes `\`, `%` and `_` with `ESCAPE '\'`
    (same class as BH-E1) so a literal wildcard cannot widen a match, and
    degrades to LIKE rather than crashing if FTS5 ever rejects a query.

### BH-C3 — Concurrent queue drains can process the same job twice

- **Severity:** wrong-action
- **Status:** fixed (was open-xfail)
- **Repros:** `test_concurrent_queue_drains_claim_a_job_once`,
  `test_claim_cloud_job_lets_exactly_one_caller_win`
- **Expected:** exactly one drain claims and handles a pending job.
- **Was:** `CloudQueue.drain()` selected candidates and then updated the
  winner to `running` as two separate statements, so two drains that listed
  the same job both ran it — repeating model calls and side effects, and
  double-counting `attempts`.
- **Why it XPASSed on Fedora, and why that was not a fix:** the old test
  raced two threads with no synchronization at the select/claim boundary, so
  it passed whenever one thread marked the job `running` before the other
  listed candidates. Barrier-synchronised at that boundary it reproduces
  **20/20** on the unfixed code (`['chat', 'chat'] == ['chat']`).
- **Fix:** `Store.claim_cloud_job()` — one conditional
  `UPDATE … SET status='running', attempts = attempts + 1 WHERE id = ? AND
  status IN ('pending','approved')`, reporting success from `rowcount`.
  SQLite applies it atomically, so at most one caller wins; `drain()` skips
  any job it fails to claim, and only the claimant increments `attempts`.
  The `awaiting_approval` transition is claimed the same way, so only the
  drain that actually moved the job reports it.
- **Evidence:** with the fix the strengthened test passes **20/20**
  consecutive runs; handler runs once, final state `done`, `attempts == 1`,
  and the two drains report `done` counts `1` and `0`.

## Fixed in the full-repo hardening pass: executor/organiser & Areas D–G

### BH-A5 — Executor does not verify plan root against root spec

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_plan_for_one_root_cannot_be_applied_with_another_root_spec`
- **Expected:** applying a plan built for root B with root A's spec raises
  before any file moves.
- **Actual:** the executor accepts the mismatch and can move B's indexed
  files into A. Daemon/CLI callers pair them correctly today, but the sole
  file-moving authority does not enforce its own boundary.

### BH-A6 — Executor accepts a source outside the organise root

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_plan_item_source_outside_root_is_refused`
- **Expected:** every plan item source must be inside the root being applied.
- **Actual:** if the outside file is indexed under another root/spec, the
  executor moves it into the current root.

### BH-A7 — Executor accepts invented destinations outside frozen taxonomy

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_plan_item_invented_destination_is_refused`
- **Expected:** a corrupted/manual plan item with `dest="Invented"` is
  refused because `Invented` is not in the root taxonomy.
- **Actual:** syntax/root-containment checks pass and the executor creates
  and files into `Invented/`.

### BH-A8 — Nested already-filed files are flattened

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repro:** `test_nested_already_filed_file_is_not_flattened`
- **Expected:** `Finance/2024/invoice.txt` is already inside the taxonomy
  and stays exactly there.
- **Actual:** organiser marks it already-filed with destination `Finance`
  and basename only; executor therefore moves it to `Finance/invoice.txt`.

### BH-A9 — Destination occupied by a directory crashes the apply

- **Severity:** crash-with-safe-state
- **Status:** fixed in `0176d8d`
- **Repro:** `test_destination_occupied_by_directory_is_refused_not_raised`
- **Expected:** one refused item in the report; source and directory intact.
- **Actual:** `check_operation()` tries to hash the directory and raises
  `IsADirectoryError`, aborting the apply loop.

### BH-A10 — `ApplyReport.op_ids` is always empty

- **Severity:** cosmetic
- **Status:** fixed in `0176d8d`
- **Repro:** `test_apply_report_names_the_journal_operations_it_committed`
- **Expected:** the report names committed journal operation IDs.
- **Actual:** files move and journal rows commit, but `op_ids == []`.

### BH-B7 — Watcher debounce does not restart on later writes

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_watcher_debounce_restarts_when_a_file_changes_again`
- **Expected:** a file changed at t=0 and again at t=9 is not settled at
  t=11 with a 10-second debounce.
- **Actual:** the pending timestamp keeps the first change time; only the
  scan that directly observes the second modification suppresses settling.

### BH-B8 — Unreadable directory is indexed as empty and docs go missing

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_unreadable_directory_does_not_mark_known_files_missing`
- **Expected:** indexing reports an error and leaves known document state
  unchanged while the directory cannot be read.
- **Actual:** `os.walk` silently yields no files below the unreadable
  directory and reconciliation marks known documents `missing`.

### BH-B9 — `build_plan` ignores a missing-root index error

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_build_plan_for_missing_root_does_not_finish_ready`
- **Expected:** a missing root fails the plan.
- **Actual:** indexer returns `stats["error"]`, organiser proceeds with
  stale document rows, writes a shadow log, and finishes the plan `ready`.

## Fixed in the full-repo hardening pass: Area D — planner, intents, config

### BH-D1 — LLM batch verifier does not require an exact path set

- **Severity:** wrong-action
- **Status:** fixed in `0176d8d`
- **Repros:** `test_llm_batch_with_duplicate_path_and_missing_file_is_invalid`,
  `test_llm_batch_boolean_confidence_is_invalid`
- **Expected:** duplicates, dropped files, subsets, and boolean confidence
  invalidate the batch.
- **Actual:** each returned path is checked for membership, but cardinality
  and uniqueness are not; `True` also passes as numeric confidence because
  Python `bool` is an `int`.

### BH-D2 — API-cost intent overmatches ordinary English

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_ordinary_cost_words_are_not_the_api_cost_intent`
- **Expected:** “cost of living…”, “usage of the word…”, and
  “quota for fishing boats” go up the conversational ladder.
- **Actual:** all route locally to the Gemini cost report.

### BH-D3 — Natural emergency halt variants are misses

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_natural_halt_variants_route_to_halt`
- **Expected:** “halt please”, “stop everything now”, and “panic stop now”
  set the halt.
- **Actual:** only exact canned forms match; these fall through.

### BH-D4 — A string where a config sequence belongs becomes characters

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_string_taxonomy_and_languages_are_rejected_or_wrapped`
- **Expected:** `taxonomy="Finance"` and `languages="sw"` are rejected with
  a useful config error or normalized to one-element lists.
- **Actual:** taxonomy becomes `['F','i','n','a','n','c','e', ...]` and
  languages becomes `['s','w']`.

### BH-D5 — Loaded configs share nested `DEFAULTS` objects

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_mutating_loaded_config_does_not_pollute_next_load`
- **Expected:** mutating one `Config.raw` cannot change the defaults seen by
  the next `load_config()` in the same process.
- **Actual:** `_deep_merge(DEFAULTS, {})` shallow-copies the outer dict, so
  nested section dicts/lists remain shared.

### BH-D6 — Malformed humour TOML crashes instead of degrading

- **Severity:** crash-with-safe-state
- **Status:** fixed in `810bab4`
- **Repro:** `test_malformed_humour_profile_degrades_to_empty_profile`
- **Expected:** per its contract, `load_humour_profile()` returns `{}` and
  the governor falls back to restraint.
- **Actual:** TOML parse errors propagate, breaking doctor/daemon startup.

## Fixed in the full-repo hardening pass: Area E — store, queue, modes, harness

(BH-E2 moved to *Fixed* above.)

### BH-E3 — Every `OSError` is classified as a network failure

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_local_filesystem_errors_are_not_network_failures`
- **Expected:** missing file, permission denied, and disk-full are local
  failures with terminal/inspectable queue state.
- **Actual:** `looks_like_network_failure()` returns true for every
  `OSError`; in the queue this can requeue forever and mark connectivity
  unhealthy—for example when saved dictation audio is missing.

### BH-E4 — First 500 historical queue jobs starve newer pending jobs

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_queue_drain_reaches_pending_job_after_500_finished_jobs`
- **Expected:** drain selects pending/approved jobs regardless of how much
  completed history precedes them.
- **Actual:** drain loads the first 500 rows by ID across all statuses,
  filters afterward, and never reaches pending job #501.

### BH-E5 — A cloud job left `running` by a crash is never recovered

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_queue_recovers_a_job_left_running_by_a_crash`
- **Expected:** restart/drain reconciles a dead `running` job.
- **Actual:** candidates are only `pending`/`approved`; `running` remains
  forever while duplicate-suppression treats it as active.

### BH-E6 — `ModeManager` without a store cannot remember a switch

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_mode_manager_without_store_remembers_requested_preference`
- **Expected:** `request_preference("offline")` yields FORCED_OFFLINE even
  for the supported `store=None` construction.
- **Actual:** preference writes are no-ops and status re-reads config's old
  `auto` preference.

### BH-E7 — Harness verification outcomes are never ledgered

- **Severity:** cosmetic
- **Status:** fixed in `810bab4`
- **Repro:** `test_verified_outcome_is_recorded_in_the_ledger`
- **Expected:** failed/successful verified attempts write `verified=0/1` to
  `llm_calls`.
- **Actual:** `_call_once()` always writes `verified=None` before the
  verifier runs, and nothing updates the row afterward.

(BH-C3 moved to *Fixed* above.)

## Fixed in the full-repo hardening pass: Area F — audio, dictation, meeting, TTS

### BH-F1 — Empty ASR output stops the fallback chain

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_asr_fallback_chain_continues_after_empty_text`
- **Expected:** `transcribe_file()` walks until a backend produces text.
- **Actual:** a backend returning `Transcript("")` is treated as success
  and later backends are never tried.

### BH-F2 — `WavSink.close()` reports duration at the wrong sample rate

- **Severity:** cosmetic
- **Status:** fixed in `810bab4`
- **Repro:** `test_wav_sink_reports_duration_at_its_configured_sample_rate`
- **Expected:** 8,000 frames at 8kHz report 1.0s.
- **Actual:** the WAV is written at 8kHz but duration divides by the global
  16kHz constant and reports 0.5s.

### BH-F3 — PCM-stream PipeWire command bypasses the object.id trap guard

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_pw_record_stream_rejects_short_numeric_object_id_targets`
- **Expected:** a short numeric target such as `42` is rejected because
  `pw-record --target` needs `object.serial` or `node.name`.
- **Actual:** `pw_record_command()` guards this, but the raw-stream command
  used by live capture accepts it and can silently capture the default
  device on Fedora.

### BH-F6 — Live age rotation reconnects on every later frame

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_live_age_rotation_does_not_reconnect_on_every_frame`
- **Expected:** proactive rotation after the Live session-age cap resets
  that transport's age clock.
- **Actual:** `started` remains dictation start time; once the cap is
  crossed, each subsequent frame raises rotation, reconnects, and replays
  the buffered tail again.

### BH-F7 — Cleanup failure prevents raw dictation persistence

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_cleanup_failure_still_persists_raw_transcript`
- **Expected:** ASR text lands in the transcript store/inbox even if the
  optional cleanup model call fails.
- **Actual:** cleanup is called before either persistence step; an
  exception propagates and only the raw WAV remains.

### BH-F8 — Piper availability ignores a missing voice JSON config

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_piper_availability_requires_the_json_config`
- **Expected:** status reports unavailable when the selected model's
  `.onnx.json` config is absent.
- **Actual:** model + executable presence is reported available; synthesis
  is the first place the missing config can fail.

### BH-F9 — Explicit TTS destination is reused as cache for different text

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_tts_explicit_destination_is_not_reused_for_different_text`
- **Expected:** synthesizing “second text” to an explicit WAV path produces
  audio for the second text.
- **Actual:** any non-empty explicit destination is considered cached, so
  the result claims the second text while the file still contains the first
  synthesis.

## Voice hunt (VOICE-BUGTEST.md) — status after the Gate A–D fixes

Same ledger rules as the sections above; `VB-*` ids are the ones used in
[`VOICE-BUGTEST.md`](VOICE-BUGTEST.md). Hunt classes are quoted alongside the
severity vocabulary because the owner marked wrong-voice and offline-speaking as
their own CRITICAL class.

### VB-1 — Online cache key ignored the voice, so a voice change replayed Flare

- **Severity:** wrong-action (hunt class: CRITICAL — wrong voice)
- **Status:** fixed in `3d2b9e5`
- **Repro:** `test_b7_voice_change_invalidates_the_online_cache`
- **Expected:** a `[gemini] voice` (or `model_voice`) change cannot serve audio
  rendered for the previous identity, in either direction.
- **Actual (before):** the key carried the dormant local descriptor, so the same
  `speech-<hash>.wav` answered for a different voice while `status` reported the
  new one. The key is now the route's own audio identity.

### VB-2 — A dormant-path setting made every cached ack a permanent silence

- **Severity:** wrong-action (hunt class: HIGH — silent hotkey)
- **Status:** fixed in `3d2b9e5` (key) and `d63f0de` (re-warm)
- **Repro:** `test_b5b_dormant_config_change_must_not_silence_the_hotkey_path`,
  `test_b5d_ack_miss_self_heals_within_one_warm_cycle`, `test_b5e_daemon_re_warms_after_a_miss`
- **Expected:** either the change does not invalidate the online acks, or a miss
  triggers exactly one warm cycle and a doctor/`voice status` warning — never a
  permanent silent `cache_miss`.
- **Actual (before):** `[tts] length_scale` (a dormant-path key) invalidated every
  online ack forever; 1.286 ms audible became 0.063 ms silence, and only a manual
  `assist voice warm` healed it.

### VB-3 — A dormant Piper render answered an online ack

- **Severity:** wrong-action (hunt class: CRITICAL — a voice that must never speak
  spoke)
- **Status:** fixed in `3d2b9e5`
- **Repro:** `test_b7c_local_audio_never_answers_an_online_ack`
- **Expected:** a missing Flare ack file is silence + a warning + a re-warm, never
  substitute audio, and `cached_acks` must not call a local file healthy.
- **Actual (before):** `_ack_path` preferred any warmed local copy "beats silence"
  — introduced with the interim online-voice commit and reachable on any box that
  had ever run the local voice. The fallback and its comment are deleted.

### VB-4 — Any string in `[gemini] voice` silently became her voice

- **Severity:** wrong-action (hunt class: CRITICAL — config poisoning)
- **Status:** fixed in `3d2b9e5`
- **Repro:** `test_a3_voice_is_pinned_and_the_precedence_is_documented`,
  `test_a3b_client_refuses_an_unapproved_voice_even_when_called_directly`
- **Expected:** `[gemini] voice` validated against the configured canonical voice
  (Flare); a mismatch is a loud doctor FAIL and reported silence, never silent
  adoption; the precedence over the legacy `tts.selected_voice` row is documented.
- **Actual (before):** `voice_name = voice or "Flare"` with no validation, doctor
  green, and two config sources disagreeing about who speaks.

### VB-5 — One thought, two check-ins

- **Severity:** wrong-action (hunt class: MED — she speaks when she should not)
- **Status:** fixed in `c1469cc`
- **Repro:** `test_c9_blip_speech_does_not_rearm_the_ladder_for_a_second_nag`
- **Expected:** "Is that all?" once per thought; only a real resumption re-arms.
- **Actual (before):** any frame ≥ the RMS gate cleared `_asked`, so a 30 ms breath
  or click inside one long pause earned a second nag.

### VB-6 — Asked, then the mic never released

- **Severity:** crash-with-safe-state (hunt class: MED — resource hold)
- **Status:** fixed in `c1469cc`
- **Repro:** `test_c9b_after_the_checkin_the_session_closes_after_grace`
- **Expected:** the check-in is followed by a grace close that releases the
  microphone and the `listening` state.
- **Actual (before):** the user's hotkey was the only exit; a headless repro held
  the source for ~50 minutes.

### VB-7 — Rotation dropped the head of a long dictation

- **Severity:** data-loss
- **Status:** fixed in `c1469cc`
- **Repro:** `test_d11b_rotation_on_a_long_utterance_keeps_every_word`
- **Expected:** words already transcribed are never discarded because a Live
  session rotated.
- **Actual (before):** `collected.clear()` threw away received finals; anything
  older than the ≤30 s replay buffer vanished from the transcript while
  `assist events` had already shown it.

### VB-8 — Transcribed words reached the intent ladder with no confidence gate

- **Severity:** wrong-action (hunt class: HIGH)
- **Status:** fixed in `c1469cc`
- **Repro:** `test_d13b_low_confidence_command_words_never_execute`
- **Expected:** a command-mode transcript is gated on ASR confidence and on the
  cleanup-flagged state before anything is routed, and a mutating intent never runs
  on unverifiable audio.
- **Actual (before):** `route(text)` ran whatever the mic heard: a TV saying
  "undo." reversed files. `Daemon._command_gate` now vetoes and says why.

### VB-9 — The doctor green-lit a broken biometric template

- **Severity:** cosmetic (hunt class: MED — misleading reporting about a real
  failure)
- **Status:** fixed in `b058ea2`
- **Repro:** `test_e14_corrupt_or_world_readable_voiceprint_fails_the_doctor`
  (6 parametrised cases), `test_e14c_voiceprint_checks_agree_with_the_runtime_and_leave_good_files_alone`
- **Expected:** non-empty, parseable, right schema, dimension and model agreeing
  with config, mode `0600`; anything else FAILs.
- **Actual (before):** `voiceprint.exists()` only — `ok — present (path only…)` for
  a 0-byte or 0644 template.

### VB-10 — SIGKILL of the daemon orphaned its audio child

- **Severity:** crash-with-safe-state (hunt class: MED)
- **Status:** fixed in `b058ea2`
- **Repro:** `test_g18_kill_daemon_mid_playback_leaves_no_player_running`,
  `test_g18b_the_sweep_names_a_parentless_audio_child`
- **Expected:** no audio process survives the daemon; if one does, it is named by
  the doctor and reaped by `assist voice cleanup` / the boot sweep.
- **Actual (before):** the player (observed pid 11712) outlived `kill -9`;
  `pw-record` had the same shape, so the mic stayed claimed. `PR_SET_PDEATHSIG`
  plus a real supervisor sweep now cover it — the sandbox kernel proved pdeathsig
  alone is not a promise to rely on.

### VB-11 — A rejected second hotkey press spoke its own ack

- **Severity:** cosmetic (hunt class: LOW)
- **Status:** fixed in `c1469cc`
- **Repro:** `test_g19_double_hotkey_acks_once`
- **Expected:** a refusal is not a request to be acknowledged.
- **Actual (before):** the loser got `note: "already listening"` *and* an "On it."
  clip: one double-press, two answers.

### VB-12 — 0-byte audio blamed on a missing package

- **Severity:** cosmetic (hunt class: LOW)
- **Status:** open-reproduced, deliberately unpinned — it fails safe
- **Repro:** `test_d13_empty_or_silent_audio_is_never_a_confident_transcript`
  covers the safe half; the misleading message is unreproducible without
  `faster-whisper` absent, so it is recorded, not tested.
- **Expected:** "the recording is empty", not "install faster-whisper".

### VB-13 — The socket opened before the ack cache existed

- **Severity:** wrong-action (hunt class: HIGH — silent at boot)
- **Status:** fixed in `d63f0de`
- **Repro:** `test_b5c_boot_warm_starts_before_the_socket_serves`,
  `test_b5cb_early_acks_queue_behind_the_boot_warm`
- **Expected:** the warm starts before anything can ask for an ack, or early acks
  queue behind it.
- **Actual (before):** `await serve(...)` came first and the warm was a background
  task afterwards, so the first press after boot was silent — online, one
  rate-limited render per ack.

### VB-14 — The Waybar pill called cloud audio "local"

- **Severity:** cosmetic (hunt class: LOW)
- **Status:** fixed in `b058ea2`
- **Repro:** `test_a4c_waybar_line_is_truthful_in_every_mode`
- **Expected:** the pill states the posture: cloud, local, or silent-with-reason.
- **Actual (before):** `voice: local gemini-native-audio / Flare` online and
  `voice: local none / none` offline.

### VB-15 — "do it anyway" / "approve" are not voice-reachable (gap, not a bug)

- **Severity:** cosmetic (a missing capability, recorded so it is not mistaken for
  a broken gate)
- **Status:** open — deliberately not implemented while fixing bugs
- **Evidence:** `intents.route("do it anyway")` and `route("approve")` return
  `None`; `test_f16d_do_it_anyway_by_voice_is_not_a_gate_bypass` pins that no
  spoken phrase bypasses a gate today.
- **Note for the owner:** this is also why VB-8's veto ends with a typed
  instruction rather than "say it again to confirm" — there is no spoken
  confirmation channel to offer yet.

## Fixed in the full-repo hardening pass: Area G — IPC, daemon, voice-test

### BH-G1 — Speaker-threshold suggestion tie-breaks dangerously low

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_suggested_speaker_threshold_uses_the_separation_gap_midpoint`
- **Expected:** with false scores at 0.10 and true scores at 0.90, the
  suggested threshold sits in the separation gap (about 0.50).
- **Actual:** the sweep keeps the first zero-error threshold, 0.101,
  maximizing unseen-impostor false-accept risk.

### BH-G2 — `review.decide` reports success for a nonexistent item

- **Severity:** cosmetic
- **Status:** fixed in `810bab4`
- **Repro:** `test_review_decide_rejects_a_nonexistent_item`
- **Expected:** deciding item #999999 raises a clear no-such-item error.
- **Actual:** the SQL update affects zero rows but the daemon returns a
  successful approve/reject response.

### BH-G3 — IPC client mistakes a pushed event for its reply

- **Severity:** crash-with-safe-state
- **Status:** fixed in `810bab4`
- **Repro:** `test_ipc_call_skips_event_lines_until_the_matching_reply`
- **Expected:** `ipc.call()` skips server-pushed event lines and returns the
  matching JSON-RPC-style result.
- **Actual:** it treats the first event line as the reply; with no `ok`
  field it raises a daemon error even though the real reply follows.

## Fixed in the full-repo hardening pass: Area H — Stages A–D & cross-cutting (`tests/test_stage_abcd_bughunt.py`)

### BH-H1 — Live session failure mid-ack or mid-conversation leaves truncated WAV or ignores connectivity loss

- **Severity:** crash-with-safe-state / wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_bh_h1_live_session_failure_mid_ack_leaves_no_partial_wav_and_falls_back_to_text`
- **Expected:** `SpeechService.write_wav()` writes atomically via temp file +
  `os.replace`, `GeminiClient._live_voice()` discards partial PCM on mid-stream
  disconnect, and `Daemon._maybe_speak_reply()` notifies `mode_manager.observe_failure()`
  on network errors while returning the text reply cleanly.
- **Actual (before):** `write_wav()` wrote in place (`wave.open(dest, "wb")`),
  mid-stream Live disconnects were not distinguished from completed turns, and
  conversation speech failures did not update `mode_manager`.

### BH-H2 — Voice catalogue cache never expires and `voice_route()` ignores upstream voice removal

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h2_catalogue_cache_ttl_and_upstream_voice_removal`
- **Expected:** `load_cached()` enforces a TTL (`DEFAULT_CATALOGUE_TTL_S = 86400s`),
  `validate_voice()` includes `candidate_voices` in `allowed`, and `SpeechService.voice_route()`
  refuses a voice removed from a verified cached catalogue.
- **Actual (before):** cached catalogues persisted forever without TTL checks,
  and `voice_route()` only checked local `voice_identity()` without consulting
  the verified cached catalogue.

### BH-H3 — Narrowing `allowed_voices` leaks the unapproved voice into `cloud_cache_identity()` and `status()`

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h3_allowed_voices_widened_then_narrowed_and_case_canonical`
- **Expected:** when `allowed_voices` is narrowed so `configured_voice()` is
  refused, `cloud_cache_identity()["voice"]` is `""` and `status()["gemini_voice"]`
  is `"none"`; lowercase `"flare"` canonicalizes to `"Flare"`.
- **Actual (before):** `cloud_cache_identity()` and `status()` fell back to
  `self.configured_voice()` (`"Kore"`) via `or`, and `resolve_voice()` returned
  raw lowercase `"flare"`.

### BH-H4 — Removed legacy `model_voice = "gemini-2.5-flash-preview-tts"` shadows `gemini_voice_model`

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h4_deprecated_model_voice_never_shadows_gemini_voice_model`
- **Expected:** the removed TTS-preview default `gemini-2.5-flash-preview-tts`
  in deprecated `model_voice` never overrides `gemini_voice_model = "gemini-3.8-live"`.
- **Actual (before):** `voice_model()` let any non-empty `model_voice` shadow
  `gemini_voice_model` whenever `gemini_voice_model == DEFAULT_VOICE_MODEL`.

### BH-H5 — Daemon restart mid-conversation omits prior SQLite turns from `ask` prompt

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_bh_h5_session_continuity_under_daemon_restart_includes_history_in_prompt`
- **Expected:** `Daemon._ask` injects recent turns from the active SQLite
  conversation into the prompt sent to `GeminiClient.generate("chat", ...)`,
  so conversation context survives a daemon restart.
- **Actual (before):** `SessionService` stored turns in SQLite, but `Daemon._ask`
  built the prompt from `memory.recall(text)` alone and never included the
  active conversation's recent messages.

### BH-H6 — Console follow-mode stalls forever on dead socket and leaks dead subscriber writers

- **Severity:** crash-with-safe-state
- **Status:** fixed in `810bab4`
- **Repro:** `test_bh_h6_console_follow_mode_disconnect_timeout_and_dead_subscriber_pruning`
- **Expected:** `subscribe_events()` sets a read timeout (`timeout=30.0`) so a
  dead peer cannot block `sock.recv()` forever, and `Daemon.broadcast()` awaits
  `w.drain()` to prune broken subscriber sockets immediately.
- **Actual (before):** `subscribe_events()` cleared the socket timeout to
  `None` after connecting, and `Daemon.broadcast()` only called `w.write()`
  without `await w.drain()`.

### BH-H7 — Class-mode toggle racing in-flight speech synthesis allows audio playback after class mode is enabled

- **Severity:** wrong-action
- **Status:** fixed in `810bab4`
- **Repro:** `test_bh_h7_class_mode_toggle_racing_spoken_ack_or_say_speech_loses`
- **Expected:** `SpeechService.say()` and `SpeechService.play_ack()` re-verify
  `self.voice_route()` immediately before invoking `self.play_audio()`, so a
  class-mode toggle landing during synthesis wins and suppresses audio.
- **Actual (before):** `voice_route()` was checked only before synthesis; if
  class mode turned on while synthesis was in flight, `play_audio()` still ran.

### BH-H8 — Overnight schedule windows fail across midnight and boolean `days` match Tuesday/Monday

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h8_schedule_suggestion_overnight_and_malformed_days_never_self_activate`
- **Expected:** overnight windows (`start > end`, e.g. `22:00`–`02:00`) match
  both late evening on day $d$ and early morning on day $(d+1) \bmod 7$;
  boolean entries in `days` are rejected; string `"false"` in `class.set`
  disables class mode; schedule suggestions never self-activate class mode.
- **Actual (before):** `_time_in_window` used `start <= cur <= end` (impossible
  when `start > end`), `isinstance(True, int)` matched weekday `1`, and
  `bool("false")` in `_class_set` evaluated to `True`.

### BH-H9 — `KnockSignal.emit()` ignores `knock["silent"]` and `raise_knock()` ignores `urgent_in_class_mode`

- **Severity:** wrong-action
- **Status:** fixed in `810bab4` / `e4108b5`
- **Repro:** `test_bh_h9_knock_during_class_mode_silent_pulse_and_urgent_config_respected`
- **Expected:** `KnockSignal.emit()` checks `bool(class_mode or knock.get("silent"))`
  and defaults `class_mode: bool = False`, and `InitiativeService.raise_knock()`
  respects `urgent_in_class_mode = false` in `[initiative]`.
- **Actual (before):** `KnockSignal.emit()` ignored `knock["silent"]`, and
  `raise_knock()` read `class_mode_urgent_only` while `DEFAULTS` and
  `config.toml.example` defined `urgent_in_class_mode`.

### BH-H10 — Accepting a knock while voice is muted opens `"voice"`, and crash before `sessions.append` loses the opener

- **Severity:** wrong-action / data-loss
- **Status:** fixed in `810bab4`
- **Repro:** `test_bh_h10_knock_accept_respects_mute_and_survives_daemon_restart`
- **Expected:** `Daemon._knock_accept()` passes `voice_available=not speech.status()["muted"]`
  so muted posture opens `"console"`, and `InitiativeService.accept()` appends
  the opener line to `self.sessions` so it is persisted before returning.
- **Actual (before):** `voice_available` only checked `speech.status()["available"]`
  (always `True`), and `sessions.append` only ran in `Daemon._knock_accept`
  after `initiative.accept()` returned.

### BH-H11 — Declining a snoozed or proposal-backed knock leaves its commitment active in `facts`

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h11_commitment_created_by_accepted_proposal_then_declined_is_deactivated`
- **Expected:** `decline()` accepts both `"pending"` and `"snoozed"` knocks,
  declines all pending/snoozed knocks on that normalized topic, and deactivates
  both the knock's commitment and any `parent_commitment_id` linked by `later()`.
- **Actual (before):** `decline()` rejected `"snoozed"` knocks and never
  deactivated the underlying commitment row in `facts`.

### BH-H12 — Topic retirement can be bypassed by punctuation variants or calling `ignore()` on resolved knocks

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h12_topic_retire_counter_manipulation_and_punctuation_normalisation`
- **Expected:** `_topic_key()` strips punctuation so `"Tax-Return!"` and
  `"tax return"` share one topic key, `ignore()` rejects non-pending knocks,
  and 3 ignored knocks across a topic retire the topic.
- **Actual (before):** `_topic_key()` only collapsed whitespace, `ignore()`
  mutated already-accepted/declined knocks, and retirement only checked a
  single knock row's `ignore_count`.

### BH-H13 — AST boundary test for knock sound and signal emit paths

- **Severity:** cosmetic (guard)
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h13_ast_knock_signal_and_sound_only_called_from_knock_handlers`
- **Expected:** `KnockSignal`, `.emit()`, and `knock.wav` / `knock.oga` are
  only referenced in `initiative.py`, `config.py`, and `Daemon._knock_*`
  handlers.

### BH-H14 — Needy-framing paraphrases slip past `NEEDY_PATTERNS`

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h14_needy_framing_fuzz_catches_subtle_paraphrases`
- **Expected:** paraphrases such as `"It's been quiet lately..."`,
  `"Just checking you still want me..."`, `"Did you forget about me?"`, and
  `"Are you ignoring me?"` are rejected by `InitiativeService._validate_reason()`.
- **Actual (before):** `NEEDY_PATTERNS` missed these paraphrases.

### BH-H15 — Show-off entry accepts a replayed recording of the owner's voice

- **Severity:** wrong-action (security boundary)
- **Status:** fixed in `0176d8d`
- **Repro:** `test_bh_h15_showoff_entry_rejects_recorded_or_replayed_owner_audio`
- **Expected:** `ShowoffService.enter()` rejects `source != "mic"`,
  `replayed=True`, `live_mic=False`, or any repeated `audio_sha256` digest.
- **Actual (before):** `enter()` only checked cosine similarity against the
  owner's voiceprint and had no replay or live-mic provenance check.

### BH-H16 — Unverified turn during show-off falls through to owner path if `speaker` is omitted

- **Severity:** wrong-action (security boundary)
- **Status:** fixed in `0176d8d`
- **Repro:** `test_bh_h16_guest_audio_during_showoff_without_speaker_tag_is_treated_as_guest`
- **Expected:** while `showoff.active()` is True, `Daemon._ask` requires explicit
  owner biometric verification (voiceprint match) or `owner_verified=True` before
  granting owner authority; unverified turns route to `_guest_turn`.
- **Actual (before):** `_ask` defaulted `speaker = "owner"` whenever `speaker`
  was omitted and no `embedding` was supplied, even during active show-off mode.

### BH-H17 — Show-off timeout racing `exit_owner()` raises `ShowoffError` instead of returning the expired session summary

- **Severity:** crash-with-safe-state
- **Status:** fixed in `0176d8d`
- **Repro:** `test_bh_h17_showoff_timeout_racing_owner_stop_returns_clean_summary`
- **Expected:** if the 30-minute timeout closes the session just before
  `exit_owner()` or `exit_hotkey()` runs, the exit call verifies the owner and
  returns the just-expired session summary idempotently.
- **Actual (before):** `self.status()` auto-closed the timed-out session first,
  causing `exit_owner()` to see `current is None` and raise `ShowoffError`.

### BH-H18 — `demo_write()` follows a symlink inside the demo sandbox to overwrite an outside file

- **Severity:** data-loss (security boundary)
- **Status:** fixed in `0176d8d`
- **Repro:** `test_bh_h18_demo_action_via_symlink_inside_sandbox_is_refused`
- **Expected:** `ShowoffService.demo_target()` rejects symlinks (`is_symlink()`)
  in any path component and verifies `resolve()` stays inside `sandbox.resolve()`.
- **Actual (before):** `demo_target()` checked lexical `Path(name).parts` only,
  allowing a symlink inside the sandbox to point outside.

### BH-H19 — Outgoing leak guard misses colon-delimited and paraphrased owner secrets

- **Severity:** data-loss (privacy boundary)
- **Status:** fixed in `0176d8d`
- **Repro:** `test_bh_h19_allowlist_fact_leaking_via_paraphrase_or_colon_value_is_blocked`
- **Expected:** `sensitive_values()` extracts values after `:`, `=`, `"is"`,
  `"called"`, `"named"`, `"set to"` as well as distinctive tokens from secret
  facts (`len >= 6`), blocking paraphrased secret leaks in `leak_in()`.
- **Actual (before):** `_VALUE_AFTER_IS` only matched `is|are|was|equals`, so
  `"My bank vault code: EmeraldFalcon"` had `sensitive_values() == []`.

### BH-H20 — `kill -9` mid-showoff leaves guest audio in sandbox and `guests_heard=0` on restart

- **Severity:** data-loss (privacy boundary)
- **Status:** fixed in `0176d8d`
- **Repro:** `test_bh_h20_crash_exit_mid_showoff_cleans_audio_residue_and_persists_guest_count`
- **Expected:** `record_guest_turn()` persists `guests_heard` incrementally in
  SQLite, and `recover_unclosed()` purges any `.wav`/`.pcm`/`.ogg`/`.flac`/`.mp3`/`.raw`
  residue from the demo sandbox on restart.
- **Actual (before):** `guests_heard` was only written on clean `_close()`, and
  `recover_unclosed()` did not sweep audio files from the demo sandbox.

### BH-H21 — Second daemon unlinks a live daemon's socket, and non-dict JSON frame crashes IPC handler

- **Severity:** crash-with-safe-state / wrong-action
- **Status:** fixed in `810bab4` / `e4108b5`
- **Repro:** `test_bh_h21_second_daemon_refuses_to_steal_active_socket_and_ipc_handles_non_dict`
- **Expected:** `ipc.serve()` probes the existing Unix socket before unlinking
  and raises `RuntimeError` if a live daemon is listening; non-dict JSON frames
  return `{"ok": False, "error": "TypeError: ..."}` without crashing.
- **Actual (before):** `serve()` unconditionally called `socket_path.unlink()`,
  stealing the live daemon's socket, and `request.get("id")` raised an
  unhandled `AttributeError` before `req_id` was initialized when `json.loads`
  returned a list.

### BH-H22 — `config.toml.example` table scoping bug (`[quota.models.transcribe-batch]`) and config schema drift

- **Severity:** wrong-action
- **Status:** fixed in `e4108b5`
- **Repro:** `test_bh_h22_config_example_parity_and_validation`
- **Expected:** flat `[quota]` keys in `config.toml.example` sit under `[quota]`
  before `[quota.models.*]`, every section/key in `config.toml.example` matches
  `DEFAULTS` in `src/assistant/config.py`, and `run_doctor()` validates config
  schema via `validate_config()`.
- **Actual (before):** `flash_rpm`, `flash_lite_rpm`, `max_requests_per_day`,
  and `max_requests_per_minute` were placed after `[quota.models.transcribe-batch]`
  (so TOML parsed them inside `transcribe-batch`), 10 keys drifted between
  `DEFAULTS` and `config.toml.example`, and `run_doctor()` had no schema check.


---

## Area I — Second hardening pass (2026-10-20, `arena/8952fe51-elaria`)

All thirteen were reproduced on `25179c8` by `tests/test_hardening_pass2.py`
(written first; 24 of its 28 cases failed before any fix).

### BH-I1 — Deprecated `gemini.model_voice` still beat an explicit `gemini_voice_model`

- **Severity:** wrong-behaviour (voice identity)
- **Status:** fixed in this pass
- **Repro:** `test_voice_model_explicit_new_key_wins_over_legacy_alias`
  (and `test_voice_model_legacy_alias_is_still_read_when_alone`)
- **Expected:** a key the owner's TOML actually names wins; the legacy alias is
  read only when the new key is absent, and never when it holds the removed
  TTS-preview id.
- **Actual (before):** `voice_model()` preferred any non-removed `model_voice`
  over `gemini_voice_model`. `BH-H4` had only filtered the specific removed id
  `gemini-2.5-flash-preview-tts`, so a file carrying both keys still spoke the
  legacy model while doctor reported the new key as authoritative.

### BH-I2 — Config poisoning passed validation and crashed the readers

- **Severity:** crash-with-safe-state / wrong-action
- **Status:** fixed in this pass
- **Repro:** `test_validate_config_names_poisoned_keys`,
  `test_doctor_survives_poisoned_config`,
  `test_speech_status_survives_poisoned_tts_values`,
  `test_organise_roots_rejects_bad_entries`
- **Expected:** `validate_config()` names the key, the expected shape and the
  bad value; `Config.section()` returns `{}` for a non-table; `organise_roots()`
  raises a named `ValueError`; doctor completes and reports.
- **Actual (before):** `gemini.mode="bogus"`, `tts.speaker="loud"`,
  `gemini.allowed_voices=5` and `organise.roots=[{"mode":"shadow"}]` all passed
  with zero errors/warnings. Downstream: `SpeechService.status()` raised
  `TypeError: 'int' object is not iterable`, `organise_roots()` raised
  `KeyError: 'path'`, and unknown keys were silently accepted (the
  accept-and-ignore bug class the task forbids).

### BH-I3 — `[console] history_limit` was documented but ignored

- **Severity:** wrong-behaviour
- **Status:** fixed in this pass
- **Repro:** `test_daemon_uses_console_history_limit`
- **Expected:** the daemon's one `SessionService` is constructed with the
  configured limit; `history_limit = 1` retains one message.
- **Actual (before):** daemon used the `SessionService` default (200) while
  `console.history` honoured the config, so follow-mode and print-mode
  disagreed about the same conversation.

### BH-I4 — A timed-out reply was synthesised and played twice

- **Severity:** wrong-behaviour (double audio, owner-visible)
- **Status:** fixed in this pass
- **Repro:** `test_timed_out_reply_is_spoken_once`
- **Expected:** one synthesis per utterance; a slow render keeps running in the
  background and the handler returns `queued=True`.
- **Actual (before):** `_maybe_speak_reply` waited 1.5 s, timed out, and queued
  `_speak_reply_async`; the original `to_thread` call was never cancelled, so a
  1.9 s utterance was spoken twice, overlapping.

### BH-I5 — Post-guard echo check suppressed legitimate short replies

- **Severity:** wrong-behaviour
- **Status:** fixed in this pass
- **Repro:** `test_short_user_reply_is_not_echo_after_guard`
- **Expected:** with the speaking guard expired, `"No."` is a user turn even if
  her last sentence contained the word.
- **Actual (before):** `_is_echo` used two-way substring containment, so any
  short reply (`"No."`, `"Yes."`, `"Ok."`) that appeared anywhere in her previous
  utterance was discarded as echo. Reproduced with
  `_speaking_until = 0` and `"No. Not at this hour."`.

### BH-I6 — Show-off crash recovery deleted EVERY dictation and meeting recording

- **Severity:** data-loss
- **Status:** fixed in this pass
- **Repro:** `test_showoff_crash_recovery_never_deletes_dictation_or_meeting_audio`
  (and the corrected `test_bh_h20_showoff_crash_exit_residue_cleaned_on_restart`)
- **Expected:** recovery purges only the demo sandbox, where the demo ever wrote.
- **Actual (before):** `_reconcile()` globbed `data_dir/audio/*.wav` and
  unlinked every match on the first start after `kill -9` — including
  dictation WAVs and `meeting-<stamp>-{mic,system}.wav`, i.e. the §12.5 record.
  The `BH-H20` test had encoded that deletion as the contract; it was corrected,
  not deleted (see `change.md`).

### BH-I7 — `initiative.status()["latest"]` reported the OLDEST pending knock

- **Severity:** wrong-behaviour
- **Status:** fixed in this pass
- **Repro:** `test_initiative_latest_is_newest_pending`
- **Expected:** `latest` is the newest pending knock (`list_knocks()` is id DESC).
- **Actual (before):** `pending[-1]` returned the oldest, so Waybar and the
  console announced a stale knock while a newer one was waiting.

### BH-I7b — A due knock refused every cycle was silent

- **Severity:** wrong-behaviour (observability)
- **Status:** fixed in this pass
- **Repro:** `test_due_loop_refusal_is_logged_not_swallowed`
- **Expected:** an `InitiativeError` while raising a due knock leaves the row
  snoozed but writes a `knock_due_refused` persona event (knock id, topic,
  reason).
- **Actual (before):** `except InitiativeError: continue` — a commitment that
  could never be raised vanished from all evidence surfaces while `pending`
  stayed non-zero.

### BH-I8 — Two daemons could still race the check-unlink-bind window

- **Severity:** crash-with-safe-state (socket loss)
- **Status:** fixed in this pass
- **Repro:** `test_ipc_serve_refuses_when_daemon_lock_is_held`,
  `test_ipc_serve_reclaims_stale_lock`
- **Expected:** `serve()` takes an exclusive `flock` on `<sock>.lock` before
  probing/unlinking; a held lock raises `RuntimeError("already running")`; the
  lock is released when the server closes.
- **Actual (before):** two starts that both observed a stale socket could both
  unlink and bind; one could delete the other's freshly bound socket (the
  `BH-H21` probe only narrowed the window, it did not close it).

### BH-I9 — Malformed IPC frames escaped as raw JSON errors; reply drain was unbounded

- **Severity:** crash-with-safe-state / hang
- **Status:** fixed in this pass
- **Repro:** `test_ipc_call_malformed_reply_is_daemon_unavailable`,
  `test_subscribe_events_skips_malformed_lines`,
  `test_play_audio_timeout_is_reported`
- **Expected:** `call()` raises `DaemonUnavailable` naming the malformed reply;
  event consumers skip non-object frames; a client that stops reading cannot
  park the handler (5 s drain bound); a player timeout is surfaced in
  `last_voice_error`.
- **Actual (before):** `json.loads` inside `call()` leaked `JSONDecodeError`
  (not a CLI error class), `subscribe_events()` killed the iterator on a torn
  line, `writer.drain()` had no bound, and `play_audio()` swallowed
  `TimeoutExpired` into a bare `False`.

### BH-I10 — A failed catalogue refresh downgraded a verified cache; timestamp-less cache was trusted

- **Severity:** wrong-action (voice selection)
- **Status:** fixed in this pass
- **Repro:** `test_catalogue_refresh_falls_back_to_verified_cache`,
  `test_catalogue_cache_without_timestamp_is_not_trusted`
- **Expected:** a refresh that returns nothing falls back to the verified cached
  catalogue and says why; a cache row with no `retrieved` stamp is unusable.
- **Actual (before):** `refresh=True` skipped the cache and returned the
  committed baseline (never checked against the API), and `load_cached()` with
  `max_age_s=None` accepted a cache row with no timestamp.

### BH-I11 — Needy framing survived paraphrases

- **Severity:** wrong-behaviour (persona boundary)
- **Status:** fixed in this pass
- **Repro:** `test_needy_paraphrases_rejected` (7 parametrised openers, e.g.
  "it's been quiet lately", "just checking you still want me",
  "you've been away")
- **Expected:** `NeedinessError` before any knock/speech.
- **Actual (before):** the `NEEDY_PATTERNS` list missed all seven; two of the
  seven were already caught by earlier patterns and stayed as regression pins.

### BH-I12 — A guest turn had no network timeout at all

- **Severity:** crash-unsafe (hung demo)
- **Status:** fixed in this pass
- **Repro:** `test_guest_turn_is_time_bounded`
- **Expected:** guest generation is bounded by the same 4 s ceiling as owner
  turns; a timeout yields a spoken fallback and the demo continues.
- **Actual (before):** `_guest_turn` called `asyncio.to_thread(self.client.generate, ...)`
  with no `wait_for`, so a stalled Live transport froze the show-off until the
  process was killed. The `TypeError`-as-feature-detect retry around it could
  also only fire after awaiting.

### BH-I13 — Waybar/console streams died on one malformed event line

- **Severity:** crash-with-safe-state (display only)
- **Status:** fixed in this pass
- **Repro:** `test_waybar_stream_survives_malformed_event_line`
- **Expected:** a non-JSON or non-object line is skipped and the stream keeps
  yielding.
- **Actual (before):** `json.loads(line)` in `stream_waybar()` raised and ended
  the generator; the bar froze until restart.

---

## Area J — Second-batch pins (2026-10-20, same branch)

Reproduced with `tests/test_hardening_pass2b.py` (5 cases; J1, J2 and J3 were
red before their fixes, J4/J5 were missing helpers, J6 was reproduced by
running the documented command chain).

### BH-J1 — Guest speech was written into the OWNER's conversation record

- **Severity:** privacy boundary / record contamination
- **Status:** fixed in this pass
- **Repro:** `test_non_owner_voice_never_enters_owner_conversation`,
  `test_showoff_guest_turn_never_enters_owner_conversation`
- **Expected:** the §16 conversation contains only turns addressed to the owner;
  a non-owner voice is audited through `disclosure.log_guest` and broadcast, but
  not persisted as `user`/`assistant` history.
- **Actual (before):** both guest paths (`_guest_turn_normal` for a TV/room
  voice, `_guest_turn` for show-off) called `sessions.append` twice. A guest
  utterance therefore appeared in `assist console`, was loaded as `prior_turns`
  context for the owner's next model turn, and was stored in SQLite as the
  owner's conversation. In show-off, guest turns also had no
  `disclosure.log_guest` row at all.

### BH-J2 — One connectivity probe error killed the posture loop

- **Severity:** crash-unsafe (frozen state)
- **Status:** fixed in this pass
- **Repro:** `test_connectivity_loop_survives_a_failing_tick`
- **Expected:** a failed probe is logged and the loop keeps its cadence.
- **Actual (before):** `_connectivity_loop` was a bare `while True` around
  `mode_manager.refresh(force=True)`. The first exception (DB locked, socket
  race, transient parse error) ended the background task silently. The daemon
  kept serving with a frozen connectivity posture — it could not transition to
  or from `OFFLINE`/`FORCED_OFFLINE` again, so queue drain and voice routing
  stayed stale until restart.

### BH-J3 — A second `assistd` printed a traceback instead of one line

- **Severity:** cosmetic (diagnosability)
- **Status:** fixed in this pass
- **Repro:** `test_second_daemon_exits_cleanly_with_one_line`
- **Expected:** `assistd: another daemon is already running …`, exit 1.
- **Actual (before):** the `RuntimeError` from `ipc.serve()` escaped `main()`
  as a full traceback. The first fix attempt in this pass also proved the test
  catches a missing `import sys` (NameError inside the handler), which is why
  the assertion is on stderr text, not just the exit code.

### BH-J4 — `assist forget <topic>` claimed "No argument, as designed."

- **Severity:** cosmetic (misleading output)
- **Status:** fixed in this pass
- **Repro:** `test_forget_message_names_the_topic_it_searched`
- **Expected:** name the topic searched and whether anything matched.
- **Actual (before):** the message was written when the topic argument was
  optional; with the now-required argument every miss printed the stale
  no-argument sentence. The parser help also still said "no argument".

### BH-J5 — Daemon refusals printed "refused: refused: …"

- **Severity:** cosmetic
- **Status:** fixed in this pass
- **Repro:** `test_refusal_text_does_not_double_the_prefix`
- **Expected:** exactly one prefix.
- **Actual (before):** `raise_knock` already raises `InitiativeError("refused: …")`
  and the CLI wrapped every exception in `refused: {exc}`.

### BH-J6 — README's `assist status && assist cost` chain stops when the daemon is down

- **Severity:** documentation (stale command)
- **Status:** fixed in this pass (README changed to `assist status; assist cost`)
- **Repro:** run both commands with no daemon: `assist status` correctly prints a
  `running: false` snapshot but exits 1 (service-down signal), so `&&` skips
  `cost` — the command you most want when the daemon is down.
- **Expected:** the documented command always shows cost.

## BUG 6f — Residual dictation latency and startup speaker self-capture (2026-10-20)

- **Severity:** wrong-action / record contamination, with avoidable batch latency.
- **Status:** fixed with offline protocol/audio-state regressions; owner hardware
  recheck remains outstanding (see `change.md`).
- **Repro:** `tests/test_bug6f_live_final_and_startup_ack.py`; the initial run
  against the old code was **12 failed, 1 passed**. The fixtures send 356 speech
  frames and the transcription-only model's committed `input_transcription`
  without `finished`/`turn_complete`, and play a queued ack while capture is open.
- **Expected:** committed Live input is saved directly without the final timeout
  or batch call; opening ack and speaker-tail frames reach neither Live uplink
  nor saved WAV, so inbox/clipboard contain only the user's sentence.
- **Was:** parser required an optional `finished=True` and ignored the separate
  interim envelope; ack playback bypassed the daemon speaking-state guard.
  Live consequently fell back despite valid committed text, while both the Live
  and saved-WAV paths could prepend `On it.` to the record.
- **Fix:** model-aware input-envelope normalization, continued SDK receive across
  model turns, final-wait re-arming for the released activity, privacy-safe
  receive diagnostics, and a synchronous ack gate reservation held through actual
  playback plus the 400 ms tail guard. Genuine failures retain 6e's bounded WAV
  recovery and durable capture stats; speculative/output text is not a final.

## BUG HUNT 2026-10-21 — BH-K series (see BUGHUNT-2026-10-21.md)

### BH-K1 — Dictated text containing a filler phrase was silently discarded

- **Severity:** data-loss
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_transcript_integrity.py::test_dictated_email_with_filler_signoff_is_kept` (fails pre-fix)
- **Expected:** dictating "Dear team, … Let me know how I can help with the board pack." returns that text with a transcript id and an inbox file.
- **Was:** a post-persist "BUG5 echo filter" in `DictationService.dictate` matched the final text against persona `FILLER_PHRASES` substrings ("let me know how i can", "how can i help", …) and, on any hit, replaced the already-persisted `SessionResult` with a fabricated empty one — raw/cleaned text, inbox path, clipboard and transcript_id all falsified while the store row kept the real words. The user got nothing; the record lied about it.
- **Fix:** block removed. Echo defence is upstream and evidence-based (frames during playback never reach uplink/WAV; duplex refuses self-audio finals; the daemon strips by exact spoken-text comparison, BH-K2). Resemblance to her filler is not evidence about user speech.

### BH-K2 — Daemon echo check wiped real dictation on timing alone

- **Severity:** data-loss
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_transcript_integrity.py` (`test_echo_requires_textual_match_not_timing`, `test_finish_dictation_keeps_text_that_lands_during_ack`, …)
- **Expected:** a transcript is echo only when its words are the words she just spoke; her words as a prefix are excised and the user's remainder kept.
- **Was:** `Daemon._is_echo` returned True whenever a transcript merely *finished* while an ack was playing (or inside the guard), with no textual comparison — `_speaking_text` is never cleared, so the timing branch was armed forever — and also on any `FILLER_PHRASES` substring. `_finish_dictation` then emptied `text`/`raw_text` in `ptt.result`. In command mode the general check ran *after* `_ask` had spoken its reply, so a routed command's own text was reported back as "" with "echo suppressed".
- **Fix:** `Daemon._strip_self_echo` compares normalised word sequences against `_speaking_text`: exact match or a ≥2-word contiguous run of her sentence is hers (the ≥2 floor preserves BH-I5's one-word "No."); her sentence as a prefix is stripped and the user's words kept. Applied once, before routing; `raw_text` remains the ASR record. Two assertions in `test_bugs_1_to_5_regressions.py` encoded the old rule and were updated with justification inline — the BUG5 incident line is still caught when she actually spoke it.

### BH-K3 — Committed Live finals were overwritten by the saved-WAV batch redo

- **Severity:** data-loss (silent substitution) + wrong-action (double transcription cost)
- **Status:** fixed in this pass; hardware sequence still to confirm (BH-K4/S2)
- **Repro:** `tests/test_bughunt_k_transcript_integrity.py` (`test_pause_then_release_silence_after_end_keeps_live`, `test_turn_complete_only_with_uncommitted_tail_recovers_via_batch`)
- **Expected:** the batch fallback replaces Live text only with positive evidence the Live text is missing or incomplete: nothing committed, or speech was sent after the last committed final and no clean post-release terminal arrived.
- **Was:** `needs_fallback = live_failed or live_terminal_missing or not final_text`. Any post-`activity_end` wait timeout — including the benign case where every segment committed during speech and the user simply paused before releasing — re-transcribed the WAV and assigned `final_text = fallback_text`, silently swapping the Live transcript (the one interims had shown) for a different batch transcription. Contributing cause: `GenaiLiveTransport` swallowed the server's `turn_complete` for the transcription-only model, so the boundary was invisible to collector, diagnostics and fixtures alike.
- **Fix:** (a) the parser surfaces `turn_complete` for both model shapes (finals in the same message are queued first); for the transcription-only model `events()` does not end there and the collector does not treat it as a terminal, because a committed segment can arrive *after* the boundary (test_bug6f) — it is evidence for diagnostics, not a completeness proof. (b) `dictate` now accounts in audio time: seconds of speech-level audio sent vs. sent at the moment the last final arrived. Batch runs only when no text was committed, or speech followed the last final *and* no clean post-release terminal arrived; every branch is stated in `notes`. The 6f guarantee is preserved: an unconfirmed tail is still recovered from the WAV, never truncated.

### BH-K4 — `GEMINI_MODE=record` never recorded Live session sequences

- **Severity:** wrong-action (broken debugging contract)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_record_mode.py`
- **Expected:** record mode = real API + fixtures saved (§12.9), including the streaming message sequence as `fixtures/seq-live.jsonl`.
- **Was:** `asr.make_live_transport` returned the bare `GenaiLiveTransport` for record mode; `RecordingTransport` existed and was tested in isolation but was wired into no production path. The documented way to capture evidence for the hardware "no final after activity_end" bug produced nothing.
- **Fix:** the factory wraps the real transport in `RecordingTransport(..., "live")` when `gemini_mode == "record"` (audio is logged as hash+size only, sequence written on close).

### BH-K5 — Voice render could hang a worker thread forever

- **Severity:** wrong-action (unbounded wait / thread-pool starvation)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_waits.py::test_run_coroutine_sync_*`
- **Expected:** a wedged Live voice session surfaces as a TimeoutError in bounded time.
- **Was:** `gemini_client._run_coroutine_sync` ran the render with no timeout in both branches (`asyncio.run` and `thread.join()`), and `render()`'s `async for message in session.receive()` can wait forever. TTS runs on the shared `to_thread` executor, so each hang permanently consumed a daemon worker thread.
- **Fix:** `_run_coroutine_sync(factory, timeout_s=60)` wraps the coroutine in `asyncio.wait_for`; the thread branch joins with a margin and raises `TimeoutError` (thread is daemonized). Voice render passes 30s.

### BH-K6 — Capture close could hang or leave pw-record running

- **Severity:** wrong-action / privacy (unbounded wait, orphaned microphone)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_waits.py::test_aclose_*`
- **Expected:** `PipeWireCapture.aclose()` always ends with the process dead, bounded, even if the caller cancels.
- **Was:** `terminate()` then `await proc.wait()` with no bound and no SIGKILL escalation; if the caller's lifecycle timeout cancelled the wait, the process was simply abandoned.
- **Fix:** bounded wait (`TERMINATE_TIMEOUT_S = 2.0`) then `kill()` + reap; on `CancelledError`, `kill()` before re-raising. The process handle is detached first so a second close is a no-op.

### BH-K7 — Hotword capture path: factory TypeError, leaked pw-record, silent stall

- **Severity:** crash-with-safe-state (factory) + privacy (orphaned live mic) + wrong-action (false "armed")
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_hotword_knock.py::test_hotword_*`
- **Expected:** `hotword start` builds a real capture; stop/stall always terminates pw-record and reports the true guard state.
- **Was:** three root causes, all invisible to tests that replace the factory: (1) `_hotword_capture_factory` passed `chunk_ms=` to `PipeWireCapture(frame_ms=...)` → TypeError on every production start; (2) `_hotword_loop`'s finally called a sync `close()` that does not exist on `PipeWireCapture` (only `aclose()`), so a running capture was never closed; (3) a capture stall ends `frames()`, but the loop then exited without disarming or broadcasting — `hotword status` claimed armed over a dead stream. The `[hotword] stall_timeout_s` (2s) was also never passed, silently using the 8s capture default.
- **Fix:** factory maps `[capture] chunk_ms` → `frame_ms` and passes the hotword stall timeout; the loop treats stream-end-while-armed as the stall (disarm + `hotword.stalled` broadcast); the finally awaits a shielded `aclose()` (with sync-`close()` fallback for test doubles) so cancellation by `hotword.stop` still reaps the process.

### BH-K8 — `assist plan build` polled a stuck "building" plan forever

- **Severity:** wrong-action (unbounded wait)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_waits.py::test_plan_build_poll_gives_up_on_a_stuck_building_plan`
- **Expected:** polling ends with a clear message if the plan never leaves `building`.
- **Was:** `while True` poll with no deadline. A daemon restart mid-build orphans the plan row in `building` (its build task died with the old process), so the CLI spun forever.
- **Fix:** total deadline `_PLAN_BUILD_POLL_DEADLINE_S = 600` in cli.py; on expiry it prints that the daemon may have restarted mid-build, points at `assist plan show`, and exits 1. Nothing was moved (build is shadow-only).

### BH-K9 — Knock delivery blocked the daemon event loop and bypassed the speaking gate

- **Severity:** wrong-action (loop stall) + duplex hole
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_hotword_knock.py::test_knock_emit_does_not_block_the_event_loop_and_is_gated`
- **Expected:** `knock.raise`/`knock.due` stay responsive while the notification/player subprocesses run, and the knock sound is treated as speaker output by capture gating.
- **Was:** `KnockSignal.emit` (two `subprocess.run(timeout=5)` calls) was invoked synchronously inside the async `_knock_raise`/`_knock_due` handlers — up to ~10s where every IPC call, including `ptt.stop`, waited — and the sound played with no speaking-gate marks, straight into any open microphone.
- **Fix:** both handlers now run emit via `asyncio.to_thread` with `_set_speaking` held (class mode short-circuits: silent pulse, no thread, no gate). `_set_speaking(True, text=None)` no longer clobbers `_speaking_text` (the BH-K2 echo reference). The code is inlined at both handlers so the BH-H13 boundary (knock emit reachable only from `_knock_raise`/`_knock_due`) is preserved unchanged.

### BH-K10 — Wake-guard posture probes failed OPEN

- **Severity:** wrong-action (authority/privacy leak)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_authority.py::test_*_probe_failure_fails_closed`
- **Expected:** if the presence/showoff probe cannot answer, the wake path takes the restrictive branch (console-not-PTT; guest door blocked).
- **Was:** `WakeGuard._in_class_mode()` and `_guest_door_blocked()` returned `False` on any exception from the wired probe, so a broken presence/showoff read let an accepted wake-knock open voice listening in class mode or during show-off — despite `WakeGuardError`'s own "fail closed" contract.
- **Fix:** exceptions now fail closed (`True`) and are recorded as `posture_error`, surfaced in `status()` so the restriction is diagnosable. Unwired probes (`None`, headless/tests) keep meaning "no such concept" and are unchanged.

### BH-K11 — Daemon's company posture was cached forever per-process

- **Severity:** wrong-action (privacy: disclosure on stale posture)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_authority.py::test_company_state_is_read_fresh_from_the_store`
- **Expected:** `DisclosureService.company()` reflects the stored state, whoever wrote it.
- **Was:** the first read was cached in `_company` for the process lifetime. The CLI's local path writes company state directly to the same SQLite store; the daemon never observed it — it could keep treating the room as private with company present (or stay restricted after they left). `PresenceService` already read fresh; disclosure did not.
- **Fix:** `company()` reads the store on every call; the cache field is removed. `set_company` is unchanged apart from dropping the cache write.

### BH-K12 — CLI treated daemon refusals as "daemon unavailable" and re-ran them locally

- **Severity:** wrong-action (silent substitution / split-brain writes; refusals reported as success)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_error_surfacing.py` — with the daemon UP, `assist review approve 999` printed "item 999: approved" and exited 0.
- **Expected:** a daemon `ok:false` reply is an authoritative refusal: printed as one, exit 2, no local retry. Local fallback happens only when the daemon is genuinely unreachable.
- **Was:** `ipc.call` raised plain `RuntimeError` for `ok:false`, and 37 CLI sites caught `(DaemonUnavailable, RuntimeError, OSError)` around the call and silently re-ran the operation against the local store/services. Refusals were masked (and sometimes converted to printed success: the local review path ignored `set_item_decision`'s rowcount and printed "approved" for nonexistent items); writes could also split-brain against a live daemon (see BH-K11 for the posture instance).
- **Fix:** `ipc.DaemonError(RuntimeError)` is raised for `ok:false`. CLI fallback sites now catch `DaemonUnavailable` only (print-and-continue surfaces — the console REPL and the ptt.result wait — catch both and print the real message). `main` gains a `DaemonError` net: `_refusal_text` + exit 2. Special cases kept honest: doctor distinguishes down vs erroring; `assist halt` still sets the flag file when the daemon errors (a kill switch must land) but now says so. The local review path checks the rowcount and exits 1 on a missing item.

### BH-K13 — wpctl parser offered the camera as a microphone

- **Severity:** wrong-action (mock-fidelity: green tests, dead hardware path)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_wpctl.py` with a full real-shape `wpctl status` (Audio + Video groups, Devices, Streams, Settings)
- **Expected:** `Sources` contains audio input nodes only.
- **Was:** sections were keyed by name alone and `current` was never reset on unknown headers — the Video group's `Sources:` (the camera) merged into audio Sources, `Streams:` entries (Firefox, pw-record) became "Source endpoints", and `Default Configured Devices:` entries polluted the last section. `meeting setup`/doctor thus offered cameras and streams as mic/system nodes. The existing fixture had an Audio group only, so this was invisible.
- **Fix:** track the top-level group (Audio/Video/Settings) and collect only under Audio; any other header line ends the current section.

### BH-K14 — Disconnected event subscribers were never removed

- **Severity:** wrong-action (slow leak; false status)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_subscribers.py`
- **Expected:** when an `events.subscribe` client disconnects, its writer leaves `Daemon._subscribers` immediately.
- **Was:** `ipc.serve` closed the writer in the connection's finally but never told the daemon; pruning happened only when a later broadcast failed writing to the corpse. Owner observed 2 leaked subscribers in `status`.
- **Fix:** `ipc.serve(..., on_disconnect=...)` is invoked in the connection finally (before close, teardown-safe); the daemon passes `self._subscribers.discard`. The broadcast-time prune remains as backstop.

### BH-K15 — Executor operations raced across processes (cap double-spend)

- **Severity:** wrong-action
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_executor.py::test_executor_refuses_to_race_another_process`
- **Expected:** one organise mutation at a time, daemon and CLI combined; the second runner is refused clearly.
- **Was:** no serialisation at all. The daemon applies in a thread while a CLI invocation can apply/undo in its own process; both read the hourly budget (`ops_since`) before either journaled — double-spending `max_ops_per_hour` — and could move the same files concurrently.
- **Fix:** `Executor._operation_gate()` wraps apply/undo/trash: a non-blocking process lock plus an `flock` on `<db>.executor.lock`. Contention raises a clear `RuntimeError` (surfaced via IPC/CLI, BH-K12). Re-entrant on the holding thread (undo retires duplicates via trash). `verify()` is read-only and deliberately ungated.

### BH-K16 — trash() claimed success for moves that had failed

- **Severity:** wrong-action (false report; file believed trashed)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_executor.py::test_trash_same_name_twice_both_land_and_report_truly`
- **Expected:** `trashed_as` names a file that actually landed in trash; failures say so.
- **Was:** the destination name had second resolution, so two same-name files trashed within one second collided; the journaled move failed, yet the manifest and the return value still claimed `trashed_as=<dest>`.
- **Fix:** destination uniquified (`name (2)`, `(3)`, … — same style as `_Conflicts`); `trashed_as` in both the manifest and the return is set only when the move actually applied.

### BH-K17 — Undo of a `copied` op failed with a misleading FileExists

- **Severity:** wrong-action (undo unavailable precisely for crash-interrupted ops)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_executor.py::test_undo_of_copied_op_reconciles_identical_duplicate`
- **Expected:** undoing an op whose both copies exist identically (crash between copy-verify and source unlink) reconciles: bytes stay at the original location, the duplicate is retired journaled, the op rolls back.
- **Was:** undo fell through to `_journaled_move`, whose no-overwrite rule (correctly) refused the occupied destination; the op reported a raw FileExists problem and could never be undone.
- **Fix:** when the original location already holds identical content, undo retires the duplicate through the journaled trash path (recoverable — never a bare unlink) and marks the op rolled back.

### BH-K22 — Shared SQLite store had no WAL / busy-timeout posture

- **Severity:** wrong-action (cross-process "database is locked" failures)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_store.py`
- **Expected:** daemon + CLI + doctor share the DB without lock failures under brief contention.
- **Was:** default rollback journal, implicit timeout — the exact multi-process shape (daemon resident, CLI one-shots writing state/facts/queue rows) that produces locked-database errors.
- **Fix:** `PRAGMA journal_mode=WAL` + `busy_timeout=5000` at open (with an explicit connect timeout). Companion honesty fix: `forget_facts` by-id now also filters `active = 1`, so double-forget counts 0 instead of recounting.

### BH-K20 — Config keys the code read were undeclared and undocumented

- **Severity:** cosmetic (doctor false "unknown key"; undiscoverable knobs)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_config.py::test_keys_the_code_reads_are_declared_and_documented`
- **Was:** `[organise] tier1_batch_size`/`tier2_batch_size` (planner_llm), `[hotword] sample_rate` (daemon) and `[hotword] unit_path` (wake_guard) were read with in-code defaults but absent from DEFAULTS and config.toml.example.
- **Fix:** declared in DEFAULTS with the code's defaults (50/10/16000/"") and documented in the example.

### BH-K21 — meeting.start ignored the documented [capture] mic_target

- **Severity:** wrong-action (meetings recorded the PipeWire default mic)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_config.py::test_meeting_mic_*`
- **Was:** dictate/hotword resolve `param → [capture] → [meeting]`, but `_meeting_start` read `[meeting] mic_target` only — an owner who set their mic under `[capture]` (as the example documents) got the default source in meetings.
- **Fix:** meeting resolves `[meeting] mic_target → [capture] mic_target → default` (its own section wins, the documented capture mic is the fallback).

### BH-K24 — Malformed config.toml crashed every command with a traceback

- **Severity:** crash-with-safe-state (every invocation, until fixed by hand)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_config.py::test_malformed_config_is_a_one_line_error_exit_2`
- **Was:** `load_config()` ran before `main()`'s try and the raw `TOMLDecodeError` (no filename in the message) propagated as a traceback; same in `assistd`.
- **Fix:** `load_config` wraps parse/IO errors as `ValueError("cannot parse config <path>: …")`; both entry points print one line and exit 2.

### BH-K18 — Per-model quota (RPD) was configured but never enforced

- **Severity:** wrong-action (quota burned into opaque 429s; two drifting sources of truth)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_quota.py`
- **Expected:** the verified per-model limits in `[quota.models.*]` (flash 20 RPD!) stop calls locally with a clear refusal; flat keys and structured rows cannot silently disagree.
- **Was:** only the flat `flash_rpm`/`flash_lite_rpm` fed the limiter and only a global 1200/day cap existed. The 21st flash call of the day went out, earned a 429, and burned backoff time before failing opaquely. Also latent: `PerModelLimiter` clamped rpm to `max(1, …)`, so a configured `0` ("not rate-limited", per the config comments) meant 1/minute.
- **Fix:** `quota_family()` maps model ids to quota rows; `rpm_for` takes the stricter of structured vs flat (0/unlimited in a row disables the limiter for that model, which now honours ≤0); `_check_daily_cap(model)` additionally enforces the family's RPD from the ledger with a clear `QuotaExhausted`; `validate_config` warns when flat and structured values disagree.

### BH-K23 — Keyword spotter scored a single 30 ms frame, not a window

- **Severity:** dead-hardware-path (acoustic arming could never fire with a real model)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_keyword_window.py`
- **Expected:** `score_window` receives a trailing window of audio (the ring exists precisely to hold it).
- **Was:** `WakeGuard.feed()` passed the single 30 ms frame just received. No keyword model recognises a phrase in 30 ms; the energy test model masked it because RMS works on any length.
- **Fix:** `feed()` scores the trailing `[hotword] keyword_window_s` (default 1.0 s, validated 0.1–2.0) slice of the pre-wake ring, ending with the frame just fed.

### BH-K19 — `[asr] assert_output_language` was never called

- **Severity:** dead promise (silent-translation guard, §12.4)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_language_assert.py`
- **Expected:** with the flag on (default), a transcript whose language tag falls outside the pinned set is caught — the exact silent-translation failure mode the blueprint says this key catches.
- **Was:** the helper `asr.assert_output_language` and the config key both existed; zero call sites in `src/` (only a unit test of the helper itself). The content-level marker gate in cleanup was wired; the tag gate was not.
- **Fix:** enforced at the one seam every batch transcript crosses (`asr.transcribe_file`): an out-of-set result is passed over for the next backend; if the chain exhausts it returns degraded-but-marked (`Transcript.language_ok=False`), and both `Transcriber` batch call sites surface a loud session note. Flag off restores first-result-wins.

### BH-K25 — Flat 120 s timeouts on audio playback and Piper synthesis

- **Severity:** wrong-output / bounded-wait (long speech truncated; hung player stalls)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_tts_timeout.py`
- **Expected:** waits proportional to the work: a 200 s utterance plays to the end; a wedged player on a 1 s chirp is caught in seconds.
- **Was:** `play_audio` and Piper `synthesize` both used a flat `timeout=120` — long read-alouds were killed mid-speech and misreported as player failures, while a hung player blocked its thread for two minutes on any clip.
- **Fix:** playback bound derived from the WAV header (duration × 1.5 + 10 s, floor 15 s, cap 30 min; 120 s only when unreadable); synth bound scales with text length (60 s floor, 600 s cap). Both remain finite.

### BH-K26 — Doctor drift check covered only one of the shipped-and-copied files

- **Severity:** stale-deployment (disease 5; the LimitCORE pattern, generalized)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_doctor_drift.py`
- **Expected:** every file the install instructions copy elsewhere is drift-checked by doctor.
- **Was:** only `systemd/assistant.service` was compared. `elaria-overlay.service`, `elaria-console.service`, the installed knock sound (which shadows the repo asset), and the appended Hyprland binds could all go stale invisibly; the UI units' hardcoded `%h/Elaria` quickshell path was never sanity-checked against the actual checkout.
- **Fix:** `_deployment_drift_checks()` byte-compares all three units + knock.wav (LimitCORE callout retained), verifies each UI unit's `quickshell -p` target exists, and checks the load-bearing bind markers in an existing Hyprland config. Merged files (Waybar module/style) remain unchecked — they are not byte copies.

### BH-K27 — ECAPA scoring wrote the wake clip to /tmp

- **Severity:** privacy (wake audio on a persistent filesystem, contradicting the RAM-only design)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_ecapa_memfd.py`
- **Expected:** wake audio never touches disk — the ring/pending buffers are anonymous mmap + MADV_DONTDUMP precisely so a crash leaves nothing.
- **Was:** `EcapaCommandScorer.score_owner` used `NamedTemporaryFile(delete=False)` in the default temp dir and unlinked after the run; a SIGKILL in between (or a non-tmpfs /tmp) left the wake utterance on disk.
- **Fix:** the clip travels in an anonymous memfd inherited by the child (`/proc/self/fd/N`, `pass_fds`); a `/dev/shm` file remains only as the non-Linux fallback.

### BH-K28 — Dangling symlinks / unhashable paths crashed executor operations

- **Severity:** crash (batch operations die on ordinary folder contents)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_symlink_hash.py`
- **Expected:** one dangling symlink (routine in ~/Downloads) yields a per-item refusal, like every neighbouring guard.
- **Was:** `trash()` and `verify()` (and the apply/undo hash comparisons) called `sha256_file` unguarded; a dangling symlink raised FileNotFoundError and a symlink-to-directory raised IsADirectoryError, escaping as a raw daemon error mid-batch.
- **Fix:** `safety.try_sha256_file` returns None on OSError; comparison/refusal sites use it (None never equals an expected hash, so existing refusal branches fire). `trash` returns its standard refusal dict ("unreadable…"); strict `sha256_file` remains for post-move verification, where raising is correct and journaled.

### BH-K29 — Missing/mistyped IPC ids surfaced as TypeError/KeyError gibberish

- **Severity:** error-surfacing (traceback-flavoured text to users of the IPC surface)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_param_coercion.py`
- **Expected:** a client that omits `id` gets "parameter 'id' is required (integer)" via the daemon's ValueError refusal channel.
- **Was:** `int(params.get("id"))` / `int(params["item_id"])` / `int(params["job_id"])` raised TypeError/KeyError, which the IPC layer stringified verbatim ("TypeError: int() argument must be…").
- **Fix:** `daemon._int_param()` coerces with a named ValueError at the knock, review, queue-approve and knock-raise commitment sites.

### BH-K30 — Plan-build tasks leaked; early build failures stranded plans at 'building'

- **Severity:** wrong-output + unbounded growth (minor)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_plan_tasks.py`
- **Expected:** finished build tasks are forgotten; a failed build's plan row says `failed` with the error.
- **Was:** `_plan_tasks` only ever grew. And while `Organiser.build_plan` marks its own failures, a failure before its try (invalid root mode) or after it (tier enqueue) left the daemon-reserved row at 'building' forever — `plan.show` reported a build that would never end.
- **Fix:** done-callback prunes the task; `_run`'s failure path marks a still-'building' plan failed via `finish_plan(error=…)`.

### BH-K31 — `status` silently swallowed its last-capture diagnostics failure

- **Severity:** cosmetic/diagnostics (silent discard)
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_status_surface.py`
- **Expected:** a broken capture-stats read is visible in the status payload.
- **Was:** `except Exception: last_capture = None` — indistinguishable from "no capture session ever ran", hiding the failure exactly when capture debugging needs it.
- **Fix:** `last_capture = {"error": …}`; the aggregator stays up, the hole is labelled. Also in this commit: removed a fully-shadowed dead `is_user` assignment in `GeminiClient._call_once` (every branch below it reassigned before use; quota attribution unchanged, pinned by existing tests) and the unused `_WAKE_BOUNDARY` regex in `hotword.py` (zero references repo-wide).

### BH-K32 — `assist knock accept|decline|…` bypassed the running daemon (recon S10, proven)

- **Severity:** authority/privacy plumbing + fabricated output
- **Status:** fixed in this pass
- **Repro:** `tests/test_bughunt_k_knock_daemon_first.py`
- **Expected:** knock actions settle where the state lives: the daemon (WakeGuard authentication, conversation, signal delivery). A wake-knock voice-accept must verify.
- **Was:** every mutating knock action drove a local `InitiativeService` directly, even with the daemon up. Accept printed "voice · first line: <reason>" while the reason was never appended to the daemon's conversation nor spoken (the local service has no sessions). A wake-knock could be "accepted" with zero WakeGuard involvement while the guard stayed in `wake_knock` holding its pending utterance; decline/ignore never zeroed that RAM-only audio via the deny path; raise/due delivered no knock signal at all.
- **Fix:** `_knock_command` calls the daemon first for raise/accept/decline/later/ignore/due (refusals surface as exit 2 per BH-K12). The local store remains the fallback for a stopped daemon only, and there a wake-knock *accept* refuses — only the guard can settle it, and its pending audio died with the daemon process.

### BH-K33 — Overlapping meeting stops reused raw WAV paths and cleared processing early

- **Severity:** data-loss (silent session substitution) + wrong-action (mode switch unparked early)
- **Status:** fixed in this pass
- **Invariant (prose):** each meeting's captured bytes remain bound to that session until archival; processing remains active until every in-flight stop finishes.
- **Root cause:** `_meeting_stop()` named raw WAVs with only second-resolution timestamps. It also used one shared boolean for concurrent transcriptions, so the later stop could clear it while an earlier worker was still pending. A transcription failure could leave `mode="processing"` because cleanup and mode restoration were not in the same `finally` block.
- **Repro:** `tests/test_bug_meeting_raw_collision.py::test_bug_meeting_overlapping_stops_keep_each_sessions_raw_wav` freezes the clock, pauses the first real `MeetingService.transcribe_dual()` before its source copy, then stops a second session with distinct bytes. Before the fix, both stops used the same raw path, the first archive contained the second session's bytes, and processing was false while the first stop remained pending. `tests/test_bug_meeting_stop_failure.py::test_bug_meeting_transcription_failure_restores_mode_and_unparks_switch` proves a failed ASR worker also releases the processing gate and applies the parked preference.
- **Verifier:** `pytest -q tests/test_bug_meeting_raw_collision.py tests/test_bug_meeting_stop_failure.py tests/test_phase6_meeting.py tests/test_bughunt_k_config.py tests/test_bughunt_systems.py -k meeting` — **14 passed, 60 deselected**; Ruff on touched Python files passed.
- **Fix:** assign a UUID to each meeting at start, include it in the raw WAV names, track processing session IDs in a set, recompute global mode from active capture/processing state, and restore mode/apply parked switches in `finally` on success or failure.

### BH-K34 — Sample capture and eval splitting could escape or corrupt the dataset

- **Severity:** data-loss (out-of-root writes, take replacement, or a changed/stale eval split); wrong-action for invalid capture arguments reported as success
- **Status:** fixed in this pass
- **Invariant (prose):** captured WAVs stay beneath the selected sample root; existing samples are never replaced; a frozen eval split, its files, and manifest paths agree and cannot silently change; invalid recording requests do not reach capture or report success.
- **Root cause:** bucket text was inserted into filesystem paths without component validation; second-resolution filenames plus per-invocation indices collided across commands; `Path.rename()` could replace an existing eval file; bucket/manifest symlinks were followed; `freeze_eval()` clamped fractions, allowed repeated runs, and did not update manifest paths; `takes` and `seconds` were not validated.
- **Repros:** `tests/test_bug_record_elaria_samples.py` covers bucket traversal, same-second replacement, invalid counts/durations, manifest symlink refusal, symlinked train/eval buckets, destination collision, zero/out-of-range/non-finite fractions, stale manifest paths, repeat freeze, partial-move rollback, manifest-write rollback, and retention of an in-progress marker when recovery is uncertain. The first red run failed on bucket escape, symlink traversal, eval overwrite, fraction-zero movement, and stale manifest; the second red run failed on bucket escape, same-second replacement, and invalid capture arguments. The Phase 0 fraction-2 probe moved every take. Existing coverage is in `tests/test_wake_knock_package.py`.
- **Verifier:** `.venv/bin/pytest -q tests/test_bug_record_elaria_samples.py tests/test_wake_knock_package.py` — **50 passed**; `.venv/bin/ruff check scripts/record_elaria_samples.py tests/test_bug_record_elaria_samples.py` and `git diff --check` passed. Real `pw-record`/PipeWire behavior was not tested.
- **Fix:** validate bucket names and root containment; refuse symlinks; use UUID filenames and reject existing capture destinations; validate positive finite recording parameters and a finite `[0, 1]` eval fraction; move with a no-overwrite same-filesystem link/unlink; enforce the one-shot `.frozen` marker; update the manifest atomically; roll back pre-commit failures and keep an in-progress marker if recovery may be incomplete. Cross-filesystem splits fail safely instead of falling back to an overwriting move.

### BH-K35 — IPC timeout after dispatch triggered a duplicate local enqueue

- **Severity:** wrong-action (a duplicate external job can be approved and executed twice)
- **Status:** fixed in this pass
- **Invariant (prose / I1):** each CLI request causes at most one durable side effect; local fallback is allowed only when the daemon request was never sent.
- **Root cause:** `ipc.call()` translated all socket `OSError`s and malformed/empty replies into `DaemonUnavailable`, even after `sendall()`. `_queue_command()` interpreted that as safe daemon absence and enqueued the same external action in the local SQLite store although the daemon had already committed it.
- **Repro:** `tests/test_bug_queue_timeout_duplicate.py::test_bug_queue_timeout_after_commit_does_not_enqueue_again` uses the real Unix-socket server and real `CloudQueue`: the daemon commits the job, delays the reply 300 ms, and the client deadline is 50 ms. Before the fix the CLI returned success with **two** matching durable `external_action` rows. After the fix it returns 1, explains that the result is unknown and not retried, and leaves exactly one row. `tests/test_hardening_pass2.py` also proves malformed and empty replies after send are outcome-unknown; the missing-socket and offline-queue tests prove definite pre-send unavailability still uses the local fallback.
- **Verifier:** `.venv/bin/pytest -q tests/test_bug_queue_timeout_duplicate.py tests/test_hardening_pass2.py tests/test_bughunt_k_error_surfacing.py tests/test_bug6d_ptt_result_orphans.py tests/test_phase8_offline_voice.py` — **70 passed**. Full Ruff and `git diff --check` passed.
- **Fix:** `DaemonUnavailable` now means the request was not sent; `DaemonOutcomeUnknown` means sending may have begun but no authoritative reply arrived. The latter is not caught by local fallback handlers. Queue and knock commands report the ambiguity without replaying. A valid `ok: false` still remains an authoritative `DaemonError`.

### BH-K36 — Total chat timeout left live generation work running

- **Severity:** unbounded work / I3 total-deadline and cancellation violation
- **Status:** fixed in this pass; real Gemini network cancellation remains UNVERIFIED on hardware
- **Invariant (prose / I3):** once a chat's total deadline expires, no live generation request or worker may continue running in the background; cancellation must not be replaced by a larger timeout.
- **Root cause:** `Daemon._generate()` used `asyncio.to_thread()` and shielded its task. Raising `ChatTimeout` stopped waiting but could not stop the synchronous SDK call, leaving its task tracked and its worker blocked. The Google SDK 1.x `aio` facade also delegated HTTP requests to `asyncio.to_thread`, so switching method names alone would not cancel the request.
- **Red repro:** before the fix, `tests/test_bug_generate_worker_cancellation.py` blocked a synchronous backend on a threading event and set first-token/total deadlines to 20/80 ms. The caller raised `ChatTimeout` at the total bound with **one pending `to_thread` task** still blocked until the test released the worker.
- **Fix:** live chat now uses `_SdkTransport.generate_async()` and the SDK's native async HTTP stream; `GeminiClient.generate_async()` retains quota checks, cancellable async RPM waiting, retries, verification, and ledger writes. The absolute caller deadline is passed through retries and into the SDK request timeout; `_generate()` cancels rather than shields the async task. The live extra/runtime guard requires `google-genai>=2.0.0` because 1.x implements its async request through a synchronous worker. Fixture/legacy synchronous transports retain the existing compatibility path.
- **Verifier:** `.venv/bin/pytest -q tests/test_bug_generate_worker_cancellation.py tests/test_hotword_and_reply_delivery.py tests/test_disclosure.py tests/test_fixtures_and_harness.py tests/test_bughunt_k_quota.py` — **75 passed**; full `.venv/bin/ruff check .` and `git diff --check` passed. Installed `google-genai==2.0.0` locally and verified `_SdkTransport`'s SDK streaming method is a coroutine; no Gemini key/network call was made.
- **Hardware check (UNVERIFIED):** after installing the live extra and restarting the owner daemon, run the forced-deadline probe recorded in `BUGHUNT-ARENA-2026-10-21.md`; it requires the owner's valid key and checks the real SDK stream cancels with no remaining `_background_tasks`.

### BH-K37 — `ptt.result` accepted infinite wait budgets and orphaned handlers

- **Severity:** unbounded wait / daemon handler leak (I3 total-deadline violation)
- **Status:** fixed in this pass
- **Invariant (prose / I3):** a request-supplied PTT wait budget is finite and bounded; untrusted `Infinity`, NaN, negative, or oversized values cannot create a handler that outlives its deadline.
- **Root cause:** `float(params.get("wait_s") or 0)` accepted `Infinity`; `_ptt_wait_for()` then built an infinite deadline and awaited an event with no expiry. The IPC server awaits each handler inline and does not notice a client disconnect until the handler returns.
- **Red repro:** `tests/test_bug_ptt_infinite_wait.py` sends `ptt.result` over a real Unix socket with `wait_s=float("inf")` and a 1 s client deadline. Before the fix, the request ended as `DaemonOutcomeUnknown` rather than an immediate refusal, and the instrumented daemon-side waiter remained pending after the client timed out. The same regression now covers `ptt.stop`.
- **Fix:** `_ptt_wait_budget()` rejects booleans, parse failures, non-finite, negative, and greater-than-90-second budgets. Both `ptt.result` and `ptt.stop` use it; `ptt.stop` validates before emitting an ack or changing session state. The 90-second cap matches the existing CLI's largest explicit wait and does not widen it.
- **Verifier:** `.venv/bin/pytest -q tests/test_bug_ptt_infinite_wait.py tests/test_bug6d_ptt_result_orphans.py tests/test_phase2_surfaces.py tests/test_phase1_dictation.py tests/test_phase8_offline_voice.py tests/test_bug6_live_duplex_and_stop.py` — **90 passed**. No audio hardware or Gemini key/network was involved.

### BH-K38 — daemon shutdown left active meeting capture running

- **Severity:** privacy/capture-lifetime leak (microphone/system capture survives owner-daemon shutdown)
- **Status:** fixed in this pass
- **Invariant (prose):** daemon shutdown releases every active audio source and stops the collector that owns it.
- **Root cause:** `Daemon.aclose()` cancelled dictation/background tasks but omitted `_meeting`, whose `DualCapture` and collector task are stored separately.
- **Red repro:** `tests/test_bug_daemon_aclose_meeting_capture.py` creates an active meeting plus a pending collector, calls `Daemon.aclose()`, and checks capture closure, collector completion, and detachment. Before the fix, all three assertions failed. It uses a device-free capture double.
- **Fix:** shutdown detaches the active meeting, cancels its collector, calls `DualCapture.aclose()`, includes that task in cleanup gathering, resets mode when needed, and reports capture-close errors without skipping remaining shutdown.
- **Verifier:** `.venv/bin/pytest -q tests/test_bug_daemon_aclose_meeting_capture.py tests/test_bug_meeting_stop_failure.py tests/test_bug_meeting_raw_collision.py tests/test_phase6_meeting.py` — **10 passed**. No microphone, PipeWire, or Gemini key/network was used.
- **Hardware check (UNVERIFIED):** on Fedora with live PipeWire sources, run `assist meeting start`, record the `pw-record` child PIDs with `pgrep -af '[p]w-record'`, then run `systemctl --user stop assistant`. Confirm those exact PIDs exit and the mic/system nodes are released; restart with `systemctl --user start assistant`.

### BH-K39 — live meeting transcription could outlive stop and shutdown

- **Severity:** unbounded wait / abandoned request (prose invariant / I3 total deadline and cancellation)
- **Status:** fixed for the live Gemini batch-ASR path and daemon shutdown during `meeting.stop`; offline/native-ASR limits remain SUSPECT
- **Invariant:** live upload and generation share one absolute meeting budget; expiry cancels the request, preserves both raw WAVs, and starts no later utterance. Completed transcripts are not rejected by a stale post-completion deadline check. Daemon shutdown cancels an active stop request only after protecting dual-capture close, and a cancelled provider attempt is ledgered.
- **Root cause:** `_meeting_stop()` awaited synchronous `MeetingService.transcribe_dual()` in `asyncio.to_thread()` without a deadline. SDK `HttpOptions.timeout` defaults to `None`; synchronous HTTP timeouts alone cannot guarantee coroutine-level cancellation. Separately, `Daemon.aclose()` omitted in-flight `meeting.stop` handler tasks, and cancellation during the handler's sequential `DualCapture.aclose()` could leave a capture channel open and skip the failed-request ledger write.
- **Before-fix red repros:** `tests/test_bug_meeting_stop_deadline.py::test_bug_meeting_stop_bounds_live_request_and_retains_raw_audio` uses the real Unix socket and controlled SDK seams for upload and generation; the pre-fix blocked upload produced `DaemonOutcomeUnknown` with a pending worker. `test_bug_daemon_aclose_cancels_pending_live_meeting_stop` failed with the stop handler still pending when it was omitted from the shutdown task set. `test_bug_meeting_stop_shutdown_finishes_both_capture_closes` failed when shutdown interrupted sequential dual-capture close. Shutdown tests also assert task/ledger cleanup, both capture closes, and idle mode.
- **Fix:** `MEETING_TRANSCRIPTION_TIMEOUT_S=840` stays 60 s inside the existing 900 s IPC timeout. Live daemon and direct CLI paths use native async SDK upload/generation, `asyncio.timeout_at(deadline)`, and the remaining time in each `http_options.timeout`; no synchronous Gemini network worker is abandoned in `to_thread`. `meeting.stop` tracks its handler so `Daemon.aclose()` cancels and gathers it; capture close is shielded through completion, stale meeting mode is reset, cancellation is logged as a failed request, and raw WAVs remain durable. A completed transcript is persisted without a post-completion expiry check.
- **Verifier:** focused meeting/deadline/PTT/shutdown command — **69 passed**; `.venv/bin/ruff check .` and `git diff --check` passed. The first full-suite run had **1,543 passed, 2 failed, 6 skipped**: the handler-integrity audit misclassified `_meeting_stop_impl(params)` as a dispatch handler, and the BH-H1 `_SdkTransport` test double implemented only sync methods after BH-K36 introduced the native async interface. Renamed the helper parameter to `request` and updated that fake to implement `generate_async`. Fresh `.venv/bin/pytest -q` — **1,545 passed, 6 skipped** (**1,551 collected**) versus the user's stated **1,393** baseline. SDK 2.0.0 async methods/config types were inspected locally; no live key or network request was made. The 10-seed randomized/coverage run on the initial checkout (1,506 collected, 1,500 passed, 6 skipped) has not been repeated on the current tree.
- **Hardware check (UNVERIFIED):** with the owner's key on Fedora, run `assist meeting start`, record several utterances, then `time assist meeting stop`; verify `assist status`, the resulting note, and `assist cost` batch rows. This exercises successful live upload/generation but not a forced provider stall; timeout behavior under real networking remains unverified.

## SUSPECTS from the 2026-10-21 hunt — unproven, NOT fixed (evidence + settling check in BUGHUNT-2026-10-21.md)

- **S1** Live model ids exist for the owner's key → `assist voice models`.
- **S2** Final segment vs `turn_complete` ordering after `activityEnd` → `GEMINI_MODE=record` dictate, read `fixtures/seq-live.jsonl` (possible after BH-K4).
- **S3** `generate_audio` fallback `send_realtime_input(text=…)` may not end the turn → `assist voice say "test"` on hardware.
- **S4** `ipc.subscribe_events` has no read timeout (a wedged-but-alive daemon freezes Waybar/console feeds silently) → design call; needs an owner decision on feed-liveness semantics.
- **S5** `no_speech` gate (peak RMS < 0.003) may discard very quiet real speech → quiet dictation + compare `capture.stats`.
- **S6** Duplex guard may drop a genuine user `final` inside the 400 ms output window → record-mode session with an interjection during her reply.
- **S7** Hotword scoring/verify run on the event loop (onnx + ECAPA subprocess) → ack-latency measurement on hardware.
- **S8** `_sdk_transcribe` and live `transcribe_batch_async` upload Gemini Files but do not delete the remote file; provider retention/expiry remains unverified. After a sanitized batch transcription, list the owner's Gemini Files via AI Studio/SDK.
- **S9** offline meeting ASR remains unbounded after BH-K39: `_transcribe_channel_async` runs `LocalWhisperBackend.transcribe()` in `asyncio.to_thread()` without deadline/cancellation, while optional `PyannoteDiarizer.diarize()` runs synchronously without a deadline. A stuck inference/refinement can still park `_meeting_processing` or the event loop. Settle on the owner's forced-offline path with `time assist meeting stop` while another terminal runs `watch -n 1 assist status`; if `pyannote_refine=true`, repeat with refinement enabled. Do not add a blind timeout that discards a completed transcript.
- **S10** real Google SDK timeout enforcement remains UNVERIFIED: fake SDK tests cancel both upload and generation, and installed SDK source maps the remaining-time configs to HTTP timeouts, but no live provider/network request or forced stall was run. With the owner's key, run `assist meeting start`, record several utterances, then `time assist meeting stop`; confirm a note, `assist cost` ledger rows, and idle `assist status`. This exercises real requests but does not force a stall.
