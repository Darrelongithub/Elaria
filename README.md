# Elaria — personal AI assistant

A local-first daemon on Fedora/Hyprland that transcribes by hotkey, organises
files invasively but reversibly, calls Gemini only when code genuinely can't
decide, and has a personality engine that *governs* a contextual voice —
loyal, candid, occasionally funny, and willing to say no.

Design: [`assistant-blueprint.md`](assistant-blueprint.md) (v29) ·
Setup/build order: [`GETTING-STARTED.md`](GETTING-STARTED.md) ·
Personality profile: [`humour.toml`](humour.toml)

**Status: Phase 3 built** (on Phases 0–2 + the §9-order-first `assist-voice-test`).
Dictation runs end-to-end with visible state (Waybar + overlay), and the
organiser now indexes configured roots and produces **shadow plans**:
`assist plan build` runs the Tier 0 deterministic cascade (zero API
calls) and writes a readable log of what *would* happen — nothing moves,
by construction (Phase 3 has no write path; live roots are refused).
Test suite passes with **no API key**. The real Gemini Live transport +
all Wayland surfaces are UNVERIFIED until first run on the owner's
Fedora box (Step 0; `ui/README.md` checklist). The executor is Phase 4 —
it only earns existence after shadow logs the owner agrees with.

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
uv sync --extra live          # add --extra voice later for ECAPA/openWakeWord
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

| **Surfaces (Phase 2)** | `waybar.py`, `overlay.py`, `ui/` | Event-driven Waybar (`assist status --waybar --follow`: idle/listening/transcribing/halted/mock, last-transcript tooltip, click=PTT, right-click=halt) + voice-test LED module. Overlay state machine in tested Python (`assist events --overlay`); `ui/quickshell/shell.qml` is a dumb binder (layer-shell, `WlrKeyboardFocus.None` — tests static-guard the QML). Hyprland binds in both Lua/.conf syntaxes. |

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
118 tests, all offline.

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

## Next (§9)

- **You:** Step 0 verification + key file; run `assist-voice-test` in real
  life for a few days (TV on, other voices, morning voice), label with
  `f`/`m`, tune thresholds from `report`. Targets: <1 false light-up/day,
  >95% deliberate catches. Then: Hyprland PTT binds (Step 6) + the Step 3
  A/B/C capture listening test (§10.1), one live dictation, and a
  `GEMINI_MODE=record` session so the first real fixtures exist.
- **Phase 4:** the executor — one test folder, review + undo, Tiers 1–2
  (Flash-Lite/Flash batches behind the §17 harness) wired behind it.
  Gate: shadow logs you agree with first. “File 500 files, then
  `undo --since` all of it cleanly” is the done-when.
