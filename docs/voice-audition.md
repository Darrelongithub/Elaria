# Elaria voice audition — Phase 8 shortlist

Elaria has **one speaking voice in every mode**. Gemini supplies text
(reasoning/transcription); it never supplies her voice. Gemini Live in this
codebase is text-only, and native Gemini audio output is not routed anywhere.

Flare and Vega in `humour.toml` are **trait references only**: brisk, bite,
dry, edge — never kind-polished. The runtime voice must be locally owned so it
is identical online and offline.

## Candidates to judge

These are real Piper voices. The links are the official Piper sample MP3s.
All three read the same neutral sentence about rainbows, which is useful for
timbre and pacing but not for judging how each handles Elaria's clipped acks.

| Candidate | Why it is on the shortlist | Official sample |
|---|---|---|
| `en_GB-jenny_dioco-medium` | First listen. British medium voice; most plausible route to dry understatement rather than bright US assistant polish. | [speaker_0.mp3](https://github.com/rhasspy/piper-samples/blob/master/samples/en/en_GB/jenny_dioco/medium/speaker_0.mp3) |
| `en_US-lessac-medium` | The direct medium-quality baseline: likely brisk and intelligible without sounding overly theatrical. | [speaker_0.mp3](https://github.com/rhasspy/piper-samples/blob/master/samples/en/en_US/lessac/medium/speaker_0.mp3) |
| `en_US-kathleen-low` | Flatter, lower-fidelity delivery. The roughness may give her edge, or may simply sound cheap — the owner's ears decide. | [speaker_0.mp3](https://github.com/rhasspy/piper-samples/blob/master/samples/en/en_US/kathleen/low/speaker_0.mp3) |

No winner has been picked: the shipped config deliberately starts as
`voice_id = "unselected"`, so Elaria stays text-only rather than acquiring a
voice nobody auditioned. The owner listens, then selects.

## Exact-script audition on the Fedora box

The build sandbox could retrieve the official sample MP3s, but Piper model
downloads redirect to storage hosts blocked from that environment, so it
could not honestly generate the exact-script WAVs there. On the target
machine:

```bash
uv sync --extra offline --extra tts
mkdir -p ~/.local/share/piper
```

Download each candidate's `.onnx` and `.onnx.json` pair from the canonical
Piper voices repository on Hugging Face into the voices directory. The file
names must be exactly:

```text
en_GB-jenny_dioco-medium.onnx
en_GB-jenny_dioco-medium.onnx.json
en_US-lessac-medium.onnx
en_US-lessac-medium.onnx.json
en_US-kathleen-low.onnx
en_US-kathleen-low.onnx.json
```

Then generate the audition set:

```bash
assist voice audition
```

This writes WAVs plus `manifest.json` under
`~/.local/share/assistant/voice-auditions/`; audio stays out of git. The
default script is deliberately in-register:

> On it. Done. Is that all? No. Not at this hour. Sasa, the March invoice is
> filed. The six ambiguous ones are parked, not guessed at.

Pick and warm the ack cache:

```bash
assist voice select en_GB-jenny_dioco-medium   # or whichever wins
assist voice warm
assist voice status
```

The selection persists outside the repo. After selection, online and offline
spoken replies both report the same `backend`, `voice`, `model`, and native
`length_scale` in their speech metadata.

## Non-negotiables

- **No time-stretching.** Pace comes only from Piper's native
  `--length-scale` (`0.92` by default: slightly faster than neutral).
- **No cloud voice fallback.** If Piper is unavailable, speech reports an
  error/deferred result; Elaria does not suddenly acquire a Gemini voice.
- The standard permission-neutral acks — “On it.”, “Done.”, “Is that all?”,
  “No. Not at this hour.” — are pre-rendered into the local cache so playback
  is a file lookup, not synthesis on the hotkey path.
