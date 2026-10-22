# Fresh adversarial hunt ledger — Arena branch

Date: 2026-10-21  
Branch: `arena/ef0e665f-elaria`  
Starting commit: `9151984` (working tree was clean)  
Bug entries: [`bugs.md`](bugs.md)  
Prior notes retained as leads only: [`BUGHUNT-2026-10-21.md`](BUGHUNT-2026-10-21.md)

This ledger records evidence gathered in the current checkout; prior notes are leads, not proof. Invariant tags use the exact I1–I10 definitions in `INVARIANTS.md`.

## Phase 0 — recon only (closed before fixes)

No repository source/test/ledger edits were made during recon. The initial checkout passed ten independently randomized full-suite runs (`pytest-randomly` seeds `260101`–`260110`): each **1,500 passed, 6 skipped** (1,506 collected), against the user-stated 1,393-test baseline. Combined coverage was **83%**: 10,776 statements, 1,611 missed; 3,366 branches, **559 missed**. `.venv/bin/ruff check .` passed. The disposable mock daemon and probe files were cleaned up; the mock daemon process was stopped.

The earlier all-handler hostile sweep exercised all **65** `Daemon._handlers()` entries plus `events.subscribe`. The parser currently exposes **63** `assist` leaf commands and `assist-voice-test` exposes **5** commands; `tests/test_bug7_cli_smoke.py` invokes every `assist` leaf. The voice-test CLI was also exercised with synthetic and WAV sources, report/label/corpus-check/enroll, and a noninteractive PipeWire attempt. The latter produced a traceback; it does not establish real capture behavior.

An earlier `status` harness result was inconclusive because its connectivity stub was incomplete. Freshly calling the real `Daemon.handle("status", {})` with isolated XDG paths returned successfully (`mode=idle`, no status error).

## Post-fix verification on the current tree (2026-10-22)

- After BH-K39, a fresh unseeded full suite and ten randomized seeds 260201–260210 each returned **1,545 passed, 6 skipped** (1,551 collected), compared with the user's stated **1,393** baseline; that historical combined coverage was 84.60% statements and 74.02% branches. The earlier two full-suite failures (handler-integrity false positive on `_meeting_stop_impl(params)` and stale BH-H1 sync-only SDK fake) were fixed before those results.
- After BH-K40 and the test-harness cleanup fixes, ten fresh randomized full-suite seeds **260501–260510** each returned **1,548 passed, 6 skipped** (1,554 collected). Combined coverage: **84.49% statements** (9,468/11,206), **73.87% branches** (2,612/3,536), **81.94% combined**. This is **155 passed tests above** the user's stated 1,393-pass baseline; six tests remain skipped.
- Seed **260303**, which had emitted two pending IPC-client warnings before the UI consumer teardown fix, was rerun after the fix: **1,548 passed, 6 skipped**, with empty stderr. The isolated PTT event-stream cleanup and both UI stream cleanup tests also pass. Full Ruff and `git diff --check` pass after generated mutation/coverage artifacts are removed.
- A second fresh unseeded full-suite pass after BH-K40–K42 returned **1,548 passed, 6 skipped** with empty stderr. This is a clean suite pass, not a genuinely independent reviewer-led pass; mutation survivor triage remains incomplete. Real Gemini provider behavior, live timeout/stall, PipeWire capture, and native offline/pyannote timeout behavior remain UNVERIFIED/SUSPECT as listed below.

### Freshly confirmed findings, ranked by the requested severity order

1. **Data loss — meeting raw-WAV collision and capture-close short circuit (BH-K33/BH-K40, fixed).** Frozen-clock overlapping stops reused a second-resolution daemon raw path. With the real `MeetingService.transcribe_dual` and ASR replaced only by a local stub, the first session's archive contained the second session's mic bytes. The second stop also cleared the shared processing flag while the first worker was still pending. A separate repro showed a transcription failure left mode processing and a parked preference unapplied. BH-K40 then reproduced that one capture-source close error skipped its peer close, collector cleanup and raw-WAV persistence; a source-local cancellation also skipped archival. Regressions are `tests/test_bug_meeting_raw_collision.py`, `tests/test_bug_meeting_stop_failure.py`, and the close-failure/cancellation tests in `tests/test_bug_meeting_stop_deadline.py`.
2. **Data loss / out-of-root writes — sample capture/eval tool (BH-K34, fixed).** Red regressions reproduced `--bucket ../../escaped` escaping the sample root, same-second capture replacing an existing WAV, a symlinked train/eval bucket escaping the tree, eval overwrite, stale manifest paths, fraction 0 moving a take, fraction 2 moving all takes, and a second freeze changing the split. Invalid zero/negative takes and non-positive/non-finite durations also reached success or the fake recorder. The red tests ran before the fix; after the fix, the sample regressions plus the existing wake-tool file pass. Actual `pw-record`/PipeWire capture remains unverified.
3. **Unbounded/abandoned work — deadlines and lifecycle.** The duplicate external queue enqueue after an ambiguous timeout was fixed as BH-K35; the timed-out `_generate` worker was reproduced red and fixed as BH-K36; and an infinite `ptt.result` wait was reproduced red and fixed as BH-K37. Live Gemini meeting transcription's missing request deadline was reproduced red and fixed as BH-K39; offline faster-whisper/optional pyannote bounds and real provider timeout enforcement remain SUSPECT/UNVERIFIED. The active-meeting shutdown leak is fixed as BH-K38.
4. **Authority/privacy — daemon trusts caller assertions and shutdown capture lifetime.** Current-checkout IPC repros showed: (a) `ask` with caller `owner_verified=True` skipped `ShowoffService.verify_owner`, passed an ordinary synthetic owner fact to the model, and returned it without withholding; (b) `showoff.enter` accepted caller-supplied `owner_present`, `source`, `live_mic`, and an embedding copied from a synthetic enrolled centroid; (c) wake-knock accept accepted caller channel `voice_unavailable`, and separately a caller score of 1.0, opening listening; (d) `Daemon.aclose()` left the active meeting's dual capture and collector alive (BH-K38), permitting capture work to survive daemon shutdown. These were IPC/source-level tests; no real microphone was involved.
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
- **S8:** `_sdk_transcribe` and the live `transcribe_batch_async` path upload through Gemini Files but do not delete the remote file (verified with an instrumented fake SDK for the sync path). Provider-side retention/expiry is not established here. After a sanitized batch transcription, list the owner's Gemini Files via AI Studio/SDK.
- **S9:** offline meeting ASR remains SUSPECT after BH-K39. `_transcribe_channel_async` still runs `LocalWhisperBackend.transcribe()` in `asyncio.to_thread()` without a deadline/cancellation bound, and optional `PyannoteDiarizer.diarize()` is synchronous without a deadline; a stuck native inference/refinement could still park `_meeting_processing` or the event loop. Owner check: on Fedora, force offline posture, run a representative meeting with `assist meeting start`, then `time assist meeting stop` while another terminal runs `watch -n 1 assist status`; if `pyannote_refine=true`, repeat with refinement enabled. Do not add a blind timeout that discards a completed transcript.
- **S10:** real Gemini meeting request timeout enforcement remains UNVERIFIED with the provider/network. The red Unix-socket repro before BH-K39 used an SDK-seam upload that blocked with no timeout; after BH-K39, native async upload and generation receive remaining-time HTTP configs and are wrapped in the absolute deadline. The installed SDK source confirms `HttpOptions.timeout=None` was the old default. Fake SDK tests cancel both upload and generation, but no live key/network request or forced provider stall was run. Owner check: with the owner's valid key, run `assist meeting start`, record several utterances, then `time assist meeting stop`; verify a note, `assist cost` batch rows, and idle `assist status`. This exercises real request completion, not a network stall.
- **Hardware unavailable in this sandbox:** real PipeWire/Hyprland, user systemd manager, Gemini key/network, ECAPA/ONNX model, and cross-UID filesystem access. These remain explicitly UNVERIFIED.

## Fix checkpoints

### BH-K33 [I1, I6, I10] — meeting raw WAVs and concurrent processing state

- **Before fix:** `tests/test_bug_meeting_raw_collision.py` failed with all three observations: same raw mic path for both stops; first archive held later-session bytes; processing was false while the first stop remained pending.
- **Change:** UUID-scoped raw WAV names; processing-session set instead of a shared bool; mode is recomputed from active capture/workers; `finally` restores mode and applies parked connectivity preferences even when transcription fails.
- **Verification:** `pytest -q tests/test_bug_meeting_raw_collision.py tests/test_bug_meeting_stop_failure.py tests/test_phase6_meeting.py tests/test_bughunt_k_config.py tests/test_bughunt_systems.py -k meeting` — **14 passed, 60 deselected**. Ruff passed on all touched Python files.
- **Commit/push:** committed as `a72f4e8` and pushed to `arena/ef0e665f-elaria`.

### BH-K34 [I1, I6] — sample capture and frozen eval data integrity

- **Before fix:** first red run of `tests/test_bug_record_elaria_samples.py` reported **5 failures**: fraction 0 moved a file; an existing eval take was replaced; `--bucket ../../escaped` reached the recorder; manifest paths remained under `train/`; and a symlinked train bucket was followed. A second red run reported **7 failures** for bucket escape, same-second WAV replacement, and invalid takes/durations. The independent Phase 0 probe also observed fraction 2 moving every take.
- **Invariants (prose):** recorded samples remain under the selected sample root and bucket; an existing sample/eval file is never replaced; frozen split paths and manifest entries agree; eval is split exactly once; invalid capture requests do not report success or reach capture.
- **Root cause:** unvalidated bucket strings were interpolated into paths; second-resolution filenames were reused across invocations; `Path.rename()` could replace an eval destination; symlinks were followed; fraction arithmetic clamped invalid values; the freeze marker was overwritten instead of enforced; moved paths were not reflected in the manifest; `takes` and `seconds` were not validated.
- **Repros:** `tests/test_bug_record_elaria_samples.py` covers unsafe bucket, same-second collision, invalid capture arguments, manifest symlinks, symlinked train/eval buckets, existing eval collision, zero/out-of-range/non-finite fractions, stale manifest, repeat freeze, partial-move rollback, manifest-write rollback, and an incomplete-move marker. Existing sample-capture tests remain in `tests/test_wake_knock_package.py`.
- **Fix:** bucket-component validation and root/symlink checks; UUID filenames and no-overwrite capture guard; finite positive duration and positive take count; fraction validation; no-overwrite same-filesystem moves; one-shot `.frozen` marker; atomic manifest-path update; rollback on pre-commit failures, with an in-progress marker retained when recovery is uncertain. Cross-filesystem split moves fail safely rather than copy/overwrite.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_record_elaria_samples.py tests/test_wake_knock_package.py` — **50 passed**. `.venv/bin/ruff check scripts/record_elaria_samples.py tests/test_bug_record_elaria_samples.py` and `git diff --check` passed. No real `pw-record`/PipeWire capture was run.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.
- **Commit/push:** committed as `1c145b8` and pushed to `arena/ef0e665f-elaria`.

### BH-K35 [I2, I9] — ambiguous IPC timeout replayed an external queue enqueue

- **Before fix:** a real Unix-socket `Daemon` committed `queue.enqueue_external`, then an injected 300 ms response delay exceeded the client’s 50 ms total deadline. `assist queue add-external` treated the response timeout as daemon-down, retried against the same SQLite database locally, returned success, and left **2** matching durable jobs. Red repro: `tests/test_bug_queue_timeout_duplicate.py::test_bug_queue_timeout_after_commit_does_not_enqueue_again`.
- **Invariant (prose / I1):** one request causes at most one durable side effect; local fallback is allowed only if no request was sent.
- **Root cause:** `ipc.call()` collapsed post-`sendall` timeouts, malformed replies, and empty replies into `DaemonUnavailable`, which mutating CLI fallbacks interpreted as safe-to-replay.
- **Fix:** distinguish pre-send `DaemonUnavailable` from post-send `DaemonOutcomeUnknown`; ambiguous outcomes do not inherit the fallback exception type. Queue and knock commands surface the uncertainty and do not retry. Authoritative `DaemonError` refusals remain distinct. Definite missing-socket offline fallback remains supported.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_queue_timeout_duplicate.py tests/test_hardening_pass2.py tests/test_bughunt_k_error_surfacing.py tests/test_bug6d_ptt_result_orphans.py tests/test_phase8_offline_voice.py` — **70 passed**. This includes malformed/empty reply classification, missing-socket fallback, and the total-deadline regression. Full Ruff and `git diff --check` passed.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.
- **Commit/push:** committed as the BH-K35 checkpoint and pushed to `arena/ef0e665f-elaria` after this ledger update.

### BH-K36 [I2, I3, I10] — Live chat total timeout left generation work running

- **Severity:** unbounded work / I3 total-deadline and cancellation violation.
- **Invariant (prose / I3):** when the total chat deadline expires, the live request must be cancelled; no blocked SDK worker or tracked generation task remains after `_generate` returns `ChatTimeout`. Do not extend the deadline to hide a hang.
- **Root cause:** `_generate()` called synchronous `GeminiClient.generate()` through `asyncio.to_thread()` and shielded the task. The caller stopped waiting at its total deadline, but Python could not stop the worker. Source inspection also showed that google-genai 1.x's `aio` facade delegated requests to `asyncio.to_thread(self._request)`, so merely switching to an `aio` method would still leave a sync worker.
- **Before-fix red repro:** the first run of `tests/test_bug_generate_worker_cancellation.py` blocked a synchronous fake backend on a threading event (20 ms first-token / 80 ms total). It failed because `_generate()` raised `ChatTimeout` while **one `to_thread` task remained pending and the worker was still blocked**; the test released the event in cleanup.
- **Fix:** live `_SdkTransport.generate_async()` streams using google-genai's native async HTTP client, receives the caller's absolute deadline and applies the remaining time as the SDK request timeout. `GeminiClient.generate_async()` preserves quota checks, async/cancellable RPM waiting, retry/backoff, verification and cost-ledger behavior. `_generate()` cancels (rather than shields) this async task on the unchanged total deadline. The live extra and runtime guard require `google-genai>=2.0.0`; sync fixture/legacy transports retain their compatibility path.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_generate_worker_cancellation.py tests/test_hotword_and_reply_delivery.py tests/test_disclosure.py tests/test_fixtures_and_harness.py tests/test_bughunt_k_quota.py` — **75 passed**. The new `test_bug*` regressions verify cancellation/no retained task, async quota-deadline handling, successful reply + verified ledger row, and cancellation through the `_SdkTransport` stream seam. Full `.venv/bin/ruff check .` and `git diff --check` passed. Installed `google-genai==2.0.0` locally and verified its stream method is a coroutine; no key/network request was made.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.
- **Hardware check (UNVERIFIED):** with a valid owner key, run the forced-deadline probe below after `uv sync --extra live`. It sends one small live request; check that the script reports a deadline and zero retained tasks. If the response finishes before 0.25 s, repeat with a smaller bound.

```bash
cd ~/Elaria
uv sync --extra live
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
XDG_DATA_HOME="$tmp/data" XDG_STATE_HOME="$tmp/state" GEMINI_MODE=live .venv/bin/python - <<'PY'
import asyncio
from assistant.config import load_config
from assistant.daemon import ChatTimeout, Daemon

daemon = Daemon(load_config())
daemon._chat_first_token_s = 0.05
daemon._chat_timeout_s = 0.25

async def check():
    try:
        await daemon._generate(
            "Write a detailed explanation of how rain forms.",
            gen_config={"max_output_tokens": 1024})
    except ChatTimeout as exc:
        print(f"deadline fired: {exc.reason}")
    else:
        raise SystemExit("response finished before the forced deadline; retry with a smaller bound")
    await asyncio.sleep(0)
    if daemon._background_tasks:
        raise SystemExit(f"generation tasks remain: {len(daemon._background_tasks)}")
    print("no generation tasks remain")

try:
    asyncio.run(check())
finally:
    daemon.store.close()
PY
```

### BH-K37 [I2, I3, I10] — Infinite PTT wait budget orphaned a daemon handler

- **Severity:** unbounded wait / handler leak; prose invariant I3 (total deadline and cancellation).
- **Invariant:** a client-supplied `wait_s` is finite, non-negative, and bounded. Invalid waits must be refused before they create a server-side waiter; `ptt.stop` must validate before changing session state.
- **Root cause:** `float(params.get("wait_s") or 0)` accepted `Infinity`, and `_ptt_wait_for()` then used an infinite deadline with `asyncio.wait_for`. The IPC server processes a request inline, so after the CLI's finite timeout/disconnect it kept awaiting the daemon event indefinitely.
- **Before-fix red repro:** `tests/test_bug_ptt_infinite_wait.py` sent `ptt.result(wait_s=Infinity)` through the real Unix socket with a 1 s client deadline. It failed expecting an authoritative `DaemonError`; instead `call()` raised `DaemonOutcomeUnknown` after the client timed out while the instrumented server waiter stayed pending. The final regression also covers `ptt.stop`.
- **Fix:** `_ptt_wait_budget()` rejects booleans, parse errors, non-finite, negative, and values above 90 seconds. Both `ptt.result` and `ptt.stop` use the validator; `ptt.stop` validates before ack/state mutation. Ninety seconds is the existing CLI's largest explicit wait, not a timeout increase.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_ptt_infinite_wait.py tests/test_bug6d_ptt_result_orphans.py tests/test_phase2_surfaces.py tests/test_phase1_dictation.py tests/test_phase8_offline_voice.py tests/test_bug6_live_duplex_and_stop.py` — **90 passed**. The regression matrix exercises Infinity, NaN, negative, and over-90-second waits through both PTT IPC entry points. No audio device, Gemini key, or network was used.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.

### BH-K38 [I10] — `Daemon.aclose()` left an active meeting's capture sources running

- **Severity:** privacy/capture-lifetime leak; prose invariant that daemon shutdown releases all audio sources and stops their collectors.
- **Invariant:** no microphone/system capture process or collector survives shutdown of the daemon that owns it.
- **Root cause:** `Daemon.aclose()` cancelled the dictation and tracked background tasks but omitted the separately stored `_meeting` capture and its collector task.
- **Before-fix red repro:** `tests/test_bug_daemon_aclose_meeting_capture.py` constructs an active meeting and pending collector, calls `Daemon.aclose()`, then fails all three assertions: `DualCapture.aclose()` was not called, the collector remained pending, and `_meeting` remained attached.
- **Fix:** `aclose()` detaches the active meeting, cancels and gathers its collector, calls the capture's async close, resets mode if a meeting was active, and logs capture-close errors only after remaining shutdown cleanup.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_daemon_aclose_meeting_capture.py tests/test_bug_meeting_stop_failure.py tests/test_bug_meeting_raw_collision.py tests/test_phase6_meeting.py` — **10 passed**. No microphone, PipeWire, or Gemini key/network was used.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.
- **Hardware check (UNVERIFIED):** on Fedora with live PipeWire sources, run `assist meeting start`; record the `pw-record` child PIDs using `pgrep -af '[p]w-record'`; then run `systemctl --user stop assistant`. Confirm those exact PIDs exit and the mic/system nodes are released. Restart with `systemctl --user start assistant`.

### BH-K39 [I1, I2, I3, I10] — Live meeting transcription could outlive stop and shutdown

- **Severity:** unbounded wait / abandoned request; prose invariant I3 (total deadline and cancellation).
- **Invariant:** upload and generation share one absolute end-to-end budget; expiry cancels the live request, preserves both raw WAVs, and starts no later utterance. A fully completed transcript must not be discarded because later bookkeeping crossed the budget. Daemon shutdown must cancel an in-flight stop request without abandoning capture close or losing its failure ledger entry.
- **Root cause:** `meeting.stop` used synchronous `MeetingService.transcribe_dual()` through `asyncio.to_thread()` and the SDK defaults `HttpOptions.timeout` to `None`. Merely passing timeouts to synchronous requests cannot guarantee coroutine-level cancellation. Separately, `Daemon.aclose()` did not track `meeting.stop` handler tasks; cancellation during the stop handler's sequential `DualCapture.aclose()` could leave capture channels open, and cancellation skipped the LLM ledger write.
- **Before-fix red repros:** `tests/test_bug_meeting_stop_deadline.py::test_bug_meeting_stop_bounds_live_request_and_retains_raw_audio` uses the real Unix socket and controlled SDK seams for both upload and generation; the pre-fix blocked upload returned `DaemonOutcomeUnknown` while its worker remained pending. `test_bug_daemon_aclose_cancels_pending_live_meeting_stop` failed when stop tasks were omitted from the shutdown worklist. `test_bug_meeting_stop_shutdown_finishes_both_capture_closes` failed when shutdown cancelled a sequential dual-capture close. The shutdown regressions verify handler/task and ledger cleanup, both capture closes, and idle mode.
- **Fix:** `MEETING_TRANSCRIPTION_TIMEOUT_S=840` leaves 60 s inside the existing 900 s IPC limit. Live daemon and direct CLI paths use the SDK's native async upload/generation methods, `asyncio.timeout_at(deadline)`, and remaining-time `http_options.timeout` values; they do not leave a synchronous Gemini worker in `to_thread`. `meeting.stop` tracks its handler so `Daemon.aclose()` cancels and gathers it; capture close is shielded through completion, cancellation restores stale meeting mode, and the failed provider attempt is recorded. Raw WAVs are retained on timeout. Completed transcript persistence has no post-completion time rejection.
- **Verification:** focused meeting/deadline/PTT/shutdown command — **69 passed**; `.venv/bin/ruff check .` and `git diff --check` passed. The first full-suite run returned **1,543 passed, 2 failed, 6 skipped**: the handler-integrity audit classified `_meeting_stop_impl(params)` as an unregistered handler, and the BH-H1 fake `_SdkTransport` implemented only sync methods after BH-K36 moved live calls to `generate_async`. Renamed the helper parameter to `request` and updated that fake to implement the async transport interface; fresh `.venv/bin/pytest -q` returned **1,545 passed, 6 skipped** (**1,551 collected**) versus the user's stated **1,393** baseline. Ten randomized full-suite seeds 260201–260210 each returned **1,545 passed, 6 skipped**; combined coverage was **84.60% statements** and **74.02% branches** (82.07% combined). Installed SDK 2.0.0 async methods/config types were inspected locally; no live key or network request was used. These counts precede the BH-K40 tests/fix below and are not current-tree final verification.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.
- **Hardware check (UNVERIFIED):** with the owner's live key on Fedora, run `assist meeting start`, record several utterances, then `time assist meeting stop`; verify the note, `assist cost` batch ledger rows, and idle `assist status`. This exercises real request success but does not force a provider stall. A forced live stall/timeout remains UNVERIFIED.

### BH-K40 [I1, I10] — Capture-close failure short-circuited peer cleanup and raw archival

- **Severity:** data-loss / capture-lifetime leak when either meeting source fails to close.
- **Reproduction:** `tests/test_bug_meeting_stop_deadline.py::test_bug_meeting_stop_capture_close_failure_closes_peer_and_keeps_raw` first failed on the assertion that system capture closed after a controlled mic-close `RuntimeError`. Its strengthened version blocks the peer close and proves stop cannot return before it finishes; it then checks collector cancellation, both raw WAVs, and idle mode. The independent `test_bug_meeting_stop_capture_source_cancel_keeps_raw_audio` reproduced a second failure mode: a source-local `CancelledError` was misclassified as cancellation of `meeting.stop`, so WAV persistence never ran.
- **Root cause:** sequential `DualCapture.aclose()` made the first close error skip the peer. `_meeting_stop_impl()` awaited close before collector cancellation and raw-WAV persistence, with no error path to those steps.
- **Fix:** close both sources concurrently with `asyncio.gather(..., return_exceptions=True)`, preserve/aggregate source failures, and wrap a source-local cancellation as an ordinary close error. The stop handler now cancels/gathers the collector in `finally`, writes both raw WAVs, then reports close failure with their paths and uses the existing processing/mode-finally cleanup.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_meeting_stop_deadline.py` — **9 passed**; the current ten randomized full-suite seeds 260501–260510 each pass **1,548 passed, 6 skipped**, and the fresh unseeded post-ledger suite passes **1,548 passed, 6 skipped**. This test file covers the close-failure, source-cancellation, remaining-time, async-success/persistence and completion-after-budget regressions. The capture path was not exercised on real hardware.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.

### BH-K41 [I10] — PTT event-stream test leaked an IPC client at event-loop teardown

- **Severity:** test-integrity leak only; no production failure is claimed.
- **Reproduction:** `.venv/bin/pytest -q tests/test_phase1_dictation.py::test_daemon_ptt_round_trip_and_events` passed but emitted `Task was destroyed but it is pending!` for `serve.<locals>._client()` awaiting `reader.readline()`.
- **Root cause:** the raw event subscriber socket and drainer thread were not closed, and the test stopped its event loop before awaiting the IPC server and daemon shutdown.
- **Fix:** shut down/close the subscriber socket, join its drainer, await `server.wait_closed()` and `daemon.aclose()`, stop/join the loop thread, and close the loop.
- **Verification:** the isolated test passes with empty stderr. The ten randomized full-suite runs after BH-K40–K42 and the fresh unseeded post-ledger suite each returned **1,548 passed, 6 skipped**, with no pending-task warnings.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.

### BH-K42 [I10] — UI event-stream tests abandoned subscriber threads

- **Severity:** test-integrity / pending IPC-client tasks; not a production UI behavior claim.
- **Reproduction:** full randomized seed 260303 passed tests but emitted two `Task was destroyed but it is pending!` warnings for `serve.<locals>._client()` blocked at `reader.readline()`. Adding stricter fixture teardown made the leak explicit as teardown timeouts in `test_waybar_follow_reacts_to_status_changed` and `test_overlay_stream_over_real_daemon`: their consumer threads waited indefinitely for >12/>40 output records and were never stopped or joined.
- **Fix:** the consumers now stop once the state required by each assertion arrives, close their stream generators in `finally`, and join their threads. The shared `running_daemon` fixture and manually created serve tests await connection/client cleanup instead of stopping their event loops immediately.
- **Verification:** the two stream tests pass (**2 passed**); seed 260303 rerun after the fix passed **1,548 passed, 6 skipped**, empty stderr. The ten current randomized seeds 260501–260510 also passed without pending-task warnings.
- **Independent verification:** **UNCONFIRMED**; no separate reviewer was available in this continuation.

### BH-K43 [I5] — Wake-knock accept trusted caller channel and score

- **Severity:** authority / privacy boundary; a caller could open command listening without daemon-verified accept evidence.
- **Status:** fixed locally; **UNCONFIRMED** pending independent review.
- **Before-fix red repros:** `tests/test_bug_i5_authority_ipc.py::test_bug_i5_knock_accept_rejects_forged_high_voiceprint_score` sent `channel="voice", voiceprint_score=0.99` over the real Unix socket and observed listening open. `test_bug_i5_knock_accept_rejects_voice_unavailable_bypass` sent `channel="voice_unavailable", voiceprint_score=0.01` and also observed listening open. Both failed their refusal assertions before the fix; the existing `tests/test_wake_knock_package.py` socket test also explicitly expected forged 0.95 to open listening.
- **Root cause:** `_wake_knock_accept` forwarded both values from JSON to `WakeGuard.authorize_accept()`. That guard trusted the caller's `channel`; `voice_unavailable` bypassed the threshold entirely, and `voice` trusted the caller's score.
- **Handler sweep / principal:** `Daemon.handle` is the sole production dispatcher for every registered `_handlers()` method and `events.subscribe`. It now obtains an `IpcPrincipal` from kernel `SO_PEERCRED`, checks the UID against the daemon owner, and stores principal + method in task-local context. JSON `principal`, `uid`, `role`, `speaker`, and similar fields cannot construct that identity. This dispatcher gate covers all state-changing RPC families (PTT/capture, file plans/review/undo, memory, meetings, mode, speech, queue, knocks, hotword, privacy, show-off, class mode, and ask), not only the wake path. A real-socket test verifies the principal equals the connected process and a foreign-UID principal is refused before a class-state change.
- **Fix:** `knock.accept` refuses any caller-supplied `channel` or `voiceprint_score`; the authenticated local owner action is the only currently supported wake-knock accept. `WakeGuard` now requires an `IpcPrincipal` with the daemon's UID and accepts no channel/score arguments. Voice acceptance remains closed until fresh accept audio is captured and scored inside the daemon; the CLI's ordinary `assist knock accept ID` sends only the knock ID.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_i5_authority_ipc.py tests/test_wake_knock_package.py tests/test_stage_d_showoff.py tests/test_disclosure.py tests/test_stage_c_initiative.py tests/test_stage_b_console_class.py` — **146 passed**. Ruff passed on the touched Python files. Real-socket regressions cover forged channel/score fields; no mic, voiceprint scorer, or provider was used. Independent reviewer agents are unavailable, so the fix remains **UNCONFIRMED**.

### BH-K44 [I5] — Show-off entry and owner turns trusted caller assertions

- **Severity:** authority / privacy boundary; copied owner data and booleans could manufacture show-off permission or promote a guest turn.
- **Status:** fixed locally; **UNCONFIRMED** pending independent review.
- **Before-fix red repros:** `tests/test_bug_i5_authority_ipc.py::test_bug_i5_showoff_entry_rejects_copied_centroid_and_capture_flags` created a real enrolled centroid, copied it into `showoff.enter`, and sent `owner_present=true`, `source="mic"`, `live_mic=true`, and `replayed=false`; the real socket entered show-off without any capture. `test_bug_i5_owner_verified_ipc_flag_cannot_bypass_showoff_guest_gate` sent `speaker="owner", owner_verified=true` and a copied embedding during active show-off; the response was classified as owner before the fix.
- **Root cause:** `_showoff_enter` forwarded caller-controlled embedding/presence/source/replay/live-mic assertions to the service. `_ask` treated caller `owner_verified` as authority and, if true, skipped server verification; `channel` and `speaker` were also read from the payload.
- **Fix:** the IPC `showoff.enter` endpoint now fails closed because no daemon-side fresh-capture entry flow exists; it explicitly refuses embeddings and capture flags as evidence. `ask` derives its channel from the registered RPC method, ignores caller embeddings and owner-verification claims, and allows a caller to downgrade to guest but not promote itself. Every request while show-off is active is routed as guest-scope, regardless of a supplied owner label. `showoff.exit` also requires the authenticated local owner and no longer uses caller reason/command/embedding fields to select its authority path.
- **Verification:** the same 146-test command listed under BH-K43 passed, including real-socket regressions and concurrent request-method context isolation. Existing direct `ShowoffService` unit tests still exercise service policy; no socket caller can reach entry through forged values. Independent review is unavailable; the fix is **UNCONFIRMED**. Show-off IPC entry is intentionally unavailable until a daemon-captured live-audio path exists.

### BH-K45 [I1, I5] — Show-off outgoing guard leaked a model secret to the owner path

- **Severity:** confirmed information disclosure; model-returned credential reached the reply with `withheld=None`.
- **Status:** fixed locally; **UNCONFIRMED** pending independent review.
- **Before-fix red repro:** `tests/test_bug_i5_authority_ipc.py::test_bug_i1_i5_showoff_owner_reply_still_runs_outgoing_secret_guard` made the model return a stored `The password is hunter2.` during an active show-off console turn. Before the fix, the real socket response contained `hunter2` and `withheld` was `None`.
- **Root cause:** active show-off did not itself make the ordinary owner `_ask` path restricted. `DisclosureService.leak_in()` therefore received `guest=false, company=false` and intentionally allowed owner-alone secrets.
- **Fix:** every active show-off conversation now enters the guest/demo-safe path before owner memory; that path keeps the explicit demo-safe allowlist, runs the outgoing guest leak guard, and returns a `withheld` descriptor when it substitutes a reply. The ordinary owner path also treats an active show-off observed at generation/guard time as restricted, covering a session that becomes active after prompt construction.
- **Verification:** the same 146-test command listed under BH-K43 passed. Controlled model returns exercise both a stored credential and an ordinary owner fact without network or audio; the post-fix socket replies withhold them and include a `withheld` descriptor. A show-off activation-during-generation regression covers the final race guard. Independent review is unavailable; the fix is **UNCONFIRMED**.

### BH-K46 [I5] — Show-off race kept the owner/company prompt after activation

- **Severity:** confirmed information disclosure; a paraphrase of a stored owner fact reached the active demo reply.
- **Status:** fixed locally; **UNCONFIRMED** pending independent review.
- **Before-fix red repro:** `tests/test_bug_i5_authority_ipc.py::test_bug_i5_showoff_activated_during_owner_turn_uses_guest_prompt` activated show-off during the awaited memory-recall stage of a real-socket `console.say`. A prompt-sensitive controlled model returned a paraphrase of a stored ordinary owner fact under the company prompt. The final exact-quote guard did not catch it; the response contained “bicycle” and had `withheld=None`. Test failed before the fix.
- **Root cause:** the in-flight owner path noticed `public_demo` when building restricted context and the final guard, but selected its disclosure note with `guest=(speaker != "owner")` only. It therefore sent `COMPANY_NOTE`, not `GUEST_NOTE`; a paraphrase was outside the exact-match guard.
- **Fix:** include `public_demo` in the guest predicate passed to `DisclosureService.prompt_note()`, so a show-off session that starts during an owner turn changes the prompt to guest scope as well as filtering context and applying the outgoing guard.
- **Verification:** the real-socket test fails red before this one-line change and passes after; it asserts the guest note is present and no owner-fact paraphrase reaches the response. The focused I5 suite (the six-file command listed under BH-K43) is **146 passed**. Provider, audio, and hardware were not used. Independent review is unavailable; the fix remains **UNCONFIRMED**.

### BH-K47 [I4] — `speech.say` and delayed synthesis escaped the duplex gate

- **Severity:** open-mic playback hazard; local TTS could synthesize/play while the duplex gate reported capture as safe.
- **Status:** fixed locally; **UNCONFIRMED** pending independent review.
- **Before-fix red repros:** `tests/test_bug_i4_speech_say_duplex.py::test_bug_i4_speech_say_gate_survives_synthesis_and_delayed_playback` drove `speech.say` over a real Unix socket with synthesis and playback blocked by events. After the test explicitly forced the text-duration estimate to an expired value, `daemon.is_speaking()` was false during synthesis and playback. `test_bug_i4_reply_playback_gate_survives_synthesis_longer_than_estimate` reproduced gate expiry in the owner-reply path. Both tests failed before the fix.
- **Root cause:** `speech.say` called `SpeechService.speak()` without acquiring the gate. Reply speech relied on `_speaking_until`, an estimate from text length; slow synthesis could outlast that reservation before playback began, and the playback worker itself was not represented in `is_speaking()`.
- **Fix:** playing local-TTS calls use a tracked `_speech_playbacks` worker set. The gate closes before synthesis, remains closed through synthesis/playback, then retains the existing 400 ms tail after the real worker ends. `speech.say` and `_speak_once` use the helper; play-disabled synthesis does not close the mic gate. Playing workers are shielded from request cancellation because cancelling `to_thread` cannot stop audio already being rendered.
- **Verification:** I4 regressions were run red before the change and pass after. `.venv/bin/pytest -q tests/test_bug_i4_speech_say_duplex.py tests/test_bug6f_live_final_and_startup_ack.py tests/test_voice_bughunt.py tests/test_stage_b_console_class.py tests/test_hardening_pass2.py` — **127 passed, 1 skipped**. The scoped I4 mutation audit killed **5/5** changes (worker registration, gate task check, tail reset, `speech.say` bypass, and owner-reply bypass). No audio hardware/provider was used. Independent review is unavailable; the fix remains **UNCONFIRMED**.

### Mutation-test addendum (incomplete triage)

- The earlier four-file focused run generated **1,284 mutants**: **525 killed, 737 survived, 22 with no tests**. In `GeminiClient.transcribe_batch_async`, the deadline conversion mutant `remaining_s * 1000` → `remaining_s / 1000` survived because the test had only a loose upper bound. After delaying fake upload and asserting `20,000 <= generation_timeout < upload_timeout <= 30,000`, that mutant was killed; targeted counters became **526 killed, 736 survived, 22 no tests**.
- A fresh capture-only pass on the current close-failure tests generated **89 mutants**: **59 killed, 19 survived, 11 with no tests** (limited to `tests/test_bug_meeting_stop_deadline.py`). Of the **31** mutants in `DualCapture.aclose`, **24 were killed** and **7 survived**; the seven are changes to exception/note wording, not surviving close-order or source-cancellation behavior. The blocking-peer regression kills mutants that remove/omit `return_exceptions=True`; the source-cancellation red/green test verifies raw retention and secondary error notes. The earlier four-file run remains at 1,284 generated, 526 killed after the timeout test was strengthened, 736 survivors and 22 no-tests; those survivors have not been fully reviewed. This historical broad mutation audit remains incomplete. Temporary `setup.cfg`, `mutants/`, and generated cache artifacts from that run were removed.

### Focused I5/I1 mutation audit [I1, I5]

- `mutmut 3.8.0` could not collect node-id-selected tests in its copied worktree (`no collectors`); the same command passed when run directly there. Stopped rather than spend more time polishing the mutation harness. The temporary `setup.cfg` and `mutants/` tree were removed.
- Temporarily mutated the actual changed source decision points, restored each file in `finally`, and ran the regression owning that branch. The initial **11/11** mutants were killed as listed below; after BH-K46, the added disclosure-note mutation was also killed (**12/12 scoped mutants total; no scoped survivor**): (1) dispatcher peer-UID rejection disabled — `test_bug_i5_nonowner_peer_cannot_change_state_even_with_owner_json`; (2) principal ContextVar installation removed — `test_bug_i5_principal_is_kernel_peer_not_request_json`; (3) method ContextVar installation removed — `test_bug_i5_ipc_method_context_stays_task_local_under_concurrent_sockets`; (4) `knock.accept` forged channel/score rejection disabled — the two forged-score/`voice_unavailable` socket tests; (5) WakeGuard foreign-UID rejection removed — `test_wake_accept_requires_kernel_authenticated_owner_principal`; (6) show-off entry's fail-closed capture refusal removed — `test_bug_i5_showoff_entry_rejects_copied_centroid_and_capture_flags`; (7) active-show-off guest routing disabled; (8) caller channel trusted again; (9) guest outgoing owner-fact guard downgraded to owner scope; and (10) guest `withheld` descriptor removed — each killed by `test_bug_i5_owner_verified_ipc_flag_cannot_bypass_showoff_guest_gate`; (11) final outgoing guard's show-off race bit disabled — `test_bug_i1_i5_showoff_activated_during_generation_hits_final_guard`; (12) prompt note stopped treating a late-starting demo as guest — `test_bug_i5_showoff_activated_during_owner_turn_uses_guest_prompt`.
- This scoped result covers the current I5/I1 changes and their principal disclosure decisions only. It does not resolve the historical 736-survivor mutation run above. The I5/I1 fixes remain **UNCONFIRMED** because no independent reviewer is available.

## Clean-pass log after BH-K46 [I1, I5]

- Focused I5/show-off suite: `.venv/bin/pytest -q tests/test_bug_i5_authority_ipc.py tests/test_wake_knock_package.py tests/test_stage_d_showoff.py tests/test_disclosure.py tests/test_stage_c_initiative.py tests/test_stage_b_console_class.py` — **146 passed**.
- Fresh full suite, unseeded: `.venv/bin/pytest -q` — **1,558 passed, 6 skipped in 75.31s**.
- Second fresh full suite: `.venv/bin/pytest -q --randomly-seed=260601` — **1,558 passed, 6 skipped in 74.15s**.
- `.venv/bin/ruff check .` and `git diff --check` — passed. This is **165 more passing tests** than the user's stated 1,393-test baseline. Six tests remain skipped.
- These are clean test runs, not independent review or hardware/provider proof. BH-K43–K46 remain **UNCONFIRMED**; no independent reviewer is available.

## Clean-pass log after BH-K47 [I1, I4, I5]

- Focused I4 and adjacent suite: `.venv/bin/pytest -q tests/test_bug_i4_speech_say_duplex.py tests/test_bug6f_live_final_and_startup_ack.py tests/test_voice_bughunt.py tests/test_stage_b_console_class.py tests/test_hardening_pass2.py` — **127 passed, 1 skipped**.
- Fresh full suite, unseeded: `.venv/bin/pytest -q` — **1,560 passed, 6 skipped in 70.51s**.
- Second fresh full-suite pass: `.venv/bin/pytest -q --randomly-seed=260622` — **1,560 passed, 6 skipped in 68.78s**.
- `.venv/bin/ruff check .` and `git diff --check` — passed. This is **167 more passing tests** than the user's stated 1,393-test baseline. Six tests remain skipped.
- The focused I4 source-mutation audit killed **5/5** scoped mutants. These are test passes, not independent review or hardware/provider proof. BH-K34–K47 remain **UNCONFIRMED** where no separate reviewer is available; no hardware/provider checks ran.

## Next

1. Reproduce XDG_DATA_HOME transcript placement and 0644 note/DB/WAL/enrollment permissions before any fix; if confirmed, ensure enrollment creation is atomic with mode 0600.
2. Produce the requested Part 2 status table for Live final, ack into open mic, dictate captured nothing, orphaned `ptt.result`, leaked subscribers, shadowing, and CLI ImportError audit. Live final remains SUSPECT until the protocol-level SDK-source root cause is proven; do not substitute a timeout.
3. Resolve I1 suspects with exact owner hardware commands: late Live final under playback guard; non-empty transcript below 0.003 RMS. No hardware/provider checks have run in this sandbox.
4. Run the required fresh bughunt pass and seek independent review. K34–K47 remain unconfirmed where no separate reviewer is available; do not declare completion while confirmed bugs are unfixed or fixes unconfirmed. Historical broad mutation survivors remain untriaged; the scoped I5/I1 decision-point audit is 12/12 killed and the scoped I4 audit is 5/5 killed.
