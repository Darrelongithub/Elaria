# Event mode — hardware checklist

## Quota math as built

- **Default batch route:** verified `[quota.models.transcribe-batch]` publishes
  `rpd = 25` and no TPM ceiling. It does not borrow the Live model's 20,000
  TPM. Event counter keys batch calls to the `America/Los_Angeles` quota day,
  persists each attempted provider call, and shows the next reset in EAT.
- **Tomorrow's 07:30–17:00 EAT schedule:** expected 30-minute spend is five
  calls before the 10:00 EAT reset plus 14 after it (19 total). The pre-reset
  calls share the current LA quota day with tonight's real transcription; the
  post-reset window begins fresh at 25. Keep two calls reserved in each active
  day for the closing segment. The per-minute batch ceiling is not published.
- No real 30-minute batch spike was run in this environment; no mock or
  estimated token figure is presented as a measurement.
- **Live route if selected:** verified `[quota.models.transcribe-live]` is
  **20,000 TPM**; the queue uses a 70% target (**14,000 estimated tokens per
  minute**). Oversized WAVs are split on WAV-frame boundaries into sequential
  calls at/below that estimate. Each sub-call consumes the daily call budget;
  transcript parts are stitched in source order.
- Budget exhaustion defers work and retains WAVs; it never stops capture.
- Disk estimate: 16 kHz mono s16 ≈ 115.2 MB/hour; verify free disk before
  doors open.

## Gate 2 — in-console rehearsal

- **Capture-only preflight:** run a short soak with `assist event start --no-transcribe`;
  verify rotation, durable audio-kept markers, battery warning, and sleep inhibit.
  **Soak on `--no-transcribe` costs 0 calls.**
- Then run the transcription/edit checks below with the real transport; that run
  consumes quota and must show the persisted used-today counter.

1. Start the event from the console; verify title, roster, and document path.
2. Speak for a short segment and verify the WAV and transcript appear.
3. Switch speaker from the console; verify the header changes immediately and
   the next segment receives the new label.
4. Edit a landed word **in the console**; watch the next segment land beneath
   it. Verify the edit autosaved to disk and remains after the append.
5. Stop from the console. Verify the summary and that the document and edits
   remain intact, with transcript text or an `[audio kept: …]` marker per part.
6. Repeat with transcription stalled: stop must return after the marker is
   durable and state is stopped; transcription may continue asynchronously.
7. Start an event, close/fail Quickshell, and verify capture continues while
   the fallback notice opens the live `.txt`.
8. Console home (the 2026-10-25 dress round; owner's eyeball gate, spelled out
   in `docs/console-home/hardware-gate.md`). Four looks, no commands: with
   nothing pending the shelf reads `nothing holding right now — the house is
   quiet.`; during a `--no-transcribe` event the card reads `Elaria is
   listening — <name>, M:SS into this part.`; the transcript reads as prose at
   arm's length rather than as log rows; then `systemctl --user stop assistant`
   once,
   mid-event, and confirm the failure is one plain sentence in warm text — no
   red, no code, no trace — and that it clears when the unit is started again.
   Items 1–7 are the spine and must pass either way; if they pass and this one
   does not, the dress is the bug, not the event.

## Gate 3 — one-hour capture soak

Run the battery-warning and sleep-inhibit check using `assist event start
--no-transcribe --battery-ok --segment-minutes 2`. **Soak on `--no-transcribe`
costs 0 calls.** Confirm roughly 30 boundaries, capture stats/peaks, retained
WAVs, and an audio-kept marker for every segment; do not require transcripts in
fake-transport mode.

## Venue card

> Open the .txt in your editor; edit freely above the tail; new text arrives at the bottom.

## What remains hardware-only — not claimed

The event view has **not** been rendered or exercised on the owner's Hyprland
session. Quickshell layout, focus, editable text behavior, process bindings,
and the failure fallback still need the Gate 2 rehearsal on that machine. The
real-account spike is also unmeasured here; no mock data is presented as a
provider measurement.

The console actions call the existing `assist event` handlers. Its embedded
transcript editor autosaves to the `.txt`; `Open .txt` remains available for an
external editor. Late results replace an untouched segment only when the full
following suffix is unchanged; any target/suffix edit makes them append at EOF
with an explanatory marker. `event rename` and `event export --format md|txt`
write copies; the live document is never their target. The console systemd
failure helper logs/notifies and opens the `.txt` without stopping capture. It
assumes the existing unit checkout path `~/Elaria`.

## Gate-by-gate verification status (Cluster G readback, 2026-11-19)

Code-level and contract verification ran offline (`GEMINI_MODE=mock`, no live API
key, no PipeWire audio device, no Hyprland session). Sandbox checks verify module
contracts and math only; hardware gates remain exclusively the owner's to run.

| Gate | Status | Verified in code / sandbox (`tests/test_event_*.py`) | Pending owner hardware / Z wiring |
|---|---|---|---|
| Pre-Gate 2 spike & quota math | PARTIAL (code verified; real spike pending owner) | `[quota.models.transcribe-batch]` `rpd=25` LA day, `reserve=2`, `max_attempts=3` (cap 2 retries), `deferred_retries=0`, `EventService.start` preflight reads `used_today()`. Batch spike math (`event_spike._restate_batch_math`): 30 min -> 20 calls/10 h (`headroom=5`, fits 25 RPD); 15 min -> 40 calls/10 h (exceeds 25 RPD). Historical `docs/event-spike.json` (2026-10-23 live `bidiGenerateContent` 400 failure) preserved intact. | Owner: `uv sync`, `assist doctor`, real-key 30-min batch spike on ~57 MB real WAV (`--wav`) to prove provider size/latency/token acceptance. |
| Gate 2 preflight `--no-transcribe` soak | PARTIAL (code verified; hardware soak pending owner) | `no_transcribe=True` keeps `calls_used=0` (`transport: fake — no calls will be made`), rotates WAVs, writes `audio kept:` markers, emits battery warning, and acquires/releases `SleepInhibitor` interface. | Owner: real laptop soak verifying PipeWire `pw-record`, real battery sysfs probe, and `systemd-inhibit` lock behavior. |
| Gate 2 item 1 — start, title, roster, path | PARTIAL (code verified; UI pending owner) | `EventService.start` + CLI/daemon handlers + `IF-4` verified (`387fa084...`) `event.started` / `event.segment.opened` transport shapes + deterministic `--source simulated` CLI smoke verified (`0` `pw-record` calls). | Owner: launch from Quickshell console in Hyprland; Z owes `HR-G-1` (`daemon.py` passing `on_event=self.broadcast`). |
| Gate 2 item 2 — speak, WAV + transcript | PARTIAL (code verified; mic/API pending owner) | Next-segment-opens-first rotation, `WavSink` atomic write, `capture.stats`, `NO_SIGNAL_PEAK=0.005`, ordered `.md`/`.txt` mirror appends verified. | Owner: real mic speech segment + live batch API transcript landing. |
| Gate 2 item 3 — speaker switch & label | PARTIAL (code verified; UI pending owner) | `SpeakerBook` inline marker on `batch` vs flush (`FLUSH_MIN_S=20.0`) on `transcribe-live`, `labels.json` persistence, and `event.speaker.changed` frame verified. | Owner: console `Next speaker` button + speaker label timing check. |
| Gate 2 item 4 — edit in console + tail append | PARTIAL (code verified; UI pending owner) | `EventDocument.edit_segment` CAS check (conflict tail-append), independent `.md`/`.txt` check, and Quickshell 650 ms autosave wiring verified statically. | Owner: real cursor stability & 650 ms debounced save while typing during live append in Quickshell. |
| Gate 2 item 5 — stop + intact doc/edits/markers | PARTIAL (code verified; UI pending owner) | `EventService.stop` forces pending markers before `stopped`, releases inhibitor, emits `event.stopping` -> `event.stopped`, preserves edits. | Owner: stop button from Quickshell console + visual check of `.md`/`.txt`. |
| Gate 2 item 6 — stalled transcription stop | PARTIAL (code verified; live stall pending owner) | `stop()` returns promptly with durable `audio kept:` markers while background queue resolves/defers without overwriting edited suffix; `recover_event` emits `event.recovered`. | Owner: real network-drop / stalled-API stop rehearsal on laptop. |
| Gate 2 item 7 — Quickshell crash fallback | PARTIAL (script tested; systemd unit pending owner) | `scripts/event-console-fallback.sh` passes `bash -n`, 600 s rate limit, static signal-only `notify-send` body (no path leak), stderr journal path, and `xdg-open` on `.txt` with stubbed binaries. | Owner: real `systemctl` failure drill confirming capture continues and `.txt` opens on Hyprland. |
| Gate 2 item 8 — Console home (4 looks) | HARDWARE-ONLY (owner eyeball gate) | Static QML text checks (`shell.qml` status strings) pass in `tests/test_console_home.py` / `tests/test_event_console_surface.py`. | Owner: eyeball gate in `docs/console-home/hardware-gate.md` + `systemctl --user stop assistant` mid-event. |
| Gate 3 — 1-hour capture soak (~30 boundaries) | PARTIAL (fast synthetic soak verified; 1 h laptop run pending owner) | Preflight `needs-battery-ok` -> `--battery-ok` warning, disk `<115.2 MB/h` refusal / `<10 h` warning, rotation gap <1 s, `capture.stats`, `NO_SIGNAL_PEAK=0.005` verified on synthetic clock. | Owner: real 1-hour unplugged->plugged soak with lid closed (~30 segments at 2 min) and `assist events --recent 50 --kind capture.stats`. |
| Gate 4 — far-field mic test (`docs/event-hardware-checklist.md`) | HARDWARE-ONLY | None (acoustics cannot be tested in sandbox). | Owner: real room far-field readback at panel distance. |

**Non-discrimination note:** Synthetic clock/source/mock runs cannot prove real
Gemini batch 30-min WAV payload acceptance (~57 MB), PipeWire hardware stability,
kernel `systemd-inhibit` lid-switch enforcement, Hyprland QML focus/layout, or
live daemon broadcast until `HR-G-1` lands in `src/assistant/daemon.py`.
