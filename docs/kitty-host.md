# Kitty trusted-host mount and recovery — TESTED-ONLY, 2026-11-02

**Mounted does not mean v1.1 complete or owner-scene ready.** The native-state adapter
is implemented; 11 opaque process/program effect families still need independent trusted
adapters, general selector normalization and complete effect observation remain unfinished,
and installed Fedora/OpenSSH/drift evidence is absent. The owner scene remains NOT READY.
No live kitty or owner hardware was exercised. No new daemon/server/CLI entrypoint exists.

## Narrow granted surface

`src/assistant/daemon.py` has exactly 8 inserted lines, no removed lines:

1. Lifecycle: import `KittyMount` inside `Daemon.__init__`, initialize `_kitty_mount`.
   Constructor is inert: no settings/password/journal/socket I/O, no network/model call.
2. Register `kitty.request` in `_handlers()` and add the bound `_kitty_request` delegate.
   Delegate passes only `_require_ipc_owner()`'s kernel-authenticated principal and params.
   Existing `handle()` authentication/context handling and all old handlers are untouched.
3. `Daemon.aclose()` awaits mount cleanup. Mount catches its own expected cleanup errors
   and records `cleanup_failed`; it never logs raw exceptions or bypasses old cleanup.

There are no changes to other protected files, synthetic bridge/core/runner/store, or
console/QML. There is no dynamic plugin registration, monkey-patch, replacement daemon,
second service, startup connection, automatic hand-open, or model-origin approval route.

## Existing IPC contract

One method, **`kitty.request`**, with a strict `op` field. Every operation needs the
existing local-owner kernel principal, including status/attach. Direct calls without it
refuse. Request JSON cannot supply a checker, transport, journal path, identity or consent
reference. The host's constructor-only dependency injection is for local stub tests,
not an RPC feature. Same-UID trust remains an explicit boundary, not process isolation.

| op | Exact additional fields | Effect |
|---|---|---|
| `status` | none | Attached/hand-open state, `scene_ready: false`; no I/O while detached. |
| `attach` | `public_key` | Validate intended kitty public key; load the fixed separate settings path, lease/recover the private journal. No RC command is sent by attach. |
| `detach` | none | Only when idle; close session hand and ledger. No automatic reattach. |
| `open-hand` | `phrase` | Exact `kitty hand open`; mint an opaque session reference. |
| `close-hand` | none | Close session hand and durably revoke pending per-act approvals. |
| `prepare` | `verb`, `payload`, `target_ids`, `model_tier`; optional `nonce` | Validate immutable act, independent gate, journaled K1 observation, exact target resolution, private disclosure. Never executes the proposed act. |
| `decide` | `plan_hash`, `choice`, `execute_newline`, `program_acknowledged` | Exact lowercase yes/no, two actual booleans. Host binds approval to prepared exact payload and observed identities, generates the consent reference, fsyncs before acknowledgement. |
| `run` | `plan_hash` | Execute the exact prepared plan through existing Plan/R3 and K consent gates. No caller-selected effect checker. |
| `cancel` | `plan_hash` | Cancel a known prepared act; remains reachable while a run waits on kitty. |

`model_tier` is the proposal-side **legacy T-tier**, not authority over the independent
checker or K-tier. A missing/invalid/mismatching proposal follows existing R3 behavior;
legacy T3 never gets a Yes override. The whole Plan/Step hash binds verb, exact payload,
resolved target IDs and a 32-hex nonce. A same-plan restart can resubmit the disclosed
nonce and exact request; changing bytes produces a different hash, never a reused Yes.
The public key is not a password. Passwords are never request parameters.

`prepare`/`run` use tracked worker threads so an IPC disconnect does not cancel a Python
waiter and inadvertently release an executing act. While work is in flight, only cancel
is admitted. Shutdown stops new requests, requests cancellation for a running act, waits
for its bounded transport worker and then closes the writer. No task subprocess is run.
Private disclosure/read replies must not be copied into reports or shared transcripts.

## Independent assessment and target/effect coverage — honest limits

`checker.py` parses the pinned wire declarations, rejecting unknown fields, missing
required fields, type/choice mismatch and child-RC grants. It uses no request-supplied
facts/assessment and honors the daemon's existing halt file. K1 native observations
receive T0; ordinary native-state changes receive T1; configured/reset/global persistence
receives T2 plus an irreversible K3 classification. Target-attribution K3 escalation
still happens independently in Bridge (for example HIS or mixed-tab closes).

The mounted default **refuses unresolved opaque effects**: `action`, `kitten`, `launch`,
`new-window`, `run`, `load-config`, `env`, `send-text`, `send-key`, `signal-child`, and
`create-marker`. This is an explicit unfinished independent-effect-adapter gate, **not**
a new task whitelist or a claim that v1.1's total capability has been delivered. The
underlying Bridge paths remain available to trusted injected stub assessors in tests;
a model-supplied “safe” flag or owner Yes does not invent missing independent evidence.
These adapters must be completed/reviewed before scene beats involving launch or typing.

`surface.py` requires resolved ID expressions, rejects implicit active/self and conflicting
selectors, expands tab/OS targets for attribution, binds global selection to the whole
observed set, and refuses unresolved compound destination/source selectors. General
regex/title selector normalization, creation sources/destinations, active-OS font sizing
and other compound surfaces remain under review. A declared native-state classification
is not a claim that every option combination is supported or every effect is observable.

Native effect checks claim only intended **deltas** in observable ls state with unchanged
identity (window/tab title, layout and focus); existing close/creation/text-delta observers
remain in Bridge. Other effects stay **unverified**, never true merely because kitty
returned success. Additional per-verb probes and application observers are still needed.
The accepted send-key `exclude_active` K3 hazard is unchanged; snapshots do not eliminate
focus races. This mount does not downgrade that hazard or declare a safe broadcast path.

## Durable recovery

`RecoveryLedger` opens an owned regular single-link 0600 journal in an owned 0700 parent,
uses no-follow directory/file checks and holds a lifetime exclusive flock. It fsyncs
file creation and parent metadata, then fsyncs each record before acknowledging it.
All metadata is secret-free: hashes, IDs, phases, counters, consent booleans/references;
no payload, terminal text, raw argv or passwords are persisted. No new database schema.

- `operation=probe` distinguishes observations from write-ahead dispatch intents.
- Any dispatched act intent is spent after restart, including missing/unknown results.
  Old intent records lacking this discriminator are conservatively spent, not guessed safe.
- Terminal No, explicit hand-close revocations, cancellation intents and mismatch counters
  survive restart. A second mismatch cannot be bypassed by restarting the host.
- Exact unspent Yes can restore **only for the same socket/public-key endpoint identity**.
  Session hand-open never restores. Restore is not automatic execution: exact re-preparation
  and fresh target/gate checks still apply.
- HER ownership restores only from durable successful creation records at that same
  endpoint. Title resemblance never grants ownership; reused IDs with different identity
  fingerprints do not match.
- Truncated/malformed records, a foreign/unsafe file or an existing writer lease refuse
  attachment. No truncation, auto-repair, reset or replay. At 32 MiB the ledger stops;
  reviewed archival/compaction is still a maintenance gate, not a reason to discard history.

Cancellation is durable **before** the reply. Before dispatch, denial prevents execution.
After intent/send, it is best effort and remains effect-unknown, not undo. An asynchronous
act's cancel uses its original request ID on a separately preflighted encrypted connection.
Synchronous transport checks a cancellation event before connect/send and between bounded
receive polls. The check/use and server-execution races are acknowledged: cancel-sent is
not cancel-proven. A completed/spent act is never relabeled “stopped before dispatch.”

## Next completion gate

Complete the opaque effect adapters and full target/effect matrix; exercise encrypted
stream/cancel/recovery fault boundaries more broadly; reconcile owner Fedora/OpenSSH
metadata and drift; then review/finalize the scene card. The existing drift script and
owner-only scene remain unchanged and unexecuted. All tests here are synthetic and
local-only; no automated-CI or hardware-proof claim.
