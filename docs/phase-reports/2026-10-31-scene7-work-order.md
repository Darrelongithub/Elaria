# 2026-10-31 — Scene-7 evidence bundle: work order W1–W7 (sandbox build pass)

Base `b3db316` (verified at activation per the cross-lane protocol —
origin tip == baseline, empty diff). PR #23 stays MERGE-HELD; storage
lane untouched (additive-only firewall held). Owner-run proofs are
scheduled as scene cards, never self-certified.

## DONE

- **W1 — file-leg stump: probe built, send shape verified against the
  docs [TESTED-ONLY harness; HW root cause pending owner run].**
  `scripts/file_leg_probe.py` replays both known wavs through the leg
  EXACTLY as production invokes it (`asr.transcribe_file`) and adds one
  raw SDK pass printing the metadata production discards
  (finish_reason, usage_metadata, candidate parts, raw text + char
  count). Paste-safe (the key is never printed — pinned). What
  production sends is now verified against the generateContent Files
  docs (fetched 2026-10-31): stdlib-`wave` file (mono/16-bit/16 kHz,
  header consistent — pinned), SDK `files.upload(file=path)` +
  `generate_content([prompt, file])` = the documented pattern
  [CODE-READ, docs-verified]; the prompt is production's own
  (`gemini_client.batch_transcription_prompt`, now a single shared
  construction the probe imports — no reimplementation). Root cause
  discriminator is the probe's finish_reason: **MAX_TOKENS → output
  truncation; STOP with a stump → the model heard a stump** (file
  processing/encoding/rate). Harness tests: 6 pins
  (`tests/test_file_leg_probe.py`). Acceptance (both wavs transcribe as
  complete sentences on owner runtime) awaits the SCENE run.
- **W2 — arm B rebuilt from the conversational docs, verbatim
  [TESTED-ONLY].** The door failure is named: WS 1007 "response
  modalities (TEXT) not supported" — `response_modalities: ["TEXT"]`
  belongs to transcription models. Arm B now carries the Live
  capabilities guide "Audio transcriptions" input shape (fetched
  2026-10-31): `config = {"response_modalities": ["AUDIO"],
  "input_audio_transcription": {}}`, wav as `audio/pcm;rate=16000`
  blobs, side-channel read of `server_content.input_transcription.text`
  (the get-started-sdk "Receiving text" read). Every message printed
  verbatim + summary. Verdicts are exact: `ARM B VERDICT: SPOKE` /
  `ARM B VERDICT: SILENT` (connected + audio acknowledged + zero
  transcription) — and `NO-RUN` for a dead door, which is a result
  shape, never misreported as SILENT. Robustness: every send guarded
  (a send to a closed socket prints "send refused" and completes the
  run — the old arm B tracebacks on 1007-closed sends, pinned). The
  arm-summary counter bug is fixed at the root: families are classified
  from EVERY attribute location on the message and its server_content
  (the old counter checked one location and printed `voice_activity: 0`
  while dumping two VA messages — regression pin counts 2). 7 pins
  (`tests/test_live_repro_arm_b.py`).
- **W3 — Python 3.14.8 local-ASR breakage: named degradation, and the
  mechanism class identified [TESTED-ONLY].** faster-whisper 1.2.1's
  `decode_audio` calls `av.open(file, mode="r", metadata_errors="ignore")`
  [CODE-READ, third-party source]; PyAV v11–v14 all accept
  `metadata_errors` (verified against PyAV tags v11.0.0/v12.1.0/
  v14.4.0), and faster-whisper declares `av>=11` — so the 3.14.8
  resolution pulled a NON-conforming `av` (the exact identity is what
  the guard prints). The leg now degrades BY NAME: pre-check via
  `inspect.signature(av.open)` + a TypeError belt at the decode call
  site → `LocalAsrDegraded` (plain-language, non-traceback), a
  `local_asr.degraded` schema line carrying `av_file= av_version=
  open_params=`, and the doctor view reports
  `available: false` with the named reason (no more blind "≥3.11
  supported" claim). Acceptance (transcribes OR named degradation on
  3.14.8) awaits SC-W3 on the owner runtime. 5 pins
  (`tests/test_local_asr_degraded.py`).
- **W4 — release-bind defect dossier [HW-PROVEN evidence, design only].**
  `docs/dossiers/2026-10-31-hyprland-057-release-binds.md`: both
  incidents recorded (14:02 eaten stop → 301 s / 9,637,440 B runaway →
  watchdog rescue; 14:56 F2-first clean stop + WIN-lift double stop →
  two `stop.noop`, safe direction proven), the defect shape named
  (release binds modifier-state-dependent at trigger-release), the
  standing two-step-release mitigation, the Lua-era 0.57 bind re-spec
  (release dispatch must not depend on the chord; bare-F2 release +
  chord press; two release binds are safe because stop is idempotent;
  watchdog stays a backstop), and the 300 s evaluation (acceptable as
  RESCUE, never as design; WP5 long-recording gets an explicit mode,
  not a bigger global ceiling). Re-proof in BOTH directions = SC-W4
  (the WP3 jump discriminator). No bind code touched — WP3 owns binds.
- **W5 — mic warm-up banked per the addendum ruling [HW-PROVEN ×4].**
  The always-active-mic proposal is ruled AGAINST (recorded HANDOFF
  §5.11): it would make the 14:02 hot-mic class permanent, falsify the
  `capture.node_state` suspended-after-close privacy proof, desensitize
  the mic-in-use indicator, and contradict settled hold-to-talk. WP1
  scope named: (i) READY-EARCON (distinct second cue at first audio
  frame — warm-up 1417.6/1346.5/1818.8/1607.4 ms; owner speaks on the
  blip; acceptance = audible within 50 ms of first frame,
  distinguishable from the session-open cue by ear) and (ii) PRE-ROLL
  DISCARD (frames before first-frame dropped by construction).
  Always-on listening stays exclusively a WP4 wake-word-mode property;
  no lane implements node pinning/keep-warm/always-on capture. SC-W5
  schedules the acceptance run.
- **W6 — latency budget fed and the two named levers implemented
  [HW-PROVEN numbers; TESTED-ONLY code].** The 94129e split
  (release_to_final 3.59 · final_to_reply 4.93 · reply_to_synth 11.77 ·
  synth_to_audible 0.001 · release_to_audible 20.29) is recorded in the
  G.7.3 brief addendum. Implemented: (1) the file leg now starts
  speculatively at VOICE-END (the wav is finalized at voice-end; the
  leg runs concurrently with the post-release final wait instead of
  stacked after the adaptive abandon) — the BH-K3 gate consumes it only
  when `needs_fallback`, otherwise discards it unawaited and never
  substitutes it (scene-3b contract, re-pinned); the speculative call
  is skipped when the primary already covers the audio (committed
  final, no trailing speech — the BH-K1 cost contract, untouched);
  (2) `FALLBACK_TIMEOUT_S` 5.0 → 8.0 s, the budget measured from
  voice-end (the leg landed at the old 5.0 boundary — a slower day
  timed out a working leg); a slow leg now names `verdict=timeout` on
  `fallback.outcome` instead of a generic error. New schema lines:
  `fallback.speculative_start` (journal-visible, before
  `post_timeout_route` — the ordering IS the W6 proof) and
  `fallback.discarded`. Stream TTS (~50 ms slices, first-audible at
  the first slice) remains the G.7.3/WP1 brief item (named, not
  contained — per the standing ruling). Pins: 2 new W6 contract pins +
  4 existing good-final pins updated to "at most the one speculative
  call, never substituted" (the substitution assertions are unchanged
  and stronger than before).
- **W7 — cosmetics/paperwork.** (a) `assist status` `ptt_session_id`
  now names a LIVE session only (exactly while a holder row exists —
  the 94129e "closed 14 s prior, holders empty" staleness is gone);
  history lives in the new `last_session_id` key; the `--until-quiet`
  consumer reads both (old-daemon shape tolerated). [TESTED-ONLY]
  (b) Manifest reconciliation recorded (HANDOFF §4 addendum): the
  manifest is a scene-record (8/6), the disk is 35+ (named: the 9.6 MB
  watchdog capture + W1's stump); reconcile-on-start is a storage-lane
  item inherited by WP5's deferred-retry consumer — no storage code
  touched. (c) The Google bug report is DRAFTED for the owner to file
  (`docs/bug-reports/2026-10-31-gemini-live-transcribe-zero-output.md`):
  transcribe-live accepts audio and bills input tokens (dashboards
  Oct 24–27) yet emits zero transcription output across daemon
  sessions and the verbatim-docs repro on a valid key; the draft
  includes the arm A evidence description (VAD echoes at exact offsets,
  server_content empty of transcription families, 30 s listen, zero
  transcripts) and the three asks.
- Suite: full run green on the final tree (see NEXT GATE for numbers);
  ruff clean. Scene cards for the owner proofs: SC-W3 (local ASR on
  3.14.8), SC-W4 (double-stop both directions), SC-W5 (ready-earcon),
  plus W1/W2 run instructions — `docs/scene-cards/2026-10-31-scene7-followups.md`.

## DEFECTS FOUND

- **D-1 (W6 quota tradeoff, named not resolved).** A speculative leg
  that loses the race is discarded but its worker thread runs to
  completion — the file-transcription call may still bill. On the
  silent-wire reality (4/4 sessions `transcript_family=0`) the leg is
  the de-facto primary and the tradeoff is small; if the primary
  recovers, every utterance pays one wasted call. The W6 cost guard
  (skip when the primary already covers the audio) bounds it to
  "primary silent or tail-unconfirmed" sessions. **Design chat to rule**
  whether that residual spend is acceptable on the free tier.
- **D-2 (dependency identity unknown).** Which non-conforming `av` the
  3.14.8 resolver actually installed is not yet known — the W3 guard
  prints `av_file/av_version/open_params` precisely so SC-W3's one run
  names it. Until then the fix-the-dependency path (vs the shipped
  degradation) cannot be specified.
- **D-3 (arm B configuration nuance).** The bare get-started connect
  example carries only `response_modalities`; the side-channel read
  needs `input_audio_transcription` (the capabilities guide's
  transcription example adds it). Arm B carries the transcription
  example's shape and the docstring cites both. If arm B comes back
  SILENT, the first question is this config nuance — before account
  gating.
- Logged, not fixed (existing): bug6 [BROKEN-laptop, main-parity];
  G.7.2 playback kill; mic clipping 1.0 (WP1 input-gain); the
  deferred-audio manifest contract (6 unresolved wavs).

## NEXT GATE

Owner-run scene cards (design chat schedules; ≤30 min daylight each;
both outcomes are decisions):
1. **W1 probe + W2 arms** (paste-safe scripts) — the outputs feed the
   H.5 ruling and the bug report.
2. **SC-W3** — local ASR on 3.14.8 (transcribes OR named degradation).
3. **SC-W4** — double-stop both release directions (the WP3 jump
   discriminator).
4. **SC-W5** — ready-earcon acceptance (after WP1 builds it).

Suite baseline after this round: **1,945 passed / 6 skipped / 0 errors,
ruff clean** (baseline was 1,925/6; +20 = W1 6 + W2 7 + W3 5 + W6 2). PR #23 stays MERGE-HELD; no merges until design chat
lifts the hold.

## OPEN QUESTIONS

1. **H.5 ruling** (unchanged position): the 8 s bar stands unless the
   owner re-rules with the H.5 numbers AND the W1/W2 outputs in hand.
   W6 shaves the leg stack (~3.6 s) but `reply_to_synth` 11.77 s (the
   whale) is the remaining gate-killer until G.7.3 lands.
2. **D-1 quota ruling** (above) — is one wasted file-leg call per
   silent-primary utterance acceptable on the free tier?
3. **W1 root cause** — truncation vs stump: named by the probe's
   finish_reason on owner runtime. If truncation: the leg's gen-config
   is the fix (a `maxOutputTokens` floor); if stump: the file-upload
   processing path is the suspect and the raw pass's usage_metadata is
   the next evidence.
4. **W2 verdict → re-pin question** — if ARM B SPOKE where ARM A stays
   SILENT, the design chat owes a ruling on re-pinning PTT
   transcription to the `gemini-3.8-live` side-channel (H.5 option i;
   quota math in the stream-H report).
