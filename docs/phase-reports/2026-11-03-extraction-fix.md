# Phase report — transcription extraction fix (2026-11-03)

Lane: mainline · Branch: `arena/c2a7085d-elaria` · Base: `3f48e4f` ·
Commit: `0666200` · Authority: ruling 2 (design chat), released
2026-11-03 on the diagnostic paste. No PR, nothing merged.

## DONE

**The defect, proven on the wire.** The owner-hardware paste
(2026-11-03T11:38:42+03:00, HEAD `be9183c`) is the fix's evidence and is
tagged in the commit message. `response.text` returned `''` while the
same response object carried
`part.audio_transcription.text = 'The quick brown fox jumps over the
lazy dog.'` (44 chars). Root cause, established earlier from the
installed SDK: `GenerateContentResponse._get_text()` concatenates
`part.text` of TEXT parts only and returns None when none exist
(`types.py`), while transcription models answer in
`Part.audio_transcription` (`types.py:2368`).

**The fix** [TESTED-ONLY, 18 pins]:

- `gemini_client.extract_transcript(response)` → `(text, language_code,
  part_types_seen)`: reads `part.text` and
  `part.audio_transcription.text`, joins in part order, candidate[0]
  only; no candidates/parts at all falls back to the response-level
  `text`, recorded as the token `response.text` (the meeting path's
  text-only responses, and the SDK's own fallback semantics, preserved);
  parts present never mask an empty read.
- Called at `_sdk_transcribe` (production file leg) and
  `transcribe_batch_async` (meeting path). The chat transport is
  untouched (text parts, unaffected). The probe's raw pass shares the
  helper, so instrument and production cannot diverge again.
- **(a) collision visibility**: a part carrying both readable fields is
  read once (`audio_transcription.text` wins) and the collision always
  rides `part_types_seen` as `text+audio_transcription` — recorded, not
  a silent precedence rule. Pinned.
- **(b) amended for the hardware's None**: `language_code` returns raw.
  None = "the model declared nothing" — a third state: `Transcript.
  language` takes the configured value, `Transcript.model_language`
  carries the absence, so nothing is silently reconciled. A populated
  value that differs feeds `Transcript.language` and the existing BH-K19
  walk marks `language_ok=False` with both values emitted. Pinned.
- **(c) candidate[0] only.** Pinned.
- **`finished` is not load-bearing** (it returned None on the complete
  transcript). Nothing gates on it; no completeness signal was invented,
  because the populated fields are the only evidence and deriving
  "complete" from them would be a guess dressed as a check.
- Probe `reading:` line corrected: it no longer calls an unread answer a
  stump. It separates `STOP + empty raw text + NO non-text parts`
  (nothing transcribable) from `STOP + empty raw text + `
  `audio_transcription parts` (the answer is in the part).

**Gates.** `uv run --no-sync pytest -q` → **2,019 passed, 6 skipped**
(baseline 2,001/6, +18). `ruff check .` → **All checks passed!**.
Regression sweep over the touched seams (probe, resilience, stream-H,
bug6/6d/6e/6f, local-ASR, registry, stump, meeting-stop) → 109+26 green.
Local runner only; no CI claimed.

## DEFECTS FOUND

- **[TESTED-ONLY] The 0.85 question, answered from code, and the answer
  is NO.** The fix makes the Gemini leg return the correct transcript,
  but it **cannot execute a command**. Three independent reasons, all in
  the tree: (1) `GeminiBatchBackend.transcribe` constructs `Transcript`
  without a `confidence`, so it is `None`; (2) the schema offers none —
  `Part.audio_transcription` (`Transcription`) has text/finished/
  language/words/offsets and `WordInfo` has only word/offsets, **no
  confidence field anywhere**; (3) the command gate
  (`daemon._command_gate`) vetoes unknown-confidence **mutating**
  intents. Meanwhile a *perfect* local transcript scores 0.6953
  (synthetic speech) — below 0.85 — so the local leg cannot clear the
  floor either. **What would have to change** (owner's call, not mine to
  pick): either a confidence source for the Gemini leg (none exists in
  the response schema, so it would have to be derived and justified, not
  invented), or a per-backend threshold policy where a verbatim
  transcription model with a clean parse is treated as verified by a
  different signal than whisper's log-probability. Until one of those
  lands, voice commands are blocked by the confidence gate on clean
  audio, and by capture on the owner's actual microphone.
- **[TESTED-ONLY] Arm C is not a discriminator** — design chat withdrew
  it on the paste (its registry files model resolves to the same
  `gemini-3.5-transcribe` as production). Recorded so no future
  invocation is spent on it.
- **[UNVERIFIED] Hardware confirmation pending**: S2's clean-audio run
  is the proof that production returns the 44 characters. The suite
  proves the reading, not the wire.

## NEXT GATE

Owner runs the clean-capture S1 re-run (probe sections 1/3, one paced
leg call) once capture is in range: section 3 must now show
`backend=gemini_batch` with the full text instead of falling through to
local. That closes the hold's named release path. Then S2 (ears,
clause-3 re-measure candidate, three measurements) when the mic reads
in-range.

## OPEN QUESTIONS

- **Threshold policy** (above): the owner/design chat must choose between
  a derived Gemini confidence and a per-backend verification policy. This
  is the last thing between a correct transcript and her being able to
  take a command.
- **Scope ratification**: `src/assistant/asr.py` was touched for ruling
  (b)'s data flow — `Transcript.model_language` (one field),
  `GeminiBatchBackend.transcribe`/`transcribe_async` constructions (the
  only places `Transcript.language` is fed; nothing else in the file
  reads it). Ruling 2 named `gemini_client.py`, the probe and tests;
  this is a 2-hunk consequence of the ruled language flow. Flagged for
  ratification, not asserted as granted.
- The capture fault remains separate, real and unaddressed here by
  instruction.
