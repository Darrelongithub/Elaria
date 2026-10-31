# Hands console — standalone synthetic harness (R7/R8)

[TESTED-ONLY] `harness.js` provides ten synthetic snapshots and pure grammar /
posture functions. Sandbox tests execute the JS under node. The samples cover
idle, plan, collision, injection, verification, disconnection and four posture
states. Static screens are still samples, not measured execution.

[UNVERIFIED] `shell.qml` targets Quickshell **0.2.1**. Runtime loading, focus,
layout, logind/loginctl integration and desktop privacy remain unproven.
Sandbox qmllint is **N/A**, not a pass. No owner laptop run is requested here.
No voice pane, mounting into the frozen console, unit, socket, or installation.

## Implemented synthetic boundary

- [TESTED-ONLY] R7: trim/case-fold exact `yes`/`no`; a focused pending ask produces
  a decision DTO bound to ask ID and whole-plan hash. No focused ask produces
  `no ask is selected`, not an intent. Other text stays free-text intent.
- [TESTED-ONLY] DTO grammar is exercised end-to-end with the Python synthetic
  core and durable queue in a test. The QML window itself still has **no IPC
  bridge**: capture/buttons are local previews, not executable approvals.
- [TESTED-ONLY] R8 explicit synthetic posture: normal gives the fixed notification
  preview plus console card; company/class suppress notification but keep the
  console card; locked/unknown suppress notifications and hide private content.
  The underlying ask is retained, not declined, approved or expired.
- [TESTED-ONLY] Body is byte-exact `elaria needs a yes`. No notify-send / D-Bus
  desktop notification dispatch occurs. Unknown posture fails safe.
- [TESTED-ONLY] Dynamic text declares plain-text rendering. Actual QML runtime
  interpretation remains [UNVERIFIED]. No arbitrary data-to-code bridge.
- [TESTED-ONLY] Age wording uses fixture values. Core queue persistence and
  indefinite waiting are tested separately; no timer-driven expiry exists.

## Sandbox checks

```text
.venv/bin/python -m pytest -q tests/test_hands_core.py tests/test_hands_partial_console.py tests/test_hands_partial_inventory.py tests/test_hands_partial_sink.py
```

[TESTED-ONLY] node is test-only, not a new production dependency. If absent,
JS tests explicitly skip. Structural QML checks never replace the laptop gate.

## Core / telemetry boundary

[TESTED-ONLY] Core uses only a minted `SyntheticSpace`, private tmp SQLite state,
and `FakeRunner`. File mutations delegate to the existing Executor/Store/Journal;
no production model or subprocess runner ships. R4 now has an exhaustive
registry; the previous namespace-only sink semantics are superseded.

[TESTED-ONLY] Sink writes six fields without detail or seven with metadata;
peak is `-`. Session shapes are normalized without regex-gating a log event.
Detail allows paths/hashes/counts/argv-sha and the two fixed R3 diagnostics;
no free-form contents, commands, owner intent or exceptions. Control characters
are escaped without corrupting literal backslashes. Sink failure is an
observable local drop, never a policy decision, retry, or durable receipt.

[UNVERIFIED] Production metadata trust, true process-group cleanup, broker
integration and console wiring are not proven by fake-runner tests. No scene
may substitute this static QML display for an actual persisted owner decision.
