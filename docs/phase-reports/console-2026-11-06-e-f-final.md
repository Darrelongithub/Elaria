# Final report — Tasks E then F

**Builds finished; owner wiring and hardware acceptance are not claimed.** This is the one
combined final report requested by the GO TO COMPLETION ruling. E was revalidated first;
F was then built against the exact landed pilot source and §9. No PR or force-push.

## Commits and release boundary

| Deliverable | Commit |
| --- | --- |
| Native host candidate, unchanged | `670a8d163aaeaaba3e2ad324789cab0f837b2374` |
| Task E native v4 launcher, unchanged and revalidated | `fbab9536c3dc936b898bf4d5124fa02f1a8740db` |
| Task F private undo card, protocol, tests and current-release pins | `85674cc55c53c2137b456f965ecc042436e5923b` |
| Producer seam inspected read-only, NOT merged into this branch | `e7316b985e4463d961a2ec51af6a4023360a261c` |
| Authoritative §9 / producer report inspected read-only | `5ee68530cb9129b3e3977be601f146d3cab97233` |

**The deployment split has not been hidden:** native v4 still launches the required
fcd55ca1 historical bridge/shell with the ed227a7d launcher checksum. That UI does not contain
the A–C additions or this F card. With the pilot daemon, its scoped typed undo remains refused.
F is the separately built current console artifact; neither the old worktree pin nor the
owner's installed wrapper/configuration was silently replaced. This is not a claim that the
new card is already behind Win+Space. No owner install or configuration edit was performed.

## DONE table — every completion criterion

“DONE / local” means implementation and the stated local gates, not an owner-hardware verdict.

| Criterion | Status | Evidence / exact limit |
| --- | --- | --- |
| Git 2.39.5 STOP substitution | DONE / local | Three configuration key-name checks absent; transport backstop on verification reads; equivalence recorded below |
| Same wrapper path, line-149 bind unchanged | DONE / build + temporary-install test | Installer targets `/home/darrel/.config/hypr/elaria-console-launch.sh`; no Lua edit or reload; actual keypress remains owner-only |
| Worktree self-heal at exact fcd55ca1 pin | DONE / local | Missing tree and stale missing-tree registration recreated in temporary repositories from local objects; other registrations/source HEAD preserved |
| Exact ed227a7d launcher checksum gate | DONE / local | Historical executable and its embedded payload pins verified; current F launcher is NOT substituted |
| `/tmp/elaria-launch.log` retained | DONE / local | Append-only metadata, owner-owned regular file, tightened to 0600; no token/URL content |
| Absent bridge → headless bridge then native host | DONE / local process test | Actual historical bridge bytes, synthetic IPC, fake native process; no `--open` argument |
| Present bridge → another window on live file | DONE / local process test | Existing listener identity and live-token upgrade challenge; newer stale files do not win; no duplicate bridge |
| Ctrl-C only stops bridge; window close does not | DONE / local process test | Independent sessions; authenticated liveness after fake-window exit; native-window process survives bridge Ctrl-C |
| Retire Chrome/Chromium invocation | DONE / this launcher path | Fixed native-only argv, no browser fallback; global post-keypress process census remains hardware-only, and existing unrelated browsers are not killed |
| GTK ELARIA window and WebKit view | DONE / host build, runtime UNVERIFIED | Task D unchanged: fixed title, ephemeral context, strict navigation and no browser fallback |
| Pairing from private 0600 launch file, memory only | DONE / local privacy gates | Exact loopback fragment parsed in memory, no token in argv/stdout/metadata; real WebKit behavior remains unverified |
| Native six looks / actual reboot verdict | OWNER-HARDWARE ONLY | Explicitly not inferred from fake processes, DOM tests or the local recovery fixture |
| E local suite and Ruff, WebKitGTK probe skipped honestly | DONE / local | E baseline: 2641 passed, 9 skipped; locked Ruff passed; no GI/runtime/display acquisition |
| Scoped undo typed in current console cannot mutate without card Yes | DONE / local | Canonical English/Swahili scope intercepted before console.say; prepare only; no old-backend execution fallback |
| Focused private card on the prepared snapshot | DONE / local DOM + wire tests | Single row, operation/targets/hash preconditions/digest; no model-generated fields, no persistent snapshot, no content notifications |
| Collateral and reversal limits shown | DONE / bounded disclosure | Audited executor consequences labelled as semantics, NOT invented prepare fields; missing root/collateral inventory stated plainly |
| Yes dispatches apply exactly once | DONE / local | Bound connection/review/digest; token kept only in bridge memory; spend before await; duplicate/stale IDs and repeated answers refused |
| No terminal; consumed ask replay reads already-answered | DONE / local | Both Yes/No bindings consumed; replay with a fresh request ID returns already-answered; exact pinned producer methods also tested |
| Age shown; expiry lapses; no actionable card beyond token | DONE / local | Conservative elapsed budget, fresh checks before click and apply; no renewal/replay; stale UI cannot dispatch even before next timer repaint |
| Bare undo refuses byte-identically | DONE / local + protected-byte audit | Existing text/params unchanged; pinned real library bare refusal and pinned producer guard exercised; no producer edit |
| No execution path besides apply, no broader scope | DONE / console consumer | Only undo.prepare / undo.apply added; apply sends stored token + decision only, no targets/queries from browser; CLI/global enforcement not claimed |
| Clause pins, full suite, Ruff and absolute engine pin | DONE / local | Clause map below; final code: 2669 passed, 9 skipped; locked Ruff passed; engine unchanged |

## Git STOP resolution — exact record

Sandbox Git: **2.39.5**. No upgrade performed. Before verification, `git config --name-only
--get-regexp` checked these key names, **never values**:

- `extensions.partialClone` (`^extensions\.partialclone$`) — **ABSENT**.
- `remote.<name>.promisor` (`^remote\..*\.promisor$`) — **ABSENT**.
- `remote.<name>.partialCloneFilter` (`^remote\..*\.partialclonefilter$`) — **ABSENT**.

**The no-lazy-fetch guarantee holds by absence-of-promisor rather than by flag.**

Verification reads carry `-c protocol.allow=never`. The v4 runtime also supplies an empty
`GIT_ALLOW_PROTOCOL` allowlist, blocking protocol-specific allow overrides; it never fetches
or reclones. A present promisor/filter key, missing local object, locked registration, wrong
HEAD or wrong pin is a hard STOP. Name-only detection and the transport backstop have tests.

Session-only operations were explicit: fetch this session branch to restore refreshed Git
metadata, verify all **320** accepted baseline files byte-for-byte, then metadata-only mixed
reset to fbab953; fetch the two owner-named producer commits for read-only source inspection.
No checkout/merge/cherry-pick of mainline, no owner worktree action, no implicit lazy fetch.
These explicit artifact fetches are not part of native reboot recovery.

## F contract and clause pins

The bridge's new path uses the **actual §9 shape**, not earlier design prose:
`token, ask_sha256, snapshot, prepared_at, age_s, expires_in_s`. Actual e7316b9 token generation
is a 32-hex UUID; the report's “64-hex” prose is not used as a wire schema. TTL is bounded by
600s. Snapshot is one flat operation row; there is no returned root, expires_at or resolved
collateral inventory. Extra/malformed/oversized fields or a digest mismatch refuse the card.

`undo since …` / existing `rudisha|tenda upya tangu …` prepare a scope; `undo review #N`
prepares that explicit ID. Bare `undo` stays on its original route. The bridge never invokes
bare undo RPC, CLI, shell or executor. Apply receives **only** the stored producer token and
exact decision. A new chat input invalidates the old pending selection, even if its new
prepare fails. Changing the digest or using another connection cannot approve an old act.

The card requires an explicit private-review selection, visible/focused document, matching
browser session and focus inside its own controls. Dedicated entry accepts trimmed exact
Yes/No; ordinary chat “yes” is not consent. Blur/hidden state hides private fields; disconnect
or expiry removes the card; no snapshot, token or review binding is put in localStorage,
conversation history, notification text or window metadata. The digest may accompany the
non-model receipt for producer-log correlation; it is not an invented journal/event ID.

Existing daemon disclosure status must explicitly report company/restricted false before
and after preparation and before dispatch. Unknown/restricted status blocks the review;
periodic updates hide it. This is **not an OS-lock sensor, unforgeable browser-focus identity
or proof that no other person is present**. The producer still authenticates the Unix peer.

Bridge time starts before prepare and subtracts returned age; client time subtracts the
whole request/paint delay too. Subsequent elapsed time uses the conservative maximum of
monotonic and wall-clock deltas. Actions check freshness independently of the last repaint;
a lapsed card is removed on the next UI event-loop tick. Local lapse is not falsely reported
as a producer-journal event. Daemon restart/drift/expiry remains producer-authoritative.

No exact-restore promise: the card discloses possible identical-duplicate retirement through
trash, journal/state writes, and empty `_Conflicts`/`_Unsorted` parent removal, as **audited
executor semantics**, not extra prepared targets. It requests no additional operation.
Receipt counts are daemon-reported, not independently verified effects. Failed/unknown apply
is spent and never retried automatically. Global CLI/direct-executor containment is outside
this pilot; the documented daemon-unavailable CLI fallback is not silently “fixed” here.

| Clause | Consumer pins |
| --- | --- |
| Prepare only / no mutation before Yes | `test_scoped_typed_undo_only_prepares_until_focused_decision`, `test_old_backend_without_seam_fails_closed_not_console_say` |
| Single Yes and terminal No / replay | `test_answer_dispatches_apply_once_and_replay_reads_already_answered` |
| Expiry, stale digest, edits, wrong connection / privacy | `test_stale_unfocused_or_lapsed_ask_cannot_apply`, `test_unknown_privacy_blocks_preparation` |
| Drift/unknown outcome cannot re-arm | `test_unknown_or_drifted_decision_is_never_rearmed` |
| Exact snapshot/digest/schema/TTL | `test_prepare_snapshot_schema_digest_and_expiry_are_bound` |
| Bare undo unchanged | `test_bare_undo_remains_byte_identical_forwarding` and exact producer/library refusal test |
| Private focus, Yes/No entry, age/lapse, no storage or chat approval | `test_private_card_dom_gates` → `console/undo-review-test.js`, including actual shell decision-frame construction |
| Exact landed seam behavior | `test_actual_pinned_seam_methods_without_protected_file_edits`: unchanged source method bodies in an isolated synthetic test service; preverify, single-op, No, Yes, replay, lapse, row drift, bare/scoped guard |
| No private error echo | `test_refusal_filter_never_echoes_private_paths_tokens_or_details` |
| IPC unknown outcome only after mutating send | Existing deadline pin extended to undo.prepare and undo.apply |

The exact-source test reads the local e7316b9 Git object with transport disabled; it does not
modify/monkeypatch the production daemon or import a second live assistant. Store/executor
surfaces are synthetic recording services, with temporary files for hash pre-verification.
It ran here. A fresh CI clone lacking that local object skips this one explicitly rather than
fetching it or falsely claiming producer integration. No live owner backend was invoked.

## Verification, defects encountered and hard stops

- E revalidation before F: **2641 passed, 9 skipped, 117.91s**; Ruff passed.
- F focused bridge/card/launcher tests: **218 passed, 2 skipped, 29.71s**.
- F final implementation suite: **2669 passed, 9 skipped, 128.68s**; Ruff passed.
- Build: shell/engine JavaScript syntax, GLSL uniform checks, absolute engine and inlined bytes
  passed. E installer/native checksum manifest remains valid and unchanged.
- Tooling correction: an unconstrained pip install selected Ruff 0.17.4 and newly flagged
  accepted protected kitty code. Installed **uv.lock's Ruff 0.17.2**, reran green without a
  waiver, lint-rule change or protected edit. No Git/toolchain upgrade was made.
- Test-fixture correction: the initial DOM test repeatedly reconnected an already attached
  fake adapter and stalled the legacy toast queue. It now uses the actual one-connection card
  flow, with a separate document for wire framing. No notification subsystem fix or flood-
  stress acceptance is claimed; ordinary existing reconnect tests remain green.
- **Hard stops:** the earlier Git-version STOP is resolved by the owner's absence-of-promisor
  ruling; no unresolved implementation STOP remains. Missing GI/display remains an explicit
  skipped hardware gate, not a reason to hold the F build or infer a rendering pass.

## Release pins and operational boundary

Current F release SHA256:

- `console/run_bridge.py`: `594bde664e62da42f391bf83b09a4b1ae913387d1ee27031f0e1376dace71791`.
- `console/bridge.py`: `5abf2f5959e2a41879a911f4373d050f54f5e1267c1e365312d37fd5814ce0dc`.
- `console/index.html`: `9f20df8513c5ad7ffdbdc5dd7e430f57999f5fa790b7bc00e873578c6d6e32af`.
- Immutable engine: `5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.

Native v4's separate exact fcd55ca1/ed227a7d pins and checksummed same-path installer remain
in `docs/phase-reports/console-2026-11-05-native-launcher-v4.md`. Current-release check-before-
run instructions/pins are in `console/BRIDGE.md`; mismatch means STOP, not repair or browser
fallback. Neither set of instructions authorizes swapping the other's payload or pin.

### Two owner lines

**Owner line 1 — prerequisite:** `sudo dnf install -y python3-gobject webkit2gtk4.1` (owner-side, coordinated through design chat; not run here).

**Owner line 2 — hardware-only acceptance:** verify the actual unchanged Win+Space bind opens ELARIA with no Chrome/Chromium process, token-safe native WebKit pairing/origin behavior, all six looks, independent close/Ctrl-C behavior and the real reboot self-heal verdict; none is certified by sandbox stubs.

### Honest unverified list

- Native rendering / WebGL and the six looks on the owner's size, zoom and monitor.
- Fragment pairing **inside WebKitGTK** and its cross-origin behavior; optional probe skipped.
- Real keypress, GTK title/window metadata/process census and actual reboot acceptance.
- Owner installation/deployment of v4, and deployment/use of the current F artifact against
  the real pilot daemon. No claim F is already wired into the historical native worktree.
- Independent observed filesystem effects of an approved real undo; synthetic service counts
  and producer acknowledgements do not substitute for that evidence.
- OS lock/privacy-sensor integration, global CLI enforcement and notification flood behavior.

## Pinned source anchors

- `fbab9536c3dc936b898bf4d5124fa02f1a8740db:console/native_launch.py:84` — local-only Git verification and recovery.
- `fbab9536c3dc936b898bf4d5124fa02f1a8740db:console/native_launch.py:273` — native startup/reuse path.
- `5ee68530cb9129b3e3977be601f146d3cab97233:docs/design/2026-11-04-undo-consent-seam.md:193` — authoritative §9 deltas.
- `e7316b985e4463d961a2ec51af6a4023360a261c:src/assistant/daemon.py:2844` — exact prepare snapshot/digest/expiry shape.
- `e7316b985e4463d961a2ec51af6a4023360a261c:src/assistant/daemon.py:2899` — terminal decision, expiry, drift and apply.
- `85674cc55c53c2137b456f965ecc042436e5923b:console/bridge.py:541` — consumer prepare, privacy and binding.
- `85674cc55c53c2137b456f965ecc042436e5923b:console/bridge.py:579` — only consumer execution path, exactly-once apply.
- `85674cc55c53c2137b456f965ecc042436e5923b:console/src/shell.js:743` — private focused expiring card.
- `85674cc55c53c2137b456f965ecc042436e5923b:tests/test_console_undo_review.py:71` — clause-by-clause consumer pins.

Protected source, shared fixtures, engine, history_limit and native v4 pins remain unchanged.
Remember/forget cards stay held behind the owner's seams word. Kitty remains parked;
NectarLink is out. No PR, force-push, owner-service edit, native install or owner-worktree change.

Final report commit regression gate: **2669 passed, 9 skipped in 129.59s (0:02:09)**; locked Ruff and protected-byte/diff checks passed.
