# Round 3 — medium/high female voices (measured, not listened to)

Date: 2026-10-19. Incumbent `en_GB-southern_english_female-low` stays
**provisional** — the owner could not parse it, so it is not canonical until a
voice is explicitly approved. Nothing here changes the ONE-VOICE rule: one
local voice, online and offline, no cloud voice, no time-stretching.

## What was actually run

Real Piper, not the mock backend. The three requested voices were fetched,
installed and rendered on this box; the incumbent was rendered alongside as a
control so the numbers are comparable.

| voice | weight | sample rate | status here |
|---|---|---|---|
| `en_GB-jenny_dioco-medium` | 63,201,294 B | 22,050 | rendered ✅ |
| `en_GB-alba-medium` | 63,201,294 B | 22,050 | rendered ✅ |
| `en_GB-cori-high` | ~110 MB | 22,050 | **NOT testable here** ⚠️ |
| `en_GB-cori-medium` | 63,531,379 B | 22,050 | rendered ✅ (stand-in for cori) |
| `en_GB-southern_english_female-low` | 63,104,526 B | **16,000** | rendered ✅ (control) |

⚠️ `en_GB-cori-high` could not be obtained: Hugging Face and every GitHub asset
host are unreachable from this sandbox, and the fp32 weight is over GitHub's
100 MB non-LFS blob limit, so no mirror carries it as a plain file.
`en_GB-cori-medium` (same speaker, same Librivox corpus, medium quality) was
measured as the stand-in. **cori-high must be auditioned on the Fedora box**
where HF resolves; its numbers are not inferred from the medium model.

Weights came from a GitHub mirror of the canonical `rhasspy/piper-voices` tree
and were integrity-checked: `git hash-object` on every downloaded file
reproduced the blob SHA in the repo tree, so bytes match what is published.
Before making one canonical, re-verify against HF on the owner's box:

```bash
cd ~/.local/share/piper && sha256sum *.onnx
# jenny 469c630d209e139dd392a66bf4abde4ab86390a0269c1e47b4e5d7ce81526b01
# alba  401369c4a81d09fdd86c32c5c864440811dbdcc66466cde2d64f7133a66ad03b
# cori-medium 1899f98e5fb8310154f3c2973f4b8a929ba7245e722b3d3a85680b833d95f10d
# southern-low f2f37aed1b3a093476f719d1379ba0c0b1b1cf6f1ef99288e2ebf502971a07c3
```

## The measurement is not an ear

I cannot hear. What I can do is synthesise the exact test line, hand it to an
independent ASR (Vosk small-en, which never saw Piper output), and count words
it failed to recover. High recovery = the synthesis carried its own
consonants. It is a proxy for intelligibility, not a substitute for the owner's
judgement — and it is biased *against* strong regional accents, so it can
underrate a voice, never overrate one.

Script: `"On it. Sorting 148 files into Finance. Twelve need review. Is that
all? No. Not at this hour."` — 3 takes per voice at the shipped
`length_scale = 0.92`, plus the four production acks (the actual hot-path
audio) per voice.

### Intelligibility (priority 1)

| voice | mean word accuracy | worst take | run-to-run spread | acks heard exactly |
|---|---|---|---|---|
| `en_GB-alba-medium` | **98.5%** | 95.5% | 4.5 pp | **4/4** |
| `en_GB-jenny_dioco-medium` | 87.9% | 86.4% | 4.5 pp | 3/4 |
| `en_GB-cori-medium` | 84.9% | 77.3% | **22.7 pp** | 3/4 |
| `en_GB-southern_english_female-low` (incumbent) | **74.2%** | 68.2% | 13.6 pp | 3/4 |

What the ASR actually heard, which is the honest version of "poor
intelligibility":

- incumbent `on_it`/`done` → `"on it's sorting…"` / `"pan"`; alba → exact.
- cori `on_it` → `"on it has to have with her and"` (3.75 s for a two-word
  ack: it invented an entire phrase). That instability is disqualifying for a
  pre-rendered cache entry.
- jenny `on_it` → `"nice"` — muffled onset, consistent across all 3 takes.

### Brisk pace (priority 2)

Duration of the full line at the shipped `length_scale = 0.92`:

| voice | duration | words/s | pause fraction | ms/syllable |
|---|---|---|---|---|
| `en_GB-jenny_dioco-medium` | **6.57 s** | 2.69 | **0.18** | 196 |
| `en_GB-southern_english_female-low` | 7.32 s | 2.65 | 0.42 | 141 |
| `en_GB-alba-medium` | 8.05 s | 2.22 | 0.38 | 179 |
| `en_GB-cori-medium` | 8.52 s | 2.19 | 0.32 | 199 |

jenny is the only voice that is genuinely brisk *and* connected (18% silence).
The incumbent is "fast" only in the worst way: 141 ms/syllable rushed inside
bursts, but 42% of the render is gaps — which reads as clipped and racy, not
brisk. Alba is slow by default; see the pace ladder below for the fix.

### Bite / edge (priority 3)

Measured inside a common 0–8 kHz window so the 16 kHz incumbent is compared
fairly (no penalty for spectrum it never had):

| voice | spectral centroid | 2.5–8 kHz energy | 3–8 kHz (fricatives) | HF flatness (↑ = rasp/bite) |
|---|---|---|---|---|
| `en_GB-alba-medium` | **972 Hz** | 29.2% | 26.0% | 0.606 |
| `en_GB-cori-medium` | 970 Hz | 28.8% | **26.2%** | **0.649** |
| `en_GB-southern_english_female-low` | 936 Hz | **33.2%** | 29.0% | 0.554 |
| `en_GB-jenny_dioco-medium` | 883 Hz | 26.9% | 23.8% | 0.569 |

The incumbent's high HF *share* is an artifact: its spectrum is truncated at
8 kHz, so energy is concentrated below the cliff. That truncation is real —
16 kHz audio has no 8–11 kHz band where sibilant and fricative detail lives,
and no `length_scale`, volume or prompt change can add a band that is not in
the file. **It is not, however, the explanation for the owner's complaint**;
see "Round 4 addendum" at the end of this file, which supersedes the sentence
this paragraph used to end with ("that truncation is the mechanical reason it
is hard to parse"). The same truncated file renders full sentences at 76–84 %
ASR-recoverable, so a missing band above the speech range cannot be the whole
story. The medium/high voices all have that band. jenny is the dullest of the
set (lowest centroid): intelligible and quick, but light on edge.

## Pace ladder (native `length_scale` only, no stretching)

| voice | 0.92 | 0.80 | 0.70 |
|---|---|---|---|
| `en_GB-alba-medium` | 97.7% / 8.12 s | **95.5% / 7.19 s** | 90.9% / 6.52 s |
| `en_GB-jenny_dioco-medium` | 86.4% / 6.47 s | **90.9% / 6.01 s** | 86.4% / 5.13 s |
| `en_GB-cori-medium` | 81.8% / 7.85 s | 81.8% / 7.30 s | 95.5% / 6.76 s |
| `en_GB-southern_english_female-low` | 84.1% / 7.42 s | 75.0% / 7.18 s | **70.5% / 6.23 s** |

The incumbent gets *worse* as it gets faster (84.1 → 75.0 → 70.5). Pace cannot
rescue it. Alba at 0.80 is both brisker than the incumbent and ~11 pp more
intelligible; jenny at 0.80 is the fastest usable render in the whole table.

## Ranking against the stated priority order

1. **`en_GB-alba-medium`** — best intelligibility by a wide margin, the only
   voice whose four production acks all survived round-trip, tightest
   variance, and it has the highest centroid plus real fricative energy. Its
   one weakness (pace) is fixed by a native `length_scale` of ~0.80, after
   which it is still ~11 pp clearer than the incumbent at the same speed.
2. **`en_GB-jenny_dioco-medium`** — the pace winner and very stable, but the
   dullest timbre of the set and a consistently muffled `"On it."` ack. A good
   second choice if briskness is weighted above edge.
3. **`en_GB-cori-medium`** — most rasp/edge, and a perfect take exists, but a
   22.7 pp spread with a hallucinating `on_it` ack makes it untrustworthy for
   cached hot-path audio. `cori-high` is unmeasured here and could differ.
4. **`en_GB-southern_english_female-low`** — last on intelligibility, and
   structurally band-limited. Recommend demoting it from "selected".

## Switching voices: config keys and paths (no code change)

Two layers decide the voice, and the DB layer wins. Measured here: with
`[tts] voice_id = "en_GB-alba-medium"` in the config file, `voice status` still
reported `en_GB-southern_english_female-low` until the state row was deleted.

1. **Weights** — `~/.local/share/piper/<voice>.onnx` + `<voice>.onnx.json`
   (both required; `PiperTtsBackend.availability_error()` checks the `.onnx`).
2. **Selection, layer A (authoritative)** — row `tts.selected_voice` (JSON
   descriptor) in table `state` of `~/.local/share/assistant/assistant.db`.
   Written by `assist voice select <id>`, which only accepts ids present in
   `[[tts.audition_candidates]]` — selecting jenny with the shipped list fails
   outright (`ValueError: unknown voice candidate 'en_GB-jenny_dioco-medium'`,
   reproduced here). The shipped defaults deliberately keep round-1 rejects out
   (`tests/test_phase8_offline_voice.py:254` guards that), so **jenny becomes
   selectable by adding one `[[tts.audition_candidates]]` block to the local
   config — no code change, and the guard test still passes** because it
   asserts on defaults, not on the owner's file.
   The 110 MB `cori-high` weight lands in `~/.local/share/piper/` from HF even
   though it cannot be mirrored on GitHub, and `en_GB-cori-high` is already a
   listed candidate, so it needs no new block at all.
3. **Selection, layer B (default when no row exists)** — `~/.config/assistant/`
   `config.toml`, `[tts] voice_id` / `model` / `config` / `speaker` /
   `length_scale` / `command` / `player`.
4. **Candidate list** — `[[tts.audition_candidates]]` in the same file. Note
   `config._deep_merge` **replaces** lists instead of appending: a user-level
   candidate list must contain every voice to be selectable, not just the new
   one. (Verified — with four blocks in the user config, status listed exactly
   those four.)
5. **Ack cache** — `~/.local/share/assistant/voice-cache/`, filename keyed by a
   hash of text + voice + model + speaker + `length_scale`. Switching voice
   (or pace) invalidates all four acks, and `play_ack` deliberately does *not*
   synthesise on the hotkey path — it returns `cache_miss`, so the assistant
   goes **silent** on "On it." until re-warmed. Stale files from the previous
   voice are never read (different hash), so no wrong-voice leakage.
6. **Auditions** — `~/.local/share/assistant/voice-auditions/<voice_id>.wav`
   + `manifest.json`, produced by `assist voice audition --text "<script>"`.

One voice at a time, on the Fedora box (`[tts]` edits are the only repo-side
touchpoint, and `player`/`length_scale` are yours to set):

`piper.download_voices` (ships with the `tts` extra) fetches the `.onnx` and
`.onnx.json` pair from the canonical repo, so no hand-built URLs:

```bash
uv sync --extra offline --extra tts     # creates .venv/ with piper in it
mkdir -p ~/.local/share/piper
.venv/bin/python -m piper.download_voices \
  en_GB-alba-medium en_GB-jenny_dioco-medium en_GB-cori-high \
  --data-dir ~/.local/share/piper
sha256sum ~/.local/share/piper/*.onnx   # compare to the pinned digests above
```

Bare `python -m piper.download_voices` with no voice name lists every voice the
installed Piper knows about — handy for confirming `cori-high` is offered
before trusting a URL by hand.

Then, **one voice at a time** — copy this block into `~/.config/assistant/`
`config.toml` under `[tts]` (keeping the incumbent in the list so you can fall
back to it), and for each candidate in turn:

```bash
systemctl --user restart assistant          # config.toml is read once at startup
assist voice select en_GB-alba-medium       # writes the state row; the live pick
assist voice status                         # confirm voice_id + available: true
assist voice warm                           # MANDATORY: re-renders the 4 acks
assist voice say "On it. Sorting 148 files into Finance. Twelve need review. Is that all? No. Not at this hour."
```

Roll back with `assist voice select en_GB-southern_english_female-low` plus
`assist voice warm`. To stop the DB row shadowing the file entirely:

```bash
sqlite3 ~/.local/share/assistant/assistant.db \
  "DELETE FROM state WHERE key='tts.selected_voice'"
```

`assist voice say` without `--no-play` goes through `[tts] player = "auto"`
(`pw-play` → `paplay` → `aplay`), i.e. the PipeWire **default sink** — so the
muted speaker sink has to be fixed first or playback tests will look like
silent synthesis.

## Output-device note (owner's box; untestable here)

No PipeWire in this sandbox, so nothing about nodes 109/110/111 was executed —
only the config side was verified. The usual trap applies in reverse to
`wpctl`: the numbers in this report's node list are `node.serial`, while
`wpctl set-mute`/`set-default` want the **`wpctl status` id**. Resolve them
first (`pw-record --target=` is the opposite: it wants serial or `node.name`,
per `capture.py`).

```bash
for s in 109 110 111; do
  pw-dump | jq -r --argjson s $s \
    '.[] | select(.info.props["node.serial"]==$s)
     | "serial=\($s) id=\(.id) \(.info.props["node.name"])"'
done
wpctl set-mute <SPEAKER_ID> 0     # sink serial 109, then confirm:
wpctl get-volume <SPEAKER_ID>
```

Route playback by making the unmuted sink the default, which is certain to work
with `player = "auto"` (that path just runs `pw-play`/`paplay`/`aplay` and lets
PipeWire pick the default sink):

```bash
wpctl set-default <SPEAKER_ID>       # the id from the pw-dump lookup above
```

`[tts] player` accepts a full command line (it is `shlex`-split, and the first
token must be on `PATH`), so a device can be pinned instead — e.g.
`player = "paplay --device=<alsa node name>"`. **Confirm the exact device flag
on the box** (`pw-play --help`, `paplay --help`); this sandbox has no PipeWire,
so the playback side is unverified by design and only the config plumbing was
tested here.

For capture, the serial/node-name pair belongs in `[meeting] mic_target` /
`system_target` (Phase 6 path); `[capture]` today only exposes `source`,
`sample_rate`, `chunk_ms`, `retention_days`.

## Listening pack

`audio/round3/` (git-ignored by design — models and generated audio stay out of
git). `1-*` = test line at 0.92, `2-*` = the four acks, `3-*` = pace ladder at
0.80/0.70, `0-REFERENCE-*` = the official upstream cori-high sample (the only
cori-high audio obtainable from here — listen for timbre only; it is not our
test line).

Two stitched files exist for actually listening, because per-voice files invite
comparing one clip to a memory:

* `A-listen-blind-testline.{wav,mp3}` — all four voices, same test line,
  back-to-back with 0.75 s gaps, in a **seeded shuffled order** so the measured
  ranking cannot bias the ear. Order is withheld in
  `A-listen-BLIND-ORDER-KEY.txt`; score all four, then reveal.
* `B-listen-acks-incumbent-vs-alba.{wav,mp3}` — the four **production** acks,
  incumbent first then the front-runner. This is the closest thing to how
  Elaria actually sounds on the hotkey path.

Stitching is sample-rate conversion plus mono→duplication only — **no EQ, no
gain change, no time-stretch**. Verified against the source WAVs rather than
assumed: correlation ≥ 0.9998 after accounting for the ~25 ms MPEG encoder
delay, and the incumbent's 8–11 kHz energy stays at 0.40 % (wav) / 0.38 %
(mp3) where alba sits at 7.74 % / 7.49 % — i.e. the low voice's missing band is
still missing, nothing was brightened to make it look better or worse. The
`.wav` is bit-faithful; the `.mp3` is for browser players (16-bit/22.05 kHz
mono can fail in some web players).

Not approved, not canonical: owner ear-check required before anything else
(Hyprland binds, live Gemini) proceeds.

---

# Round 4 addendum — keeping the incumbent, and what config can actually buy

Added 2026-10-19 after the owner rejected the framing of rounds 1–3. Their
words: *"i dont get why im picking a new voice, i already had one — the problem
was i couldnt make out what it was saying."* So the task is **audibility of
`en_GB-southern_english_female-low`**, not a replacement beauty pageant. The
ranking tables above stay valid as measurement context; they are no longer the
decision under discussion.

Method unchanged: render, run an independent ASR (vosk `small-en-us-0.15`)
over the result, score recovered words against the script (numerals expanded
first). Short phrases are scored with a best-local-window alignment, because
scoring one 2-word phrase against a hypothesis that contains five phrases
measures nothing. Multiple takes per setting, always.

## Ruled out for the broken phrases

`Done.` and `Is that all?` stayed unrecoverable in roughly 30 renders across
every lever available without touching code:

| lever | range tested | result |
|---|---|---|
| `length_scale` | 0.80 / 0.92 / 1.00 / 1.15 / 1.30 | `Done.` 0 % at all five |
| silence padding around the clip | ±0.4 s | `Done.` 0 %; `Twelve need review.` 67 % → 100 % |
| render alone vs inside the full line | both | no change for either phrase |
| piper renderer | 1.2.0 (onnx 1.11) vs 1.8.0 | `Done.` 0 % on both |
| joined as `"Yes. <ack> Thank you."` | — | no change |

`On it.`, `Twelve need review.` and `No. Not at this hour.` are all fine
(75–100 %). The defect is specific to very short text, and it is deterministic,
so it is not a sampling accident and not a renderer bug.

## What the clips look like

Envelope anatomy, shipped `length_scale 0.92` (10 ms RMS frame, 18 % of peak
gate):

| clip | dur | speech | internal gaps | envelope peaks |
|---|---|---|---|---|
| `On it.` | 0.72 s | 26.8 % | 1 | 4 |
| `Done.` | 0.48 s | 53.2 % | 1 | 3 |
| `Is that all?` | 0.77 s | 40.8 % | 3 | 5 |
| `Twelve need review.` | 0.96 s | 47.4 % | 4 | 7 |
| `Done.` at `ls 1.30` | **1.54 s** | 22.9 % | **1 × 0.98 s** | 9 |

Two things are visible here. A three-word question gets 0.77 s (a 0.26 s/word
grind), and asking the model to go *slower* does not stretch it cleanly — at
`ls 1.30` it inserts a one-second hole inside a single word and grows spurious
peaks. That is also why the pace ladder below is non-monotonic in duration
(11.06 s at `ls 1.00`, 10.74 s at `ls 1.30`): this weight does not honour the
one knob that is supposed to control it.

## Config variants, measured through the repo pipeline

Rendered with `PiperTtsBackend` itself (not a hand-rolled piper call), 2 takes,
test line plus the four production acks:

| setting | knobs | line acc | dur | acks exact |
|---|---|---|---|---|
| A — as shipped | `ls 0.92` | 70.5 % | 7.39 s | 1/4 |
| B | `ls 1.15 --sentence-silence 0.35` | 77.3 % | 9.97 s | 1/4 |
| C | `ls 1.30 --sentence-silence 0.35` | 65.9 % | 11.30 s | 1/4 |
| D | `--sentence-silence 0.35` only | 72.7 % | 9.09 s | 1/4 |
| E | `--noise-scale 0.15 --noise-w-scale 0.5 --sentence-silence 0.3` | **84.1 %** | 8.59 s | **2/4** |

E looked like a 13.6 pp win, which with n=2 is exactly the kind of result this
voice's variance manufactures. Paired replication, 4 takes each:

| setting | line acc per take | mean | sd | worst | dur | `On it.` | `No. Not at this hour.` | `Done.` | `Is that all?` |
|---|---|---|---|---|---|---|---|---|---|
| A | 72.7 / 90.9 / 63.6 / 77.3 | 76.1 % | 9.8 pp | 63.6 % | 7.49 s | 3/4 | 3/4 | 0/4 | 0/4 |
| E | 72.7 / 77.3 / 77.3 / 86.4 | 78.4 % | 5.0 pp | 72.7 % | 8.44 s | 4/4 | 4/4 | 0/4 | 0/4 |

So: **the mean does not move** (+2.3 pp against a ±7–10 pp spread). What moves
is the floor — variance halves, the worst take goes 63.6 % → 72.7 %, and both
two-word acks go from sometimes-right to always-right. E is a reliability
change, not a clarity change, and it costs ~1 s on a sentence. Anyone who
reports "pace fixes it" or "slowing it down fixes `Done.`" from a single take
was reading noise; both claims were mine at various points in this round.

## The knobs, and where they legally live

Verified against `src/assistant/tts.py` rather than assumed:

* `[tts] length_scale` → reaches piper as `--length-scale` (`tts.py:162`). This
  is the sanctioned pace knob and the only pace knob.
* `[tts] command` is a **command prefix**, `shlex.split` then passed through
  whenever the first token resolves (`tts.py:132-143`). So extra piper flags
  that the repo never passes — `--noise-scale`, `--noise-w-scale`,
  `--sentence-silence` — are reachable from config with no code change. That is
  how E was applied. It does not violate the "no EQ, no time-stretch" rule
  (`tts.py:9`): nothing is filtered or resampled.
* Footgun: if `command` starts with a bare `piper` that is *not* on `PATH`,
  `command()` falls back to `[sys.executable, "-m", "piper"]` and **silently
  drops every flag in the prefix**. Use an absolute path to the binary.
* Second footgun, same function: `command` must be an **absolute** path, not a
  `~`-prefixed one. `Path(exe).expanduser().exists()` expands for the existence
  check but the returned argv keeps the literal `~`, so `subprocess.run` dies
  with `FileNotFoundError: '~/.venv/bin/piper'` on the first synth (measured —
  `~`-form fails, absolute form renders in 2.74 s). `model` and `config` *do*
  accept `~` (`expanduser()` is applied at `tts.py:159`-ish and `166`). Anything
  that makes the acks go silent is worth knowing about, so it is spelled out in
  the block below rather than trusted to memory.
* The model's own `<model>.onnx.json` `inference` block is **not** a usable
  place for pace: piper 1.8's CLI defaults override it (measured —
  `length_scale` 0.92 vs 1.4 in the JSON gave 3.856 s and 3.872 s for the same
  text). The repo passes `--config` (`tts.py:164-166`), so the file is read for
  the voice metadata, but pace must come from `config.toml`.

Recommended `[tts]` block for the owner's box, config-only:

```toml
[tts]
enabled = true
backend = "piper"
voice_id = "en_GB-southern_english_female-low"
model = "~/.local/share/piper/en_GB-southern_english_female-low.onnx"
config = "~/.local/share/piper/en_GB-southern_english_female-low.onnx.json"
speaker = 0
length_scale = 0.92
command = "/home/YOU/.venv/bin/piper --noise-scale 0.15 --noise-w-scale 0.5 --sentence-silence 0.3"
player = "auto"
speak_acks = true
```

(`model` / `config` keep `~`; `command` cannot.)

Then: `systemctl --user restart assistant` (config is read once, `daemon.py:920`)
→ `assist voice select en_GB-southern_english_female-low` (the `state` table row
in `~/.local/share/assistant/assistant.db` outranks `[tts] voice_id`) →
`assist voice warm` → `assist voice say "<test line>"`.

## Where the config-only route ends

Two of the four acks are still broken after every lever. Remaining options are
deliberately **not** implemented, since this round is diagnostic:

1. `speak_acks = false` — config-only, and it does make the garbage inaudible by
   removing the material that produces it. Costs the ack feedback channel.
2. Longer ack strings (`Done.` → `Done, sorted.`). The ack texts are hardcoded
   in `STANDARD_ACKS` (`tts.py:29-34`), so this is a code change. The three-word
   acks in the same table are fine, which is the argument for it.
3. Pad the ack with context at synthesis time and trim — code change, and
   trimming is a frame operation on an already-marginal clip. Not recommended.
4. A 22.05 kHz weight from the same speaker family, `southern_english_female`
   `medium`, exists only as a k2-fsa/sherpa-onnx export
   (`vits-piper-en_GB-southern_english_female_medium`), not in
   `rhasspy/piper-voices` (verified: the canonical repo ships that speaker at
   `low` only). Unreachable from this sandbox and **never heard or measured
   here**; the export is also a 6-speaker artifact, so it is not a drop-in for
   the same file. Do not treat it as a fix until it has been rendered and
   auditioned.

Corrections carried in this addendum, so the record is honest: the earlier
draft of this file attributed the muffle to the 16 kHz ceiling; that claim is
superseded above. And while re-checking the owner's `config.toml` I found that
the `en_GB-southern_english_female-low` audition candidate had been left
pointing at alba's weights — the 13:47 audition run itself was clean (its
manifest and the 16 kHz wav both record the correct model), but any
`voice select`/`audition` done between then and the fix would have played alba
under the incumbent's name. Paths are corrected; verify with
`assist voice status`, which must show `"voice_id": "en_GB-southern_english_female-low"`
**and** a `southern_english_female` model path.

Not approved, not canonical: `Done.` and `Is that all?` remain unrecoverable by
ASR at every setting tried, so the ear-check in the served preview
(section 5) is still the gate before any Hyprland bind or live-Gemini work.
