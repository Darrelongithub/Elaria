# Personal AI Assistant — Architecture Blueprint

**Target:** Fedora + Hyprland (Wayland) · Gemini API · single user (you)
**Capabilities:** live push-to-talk transcription · invasive document organisation · tool actions · chat
**Status:** discussion document — decisions marked 🔒 are settled, ❓ are open

---

## 0. What is settled

| Decision | Value |
|---|---|
| Brain | Gemini API — **free tier, one project, one key** (see §12.8) |
| Transcription | **Live**, hotkey-initiated, streamed |
| ASR backend | **Gemini Live** (free tier); chain: live → batch → local |
| Languages | **English first.** Kiswahili deferred to Phase 7 — but the language seam stays in from day one (§12.7) |
| Data/privacy | Free-tier terms accepted (prompts may be used to improve Google's products) |
| Document handling | **Invasive** — may move, rename, and file things on disk |
| Audience | **Personal project, one owner.** Mentors/debuggers have repo access only — no credentials, no data (§12.9) |
| Platform | Fedora, Hyprland, Wayland |
| Hardware | Ultrabook, UHD 620, 8 threads — **no GPU**, so no local ASR (§12.6) |
| Budget | $0 — quota, not money, is the binding constraint (§12.1) |
| Quota strategy | **Cascade + patience, not key rotation** (§3.7, §12.8) · single key, single account (§12.9) |
| Personality | **A presence, not a butler.** Has opinions, narrates its thinking, and can say no (§13) |
| Runtime philosophy | **99% code.** Deterministic local logic by default; Gemini is a scarce specialist called only when code genuinely can't decide (§13.4) |

Because it's a solo personal tool, we skip: multi-tenancy, auth, user management, packaging for distribution, web-deployable config. That's a large saving — the complexity budget goes entirely into **the safety spine** and **latency**, which are the two things that actually decide whether you use this daily.

---

## 1. Design principles

1. **The daemon is the product.** All state, all policy, all safety lives in one long-running process. Clients (CLI, waybar, overlay) are dumb and disposable. You will rewrite the UI; you should never rewrite the safety layer.
2. **Write-ahead intent.** No file is touched before an intent record is on disk. This is what makes "invasive" survivable.
3. **Everything reversible.** There is no `rm`. There is no silent overwrite. If it can't be undone, it doesn't ship.
4. **The model proposes, the policy disposes.** Gemini never touches the filesystem. It returns structured JSON proposals; the executor validates them against policy and applies them. The LLM is an advisor, not an actor.
5. **Measure tokens from day one.** Cost visibility is Phase 0, not "later". Retrofitting observability is miserable and you'll fly blind on a per-token API.
6. **Isolate the Wayland-specific code.** Audio capture and hotkeys are the only parts that care about Hyprland. Everything else is plain Linux, so if you ever leave Hyprland you replace two modules, not the system.
7. **Code first, model last.** Every request climbs a ladder: exact command → grammar/regex parser → local rules/memory → cached answer → *only then* Gemini. The model's job is judgement, not plumbing.
8. **Personality is state and judgement, not a joke bank.** The persona engine governs *when to speak, when to shut up, how familiar to be, and where the lines are* — memory, mood, candour, pushback rules, serious-gates. It does **not** manufacture humour from canned lines. Wit, when it happens, is contextual phrasing in the moment — the way a good conversational model matches your vibe once it knows it — not a template with slots.
9. **Loyal, not sycophantic.** It works for your *informed* interests, not your momentary impulse. It may disagree, delay, or refuse — and must always say why, and what would change its mind.

---

## 2. Architecture

```
  Hyprland binds ─┐
  Waybar module ──┤   assist CLI  (thin IPC client, ~5 ms exec)
  Quickshell  ────┘        │
                           │  unix socket · newline-delimited JSON
                 ┌─────────▼──────────────────────────────────────┐
                 │        DAEMON     (systemd --user)             │
                 │                                                │
                 │  session router ── tool registry ── cost ledger│
                 │         │              │               │       │
                 │         └──────┬───────┴───────────────┘       │
                 │                │                               │
                 │        ┌───────▼────────┐                      │
                 │        │  SAFETY SPINE  │  journal · policy    │
                 │        │  (all writes   │  quarantine · undo   │
                 │        │   pass through)│  rate limits · halt  │
                 │        └───────┬────────┘                      │
                 └────────────────┼───────────────────────────────┘
                                  │
        ┌─────────────────┬───────┴────────┬──────────────────┐
        ▼                 ▼                ▼                  ▼
 ┌─────────────┐  ┌──────────────┐  ┌────────────┐   ┌──────────────┐
 │ capture svc │  │  organiser   │  │  memory    │   │ gemini client│
 │ PipeWire:   │  │  indexer     │  │ SQLite     │   │ models by    │
 │ mic/monitor │  │  watcher     │  │ FTS5       │   │ role + cost  │
 │ /mix        │  │  planner     │  │ + vectors  │   │ accounting   │
 └──────┬──────┘  │  executor    │  └────────────┘   └──────┬───────┘
        │         └──────────────┘                          │
        ▼                                                   ▼
 ┌────────────────────┐                              Gemini API
 │ gemini-3.5-        │                              (Live WS, REST)
 │ transcribe-live    │
 │ (WebSocket)        │
 └────────────────────┘
```

**Runtime:** Python 3.12+ (best ecosystem for this: `google-genai`, `watchdog`, `pymupdf`, `sqlite-vec`, `sounddevice`), managed with `uv`, run as a `systemd --user` service. Rust is the only serious alternative and its advantage is idle footprint, which is not your bottleneck — your bottleneck is how much glue code exists between five subsystems, and Python wins that decisively.

**Key idea:** the CLI is a ~5 ms IPC client, so Hyprland binds can call it freely with no startup cost. This is what lets a keybind feel instant on Wayland.

---

## 3. Component specification

### 3.1 Daemon & IPC

- Single `asyncio` process, `systemd --user`, `Restart=on-failure`.
- Unix socket at `$XDG_RUNTIME_DIR/assistant.sock`, permissions `0600`. **No TCP port, no network surface.**
- Protocol: newline-delimited JSON. Request/response plus a subscribed event stream.

**Commands**

| Command | Purpose |
|---|---|
| `ptt.start` / `ptt.stop` | Push-to-talk open/close |
| `transcribe.file` | Batch-transcribe an existing recording |
| `plan.build` | Index + propose an organisation plan (no writes) |
| `plan.review` / `plan.apply` | Inspect / execute a plan |
| `undo` | Reverse by op-id, plan-id, or time window |
| `halt` | Panic switch |
| `status` / `cost` | Health and spend |
| `ask` | Conversational turn (with tools available) |

**Events**

`transcript.interim` · `transcript.final` · `plan.proposed` · `op.applied` · `op.conflict` · `session.ended` · `error`

### 3.2 Gemini client — models by role

Gemini models differ enormously in price by tier, so each job gets its own model. This is the single biggest cost lever you have.

| Role | Model class | Rate (as of Oct 2026) |
|---|---|---|
| Live transcription | `gemini-3.5-transcribe-live` | Live audio-in pricing — see §7 |
| Batch transcription | Flash-Lite / Flash | audio-in $0.50–$1.00 / 1M |
| Organiser / classifier | Flash-Lite (structured output) | $0.25 in / $1.50 out per 1M |
| Chat, planning | flash-class default | $0.75 in / $3.75 out per 1M |
| Hard reasoning (rare) | pro-class | $2.00 in / $12.00 out per 1M |

Two hard requirements on this client:

- **A rate limiter and an exponential-backoff retry per model.** Live sockets die on 429s, and Google's tier-based quota means you *will* hit them.
- **A cost ledger written on every call** — model, tokens in, tokens out, audio seconds, cost, correlation id. Cheap to add now; impossible to reconstruct later.

Note: Pro-class models have **no free tier** — every call bills from the first one. Flash-class carries a free tier, which is where you prototype.

### 3.3 Hyprland integration

Hyprland gives you two things: keybinds, and an event socket at `$XDG_RUNTIME_DIR/hypr/$HYPRLAND_INSTANCE_SIGNATURE/.socket2.sock` (subscribe to it if you ever want the assistant to know what window you're in).

Recent Hyprland (0.55+) uses a Lua config (`hl.bind(...)`); older versions use the `.conf` `bind`/`bindr` syntax. Either way, the shape is the same, and the CLI-as-IPC-client design means your config changes are one line each.

Push-to-talk needs **press → start** and **release → stop**:

```lua
-- Lua config (Hyprland 0.55+)
hl.bind("SUPER + grave",        hl.dsp.exec_cmd("assist ptt start"))
hl.bind("SUPER + grave",        hl.dsp.exec_cmd("assist ptt stop"), { release = true })
```

```ini
# legacy .conf syntax
bind  = SUPER, grave, exec, assist ptt start
bindr = SUPER, grave, exec, assist ptt stop
```

The `release` flag on a bind is exactly the primitive push-to-talk needs — which is a real advantage here, and one that X11 hotkey daemons never gave you cleanly.

**Wayland details that will bite you**

- There is no global hotkey daemon. Use Hyprland binds. A `GlobalShortcuts` portal may exist depending on version — treat it as optional, not the plan.
- **Layer-shell overlays must set keyboard interactivity to `none`.** A floating overlay that steals focus mid-sentence is worse than no overlay.
- Run `wl-copy` / `wl-paste` for clipboard (`wl-clipboard` package); anything X11-shaped silently fails.

### 3.4 Audio capture

PipeWire, not ALSA, not raw PortAudio:

- **Mic mode:** capture the default source (`pw-record --target=<node>`).
- **Meeting mode:** capture the sink monitor (`<sink>.monitor`) to hear the *other* side, or build a virtual mix sink with `module-loopback` (mic + sink-monitor) to capture both sides in one stream.
- **Format:** 16-bit PCM, mono, 16 kHz — this is what the Live API wants natively. Resample/buffer locally so you stream clean frames.

Do **not** shell out to `parec` per chunk. Keep one capture process per session, buffered, so there's no per-chunk process-spawn jitter.

### 3.5 Streaming transcription (the hotkey path)

The Live API is the right primitive, and it happens to have exactly the feature push-to-talk needs: **manual VAD with explicit activity signalling.**

```
hotkey press
   └─► socket open (or reuse warm session)
        └─► realtimeInput.activityStart          ← you started talking
             └─► audio/pcm;rate=16000 chunks (20–40 ms frames)
                  └─► interim_input_transcription  → overlay, live
hotkey release
   └─► realtimeInput.activityEnd
        └─► input_transcription (final utterance)
             └─► journaled to transcript store → inbox .md, clipboard, memory
```

**Constraints you must engineer around:**

| Limit | Value | Mitigation |
|---|---|---|
| Continuous live session | ~10 min (audio-only Live API: 15 min rare-time) | Session resumption + reconnect |
| Connection lifetime | ~10 min | Reconnect proactively on `GoAway`; resumption handles it |
| Context window | 128k in (native audio) | Context-window compression / sliding window |
| Speaker diarization | **Not supported live** | Post-process from saved audio (§3.6) |
| Timestamps | Utterance-level only | Save audio if you need word-level |
| Response modality | TEXT or AUDIO, not both | We want TEXT |

**The reconnect gap is the thing that will annoy you.** If a session resets mid-sentence you lose the utterance. So: keep a rolling local audio buffer (last ~30 s), and on unexpected disconnect, replay the buffered tail into the new session. That's maybe 40 lines and it's the difference between "feels solid" and "drops words".

**Always save the raw audio.** Disk is free; re-transcription isn't. It enables diarization post-pass, timestamps, and "what did they actually say" re-checks.

### 3.6 Two-tier transcription

| Tier | Path | Purpose |
|---|---|---|
| Live | `transcribe-live` over WS | In-the-moment text, ~1 s latency |
| Post | `generateContent` on saved audio | Accurate pass, **diarization support**, timestamps, durable archive |

Live gets you the words now. Post gets you the *record*. For meetings this matters: the live pass tells you what's being said, and a few seconds after the call the post pass gives you a proper labelled transcript with speaker turns.

This also gives you `assist transcribe <file>` for free — same module, no extra design.

### 3.7 Document organiser

Four stages, each independently testable:

```
 indexer ──► watcher ──► planner ──► executor
 (walk,      (inotify,   (Gemini:    (policy check
  extract,    debounce,   propose     → journal
  embed)      reindex)    dest+name   → apply)
                          +confidence)
```

**Indexer.** Walk whitelisted roots. Extract text by type: PDF (`pymupdf`/`pdftotext`), OOXML (`python-docx`/`python-pptx`/`openpyxl`), plain text, images via Gemini vision (OCR only when asked — vision calls cost more than text). Compute `sha256` + mtime + size. Store extracted text for search, embeddings for semantic search.

**Watcher.** `inotify` via `watchdog` with a debounce window (files arrive in bursts — a single download fires several events). Skip temp/partial extensions (`.part`, `.crdownload`, `.tmp`) and files modified in the last N minutes.

**Planner — a four-tier cascade.** This is the single biggest quota lever in the whole system, and it's free.

| Tier | Method | API calls | Expected share |
|---|---|---|---|
| **0** | Deterministic rules: extension mapping, date prefixes in filenames (`2026-03-15_*.pdf`), keyword match against *existing* folder names, MIME type | **none** | ~70% |
| **1** | Flash-Lite classification, batch of ~50 files/request, content snippet + frozen taxonomy | few | ~25% |
| **2** | Flash on genuinely ambiguous files, batch of ~10 | fewer | ~4% |
| **3** | Local small model overnight drain — non-urgent backlog, no quota at all | none | ~1% |

Most personal file collections are far more deterministic than they look. Invoices have "invoice" in them. Screenshots have predictable names. A 2026-03 date prefix means it belongs in a dated folder. **Tier 0 costs nothing and places the majority of any archive.** The LLM should only ever see the genuinely ambiguous tail.

Worked example — a 10,000-file archive:

```
naive (10 files/request)          ~1,000 requests   ← most of a day's free quota
rules-first cascade               ~80 requests      ← 12.5× reduction, same result
```

That reduction dwarfs anything key rotation could buy, and it makes the tool *faster* too — most files never leave the machine.

Then for Tiers 1–2:

**Planner.** Batches files into single requests — filename, path, first ~N chars of extracted text, MIME, size → Gemini returns a strict JSON array:

```json
[{ "path": "…", "dest": "…", "new_name": "…", "confidence": 0.91, "reason": "…" }]
```

Enforced with a response schema. **The model may not invent new folders** — it picks from a frozen taxonomy plus a single `_Unsorted/` escape hatch, and new folders require your approval. With 1,000 files/month, this whole stage costs roughly **$0.20/month**, which is to say: don't optimise it, just constrain it.

**Executor.** Validates every proposed op against policy, journals intent, applies, verifies. See §4.

### 3.8 Memory

One SQLite file, `~/.local/share/assistant/assistant.db`. No vector database service — `sqlite-vec` plus FTS5 covers a personal corpus and keeps the daemon a single process with no port to babysit.

Tables: `conversations`, `messages`, `facts`, `preferences`, `transcripts`, `documents`, `doc_chunks` (`+ embedding`), `plans`, `operations`, `llm_calls`.

Retrieval: hybrid — FTS5 keyword + vector similarity, merged and reranked. For a personal corpus, hybrid beats pure vector by a wide margin on exact-string queries like filenames and project codes.

### 3.9 UI surface

| Surface | Role |
|---|---|
| `assist` CLI | Primary, honest interface. Scriptable, debuggable, always right. |
| Waybar module | State at a glance: idle / recording / transcribing / organising / error. Click to toggle. |
| Quickshell overlay | Floating layer-shell pill with live partial transcript. `keyboard-interactivity: none`. |
| `notify-send` | Plan proposals, conflicts, halts. |

Build in that order. The CLI and waybar module carry 90% of the value; the overlay is polish.

Toolkit note: Quickshell (Qt/QML, layer-shell native) is the modern fit for Hyprland. `eww`/`ags` (GTK) work but fight Wayland a little. None of this touches the daemon.

---

## 4. The safety spine

You said **super invasive**. That's the right ambition — but the failure mode isn't "it breaks my files", it's **"it works confidently and wrongly at scale"**. A misfiling bug that runs overnight reorganises four months of work into a taxonomy you don't recognise. Every rule below exists because of that specific failure.

### 4.1 Absolute rules

- **Never overwrite.** Destination collision with different content → both go to `_Conflicts/`. No exceptions, no "force" flag without an explicit `--i-know-what-im-doing`.
- **Never `rm`.** Deletes move to `~/.local/share/assistant/trash/` with a manifest and a retention window.
- **Never act on an unindexed or changed file.** If `sha256` or mtime differs from the index, refuse and re-index.
- **Never touch protected paths.** `~/.ssh`, `~/.gnupg`, `~/.config`, `~/.local/share/assistant`, anything with `.assistant-ignore`, any git repo with a dirty working tree, immutables, and anything modified in the last 15 minutes.

### 4.2 Journal and undo

Write-ahead intent, then act, then commit:

```sql
CREATE TABLE operations (
  id INTEGER PRIMARY KEY, plan_id INTEGER, ts TEXT,
  op TEXT,            -- move | rename | copy | mkdir | trash
  src TEXT, dst TEXT,
  sha256_before TEXT, sha256_after TEXT, bytes INTEGER,
  status TEXT,        -- intent | committed | failed | rolled_back
  error TEXT
);
```

Rows are written **before** the syscall. Crash mid-op → daemon recovery on start replays outstanding intents and repairs or quarantines.

```
assist undo <op-id>          # single operation
assist undo --plan 42        # an entire run, in reverse
assist undo --since 2h       # everything recent
assist verify --since 24h    # re-walk and check hashes match the journal
```

Undo is itself journaled, so undo is itself undoable.

### 4.3 Shadow mode (the thing that earns trust)

New roots start in `mode: shadow`. The planner runs, the executor logs what it *would* do — **nothing moves**. You read the shadow log, correct the taxonomy, and only then flip that root to `live` in config. Per-root, explicit, reversible.

After a shadow period you'll have a real distribution of the model's mistakes, which is the only honest way to set confidence thresholds.

### 4.4 Confidence gating and blast radius

| Confidence | Action |
|---|---|
| ≥ 0.90 | auto (if root is `live`) |
| 0.60–0.89 | queue → `assist review` |
| < 0.60 | `_Unsorted/` |

Plus hard caps: max N ops per run, max M per hour, and a **structural tripwire** — if a plan would move more than K% of a tree, pause everything and ask. A runaway classifier looks exactly like a legitimate big cleanup until you check the numbers.

`assist halt`, plus a Hyprland bind for it. The executor checks a halt flag between every operation. Panic must be one keypress and must be honoured within one file operation.

### 4.5 Why this is not over-engineering

Strip the safety spine from this design and you have a tool you'll run once, nervously, and then never enable again. The spine is what makes invasiveness *usable* — it's the enabling feature, not the brake on it.

---

## 5. Tool layer

Gemini supports function calling natively, so the assistant can act, not just answer.

| Tool group | Examples | Gate |
|---|---|---|
| `files` | search, read, move, rename, tag | through safety spine |
| `transcribe` | start/stop, transcribe file, mark meeting | open |
| `memory` | recall, remember fact, search docs | open |
| `web` | Gemini's built-in Search grounding | open (needs billing) |
| `shell` | run command | **confirm each time**, allowlist, no shell metacharacters |

**Architectural recommendation: shape the tool layer as MCP.** Build an internal registry with an MCP-shaped interface now, and later expose the document organiser as a genuine MCP server. Two payoffs: the organiser becomes callable from other clients (Claude Desktop, an editor), and if the Gemini API ever stops being the right brain, your toolbox doesn't get rewritten. The cost is a small amount of indirection today.

`shell` is the one genuinely dangerous tool. Confirmation-gated, allowlisted, logged. Don't give a model an unprompted `subprocess.run(shell=True)`.

---

## 6. Data layout

```
~/.config/assistant/config.toml          # policy: roots, modes, thresholds, models
~/.local/share/assistant/assistant.db    # memory, index, journal, cost ledger
~/.local/share/assistant/audio/          # raw captures (retention window)
~/.local/share/assistant/trash/          # nothing is ever rm'd
~/.local/share/assistant/quarantine/     # crashed ops, unrecoverable states
~/.local/state/assistant/log.jsonl       # structured logs
```

`$XDG_RUNTIME_DIR/assistant.sock` for IPC (never on disk).

API key in the systemd unit's `EnvironmentFile=` with `0600`, not in a repo, not in `config.toml`.

---

## 7. Where the cost actually lives

*This section was rewritten for the zero-budget constraint — see §12.*

Real rates, October 2026. Audio bills at **25 tokens/second**, i.e. 1,500 tokens per minute of speech.

| Path | Per minute of speech | Notes |
|---|---|---|
| Live API, audio in | **~$0.005** | $3.00/1M tokens |
| Batch ASR, Flash-Lite audio in | **~$0.00075** | $0.50/1M tokens, ~6× cheaper |
| Text cleanup of that minute | **~$0.0004** | 200 in + 250 out at Flash-Lite rates |
| Live API, audio out (if you add voice replies) | ~$0.018 | includes thinking tokens |

**The real asymmetry is not the rate — it's the accumulation.** Text work is discrete and bounded: you ask for a cleanup, you get a cleanup, the meter stops. Audio billed by the minute accrues for as long as the mic is open, whether or not anyone is talking. That's why the transcription path dominates the bill and everything else rounds to zero.

Second-order effects that matter more than people expect:

- **Document organisation runs ~$0.20 per 1,000 files.** Do not optimise this. Constrain it with a frozen taxonomy instead.
- **Chat on Flash-class is cents per heavy day.**
- ⚠️ Live *output* pricing **includes thinking tokens**, which produce no audio and therefore never appear in the per-minute figures. Budgeting from per-minute numbers understates the real bill.
- ⚠️ Gemini Flash sits on promotional pricing through **31 Dec 2026** at $0.75/$3.75 and is scheduled to **double on 1 Jan 2027**. The cost ledger exists so that's a line in a report, not a surprise on a statement.

**Conclusion for a metered budget: under $10/month total.** Money is not the risk; runaway loops are. Hence the rate limiter and the halt switch.

---

## 8. Failure modes

| Failure | Mitigation |
|---|---|
| Live session drops mid-utterance | Rolling 30 s audio buffer + resumption replay |
| Rate limit (429) mid-call | Per-model limiter, backoff, degrade to batch path |
| Daemon crash mid-move | Write-ahead intent + startup recovery |
| File changed since index | Hash/mtime check, refuse, re-index |
| Destination collision | `_Conflicts/`, never overwrite |
| Hallucinated transcript on silence | VAD-gated sends; never stream empty audio |
| LLM creates 400 folders | Frozen taxonomy + `_Unsorted` + tripwire |
| Overnight runaway reorganisation | Ops/hour cap, tree-percentage tripwire, halt flag |
| Transcript duplicates | Content hashing on ingest |
| Overlay steals keyboard focus | Layer-shell `keyboard-interactivity: none` |
| Cost surprise | Per-call ledger from day one |

---

## 9. Build phases

| Phase | Deliverable | Done when |
|---|---|---|
| **0** | Skeleton: daemon, IPC socket, `assist` CLI, Gemini client, **cost ledger**, **mock/record/live fixture harness** | `assist doctor`, `assist status`, `assist cost` work — and the test suite passes with **no API key** |
| **1** | Hotkey → mic → live transcription → markdown inbox + clipboard, **persona governor v0** (state, serious-gates, plain factual narration — no canned lines) | You dictate a note and it appears |
| **2** | Waybar module + Quickshell overlay | State visible, partials render, no focus steal |
| **3** | Journal + shadow mode + indexer + **Tier 0 rules cascade** (§3.7). **No writes at all.** | A week of shadow logs you actually agree with, and Tier 0 alone places >50% of them |
| **4** | Executor on one test folder; review + undo. Tiers 1–2 wired in behind it | You file 500 files, then `undo --since` all of it cleanly |
| **5** | Semantic search + memory + `assist ask` chat | "Where's that invoice from March" works |
| **6** | Meeting mode (mic+sink mix), pyannote diarization, batch transcribe | A call gets a proper labelled transcript |
| **7** | **Kiswahili.** Flip `languages = ["sw","en"]`, enable code-switching guards, re-tune cleanup prompt | Swahili dictation works end to end |

Phase 3 is where the project succeeds or fails. Everything before it is plumbing; everything after it depends on trusting the executor.

---

## 10. Open decisions

**Resolved this round:** privacy tier (free, accepted) · ASR backend (Gemini Live → batch → local) · hardware (no GPU — local ASR ruled out for primary use) · **English first, Kiswahili in Phase 7** · **no key rotation — cascade instead of aggregation (§12.8)** · **solo project with mentors: repo access only, no credential or data sharing; fixture harness for remote debugging (§12.9)**.

Still open:

| # | Decision | My recommendation |
|---|---|---|
| 1 | **Transcription source:** mic only, or mic + system audio? | Mic first (Phase 1). Add system-audio mix sink in Phase 6 for meetings. |
| 2 | **Document taxonomy:** define it yourself, or let the model derive it? | Bootstrap: cluster your *existing* folders, propose a taxonomy once, approve it, then freeze it + `_Unsorted`. |
| 3 | **Where does chat live?** CLI TUI, floating Quickshell window, or local web UI? | CLI first. Overlay chat only if the CLI becomes annoying. |
| 4 | **Shell tool: enable at all?** | Enable, confirmation-gated, allowlisted. Powerful but the one place a bad day is really bad. |
| 5 | **Embeddings:** local model or Gemini embeddings endpoint? | **Local** (`sentence-transformers`) — free, unlimited, no quota. The organiser already has a quota problem; don't make it worse. Accepts a torch dependency. |
| 6 | **Overlay toolkit:** Quickshell vs Waybar-only? | Waybar-only through Phase 2; Quickshell overlay in Phase 3 polish. |
| 7 | **Never-send list:** which folders skip the cloud entirely? | Decide before indexing. Retrofitting exclusions after everything's embedded is painful. |
| 8 | **Diarization:** worth the pyannote post-pass (§12.4)? | Phase 6. Only if you actually record multi-speaker meetings. |

---

## 11. Things to verify before writing code

1. **`gemini-3.5-transcribe-live` rate and availability** in your region/tier. Live audio-in is ~$3/1M; confirm the transcribe-live row specifically.
2. **Your Live API tier limits** — Tier 1 quotas are a real ceiling, and exceeding them returns 429 mid-session.
3. **Current Gemini embedding model ID** — names churn; check the docs rather than trusting tutorials.
4. **Hyprland version + config syntax** — Lua (0.55+) vs `.conf`.
5. **Billing on the API key** — needed for Search grounding and Pro-class models.
6. **Is the Live API actually free-tier eligible?** Reports say yes for Gemini Live audio in/out, but confirm the quota shape — a free Live tier with a small RPD would be useless for continuous streaming. Decides whether Option A in §12.3 is viable.
7. **Free-tier RPD for the exact models you pick.** Flash is ~1,500 RPD, Flash-Lite ~1,000. These are the numbers the organiser queue must be sized against.
8. **Your GPU/CPU** — decides local ASR viability (§12.6). Blocking for the transcription design.

---

## 12. Zero-budget architecture

*Added after the budget constraint was set to $0. This section overrides parts of §2, §3.5–3.6, and §7.*

### 12.1 The constraint is not money — it's quota and privacy

At $0/month the Gemini free tier is generous on paper:

| Model | RPM | TPM | RPD |
|---|---|---|---|
| Gemini Flash | 10 | 250,000 | 1,500 |
| Gemini Flash-Lite | 15 | 250,000 | 1,000 |
| Pro-class | — | — | **paid-only since April 2026** |

Two consequences follow immediately.

**Quota becomes an architectural constraint, not an error condition.** 1,500 requests/day sounds like a lot until the organiser wants to chew through 10,000 files. At a batch of 10 files per request that's 1,000 requests — most of one day's entire allowance, for one indexing run. So the organiser **must be a patient background queue that spreads work across days**, not a burst that runs when you press go. This is a design decision the free tier forces, and it's a good one regardless: it keeps blast radius small.

**The rate limiter from §3.2 is now load-bearing infrastructure**, not a nicety. On the free tier you will hit 429s routinely, and the assistant must degrade gracefully (queue, retry with backoff, fall back to a local model) rather than fall over.

### 12.2 The price that isn't money ⚠️

**On the free tier, your prompts and responses may be used to improve Google's products, including human review. On the paid tier, they are not.**

Read that against what this tool is: it transcribes your meetings, reads the full text of every document you index, and holds conversational memory about your life. "Improves Google's products, with human review" is a materially different proposition here than for a toy chatbot.

This is the actual decision at budget 0, and it deserves to be made explicitly rather than discovered later:

| | Free tier ($0) | Paid tier (~$5/month) |
|---|---|---|
| Cost | $0 | ~$5–10 |
| Rate limits | 1,000–1,500 RPD | 2,000 RPM / 4M RPD |
| Your meetings + documents | **may train Google's models, human-reviewed** | not used for training |
| Pro-class models | unavailable | available |

Neither answer is wrong. But "budget 0" and "my assistant reads all my documents" are in tension, and you should choose knowingly. **A reasonable middle: keep audio local (it's the most personal data and the easiest to keep local), and send only text to the free tier, with a strict never-send list.**

### 12.3 Verdict: the constraints converge

Three constraints arrived in sequence — zero budget, then the hardware, then the languages. They all point at the same answer, which is a good sign that it's the right one.

| | **A. Gemini Live, free tier** ✅ | **B. Local Whisper** ❌ | **C. Groq Whisper** ⚠️ |
|---|---|---|---|
| ASR cost | $0 (free tier) | $0 (unmetered) | $0 — 8 hrs audio/day |
| Streaming + partial text | **yes** | yes, if fast enough | **no** — batch only |
| **Kiswahili accuracy** | **strong** (Google's ASR leads on low-resource languages) | **~30% WER — unusable** | **~30% WER — unusable** |
| Code-switching (SW/EN) | good | **weak, and may translate** | **weak** |
| Viable on UHD 620 / 8 threads | yes (no local compute) | **no — see §12.6** | yes |
| Latency | ~1 s, live | 2–5 s per utterance (est.) | ~1–2 s after release |
| Thermals / battery | none | **severe on a 15 W ultrabook** | none |
| Diarization | not in live mode (see §12.4) | yes, but transcription is unusable | no |

**Build A. Use Gemini Live on the free tier.**

The decisive fact is the language, not the money. Google's own documentation mirrors show the **Live API is free-tier eligible with 3 concurrent sessions and 1,000,000 TPM** — far more than a single user can consume [2](https://gemini-api.apidog.io/doc-965865). So the streaming design you specified in your very first message survives the budget cut intact, and it's the only option of the three that's genuinely good at Kiswahili.

⚠️ **Verify this first.** Free-tier terms shift, and the Live quota shape is the load-bearing assumption of the entire design. Confirm on `aistudio.google.com/rate-limit` before Phase 1.

### 12.4 Why Whisper lost — the Kiswahili problem

This is worth stating precisely, because "just run Whisper locally" is the obvious zero-budget move and it does not survive contact with your language requirements.

Published Whisper WER on Swahili:

| Model | Swahili WER | Verdict |
|---|---|---|
| `small` | ~75% | **garbage** — three out of four words wrong |
| `large-v3` | ~29–31% | **unusable as a primary** — one word in three |
| `large-v3-turbo` | worse than large-v3 | turbo's 4-layer decoder has less capacity for rare linguistic patterns |

Whisper is genuinely excellent on English (~2.7% WER on clean read speech) and its low-resource performance degrades to **25–35% WER on languages with under ~1,000 hours of training data** — Swahili, Urdu, Tamil [1](https://convertaudiototext.com/blog/whisper-large-v3-explained). Google's speech models beat Whisper on exactly these languages by **5–10% WER** on the strength of proprietary training data [1](https://ucstrategies.com/news/whisper-v3-large-open-source-speech-to-text-guide-99-languages/).

There is a LoRA fine-tune of Whisper turbo targeting Swahili–English code-switching on Hugging Face, but its own model card admits the dataset is too small to establish production-grade accuracy [4](https://huggingface.co/Karsamanja/paza-whisper-large-v3-turbo-swahili-english-cs). Don't build on a research experiment.

**Also a trap worth knowing:** Whisper can silently *translate* instead of transcribe. One production team reported their pipeline falling back to a UI locale and quietly rendering French meetings into English, with the scoring script never noticing [5](https://www.reddit.com/r/speechtech/comments/1utpb5z/whisper_largev3_vs_turbo_vs_small_wer_on_10/). With Swahili in the mix, that's not a cosmetic bug — it's your transcript becoming a different document. **Always pin the language explicitly and assert the output language matches the input.**

**Diarization still works, just not from Whisper.** pyannote speaker diarization is *language-agnostic* — it labels who spoke when, independent of what was said. So the good architecture is: **Gemini transcribes (strong Swahili), pyannote diarizes locally (works on any language), merge by timestamp.** pyannote on CPU is slow but it's a post-pass — it can run overnight. That's Phase 6.

### 12.5 The "strengthen it through the API" pass

This is a real and worthwhile technique, with precise boundaries. Be clear about which side of them you're on.

**What the cleanup pass genuinely fixes:**
- Punctuation, capitalisation, paragraphing
- Filler words and false starts ("um", "uh", "you know", repeated words)
- Homophones and near-misses — *their/there*, *your/you're*
- **Proper nouns your ASR has never heard** — colleagues' names, project codenames, Nairobi place names, jargon. Feed it a glossary and this is where the biggest quality jump comes from.
- Spoken formatting commands ("new paragraph", "scratch that", "bullet point")

**What it cannot fix:**
- **Words the ASR never heard.** If the model misheard a name, cleanup can often infer it from context — but when it can't, it will produce something plausible and wrong rather than admit defeat.
- Overlapping speakers, heavy accents, technical vocabulary in noisy rooms.

**⚠️ The bilingual-specific hazard (deferred with Kiswahili).** Because we're starting English-only, these two failure modes are dormant in Phase 1 — but the prompt scaffold should still carry the instruction, because the day you flip `languages = ["sw", "en"]` in config is the day they activate. For Swahili/English code-switching there are two failure modes the prompt must actively forbid:

1. **Translation.** An LLM told to "clean up this transcript" will sometimes render your Swahili into English, because that reads as improvement to it. Your transcript quietly becomes a different document in a different language.
2. **Normalisation.** Pushing the whole transcript into one language — dropping the English loanwords that are natural in Kenyan Swahili, or anglicising Swahili syntax.

The cleanup prompt must state explicitly: *preserve the language of each passage exactly as spoken; do not translate; do not convert code-switched speech into a single language; when in doubt, change nothing.* And the diff-gate should additionally assert the language mix is preserved — not just the character count.

**The other failure mode it introduces:** an LLM asked to clean up a transcript will sometimes *improve* it into being incorrect — smoothing over a hesitation you actually made, or substituting a sensible word for the strange one you really said. For dictation this is an annoyance. For anything you'll rely on later it's corruption.

Mitigations, all cheap:
1. **Always store raw and cleaned side by side.** Raw is the record; cleaned is the convenience. Never destroy the original.
2. **Low temperature, strict prompt, explicit "do not add or remove content" instruction.**
3. **Diff-gate**: if the cleaned text differs from raw by more than N%, flag for review. Large divergence means the model rewrote rather than repaired.
4. **Language-check gate**: assert the Swahili/English mix survived. A translated transcript is a failure, not a cleanup.
5. **Log both plus the model id** in the transcript table, so a bad batch is discoverable and re-runnable.

Budget note: this pass costs ~$0.0004 per minute of speech, and on Flash-Lite the free tier covers it outright. **The strengthening pass was never the expensive part — the audio was.** Your instinct was right, for a slightly different reason than it might have looked.

### 12.6 Hardware verdict — settled, and it rules out local ASR

Your `lspci` settles it:

- **GPU: Intel UHD Graphics 620** — integrated Whiskey Lake graphics. No CUDA, no ROCm, no usable compute for Whisper. CUDA is out entirely.
- **CPU: Whiskey Lake-U, 8 threads** — a ~15 W ultrabook part, roughly 6–7× slower than the desktop 8-core chips those "35× realtime" benchmarks are measured on. Expect **~2–5× realtime on `large-v3-turbo` at INT8** (estimate, not measured — and Whiskey Lake lacks AVX-512 and VNNI, so it won't hit modern INT8 throughput).
- RAM unknown, but ~3 GB for `large-v3` on an ultrabook is worth checking with `free -h`.

Practically that means a 10-second utterance takes 2–5 seconds to transcribe, and `small` — the only model fast enough to feel responsive — is **75% WER on Swahili**. There is no configuration of this laptop where local Whisper is usable for your languages.

**And the thermals matter as much as the speed.** Running continuous `large-v3` inference on a 15 W U-series chip means the fan spins up during every meeting, the package throttles within minutes, and battery life collapses. Even if the accuracy were acceptable, you would not want this running daily on this machine.

Verdict: **local ASR is an offline-only emergency fallback on this hardware.** It is not the primary path, and it will not handle Swahili. Plan accordingly.

### 12.7 The ASR seam (and the upgrade path)

ASR sits behind a single interface, so the backend is a config change rather than a rewrite. Build the fallback chain now — it's cheap, and it's what keeps a quota-exhausted day from breaking your workflow:

```
gemini_live  ──429 / disconnect──►  gemini_batch  ──offline──►  local
 (primary)                          (same quality,             (small,
  streaming                          ~1–3 s latency)            English only)
```

```toml
[asr]
primary   = "gemini_live"     # free tier: 3 concurrent sessions, 1M TPM
fallback  = ["gemini_batch", "local"]
offline_model = "small"       # English only — Swahili is not viable offline
languages = ["en"]           # Phase 1: English only. Add "sw" in Phase 7.
                             # Pinned explicitly, never auto-detected.
preserve_code_switching = false  # flip to true with sw+en in Phase 7
assert_output_language  = true   # catches silent translation
```

Two things this buys you:

- **Quota exhaustion degrades instead of failing.** When Live returns 429, the utterance still gets transcribed — a second later, via the batch path.
- **The budget decision stays reversible.** If you later add $5/month, swapping in a paid tier or a different provider is a line in this file. Nothing above the seam changes.

That seam is the most valuable abstraction in the transcription stack. Build it in Phase 1, not later.

### 12.8 Quota economics — why more keys is the wrong lever

The instinct is sound: the free tier is the binding constraint, so widen it. But working through the mechanics shows this solves the wrong problem, at a price you shouldn't pay.

**Fact 1: rate limits are enforced per *project*, not per API key.** Google's own documentation is explicit [3](https://gemini-api.apidog.io/doc-965865), and every independent source agrees: *"Creating multiple API keys within the same project → Ineffective; all keys share the same quota pool"* [2](https://help.apiyi.com/en/gemini-3-1-pro-429-rate-limit-quota-exceeded-fix-guide-en.html). So adding keys to your project gains exactly nothing.

**Fact 2: separate projects is a ToS violation, and Google enforces it.** Making new projects *does* technically create separate quota pools — and that's the trap. Google treats this as quota circumvention, and real developers are getting caught:

> *"I received a policy violation notice stating that my project was allegedly involved in attempts to circumvent quota restrictions by operating multiple projects as a single project."* [3](https://discuss.ai.google.dev/t/gemini-api-project-restricted-for-quota-circumvention-appeal-pending/175958)

> *"Quota limit value: 0 ... The effective general Gemini API request limit for the project is currently zero."* — appeal pending, weeks later [5](https://discuss.ai.google.dev/t/gemini-api-project-wide-quota-set-to-0-rpm-after-policy-notice-appeal-still-pending/176359)

Note what happens when it goes wrong: the project is **zeroed**, not throttled. Not a soft limit you can wait out — total loss of API access, with appeals sitting unanswered. And there's a further wrinkle: some reports say quota actually tracks the **Google account tier**, not the project, so a brand-new project can inherit the same block immediately [4](https://www.aiqnahub.com/why-my-gemini-api-quota-exceededis/). To reliably multiply quota you'd need separate *Google accounts*, which is a clearer violation still.

**Fact 3 — the asymmetry that settles it.** You'd be risking a **total, possibly permanent** loss of the assistant's API access, in exchange for quota you mostly don't need. If your project gets zeroed, the Live transcription path — the part that works fine on one key — dies with it. That's a catastrophic trade for a marginal gain.

**Fact 4 — and this is the good news — you probably don't need the extra quota at all.**

| Path | Free allowance | Your actual usage | Headroom |
|---|---|---|---|
| **Live transcription** | 3 concurrent sessions, **1,000,000 TPM** | 1 session, 1,500 tokens/min | **~600×** |
| Organiser (naive) | ~1,000–1,500 RPD | ~1,000 req for a 10k archive | tight, once |
| Organiser (cascade, §3.7) | same | **~80 req** | comfortable |
| Chat | ~1,000–1,500 RPD | tens/day | ample |
| Embeddings | — | **local, zero quota** | unlimited |

Read the first row again. The Live API is limited by **concurrent sessions** and **tokens per minute** — there is no RPD ceiling on it at all. You are one person with one microphone, consuming 0.15% of the TPM budget. **Live transcription was never the quota problem.** It was already ~600× oversupplied.

The only genuine pressure point is the organiser's one-time archive pass — and the cascade in §3.7 cuts that by 12.5×, for free, without touching anyone's terms of service.

**So the plan stands: one project, one key.** Spend the effort on the cascade instead. It's more effective, it's faster, most files never leave your machine, and it can't get your project zeroed.

If you ever genuinely exhaust the free tier: **wait for the reset** (RPD resets midnight Pacific), let the fallback chain (§12.7) absorb it, drain the backlog overnight via Tier 3, or pay the ~$5/month. All four are legitimate, and all four are recoverable. A zeroed project isn't.

### 12.9 Development, debugging, and mentors

*Revised twice. Earlier versions assumed a borrowed credential, then a co-development partnership. It's neither — it's your project, with people helping you debug. That's simpler, and it changes what matters.*

**Credentials: nothing to share.** One project, one key, yours. Mentors don't need a key to help you, and you shouldn't give them one. The single exception is legitimate and trivial: if a mentor wants to exercise the real API on his own machine, he makes **his own free project and key** in ten minutes. That's his credential serving his use — not a workaround, just setup.

**What mentors actually need is the ability to run your code without your key.** That's an architecture requirement, and it's the same requirement as "your test suite must not need an API key" — but for LLM work it goes considerably deeper than testing hygiene.

#### Fixtures are mandatory, not optional, for an LLM app

This is the part that's genuinely easy to miss.

**An LLM system is non-deterministic.** The same input produces different output on every call, and often with no way to tell why. So the ordinary debugging loop — reproduce, inspect, fix, verify — **does not work**. You cannot reproduce a bug by running the same command again. It comes back different, or it comes back fine, and you learn nothing.

The only way to debug an LLM system is to **freeze the model's responses** and replay them:

```
GEMINI_MODE = live | record | mock

live     normal operation — real API, real responses
record   real API, and every request/response pair is saved to fixtures/
mock     no network at all — replays recorded fixtures
```

Fixtures are keyed by a hash of the request, so a replayed call returns exactly what it returned the day you recorded it. Now the bug reproduces every time, and you can step through *your* logic with the model's behaviour held constant.

Three things this unlocks:

- **Mentors can debug everything without a key.** They clone the repo, run `GEMINI_MODE=mock`, and get your exact behaviour. They see the same failure you see.
- **A bug becomes reportable.** "Here's the fixture and here's the trace" is a reproducible artifact. "It sometimes messes up the filing" is not.
- **Your quota is safe.** Mock mode makes zero API calls. A mentor running the test suite cannot burn your free tier by accident.

**Be honest about the cost:** fixtureing the **Live API is genuinely harder** than fixtureing REST calls, because a streaming session is a sequence of websocket messages, not one request/response. You'll need to record the full message sequence per session and replay it as a script. Budget real time for this — but build it in Phase 1, because the Live path is the piece you most need to debug and the least able to reproduce by hand.

The same discipline pays off for the organiser: a folder of fixture files covering the awkward cases (duplicate names, ambiguous dates, PDF-only scans, weird encodings) is worth more than any amount of prompt tweaking.

#### Guardrails, so nobody burns your quota

Mentors debugging on your machine is the realistic accident risk. Three cheap defences:

1. **No key in the repo, ever.** Clone-and-run gets mock mode, not a live connection. This falls out of Step 1 of `GETTING-STARTED.md` for free.
2. **Default to mock when no key is present**, rather than erroring out. A missing key should mean "no network", not "crashes on import".
3. **The rate limiter and daily cap from §12.1 apply to everyone**, including you. A runaway loop is a runaway loop regardless of who wrote it.

#### What this means for the build

Keeping it a solo project — with helpers — means you *don't* need per-user config, per-user data directories, or any of the multi-tenancy machinery I sketched earlier. Your paths, your key, your `~/.local/share/assistant/`.

What you *do* want:

- **Clean module boundaries.** Mentors are most useful when they can debug one layer at a time — that's what the `asr` seam (§12.7) and the safety spine already give you.
- **`assist doctor` output in every bug report.** Shared vocabulary for "what state is your machine in".
- **Fixtures + mock mode** (above) — the thing that actually makes remote debugging possible.
- **Small, frequent commits.** A mentor staring at a 2,000-line diff isn't debugging, he's reading.

---


## 13. Personality — an AI friend, not a boring assistant

> The product difference. Everything before this section describes a competent assistant. This section describes the thing you actually asked for: a presence in the machine — opinionated, funny when it lands, honest when it's awkward — that happens to also organise your files.

### 13.1 What "personality" means here, concretely

Not a system prompt that says "be witty." Four mechanisms, all buildable:

1. **It narrates its thinking.** While working, it comments on what it sees — like Jarvis mid-task, not a progress bar:
   > "That folder's a mess. 43 PDFs, mostly invoices — I'll sort by issuer. Six of them are ambiguous; parking those for you rather than guessing."
   
   This is *transparent reasoning*, generated from real task state (counts, tiers, confidence). Never fake chain-of-thought, never filler.

2. **It has standing opinions.** Encoded preferences about your world, learned and explicit: your naming conventions, your folder taxonomy, "you hate notifications after 22:00", "you always regret bulk-renames". Opinions live in memory and *bind* future behaviour.

3. **It can say no.** Three grades of no (§13.3). This is the feature that separates a friend from a vending machine.

4. **It remembers the relationship.** Familiarity grows: early on it's careful and explanatory; over months it gets terse, teasing, and proactive. Same engine, evolving state.

### 13.2 The persona engine — a governor, not a comedian

**Design correction, made explicitly:** an early draft had the engine speaking from a *voice-line template bank*. That is exactly how you get a ChatGPT with no humour that thinks it's funny — canned quips, rotated so they don't repeat, landing like a screensaver. **Cut.** There is no joke bank. There will never be a joke bank.

What the user actually likes about a good conversational model (the Claude pattern) is not jokes — it's **vibe-matching**: it reads the room, matches your energy, is funny *because the moment is funny*, serious the instant it isn't, and never performs at you. That quality comes from context + restraint, not scripting. So the engine is split:

```
   ┌──────────────────────── PERSONA ENGINE (local code) ───────────────────────┐
   │  GOVERNS: should it speak at all? · serious-gate active? · familiarity      │
   │           candour level · pushback warranted? · joke opportunity REAL?     │
   │  KNOWS:   your humour profile · your history · time, mood, session state   │
   │  NEVER:   writes jokes · rotates quips · fills mad-libs with your filenames │
   └───────────────────────────────┬────────────────────────────────────────────┘
                                   ▼  (only when expression is actually needed)
   ┌──────────────────── EXPRESSIVE VOICE (contextual) ─────────────────────────┐
   │  In conversation/banter: the model phrases it, guided by humour.toml +     │
   │  the immediate context. Humour emerges or it doesn't — silence is a        │
   │  valid, common output.                                                     │
   │  In routine tasks: mostly plain, factual narration from real state.        │
   │  A dry observation arising from the actual data is allowed; a             │
   │  pre-written gag is not.                                                   │
   └─────────────────────────────────────────────────────────────────────────────┘
```

Rules that keep it Claude-like instead of ChatGPT-like:

- **Restraint is the default.** Most turns: no joke attempted. The engine's most frequent humour decision is "not now."
- **No humour-only model calls.** It never spends a Gemini call just to generate a quip about a finished task. If a call is already happening (chat, a summary, a plan), personality may colour that response for free.
- **Context or nothing.** Any funny line must be about *this* moment — this file, this hour, your actual history. If it could be said to anyone, it's banned.
- **Match, don't perform.** If you're terse, it's terse. If you're riffing, it volleys. If you're stressed, the gates in `humour.toml` shut humour off entirely.
- **Factual templates exist only for facts.** "Sorted 32 files, 4 need review" may vary its wording mechanically; it will not have a punchline bolted on.

This still satisfies "99% code": the *governor* is all code, and routine operations stay model-free. What's conceded — deliberately — is that genuine wit in open conversation is a model behaviour, used sparingly, exactly the way a person doesn't rehearse being funny with their friends.

### 13.3 The three kinds of "no"

This is the heart of it. A friend who never pushes back is just a mirror.

| Grade | Trigger | Behaviour | Example |
|---|---|---|---|
| **Hard no** | Safety spine (§4): protected paths, destructive ops, `rm` | Refuses. Non-negotiable, explains the rule | "No. That's `~/.ssh`. Nothing touches that — not you, not me, not at 3am." |
| **Pushback** | Legal but probably against your own interests: bulk move at 1am, sending a heated message, renaming 400 files on a hunch, acting on a low-confidence plan | States its objection + evidence, offers the safer version, **accepts a deliberate override** ("do it anyway") | "You want me to text Kamau *that*? Read it back first. …Still yes? Say 'send it anyway' and it's gone." |
| **Taste no** | It has a standing opinion and the stakes are low | Declines playfully or counter-proposes; folds instantly if you insist | "Organise Downloads? Again? It's 60% installers you never ran. Archive the lot, sort the rest — trust me." |

Design rules for pushback, so it stays a friend and never becomes Clippy-with-authority:

- **Evidence or it doesn't push back.** Every objection cites something real: the clock, your history, a confidence score, a rule you set. Vibes-based nagging is banned.
- **Override is always one phrase away** (except hard no). It argues once, clearly — then obeys. It never sulks, never re-litigates the same decision twice in a session.
- **Frequency budget.** Pushback is rationed (e.g. taste-no at most a few times a day, and never twice in an hour). Scarcity is what makes it land.
- **It can be wrong gracefully.** If you override and you were right, it logs that and lowers that rule's confidence. The relationship learns in both directions.
- **Candour is a dial** (`candour = 0..1` in config): 0 = polite butler, 1 = the friend who tells you the draft is bad. Default somewhere honest-but-kind; you tune it.

### 13.4 99% code — the local-first runtime

Your instinct, formalised. Gemini's free tier is genuinely usable — but a personality that calls the cloud to say "done" would burn quota on chatter, feel laggy, and die offline. So:

**The escalation ladder** — every request climbs only as high as it must:

```
 1. exact command          ("status", "halt", "undo")            → code
 2. grammar / regex intent ("organise downloads",                → code
                            "transcribe that", "remind me…")
 3. local rules + memory   (Tier-0 cascade, FTS memory lookup,   → code
                            persona engine, schedules)
 4. cache                  (same question/file seen before)      → code
 5. LOCAL small model*     (optional, later — classification)    → code-ish
 6. GEMINI                 (ambiguous intent, open chat,         → tokens
                            Tier 1/2 classification, cleanup,
                            summaries, novel judgement)
```

\* The UHD 620 can't run much, but tiny CPU tasks (intent classification, embeddings) are feasible later. Not Phase 1.

**What that means in practice:**

| Workload | Code % | Gemini's role |
|---|---|---|
| Hotkey, capture, session control | 100% | none |
| Routine commands & tool actions | ~100% | none |
| Persona narration ("thoughts") | ~95–100% | novel situations only |
| Document organising | ~70–96% | Tier 1/2 ambiguous files only (§3.7) |
| Transcription | ASR is Gemini Live | — but cleanup only when worth it |
| Memory recall | 100% local (SQLite FTS) | summarising memory, rarely |
| Open-ended chat / advice | ~0% | this is what the model is *for* |
| Pushback decisions | ~100% | rules + your history; LLM only to phrase a tricky one |

**Token governor.** A local budgeter in front of every model call asks: *is this worth a request?* It enforces the daily soft cap, batches aggressively, dedupes identical requests, serves cache first, and — critically — **can say "no, do it with code" to the rest of the system**. `assist cost` should normally show a near-flat line on days you only gave commands. The day it spikes is the day you actually had a conversation.

**The honest exception:** transcription itself is a Gemini Live session, and open chat is inherently model work. "99% code" governs *decisions and personality*, not physics. The design target: **≥95% of non-transcription interactions complete with zero generative-LLM calls.**

### 13.5 Proactivity (bounded, or it's just nagging)

A friend notices things. Within hard bounds:

- **Notices:** "You've dumped 200 files in Downloads this week — want the usual sort?" · "That meeting transcript mentions a deadline nobody wrote down."
- **Bounds:** quiet hours, max N unsolicited messages/day, never during a call or fullscreen app, every proactive class individually disable-able, and it *learns from dismissals* — ignore a class three times and it stops offering.
- Proactive detection is pure local code (file counts, transcript keyword scans, calendar-ish heuristics when they exist). Only *phrasing* a complex one might merit a model call — usually not.

### 13.6 Naming & character

Working codename in code: `friend` (package/module names stay neutral: `persona/`). The display name, wake style, and voice register are **config, not architecture** — picked later, changeable anytime:

```toml
[persona]
name = "Elaria"           # chosen Oct 2026 — also the wake word (§13.10)
candour = 0.7             # 0 butler → 1 brutally honest friend
verbosity = "normal"      # quiet | normal | chatty
humour = "witty"          # calibrated register — see §13.7 (v0: playful-teasing, mock-dramatic)
humour_profile = "~/.local/share/assistant/persona/humour.toml"
proactive = true
proactive_max_per_day = 3
pushback_budget_per_day = 5
quiet_hours = "23:00-07:00"
```

Character emerges from the *combination*: candour × memory × the no-engine. Get those right and the name is the easy part.

### 13.7 Humour calibration — learning *your* funny, not "funny"

Generic LLM humour fails predictably: it's an average of everyone, so it lands for no one — dad jokes, forced puns, "as an AI" energy. The fix is a **calibration corpus**: real conversations with your friends, used to extract a humour *style* that the persona engine then applies. Witty is the target register.

**What the corpus is used for — style extraction, not memorisation:**

| Extract (keep) | Discard (never store) |
|---|---|
| Joke *structures* you like (dry one-liners, roasts, callbacks, deadpan understatement) | The actual private content of conversations |
| Roast intensity and where the line is | Names, numbers, addresses, anyone's personal details |
| Timing/register (when a joke lands vs. when it's serious time) | Verbatim quotes replayed back at you |
| Running references and callback habits | Anything about people who aren't you |
| Your own comedic voice — the lines *you* wrote that killed | Impersonating your friends |

The output is a **`humour.toml` profile** — parameters and patterns, derived from style, e.g. roast intensity, joke density, serious-topic gates.

**Calibration v1 (first corpus, one dyadic chat: 13,138 messages parsed, 7,601 of them the user's) — what it actually showed:**

- **Not dry.** Social, expressive banter: playful teasing and mock-drama in very short lines (median ~28 chars), delivered in ~2-message bursts — setup, then the tag. Earlier "dry" setting was a guess; corrected.
- **Signature moves** (structures the engine may use, generating its own words): verdict-first openers ("No wonder…", "Imagine…"), challenge-questions that cross-examine playfully, mock-outrage with absolutes/CAPS about tiny things, mock-despair energy, self-owning before teasing. ~73% of the user's laugh-marked messages drew a laughing reply — the style is validated by its audience of one.
- **Tone is read from the writing, not emoji** (emoji removed from the profile at the user's instruction): absolutes signal exaggeration, CAPS a raised voice, "…" a pause before judgement, short fast bursts banter energy, the code-switch beat marking the joke. Teasing and roasting are first-class: teasing is the default social register, roasting the earned escalation for repeated behaviour — affection and honesty respectively, aimed only at the user's observable habits.
- **Code-switching is rhythm, not decoration:** ~1 in 5 of the user's messages mixes Kiswahili/Sheng, with discourse markers (*sasa, alafu, kwanza, mbona, sijui*) frequently carrying the punchline beat. Light seasoning now; full sentences await Phase 7.
- **Beyond humour:** warmth expressed as teasing and presence rather than compliments; zero formality tolerance; hedging reads as fake. These are engine behaviours, encoded in `humour.toml`.
- **Density is natural, not rationed:** genuinely funny → say it; otherwise silence. No forced jokes. Group-chat register (more violent) is explicitly excluded as a source by the user.

Full v1 profile: `humour.toml` (workspace root, to move to `~/.local/share/assistant/persona/` at build time).

**The pipeline is offline and mostly human:**

1. **You provide conversations** (chat exports or pasted excerpts — see privacy rules below).
2. **Analysis happens locally / in-session, producing the profile.** The corpus itself is never sent to Gemini. It lives outside the repo, in `~/.local/share/assistant/persona/corpus/` (gitignored, never committed).
3. **The persona engine reads only `humour.toml`** — patterns, not people. The corpus can be deleted after calibration; the style remains.
4. **Feedback loop:** every persona line you react to (laugh emoji equivalent = you running with it; silence/override = it missed) nudges the profile. Wit is tuned, not prompted.

**Privacy rules for the corpus (non-negotiable):**

- **Friends didn't consent to training your robot.** So: redact names/numbers before sharing where practical, and the corpus is used to learn *your* taste — never stored in the repo, never uploaded to the free tier, never quoted back.
- Safest source: **your own sent messages** plus enough surrounding context to see what landed. Your voice is yours to share.
- Corpus is deletable at any time with zero loss of function — only the derived profile persists.

**Why this works where prompting doesn't:** humour is timing, restraint, and shared context. A profile that says *"opportunistic, situational, callbacks to the user's own history, never joke during stress"* gives a conversational model the user's actual taste to match. A prompt that says *"be witty"* produces a chatbot doing stand-up at you. The profile guides phrasing in the moment (§13.2); it is not — and must never become — a bank of pre-written lines.

---



### 13.8 Real-time talk-back — what "it talks back" actually means

Three different features are hiding inside that phrase. They have different costs:

| Mode | What happens | Latency | Cost |
|---|---|---|---|
| **Dictation** (Phase 1) | You hold the hotkey, speak, release → text appears | Streaming, words as you speak | Live ASR only |
| **Voice command + spoken reply** (Phase 2) | You say a command → it acts → it *says* the result back | Reply in ~0.5–1s after you release | Local TTS, **zero tokens** |
| **Full conversation** (later phase) | Open back-and-forth talking, interruptions, it speaks first sometimes | Near-human turn-taking | Live API session while active |

**The recommended shape:** voice-out via a **local TTS engine (Piper-class)** — runs on CPU fine on this laptop, free, offline, instant, and good enough for short replies. The personality lives in *what it chooses to say and when* (§13.2 governor + `humour.toml`), not in an expensive cloud voice. Gemini Live's native-audio conversation is the premium option for full conversation mode later: more natural voice, but cloud-dependent and session-metered, so it stays optional.

**What real-time personality means in practice:** you say "organise downloads" → half a second later, out loud: the plan in one short line, with the verdict-first register if the governor allows it. The pushback grades (§13.3) also speak: pushback is *much* more effective spoken than as a wall of text.



**Soft check-in (the user's refinement):** no mode ever hard-cuts on silence. Each mode climbs a silence ladder — soft zone (listening pulse, nothing said) → one gentle spoken check, *"Is that all?"*, asked at most once per segment → resume and it's instantly forgotten, confirm or outlast a final grace and the session closes. Conversation/command modes reach the check quickly; narration mode waits much longer first. Never nagged twice.


**Reading the 0.96 honestly:** embeddings are unit vectors; cosine similarity runs -1→1, with 1.0 = identical. Mean *pairwise* cosine across the user's files is **0.96** — his files resemble each other almost as much as a file resembles itself. Strong baseline. But it is a *self-similarity* number only: the corpus contains no impostor voices, so it cannot by itself set an accept threshold. Activation accuracy needs the other distribution too — other speakers, TV, and the user's own edge registers. The voice also likely runs *consistent tone* (his own observation) with predictable drift when sleepy/sick: lower pitch, slower pace, flatter energy. User-corrected context makes this stronger than it first looked: the recordings were *not* close-held — phone at roughly laptop distance — and span reluctant, tired, energetic and angry registers. A 0.96 across *that* spread means consistency is a property of the voice, not of the recording conditions. Design consequence stands but softens: cluster the corpus embeddings (registers will likely emerge on their own — tired vs animated) rather than one average, and the live test harness (§13.10) mainly still needs what the corpus cannot contain: impostor voices, playback/TV, deliberate keyword samples, and the laptop's own microphone channel (distance matches; the device and room still differ). Threshold = chosen from the gap between *his lowest self-scores* and *the highest impostor scores*, measured, not assumed.

**Baseline + live test harness (the user's experiment, specced):** the ~5-hour corpus builds the baseline in two halves — (a) the **voiceprint** (who you are) and (b) the **negative set** (hours of you talking normally, used to prove ordinary speech does *not* trigger). One gap the corpus can't fill: it may contain no one saying the keyword, so enrolment adds ~20 deliberate keyword samples from you (varied tone/distance) as the positive set.

The test script (`assist-voice-test`, built before the daemon):

```
assist-voice-test run
  → mic opens LOCALLY, ring buffer only, nothing recorded or sent anywhere
  → says keyword + voiceprint matches → indicator LIGHTS UP (Waybar/overlay
    LED + optional soft chime) and the event is logged:
    { time, keyword_score, speaker_score, latency_ms }
  → you talk normally / TV plays / someone else speaks → any light-up is a
    FALSE trigger, logged the same way
  → you tap a hotkey (or click the LED) to mark the last event
    "that was wrong" / "that was me and it missed" — one-key labelling
assist-voice-test report
  → false triggers per hour · missed-keyword rate · speaker false-accepts
    (other voices/TV) · average detection latency · score distributions
    with a suggested threshold
```

**Test protocol:** run it in the background of real life for a few days — desk distance, across the room, tired morning voice, music on. Accuracy is measured in *your* rooms, not a lab: target **<1 false light-up per day** and **>95% of your deliberate keywords caught**, with latency under the §18 budget. Thresholds get tuned from the report's score distributions, per-user, from data — never from a default someone else chose.

**Privacy of the test itself:** logs contain timestamps and scores only. No audio is stored unless you explicitly enable "save near-miss clips" for debugging, and that toggle is off by default and deletes after 24h.

**Measured baseline (Oct 2026, external processing of the user's corpus):** 234 min of speech across 2 archives; ECAPA-TDNN voiceprint consistency **0.96** (very high — strict activation thresholds are affordable); speech is **mixed-language** (auto-tags ~54% Swahili / ~21% English — reinforcing that code-switching is the user's native rhythm, §13.7, and Phase 7 matters); English passages run **~146 wpm including pauses** with a stable syllable rate of **3.97/s**; pitch wide/expressive (median 106 Hz); energy falls within phrases; **pauses measured frequent (17/min, median 0.58 s) — but the user corrects: the corpus is mostly storytelling/narration; in conversation he pauses far less. Endpointing is therefore ADAPTIVE: patient in dictation/narration mode, responsive in command/conversation mode — inferred from how the session was opened, never one global timeout**. Full profile in `humour.toml [spoken_delivery]`. `voiceprint.json` is a biometric template: it stays OUT of any public repo and out of git entirely.

**Better enrollment: process the voice notes you already have.** Repeating a keyword ten times in a quiet room produces a fragile voiceprint — one recording condition, one mood. Existing voice notes to a friend are the opposite: many days, rooms, energy levels, and your natural register. Processing pipeline (all local/offline):

1. **Collect** the audio files (WhatsApp voice notes are `.opus` — ideal). Only *your* sent notes are processed; anything from the other side is discarded untouched.
2. **Embed** each note into a speaker vector (ECAPA-class model, CPU-feasible as a batch job) and average into one robust voiceprint with measured variance — the system learns how much your voice legitimately varies.
3. **Profile your delivery** from the same audio: speaking pace, pause habits, pitch range, energy curve, how you sound starting a thought vs. landing one. Stored as numbers in `[spoken_delivery]` — this later tunes both the speaker-check threshold and how the assistant paces *its* speech to sit naturally with yours.
4. **Delete the audio.** What persists is vectors and statistics — a voiceprint cannot be played back as you, and the originals are gone unless you keep them.

Bonus: the same corpus stress-tests activation — the keyword check can be validated against hours of you *not* saying the keyword (your normal speech as the negative set), giving a measured false-trigger rate before it ever goes live.

**Honest limits:** (1) Phase 1 as specced is dictation only — no voice-out until Phase 2 adds TTS. (2) Full-duplex conversation (barge-in, talking over it) is a distinct mode, not an upgrade of dictation; it's specced as a later phase. (3) A local TTS voice will sound like a clean assistant voice, not a specific person — character comes from the words.


### 13.9 Offline mode — what survives a dead router

Because the runtime is local-first (§13.4), most of the system never needed the network. Offline is a **degradation mode, not an outage**:

| Capability | Offline behaviour |
|---|---|
| Daemon, hotkey, CLI, Waybar, overlay | ✅ Full — never touched the network |
| Persona governor + `humour.toml` voice | ✅ Full — it's local code and state |
| Voice-out (Piper-class TTS) | ✅ Full — local engine |
| Voice commands (known grammar: "organise downloads", "status", "undo") | ✅ Works — constrained local recognition (grammar-based recogniser or whisper.cpp `small`), because the vocabulary is small |
| Document organising — Tier 0 rules (~70%) | ✅ Full — deterministic rules |
| Document organising — Tier 1/2 (LLM judgement) | ⏸️ **Queues**: files go to a "pending judgement" pile and drain automatically when connectivity returns |
| Memory search (SQLite FTS) | ✅ Full |
| Reminders, schedules, journal, undo | ✅ Full |
| Free-form dictation | ⚠️ Degraded: local whisper.cpp `small`, English only, noticeably worse accuracy, no cleanup pass. Usable for notes-to-self, not for records |
| Open-ended chat / advice | ❌ Unavailable — that's inherently the cloud model's job |
| Transcript cleanup/polish | ⏸️ Queued with the raw transcript; applied on reconnect |

**Design rules for offline:**

1. **The user should never have to know.** The daemon detects connectivity loss and switches ASR backend + organiser tiers automatically (the §12.7 seam already allows this). Waybar shows one small "offline" glyph; that's the entire UI change.
2. **Queue, don't fail.** Anything cloud-bound becomes a durable queue entry in SQLite with the raw material attached (audio file, file list). Reconnect drains it in the background. Offline work is never lost work.
3. **Raw audio is always saved locally** (already a rule), so an offline dictation can be *re-transcribed properly* by Gemini when back online — the rough local transcript is a placeholder, the audio is the truth.
4. **Offline is also a privacy mode.** A manual `assist offline` toggle forces this posture even with the router up: nothing leaves the machine, cloud tiers queue. Same mechanism, user-invoked.

**What offline will never be on this hardware:** a good free-form Swahili/English conversational brain (§12.6 — the UHD 620 cannot run one). Offline = a competent, funny, useful *tool*. Online = that, plus a mind.


### 13.10 Voice activation — a keyword, in *your* voice

Two separate jobs, often confused:

| Job | Tech (local, offline) | Cost on this laptop |
|---|---|---|
| **Hear the keyword** ("Elaria") | Custom `.onnx` keyword model through ONNX Runtime (one shared inference adapter) | Tiny — a few % of one core, always-on |
| **Know it's you** | Speaker verification: your voiceprint (embedding model, SpeechBrain ECAPA-class) compared against an enrolled sample | Runs only *after* the keyword fires — a fraction of a second |

**Packaging decision, 2026-10-25 (GATE-FIX 2):** wake inference uses ONNX
Runtime on the normal interpreter, not Linux openWakeWord/TFLite and not a
separate Python 3.11 toolchain. `uv sync --extra voice` is opt-in; plain
`uv sync` installs the working daemon + dev tools. Wake is **paused at 0 takes**;
a missing extra/model must report “wake word paused”, never prevent daemon or
doctor startup. The executable seam, model contract and no-migration rationale
are recorded in [the hotword training plan](docs/hotword-training-plan.md#inference-home--onnx-only-gate-fix-2-2026-10-25).

**How it works in the daemon:**

1. Mic feeds a **ring buffer processed locally and never stored or streamed**. Nothing leaves the machine, nothing is recorded; audio older than ~2 seconds is discarded continuously. This is the privacy contract that makes always-listening acceptable.
2. Keyword fires → speaker check against your enrolled voiceprint (enrolment: you repeat the keyword ~10 times once, at setup).
3. Match → session opens (same pipeline as the hotkey). No match → it stays silent; someone else in the room — or the TV — can't drive it.
4. **Voiceprint gates by level (§15):** your voice alone can unlock L0–L2. L3+ (desktop hands, sending) still needs the plan-approval rules; a recording of you is not a blank cheque, so away-mode plans approved earlier carry the authority, not the voiceprint.

**Honest limits:**

- Speaker verification *raises the bar*, it isn't biometrics-grade security: a good recording of you saying the keyword could fool it. Fine for "don't let my brother troll it"; not for guarding secrets — which is why hard-no rules (§13.3) ignore voice entirely.
- **The name/keyword is "Elaria"** (chosen Oct 2026): four clear syllables (eh-LAR-ee-uh), phonetically unlike everyday English/Swahili vocabulary, and not a word that occurs in normal conversation — all three properties minimise false triggers. Any renaming later must re-run the §13.10 false-trigger test, since the acoustic profile changes with the word.
- Keyword detection is offline by design (it must be — it's pre-activation), so **offline mode (§13.9) keeps full voice activation**.
- Push-to-talk remains the default and the fallback: wake word is an *additional* trigger, and a hardware mic-mute always wins. Waybar shows a live mic state; a muted mic means the keyword model hears nothing.

## 14. Blueprint status — is this done?

**For Phase 0: yes, after this revision.** No GitHub link exists in this environment, which is why this stayed a blueprint — that was the user's instruction, not a stall.

Done means: every Phase 0 component is specified (daemon, IPC, CLI, Gemini client, cost ledger, fixture harness, persona *governor* skeleton), the quota/privacy/hardware questions are settled with evidence (§12), and the personality risk is named and designed against (§13.2: governor, not joke bank).

**Explicitly NOT blocking Phase 0** (decide later, in their phases): assistant name · taxonomy (Phase 3) · chat surface (Phase 2/5) · system-audio mix (Phase 6) · diarization (Phase 6) · Kiswahili (Phase 7).

**The one-sentence spec, if everything else is lost:** *a local-first daemon on Fedora/Hyprland that transcribes by hotkey, organises files invasively but reversibly, calls Gemini only when code genuinely can't decide, and has a personality engine that governs a contextual voice — loyal, candid, occasionally funny, and willing to say no.*

---


## 15. Task depth — how much can it actually *do*?

"Tell it I'm leaving, click this and that, handle it" is a specific feature: **delegated multi-step tasks, executed unattended**. Depth comes in levels; each is gated harder than the last.

| Level | What it does | Example | Gate |
|---|---|---|---|
| **L0 — Answer** | Reads, searches, recalls | "Where's the invoice from March?" | none |
| **L1 — Single action** | One tool call | "Move this to Finance." | safety spine |
| **L2 — Workflow** | Chained steps it plans & sequences | "Sort Downloads, rename the invoices properly, tell me what wouldn't fit." | plan shown, one approval |
| **L3 — Desktop hands** | Operates apps: launch, click, type, shortcut | "Open the spreadsheet, export sheet 2 as PDF, file it." | plan approval + allowlisted apps |
| **L4 — While-you're-away** | Runs an approved task queue unattended, reports on return | "I'm leaving — finish the sort, back up Documents, and have the summary ready." | **pre-approved plan only**, blast-radius caps, nothing new invented mid-run |
| **L5 — External effects** | Messages sent, things posted/purchased on your behalf | "Text Kamau that I'll be late." | **per-action confirmation by default**; standing permission only per-contact/per-action-type, revocable |

**The maximum useful task surface** (buildable on this stack): files & folders · app launching/control · browser assistance · media/download management · reminders & schedules · transcription pipelines · backups · dev chores (run tests, sort build output) · system info/settings via CLI · cross-app chains of all of the above ("when the render finishes, move it, back it up, and tell me").

### 15.1 Desktop hands on Wayland — the honest mechanics

Wayland deliberately makes synthetic input hard. What actually works on Hyprland:

- **Prefer not clicking at all:** most "click this" goals have a CLI, D-Bus, or keyboard-shortcut path underneath. Shortcuts (`hyprctl dispatch`, app keybinds) are robust; pixel coordinates are not.
- **When clicking is unavoidable:** `ydotool` (talks to `/dev/uinput`, works regardless of compositor) for mouse/keys, `wtype` for text. Coordinate targets are fragile — a moved window breaks them — so recorded macros store *window + relative position*, and every L3+ plan is re-validated against the current screen state before running.
- **Reading the screen:** AT-SPI2 accessibility tree where apps expose it; screenshot + (cloud vision) only when necessary and never silently.
- **The rule:** GUI automation is the *last resort adapter*, used when no API/shortcut exists. A task engine built on clicking is a task engine that breaks weekly.

### 15.2 While-you're-away mode (L4) — the "I'm leaving" contract

1. You describe the job in speech or text. It decomposes it into a numbered plan.
2. **You approve the plan** (voice "do it" / hotkey). Approval is scoped: these apps, these folders, this many operations, this long.
3. It runs within the safety spine: journalled, rate-capped, halt-able remotely by the panic hotkey when you return — and it **stops and parks** anything the plan didn't cover rather than improvising.
4. On return: a spoken + written report — done, parked, failed, and anything it refused and why.

No plan approval, no unattended run. That single rule is the difference between a butler and a liability.

---


### 15.3 The task console & toolchain manager

One surface for delegated work, spoken or typed — same pipeline either way:

```
you:  "find me 100 videos of X and download them"
      "merge these files"  ·  "convert this folder to mp3"  ·  "shrink these PDFs"

console: 1. parses the job → identifies the CAPABILITY needed
         2. inspects files/system → detects formats, sizes, what's missing
         3. checks the toolchain → installed? installable? from where, how big?
         4. shows a plan (tools to fetch, steps, output location) → you approve
         5. executes with live progress, logs every command, reports + undo info
```

**The toolchain manager is the "scans and downloads the tools" brain.** Every capability declares what it needs; the manager resolves it in a strict preference order:

| Preference | Source | Rule |
|---|---|---|
| 1 | Already installed | use it (`ffmpeg`, `pdftk`, …) |
| 2 | Python stdlib / existing deps | no new code |
| 3 | Fedora repo (`dnf`) | system packages; **sudo needs your approval each time** |
| 4 | `uv tool` / pip package | user-level, no sudo (e.g. `yt-dlp`) |
| 5 | Vendored binary release | checksum-verified, pinned version, stored under `~/.local/share/assistant/tools/` |

**Hard rules:** never `curl | sh`; never install silently; every install is in the plan you approve, with source + size; installs are journalled and removable (`assist tools remove X`). A capability database (local TOML) maps jobs → tools: *download video → yt-dlp (+ffmpeg for merging formats); merge PDFs → pdfunite/qpdf; merge video → ffmpeg concat; merge audio → ffmpeg/sox; convert → ffmpeg/ImageMagick; archive → 7z.*

**Worked examples:**

- *"Find me 100 videos of X, download them"* → needs `yt-dlp`; plan shows source, count cap, quality, destination folder, estimated size → approve → downloads with progress, dedupes, logs URLs, produces a manifest. **Rights rule: it downloads what you have the right to download — your own, Creative Commons/public domain, or content you supply URLs for. It will push back on an obvious ripped-content trawl the same way it pushes back elsewhere (§13.3), because "friend, not accomplice" is the same personality.**
- *"Merge these files"* (you drop/point at files) → it inspects actual types: 3 PDFs → `pdfunite`; 2 videos → `ffmpeg` (re-encode only if codecs differ); mixed types → it asks, because "merge" of a PDF and an MP4 is not a thing. Output is a *new* file; originals untouched until you say otherwise.

**Console properties:** streaming logs (not a spinner then a wall), every command echoed before it runs at L3+, cancellable mid-job (`assist halt` / Ctrl-C), resumable where the tool supports it, and a job history (`assist jobs`) with full provenance — what ran, with what, producing what.

This console is also where voice commands (§13.8/§13.10) land: "hey — merge these and put it in Documents" is the same job, just spoken, with the plan read back instead of shown.

## 16. Memory — offline, on your disk, yours

One SQLite database at `~/.local/share/assistant/assistant.db`. **It never syncs anywhere.** When Gemini needs context, the daemon retrieves a few relevant snippets and includes them in that one request — the memory itself stays home. This is where "things it learns about me" live:

| Memory type | Contents | Example |
|---|---|---|
| **Profile** | Facts you've stated | names, projects, your people, your setup |
| **Preferences** | Explicit + inferred (with confidence) | naming conventions, "PDFs by issuer", quiet hours |
| **Episodic** | What happened | tasks run, decisions made, files moved, meetings transcribed |
| **Procedural** | How you like things done | your macros, workflows, folder logic — the L2/L4 fuel |
| **Relationship** | The personality state | familiarity level, teasing licence earned, what landed, what flopped |
| **Commitments** | Open loops | "you said you'd review the parked files" — powers bounded proactivity (§13.5) |

**Learning rules (so learning never becomes creepy or wrong):**

- **Stated beats inferred.** Anything you say explicitly is stored as fact. Anything it *infers* is stored as a guess with a confidence score, and it must be able to show its evidence ("you've filed invoices by issuer 11 times").
- **Inferred memories start probationary** — they bias suggestions, never irreversible actions, until confirmed or repeatedly validated.
- **Fully inspectable:** `assist memory` lists what it believes about you; `assist forget <topic>` deletes, no argument. A memory it can't show you is a memory it doesn't get to keep.
- **Offline by architecture**, not by policy toggle: the store has no network code path at all. The offline mode (§13.9) loses *nothing* from memory.
- **Recall is local:** FTS5 + local embeddings; retrieval takes milliseconds and zero tokens. Gemini sees snippets, never the database.

This memory is what makes the personality real over time: the roasting is earned because the *relationship memory* remembers, and the "no" is credible because the *episodic memory* can cite what happened last time.

---


## 17. The reasoning harness — code that makes cheap models punch up

**The user's idea, formalised:** default every Gemini call to the *lowest* capable model (Flash-Lite class) and let our code supply the reasoning structure that expensive models carry internally. This works — within honest limits.

### 17.1 What code can genuinely supply

A frontier model given a raw prompt does several things invisibly: decompose, gather context, draft, check itself, revise. Every one of those can be *externalised into code* around a cheap model:

| Technique | How the harness does it | What it buys |
|---|---|---|
| **Decomposition** | Code splits the job into small, single-purpose calls ("classify these 10 names" not "organise my disk") | Cheap models are reliable at small tasks, unreliable at big ones — so never give them big ones |
| **Context assembly** | Code retrieves the exact memory/files/taxonomy the call needs (§16) | A cheap model with perfect context beats a smart model guessing |
| **Structured output** | JSON schemas, enums, frozen taxonomies (§3.7) | No rambling, no parsing failures, machine-checkable answers |
| **Tool grounding** | The model proposes; tools return *facts* (file sizes, dates, tool output) | It reasons over verified data instead of hallucinating premises |
| **Verification pass** | Deterministic code checks the proposal (policy, exists?, reversible?) + optionally a second cheap call as critic | Catches the errors cheap models actually make |
| **Retry with feedback** | Failed check → error fed back → one targeted retry | Converts "wrong" into "wrong, told why, fixed" |
| **Escalation** | Only when verification fails twice does the call climb a tier (Lite → Flash) | Expensive reasoning is spent on the ~2% of cases that earned it |

This is why the organiser cascade (§3.7) already works: Tier 0 rules + Tier 1 micro-calls *is* this harness, applied to filing.

### 17.2 The honest ceiling

- **Scaffolding multiplies capability; it doesn't create it.** A Lite model inside a great harness will beat a raw frontier model on *structured, verifiable, narrow* work (filing, extracting, classifying, formatting, tool-chaining). It will still lose on open-ended judgement, subtle writing, and genuinely novel problems — that's what chat/escalation is for.
- **More calls ≠ free.** Five Lite calls to simulate one smart call still costs five requests against RPM/RPD. The harness tracks this: if a task's scaffold would take >N cheap calls, it escalates early instead of performing thrift theatre.
- **Verification needs something to verify against.** Where no ground truth exists (taste, advice), the harness can't certify quality — it can only present, cite its sources, and let the pushback rules (§13.3) speak.

### 17.3 Where it applies in this system

- **Everywhere by default:** organiser, console job planning (§15.3), memory extraction, transcript cleanup — all Lite-first, harness-wrapped, escalate-on-failure.
- **The persona governor benefits too:** the decision *whether* something is funny/appropriate stays code; when a conversational reply is already being generated, the harness gives the cheap model your profile + the moment's context, which is most of "vibe-matching" anyway (§13.2).
- **Config:** `model_default = flash-lite`, `escalate_after_failures = 2`, `max_scaffold_calls = 6` — tuned by `assist cost` data, not by hope.

**One-sentence version:** *the expensive model's advantage is mostly process; process can be code; what's left — raw judgement — is the only thing we rent, and we rent it rarely.*

---


## 18. Speed — the latency budget (hard spec, not aspiration)

The user interacts mostly by voice. In voice, **silence reads as broken**. A 10-second pause before "working on it" is a failed product even if the eventual work is perfect. So responsiveness is layered, and the layers have budgets:

| Moment | Budget | How |
|---|---|---|
| Hotkey/wake-word → it's listening | **<150 ms** | Local chime + Waybar state. No model involved. |
| You stop speaking → it acknowledges | **<300 ms** | **Pre-synthesised local ack** ("On it." / a short earcon). Cached audio files — zero TTS delay, zero network. |
| Simple command done ("undo", "status", known grammar) | **<1 s** end-to-end | Local parse + local tool. No Gemini call exists in this path. |
| Complex job → plan or first progress | **<2 s** to *first spoken feedback* | Local decomposition starts instantly; if Gemini is still thinking, it says what it's doing, not "please wait" |
| Long job running | update every **3–5 s** | Spoken/overlay progress from real state (files done, %, current step). Never a silent spinner. |
| Open chat reply starts | streaming, first words **<1.5 s** | Streamed TTS: speak sentence 1 while sentence 2 generates. |

**The architectural rules that make this true:**

1. **Acknowledge first, think second.** The ack is dumb, local and instant. Intelligence catches up behind it. The user should *never* be able to perceive the reasoning harness (§17) warming up.
2. **Nothing on the ack path touches the network.** Wake → ack → local parse → (maybe) a tool is an all-local chain. Gemini, when needed, joins a conversation already in motion.
3. **Parse while you speak.** Streaming partial transcripts feed the local intent parser during speech, so by the time you stop, known commands are already matched and tools can be pre-staged. The release of the hotkey is the starting gun, not the beginning of thought.
4. **Optimistic, honest feedback.** It may say "Sorting your downloads —" the moment the local job starts (true), and must never fake progress it isn't making. Fast *and* truthful beats fast and theatrical.
5. **Long work goes async immediately.** The voice channel returns to you in seconds with a plan summary; the job runs in the background and interrupts only for decisions, completion, or trouble. You are never held hostage by your own instruction.
6. **Pre-warm the hot paths.** Daemon keeps the local recogniser, TTS engine and persona state resident. Cold starts are a Phase-0 bug, not a personality trait.
7. **Silence is handled by ladder, never by guillotine** (§13.10): listen → one soft "Is that all?" → close. A slow thinker must never be amputated mid-thought, and a finished speaker must never be left hanging.

**Persona consequence (§13):** the voice you hear in the first 300 ms is a small set of cached, personality-true acks — short, in-register, rotated rarely. The full expressive voice arrives with the first *substantive* sentence, which is where it belongs.

**Test for every future feature:** *what does the user hear within one second of finishing speaking?* If the answer is "nothing yet", the feature is not done.

---

## Appendix A — config sketch

```toml
[gemini]
api_key_file = "/run/user/1000/assistant.env"
model_chat = "gemini-3.8-flash"
model_organise = "gemini-3.1-flash-lite"
model_default = "flash-lite"   # reasoning harness (§17): cheapest first, escalate on verified failure
escalate_after_failures = 2
max_scaffold_calls = 6
model_transcribe_live = "gemini-3.5-transcribe-live"

[asr]
primary  = "gemini_live"  # free tier: 3 concurrent sessions, 1M TPM  (see §12.3)
fallback = ["gemini_batch", "local"]
offline_model = "small"   # English only — Kiswahili is not viable offline
languages = ["en"]        # Phase 1: English only. Add "sw" in Phase 7 — config, not refactor.
                          # Pinned explicitly, never auto-detected.
preserve_code_switching = false  # flip to true with sw/en in Phase 7
assert_output_language = true    # catches silent translation
diarization = "pyannote"  # language-agnostic, local, post-pass (§12.4)

[cleanup]
enabled = true
model = "gemini-3.1-flash-lite"
max_divergence_pct = 35   # diff-gate: above this, flag for review
keep_raw = true           # never destroy the original transcript
glossary_file = "~/.config/assistant/glossary.toml"   # names, places, jargon

[capture]
source = "mic"            # mic | monitor | mix
sample_rate = 16000
chunk_ms = 30
retention_days = 30

[transcribe]
reconnect_replay_s = 30

[persona]
name = "Elaria"
candour = 0.7             # 0 butler → 1 brutally honest
verbosity = "normal"      # quiet | normal | chatty
humour = "witty"          # calibrated register — see §13.7
humour_profile = "~/.local/share/assistant/persona/humour.toml"
proactive = true
proactive_max_per_day = 3
pushback_budget_per_day = 5
quiet_hours = "23:00-07:00"

[quota]
# free-tier reality: the organiser must be a patient background queue
max_requests_per_day = 1200
max_requests_per_minute = 12
queue_drain_hours = 6

[privacy]
tier = "free"             # free | paid  — see §12.2
never_send_to_cloud = ["~/Documents/Personal/Medical"]
audio_leaves_machine = false   # true for groq / gemini_live backends

[organise]
mode = "shadow"           # shadow | live   (per-root override)
cascade = true            # four-tier rules-first planner (see §3.7) — huge quota saver
tier0_min_confidence = 0.85   # below this, escalate to the LLM tiers
tier1_batch_size = 50
tier2_batch_size = 10
tier3_backlog = "overnight"   # local model drain, no quota
confidence_auto = 0.90
confidence_review = 0.60
max_ops_per_run = 200
max_ops_per_hour = 500
tree_tripwire_pct = 25

[[organise.roots]]
path = "~/Documents"
mode = "shadow"
taxonomy = ["Finance", "Work", "Personal", "Reference", "_Unsorted", "_Conflicts"]

[policy]
protected = ["~/.ssh", "~/.gnupg", "~/.config", "~/.local/share/assistant"]
never_send_to_cloud = ["~/Documents/Personal/Medical"]

[tools]
shell = "confirm"         # off | confirm | allow
```

---

*Blueprint v29 — discussion draft. The assistant is named: **Elaria** (also the wake word), set in persona config and §13.10. Ready to build when a repo exists.*
