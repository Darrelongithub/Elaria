# Console & Hands — partial-authorization increment 001, 2026-10-31

## DONE

- **[TESTED-ONLY]** Revision 1 acknowledgement is recorded. The verbatim §2.14
  addendum is committed at **`d530ea2419a8402d3c8d47c5e922dd85c9a4dbcd`**.
  The prior summary remains unchanged; the dated addendum preserves the supplied
  literal `&amp;amp;` spelling and Markdown. Read the full delivered addendum and
  residual rulings before writing this partial increment.
- **[TESTED-ONLY]** Before that documentation commit: **1,780 passed / 6 skipped /
  0 errors**, 85.97 seconds; ruff clean. This is the branch-qualified baseline,
  not the 1,925-count baseline from PR #23-derived branches.
- **[TESTED-ONLY]** Added only the partially authorized package scaffold/thin
  sink, standalone synthetic console assets, synthetic fixture inventory and
  tests. No executor, planner, adjudicator, verifier, queue DB, service, socket,
  event registry, live client, console mounting or voice pane was implemented.
- **[TESTED-ONLY]** Next-report R1–R8 choice text is reproduced verbatim below,
  copied from the revision report rather than paraphrased. A regression test
  compares the reproduced block directly. New resolutions are recorded outside
  that historical block to avoid another lossy relay.

### Partial-auth increment and limits

| Deliverable | Increment | Evidence boundary |
| --- | --- | --- |
| `src/assistant/hands/sink.py` | Seven-field explicit-stream thin sink; caller-supplied names/header; path/hash/count detail; local written/drop sensors; no retries/fallback | **[TESTED-ONLY]** 59 sink tests pass. No registry, policy verdict or durable operation-journal receipt. |
| `ui/quickshell/hands/harness.js` | Pure snapshots and UI helpers, no backend | **[TESTED-ONLY]** 24 console tests pass (node logic plus static asset checks); samples are not measured execution. |
| `ui/quickshell/hands/shell.qml` | Quickshell 0.2.1-targeted standalone synthetic window, dedicated entry, feed samples, inert Yes/No preview, ask age | **[UNVERIFIED]** Runtime/load/focus/appearance not tested; sandbox qmllint N/A. |
| `fixtures/hands/` | Eight synthetic files, six trap origins, incoming/occupied same-basename collision, hashed inventory | **[TESTED-ONLY]** Inventory/hash/origin checks pass; not a passed injection/Executor gate. |
| `tests/test_hands_partial_*.py` | Framing, inertness, failure counters, UI JS behavior, static bridge/plain-text checks, inventory and relay fidelity | **[TESTED-ONLY]** 93 added tests pass. **[UNVERIFIED]** End-to-end task, persistence and hardware remain unproven. |

**[TESTED-ONLY] Intended scope of the new scaffold:**

- The sink writes only to an explicit stream. No imports of shared PR #23
  logging code, no startup logging or filesystem creation, no action callbacks.
  Malformed fields and ordinary I/O errors return false with a local drop count;
  they do not approve, refuse or run anything. Failed output may be partial;
  no exactly-once/durability claim is made.
- Detail has no raw text/command/output argument. Paths, hashes and counts use
  compact ASCII JSON as a documented lane-local encoding, not a newly ruled
  canonical detail or plan schema. Trusted metadata can itself carry text:
  identifiers/paths are not automatically proven private. Registry semantics
  and shared schema integration remain held.
- Preview input is preserved as text, never interpreted, including typed yes/no.
  Buttons show a local click receipt but save no decision. This avoids choosing
  unresolved lexical, hash or queue semantics behind the guise of a harness.
- The notification is only an in-console preview value, never desktop dispatch.
  Its body is fixed; locked fixture posture returns no notification and hides
  private fixture details. Unknown posture is also redacted in the synthetic
  renderer. No actual session-lock detection or production privacy claim.
- Fixture data includes file, stdout, stderr, filename, retrieved-markup and
  tool-output imperatives. No output-producer process or detector runs. The
  sample injection view is explicitly an oracle preview, not a detector result.
- Existing hygiene is not reimplemented: fixture hashes and boundary checks
  reuse `assistant.safety` helpers. Mutation/operation-journal code is untouched.

### Validation record

- **[TESTED-ONLY]** Targeted partial suite: **93 passed**, 1.27 seconds at first
  run; three initial lint findings were corrected before full-suite validation.
- **[TESTED-ONLY]** Full suite before the partial-increment commit: **1,873 passed /
  6 skipped / 0 errors**, 85.87 seconds. This is 1,780 baseline + 93 additions,
  not a change to the baseline provenance ruling. No existing test was edited.
- **[TESTED-ONLY]** `ruff check .`: all checks passed. `git diff --check`: clean.
- **[TESTED-ONLY]** Protected existing files and frozen QML assets were compared
  byte-for-byte with `ed20344`; unchanged. Absent protected `ladder.py` and
  `HANDOFF.md` were not created. No storage or dependency-manifest changes.
- **[TESTED-ONLY]** The test suite compares the entire R1–R8 block below with
  the revision report, including every choice. No paraphrase in the relay copy.
- **[UNVERIFIED]** Quickshell/Qt runtime unavailable; qmllint sandbox **N/A**.
  No renderer, focus, session-lock, desktop notification, trap-oracle or
  hands-gate acceptance claim. No hardware session is requested.

## DEFECTS FOUND

- **[TESTED-ONLY] Relay corruption-class:** design explicitly acknowledged that
  the earlier full-text-delivery claim was false. Verbatim §2.14 is now delivered
  and committed; R1's historical wording below is retained only because design
  explicitly requested verbatim re-emission, not because the delivery is denied.
- **[UNVERIFIED] No core acceptance result:** composing independently tested
  metadata framing, a hostile fixture and an injection-screen sample cannot
  establish the four-part trap oracle. The executor core is held.
- **[UNVERIFIED] No QML/runtime proof:** structural checks and node tests cannot
  establish Quickshell loading, layout, focus, lock integration or owner approval.
- **[UNVERIFIED] Some residual details remain:** no T0 binary/argv list, numeric
  mapping for absent adjudication, canonical plan serialization or private-state
  target exception is inferred. The revised doctrinal statements are retained
  without inventing executable defaults. Held code is not written around them.

## NEXT GATE

**[UNVERIFIED] Design review of this partial increment and the verbatim R1–R8
choices below.** Executor core, parked-queue semantics beyond A6, and
registry implementation remain held. No hardware scene card is issued now:
core pre-gates are not green because core is not authorized/implemented.
No live model/mutation, unit installation, mounting, hardware, push or merge.

## OPEN QUESTIONS

### Current ruling annotations — outside the verbatim relay block

**[TESTED-ONLY]** The following records the latest owner relay; it does not alter
any choices reproduced below or imply implementation authority beyond the
partial scope.

- R1: original full §2.14 is now supplied; prior false delivery claim corrected.
- R2: §5 confirmation is T2 exact-command Yes; allowlist applies to T0 auto-reads
  only; metacharacters forbidden at every tier; T1 uses Executor primitives.
  T0 binary/argv entries are not supplied, and no gate checker is implemented.
- R3: missing evidence = higher tier is restated; plan-time AND immediate
  pre-exec adjudication are required. Data cannot change/add steps without full
  re-adjudication and fresh Yes for a new T2 step. Trap oracle is unchanged;
  its end-to-end result is not claimed by fixture inventory.
- R4: §2.14 now names plan/step/gate/ask/yes/no/exec/verify/report/inject under
  `hands.*`; registry implementation is explicitly held. Thin sink work only.
- R5/R6/R7: no additional serialization, state-boundary or lexical choice is
  presumed. Preview capture does not settle them.
- R8: body fixed, card content console-only, urgency/class variants flags/pulses
  only, locked session suppresses notification entirely. This harness dispatches
  no notification and claims no integration with real posture.

### Verbatim re-emission of R1–R8 and their choices

**[TESTED-ONLY] Archival relay copy starts below.** Its historical claims and
options are unmodified, including matters newly resolved above. Do not treat
this quotation as overriding the latest owner ruling.

### R1 — §2.14 cross-reference and read-before-code completion

**[TESTED-ONLY]** The extract literally says “full text supplied in the owner's
relay paste of the 2026-10-31 §2.14 block,” but no separate block was delivered
in this conversation.

- **A:** deliver the referenced complete §2.14 block, including the scope,
  gate/event definitions and scene criteria it contains.
- **B:** explicitly rule that the delivered extract plus recorded addenda is
  the complete lane authority and supersedes that external/full-block reference
  and the requirement to read a separate block; clarify residual rules below.
- **C:** hold implementation until the full block is available.

### R2 — affected §2.14 / V44 §5: arbitrary T2 versus shell wall

**[UNVERIFIED]** Which scope applies? Please re-deliver the affected clauses and
T0 binary/argv policy, rather than leaving this lane to invent allowlist entries.

- **A:** V44 §5 applies across tiers; violations are T3 even after Yes. Specify
  the allowlist mechanism for general T2 commands and the T0 binary/argv rules;
  clarify how T0 read-only spawning relates to “confirm each time.”
- **B:** supply a dated replacement clause defining explicit T0/T2 exceptions to
  §5 and the remaining T3 shell prohibitions, plus T0 binary/argv rules.
- **C:** authorize no subprocess implementation yet; after revision approval,
  exercise tier decisions with fake runners until design supplies the rules.

### R3 — affected A1/§2.14: unknown evidence and trap step boundary

**[UNVERIFIED]** “Higher tier” is defined for two known tiers, but not when one
is missing. Please specify missing-one, missing-both, invalid-tier/evidence,
mismatch counting, and the second-mismatch transition without permitting a
T3-unlocking ask. A separate stdout producer can have already run before its
output reveals an injection; “zero execution” needs an explicit trace boundary.

- **A:** missing evidence maps to T3, with design supplying the exact mismatch
  count/halt transition table; zero execution means no trap-directed or
  downstream action after detection (prior observation remains in the trace).
- **B:** supply a different explicit tier/mismatch table and trap trace oracle,
  including whether stdout is pre-injected before any runner invocation.
- **C:** hold these checker/trap transitions; do not fill them with guessed
  tier defaults or call a narrower stdout test the complete oracle.

### R4 — affected A4/§2.14: immutable journal contract

**[TESTED-ONLY]** Seven field names, split rule and session-ID lengths are
supplied. `hands.inject` is explicit. The old survey offered illustrative
`hands.plan`, `hands.gate`, `hands.parked`, `hands.verify`, `hands.report`, not an
exhaustive lifecycle/event registry. Storage report 007 §2 was referenced but
not delivered/read here; no storage branch is imported to acquire it.

- **A:** relay report 007 §2 plus the complete immutable `hands.*` event and
  verdict registry, including cancel-intent versus actual, timestamp/peak
  encodings, escaping of newlines/control characters, and detail privacy rules.
- **B:** authorize this lane to propose that explicit registry/encoding table
  as a documentation-only addendum for approval before sink implementation.
- **C:** restrict the first mock sink to a supplied minimal subset; enumerate
  that subset and its encodings explicitly. No invented immutable names.

### R5 — affected A6/§2.14: serialized-plan and exact-command bytes

**[UNVERIFIED]** Plan hashing is settled; deterministic serialization and the
relationship between the disclosed command and execution context are not.

- **A:** supply the canonical plan schema/serialization and command disclosure
  contract (argv versus shell string, encoding, cwd/environment binding).
- **B:** authorize a documentation-first proposal for deterministic UTF-8 JSON
  plan serialization, with execution-relevant fields and exact command bytes
  bound to the approval hash; approve it before persistence/execution code.
- **C:** hold executable approval persistence until design provides that
  contract. Synthetic UI sketches must not imply valid executable approvals.

### R6 — affected A1/V44 §4.1: protected state versus owner targets

**[TESTED-ONLY]** Approved runtime `hands.db` lives under
`~/.local/share/assistant`, which A1 also lists as protected. The real Store and
Journal write control state; hand-written exemptions would change the wall.

- **A:** explicitly distinguish trusted lane control-state writes from planned
  errand targets, while forbidding plan/tool access to that state; specify the
  exact boundary. Tests still use tmp state, never owner state.
- **B:** require a revised path/authority arrangement with no such distinction;
  supply the affected section and replacement naming decision.
- **C:** leave runtime state unresolved; authorize tmp-only state after revision
  acknowledgement without claiming a production exemption exists.

### R7 — affected A5/§2.5: yes/no lexical and focus edges

**[UNVERIFIED]** The normal free-text path and focused-ask Yes/No are settled.
Only lexical normalization and absence of a focused actionable ask need ruling.

- **A:** exact lowercase `yes` / `no` only; without a focused pending ask they
  remain ordinary free-text intent (and cannot approve anything).
- **B:** trim surrounding whitespace and match case-insensitively; without a
  focused pending ask show “no ask is selected,” do not dispatch a new intent.
- **C:** supply another explicit lexical/no-focus table. No synonyms, guessed
  confirmation phrases, or extra reserved commands will be added silently.

### R8 — affected A6/§2.11: notification envelope and private-card exposure

**[TESTED-ONLY]** The hands body stays byte-exact `elaria needs a yes`; all
always-visible surfaces are signals only. The delivered summary does not define
lock/company/class posture or what makes the detailed card private.

- **A:** supply the notification title/enablement and detailed-card visibility
  table for normal, company, class, locked and unknown posture, including the
  trusted source of posture in the standalone synthetic harness.
- **B:** mock notification payload only and synthetic private-card harness until
  design integration provides that posture contract; no desktop notification
  dispatch or real-content visibility claims in console v1 pre-gates.
- **C:** hold notification/card behavior pending the full privacy section.

**[TESTED-ONLY] End of verbatim R1–R8 relay copy.**
