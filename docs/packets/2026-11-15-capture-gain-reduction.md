# Owner-run packet — capture input-gain reduction (D-B)

Issued 2026-11-15 on the design-chat ruling that follows the three frame-probe
readings. **Revised 2026-11-17** after Gate 1 ran: the source-check script had
two defects (no default config path, and it presented the system default source
as a capture target — F17 refuses exactly that), both fixed; Gate 1's output
fields changed accordingly, and a pin step is added for an unnamed node. **Owner-run by design**: a gain change on the owner's machine is the
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

## Gate 2 — the change, candidate A

Node name, from the ruling: `alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source`
(substitute your `node` value if it differs).

```
pactl set-source-volume alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source 18%
```

(Candidate values are 18 % first, then 12 %. Record the value Gate 1 printed —
on 2026-11-17 it was **35.0**, not the 31 % of the earlier readings; the input
level moved between sittings and Gate 1's number, whatever it is, is the restore
value.)

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

**Measured 2026-11-17 (Gate 1):** `node_is_monitor 0`, `node_is_mic1 1` on the
Mic1 node, with four monitor sources present on the machine (`HDMI1/2/3` and
`Speaker` sinks). Presence is normal; capture simply is not pointed at one. So
**(b) is dead for the node Gate 1 read**, and what remains is the (a) test —
gain down, envelope back?

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

Numbers only; no audio files leave your machine for this step.
