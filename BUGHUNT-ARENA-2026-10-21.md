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

### BH-K36 — Live chat total timeout left generation work running

- **Severity:** unbounded work / I3 total-deadline and cancellation violation.
- **Invariant (prose / I3):** when the total chat deadline expires, the live request must be cancelled; no blocked SDK worker or tracked generation task remains after `_generate` returns `ChatTimeout`. Do not extend the deadline to hide a hang.
- **Root cause:** `_generate()` called synchronous `GeminiClient.generate()` through `asyncio.to_thread()` and shielded the task. The caller stopped waiting at its total deadline, but Python could not stop the worker. Source inspection also showed that google-genai 1.x's `aio` facade delegated requests to `asyncio.to_thread(self._request)`, so merely switching to an `aio` method would still leave a sync worker.
- **Before-fix red repro:** the first run of `tests/test_bug_generate_worker_cancellation.py` blocked a synchronous fake backend on a threading event (20 ms first-token / 80 ms total). It failed because `_generate()` raised `ChatTimeout` while **one `to_thread` task remained pending and the worker was still blocked**; the test released the event in cleanup.
- **Fix:** live `_SdkTransport.generate_async()` streams using google-genai's native async HTTP client, receives the caller's absolute deadline and applies the remaining time as the SDK request timeout. `GeminiClient.generate_async()` preserves quota checks, async/cancellable RPM waiting, retry/backoff, verification and cost-ledger behavior. `_generate()` cancels (rather than shields) this async task on the unchanged total deadline. The live extra and runtime guard require `google-genai>=2.0.0`; sync fixture/legacy transports retain their compatibility path.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_generate_worker_cancellation.py tests/test_hotword_and_reply_delivery.py tests/test_disclosure.py tests/test_fixtures_and_harness.py tests/test_bughunt_k_quota.py` — **75 passed**. The new `test_bug*` regressions verify cancellation/no retained task, async quota-deadline handling, successful reply + verified ledger row, and cancellation through the `_SdkTransport` stream seam. Full `.venv/bin/ruff check .` and `git diff --check` passed. Installed `google-genai==2.0.0` locally and verified its stream method is a coroutine; no key/network request was made.
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

### BH-K37 — Infinite PTT wait budget orphaned a daemon handler

- **Severity:** unbounded wait / handler leak; prose invariant I3 (total deadline and cancellation).
- **Invariant:** a client-supplied `wait_s` is finite, non-negative, and bounded. Invalid waits must be refused before they create a server-side waiter; `ptt.stop` must validate before changing session state.
- **Root cause:** `float(params.get("wait_s") or 0)` accepted `Infinity`, and `_ptt_wait_for()` then used an infinite deadline with `asyncio.wait_for`. The IPC server processes a request inline, so after the CLI's finite timeout/disconnect it kept awaiting the daemon event indefinitely.
- **Before-fix red repro:** `tests/test_bug_ptt_infinite_wait.py` sent `ptt.result(wait_s=Infinity)` through the real Unix socket with a 1 s client deadline. It failed expecting an authoritative `DaemonError`; instead `call()` raised `DaemonOutcomeUnknown` after the client timed out while the instrumented server waiter stayed pending. The final regression also covers `ptt.stop`.
- **Fix:** `_ptt_wait_budget()` rejects booleans, parse errors, non-finite, negative, and values above 90 seconds. Both `ptt.result` and `ptt.stop` use the validator; `ptt.stop` validates before ack/state mutation. Ninety seconds is the existing CLI's largest explicit wait, not a timeout increase.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_ptt_infinite_wait.py tests/test_bug6d_ptt_result_orphans.py tests/test_phase2_surfaces.py tests/test_phase1_dictation.py tests/test_phase8_offline_voice.py tests/test_bug6_live_duplex_and_stop.py` — **90 passed**. The regression matrix exercises Infinity, NaN, negative, and over-90-second waits through both PTT IPC entry points. No audio device, Gemini key, or network was used.

### BH-K38 — `Daemon.aclose()` left an active meeting's capture sources running

- **Severity:** privacy/capture-lifetime leak; prose invariant that daemon shutdown releases all audio sources and stops their collectors.
- **Invariant:** no microphone/system capture process or collector survives shutdown of the daemon that owns it.
- **Root cause:** `Daemon.aclose()` cancelled the dictation and tracked background tasks but omitted the separately stored `_meeting` capture and its collector task.
- **Before-fix red repro:** `tests/test_bug_daemon_aclose_meeting_capture.py` constructs an active meeting and pending collector, calls `Daemon.aclose()`, then fails all three assertions: `DualCapture.aclose()` was not called, the collector remained pending, and `_meeting` remained attached.
- **Fix:** `aclose()` detaches the active meeting, cancels and gathers its collector, calls the capture's async close, resets mode if a meeting was active, and logs capture-close errors only after remaining shutdown cleanup.
- **Verification:** `.venv/bin/pytest -q tests/test_bug_daemon_aclose_meeting_capture.py tests/test_bug_meeting_stop_failure.py tests/test_bug_meeting_raw_collision.py tests/test_phase6_meeting.py` — **10 passed**. No microphone, PipeWire, or Gemini key/network was used.
- **Hardware check (UNVERIFIED):** on Fedora with live PipeWire sources, run `assist meeting start`; record the `pw-record` child PIDs using `pgrep -af '[p]w-record'`; then run `systemctl --user stop assistant`. Confirm those exact PIDs exit and the mic/system nodes are released. Restart with `systemctl --user start assistant`.

### BH-K39 — Live meeting transcription could outlive stop and shutdown

- **Severity:** unbounded wait / abandoned request; prose invariant I3 (total deadline and cancellation).
- **Invariant:** upload and generation share one absolute end-to-end budget; expiry cancels the live request, preserves both raw WAVs, and starts no later utterance. A fully completed transcript must not be discarded because later bookkeeping crossed the budget. Daemon shutdown must cancel an in-flight stop request without abandoning capture close or losing its failure ledger entry.
- **Root cause:** `meeting.stop` used synchronous `MeetingService.transcribe_dual()` through `asyncio.to_thread()` and the SDK defaults `HttpOptions.timeout` to `None`. Merely passing timeouts to synchronous requests cannot guarantee coroutine-level cancellation. Separately, `Daemon.aclose()` did not track `meeting.stop` handler tasks; cancellation during the stop handler's sequential `DualCapture.aclose()` could leave capture channels open, and cancellation skipped the LLM ledger write.
- **Before-fix red repros:** `tests/test_bug_meeting_stop_deadline.py::test_bug_meeting_stop_bounds_live_request_and_retains_raw_audio` uses the real Unix socket and controlled SDK seams for both upload and generation; the pre-fix blocked upload returned `DaemonOutcomeUnknown` while its worker remained pending. `test_bug_daemon_aclose_cancels_pending_live_meeting_stop` failed when stop tasks were omitted from the shutdown worklist. `test_bug_meeting_stop_shutdown_finishes_both_capture_closes` failed when shutdown cancelled a sequential dual-capture close. The shutdown regressions verify handler/task and ledger cleanup, both capture closes, and idle mode.
- **Fix:** `MEETING_TRANSCRIPTION_TIMEOUT_S=840` leaves 60 s inside the existing 900 s IPC limit. Live daemon and direct CLI paths use the SDK's native async upload/generation methods, `asyncio.timeout_at(deadline)`, and remaining-time `http_options.timeout` values; they do not leave a synchronous Gemini worker in `to_thread`. `meeting.stop` tracks its handler so `Daemon.aclose()` cancels and gathers it; capture close is shielded through completion, cancellation restores stale meeting mode, and the failed provider attempt is recorded. Raw WAVs are retained on timeout. Completed transcript persistence has no post-completion time rejection.
- **Verification:** focused meeting/deadline/PTT/shutdown command — **69 passed**; `.venv/bin/ruff check .` and `git diff --check` passed. The first full-suite run returned **1,543 passed, 2 failed, 6 skipped**: the handler-integrity audit classified `_meeting_stop_impl(params)` as an unregistered handler, and the BH-H1 fake `_SdkTransport` implemented only sync methods after BH-K36 moved live calls to `generate_async`. Renamed the helper parameter to `request` and updated that fake to implement the async transport interface; fresh `.venv/bin/pytest -q` then returned **1,545 passed, 6 skipped** (**1,551 collected**) versus the user's stated **1,393** baseline. SDK 2.0.0 async methods/config types were inspected locally; no live key or network request was used. The 10 seeded randomized/coverage baseline remains the earlier 1,506 collected (1,500 passed, 6 skipped); the new suite has not yet had the required 10-seed pass.
- **Hardware check (UNVERIFIED):** with the owner's live key on Fedora, run `assist meeting start`, record several utterances, then `time assist meeting stop`; verify the note, `assist cost` batch ledger rows, and idle `assist status`. This exercises real request success but does not force a provider stall. A forced live stall/timeout remains UNVERIFIED.

## Next

Settle S9's unbounded offline faster-whisper and optional pyannote paths without losing completed transcripts. Then resume the fresh full pass, mutation testing, independent fix reviews, and final clean pass; report survivors, entry-point maps, and hardware-only checks precisely.
