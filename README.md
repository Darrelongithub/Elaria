# Elaria — personal AI assistant

A local-first daemon on Fedora/Hyprland that transcribes by hotkey, organises
files invasively but reversibly, calls Gemini only when code genuinely can't
decide, and has a personality engine that *governs* a contextual voice —
loyal, candid, occasionally funny, and willing to say no.

Design: [`assistant-blueprint.md`](assistant-blueprint.md) (v29) ·
Setup/build order: [`GETTING-STARTED.md`](GETTING-STARTED.md) ·
Personality profile: [`humour.toml`](humour.toml)

**Status: Phases 0–8 built** (the full §9 sequence, on the
§9-order-first `assist-voice-test`). Dictation runs end-to-end with
visible state (Waybar + overlay); the organiser indexes, plans
(Tier 0 → Tier 1/2), executes on live roots behind the §4 spine
(journal, review, undo); memory + hybrid recall answers “where's
that March invoice” locally; meeting mode records both call sides
with exact channel labels; Kiswahili flips on by config with
code-switch guards armed; offline mode keeps local dictation,
recall, Tier 0 and the one local speaking voice working while
cloud-bound work queues durably for reconnect. Test suite passes
with **no API key**. The real Gemini Live transport, Piper/
Whisper runtime quality, and all Wayland surfaces are UNVERIFIED
until first run on the owner's Fedora box (Step 0; `ui/README.md`
checklist). File execution only earns existence after shadow logs
the owner agrees with.

---

## ⚠️ Before anything live: two verifications only you can do

This code was built and tested in a headless container (no Hyprland, no
PipeWire, no API key — `assist doctor` says so honestly). On your Fedora box:

### 1. Step 0 — quota shape (the load-bearing assumption, blueprint §12.3/§11)

1. Go to **`aistudio.google.com/rate-limit`** on your account.
2. Confirm **Live** models are free-tier eligible. If they are not, **stop** —
   transcription falls back to batch (§12.7) and Phase 1 changes shape.
3. Note the real **RPM / TPM / RPD** for Flash and Flash-Lite and the **exact
   model IDs** offered. Fix the `VERIFY` values in your `config.toml`
   (from `config.toml.example`). Until then `assist doctor` correctly
   reports the quota shape as **ASSUMED, UNVERIFIED**.
4. One project, one key (§12.8 — key rotation gets projects zeroed):
   ```bash
   mkdir -p ~/.config/assistant
   printf 'GEMINI_API_KEY=your-key-here\n' > ~/.config/assistant/gemini.env
   chmod 600 ~/.config/assistant/gemini.env && chmod 700 ~/.config/assistant
   ```
   Never put the key in `config.toml`, the repo, or a chat. Mentors get repo
   access + fixtures, never credentials (§12.9).

### 2. Hyprland version → bind syntax

`assist doctor` parses `hyprctl version` for you:
- **≥ 0.55** → Lua config (`hl.bind(...)`)
- **older** → `.conf` (`bind`/`bindr`)

Both snippets are in `GETTING-STARTED.md` Step 6. Phase 0 doesn't need the
hotkey yet (`assist ptt start/stop` already ack locally); wire it in Phase 1.

---

## Install (Fedora target)

```bash
sudo dnf install -y git pipewire-utils wireplumber wl-clipboard libnotify uv
uv python install 3.12
git clone <this repo> ~/Elaria && cd ~/Elaria
uv sync --extra live --extra offline --extra tts  # local Whisper + Piper; add --extra voice later for ECAPA/openWakeWord
uv run assist doctor          # the honest check — paste into every bug report

cp config.toml.example ~/.config/assistant/config.toml   # then edit VERIFY values
cp humour.toml ~/.local/share/assistant/persona/humour.toml  # (mkdir -p first)

# Daemon under systemd --user:
mkdir -p ~/.local/bin ~/.config/systemd/user
ln -sf "$PWD/.venv/bin/assistd" ~/.local/bin/assistd
ln -sf "$PWD/.venv/bin/assist" ~/.local/bin/assist
cp systemd/assistant.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now assistant
assist status && assist cost
```

No key yet? Everything still runs — `GEMINI_MODE` defaults to **mock**
(fixtures/synthetic, zero network). That is by design (§12.9), not an error.

## What's built (Phase 0 + voice-test)

| Piece | Where | Notes |
|---|---|---|
| `assist-voice-test` (§13.10) | `src/assistant/voicetest.py` | Ring buffer (never persisted), LED (terminal + Waybar state file), event log `{ts, keyword_score, speaker_score, latency_ms}`, one-key/`label` labelling, accuracy `report` with threshold suggested *from labelled impostor data*, `corpus-check`/`enroll` for ECAPA sidecars. Models are pluggable: `--source synthetic` runs anywhere today; `pipewire`/openWakeWord/ECAPA need `--extra voice` + a trained “Elaria” model on Fedora. Baseline: consistency **0.96**, **3.9h** negative corpus. |
| Daemon (`assistd`) | `daemon.py` | asyncio, systemd `--user`, Unix socket `0600` NDJSON, no TCP. Handlers: `status/cost/ack/halt/resume/ptt.start/stop/ask`. Startup recovery reports uncommitted journal intents (§4.2). |
| `assist` CLI | `cli.py` | Thin IPC client; `doctor/status/cost/halt/resume/ask/ptt`; `status --waybar` emits Waybar JSON. `doctor`/`cost` work with the daemon down. |
| Gemini client + harness | `gemini_client.py` | Models by role, per-model RPM limiter, backoff, **ledger write on every call**, cheapest-first with escalation only on *verified* failure (§17: `escalate_after_failures=2`, `max_scaffold_calls=6`). |
| Cost ledger | `store.py` + `cost.py` | SQLite `llm_calls` from day one. Free tier bills $0 — reports requests/tokens vs quota plus shadow cost at paid rates. |
| Fixture harness | `fixtures.py` | `live/record/mock`, hash-keyed replay, session-sequence fixtures for Live (Phase 1). Mock misses return deterministic **flagged-synthetic** replies. |
| Persona governor | `persona.py` | §13.2: governs *whether/when*, serious-gates read from `humour.toml`, tone read from writing (never emoji), teasing/roasting licence earned by familiarity, factual narration only. **No canned lines exist in this codebase.** |
| Safety spine primitives | `safety.py` | Policy checks (protected paths, never-overwrite→`_Conflicts`, no-`rm`, 15-min guard), blast-radius tripwire, write-ahead journal, halt flag. Executor itself is Phase 4. |
| Local ack (§18) | `persona.ack` + daemon | Pure in-process code, zero network by construction; tests assert <300ms with sockets sabotaged. Cached-audio acks arrive with TTS in Phase 2. |
| ASR seam + capture helpers | `asr.py`, `capture.py` | `live → batch → local` chain (§12.7), language pinned (`en`; Kiswahili = Phase 7 config flip), `pw-record` target trap (object.id) guarded in code. |
| **Dictation (Phase 1)** | `transcribe.py`, `live_client.py`, `cleanup.py`, `inbox.py`, `clipboard.py` | PTT session: `pw-record` frames → WAV sink (raw always kept) + rolling 30s buffer + VAD gate → Live manual-activity streaming with interim events; disconnect/GoAway → resumption + tail replay; unrecoverable → batch on the saved WAV. Silence ladder emits ONE soft check-in per segment, per-mode thresholds. Cleanup pass with diff-gate + language gate (raw is the record); note lands in the markdown inbox + `wl-copy`. `assist dictate` (terminal PTT), `assist transcribe FILE.wav`, `assist events` (overlay feed). Live-session fixtures are recordable *sequences* (hashes only — no audio in git). |

| **Surfaces (Phase 2)** | `waybar.py`, `overlay.py`, `ui/` | Event-driven Waybar (`assist status --waybar --follow`: idle/listening/transcribing/halted/mock/offline, last-transcript + queue/voice tooltip, click=PTT, right-click=halt) + voice-test LED module. Overlay state machine in tested Python (`assist events --overlay`); `ui/quickshell/shell.qml` is a dumb binder (layer-shell, `WlrKeyboardFocus.None` — tests static-guard the QML). Hyprland binds in both Lua/.conf syntaxes. |
| **Offline mode + one voice (Phase 8)** | `modes.py`, `tts.py`, `offline_queue.py`, `asr.py` | `assist mode auto|online|offline` distinguishes detected `OFFLINE` from deliberate `FORCED_OFFLINE`; Waybar/status show it and an in-progress session is finished before a parked switch applies. All speech exits through one local Piper voice in both modes — the owner-selected `en_GB-southern_english_female-low`; Gemini Live is text-only and Gemini native audio is never Elaria's voice. Native Piper length scale only, never time-stretching; standard acks are pre-cached. Offline dictation uses faster-whisper/whisper.cpp behind the §12.7 seam, always saves WAV, and queues low-confidence redo/cleanup. Tier 1/2, chat and other cloud work queue in SQLite; reconnect drains automatic items, gates downloads/external actions behind approval, and speaks a short summary. See [`docs/voice-audition.md`](docs/voice-audition.md). |

**Definitions of done:** Phase 0 — `assist doctor/status/cost` ✓ · keyless
tests ✓. Phase 1 — “you dictate a note and it appears” ✓ in mock/simulated
mode everywhere; on Fedora with a key it's the same code path with
`pw-record` + the real Live transport (verify model/quotas first, Step 0).
Phase 2 — state visible ✓, partials render ✓ (overlay feed), no focus
steal ✓ by construction + test guards; on-screen QML rendering itself
awaits the Fedora checklist in `ui/README.md`.
Phase 3 — indexer (stdlib extraction incl. OOXML; `pdftotext`/PyMuPDF
guarded; sha256 + FTS5; `.assistant-ignore`/protected/never-send honoured),
Tier 0 cascade (folder-keyword, keyword-seed, screenshot/date rules,
content-keyword, extension class; abstains rather than guesses; frozen
taxonomy only), polling watcher with debounce, shadow logs in
`~/.local/share/assistant/shadow/`. On the test chaos tree Tier 0 placed
70% with the blast-radius tripwire correctly firing. **The human half of
Phase 3's done-when — “a week of shadow logs you actually agree with” —
is yours: configure one real root, build plans, argue with them.**
Phase 4 — executor (live-gate in code, halt per op, index-identity
re-verified, write-ahead journal → move → hash-verify → commit,
`_Conflicts/` never overwrites, trash-with-manifest, no `rm` anywhere),
review queue, `assist undo --plan/--since/<op>`, `assist verify`,
Tier 1/2 batched classification behind the §17 harness (schema-strict,
taxonomy-only, never-send = filename-only). 500-file round trip tested.
Phase 5 — §16 memory (stated vs inferred-with-evidence, inspectable via
`assist memory`, forgettable without argument), local embeddings
(stdlib hashing baseline; `sentence-transformers` extra), hybrid recall
(FTS5 + vectors + filename exactness, relevance floor, no bluffing),
and `assist ask` on the §13.4 ladder: local intents + memory at zero
tokens (`via` says which), open questions climb to the cheapest-first
harness with assembled context.
Phase 6 — meeting mode: mic + sink as separate channels, energy
segmentation, per-utterance batch transcription, You/Them channel
diarization (optional pyannote refine of the far side,
`--extra diarize` + HF_TOKEN), timestamped markdown notes.
Rehearse: `assist meeting transcribe mic.wav sys.wav`; node plan:
`assist meeting setup` (Step 3C).
Phase 7 — Kiswahili: `languages = ["sw", "en"]` +
`preserve_code_switching = true` flips it (config only, §12.4 pinned,
never auto-detected). Guards: bilingual batch prompt, proportional
(≥50%) Swahili-marker retention gate in cleanup, subset language-tag
assertion, Kiswahili intent ladder (`kumbuka`, `tafuta`, `iko wapi`,
`simama`, `rudisha`…), doctor reports guards ARMED. Swahili ASR
accuracy on your voice is a live-key Step-0 measurement.
Phase 8 — offline competence without a second personality: local
search/memory/Tier 0/undo keep working; dictation and meetings use
local Whisper with raw audio retained; cloud judgement queues
instead of vanishing; and both online/offline spoken replies use the
same configured local voice. Required Phase 8 tests cover a simulated
network drop mid-dictation (offline transcript + queued Gemini redo),
forced-offline zero-network behaviour, identical TTS backend+voice in
both modes, and reconnect drain with external work still approval-gated.
196 tests, all offline and keyless.

## §10 open decisions — defaults taken, awaiting your word

None block Phase 0 (§14). Each defaults to the blueprint's recommendation
**as config**, so overriding is a line edit, not a refactor. Confirm or veto:

| # | Decision | Default in config | Needed by |
|---|---|---|---|
| 1 | Capture source | `source = "mic"` (mix in Phase 6) | Phase 1 — settle with the Step 3 A/B/C listening test |
| 2 | Taxonomy | *(yours to freeze — `assist taxonomy suggest <root>` proposes from existing folders)* | Phase 3 → now |
| 3 | Chat surface | CLI first (`assist ask`) | Phase 2/5 |
| 4 | Shell tool | `shell = "confirm"` (allowlisted later) | Phase 4+ |
| 5 | Embeddings | local (deferred; no torch dep yet) | Phase 5 |
| 6 | Overlay toolkit | **Decided by build:** Waybar + Quickshell shipped in `ui/` | ✓ Phase 2 |
| 7 | Never-send list | `never_send_to_cloud = []` — enforced in the indexer; **fill before pointing at real folders** | Phase 3 → now |
| 8 | Diarization (pyannote) | deferred | Phase 6 |

## Debugging with mentors (§12.9)

```bash
GEMINI_MODE=record assist ask "..."   # capture exact model behaviour (needs key)
git add fixtures/ && git commit -m "repro: ..."
GEMINI_MODE=mock pytest               # mentor replays it deterministically, no key
assist doctor                         # paste this into the question, always
```

## Tests

```bash
uv run pytest        # or: python -m pytest — passes offline, keyless, ~1s
```

Tests deliberately strip `GEMINI_API_KEY` and forbid network on the ack path.
Core Phase 0 is **standard-library only**; `google-genai` (`--extra live`)
and the voice models (`--extra voice`) are lazy imports so clone-and-run
never breaks.

## Next — the human halves (§9 done-whens that code can't self-certify)

- **You, Step 0:** verify quotas + model IDs at
  `aistudio.google.com/rate-limit`, create the key file (0600), run
  `assist doctor`, one live dictation, and a `GEMINI_MODE=record`
  session so the first real fixtures exist. Then `assist-voice-test`
  for a few days (<1 false light-up/day, >95% deliberate catches),
  Hyprland binds (Step 6), Step 3 A/B/C listening test, `ui/README.md`
  on-hardware checklist.
- **You, §10 decisions:** freeze the taxonomy (`assist taxonomy
  suggest`), fill `never_send_to_cloud`, keep one root `shadow` until
  a week of logs you agree with — only then flip a TEST folder to
  `live` and rehearse file → `undo --since` before any real tree.
- **Phase 7 done-when:** after the flip, dictate code-switched
  sentences and confirm the mix survives end-to-end (the guards will
  flag loudly if the model normalises — that's them working).
- **Phase 8 voice:** the pick is made — `en_GB-southern_english_female-low`
  (see [`docs/voice-audition.md`](docs/voice-audition.md)). On Fedora,
  download its model pair, run `assist voice warm`, and judge the
  exact-script acks, not the sample sentence. Finally verify
  faster-whisper or whisper.cpp on the actual microphone, including
  one forced-offline dictation and one Wi-Fi-drop/reconnect drill.
