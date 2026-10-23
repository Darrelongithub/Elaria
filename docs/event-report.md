# Event mode — completion report

## Capture and stop guarantee

Stop closes the capture segment, fsyncs transcript text or an explicit audio-kept
marker before it records `stopped`, and returns a done/queued summary without
waiting for remote transcription. Outstanding transcription continues on the
background queue; a late result either replaces an unchanged deferred region
when its entire displaced suffix is pristine, or appends at EOF with a marker.
The latter is deliberately conservative. Audio files remain the record of truth.

## Console editing

The event notebook has editable transcript segment bodies. Edits autosave after
a 650 ms quiet period via `assist event edit`; the daemon compares the displayed
base text before changing a segment. A stale edit is preserved as an explicit
tail copy rather than overwriting a changed region. Each live mirror (`.md`
and `.txt`) is independently checked, fsynced, and atomically updated; a
conflicting mirror gets a marked tail copy. Capture and transcription do not
await the editor. Appends remain EOF-only and preserve the edited text. The console reloads
the document only when its file fingerprint changes, so a live append does not
reset an active text cursor.

## Rename and export

`assist event rename S2 "Name"` updates the labels/roster mapping and produces
an exported Markdown copy; it never changes the live document. `assist event
export --format md|txt` makes a new copy. The console exposes the same actions.
No DOCX path or dependency was added. Rename does not apply to the live final
document, even after stop; the owner can choose to use the exported copy.

## Quota, counter, and event-day math

The configured route remains **batch**, **30-minute** segments. Verified
`[quota.models.transcribe-batch]` has a limit of **25 calls per
America/Los_Angeles calendar day** and publishes no TPM ceiling; batch does not
inherit Live's 20,000 TPM. Every provider attempt, including retries, is fsynced
to `events/transcribe-calls.jsonl`; status rebuilds the day count from that log
and displays calls used today/25 plus the next reset in EAT. A daemon restart
cannot reset usage. The last **two calls** of each quota day are held for the
closing segment; ordinary segments defer with audio-kept markers when only the
reserve remains. Retries are capped at two per segment and spend real calls.

For the scheduled **07:30–17:00 EAT (9.5 h)** event, 30-minute segmentation
expects **5 calls from 07:30 to the 10:00 EAT reset** (old quota day), then
**14 calls from 10:00 to 17:00** (fresh quota day): **19 calls total**. The
pre-reset quota also includes any real calls from tonight, so the zero-call
soak must use `--no-transcribe`; the post-reset window starts at 25, with 14
planned event calls and two held for closing. The pre-reset planned five plus
reserve two fit only if earlier real calls leave at least seven calls there;
check the live counter before event start. The batch per-minute ceiling is not
published.

If the live route is explicitly selected, its verified ceiling is **20,000
TPM** and pacing target is **14,000 estimated tokens/minute**. WAVs exceeding
the target are split at frame boundaries into sequential requests and stitched
in source order; each actual request/retry is logged.

**Real spike:** not run. This environment has no Gemini API key configured, so
no 30-minute provider request, usage-token figure, latency, or transcript
acceptance can honestly be reported. No synthetic/mock result is presented as
a measurement.

## Test status

- Full suite: **1,630 passed, 6 skipped** (baseline 1,624 before pre-event
  fixes; six new tests cover the zero-call soak, quota ledger, reserve, retries,
  and CLI/status behavior).
- Ruff: clean.
- `bash -n scripts/event-console-fallback.sh` and `git diff --check`: clean.

## Hardware-only validation — not claimed

The event view has **not** been rendered or exercised on the owner's Hyprland
session. Quickshell sizing, focus, text editing, and process bindings remain
hardware-only until Gate 2 succeeds on that machine. A measured provider spike
also requires the owner's real account; no sandbox measurement is claimed.

Gate 2 checklist: [`EVENT-MODE-HARDWARE-CHECKLIST.md`](EVENT-MODE-HARDWARE-CHECKLIST.md).
