# Elaria adversarial bug hunt & full-repo hardening — final summary

Date: 2026-10-20  
Branch: `arena/86517426-elaria`  
Detailed bug ledger: [`bugs.md`](bugs.md)  
Chronological change ledger: [`change.md`](change.md)  
Voice pipeline ledger: [`VOICE-BUGTEST.md`](VOICE-BUGTEST.md)

## Method

- Baseline before this hardening pass (`36f0618`): **1,246 collected, 1,194 passed,
  6 skipped, 46 xfailed**, Ruff 0 errors.
- All hunt tests run in temporary sandbox directories and temporary SQLite
  stores. No real user folders, API keys, or biometric voiceprints are touched.
- State is the oracle: files, journal rows, SQLite rows, queue rows, routing
  results, and returned records—not process exit codes alone.
- Every behaviour change was preceded by a failing test (`tests/test_bughunt_safety.py`,
  `tests/test_bughunt_systems.py`, `tests/test_stage_abcd_bughunt.py`).
- Every dead-code removal was proven with 0 external references across `src/`,
  `tests/`, `config.toml.example`, `README.md`, `GETTING-STARTED.md`, `systemd/`,
  and `ui/`.

## Scoreboard & Verification (2026-10-20)

| Metric | Baseline (`36f0618`) | Final (`arena/86517426-elaria`) | Delta |
|---|---:|---:|---:|
| **Collected** | 1,246 | 1,281 | +35 |
| **Passed** | 1,194 | 1,275 | **+81** |
| **Skipped** | 6 | 6 | 0 |
| **XFailed** | 46 | **0** | **-46** |
| **Failed** | 0 | 0 | 0 |
| **Warnings** | 9 | **0** | **-9** |
| **Ruff (`ruff check .`)** | 0 errors | 0 errors | 0 |
| **Vulture (`vulture src/ --min-confidence 80`)** | 12 unused defs | **0 unused defs** | **-12** |

## Summary of Fixed Bug Classes

### Class 1 — CRITICAL / HIGH (Data-loss, security/privacy boundary, wrong-action) — `0176d8d`

- **Filesystem & Executor Safety (`BH-A4`..`BH-A10`, `BH-B1`..`BH-B3`, `BH-C1`, `BH-C2`)**:
  - `expand()` now expands `$VAR` environment variables alongside `~` (`BH-A4`).
  - `Executor.apply_plan()` enforces plan-root vs spec-root identity (`BH-A5`),
    source-within-root containment (`BH-A6`), and frozen taxonomy membership (`BH-A7`).
  - Nested already-filed files (`Finance/2024/invoice.txt`) are preserved in place
    rather than flattened to `Finance/invoice.txt` (`BH-A8`).
  - Directory-occupied destinations are refused cleanly without raising
    `IsADirectoryError` (`BH-A9`), and `ApplyReport.op_ids` records every
    committed journal operation ID (`BH-A10`).
  - `Executor.undo()` reconciles interrupted `intent`/`copied` journal rows whose
    destination exists on disk (`BH-B1`), `_copy_file_no_overwrite()` cleans up
    partial destination files on `ENOSPC`/mid-copy errors (`BH-B2`), and bare
    `Executor.undo()` without scope (`op_id`/`plan_id`/`since_iso`) is refused (`BH-B3`).
  - `is_halted()` is re-checked immediately before filesystem move syscalls (`BH-C1`),
    and `Executor.trash()` enforces `is_halted()` and `is_protected()` (`BH-C2`).
- **Planner Verification (`BH-D1`)**:
  - `_parse_batch()` requires exact 1-to-1 path coverage (rejecting duplicates and
    subsets) and rejects boolean `confidence` (`isinstance(conf, bool)`).
- **Stage D Show-off & Disclosure Boundaries (`BH-H15`..`BH-H20`)**:
  - `ShowoffService.enter()` rejects non-mic sources, `replayed=True`, `live_mic=False`,
    and replayed `audio_sha256` digests (`BH-H15`).
  - `Daemon._ask()` treats any turn without verified owner biometrics during
    active show-off mode as `"guest"` (`BH-H16`).
  - `ShowoffService.exit_owner()` and `exit_hotkey()` handle timeout races
    idempotently by returning the just-expired session summary (`BH-H17`).
  - `ShowoffService.demo_target()` rejects symlinks (`is_symlink()`) inside the
    sandbox and verifies `resolve()` containment (`BH-H18`).
  - `disclosure.sensitive_values()` extracts colon/equals/named values and
    distinctive secret tokens (`len >= 6`) so paraphrased owner secrets are
    blocked by `leak_in()` (`BH-H19`).
  - `ShowoffService.record_guest_turn()` persists `guests_heard` incrementally in
    SQLite, and `recover_unclosed()` purges any `.wav`/`.pcm`/`.ogg`/`.flac`/`.mp3`/`.raw`
    residue from the demo sandbox on restart after `kill -9` (`BH-H20`).

### Class 2 — HIGH / MEDIUM (Crash-unsafe, resource/socket/DB recovery, races) — `810bab4`

- **Indexer, Organiser & Watcher (`BH-B4`..`BH-B9`)**:
  - `Indexer.index_root()` uses `lstat()`/`is_symlink()` first so broken symlinks
    (`skipped["symlink"]`) and FIFOs/devices (`skipped["special"]`) never crash or
    hang indexing (`BH-B4`, `BH-B5`).
  - Unchanged files refresh their `never_send` flag when privacy policy changes (`BH-B6`).
  - `os.walk(..., onerror=...)` records unreadable directory errors in `stats["error"]`
    and preserves known document rows under unreadable prefixes instead of marking
    them `missing` (`BH-B8`).
  - `OrganiserService.build_plan()` refuses missing/unreadable roots and marks the
    plan `"failed"` (`BH-B9`).
  - `PollingWatcher.scan()` restarts the settle debounce clock when a pending file's
    `(size, mtime)` changes again (`BH-B7`).
- **Config, Queue, Modes & Harness (`BH-D6`, `BH-E3`..`BH-E7`)**:
  - `load_humour_profile()` catches `(tomllib.TOMLDecodeError, OSError)` and
    degrades to `{}` (`BH-D6`).
  - `looks_like_network_failure()` excludes local filesystem `OSError`s
    (`FileNotFoundError`, `PermissionError`, `IsADirectoryError`, `ENOSPC`, `EROFS`) (`BH-E3`).
  - `CloudQueue.drain()` queries `status='pending'` and `status='approved'`
    separately so 500 finished jobs never starve pending item #501 (`BH-E4`), and
    reconciles stale `running` jobs left behind by crashes (`BH-E5`).
  - `ModeManager(store=None)` maintains state in memory (`BH-E6`).
  - `GeminiClient.generate()` records `verified=1`/`0` on `llm_calls` (`BH-E7`).
- **Audio, Dictation, TTS & IPC (`BH-F1`..`BH-F3`, `BH-F6`..`BH-F9`, `BH-G2`, `BH-G3`)**:
  - `transcribe_file()` continues down the fallback chain on empty transcripts (`BH-F1`).
  - `WavSink.close()` divides by `self.sample_rate` (`BH-F2`).
  - `pw_record_pcm_stream_command()` rejects short numeric `object.id` targets (`BH-F3`).
  - `DictationService` resets `started` after proactive session-age rotation (`BH-F6`)
    and persists the raw transcript even when `cleanup.run()` raises (`BH-F7`).
  - `PiperTtsBackend.availability_error()` checks for the `.onnx.json` config (`BH-F8`).
  - `SpeechService.synthesize(dest=...)` only treats `path == route_cache` as a
    cache hit (`BH-F9`).
  - `Daemon._review_decide()` raises `ValueError` for nonexistent review items (`BH-G2`).
  - `ipc.call()` skips server-pushed `"event"` lines until the reply (`BH-G3`).
- **Stage A/B/C & Cross-Cutting Crash/Race Hardening (`BH-H1`, `BH-H5`..`BH-H7`, `BH-H10`, `BH-H21`)**:
  - Atomic WAV writing in `SpeechService.write_wav()`, mid-stream Live disconnect
    rejection in `GeminiClient._live_voice()`, and `mode_manager.observe_failure()`
    reporting in `Daemon._maybe_speak_reply()` (`BH-H1`).
  - Active SQLite conversation history injected into `Daemon._ask()` prompts across
    restarts (`BH-H5`).
  - `ipc.subscribe_events()` read timeout (`30.0s`) and `await w.drain()` dead-subscriber
    pruning in `Daemon.broadcast()` (`BH-H6`).
  - `SpeechService.say()` and `play_ack()` re-verify `voice_route()` immediately
    before `play_audio()` so class-mode toggles win races against in-flight synthesis (`BH-H7`).
  - `Daemon._knock_accept()` checks `not speech.status()["muted"]` and
    `InitiativeService.accept()` persists the opener line to `sessions` atomically (`BH-H10`).
  - `ipc.serve()` refuses to unlink a socket with a live listening daemon and
    handles non-dict JSON frames cleanly (`BH-H21`).

### Class 3 — MEDIUM / LOW (Wrong-behaviour, logic, catalogue TTL, config schema) — `e4108b5`

- **Intents & Voice-Test (`BH-D2`..`BH-D5`, `BH-G1`)**:
  - Narrowed `cost` intent regex (`BH-D2`) and expanded `halt` intent regex (`BH-D3`).
  - Normalized string `taxonomy` and `asr.languages` to single-element lists (`BH-D4`),
    and deep-copied `DEFAULTS` in `_deep_merge()` (`BH-D5`).
  - `suggest_threshold()` returns the midpoint of the optimal threshold interval (`BH-G1`).
- **Stage A Catalogue & Identity (`BH-H2`..`BH-H4`)**:
  - Added 24-hour TTL (`DEFAULT_CATALOGUE_TTL_S = 86400`) to `load_cached()`,
    included `candidate_voices` in `validate_voice()` failure `allowed`, and
    checked cached verified catalogues in `SpeechService.voice_route()` (`BH-H2`).
  - Canonicalized case in `resolve_voice()` (`"flare"` -> `"Flare"`) and prevented
    refused voices from leaking into `cloud_cache_identity()` or `status()["gemini_voice"]` (`BH-H3`).
  - Prevented the removed `gemini-2.5-flash-preview-tts` default in deprecated
    `model_voice` from shadowing `gemini_voice_model` (`BH-H4`).
- **Stage B/C Schedule & Initiative (`BH-H8`, `BH-H9`, `BH-H11`..`BH-H14`)**:
  - Supported overnight midnight-spanning windows (`start > end`) and rejected
    `bool` day entries in `PresenceService`, plus string-boolean parsing in
    `Daemon._class_set()` (`BH-H8`).
  - Enforced `knock.get("silent")` in `KnockSignal.emit()` and `urgent_in_class_mode`
    in `InitiativeService.raise_knock()` (`BH-H9`).
  - `InitiativeService.decline()` accepts snoozed knocks and deactivates both the
    knock's commitment and any `parent_commitment_id` linked by `later()` (`BH-H11`).
  - Normalized punctuation in `_topic_key()`, rejected non-pending knocks in
    `ignore()`, and retired topics across 3 ignored knocks (`BH-H12`).
  - Extended AST boundary verification (`BH-H13`) and expanded `NEEDY_PATTERNS` (`BH-H14`).
- **Config Parity & Doctor Schema Validation (`BH-H22`)**:
  - Fixed `[quota.models.transcribe-batch]` table scoping in `config.toml.example`,
    achieved 100% key parity between `DEFAULTS` and `config.toml.example`, and
    added `validate_config()` + the `"config schema"` check in `run_doctor()`.

## Removed Dead Code (with 0-reference proofs)

Every removed definition was verified via `vulture` and full-repo regex search across
`src/`, `tests/`, `config.toml.example`, `README.md`, `GETTING-STARTED.md`, `systemd/`,
and `ui/` to have zero callers before deletion:

1. `src/assistant/asr.py` — `class PhasePending(NotImplementedError)`: 0 external references (leftover Phase 0 stub exception).
2. `src/assistant/capture.py` — `def pw_record_command(...)`: 0 callers in `src/` or `tests/` (superseded by `pw_record_pcm_stream_command`).
3. `src/assistant/capture.py` — `class FileCapture`: 0 references in `src/` or `tests/` (superseded by `SimulatedCapture` and `WavFileSource`).
4. `src/assistant/disclosure.py` — `def is_owner_probe(...)` and `_PROBE_PATTERNS`: 0 callers in `src/` or `tests/` (superseded by `filter_hits` and `leak_in`).
5. `src/assistant/disclosure.py` — `DisclosureService.guest_prompt(...)`: 0 callers in `src/` or `tests/` (superseded by `prompt_note(guest=True)` and `ShowoffService.guest_prompt`).
6. `src/assistant/executor.py` — `Executor.assert_demo_path(...)`: 0 callers in `src/` or `tests/` (`assert_within_sandbox` in `safety.py` is used directly).
7. `src/assistant/initiative.py` — `InitiativeService.find_commitment(...)`: 0 callers in `src/` or `tests/` (`commitment(commitment_id)` is used instead).
8. `src/assistant/offline_queue.py` — `def capability_for(...)`: 0 callers in `src/` or `tests/`.
9. `src/assistant/proc.py` — `def supported()`: 0 callers in `src/` or `tests/` (`_SUPPORTED` is used internally).
10. `src/assistant/store.py` — `Store.update_holding(...)`: 0 callers in `src/` or `tests/`.
11. `src/assistant/transcribe.py` — `SilenceLadder.asked` property: 0 callers in `src/` or `tests/` (`_asked` is internal state).
12. `src/assistant/voicetest.py` — `class FrameSource(Protocol)`: 0 references in `src/` or `tests/` (`AsyncFrameSource` is the active protocol).

### Pass 2 removals (2026-10-20)

Proven with `ruff` F401, `vulture src/ --min-confidence 80`, and a repo-wide
`grep` returning zero references outside git history:

13. `src/assistant/config.py` — `_file_sections()`: 0 callers after `validate_config()` was rewritten.
14. `src/assistant/daemon.py` — `_speak_reply_async()`: superseded by `_speak_once()`; 0 callers.
15. `src/assistant/daemon.py` — `persona.is_simple_turn` import: unused (ruff F401).
16. `src/assistant/transcribe.py` — `from pathlib import Path as _P` (inside `_finalize`): unused (vulture 90 %).
17. `src/assistant/waybar.py` — `json` import: unused after `parse_event_line()`.
18. `src/assistant/console.py` — `json` import: unused after `parse_event_line()`.
19. `tests/test_bugs_1_to_5_regressions.py` — 7 unused imports and 1 unused unpack (ruff F401/RUF059); no assertion changed.
20. `tests/test_hardening_pass2.py` — unused `os` import and one bare expression.

## Verdict — Running Unattended in Shadow Mode

**SAFE TO RUN UNATTENDED IN SHADOW MODE** (`[organise] mode = "shadow"`).

- **Blocking bug IDs remaining:** **None (0 open blocking bugs; 0 xfails).**
- **Why shadow mode is safe unattended:**
  1. In shadow mode (`mode = "shadow"`), `OrganiserService.build_plan()` never calls
     `Executor.apply_plan()`; it only indexes whitelisted roots, classifies documents,
     and writes a JSONL shadow plan to `~/.local/share/assistant/shadow-plans/`.
  2. `Indexer.index_root()` uses `lstat()` first (`BH-B4`, `BH-B5`), skips symlinks
     and special files (FIFOs/sockets/devices) without opening them, honors `$VAR`
     and `~` protected paths (`BH-A4`), and preserves existing document rows when a
     subdirectory is temporarily unreadable (`BH-B8`).
  3. Even when `assist plan apply` is later invoked in live mode, the executor
     enforces root identity (`BH-A5`), source containment (`BH-A6`), frozen taxonomy
     membership (`BH-A7`), nested-path preservation (`BH-A8`), atomic no-overwrite
     placement (`BH-A1`), pre-syscall halt checks (`BH-C1`), and scoped journaled
     undo (`BH-B1`..`BH-B3`).
  4. Offline/online posture transitions, class-mode silence guarantees (`BH-H7`,
     `BH-H9`), knock reason/retirement gates (`BH-H10`..`BH-H14`), and show-off
     sandbox/biometric/leak boundaries (`BH-H15`..`BH-H20`) are all enforced and
     covered by regression tests.

## Second hardening pass — `arena/8952fe51-elaria` (2026-10-20)

Baseline measured in this checkout at `25179c8`, immediately before any edit:
**1,280 passed / 6 skipped / 0 failed / 0 xfailed / 0 warnings**, ruff **17
errors**, vulture **1 finding**.

| Metric | Baseline `25179c8` | After pass 2 |
|---|---:|---:|
| Collected | 1,286 | 1,315 |
| Passed | 1,280 | 1,309 |
| Skipped | 6 | 6 (unchanged; all environmental) |
| XFailed | 0 | 0 |
| Failed | 0 | 0 |
| Ruff | 17 errors | **0** |
| Vulture (`--min-confidence 80`) | 1 | **0** |

The previous table in this file records 1,281 collected at its "final"
checkpoint; this checkout measured 1,286 before pass 2 (1,280 passed + 6
skipped). Recorded rather than silently rewritten.

### Fixed in pass 2 (all were reproduced red first)

- **BH-I1** — explicit `gemini_voice_model` is no longer shadowed by the
  deprecated `model_voice` alias (`Config.explicit_keys` records user intent).
- **BH-I2** — `validate_config()` names poisoned enums/types/ranges/sections;
  `Config.section()`, `organise_roots()` and `humour_profile_path()` degrade
  safely; unknown keys warn in doctor.
- **BH-I3** — `[console] history_limit` now reaches the daemon's sessions.
- **BH-I4** — a reply that outlives the 1.5 s inline wait is spoken once
  (`_speak_once()` + shielded task), not twice.
- **BH-I5** — short real replies (`"No."`) are no longer discarded as echo after
  the speaking guard expires.
- **BH-I6** — show-off crash recovery purges only the demo sandbox; it no longer
  deletes dictation and meeting recordings from `data_dir/audio`.
- **BH-I7 / BH-I7b** — `initiative.status()["latest"]` is the newest pending
  knock; a due knock that cannot be raised logs `knock_due_refused`.
- **BH-I8** — `ipc.serve()` serialises check-unlink-bind with an exclusive
  `<sock>.lock` flock and releases it on close.
- **BH-I9** — malformed IPC replies raise `DaemonUnavailable`; event consumers
  skip bad frames; reply drain is bounded; player timeouts are reported.
- **BH-I10** — a failed catalogue refresh falls back to the verified cache
  (stale cache preferred over the never-verified baseline); timestamp-less cache
  rows are untrusted.
- **BH-I11** — 8 new needy-framing paraphrases are refused.
- **BH-I12** — guest turns are bounded by the same 4 s chat ceiling as owner
  turns; the timeout speaks a fallback instead of freezing the demo.
- **BH-I13** — Waybar/console event streams survive malformed lines.

Guard tests: `tests/test_hardening_pass2.py` (29 cases). Pre-fix: 24 failed /
4 passed (the 29th was added when the stale-cache fallback was tightened).
Corrected test: `test_bh_h20_showoff_crash_exit_residue_cleaned_on_restart` had
encoded BH-I6 (deleting `data_dir/audio`) as the contract; its remaining BH-H20
assertions were preserved and a meeting recording now proves the fix.

### Verdict — unchanged direction, pass 2

Shadow mode remains **safe to run unattended**. Pass 2 added no new blocking
defects; it removed the only data-loss path introduced by the previous pass
(BH-I6) and closed the last two-daemon race (BH-I8). Live mode, dictation
cleanup, and unattended show-off remain **not** approved for unattended use
(the voice/ASR stack still depends on the network and on a real device).
