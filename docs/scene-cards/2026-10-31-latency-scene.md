# Scene card proposal — LATENCY SCENE (2026-10-31, mini order M-4, for design chat)

Status: **PROPOSED via design chat — the owner schedules it; never
self-certified.** This is the gate v2-AMENDED clause-3 instrument:
`release → first-audible ≤ 8 s` on the fallback-as-primary chain with
streamed TTS, with the owner's ear as the instrument. The journal's
`latency.table` now carries the **first-audible-at-slice** stage; the
scene reads the table against what the ear hears.

Constraint checklist: ≤30 min daylight; both outcomes are decisions;
EARS steps and TERMINAL steps strictly separated — no physical action
appears in any paste-able block.

## What is under proof

- M-4 streamed TTS (G.7.3(i)): ~50 ms slices (2,400 B @ 24 kHz) to the
  raw player; first-audible at the FIRST slice while the render
  continues; the W6 whale (reply_to_synth 11.77 s on 94129e) must stop
  being unheard time.
- M-4 early dispatch (G.7.3(ii)): chat starts the moment the
  transcription leg lands (the cleanup model call + persist no longer
  sit between final text and reply generation).
- The fallback-as-primary chain end to end (H.5 ruling): release →
  speculative file leg → chat → streamed voice → first slice.
- M-2/M-3 acceptance (owner-run, same session window if convenient):
  probe arm C whole-sentence transcripts on both standing wavs.

## Step 1 — EARS ONLY (no terminal in this block)

Press and hold the talk key (one ordinary turn; say something that
expects a real answer, e.g. "what time is it"). While holding, note:

- the session-open cue at press;
- any silence while the chain works (this is the measured window);
- the FIRST instant her voice becomes audible.

Release, and count nothing — the ear is the instrument; the terminal
reads the numbers after. One more turn if the first felt ambiguous.

## Step 2 — TERMINAL (no listening, no pressing in this block)

1. `assist events --recent 40 | grep latency.table` — one table per
   turn; the streamed turn shows `reply_to_first_slice_s=` and
   `release_to_first_slice_s=` (the target leg).
2. Expected shape (streamed playback):

   `release_to_final_s=…; final_to_reply_s=…; reply_to_audible_s=…;
   first_slice_to_synth_s=…; release_to_first_slice_s=…;
   release_to_audible_s=…`

3. `grep audio.first_byte` — the reply turn's line reads `at=slice`
   (first-audible-at-slice); `grep tts.interrupted` only if halt fired.
4. `grep transcription.stump` — M-5: any landed stump is class-marked
   (`noise_token`/`short_stump`, chars + sha16, never the text).
5. `assist doctor` — the `registry role pins` check (M-3) must read ok;
   if it names `model_transcribe_batch`, fix the config line it names
   and re-run before counting any latency number.

## Outcomes (both are decisions)

- **≤ 8 s `release_to_first_slice_s` and the ear agrees the reply was
  conversational** — gate v2-AMENDED clause 3 GREEN on this hardware
  scene; the fallback-as-primary chain is provisionally merge-ready
  pending the other clauses.
- **> 8 s, or the ear hears a non-conversational gap** — the table
  NAMES the leg that ate it (final wait vs reply dispatch vs
  first-slice). That leg is the next whale; the scene's numbers are the
  order for it. A missing `first_slice` stage (no `at=slice` in
  `audio.first_byte`) means streaming did not engage — the report's
  fallback notes name the three switches to check
  (`stream_playback`, `[tts] player = auto`, player binaries).

## Quota note (M-2's, for the same window)

transcribe-batch free tier = **25 RPD** (config `transcribe_batch_rpd`;
models/batch-25e-06 input tier) vs projected fallback volume: every
silent-primary turn spends one. At scene-6 rates (a handful of turns per
session) the cap is not the constraint; a sustained fallback-as-primary
day is bounded by it — the latency scene should note how many file-leg
calls the window spent.

## Timing budget

Two spoken turns + the terminal greps ≈ 15 min including the M-2 probe
run (`uv run python scripts/file_leg_probe.py` — arm C section 5 shows
whole sentences on both wavs, eyeball-verified).
