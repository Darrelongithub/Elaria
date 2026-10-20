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

### 1. Step 0 — quota shape (**now verified in config**)

The owner-verified shape (2026-10-20) is committed in `[quota]`:
Flash **5 RPM / 250K TPM / 20 RPD**, Flash-Lite **15 / 250K / 500**,
Transcribe Live **unlimited / 20K TPM**, batch Transcribe **25 RPD**.
`[quota] verified = true` makes `assist doctor` print these real figures and
stops the old assumed-number warning; remove the marker and the warning comes
back deliberately.

Still confirm, once, on your own account:
1. **Live** models are free-tier eligible. If they are not, **stop** —
   transcription falls back to batch (§12.7) and Phase 1 changes shape.
2. The **exact Live model id** offered to your project:
   ```bash
   assist voice models     # real models.list + the voice catalogue warm will use
   ```
   Stage A defaults to `gemini-3.8-live` (GA, Live native audio). The key is
   `[gemini] gemini_voice_model`; a TTS-preview model there is a doctor FAILURE.
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
assist status; assist cost
```

No key yet? Everything still runs — `GEMINI_MODE` defaults to **mock**
(fixtures/synthetic, zero network). That is by design (§12.9), not an error.

## What's built (Phase 0 + voice-test)

| Piece | Where | Notes |
|---|---|---|
| `assist-voice-test` (§13.10) | `src/assistant/voicetest.py` | Ring buffer (never persisted), LED (terminal + Waybar state file), event log `{ts, keyword_score, speaker_score, latency_ms}`, one-key/`label` labelling, accuracy `report` with threshold suggested *from labelled impostor data*, `corpus-check`/`enroll` for ECAPA sidecars. Models are pluggable: `--source synthetic` runs anywhere today; `pipewire`/openWakeWord/ECAPA need `--extra voice` + a trained “Elaria” model on Fedora. Baseline: consistency **0.96**, **3.9h** negative corpus. |
| Daemon (`assistd`) | `daemon.py` | asyncio, systemd `--user`, Unix socket `0600` NDJSON, no TCP. Handlers: `status/cost/ack/halt/resume/ptt.start/stop/result/ask` (`ptt.stop` acks the release immediately; `ptt.result` returns the transcript when it exists, optionally waiting). Startup recovery reports uncommitted journal intents (§4.2). |
| `assist` CLI | `cli.py` | Thin IPC client; `doctor/status/cost/halt/resume/ask/ptt`; `status --waybar` emits Waybar JSON. `doctor`/`cost` work with the daemon down. |
| Gemini client + harness | `gemini_client.py` | Models by role, per-model RPM limiter, backoff, **ledger write on every call**, cheapest-first with escalation only on *verified* failure (§17: `escalate_after_failures=2`, `max_scaffold_calls=6`). |
| Cost ledger | `store.py` + `cost.py` | SQLite `llm_calls` from day one. Free tier bills $0 — reports requests/tokens vs quota plus shadow cost at paid rates. |
| Fixture harness | `fixtures.py` | `live/record/mock`, hash-keyed replay, session-sequence fixtures for Live (Phase 1). Mock misses return deterministic **flagged-synthetic** replies. |
| Persona governor | `persona.py` | §13.2: governs *whether/when*, serious-gates read from `humour.toml`, tone read from writing (never emoji), teasing/roasting licence earned by familiarity, factual narration only. **No canned lines exist in this codebase.** |
| Safety spine primitives | `safety.py` | Policy checks (protected paths, never-overwrite→`_Conflicts`, no-`rm`, 15-min guard), blast-radius tripwire, write-ahead journal, halt flag. Executor itself is Phase 4. |
| Local ack (§18) | `persona.ack` + daemon | Pure in-process code, zero network by construction; tests assert <300ms with sockets sabotaged. Cached-audio acks arrive with TTS in Phase 2. |
| ASR seam + capture helpers | `asr.py`, `capture.py` | `live → batch → local` chain (§12.7), language pinned (`en`; Kiswahili = Phase 7 config flip), `pw-record` target trap (object.id) guarded in code. |
| **Dictation (Phase 1)** | `transcribe.py`, `live_client.py`, `cleanup.py`, `inbox.py`, `clipboard.py` | PTT session: `pw-record` frames → WAV sink (raw always kept) + rolling 30s buffer + VAD gate → Live manual-activity streaming with interim events; disconnect/GoAway → resumption + tail replay; unrecoverable → batch on the saved WAV. Silence ladder emits ONE soft check-in per segment, per-mode thresholds. Cleanup pass with diff-gate + language gate (raw is the record); note lands in the markdown inbox + `wl-copy`. `assist dictate` (terminal PTT), `assist transcribe FILE.wav`, `assist events` (overlay feed; `assist events --recent N` replays the stored persona step-log — `ptt.lifecycle`, `capture.stats` — after a hardware run, no live tail needed). Live-session fixtures are recordable *sequences* (hashes only — no audio in git). |

| **Surfaces (Phase 2)** | `waybar.py`, `overlay.py`, `ui/` | Event-driven Waybar (`assist status --waybar --follow`: idle/listening/transcribing/halted/mock/offline, last-transcript + queue/voice tooltip, click=PTT, right-click=halt) + voice-test LED module. Overlay state machine in tested Python (`assist events --overlay`); `ui/quickshell/shell.qml` is a dumb binder (layer-shell, `WlrKeyboardFocus.None` — tests static-guard the QML). Hyprland binds in both Lua/.conf syntaxes. |
| **Offline mode + one voice (Phase 8)** | `modes.py`, `tts.py`, `offline_queue.py`, `asr.py` | `assist mode auto|online|offline` distinguishes detected `OFFLINE` from deliberate `FORCED_OFFLINE`; Waybar/status show it and an in-progress session is finished before a parked switch applies. **INTERIM + AMENDED (owner decisions 2026-10-20 — the one-voice rule is deferred, not cancelled):** online conversation and replies are voiced by **Gemini native audio, `[gemini] voice = "Flare"`** — the only voice Elaria ever speaks with in normal operation. **Offline mode has no voice output at all**: replies land as text on the Waybar, overlay, notification and log surfaces. The owned local Piper voice (`en_GB-southern_english_female-low`) stays wired but **dormant** behind config, so the endgame — one locally owned voice in every mode, adopted in a single switch — needs no re-plumbing: `[tts] online_voice = "local"` (every mode) or `offline_voice = "local"` (offline speech back). A missing key, `GEMINI_MODE=mock`, or any cloud failure produces **reported silence** (`muted: true` plus the reason in `assist voice status`), never a hidden fallback and never a mystery. Nothing routes speech to a second cloud voice. Acks keep the §18 shape — one cached file lookup — warmed off the hot path, and online that file is Flare audio. Native Piper length scale only, never time-stretching; the dormant path is untouched. Offline dictation uses faster-whisper/whisper.cpp behind the §12.7 seam, always saves WAV, and queues low-confidence redo/cleanup. Tier 1/2, chat and other cloud work queue in SQLite; reconnect drains automatic items, gates downloads/external actions behind approval, and speaks a short summary. See [`docs/voice-audition.md`](docs/voice-audition.md). |

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
instead of vanishing; and offline mode is TEXT-ONLY by owner amendment
(2026-10-20) — online replies are voiced by Flare, offline replies are
never voiced. Required Phase 8 tests cover a simulated
network drop mid-dictation (offline transcript + queued Gemini redo),
forced-offline zero-network behaviour, the single-voice route plus
reported silence in both modes, and reconnect drain with external work
still approval-gated. 196 tests, all offline and keyless.

### Her voice: one name, pinned, with documented precedence

`[gemini] voice` is the whole story while online (Flare, the owner's
pick). The legacy `assist voice select` row (`tts.selected_voice`) and
`[tts] voice_id`/`model` belong to the **dormant local path only** and
are ignored online — `assist voice status` reports
`legacy_selection_ignored_online: true` instead of leaving it to be
guessed, and `assist doctor` names which voice is actually live.

Two keys, deliberately: `[gemini] allowed_voices` (default
`["Flare"]`) is the one-voice rule as data. A `voice` that is not in
that list is never silently adopted — she refuses to speak, says the
reason in `voice status`, and `assist doctor` FAILS until you either
correct `voice` or widen `allowed_voices` on purpose. Changing her
voice therefore means editing both keys and running `assist voice warm`:
spoken audio and the ack cache are keyed on the voice and model that are
actually live, so old audio can never be served under a new identity.

**Stage A (2026-10-20) — Flare is a Live voice, so native audio rides a Live
model.** The live repro (`Voice name Flare is not supported`) came from
`gemini-2.5-flash-preview-tts`. Now:
- `[gemini] gemini_voice_model = "gemini-3.8-live"` (replaces that TTS id).
- ack warm, `voice say`, command replies and conversational speech all open a
  **Live** session (`response_modalities: ["AUDIO"]`), never a TTS-preview call;
- at warm time the model is checked against a real `models.list` and the voice
  against that model's **real catalogue** (`voices.list()`, cached in the
  store). A mismatch fails with the allowed list in the error — never a
  substitution and never a mid-sentence 400;
- `voice_identity()` now says *verified* when it passes (the old code claimed
  `allowed=true` while its `reason` still said "refused … not canonical");
- `assist doctor` reads quota from config and prints `VERIFIED`, not assumptions.
- `model_transcribe_batch = "gemini-3.5-transcribe"` (dedicated batch STT, not
  Flash-Lite).

### Her console + class mode (Stage B, §19.1)

```bash
assist talk                 # the console in your terminal (interactive)
assist talk "..."           # one console turn — same conversation as voice
assist console --json       # the snapshot the Quickshell panel renders
assist console --follow     # streaming snapshots (one JSON per daemon event)
assist class on|off|toggle|status
```

One conversation, two channels: a turn started by voice continues in the
console with full context, and the reverse works too. The store has a single
conversation id; `messages.channel` records `voice` or `console` for display
only. There is no per-channel history to fork.

The console shows the conversation, pending plans, parked review/unsorted
items, the offline queue, job progress and the **holding shelf** (follow-ups and
findings that are hers to keep). The Quickshell panel lives at
`ui/quickshell/console/` and binds the same snapshot — dumb renderer, no logic.

**Class mode** is one toggle. Voice out OFF, spoken acks OFF, knocks become
silent visual pulses (Stage C), initiative restricted to urgent-only; the
console and every local tool keep working. It is visible in the console header,
in Waybar (`·class`) and in `assist status` (`class_mode`). A schedule can
*suggest* class mode, but it never switches it by itself — the toggle stays the
owner's. Spoken acks are suppressed in the daemon and the speech route reports
silence with the reason, so nothing can accidentally speak around the toggle.

### Initiative — the knock (Stage C, §19.2 as amended)

```bash
assist knock list                 # pending knocks, reason first
assist knock raise --topic tax --reason "..." --kind finding --referent "the tax folder"
assist knock accept 3             # opens console/voice with her REASON as line one
assist knock decline 3            # no follow-up on that topic, ever
assist knock later 3 --hours 24   # snooze into commitment memory
assist knock ignore 3             # same topic 3× → retired
assist knock status               # posture: budget = "none"
assist commitment add "chase the tax office"   # the user's own follow-up
```

A knock is the **only** signal that means "Elaria wants to talk". It has its own
Waybar state (`✦` / `·wants to talk`), its own notification identity
(`Elaria · knock`) and its own short sound (`ui/sounds/knock.wav`). Errors,
completions and system events never borrow it, and an AST test enforces that
`knock_signal.emit` is reachable only from the two knock handlers.

**There is no knock budget.** No daily counter, spacing rule, cooldown or rate
rationing exists anywhere — `assist knock status` says so, and the tests raise a
dozen knocks in a row without refusal. The control is the **reason gate**: a
knock requires a stored, citable reason, enforced by a `NOT NULL CHECK` in SQLite
and again in `InitiativeService.raise_knock()`. No reason → no knock.

A follow-up can only cite a commitment created by an explicit user request or an
accepted proposal (`assist commitment add …`, or "later" on a knock). She cannot
invent an obligation and then use her own invention as a reason.

**Anti-psychosis is runtime, not policy prose.** Needy framing (loneliness,
missing-you, neglect, "you haven't talked to me", simulated feelings) and
temporal initiation ("it's been three days…") are refused in the reason text and
in every rendered opener; the generation prompts carry the same prohibition and
tests lint both. A check-in needs a concrete referent; an urgency needs a real
one. Class mode restricts knocks to urgent-only and renders them as silent
visual pulses — no popup, no sound.

Decline stops that topic. "Later" writes a commitment and snoozes; when it comes
due, `assist knock due` raises a fresh knock whose reason is the user's own
request ("You asked me to chase this, and it is due…"). Ignoring the same topic
three times retires it.

### Show-off mode (Stage D, §19.3)

```bash
assist showoff status        # active? sandbox? permissions? (always [])
assist showoff exit          # owner hotkey / local stop
assist showoff demo --action write --name notes.txt
```

**Entry is voice-only, and it is the owner's.** "Elaria, show off" / "talk to
them", spoken with the owner present and verified against the enrolled
voiceprint. There is deliberately no CLI `enter`: the phrase is not the
credential, so a guest who says the same words gets nothing. A voiceprint score
below `voice_test.speaker_threshold` is refused with the reason.

Once in, exactly one gate opens: **speaker verification is off for
conversation**. Guests may talk, banter and ask what she can do; the persona
governor takes the brag register one notch up — performative confidence and
roasting *situations*, never a guest's body, accent, identity, history or real
traits. Serious-gates still win, so a stressed room gets plain speech.

Everything else stays shut:

* **Authority never transfers.** A guest request to move files, send messages,
  change settings, buy something or expose owner data is declined in character,
  counted, logged (category only — never the guest's words) and ends the demo as
  a never-list attempt. Guest turns never reach intents or tools.
* **Private memory (§16) is closed.** The only owner facts visible in this mode
  are the owner-editable `[showoff] demo_safe_facts` allowlist (empty by
  default). A "what does he usually…" probe is deflected, not answered.
* **Demonstrations are sandboxed.** They act only inside `[showoff] sandbox`
  (default `<data dir>/demo-sandbox`). The executor enforces it at the syscall
  boundary via `safety.assert_within_sandbox`; a real path is refused even if a
  plan or prompt is fooled.
* **Zero standing permissions.** Nothing is granted on entry, nothing survives
  exit, and a daemon restart closes any open session as `daemon_restart`.

Exit paths: owner stop command (voiceprint-verified), ~10-minute timeout, owner
hotkey, or any never-list attempt. On exit `assist status` reports show-off off,
`permissions: []`, and the session row keeps a summary — what the room was told,
how many guest turns were heard, how many requests were declined, why it ended —
with `audio_retained = 0`. No guest audio is kept.

### Disclosure awareness — memory is allowed, leaking is not

```bash
assist privacy status        # company present? what is withheld?
assist privacy company       # "I'm not alone" (also: `assist privacy alone`)
assist privacy toggle
```

Or just say it: **"I'm not alone"** / **"we have company"** turns awareness on;
**"I'm alone now"** / **"they've left"** turns it off. The same flips happen in
`assist talk` with `/company on|off`.

`disclosure.py` classifies what she remembers:

| Class | Example | Owner alone | Company present / show-off |
|---|---|---|---|
| `behaviour` | "files invoices on Fridays", "prefers the window seat" | speakable | **speakable** |
| `plan` | "we're going to surprise Sam Friday" | speakable | withheld |
| `secret` | passwords, PINs, API keys, card/bank, passport/ID, "keep this between us" | speakable | **withheld** |

Awareness is not a mode: voice, class mode and surfacing are unaffected. While it
is on, stored secrets and private plans are filtered out of the model's context,
and an outgoing guard checks the reply before it is spoken — so a model that
ignores the prompt still cannot read a password back to the room. A blocked
reply is replaced with a deflection and logged by category and fact id, never by
the secret's text.

A voice that is not the owner's gets **no owner memory at all** — not even in
normal mode. Probes get the deflection in character ("Oh, the boss would kill me
if I told you that."), instructions get "I only take that kind of instruction
from the boss." Speaker verification results supplied by the capture path
(`owner_verified: false`) are honoured at the same boundary.

A knock cannot carry a secret or private plan as its reason while company is
present — a knock is spoken aloud. Class mode still controls how loud it is.

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
uv run pytest        # or: python -m pytest — passes offline, keyless, ~40s
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
- **Phase 8 voice:** the online pick is made — **Flare** (`[gemini]
  voice`), and it is pinned by `[gemini] allowed_voices`. The local pick
  (`en_GB-southern_english_female-low`, see
  [`docs/voice-audition.md`](docs/voice-audition.md)) stays dormant
  behind config; download its model pair only if you mean to switch the
  endgame in (`online_voice = "local"`). Either way run
  `assist voice warm` and judge the exact-script acks, not the sample
  sentence — and after any voice change, confirm `assist doctor` is
  green on `voice routing` and that the acks you hear are the NEW voice
  (by ear: the cache key changed, so a stale file cannot answer).
  Finally verify faster-whisper or whisper.cpp on the actual
  microphone, including one forced-offline dictation and one
  Wi-Fi-drop/reconnect drill.
