# DISPATCH-BUGFIX-3 — hardware-found capture bug (manager, 2026-11-26)

## FIX-HW1 — Agent J · `BUG-HW1` · daemon capture is static on real hardware

> You are Agent J. Fix `BUG-HW1` in `bugs.md` — the first
> hardware-found bug, with physical evidence. Facts: on the
> owner's Fedora 44 laptop, daemon-captured audio
> (`src/assistant/capture.py`: `pw-record --target=<node.name>
> --rate 16000 --channels 1 --format s16 -`, raw PCM over stdout,
> one process per session) plays back as explosive static
> (owner-saved WAVs `20261126-165648-0f964a.wav`,
> `20261126-171509-974193.wav`; raw_peak 1.0 pre-limiter), while
> the owner's manual `pw-record --target <same node> --rate 16000
> --channels 1 file.wav` is CLEAN. Secondary: intermittent 0-byte
> captures (first-frame latency ~1.5 s; fast stops starve).
> Diagnose the differential — suspects in order: (1) the stream
> PipeWire actually delivers vs the assumed s16le/16 kHz/mono
> (format or rate mismatch reads exactly like this); (2) stdout
> pipe framing/`readexactly` alignment; (3) `--target=` node.name
> resolution opening a different stream than the owner's manual
> target; (4) any processing between pipe and `WavSink`. Method:
> build a sandbox differential harness around
> `pw_record_pcm_stream_command` with a fake `pw-record` that
> emits known-format PCM (including deliberately mislabelled
> rate/format variants) and prove which mismatch reproduces
> static statistics (peak/RMS shape) matching the bug; journal
> the exact argv + negotiated stream facts at capture start so
> the next hardware report is self-diagnosing; add
> `scripts/capture_source_check.py`-compatible owner-runnable
> differential steps to your report (owner records A/B WAVs and
> pastes stats — his ears + `assist transcribe` are the oracle).
> Frozen: wake/voice thresholds (1.75/0.75/0.5), silence floor,
> limiter curve — capture fidelity only. Regression tests named
> `test_bug_hw1_*`. Sync main first (`git fetch origin && git
> merge origin/main`). New `arena/*` branch, merged PR or it
> didn't happen. Never edit OWNERS.yaml. State plainly what only
> the owner's hardware can confirm.
