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
