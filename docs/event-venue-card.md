# If X breaks at the venue — one card

The recording is the truth. Nothing below can lose the day.

| Situation | Do this | What you get |
|---|---|---|
| **Mic seems dead** (no signal in `event status` / `[seg N: no signal detected]` in the doc) | Check the cable/mute, then `assist meeting setup` to see nodes. If the node is gone, stop and restart with `assist event start --source simulated` is NOT the fix — fix the mic. Audio already on disk stays. | Segments already written are safe; `capture.stats` shows exactly when it died |
| **Wi-Fi drops** | Nothing. Keep going. The queue marks affected segments `deferred — audio kept: <path>` and retries when it can | Document keeps filling with honest markers; audio never discarded |
| **Daemon crash / laptop rebooted mid-event** | `assist event stop` (works with the daemon down) | Full document assembled from the segments + labels on disk; anything untranscribed gets its `audio kept` marker |
| **Laptop on battery** | Plug in. If you can't, `assist event start` warned you — recording continues regardless; suspend is inhibited while the event runs (`sleep_inhibit = true`) | Check `event status` → `disk` + `calls` occasionally |
| **Transcription lags behind the room** | Normal and fine — the text is convenience. Check `assist event status`: `queued` is expected to drain; `deferred` rows each carry their WAV path | Audio is already safe; text catches up or you batch it tonight |
| **Quota ran out** | Keep recording. `event status` shows `calls.used` vs `budget`. Deferred segments are listed at `assist event stop` with their WAVs | Next day's batch budget (25) is the retry pool; or: `assist transcribe <wav>` per segment |
| **Everything is on fire (Plan Z)** | `assist meeting start` (the proven path), let it run the day | You lose live text, not the day. Batch-transcribe the saved WAVs tonight |

**Stop is always safe:** `assist event stop` closes the last segment, finishes
or marks everything, prints the document path + every deferred segment with its
audio path, and releases the sleep lock.

**Where things live** (under `~/.local/share/assistant/events/`):
`<date>-<title>.md` / `.txt` — the document · `<date>-<title>/segments/` —
every raw WAV + transcript · `labels.json` — speaker labels (rename stays
lossless) · `state.json` — the resume/recovery record.
