# Capture clipping — pop vs voice (2026-11-15)

Authority: MASTER BUILD PROMPT — ELARIA, BLUEPRINT V2 WIRING SPEC (2026-10-25),
the owner's hardware split of the capture-clipping defect, and the design-chat
ruling that follows the three frame-probe readings. One report for the whole
investigation. Branch `arena/c2a7085d-elaria`; instruments at `6785860`
(+`606ffc0`, `d765626`), this phase uncommitted at time of writing. Nothing
merged; PR #23's hold is unchanged.

**Status: D-B FIXED AT 18 % AND STILL CLIPPING ON LOUD SYLLABLES.** Gate 1 ran
2026-11-17 and found two defects in my own probe (fixed); Gate 2 set 35.0 → 18.0
and the production take at 18 % reads `rms_steady` 0.2311 (mid-band) with
`rms_variation` 1.6178 — the band is validated on real speech. But
`peak_steady` is still 1.0000 with 37 full-scale frames (`full_scale_share`
0.2284), and the packet's own capture line produced six seconds of silence while
production recorded the same mic (fixed: the take is now recorded through
production's argv). Candidate B (12 %) is in flight. The voice is at full scale on all
three kept takes; the start pop is real, one frame, and already handled; the fix
is the owner's input gain, issued as a packet
(`docs/packets/2026-11-15-capture-gain-reduction.md`), not daemon code.

**Estimate before code.** Phase 1: ~875 lines (packet 190 + manifest, doctor
split 60, gate 110, transcribe 60, pins 25, fixtures 260, report 170) →
delivered 718 + the report. Phase 2: ~690 lines (owner packet 175, source-check
script 280, acceptance 60, pins 200, docs 150) → delivered 947 (282 + 212 + 175
new lines, 178 inserted, 8 removed). 1.37× overall, under the 2× that would
require a cause paragraph; the overrun is in the source-check script (adds a
second file, its manifest and 13 pins that were not foreseen as a file of their
own).

## DONE

| item | where | pins |
| --- | --- | --- |
| Frame-level packet, checksummed, owner-runnable | `scripts/frame_probe.py` + `.sha256` | 6 |
| Peak split (`peak_full` / `peak_steady`) in doctor and in the session | `capture.split_peak`, `live_level_check`, `cli` doctor | 5 |
| Start-transient gate before VAD/ASR | `capture.StartTransientGate`, `transcribe.dictate` | 4 |
| **Gain acceptance** (`--gain-check`): shape, not a number | `frame_probe.gain_acceptance` | 5 |
| **Capture-path source check** (node, monitor state, volume, F17 refusal) | `scripts/capture_source_check.py` + `.sha256` | 20 |
| **Owner packet** for the gain change (gates, lines, acceptance, restore) | `docs/packets/2026-11-15-capture-gain-reduction.md` | — |

Suite **2199 passed, 6 skipped in 179.00 s** (from 2150/6 in 171.67 s; +49
pins), `ruff check .` clean. F36 trend continues.

### 1. The packet (the instrument, not the reading)

`python3 scripts/frame_probe.py <file.wav>` — one physical line, stdlib only, no
network, no credentials, numbers-only output (`key value` summary, then one
`FRAME index start_ms peak rms` row per 50 ms frame; a missing reading prints
`-1`, never a word). Keys that decide the question: `peak_full`, `peak_steady`,
`rms_full`, `rms_steady`, `full_scale_frames`, `full_scale_after_start`,
`first|last_full_scale_ms`, `verdict`, `recommended_start_pop_ms`.

Integrity: `sha256sum -c scripts/frame_probe.py.sha256` from the repository
root; the manifest names the file repo-relative and a pin both recomputes the
digest and shells out to `sha256sum -c`. The owner ran `286977be…`
(commit `6785860`), cross-checked byte-identical against `606ffc0`; the current
digest moved only when `--gain-check` was added, and the analysis path is
untouched.

### 2. The split

- `capture.split_peak(pcm, rate, skip_ms)` → `peak_full`, `peak_steady`,
  `start_pop_ms`, `steady_bytes`.
- **`peak_steady` = every frame that is not a start transient** (a full-scale
  frame inside the hold-off), not "everything after N ms". The first definition
  I wrote was time-based; it discarded a real first syllable and reported an
  empty steady span for a take shorter than the window, which turned a 30 ms
  genuine utterance into "silence" in an existing pin. The transient-based
  definition describes the person and never the pop.
- **Documented, deliberate asymmetry:** the *packet* computes its steady span
  by time (`start_ms >= 100`), the *session* computes it by transient. They
  differ only for a take whose speech begins inside the first 100 ms, and both
  names are defined at their source. Anything quoting `peak_steady` must say
  which one it means.
- `live_level_check` reports both peaks and keeps `peak` (== `peak_full`) for
  older readers; doctor prints `peak full X · peak steady Y (first N ms
  excluded)`; `capture.levels` journals both, plus `start_pop_ms` and the
  transient count.

### 3. The gate — hygiene, not the fix

`capture.StartTransientGate` + `transcribe.dictate`: inside `[capture]
start_pop_ms` (default 100 ms, which is what all three takes recommend) a
**full-scale** frame is recorded to the WAV and replay buffer but never
uploaded, and can never be `first_speech_frame_s`; a **speech-level** frame
inside the window is kept. The silence verdict reads the steady peak, so a
pop-only take is silence.

**It is not the clipping fix and must not be described as one.** D-B says the
voice itself is at full scale for 7.5–10 s per take; a hold-off trims one 50 ms
frame and leaves all of it.

### 4. Gain acceptance — shape, not a smaller number

`python3 scripts/frame_probe.py <wav> --gain-check` appends:

```
ACCEPT peak_steady <value> pass|fail
ACCEPT rms_steady <value> pass|fail
ACCEPT rms_variation <value> pass|fail
ACCEPT full_scale_share <value> pass|fail
gain_accept pass|fail
```

Thresholds: `peak_steady < 1.0`, `rms_steady` 0.15–0.30, and
`rms_variation = (p90-p10)/rms_steady ≥ 0.25` — the ruling's three criteria,
quantified. A fourth is added here and disclosed: `full_scale_share ≤ 0.05`,
because `peak_steady < 1.0` alone would accept a take peaking at 0.995 in every
frame. Pinned on synthetic takes: a speech-shaped take passes all four; the
20261102 flat-rail shape fails three; a steady tone at a *perfect* level fails
on variation alone — which is the point of the criterion.

### 5. Capture-path source check

`python3 scripts/capture_source_check.py` — read-only, stdlib, no network, no
credentials. Prints `default_source`, `configured_node` (`[capture]
mic_target`), the `node` capture would open now, `node_found`,
`node_is_monitor`, `node_is_mic1`, `volume_percent`, `monitor_sources` and the
monitor names, `note read_only`. It is the instrument for the 20261102 shape
question (b) and the packet's reversibility gate (the current volume, recorded
before the change). `pactl -f json` with a plain-text fallback; absent pactl
reports `available 0` + `reason` and never invents a number. A pin asserts the
script contains no volume-setting verb at all.

### 6. Readers that emit a level, named

The ruling made the unsplit readers a correctness question, so here is every
reader that can put a number in front of a person or a journal, with what the
number actually is:

| reader | SHA:line | emits | semantics |
| --- | --- | --- | --- |
| session schema `capture.stats` | `transcribe.py:1280` | `peak` (= `peak_full`), `peak_steady`, `start_transient` | split since `6785860`; `peak` kept for old readers |
| session `peak_rms` | `transcribe.py:1279` | `peak_rms` | **peak of the per-frame RMS** — a third metric, neither a sample peak nor an rms |
| no-speech note | `transcribe.py:1312` | was `peak=<peak_rms>` → now `peak_rms= / peak_full= / peak_steady=` | the old line printed the frame-rms peak under the name `peak`; renamed so it cannot be misquoted again |
| CLI capture trailer | `cli.py:2586` | was `peak=<peak_rms>` → now `peak_rms= / peak_full= / peak_steady=` | same rename, same reason |
| limiter stats | `capture.py:471,478` | `raw_peak`, `processed_peak` | whole-take maximums, pre/post limiter; **not split, and not a voice reading** — the limiter's own ceiling is 0.89, so `processed_peak` near 0.89 means "the limiter was working", not "the input is fine" |
| journal `session.close` | `daemon.py:2787` | `peak=<capture.peak>` | full peak only; the steady value is in `capture.stats` |

Two fields are still unsplit and are documented rather than renamed, because
renaming a journalled schema field is a contract change and needs its own
grant: the limiter's `raw_peak`/`processed_peak`, and the journal's
`session.close peak`. Neither may be cited as evidence about the voice.

## OWNER EVIDENCE (2026-11-15) — complete

Run conditions: worktree `/tmp/elaria-probe` detached at `6785860`;
`sha256sum -c frame_probe.py.sha256` OK (`286977be…`), byte-identical to
`606ffc0` by remote cross-check; the owner's venv interpreter; **31 % capture
volume** on the named Mic1 node
(`alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source`).

| | 20261027-064450-77cc4e | 20261031-145603-94129e | 20261102-100558-61258b |
| --- | --- | --- | --- |
| `duration_ms` / `frames` | 9750.0 / 195 | 10320.0 / 207 | 9930.0 / 199 |
| `peak_full` / `peak_steady` | 1.0000 / 1.0000 | 1.0000 / 1.0000 | 1.0000 / 1.0000 |
| `rms_full` / `rms_steady` | 0.4963 / 0.4988 | 0.4774 / 0.4797 | 0.5746 / 0.5747 |
| `full_scale_frames` | 128 | 159 | 199 |
| **`full_scale_after_start`** | **127** | **158** | **197** |
| `first` / `last_full_scale_ms` | 0 / 7700 | 0 / 10300 | 0 / 9900 |
| `recommended_start_pop_ms` | 100 | 100 | 100 |
| `verdict` | mixed | mixed | mixed |

Shapes: files 1–2 open with the pop (`FRAME 0` peak 0.9981, rms 0.0554), two
near-silent frames, voice from frame 3, then peak pinned at ~1.0 to the end with
real dips (down to 0.5781 in file 2). File 3 is different: frame 0 is already
1.0000/0.5683, there is no silent gap, peak never drops below 0.9922 in any of
199 frames, and rms stays in a ±0.07 band around 0.575 for 9.93 s.

Two facts worth keeping: frame 0 of files 1–2 reads **0.9981**, exactly the
muted-node doctor reading — so the muted probe was almost certainly the pop
alone (same number, different sessions; identity is inference, and it does not
change the ruling). And all three takes recommend **100 ms**, which is the
shipped default, so no config change follows from this.

## THE RULING, AS APPLIED

**D-B confirmed for the current configuration.** Sustained full-scale
flat-topping in every file; two of them recent enough to be the live config;
`rms_steady` 0.48–0.57 with `full_scale_after_start` 127/158/197. WP1's
input-gain review is **reinstated with evidence** — no longer "unproven". D-A is
**not** the fix: a hold-off trims one 50 ms frame.

Consequences carried into the docs, the packet and HANDOFF:

1. `[capture] start_pop_ms = 100` stays and the measurement is recorded in
   `config.toml.example`. The gate stays, described as hygiene.
2. **Applied and accepted:** 35.0 → **18.0** on the Mic1 node, kept; the 35.0
   restore value is recorded and unused. 18 % halves the level (0.4988 → 0.2311)
   but leaves loud syllables at full scale, so candidate B (12 %) follows.
   The gain change is an **owner-run packet**, not daemon code
   (`docs/packets/2026-11-15-capture-gain-reduction.md`): record the current
   value, change to 18 % (then 12 % if needed), one fresh take through the
   production chain, `--gain-check` twice, restore line, and the (a)/(b)
   separation for file 3.
3. Pre-roll ordering is unchanged in design and affected in order: clipping →
   capture fix (this packet) → pre-roll → wake word. Pre-roll is not built on a
   clipping path.
4. The "newer takes are cooler" reading is **retired** (below), and the Gemini
   emptiness now has a **sufficient** cause in evidence: destroyed input.

## DEFECTS FOUND

1. **The "cooler newer takes" numbers were a measurement artefact.**
   `rms 0.2754` (20261031) and `0.3485` (20261102) were quoted in chat for these
   same files; the frame probe reads `0.4797` and `0.5747`. Both retired. They
   cannot be reproduced from the repository's records: no reader here emits a
   whole-file rms at 31 % that yields those values for these files, and the two
   that *could* have produced a number of that size measure something else —
   `peak_rms` (peak of per-frame rms) or the doctor's short live-probe `rms`.
   Which one produced them is **unresolved [UNVERIFIED]**, and both numbers are
   therefore not citable again. The lesson is in §3 of DONE: two readers printed
   a frame-rms peak under the name `peak`, and have been renamed.
2. **The first version of the transient fix broke a real sensor.** Excluding
   every frame inside the hold-off from onset evidence moved a genuine
   `first_speech_frame_s` from 0.09 to 0.12 in an existing pin. Narrowed to
   transients only.
3. **The first definition of `peak_steady` (time-based) called a 30 ms utterance
   silence** — caught by `test_pause_then_release_silence_after_end_keeps_live`.
   Replaced by the transient-based definition; the short-take hole is closed by
   construction.
4. **Two names, one word.** `peak_steady` means "after 100 ms" in the packet and
   "non-transient" in the session. Documented at both sources, but a future
   reader can still conflate them; if it ever matters, the packet should adopt
   the session definition.
5. **Two unsplit fields remain** (limiter `raw_peak`/`processed_peak`, journal
   `session.close peak`) because renaming a journalled field is a contract
   change. Both documented as "not a voice reading".
6. **The 100 ms hold-off interacts with very short presses**: a press shorter
   than the window whose only frames are transient reads as silence (WAV kept).
   Honest, but a behaviour change for sub-100 ms presses.
7. **My own probe had two defects, found by the owner's Gate 1** (see the
   addendum): no default config path, and the system default source printed as
   a capture target in contradiction of F17. Both fixed and pinned; the 11-17
   Gate 1 reading has to be re-taken. This is the second time in this
   investigation that the instrument, not the system, was the fault (see
   DEFECTS 2 and 3) — worth remembering before a reading is believed.
8. **The packet's capture line was accepted and silent** (2026-11-17): `pw-record
   --target <node>` exited 0 with 5.95 s of rms 0.0003 while production recorded
   the same mic. Fixed by recording through production's own argv
   (`scripts/record_probe_take.py`), by `no_signal` in the probe, and by words in
   the packet. The *cause* of the silence remains [UNVERIFIED]; `--compare`
   reproduces both invocations in one sitting to settle it.
9. **A contradiction, surfaced not resolved:** the dictate path writes the
   limited audio to disk, and a pinned full-scale run reads back at ≤ 0.89, yet
   the owner's take shows 1.0000. Either that file predates the wiring or another
   writer produced it. Discriminator: the `capture.levels` journal line.
10. **No hardware evidence in the sandbox.** Every number in the pins is
   synthetic; the owner's three takes and the packet run are the measurement.

## NEXT GATE

**Candidate B — 12 %, measured through the production path** (in flight).

```
python3 scripts/record_probe_take.py /tmp/gain-12.wav --seconds 5   # exit 3 = capture-line failure, not a gain result
python3 scripts/frame_probe.py /tmp/gain-12.wav --gain-check
```

Acceptance: all four `ACCEPT` lines pass. `rms_steady` 0.15–0.30 is now
demonstrated achievable by the 18 % take (0.2311); what 12 % has to fix is
`peak_steady`/`full_scale_share` **without** spending the headroom the quiet
passages need (measured: room tone ~0.03 at 12 %, still above the 0.01 VAD
gate).

**If 12 % still clips, the answer is not more gain reduction.** Then the
question moves to the limiter's numbers (packet Gate 4b, one journal grep) and,
if the limiter is genuinely absent from that path, to wiring it — because the
owner's goal is an always-on mic feeding a 5 s pre-roll ring, and a ring that
stores clipped syllables stores damaged audio continuously.

`[capture] start_pop_ms = 100`: four independent confirmations (three kept takes
+ the production take), shipped default unchanged.

### Follow-ups still open, unchanged in kind

- Ask 13 / `mic_target`: now *narrower* — production capture succeeded, and
  `audio_gateway.resolve_target` refuses without a named node, so a node **is**
  named; `configured_node -1` was the probe's blindness. The corrected script
  confirms it on the next run. Nothing to pin until then.
- Two unsplit fields stay documented, not renamed (limiter
  `raw_peak`/`processed_peak`, journal `session.close peak`).
- Sub-100 ms presses: a take whose only frames are transient reads as silence.

## POST-RULING ADDENDUM — Gate 1 on the owner's machine (2026-11-17)

Run from a worktree at `f102920`; both manifests verified (`capture_source_check.py`
OK, `frame_probe.py` OK).

```
available 1
default_source alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source
node alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source
node_found 1
node_is_monitor 0
node_is_mic1 1
volume_percent 35.0
monitor_sources 4
sources 6
monitor_source_0..3 HDMI3 / HDMI2 / HDMI1 / Speaker .monitor
note read_only
```

**Explanation (b) is dead for this configuration [HW-PROVEN].** The node is the
named Mic1 input, not a `.monitor`; four monitor sources exist because every
sink has one, and capture is not pointed at any of them. What remains for the
20261102 flat envelope is (a): gain, tested by the packet.

### Finding 1 — the current value is 35.0, not 31

The packet's example said 31 %; Gate 1 read **35.0**. Not a defect (the packet
says the numbers are the owner's and Gate 1's value IS the restore gate), but it
means the input level moved between the earlier readings and now. Two
candidates, **not attributed**: the owner adjusted it, or WirePlumber restored a
stored level.

Consequence, now in the packet as **Gate 5**: if something restores levels on
its own, a manual gain change may not persist, so `volume_percent` is re-read
**at the end of the sitting and again after the next reboot**. A divergence
means the fix belongs at the session/WirePlumber level — a separate packet with
its own grant. Restore value for that sitting was **35.0**.

### Finding 2 — `configured_node -1`, and it was my defect

The addendum read `configured_node -1` as "`mic_target` is unset in the owner's
config". **That reading is not supported, and the fault is mine.** The script
had two defects:

1. **It never looked for a config unless `--config` was passed.** No default
   path at all — so `configured_node -1` was the script's own blindness, not a
   fact about the config. The daemon reads `$ASSIST_CONFIG`, else
   `$XDG_CONFIG_HOME/assistant/config.toml`; the script now resolves exactly
   that and prints `config_path` + `config_found`, so a `-1` can never again be
   mistaken for "not set".
2. **It presented the system default source as something capture would open.**
   `audio_gateway.resolve_target` has **no default-source fallback**: with no
   node named it raises, `refusal="policy"`, before anything is recorded. The
   script printed `node alsa_input…Mic1` as "the node capture would open", which
   contradicts F17 and would have measured a microphone the daemon never opens.
   Fixed: `node -1`, `capture_would_refuse 1`, `refusal f17_no_node`, with the
   default source reported under its own name and its own volume
   (`default_source`, `default_volume_percent`) as a fact about the machine, not
   a capture target. A pin imports `AudioGateway` and asserts the two agree.

Consequence: **the Gate 1 reading must be re-taken with the corrected script
before Finding 2 is decided.** Whether the owner's `mic_target` is unset is
currently unknown — the earlier doctor readings (muted node: rms 0.007, peak
0.9981) could only have been produced with a node named, which suggests it was
set then; that is inference, not evidence.

### Ask 13 — should `mic_target` be pinned? Yes, and here is what F17 refuses

**Design intent: the node is pinned; there is no default fallback.** F17's
implementation (`audio_gateway.resolve_target`) refuses **unconditionally** when
no node is named — "cleared" and "never had one" are *the same state* in this
code and **both refuse**, which is what RULING 1 demanded ("refuse an unnamed
capture node UNCONDITIONALLY; identical reason on both machine shapes"). On this
machine, F17 refuses:

- `ptt.start` / any real capture open → `GatewayRefused(refusal="policy")`,
  *before the earcon*;
- the doctor's live `mic level` probe → reports the refusal text instead of a
  level;
- the doctor's `capture node (Mic1)` check → `warn`, detail "mic_target empty —
  capture is REFUSED on every machine (F17 …)".

So "capture works by default fallback" is not a state this deployment has. If
Gate 1 (corrected) still reads `capture_would_refuse 1`, the pin is required and
is issued as an **owner-run line with a readback**, not a chat transcription of a
node name:

```
python3 scripts/capture_source_check.py --pin-line      # prints mic_target = "<node>"
```

paste that line under `[capture]` in the `config_path` the probe printed,
save, then acceptance is `configured_node` == `node`, `capture_would_refuse 0`,
`node_is_mic1 1`, and doctor's `capture node (Mic1)` ok. `--pin-line` prints `-1`
rather than a line when the node it would pin is a `.monitor` — pinning a
loopback would make (b) permanent. Packet Gate 1b carries this.

## ADDENDUM 2 — Gates 2–4 (2026-11-17): the gain worked, the packet's line did not

**Gate 2:** `35.0 → 18.0` on the Mic1 node; every other field identical
(`node_is_monitor 0`, `node_is_mic1 1`, 4 monitor sources, 6 sources). The 35.0
restore value is recorded and **unused** — 18 % is kept.

**Gate 3 failed as an instrument, not as a measurement.** The packet's
`pw-record --target <node> … /tmp/gain-18.wav` exited 0 and wrote 5.95 s of
`rms_steady 0.0003`, `peak 0.0055`, `verdict clean` — and the ACCEPT block read
"2 pass, 2 fail", which looks like a partial success and nearly became the
conclusion "18 % is too quiet". In the same sitting, same gain, `assist talk`
transcribed a voice turn verbatim. The syntax was *accepted* and opened
something silent: a refusal would have been information.

Fixes, in the order the design chat asked for them:

1. **The take is now recorded by the production path.**
   `scripts/record_probe_take.py` delegates its argv to
   `capture.pw_record_pcm_stream_command` — the same function the daemon uses —
   writes the stdout PCM to a WAV, and exits **3** with `silent 1` when a take
   is silent. `--compare` records the old line alongside it
   (`legacy_peak`/`legacy_silent`/`same`), which is the experiment that would
   say whether the silence was the invocation spelling (it is a diagnosis, not
   an attribution). A pin asserts the argv equality, so the two dialects cannot
   drift apart again.
2. **Silence fails closed in the probe.** `verdict no_signal` when `rms_steady`
   < 0.005 — outranking `clean` — and `--gain-check` on such a take prints
   **no** criterion lines at all, only `gain_accept no_signal` and
   `note silent_take_is_not_a_gain_reading`. A silent file can no longer read
   as partial success.
3. **The packet says it in words**: a silent take is a capture-line failure,
   never a gain result.

**Withdrawal.** Nothing in this lane's conclusions is drawn from that
`gain_accept fail`. The acceptance band was **not** evaluated by it.

## ADDENDUM 3 — the production take (2026-11-17 09:32, 18 %): band validated

| reading | value |
| --- | --- |
| duration / frames | 8190.0 ms / 164 |
| `peak_full` / `peak_steady` | 1.0000 / 1.0000 |
| `rms_full` / `rms_steady` | 0.2297 / **0.2311** |
| `full_scale_frames` / `after_start` | 38 / **37** (share 0.2284) |
| `first` / `last_full_scale_ms` | 0 / 4050 |
| `rms_variation` | **1.6178** |
| `verdict` | mixed · `recommended_start_pop_ms` 100 |

Envelope: frame 0 is the start pop with the October signature (0.9981/0.0554),
frames 1–2 silent, frames 3–17 a quiet lead-in, frames 18–81 loud passages with
full-scale hits interleaved with dips, frames 90–142 **2.4 s of room tone**
(rms 0.049–0.074), frames 143–155 a moderate passage peaking 0.60 with **no**
clipping, frames 156–163 decay.

**The band is validated.** `rms_steady` 0.2311 is mid-band and `rms_variation`
1.6178 is ~6.5x the 0.25 threshold, while the flat 20261102 rail scores ~0.17
and fails. The criteria are achievable by real speech; two of four pass.

**Clipping is graded, not binary — the report's own claim refined on evidence.**
This take was transcribed **verbatim** ("Testing testing, can you hear me?" →
"Loud and clear. What's on your mind?") while 22.8 % of its frames sat at full
scale. The October/November files that returned empty transcripts were 65–100 %
full-scale at `rms_steady` 0.48–0.57. Destroyed input remains a sufficient cause
for those empties, but the relationship is **severity, not presence**: partial
clipping can still transcribe. Any future sentence in this repo implying "one
full-scale frame is fatal" is wrong and should cite this.

**18 % halved the level as predicted and is still too hot for loud syllables.**
`rms_steady` 0.4988/0.4797/0.5747 at 31–35 % → 0.2311 at 18 %, but the peaks are
unchanged at 1.0000. The full-scale hits concentrate in the first four seconds
and the 7.2–7.7 s passage peaks at 0.60 with none, so this is transient loud
speech, not a steady source.

**The start pop is confirmed a fourth time** in a production take at the current
gain (frame 0, 0.9981/0.0554, then two silent frames) with
`recommended_start_pop_ms` 100 again. The 100 ms default and the gate are right.

**The 2.4 s interior room tone is a fixture now.** A speech → long silence →
speech take is exactly what the VAD strip and the no-speech path must survive;
`tests/test_gain_shape_fixture.py` freezes the shape (synthesised from the
reported numbers, never the owner's audio) and pins: band achievable, clipping
still present, the pop at frame 0, `recommended_start_pop_ms` 100, room tone
above the VAD floor, and the flat rail failing variation.

### The limiter question, answered from the code — and the contradiction it leaves

The design chat's ask was right and the code's answer is more interesting than a
yes/no:

- `capture.SoftLimiter` is **wired** into the dictate loop and **enabled
  unconditionally**; it is a **static** curve (knee 0.6, ceiling 0.89, no
  attack, no lookahead), so it cannot swallow an onset;
- it is applied **before the take is written** (`frame = limiter.apply(frame)`
  at `transcribe.py:857`, `wav_sink.write(frame)` at `:902`), so a
  dictate-produced WAV **cannot contain a sample above ~0.855**. A new pin runs
  a full-scale fake source through `DictationService.dictate` and reads the
  saved WAV back at ≤ 0.89, with `raw_peak 1.0` and `peak_full 1.0` still
  reported from the pre-limiter measurement.

So the owner's take reading `peak_full 1.0000` **cannot have come through this
path** — unless it predates the wiring or was written by another writer. This is
a contradiction, surfaced rather than resolved: the discriminator is the
session's journal line, `capture.levels`, which carries `raw_peak`,
`processed_peak` and `limited_samples` for that exact take. `raw_peak 1.0` with
`processed_peak` ≈ 0.85–0.89 is a working limiter on a hot input;
`processed_peak 1.0` would mean it is not in that path after all. Packet Gate 4b
asks for that line, one grep, before any further gain step is interpreted.

### VAD headroom, measured

At 18 % the quiet passages run rms ~0.05–0.10 and the room tone 0.049–0.074,
while `[transcribe] vad_rms_threshold` is **0.01**. Halving the gain again leaves
room tone ~0.025–0.037 — still above the gate, so the VAD is **not** the
constraint on going lower; the peaks are. The no-speech verdict reads the steady
**peak** against `[voice] silence_floor` 0.05, and even at 12 % a moderate
passage peaks ~0.3. Pinned in the fixture file.

## ADDENDUM 4 — the limiter grep came back empty (2026-11-17)

The owner ran the packet's Gate 4b line:

```
journalctl --user -u assistant --since "today" --no-pager | grep capture.levels | tail -3
```

**Result: nothing.** That is a measurement, and it is worth stating what it does
and does not discriminate. An empty result is the same shape for three different
worlds:

1. **the daemon is not running branch code** — `capture.levels` exists only in
   this branch (`transcribe.py:1683`, emitted unconditionally at the end of
   every `dictate`), so a stale daemon that transcribed the 09:32 turn
   perfectly well would still print no such line. This is the daemon-was-stale
   lesson from scene 1, and it is the likeliest of the three;
2. **a different unit** — the line is only on `assistant.service` if that is the
   unit that runs the daemon on this machine;
3. **no `ptt`/`dictate` session on that unit since midnight** — but the 09:32
   turn transcribed, so *some* session ran somewhere.

**It does not say anything about the limiter.** Nothing in the empty grep is
evidence for or against the limiter running, and it must not be cited as such.

### The instrument that cannot be stale

The durable record is the store: every `dictate` writes a `capture.stats`
persona event carrying `raw_peak`, `processed_peak`, `limited_samples`,
`peak_full`, `peak_steady` and the limiter's own block. `scripts/limiter_readings.py`
reads the newest of those, **read-only** (`sqlite3` URI `mode=ro`, no DDL, no
migration, pinned byte-identical), and prints one `key value` line per session
plus `limiter_effective`:

- `1` — `processed_peak < raw_peak` **and** `limited_samples > 0`, i.e. the
  input was hotter than what went out;
- `0` — nothing needed limiting, or the limiter did not see that audio.

The packet's Gate 4b now reads in the order that cannot lie: **doctor** (the
running daemon's in-memory last session: `processed peak`, `limited samples`),
then **`limiter_readings.py`** (the store, durable), and only then the journal —
with the empty-journal caveat written down beside it so no future reader treats
silence as a limiter verdict.

### What is still true from the code

Unchanged and pinned: the limiter is wired, unconditional, static (knee 0.6,
ceiling 0.89, no attack), applied **before** the take is written, and a
full-scale fake source read back from disk peaks at ≤ 0.89. So the open question
is narrower than "is there a limiter": it is **which writer produced the file
that reads 1.0000**, and the store's `capture.stats` row (or doctor's line) for
that session settles it without another theory.

## OPEN QUESTIONS

1. **The clipping narrative, restated.** Measured facts are marked; the rest is
   inference and says so.

   **Proven by measurement [HW-PROVEN].** The muted node reads rms 0.007 with
   peak 0.9981 — a full-scale sample survives a volume stage that provably owns
   the signal, so a start transient is injected at or after stream open. All
   three kept takes carry sustained full-scale flat-topping for 7.5–10 s at
   `rms_steady` 0.48–0.57, so the *voice* is at full scale too, on the current
   configuration. These are two defects, both real, in the same take.

   | historic claim | status now |
   | --- | --- |
   | "mic peak 1.0 → the microphone is clipping" (scene 1 `0.9981`, scene 2 `1.0`) | **REINSTATED, with a better instrument.** Peak never proved it; `full_scale_after_start` + `rms_steady` do. WP1's input-gain review is active again and this time it has evidence. |
   | "steady-state saturation through the take" (the October narrative) | **CONFIRMED, and it was the dominant defect.** `full_scale_after_start` 127/158/197. |
   | "`first_speech_frame_s 0.0` and `gated_frames 0` on real turns" | **EXPLAINED as the pop** (a full-scale frame at 0 ms is instant speech to an energy gate) and **defended against** (transients no longer count as onset evidence). Whether the number was this pop is still [UNVERIFIED] until a post-gate session reports non-zero. |
   | "owner speech proven at peak 0.8624" (silence hotfix rule 2) | **STANDS** — below full scale, so not the pop shape; a real loud voice. The 0.05 floor it justified is untouched. |
   | "the newer takes are cooler (rms 0.2754 / 0.3485)" | **RETIRED** — the probe reads 0.4797 / 0.5747 on the same files; the older numbers have no reproducible producer in this tree (DEFECTS 1). |
   | "the takes are empty when sent to Gemini" (measured) | **STANDS as measured, and now has a sufficient cause in evidence**: clipped, flat-topped input at rms ~0.5–0.58 is destroyed audio, upstream of any model setting. Sufficient, not proven unique — the report's discipline holds. |
   | "the limiter mitigates but never conceals" (J5) | **STANDS**, and matters more: the limiter's `processed_peak` (ceiling 0.89) hides nothing and also proves nothing about the input. |

2. **The 20261102 constant envelope — (a) or (b)?** Asked, not asserted. (a)
   gain so hot that quiet passages saturate; (b) a steady loud source beside the
   voice (monitor/loopback of playback, the thing the gateway's single-throat
   rule exists to prevent). The packet measures both: `node_is_monitor` at Gate
   1 answers (b) for the node, and a take at reduced gain answers (a). **If the
   envelope stays flat across two different gains, it is (b) and no amount of
   gain reduction will fix it.**
3. **Should the packet's `recommended_start_pop_ms` set the config
   automatically?** Still prints and is set by hand; an auto-writer mutates the
   owner's config and needs its own grant.
4. **Should the split replace bare `peak` everywhere** (limiter stats, journal
   `session.close`)? A contract change to fields other documents quote —
   proposed, not done.
5. **What was the October config?** File 1 predates the current session
   settings; if the gain packet fixes current takes and file 1 keeps clipping at
   the same gain, the October difference (config or voice) is still unrecorded.
   Optional, cheap to write down while the journal is at hand.
