# Ask 40 — console voice observation contract v1

**Status: consumer interface REQUEST, not an implemented/published daemon API.** Mainline owns
producer/fidelity work. The console lane owns this requested wire contract and the future consumer.
No voice capability may be advertised merely because this document or its examples exist.

## 0. Authority, source receipts and scope

Read in full through Drive (untruncated), metadata verified against the owner's supplied pins:

| Source | Current Drive ID | Bytes | Drive-reported SHA256 |
|---|---|---:|---|
| CONSOLE-VOICE-SURFACE.md | `1X20t1J_Bm8Vng7C14dM1dvXBNUI-ER--` | 16759 | `d1cb1610044b55ac834dff04d05c3e056b4623ceef31ad2fdca43cfd00e659c7` |
| OWNER-RULINGS-2026-11-17.md | `1XtuVDo3OZ7GirNRABp5-Q8jGa691GC2R` | 4990 | `a72916d0a5e1167707655ba5ba91f81e2f23a0d21b3c4aa8e18d4d2e366634ab` |

These are checks of Drive metadata plus complete extracted-text reads, not a claim of hashing a
locally downloaded raw blob. The trashed superseded copy was not fetched. Part 2 overrides Part 1.
The earlier preflight's pending-egress/scope questions are superseded by these rulings; it remains
historical, not silently rewritten.

- Browser/console captures/uploads **no audio**, ever; no browser playback or daemon-down fallback.
  Daemon microphone PCM may leave the machine under its existing authorized policy. Cloud synthesis
  stays; no Piper switch and no producer edits on egress grounds.
- Intended reply text never supplies the speech transcript. Generated, playing, delivered, muted
  and failed remain distinct. Consent asks never enter speech.
- Producer changes belong to mainline: fidelity/cache, capture levels, lifecycle events. `capture.py`
  is not protected (F18); `transcribe.py`/`live_client.py` remain protected. Any event-transport mount
  in `daemon.py` is separate and separately regression-pinned; the hands eight-line mount is not
  widened. This request is not permission for this lane to edit any of those files.
- No daemon WebSocket, second assistant, model call, microphone PCM, audio URL, file handle/path or
  audio element goes to the renderer. Existing same-owner authenticated Unix IPC is the boundary;
  the bridge forwards only schema-validated metadata/text on its existing authenticated wire.

Audit basis: immutable mainline `9e4991583e8659703cda2df0eac9f4c59fd1c740`, read-only, not an assertion
about a moving tip or the resident owner process. Consumer baseline `a26dbdc`. Existing real
producer `message_id`/`user_message_id`/receipts are consumed, not replaced by latest-row guesses.

## 1. What is present, and what mainline must publish

| Required indication | Proposed event(s) | Evidence at audited producer | Missing work / no consumer substitution |
|---|---|---|---|
| Capture-open acknowledgement | `voice.capture` | `session.started`, `status.changed`, PTT results exist | Actual device-open/close acknowledgement with capture ID and revision; start request/session startup is not device-open |
| VAD state | `voice.vad` | VAD used internally | Continuous scoped VAD observation, measured RMS, actual threshold, enabled/unknown state; no guessed speech from typed text |
| Live raw/processed levels | `voice.levels` | `capture.stats`; final `capture.levels` log at transcribe.py:1683 | Live same-window pre/post-limiter feed from capture path; the aggregate after a take is not this event |
| Thinking / generation | `voice.generation` | `_ask`, `conversation.message`, timeout and message IDs exist | Accepted turn identity + bounded generation start/terminal lifecycle, linked to exact message writes |
| Generated transcript / playing / delivered / muted / failed | `voice.transcript`, `voice.fidelity`, `voice.playback` | TTS logs/results, player marks, speech.error; adapter requests output transcription | Retained reply-synthesis transcription; content-bound cache receipt; verified player progress/completion and causal linkage. Existing capture-side `live.output_transcript` is **not** the reply-synthesis transcript |
| Error / unknown | `voice.error`, `voice.snapshot`, `voice.heartbeat` | Generic error, no-signal/capture statistics and speech.error exist | Structured safe reason codes, fault lifecycle and authoritative resync; don't regex arbitrary log strings |

**All proposed names below require mainline publication.** Existing similarly named events are not
implicitly compatible. In particular, transcription transport output events cannot be substituted
for speech synthesis output just because both contain the word “output”.

## 2. Transport and common envelope

Proposed read-only IPC subscription: `voice.observe`, parameters:
`{"contract":"elaria.voice-observation/1","resume":null}` on first connect, or a cursor
`{"daemon_epoch":"…","seq":42}` on reconnect. A mainline-chosen equivalent method is acceptable
only through an explicit contract revision; the bridge must not probe arbitrary methods as fallback.

Same-owner SO_PEERCRED checks and private socket permissions apply as in the existing bridge.
Authentication is not permission to execute arbitrary IPC: only observation, the specific control
method below and existing whitelisted methods are forwarded. Observation subscription itself never
opens capture, starts playback, or executes hands. Consumer sends no microphone bytes or cloud keys.

Every event has exactly these envelope fields (JSON objects, not log strings):

| Field | Type / requirement |
|---|---|
| `contract` | constant `elaria.voice-observation/1` |
| `event` | one event name defined below |
| `daemon_epoch` | opaque nonempty daemon-instance ID; changes on daemon restart |
| `seq` | positive integer, strictly increasing for durable lifecycle/sample events in that epoch; null for snapshot/heartbeat transport frames |
| `event_id` | stable `daemon_epoch:seq` identity, same on replay; null for snapshot/heartbeat transport frames |
| `emitted_monotonic_ns` | nonnegative integer from producer clock; ordering uses sequence, not wall time |
| `wall_time` | UTC RFC3339 timestamp for attribution only |
| `replayed` | boolean; historical events cannot animate live recording/playback |
| `context` | object described below |
| `data` | event-specific object; unknown extra data fields are rejected, never forwarded wholesale |

`context` always names `request_id`, `capture_id`, `turn_id`, `utterance_id`, `conversation_id`,
`user_message_id`, `assistant_message_id`, and `origin`. IDs are opaque strings (message/conversation
IDs may instead be producer's nonnegative integer IDs); absent/not-yet-created IDs are explicit null,
never invented IDs. `origin` is `voice`, `console`, `system` or `unknown`, derived by the producer from
the registered ingress. No client-supplied channel claim becomes attribution. Once assigned, IDs
never change for that operation. Assistant row IDs appear once persistence has happened; return and
journal events carry those exact IDs, not a later history sample.

Scope rules: capture/VAD/input-level events require capture_id. Generation requires turn_id and the
accepted request identity; utterance events additionally require utterance_id and turn_id. An output
utterance may inherit its originating capture_id after capture closes; that does not reopen capture.
System cues use a separately identified origin/kind, never impersonate a reply. Consent kinds are
text-only and cannot get a synthesis/playback event. Global errors/snapshots may have null scope.

Limits requested: event frame at most 65,536 UTF-8 bytes, transcript revision at most 8,192 UTF-8
bytes; no silent truncation. Oversize becomes a structured unavailable/error indication, not a
shortened “faithful” transcript. A larger/chunked text contract needs an agreed revision. All
numbers must be finite; no NaN/Infinity. Strings rendered with textContent, not HTML/commands.
Bounds/unknown required versions fail closed; a truncated/error report is not a completed turn.

## 3. Authoritative snapshots, liveness and replay

First `voice.observe` response must be an **atomic snapshot + event-stream watermark**. There is no
read-snapshot-then-subscribe race. Proposed `voice.snapshot.data`:

- `capabilities`: schema version, producer source revision, `fidelity_ready`,
  `cache_content_validation`, `capture_ack`, `live_input_levels`, `vad_events`, `player_events`,
  `atomic_controls`, and numeric bounds/rates. Each feature is true/false/unknown with safe reason.
- `control_revision`: monotonic revision for capture/control state; level samples don't increment it.
- `capture`: state, capture_id, device_open, observed VAD state, latest level sample or null.
- `generations`: bounded list of active turn IDs/states and exact message IDs.
- `utterances`: bounded list of current/recent utterance lifecycle records, fidelity/transcript
  references, replay classification and player state; omitted count is explicit.
- `faults`: active structured faults, and redaction/withheld status for private text.
- `watermark_seq`: sequence through which the snapshot fully accounts for state.
- `reset`: boolean with reason (`initial`, `epoch_changed`, `cursor_expired`, `gap`, etc.).

Snapshot/heartbeat frames are out-of-band, not durable events: their `seq`/`event_id` are null,
`replayed=false`, and their payload carries `watermark_seq`. They do not consume or skip stream
sequence numbers. The subscription has one ordered owner-scoped event sequence; privacy withholding
redacts a payload in-place with an explicit reason, rather than silently dropping its sequence.
The initial snapshot establishes the cursor; a resume may include historical replay through its
watermark, followed by a snapshot fence. Only subsequent live events may animate.

Lifecycle events are never silently dropped. Producer coalesces level samples **before** assigning
published sequence numbers; a published sequence gap requires resync. Per-subscriber overflow emits
a reset if possible and closes/requires snapshot; it never discards capture-close behind a graph.
Heartbeat requested every 1 second (`voice.heartbeat.data` contains `control_revision` and
`watermark_seq`, both nonnegative integers). After 3 seconds
without valid heartbeat/event, the consumer marks connection/state **unknown/disconnected**, zeros
animation, disables state-dependent controls and clears any recording claim. It does not falsely
claim the actual device closed. Producer readiness is a separate fact from socket connectivity.

A known cursor yields bounded replay then a snapshot fence before live animation resumes; an
expired cursor yields explicit reset, not a partial history passed off as complete. Replayed capture
or playing events never reanimate. A new epoch clears previous active IDs; late prior-epoch frames
are rejected. Duplicate events are idempotent. Same event_id with different immutable content is a
protocol fault; the transport's `replayed` flag is excluded from that comparison, but original
emission timestamps, context and data stay identical. Observations may be replayed; commands are
never auto-replayed after uncertain delivery.

No browser-vs-daemon monotonic-clock subtraction: bridge calculates sample age on the same host
clock domain, or uses producer-computed age plus local elapsed time. The renderer uses receive-age
and supplied age, not UTC clock guesses. Samples older than 500 ms are stale and cannot animate;
a still-open capture can be labelled “mic open; levels unavailable” without pretending to hear.

## 4. Event payloads and guarantees

### 4.1 `voice.capture` — actual capture, not intent

`state`: `opening | open | closing | closed | refused | failed | unknown`;
`device_open`: true/false/null; `control_revision`: integer; `reason_code`: bounded enum or null;
`device_id`: opaque local identifier, not an unrestricted path; `mode`: conversation/command/etc.

OPEN must follow successful device acquisition by the actual capture owner. Requested/opening is not
open. CLOSED follows release/confirmed closure. A crash without confirmation is UNKNOWN. Failed
acquisition never publishes OPEN. The terminal event and snapshot agree. Captures get fresh IDs;
a late terminal event for A cannot close new capture B. No automatic capture start on observation.

### 4.2 `voice.vad` — evidence about the same open capture

`state`: `speech | silence | disabled | unknown`; `rms`: nonnegative finite number or null;
`threshold`: actual nonnegative configured value; `window_samples`, `sample_rate_hz`,
`sample_monotonic_ns`; `reason_code` for disabled/unknown. Threshold currently reported as 0.01 is
not a hardcoded promise: send the actual configuration. VAD silence does not mean capture closed.
Input may continue leaving through authorized daemon policy while VAD is silent; never imply a
privacy gate that the producer has not asserted.

### 4.3 `voice.levels` — live measurements, never a fabricated signal

`direction`: `input | output`; `basis`: `captured_pcm | player_consumed_pcm`;
`player_instance_id`: null for input, the exact playback attempt ID for output;
`sample_monotonic_ns`, `window_ms`, `sample_rate_hz`, `channels`, `sample_count`;
`raw_peak`, `processed_peak`, `raw_rms`, `processed_rms`; `limited_samples_window`,
`limited_samples_total`; `limiter`: `{enabled, knee, ceiling, implementation_id}`;
`measurement_stage`: fixed producer identifier; `capture_path`: fixed implementation/path ID,
not owner filesystem content; `gain`: actual gain or null; `measurement_status`: `measured | unknown`.

Request 10 Hz maximum, same PCM window for pre/post values, counters monotonic per capture for
input and per utterance/player attempt for output. `sample_count` and limiter counters count scalar
PCM samples across all channels, not frames; `window_ms` follows frame count/sample rate. Sample
counts make counter contradictions checkable. Input requires confirmed open capture; output requires
that utterance's player-confirmed PLAYING and uses PCM consumed for playback, **not** generated but
unplayed bytes. If that output measurement does not exist, send no output level and report missing
capability; speaking state may still use player lifecycle without invented amplitude.

Raw and processed diagnostics stay separately labelled, unmodified. Values above expected PCM or
limiter bounds remain visible as numeric evidence plus a structured contradiction; never clamp raw
into looking healthy. The orb's normalized visualization is separate from the numeric diagnostic.
Enabled limiter with processed_peak > declared ceiling (beyond declared quantization tolerance),
negative/inconsistent counters, or absent raw/processed pairing produces a fault, not a healthy lamp.
Aggregate final-take statistics must carry `basis=aggregate` in a separately versioned stats event;
they are not valid `voice.levels`. No packet contains PCM, base64 audio or audio URLs.

### 4.4 `voice.generation` — thinking belongs to an accepted turn

`state`: `accepted | started | completed | failed | cancelled`;
`reason_code`; `requested_speech`: boolean; `intended_text_sha256`: full SHA256 or null until known;
`journal_ref`: exact assistant message ID/revision or null before persistence.

`accepted` acknowledges a real accepted request, not a speculative UI click. The producer binds
turn_id before generation starts and preserves it through journal, synthesis and player stages.
`completed` means intended reply generation completed, not speech played. Emit exactly one terminal
result per generation. Typed text, queued/offline text, rejected requests and history replay cannot
create a voice-generation lifecycle by consumer inference. A silent console turn remains speak=False.

### 4.5 `voice.transcript` and `voice.fidelity` — retained output, not intended text

`voice.transcript.data`: `source` constant `speech_output_transcription`; `revision` increasing per
utterance; `text` (the actual retained output transcription); `final` boolean;
`text_sha256` (full hash of exact UTF-8 text); `audio_content_sha256` (null before final content is
known); `provenance` (`fresh_synthesis | validated_cache`); `receipt_id` or null while pending;
`redaction` (`none | withheld`) and a safe reason. Interim revisions **replace** earlier revisions;
they are not concatenated twice. Final text is immutable; subsequent correction needs an explicit
new version/error, never an invisible edit to the prior delivered record. Withheld text is absent,
not a different filler sentence labelled transcript.

`voice.fidelity.data`: `state` (`pending | verified | mismatch | missing | invalid_cache | failed`);
`reason_code`; `requested_text_sha256`, `output_text_sha256`, `audio_content_sha256`;
`voice_id`, `model_id`, `route_id`, `route_settings_sha256`; `verification_method` and
`comparison_policy_id`; `receipt_id`; `cache_hit`; `cache_validation` (`not_applicable | verified |
invalid | legacy_unverified`); `journal_observation_id`.

Mainline must retain output transcription from the SAME speech generation that produced the bytes.
A literal echo of requested text is not output transcription. Existing capture-side transcripts,
intended journal text and results labelled with request text are never acceptable substitutes.
The consumer shows interim/final **generated** text only with its source and pending/fidelity status;
no such text is labelled heard/delivered before a valid player terminal observation. Missing output
transcription shows “transcript unavailable”, not a transcript guessed from the chat response.

Verification requires explicit requested-vs-output comparison. Proposed conservative comparison
policy v1 is Unicode NFC plus whitespace normalization only; retain both raw strings/hashes. No
silent removal of negations, numbers, words, punctuation or case to manufacture a match. Mainline
must publish the exact approved policy and tests; consumer never repairs fidelity by rewriting text.
Mismatch/missing/invalid cache blocks a trusted-delivery claim and is visible immediately. An
observed mismatch stays in the append-only record even if later regeneration succeeds.

**Before first playback:** verified final output transcription and content binding are required for
this fidelity-ready contract. Current streamed playback can send audio before final transcription;
mainline must gate it or publish a separately approved chunk-validation protocol. Simply attaching
an eventual transcript to already-played unverified PCM does not meet this contract. No silent
stream-to-whole-file retry that repeats an already-played prefix. No paid/local-route substitution.

### 4.6 Cache-content receipt (producer-local, sanitized reference over the wire)

A durable receipt binds: full requested text, raw retained output transcription, their full SHA256s,
voice/model/route/settings identity, actual audio content digest, PCM format/frame count, comparison
policy/method/result, source generation ID, schema version and completion status. Keep it private
locally; do not send local audio paths or raw audio to the browser. Publish only needed transcript,
hashes/status/opaque receipt reference, applying existing privacy withholding.

A hit must re-read bounded actual bytes, validate format/completeness, hash them and match the
receipt, compare the complete request/identity and validate the retained transcript under the
approved policy. Both sides must commit coherently. File exists/nonzero, filename/key match, or
`SpeechResult.text=requested_text` is not content evidence. Swapped/wrong/truncated audio, a missing
receipt, interrupted writes and legacy unverified cache entries fail closed; do not auto-promote
old entries to verified. New request gets new utterance ID even when reusing a valid receipt.

A digest binds bytes to a verified generation record, not mathematical proof of phonetic truth.
Model output transcription can err. State the verification method honestly; do not introduce a new
remote retranscription route or cost as an implementation convenience. The owner's ear comparison
remains the hardware test. The consumer contract needs that limitation, not “agrees by construction”.

### 4.7 `voice.playback` — one player and evidence stronger than exit zero

`state`: `generated | playing | delivered | muted | failed | partial | cancelled | unknown`;
`player_instance_id` (null before player acquisition); `receipt_id`; `audio_content_sha256`;
`frames_expected`, `frames_submitted`, `frames_played` (nullable when unobservable);
`sample_rate_hz`; `muted`: true/false/null; `completion_verified`: boolean;
`evidence_kind`: `synthesis_only | sink_started | sink_progress | sink_drained | unavailable`;
`reason_code`; `exit_code`: integer/null (diagnostic, never sole success evidence);
`journal_observation_id` (terminal results persisted before delivery acknowledgement).

GENERATED says valid synthesis/cache content exists, not a player or sound. PLAYING requires
player-owned accepted playback/progress evidence; process spawn alone is insufficient. DELIVERED
requires the same receipt/content, verified fidelity, full completion evidence, no known failure,
and known unmuted state. If the backend only knows exit zero or cannot observe completion/mute,
report UNKNOWN/completed-unverified with reason; do not claim delivery. DELIVERED means the declared
player evidence was met, not that the owner's ears have independently confirmed the words.

Muted/unavailable/failure cannot transition straight to DELIVERED. Interrupted partial audio is
PARTIAL with its evidence, never complete and never automatically replayed. Every playback attempt
has its own player identity; old completions cannot settle a new utterance. Mainline serializes
whole replies and reports competing-owner refusal; the console does not add another player or
hide existing `assist voice say` fallback exceptions. Capture-open and playback state are separate
facts; do not infer microphone closure from the speaking animation.

### 4.8 `voice.error` — structured, attributable, safely bounded

`fault_id`, `code`, `component` (`capture | vad | levels | generation | fidelity | cache | player |
transport | control`), `severity` (`warning | error`), `terminal` boolean, `retryable` boolean,
`safe_message`, `related_event_id`, `resolution` (`active | cleared`). Context IDs scope the fault.
Required codes include `no_signal`, `capture_open_failed`, `capture_closed_unconfirmed`,
`levels_unavailable`, `limiter_contradiction`, `fidelity_mismatch`, `output_transcript_missing`,
`cache_content_invalid`, `player_unavailable`, `player_muted`, `playback_partial`,
`outcome_unknown`, `stale_control_revision`, `protocol_gap`, `unsupported_contract`.

No raw exception text/argv/config/secrets are forwarded. A clear event references the original
fault_id; a later unrelated success doesn't erase it. Retrying effects requires a new deliberate
command; a retryable label is not retry permission. Active failures render through the existing
readout/accessible error treatment because the frozen engine has no native error state.

## 5. Toggle control — authoritative start/stop, idempotency, no duplicated toggle

Proposed owner-authenticated `voice.control` request:
`{contract, request_id, daemon_epoch, expected_control_revision, operation, capture_id}`.
`operation` is `toggle` or explicit `stop` (never arbitrary CLI/argv); capture_id is null when
requesting a start from confirmed closed state, otherwise the observed active capture ID.

Producer atomically validates epoch/revision/current capture, chooses START or STOP, then calls the
same existing daemon PTT implementation. No shell subprocess, copied recorder, model routing or
unlocked read-then-write check in the browser. Response: request_id, accepted/refused/unknown,
chosen_operation, safe reason, new control revision and capture ID if assigned. ACCEPTED is not
capture-open. Concurrent clients on one revision cannot both invert state; the loser gets a stale
revision refusal plus authoritative state. A second deliberate click uses the new revision.

The daemon deduplicates the same request_id/parameters for its epoch; conflicting reused IDs are
refused. Reconnect does NOT resend a toggle. Proposed read-only `voice.control_status(request_id,
daemon_epoch)` resolves uncertain delivery within bounded retention; expired/unknown means resync
and owner decision, not automatic re-execution. Stop races must not close a newer capture ID.
Do not disable the existing emergency stop path because the voice feature is unavailable.

`assist ptt toggle` currently decides start/stop client-side. Mainline must share the atomic decision
for all toggling entrypoints or prove equivalent serialization; a console-only lock does not cover
the chord/CLI. `_ptt_start` returning `already_listening` is not toggle-stop behaviour.

## 6. Consumer mapping and privacy — no production enablement before contract

Existing elements: #orb, #stage, #rs, #rsrc, #rm, #orbnote. Engine states: idle/listening/thinking/
speaking/offline; input/output levels are separate. No new orb is needed. Error uses explicit
accessible readout/indicator, not an unrecognized engine enum. Hands indications are orthogonal;
see the separate hands ruling transition document, not a reuse of listening for action.

- Idle only with live authoritative closed capture, no active generation/player and no unresolved
  active-state uncertainty. Disconnected is offline/unknown, not reassuring idle.
- Capture-open is always independently labelled. Listening/VAD animation follows OPEN + fresh VAD;
  VAD silence leaves “mic open, no speech detected” visible, not “mic closed”.
- Input levels require that capture's OPEN + fresh measured input data. Thinking requires current
  generation lifecycle. Speaking requires current player PLAYING; amplitude alone cannot set it.
- Capture failure, limiter contradiction and fidelity failures retain numeric/reason evidence and
  truthful mic/player indicators even if error presentation has display priority.
- Transcript beside orb uses only retained output transcription, linked to utterance and journal
  observation. Historical snapshots are labelled history, never a newly delivered answer. Ordinary
  typed chat may keep its intended reply, separately labelled; it is not the speech transcript.
- No `useMicrophone`, `getUserMedia`, MediaRecorder, audio-context capture, browser audio playback,
  `attachElement`, `loadAudio`, `playAudio`, `attachStream` or daemon-down fallback may be reachable
  from console controls. Remove/disable the shipped local mic control, not just its event wiring.
  Production `simulate(true)`, text-cadence output levels and textarea input levels must be removed.
  Frozen engine bytes need not change: consumer integration must withhold capture/playback APIs.
- Existing company/privacy withholding still applies to private text. Removing hands action prompts
  is not blanket authorization to show private voice history in public. Withheld is not missing
  transcription and neither can be replaced by intended text. No transcript/audio token persistence
  in browser storage by default. No unrelated daemon events or raw journal dump go to the browser.

## 7. Required executable acceptance pins (mainline then consumer)

**Producer gates:** two distinct reply texts, identical voice/model/route/settings; exact canonical
request → message IDs/journal text → TTS source; retained real transport output transcription;
wrong/different/missing output transcription; full-prefix-different-suffix request; cache-swap,
wrong receipt, wrong identity, corrupted/truncated bytes, legacy cache; mismatch before playback;
stream cancellation/partial delivery; no consent speech; muted/unavailable/exit-zero-only never
DELIVERED; turn/capture/utterance crossings refused. Fake output transcription must independently
supply contrasting words, not echo the request as the oracle. No universal hash-collision claim.

**Wire/consumer gates:** snapshot/subscription race, reconnect/epoch change, gap/duplicate/conflicting
ID, late close vs new capture, stale levels, VAD silence vs closed, premature playing/delivered,
withheld/missing transcript, typed input cannot light recording, no synthetic production levels,
all forbidden browser media calls unreachable, simultaneous toggle clients, uncertain command not
replayed, limits and private error sanitization. Positive transcript = verified output source linked
to the exact stored turn; mismatch is visible and append-only, not silently normalized away.

**Owner hardware:** press → acknowledged capture/listening → measured input → generation → daemon
player → retained output transcript matching what owner hears → confirmed close/idle; muted or
unavailable player yields no console sound; capture closed yields no recording claim. No browser
microphone permission request. Keep build, protocol fixtures, player evidence and owner ears as
separate acceptance labels.

## 8. Mainline handoff checklist / readiness trigger

Publish: immutable producer revision; event/control schemas + samples; fidelity policy/method and
cache receipt format; progress/completion/mute evidence supported by each player; bounded timing
and replay behaviour; the separate event mount diff/regression; producer gate results and explicit
unavailable capabilities. Existing daemon socket permissions and auth must remain intact.

Until that publication passes review, the live button/transcript stay unavailable, not simulated.
The egress ruling is **resolved**; the remaining dependency is the producer, not a new owner hold.
This is a concrete interface request to that lane. No merge, rebase, source repin, daemon edit or
service action is part of publishing it.
