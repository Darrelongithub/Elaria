# Owner-run packet — capture input-gain reduction (D-B)

Issued 2026-11-15 on the design-chat ruling that follows the three frame-probe
readings. **Revised 2026-11-17 (twice).** First after Gate 1 ran: the source-check script
had two defects (no default config path, and it presented the system default
source as a capture target — F17 refuses exactly that), both fixed, with a pin
step added for an unnamed node. Then after Gates 2–4 ran and the packet's own
capture line produced **5.95 s of digital silence** while production recorded
the same microphone fine: Gate 3 is now a production-path recorder, a silent
take is labelled a capture-line failure and never a gain reading, and the
limiter and VAD checks are added because 18 % still clips on loud syllables.

**State of play (2026-11-17):** Gate 1 read 35.0, Gate 2 set **18.0**, and
**18 % is accepted and kept** — the production take at 18 % was transcribed
verbatim, `rms_steady` 0.2311 sits mid-band, and `rms_variation` 1.6178 is ~6.5x
the threshold. The 35.0 restore value is recorded and **unused**. What remains
is loud-syllable clipping: `peak_steady` 1.0000, `full_scale_after_start` 37
(share 0.2284). Candidate B (12 %) is being measured through the production
path. **Owner-run by design**: a gain change on the owner's machine is the
owner's action, not daemon code. This packet adds no code to the capture path
and changes no config file — it is lines to run, in order, with the numbers to
read at each step.

Why: all three kept takes carry sustained full-scale flat-topping
(`full_scale_after_start` 127 / 158 / 197 of 195 / 207 / 199 frames), so the
defect is the voice at the input, not the start pop. The start pop is real, one
50 ms frame, and already handled by `[capture] start_pop_ms = 100` — it is
hygiene, not the clipping fix. **A hold-off cannot repair this; the gain can.**

Nothing here is destructive, and every step is reversible from a value you
record *before* you touch anything. That is the first gate.

---

## Gate 1 — verify the instruments, then record the current value

Run from the repository root. Two checks, both read-only.

```
sha256sum -c scripts/capture_source_check.py.sha256
sha256sum -c scripts/frame_probe.py.sha256
```

Expected: two `OK` lines. A mismatch means the file is not the reviewed one —
stop and send the mismatch, do not run the rest.

```
python3 scripts/capture_source_check.py
```

Expected shape (numbers are yours; this is the field list):

```
available 1
config_path /home/<you>/.config/assistant/config.toml
config_found 1
configured_node <[capture] mic_target, or -1 if unset>
node <the node capture would open, or -1 if it would refuse>
capture_would_refuse 0
refusal -1
node_found 1
node_is_monitor 0
node_is_mic1 1
volume_percent 35.0
default_source <your PipeWire default source>
default_volume_percent 35.0
monitor_sources 4
sources 6
monitor_source_0 <name>
note read_only
```

**Write `volume_percent` down.** It is the reversibility gate: whatever happens
below, that number restores the machine exactly.

Read four things in that output:

| field | meaning | what matters |
| --- | --- | --- |
| `config_path` / `config_found` | which config file was read | `config_found 0` means the file is not where the daemon looks; a `-1` under `configured_node` is then "not read", not "not set" |
| `node` / `capture_would_refuse` | the node capture would open | `capture_would_refuse 1` means F17 will refuse every capture — do Gate 1b before anything else |
| `node_is_monitor` | is that node a loopback of playback? | must be `0`; `1` means the mic is not the mic and no gain change will fix it |
| `monitor_sources` | monitor sources present on the system | presence is normal (every sink has one); the question is only whether capture is pointed at one — `node_is_monitor` answers that |

`default_source` / `default_volume_percent` are facts about the machine, not a
capture target: F17 forbids opening the default node, and the probe says so
instead of dressing it up as one.

If `capture_would_refuse 1`: do **Gate 1b** now.
If `node_is_monitor 1`: **stop here.** That is explanation (b) for the 20261102
flat envelope, and the fix is a wiring fix, not a gain fix. Send the output.

## Gate 1b — pin the node (only if `capture_would_refuse 1`)

F17 refuses an unnamed node on every machine, so "mic_target was never set" and
"mic_target was cleared" are the same state and both refuse. Do not hand-type a
node name; have the instrument print the exact line:

```
python3 scripts/capture_source_check.py --pin-line
```

Expected: one line, `mic_target = "<node.name>"`, or `-1` if the node it would
pin is a `.monitor` (in which case stop and send the reading — pinning a
loopback would make (b) permanent).

Paste that line under `[capture]` in the file `config_path` named, save, then
prove it landed:

```
python3 scripts/capture_source_check.py
```

Acceptance: `configured_node` and `node` are the same node, `capture_would_refuse 0`,
`node_is_mic1 1`, and `assistant doctor`'s `capture node (Mic1)` check reads ok.
Then continue at Gate 2.

## Gate 2 — the change, candidate A (DONE 2026-11-17: 35.0 → 18.0, kept) 

Node name, from the ruling: `alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source`
(substitute your `node` value if it differs).

```
pactl set-source-volume alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source 18%
```

(Candidate A is **18 %**: applied 2026-11-17, accepted on production evidence
and kept. **Candidate B is 12 %**, and it is the next step because loud
syllables still reach full scale at 18 %. Record the value Gate 1 printed — on
2026-11-17 it was **35.0**, not the 31 % of the earlier readings; Gate 1's
number, whatever it is, is the restore value.)

WirePlumber equivalent, if you prefer it — note it takes the numeric **id**,
not the name (`wpctl status` lists sources with ids next to them):

```
wpctl set-volume <id> 18%
```

Then re-read the node to confirm the change landed (read-only, same script):

```
python3 scripts/capture_source_check.py
```

Expected: `volume_percent 18.0`.

## Gate 3 — one fresh take, through the PRODUCTION path

**Do not use `pw-record` directly.** On 2026-11-17 the old line here
(`pw-record --target <node> … /tmp/gain-18.wav`) exited 0 and wrote 5.95 s of
rms 0.0003 — digital silence — while the assistant's own capture recorded the
same microphone fine in the same sitting. The syntax was *accepted*, so it
looked like a result. A silent take is a **capture-line failure, not a gain
result**; it must never be read as "this gain is too quiet".

So the take is recorded through production's own argv, delegated rather than
re-spelled:

```
sha256sum -c scripts/record_probe_take.py.sha256
python3 scripts/record_probe_take.py /tmp/gain-18.wav --seconds 5
```

It resolves the node exactly as the daemon does (F17: no node named is a
refusal, never the default source), calls
`capture.pw_record_pcm_stream_command`, writes a 16 kHz mono s16 WAV, and prints
`target`, `argv production`, `bytes`, `seconds`, `peak`, `rms`, `silent`.

- `silent 0` → continue to Gate 4.
- `silent 1` (and exit code 3) → **the capture line failed, not the gain.** Stop,
  send the output, do not read `rms` as a level. `--compare` records the same
  seconds through the old `pw-record` line as well and prints
  `legacy_peak`/`legacy_silent`/`same`, which is what would say whether the
  silence was the invocation spelling — it is a diagnosis, not a claim.

**Gate 3b — the source question (answered 2026-11-17).** The 20261102 flat
envelope had two candidates: **(a)** gain so hot that quiet passages saturate;
**(b)** a steady loud source beside the voice (monitor/loopback). Gate 1 read
`node_is_monitor 0`, `node_is_mic1 1`, with four monitor sources present and
normal — **so (b) is dead** for this configuration, and the take above tests
(a).

## Gate 4 — measure, twice

```
python3 scripts/frame_probe.py /tmp/gain-18.wav --gain-check
```

The summary is as before; the new block at the end is the acceptance verdict:

```
ACCEPT peak_steady <value> pass|fail
ACCEPT rms_steady <value> pass|fail
ACCEPT rms_variation <value> pass|fail
ACCEPT full_scale_share <value> pass|fail
gain_accept pass|fail
```

Acceptance is **all four pass** — which is the ruling's shape, not merely a
smaller number:

| criterion | pass when | why |
| --- | --- | --- |
| `peak_steady` | < 1.0 | no sample at full scale past the start window |
| `rms_steady` | 0.15 .. 0.30 | a speaking level with headroom, not a rail (the clipped takes read 0.48-0.57) |
| `rms_variation` | ≥ 0.25 | `(p90-p10)/rms_steady` — speech swings; a saturated rail sits in a narrow band (the 20261102 file scores ~0.17) |
| `full_scale_share` | ≤ 0.05 | **guard added here, not in the ruling:** `peak_steady < 1.0` alone would accept a take peaking at 0.995 in every frame |

A **silent** take prints `gain_accept no_signal` and a `note` instead of the
four criteria — never `clean` with two passing lines, which reads like partial
success and is how a capture-line failure nearly became a gain conclusion.

**The band is validated.** The first genuine take (2026-11-17, 18 %,
`assist talk`) reads `rms_steady` 0.2311 — mid-band — and `rms_variation`
1.6178, ~6.5x the threshold; the flat 20261102 rail scores ~0.17 and fails, as
designed. What it does *not* pass is clipping: `peak_steady` 1.0000, 37
full-scale frames after the start window, share 0.2284. Clipping is **graded**:
that take transcribed verbatim.

If `gain_accept pass`: record the two lines (`volume_percent`, `gain_accept`)
and stop. If it fails on `peak_steady` or `full_scale_share`, run candidate B
(12 %) and repeat Gates 2–4 into `/tmp/gain-12.wav`.

If it fails on `rms_variation` **twice, at two different gains, and
`node_is_monitor` was 0**, that is the (b) answer in a different form: something
other than the voice is holding the envelope. Stop and send both outputs — do
not keep lowering gain.

## Gate 4b — the limiter's own numbers (only if a take still clips)

The design chat asked, correctly: if a limiter were active, nothing should read
1.0000 — and 38 frames do. The answer from the code is sharper than either
"wired" or "not wired", and it needs one measurement from the journal:

- the capture limiter (`capture.SoftLimiter`, E5/F18/F27) **is** wired into the
  dictate loop, is enabled unconditionally, and is a **static** curve — knee
  0.6, ceiling 0.89, no attack and no lookahead, so it cannot swallow an onset;
- it is applied **before** the take is written (`frame = limiter.apply(frame)`
  then `wav_sink.write(frame)`), so a take produced this way **cannot contain a
  sample above ~0.89**. A pinned test runs a full-scale source through
  `dictate` and reads the saved WAV back at ≤ 0.89.

Which means: **if the take you probed really shows `peak_full 1.0000`, then that
file did not come through the limiting path** (it predates the wiring, or it was
written by another writer). Do not conclude "no limiter" from the WAV. The
evidence is the session's own line:

```
journalctl --user -u assistant --since "today" --no-pager | grep capture.levels | tail -3
```

Look for `raw_peak`, `processed_peak`, `limited_samples` (and `peak_full` /
`peak_steady`). `raw_peak 1.0` with `processed_peak` ≈ 0.85-0.89 is a working
limiter on a hot input; `processed_peak 1.0` would mean it is not. Send the
line as printed.

## Gate 4c — the VAD headroom, before going lower

Measured, not guessed: at 18 % the quiet passages run rms ~0.05-0.10 and the
2.4 s room tone ~0.049-0.074. The frame gate's threshold is
`[transcribe] vad_rms_threshold` = 0.01, so halving the gain again leaves room
tone at ~0.025-0.037 — still above the gate. The VAD is **not** the constraint
on going lower; the peaks are. The constraint that *would* bite is the
no-speech floor (`[voice] silence_floor`, a peak floor at 0.05): it reads the
steady **peak**, and even at 12 % a moderate passage peaks ~0.3.

## Restore

Back to the value recorded in Gate 1 — your own number, not the one in this
example (Gate 1 read **35.0** on 2026-11-17; the earlier readings were 31 %):

```
pactl set-source-volume alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source <gate1 volume>%
```

then `python3 scripts/capture_source_check.py` and confirm that same
`volume_percent`.

You only need to restore if you are abandoning the change; if the new gain is
good, keep it and tell me the final number so the docs record it.

## Gate 5 — does it persist?

A level can be restored from WirePlumber's own state, so a manual change need
not survive a reboot. Read the value back rather than assume it — twice:

```
python3 scripts/capture_source_check.py
```

1. **at the end of the sitting** — expect the value you set at Gate 2;
2. **after the next reboot** — same expectation.

If either re-read differs from what Gate 2 set, the change did not persist and
the real fix belongs at the session/WirePlumber level, which is a separate
packet with its own grant. Either way the re-read is the evidence: send
`volume_percent` from both.

## What this packet does not touch

- No daemon code and no `[capture] start_pop_ms` change beyond recording the
  measurement (all three takes recommended 100 ms, which is the shipped
  default). The **only** config edit is Gate 1b's `mic_target` pin — yours to
  make, with a readback as its acceptance.
- The start-transient gate stays as built — it is correct hygiene and it is
  **not** the clipping fix; nothing in this packet depends on it.
- No attribution is made for the Gemini emptiness beyond what the three files
  show: destroyed input is a sufficient cause, not a proven only-cause.

## What to send back

1. `capture_source_check.py` output (Gate 1), before anything changed — and the
   Gate 1b readback if the node had to be pinned.
2. The change that was made: old → new `volume_percent`.
3. The full `frame_probe.py … --gain-check` output for each take measured.
4. Whether `gain_accept` passed, and at which gain.
5. The Gate 5 re-reads: `volume_percent` at the end of the sitting, and after
   the next reboot.
6. For a take that still clips: the `capture.levels` journal line (Gate 4b).

Numbers only; no audio files leave your machine for this step.
