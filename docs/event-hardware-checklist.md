# Event Transcriber — Hardware Checklist (owner, Fedora box)

Ordered, copy-paste runnable. Do these **tonight** (Gate 2 → Gate 3) and
**before doors** (Gate 4 + morning-of). Gate wording is from Blueprint v2 §8.
If a gate fails and can't be fixed in ~2 hours → **Plan Z**: `assist meeting
start/stop` captures the day; batch-transcribe the saved WAVs afterwards.

---

## 0. Before Gate 2 — one-time setup (5 min)

```bash
cd ~/Elaria
uv sync --extra live --extra offline          # google-genai + faster-whisper
assist doctor                                 # mic + pw-record + inhibit lines green
assist event status                           # verify calls used today / 25 and next reset
```

Make sure `~/.config/assistant/gemini.env` (0600) has the key and
`assist doctor` shows **voice routing / connectivity** sane. The required
30-minute batch spike must be performed once with a real key/account; this
sandbox has no API key, so no result is claimed and no mock spike is a
substitute.

## 1. Gate 2 — end-to-end on real mic (§8, verbatim)

**Zero-cost capture soak:** first run `assist event start --no-transcribe
--segment-minutes 2 --title "Gate 2 capture soak" --battery-ok`. Verify WAV
rotation, durable audio-kept markers, battery warning, and inhibit lock.
**Soak on `--no-transcribe` costs 0 calls.** Then stop and run the real-mic
transcription/edit rehearsal below; that run uses the persisted quota counter.

> **Gate 2, end-to-end on real mic** with `--segment-minutes 2`: start from the console, speak, switch speakers from the console, edit a landed word IN THE CONSOLE, watch the next segment land beneath it, then stop from the console. Confirm the document and edits are intact.

```bash
assist event start --segment-minutes 2 --title "Gate 2 rehearsal" --speakers "Me,Other"
# speak for ~5 minutes at the real mic; at least one switch:
assist event speaker next          # (or: assist event speaker "Other")
# …keep talking under the new label ~2 min, then:
assist event speaker "Me"
assist event stop
```

Confirm, in the printed document path:
- [ ] headers appear in **segment order** (`## HH:MM · Me · seg 001`, 002, …)
- [ ] the switch produced either a flush boundary (live route) or an
      inline `[→ Other @ HH:MM:SS]` marker (batch route) — **not both**
- [ ] both speakers' text is under the right label (first 1–3 s may land under
      the previous label — §4 known limitation, fix later with rename)
- [ ] `assist event status` (during the run) showed segments climbing and
      `calls.used` moving

## 2. Gate 3 — soak (§8, verbatim)

> **Gate 3, soak** (run before you sleep): 1 hour, `--segment-minutes 2` (~30 boundaries), laptop **unplugged for part of it** to confirm the battery warning, lid/idle left alone to confirm the inhibit lock holds. Inspect: segment count, no gaps > 1s, `capture.stats` peaks sane, no queue growth, no deferred segments unexplained.

```bash
# start it UNPLUGGED so the battery warning fires at you:
assist event start --no-transcribe --segment-minutes 2 --title "Gate 3 soak" --battery-ok
#   ^ confirm WARN power: ON BATTERY and transport: fake — no calls will be made
#   Soak on --no-transcribe costs 0 calls.
# now plug in, close the lid / walk away for one hour. Do NOT touch it.
```

After one hour:

```bash
assist event stop
assist events --recent 50 --kind capture.stats     # per-segment peaks/bytes
```

Confirm:
- [ ] ~30 segments (±1–2)
- [ ] no gaps > 1 s between segments (headers carry HH:MM — adjacent segments
      must abut)
- [ ] `capture.stats` peaks are sane the whole way (a flat near-zero run = dead
      mic hour — that is exactly what the log is for)
- [ ] fake-transport status shows calls used unchanged at 0; every captured WAV
      has a durable `audio kept:` marker (deferred markers are expected here)
- [ ] `event status` shows `transport: fake — no calls will be made`
- [ ] the laptop did **not** suspend (inhibit lock held — status/`doctor`)

## 3. Gate 4 — far-field (§8, verbatim)

> **Gate 4, far-field test:** read a paragraph aloud from the distance the real panel will sit (not at the mic). Judge the transcript yourself. If it's unusable, the fix is mic placement or a closer mic, not code.

```bash
assist event start --segment-minutes 2 --title "Gate 4 far field" --battery-ok
# walk to the panel's real position and read a paragraph aloud
assist event stop
```

- [ ] the transcript is usable **at the real distance** — if not: move the mic
      closer. Do not tune code.

## 4. Morning of the event

```bash
assist doctor                      # 1) environment green: mic, inhibit, disk
df -h ~                            # 2) ≥ 2 GB free (10 h ≈ 1.2 GB audio + headroom)
upower -i $(upower -e | grep BAT | head -1) 2>/dev/null   # 3) AC plugged in?
assist event start --title "<Event title>" --speakers "<A,B,C>"
# read the preflight block: mic signal, disk hours, inhibit held, route, budget
```

During the day: `assist event speaker "Name"` (bind it if you want — F3 is the
suggestion, no binds ship unasked), `assist event status` anytime.
End: `assist event stop` — it prints the document path, word count and every
deferred segment with its audio path.
