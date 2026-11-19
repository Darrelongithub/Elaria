# Phase report — scene-7 mini order M (2026-10-31)

Date: 2026-10-31 · Branch: `arena/c2a7085d-elaria` · Base: `b62e1ca`
(latest clean push) · Authority: mini order M (2026-10-31 rulings:
H.5 fallback-as-primary; gate v2-AMENDED; W1 root cause named).
Sandbox: headless container (not the Fedora laptop). No hardware, no
API key, no PipeWire — everything below is fakes-and-journals unless
tagged otherwise. Merge hold on PR #23 stands; nothing merged.

Order executed: M-2 → (M-3 + M-5) → M-4 → latency scene card proposal.
Verification per order: full suite + ruff + new pins per item.

Suite after the order: **1,982 passed / 6 skipped** (last work-order
baseline 1,945/6; +37 = M-2 ×4, M-3 ×5, M-5 ×8, M-4 ×20) · ruff clean
· plain `uv sync` unchanged (google-genai base).

---

## DONE

### M-2 — probe arm C (registry files model, same wire) [TESTED-ONLY]

`scripts/file_leg_probe.py` gains `--model` (default: the REGISTRY pin
`model_registry.EVENT_TRANSCRIPTION` = `gemini-3.5-transcribe`) and a
section-5 arm C pass: the same production wire (`files.upload` +
`generate_content([prompt, file])`), the same paste-safe output shape as
section 4 (model, raw text + char count, finish_reason, candidate
parts, usage_metadata). Sections 3/4 stay on PRODUCTION's resolved
model — the W1 root-cause record (both wavs landed the literal
`<noise>`, `finish_reason=STOP`) is preserved; arm C is the causal
discriminator: same wav, same wire, only the model differs.

Pins (4 new): arm C routes its own model while section 4 keeps
production's; `--model` override honored; `main()` defaults arm C to
the registry pin (never config resolution — that is the point); the key
never leaks through the arm C pass. File total 10.

**Owner acceptance (scene card):** both standing wavs transcribe as
complete sentences through arm C, eyeball-verified.

**Quota note (ordered):** transcribe-batch free tier = **25 RPD**
(config `transcribe_batch_rpd`, models/batch-25e-06 input tier) vs
projected fallback volume — fallback-as-primary spends one file-leg
call per silent-primary turn. Scene-6 turn rates are far below the cap;
a sustained day is bounded by it. W6's discarded-leg tradeoff (D-1 of
the work-order report) still bills within the same cap.

### M-3 — re-pin the production file leg to the registry model [TESTED-ONLY]

The named suspect is now closed at every layer the order named
(config + doctor registry assert + pin tests):

1. **config:** `model_for_role` resolves a missing/empty `model_<role>`
   key to `PINNED_ROLES[role]` before `model_default` — an unset files
   route can never fall through to the chat model again. Explicit
   config still wins (the §4.1 doctrine: experimentation never blocked
   at runtime).
2. **doctor registry assert:** `registry_report` gains `role_drift`
   rows and doctor renders a hard-fail `registry role pins` check
   naming key / configured / pinned. The membership scan alone called
   this drift "registered" (`gemini-3.5-flash-lite` IS the chat pin) —
   role fit is its own defect class. This check names the owner's
   config line exactly; unset keys are not drift.
3. **pins (5):** registry-pin resolution; drift reported with
   `ok=False`, clean defaults have none; the leg seam
   (`GeminiBatchBackend`) never hard-codes a model (resolution stays
   `model_for_role` = the registry value); `production_facts` == the
   registry pin; doctor wiring end-to-end (drifted `ASSIST_CONFIG`
   → status "fail" naming the key; clean → "ok").

Gate v2-AMENDED clause (ii) first half: **code-complete [TESTED-ONLY]**;
the owner half = the probe re-run through `asr.transcribe_file` after
doctor points the config at the pin (whole sentences = green).

### M-5 — `transcription.stump` sensor [TESTED-ONLY]

Schema line `transcription.stump` when a LANDED transcript is a stump:
char-count < 12 (the order's threshold) or the noise-token class
(`<noise>`, `[Noise]`, silence/music/inaudible-style bracket tokens).
The line carries the class (`noise_token` | `short_stump`), the char
count and sha16 of the stripped text — never the text (the transcript
row is the text's home). Empty text is not a stump: no-text sessions
keep their own verdicts (silence / no_final / deferred / empty).

Wired at both land seams: the dictate flow's `transcription.landed`
emit (shown text) and `DictationService.transcribe_file` (the daemon
file path). Meeting / offline-queue landings are NOT wired — named
below as a next consumer.

Pins (8): detector classes incl. the W1 token verbatim; healthy and
empty negatives; schema content (class + chars + sha16 present, text
ABSENT); dictate wiring both ways (stump lands → line; real sentence →
none); file-service wiring. Journal-sensitive suites swept clean
(stream-h, wp0 journal schema, bug6f/6d/6e/bug6 capture).

### M-4 — G.7.3 streaming TTS (the whale) + early dispatch [TESTED-ONLY]

W6's `reply_to_synth 11.77 s` is synthesized-but-unheard time. Both
G.7.3 halves landed:

**(i) Chunked playback queue** (`tts.ChunkedPlayback`): PCM sliced
~50 ms (2,400 B at 24 kHz s16le mono) into a raw-PCM player's stdin
(`paplay --raw` / `pw-cat -` / `aplay -t raw` — **[UNVERIFIED-argv]
until the latency scene**; spawn failure falls back to whole-wav
playback by construction and the wav is always written). First-audible
at the FIRST slice: `first_slice_mark` + `audio.first_byte at=slice`;
a streamed result's `audible` mark rides it. Interrupt = drain queue +
flag + measured cutoff (< 100 ms design contract, logged as
`tts.interrupted`) — wired into `halt` with the turn-state reset at the
daemon (G.7.2's "halt does not stop mid-reply" gap closed at the
mechanism level). The sink never raises: a dead player drops the
stream and the whole wav reaches the ear; a stream that errored is
never claimed as played. `stream_playback` switch (default on),
honored only with `[tts] player = auto`; `on_chunk` rides
`generate_voice` ONLY when streaming — strict old transport fakes stay
valid.

**(ii) Early-dispatch pipelining:** chat starts the moment the leg
lands. `dictate(on_final_text=)` fires after the text is decided and
BEFORE the cleanup model call + persist (the serial work behind
`final_to_reply 4.93 s` on 94129e); the daemon dispatches `_ask` there
(conversation/narration — the command gate needs cleanup's `flagged`
verdict and deliberately stays on the late path). Exactly-one-reply is
pinned three ways: single-fire claim; the late gate REUSES the early
task with its true start mark (one `reply.invocation` per session);
echo-to-empty / error / no-gate paths CANCEL the parked task.

**latency.table gains the first-audible-at-slice stage** (ordered
journal surface): `first_slice` legs (`reply_to_first_slice_s`,
`first_slice_to_synth_s`) + the target metric `release_to_first_slice_s`
(gate v2-AMENDED clause 3's number). Legs run chronologically — the
stream breaks synth-before-audible — with zero-length legs skipped
(streamed `audible` == `first_slice`); the non-streamed table renders
identical to the G.6 pins.

Pins (20): slice size + first-slice mark + tail flush; honest close
failures; interrupt drain/flag/cutoff < 100 ms; dead-player sink
contract; `audio.first_byte at=slice` (acks stay silent); streamed
`speak` marks + wav kept + no file replay; cache-hit whole-wav
fallback; switch-off keeps strict fakes valid; mid-stream failure
(audio never lost); `interrupt_speech` logging + honest no-op; the
latency table in both modes; early dispatch single-fire / mode-gate /
echo-gate; `_finish_dictation` reuse + echo-cancel + orphan-cancel;
the hook fires before persist (journal-order pin). bug6/bug6d test
doubles updated for the new `dictate` kwarg (same class as the old
`session_id=` lesson).

### M-6 — bug draft exhibit 2 [TESTED-ONLY harness, owner files]

`docs/bug-reports/2026-10-31-gemini-live-transcribe-zero-output.md`
gains exhibit 2: arm B (`gemini-3.8-live` side-channel, the
capabilities-guide config verbatim) — owner-run 2026-10-31: connected,
resumption handle issued, 98/98 chunks acked, 30 s listen, ZERO
transcription-family messages. Verdict shape SILENT (healthy wire,
server heard the audio, output never came) — suppression spans model
families under one account. Owner files the report; both raw transcripts
are the attachment core.

### Latency scene card — proposed [UNVERIFIED until owner scene]

`docs/scene-cards/2026-10-31-latency-scene.md` — proposed via design
chat (the owner schedules; never self-certified). EARS steps and
TERMINAL steps strictly separated (no physical action in a paste-able
block); owner ear = instrument; the terminal reads
`release_to_first_slice_s` against the ear's verdict; both outcomes
are decisions (green = clause 3 provisionally met; slow = the table
NAMES the next whale). Carries the M-2 quota note for the window.

---

## DEFECTS FOUND

- **D-M1 [TESTED-ONLY] short-stump threshold fires on legitimate short
  replies** ("Yes." = 4 chars → `short_stump`). The order's threshold
  (char-count < 12) is implemented literally and pinned; the class tag
  separates true noise-token stumps from short answers. If the owner
  wants fewer false positives on short answers, the threshold or the
  class split is a one-line change — a scene-card ruling, not a builder
  guess.
- **D-M2 [UNVERIFIED-argv]** the three raw-player argvs (paplay `--raw`,
  pw-cat `-`, aplay `-t raw`) are documented-contract shapes, unproven
  on the owner's PipeWire. Failure mode is safe (spawn/write failure →
  whole-wav fallback, `audio.first_byte at=slice` simply absent); the
  latency scene names whichever player engaged.
- **D-M3 [TESTED-ONLY]** meeting and offline-queue transcript landings
  do not yet emit `transcription.stump` (the order named "a landed
  transcript"; the two wired seams cover the dictate chain and the file
  service). Cheap to extend at the same helper; routed to WP5/scene-card
  scope rather than guessed at here.
- **D-M4 [TESTED-ONLY]** early dispatch replies from the RAW transcript
  (at leg-landing the cleanup pass has not run). The late path
  previously preferred the cleaned text when cleanup succeeded — the
  reply now answers the user's actual words; cleanup's `flagged`
  verdict remains a record concern (inbox/transcript row) and a
  command-gate input, exactly as before. Named here because it is a
  reply-text provenance change the owner's ear may notice.
- **D-M5 [TESTED-ONLY]** the interrupt-vs-blocked-write race (halt while
  the feed thread blocks on a full stdin pipe) is handled on both sides
  (the sink swallows, `interrupt` closes/terminates under try/except)
  but pinned only with fakes. The latency scene's halt step (stop
  mid-reply, watch `tts.interrupted cutoff_ms=`) is the hardware proof
  of the < 100 ms contract.
- **D-M6 (carried, open ruling)** the discarded speculative leg may
  still bill (W6 D-1); bounded to silent-primary sessions and the
  25 RPD cap above.

## NEXT GATE

1. **Latency scene (owner, scene card proposed above):** the M-4 target
   `release→first-audible ≤ 8 s` with streamed TTS on the
   fallback-as-primary chain + owner's-ear conversational verdict —
   gate v2-AMENDED clause 3.
2. **M-2/M-3 owner acceptance:** probe run on the owner runtime —
   arm C whole sentences on both standing wavs (clause (ii) first
   half's owner half); `assist doctor` first (it names any role drift).
3. **SC-W3 / SC-W4 / SC-W5** (unchanged, `docs/scene-cards/
   2026-10-31-scene7-followups.md` + the W4 dossier).
4. Then the design chat's gate ruling; merge hold on PR #23 lifts only
   there. §5 order after the gate: WP1 → WP2 → WP4 → WP5 → WP3 (jump
   if rpm hyprland ≥ 0.57) → WP6.

## OPEN QUESTIONS

- **Q-M1:** should `short_stump` (D-M1) stay at the ordered 12-char
  threshold, or should short answers above some floor (e.g. trailing
  punctuation present) be exempted? The scene card's stump greps will
  show the false-positive rate.
- **Q-M2:** gate v2-AMENDED clause 3 measures "release→first-audible"
  — with streamed playback `audible == first_slice` on the healthy
  path, so `release_to_first_slice_s` IS the number. Confirm the design
  chat wants the first-slice leg as THE clause-3 metric (that is how the
  scene card reads it).
- **Q-M3:** the sunrise clause (Live primary restored by config pin if
  Google fixes the account) keeps `model_transcribe_live` in play —
  when the bug report lands with Google, should the fallback-as-primary
  chain keep the speculative Live leg at all, or should W6's
  spec-skip-on-committed-final become the default posture? (No action
  until the account-side suppression is resolved either way.)
