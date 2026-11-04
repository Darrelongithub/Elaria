# Task A — attribution surfacing, 2026-11-04

Estimate given before work: 90–150 minutes, including explicitly missing producer seams.
Owner scope: surface existing console-path attribution, not build a new hands route or
change execution exposure. Each task has its own commit; this commit is Task A only.

## Delivered

Separate, text-safe **Bridge attribution** blocks alongside replies; included in browser-local
session persistence/reload and attached to returned errors where observations are available.
Model text remains unchanged; attribution is not appended to its prose or treated as a model
answer. No feed arrays are invented and no pane badge is promoted by this feature.

- Per-launch/counter bridge observation reference, explicitly **not a durable journal receipt**.
- Actual admitted reply provenance (`local-daemon`, `live-model`, original `via`). Model prose
  is explicitly not capability confirmation, approval or an effect receipt.
- Advisory input shape from the audited intent vocabulary, including existing aliases and
  mode/queue shapes. It **never dispatches** or establishes the daemon's executed intent.
  Unknown shapes still receive provenance/gap reporting, rather than vanishing.
- Actual returned conversation reference when present. A matching returned tail message ID
  is labelled **not request-bound**: another caller can append history after `_ask` returns.
  Mismatch/absence yields no inferred message attribution. No unrelated history text is shown.
- findwhere/search: `local-memory` reply versus model fallback; bounded matching local hit
  lines labelled **daemon-reported, unstructured**, not fresh-file access or structured refs.
  Unparseable/bounded-out variants visibly lack structured refs; their admitted reply remains.
- remember: fact ID/kind explicitly unavailable. Retention disclosure: deactivation is not
  erasure; text/history may remain; no duration or exact restore guarantee is on the wire.
- forget: exact digit-string count from the admitted local producer's bounded reply format;
  explicitly daemon-reported, not independently verified; **deactivation-not-erasure**.
- organise: plan references from the admitted local reply where formatted as audited;
  resolved roots explicitly unavailable. Audited semantics disclose configured-root reads
  and index/chunk/status, plan/item, shadow-log writes, **not a completed-write receipt**.
- No semantic effect details are extracted from model, fixture, withheld or rejected replies.
  A failure/withheld reply is not proof that no mutation occurred. No automatic replay.

## Mainline seam requests — not implemented or invented

| Missing evidence | Minimum producer seam requested | Current surface |
| --- | --- | --- |
| Actual executed intent and request correlation | Request-bound canonical intent/outcome, with correlation carried from authenticated dispatch through reply | Advisory input shape + actual reply via; never “executed” inferred from grammar |
| Operation journal attribution | Structured operation/journal references, explicit no-operation/refused state where applicable, tied to the request | “Operation journal reference not supplied”; a bridge ID/conversation ID is not a substitute |
| Causal message reference | Message ID from this turn's append, not a post-turn history sample | Matching returned tail labelled noncausal; mismatches suppressed |
| Indexed hits | Structured source/ref/index timestamp or revision and local hit/miss/fallback outcome | Bounded local reply hit text labelled unstructured; no freshness claim |
| Remember result | Fact ID, kind, resulting state and retention/restore semantics from the actual service result | ID/kind unavailable; no guessing by listing matching facts |
| Forget result | Structured exact count, affected IDs/versions/state and operation/decision correlation for the later pilot | Count only from matching local prose; affected IDs not invented |
| Organise result | Resolved root set, started plan IDs, write kinds and separate completed/failed build receipts | Root set unavailable; reported plan IDs and labelled audited semantics only |

No additional memory/plan/docs RPC was added to reconstruct these fields. Such queries would
not prove attribution and could expose unrelated data. Mainline owns producer changes; no
protected-file grant is assumed by this consumer work. The literal “every intent with its
journal reference” is therefore **surface-complete but evidence-limited**, not a claim that
missing journal records now exist. No caller-supplied future receipt schema is trusted here.

## Source evidence (SHA:file:line)

- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/daemon.py:1167`:
  console.say returns `_ask` plus a post-turn history sample.
- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/daemon.py:3565`:
  reply envelope has via/conversation ID, not executed-intent or effect IDs.
- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/daemon.py:3582`:
  local intent formatting discards remember's service ID and exposes only prose for others.
- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/console.py:51`:
  history entries contain IDs but are a separately sampled conversation tail.
- `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/intents.py:25`:
  mirrored grammar is used only as an advisory bridge observer, never a second dispatcher.

## Holds and evidence

305 accepted baseline files were byte-checked before repairing refreshed Git metadata to
c327df7; source work stayed on arena/b65d5161-elaria. No mainline checkout/merge, daemon,
protected source, shared-fixture, history_limit, service, engine or kitty change. No new
approval/execution path; typed reads/memory/organise continue unchanged. Mainline's scoped
undo gate is owner-ruled, not implemented or deployment-certified by this branch.

Tests cover local-vs-model/fixture distinction, exact count, unavailable roots/fact fields,
uncorrelated history, a real fixture-backed local remember result, and DOM separation,
injection safety and persistence. These are local stub/renderer tests, not owner hardware
or live backend verification. Build's absolute engine/GLSL/JS gates remain mandatory.

Verification: focused wire/launcher **135 passed, 2 skipped**; full suite first run
**2534 passed, 8 skipped, 1 teardown error** at the previously observed
`tests/conftest.py:91` (`async_generator_athrow.__qualname__`); unmodified rerun
**2534 passed, 8 skipped, 116.54s**. Shared fixture untouched. Ruff passed;
smoke **114/0**, sessions **23/0**; DOM safety/persistence/error checks also passed.
Browser native-window, owner-size clipping and real-backend acceptance were not run.

Release bytes: bridge `265a351afd8e0dfb5452d33b6e7ce974522d6a992722782ddc52f8d1472cb2f3`;
index `fe4154f502b918c9cfd0e1e5eb60c0107a339e30b3268e28726c2c68449afad9`;
launcher `30adee34237ccfffc99f1926c68927c9400ebf9517366de786ccc2277b7acc8a`.
Engine unchanged `5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.

Housekeeping: owner reports interim **Win+Space WORKS on hardware (2026-11-04)**;
optional repository wrapper skipped; no keybind or service change.
