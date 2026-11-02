# KITTY HANDS v1.1 — first family / assessment attribution checkpoint

**TESTED-ONLY. NOT v1.1 completion. Owner scene NOT READY. Blocked, not bypassed.**

Branch: `arena/b65d5161-elaria`, active and accepted in place.
Accepted parent: `e22005257a1be4680bfd164057bd4a7791601ac4`.
Resulting SHA is supplied in the delivery message. No PR, merge, force-push, branch
switch, fixture repair, protected-file edit or owner hardware session in this tranche.

## DONE

- Recorded the owner-carried acceptance and binding five-point adapter doctrine, the
  sequence of remaining gates, parallel reconciliation, and interpreter disclosure rule.
- Implemented **one partial per-family adapter**, `kitty.create-marker/v1`. It assesses
  reviewed 0.47.1 literal `text`/`itext` highlighting by grammar, not by task/content
  whitelist. Missing source/specification/target evidence refuses with a reason.
- `function` markers remain legacy Python-evaluation T3 and are refused even with Yes
  and an open hand. Regex forms refuse pending complexity/effect evidence. Unknown or
  unproven parser forms refuse. No requested marker file is opened or executed.
- Added metadata-only assessment receipts with assessor/version, reason, verdict,
  phase and evidence reference bound to exact act/nonce, observed target identity,
  catalogue, and matched family source-review identity. Shared receipt formatting is
  **not** shared classification and does not count as another adapter.
- Persist/fsync `phase=assessment` before R3/consent/dispatch, including refusals and
  disclosure assessments. Missing journal capacity/write success blocks dispatch.
  Invalid or throwing checkers produce attributed boundary refusals without exception
  content. The boundary cannot supply a generic positive effect assessment.
- Recovery validates receipts, retains the trail, and never restores an assessment as
  owner consent, hand-open or execution authority. Old ledger records remain readable;
  they are not rewritten or retroactively assigned evidence.
- **61 new synthetic tests** cover the family's primary missing-evidence behavior,
  source mismatch, target absence, T3/consent non-override, grammar/content distinction,
  exact receipt binding, tampering, journal failure, durable recovery and secrecy.
  Existing 117 kitty tests and all shared fixtures are unchanged.

## Verbatim local gates

```text
Python 3.11.2
```

Combined kitty suites:

```text
178 passed in 1.59s
```

Full suite:

```text
2281 passed, 6 skipped in 97.94s (0:01:37)
```

Ruff:

```text
All checks passed!
```

Arithmetic: accepted 2220 + 61 = 2281; kitty 117 + 61 = 178.
Full log: `.venv/kitty-marker-attribution-suite.log` (local, ignored).
No known running_daemon teardown intermittent occurred in this full run. No fixture
was changed. These are local-runner gates, not automated CI or hardware proof.

During development, an initial focused run caught 8 failures: assessment records lacked
run's silent metadata, and receipt-key validation incorrectly excluded digits in hash
field names. Production code was corrected; accepted tests were not weakened/edited.
Subsequent focused runs and the final full gate above pass.

## DEFECTS FOUND / incomplete scope

This is **not 11 completed adapters**. Ten families still have no family adapter:
`action`, `kitten`, `launch`, `new-window`, `run`, `load-config`, `env`, `send-text`,
`send-key`, `signal-child`. Each valid request is refused by the native boundary with
its specific `<verb>-adapter-not-implemented` reason and a reference. Those boundary
refusals are not counted as implemented family assessments. Blocked, not bypassed.

Even create-marker is partial: regex cost analysis, other accepted upstream integer
forms and broader grammar coverage remain unfinished. Function markers are still
legacy T3; total kitty capability never overrides that hold. The adapter classifies a
reviewed literal effect, but has no independent post-marker state probe: successful RC
replies stay **UNVERIFIED**, never proof of highlighting or restoration of a prior marker.

General/compound selectors, creation sources/destinations and the full per-verb effect
matrix remain incomplete. Stream/encrypted-cancel faults, pending-plan resource bounds
and reviewed ledger archival remain later gates. No new protected grant is requested
or assumed. The existing daemon door is unchanged; all implementation remains in
kitty-owned modules/tests/docs.

Legacy library tests can still inject checkers without receipts; their trail explicitly
says `unattributed-library-checker` with a null reference. This is not an adapter or
production evidence. Mounted attach constructs NativeChecker; IPC cannot inject these
legacy test dependencies. No fixed-safe checker is used to unlock the owner scene.

## Parallel reconciliation / interpreter evidence

Rechecked **all 39** pinned RC source hashes against the disposable 0.47.1 research
checkout, plus all four files in the marker parser/dispatch dependency chain. Exact
source references and semantics are in `docs/kitty-adapters.md`. No inventory JSON,
schema, renderer, drift tool or owner scene file changed. Inventory SHA256 remains
`7e0f01ff2396c292f05528261d349142f1c6e08eed948847ee1300633a1aafcd`.

**Owner reconciliation remains unreceived:** installed kitty/kitten versions/help,
Fedora package/file membership, OpenSSH and the owner drift output are not available.
Source research is not installed-owner evidence. Reconciliation runs alongside adapters,
not as their dependency or a task deferred until after them. Upgrade drift still needs
owner execution and semantic reconciliation before completion.

Owner reports Python **3.14.8**. Available sandbox interpreter is **3.11.2**.
An attempted GitHub standalone **3.14.10** download failed at the redirect to
`release-assets.githubusercontent.com` with curl exit **35**, `SSL_ERROR_SYSCALL`;
that redirect host is outside the sandbox outbound allowlist. No 3.14 interpreter was
installed/executed and **no 3.14 test pass is claimed**. A local 3.14 suite remains an
outstanding pre-card gate to attempt; no shared fixture or network policy workaround
was used. The first owner mounted-daemon run remains design-supervised.

## NEXT GATE / OPEN QUESTIONS

Continue **per-family adapters first**, each with its own evidence requirements and
primary refusal tests. Then full target/effect coverage; broader stream/cancellation
fault tests; resource bounds. Fedora/OpenSSH/drift reconciliation runs alongside.
Scene card comes **last** and remains NOT READY. No hardware request is made here.

No new design ruling is needed for this tranche. The remaining gates are substantive
engineering/evidence work, not grounds to invent safe verdicts or expand a protected
surface. Lane remediation and the separate console cherry-pick plan remain unchanged.

## Diff / structural boundary audit

```text
 docs/design/kitty-2026-11-02-checkpoint-ruling.md         |  30 ++++
 docs/kitty-adapters.md                                    | 108 ++++++++++++
 docs/kitty-host.md                                        |  16 +-
 docs/phase-reports/kitty-2026-11-02-marker-attribution.md | 166 ++++++++++++++++++
 src/assistant/hands/kitty/adapters/__init__.py            |   5 +
 src/assistant/hands/kitty/adapters/marker.py              |  76 +++++++++
 src/assistant/hands/kitty/attribution.py                  |  77 +++++++++
 src/assistant/hands/kitty/bridge.py                       |  10 +-
 src/assistant/hands/kitty/checker.py                      |  31 +++-
 src/assistant/hands/kitty/host.py                         |   2 +-
 src/assistant/hands/kitty/policy.py                       |  32 +++-
 src/assistant/hands/kitty/recovery.py                     |   5 +-
 tests/test_kitty_adapters.py                              | 313 ++++++++++++++++++++++++++++++++++
 13 files changed, 851 insertions(+), 20 deletions(-)
```

All 247 pre-kitty baseline paths at `35adbbaf` were compared: **246 byte-identical**;
the sole exception remains the already accepted 8-line daemon door. `daemon.py` is
byte-identical to accepted parent `e220052`; removing those same 8 insertions still
reproduces the pre-kitty daemon exactly. **Zero additional protected hunks.** Shared
fixtures, frozen hands/console, owner scene and inventory/drift artifacts are unchanged.
Extra diff outside kitty-owned modules/tests/docs: **NONE**.

Clause unchanged: 14322 bytes, SHA256
`8be8a4a94e958e1fd0323d8e687418f73e6cfd407a5a08bb6720b75769ffb6bc`.

## Artifact paths

- `src/assistant/hands/kitty/adapters/{__init__,marker}.py` — first partial family only.
- `src/assistant/hands/kitty/attribution.py` — receipt formatting/validation, no verdict engine.
- `src/assistant/hands/kitty/{checker,policy,bridge,host,recovery}.py` — native routing and durable attribution.
- `tests/test_kitty_adapters.py` — 61 new synthetic regressions.
- `docs/kitty-adapters.md` — exact source identities, grammar, evidence and incomplete coverage.
- `docs/kitty-host.md` — current host coverage/recovery contract.
- `docs/design/kitty-2026-11-02-checkpoint-ruling.md` — acceptance/doctrine/sequencing record.
- This report — local gates, structural audit, missing interpreter/owner evidence and next gate.
