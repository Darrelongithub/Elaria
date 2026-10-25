# Getting started — from zero to a running assistant

Companion to `assistant-blueprint.md`. This is the build order, with commands that work on Fedora + Hyprland.

**One owner, some helpers:** this is your project. Mentors and debuggers help with code review and troubleshooting, and they need *repo access* — not credentials. Don't share your key file with anyone. If a mentor wants to exercise the real API on his own machine, he creates his own free project and key in ten minutes (§12.9).

## Install or update the working runtime (GATE-FIX 2)

From a fresh checkout, **plain `uv sync` is sufficient** for the daemon's
Python runtime and the default dev tools. No `--all-extras` recovery command
is needed. On the owner's Fedora 44 / CPython 3.14 laptop (Python >= 3.11 is
supported):

```bash
git clone https://github.com/Darrelongithub/Elaria.git ~/Elaria
cd ~/Elaria
uv sync
uv run assist --help
uv run assist doctor
```

For an existing checkout, start at `cd ~/Elaria`; check out the PR branch
before syncing when following the [console branch gate](docs/console-home/hardware-gate.md).
Runtime dependencies (`google-genai`, `httpx`, `faster-whisper`, `piper-tts`,
including their CTranslate2/ONNX Runtime dependencies) live in
`[project].dependencies`. `pytest` and `ruff` live in the default `dev`
dependency-group. `uv.lock` pins the reviewed resolution; do not depend on
packages left behind in an old `.venv`. Installing packages does not download
Whisper/Piper models, provide an API key, or enable the dormant local voice.
Mock mode remains keyless and network-free; live audio still needs the Fedora
prerequisites, owner config/key and model assets described below.

Install the service once (the links must point at **this** checkout's venv):

```bash
mkdir -p ~/.local/bin ~/.config/systemd/user
ln -sf "$PWD/.venv/bin/assistd" ~/.local/bin/assistd
ln -sf "$PWD/.venv/bin/assist" ~/.local/bin/assist
cp systemd/assistant.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now assistant
```

After a normal update, or to recover the gutted venv:

```bash
cd ~/Elaria
uv sync
systemctl --user restart assistant
systemctl --user is-active assistant     # must say active
```

### Genuinely optional shelves (none is selected by plain sync)

| Capability | Exact sync command | Still needed |
| --- | --- | --- |
| Semantic embeddings beyond the hashing baseline | `uv sync --extra embeddings` | model assets; larger ML stack |
| Speaker diarization post-pass | `uv sync --extra diarize` | model access/assets; channel diarization works without it |
| Wake keyword inference | `uv sync --extra voice` | a real owner `.onnx` model and external ECAPA scorer; **paused at 0 takes** |

Repeat the desired extra flags on subsequent syncs to keep optional shelves
installed; combine flags if using more than one. `--extra live`, `--extra
offline`, `--extra tts` are compatibility names only: those runtimes are now
always installed. `--extra dev` remains a pip/old-command compatibility alias;
plain uv uses the default `dev` group instead.

**Wake choice: ONNX Runtime only**, through `wake_guard.OnnxKeywordModel`,
shared with the test harness adapter. No `openwakeword` package or
`tflite-runtime` dependency remains: openWakeWord pulled Linux TFLite even
for ONNX models, and TFLite 2.14 had no cp314 wheel/source distribution.
No Python 3.11 wake-only toolchain and no migration are needed. The existing
`voice` extra is opt-in, never a default group; ONNX Runtime can already be
present for Whisper/Piper without arming the wake path. uv locks optional
metadata together, but neither the default selection nor the lock contains
TFLite. Missing runtime/model means **wake word paused**, not a daemon or
doctor crash; push-to-talk and terminal dictation do not depend on wake.
See the [inference decision and model contract](docs/hotword-training-plan.md#inference-home--onnx-only-gate-fix-2-2026-10-25).

The owner's emergency `uv sync --all-groups --all-extras --no-install-package
tflite-runtime` was a workaround for the old package graph, **not** the new
installation instruction. Use plain `uv sync` now. Do not enable the large
embeddings/diarization stacks just to repair the daemon.

---

## Step 0 — Verify the load-bearing assumption (do this first)

The entire design rests on the Gemini **Live API being free-tier eligible**. If that's wrong, the transcription approach changes and Steps 3+ change with it. Ten seconds to check:

1. Go to **`aistudio.google.com/rate-limit`**
2. Confirm your project has free-tier access to the **Live** models
3. Note your actual **RPM / TPM / RPD** numbers — Google no longer publishes a fixed table, your live numbers are the only ones that matter
4. Note the exact model IDs available (e.g. `gemini-3.5-transcribe-live`)

✅ **If free Live is available** → proceed. This is the expected case.
❌ **If it isn't** → stop and tell me. We fall back to batch transcription + the §12.7 chain, which changes Step 3 and delays Phase 2.

While you're there, check the free-tier RPD for Flash and Flash-Lite. Those are the numbers the organiser queue gets sized against.

---

## Step 1 — Account and key (yours only)

1. Go to **`aistudio.google.com`** → create a project (or accept the default).
2. Create an **API key**. Since May 2026 these are **auth keys** — service-account-backed, Gemini-API-only by default. That's what you want.
3. Verify the key is **restricted to the Generative Language API**. Unrestricted standard keys are rejected by Gemini as of June 2026, and restricted keys have a smaller blast radius if leaked.
4. Store it **outside the repo**:

```bash
mkdir -p ~/.config/assistant
printf 'GEMINI_API_KEY=your-key-here\n' > ~/.config/assistant/gemini.env
chmod 600 ~/.config/assistant/gemini.env
chmod 700 ~/.config/assistant
```

5. Confirm it's readable only by you: `ls -l ~/.config/assistant/gemini.env` → `-rw-------`

**Never** put the key in `config.toml`, the repo, a shell profile, or a chat message. It goes in that one file, `0600`, and the daemon's systemd unit reads it via `EnvironmentFile=`.

> **One key, one owner.** Nobody else needs this file. Mentors debug against fixtures (Step 5), not against your live credential.

---

## Step 2 — Fedora prerequisites

Most of this is probably already present if you're running Hyprland.

```bash
sudo dnf install -y git pipewire-utils wireplumber wl-clipboard libnotify uv
```

| Package | Provides | Needed for |
|---|---|---|
| `pipewire-utils` | `pw-record`, `pw-play`, `pw-cli` | audio capture |
| `wireplumber` | `wpctl` | finding your mic/sink nodes |
| `wl-clipboard` | `wl-copy`, `wl-paste` | clipboard — X11 tools silently fail on Wayland |
| `libnotify` | `notify-send` | plan proposals, conflicts, halt notices |
| `uv` | `uv` | Python env + package management |

`uv` is in Fedora's repos since F40. If yours is older or it's missing:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Fedora 44's CPython 3.14 is supported; no downgrade is required. If you
prefer an independently managed interpreter, install one explicitly:

```bash
uv python install 3.14
```

**Verify everything:**

```bash
hyprctl version          # Hyprland version — tells you Lua vs .conf config syntax
wpctl status | head -20  # your audio nodes
pw-record --help | head -3
wl-copy --version
uv --version
```

Note whether your Hyprland is **0.55+** (Lua config, `hl.bind(...)`) or older (`.conf`, `bind`/`bindr`). That changes Step 6.

---

## Step 3 — Decide the capture source (the open question)

This is the one unresolved decision, and it's easier to settle by testing than by reasoning. Run all three, listen to the output, pick.

**First, find your node names:**

```bash
wpctl status
```

Look at the **Sources** list for your mic, and the **Sinks** list for your output.

> ⚠️ **The trap that costs people an evening:** `pw-record --target=` takes the **`object.serial`** or the **`node.name`** — *not* the `object.id`. Passing the ID silently records the default device instead of erroring. If your "system audio" test sounds like your microphone, this is why.

**A — Microphone** (recommended starting point):

```bash
pw-record --target=<node.name> --rate 16000 --channels 1 /tmp/test-mic.wav
# speak for a few seconds, then Ctrl-C
pw-play /tmp/test-mic.wav
```

**B — System audio** (the other side of a call):

```bash
pw-record -P '{ stream.capture.sink=true }' --rate 16000 --channels 1 /tmp/test-sys.wav
# play a video or music, then Ctrl-C
pw-play /tmp/test-sys.wav
```

**C — Mix** (both sides, one stream — the meeting-mode goal):

```bash
pactl load-module module-loopback source=<mic_source> sink=<virtual_sink>
# then capture the virtual sink's monitor
```

**Decision gate:**

| What you heard | Set in config |
|---|---|
| Only your voice, A worked | `source = "mic"` — start here |
| System audio in B | good, that path works for meeting mode later |
| Both worked | start with `mic`; add `mix` in Phase 6 |

My recommendation stays: **mic first.** It's one stream instead of three, and it's what dictation needs. Meeting mode is Phase 6.

---

## Step 4 — Repo skeleton

One shared repo, no secrets. Both of you clone it.

```
assistant/
├── README.md
├── SETUP.md                 # ← the two-dev version of this file
├── .gitignore
├── pyproject.toml
├── config.toml.example      # committed
├── config.toml              # gitignored, local
├── src/assistant/
│   ├── __init__.py
│   ├── config.py            # loads config.toml + env
│   ├── ipc.py               # unix socket, NDJSON protocol
│   ├── daemon.py            # asyncio event loop, systemd service
│   ├── cli.py               # the `assist` command — thin IPC client
│   ├── gemini_client.py     # models by role, retries, backoff
│   ├── cost.py              # cost ledger — Phase 0, not later
│   ├── asr.py               # the backend seam (§12.7)
│   ├── capture.py           # PipeWire via pw-record, session-scoped
│   ├── store.py             # SQLite: conversations, transcripts, ops, llm_calls
│   └── fixtures.py          # mock | record | live harness (§12.9)
├── fixtures/                # recorded request/response pairs — committed
├── tests/                   # must run with NO api key
└── systemd/assistant.service
```

**`.gitignore`** — minimum:

```gitignore
config.toml
*.env
.venv/
__pycache__/
*.db
audio/
```

`fixtures/` is **committed**, deliberately. It's the shared debugging artifact — the thing a mentor works against.

**`pyproject.toml` (current default-sync contract; see the real file for extras):**

```toml
[project]
name = "assistant"
version = "0.0.1"
requires-python = ">=3.11"
dependencies = ["google-genai>=2.0.0", "httpx>=0.27", "faster-whisper>=1.1", "piper-tts"]

[project.scripts]
assist = "assistant.cli:main"
assistd = "assistant.daemon:main"

[dependency-groups]
dev = ["pytest>=8", "ruff"]

[tool.uv]
default-groups = ["dev"]
```

**`systemd/assistant.service`:**

```ini
[Unit]
Description=Personal AI assistant daemon
After=pipewire.service

[Service]
Type=simple
EnvironmentFile=%h/.config/assistant/gemini.env
ExecStart=%h/.local/bin/assistd
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
```

`EnvironmentFile` keeps the key out of the unit file, out of `config.toml`, and out of git — while still being an environment variable to the process.

---

## Step 5 — Phase 0: the skeleton that proves itself

**Definition of done:** three commands work.

```bash
assist doctor    # key valid? models reachable? PipeWire up? Hyprland socket found? quota?
assist status    # daemon running, current mode, uptime
assist cost      # this month's spend + request count, from the ledger
pytest           # passes with NO API key present
```

That last line is not a formality. **An LLM app is non-deterministic, so the ordinary reproduce-and-fix loop doesn't work** — the same command gives different output, and a bug you can't reproduce is a bug you can't fix. The fixture harness is what makes debugging possible at all:

```
GEMINI_MODE = live | record | mock

live     real API, real responses
record   real API, and every request/response pair is saved to fixtures/
mock     no network — replays recorded fixtures, deterministic, zero quota
```

Fixtures are keyed by a hash of the request, so a replayed call returns exactly what it returned on recording day. Your logic becomes steppable with the model's behaviour held constant — and a mentor running `GEMINI_MODE=mock` gets your **exact** behaviour, without a key and without touching your quota.

Build order inside Phase 0:

1. **`config.py`** — load `config.toml`, resolve `~`, read the env file. **No hardcoded absolute paths anywhere** — `$HOME`/`$XDG_*`/config only, so the code stays portable.
2. **`store.py`** — create `~/.local/share/assistant/assistant.db`, the `llm_calls` table first. Everything else can wait; the ledger can't.
3. **`ipc.py`** — `$XDG_RUNTIME_DIR/assistant.sock`, mode `0600`, NDJSON. Not TCP. No network surface.
4. **`gemini_client.py`** — models by role, per-model rate limiter, exponential backoff, **and a ledger write on every call**.
5. **`daemon.py`** — asyncio, systemd `--user`, handles `status` / `cost` / `doctor`.
6. **`cli.py`** — thin client, ~5 ms exec, safe to bind to a hotkey.
7. **`fixtures.py`** — the `mock | record | live` switch. **Default to `mock` when no key is present**, so a missing key means "no network", not "crash on import".
8. **`assist doctor`** — the honest check. Verify the key, list the models you can actually reach, confirm the free-tier quota shape, check `pw-record` works, find the Hyprland socket, report the config.

**`assist doctor` is the most valuable thing in Phase 0.** It converts "I think it's set up" into a list of facts, and it's the first thing you'll run when something breaks at Phase 4.

**Tests must run without an API key** — that's the whole point of the harness. And be realistic about scope: fixtureing the **Live API is much harder than fixtureing REST**. A streaming session is a sequence of websocket messages, not one request/response, so you'll record full message sequences and replay them as scripts. Budget real time for it in Phase 1 — the Live path is the piece you most need to debug and the one you can least reproduce by hand.

---

## Step 6 — Wire up Hyprland

Check `hyprctl version` from Step 2 first.

**Hyprland 0.55+ (Lua config):**

```lua
hl.bind("SUPER + grave",       hl.dsp.exec_cmd("assist ptt start"))
hl.bind("SUPER + grave",       hl.dsp.exec_cmd("assist ptt stop"), { release = true })
hl.bind("SUPER + SHIFT + F12", hl.dsp.exec_cmd("assist halt"))       -- panic switch
```

**Older (`.conf`):**

```ini
bind  = SUPER, grave, exec, assist ptt start
bindr = SUPER, grave, exec, assist ptt stop
bind  = SUPER SHIFT, F12, exec, assist halt
```

The `release` flag is exactly push-to-talk — press starts, release stops. This is why Hyprland is a good host for this.

**Waybar module** — add to your waybar config:

```json
"custom/assistant": {
  "exec": "assist status --waybar",
  "interval": 2,
  "on-click": "assist ptt toggle"
}
```

Three Wayland rules that will otherwise waste your time:

- **No global hotkey daemon exists.** Use Hyprland binds. Ignore `xdotool`, `xbindkeys`, and X11 tutorials entirely.
- **Layer-shell overlays must set `keyboard-interactivity: none`.** An overlay that steals focus mid-sentence is worse than no overlay.
- **Clipboard is `wl-copy` / `wl-paste` only.** X11 clipboard tools fail silently.

---

## Step 7 — Working with mentors and debuggers

It's your project. They're helping you get unstuck, which means the goal is to make **your** bugs visible to **them**. Four habits do most of that work.

**1. Never give out your key.** Not in chat, not in a repo, not in a screenshot. Nothing in the architecture needs it — see the fixture harness below.

**2. Fixtures are the shared artifact.** When something misbehaves, the useful message isn't "it filed things wrong sometimes". It's:

```
GEMINI_MODE=record assist transcribe /path/to/clip.wav   # capture the behaviour
git add fixtures/ && git commit -m "repro: misfiled invoice cluster"
```

Now your mentor clones, runs `GEMINI_MODE=mock pytest`, and sees your exact failure — deterministically, no key, no quota. This is the single highest-leverage habit in the whole project, because in a non-deterministic system a fixture *is* a bug report.

**3. `assist doctor` output goes in every question.** It's the shared vocabulary for "what state is your machine in" — key valid, models reachable, PipeWire up, quota remaining, config resolved. Most "it doesn't work" conversations collapse to one line of doctor output.

**4. Keep module boundaries honest.** A mentor can only help debug one layer at a time. The seams already in the blueprint exist for this: the **`asr` seam** (§12.7) means audio problems and model problems are separable, and the **safety spine** means filesystem problems are separable from planning problems. If a bug touches four modules at once, the architecture is telling you something.

**On commits:** small and frequent. A mentor staring at a 2,000-line diff isn't debugging, he's reading.

**What not to build:** no per-user config, no multi-tenancy, no auth. This is one person's tool with helpers. Per-user machinery would be effort spent on a problem you don't have.

### If a mentor wants to run it live

He creates his own free project and key at `aistudio.google.com` — ten minutes, no card. His credential, his use, his quota. Then `GEMINI_MODE=live` on his machine.

That's the entire sharing story. There's no configuration for it, because there's nothing to configure — which is the sign the architecture is right.

## What comes after

| Phase | Goal |
|---|---|
| **0** | daemon, IPC, CLI, Gemini client, cost ledger, `assist doctor` |
| **1** | hotkey → mic → live transcription → markdown inbox + clipboard |
| **2** | Waybar module + overlay (keyboard-interactivity: none) |
| **3** | journal + shadow mode + indexer + Tier 0 rules cascade — **no writes at all** |
| **4** | executor on one test folder, review + undo |
| **5** | semantic search, memory, `assist ask` |
| **6** | meeting mode (mic+sink mix), pyannote diarization, batch transcribe |
| **7** | Kiswahili — flip `languages = ["sw","en"]`, enable the code-switching guards |

Phase 3 is where the project succeeds or fails. Phase 0 is where you find out whether your assumptions hold.

---

## Gotchas, collected

| Symptom | Cause | Fix |
|---|---|---|
| System-audio recording captures your mic | `--target` given an `object.id` | Use `object.serial` or `node.name` |
| X11 hotkey tool does nothing | No global hotkeys on Wayland | Hyprland binds |
| Overlay steals keyboard mid-sentence | Layer-shell keyboard interactivity | Set to `none` |
| Clipboard tool silently fails | Using `xclip`/`xsel` | Use `wl-copy`/`wl-paste` |
| 429 mid-transcription | Free-tier RPM/TPM/RPD hit — all return the same error | Check `assist cost`, let the §12.7 fallback chain absorb it |
| Quota exhausted despite low request count | TPM ceiling, not RPM | Count tokens, not requests |
| `assist` slow to start | Startup work in the CLI | Keep it a thin IPC client |
| Different result every run | LLM non-determinism | Record a fixture and debug against `GEMINI_MODE=mock` |
| Key suddenly stops working | Key file copied off your machine → auth-key leak detection | Never share it; mentors use fixtures |

---

## The next thing

Everything above is environment and skeleton. The first real code is **Phase 0**, whose only job is to prove the plumbing works and the assumptions hold — before you invest in transcription or file operations.

Say the word and I'll build it: the daemon, the IPC socket, the `assist` CLI with `doctor`/`status`/`cost`, the Gemini client with the fallback chain, the cost ledger, and the `mock | record | live` fixture harness. Then you run it and we tune against real `assist doctor` output.
