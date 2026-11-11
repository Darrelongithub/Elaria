# Phase report — stream G: the primary route must hear AND speak (2026-10-27)

WP1 round 1. Owner order 2026-10-27 after scene 5 (session 77cc4efb1886
met the WRITTEN gate but the owner held the merge: "that was so slow took
like a minute"). Commits: sensors → fix → docs, in that order.
Tags: [HW-PROVEN] / [TESTED-ONLY] / [UNVERIFIED] / [BROKEN-laptop,
main-parity].

## DONE

- **Scene-5 wire record** [HW-PROVEN]: the stream-F chunk fix is proven
  on the wire — `voice_activity` timestamps match `audio.sent` bytes
  exactly (720,960 B = 22.53 s; 312,000 B = 9.75 s @ 16 kHz/16-bit) and
  the model's VAD tracks the speech. And the defect is now on the wire
  too: `types={"message": 2, "voice_activity": 2}` — zero
  transcript-family messages, both sessions. The turn that did answer
  (77cc4efb1886) answered via the saved-WAV fallback: release
  06:45:01 → synth complete 06:45:29 = 28 s (12 s dead final-wait + 7 s
  fallback transcription + 9 s reply+TTS); playback-start was
  UNMEASURED — hence G.6.

- **G.1 docs first** (citations and diff below): the complete
  session-setup example for realtime transcription on the Live API,
  field-by-field against what we send. Two deviations named BEFORE the
  fix.

- **G.2 sensors** (`tests/test_stream_g_primary.py`, fakes only):
  `ws.histogram` sampling extended to ALL message types (text fields
  only, ≤200 chars per sample, never audio bytes, up to 3 samples per
  type) so scene 6 shows the payloads themselves; the histogram line
  now carries `setup=ok|missing retries=N; voice_end=…;
  transcript_family=…; types={…}; samples=[…]`. Setup evidence comes
  from `session.setup_complete` — which matters because the google-genai
  SDK reads exactly ONE message in `connect()` and proceeds even when it
  is not `setup_complete` (live.py ~1217).

- **G.6 latency instrumentation**: `audio.first_byte` (playback-start,
  emitted at successful player spawn with `since_synth_s`) closes the
  synth→audible blind spot; `latency.table` logs the measured stage
  legs per session — `release_to_final_s`, `final_to_reply_s`,
  `reply_to_synth_s`, `synth_to_audible_s`, `release_to_audible_s` +
  named missing legs. Marks ride `SessionResult.final_mark` (stamped at
  final.* classification), `SpeechResult.synth_mark/play_mark`, and the
  daemon's stage table. A reply session emits at speech completion; a
  no-reply session emits at finisher close. Release→AUDIBLE is now
  measured, never inferred.

- **G.3 setup fix** (the two named deviations, gone):
  `input_audio_transcription.language_codes` is now `[]` (the documented
  auto-detect form — see the diff), and `session_resumption` rides only
  when a rotation handle exists (we always sent `sessionResumption: {}`).
  Plus the setup-proof guard: a connect whose first message is not
  `setup_complete` takes ONE fresh session before the link is trusted
  (Enterprise docs: streaming audio before setup_complete "may result in
  empty transcriptions" — our exact symptom), with the evidence on the
  histogram line.

- **G.4 adaptive early-abandon**: when the server's `voice_activity`
  ACTIVITY_END has been received and zero transcript-family messages
  exist, the documented prompt final is already overdue — the remaining
  wait is cut to the new `[transcribe] final_abandon_grace_s` (default
  3.0 s, configurable), while `final_wait_s` (12.0 s) stays the
  ceiling. `final.timeout`'s note names the reason
  ("adaptive abandon after voice_end grace …" vs "budget expired
  after …"). The 12-second dead wait can no longer happen on the known
  failure shape.

- **G.5 config-ID audit vs lifecycle (2026-11-17 retirements) +
  forbidden-ID scan** [TESTED-ONLY, docs-verified]: all 10 configured
  model strings are `registered` (scan output recorded below); zero
  forbidden, zero unregistered. The 2026-11-17 shutdown cohort
  (`gemini-3.1-flash-tts-preview`, `gemini-2.5-flash-preview-tts`,
  `gemini-2.5-pro-preview-tts`, `gemini-3.1-flash-live-preview`,
  `gemini-2.5-flash-native-audio-preview-12-2025`; replacements
  gemini-3.8-flash-tts / gemini-3.8-flash-lite-tts / gemini-3.8-live —
  ai.google.dev/gemini-api/docs/deprecations) touches this project ONLY
  through `FORBIDDEN_IDS`, which is exactly where those ids are allowed
  to live as data. Every invoked id is safe past 2026-11-17:
  `gemini-3.5-flash-lite` (retirement 2027-07-21 or later), and "no
  shutdown date announced" for `gemini-3.5-transcribe`,
  `gemini-3.5-transcribe-live`, `gemini-3.8-live`; `gemini-3.8-flash`
  is current GA. `CACHED_TTS = gemini-3.8-flash-lite-tts` is the
  documented replacement family, not a retiring preview.

### G.1 — the setup diff (named before the fix)

The docs' complete Python setup for realtime transcription
(ai.google.dev/gemini-api/docs/live-api/live-transcribe, §Get started,
last updated 2026-08-26) is:

```python
config = types.LiveConnectConfig(
    response_modalities=["TEXT"],
    input_audio_transcription=types.AudioTranscriptionConfig(
        language_codes=[],  # Automatic language detection
    ),
)
```

and its §Manual VAD (Push-to-Talk) variant — our idiom — is exactly:

```python
config = types.LiveConnectConfig(
    response_modalities=["TEXT"],
    realtime_input_config=types.RealtimeInputConfig(
        automatic_activity_detection=types.AutomaticActivityDetection(
            disabled=True
        )
    ),
    input_audio_transcription=types.AudioTranscriptionConfig(),
)
```

with the handshake `activity_start` → audio (`audio/pcm;rate=16000`,
100 ms chunks) → `activity_end`. Field-by-field against what we sent:

| Field | Docs | We sent | Verdict |
| --- | --- | --- | --- |
| `generationConfig.responseModalities` | `["TEXT"]` | `["TEXT"]` | match |
| `realtimeInputConfig.automaticActivityDetection.disabled` | `true` | `true` | match |
| activity_start/audio/activity_end handshake | Manual VAD idiom | same (100 ms chunks since stream F) | match |
| `inputAudioTranscription` | `{}` or `{languageCodes: []}` (auto); hints are BCP-47 **with region** (e.g. `["es-ES"]`; supported table lists `en-US`/`en-GB`/`en-IN`, no bare `en`) | `{languageCodes: ["en"]}` | **DEVIATION 1 (fixed)** — bare ISO-639 tag, not the documented shape |
| `sessionResumption` | absent from every example | `{}` always (`handle=None` → empty object on the wire) | **DEVIATION 2 (fixed)** — now only with a real handle |
| `setup_complete` before audio | required (Enterprise model page: else "may result in empty transcriptions") | assumed, never proven (SDK swallows it) | **DEVIATION 3 (fixed)** — proven + one retry |

Corroboration: the Google AI forum's own guidance for
"gemini-3.5-transcribe-live sessions … silently stop returning
transcripts" recommends `input_audio_transcription=AudioTranscriptionConfig(
language_codes=[])` precisely, and notes VAD filters non-speech out of
transcription entirely (which is also why the run page asks for a
NORMAL-VOICED sentence).

### G.6 — target math (owner's 8-second conversational ceiling)

GATE v2 budget: release→first-audible ≤ 8 s. Targets for the fixed
primary route: primary final ~1–3 s (the docs: the finalized transcript
is "emitted when the speaker pauses, the turn completes, or speech is
finalized" — prompt at `activityEnd`) + reply generation (flash-lite,
~0.5–1.5 s) + first-audio ~2–4 s = 4–8 s total. The 28-second
decomposition is the anti-target: 12 s dead wait (G.4 kills it) + 7 s
fallback transcription (G.3 removes the need) + 9 s reply+TTS.

**Streaming playback evaluation** (measure/design this round, implement
if contained — else name the WP1 item with numbers): NOT contained. The
native-audio path (`generate_voice`) returns ONE pcm blob per request
and playback begins after `write_wav` completes, so "playing the first
PCM chunks while synthesis continues" is not a player change — it needs
chunked/streamed generation from the voice model (a model-path
rewrite). The 9 s reply+TTS leg must still shrink to 2–4 s first-audio
to fit GATE v2; the scene-6 `latency.table` will split it into
reply→synth (model reply) and synth→audible (voice generation + spawn)
before any rewrite is designed. **Named WP1 item: streamed first-audio
(chunked voice generation + playback of the first chunk), to be sized
from the scene-6 table.**

## DEFECTS FOUND

- [HW-PROVEN] **Primary route hears but never speaks the words**: model
  VAD tracks speech on the wire, yet zero transcript-family messages in
  both scene-5 sessions. The three named setup deviations (G.1) are now
  fixed (G.3); scene 6 re-measures. If the histogram still shows zero
  transcript-family counts, the remaining fork is server-side/model-side
  and the payload samples carry it to the model page as a bug report.
- [HW-PROVEN] **The 28-second turn** (12 + 7 + 9) — the merge hold.
  G.4 bounds the first leg, G.3 removes the second's cause, G.6
  measures the third. GATE v2 (≤ 8 s, primary final, conversational
  ear) is the standing gate; PR #23 stays OPEN under owner hold.
- [TESTED-ONLY] The setup-complete hole in the SDK path (proceeds on a
  missing setup) — guarded with one retry now; live behavior unproven
  until scene 6.
- [UNVERIFIED] The 1.4 GB daemon peak (stream F watch item) unchanged;
  WP1 still owns the profiled run.

## NEXT GATE

**GATE v2 (owner 2026-10-27) — PR #23 merge stays held until all three:**
the previous chain (full chain, first user-turn, spoken reply) AND the
final from the PRIMARY route (`final.received` — the fallback path is a
degraded mode, never a gate-passer) AND release→first-audible ≤ 8 s
AND the owner's ear calls it conversational. Scene 6 is the run: the
run page is HANDOFF §7 (EARS and TERMINAL strictly separated; no
physical action inside a paste-able block). Expected dump: `final.received`
from the primary route, transcript-family counts in `ws.histogram`
(samples show the payloads), the `latency.table` legs under budget —
then EARS: her exact words and the conversational verdict. The
double-stop proof closes the run (release WIN first, then F2:
`stop.requested` + `stop.noop`, one reply only). §5 order after the
gate: WP1→WP2→WP4→WP5→WP3 (jump if rpm hyprland ≥ 0.57)→WP6.

## OPEN QUESTIONS

- Does the fixed setup make `gemini-3.5-transcribe-live` speak the
  transcript? (Scene 6's histogram decides; the samples are now
  payload-level, so either fork leaves evidence.)
- Where does the 9-second reply+TTS leg actually go — reply→synth or
  synth→audible? The scene-6 table answers; streamed first-audio gets
  its numbers from that split.
- Kept-audio manifest (HANDOFF §4): 4 unresolved wavs still owe
  transcribe+answer or an explicit never-retried mark (WP5's consumer);
  191330 resolved as `<noise>`, 064450 resolved (replied).
- The conversational verdict is the owner's ear alone — no sensor
  replaces it.
