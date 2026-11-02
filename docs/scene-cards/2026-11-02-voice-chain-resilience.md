# Scene card — voice-chain resilience S1/S2/S3 (2026-11-02, window findings order v1)

Status: **builder-drafted, owner runs** — scheduled by design chat, never
self-certified. ≤30 min daylight; both outcomes are decisions. EARS
steps and TERMINAL steps strictly separated (no physical action in a
paste-able block), per the latency card's discipline.

What is under proof: F1 (the local leg decodes again), F2 (the file leg
paces itself under the transcribe model's 3 RPM), F3 (empty-leg
semantics — the chain falls through to local and the journal is legible
when nothing lands). The turn that starved (session 61258b3b343a) must
become a local-whisper answer.

Run on the mainline branch code, daemon restarted on it, after
`uv sync` (the lock now resolves `av 18.1.x` — `uv pip list | grep ^av`
must show < 19).

## S1 — TERMINAL: the file leg lives again (F1 + F3b)

1. `uv run python scripts/file_leg_probe.py` — expect per wav:
   section 3 lands WHOLE SENTENCES with `backend=local` (Gemini may
   still return empty or refuse under 3 RPM — the fall-through carries
   the turn to whisper; a `leg raised: RuntimeError: all ASR backends
   failed — …` line would mean BOTH legs died — that is a red result).
   The `local_asr.degraded` warning must be GONE — no
   `metadata_errors` TypeError anywhere.
2. `assist doctor` — the local-ASR section reads available (not
   "installed but degraded").
3. Paste sections 1/3 (+ 4/5 if run) and the doctor line.

Note on pacing (F2): sections 4/5 are UNPACED diagnostic sends on the
same 3-RPM quota — a `429 … retryDelay …` printed there is the F2
surface itself (paste it; it is evidence, not failure). For a clean call
count, run the probe once and let a minute pass before re-running.

## S2 — EARS, then TERMINAL: one live voice turn (F3 + M-4 chain)

EARS ONLY (no terminal in this block): press and hold, ask something
with a real answer ("what time is it"). Expect: she ANSWERS — with
Google's file tier still suppressing, the answer rides the local
whisper transcript → chat → streamed TTS. Record the ear verdict
(conversational / not). Then release.

TERMINAL (no listening/pressing in this block):

1. `assist events --recent 60 | grep -E "fallback.outcome|transcription.backend|transcription.starvation|latency.table"` —
   the legible sequence: per-backend class-marks → `fallback.outcome`
   → (if nothing landed) `transcription.starvation` with `outcome=…`;
   `latency.table` carries `release_to_first_slice_s` (clause-3
   re-run candidate — measure, do not promise).
2. `grep -E "audio.first_byte|transcription.stump"` — `at=slice` for
   streamed TTS; stump/short marks per M-5 if a stump lands.
3. Any line with `error=` must carry non-empty text (F3a). An empty
   error string anywhere in the paste is a RED result.

## S3 — TERMINAL: quota pacing (F2)

1. Count the file-leg sends in the window (sections 3 / the turn's
   `fallback.outcome` lines) and paste any 429s with their retryDelay.
2. Expect: no more than 3 transcribe-model sends per 60 s FROM THE
   LEG; a 429 drawn by S1's unpaced diagnostic sends (sections 4/5) is
   the F2 evidence surface, not a leg-pacing failure (the S1 note
   applies).
3. Optional owner config line (makes doctor's quota shape show the
   figure; the enforcement already knows it from the registry):

   ```toml
   [quota.models.transcribe-batch]
   rpm = 3
   ```

## Outcomes (both are decisions)

- **GREEN:** S1 whole sentences via `backend=local` with no
  `local_asr.degraded`; S2 she answers and the journal sequence is
  legible with no empty error strings; S3 pacing holds on the leg.
  → the chain survives Google's silence; gate v2-AMENDED clause (ii)
  has its production-path transcripts (whole sentences) and clause 3
  can re-measure.
- **RED:** any named expectation fails — the paste names which fix
  (F1/F2/F3) and which leg. That is the next order's content.
