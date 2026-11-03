# Console text bridge — 2026-11-03 checkpoint

**TESTED-ONLY. Built, not an owner live-model/browser/audio demonstration.**
**Kitty action work parked separately. Scene NOT READY. No PR.**

Branch: `arena/b65d5161-elaria`.
Parent: `82880e86b2af6361b0d0aa0b4b2cbbc9f3a181ed`.
Resulting console-only commit SHA is supplied in the delivery message.

## DONE

- Applied the owner's correction: console and hands are one builder on this branch,
  with separate commits and revert paths. No branch switch or force-push.
- Parked the nine-path kitty action checkpoint in stash
  `78bc7cc24f584f063b41caec20b24aabc3f41ff2`, also exported as an independent patch in
  the workspace outside this checkout. Its interrupted rerun finished **2448 passed,
  6 skipped in 88.74s**. That work is not part of this console commit; its final report
  and commit remain pending. No source/evidence from it is used to inflate console gates.
- Reverified HEAD's registered `console.say`: `src/assistant/daemon.py:974`,
  `async def _console_say(self, params: dict) -> dict`. Text, speak=false by default,
  shared `_ask`, result plus conversation history. The prior read-only cross-check at
  mainline `fdcdb47fb82707dc9f2a47e352473dc9e781cd07` found identical ASTs for typed
  entry/shared turn/generation. No new handler or protected-file hunk is necessary.
- Added `console/bridge.py`, a separate HTTP/WebSocket process using the existing
  newline-JSON Unix IPC. It does not import a model SDK, load a model key, replace the
  assistant, monkeypatch the daemon, read its database or implement a second policy layer.
- Implemented the four requested message paths: **hello/hello-ok, same-ID send/reply,
  state, levels**. Version mismatch refuses with bye. Existing model words are preserved
  verbatim; local daemon responses are explicitly labelled non-model.
- Adopted the levels ruling: **SYNTHESISED TEXT CADENCE, NOT measured audio**, labelled
  in code, wire metadata, the wrapper and INTEGRATION.md. Named speaking state during
  text display is not a TTS assertion. Maker engine untouched.
- Added checksum-gated `console/run_bridge.py` and an additive consumer wrapper. The
  process binds **127.0.0.1:8744 only**. It does not run or edit `serve.py`; that server
  still binds **0.0.0.0:8123**, unchanged. No automatic daemon start or dependency install.
- Private per-launch local pairing token, exact Host/Origin checks, owner-only socket
  mode and kernel peer UID verification. The root page does not disclose token or shell
  content. File/cross-origin requests are refused. No API key crosses the browser wire.
- Positive live/online status required before hello-ok and each turn, plus periodic health
  checks. Failure closes the wire so lamps disconnect. Fixture/mock/record, queued,
  timeout, withheld or unknown replies cannot masquerade as model answers.
- 64 KiB WebSocket messages; 8 KiB input and 32 KiB reply; four clients, one turn at a time.
  3-second probe and 35-second IPC turn bounds. Lost IPC response after sending freezes
  later turns, including reconnects, pending explicit review/restart. No automatic replay,
  queue drain, cancellation-as-undo or arbitrary IPC forwarding.
- Browser session/history are display context only; daemon conversation/authority remain
  authoritative. Only text, speak=false and history_limit=1 reach console.say.

## Console-only client integration corrections

The wrapper uses the public ElariaShell API. The existing client received limited wire
corrections, not visualizer edits: explicit synthesised-text comment, localhost URL guard,
hello-ok version check, reconnect reset after successful hello (not each TCP open), immediate
pending-call failure on disconnect, no silent fallback to stubs after attaching a wire,
64 KiB history trimming, and a truthful connection sentence which no longer declares all
panes live. The compiled index was rebuilt with the existing build/gate script.

The standalone index still boots without network and retains labelled stubs and shell-copy
memories when no wire is attached. Standalone regression tests remain green.

## LIVE versus PENDING

| Surface | Implementation status | Owner proof |
| --- | --- | --- |
| hello / hello-ok / bye | Implemented, real-socket tested | Pending |
| typed send / reply | Existing daemon route, same ID, provenance guarded | **Live model pending** |
| state | Connection/request lifecycle, text-display distinction | Owner rendering pending |
| levels | Synthesised text cadence, explicitly not measured | Owner rendering pending |
| speech / reply audio | Not implemented | Pending |
| notify feed | Not implemented | Pending |
| transcript / audio rows | Not implemented; PENDING defaults | Pending |
| memory feed | Not implemented; eleven labelled shell-copy cards retained | Pending |

No empty stub arrays turn pane badges LIVE. A green wire is not proof of a model response.
The existing `attachElement` audio hook remains available for later consumer work; no audio
artifact is served, measured or claimed here.

## DEFECTS / boundaries

Typed entry bypasses microphone capture, transcription and transcription-confidence gating.
This is a source-path finding, not a voice repair or assertion that the owner's provider,
quota, current daemon mode or microphone is healthy. The clipping/transcription/parser work
remains separate and untouched.

The bridge exposes existing console.say intent routing; it does **not** make arbitrary model
output executable, mount new hands routes, grant action consent or unlock blocked kitty
families. Owner authentication is not effect evidence. Existing company/show-off posture is
not enabled automatically just because a friend is in the room.

A posture race can still queue a submitted turn inside the daemon; the bridge reports QUEUED
rather than presenting a model answer or replaying. A browser disconnect cannot undo a
submitted turn. Same-UID compromise/physical access/browser extensions are outside this local
capability boundary; it is not an OS sandbox.

## Verbatim local gates

Main Python environment: **3.11.2**; WebSocket library **17.4**; Node **v22.22.3**;
jsdom **30.1.3**. No Python 3.14 acquisition/run or owner hardware call.

New bridge suite (64 new tests):

```text
64 passed in 6.66s
```

Full suite, with kitty work parked:

```text
2463 passed, 6 skipped in 94.66s (0:01:34)
```

Arithmetic: **2399 accepted baseline + 64 new console tests = 2463**.
The parked 49 kitty tests are not in this commit's total.

Existing local-only console build/smoke/session gates:

```text
PASS 114   FAIL 0
PASS 23   FAIL 0
PASS: no src="http or href="http references in index.html
```

Ruff:

```text
All checks passed!
```

Additional compatibility run with the bridge imported against websockets **14.2**:

```text
64 passed in 6.60s
```

Isolated launcher subprocesses in that compatibility run still use the primary environment
(17.4); this is not a claim of a separate 14.2 launcher installation or a Python 3.14 pass.

The new tests include real HTTP/WebSocket/Unix transports, a separate launcher subprocess,
status-only preflight, tamper refusal before import, host/origin/pairing and peer-UID checks,
model-provenance refusals, deadlines/unknown outcome, disconnect/no replay, and DOM delivery.
A direct call to the existing fixture-backed daemon proves IPC interoperability and verifies
its mock result is rejected as non-live. The end-to-end renderer uses jsdom with a 2D canvas
test double; no real WebGL pixels or owner audio are claimed. No shared fixture was changed.

Local logs: `.venv/console-wire-full-suite.log` and
`.venv/console-wire-shell-gates.log` (ignored, not owner artifacts). No automated CI claim.

## Structural audit

All **287 parent files** were byte-compared. **284 remain identical**. The only modified
parent files are `console/INTEGRATION.md`, `console/src/shell.js`, and rebuilt
`console/index.html`. Everything else is additive, console-owned code/tests/docs.

`daemon.py` is byte-identical to the accepted parent and still has exactly the same eight
insertions versus pre-kitty `35adbba`. No transcribe/live-client/CLI/config/ladder/pyproject/
HANDOFF/storage/hands/shared-fixture edit. No owner packet, collector, drift or inventory edit.

`gate_verbatim` passed against the untouched engine, including its literal inclusion in the
built shell. SHA256:
`5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.
All five runtime payload hashes embedded in the launcher were independently recomputed.

## NEXT / delivery

Executable: `console/run_bridge.py`.
SHA256: `cfcfadb085a1919b37f8ed287543a62dd0e8927e2454efbe036c3bbc154cbc23`.
Checksum-first one-line invocation and explicit prerequisites are in `console/BRIDGE.md`.
The launcher and its pinned siblings can be delivered as a separate directory, using the
existing interpreter/daemon without switching the owner's checkout. A generated handoff
archive, if supplied, is outside Git; runtime source and launcher are committed.

The outstanding demo gate is **owner-side live typed reply plus actual browser presentation**.
No successful owner turn is claimed in advance. If readiness/live verification cannot be
completed in the available time, the standalone shell is the honest fallback.

After the console priority gate, resume the parked kitty audit/checkpoint as a separate commit.
Scene remains NOT READY. No PR, protected-file grant, hardware scene or extra owner instrument
is requested by this checkpoint.
