# Fresh adversarial hunt ledger — Arena branch

Date: 2026-10-21  
Branch: `arena/ef0e665f-elaria`  
Starting commit: `9151984` (working tree was clean)  
Bug entries: [`bugs.md`](bugs.md)  
Prior notes retained as leads only: [`BUGHUNT-2026-10-21.md`](BUGHUNT-2026-10-21.md)

This ledger records evidence gathered independently in the current checkout. The prior bughunt files are not accepted as proof by themselves. Invariant labels use prose where the condensed task context omitted exact I1–I10 definitions; only I1, I3, and I4 are used when their meanings are clear from the available context.

## Phase 0 — recon only (closed before fixes)

No repository source/test/ledger edits were made during recon. The initial checkout passed ten independently randomized full-suite runs (`pytest-randomly` seeds `260101`–`260110`): each **1,500 passed, 6 skipped** (1,506 collected), against the user-stated 1,393-test baseline. Combined coverage was **83%**: 10,776 statements, 1,611 missed; 3,366 branches, **559 missed**. `.venv/bin/ruff check .` passed. The disposable mock daemon and probe files were cleaned up; the mock daemon process was stopped.

The earlier all-handler hostile sweep exercised all **65** `Daemon._handlers()` entries plus `events.subscribe`. The parser currently exposes **63** `assist` leaf commands and `assist-voice-test` exposes **5** commands; `tests/test_bug7_cli_smoke.py` invokes every `assist` leaf. The voice-test CLI was also exercised with synthetic and WAV sources, report/label/corpus-check/enroll, and a noninteractive PipeWire attempt. The latter produced a traceback; it does not establish real capture behavior.

An earlier `status` harness result was inconclusive because its connectivity stub was incomplete. Freshly calling the real `Daemon.handle("status", {})` with isolated XDG paths returned successfully (`mode=idle`, no status error).

### Freshly confirmed findings, ranked by the requested severity order

1. **Data loss — meeting raw-WAV collision (BH-K33, now fixed).** Frozen-clock overlapping stops reused a second-resolution daemon raw path. With the real `MeetingService.transcribe_dual` and ASR replaced only by a local stub, the first session's archive contained the second session's mic bytes. The second stop also cleared the shared processing flag while the first worker was still pending. A separate repro showed a transcription failure left mode processing and a parked preference unapplied. Red/green regressions are `tests/test_bug_meeting_raw_collision.py` and `tests/test_bug_meeting_stop_failure.py`.
2. **Data loss / out-of-root writes — sample capture/eval tool (BH-K34, fixed).** Red regressions reproduced `--bucket ../../escaped` escaping the sample root, same-second capture replacing an existing WAV, a symlinked train/eval bucket escaping the tree, eval overwrite, stale manifest paths, fraction 0 moving a take, fraction 2 moving all takes, and a second freeze changing the split. Invalid zero/negative takes and non-positive/non-finite durations also reached success or the fake recorder. The red tests ran before the fix; after the fix, the sample regressions plus the existing wake-tool file pass. Actual `pw-record`/PipeWire capture remains unverified.
3. **Unbounded/abandoned work — deadlines and lifecycle.** The duplicate external queue enqueue after an ambiguous timeout was fixed as BH-K35. Remaining reproductions: a timed-out `_generate` leaves its synchronous worker blocked/tracked (I3 meaning: total deadline/cancellation); active `ptt.result(wait_s=Infinity)` remains pending beyond the client's timeout; `meeting.stop` awaits a thread with no end-to-end bound; and `Daemon.aclose()` leaves active meeting capture resources running. Production SDK cancellation remains unverified.
4. **Authority/privacy — daemon trusts caller assertions.** Current-checkout IPC repros showed: (a) `ask` with caller `owner_verified=True` skipped `ShowoffService.verify_owner`, passed an ordinary synthetic owner fact to the model, and returned it without withholding; (b) `showoff.enter` accepted caller-supplied `owner_present`, `source`, `live_mic`, and an embedding copied from a synthetic enrolled centroid; (c) wake-knock accept accepted caller channel `voice_unavailable`, and separately a caller score of 1.0, opening listening. No real microphone was involved; these are IPC validation failures.
5. **Half-duplex — speech output gate gaps (I4 meaning: no user mic/uplink while Elaria speaks).** Earlier injected playback/synthesis probes showed `speech.say` playing while the daemon speaking gate was false, a mic frame passing during playback, overlapping speech clearing shared state early, and delayed synthesis outliving its estimated gate window. No hardware acoustics were tested.
6. **Wrong behavior / privacy plumbing.** Earlier probes confirmed `privacy.set(company="false")` stores true; custom `XDG_DATA_HOME` did not relocate dictation inbox notes; data/audio directories were 0755 and DB/WAL/SHM/WAV/note files 0644 under umask 0022 (cross-UID reads unverified); voice-test enrollment briefly created a 0644 biometric template before chmod to 0600; malformed TOML and noninteractive PipeWire voice-test paths emitted tracebacks. Sample capture argument failures are now covered by BH-K34 regressions.
7. **Event-loop latency.** An injected 250 ms hotword scorer blocked the daemon event loop; a concurrently scheduled status handler did not start until the scorer returned (~251 ms). Real ONNX/ECAPA latency remains hardware-dependent.

### Evidence-backed suspects — not fixed without hardware/owner semantics

- **S1/S2:** model/voice availability and real Live segment/`turn_complete` ordering. Settle with `assist voice models`, then `GEMINI_MODE=record assist dictate` (speak ~5 seconds, release) and inspect `fixtures/seq-live.jsonl` plus `assist cost`.
- **S3:** older-SDK `_SdkTransport.generate_audio` fallback may not complete a text turn. Settle with a timed `assist voice say "test"` on the owner's key/device.
- **S4:** `ipc.subscribe_events` blocks on a silent, open socket (reproduced with a fake Unix server). Whether that is a defect depends on the intended long-lived feed contract; owner decision required. Hardware observation: `timeout 35s assist events` while the daemon is alive but idle.
- **S5:** synthetic input below 0.003 RMS caused a non-empty fake Live final to be discarded as no speech. Settle with `assist doctor` mic-level check and a genuinely quiet, arm's-length dictation; compare `capture.stats` peak to 0.003.
- **S6:** a final for previously sent user audio was suppressed when it arrived after an output-audio event inside the playback guard (synthetic repro). Settle with record-mode dictation and an interjection during her reply; inspect `transcript.echo_suppressed` and committed finals.
- **S7:** synchronous hotword scorer blocking is confirmed with injection; measure actual ONNX/ECAPA status/ack latency on hardware using `assist hotword start`, trigger the phrase, and issue `assist status` concurrently.
- **S8:** `_sdk_transcribe` calls Files API upload and generation but no delete (verified with an instrumented fake SDK). Provider-side retention/expiry is not established here. After a sanitized batch transcription, list the owner's Gemini Files via AI Studio/SDK.
- **S9:** a wedged injected meeting backend parks processing indefinitely (code path reproduced); do not add a blind timeout that drops a completed transcript. Settle on hardware with a test ASR wrapper that blocks and observe `assist status` until it is safely released.
- **Hardware unavailable in this sandbox:** real PipeWire/Hyprland, user systemd manager, Gemini key/network, ECAPA/ONNX model, and cross-UID filesystem access. These remain explicitly UNVERIFIED.

## Fix checkpoints

### BH-K33 — meeting raw WAVs and concurrent processing state

- **Before fix:** `tests/test_bug_meeting_raw_collision.py` failed with all three observations: same raw mic path for both stops; first archive held later-session bytes; processing was false while the first stop remained pending.
- **Change:** UUID-scoped raw WAV names; processing-session set instead of a shared bool; mode is recomputed from active capture/workers; `finally` restores mode and applies parked connectivity preferences even when transcription fails.
- **Verification:** `pytest -q tests/test_bug_meeting_raw_collision.py tests/test_bug_meeting_stop_failure.py tests/test_phase6_meeting.py tests/test_bughunt_k_config.py tests/test_bughunt_systems.py -k meeting` — **14 passed, 60 deselected**. Ruff passed on all touched Python files.
- **Commit/push:** committed as `a72f4e8` and pushed to `arena/ef0e665f-elaria`.

### BH-K34 — sample capture and frozen eval data integrity

- **Before fix:** first red run of `tests/test_bug_record_elaria_samples.py` reported **5 failures**: fraction 0 moved a file; an existing eval take was replaced; `--bucket ../../escaped` reached the recorder; manifest paths remained under `train/`; and a symlinked train bucket was followed. A second red run reported **7 failures** for bucket escape, same-second WAV replacement, and invalid takes/durations. The independent Phase 0 probe also observed fraction 2 moving every take.
- **Invariants (prose):** recorded samples remain under the selected sample root and bucket; an existing sample/eval file is never replaced; frozen split paths and manifest entries agree; eval is split exactly once; invalid capture requests do not report success or reach capture.
- **Root cause:** unvalidated bucket strings were interpolated into paths; second-resolution filenames were reused across invocations; `Path.rename()` could replace an eval destination; symlinks were followed; fraction arithmetic clamped invalid values; the freeze marker was overwritten instead of enforced; moved paths were not reflected in the manifest; `takes` and `seconds` were not validated.
- **Repros:** `tests/test_bug_record_elaria_samples.py` covers unsafe bucket, same-second collision, invalid capture arguments, manifest symlinks, symlinked train/eval buckets, existing eval collision, zero/out-of-range/non-finite fractions, stale manifest, repeat freeze, partial-move rollback, manifest-write rollback, and an incomplete-move marker. Existing sample-capture tests remain in `tests/test_wake_knock_package.py`.
- **Fix:** bucket-component validation and root/symlink checks; UUID filenames and no-overwrite capture guard; finite positive duration and positive take count; fraction validation; no-overwrite same-filesystem moves; one-shot `.frozen` marker; atomic manifest-path update; rollback on pre-commit failures, with an in-progress marker retained when recovery is uncertain. Cross-filesystem split moves fail safely rather than copy/overwrite.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_record_elaria_samples.py tests/test_wake_knock_package.py` — **50 passed**. `.venv/bin/ruff check scripts/record_elaria_samples.py tests/test_bug_record_elaria_samples.py` and `git diff --check` passed. No real `pw-record`/PipeWire capture was run.
- **Commit/push:** committed as `1c145b8` and pushed to `arena/ef0e665f-elaria`.

### BH-K35 — ambiguous IPC timeout replayed an external queue enqueue

- **Before fix:** a real Unix-socket `Daemon` committed `queue.enqueue_external`, then an injected 300 ms response delay exceeded the client’s 50 ms total deadline. `assist queue add-external` treated the response timeout as daemon-down, retried against the same SQLite database locally, returned success, and left **2** matching durable jobs. Red repro: `tests/test_bug_queue_timeout_duplicate.py::test_bug_queue_timeout_after_commit_does_not_enqueue_again`.
- **Invariant (prose / I1):** one request causes at most one durable side effect; local fallback is allowed only if no request was sent.
- **Root cause:** `ipc.call()` collapsed post-`sendall` timeouts, malformed replies, and empty replies into `DaemonUnavailable`, which mutating CLI fallbacks interpreted as safe-to-replay.
- **Fix:** distinguish pre-send `DaemonUnavailable` from post-send `DaemonOutcomeUnknown`; ambiguous outcomes do not inherit the fallback exception type. Queue and knock commands surface the uncertainty and do not retry. Authoritative `DaemonError` refusals remain distinct. Definite missing-socket offline fallback remains supported.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_queue_timeout_duplicate.py tests/test_hardening_pass2.py tests/test_bughunt_k_error_surfacing.py tests/test_bug6d_ptt_result_orphans.py tests/test_phase8_offline_voice.py` — **70 passed**. This includes malformed/empty reply classification, missing-socket fallback, and the total-deadline regression. Full Ruff and `git diff --check` passed.
- **Commit/push:** committed as the BH-K35 checkpoint and pushed to `arena/ef0e665f-elaria` after this ledger update.

## Next

Continue one confirmed bug at a time: add/run a red `test_bug*` regression, fix at root, update this ledger and `bugs.md`, run targeted verification, commit, and push only to `arena/ef0e665f-elaria`. After proven bugs are addressed, run the required fresh full pass and mutation testing; report survivors and preserve every hardware-only item as UNVERIFIED/SUSPECT with its settling command.
