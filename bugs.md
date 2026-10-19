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

## Open reproduced bugs from Areas A–C

### BH-A4 — Protected paths ignore `$VAR` spelling

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_protected_path_env_var_spelling_is_honoured`
- **Expected:** `$HOME/secret` protects the expanded directory.
- **Actual:** only `~` expansion is honoured; `$HOME/...` is treated as a
  literal relative path.

### BH-B1 — Move completed before journal commit is not undoable

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_kill_after_move_before_commit_can_be_undone`
- **Expected:** after restart, an outstanding intent whose bytes are at the
  destination can be reconciled/undone.
- **Actual:** undo only considers `committed` operations, so the moved file is
  stranded outside the normal undo path.

### BH-B2 — Partial cross-device copy is left at the destination

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_disk_full_mid_move_leaves_no_partial_destination`
- **Expected:** disk-full during a cross-device copy leaves the source and no
  misleading partial destination.
- **Actual:** the source is preserved, but a partial destination remains for
  inspection. This follows the never-delete bias, but is not yet reconciled
  into a named partial/quarantine state.

### BH-B3 — Executor-level bare undo unwinds all committed history

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_bare_undo_refuses_without_scope`
- **Expected:** `Executor.undo()` without op/plan/since refuses.
- **Actual:** it unwinds every committed operation. The CLI guards this, but
  daemon/intent paths can still reach the executor surface.

### BH-B4 — Broken symlink crashes indexing

- **Severity:** crash-with-safe-state
- **Status:** open-xfail
- **Repro:** `test_broken_symlink_is_skipped_not_fatal`
- **Expected:** the dangling symlink is counted/skipped and ordinary files
  still index.
- **Actual:** `Path.stat()` raises and aborts the root indexing pass.

### BH-B5 — FIFO/special file can hang the indexer

- **Severity:** crash-with-safe-state
- **Status:** open-xfail
- **Repro:** `test_fifo_is_skipped_instead_of_blocking_indexer`
- **Expected:** non-regular files are skipped by type before any read.
- **Actual:** the indexer attempts to read the FIFO and blocks.

### BH-B6 — Later `never_send` policy does not reflag unchanged files

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_never_send_added_later_reflags_unchanged_documents`
- **Expected:** adding a root to `never_send_to_cloud` updates existing
  unchanged document rows on the next index pass.
- **Actual:** unchanged size/mtime short-circuits before the privacy flag is
  refreshed.

### BH-C1 — Halt landing after policy check does not stop the imminent move

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_halt_landing_after_policy_check_prevents_the_move`
- **Expected:** halt is honoured immediately before the filesystem syscall.
- **Actual:** halt is checked between plan items, but a halt landing after an
  item's policy check can still allow that item to move.

### BH-C2 — `trash()` bypasses protected-path and halt policy

- **Severity:** data-loss
- **Status:** open-xfail
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

## Open reproduced bugs: executor/organiser continuation

### BH-A5 — Executor does not verify plan root against root spec

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_plan_for_one_root_cannot_be_applied_with_another_root_spec`
- **Expected:** applying a plan built for root B with root A's spec raises
  before any file moves.
- **Actual:** the executor accepts the mismatch and can move B's indexed
  files into A. Daemon/CLI callers pair them correctly today, but the sole
  file-moving authority does not enforce its own boundary.

### BH-A6 — Executor accepts a source outside the organise root

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_plan_item_source_outside_root_is_refused`
- **Expected:** every plan item source must be inside the root being applied.
- **Actual:** if the outside file is indexed under another root/spec, the
  executor moves it into the current root.

### BH-A7 — Executor accepts invented destinations outside frozen taxonomy

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_plan_item_invented_destination_is_refused`
- **Expected:** a corrupted/manual plan item with `dest="Invented"` is
  refused because `Invented` is not in the root taxonomy.
- **Actual:** syntax/root-containment checks pass and the executor creates
  and files into `Invented/`.

### BH-A8 — Nested already-filed files are flattened

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_nested_already_filed_file_is_not_flattened`
- **Expected:** `Finance/2024/invoice.txt` is already inside the taxonomy
  and stays exactly there.
- **Actual:** organiser marks it already-filed with destination `Finance`
  and basename only; executor therefore moves it to `Finance/invoice.txt`.

### BH-A9 — Destination occupied by a directory crashes the apply

- **Severity:** crash-with-safe-state
- **Status:** open-xfail
- **Repro:** `test_destination_occupied_by_directory_is_refused_not_raised`
- **Expected:** one refused item in the report; source and directory intact.
- **Actual:** `check_operation()` tries to hash the directory and raises
  `IsADirectoryError`, aborting the apply loop.

### BH-A10 — `ApplyReport.op_ids` is always empty

- **Severity:** cosmetic
- **Status:** open-xfail
- **Repro:** `test_apply_report_names_the_journal_operations_it_committed`
- **Expected:** the report names committed journal operation IDs.
- **Actual:** files move and journal rows commit, but `op_ids == []`.

### BH-B7 — Watcher debounce does not restart on later writes

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_watcher_debounce_restarts_when_a_file_changes_again`
- **Expected:** a file changed at t=0 and again at t=9 is not settled at
  t=11 with a 10-second debounce.
- **Actual:** the pending timestamp keeps the first change time; only the
  scan that directly observes the second modification suppresses settling.

### BH-B8 — Unreadable directory is indexed as empty and docs go missing

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_unreadable_directory_does_not_mark_known_files_missing`
- **Expected:** indexing reports an error and leaves known document state
  unchanged while the directory cannot be read.
- **Actual:** `os.walk` silently yields no files below the unreadable
  directory and reconciliation marks known documents `missing`.

### BH-B9 — `build_plan` ignores a missing-root index error

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_build_plan_for_missing_root_does_not_finish_ready`
- **Expected:** a missing root fails the plan.
- **Actual:** indexer returns `stats["error"]`, organiser proceeds with
  stale document rows, writes a shadow log, and finishes the plan `ready`.

## Open reproduced bugs: Area D — planner, intents, config

### BH-D1 — LLM batch verifier does not require an exact path set

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repros:** `test_llm_batch_with_duplicate_path_and_missing_file_is_invalid`,
  `test_llm_batch_boolean_confidence_is_invalid`
- **Expected:** duplicates, dropped files, subsets, and boolean confidence
  invalidate the batch.
- **Actual:** each returned path is checked for membership, but cardinality
  and uniqueness are not; `True` also passes as numeric confidence because
  Python `bool` is an `int`.

### BH-D2 — API-cost intent overmatches ordinary English

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_ordinary_cost_words_are_not_the_api_cost_intent`
- **Expected:** “cost of living…”, “usage of the word…”, and
  “quota for fishing boats” go up the conversational ladder.
- **Actual:** all route locally to the Gemini cost report.

### BH-D3 — Natural emergency halt variants are misses

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_natural_halt_variants_route_to_halt`
- **Expected:** “halt please”, “stop everything now”, and “panic stop now”
  set the halt.
- **Actual:** only exact canned forms match; these fall through.

### BH-D4 — A string where a config sequence belongs becomes characters

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_string_taxonomy_and_languages_are_rejected_or_wrapped`
- **Expected:** `taxonomy="Finance"` and `languages="sw"` are rejected with
  a useful config error or normalized to one-element lists.
- **Actual:** taxonomy becomes `['F','i','n','a','n','c','e', ...]` and
  languages becomes `['s','w']`.

### BH-D5 — Loaded configs share nested `DEFAULTS` objects

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_mutating_loaded_config_does_not_pollute_next_load`
- **Expected:** mutating one `Config.raw` cannot change the defaults seen by
  the next `load_config()` in the same process.
- **Actual:** `_deep_merge(DEFAULTS, {})` shallow-copies the outer dict, so
  nested section dicts/lists remain shared.

### BH-D6 — Malformed humour TOML crashes instead of degrading

- **Severity:** crash-with-safe-state
- **Status:** open-xfail
- **Repro:** `test_malformed_humour_profile_degrades_to_empty_profile`
- **Expected:** per its contract, `load_humour_profile()` returns `{}` and
  the governor falls back to restraint.
- **Actual:** TOML parse errors propagate, breaking doctor/daemon startup.

## Open reproduced bugs: Area E — store, queue, modes, harness

(BH-E2 moved to *Fixed* below.)

### BH-E3 — Every `OSError` is classified as a network failure

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_local_filesystem_errors_are_not_network_failures`
- **Expected:** missing file, permission denied, and disk-full are local
  failures with terminal/inspectable queue state.
- **Actual:** `looks_like_network_failure()` returns true for every
  `OSError`; in the queue this can requeue forever and mark connectivity
  unhealthy—for example when saved dictation audio is missing.

### BH-E4 — First 500 historical queue jobs starve newer pending jobs

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_queue_drain_reaches_pending_job_after_500_finished_jobs`
- **Expected:** drain selects pending/approved jobs regardless of how much
  completed history precedes them.
- **Actual:** drain loads the first 500 rows by ID across all statuses,
  filters afterward, and never reaches pending job #501.

### BH-E5 — A cloud job left `running` by a crash is never recovered

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_queue_recovers_a_job_left_running_by_a_crash`
- **Expected:** restart/drain reconciles a dead `running` job.
- **Actual:** candidates are only `pending`/`approved`; `running` remains
  forever while duplicate-suppression treats it as active.

### BH-E6 — `ModeManager` without a store cannot remember a switch

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_mode_manager_without_store_remembers_requested_preference`
- **Expected:** `request_preference("offline")` yields FORCED_OFFLINE even
  for the supported `store=None` construction.
- **Actual:** preference writes are no-ops and status re-reads config's old
  `auto` preference.

### BH-E7 — Harness verification outcomes are never ledgered

- **Severity:** cosmetic
- **Status:** open-xfail
- **Repro:** `test_verified_outcome_is_recorded_in_the_ledger`
- **Expected:** failed/successful verified attempts write `verified=0/1` to
  `llm_calls`.
- **Actual:** `_call_once()` always writes `verified=None` before the
  verifier runs, and nothing updates the row afterward.

(BH-C3 moved to *Fixed* below.)

## Open reproduced bugs: Area F — audio, dictation, meeting, TTS

### BH-F1 — Empty ASR output stops the fallback chain

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_asr_fallback_chain_continues_after_empty_text`
- **Expected:** `transcribe_file()` walks until a backend produces text.
- **Actual:** a backend returning `Transcript("")` is treated as success
  and later backends are never tried.

### BH-F2 — `WavSink.close()` reports duration at the wrong sample rate

- **Severity:** cosmetic
- **Status:** open-xfail
- **Repro:** `test_wav_sink_reports_duration_at_its_configured_sample_rate`
- **Expected:** 8,000 frames at 8kHz report 1.0s.
- **Actual:** the WAV is written at 8kHz but duration divides by the global
  16kHz constant and reports 0.5s.

### BH-F3 — PCM-stream PipeWire command bypasses the object.id trap guard

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_pw_record_stream_rejects_short_numeric_object_id_targets`
- **Expected:** a short numeric target such as `42` is rejected because
  `pw-record --target` needs `object.serial` or `node.name`.
- **Actual:** `pw_record_command()` guards this, but the raw-stream command
  used by live capture accepts it and can silently capture the default
  device on Fedora.

### BH-F6 — Live age rotation reconnects on every later frame

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_live_age_rotation_does_not_reconnect_on_every_frame`
- **Expected:** proactive rotation after the Live session-age cap resets
  that transport's age clock.
- **Actual:** `started` remains dictation start time; once the cap is
  crossed, each subsequent frame raises rotation, reconnects, and replays
  the buffered tail again.

### BH-F7 — Cleanup failure prevents raw dictation persistence

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_cleanup_failure_still_persists_raw_transcript`
- **Expected:** ASR text lands in the transcript store/inbox even if the
  optional cleanup model call fails.
- **Actual:** cleanup is called before either persistence step; an
  exception propagates and only the raw WAV remains.

### BH-F8 — Piper availability ignores a missing voice JSON config

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_piper_availability_requires_the_json_config`
- **Expected:** status reports unavailable when the selected model's
  `.onnx.json` config is absent.
- **Actual:** model + executable presence is reported available; synthesis
  is the first place the missing config can fail.

### BH-F9 — Explicit TTS destination is reused as cache for different text

- **Severity:** wrong-action
- **Status:** open-xfail
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

## Open reproduced bugs: Area G — IPC, daemon, voice-test

### BH-G1 — Speaker-threshold suggestion tie-breaks dangerously low

- **Severity:** wrong-action
- **Status:** open-xfail
- **Repro:** `test_suggested_speaker_threshold_uses_the_separation_gap_midpoint`
- **Expected:** with false scores at 0.10 and true scores at 0.90, the
  suggested threshold sits in the separation gap (about 0.50).
- **Actual:** the sweep keeps the first zero-error threshold, 0.101,
  maximizing unseen-impostor false-accept risk.

### BH-G2 — `review.decide` reports success for a nonexistent item

- **Severity:** cosmetic
- **Status:** open-xfail
- **Repro:** `test_review_decide_rejects_a_nonexistent_item`
- **Expected:** deciding item #999999 raises a clear no-such-item error.
- **Actual:** the SQL update affects zero rows but the daemon returns a
  successful approve/reject response.

### BH-G3 — IPC client mistakes a pushed event for its reply

- **Severity:** crash-with-safe-state
- **Status:** open-xfail
- **Repro:** `test_ipc_call_skips_event_lines_until_the_matching_reply`
- **Expected:** `ipc.call()` skips server-pushed event lines and returns the
  matching JSON-RPC-style result.
- **Actual:** it treats the first event line as the reply; with no `ok`
  field it raises a daemon error even though the real reply follows.
