# Console WS1–WS5 research gate — 2026-11-04

**Findings recorded before CSS changes or hands implementation.**
Console baseline: `e448823d93a52651d53c44d6361535081901a106`.
Read-only mainline audit: `a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1`.
Working branch remains `arena/b65d5161-elaria`; no checkout of mainline.

## Accepted evidence / binding scope

Owner-relayed acceptance: eight live replies, two-to-eight seconds apart; all four demo
verification points including the orb accepted on the owner's word. This closes the prior
owner demo gate; it is not a builder-side measurement of that hardware. Provenance is not
proof of a capability or action completion: reply_message also admits explicitly labelled
local-daemon responses, while errors/refusals are not model answers.

Drafts ruling is binding: she composes, he approves; nothing leaves the phone before approval.
No send path before an approve path, no autonomy tier before draft review, and graduation
needs a separate ruling. First messaging work must deliver draft review, not a send adapter.
No messaging implementation, NectarLink, kitty adapters or new hands routes in this audit.
Kitty remains held, scene NOT READY. elaria-console.service is not changed or controlled.

## R1 — commit attribution and flex hypothesis

Compared v6.15 commit `35adbba` against `42a717d`, then `42a717d` against `e448823`:

| File | 42a717d versus v6.15 | e448823 versus 42a717d |
| --- | --- | --- |
| console/src/shell.css | byte-identical | byte-identical |
| console/src/shell.js | 30 inserted / 5 deleted lines: wire bounds, URL/version gates, disconnect/no-replay, reconnect reset, no-stub guard, honest connect text, synthesis comment | byte-identical |
| console/index.html | same 30 inserted / 5 deleted lines in the embedded shell script; CSS/engine unchanged | byte-identical |

Neither commit changed `.stage-box`, canvas geometry, fit, aspect or renderer code.
The normal stage still uses **flex: 1 1 auto; min-height: 0**, with an absolutely positioned
`#stage` inset into it. There is no basis for blaming these commits for a direct change to
that flex rule. The integration DID add an outer iframe plus a three-line header, reducing
the inner viewport height; that is an ancestor geometry change, not a changed stage rule.

**Working hypothesis outcome:** the proposed direct stage-flex regression is rejected by
the byte comparison and wide-viewport containment measurements below. The owner's reported
wide-screen clipping is not reproduced here, so it is not declared nonexistent or fixed.

## R2 — current stage path and reproduced defects

- The shell calls the maker's public create API with **simulate:true, fit:1.8**.
- Engine canvas CSS is display:block; width:100%; height:100%. It is appended to #stage.
- `resize()` reads container clientWidth/clientHeight, calls setPixelRatio and
  setSize(W,H,false), sets camera aspect, and derives distance from
  `FIT_R / (tan(fov/2) * min(1, aspect))`.
- Size scaling uses min(W,H); projection also accounts for aspect. A tall, narrow container
  therefore makes the drawn orb width-limited; unused vertical space is not proof of a
  collapsed or undersized canvas.
- ResizeObserver watches the container; window resize is the fallback. Adaptive pixel-ratio
  behavior is maker code and remains out of scope. Engine SHA is
  `5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.
- `.app` is a 100dvh three-column grid; right rail is fixed at 396px/440px on wide screens.
  440/1920 = 22.9%, explaining the roughly 23% panel. This is v6.15 sizing, superseded by
  the new owner ruling (~36% wide panel, ~80% stage region, bottom lamps).
- Body/orb hide overflow; the transcript log intentionally scrolls. That scroll is not
  evidence that the orb itself is scrolling.
- At <=940px the sidebar becomes fixed-position but its zero-width grid column remains.
  Children have no explicit grid-column assignment: auto-placement moves chat into column
  one and the orb into column two. This is a **reproduced legacy narrow-layout defect**.
- At <=680px the floating stage keeps width:100% AND inset:6px, producing horizontal overflow
  beyond its padded containing box. This is a second **reproduced legacy defect**.

Local measurements: Chromium 153 headless with software rendering, local synthetic status
backend; not owner hardware or model calls. All dimensions below are CSS pixels. Canvas
client size equalled stage size in every run.

| Outer viewport | Inner viewport after banner | Orb client | Stage/canvas client | Orb scroll extent |
| --- | --- | --- | --- | --- |
| 1920×1080 | 1920×1006 | 439×1006 | 439×933 | 439×1006 |
| 1440×900 | 1440×826 | 395×826 | 395×753 | 395×826 |
| 1024×768 | 1024×694 | 267×694 | 267×621 | 267×694 |
| 800×600 | 800×526 | 531×526 | 531×453 | 531×526 |
| 390×844 | 390×713 | 94×94 | 94×82 | **100×94** |

The 800px row's oversized orb column and zero-column chat are auto-placement, not a new
engine defect. The 390px row demonstrates overflow. No outer document overflow was measured
at the five sizes. No exact luminous-orb percentage or owner-wide clipping proof is claimed.
Research metrics are retained locally under ignored `.venv/research-a6/`.

Shell-only fix direction: explicit grid placement; proportional wide rail; definite bounded
grid rows and stage containment; remove the wrapper header; let the orb yield at narrow
widths instead of overlaying/cropping the composer; bottom-pinned status/footer. Keep engine
and fit:1.8 unchanged. Preserve intentional transcript scrolling, not document/orb scrolling.

## R4 / WS5 — what typed hands already reach on a6cc150

Actual mainline positions: console.say **1167**, _ask **3333**, _run_intent **3582**,
_command_gate **1045**. The relay's line 974 names the older branch position of the same
console handler; this audit uses the actual pinned mainline positions.

The fixed dispatch invokes console.say under kernel-authenticated owner IPC. It forwards
text and speak to _ask, which derives the console channel from the registered method.
Show-off mode diverts to guest handling. Otherwise local intent routing runs **before**
model generation. Model output is not parsed back into an action. These are different facts:
there IS a typed action path, but arbitrary model prose is NOT that path.

### (a) Mutations and gates

| Typed intent | Existing effect / gate |
| --- | --- |
| remember / forget | Add stated facts or deactivate matching facts immediately in the daemon store. No fresh approval dialogue here. |
| company-awareness phrases | Change disclosure/company state before generation; no fresh approval dialogue. |
| halt | Existing halt behavior, not a model operation. |
| go offline / online / auto | Change connectivity preference, with existing active-session parking rules. Bridge readiness can then close the wire when offline. |
| drain queue | Calls existing cloud queue drain; can make queued provider calls. Not merely displaying status. |
| organise / sort / tidy | Calls _plan_build({}), across configured roots; the phrase's argument does not narrow roots. Creates plan rows, indexes/reads roots and builds proposals asynchronously. No plan.apply call from this intent. |
| bare undo | Reaches Executor but **refuses**: explicit op/plan/since scope required. |
| undo since <scope> | Reaches journalled Executor.undo. Operation lock, scope, halt checks, content hashes and collision checks apply. There is **no new human approval dialogue** on this route. It can reverse real operations when eligible. |

Plan building writes index/plan records even though it does not move source files. The fixed
“Shadow plan(s)” reply is not proof that every configured root is shadow-mode. Separate
plan.apply/review RPCs exist, but the bridge does not expose arbitrary methods and the text
router has no apply intent. Do not describe the operation lock as owner approval or as the
parked kitty consent machinery.

The voice command gate rejects flagged/low-confidence transcripts. At a6cc150 its
MUTATING_INTENTS tuple contains **undo only**, not every state-mutating intent above; unknown
confidence handling must not be mistaken for a universal mutation policy. console.say does
not invoke this transcription gate. 0.6953 is below 0.85, so a perfect-but-low-scored transcript
can be blocked while typing reaches the same local intent. No threshold change is proposed.

### (b) Existing file/data access

`find`/`where` → Memory.answer_where → indexed document paths. `search` → Memory.recall →
local indexed snippets/facts/transcripts. On a miss both can fall through to model generation;
a generated response after a miss is not a verified file match.

General _ask also incorporates recalled snippets, after disclosure filtering. That can
support discussion of already-indexed content, not proof of reading a current arbitrary
file or its full contents. The index may be stale and snippets are bounded.

Organise can invoke Indexer.index_root on configured roots: actual extraction/hash/indexing
exists, with protected/symlink rules. This is a side-effecting plan/index operation, not a
read-only “open this exact file” API. No calendar/schedule-management intent or general fresh
file reader is established on the audited console route. Text saying “Confirmed” is no receipt.

### (c) Smallest honest next capability — proposal, NOT built

Existing typed `find <query>` already works as index lookup; this is wiring, not a new daemon
feature. For a hard, receipt-backed file-result surface with no model fallback, the smallest
proposal is **one lookup-index verb** wrapping the already-registered `docs.search` RPC in
an additive bridge consumer. Render structured index results, explicit misses, and index
provenance; never claim a fresh file read or analysis. Estimate **2–4 hours** for bounded
request/result validation, a result surface and stub tests, then owner verification.

This would extend the bridge's current two-method allowlist, so it is **held for owner ruling**.
A fresh-file reader is a different capability needing explicit scope, identity/bounds and
privacy review; it is not hidden inside this estimate. Kitty adapters and NectarLink remain
explicitly out of scope.

## R5 — history_limit=1 is response trimming, not prompt amnesia

Bridge.turn sends history_limit=1 to console.say. That handler calls _ask FIRST, then uses
the value only in the returned conversation history. _ask independently fetches eight prior
messages and formats at most the last six after disclosure filtering; its current text is
then appended. Browser-provided history/session are not injected into that context.

Trade-offs/options:

1. **Keep 1**: smallest unused response-history payload; same model context. Current bridge
   discards the history envelope and renders reply text only.
2. **Return 20/40**: useful only if building a daemon-history/reconciliation surface. More
   local IPC data, no automatic increase in model context. Would need a visible consumer.
3. **Change generation's six-message window**: a separate protected daemon change and privacy/
   token-cost decision. Not authorised here and not silently implemented.

The four-message contradiction is therefore **not explained by history_limit=1**. There is
already recent context, subject to disclosure filtering and guest/show-off routing. Neither
context nor a live provider prevents unsupported self-claims.

## WS2 — enforceability boundary and owner decision

The owner questions (“what can you do?”, “can you confirm you can do those rn?”, and a file
request) must be tested against verified capabilities, not another free-form model promise.
A prompt, keyword list, or a “not verified” label cannot make false claims in unrestricted
model prose impossible. Nor does origin=live-model establish an effect or capability.

A hard guarantee requires a constrained capability/action surface: only registered,
evidence-backed results or deterministic refusals are authoritative. Making that guarantee
for **all displayed prose** would require withholding unrestricted model replies or moving
them into a separately accepted draft/untrusted-content experience. That changes the
accepted conversational demo and needs an explicit owner choice; this audit does not
silently disable it or claim a semantic filter is proof.

Decision needed: scope the hard guarantee to a deterministic capability/action surface while
retaining non-authoritative chat, or require a constrained mode with no unrestricted model
assertions displayed. No new hands route follows merely from this choice; WS5 still needs
its own ruling. Acceptance cases remain OPEN until the selected boundary is implemented.

## WS3 / WS4 findings and implementation boundary

The banner's preserved homes: per-reply non-model/error labels; footer for “synthesised text
cadence, not measured audio” and “text-only, no speech”; pane badges for PENDING/SHELL COPY;
shared-daemon-conversation note in BRIDGE.md only. Connection lamps retain wire health.
The existing “driven by real levels” footer is false for text synthesis and must be removed.

Further string/label defects found: status/help copy still says the bridge does not exist;
“typed log never leaves this machine” overstates privacy when submitted messages reach the
configured provider; badgeFor uses transcript OR audio state for both badges; memory badge
is always shell-copy even when fed live cards; empty arrays are truthy and can mark feeds LIVE.
No placeholder feed will be added to manufacture readiness.

--open implementation must use direct argv with the current per-launch URL, app mode,
a distinct private user-data directory per launch and explicit window size. Detach the
browser session and stdin/stdout/stderr; do not wait for window closure and do not kill it
when stopping the bridge. Do not print the token. A private local launch-link file can serve
manual mode without logging the URL. No existing browser profile or service setting changes.
If the existing service owns the port, refuse rather than killing/disabling it.

## Research hygiene

The sandbox again arrived with original-base Git metadata and accepted files. All **297**
accepted files were byte-compared with e448823, no extras, before restoring HEAD/index only.
Mainline a6cc150 was fetched/read without checkout. No protected file or CSS was changed
while preparing these findings. Browser tooling/dependencies are disposable under ignored
.venv; no project dependency or service change. The previously recorded kitty stash object
is not materialised in this refreshed sandbox; no stash was applied, dropped or recreated.
No owner hardware request or new action route was issued.

Research-only verification: Ruff passed. Full local stub suite first produced **2498 passed,
6 skipped, 1 teardown error** in frozen tests/conftest.py (`async_generator_athrow` lacks
`__qualname__`), the previously observed intermittent shared teardown defect. No fixture
was changed. Full rerun: **2498 passed, 6 skipped**, 103.49s. No hardware/live-provider
certification follows from this suite.
