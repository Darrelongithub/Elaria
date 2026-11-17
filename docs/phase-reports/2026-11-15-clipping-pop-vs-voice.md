# Capture clipping — pop vs voice (2026-11-15)

Authority: MASTER BUILD PROMPT — ELARIA, BLUEPRINT V2 WIRING SPEC (2026-10-25),
plus the owner's split of the capture-clipping defect (2026-11-15). One report
for this investigation. Branch `arena/c2a7085d-elaria`, commit `6785860`.
Nothing merged; PR #23's hold is unchanged.

**Estimate given before code:** packet ~190 lines + manifest, doctor split ~60,
transient gate ~110, transcribe wiring ~60, J-pin updates ~25, fixtures/tests
~260 (~16 pins), report ~170 — ~875 lines, and the transcribe wiring was named
as the part expected to overrun.

**Delivered:** 718 insertions across 8 files — packet 201, manifest 1, capture
104, cli 19, config 7, transcribe 62, tests 328 (14 pins), example 6. The
overrun did not happen; the pin count came in under (14 vs ~16). Two things
were rebuilt mid-task rather than planned: the steady-peak definition (below)
and a J-era sensor regression the first version caused.

## DONE

| item | where | pins |
| --- | --- | --- |
| Frame-level packet, checksummed, owner-runnable | `scripts/frame_probe.py` + `.sha256` | 5 (checksum, numbers-only shape, clean, pop, steady-clip, mixed) |
| Peak split (`peak_full` / `peak_steady`) in doctor and in the session | `capture.split_peak`, `live_level_check`, `cli` doctor | 5 |
| Start-transient gate before VAD/ASR | `capture.StartTransientGate`, `transcribe.dictate` | 4 |
| Semantics: onset and silence verdict no longer read a pop | `transcribe.py` | inside the above |

### 1. The packet (the instrument, not the reading)

`python3 scripts/frame_probe.py /path/to/file.wav` — one physical line, stdlib
only, no network, no credentials, numbers-only output (a `key value` summary
then one `FRAME index start_ms peak rms` row per 50 ms frame; a missing reading
prints `-1`, never a word).

Summary keys that decide the question:

- `peak_full`, `peak_steady` — the two readings of the same take;
- `full_scale_frames`, `full_scale_after_start`, `first_full_scale_ms`,
  `last_full_scale_ms` — where the full-scale samples are;
- `verdict` — `clean` | `pop_at_start` | `steady_clip` | `mixed`;
- `recommended_start_pop_ms` — the hold-off the numbers imply (0 when clean,
  rounded up to a frame and capped at 100 ms when a start pop exists).

Checksum: `sha256sum -c scripts/frame_probe.py.sha256` from the repo root. The
manifest names the file **repo-relative** (`scripts/frame_probe.py`) so that
line verifies from the root, as every other pin in this house does; a pin both
recomputes the digest and runs `sha256sum -c` itself. Two digests are in play
and neither is an error: `286977be…` is commit `6785860` (the copy the owner
ran, cross-checked byte-identical against tip `606ffc0`), and `47dc0e65…` is
the current tip after the manifest-name fix — the analysis path was not touched,
only the name the manifest writes.

Sandbox verification (pins, synthetic takes — [TESTED-ONLY]):

- clean sine at 0.25 → `verdict clean`, no full-scale frames, both peaks 0.2500;
- 3 ms full-scale burst then 0.25 voice → `verdict pop_at_start`, first/last
  full-scale at 0 ms, `full_scale_after_start 0`, peak_full ≥ 0.999 while
  peak_steady ≤ 0.26, `recommended_start_pop_ms 50`;
- quiet lead-in then 0.999 voice → `verdict steady_clip`, first full-scale at
  ≥ 100 ms, peak_steady ≥ 0.99;
- both shapes together → `verdict mixed`.

### 2. The split

- `capture.split_peak(pcm, sample_rate, skip_ms)` → `peak_full`, `peak_steady`,
  `start_pop_ms`, `steady_bytes`.
- **`peak_steady` is every frame that is not a start transient** (a full-scale
  frame inside the hold-off), not "everything after N ms". The first definition
  I wrote was time-based; it discarded a real first syllable and reported an
  empty steady span for any take shorter than the window, which turned a 30 ms
  genuine utterance into "silence" in an existing pin. The transient-based
  definition describes the person and never the pop, and it is the one shipped.
- `live_level_check` reports `peak_full`, `peak_steady`, `start_pop_ms`, and
  keeps `peak` (== `peak_full`) for every existing reader.
- doctor prints `peak full X · peak steady Y (first N ms excluded)` in the
  `mic level` check and the same pair plus the transient count in
  `capture levels`; the journal line `capture.levels` carries
  `peak_full=`, `peak_steady=`, `start_pop_ms=`, `start_transients=`.
- Pins: both peaks survive a probe, config declares the hold-off, `0` disables
  the gate, and the doctor line cannot show a bare peak again.

### 3. The capture fix

`capture.StartTransientGate` + `transcribe.dictate`:

- inside `[capture] start_pop_ms` (default 100 ms), a **full-scale** frame is
  transport, not the owner: it is written to the WAV and the replay buffer
  (audio is never lost) and **not uploaded** to Live/ASR;
- a **speech-level** frame inside the window is kept and uploaded — the
  hold-off must never cost a syllable;
- a transient can never be `first_speech_frame_s` (this is the 0.0 reading:
  the pop counted as instant speech); a real first syllable inside the window
  still can be, so the sensor keeps describing the owner;
- the silence verdict now reads the steady peak, so a take that is only a pop
  is reported as silence. Both peaks stay in `capture.stats` and in the
  journal, so nothing is concealed;
- `[capture] start_pop_ms` is declared in DEFAULTS and documented in
  `config.toml.example` with the packet as its derivation.

Why 100 ms as the default: the synthetic worst case is a one-frame pop →
packet recommendation 50 ms; one frame of margin gives 100. It is **provisional**
until the owner's three takes are measured, and changing it is one config line.

F28 and the gateway contract are untouched (no playback-adjacent code moved).
J's pins needed no edits: none asserted pop behaviour, and the two semantic
changes are pinned in the new file.

### 4. What this did and did not decide

The packet is the instrument; the **D-A / D-B verdict on real data is still
owed**. Nothing in this commit claims to know which shape the owner's takes are.

## DEFECTS FOUND

1. **The first version of the fix broke a real sensor.** Excluding every frame
   inside the hold-off from onset evidence moved a genuine
   `first_speech_frame_s` from 0.09 to 0.12 in an existing pin
   (`test_stream_h_sensors`) — i.e. it would have made the number wrong for
   normal speech to make it right for a pop. Narrowed to transients only.
2. **The first definition of `peak_steady` (time-based) called a 30 ms
   utterance silence** — an existing transcript-integrity pin caught it
   (`test_pause_then_release_silence_after_end_keeps_live` returned empty text
   because the steady span was empty). Replaced with the transient-based
   definition; the short-take hole is closed by construction, not by a special
   case.
3. **`peak` is read in at least five places that predate the split** (schema
   lines, doctor, CLI dictate stderr, the silence-floor rationale in
   `HANDOFF.md`, WP1's "input-gain review"). Only doctor and the session stats
   are split in this commit. The others still print `peak`, which is now
   documented as the full reading — but a reader who does not know the split
   exists can still misread one. Listed, not silently rewritten: changing them
   is content, not plumbing.
4. **The 100 ms hold-off interacts with very short presses**: a press
   shorter than the window has no steady span containing speech, and its only
   frames could be a transient. `no_speech` would be true and the WAV is kept.
   That is the honest outcome (a pop-only take is silence), but it is a
   behaviour change for sub-100 ms presses that the owner should know about.
5. **No hardware evidence in this commit.** Every number above is synthetic.

## NEXT GATE

**The owner's one-line run, three times** (numbers only, nothing to collect by
hand — paste the summary block, the `FRAME` rows are optional):

```
python3 scripts/frame_probe.py ~/…/20261027-064450-77cc4e.wav
python3 scripts/frame_probe.py ~/…/20261031-145603-94129e.wav
python3 scripts/frame_probe.py ~/…/20261102-100558-61258b.wav
```

Verification first: `sha256sum -c scripts/frame_probe.py.sha256`.

**Run 1 of 3 is in (2026-11-15, PARTIAL EVIDENCE — no fix ruling yet).** See
"Owner run 1" below; files 2 and 3 (the two newer kept wavs) decide it.

Then the reading:

- **D-A (pop)** — `verdict pop_at_start` on the takes: the historical `peak`
  readings were the stream-open transient; set `[capture] start_pop_ms` to the
  largest `recommended_start_pop_ms` of the three and re-run doctor once. The
  limiter's ceiling (0.89) does not swallow onset — it is a static per-sample
  curve with no attack time, so nothing further is needed on that side.
- **D-B (steady clip)** — `verdict steady_clip`/`mixed` with
  `full_scale_after_start` in double digits: the voice itself is at full scale
  and the input-gain review (WP1) is the real fix; the hold-off then only
  removes the pop from the diagnosis, not the clipping from the audio.
- **`clean` on all three** — the October peak-1.0 readings were neither: look at
  what changed between the takes and the sessions that produced 0.9981/1.0.

Doctor after the fix should read `peak full … · peak steady …` on the next
session; if `peak steady` is low while `peak full` is 1.0, the pop reading is
confirmed on live hardware without waiting for the packet.

**Tonight's F2 press:** no expectation is set here. It is a datapoint — the
journal `capture.levels` line now carries both peaks and the transient count,
so whatever it shows is readable. No claim is made about what it will show.

## OWNER RUN 1 OF 3 (partial evidence — 2026-11-15)

Recorded, not ruled. Worktree detached at `6785860`; `sha256sum -c
scripts/frame_probe.py.sha256` OK (`286977be…`), cross-checked byte-identical
against tip `606ffc0`; interpreter the owner's venv. Files 2 and 3 pending in
the same sitting — **do not act on file 1 alone.**

`20261027-064450-77cc4e.wav` (October 27 capture, 9.75 s, 16 kHz mono,
195 frames) — numbers as printed:

| reading | value |
| --- | --- |
| `peak_full` / `peak_steady` | 1.0000 / 1.0000 |
| `rms_full` / `rms_steady` | 0.4963 / 0.4988 |
| `full_scale_frames` / `full_scale_after_start` | 128 / 127 |
| `first_full_scale_ms` / `last_full_scale_ms` | 0 / 7700 |
| `start_window_ms` / `recommended_start_pop_ms` | 100 / 100 |
| `verdict` | **mixed** |

Shape: `FRAME 0` is 0.9981 peak at 0.0554 rms (one frame — the power-up pop);
frame 1 is digital silence, frame 2 is 0.0313; the voice enters around 150 ms
and sits at or within 0.01 of full scale for ~7.5 s; only frames 155–194 fall
back to 0.28–0.97.

Reading (mine, on the numbers above, and it is not the ruling): for **this
file** the dominant defect is **steady clipping, not the pop**. A hold-off
alone would trim frame 0 and leave 127 full-scale frames of distorted voice —
so D-A is not sufficient here; the file is D-B territory. The `mixed` verdict
is correctly carried by the pop, and that is exactly why the verdict alone was
never allowed to decide: `full_scale_after_start 127` is what decides.

One corroboration worth recording: frame 0 reads **0.9981**, and the
muted-node doctor probe read **0.9981**. That makes it plausible that the
muted reading *was* the pop and nothing else — the strongest hint yet that the
mute test and this take share one mechanism. Identity is inference, not proof
(same number, different sessions); files 2–3 may confirm or dissolve it.

Whatever the other two say, this file's `recommended_start_pop_ms` is **100**,
which is already the shipped default, so no config change is implied by run 1.

### The decision once files 2–3 land

- **2 and 3 also `steady_clip`/`mixed` with material `full_scale_after_start`**
  → D-B confirmed for the *current* config: WP1's input-gain review is
  reinstated with evidence. The remedy is an **owner-run** line dropping input
  31 % → 15–20 %, then one doctor line and one fresh capture showing
  `rms_steady` ~0.25–0.35 with `peak_full < 1.0`. A gain change is the owner's
  action, not daemon code, and this session does not touch it.
- **2 and 3 `clean`/`pop_at_start`** → the October clipping is a historical
  artefact of that session's gain and voice; current captures are acceptable;
  remaining work is pop hygiene (the gate already built at `6785860`) and,
  optionally, recording what the October config was.
- **the pop default** stays 100 ms; if 2–3 recommend otherwise, the largest of
  the three sets it, and the measurement is recorded here.

## OPEN QUESTIONS

1. **The clipping narrative, restated** — this is the answer to "what was pop,
   what was voice, which claims retire". Measured facts are marked; everything
   else is inference and says so.

   **What the mute test proves [HW-PROVEN].** With the node muted, rms 0.007
   (speech gone) but peak 0.9981 (a full-scale sample survived). Node volume is
   upstream of rms and yet cannot remove that sample, so at least one
   full-scale event is injected at or after stream open — a start-pop / DSP
   power-up click. This is the first measurement in the whole history of this
   defect that separates the two mechanisms.

   **What follows for the historic claims.**

   | historic claim | status now |
   | --- | --- |
   | "mic peak 1.0 → the microphone is clipping" (scene 1 `0.9981`, scene 2 `1.0`, WP1 input-gain review) | **RETIRED as stated.** A peak reading cannot distinguish a pop from the voice; at most one full-scale event is proven to be transport. The input-gain review is not cancelled — it is *unproven*, and D-B is what would reinstate it. |
   | "steady-state saturation through the take" (the October narrative) | **SUSPENDED.** It anchored on peak. Nothing has ever shown full-scale samples spread through a take; the packet's `full_scale_after_start` is the first instrument that could. |
   | "`first_speech_frame_s 0.0` and `gated_frames 0` on real turns are odd" | **EXPLAINED as a candidate, and now defended against.** A pop at 0 ms is instant "speech" to an energy onset detector — the mechanism is consistent with the reading. The gate now excludes transients from onset evidence, so the number will describe the owner. Whether 0.0 was *this* pop is still [UNVERIFIED] until a post-fix session reports a non-zero value. |
   | "owner speech proven at peak 0.8624" (silence hotfix rule 2) | **STANDS**, with a caveat: 0.8624 is below the full-scale threshold, so it was not the pop shape; it was a real loud voice. The 0.05 floor it justified is untouched. |
   | "the takes are empty when sent to Gemini" (measured) | **STANDS as measured.** Only its *cause attribution* is in play: if the pop is what the transcriber choked on, the cause is transport; if the takes are genuinely clipped speech, the cause is gain; if the takes contain no speech at all, neither. The packet's numbers, not this report, decide which. |
   | "the limiter mitigates but never conceals" (J5) | **STANDS unchanged** — and it is now stronger: the limiter never touches the measurement, and the measurement itself is split. |

   **What is explicitly not claimed.** That the owner's voice is clean at high
   slider positions. The second question (is rms 0.35 at 31 % merely hot or
   genuinely clipped?) is untouched by this work: rms cannot answer it and the
   packet's `rms_steady`/`peak_steady` pair can only narrow it. A proper answer
   needs the packet on a take with known content, which is the owner's run.

2. **Should the packet's `recommended_start_pop_ms` set the config
   automatically?** Today it prints and the owner (or I) set the value. An
   auto-writer would be a mutating action against the owner's config and needs
   its own grant.
3. **Should the split replace `peak` everywhere** (schema lines, CLI stderr,
   ladder) rather than living beside it? That is a schema change to lines other
   documents quote, so it is proposed, not done.
4. **Is 100 ms the right hold-off on this hardware?** Provisional by
   construction; the owner's three takes answer it.
