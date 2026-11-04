# Task C — remember/forget per-act pilot review surface

2026-11-04 · **DESIGN ONLY / NOT BUILT / NOT A PILOT APPROVAL**

Estimate before work: 30–45 minutes. This separate docs-only task expands matrix §3's
remember/forget rows into a reviewable surface and seam contract. Nothing here enables a
button, adds an RPC, alters existing typed execution, or claims an approval consumer exists.

Owner order: mainline owns the scoped-undo fail-closed grant; consent builds proceed behind
that. Reads, remember/forget and organise remain executable on today's typed text until their
pilots exist. Task A exposed evidence gaps; Task B added the bounded registry, not consent.
This document is not permission to bypass that sequencing or to implement protected seams.

## 1. The surface, before any execution

Two separate review cards, never an approval embedded in the model's reply. An immutable
prepared act has an opaque ask ID/version, a fixed named service endpoint/instance identity,
a focused private owner decision and a receipt lineage. These are **proposed fields**, not
claims about today's console.say envelope. A browser session name or conversation ID does
not authenticate the owner or identify the currently focused ask.

Draft composition stays local to the authorised private surface; no new model/provider,
phone synchronization or write-on-preview path. Today's `remember ...` console.say route
cannot be used to prepare a draft because it already writes. A dedicated non-mutating
preparation seam must be designed/ruled first. Forget resolution likewise requires a scoped
named-service read seam, not arbitrary SQL or a broad database listing.

### Remember — exact fact review

Private card contents:

| Field | Review requirement |
| --- | --- |
| Heading | **Remember — review one fact**; status **DRAFT / NO WRITE SENT** |
| Ask reference | Opaque ask ID, immutable version, age; not a fact ID |
| Exact fact | Exact final UTF-8 text proposed for storage, including meaningful whitespace/newlines; escaping must not silently alter stored bytes |
| Kind/source | Service-prepared effective kind and source (today normally profile/stated), not a model guess or an editable promise of unsupported kinds |
| Destination | Named memory-service instance and allowed scope, not an arbitrary path/SQL target |
| Effects | New active fact; disclose permitted associated metadata/receipt writes; no hidden secondary action |
| Limits | Persistent until policy/deactivation; no guaranteed expiry supplied; text/history/provider copies are not erased by later deactivation; no exact restore guarantee |
| Assessment | Current permitted scope and policy result; unresolved or T3 proposals are refused before Yes is enabled |
| Controls | **Edit draft**, **Yes — store this exact fact**, **No — do not store** |

Illustrative content is synthetic, not an existing fact or implemented UI:

> Remember — review one fact  
> Exact text: “Synthetic example: I prefer a quiet workspace.”  
> Kind/source: supplied by the prepared service result; unavailable until that seam exists.  
> State: DRAFT — NO WRITE SENT.  
> A new fact ID will be reported only after an observed store result.  
> Deactivation later is not erasure or exact undo.  
> [Yes — store this exact fact] [No — do not store] [Edit draft]

Do not display a guessed fact ID, “remembered”, a fake kind or a success animation while the
card is merely drafted/approved/dispatched. Duplicate detection, if provided, is an explicit
non-mutating preparation result; silently changing an add into update/merge is a new act.

### Forget — freeze exact targets before review

Private card contents:

| Field | Review requirement |
| --- | --- |
| Heading | **Forget — review deactivation**, never “erase” |
| Original selection | ID or substring used to prepare the selection; context only, not an execution-time selector |
| Frozen targets | Exact affected fact IDs, service revisions/identity, current active states, exact private fact text and relevant kind/source |
| Exact count | Count of that immutable target set; every target accessible in the review, no hidden off-screen additions |
| Intended change | Each listed active fact becomes inactive; no deletion, no broad future substring match |
| Retention | **Deactivation-not-erasure**: fact text and conversation/history may remain; no exposed exact restore operation; remembering again creates a different fact |
| Assessment | Scoped named-service authority, current state/policy and any bounded batch ruling; no generic store access |
| Controls | **Edit selection**, **Yes — deactivate these exact N facts**, **No — keep these facts active** |

Illustrative content, not a real returned receipt:

> Forget — review deactivation  
> Selection: a synthetic substring, used only to prepare this draft.  
> Targets: exact IDs/text/revisions must come from the named service; none fabricated here.  
> Count: unavailable until resolution — **Yes disabled**.  
> Deactivation-not-erasure. No restore button is promised.  
> [Yes — unavailable pending preparation] [No] [Edit selection]

An empty resolved set is a no-op result, not “forgotten” and not a reason to fabricate an ask.
Unbounded, truncated, mixed-scope or unassessable results must be refused, not presented as
“and more”. A first one-fact pilot is a recommendation, **not an adopted batch limit**; owner
ruling must set the permitted count and partial-failure contract before any multi-fact build.

## 2. Dedicated focused Yes/No, not conversational intent

- Exact private card focus selects one immutable ask version. Merely opening the app,
  connecting the wire, identifying the owner, or holding session authority is not consent.
- Only the dedicated decision entry/buttons consume Yes/No. Text entry follows the existing
  precedent: trim/casefold exact `yes` or `no`; other strings are not decisions. Do not dispatch
  these through chat, the intent parser, a model, a terminal or a kitty hand.
- With no focused eligible ask, return **“no ask is selected”** and cause no effect. The latest
  chat turn, notification click, visible conversation tail or last-created ask is not a fallback.
- A click/keystroke binds ask ID/version, exact act, actor, service identity and current private
  focus. Recheck that binding at consumption; a focus race must not approve a different card.
- No is terminal for that ask/act version. A new nonce or reopened window cannot evade it.
  An explicitly revised act needs a new preparation/review, not automatic reissuance after No.
- Pending asks show age; time passing does not approve them. Restarts do not restore a session
  hand or execute an unspent decision automatically. Preserve only correctly bound durable
  state, re-establish authorised focus and reassess freshness under the ruled consumer policy.
- Company/locked/unknown posture must not expose exact facts. Hide/park according to the
  existing private-surface policy. Any public knock contains only **`elaria needs a yes`**,
  with no fact text, IDs, count, target or decision detail; no notification action executes.
- Consent is separate from capability evidence, assessment and observed effect. Yes cannot
  make an unassessable proposal assessable, convert refusal into capability, or unlock T3.
  K-style authority is not a T-tier classification; session permission is not per-act approval.

## 3. Edits and stale approval

Preparation must freeze the complete semantic act, not just a chat string: operation kind,
named service/instance, canonical exact fact bytes/effective kind/source for remember, or
ordered exact target IDs/revisions/states for forget, intended changes, relevant policy and
receipt contract. The canonical representation and digest/version scheme need a mainline
contract; this document does not invent a live token or imply a schema already exists.

**Any edit invalidates approval immediately.** This includes fact text, whitespace that will
be stored, kind, selection, membership, order if material, destination, scope, policy or
service identity. The card returns to draft/stale, with Yes unavailable until fresh preparation
and review. No silent normalization after approval and no “same words” override of changed
bytes. Changing only an ask ID cannot turn the denied act into an approved one.

Before mutation, the future named-service consumer must atomically validate/consume the
specific decision against fresh policy and the exact prepared target identity. A browser-only
check cannot close a concurrent update race. Missing/deleted/edited/already-inactive targets,
revision mismatch or scope drift require refusal/review, not substitution or re-resolution.
**Never execute the broad forget substring again after Yes**: a newly matching fact is not
approved. A missing version/freshness primitive is a seam blocker, not permission to use a
creation timestamp, nearby row or the post-turn history sample as a substitute.

A decision authorizes at most one dispatch of that exact act. Disconnect/timeout after
submission is **unknown**, not rollback. The dispatch authority is spent; reconcile through
request-bound service observations rather than automatic replay. Repeating remember can
create another fact; repeating forget can sweep in newly matching rows if scope is not frozen.

## 4. Receipt surface and state meanings

All IDs below are proposed service-returned identifiers. Never show fabricated examples as
live values. Link request/prepared act, assessment, owner decision, one dispatch and observed
result; keep exact fact content on the private review surface, not general telemetry/journals.
An operation receipt is distinct from a bridge observation, conversation ID and message ID.

| State | Private receipt presentation | Authority/effect meaning |
| --- | --- | --- |
| DRAFT / PREPARED | Ask ID/version, exact act and assessment reference if available | No decision or mutation |
| REFUSED / NO | Bound ask/version, reason or owner No | No execution; not a missing capability proof |
| STALE | Prior version and change reason | Previous Yes is unusable; new review required |
| APPROVED | Decision ID, actor/focus binding, act version | Permission for this act only; not completion |
| DISPATCHED | Request/operation reference and decision-consumption state | Exactly one submission; not yet verified |
| VERIFIED | Result receipt ID, exact fact ID(s), resulting active state(s), exact affected count and observation source | Observed result of this act, not just an acknowledgement |
| FAILED / PARTIAL | Exact observed per-target outcomes plus unresolved targets | No blanket success; no automatic compensating operation |
| UNKNOWN | Request/decision/dispatch references, uncertainty reason, reconciliation status | Do not retry automatically or claim no write happened |

Remember verification must bind the returned new ID to the approved content/kind/source and
resulting active state using a permitted service observation. Forget verification must cover
the exact approved ID set, revisions and resulting inactive states, with exact affected count.
A string “Remembered” or “Forgotten (N...)” alone is not the future complete receipt chain.
If acknowledgement arrives but independent permitted observation is unavailable, keep it
unverified/unknown rather than inventing a verified badge. Verification reads and any receipt
metadata writes must be included in the pilot's scoped assessment and privacy contract.

No “undo”/“restore” control is promised. A later deactivation or new remember is a separately
assessed act, not automatic exact reversal; failure does not authorize a compensating write.

## 5. Mainline seams and explicit build holds

1. Owner pilot ruling: named memory-service scope and authority, retention/reversibility text,
   one-fact versus bounded-batch limits, partial failure semantics and accepted private focus.
2. Non-mutating preparation: exact effective remember fields; exact forget IDs/text/revisions/
   states/count. No draft execution through today's console.say and no arbitrary DB access.
3. Consent persistence/consumer: durable ask/version/decision/no state, trusted actor/focus,
   single-use dispatch binding and atomic stale/policy validation at the service boundary.
4. Request-bound results: actual fact IDs/kinds/states/counts, receipt references and bounded
   reconciliation/verification reads. Existing reply prose/history IDs do not supply these.
5. Private presentation/posture seam: focused decision entry separated from chat, correct
   hiding/parking, generic notifications and private receipt retrieval.
6. Narrow protected-code grant and explicit pilot build order after the mainline consent seam
   and scoped-undo ruling. This task grants none of these and implements no UI or endpoint.

**Control-state boundary remains:** no SQL, file editing, generic shell/T1 wrapper or direct
store.db/hands.db access. The owner must rule how the existing dedicated memory service gets
an approval adapter; that is not a general protected-tree exemption. T3 remains refused even
with Yes, including any proposal that actually edits protected control-plane state outside
the ruled named service. Kitty/NectarLink remains parked; no borrowed hand/password/decide.

## 6. Future pilot acceptance cases — specifications, NOT executed tests

- Remember review exposes exact prepared bytes/kind/source; Yes stores once and returns an
  observed new fact ID/state; No causes zero write. Approved then edited text is stale.
- Forget review exposes the complete frozen ID/version set and count. A new matching row
  appearing after review is excluded, and changes to a reviewed row invalidate dispatch.
- Wrong/no focus, a switched ask, non-exact decision text, company/locked/unknown posture,
  reconnect and restart never route a generic Yes into mutation or expose private facts.
- A repeated decision, already-consumed token or denied version cannot dispatch again.
  After timeout, reconciliation reports exact outcomes or unknown; no automatic replay.
- Missing receipt/freshness fields prevent a verified badge and block unsafe execution.
  A denied assessment/T3 cannot be bypassed with explicit Yes, a new nonce or session authority.
- Tests observe both permitted and denied outcomes using synthetic temporary service state;
  verification needs actual effect observations, not only receipt strings or UI snapshots.

## 7. Pinned references and delivery status

- `c327df72d75f05e0035c2ffed1ed91cd78eb20d7:docs/phase-reports/console-2026-11-04-exposure-consent-matrix.md:73`:
  exact remember draft, private focused decision and ID/state receipt.
- `c327df72d75f05e0035c2ffed1ed91cd78eb20d7:docs/phase-reports/console-2026-11-04-exposure-consent-matrix.md:74`:
  frozen forget IDs/versions/count, no substring re-sweep and deactivation-not-erasure.
- `c327df72d75f05e0035c2ffed1ed91cd78eb20d7:docs/phase-reports/console-2026-11-04-exposure-consent-matrix.md:83`:
  consent/focus/privacy/receipt precedents and the non-waived control-state boundary.
- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/daemon.py:3582`:
  audited current local intent path, not the proposed consent consumer.
- `7f718680b45d62e0dbe8da4b7097b27cbd5f57af:docs/phase-reports/console-2026-11-04-task-b-registry.md:37`:
  registry responses do not execute or become daemon conversation entries.

**DONE:** docs review surface and seam checklist, not an operational pilot.  
**DEFECTS / GAPS:** missing producer preparation/consent/freshness/result seams; no private
review implementation or owner-hardware validation.  
**NEXT:** mainline consent seam and explicit pilot ruling before code; separate supervised
build/test/acceptance, not implicit graduation.  
**OPEN:** exact named-service authority, batch bound/atomicity, retention/reconciliation and
private-focus contracts. Current typed execution is unchanged by this document.


Repository regression checks for this **docs-only** commit: full suite **2589 passed,
8 skipped, 118.16s**; Ruff passed; diff whitespace check passed. These checks validate the
existing repository, **not the unimplemented pilot acceptance cases above**. No code/payload
change, backend/model invocation or hardware validation in Task C. Task A/B release pins
remain unchanged; the current check-before-run/hard-stop entry stays in `console/BRIDGE.md`.
