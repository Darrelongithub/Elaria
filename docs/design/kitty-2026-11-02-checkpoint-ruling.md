# Kitty foundation acceptance, lane correction and wiring boundary — 2026-11-02

## Owner-carried design ruling (authoritative for this lane)

Design chat VERIFIED AND ACCEPTED foundation checkpoint
`66e154a9d68fcae7542045f7f6f7f70360ba2333` in place on
`arena/b65d5161-elaria`. It authorized continuing toward consolidated v1.1 within
all remaining holds. The checkpoint remains TESTED-ONLY, not completed live wiring.

**Correction:** the earlier “explicit A” citation was the sequencing-only ruling
(build now versus wait); it named no lane. Treating that A as lane authorization was
incorrect. Lane placement is design chat's decision, accepted in place by this new
ruling, not a precedent or retroactive expansion of the sequencing addendum. Historical
checkpoint reports are retained as records; this correction controls their attribution.

When branch creation is possible or at merge era, cherry-pick the kitty commits onto a
branch based on the hands tip, under the then-current lane ruling. The distinct console
commit `35adbbaf5ccf471e2075aaea432f9429e4d2d1e7` and its separate cherry-pick plan are
unaffected. **Never force-push.** No branch creation/switch, cherry-pick, PR or merge is
performed by this checkpoint.

## Adopted errata — clause stays pinned and unchanged

- kitty **0.47.1** `send-key` does not enforce its declared `exclude_active` field in
  `SendKey.response_from_kitty` or `RemoteCommand.windows_for_payload`. Broadcast
  exclusion is **untrustworthy** on that version. It carries the machine hazard
  `K3-send-key-exclude-active-unenforced-0.47.1` in the verb's `hazards` and in the
  `--exclude-active` option's `hazards`; the verb remains K3 even for HER windows.
  A fresh ls/focus observation helps detect changed targets but cannot close the
  observation-to-key-event race. Never describe `exclude_active=true` as a safety proof.
- `set-os-window-title` remains **absent-in-0.47.1**, not an invented command/alias.
- Hyprland interop remains version-matched to **0.57.0 Lua**: `hl.window_rule`,
  `initial_title`, `no_initial_focus`. Existing `stay_focused` rules need owner audit;
  they are not silently modified.

The source pin remains upstream kitty commit
`fb5255b1ae4f0249ba832d6a773348fd103449ce`. At this checkpoint the disposable research
copy of every inventoried RC source file was checked against the accepted per-file
SHA256 values before regeneration.

KITTY-CLAUSE v2 remains 14322 bytes, SHA256
`8be8a4a94e958e1fd0323d8e687418f73e6cfd407a5a08bb6720b75769ffb6bc`.
This ledger records accepted errata; it does not revise the Drive clause.

## Verified wiring wall — no protected/frozen edits made

Read-only inspection of the accepted checkout found:

1. `src/assistant/daemon.py`, `Daemon._handlers()` (line 599 at the checkpoint),
   returns a fixed dispatch table. Its contract requires handlers to be bound methods
   of that daemon instance. There is no public plugin/handler-registration hook.
2. `Daemon.handle()` (line 692) establishes the kernel-authenticated owner principal,
   then dispatches through that table. `_require_ipc_owner()` is the existing trusted
   owner boundary. Merely adding a module under `hands/kitty/` does not mount it there.
3. `src/assistant/hands/bridge.py`, `BridgeApp`, accepts only minted synthetic state,
   fixed fixture intents and a fixed method set. Its authenticated server is a
   synthetic lab, not a production kitty extension point.
4. `src/assistant/hands/core.py`, `SandboxCore.__init__`, explicitly requires the exact
   `FakeRunner` class for the synthetic workspace. Replacing that runner would remove a
   frozen safety invariant, not reuse an existing live dispatch mechanism.
5. The existing `hands.registry` is a telemetry contract, not an executable plugin registry.

Therefore the builder has **stopped at live host mounting**, before modifying any
protected file. It has not monkey-patched methods, substituted a daemon entrypoint,
copied the daemon, added a second service, repurposed synthetic storage, or widened the
legacy T3 gate. Additive inventory, policy, recovery and stub-adapter work can continue,
but cannot honestly be reported as mounted in the current trusted host.

## Exact decision requested from design (neither choice is assumed)

**A — Keep the protected-file hold absolute.** Continue only additive library/adapter,
recovery and stub-test work. Production host mounting and owner scene remain held.
This cannot constitute full trusted-host wiring under the current entrypoints.

**B — Grant a narrowly scoped exception for `src/assistant/daemon.py` only.** Permit
minimal kitty lifecycle state, a fixed set of bound-method IPC delegates in
`Daemon._handlers()`, delegation through `_require_ipc_owner()`, and shutdown cleanup
in `Daemon.aclose()`. Keep checker, policy, protocol, journal, recovery and request-shape
logic in additive `hands/kitty/` modules. Mount stays inert until explicit owner attach;
no startup connect, automatic hand-open or model-origin approval. Exercise it only
against stub transport in the sandbox. No other protected/frozen file exception,
new daemon, console edit, config application, model call or live kitty test is implied.

B is a proposal, **not authorization**. If implementation needs any broader change,
stop and ask again rather than treating this proposal as a blanket thaw. Reuse the
existing Plan/Step and R3 adjudication functions; neither A nor B authorizes a legacy
T3 override or a fixed-safe checker. Focused regression tests must protect all existing
IPC-boundary and handler-integrity contracts before any such mount can ship.

## Holds / readiness

No PR; no force-push; zero protected-file edits absent a specific ruling; password
secrecy; stub-only tests; local runner only, never automated-CI claims. PR23, console
cherry-pick and SC-H1 are independent, not prerequisites for additive build work.
`docs/kitty-owner-scene.md` remains **NOT READY TO RUN**. No owner version/drift/hardware
result has been received, and no extra owner hardware session is scheduled here.
