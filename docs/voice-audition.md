# Elaria voice — selected

Elaria has **one speaking voice in every mode**. Gemini supplies text
(reasoning/transcription); it never supplies her voice. Gemini Live in this
codebase is text-only, and native Gemini audio output is not routed anywhere.

Flare and Vega in `humour.toml` are **trait references only**: brisk, bite,
dry, edge — never kind-polished. The runtime voice is locally owned so it is
identical online and offline.

## Selected voice

> **STATUS: PROVISIONAL — NOT CANONICAL.** Re-auditioned 2026-10-19: the owner
> could not parse this voice in normal playback, and round-3 measurements rank
> it last of four on intelligibility (see
> [`voice-audition-round3.md`](voice-audition-round3.md)). The owner is keeping
> the voice — the job is audibility, not replacement.
>
> The 16 kHz sample rate is a real ceiling (no 8–11 kHz band exists in the
> file), but it is **not** the root cause: the same weight renders the long
> sentences at 76–84 % ASR-recoverable and one-word acks at **0 %**, at every
> pace, with or without silence padding, alone or inside a line, on piper 1.2.0
> and 1.8.0 alike. The failure is short-phrase instability plus high
> take-to-take variance, not missing bandwidth. Round-4 evidence and the
> config-only knobs are in
> [`voice-audition-round3.md`](voice-audition-round3.md) ("Round 4 addendum").
> Do not treat it as final; do not build Hyprland binds or live-Gemini voice
> routing on it until the owner approves the repaired setting.

**`en_GB-southern_english_female-low`** — Piper Southern English Female, low
quality. Chosen by the owner on 2026-10-19 after two audition rounds, on the
theory that the roughness was the point (edge over polish). That trade turned
out to cost intelligibility, not just polish.

Official sample:
[speaker_0.mp3](https://github.com/rhasspy/piper-samples/blob/master/samples/en/en_GB/southern_english_female/low/speaker_0.mp3)

Audition history, for the record:

- Round 1 — `en_GB-jenny_dioco-medium`, `en_US-lessac-medium`,
  `en_US-kathleen-low`: **all rejected**.
- Round 2 — `en_GB-cori-high`, `en_GB-alba-medium`,
  `en_GB-southern_english_female-low`, `en_US-kristin-medium`,
  `en_US-ljspeech-high`: Southern English Female won. The other four stay in
  config as alternates only if exact-script checks ever reopen the question.

## Install the selected voice on the Fedora box

```bash
uv sync --extra offline --extra tts
mkdir -p ~/.local/share/piper
```

Download the selected voice's `.onnx` and `.onnx.json` pair from the canonical
Piper voices repository on Hugging Face into `~/.local/share/piper/`:

```text
en_GB-southern_english_female-low.onnx
en_GB-southern_english_female-low.onnx.json
```

The shipped config already names this voice as the default. On an existing
install whose local config predates the pick, select and warm it explicitly:

```bash
assist voice select en_GB-southern_english_female-low
assist voice warm
assist voice status
```

Then verify the exact-script rendering — the standard acks are the real test,
not the neutral sample sentence:

```bash
assist voice say "On it. Done. Is that all? No. Not at this hour."
```

`assist voice audition` can still render the alternate candidates with the
in-register script:

> On it. Done. Is that all? No. Not at this hour. Sasa, the March invoice is
> filed. The six ambiguous ones are parked, not guessed at.

Audition WAVs land under `~/.local/share/assistant/voice-auditions/`; model
files and generated audio stay out of git.

## Non-negotiables

- **No time-stretching.** Pace comes only from Piper's native
  `--length-scale` (`0.92` by default: slightly faster than neutral).
- **No cloud voice fallback.** If Piper or the selected model is unavailable,
  speech reports an error/deferred result; Elaria does not suddenly acquire a
  Gemini voice.
- The standard permission-neutral acks — “On it.”, “Done.”, “Is that all?”,
  “No. Not at this hour.” — are pre-rendered into the local cache so playback
  is a file lookup, not synthesis on the hotkey path.
