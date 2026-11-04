# Task B — WS2 implemented boundary, 2026-11-04

Estimate before work: 90–150 minutes. Separate Task B commit; no new hands executor or
protected daemon grant. Owner adopted the constrained capability/action boundary, not a
claim that unrestricted generated prose can be made universally honest with keywords.

## Deterministic surface

`CAPABILITIES` in the bridge is the single answer registry: **status, cost, where, search,
remember, forget, halt, undo, organise**. Descriptions state actual audited route limits,
including index/model fallback, deactivation-not-erasure, metadata writes and missing receipts.
`BRIDGE_FACTS` supplies only bridge-owned facts (text-only, RPC vocabulary, absent adapters).
No prompt/model generation assembles these answers and no input fragment is echoed into them.

Input handling order:

1. Existing typed intent shapes/aliases are preserved first and forwarded byte-for-byte under
   the unchanged live-ready checks. This includes legacy mode/queue forms, not new advertised
   entries in the nine-verb registry. No generic keyword scan of remember/search payloads.
2. Optional existing Elaria wake prefix, case and whitespace are normalized **for recognition
   only**, not rewriting a forwarded message. Terminal `?.!` punctuation is ignored here.
3. `capabilities`, `capability NAME`, `help` (and these names with a trailing argument) form
   the explicit catalogue surface. An exact registered name yields its static entry. Anything
   absent/compound/unknown yields the static refusal plus catalogue, never an invented entry.
4. Recognized inquiry prefixes: what/which can/could/do/will you; what are your
   capabilities/abilities/functions; can/could/would/will you; are you able;
   do you support/have access/know how. Only an exact simple registered verb inquiry selects
   one entry; the rest receive refusal/catalogue and no confirmation of prior prose.
5. Recognized unsupported request prefixes (optionally `please`): open/read/analyse/analyze/
   summarise/summarize/inspect/review/load/scan; schedule/reschedule/book;
   send/text/email/message/whatsapp/dm/notify/reply; create/delete/move/rename/copy/
   execute/run/install/launch/browse/download/upload/call. Also check/show/manage/update/
   access/what's/what is requests containing the word calendar. These get static refusals.
6. Other text follows the existing console.say conversational route. It is **not** promoted
   to a registered capability by any model response, including “yes” after an earlier claim.

Matched boundary replies use `provenance=bridge-registry`, deterministic prefix and separate
source metadata. No console.say, model call, fact lookup, journal event or effect is invented.
They do not probe current readiness. The normal authenticated, live-ready hello gate is still
required; this is not an offline-connect bypass. After an accepted hello, a registry response
can remain static when status changes; periodic health monitoring and the uncertainty hold
are unchanged. It is not evidence that a real action would work now.

These replies persist only in the browser display session; because they do not go through
console.say, they do **not** enter the daemon's shared conversation. Ordinary follow-ups still
use the daemon's existing history. No synthetic history injection or new context window.

## Guarantee versus limitation

**Guaranteed on the defined surface:** arbitrary absent `capability NAME` queries and matched
request frames cannot cause generated capability promises, an action rewrite, console.say,
or execution by this branch. Only fixed registry/refusal text is returned. Registry entries
are route descriptions, never permission or “working right now” certification. Existing
canonical commands retain their effects, including typed remember/forget/organise until pilots.

**Not guaranteed:** all paraphrases, all languages, indirect/referential asks, arbitrary text
inside ordinary conversation, future producer drift, or claims in model fallback replies.
For example, an indirect “I wish someone would look through that document” is not covered by
the request grammar; `search` with action-looking words remains the existing indexed search,
which can fall back to model prose. “Read your last sentence” may be over-refused by the
finite request prefix. This is intentional bounded recognition, **not semantic proof**.
Neither keyword frames nor provenance labels make unrestricted prose honest. Achieving that
stronger guarantee needs a separate output contract/ruling, not claims about this filter.

This is a console consumer boundary, not a daemon/executor-wide policy gate. No claim is
made that mainline's scoped-undo repair is deployed. No new file, calendar or messaging-send
adapter exists here. Drafts-before-send remains binding if such a capability is later ruled.

## Evidence anchors

- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/intents.py:25`:
  audited existing typed grammar and aliases; not a capability promise generator.
- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/daemon.py:3582`:
  local handlers and local-memory/model fallthrough semantics behind registry entries.
- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/daemon.py:1167`:
  existing console.say envelope; no new method invented by the consumer.
- `342fdd9449f334ee2479c887b6bc9bdbddef741f:console/bridge.py:193`: prior Task A's provenance metadata, not a model honesty gate.

## Behavioral targets, not proof by examples

| Owner target | Deterministic result | Test limit |
| --- | --- | --- |
| “what can you do?” | Fixed nine-entry registry plus bridge facts | Does not establish runtime readiness |
| “can you confirm you can do those rn?” | No prior prose claim confirmed; same bounded catalogue | Does not import a preceding model promise |
| A fresh-file request (test: “analyse this file /synthetic/test.txt”) | Explicit refusal; no console.say | One request frame, not every possible paraphrase |

Tests also cover every exact entry, unknown/compound names, aliases/wake prefix, calendar and
send requests, immutable typed payload forwarding, and an accepted wire with changed offline
status. Synthetic socket results are not real-backend or owner-hardware proof. Initial offline
hello remains rejected; an early test incorrectly assumed otherwise and was corrected without
loosening the existing gate. No CSS/engine/source build change in Task B; launcher is repinned.

Verification: focused wire/launcher **190 passed, 2 skipped, 18.40s**; full suite
**2589 passed, 8 skipped, 117.19s**; Ruff and diff whitespace checks passed. No owner
backend/model invocation, native browser-window or new geometry acceptance claimed.

Release SHA256 values (check-before-run instructions remain in console/BRIDGE.md):
- `bridge.py`: `79d467a2e82f388663ad7d7ae4f4b0adf51516a7875b6e753a1c714abc3a4127`.
- `run_bridge.py`: `fde8c4160874dc14be07a8c56a79ee2c581ef07bf79b2144b1baf0e0d13904eb`.
- `index.html`: `fe4154f502b918c9cfd0e1e5eb60c0107a339e30b3268e28726c2c68449afad9`.
- `elaria-visualizer.js`: `5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.
