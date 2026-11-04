# WS5 exposure-and-consent matrix — draft for owner ruling

**Docs only. No implementation, route, exposure, protected-file or service change.**
Baseline: accepted `fcd55ca1bce34d8a1f479bf2d035cc866c4a482f`.
Reachability/effect audit: exact mainline `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1`,
read without checkout or merge. Proposals below are NOT adopted permissions.

**Sharpest edge: scoped undo can change real files without a fresh approval dialogue.**
Its operation lock is concurrency control, not consent. A journalled reversal is not
permission to perform that reversal.

> An owner-authenticated typed request is not evidence of an effect or automatic consent.
> — console/BRIDGE.md

WS4 confirmation: both shutdown directions, unique private profiles, and no token in stdout or argv completed green as described in the handoff; the four targeted local tests reran green (4 passed, 0.97s), not owner-hardware certification.

## 1. Reading the matrix

The two tables are one matrix split for readability: effects/evidence, then current/proposed
consent, with the same seven rows. `findwhere` is the relay's label for parser kind **where**
(`find`, `where is`/`where's`/`where are`, `locate`), not a new literal command or route.
The typed scoped-undo grammar supplies **since**; op_id/plan_id exist at the backend API,
not as additional typed syntaxes established by this audit.

**Mutating** below means the verb's domain effect. Every normal owner `_ask` turn also writes
conversation/persona bookkeeping: user text before dispatch, and assistant reply/via on
successful completion. Thus “No” for lookup does not mean a literally write-free RPC.
A refused/erroring turn may leave the user record without a completed assistant record.
Undo also acquires an executor lock and can create its lock file before the scope refusal.

These paths describe the normal authenticated owner route. Show-off mode diverts to guest
handling; disclosure filtering also applies. Typed console input does not traverse the ASR
confidence gate. A withheld reply, disconnect or timeout does not undo an earlier mutation.
The bridge's readiness/provenance checks are neither an approval system nor an effect sensor.

## 2. Effects, reversibility and attribution — current implementation

| Verb | What it touches today | Mutating? | Reversibility today | Attribution trail today |
| --- | --- | --- | --- | --- |
| **findwhere** | `Memory.answer_where` uses recall and returns up to three indexed document candidates. Recall can examine document snippets/vectors, active facts and recent transcripts before filtering to documents. No fresh arbitrary-file open. Weak/no document hit returns control to `_ask`, which may invoke the model. | **No** index/source edit by the lookup; common turn writes still occur. Model fallback is a separate outward effect, not a pure local lookup. | No source-file change to reverse. Displayed information, stored conversation or a transmitted model prompt cannot be “unread” by undo. | **Partial:** indexed path/ref and existing index metadata; user/assistant messages with timestamp/channel and successful `via=local-memory`. No dedicated receipt tying the actor, exact read set and consent to this lookup. An index candidate is not proof the file still exists or was freshly read. |
| **search** | `Memory.recall` searches indexed documents/chunks, active facts and recent transcripts; local reply includes source/ref and snippets (up to 100 characters per displayed hit in this intent). A miss can fall through to the model. | **No** source/index edit by recall; common turn writes and possible model fallback as above. | No source mutation to reverse. Exposure/history/provider transmission is not reversible by deleting a result card. | **Partial:** source/ref on hits and conversation/via, not a per-read actor/approval/effect ledger. A source label does not establish freshness or permission for further analysis/sending. |
| **remember** | Adds a fact to the daemon store, normally kind `profile`, source `stated`, confidence 1.0. The service obtains a new fact ID; the typed answer repeats the fact rather than returning a structured ID receipt. | **Yes** — persistent memory write, plus common turn writes. | Can later soft-deactivate a fact, but that is another mutation, not an automatic exact undo. The row and conversation are retained; later use/disclosure cannot be erased retroactively. Do not call this fully reversible. | **Partial:** fact ID/creation timestamp/kind/source/confidence and conversation. `stated` is provenance, not an approval record. No fact-row binding to requester, focused ask, consent version or originating message. |
| **forget** | Sets `active=0` for an active exact fact ID (`#N`/`N`) or every active fact matching a literal substring. `%` and `_` are escaped; ordinary substrings can still match several facts. Does not delete fact text, conversation history or provider copies. | **Yes** — potentially multiple fact-state changes. | Logical deactivation, not erasure. No reactivation/exact restore is exposed by these typed verbs. Remembering the text again creates a new row, not restoration of the original ID/state. | **Weak/partial:** retained rows/current active flags and, on completion, a count in the conversation. This path adds no deactivation timestamp, actor, exact affected-ID receipt or per-act approval record. Original fact creation timestamps do not date the forget operation. |
| **organise** | `_run_intent` calls `_plan_build({})`: the typed argument does **not** narrow roots. It reserves plans for **all configured roots**, re-indexes permitted files, updates documents/chunks/status, persists plan items/stats and writes a shadow Markdown log. This invocation does not request model tiers or call apply. | **Yes** — index/plan/log writes and fresh local file reads; **No** source-file moves on this route. “Build only” is not “write-free.” | Source placement is unchanged. No exact rollback of previous index/chunk state is established. Removing a plan/log would not restore overwritten index state and is not an authorised cleanup proposal here. | **Partial:** plan IDs, timestamp/root/mode, item source/destination proposals, stats/log path, index metadata and progress events. No originating-message/actor/consent binding in the plan row. A started-plan reply or proposed destination is not an executed-move receipt. |
| **scoped undo** | Resolves a relative/ISO since value, selects eligible operations (`committed`, `copied`, `intent`) and visits them in reverse order. Can move current destinations back, journal/trash an identical duplicate, mark original operations rolled back, and remove an empty `_Conflicts`/`_Unsorted` parent. Different-content collisions/hash changes refuse affected operations. | **Yes** — real filesystem, journal and operation-status changes; a batch can partly complete. | **Conditional**, not unconditional rollback: source must exist and checks must pass. Reverse file operations are journalled, so further reversal may be possible; no automatic redo or whole-batch atomicity. Empty-directory cleanup is not a complete journalled metadata restoration contract. | **Strong effect metadata, incomplete actor/consent attribution:** operation IDs, plan IDs, paths, timestamps, before/after hashes, phases/status/error and original-row rolled-back state. `Journal.begin` has no actor or consent fields and no dedicated undo-of approval linkage. A plan ID is not proof that the assistant owns the target or that the owner approved this reversal. |
| **bare undo** | Enters the executor operation gate, then rejects the missing op/plan/since scope before selecting or reversing files. Common request bookkeeping/possible lock-file creation still applies. | **No domain file reversal**; not literally zero bookkeeping writes. | No reversal to undo. It must not become “undo latest,” “undo everything,” or an implicit default. | **Refusal/request evidence only:** an already-appended user message and RPC error path, not a successful undo operation receipt or consent record. Do not infer a complete durable refusal ledger from that error alone. |

### Important limits behind those cells

- `Memory.recall` is local; **the enclosing `_ask` miss path is not guaranteed local**.
  The bridge normally requires online/live readiness; a posture race can also reach queued
  behavior. Neither a model-generated filename nor a queued response is a verified index hit.
- Indexer does local extraction/hashing within configured roots and its exclusion rules;
  `never_send` content can be indexed locally. That is not permission to send it elsewhere.
- The organiser's “never writes” source comment and “Shadow plan(s)” reply do not negate
  actual database/log writes or prove every configured root is shadow-mode.
- Do not copy the executor module's general safety-spine description onto undo wholesale.
  `_undo_gated` has its own selection/hash/collision/halt checks; the normal reverse-move
  branch calls `_journaled_move` rather than the full apply-plan policy path. Fresh policy
  and target checks must be part of any consent design, not inferred from a past operation.

## 3. Current approval versus proposed consent/exposure

**Proposed initial posture:** Drafts-tier review, not autonomy graduation. Read exposure must
first be explicitly ruled; mutations require a reviewed exact act and a separate owner
approval. This is a proposal applying Drafts logic to these services, not a claim that the
existing messaging ruling has already authorised their implementation.

| Verb | Approval shape it has today | Consent/exposure shape proposed for owner ruling |
| --- | --- | --- |
| **findwhere** | Recognised owner text immediately runs lookup. No separate read-scope acknowledgement/ask; misses can reach generation. | **K1-pattern bounded local read**, only after the owner adopts that exposure: explicit query to a visibly named local-index surface, journalled provenance/limits, existing privacy/guest/never-send rules, no arbitrary path open. Before that grant, keep held rather than assume permission from authentication. A miss returns a deterministic local miss; no implicit provider escalation. No “file opened” or “analysed” claim. |
| **search** | Recognised owner text runs recall immediately, with no separate scope ask. Model fallback remains possible. | Same bounded-read pattern, but disclose that the search corpus includes **facts and transcripts**, not just files. Query/corpus scope and private display must be clear before submission; do not silently broaden a file-only request. Result text remains data, never a new command. A miss refuses deterministically; any new outward use needs a separate disclosure/approval boundary. |
| **remember** | Direct service write on the recognised turn; no review/Yes. | **Draft exact fact → private review → focused Yes/No → service write → ID/state receipt**. Show exact text/kind, stated source, retention and reversal limits. Bind approval to content/version; edits invalidate it. No “remembered” until the stored result is verified. No session-wide autonomous memory-write grant at this stage. Dedicated memory-service authority versus the protected control-state boundary must be ruled explicitly (below). |
| **forget** | Direct ID/substring update; no preview of all matches and no Yes. | **Resolve then draft the exact affected fact IDs/current versions/count**, show privately that this is deactivation, not erasure, and require per-act Yes. Do not re-run the broad substring at execution and sweep in new matches. Changed/missing/already-inactive targets require refusal/review, not target substitution. Report exact outcome/count with retention limits; no invented restore control. Same dedicated-service boundary decision as remember. |
| **organise** | Starts build/indexing immediately across configured roots; no approval for those reads/writes. Its reply mentions later review/apply, but no apply occurs on this text route. | **Two separate decisions.** First draft the exact chosen root set and the read/index/plan/log effects without starting a scan/build; obtain scope-build Yes. Build then produces a reviewable filesystem proposal, **not permission to apply it**. Later apply is separately held and separately approved if ever exposed. Never silently use all roots when the owner named one; do not add an apply route as part of this matrix. |
| **scoped undo** | Explicit scope + executor concurrency/safety checks, **NO fresh approval dialogue**. Typed input bypasses the ASR gate. | **Highest-priority per-act draft/approval boundary:** resolve scope once, display exact operation(s), targets, preconditions, collateral effects and reversal limits; bind a focused owner Yes to that immutable snapshot. Recheck policy/identity under execution exclusion; changed scope/targets invalidate approval. No re-evaluated moving since-window, no auto retry, no “undo is safe because it reverses something.” Use the conservative exact-act/target consent pattern, not an inferred ownership/session grant. |
| **bare undo** | Missing-scope refusal, not an approval request. | Keep deterministic refusal and ask the owner to select a scope. If a later review surface offers eligible-operation selection, that is a read/draft step, not execution. **Yes to an unscoped undo must do nothing**; no default operation may be manufactured. |

A scoped read grant above is an explicit owner policy for a deliberately selected read
surface, not a transport credential magically becoming consent. It cannot authorise mutation,
model fallback or outward transmission. No such exposure change is made by this report.

## 4. What transfers from kitty consent — and what does not

1. **Nature, attribution, reversibility before permission.** File ownership by UID, a friendly
   filename or a previous plan does not establish assistant-created/HER attribution. Missing
   attribution or unknown effects never earn a more permissive path.
2. **K and T are not interchangeable.** K1's journalled-read pattern, K2's explicit session
   hand plus plan/gate checks, and K3's exact-act/target consent are architectural precedents,
   not new classifications granted to memory/filesystem verbs. This proposal starts mutations
   behind per-act review even when later reversible autonomy might be considered. A session
   hand alone is not the proposed Drafts-tier approval; graduation is a separate ruling.
3. **Independent assessment stays independent.** Model prose, retrieved content and caller
   booleans cannot supply consent, identity, a safe-tier verdict or an effect checker. Assess
   at planning and again before execution; refusal/unknown evidence is not fixed by Yes.
4. **Bind the reviewed act.** Reuse the immutable whole-plan/hash discipline without silently
   changing its serialization contract. Bind exact logical payload, scope, ordered target IDs,
   target versions/identity and endpoint to the reviewed ask. A consent record also binds the
   observed target fingerprint; do not treat a plan hash alone as current-target evidence.
5. **Dedicated owner-input path.** Focused private card, exact Yes/No semantics; without a
   focused ask, “no ask is selected,” no intent dispatch. A chat “Confirmed” or model-authored
   Yes is not a decision. The shared daemon conversation is not sufficient ask/focus binding
   across tabs/clients. Do not send an approval through ordinary model conversation and hope
   it selects the right act.
6. **No wins; no replay.** No is terminal for that ask version. An edit/new target makes Yes
   stale; changing a nonce alone cannot evade a No. Pending asks do not time out into Yes;
   show age. Restart/disconnect uncertainty is not permission or rollback. Restore at most
   a valid unspent decision for the same immutable act/endpoint; never restore a session hand
   or auto-run. A dispatched/unknown act is spent and reconciled, not retried blindly.
7. **Privacy and receipts.** Exact content belongs only on the authorised private review
   surface. Public notifications carry only `elaria needs a yes`, never file/fact content;
   existing company/locked/unknown posture rules remain. Receipt metadata should link request,
   assessment, owner decision, dispatch and observed result without copying secrets/content
   into general journals. Existing channels/messages are not that complete receipt chain.
8. **Verify the effect.** Keep separate outcomes: proposed, refused, approved, dispatched,
   verified, failed/partial, unknown. Transport success and an executor return are not blanket
   completion proof. Re-read the exact approved targets; never let acknowledgement stand in
   for an observed effect.

**Control-plane boundary is not waived.** Existing dedicated memory services already write
facts, but the general hands errand plane still cannot read/edit store.db, hands.db or the
protected assistant state tree, even with Yes. Do not implement remember/forget as SQL, a
file edit, an arbitrary command or a generic T1 wrapper around that tree. Owner ruling must
settle whether/how the existing named memory service receives a review/approval adapter;
this is not a production control-state exemption. Refuse any proposal that actually falls
inside T3; no consent dialogue unlocks it. Likewise, no kitty hand/password/decide route is
borrowed to authorise an unrelated filesystem or memory operation.

## 5. Smallest scoped-undo repair proposed — not implemented

**Smallest containment:** if the owner wants a safety stop before the usable review path is
ready, refuse scoped undo at the canonical daemon undo entry before mutation. A banner,
regex warning or an extra conversational “are you sure?” does not close the path. This stop
would be an exposure change and a protected-code edit; it is **not authorised or applied now**.
It blocks unapproved execution but is not delivery of an approval dialogue.

**Smallest usable repair:** an **undo-only prepare → focused decision → execute gate** around
the existing journalled executor, not a general hands runner or a new filesystem capability.

- Intercept the canonical undo entry shared by typed intent and the daemon undo RPC, not
  just the browser's spelling of `undo`. Preserve bare-undo refusal and cover language aliases.
- Preparation resolves the since expression to a fixed time and exact eligible operation set.
  Bind row IDs/status/version, current/reverse paths, expected bytes/hashes and fresh target
  identity; disclose duplicate retirement/trash and directory cleanup if they may occur.
  The ordered scope is fixed: **do not invoke a fresh `undo since ...` after Yes**.
- Recommend a **single explicit operation** as the first usable pilot. A multi-operation since
  selection becomes a selection/review step, not automatic permission to reverse the batch.
  Initially refuse ambiguous `intent`/`copied` recovery, duplicate-retirement or other branches
  whose exact effects cannot yet be bound and assessed. That proposed narrowing also needs
  the owner's ruling; it is not current behavior. Batch support requires exact ordered-set
  binding and an explicit partial-completion policy, not “undo all” hidden behind the button.
- The separate owner decision binds ask/version/actor and current identity, never just the
  original phrase. Check approval and fresh policy under the mutation exclusion boundary;
  invalidate on change. Keep existing hash, collision, halt and journal safeguards. Consume
  dispatch authority once; observe/reconcile uncertain effects rather than replay them.
- Return a result linked to the original operation, consent and newly journalled reversal;
  verify target placement/content and report partial/unknown outcomes explicitly. If the
  required observation or reversibility cannot be established, refuse instead of adding Yes
  as a substitute for evidence.

**Honest scope of that repair:** a daemon-entry gate closes the console/daemon route, not
all direct executor use. Mainline CLI can fall back to `Executor.undo` when the daemon is
unavailable (`cli.py:2409–2416`). If the owner's ruling demands global enforcement, the
executor/direct-CLI boundary must also enforce it. Conversely, a browser-only gate can be
bypassed through the daemon and must not be described as a global fix.

The existing API already supports an explicit op_id, which avoids inventing a new undo
primitive. It does **not** already provide a reviewed target-fingerprint/consent check under
its operation lock. The usable repair therefore needs a narrowly ruled protected integration
seam and a real approval consumer; an additive UI alone cannot certify it. Request that
file-specific grant before implementation. No parser, daemon, executor, CLI, store, shared
fixture, approval route or consent ledger is changed in this docs-only task.

## 6. Decisions for the owner / design chat

- Adopt or revise the proposed bounded-read exposure (corpus, privacy, deterministic misses;
  no implicit model fallback). Neither lookup is fresh-file analysis or calendar capability.
- Adopt or revise per-act Drafts-tier review for remember/forget, including retention/restore
  limits and the dedicated-memory-service/control-plane distinction.
- Decide organiser's scope-build approval separately from any future apply exposure.
- Prioritise scoped undo: temporary fail-closed containment versus the single-operation
  review pilot; console/daemon scope versus enforcement at every executor entry.
- Any broader batch scope, automatic reversible action, messaging send path or autonomy
  graduation requires its own ruling. No feature build starts merely because this draft exists.

WS2's documented decision boundary/deterministic refusals await the owner's formal adoption;
the three questions remain a behavioural target, not proof. **history_limit stays unchanged**;
its dismissed context-loss hypothesis is not reopened. Wide-screen clipping remains an owner
observation under acceptance: if reproduced, first reproduce at the supplied exact window
size, zoom and monitor, record what headless missed, and only then consider a change. No new
sizing work is performed here. Native --open appearance remains the owner's hardware verdict.

## 7. Source anchors and verification

Source claims above were re-read at **a6cc150**, not inferred from comments or the prior report:

- `src/assistant/intents.py:35–40,53–58`: undo scope/lookup/memory/organise grammar and aliases.
- `daemon.py:_console_say` (1167), `_ask` (3333): channel/principal, guest diversion,
  pre-dispatch user record, local routing, post-effect disclosure and reply persistence.
- `daemon.py:_run_intent` (3582): the seven dispatch paths; no scoped-undo approval branch.
- `memory.py:Memory.remember/forget/recall/answer_where`; `store.py:add_fact/forget_facts`,
  facts/messages schemas: local recall, fact mutation and attribution limits.
- `daemon.py:_plan_build` (2651), `organiser.py:build_plan/_write_shadow_log`,
  `indexer.py:index_root`, `store.py:create_plan/add_plan_items/finish_plan`: actual build effects.
- `daemon.py:_undo` (2775); `executor.py:_operation_gate`, `undo/_undo_gated` (440/446),
  `_journaled_move`, `parse_since`; `store.py:undoable_operations/mark_rolled_back`;
  `safety.py:Journal.begin/commit`: lock, selection, mutation, recovery and journal limits.
- `cli.py:2409–2416`: direct fallback outside the daemon boundary.

Consent architecture references at the accepted branch baseline: `docs/kitty-host.md`
(contract/recovery), `docs/kitty-setup.md` (integration),
`src/assistant/hands/kitty/policy.py:Authorizer`, and
`docs/design/BLUEPRINT-V2-extract.md` dated R3/R5/R6/R7/R8 addenda. These are precedents and
holds, not permission to activate parked kitty adapters or assign new K/T tiers by analogy.

**Verification of this docs-only delivery:**

- Existing full local stub suite: **2520 passed, 8 skipped**, 106.90s; Ruff passed.
  No new consent tests or implementation were created. These results protect the unchanged
  baseline; they do not prove the proposed consent system exists. No browser geometry or
  native app-window gate was rerun for this report.
- Sandbox refresh had reset Git metadata to the original base while leaving accepted files.
  All **304** accepted files were byte-checked against fcd55ca, with no extra nonignored files,
  before restoring HEAD/index only. Final scope gate requires all 304 to remain byte-identical
  and this report to be the sole added file. Mainline a6cc150 was fetched/read only.
- Engine pin remains `5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`;
  launcher pin remains `ed227a7d50effb874e303f95462f3dc127c9bd79a71a8d9b34f86980815b091c`.
- No protected source, config, fixture, route, exposure, threshold, history limit or engine
  edit. No service commands/unit edits: elaria-console.service's enabled-state hold is
  preserved, not claimed to have been remotely measured. Kitty stays parked/scene NOT READY;
  NectarLink stays out. No owner content/keys, paid model call, owner checkout action, PR or
  force push. Research/dependency artifacts stay ignored and outside the report commit.

**DONE:** requested seven-verb matrix and scoped-undo repair proposal. **DEFECTS:** missing
undo approval and incomplete actor/consent bindings remain current behavior, not repaired.
**NEXT:** design chat folds the matrix into the owner's ruling. **OPEN:** exposure/consent,
WS2 adoption and the owner's layout/native-window verdicts; no implementation proceeds on
this report's authority.

If the undo proposal is later adopted, its acceptance must include zero reversal before Yes;
exact-operation/target binding after Yes; preserved bare-undo refusal and canonical consent
checks across aliases; T3/unknown-effect refusal; stale/wrong-tab/replayed/No decisions; new operations appearing after a
since-scope draft; halt/partial/unknown outcome reconciliation without replay. These are
**future required tests, not tests executed or passed in this docs-only task**.
