# Elaria console shell — integration pack for the mainline builder

Version **6.15** · dated **2026-11-02** · authored in the design chat, handed over as a zip.

This document is the contract. The shell is finished on the design side; everything below is what
the mainline repo needs in order to own it. Read it before touching a file.

---

## 1. What is in the zip

| path | what it is |
|---|---|
| `index.html` | **the deliverable.** One self-contained file: inline CSS + inline JS + inlined three.js r128 (MIT) + inlined visualizer engine. Zero external references, zero network calls, no API key touched. Runs from `file://` or any static server. ~724 KB, most of it three.js. |
| `src/shell.css` | the stylesheet, pre-build |
| `src/shell.html` | the markup, pre-build |
| `src/shell.js` | the application logic, pre-build |
| `elaria-visualizer.js` | the WebGL orb engine (`window.Elaria.create`). Owner-supplied, v1.0.0 + the per-state palette work described in §6 |
| `vendor/three.min.js` | three.js r128 UMD, vendored so the build never needs a CDN |
| `build.py` | assembles the four sources into `index.html`. **Refuses to build** if any JS it is about to inline fails `node --check` |
| `serve.py` | static server on `0.0.0.0:8123` with `Cache-Control: no-store` so a reload is never stale |
| `harness.js` | shared jsdom loader used by both test files |
| `smoke.js` | 114 DOM assertions against the built file |
| `session-test.js` | 23 DOM assertions: session switching, interrupts, reload-from-storage |

Build: `python3 build.py` (needs `node` for the syntax gate). Test: `npm i jsdom` then
`node smoke.js && node session-test.js`. Both exit non-zero on failure; wire them into CI as-is.

---

## 2. The one rule that governs the merge

The console lives in the **hands/console lane**. The parallel-chat firewall is unchanged and absolute:
**additive-only; zero edits to `daemon.py`, `transcribe.py`, `live_client.py`, `cli.py`, `config.py`,
`ladder.py`, `pyproject.toml`, `HANDOFF.md`, or the storage/hands branches.** The shell lands as its own
module/asset with its own PR. Merges stay design-gated — this pack does not authorise a merge.

---

## 3. Public surface: `window.ElariaShell`

The shell boots standalone and stays honest when nothing is attached (stub replies labelled as stubs,
lamps amber/red). Pre-wire pane states are **not all the same, on purpose**: transcript and audio read
`[PENDING] no wire — nothing to show yet`, while **memory boots as a labelled `[WARN] shell copy`** —
eleven real cards baked from the design record, badged `shell copy`, never presented as live, and
discarded the moment `ElariaShell.memory(cards)` delivers real rows. An empty memory pane would break
the owner's standing requirement that the console has a place to see her memories; a labelled copy
keeps the view real and the honesty intact. A ship order that says "all panes pending" is wrong; this
paragraph is the correction. The repo takes ownership by calling into this object. Nothing else
in the page is API.

```js
ElariaShell.connect(adapter)        // adapter = { name, send(text, ctx) -> string | {text, audio} }
                                    //   ctx = { session, history } ; audio = URL or <audio> element
ElariaShell.disconnect()            // wire lost: lamps, offline state, notification
ElariaShell.attachSocket(url?)      // THE WIRE. defaults to ws://127.0.0.1:8744/elaria  (see §5)
ElariaShell.notify({ text, speak }) // proactive tap on the shoulder: mini-orb toast + rail pip
ElariaShell.say(text)               // push an unprompted reply into the log
ElariaShell.setState(name)          // idle | listening | thinking | speaking | offline
ElariaShell.levels(role, level)     // push amplitude 0..1, role 'input' | 'output'
ElariaShell.transcript(rows)        // rows: { ts, id, who, text, peak, verdict }  -> transcript pane goes LIVE
ElariaShell.audio(rows)             // rows: { name, size, age, tier }              -> audio pane goes LIVE
ElariaShell.memory(cards)           // cards: { t, v, w }                          -> memory pane goes LIVE
ElariaShell.state                   // getter: { daemon, mic, state, pane, section }
```

Until `connect`/`attachSocket` runs, the shell answers slash commands itself and says plainly that
nothing is on the wire. **Do not delete that behaviour** — it is what makes the console testable with
the daemon off, and it is the owner's honesty rule: amber means exists-but-unreachable, red means
does-not-exist-yet, and a pane with no data says so instead of showing nothing.

---

## 4. What the wire has to feed, in priority order

1. **replies** — `send(text, ctx)`; the shell types them out and drives the orb from `levels`.
2. **state** — push `setState` on wake / voice-end / model-start / tts-start / tts-end so her shape is true.
3. **transcript rows** — the daemon journal, seven-field contract (`ts level event session_id peak verdict detail`).
4. **audio rows** — the storage manifest (file, size, age, tier hot/cold/never-retry).
5. **memory cards** — her live store, replacing the baked shell copy.

Each of 3–5 flips its pane badge from `pending` to `live` the moment real rows arrive, and demo rows are
discarded. There is no migration to write: the panes are dumb renderers over these three arrays.

---

## 5. Socket protocol (client half already implemented in `src/shell.js`)

Transport: **WebSocket, localhost only**, default `ws://127.0.0.1:8744/elaria`. One JSON object per
message. The client reconnects with exponential backoff (700 ms × 1.7, capped 15 s) and calls
`disconnect()` on close, so the wire lamp tracks reality without help.

client → daemon

```jsonc
{ "t": "hello", "v": 1, "client": "console", "caps": ["text","transcript","audio","memory"] }
{ "t": "send",  "id": 7, "text": "…", "session": "boot", "history": [ {r,t,ts}, … ] }   // history ≤ 20
```

daemon → client

```jsonc
{ "t": "hello-ok", "v": 1, "name": "elaria-daemon" }
{ "t": "reply", "id": 7, "text": "…", "audio": "optional url or omitted" }
{ "t": "reply", "id": 7, "error": "reason" }                 // rejected promise, shown as [BROKEN]
{ "t": "state",  "name": "listening" }
{ "t": "levels", "role": "input", "level": 0.42 }
{ "t": "notify", "text": "…", "speak": true }
{ "t": "transcript", "rows": [ … ] }
{ "t": "audio",      "rows": [ … ] }
{ "t": "memory",     "cards": [ … ] }
{ "t": "bye", "reason": "…" }
```

Rules the daemon side must honour: `v` mismatch → refuse with `bye`; `send` replies carry the same
`id`; a `send` with no answer within 45 s is abandoned by the client as "daemon went quiet"; the socket
**never** carries the API key, and the console never makes any non-localhost request.

---


## 5a. Text bridge — 2026-11-03 implementation and owner ruling

The console and hands builder are **the same builder on the same branch**, with separate
commits/revert paths. This supersedes §2's lane-topology/own-PR wording: no PR is authorised.
The protected-file firewall and verbatim engine pin remain absolute.

`run_bridge.py` starts a **separate process**, implemented in `bridge.py`, speaking the
existing owner-authenticated newline-JSON Unix IPC. It does not mount a new daemon handler,
start a second assistant, import a model SDK, or change the daemon's authority policy.
Verified on parent `82880e8`: `daemon.py:974`,
`async def _console_say(self, params: dict) -> dict`; text, speak=false by default,
shared `_ask`, reply plus shared conversation. The typed route bypasses PTT, transcription
and transcription-confidence gating. It does not repair those paths or prove model availability.

**Minimum implemented:** hello/hello-ok (v1), same-ID send/reply, state, levels.
**Levels are SYNTHESISED TEXT CADENCE, NOT measured audio.** This is the owner's explicit
ruling for text turns. Both the bridge frames (`source: synthesised-text`, `measured: false`)
and the shell's typewriter levels are labelled accordingly in code. The wrapper permanently
labels them; the engine's public `setLevels` consumer path is used unchanged. The named
speaking state during text display does **not** assert TTS playback. A future audio path
must replace synthesis with measured levels/`attachElement`; audio is not implemented here.

Readiness contract correction (2026-11-03): use the nested
`connectivity.effective_mode == "ONLINE"`, the preference-resolved enum used by
`ModeStatus.is_online`, with consistent `online is True`, `offline is False` and
`forced_offline is False`. Missing/malformed/contradictory fields refuse. The top-level
`connectivity_mode` is also uppercase; only the display alias `connectivity.mode` is
lowercase. Network health is not preference resolution: explicit online with an unhealthy
last probe remains eligible under the daemon's policy. `gemini_mode` and reply `mode` are
separate, config-derived lowercase values; they must still equal `live`. No case-folding
or fallback to a display alias is used. Actual `local-awareness` and `local-hotword-checkin`
reply tags are labelled non-model; show-off's offline `local` tag is an OFFLINE error.

Only a daemon reporting **live + online** receives turns. Genuine model words are returned
verbatim. Local-intent/memory responses carry an explicit non-model label. Mock/fixture,
queued, timeout, withheld and unknown-provenance results are errors, never model answers.
Readiness is checked before acknowledgement and every send, then polled every three seconds;
loss closes the wire and restores disconnected lamps. No wire failure falls back to stubs
in a window which attached a wire. Standalone `index.html` still has its honest stub fallback.

Notify, transcript rows, audio rows, live memory and reply audio are **not implemented**.
Transcript/audio remain PENDING by default; memory retains the eleven labelled shell-copy
cards. The connect sentence no longer incorrectly declares all panes live. No placeholder
arrays are sent to turn badges green. A green wire means connection, not a proven model answer.

The launcher starts a **new loopback-only HTTP/WebSocket listener on 127.0.0.1:8744**.
It does NOT launch, widen, narrow or edit `serve.py`; that existing server remains
**0.0.0.0:8123** and would expose its static files to reachable LAN clients if run separately.
Open the private URL printed by the launcher. It carries a random, per-process local pairing
token in the URL fragment, **not an API key**. Public HTTP pages do not expose the token or
shell content. The authenticated shell and `/elaria` requests require the token; WebSocket
requests additionally require the exact loopback Origin/Host. File-origin and cross-origin
clients are refused. Do not publish the pairing URL; stopping the process invalidates it.
The browser makes no non-localhost requests; no API key/configuration is loaded by the bridge.

The existing shell client now enforces loopback URLs, protocol acknowledgement version,
700 ms × 1.7 reconnect backoff capped at 15 s (reset after hello-ok, not TCP open), the
45-second abandonment and same-ID matching. Connection loss rejects pending calls without
replaying them. History is at most 20 entries, trimmed oldest-first to the 64 KiB frame bound;
it is display context only. The daemon owns conversation/authority, including across shell
tabs. The bridge forwards only text, speak=false and history_limit=1 to console.say.

Limits: 8 KiB UTF-8 input, 32 KiB UTF-8 reply, four connected clients, one turn at a time,
3-second status deadline and 35-second turn deadline. An IPC response lost after sending
means **outcome unknown**, not rollback; the bridge blocks later turns across reconnect until
an explicit restart after conversation review. No automatic retry, queue drain or cancellation
claim is made. A disconnect cannot undo an action the daemon may already have performed.

See `BRIDGE.md` for the committed launcher, checksum-first one-line delivery and verification
boundary. `gate_verbatim` still requires ENGINE_SHA
`5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.

---

## 6. Her states: the owner's spec, verbatim

> *"listening orange, thinking, rapid movement then talking pulsing"*

That sentence is the whole doctrine. Anything that contradicts it is a defect, including earlier
sections of this document and earlier packs (v6.2-v6.4 got it wrong in both directions and are trashed).

| state | look | how |
|---|---|---|
| idle | her shipped calm | shipped numbers, scatter 0 |
| **listening** | **ORANGE** | warm window held: `hueBase .45, hueSpan .12, hueSpread .18, hueScatter 1, hueDrift 0` |
| **thinking** | **rapid movement** | `speed 1.80, weave 1.60, density .95, hueDrift .090` — the fast, busy one |
| **speaking** | **pulsing** | a speech-rate metronome in `step()` drives `uPulse`/`uPulseR`/`uContract`/`uBreath` on a beat that quickens with amplitude |
| offline | dim, near-still | shipped numbers |

**The warm window is a bound, not a vibe.** The ramp's stops 4-6 (0.444-0.778) are ORANGE/AMBER/ORANGE.
Listening must satisfy `hueBase >= 4/9` and `hueBase + hueSpan + hueSpread <= 7/9`, with `hueDrift == 0`,
or the time term walks her out of orange and the owner reports it. `smoke.js` asserts the inequality.

**Why `hueScatter` exists.** Ribbon colour offsets used to be `id * 0.113`, linear in the ribbon index.
The inner ring's ids start at 40, so any per-state offset that keeps the outer ring in a narrow window
wraps the inner ring somewhere else entirely. `mix(id*uHueId, h1(id*3.7)*uHueSpread, uHueScatter)` fixes
that: scatter 0 reproduces the shipped formula exactly (idle, thinking, speaking, offline all use 0, so
their look is untouched), scatter 1 confines every ribbon to `h1(id)*hueSpread` inside the state's window.
When you add a state, choose scatter deliberately and re-check the window arithmetic.

All parameters damp through `TAU` (~1 s) so a state change glides. A hard cut reads to the owner as a crash.

**v6.15: the maker's final file, byte-identical, and a build gate that keeps it so.** The owner's
ruling, 2026-11-02, verbatim: "stop trying to learn from what I sent u just implement it verbatim as
is thstts bbeen the problem from the start." The engine inlined in this pack is the maker's final
upload, sha256 `5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`, and `build.py`
carries `gate_verbatim`: if one byte of `elaria-visualizer.js` drifts from that pin, the build
refuses and names the ruling. The v6.14 owner layer (thinking motion override, speech-rate
metronome, antialias true, pixel-count floor, uSizeScale floor) is DELETED whole — those five items
were exactly the "learning" the ruling forbids. The owner's earlier motion and smoothness specs are
SUSPENDED as engine edits: if the maker's motion or smoothness displeases him, the road is a word to
the maker or an explicit new ruling, never a silent edit. The pin moves only when the owner hands
over a new maker file. `smoke.js` asserts the verbatim markers (antialias false, the maker's adaptive
loop and uSizeScale lines, no `beatT`, no floors) and the palette rows.

**What the console adds is integration, not modification.** `Elaria.create(el.stage,
{ simulate: true, fit: 1.8 })` — `fit: 1.8` is the maker's snippet verbatim, his own number for a
narrow side panel; `simulate` is the maker's designed option and the console needs it pre-wire so she
reads "simulated" honestly instead of frozen. Everything else is shell-side: layout, panes, commands,
lamps, sessions, wire consumers. When the wire lands, her voice enters through the maker's sanctioned
hooks — `setLevels('output', {level})` per audio frame, or `attachElement(audioEl)` — consumer-side,
and the priority path for §5 wire consumers. Call `destroy()` if the panel is ever removed (the
console never removes the rail; the floating mini-orb is a move, not a removal). The maker's cautions
are verified shell-side: the container has a real height (`.stage-box` is `flex: 1 1 auto;
min-height: 0` inside a definite grid row, with an 80% maximum stage height; no floating
narrow-screen stage); three.js is inlined ahead of the engine; `useMicrophone()` needs https
or localhost (`serve.py` still binds **0.0.0.0:8123**, not loopback-only; the bridge uses
127.0.0.1:8744; `/mic` fails honestly through try/catch on `file://`).

**Colour ruling stands (2026-11-02): the maker's per-state worlds are the owner's adopted look.**
`PALS` — nine-stop palettes per state, cross-faded on every `setState`: idle violet, listening
blue-cyan, thinking magenta-pink, speaking orange-amber, offline muted. The owner adopted the
recoloured file twice with emphasis ("this is the final thingy... remember this is how it should look
like") and archived `uploads/image-15.png` as the reference; his earlier verbatim "listening orange"
spec is superseded by that adoption. With the engine pinned, the only colour lever left is a new
maker file. One caution for comparisons: states differ in motion AND colour by design; judge her
state against the same state in the original, never thinking against idle.

**Historical v6.9 explanation, not permission to edit the now-pinned engine:**
Smoothness was investigated through pixel ratio and MSAA, not shader work. The owner's last visual gap ("just a matter of
smoothening something out") was aliasing: the renderer was created with `antialias: false`, and the
adaptive quality loop dropped pixel ratio whenever mean frame time crossed 26 ms — which a small preview
iframe does constantly, so she rendered at ratio 1 with no MSAA and read as jagged, while the original
full-window demo ran at ratio 2 and read as smooth. v6.9 sets `antialias: true` and gives the adaptive
loop a pixel-count floor: canvases under 1.5 M rendered pixels keep their device pixel ratio (few pixels
is cheap; starving them only buys aliasing), while full windows keep the original thermal protection
exactly as shipped. Do not "optimise" either back: MSAA off or an unfloored ratio reproduces the jaggy
render the owner rejected.

**GLSL is not checked by `node --check`.** v6.2 shipped four uniforms *used* in three shaders but never
*declared*, so every shader program failed to compile and the orb drew nothing — silently. `build.py`
runs `gate_glsl`: it resolves each shader's concatenated source (PAL and VERT_COMMON prefixes included)
and **refuses to build** if any `uXxx` is used without a `uniform ... uXxx` declaration in that same
shader. The current engine is absolute-pinned: any engine change is out of scope, even if
the GLSL gate passes.

## 7. Layout rulings that are load-bearing (do not "improve" these away)

- **2026-11-04 owner ruling supersedes the narrow-rail sizes:** sidebar `--sbw` · flexible chat
  · right panel `--orbw:36vw` on wide screens. Stage region is bounded to 80% of panel height;
  engine and fit:1.8 remain unchanged. Explicit grid placement prevents fixed-overlay sidebar
  removal from shifting chat into a zero-width column. Below 1040px the rail yields to 28vw;
  at <=680px it is hidden, never floating over or cropping the composer.
- **Sidebar, top to bottom:** sessions (permanently open) then transcript · memory · audio fold-outs.
  Fold-outs animate **both directions** (`max-height`/`opacity`, 0.3 s) — an instant show/hide reads as a bug.
- **Transcript opens full screen** over the chat *and* her panel, stopping at the sidebar edge, so the
  sidebar stays where it is. Esc plays a 0.18 s exit animation before hiding. `#full` occupies
  grid columns 2/-1, row 1, leaving the bottom footer visible. Below 940px the sidebar opens
  only on explicit request and offers a close control; the chat retains its column.
- **Her panel has no buttons.** State and signal rows exist in the standalone demo only, to stimulate
  modes by hand; in the console every state arrives in real time. `/state`, `/sim`, `/mic` remain as
  typed commands. The panel top line is `ELARIA` + live readout (state word · source · meter).
- **Header is a whisper:** session path and three controls. Four status dots now live in the
  bottom-pinned footer, with state-specific hover text. The outer three-line bridge banner
  is removed; its facts have the homes specified in BRIDGE.md.
- **Colour descriptions stay:** the colour-key line in the boot transcript remains. The old
  swatch row is absent, consistent with the already-accepted v6.15 smoke gate.
- **Colour semantics:** white = his words (and `paintYou` adds colour to nothing else but `/commands`),
  green = her words only, orange = names/labels/numbers, blue = machine, violet = aside, amber = not yet,
  red = broken/absent, ice = paths, acid = commands. `paintYou` emitting zero spans for plain prose is
  asserted in `smoke.js`; keep that assertion.
- **No decorative ASCII banners, no dotted blocks.** Rejected twice, in writing.
- **Nothing is deleted at a narrow width** — it becomes an overlay. Below 680 px her panel becomes a
  96 px floating square rather than vanishing.

---

## 8. Behavioural contracts the tests already enforce

- Session switching and "new session" are **never blocked by an in-flight reply**: `interrupt()` cuts the
  sentence, stores it **in full** in the session it belongs to (the session is bound at send time), and
  prints one `[note]` line naming that session. `Esc` uses the same `interrupt()`; clearing the typewriter
  timer without resolving its promise used to lock `busy` forever.
- Reloading restores sessions, transcript and prefs from `localStorage` key `elaria.console.v6`.
- WebGL absent → the stage shows an honest one-line fallback and everything else keeps working.
- Microphone, when granted, drives the orb only: nothing is recorded, stored or uploaded by the shell.

---

## 9. Acceptance for the merge

1. `python3 build.py` clean (JS gate **and** GLSL gate), `node smoke.js` 114/114, `node session-test.js` 23/23, in CI.
2. `index.html` still has **zero external references** (grep it; a CDN `<script src>` breaks the offline
   and sandboxed-preview cases and has broken them before).
3. With no daemon: lamps `ok/wait/wait/gone`, panes `pending`, replies labelled stub. With the daemon:
   wire lamp green within one hello round-trip, and `transcript`/`audio`/`memory` badges read `live`
   after their own first nonempty feed, never from another pane or an empty placeholder.
4. Owner eye/ear sign-off on: her size and position, the full-screen transcript, the mini-orb
   notification, and listening reading cool rather than orange. He is the instrument; the suite is not.
