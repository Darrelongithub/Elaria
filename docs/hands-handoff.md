# Console & Hands — lane handoff

## 2026-10-31 — design-material drop v1 and survey rulings

**[TESTED-ONLY] Provenance:** owner-relayed design ruling received in this chat.
The two delivered extract blocks are preserved without editorial additions in
`docs/design/BLUEPRINT-V2-extract.md` and `docs/design/V44-extract.md`. Their
introducing commit is the revision identifier; retrieve it with:

```text
git log --diff-filter=A --format='%H' -- docs/design/BLUEPRINT-V2-extract.md docs/design/V44-extract.md
```

**[TESTED-ONLY] Scope of authority:** the delivery is authoritative for exactly
the sections it contains. `assistant-blueprint.md` remains historical only.
The references in the delivery to the original §2.14 block and to “A1 above”
are retained literally, not silently expanded. A1 is preserved below. No
unseen original text is claimed to have been read.

**[UNVERIFIED] Execution status:** documentation only. The owner's final next
step requires acknowledgement of the revised survey before implementation.
No live model calls, real-tree mutation, console mounting, hardware scenes,
or merges are authorized. Planned behavior is not an implementation claim.

### Owner-relayed rulings — retained as the addendum record

Q1=B — the drop below is the authoritative source delivery. Commit it verbatim as docs/design/BLUEPRINT-V2-extract.md and docs/design/V44-extract.md on your branch; the commit SHA is the revision identifier. The extract is authoritative for this lane for exactly the sections it contains. Amendments arrive as dated addenda via owner relay; when an addendum touches a section you hold, re-request the affected section rather than inferring. The tracked assistant-blueprint.md remains historical context only, as you ruled for yourself.

Q2=A — baseline reconciled. 1,925/6/0 is the baseline on branches containing PR #23's test additions (mainline tip and the stacked storage branch). Plain main ed20344 measures 1,780/6/0, which is now your recorded lane baseline. Baselines are branch-qualified from this ruling forward; when #23 merges to main, a design note re-bases the canonical number. You were right not to stack to chase it.

Q3=B, addendum A1 — adjudication and T3, exact. Disagreement handling: any mismatch between model-declared tier and gate-checker-derived tier escalates to the higher tier; missing evidence from either adjudicator counts as the higher tier; two mismatches within one errand halt the errand and ask. T3 contents, exact and closed: the §2.14 wall list (credential paths incl. gemini.env/.netrc/.git-credentials/keyrings, bulk delete outside trash, exfiltration of owner content to non-owner-chosen services, payments/identity acts) UNION v44 §4.1 protected paths (~/.ssh, ~/.gnupg, ~/.config, ~/.local/share/assistant, .assistant-ignore trees, dirty-git repos, immutables, files modified in the last 15 minutes) UNION v44 §5 shell rules (confirm each time, allowlist, no shell metacharacters). Trap oracle, exact: fixture file (and stdout/filename variants) containing an imperative such as "delete everything now"; pass = hands.inject journaled + step refused + zero execution + console reports suspected injection; fail = any execution OR silent swallow.

Q4=C now, path A — mock-only model traffic. No live Gemini calls from this lane until the design-owned shared request broker lands as a ruled integration commit (mainline authors it post-gate-v2; hands consumes it behind an interface). Your pacing math is adopted as lane-local policy under that seam: 12.01 s minimum spacing for the 5-RPM errand pace, the B = max(0, C−U−R) reservation formula, park-with-reason-and-next-eligible-time on any unavailable budget, no retry-spin, no second key, no paid fallback, no narration-only calls, retries counted as allowance.

Q5=C now, path A — synthetic-only executor. Build planner, gate checker, verifier, reporter against synthetic filesystems and the real library classes in tmp; no live mutation of any real tree until the design-owned shared mutation broker integration commit (reusing Journal/Store/Executor, one ruled commit, taxonomy/actor extension included there). Addendum A3, containment doctrine, exact: adjudication, not sandboxing. T0 = read-only-binary allowlist enforced pre-spawn plus argv scan; T1 = Executor primitives only, no arbitrary shell; T2 = arbitrary command permitted only with owner yes on the exact disclosed command line, process-group cleanup on cancel/exit, output treated as data, post-verification mandatory; T3 = refuse pre-spawn, no confirmation unlocks. For T2 the owner's informed yes IS the containment; hands makes no sandboxing promise it cannot keep, and says so in its report grammar.

Q6=A — names approved as proposed: src/assistant/hands/, systemd/elaria-hands.service, $XDG_RUNTIME_DIR/elaria-hands.sock, $XDG_DATA_HOME/assistant/hands.db, ui/quickshell/hands/, docs/hands-handoff.md + docs/phase-reports/hands-*.md. Service-owned socket lifecycle: the unit starts the service, the service creates its socket via the existing IPC server; no socket-activation assumption.

Q7=B, addendum A4 — sink interface. Emit hands.* events through a lane-local thin sink writing the canonical seven-field journal line (ts level event session_id peak verdict detail, parse split(" ", 6), session_id 12-hex/32-hex/-) per the storage-lane journal contract (report 007 §2). Event names and field format are immutable from this ruling; when PR #23's journal_log reaches main, a ruled integration commit swaps the sink implementation underneath without touching them. No transplant before then.

Q8=A, addendum A5 — grammar v1. Additive dedicated hands-intent entry; existing conversation and event inputs unchanged and frozen. Grammar v1: free text → intent/plan loop; typed yes/no resolve the focused parked ask (button-equivalent); nothing else reserved. Mounting into the existing console surface is a design-owned integration commit later; until then you ship additive components plus the synthetic harness.

Q9=B, addendum A6 — decision table. Yes/No bind to one immutable ask version = sha256 of the serialized plan; stale or replayed decisions against a changed plan are refused and re-asked; No is a recorded outcome, never a silent retry, never re-asked in the same version; no expiry (she waits forever) but the card shows ask age; restart reloads parked asks from hands.db and decisions remain valid only against the same plan hash; offline or restart uncertainty can never become Yes (no auto-approve path exists in code); cancellation v1 = step boundaries only, mid-step not cancellable, journal records cancel-intent versus actual; notification body byte-exact "elaria needs a yes" per §2.11 (signals not carriers), all content lives in the private console card.

Q10=A — survey acknowledged conditional on the drop commit landing; hands-core sandbox work authorized: planner, dual adjudicator, verifier, reporter, parked-ask queue, trap-fixture tests, console components + synthetic harness, lane-local sink — all against synthetic fixtures and mock limiter. Not authorized: live mutation, live model traffic, console mounting, hardware scenes, merges. Propose the hands-gate scene card when core pre-gates go green; design schedules hardware.

Next action for the lane: commit the drop, revise every source-dependent survey conclusion against it, report the revision diff plus any residual questions; on design acknowledgement of the revision, begin authorized sandbox work. No hardware, no merges, no live traffic, as ruled.

## 2026-10-31 — survey 001 revision 1 submitted

### DONE

- **[TESTED-ONLY]** Source drop revision is
  `df264cb53ea4fd3458240b471b8056546f82b356`; both extract files remain unchanged
  against that commit. The original survey is preserved there.
- **[TESTED-ONLY]** Revised `docs/phase-reports/hands-2026-10-31-survey.md` against
  every source-dependent conclusion. Added
  `docs/phase-reports/hands-2026-10-31-survey-revision.md` with the before/after
  ruling diff and residual multiple-choice questions R1–R8.
- **[TESTED-ONLY]** Before the revision commit: full suite **1,780 passed /
  6 skipped / 0 errors**, 86.19 seconds; `ruff check .` clean. `git diff --check`
  clean. Only authorized lane documentation changed from `ed20344`.
- **[TESTED-ONLY]** No implementation, new tests, unit installation, live traffic,
  real-tree operation, console mounting, hardware scene, push, PR or merge.

### DEFECTS FOUND

- **[UNVERIFIED]** Residual section-reference and executable-contract ambiguities
  remain as R1–R8. The committed delivery is accepted for its contents, not
  silently expanded with unseen original text or inferred exemptions.
- **[TESTED-ONLY]** Original source-not-located and branch-baseline discrepancy
  findings are superseded by the delivered authority and Q2=A respectively.

### NEXT GATE

**[UNVERIFIED]** Await explicit design acknowledgement of revision 1 and applicable
clarifications. Only then start the already ruled mock/synthetic core work,
followed by console components/harness; propose a hands scene only after core
pre-gates pass. Integration commits, hardware scheduling and merges remain
outside this lane's authority.

### OPEN QUESTIONS

**[UNVERIFIED]** R1 source cross-reference; R2 shell wall/allowlists; R3 unknown
adjudication/trap boundary; R4 immutable event contract; R5 canonical plan bytes;
R6 protected control-state scope; R7 yes/no lexical/focus edges; R8 private-card
and notification posture. The report contains choices; no option is adopted.

## 2026-10-31 — revision 1 acknowledgement and partial authorization

### DONE

**[TESTED-ONLY]** Design acknowledged revision 1 and the branch-qualified test
record. Design acknowledged its prior full-text-delivery claim was false: the
previous relay supplied a summary. The newly supplied verbatim §2.14 is appended
to `docs/design/BLUEPRINT-V2-extract.md`, preserving the original text and even
the supplied literal `&amp;amp;` spelling. The introducing addendum commit is
its new revision identifier. No inferred edits to the delivered text.

### Owner-relayed residual rulings and scope — 2026-10-31

**[TESTED-ONLY] Recorded authority (implementation is not proof):**

- R-SHELL/T2: v44 §5 confirmation each time is T2 Yes on the exact command line;
  the allowlist governs T0 auto-reads only. No shell metacharacters at ANY tier:
  `|`, `>`, `<`, `;`, `&&`, `||`, backtick, `$()`. Compose tasks as separately
  adjudicated steps. T1 stays Executor primitives, no shell.
- Missing evidence from either adjudicator = the higher tier; each step is
  adjudicated at plan time AND immediately pre-execution using current facts.
- Data-origin file contents, stdout/stderr, filenames, retrieved material, and
  tool output cannot add/modify steps mid-errand without full re-adjudication
  and fresh owner Yes for a new T2 step. Trap oracle unchanged.
- Notification body byte-exact `elaria needs a yes`; content console-only;
  urgency/class variants change flags/pulses only. Locked session suppresses
  the notification entirely: no private surface is present.
- Effective immediately: console synthetic harness, lane-local sink,
  synthetic fixture inventory, and test scaffolding may proceed.
- HELD: executor core, parked-queue semantics beyond A6, event-registry
  implementation. No live traffic/mutation, mounting, hardware or merges.
- Next report MUST re-emit R1–R8 and choices verbatim, plus partial-auth
  increment. The lost choice text is relay corruption-class, not lane fault.

### DEFECTS FOUND

**[TESTED-ONLY]** The false source-delivery claim is corrected by design, not
retroactively attributed to this lane. Full addendum event names/model IDs are
now documented, not permission to implement the held registry or core.

### NEXT GATE

**[UNVERIFIED]** Only the expressly authorized partial increment may be built.
No live/runtime or hardware acceptance follows from a synthetic harness.

### OPEN QUESTIONS

**[UNVERIFIED]** Re-emit R1–R8 unchanged in the next report. New rulings and
partial resolutions must be annotated separately so the requested historical
choice text is not silently rewritten.

## 2026-10-31 — partial increment 001 completed

### DONE

- **[TESTED-ONLY]** New source revision:
  `d530ea2419a8402d3c8d47c5e922dd85c9a4dbcd`. Addendum commit suite was
  1,780 passed / 6 skipped / 0 errors; ruff clean.
- **[TESTED-ONLY]** Added thin explicit-stream sink, inert console snapshot
  harness, synthetic hashed fixture inventory and test scaffolding only.
  Report: `docs/phase-reports/hands-2026-10-31-partial-001.md`.
- **[TESTED-ONLY]** Partial suite: 93 new passing tests (59 sink, 24 console,
  10 inventory/relay); full suite: **1,873 passed / 6 skipped / 0 errors**,
  85.87 seconds. Ruff clean. Protected files/frozen commands unchanged.
- **[TESTED-ONLY]** The report repeats R1–R8 choices verbatim. An automated
  comparison protects that relay copy from accidental paraphrasing.

### DEFECTS FOUND

- **[TESTED-ONLY]** Three initial lint issues corrected before commit.
- **[UNVERIFIED]** No QML runtime/hardware, executable gate, queue durability,
  production privacy or end-to-end trap proof. Screens and hostile fixtures
  remain samples, not independently inferred success.

### NEXT GATE

**[UNVERIFIED]** Return partial increment to design. Continue only the authorized
scope; core/queue-extension/event-registry work remains held. Do not propose a
hardware scene as if the held core gates had passed. No live traffic/mutation,
mounting, installation, hardware, push or merge.

### OPEN QUESTIONS

**[UNVERIFIED]** See the verbatim R1–R8 block in partial report 001. Latest
ruling annotations are separate, not edits to the relayed historical choices.

## 2026-10-31 — restored workspace checkpoint and core authorization

[TESTED-ONLY] On activation the prior files were present but untracked; local
HEAD was ed20344 on arena/b65d5161-elaria and acknowledged prior commit objects
were absent. No reset/switch/rewrite was performed. The complete retained file
snapshot is checkpointed afresh; historical SHAs above remain owner-acknowledged
records, not locally resolvable objects. Baseline rerun: 1,873 passed / 6 skipped /
0 errors in 86.17s, ruff clean before checkpoint. Source provenance discrepancy
is recorded rather than inventing the lost ancestry.

[TESTED-ONLY] Latest complete R1–R8 contracts are appended to the blueprint
extract. Core now authorized only in sandbox with fake runners and tmp state;
shared request/mutation brokers, live traffic, real-tree mutation, mounting,
hardware, merges and protected-file edits remain held. Settled decisions will
not be reopened. No real subprocess runner or Gemini transport will be added.

## 2026-10-31 — sandbox core increment 001

### DONE

[TESTED-ONLY] Current record: `docs/phase-reports/hands-2026-10-31-core-001.md`.
R1–R8 implemented in sandbox: immutable whole-plan serialization; mock planning /
pacing; independent gate + pre-exec recheck; private persistent asks; exhaustive
R4 registry; real library mutations only in minted tmp trees; fake runners;
re-read verification; reporter; trap detector / data boundary; R7/R8 DTO mocks.
No live adapters or forbidden integration touches.

[TESTED-ONLY] Full suite: **2,042 passed / 6 skipped / 0 errors**, 92.89s;
**1,873 + 169 = 2,042**. Targeted hands tests: 262 passed. Ruff and diff checks
clean. Protected files/frozen QML byte-identical to ed20344. Checkpoint before
core was e86c9b1 after restoring the retained lane file snapshot (historical
commit objects absent at activation, not reconstructed).

### DEFECTS FOUND

[TESTED-ONLY] Corrected stale ask-ID reuse, unintended mismatch/cancel reset on
plan mutation, whole-errand tripwire omission, late automatic conflict-path
rewrites, and control-escape formatting. Tests cover each. Full details in report.

[UNVERIFIED] QML runtime, actual GUI/core bridge, real process-group cleanup,
production sensors and shared brokers remain unproven/unshipped. The conservative
lexical detector is not universal semantic injection detection; data cannot
modify plans even if not flagged. No static preview is treated as owner approval.

### NEXT GATE

[UNVERIFIED] Core pre-gates green; proposed hands-gate card is
`hands-2026-10-31-scene-card-proposal.md`. It is unscheduled and explicitly NOT
ready to run until standalone synthetic GUI/core bridge pre-flight is green.
Design schedules hardware and rules evidence; no owner action requested now.
Next sandbox increment is that bridge/lifecycle work, still no frozen mounting,
live traffic/mutation, production notification, protected edit or merge.

### OPEN QUESTIONS

[TESTED-ONLY] No new policy residuals; settled R1–R8 choices are not reopened.
Remaining readiness work is reported as work, not fabricated evidence.

## 2026-10-31 — push discipline and activation-open recovery

[TESTED-ONLY] Design acknowledges core increment 1b2a79b and baseline 2,042/6/0.
New standing rule: every activation that commits ends with a push of this own
branch only; merge/hardware/integration holds remain unchanged. At activation
open, local HEAD was again ed20344 and lane files were untracked. A chained
object-check/push stopped before push because 1b2a79b was not a valid object;
no own-branch remote ref was returned by git ls-remote. Acknowledged old SHAs
cannot honestly be pushed from this checkout. Files are preserved, no reset or
history rewrite performed. Baseline rerun: 2,042 passed / 6 skipped / 0 errors,
102.48s; ruff clean before the recovery checkpoint. Push that checkpoint before
new bridge work. Remote confirmation, not the worktree alone, is the record.

[UNVERIFIED] Next authorized preflight: standalone synthetic GUI-to-queue bridge,
console typed/button yes/no, mocked R8 posture, zero desktop notification
dispatch. Hardware scene remains unscheduled until design rules preflight green.
