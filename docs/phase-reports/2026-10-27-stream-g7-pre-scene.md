# Phase report — stream G.7: pre-scene guard + audit triage (2026-10-27)

Design-chat follow-up to stream G (approved as landed). Scene 6 is the
next hardware step; G.7.1 was the only scene-blocking item and is now
landed. Provenance rule applied throughout: the third-party audit is
[CODE-READ, third-party, UNVERIFIED against current docs] — abandonware
with no license, ideas only, zero code copied — and every G.7.1 claim
was verified G.1-class (docs-first) before implementing. Commits:
`319cb37` (G.7.1 sensors) → `2ed6661` (G.7.1 fix) → `32500b4` (G.7.4).

## DONE

- **G.7.1(a) — the documented output shape** (docs-first, binding):
  - live-transcribe §Interim and finalized transcriptions + §Server
    response fields (ai.google.dev/gemini-api/docs/live-api/live-transcribe):
    `interim_input_transcription` = "interim partial transcription
    hypothesis emitted continuously while the user is actively
    speaking"; `input_transcription` = "Finalized, authoritative input
    transcript emitted when a speech turn finishes". **Documented shape
    for our model: continuous interims + one finalized envelope per
    speech turn.**
  - api/live `BidiGenerateContentTranscription`: `text`, `languageCode`,
    `startOffset`/`endOffset` spans — the wire type has no delta flag.
  - SDK `types.Transcription` adds `finished` ("The bool indicates the
    end of the transcription"), `speaker_label`, `words` — so
    **multi-message `input_transcription` with a finish marker is
    type-legal**, and the forum thread "inputTranscription no longer
    streams incrementally" (discuss.ai.google.dev/t/…/136977)
    corroborates incremental delivery in the wild.
  - Verdict: deltas are **plausible but unverified** for
    `gemini-3.5-transcribe-live`; one-shot segments are the documented
    shape; both are type-legal. The third-party "no single final exists"
    claim is therefore NOT adopted as truth — it is adopted as a shape
    the parser must survive.

- **G.7.1(b) — collector trace + the shape-tolerant fix** [TESTED-ONLY]:
  the collector emitted ONE final per envelope (the 6f contract) and
  the flush space-joined finals — correct for segments, corrupting for
  deltas ("Hel"+"lo" → "Hel lo"; worse, a first delta would set the
  collector terminal and truncate the turn). Now one parser serves both
  shapes: parts accumulate (control characters and `<ctrl-token>`
  artifacts stripped; consecutive-identical deltas deduped; cumulative
  snapshots supersede, never append) and ONE final per segment commits
  on the earliest trigger — `finished=True`, a sentence-final boundary
  (the 6f contract: a committed envelope surfaces its final
  immediately), a 0.4 s debounce gap (standalone VERBATIM envelopes
  without punctuation), `turn_complete`, or receiver-loop exit (a dead
  link commits the words BEFORE reporting the failure). Join rules
  (pinned): whitespace boundaries raw-concat (deltas carry their own
  whitespace — the conversational path's pinned semantics), everything
  else space-joined. `commit_reasons` (finished/segment/debounce/
  turn_complete/loop_exit) rides `wire_stats` — scene 6 shows which
  trigger actually fired. The full bug6f suite stays green, including
  the 0.2 s preview+committed envelope pin and the
  finished-omitted/True/False matrix (6f's lesson: `finished` is
  optional on transcribe-live and never gates a commit).

- **G.7.1(c) — audit item #14 closed, one evidenced line:** the
  transcribe-live Manual-VAD docs example does NOT omit
  `input_audio_transcription` — it carries
  `input_audio_transcription=types.AudioTranscriptionConfig()` verbatim
  (live-transcribe §Manual VAD), and api/live documents
  `inputAudioTranscription`: "Optional. If set, enables transcription of
  voice input." Our fixed setup carries it
  (`AudioTranscriptionConfig(language_codes=[])`) — it is required for
  transcript emission, present in both, nothing to change.

- **G.7.1 sensors (commit `319cb37`, landed before the fix):** the
  deciding numbers ride the histogram line — `transcript_family=N
  commits=M dupes=D snapshots=S`. At scene 6: parts > commits =
  accumulation happened (delta shape on the wire); parts == commits =
  one-shot segments. The wire-shape fork is now distinguishable from a
  daylight cycle.

- **G.7.2 — halt vs mid-reply playback, named (report-only, as
  ordered):** NOT instant. Mechanism: **nothing kills the player.**
  `halt` (Win+Shift+F12 → `assist halt` → `_halt`) only sets the
  §4.4 halt flag + `mode=halted` and gates the executor between ops;
  `ptt stop` never touches speech either. The reply's `speak()` runs
  `subprocess.run(player)` in a worker thread and the wav finishes
  (PR_SET_PDEATHSIG kills the player only when the DAEMON process
  dies). Not fixed this round — recorded as a WP1 item beside streaming
  playback; G.7.3's interrupt path is the known mechanism pattern.

- **G.7.3 — WP1 streaming-playback design brief (no implementation,
  attached here and in HANDOFF §5):**
  (i) **Chunked playback queue** — PCM sliced ~50 ms (2,400 B at
  24 kHz); playback starts at the FIRST chunk, not the finished wav;
  interrupt = drain queue + flag + turn-state reset, cutoff < 100 ms
  (this is also G.7.2's fix pattern: a drained queue stops mid-reply
  instantly).
  (ii) **Early-dispatch pipelining** — begin the next leg's generation
  (reply model → voice model) while the previous audio still plays.
  Sizing waits for scene 6's `latency.table` split (reply_to_synth vs
  synth_to_audible). Target math unchanged: release→audible ≤ 8 s
  (primary final ~1–3 s + first audio ~2–4 s).
  **W6 addendum (2026-10-31, measured on owner hardware, session
  94129e):** the full split is now known — release_to_final 3.59 s
  (adaptive abandon; primary wire silent again) · final_to_reply 4.93 s
  (file leg) · **reply_to_synth 11.77 s (chat+TTS — the whale this brief
  exists for)** · synth_to_audible 0.001 s · release_to_audible 20.29 s.
  Prescriptions confirmed/added: stream TTS in ~50 ms slices with
  first-audible at the FIRST slice (the whale is synthesized-but-unheard
  time); the file leg now starts at voice-end (W6 implemented — the
  3.59 + 4.93 stack collapses under the final wait); and
  `FALLBACK_TIMEOUT_S` is now 8.0 s measured from voice-end (the leg
  landed at the old 5.0 s boundary).

- **G.7.4 — transient-state reset pin + contained fix** [TESTED-ONLY]:
  audited the session.open reset block (6d-era): mode, `_stop_event`,
  session ids, `_ptt_last_result`, result slots, finishing marks,
  started/released marks, and the superseded-terminal path all reset —
  the 6d contract holds (pin added). The one gap: the G.6 stage tables
  (`_stage_marks`/`_latency_emitted`) were never pruned — a crashed
  session leaked them forever. Contained fix at the same reset point:
  keep the last 4 tables (an in-flight reply still owes its
  `latency.table`), prune the rest. Pin: 10 crashed sessions' leftovers
  reduce to the in-flight window on the next `ptt.start`.

- **G.7.5 — notes for the record (no action, routed):**
  half-duplex mic gating (frames dropped while she speaks) → WP1 AEC
  decision (unknown #6) + WP4 wake-arming gate context;
  `session_resumption` capability exists on the wire → WP5
  flight/reconnect reference (its G.1 removal from our setup stays
  correct for now — it is sent only with a real rotation handle);
  bounded queues + the TaskGroup BaseExceptionGroup lesson → input to
  the WP1 1.4 GB profiled run.

## DEFECTS FOUND

- [TESTED-ONLY] **The parse-side fork (delta vs one-shot) was
  undistinguishable from a daylight cycle** — right message counts,
  wrong assembled text. Guarded: shape-tolerant accumulation landed and
  the histogram now reports parts/commits/dupes/snapshots. Scene 6
  closes the evidence.
- [UNVERIFIED] Third-party delta claim for our exact model — the docs
  say one-shot; the type system and the forum say deltas are legal. The
  parser survives both; which one `gemini-3.5-transcribe-live` actually
  emits is scene-6 evidence, not chat evidence.
- [TESTED-ONLY, pinned residual] Sub-word deltas without whitespace
  ("Hel"+"lo") join with a space under the pinned join rules. Named in
  the pin (`test_join_rules_whitespace_raw_boundary_space`).
- [UNVERIFIED — named WP1 item] Halt/stop does not stop mid-reply
  playback (G.7.2: nothing kills the player). Fix pattern = G.7.3(i)'s
  queue-drain interrupt (<100 ms). No fix this round, per order.
- [UNVERIFIED] The 1.4 GB daemon peak (stream-F watch item) unchanged;
  WP1's profiled run now also takes the G.7.5 queue notes.

## NEXT GATE

Scene 6, unchanged — GATE v2 stands (HANDOFF §5.6) and §7 is still the
run page. G.7.1 was the pre-scene guard and it has landed; the scene is
unblocked. Expected dump lines gained the shape numbers: `ws.histogram …
transcript_family=N commits=M dupes=D snapshots=S` — `M < N` proves
delta accumulation happened; `M == N` proves one-shot segments; the
`samples=` payloads show the raw pieces either way. Both red and green
are decisions. §5 order after the gate: WP1→WP2→WP4→WP5→WP3 (jump if
rpm hyprland ≥ 0.57)→WP6.

## OPEN QUESTIONS

- Which shape does the wire actually deliver for
  `gemini-3.5-transcribe-live` in Manual-VAD mode? (Scene 6's histogram:
  parts vs commits.)
- VERBATIM transcripts may omit punctuation — the sentence-final
  trigger then falls to the 0.4 s debounce/turn_complete. If scene 6
  shows `commit_reasons` dominated by `debounce` with slow finals, the
  gap constant is the first knob.
- G.7.2's playback kill waits its turn beside streaming playback in
  WP1 — same mechanism, one fix.
- The conversational-Live delta path (non-transcribe models) keeps its
  original raw-concat semantics — untouched by design; if a future
  scene exercises it, the same hygiene rules should migrate.
