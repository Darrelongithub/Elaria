# Event Transcriber — Implementation Report (Blueprint v2, P0)

**Built:** 2026-10-22 · branch `arena/86223b1a-elaria` · for the live event in ~24 h
**Prime directive, enforced in code and tested:** transcription can fail, lag,
or run out of quota — capture may not. If audio exists, a transcript or an
explicit `audio kept: <path>` marker always comes back. No silent drops.

---

## 1. §0 Step 0 spike — which row applied

Ran `assist event spike` (one closed 10-minute WAV through the
**transcribe-live route as a batch call**). Record: [`docs/event-spike.json`](event-spike.json).

| # | Spike result | Measured |
|---|---|---|
| a | Full transcript? | yes (mock/synthetic — flagged by the harness) |
| b | Tokens for the 10-min WAV | **NOT MEASURED** — 94 estimated, `tokens_measured: false` |
| c | Wall-clock latency | 0.029 s (mock path, no network) |

**Row applied: ROW 3 (default).** This build ran in a headless container with
no `GEMINI_API_KEY`, so the spike is **ambiguous by construction** — there is no
real token figure, and the table says: *ambiguous → third row, it is the proven
engine*.

> **Row 3 as built:** route = **batch** (`gemini-3.5-transcribe`, 25 calls/day),
> segments = **30 min**, speaker switches **log inline markers and do NOT
> flush**. Nothing downstream is built on assumption beyond this default —
> all pacing constants are config (`[event]`), one line to change when the real
> spike says row 1 or 2.

**Owner action before the event (15 min):** on the Fedora box with the key in
place, run:

```bash
assist event spike --minutes 10 --out docs/event-spike.json
```

If it returns **row 1 or 2**, edit `[event] route = "transcribe-live"`,
`segment_minutes`, and `tokens_per_second` (the spike prints the measured
figure) — the queue pacing, flush behaviour and budget math all read those
keys. Re-run the Gate 2 rehearsal after any change.

### Measured tokens/segment

**None exist yet** (see above). The 32 tok/s audio-token estimate is what the
queue paces with until the spike replaces it. For planning: 30 min ≈ 1,800 s
× 32 ≈ **57.6K estimated tokens/segment**; 10 min ≈ 19.2K.

## 2. Quota math for a 10-hour day, as built (row 3)

| | |
|---|---|
| Segments | 10 h @ 30 min = **20 calls** |
| Budget | `[quota] transcribe_batch_rpd` = **25 calls/day** |
| Spare | **5 calls** for retries and anything unexpected |
| Speaker switches | inline markers — **0 calls**, no flush (rule in code + tests) |
| TPM pacing | rolling-minute cap at **70% of 20,000 TPM** (=14K/min), wait — never burst |
| Quota exhausted mid-event | capture continues; segments mark `deferred — audio kept: <path>`; nothing is discarded |
| Deferred retries | retry pool drains when idle; the batch 25/day of a later day is the reserved recovery budget |

If the real spike returns **row 1** (10-min live): 60 segments/day through the
live route (unlimited RPD, 20K TPM) — safe only if measured tokens/segment
leaves headroom at the 70% pacing cap. **Row 2**: segment length shortens until
two segments + one retry fit a 20K-TPM minute at 70%.

## 3. What shipped (P0 checklist, §2)

| P0 item | Where | Notes |
|---|---|---|
| `assist event start/stop/status/speaker` | `cli.py`, `daemon.py` handlers | start/stop/status/speaker + `event spike`; CLI smoke-tested through the real socket |
| Segment rotation, next-segment-opens-first | `event.py` `_rotate` | new WAV opens **before** the old one closes + enqueues; tested by asserting the next `seg-NNN.wav` exists at transcribe time |
| Async rate-limited queue | `SegmentQueue` | concurrency 1, newest-closed first, 70%-TPM pacing, capped attempts + backoff/jitter, deferred + retry pool drained when idle |
| Atomic `.md` + mirrored `.txt` appends | `EventDocument` | append+fsync per block; strict segment order (`OrderedAppender`); failure markers unblock the line |
| Minimal preflight | `preflight()` | mic level, disk (hard-refuse < 1 h), battery warn + confirm, inhibit lock, route + budget, speaker/roster echoed |
| Sleep inhibition | `SleepInhibitor` | `systemd-inhibit --what=sleep:idle:handle-lid-switch --mode=block` held for the event, verified in preflight, released on stop |
| Per-segment `capture.stats` | `store.log_persona_event` | node/bytes/peak/duration per segment — a dead-mic hour is visible in `assist events --recent 50 --kind capture.stats` |
| No-signal marker | `render_segment_block` | peak < 0.005 → `[seg N: no signal detected]` in the document |
| Restart recovery = assemble from disk | `assemble_event_document` / `recover_event` | daemon kill → `assist event stop` rebuilds the full document from segments + labels; untranscribed get explicit markers. **Nothing discarded** |
| `labels.json` during the event | `_write_labels` | written at start/close/switch so P2 `rename` is lossless later |

**Prime-directive tests** (red-first, 39 new tests): failure → marker + audio
path cited; out-of-order results still land in order; quota exhaustion defers
(not drops); state-file recovery assembles everything; every wait bounded.

## 4. Skipped P1/P2 (deliberately)

| Item | Tier | Status |
|---|---|---|
| Restart recovery **beyond** assemble-from-disk | P1 #1 | **skipped** — P0 recovery covers "run `event stop` and get the full document"; auto-resume with gap markers is the P1/P2 extension |
| `event export --format md\|txt` | P1 #2 | **skipped** — the live document is already mirrored as `.md` + `.txt` on every append; a separate export transform can wait |
| Quota line in `status` with running call count | P1 #3 | **landed anyway** — `event status` shows `calls.used` vs `calls.budget` + route + disk |
| `event rename S2 "Name"` | P2 | **deferred** — `labels.json` (labels per segment + roster) is written during the event, so the rename is a ~20-line document transform later, never an audio op |
| `.docx` export | P2 | **deferred** |
| Resume-capture-after-restart (new segment + gap marker) | P2 | **deferred** — recovery stops cleanly instead of resuming |

## 5. Hardware checklist — Gate 2 and Gate 3, verbatim from §8

> **Gate 2, end-to-end on real mic** with `--segment-minutes 2`: speak, switch speakers once, confirm the document fills in order.

> **Gate 3, soak** (run before you sleep): 1 hour, `--segment-minutes 2` (~30 boundaries), laptop **unplugged for part of it** to confirm the battery warning, lid/idle left alone to confirm the inhibit lock holds. Inspect: segment count, no gaps > 1s, `capture.stats` peaks sane, no queue growth, no deferred segments unexplained.

Runnable form of both (plus Gate 4) is in
[`docs/event-hardware-checklist.md`](event-hardware-checklist.md) — work
through it top to bottom. The morning-of command is
`assist event start --title "<title>" --speakers "<A,B,C>"` after
`assist doctor` is green on mic + inhibit.

## 6. Test + lint status

```
ruff check src tests scripts   → All checks passed!
GEMINI_MODE=mock pytest        → 1604 passed, 6 skipped
                                (baseline was 1565 passed, 6 skipped — zero deletions)
```

Existing `assist meeting start/stop` is untouched (event mode is a sibling,
§11). Plan Z stands: if Gate 3 fails and can't be fixed in ~2 h, run the proven
`assist meeting start/stop` for the day and batch-transcribe after — you lose
live text, not the day.
