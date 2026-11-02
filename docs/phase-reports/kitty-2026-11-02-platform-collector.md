# KITTY HANDS — authorised platform collector build checkpoint

**TESTED-ONLY. v1.1 incomplete. Scene NOT READY. Blocked, not bypassed.**
**New collector: BUILT FOR REVIEW, NOT AUTHORISED FOR OWNER RUN.**

Branch: `arena/b65d5161-elaria` (active).
Accepted parent: `72f53b2a553f8495206f64aae2ec623c2acea7d7`.
Resulting commit SHA is supplied in the delivery message. No PR, force-push, merge,
branch switch, protected-file edit, adapter build or owner-system probe this turn.

## DONE — granted scope only

- Confirmed the Git-object drift delivery route: extracting the two exact accepted
  blobs with their script-relative layout and checking both approved SHA256 values
  before Python is equivalent for the instrument to downloading those bytes. Fetch
  may update Git metadata, but requires no checkout/branch switch. The actual owner
  extraction packet was absent from the relay; this is not an audit of unseen commands.
- Confirmed by AST import inspection that the unchanged `drift.py` is stdlib-only.
  It needs no assistant uv environment or third-party Python package. System Python
  is appropriate. Its external installed kitten executable remains a prerequisite.
- Added the **separate** `tools/kitty/collect_platform.py`, with no dependency on the
  checkout/inventory layout and no modification to the already approved drift kit.
- Twelve fixed queries collect separate kitty version, binary package owners, six
  package version/file memberships, SSH version, bare usage and query categories.
  Every subprocess preserves argv, return code, stdout/stderr, error and truncation.
  Bare SSH's expected usage exit 255 is recorded, not treated as failure. Missing
  packages/binaries are findings, never installed or substituted.
- Package-owned SSH manuals are selected only from successful OpenSSH RPM membership,
  at exact unlocalized system paths. No arbitrary path from subprocess text is read.
  Symlinks/nonregular/foreign/writable/hardlinked/oversized/changing documents refuse.
  Plain/gzip/bzip2/xz/zstd forms are handled through direct reads or fixed bounded
  decompression helpers receiving preopened bytes on stdin. Missing helpers, ambiguous
  representations and unresolved recognized roff includes remain explicit findings.
- Positive child environment, private empty HOME, no inherited input/application FDs,
  private process groups, 20-second deadlines and 2 MiB combined-output limits. Timeout
  or overflow kills the private process group and bounds reaping. No shell, connections,
  RC command, ssh -G, owner configuration, keys, agents or terminal content collection.
- Fresh private output only: owned direct child of HOME, directory/empty-home at 0700,
  fifteen JSON records at 0600, exclusive creation/fsync, no overwrite/move/delete/repair.
  Unexpected child-home writes are findings and remain owner-side, not returned as content.
- **68 new synthetic tests**, with no real system-query or decompressor execution.
  Runner tests use pipe-backed fake Popen objects; document fixtures are synthetic.
  All accepted tests and shared fixtures remain unchanged.

Exact command/decompression tables, limits, reads/writes and limitations are in
`docs/kitty-platform-collector.md`. No owner execution packet for the new collector
is issued here. Build permission is not owner-run permission.

## Verbatim final local gates

```text
Python 3.11.2
```

Combined kitty/collector suites:

```text
246 passed in 2.49s
```

Full suite:

```text
2349 passed, 6 skipped in 106.18s (0:01:46)
```

Ruff:

```text
All checks passed!
```

Arithmetic: accepted 2281 + 68 = 2349; lane 178 + 68 = 246.
Final full log: `.venv/kitty-platform-final-suite.log` (ignored/local).
An earlier full run also passed: 2349 passed, 6 skipped in 113.81s.
No known running_daemon teardown intermittent occurred in either full run.

A new test initially left a synthetic GEMINI_API_KEY visible to the existing environment
fixture's teardown assertion (65 passed, 1 error). Only the new test was corrected to
scope and restore its injected environment with monkeypatch.context(). No shared fixture
or assertion was changed. This was not the known running_daemon async-generator quirk.

All gates are local-only, not automated CI or owner hardware proof. The disposable
3.11 test environment was restored after sandbox reconstruction; no project dependency
file changed. **No Python 3.14 run occurred**, and no interpreter acquisition was attempted.
The owner machine remains the designated supervised 3.14 mounted-daemon instrument.

## Evidence pins / limits of observation

Rechecked current files against the exact accepted Git blobs and approved hashes:

- `tools/kitty/drift.py`: 5665 bytes, SHA256
  `05fa9e6cf9fa2fc7046063e8cff9326b19424016f0d396fe419ad18c5028a87b`.
- `src/assistant/hands/kitty/data/inventory.json`: 514801 bytes, SHA256
  `7e0f01ff2396c292f05528261d349142f1c6e08eed948847ee1300633a1aafcd`.

New collector SHA256:
`7e2d8679a3c18aa35968c06aab469082f9d17cfa8fb1ccaace3f5a4c85261c63`.
Its imports are also stdlib-only; fixed system binaries/decompressors are external
prerequisites, with absence recorded rather than masked by dependency installation.

The relay reports a `kitten 0.47.1` reading. It is **not** Fedora build/release evidence,
not an observed match to 0.47.1-1.fc44 and not downstream-patch equivalence. No returned
owner drift/RPM evidence package or new-collector execution is available in this lane.
No new source-research/owner-hardware verification is claimed by unchanged hashes.
The previous clause digest remains the accepted reference; the clause was not fetched
or edited, and its external verified copy was not available for a fresh hash in this
reconstructed sandbox.

## DEFECTS FOUND / remaining limits

Collection exit 0 means **collection complete**, not compatibility, reconciliation,
semantic or hardware proof. All reports explicitly retain the latter holds.
The collector is not an OS sandbox and does not claim safety against compromised
system executables. System RPM/loader/runtime settings may be read; personal child
settings are isolated by the fresh empty HOME.

Symlinked HOME/document layouts, extra/manual aliases, unrecognized compression,
missing helpers and unresolved includes are findings, not auto-resolved guesses. Its
raw manuals require human semantic reconciliation; it does not render roff, establish
configured SSH defaults, verify installed files against RPM, hash the executables or
prove downstream patches equivalent. The maximum nominal subprocess/reap budget is
14 × (20 + 2) = 308 seconds; OS/filesystem stalls are not claimed to obey a hard overall
deadline. Output/input capture is bounded; the JSON envelope adds encoding overhead.

Owner kitty.conf/effective settings, SSH configuration, sockets, keys, agents and terminal
content stay outside both collectors. No real owner content is requested into the sandbox.
The pre-existing partial create-marker adapter remains partial; ten other families remain
unimplemented. No new in-principle assessability finding is made without doing that work.
Missing assessment/effect evidence remains blocked, not bypassed.

## NEXT GATE / OPEN QUESTIONS

Review the new collector as an instrument; a **separate owner-run ruling** is required
before scheduling it. The already approved drift kit and two-binary RPM query are the
only owner collection exceptions carried by this ruling. Await and reconcile their
actual returned evidence; do not infer a match from source pins or package names.

Adapter work was not performed under this turn's narrow grant. The previously ruled
adapter → target/effect → stream/cancel → resource-bound sequence remains, with Fedora/
OpenSSH reconciliation alongside and scene card last. Scene NOT READY; no extra hardware
request. No new protected-file authority is requested or assumed.

## Structural audit / diff

```text
 docs/design/kitty-2026-11-02-checkpoint-ruling.md         |  31 +++
 docs/kitty-platform-collector.md                          | 139 +++++++++++
 docs/phase-reports/kitty-2026-11-02-platform-collector.md | 174 ++++++++++++++
 tests/test_kitty_platform_collector.py                    | 438 ++++++++++++++++++++++++++++++++++
 tools/kitty/collect_platform.py                           | 337 ++++++++++++++++++++++++++
 5 files changed, 1119 insertions(+)
```

All **279 accepted parent files** were compared: **278 byte-identical**, with only the
kitty design ledger appended. Every accepted runtime/tool/test file is unchanged.
Of 247 pre-kitty baseline files, 246 remain byte-identical. `daemon.py` is byte-identical
to the accepted eight-line mount; subtracting those same eight insertions reproduces
the pre-kitty daemon exactly. **Zero additional protected hunks.** Extra diff outside
the five collector-owned tool/test/documentation paths: **NONE**.

At turn start local Git metadata had reverted to `ed20344`, while the remote branch
still pointed to accepted `72f53b2` and all 279 accepted files were present byte-for-byte.
Fetched only this lane, verified all files/no extra nonignored files, then restored local
HEAD/index to the accepted commit without changing file contents. No ancestry fabrication,
branch switch, worktree creation, force-push or alteration of owner mainline was involved.

## Artifacts

- `tools/kitty/collect_platform.py` — standalone, review-only metadata collector.
- `tests/test_kitty_platform_collector.py` — 68 synthetic regressions; existing fixtures untouched.
- `docs/kitty-platform-collector.md` — exact instrument contract and owner-run hold.
- `docs/design/kitty-2026-11-02-checkpoint-ruling.md` — appended grants/amendments/scope record.
- This report — measured gates, pin checks, structural audit, missing owner evidence and next gate.
