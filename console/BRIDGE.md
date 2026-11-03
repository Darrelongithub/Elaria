# Local text bridge — operator handoff

**TESTED-ONLY. Real IPC/WebSocket/DOM wiring; no owner live-model or WebGL/audio proof.**
The standalone v6.15 shell remains the honest fallback if owner verification fails.

## What runs

`console/run_bridge.py` launches one separate process, serving the console and §5 WebSocket
on **127.0.0.1:8744**. It does not start/restart the assistant, install anything, change a
checkout/configuration, or read a model key. It does **not** launch `serve.py`; that file
still binds **0.0.0.0:8123**, unchanged. There is no LAN/remote-preview mode in this launcher.

Required: Linux, Python 3.11+, an existing environment with `websockets>=14,<18`, and the
owner's existing daemon socket. Use the existing project interpreter; do not install or
repair dependencies implicitly. The separate dependency declaration is
`console/requirements-bridge.txt`. Python 3.11.2 was tested here; owner Python 3.14 was not.

The launcher and its five pinned sibling payloads can also be placed in a separate directory
without switching or editing the owner's mainline checkout. Its root is its own directory,
not the current working directory; no assistant package import is required. Use the existing
interpreter by its actual path in that case. A missing/mismatched file or dependency is a
hard stop, not permission to fetch, install or reconstruct something from chat.

## Checksum-first, one-line launch

Committed executable: **`console/run_bridge.py`**.

SHA256: **`cfcfadb085a1919b37f8ed287543a62dd0e8927e2454efbe036c3bbc154cbc23`**.

From a copy containing this release's `console/` payload and the existing `.venv` interpreter,
this is one physical command line. It checks the launcher before Python runs; the launcher
then checks all five payload hashes before importing the bridge. A mismatch stops.

`test "$(sha256sum console/run_bridge.py)" = 'cfcfadb085a1919b37f8ed287543a62dd0e8927e2454efbe036c3bbc154cbc23  console/run_bridge.py' && .venv/bin/python -IB console/run_bridge.py`

`-I` isolates Python import paths; `-B` avoids bytecode writes. No standalone install, branch
switch or mainline deployment is performed by this command. If using an extracted bundle
away from the checkout, adjust only the already-verified file/interpreter locations; do not
skip the launcher hash comparison. This document does not certify an unseen rewritten command.

For the separate handoff bundle, extract it **outside** the owner checkout and open a
terminal at its extracted root (the directory containing `console/`). If the owner's
existing interpreter is `/home/darrel/Elaria/.venv/bin/python`, this alternative one-liner
uses it without copying files into or switching that checkout. A missing interpreter or
checksum mismatch stops; there is no install/repair fallback.

`test -x /home/darrel/Elaria/.venv/bin/python && test "$(sha256sum console/run_bridge.py)" = 'cfcfadb085a1919b37f8ed287543a62dd0e8927e2454efbe036c3bbc154cbc23  console/run_bridge.py' && /home/darrel/Elaria/.venv/bin/python -IB console/run_bridge.py`

Optional **`--check`** performs artifact/dependency checks and one existing-daemon `status`
RPC, then exits; it opens no browser server and sends no chat/model/voice turn. `--socket`
accepts an explicit absolute existing socket path when XDG_RUNTIME_DIR is unavailable.
There is no guessed socket, alternate host, auto-start, paid/model fallback or key setup.

## Open it

The process prints a **private local pairing URL**. Open that URL on the **same machine as
the daemon**. Its fragment contains a newly generated local capability token, not a model
API key. Keep it private; do not paste it into chat/logs. It expires when this process stops.
The root page alone contains neither token nor console memory cards. Both the shell asset
and WebSocket require the token. The WebSocket also requires exact loopback Host/Origin.
File-origin, cross-origin and non-loopback socket URLs are refused.

Opening the page only probes daemon status. **A model call can occur only after you submit
text**, through the existing `console.say` handler. Live/online readiness is required;
mock, record, unknown or offline posture does not forward turns. The launcher never changes
that posture. If it isn't ready, keep the fallback rather than treating a stub as her answer.

Ctrl-C stops this bridge only. It does not stop the daemon or roll back a submitted turn.
If a turn's outcome is unknown, inspect the existing daemon conversation before restarting
or repeating it. Reconnecting the browser never resends a turn. The bridge deliberately
blocks further turns after a lost IPC response until an explicit restart after review.

## What is live / what is not

| Surface | This release |
| --- | --- |
| hello / hello-ok | v1 handshake after real daemon live/online status; mismatch → bye |
| send / reply | same ID, real existing console.say route; live-model words preserved verbatim |
| state | bridge/request lifecycle; named speaking state also denotes text display, not TTS |
| levels | **synthesised text cadence**, source-labelled; **not measured audio** |
| local daemon answers | visibly labelled **not a model answer** |
| mock / fixture / queued / timeout / withheld / unknown result | explicit error, never passed off as model output |
| speech, notify, journal transcript rows, audio manifest, live memory | **not implemented** |
| transcript/audio panes | PENDING by default; explicit `/demo` remains labelled sample |
| memory pane | eleven labelled shell-copy cards, not a live-store claim |

A green connection is not proof of a model answer. No empty placeholder arrays flip pane
badges LIVE. The wrapper labels text-only operation and synthesised levels permanently.
The original engine is byte-identical under `gate_verbatim`; no visualizer knob/shader edit.
The browser audio consumer hook `attachElement` exists, but this bridge does not deliver audio.

The shell's browser tabs do **not** create independent daemon conversations. Browser history
is capped/trimmed display context and is not injected into model history; the existing daemon
owns conversation and authority. The bridge forwards only text, speak=false, history_limit=1.
It neither mounts new hands routes nor converts model words into actions. Existing local
intents, disclosure and hands refusal/consent boundaries remain the daemon's responsibility.
An owner-authenticated typed request is not evidence of an effect or automatic consent.
A friend being present does not itself enable the daemon's existing company/show-off posture.

## Bounded operation and known failure semantics

- Four connections maximum; one turn at a time per bridge process.
- 64 KiB incoming WebSocket message, 8 KiB UTF-8 user text, 32 KiB UTF-8 reply.
- The client trims oldest history to fit the message bound without altering daemon history.
- 3-second status and 35-second turn deadlines, below the client's 45-second abandonment.
- 700 ms × 1.7 reconnect delay, capped at 15 s; only a successful hello resets it.
- A disconnect/timeout is **not** cancellation or undo. No automatic replay occurs.
- A posture change between status and dispatch can still cause the daemon to queue a turn;
  that is surfaced as QUEUED, never a model answer. Do not resubmit it blindly.
- No content/credential logging; raw daemon errors and unrelated IPC events aren't forwarded.
- The renderer still uses browser-local session storage, as the standalone shell does.
- Same-UID compromise, browser extensions, and physical access to the private pairing URL
  are outside this local capability boundary. This is not an OS sandbox.

## Local evidence versus owner verification

The local gates use keyless synthetic backends, real Unix/WebSocket/HTTP sockets, the actual
launcher process, and jsdom. Canvas is a test double; no hardware pixels/audio are asserted.
An additional test calls the real fixture-backed daemon's existing `console.say` and confirms
that its mock result cannot be presented as a live model answer. Shared fixtures are untouched.

Owner verification remains: correct local readiness/lamp behavior, one live typed reply,
its real provenance, readable text-driven orb/state behavior, and honest pending pane labels.
No microphone, voice repair, kitty scene, install, key transfer or privileged operation is
part of that verification. If this gate cannot be completed in time, show the standalone
shell with its explicit stub and shell-copy labels instead. No success is claimed in advance.
