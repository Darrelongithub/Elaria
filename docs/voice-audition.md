# Elaria voice — selected

As of 2026-10-20 Elaria's **only spoken voice is Gemini native audio,
`[gemini] voice = "Flare"`**, online, and **offline mode speaks not at all** (text
on Waybar / overlay / notification / log). The old rule — one locally owned voice
in every mode, Gemini supplying text only, no native Gemini audio routed anywhere
— is **deferred, not cancelled**: it is the endgame, and the single config switch
that restores it is `[tts] online_voice = "local"`.

Flare and Vega in `humour.toml` were **trait references** (brisk, bite, dry, edge
— never kind-polished). Flare is now literally her voice, which is exactly why the
endgame is an owned local model: a voice the owner cannot keep must not be final.

## Selected voice

> **STATUS: DORMANT — NOT A SPOKEN FALLBACK (owner decisions 2026-10-20).** Two
> things changed, in order. First, the owner set **Gemini native audio,
> `[gemini] voice = "Flare"`, as Elaria's online speaking voice**, effective
> immediately and without further audition. Then they amended it: **offline mode
> has no voice output at all** — replies are text on the Waybar, overlay,
> notification and log surfaces. This Piper voice therefore stays wired but
> **silent in normal operation**: it is not the offline voice and it is not the
> fallback for a cloud failure (a failed or unavailable cloud voice is *reported*
> silence — `muted: true` plus a reason in `assist voice status`).
>
> The one-voice rule is **deferred, not cancelled**: the endgame is still one
> locally owned voice in every mode, adopted in a single switch
> (`[tts] online_voice = "local"`, or `offline_voice = "local"` to bring back
> offline speech only). Round 3/4 measurements below are kept as the record of
> *why* the local path was never blessed as canonical, and they are explicitly
> closed work: the owner directed that no further time be spent improving it.
> Do not build Hyprland binds or live-Gemini routing on the assumption that this
> voice speaks.

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

- **Flare online, nothing offline.** Gemini native audio is the only voice and
  it speaks only while online; offline there is no speech at all. This *replaces*
  the old rule "Elaria does not suddenly acquire a Gemini voice" — the owner
  overrode that rule for online speech on 2026-10-20 while deferring (not
  cancelling) it. The surviving half: nothing routes speech to a *second* cloud
  voice, and the dormant local voice is never used to paper over a cloud failure.
- **Silence is reported, never implied.** An unavailable or failing cloud voice
  returns `muted=True` with the reason in `status()["reason"]` / the doctor row.
- **No time-stretching** on the dormant path. Pace comes only from Piper's native
  `--length-scale` (`0.92`: slightly faster than neutral).
- The standard permission-neutral acks — “On it.”, “That is done.”,
  “Is that everything?”, “No. Not at this hour.” — stay one cached file lookup
  (`§18`), warmed off the hotkey path. Online that file is Flare audio; offline
  there is no file to play, so the ack is silent text on the normal surfaces.
