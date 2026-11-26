# RPT-J — FIX-HW1 (BUG-HW1): daemon capture is static on real hardware

Agent J · 2026-11-26 · `reports/DISPATCH-BUGFIX-3.md` → FIX-HW1 ·
regression tests `test_bug_hw1_*`

**Verdict: root cause found, fixed in the sandbox, and it explains EVERY
evidence fact at once — including the 2026-11-15 "start pop" that predates
this bug. Confirmation on the owner's laptop is three paste-back steps
(§7). Nothing in the frozen set (wake/voice thresholds 1.75/0.75/0.5,
silence floor, limiter curve) was touched — this is capture fidelity only.**

## 1. What the owner's A/B had already closed (2026-11-26)

From `bugs.md`'s differential: target resolution acquitted (both forms hit
the same default Mic1 node at 84 %), `pw-record --rate 16000 --channels 1
--format s16 file.wav` CLEAN, and the daemon's exact raw-stdout form
(`--format s16 -`) EXPLODES when played as s16/16 kHz. The corruption is
therefore in the BYTES pw-record writes — before any daemon code touches
them. Suspects 2 (pipe framing) and 4 (processing before WavSink) cannot
manufacture static the owner heard in a daemon-free manual run.

## 2. Root cause (upstream sources read in this session)

`pw-record … --format s16 -` does **not** write raw PCM to stdout.

* PipeWire `src/tools/pw-cat.c` (read at 1.4.6 and master,
  github.com/PipeWire/pipewire mirror): the raw-pipe path
  (`setup_pipe`/`setup_raw`, `fwrite` of the stream buffer to stdout) is
  gated on **`--raw` (`-a`)**. Without it, `-` goes through
  `setup_sndfile()`: `sf_open("-", SFM_WRITE, …)`.
* `format_from_filename()` maps the filename `-` to the **AU (sunau)
  container** (1.4.6: `spa_streq(filename, "-") ? SF_FORMAT_AU :
  SF_FORMAT_WAV`; master: extension `au`), with `SF_ENDIAN_FILE` —
  AU's native order is **big-endian** PCM16 plus a **24-byte `.snd`
  header** (magic, data offset, size, encoding, rate, channels).
* libsndfile `src/sndfile.c` `sf_open()`: `strcmp(path, "-") == 0` →
  `psf_set_stdio()` — the AU stream is written to **stdout**.

So the daemon received: 24 header bytes + big-endian s16, and labelled it
raw s16le/16 kHz/mono. Reading BE as LE byte-swaps every sample — a ×256
gain with wraparound. Quiet negative samples land near +full scale, small
positive samples near −full scale: **explosive static at raw_peak 1.0**,
and no phoneme structure survives (ASR empty on every backend). The
negotiated PipeWire stream itself is fine and identical in both forms (the
stream is requested s16/16 kHz/1ch either way) — only pw-cat's **output
framing** differs. The WAV-file form is clean because the `.wav` extension
selects the WAV container, whose PCM16 is little-endian.

**Byte-count prediction (the pending `/tmp/raw.pcm` hint row resolves to
its first line): ~160024 bytes for 5 s = 24-byte header + exactly the
labelled count — "samples corrupt", not a rate or width change.**

## 3. Every evidence fact, explained

| Evidence (owner hardware) | Mechanism |
|---|---|
| "mad explosion, static", ASR empty | byte-swapped PCM: ×256 gain + wraparound destroys phonemes |
| raw_peak 1.0 pre-limiter | any sample +128 → −32768, any sample −129 → +32767 |
| 4.6 % limited (frozen limiter fires on a few % of samples) | the sparse-take spike band: this harness's 11 %-voiced take measures 5.6 % |
| byte count ≈ labelled count (~160 KB/5 s) | 24-byte AU header + BE PCM at the SAME 16 kHz/s16 rate |
| manual WAV form clean | WAV container = LE PCM16, same stream, same node |
| **2026-11-15 mute test: rms 0.007, peak 0.9981** | the AU header's rate field `0x00003E80` (16000) reads as s16le word 9 = −32706 = **0.9981** full scale, written at stream open, immune to node mute — the historical "start pop" IS this header |
| secondary: 0-byte captures on fast stops | first-frame graph warmup ~1.5 s starves quick sessions (and the old 24 header bytes could never fill a 960-byte frame read either) |

## 4. The suspects, closed

1. **stream format/rate vs the label — GUILTY, with precision**: the
   negotiated stream matches the label; pw-cat's stdout *container
   framing* (AU + BE + header) does not. Rate-only mismatch is refuted by
   the owner's ears (48 kHz misread at 16 kHz is a slow voice, not an
   explosion) and width/format mislabels (s32/f32) double or sextuple the
   byte count — the hint table's 320 KB/960 KB rows, not its 160 KB row.
2. **stdout pipe framing/alignment — ACQUITTED**: `readexactly` is
   byte-faithful (harness proves concat == stream, one xrun for the tail).
   A 1-byte-offset *source stream* does read as static, but it is excluded
   by fact: the owner's daemon-free manual run exploded too, and the AU
   form names itself (header magic + the fixed 0.9981 word) while a shift
   would be +1 byte, not +24.
3. **target resolution — ACQUITTED** by the owner's probe (same Mic1 node).
4. **processing before WavSink — ACQUITTED**: the daemon order
   (measure → frozen SoftLimiter → WavSink) is deterministic and
   byte-preserving (harness: clean in/clean out; static in/static out —
   carried, never manufactured).

## 5. The sandbox differential harness

`tests/test_bug_hw1_capture_fidelity.py` — a fake `pw-record` on PATH that
replays upstream pw-cat's dispatch faithfully (argv has `--raw` → dumps the
prepared s16le stream raw; no `--raw` → wraps it in the real AU form), fed
through the REAL `PipeWireCapture` (real spawn, real `readexactly` framing,
the frozen `SoftLimiter`, the real `WavSink`). Measured signatures (5 s
take, ~11 % voiced — the occupancy of the evidence takes; `over-knee` =
share of samples over the frozen 0.60 knee; `spikes` = isolated full-scale
samples per 1000):

| variant | bytes/5 s | peak | over-knee | spikes | fits the bug |
|---|---|---|---|---|---|
| clean s16le 16 k (what `--raw` delivers) | 160000 | 0.3535 | 0.0 % | 0.00/k | control |
| **AU mislabel (the old `-` form)** | **160024** | **1.0000** | **5.6 %** | **0.59/k** | **ALL facts** |
| 48 k s16 mislabel | 480000 | 0.3535 | 0.0 % | 0.00/k | refuted (slow voice) |
| 16 k s32 mislabel | 320000 | 1.0000 | 20.0 % | 10.02/k | count refutes |
| 48 k f32 mislabel | 960000 | 1.0000 | 2.6 % | 2.83/k | count refutes |
| odd-shift framing (+1 byte) | 160001 | 1.0000 | 5.6 % | 0.59/k | refuted (§4.2) |

Only the AU form reproduces the static shape, raw_peak 1.0, the
few-percent limited band, the labelled-count + 24 byte total, and the
0.9981 start pop at a fixed position — all at once. Tests:
`test_bug_hw1_the_au_stdout_form_reproduces_the_hardware_signature`,
`..._the_raw_fix_form_passes_the_take_through_untouched`,
`..._rate_mismatch_is_slowed_speech_not_static`,
`..._width_mismatches_are_static_but_leave_their_count`,
`..._a_misaligned_source_stream_is_static_but_names_itself`,
`..._readexactly_framing_is_byte_faithful`,
`..._the_sink_and_frozen_limiter_add_no_static_of_their_own`, plus the
guard/journal tests (`..._production_argv_asks_for_the_true_raw_stream`,
`..._container_tripwire_refuses_a_mislabelled_stream`,
`..._capture_start_journals_argv_and_stream_facts`,
`..._stream_open_journals_honest_unavailable_facts`,
`..._negotiated_stream_facts_parses_pw_dump_and_stays_honest`,
`..._zero_byte_fast_stop_is_journaled_as_starved`,
`..._detect_container_prefix_is_strict`).

## 6. The fix (capture fidelity only)

* `capture.pw_record_pcm_stream_command` now passes **`--raw`** before `-`
  — pw-cat's raw path: the stream's own s16le bytes, no container, no
  header, no byteswap, across pipewire 1.4.x–1.6.x. A build too old to
  know `--raw` exits with a usage error: fail-closed, never silent static.
* **Tripwire** `capture.detect_container_prefix`: the stream head is
  checked against strict AU/WAV header recognition; a mislabelled stream
  ends with `capture.format_mismatch` and `source.stream_mismatch` set,
  and is NEVER recorded as if it were raw PCM.
* **Self-diagnosing journal** (§4.8 schema) at capture start:
  `capture.stream_open` carries the exact argv, the expected stream facts
  and the negotiated facts from `pw-dump` (honest `not available:` off
  hardware); `capture.starved` names 0-byte captures (argv + the ~1.5 s
  warmup explanation). `assist doctor`'s level check now flags
  `container=` when the bytes are not raw.
* Untouched (frozen): wake/voice thresholds, silence floor, limiter curve
  and its knee/ceiling, `START_POP_MS`, `StartTransientGate`, `split_peak`,
  `WavSink`, the frame/stop machinery. `scripts/record_probe_take.py`
  picks the fix up automatically (it delegates to the production argv;
  its pinned test moves with the fix).

## 7. Owner-runnable differential steps (paste-back the stats)

Compatible with `scripts/capture_source_check.py` house style: read-only,
stdlib, one fact per line. Ears + `assist transcribe` are the oracle.

**A. Context (which node, what volume):**
```
python3 scripts/capture_source_check.py
```
Paste the `node`/`volume` lines.

**B. The pending byte count settles the hint row (keep `/tmp/raw.pcm`):**
```
wc -c /tmp/raw.pcm
xxd /tmp/raw.pcm | head -2
```
Expect: `160024`-ish for ~5 s (NOT 320 K/480 K/960 K), and `2e73 6e64 …
0000 0018 …` (`.snd`, offset 24) at the top. That is the AU header — the
bug in two lines of hex.

**C. A/B through production argv (old semantics vs the fix):**

First, one take through the FIXED production argv (the tool delegates to
`pw_record_pcm_stream_command`, so this is exactly what the daemon runs):
```
python3 scripts/record_probe_take.py /tmp/fixed.wav --target <node> --seconds 5
python3 scripts/frame_probe.py /tmp/fixed.wav
assist transcribe /tmp/fixed.wav
```
Then the old-vs-new raw form, for the same node, ~5 s each (speak one
sentence, Ctrl-C to stop):
```
pw-record --target <node> --rate 16000 --channels 1 --format s16 --raw - > /tmp/raw-fixed.pcm   # the fix
pw-record --target <node> --rate 16000 --channels 1 --format s16 -      > /tmp/raw-old.pcm      # the bug
python3 - <<'EOF'
import struct, wave
for name in ("raw-fixed", "raw-old"):
    pcm = open(f"/tmp/{name}.pcm", "rb").read()
    with wave.open(f"/tmp/{name}.wav", "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(pcm)
    print(name, len(pcm), "bytes")
EOF
python3 scripts/frame_probe.py /tmp/raw-fixed.wav
python3 scripts/frame_probe.py /tmp/raw-old.wav
```
Expect: `--raw` forms clean (peak_steady < 1.0, `verdict clean`, real
transcript from `/tmp/fixed.wav`); `/tmp/raw-old.wav` static (raw_peak
1.0). Ears: silence-to-voice instead of the explosion.

**D. The evidence WAVs name themselves (no recording needed):**
```
python3 - <<'EOF'
import wave
for p in ("~/.local/share/assistant/audio/20261126-165648-0f964a.wav",
          "~/.local/share/assistant/audio/20261126-171509-974193.wav"):
    w = wave.open(p.replace("~", __import__("os").path.expanduser("~")))
    head = w.readframes(12)
    words = __import__("struct").unpack("<12h", head)
    print(p, words, "peak:", max(abs(x) for x in words) / 32768)
EOF
```
Expect the byte-swapped AU header: words like
`(29486, 25710, 0, 6144, -1, -1, 0, 768, 0, -32706, 0, 256)` and
`peak: 0.9981` — sample 10 is the 16000-Hz rate field read backwards.

**E. After the fix, one daemon session:** the journal must show
`capture.stream_open … argv=… --format s16 --raw - … negotiated[…]`
(paste the line — its `negotiated[...]` now records the server-side
format for future reports), and no `capture.format_mismatch`. A quick
stop before the first frame should show `capture.starved`, not silence
without explanation.

## 8. What only the owner's hardware can confirm

* That `--raw` plays CLEAN from his Mic1 node (step C) — the sandbox
  proves the mechanism and the fix's logic; only the laptop proves the
  installed pipewire's `--raw` path behaves as its source says.
* The `/tmp/raw.pcm` byte count + `.snd` magic (step B) — the sandbox
  predicts 160024 + header; the hardware confirms which pending hint row
  closes.
* The evidence WAVs' first 12 words (step D) — predicted exactly.
* The negotiated stream facts in `capture.stream_open` from a real
  `pw-dump` (the sandbox can only journal `not available`).

## 9. Notes for the manager

* **Start pop (2026-11-15) is the same bug.** The mute-test peak 0.9981 is
  the AU header's rate field. With `--raw` there is no header, so the
  owner may later re-derive `recommended_start_pop_ms` (likely 0) via
  `scripts/frame_probe.py` and move `START_POP_MS` — his call, out of
  scope here (frozen).
* **Secondary symptom**: 0-byte captures are now `capture.starved` facts
  with the warmup explanation; the ~1.5 s first-frame latency itself is
  hardware/graph behaviour and is stated as such, not "fixed".
* No `OWNERS.yaml` edit; no threshold, floor or curve change; tests named
  `test_bug_hw1_*`; full suite green (3583 passed, 6 skipped).
