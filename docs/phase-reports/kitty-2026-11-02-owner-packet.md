# KITTY HANDS — committed owner packet delivery checkpoint

**LOW PRIORITY. No owner hardware time requested. Voice-chain work takes precedence.**
**TESTED-ONLY. v1.1 incomplete. Kitty scene NOT READY. Blocked, not bypassed.**

Branch: `arena/b65d5161-elaria`, active.
Accepted parent and collector source pin: `a0e1aa8bba11e15ae6de9150b5a158a966acc2d6`.
The packet's delivery commit SHA is supplied in the delivery message, so it can be
retrieved by exact Git object/path rather than a moving branch. No PR, force-push,
branch switch, new worktree, owner execution, adapter work or cross-lane change.

## Exact owner-run artifact / bootstrap gate

Repo path: **`tools/kitty/owner_run_platform.py`**

Bytes: **10846**

SHA256: **`8c9c1d62fa3d917344e9f5903f68cb3a6666c4434d2b975847bd82d92e025b14`**

Owner/design retrieves this exact committed file through their local Git-object
mechanism and independently checks this SHA256 **before invoking Python**. The packet
cannot authenticate its own first execution. No executable shell is supplied in chat,
no reconstructed paste is required, and no unseen bootstrap/extraction script is
certified. Invocation forms live inside the committed file. The new standing rule is
recorded in `docs/kitty-platform-owner-packet.md`: future owner-run packets are committed
files; the previously issued drift packet remains its approved exception.

Default packet behavior is prepare/verify only. An explicit `--run` is the scheduled
owner choice to hand off to the collector after all gates pass. The packet is deliverable
for owner/design scheduling under the conditional ruling; this report is **not** a request
to run it now and does not release the kitty scene.

## Exact five collector-checkpoint paths and SHA256 values

Every row is pinned to **a0e1aa8bba11e15ae6de9150b5a158a966acc2d6**. These are the five
checkpoint files (four originally new files plus the appended design ledger), not a
claim that the ledger was newly created. All five remain unchanged in this delivery.

| Repo path | Bytes | SHA256 |
| --- | ---: | --- |
| `tools/kitty/collect_platform.py` | 16455 | `7e2d8679a3c18aa35968c06aab469082f9d17cfa8fb1ccaace3f5a4c85261c63` |
| `tests/test_kitty_platform_collector.py` | 18799 | `38a5cd9f3b630f8a030b9e71d3e3446fda21cfe78e5394f9183dbf78a9ae45d2` |
| `docs/kitty-platform-collector.md` | 8252 | `c7f84e3e14935b95cc7fcebb523475e0052c8bc487ea028194f70e4f37f10522` |
| `docs/design/kitty-2026-11-02-checkpoint-ruling.md` | 10972 | `088ce851db72a5b0aa66a8011660d651d75c3806dc249d39670e7c38b51eea9a` |
| `docs/phase-reports/kitty-2026-11-02-platform-collector.md` | 9797 | `5c5a5d7ead0d0de76578b5b06154506caee5cf785799b56587bc439b6ae8a472` |

Total payload: **64275 bytes**. Each current file was compared to its exact accepted
Git blob and manifest byte count/hash. The historical build-only labels inside these
immutable files remain as checkpoint history; later conditional delivery approval is
recorded separately, not by changing reviewed payload bytes.

## DONE

- Added one standalone stdlib-only Python packet. It can itself live outside a checkout
  and run from any working directory. It reads the local source clone's Git objects;
  it does not use the owner's working tree as the executable source.
- Default source repository is HOME/Elaria; a local-path override is the only source
  option. No ref, executable, expected-hash or fetch override exists. The fixed source
  is the accepted commit, not HEAD or a branch name.
- Uses fixed local `git cat-file blob` requests with **--no-lazy-fetch**,
  --no-replace-objects, --no-optional-locks, protocol denial and disabled fsmonitor.
  No remote download, fetch, checkout, branch switch, worktree, installation, config
  write, hook, textconv or shell is requested. Owner mainline stays in place.
- Git receives a positive environment, fresh empty child HOME, no global/system Git
  config, no inherited credentials/agent/loader/Git-injection variables, DEVNULL input,
  closed application descriptors and a private process group.
- Each Git call has a 20-second deadline, stdout capped at the exact expected blob
  size, stderr capped at 4096 bytes and a two-second reap bound after group termination.
  Unsupported Git flags/missing objects/overflow/timeouts stop; there is no fallback.
- Creates a fresh private HOME kit, verifies all five file hashes before persisting their
  bytes, verifies all five extracted files before writing `delivery.json`, and repeats
  that full on-disk gate immediately before any collector handoff. Unsafe files refuse.
- Default creates no collector evidence directory and executes no collector. An explicit
  run choice replaces the packet process with fixed `/usr/bin/python3`, isolated mode
  and bytecode disabled, executing **only** the verified collector. The unchanged
  collector retains its query/output/deadline controls; no wrapper timeout can orphan
  its independently grouped queries. Tests/docs are never executed.
- New kit directories are 0700 and files 0600. Existing kits are not reused. No cleanup,
  overwrite, move or repair. Failures leave a printed, locatable private partial kit.
  Delivery receipts never claim collection complete, compatibility or hardware proof.
- **50 new synthetic tests** exercise every manifest entry's corrupt/short/long refusal,
  missing objects, unsupported Git, default non-execution, explicit handoff, file modes,
  final-gate tampering, time/output bounds, environment controls and preservation of a
  synthetic mainline checkout. Every Git/execution call in tests is stubbed.

## Precision correction: empty HOME is not an SSH filesystem sandbox

The design approval's empty-HOME rationale needs this qualification: OpenSSH can derive
home-directory paths from account information. Empty HOME alone does **not** structurally
prove that it cannot reach ~/.ssh. The collector relies on the combined controls of
fixed version/no-destination-usage/query arguments (no connection/config-evaluation
mode), removed agent environment and closed application descriptors, with empty HOME as
additional isolation for programs consulting it, including RPM. Neither instrument is
an OS filesystem/network sandbox or protection against compromised system executables.
No command/configuration scope was broadened to make this clarification.

## Verbatim local gates

```text
Python 3.11.2
```

Combined kitty/collector/packet suites:

```text
296 passed in 1.98s
```

Full suite:

```text
2399 passed, 6 skipped in 94.11s (0:01:34)
```

Ruff:

```text
All checks passed!
```

Arithmetic: accepted **2349 + 50 = 2399**; lane **246 + 50 = 296**.
Full log: `.venv/kitty-owner-packet-suite.log` (ignored/local).
No known running_daemon teardown intermittent occurred in this full run. Shared fixtures
and all accepted tests remain untouched. A new handoff test initially kept mocked OS
functions active during temporary-fixture cleanup (296 passed, 1 teardown error); only
that new test was corrected to restore its mocks using a scoped monkeypatch context.
It was not the known running_daemon quirk and no fixture fix was made.

All gates are local-runner-only, not automated CI or owner hardware evidence. **No Python
3.14 run occurred**, and none was sought. A local Python 3.11 flags-only check confirmed
that the committed executable shebang's combined -IB enables isolation and disables
bytecode; this was not a collector or owner packet execution.

## Limits / missing owner evidence / next gate

Git's no-lazy-fetch behavior was checked against v2.48.0 `Documentation/git.txt` and
`git.c`. The sandbox's Git is **2.39.5**; no supported-Git live packet run is claimed.
Owner Git capability is unmeasured. An explicit unsupported option must stop rather
than be silently ignored; the packet will not retry after removing that guard. Do not
install/upgrade Git or fetch objects automatically to work around a failed packet.

Local Git repository configuration/object storage is read; this is not an OS sandbox.
Private kit permissions and last-moment hashes are delivery controls, not protection
against an adversarial same-UID process rewriting files between check and use. The
bootstrap hash must be checked externally before Python. Delivery verified is not
collection complete; collection complete is not compatibility or semantic/hardware proof.

Five Git reads give at most 110 seconds of nominal timeout/reap budget before the
collector's existing nominal 308-second process budget. No hard bound on filesystem/OS
stalls is claimed. Both instruments remain read-only with respect to owner application
state/configuration, with only their explicitly documented private-output writes.

No returned owner drift/RPM/collector evidence was received in this turn. The relayed
`kitten 0.47.1` reading is still not Fedora release or downstream-patch equivalence.
No version/source pin is promoted into an unobserved owner fact. The approved drift
files and inventory are unchanged. No adapter or in-principle assessability work was
performed in this delivery tranche; existing partial/blocked status remains.

**Priority LOW.** Design/owner may retrieve and verify the committed packet and schedule
it under the conditional ruling when appropriate. No owner hardware action is requested
now. Voice-chain work takes precedence. The kitty scene remains NOT READY; subsequent
adapter sequencing and independent evidence rules remain unchanged.

## Structural boundary / diff

```text
 docs/kitty-platform-owner-packet.md                 | 131 +++++++++++++++++
 docs/phase-reports/kitty-2026-11-02-owner-packet.md | 192 ++++++++++++++++++++++++
 tests/test_kitty_owner_packet.py                    | 319 ++++++++++++++++++++++++++++++++++++++++
 tools/kitty/owner_run_platform.py                   | 240 ++++++++++++++++++++++++++++++
 4 files changed, 882 insertions(+)
```

All **283 accepted parent files remain byte-identical**, including every runtime, tool,
test, design ledger, collector-checkpoint document and both approved drift files. Only
four new packet-owned tool/test/documentation files are added. Of the 247 pre-kitty
files, 246 remain byte-identical; daemon.py is still the exact accepted mount, and
subtracting the same eight insertions reproduces the pre-kitty daemon bytes. **No new
protected hunk. Extra diff NONE.**

The sandbox again arrived with local Git metadata at ed20344 and the accepted files on
disk. The remote still pointed to a0e1aa8. After fetching only this lane, all 283 files
and the absence of extra nonignored files were verified before restoring local HEAD/
index to the accepted commit. No file content, branch identity or remote history was
changed by that restoration. The test environment was recreated only under ignored .venv.

## Artifacts

- `tools/kitty/owner_run_platform.py` — exact committed delivery/run packet and manifest.
- `tests/test_kitty_owner_packet.py` — 50 new synthetic regressions.
- `docs/kitty-platform-owner-packet.md` — standing rule, bootstrap, controls, limits and scheduling.
- This report — packet identity, all five pinned hashes, gates, structural audit and missing evidence.
