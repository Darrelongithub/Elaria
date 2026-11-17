# Hands after owner Ruling C — asks 35–39

**Status: scoped transition design and source findings, NOT deployed behaviour.** Baseline
`a26dbdc31f5551b37a19e981d1cb8b78e29cafa7`. Current code still implements the accepted Task I ask
path. This document adopts the new owner ruling without rewriting that historical acceptance.
Ruling source: current `OWNER-RULINGS-2026-11-17.md`, Drive ID
`1XtuVDo3OZ7GirNRABp5-Q8jGa691GC2R`, 4990 bytes, Drive-reported SHA256
`a72916d0a5e1167707655ba5ba91f81e2f23a0d21b3c4aa8e18d4d2e366634ab`; read in full.

## 1. What is ruled, what code does now (asks 38/39)

**Required new behaviour:** exact owner-seeded on-list work executes only if the reversible effect
adapter and every existing policy/hash/inventory/target gate pass. Off-list, destructive,
irreversible, unknown, stale or otherwise unassessed work receives a prompt-free recorded refusal
with reason, immediately returned and summarized in the sessions sidebar. No waiting for consent,
no timeout-driven permission, no permissive default. Empty list means no newly authorized work.
“Never block” means no human-consent wait; bounded I/O, execution deadlines and fail-closed refusal
remain necessary. No permission to act on arbitrary commands is created by removing the card.

**Current code is separable but NOT already compliant:**

- `headless/contract.py::parse_intent/plan/validate` restrict the effect family to assessed empty
  directory operations, canonical ELF binaries, private workspace identity, target state and every
  top-level chain segment. `host.py::execute` separately runs independent adjudication. Those checks
  do not depend on a card and must survive.
- `host.py::handle(action='prepare')` builds/validates a plan, calls `consent.covered`, executes covered
  work, otherwise calls `consent.prepare` and returns an ask. That final branch is the change point:
  refuse with `allowlist-miss` instead, never call `prepare` or accept a delayed answer as authority.
- `consent.py` currently retains a 120-second one-ask map. Bridge/shell also retain review tokens,
  expiry/posture/reveal controls. These must be removed for ordinary hands action approval, not
  merely hidden in the UI while an answer endpoint still authorizes execution. Old tokens must
  become unusable at the policy-version boundary. F's distinct undo-review feature is not blanket
  permission to delete unrelated confirmation code; keep its scope separate.
- `host.py::deny` currently emits a single `DENIAL` row, not an action/observation pair. Existing
  `snapshot` exposes only the latest 32 rows plus omitted/total counts. There is no durable “since
  last looked” cursor. These are accountability changes required by the ruling, not existing claims.
- Journal writes are private append-only/hash-chained with a 2,000-row/4 MiB stop. That bound must
  not turn into silent record loss or unjournalled execution. Rotation/archival would need a pinned
  continuation protocol; absent that, journal-full still refuses effects with a visible error.

### Typed controls: available route versus semantics

`host.py::typed` handles `hands always on/off` and `hands revoke ABS` before model routing. `handle`
requires authenticated owner UID. These controls do **not** call `check_active` or require a card,
visible/focused browser, or an open Kitty instance. Thus, on a daemon with the mount installed, they
can be issued through `assist talk` with the GTK console closed. An unmounted installed mainline
cannot be assumed to honor them; require the hands capability preflight and a real receipt.

**Revocation survives:** it resolves the named path, removes all corresponding standing entries,
journals and persists the update, and clears outstanding asks in current code. It does not require
card focus. A returned status must be verified by readback of the remaining authority. It cannot
undo a completed action. Current mount lock serializes it behind an executing request; do not
advertise instantaneous cancellation of already-dispatched work. Revised execution must recheck
authority at dispatch/chain boundaries and report whether anything was already in flight.

**`always` cannot honestly be called semantically untouched:** today it toggles `promptAlways`,
which admits prompt-origin standing entries when true; ruling-origin entries do not depend on it.
It is NOT a master enable/disable switch for hands, and `always off` does not revoke ruling grants.
After removing prompt grants, silently making it an unattended master switch would change its
meaning and widen authority. Proposed compatibility treatment for review: keep the typed command
recognized, report that the removed prompt-grant mode cannot create permission, and use named revoke
for ruling entries; do not relabel it “hands disabled.” Mainline/owner should confirm the desired
legacy-control receipt. No new prompting/card mechanism is needed for either typed control.

Old `source=prompt` grants must not be silently relabelled `source=ruling`. Their migration treatment
must be explicit (recommended: exclude them from unattended authorization under the new policy,
retain them as historical revocable records). Old policy data is not an auto-seed under Ruling C.

## 2. Accountability without the card — required before autonomous deployment

1. Keep a durable pre-dispatch ACTION/intent and append its OBSERVATION after the effect; removing
   interactive approval does not remove crash-safe intent logging. “Acts first, records after”
   describes no prompt, not permission to lose actions on a crash between effect and first record.
2. Refusals also get paired records: intent/action record says `dispatch_attempted=false`, followed
   by OBSERVATION `verification=refused`, `effect=none`, reason and assessed identity. Do not make a
   refusal look like an executed command. Legacy DENIAL rows remain historical; never rewrite them.
3. Each accepted action binds exact parsed argv, binary and inventory hashes, effect assessment,
   workspace/operand identities, authority entry ID/revision, reason and inverse/reversibility
   assessment. Replay reconstructs state, never re-executes effects.
4. Missing marker means unknown. Exit zero alone is insufficient: retain `ELARIA_OK_<nonce>`,
   target readback, stdout digest and exit status. A partial chain does not become a whole-plan
   success. Crash recovery records unmatched attempts as unknown, never quietly repeats them.
5. Sidebar on next open fetches durable summary and bounded detail with a continuation cursor.
   Counters distinguish observed actions, refusals, failed/unknown attempts and observed undo.
   Show counts even when more than 32 rows exist; disclose any unavailable/truncated historical range.
6. A daemon-persisted acknowledged-through cursor survives browser closure/restart and is advanced
   only by an explicit “seen” acknowledgement for rendered evidence, not connection/subscription.
   Label the count “since acknowledged” if actual gaze cannot be established. Viewing/focus is
   evidence for acknowledgement, **never an execution gate** reintroducing the removed card.
7. Every permitted effect needs a valid bounded inverse or must be refused. Undo targets the exact
   owned observed state and also passes policy/authority/readback checks. Unknown state, nonempty
   directory or externally changed target prevents destructive cleanup, never prompts a bypass.
8. Unattended means the mounted daemon can handle an authorized request without a visible console;
   it is not a scheduler, model command generator, auto-started Kitty or permission to operate on the
   owner's daily terminal. No new trigger mechanism is assumed from the word “both.”

## 3. Owner-run seeding packet — no command list supplied yet

The owner names discrete commands. No packet may guess or invent that list. For each eligible
command the packet must show canonical binary, parsed argv, exact argPattern, binary hash,
inventory hash and reversibility assessment, then write the ruled entries through a bounded
owner-side authority update with cold readback. File remains private 0600, owner-owned, single-link,
non-symlink; atomic update/fsync, no truncation of unverified destination, no group/world leak.
Fields stay `path`, `argPattern=sha256:<canonical parsed argv digest>`, `binary_sha256`,
`inventory_sha256`, `source=ruling`, `lastUsed`. The packet itself, expected authority diff and
readback verifier need a pinned manifest. No hand-editing JSON from chat, auto-seed or model-generated
approval. Old/new authority counts and exact matched entries must be reported; failure is not success.
Revocation is named-path typed control, and every future inventory re-pin requires reapproval.

**Two limits that affect that packet:**
- Current `Consent.load` only accepts canonical mkdir/rmdir entries. The owner naming another exact
  binary does not make its effect assessed. Broader commands require an assessed adapter; arbitrary
  executable, interpreter, alias/script/wrapper grants remain refused.
- `DedicatedKitty` creates a workspace below `elaria-hands-<random-instance-id>/work`. The ABS operand
  is part of exact argv. Entries for one instance do not authorize a newly minted instance's path.
  No wildcard, path substitution or automatic re-seeding may be introduced to hide this. A packet can
  bind an explicitly opened instance's exact workspace; durable cross-instance authorization needs
  a separately reviewed stable-scope design, not a claim that current entries already provide it.

This is why “one packet with mkdir NAME forever” is not a valid current contract. No owner packet
was generated or run in this contract-only delivery.

## 4. Sanctioned hands deployment path (ask 35)

**A release decision and a new pinned release are required, not `git pull` inside the working
native target.** Current native launcher target remains 25ef8e6. Pulling newer source into
`/tmp/elaria-console2` does not change what the installed coordinator verifies/serves. H/I are later
consumer builds; the owner successfully opening G's window is not hands hardware acceptance.

Sequence for a sanctioned release:
1. Land reviewed producer/mount and revised hands policy on an explicitly agreed integration basis.
   F37's conditions are satisfied by owner ruling, but no automatic merge/rebase follows here.
   Reconcile disjoint regions explicitly; preserve the eight-line mount boundary/regression and
   give an event-transport mount its own baseline/regression, never a silent daemon resolution.
2. Select an immutable integrated deploy commit containing the hands sidebar, headless adapter,
   supported IPC and new policy version. Publish runtime producer compatibility as well as shell
   identity; missing backend yields unavailable/refusal, not model fallback.
3. Issue a new launcher/installer release pinning that target, bridge/index/helper payloads and
   allowlisted migration-from state (including 25ef8e6), with source and installed readback manifests.
   Do not mix G helper/bridge pins with an arbitrary newer index. No keybind edit/reload is needed
   merely for replacing a verified same-path wrapper, but unknown live bridge ownership remains STOP.
4. Re-deploy only via that owner-run release; cold verify all installed artifacts and the served
   target identity. Observe native GTK, correct hands sidebar, real backend capability and source
   revision; no new browser fallback. Test against the actually resident daemon, not only a probe.
5. Hardware acceptance includes one narrowly ruled action, one recorded refusal and an **observed
   undo**, with marker + target state + journal/sidebar attribution, console reopen/unseen summary,
   named revocation without the window and another refused attempt. The current native acceptance
   remains accepted; the new release needs its own evidence. Reboot remains the natural-reboot
   residual already ruled, not a newly invented general hold.

The proposed first run `open → mkdir → status → close` lacks both a refusal and undo. Under new
Ruling C with an empty list it also cannot create a directory. Correct future pilot: verify exact
supported Kitty version/pin (current code requires **0.47.1**, not merely “Kitty installed”); explicitly
open dedicated instance; owner-run packet seeds exact assessed mkdir **and its authorized inverse**
for that instance; execute one mkdir; observe marker/state/sidebar; request safe off-list work and
observe refusal/no effect; undo by authorized rmdir while its owned empty state still matches;
observe absence and journal; exercise revoke/status with GTK closed; close only the dedicated hand.
No hardware commands are issued for execution by this design document. No daily terminal is touched.

## 5. Read-only machine inventory adapter (ask 36)

**Confirmed reading:** the pinned repository `inventory.json` describes her tools/native payloads,
not the laptop. Exact-argv standing entries authorize discrete assessed commands. A recursive
machine inventory belongs in a separately assessed, locally summarizing read-only adapter; it is
not thousands of directory entries or an allowlisted shell/Python script.

Proposed adapter scope/acceptance, not implementation or authorization to crawl the owner machine:
- Owner approves an explicit root/category/depth/file/time/mount budget and exclusions, bound with
  adapter implementation hash/version and schema. “Pinned once” binds that scope; changing it needs
  a new ruling. It does not mean unrestricted `/` traversal or all future roots.
- Use bounded metadata APIs (`lstat`/directory enumeration without following symlinks) and approved
  local package/OS metadata. No file contents, credential paths, shell startup, arbitrary discovered
  executable `--version`, document indexing, model SDK, network request or narration. Running a
  discovered executable to ask its version is itself unassessed execution; prefer package records.
- Directory entries/filenames/package strings remain **data** in a separate typed structure. They
  cannot append plan steps, choose tools, mutate scope, seed entries or grant permission. No data-to-
  instruction/model prompt route exists; detector misses cannot turn a filename into an action.
  Escape control characters for display; a filename such as `delete everything now.txt` is only data.
- Summarize locally into bounded counts/categories/version records. Do not return a raw file list
  as a cloud prompt. Prefer no persisted raw paths; any necessary local intermediate is private,
  bounded and disclosed. No cloud summarizer, telemetry or implicit browser/model forwarding.
- Missing permissions, skipped/excluded roots, timeouts, mount boundaries and partial coverage are
  explicit numeric records. A zero count is scoped, not “nothing on this laptop.” Hashes are not
  automatic permission to export sensitive identifiers either.
- Richer paths/content leaving the machine need itemized destination/content/purpose consent and
  a separately assessed egress path. The unattended command list is not that consent.

Required tests: adversarial filenames and package fields cannot mutate plan/scope; symlink/mount
escape; no content/credential reads; no network/model calls; no discovered executable execution;
partial/denied traversal truthful; aggregate counts grounded in synthetic trees; records-only
boundary. Owner hardware test starts with a small explicitly scoped area, not a first-run whole-disk
crawl. Adapter estimate: 4–8 hours after scope approval, plus separate owner evidence.

## 6. Hands indications on the existing orb (ask 37)

The frozen engine currently has five named states, **11 scalar parameters per state** and **9
palette stops per state**, with unknown names throwing. Adding native `acting`, `refused` and
`undo-window` would require at least 33 parameter values + 27 palette stops, dispatch/labels,
accessibility/reduced-motion tests, engine hash/embedded bundle/release pin changes. An additional
real `awaiting-consent` state adds another 11 values and 9 stops. That is an engine revision, not
merely pushing a new string into the current API; no such revision is silently authorized here.

Recommended consumer-only mapping for review: keep the exact engine, use an explicitly labelled
hands-state indicator/count **on the existing #orb rail**, separate `data-hands-state`/accessible
text and sessions attribution; no new orb and no hijacking listening/speaking to mean action.
Estimated consumer work 2–4 hours once durable hands summary/cursor exists; native engine-state
revision would add roughly 2–4 hours plus explicit engine/release repin review.

- `acting`: only dispatched, nonterminal work with an actual ACTION ID; not a request/plan/allowlist
  match. Does not prove effect. Terminal unknown removes acting and displays unknown, not success.
- `refused`: exact recorded refusal/reason; never implies execution.
- `undo-available` (prefer this label to an invented time window): observed reversible action with
  current inverse validity. Existing hands code has no independent timed undo lease; do not invent
  a countdown. Changed/unknown target makes undo unavailable/refused.
- Unacknowledged count: observed actions, refusals and unknowns separately, backed by durable cursor;
  not request count or transient browser memory. Voice indications cannot erase this count.
- No `awaiting-consent` for on-list work. Current typed always/revoke controls resolve directly,
  not through a pending card; therefore do not animate a fictitious ask for them. If another actual
  confirmation remains (e.g. separately scoped undo review), it may show its real pending state.

Voice capture/player labels stay independently visible. Neither hands animation nor an unseen-count
badge may imply recording when capture is closed, or imply an action occurred merely from a plan.
Attribution, refusals and action/observation detail remain in sessions sidebar, never center chat.

## 7. Required change order and evidence

1. Publish/accept revised hands authority policy and old-prompt-entry/always compatibility decision.
2. Implement immediate miss refusal, close old answer capabilities, preserve independent classifiers,
   marker/hashes/dedicated-instance rules; add journal pairs, durable summary/cursor and safe undo.
3. Build the owner-run seeding packet only for the owner's actual exact commands/instance scope.
4. Wire sidebar and orb indicators from durable evidence. Tests must cover closed-window use,
   restart, more than 32 records, revoked/stale grants, every chain segment, legacy token/grant
   rejection, journal failure and unknown effects. Existing immutable inventory is unchanged.
5. Sanction a new integrated native release and run the owner hardware pilot above.

No hands code, standing entries, packets, runtime workspace, native target or protected mount was
changed in this delivery. This is a direct answer about what current code can and cannot promise,
not a claim that removing the ask has already shipped.
