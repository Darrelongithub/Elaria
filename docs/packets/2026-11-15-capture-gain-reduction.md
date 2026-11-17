# Owner-run packet — capture input-gain reduction (D-B)

Issued 2026-11-15 on the design-chat ruling that follows the three frame-probe
readings. **Owner-run by design**: a gain change on the owner's machine is the
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
default_source <your default source>
configured_node <[capture] mic_target, or -1 if unset>
node <the node capture would open right now>
node_found 1
node_is_monitor 0
node_is_mic1 1
volume_percent 31.0
monitor_sources <count>
sources <count>
monitor_source_0 <name, if any>
note read_only
```

**Write `volume_percent` down.** It is the reversibility gate: whatever happens
below, that number restores the machine exactly.

Read three things in that output:

| field | meaning | what matters |
| --- | --- | --- |
| `node` | the node capture opens | should be `alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source` |
| `node_is_monitor` | is that node a loopback of playback? | must be `0`; `1` means the mic is not the mic and no gain change will fix it |
| `monitor_sources` | monitor sources present on the system | presence is normal (they exist on every sink); the question is only whether capture is pointed at one — `node_is_monitor` answers that |

If `node_is_monitor 1`: **stop here.** That is explanation (b) for the 20261102
flat envelope, and the fix is a wiring fix, not a gain fix. Send the output.

## Gate 2 — the change, candidate A

Node name, from the ruling: `alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source`
(substitute your `node` value if it differs).

```
pactl set-source-volume alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source 18%
```

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

## Gate 3 — one fresh take through the production chain

```
timeout 6 pw-record --target alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source --rate 16000 --channels 1 --format s16 /tmp/gain-18.wav
```

Speak one ordinary sentence while it runs (six seconds is enough for a short
one). If `pw-record` rejects `--format s16`, use `--format s16le`; if it
rejects `--target` by name, use `--target <id>` from `wpctl status`. Both are
[UNVERIFIED-HERE] — this sandbox has no PipeWire — so a refusal is information,
not failure.

**Gate 3b — the source question for the 20261102 shape, measured.** The
20261102 take's envelope never moved: peak pinned at full scale, rms in a ±0.07
band for 9.93 s. Speech does not do that. Two candidates, in order: **(a)** gain
so hot that even quiet passages saturate; **(b)** a steady loud source in the
capture path beside the voice (monitor/loopback of playback). The take you just
recorded separates them on the next step: under (a) a lower gain restores a
speech-shaped envelope; under (b) it stays flat however low the gain goes.

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

If `gain_accept pass`: record the two lines (`volume_percent`, `gain_accept`)
and stop. If it fails on `peak_steady` or `full_scale_share`, run candidate B
(12 %) and repeat Gates 2–4 into `/tmp/gain-12.wav`.

If it fails on `rms_variation` **twice, at two different gains, and
`node_is_monitor` was 0**, that is the (b) answer in a different form: something
other than the voice is holding the envelope. Stop and send both outputs — do
not keep lowering gain.

## Restore

Back to the value recorded in Gate 1 (example shows 31 %):

```
pactl set-source-volume alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source 31%
```

then `python3 scripts/capture_source_check.py` and confirm `volume_percent 31.0`.
You only need to restore if you are abandoning the change; if the new gain is
good, keep it and tell me the final number so the docs record it.

## What this packet does not touch

- No daemon code, no `config.toml` edit, no `[capture] start_pop_ms` change
  beyond recording the measurement (all three takes recommended 100 ms, which
  is the shipped default).
- The start-transient gate stays as built — it is correct hygiene and it is
  **not** the clipping fix; nothing in this packet depends on it.
- No attribution is made for the Gemini emptiness beyond what the three files
  show: destroyed input is a sufficient cause, not a proven only-cause.

## What to send back

1. `capture_source_check.py` output (Gate 1), before anything changed.
2. The change that was made: old → new `volume_percent`.
3. The full `frame_probe.py … --gain-check` output for each take measured.
4. Whether `gain_accept` passed, and at which gain.

Numbers only; no audio files leave your machine for this step.
