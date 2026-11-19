# Phase report — stream F: why does the Live API withhold the final? (2026-10-26)

Owner order 2026-10-26, after scene 4. Evidence rules per REFERENCE §5.
Tags: [HW-PROVEN] / [TESTED-ONLY] / [UNVERIFIED] / [BROKEN-laptop,
main-parity]. Streams D and E closed their stream reports at issuecomment-
6419021018; this is the post-scene-4 stream F phase. Commits:
`19db2b3` (sensors, F.1+F.3), `c3a2b5c` (fix, F.2/F.3 + watch-item
hardening), this report + HANDOFF in the docs commit.

## DONE

- **F.1 raw-wire histogram sensor** (`19db2b3`) [TESTED-ONLY until
  scene 5 runs it]. `GenaiLiveTransport._note_wire` counts every Live
  message the session receives (top-level fields plus `server_content.*`);
  at flush the journal gets `ws.histogram session=<id> types={type:count}`
  with up to 3 samples of unparsed/unrecognized shapes — text fields
  only, never audio bytes, max ~200 chars each. google-genai surfaces
  parsed `LiveServerMessage` objects rather than raw WS frames, so
  "message type" = the populated fields of each message; that mapping is
  documented in the method. This is the deciding fork: zero
  transcript-family counts = the audio never reached the model (or
  frames were never sent); transcript deltas with no recognized final =
  the final arrives in a shape the parser does not match.

- **F.2 protocol truth** (citations below). What we send at
  `activity_end_ok=True`, quoted from `GenaiLiveTransport.activity_end`:

  ```python
  await self._session.send_realtime_input(activity_end=types.ActivityEnd())
  ```

  which the google-genai converter turns into wire
  `{"realtimeInput": {"activityEnd": {}}}` (verified in the vendored SDK
  `_live_converters.py`). Docs (live-transcribe page, "Manual VAD
  (Push-to-Talk)"): "disable automatic VAD entirely and control turn
  boundaries explicitly using `activity_start` and `activity_end`" —
  `activityEnd` IS the documented finalization trigger for this idiom
  (api/live: it "can only be sent if automatic (server-side) activity
  detection is disabled", which is exactly our
  `automatic_activity_detection.disabled=True` config). **The handshake
  matches the documented push-to-talk example bit-for-bit — the trigger
  is NOT the bug and was not changed.**

- **F.2(b)** input transcription is explicitly enabled and correctly
  shaped: `input_audio_transcription=AudioTranscriptionConfig()` is the
  documented plain form (`mode` defaults to `VERBATIM`;
  `language_codes` omitted = auto). Quote (live-transcribe, "Interim and
  finalized transcriptions"): the finalized transcript is "emitted when
  the speaker pauses, the turn completes, or speech is finalized".

- **F.3 audio-sent sensor** (`19db2b3`) [TESTED-ONLY until scene 5].
  `audio.sent session=<id> chunks=N bytes=M format=... rate=...` at
  flush, plus largest-chunk frames and the activity signals in
  `wire_stats()`. Cross-check against the docs' "Sending audio" section
  found **the one wire deviation: we pushed capture frames straight
  through (30 ms = 480 samples / 960 bytes per message) where the docs
  prescribe chunks of 100 ms (1,024 to 2,048 frames).** Format, rate and
  encoding already matched (raw 16-bit PCM, 16 kHz, mono, little-endian;
  `pw-record --rate 16000 --channels 1 --format s16`; MIME
  `audio/pcm;rate=16000`).

- **The format fix** (`c3a2b5c`) [TESTED-ONLY until scene 5]:
  `GenaiLiveTransport` coalesces capture frames into the documented
  1,600-sample / 3,200-byte (100 ms) wire chunks and flushes the partial
  tail BEFORE `ActivityEnd` (prime directive: audio never lost). Both
  meters are kept — `audio_frames_sent` (capture frames pushed in) and
  `chunks` (wire sends; `bytes/chunks` reveals the chunk size on the
  wire). bug6f's send-count pin became byte-preserving (356 × 960 bytes
  on the wire; 107 sends = 106 full chunks + flushed tail).

- **F.5 budget ruling (now, per "only after F.2"):** keep
  `[transcribe] final_wait_s = 12.0`. Reasoning: the docs imply the
  final arrives promptly after `activityEnd` ("the turn completes, or
  speech is finalized"); the Hybrid VAD section exists precisely to
  "bypass the default server-side silence wait" that would otherwise be
  the main latency, so the documented worst case is on the order of a
  second or two after the correct trigger — 12 s is a generous ceiling
  (roughly 6–12× that) and still catches slow-queue days while keeping
  the session bounded. The knob stays configurable; no change made.

- **Scene-4 record (owner-run, HW evidence)** [HW-PROVEN]: release bind
  works — `stop.requested source=bind` (wall one fallen). Flush
  mechanism proven-working: `final.wait collector=alive
  activity_end_ok=True → final.timeout waited_s=12.054 → deferred
  no_final, text_chars=0`; quota 0 user-turn; silence rules respected.
  4th wav kept: `audio/20261026-191330-d297f1.wav`.

- **F.4 DIAGNOSTIC prepared** (housekeeping, one shot — WP5 owns the
  retry consumer): `assist transcribe ~/.local/share/assistant/audio/
  20261026-191330-d297f1.wav`. One call through the pinned non-live file
  route (`model_transcribe_batch = gemini-3.5-transcribe`), labelled
  DIAGNOSTIC everywhere. Result PENDING owner run — see OPEN QUESTIONS.

## DEFECTS FOUND

- [HW-PROVEN] **The final is withheld on the wire.** Scene 4 closed with
  zero user text after a full spoken utterance (12.05 s budget,
  `text_chars=0`), four sessions running. The Live session exchanged
  messages (session alive at flush) but no transcript-family result
  reached us. Fork not yet split — that is exactly what the
  `ws.histogram` / `audio.sent` sensors decide at scene 5.

- [TESTED-ONLY] **Undersized input chunks (30 ms vs documented 100 ms).**
  Fixed in `c3a2b5c`; awaiting scene-5 wire evidence before any claim.

- [UNVERIFIED] **1.4 GB daemon peak** (16:27–19:13 run; prior runs
  70–89 MB) while holding a 5-minute live session. Findings, one
  paragraph: every obvious frame retention is bounded —
  `RollingAudioBuffer` is capped at 30 s (~1 MB), `WavSink` streams each
  `writeframes` to disk (the 5-min wav is ~9 MB on disk, not RAM), the
  wake buffers are fixed 2–3 s anonymous mmaps, and `_ptt_results` caps
  at 8. The unbounded-within-a-session structures are `collected`
  (text-only LiveEvents, MBs at worst) and the transport's asyncio
  queue, which is drained only while the collector lives — dictate
  cleanup used to cancel the collector *before* closing the transport,
  leaving a window where the receiver could still pump `output_audio`
  frames (her voice, ~48 KB/s) into a queue nobody drains; that ordering
  is now swapped (trivial hardening in `c3a2b5c`, transport closes first).
  The remaining suspect is the google-genai SDK's own WS/session state,
  which no one has profiled; **WP1 owns one profiled daemon run
  (tracemalloc or heap snapshot) before any speculative fix.**

## NEXT GATE

Scene 5 (owner-run) — the merge-gate scene, now with wire sensors. The
run page is HANDOFF §7; its EARS and TERMINAL steps are strictly
separated and no physical action appears inside a paste-able block.
Expected dump after the natural cycle: `ws.histogram` with
transcript-family counts, `audio.sent chunks=N bytes=M`, `final.received`
with text, `reply.invocation` with `reply.char.count`, quota 1
`user-turns (schema.expected)`, and the spoken reply you heard at the
end. A red scene 5 now leaves wire evidence and splits the fork
decisively: transcript deltas with no final = parser mismatch (our
side); zero transcript-family counts = the audio never reached the
model (transport/model side). §5 order after the gate: WP1→WP2→WP4→
WP5→WP3 (jump if rpm hyprland ≥ 0.57)→WP6.

## OPEN QUESTIONS

- **F.4 diagnostic transcript** — what was said at 19:13 into
  `audio/20261026-191330-d297f1.wav`? One shot, DIAGNOSTIC, on the
  laptop (the sandbox has no Google network and no key):

  ```
  assist transcribe ~/.local/share/assistant/audio/20261026-191330-d297f1.wav
  ```

  Paste the line it prints back in the PR thread. This is housekeeping
  only — WP5 owns the retry consumer; the kept-wav backlog stays at 4
  until then (transcribe+answer or explicitly marked never-retried).
- If scene 5 is red: which fork did the histogram pick? (The answer
  decides whether the next fix is the parser or the pipeline.)
- The press earcon still awaits owner ear-confirmation [TESTED-ONLY
  sensor].
- [BROKEN-laptop, main-parity] bug6e dev-laptop pw-record hang seam
  unchanged.
