# Hands console — standalone synthetic bridge (R7/R8)

**[TESTED-ONLY] Synthetic bridge preflight green.** `shell.qml` now uses
`bridge.js` over a Unix `Socket`/`SplitParser`, not local preview buttons.
The same controller is exercised under Node against the actual Python IPC
server, durable parked queue and real tmp-only hygiene library. This is **not**
a Qt rendering, keyboard-focus or owner-gate pass.

**[UNVERIFIED]** Targets Quickshell **0.2.1**. Socket `write` + `flush`,
`connectionStateChanged`, SplitParser `read` and `Quickshell.env` were checked
against upstream v0.2.1 headers at
`a1a150fab00a93ea983aaca5df55304bc837f51b`. No Quickshell/qmllint executable is
available here: qmllint is **N/A**, not green. No frozen-console mounting,
installation, unit, daemon registration, live posture source or notification
adapter ships. The owner scene remains **unscheduled by design**.

## Implemented boundary

- **[TESTED-ONLY]** Backend: `python -m assistant.hands.bridge`. A new process
  mints its own `SyntheticSpace`; no request or CLI argument can select an owner
  tree. Default endpoint is `$XDG_RUNTIME_DIR/elaria-hands.sock` (existing
  `runtime_dir()` fallback in headless environments). `--socket` changes only
  the control-plane endpoint, never the task root.
- **[TESTED-ONLY]** QML uses `ELARIA_HANDS_SOCKET` if set, otherwise the XDG
  endpoint. Without either, it stays disconnected. It does not start a backend,
  task process, HTTP service, model client or desktop notification command.
- **[TESTED-ONLY]** R7: exact trim/casefold yes/no is bound to the visible pending
  ask ID and whole-plan SHA-256. Typed decisions and buttons share the controller.
  No focus produces `no ask is selected`, not an intent. `yeſ` also folds to yes;
  other text, including shell-looking text, remains intent data.
- **[TESTED-ONLY]** The mock planner selects a **fixed** two-step synthetic
  messy-folder fixture; it does not interpret arbitrary tasks. First response
  discloses argv, cwd, env-diff, tiers and whole-plan hash with zero runner calls.
  A separate, hash-bound Start executes T1 and parks before T2. A parked ask is
  never silently replaced by another intent. Planner attempts retain 12.01s
  spacing; a parked attempt neither spins nor seeds another folder.
- **[TESTED-ONLY]** R8 is explicit mock input, initially unknown. Normal exposes
  the private card and an **in-console label** exactly `elaria needs a yes`.
  Company/class keep only the private card. Locked/unknown redact the server
  response and client surface, reject decisions/intent/run, and retain ask age.
  No desktop dispatch occurs. These are not measured room/lock states.
- **[TESTED-ONLY]** Transport reuses `assistant.ipc.serve`, its 0600 Unix socket,
  kernel peer principal and existing lock helper. No JSON uid authenticates a
  caller. Requests cannot submit plans, argv, roots or arbitrary callbacks.
- **[TESTED-ONLY]** Each mutation carries a lab epoch and nonce. Receipts live
  in the existing synthetic `hands.db`; started/duplicate/conflicting requests
  cannot replay an effect. Duplicates return **fresh, redacted** snapshots, not
  cached private responses. The bounded receipt history never evicts for replay;
  exhausting it fails closed, including privacy suppression.
- **[TESTED-ONLY]** Disconnect/5-second reply timeout clears private content.
  Reconnection sends only `hands.snapshot`, never a queued decision or intent.
  An uncertain request remains marked unknown if a different epoch appears.
  The one-second timer refreshes snapshots/age, **not** plans or decisions.
- **[TESTED-ONLY]** Dynamic text is explicitly plain text. The existing ten
  display snapshots in `harness.js` remain pure test samples; the window's data
  now comes from the backend. Samples are not approvals or execution evidence.

## Lifecycle and evidence limits

**[TESTED-ONLY]** The standalone CLI is an **ephemeral lab**: SIGTERM/SIGINT
closes idle clients, removes its owned socket, closes DBs and deletes the minted
scratch tree. A CLI restart creates a new epoch/lab, not a recovered owner task.
Same-minted-space reopen tests separately prove same-hash ask persistence,
terminal No, completed-step non-replay and interrupted-claim uncertainty.
They are not a claim of cross-process or power-loss recovery of that lab.

**[TESTED-ONLY]** `trap` seeds the exact repository `traps/document.txt` into
the minted tree and ingests it as data before dispatch. It must produce inject,
refusal, zero runner/mutation and a private console warning. Run from this
checkout; the trap fixture is not packaged as an installed-wheel resource.

**[TESTED-ONLY]** Operation counts come from the existing Store journal rows;
runner/telemetry counts are current-service observations. Zero live model/task
spawn/desktop notification values describe the absent adapters, not hardware
sensors. The preflight independently prohibits non-Unix service sockets and
non-git subprocesses. Existing read-only git hygiene probes and test-instrument
Node/Python launches are not task subprocess execution.

**[UNVERIFIED]** True Qt load, rendering, focus, logind integration, production
metadata trust, process-group cleanup and shared brokers remain held/unproven.
The finite injection detector is not universal semantic protection; immutable
plans have no data-to-plan update route. Nothing here is `[HW-PROVEN]`.

## Sandbox reproduction — not an owner scene instruction

```sh
.venv/bin/python -m pytest -q tests/test_hands_bridge.py tests/test_hands_core.py tests/test_hands_partial_console.py tests/test_hands_partial_inventory.py tests/test_hands_partial_sink.py
.venv/bin/ruff check .
```

**[TESTED-ONLY]** The new preflight requires Node and fails rather than silently
skipping it. Node is a test instrument, not a QML runtime dependency. Python
loads the package from `src` via pytest; manual sandbox service launches require
`PYTHONPATH=src` or an installed package. No background service is left running
by these tests. Design alone schedules any laptop invocation after reviewing
`docs/phase-reports/hands-2026-10-31-bridge-001.md` and the scene card.
