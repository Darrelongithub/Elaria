# KITTY HANDS v1.1 — granted mount / recovery checkpoint, 2026-11-02

**TESTED-ONLY. NOT v1.1 completion. Owner scene remains NOT READY.**

Branch: `arena/b65d5161-elaria`, active and design-accepted in place.
Accepted parent checkpoint: `26d8734f65e8a252db66bec27e7dfca7e729e15a`.
Resulting checkpoint SHA is supplied in the delivery message. No PR, merge, force-push,
branch switch, mainline overlap reconciliation or console cherry-pick performed.

## Grant consumed — exact accounting

The owner granted Option B from `docs/design/kitty-2026-11-02-checkpoint-ruling.md`.
Only **8 inserted lines / 0 deleted lines** in `src/assistant/daemon.py`:

- Lifecycle state: local import of `KittyMount`, inert `_kitty_mount` initialization.
- Bound-method delegation: one `kitty.request` table entry plus `_kitty_request`, using
  the unchanged `_require_ipc_owner()` kernel-authenticated owner boundary.
- Shutdown: one `await self._kitty_mount.aclose()` cleanup call.

These are four small diff hunks within the three authorized surfaces. Removing those
exact insertions reproduces the accepted daemon byte-for-byte. Existing handler bodies,
IPC authentication/dispatch implementation and unrelated lifecycle behavior are unchanged.
All substantive code is in additive kitty modules. No monkey-patch, copied/replacement
daemon or second service. Mainline's separate F3a/b/c grant was not used.

## DONE at this checkpoint

- Mounted `kitty.request` on the **existing** daemon socket. Detached startup performs
  no kitty settings/password/journal/socket I/O. Explicit authenticated attach loads the
  fixed separate settings file and leases/reconciles the ledger; attach itself sends no
  RC command. It never opens the session hand automatically.
- Strict owner-request shapes for status, attach/detach, hand open/close, prepare, exact
  decision, run and cancel. Request JSON cannot supply a checker/identity/transport/path
  authority or a consent reference. Proposed legacy tier is independently adjudicated
  through the existing R3 function and immutable Plan hash, not accepted as authority.
- Added conservative native-state assessment and resolved-ID targeting. Unknown fields,
  missing required wire fields, type/choice mismatch, implicit active/self selection,
  incomplete global scope and unresolved compound selectors fail closed. Tab and OS
  scopes expand to include affected children. Existing halt-file state is respected.
- Added intended-delta observers for ls-visible titles/layout/focus, with stable identity.
  Responses alone do not verify effects. Other native effects stay UNVERIFIED pending
  their independent probes; the accepted send-key K3 hazard remains unchanged.
- Durable private single-writer `RecoveryLedger`: no-follow/private-mode checks, lifetime
  flock, file and parent fsync, write-ahead act/probe distinction, bounded storage and no
  auto-repair. Truncated/malformed ledgers refuse attachment.
- Restore terminal No, explicit hand-close revocation, spent/unknown dispatch intents,
  cancellation intents and mismatch counters. Restart cannot reset a second mismatch.
  Unspent exact Yes restores only at the same socket/public-key endpoint. Session hand
  never restores. HER ownership restores only from durable successful creation at the
  same endpoint, not from a forged title. No raw payload/text/argv or passwords persisted.
- Durable cancellation intent/result: before dispatch, terminal refusal; after dispatch,
  best effort / effect unknown. Async cancellation uses the original request ID on a
  separately preflighted encrypted connection. Transport cancellation checks do not claim
  to eliminate send/server-execution races. A completed act is never called undone.
- Tracked/shielded workers prevent IPC disconnect from releasing an in-flight act or
  permitting replay. Shutdown stops admission, requests cancellation, waits for its worker,
  then closes the ledger. No task subprocess or model call is introduced.
- **50 new synthetic tests** cover kernel-authenticated daemon routing with an injected
  stub RC transport, old-handler integrity, inert startup, missing/spoofed authority,
  native selector/field failures, effect deltas, leases, malformed/torn records, restored
  Yes/No/ownership/mismatch state, cancellation and disconnected waiters. This is not
  live kitty, compositor, visual or power-loss hardware proof.

## Verbatim local gates

Interpreter:

```text
Python 3.11.2
```

Combined kitty suites:

```text
117 passed in 0.89s
```

Full suite:

```text
2220 passed, 6 skipped in 100.35s (0:01:40)
```

Ruff:

```text
All checks passed!
```

Arithmetic: accepted 2170 + 50 = 2220; kitty tests 67 + 50 = 117.
The known running_daemon async-generator teardown intermittent did not occur in this
full run. No shared fixture was edited. All gates are local-runner-only: no automated CI
was wired or claimed, and no live kitty, owner content or paid/quota endpoint was used.

## DEFECTS FOUND / remaining implementation limits

**The default mounted assessor does not yet provide total capability.** It refuses
unresolved opaque program effects in 11 families: action, kitten, launch, new-window,
run, load-config, env, send-text, send-key, signal-child and create-marker. This is an
unfinished trusted-effect-adapter gate, not a new doctrine/task whitelist or a claim of
completion. Existing underlying Bridge paths remain exercised with trusted stub assessors;
a request-supplied “safe” assertion or Yes cannot stand in for independent evidence.

General selector normalization, creation/compound source/destination handling, active-OS
font selection and a complete per-verb effect-observation matrix remain incomplete.
Only observable intended deltas are verified; all others remain UNVERIFIED. Stream and
encrypted cancellation/fault boundaries need broader coverage before activation. Ledger
archival/compaction at its 32 MiB stop bound is also not yet implemented; do not discard
history to bypass a spent/refused plan. Pending-plan resource bounds and broader
production safety review also remain outstanding. Cancellation-sent is never
cancellation-proven.

The host mount resolves the prior protected wiring wall within the grant. No new or
broader protected-file grant is being requested or assumed at this checkpoint. The
remaining gaps above are substantive engineering work, not hardware evidence or a
reason to weaken existing legacy T3/consent protections.

## NEXT GATE

Complete the independent opaque-effect adapters and full target/effect matrix, broaden
stream/cancel/recovery fault tests, and reconcile the owner inventory evidence. Then
review/finalize the scene card. No “ready” declaration has been made. The scene's launch
and typing beats cannot yet run through the default mounted assessor and must not be
worked around with a fixed-safe lambda.

## Drift / Fedora / OpenSSH / hardware status

`tools/kitty/drift.py` is unchanged; its local parser tests pass. **No owner execution
result, installed kitten version, Fedora file/package membership or OpenSSH reconciliation
has been received.** Upstream Ring 2 metadata remains available but is not substituted
for installed evidence. Run/reconcile the owner help/version drift steps after every dnf
kitty upgrade, including semantic review. No live kitty or extra hardware session was
run/scheduled here. `docs/kitty-owner-scene.md` remains unchanged and NOT READY TO RUN.

## Diff / extra-diff audit

```text
 docs/design/kitty-2026-11-02-checkpoint-ruling.md     |  15 ++
 docs/kitty-host.md                                    | 125 ++++++++++++
 docs/kitty-setup.md                                   |  40 ++--
 docs/phase-reports/kitty-2026-11-02-mount-recovery.md | 175 ++++++++++++++++
 src/assistant/daemon.py                               |   8 +
 src/assistant/hands/kitty/bridge.py                   |  82 ++++++--
 src/assistant/hands/kitty/checker.py                  |  72 +++++++
 src/assistant/hands/kitty/host.py                     | 245 +++++++++++++++++++++++
 src/assistant/hands/kitty/policy.py                   |   5 +-
 src/assistant/hands/kitty/recovery.py                 | 125 ++++++++++++
 src/assistant/hands/kitty/surface.py                  |  73 +++++++
 src/assistant/hands/kitty/transport.py                |  17 +-
 tests/test_kitty_host.py                              | 411 ++++++++++++++++++++++++++++++++++++++
 13 files changed, 1359 insertions(+), 34 deletions(-)
```

Of 247 pre-kitty baseline files at `35adbbaf`, **246 remain byte-identical**. The sole
exception is the explicitly granted 8-line additive daemon mount above. All other
changes are kitty-owned modules/tests/docs. Other protected/frozen files and the console
are unchanged. Extra diff outside the kitty order and the named daemon grant: **NONE**.

Clause remains unchanged, 14322 bytes, SHA256
`8be8a4a94e958e1fd0323d8e687418f73e6cfd407a5a08bb6720b75769ffb6bc`.
Lane-attribution correction and future hands-tip kitty cherry-pick remediation remain
as recorded by design; the separate console `35adbbaf` plan is unaffected.

## Artifact paths

- `src/assistant/daemon.py` — only the named mount/lifecycle/cleanup insertions.
- `src/assistant/hands/kitty/host.py` — strict authenticated host lifecycle and delegates.
- `src/assistant/hands/kitty/{checker,surface}.py` — conservative assessment/target binding.
- `src/assistant/hands/kitty/recovery.py` — durable private lease/reconciliation.
- `src/assistant/hands/kitty/{bridge,policy,transport}.py` — dispatch/cancel/gate integration.
- `tests/test_kitty_host.py` — 50 new synthetic regressions.
- `docs/kitty-host.md` — exact IPC/recovery contract and explicit completion limits.
- `docs/kitty-setup.md` — current mount/recovery posture; scene still held.
- `docs/design/kitty-2026-11-02-checkpoint-ruling.md` — records the subsequent Option B grant.
- Inventory JSON/schema, `docs/kitty-inventory.md`, drift script and owner scene — unchanged.
