# Phase report — stream H: scene-6 verdict, H.1 trace, H.2–H.5 (2026-10-27)

WP1 round 2. Scene 6 ran (owner hardware, 08:51–08:53, sessions
c9665bed27fc + 27c8ea99e82c) and the verdict is three words long:
**wire healthy, model silent** — plus one regression candidate. Gate v2
stays red/on hold. Commits: `8a72939` (sensors + both-path pins) →
[this commit] (H.3 repro + docs). Suite **1,925 passed / 6 skipped**,
ruff clean. $0 — the sandbox ran fakes only; H.3 spends at most two
short housekeeping Live sessions when the owner runs it.

## DONE

- **Scene-6 verdict recorded (§4 + §5.9):** `transcript_family=0
  commits=0` in BOTH cycles — zero transcript messages on the wire,
  **not missed deltas** (the G.7 shape sensors did exactly their job:
  `commits=0` proves nothing was assembled wrongly, because nothing
  arrived). Everything we control exonerated by its own sensors:
  `setup=ok retries=0`; server VAD timestamps match `audio.sent` bytes
  exactly (3.900 s ↔ 124,800 B = 124,800/2/16000 s ✓; 6.810 s ↔
  217,920 B ✓); adaptive abandon worked (3.5 s cut, not the 12 s
  budget); first real `latency.table` rows (release_to_final
  3.575/3.828 s, `missing=reply,synth,audible`).

- **H.1 — the fallback-regression trace + both-path pins** [TESTED-ONLY]:
  traced the post-timeout path for BOTH timeout kinds. They are ONE
  path: `TimeoutError` (from `_wait_final_adaptive` — "adaptive
  abandon…" or "budget expired…" as its message) →
  `live_terminal_missing` → the BH-K3 gate → `needs_fallback = (not
  final_text or tail_unconfirmed) and not no_speech` → the
  `asr.transcribe_file` leg. **The leg FIRES after an adaptive
  abandon** — four scenario pins prove it on unmodified behavior:
  budget→fallback→landed; abandon→fallback→landed (with the
  "adaptive abandon" reason asserted); abandon→fallback-empty→
  `transcription.deferred` with the wav kept; budget→fallback-empty→
  deferred. The system has NOT regressed at code level; what changed
  between scene 5 and scene 6 is the leg's OUTCOME, which nothing was
  recording. So the fix that landed is visibility, and it is total:
  `post_timeout_route` (schema: route=fallback|deferred, reason=the
  timeout kind) and `fallback.outcome` (schema: landed/empty/error with
  char counts) are now journal lines — "attempt vs no attempt" is
  never an inference again. **Contradiction surfaced to the owner per
  the standing rule:** the scene-6 "no fallback attempt" reading is
  consistent with the attempt living only in persona lifecycle rows
  (`dictate.saved_wav_fallback_start`), which the schema journal never
  carried; if those rows are ALSO absent, the code that ran was not
  this branch. Scene 7's `fallback.outcome` line answers in one read.

- **H.2 — wire sampling completeness** [TESTED-ONLY]: the two generic
  `"message"` payloads per session are the per-response TOTAL counter
  (`self._wire_counts["message"] += 1` counts every message), not an
  unidentified type — which is exactly why `samples=` showed only
  `voice_activity` while `types=` looked like it held a mystery type.
  Now every counted type appears in samples (text-only, ≤200 chars,
  never audio bytes): each message sample names its populated
  fields/subtypes (`message: voice_activity`), and a response with no
  populated field — the genuinely unnamed model notice/error shape —
  gets its own type `message.(no-populated-fields)` with its key
  names. The F-era sample-count pin updated (3 per type incl.
  "message").

- **H.4 — capture-lifecycle sensors** [TESTED-ONLY]: press→first-frame
  latency (`first_frame_latency_ms`, aggregate), first-non-silent-frame
  offset in the kept wav (`first_speech_frame_s`, aggregate only — HDA
  DSP power-up clipping is the suspect; ACTIVITY_START 0s stays
  ambiguous by design), `stream.closed` schema event at session close,
  and the mic-release probe (`capture.node_state`: PipeWire node state
  ~5 s after close via pw-cli/pactl, best-effort; `suspended/idle` =
  released, `running` = the in-use indicator was telling the truth).
  Numbers arrive with scene 7 (step 6). Not fixed anything — the
  owner's "takes a minute" impression gets measured against the ms
  first. The probe runs detached (`_probe_tasks`, cancelled in
  `aclose`) so ack-waiter bookkeeping never swallows it.

- **H.3 — the decisive repro, written for the owner to run** (`scripts/live_repro.py`):
  standalone outside the daemon (google-genai only — our parser is not
  imported), the transcribe docs' Manual-VAD setup VERBATIM (fetched
  2026-10-27: `response_modalities=["TEXT"]`, AAD disabled,
  `input_audio_transcription=AudioTranscriptionConfig()`; flow
  `activity_start` → `audio/pcm;rate=16000` 100 ms chunks →
  `activity_end`), streaming the proven wav
  (`audio/20261027-064450-77cc4e.wav`) with every raw message printed
  unfiltered. ARM A = `gemini-3.5-transcribe-live` (our pin); ARM B =
  `gemini-3.8-live` (the docs' example conversational model —
  get-started-sdk/capabilities/AI-Studio quickstart all name it — with
  the same config, i.e. the input_audio_transcription side-channel).
  The ruling tree is in the script header and §7 steps 3–4.

- **H.5 — design options sized, NO implementation** (below, DEFECTS
  FOUND carries the caveat list; the numbers are the ruling material).

## DEFECTS FOUND

- [UNVERIFIED — the regression question] Scene 5's fallback leg landed
  text (`transcription.landed` + spoken reply); scene 6's produced
  `transcription.deferred` with the reply legs missing. The route is
  pinned identical — so the difference is the leg's outcome (empty /
  error / the 5 s `FALLBACK_TIMEOUT_S` racing a ~7 s cold call?) or
  account-level gating (unknown #5). `fallback.outcome` now names it;
  H.3 disambiguates from outside our stack.
- [UNVERIFIED] `gemini-3.5-transcribe-live` never produced a transcript
  message in either cycle while the wire carried proven speech — model
  silence with healthy setup. Unknown #5 (account/model gating) is the
  leading suspect and ARM A/B of H.3 separate it from a stack defect.
- [TESTED-ONLY, pinned residual] G.7's join rules still space-join
  sub-word deltas without whitespace; irrelevant until the wire shows
  deltas at all (scene 6: `commits=0`, no parts).
- [TESTED-ONLY] `final_wait_note` was flush-local; the H.1 route line
  reads it at the gate and the offline path skips the flush block —
  fixed (initialized at dictate entry) and keyed.
- [UNVERIFIED] The 1.4 GB daemon peak (stream-F watch item) unchanged;
  the WP1 profiled run takes it plus the G.7.5 queue notes.

## NEXT GATE

Scene 7 (HANDOFF §7) — the run page is rewritten and the **double-stop
proof is its FIRST physical step** (missed in scenes 5 and 6; release
WIN first, then F2; expect `stop.requested` + `stop.noop`, one reply).
Then the H.3 arms, then one natural cycle under the stream-H sensors
(step 6 names every line to quote). GATE v2 stands (red/on hold):
previous chain + `final.received` from the PRIMARY route + release→
first-audible ≤ 8 s + the owner's ear. Scene 7 feeds the H.5 ruling;
the 8 s bar stands unless the owner re-rules with the numbers below in
hand. §5 order after the gate:
WP1→WP2→WP4→WP5→WP3 (jump if rpm hyprland ≥ 0.57)→WP6.

## H.5 — the three options, sized (ruling material, nothing built)

Measured legs (journal evidence, tags: scene stamps are [HW-PROVEN],
decompositions are estimates from those stamps): scene 5 = 28 s
release→synth = ~12 s dead wait + ~7 s file-fallback + ~9 s reply/TTS;
scene 6 = 3.575/3.828 s release→wait-end (adaptive abandon), no reply.
G.6 target math: primary final ~1–3 s + reply ~0.5–1.5 s + first audio
~2–4 s = 4–8 s ≤ the 8 s bar.

- **(i) Re-pin PTT transcription to a conversational live model's
  `input_audio_transcription` side-channel** (`gemini-3.8-live`; the
  docs' get-started example reads exactly this field). Latency: the
  same live finalization (~1–3 s at activityEnd) + unchanged reply legs
  → the 4–8 s target math holds unchanged. Quota: one live session per
  PTT turn against the conversational-live quota — the quota math is a
  design-chat item and **unknown #5 applies here too**: if H.3's ARM B
  is silent, this option dies with the account.
- **(ii) Fallback-as-primary, optimized:** incremental wav upload
  DURING the hold (frames ride out as they arrive) so the release-time
  file-transcription call starts immediately, plus streamed reply/TTS
  first-audio per the G.7.3 brief (chunked playback queue, ~50 ms /
  2,400 B slices, interrupt <100 ms). Math: file leg ~3–7 s (scene 5
  band; upload overlapped by the hold) + first audio 2–4 s →
  release→audible ≈ 5–11 s, ≤ 8 s in the optimistic band. Survives
  model silence (one batch response is enough) and keeps the deferred
  contract. This is the one that does not depend on unknown #5.
- **(iii) Accept ~19 s degraded replies:** keep the current shape
  (adaptive abandon 3.5 s + file fallback ~3–7 s + reply/TTS ~9 s ≈
  16–19 s) and spend the effort making the fallback leg RELIABLE —
  which may mean revisiting `FALLBACK_TIMEOUT_S = 5.0` if scene 7's
  `fallback.outcome` shows timeout-shaped empties (yesterday's leg
  worked inside it, so no change without that evidence).

## OPEN QUESTIONS

- Does `gemini-3.5-transcribe-live` transcribe outside our stack?
  (H.3 ARM A — the single most valuable number this week.)
- Is the account gating transcribe models? (H.3 ARM B; AI Studio
  entitlement page if both arms are silent.)
- What did scene 6's fallback leg actually return? (The persona rows
  `dictate.saved_wav_fallback_*` from 08:51–08:53 if the owner still
  has them; scene 7's `fallback.outcome` line going forward.)
- VERBATIM punctuation vs the G.7 debounce gap — parked until the wire
  produces transcripts at all.
- H.5 ruling (i)/(ii)/(iii) after scene 7; the 8 s bar stands until
  the owner says otherwise.
