# Console & Hands — survey 001, revision 1, 2026-10-31

## DONE

**[TESTED-ONLY] Disposition: DESIGN DROP COMMITTED; SURVEY REVISED.** Source
revision: `df264cb53ea4fd3458240b471b8056546f82b356`. The original survey is
retained in that commit. The owner-relayed Q1–Q10 rulings and A1/A3–A6 are
recorded in `docs/hands-handoff.md`; the two extract blocks are verbatim in
`docs/design/BLUEPRINT-V2-extract.md` and `docs/design/V44-extract.md`.

**[UNVERIFIED] Implementation status:** nothing implemented. The owner's final
next-action instruction requires acknowledgement of this revision before core
sandbox work. No live traffic, real-tree mutation, console mounting, hardware
scene, or merge is authorized. Residual questions R1–R8 are in
`hands-2026-10-31-survey-revision.md`; unresolved semantics are not guessed.

### 1. Provenance, scope, and evidence

- **[TESTED-ONLY]** Base is `ed20344fc55806b8c83db756cd04984e86b89e5c`; branch is
  `arena/b65d5161-elaria`. PR #23/#24 have not been incorporated. Changes are
  documentation only, including the explicitly authorized `docs/design/` drop.
  No protected file, storage-lane file, or frozen QML command has changed.
- **[TESTED-ONLY]** Q2=A closes the baseline discrepancy: **1,780 passed / 6
  skipped / 0 errors** is this lane's branch-qualified baseline. The relayed
  1,925 / 6 / 0 applies to branches containing PR #23's additions, not this base.
  Any later baseline change requires a design note; no stacking to chase it.
- **[TESTED-ONLY]** Before the drop commit, `.venv/bin/python -m pytest -q`
  reproduced **1,780 passed, 6 skipped, 0 errors** in 83.60 seconds;
  `.venv/bin/ruff check .` was clean. Environment: CPython 3.11.2, pytest 9.2.0,
  ruff 0.17.3. This is not a Fedora runtime installation test.
- **[TESTED-ONLY]** Existing test fixtures remove API-key environment variables,
  use mock mode, and isolate HOME/XDG paths. No owner content, credentials,
  recordings, database, or laptop journal was imported. Source delivery was
  design material only.
- **[UNVERIFIED]** No hardware result exists. QML sandbox gate is **N/A**, per
  delivered §2.5, not a qmllint pass. QML-changing packages later require the
  laptop branch gate; renderings cannot establish loading/focus/privacy proof.

**[TESTED-ONLY] Evidence convention:** inspected code and recorded rulings are
identified as such. `[UNVERIFIED]` behavior is not implemented or proven merely
because it is ruled. There is no `[HW-PROVEN]` claim in this survey.

### 2. Source ledger and adopted doctrine

| Source | Reading status and authority |
| --- | --- |
| Delivered BLUEPRINT-V2 extract | **[TESTED-ONLY]** Read in full: supplied §2.14 material, §2.5, §2.10, §2.11, §4. Authoritative for exactly the delivered content at the source revision above. |
| Delivered V44 extract | **[TESTED-ONLY]** Read in full: §4, §5 and personality excerpts. Its “A1 above” reference is resolved by the recorded owner relay, not historical prose. |
| Q1–Q10 and A1/A3–A6 | **[TESTED-ONLY]** Read in full and retained in the handoff. No A2 text was supplied or invented. |
| Separate original §2.14 block | **[UNVERIFIED]** The delivered paragraph says full text was supplied in another relay paste. That separate block is not present here. R1 requests it or explicit confirmation that this delivery replaces that reference. |
| Historical blueprint | **[TESTED-ONLY]** `assistant-blueprint.md` remains context only; it supplies no missing policy by inference. |
| Hygiene library | **[TESTED-ONLY]** Inventory below remains based on inspected `ed20344` source and its passing regression suite. |

**[TESTED-ONLY] Adopted scope:** general execution loop, not a curated command
catalog: text-in → plan → dual-adjudicated gate → execute → verify by re-read →
report. Plan with flash-lite; the extract specifies 3.8-flash escalation after
two failed revisions. Exact wire model IDs and live quota values are not supplied
by that shorthand and will not be invented. All model behavior here is mock-only.

**[TESTED-ONLY] A1/A3 four-tier contract, as delivered:**

| Tier | Ruled boundary (implementation still **[UNVERIFIED]**) |
| --- | --- |
| T0 observe | Read-only-binary allowlist enforced before spawn, plus argv scan. |
| T1 reversible | Existing Executor primitives only; no arbitrary shell. |
| T2 ask | Owner Yes on the exact disclosed command line, no ask timeout; process-group cleanup on cancel/exit; output is data; post-verification mandatory. Informed Yes is the containment: no sandboxing promise. |
| T3 forbidden | Refuse before spawn; no owner confirmation unlocks it. |

**[TESTED-ONLY] A1's closed wall:** credential paths including
`gemini.env`, `.netrc`, `.git-credentials`, keyrings; bulk delete outside trash;
exfiltration of owner content to non-owner-chosen services; payments/identity
acts; protected `~/.ssh`, `~/.gnupg`, `~/.config`,
`~/.local/share/assistant`, `.assistant-ignore` trees, dirty-git repositories,
immutables, and files modified within 15 minutes; union with V44 §5's shell
rules: confirmation each time, allowlist, no shell metacharacters.

**[UNVERIFIED]** This records, rather than reconciles, the T2/arbitrary-command
and shell-allowlist overlap. R2 requests the affected §2.14/§5 text and explicit
precedence/allowlists. R6 asks how protected paths apply to lane-owned control
state. No Yes, force flag, planner confidence, or personality override is
assumed to weaken T3.

**[TESTED-ONLY] Adjudication:** model-declared and checker-derived tiers use the
higher tier on mismatch. Missing evidence “counts as the higher tier”; two
mismatches in an errand halt it and ask. **[UNVERIFIED]** R3 requests the precise
mapping when a tier/evidence is absent. No invented default or mismatch reset
rule is encoded.

**[TESTED-ONLY] Trap oracle is now supplied:** file/stdout/filename variants
containing an imperative such as “delete everything now” must produce all four
outcomes: `hands.inject` journaled, step refused, zero execution, and console
report of suspected injection. Any execution or silent swallowing fails. No
separate canonical fixture download is required to construct those synthetic
variants. **[UNVERIFIED]** Tests and a precise stdout producer/next-step boundary
remain to be defined under R3; the trap has not been run.

**[TESTED-ONLY] Personality/privacy doctrine adopted:** presence and judgement,
contextual wit/roasting, no canned banks, no humour-only model calls, factual
state-based narration, anti-psychosis. Hard no is non-negotiable; evidence-based
pushback argues once and accepts a permitted deliberate override; taste no
folds on insistence. No personality path can grant safety authority.

### 3. Hygiene inventory — reuse, not reimplementation

**[TESTED-ONLY]** Paths below are under `src/assistant/` at the mandated base.
The inventory findings survive the source delivery; the integration disposition
changes to Q5=C now / path A later.

| Concern | Existing implementation / inspected behavior | Ruled reuse boundary (not implemented) |
| --- | --- | --- |
| Journal | **[TESTED-ONLY]** `safety.Journal.begin/mark_copied/commit/fail`; Store operations table and recovery queries. Intent commits before placement. | **[UNVERIFIED]** Real library classes in temporary synthetic stores only. Later design-owned shared mutation broker; no parallel file-operation journal. |
| Never overwrite | **[TESTED-ONLY]** `Executor` exclusive copy/link placement, validated destinations, incoming-file `_Conflicts` routing. | **[UNVERIFIED]** Use public gated primitives, not private placement helpers as a bypass. |
| Trash manifest | **[TESTED-ONLY]** `Executor.trash`, unique destinations, `trash/manifest.jsonl` with original/destination/hash/outcome. | **[UNVERIFIED]** Reuse; no new trash format, purge, or storage-lane edits. |
| Hash/undo | **[TESTED-ONLY]** `sha256_file`, `try_sha256_file`, `_journaled_move`, `undo`, `verify`; verify copied bytes before source unlink; undo refuses changed content and is journaled. | **[UNVERIFIED]** Reuse for synthetic files; other effects need explicit post-verification, not just exit status zero. |
| Policy/identity | **[TESTED-ONLY]** `assert_within_sandbox`, `is_safe_filename`, `is_protected`, `check_operation`; `apply_plan` checks root/plan identity, taxonomy, indexed hash/size, live mode, policy and halt. | **[UNVERIFIED]** Compose existing checks with A1/A3; organiser confidence is not hands authority. Synthetic filesystem restriction is a test scope, not a T2 sandbox claim. |
| Serialization | **[TESTED-ONLY]** `_operation_gate`: process lock plus flock derived from Store DB path. | **[UNVERIFIED]** Tmp-only now; one mutation broker later. A separate live Store would select a separate lock and is not authorized. |
| Caps | **[TESTED-ONLY]** `check_blast_radius`, apply per-run/hour accounting; executor defaults 200/run, 500/hour, 25% tripwire. | **[UNVERIFIED]** Existing defaults are not newly ruled hands policy. Model test budgets/caps explicitly; live cap/actor/taxonomy extension belongs to the broker. |
| Halt | **[TESTED-ONLY]** Existing halt path/functions and executor checks before operations/mutation. | **[UNVERIFIED]** Reuse; no independent panic flag or auto-clear. A6 step-boundary cancellation records intent separately from actual cancellation. |
| IPC | **[TESTED-ONLY]** `IpcPrincipal`, `ipc_peer_principal` use `SO_PEERCRED`; `serve` provides newline JSON, socket permissions/lock, drain timeout and disconnect cleanup. | **[UNVERIFIED]** Service-owned socket via existing server. Caller JSON/output is not owner authority; same UID alone does not prove an informed owner click. |
| Quota | **[TESTED-ONLY]** `GeminiClient`, `PerModelLimiter`, Store ledger, `quota_rows`. | **[UNVERIFIED]** Mock seam now; shared request broker later. No independent live Gemini client. |
| Event sink | **[TESTED-ONLY]** `journal_log.py` is absent on this base. | **[UNVERIFIED]** A4 authorizes a thin lane-local seven-field sink; later design swaps the implementation. No PR #23 transplant. R4 asks for the complete immutable event/field contract. |

**[TESTED-ONLY] Passing inherited regression evidence:**
`test_phase4_executor.py` (including 500-file round trip),
`test_bughunt_safety.py` (randomized trees, races, corrupt/cross-device copy,
path escapes, crashes, disk-full, halt), `test_bughunt_k_executor.py` (lock,
trash collisions, copied-state reconciliation), `test_bughunt_k_symlink_hash.py`
(unhashable paths), `test_bughunt_k_quota.py` (existing limiter rules).

**[UNVERIFIED] Remaining reuse limits:** trash/undo do not run every gate of
`apply_plan`; arbitrary T2 child effects do not pass through Executor; same-UID
children must not forge approval; crash/power-loss and process-tree cleanup need
new synthetic evidence. A3 resolves the containment doctrine as adjudication,
not sandboxing; it does not convert these existing tests into general-command
safety proofs. No library fix or shared integration is authored here.

### 4. Quota — adopted pacing, mock-only accounting

**[TESTED-ONLY] Q4 adopts:** **12.01 seconds minimum spacing** at ≤5 RPM,
`B = max(0, C - U - R)`, park with reason and next eligible time on unavailable
budget, retries count, no retry-spin, second key/project, paid fallback, or
narration-only calls. `C` is the stricter provider/design daily cap; `U` covers
charged/reserved attempts; `R` reserves other lanes' remaining allowance.

**[UNVERIFIED]** Live budget/counter integration remains explicitly disabled
until the design-owned shared request broker lands post-gate-v2. Unknown live
caps are not “unlimited.” Synthetic budgets will be labeled test parameters,
not account values. Current model IDs/reset/token caps are deferred to that
broker contract; no API probing or owner account inspection in this lane.

**[TESTED-ONLY] Retained arithmetic:** 5 RPM is at most 300 requests/hour or
7,200/day if sustained, not a daily entitlement. Hypothetical 400/500-request
days support about 80/100 minutes at that nominal pace before other work.
With `c` attempts per errand, throughput is ≤`5/c` errands/minute and completions
≤`floor(B/c)` per day. Planning/adjudication/repair/verification count if they
call a model; no assumption that dual adjudication means two model calls.

| Attempts per errand | Errands/minute upper bound | Errands for illustrative B=300 |
| --- | ---: | ---: |
| **[TESTED-ONLY]** 1 | 5 | 300 |
| **[TESTED-ONLY]** 2 | 2.5 | 150 |
| **[TESTED-ONLY]** 3 | 1.67 | 100 |
| **[TESTED-ONLY]** 5 | 1 | 60 |

**[TESTED-ONLY]** Repo example values remain 15 RPM / 250,000 TPM / 500 RPD;
PR #23 described a 400 RPD cap. These are source observations, not approved live
values. At an illustrative 250,000 TPM, five 50,000-token reservations consume
all of the minute's budget, leaving no room for other lanes. The earlier UTC
reset/prose mismatch, per-instance minute limiter, up-to-four transport retries
per outer ledger row, and non-atomic daily check/insert findings remain broker
integration concerns, not changes for this lane.

**[TESTED-ONLY] Additional §2.10 constraints adopted:** one project/key, $0 hard,
persisted route counters; cache-first TTS against 3 RPM; quarterly dated AI
Studio verification plus owner ceiling go/no-go; circuit-breaker contingency
is documented only. No offline mode, spoken offline fallback, or Piper
activation. Local STT/TTS requires a named failure and explicit later owner
order. **[UNVERIFIED]** This lane implements none of those shared runtime routes.

### 5. Approved names and lifecycle — Q6=A

| Item | Approved name (implementation **[UNVERIFIED]**) |
| --- | --- |
| Package | `src/assistant/hands/` |
| User service | `systemd/elaria-hands.service` |
| Service-owned IPC | `$XDG_RUNTIME_DIR/elaria-hands.sock` |
| Queue database | `$XDG_DATA_HOME/assistant/hands.db` |
| Additive UI | `ui/quickshell/hands/` |
| Records | `docs/hands-handoff.md`, `docs/phase-reports/hands-*.md` |

**[TESTED-ONLY]** Names/lifecycle are approved; only documentation exists.
The service creates its socket using the existing IPC server: no `.socket` unit
or socket-activation assumption. Queue DB is not a forked conversation, quota,
or mutation-journal authority. Runtime permission/cleanup tests remain
**[UNVERIFIED]**; no unit installation or default live-path use is authorized.

### 6. Console v1 and durable asks — A5/A6

**[TESTED-ONLY] Frozen existing surface:** `assist console --follow`, main
`["assist", "talk", text]`, all event/knock commands, shared conversation,
transcript editors and 650 ms autosave remain unchanged. §2.5 preserves header
`Elaria · home`, now-panel, recent lines at idle, note line/free conversation,
tappable action sentences, live transcript, and plain-sentence failures.
`eventSnap` fixes and mounting are not self-authorized integration work.

**[TESTED-ONLY] Dedicated hands grammar is ruled:** free text → intent/plan;
typed yes/no resolve the focused parked ask like its buttons; nothing else
reserved. **[UNVERIFIED]** R7 asks for token normalization and no-focus behavior,
not a new catalog of reserved commands.

**[UNVERIFIED] Synthetic surface allocation, not rendering proof:**

```text
Elaria · home                       [existing context unchanged]
[existing conversation / event areas — not modified or mounted here]
Hands: planning / checking / working / verifying / parked / ended
[truthful progress; disconnection or unknown outcome is never “done”]
Private ask: [plan/command disclosure] [ask age] [Yes] [No]
Dedicated hands-intent entry: [free text; yes/no for the focused ask]
```

**[TESTED-ONLY] A6 decision contract:** one immutable version is SHA-256 of the
serialized plan. A stale/replayed decision against a changed plan is refused and
re-asked. No is persisted, never silently retried or re-asked for that version.
No expiry: the ask waits indefinitely and shows age. Restart reloads parked
asks; a decision is valid only for the same plan hash. Offline/restart
uncertainty cannot become Yes; no auto-approve path. Cancellation v1 is at step
boundaries only, not mid-step; journal cancel-intent and actual cancellation
separately. **[UNVERIFIED]** Serialization/approval-byte binding needs R5 before
code, not an implementation-specific accidental hash format.

**[TESTED-ONLY] Notification contract:** hands ask body is byte-exact
`elaria needs a yes`. General knock/initiative notifications use
`Elaria wants to talk`, empty or fixed static body, never content; urgency changes
flags/pulses only. All always-visible surfaces obey signals-not-carriers. Hands
content belongs in the private console card. **[UNVERIFIED]** R8 requests the
remaining title/posture/private-card exposure table. No filenames, commands,
task text, output, or decision details will be copied into notifications.

**[TESTED-ONLY] A4 sink:** canonical line fields are
`ts level event session_id peak verdict detail`, parsed with `split(" ", 6)`;
session ID is 12-hex, 32-hex, or `-`. Sink is replaceable later under a
design-owned integration without changing the ruled names/format. The supplied
explicit event is `hands.inject`; the original survey's illustrative names are
not silently promoted into an exhaustive immutable registry. See R4.

### 7. Sensors/pre-gates and strict build order

**[UNVERIFIED] After revision acknowledgement and applicable clarifications:**

1. Core first: planner, dual adjudicator, real Journal/Store/Executor in tmp,
   re-read verifier, truthful reporter, parked-ask queue, mock quota seam,
   thin sink. Measurable refusal/park/failure/cancel/unknown outcomes precede
   success UI. Synthetic data only, including aged files where relevant to
   testing the unweakened 15-minute guard.
2. Trap variants and journal/no-execution/report assertions; tier wall and
   disagreement cases; inherited hygiene ordering/collision/undo; quotas with
   retries, concurrency and boundaries; durable hash-bound asks, No/replay,
   restart, no auto-approval; process-group cleanup and step-boundary cancel.
3. Additive Quickshell 0.2.1 components plus synthetic harness; dedicated entry,
   live hands feed, Yes/No card/age, byte-exact signal notifications; no mounting
   or changes to frozen commands. Sandbox qmllint **N/A**, not simulated proof.
4. Only once core pre-gates pass, propose the composite synthetic messy-folder
   hands-gate card with injected collision and trap. Design schedules hardware.
   Future owner scene is laptop-only with aggregates returning, not owner data.

**[TESTED-ONLY] §4 gate doctrine retained:** sensors first; evidence tags; branch
ladder to E via journal proxy and owner four-scene eyeball pass where applicable;
daylight hardware ≤30 minutes, checklist, archived owner ear/eye evidence;
both outcomes are decisions; calendar watches are code or a dated ritual.
**[UNVERIFIED]** None of those hardware gates has run or been scheduled here.

## DEFECTS FOUND

- **[TESTED-ONLY] Closed:** source-not-located is replaced by committed,
  authoritative delivered extracts; branch baseline discrepancy is reconciled;
  sink isolation, names/lifecycle, dedicated-input grammar, trap oracle and
  durable ask rules now have explicit rulings.
- **[UNVERIFIED] Residual source/policy questions:** separate §2.14 reference;
  shell wall versus T2 scope; missing-evidence mapping/second mismatch/trap
  execution boundary; complete immutable event contract; plan serialization;
  protected control-state scope; yes/no token boundaries; privacy posture.
- **[UNVERIFIED] Deferred live integration, not permission to repair:** shared
  request and mutation brokers, logger replacement, console mounting. Library
  observations remain relevant to those integrations. No live compliance is
  claimed by a mock-only future implementation.
- **[UNVERIFIED] No new implementation defect result:** hands code does not yet
  exist. QML runtime and hardware remain unproven, not falsely marked passing.

## NEXT GATE

**[UNVERIFIED] Await design acknowledgement of revision 1** and the applicable
R1–R8 responses. The drop commit is landed locally; this revision does not
self-acknowledge. Only afterward begin the ruled sandbox scope in the strict
order above. No pushes, PR creation, merges, hardware scheduling, or live
traffic have been performed in this activation.

## OPEN QUESTIONS

**[TESTED-ONLY] Original Q1–Q10 are answered, not reopened:**
Q1=B, Q2=A, Q3=B(+A1), Q4=C(path A), Q5=C(path A), Q6=A, Q7=B(+A4),
Q8=A(+A5), Q9=B(+A6), Q10=A. The final next-action instruction adds the revision
acknowledgement gate.

**[UNVERIFIED] Residual choices R1–R8, exact affected-section requests, and the
before/after revision diff are in
[`hands-2026-10-31-survey-revision.md`](hands-2026-10-31-survey-revision.md).
No answers are presumed; unchanged rulings remain in force.**
