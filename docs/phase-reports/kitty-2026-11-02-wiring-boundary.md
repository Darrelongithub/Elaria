# KITTY HANDS v1.1 — adopted errata / protected wiring wall, 2026-11-02

**NOT DONE. TESTED-ONLY checkpoint; owner scene remains NOT READY.**

Branch: `arena/b65d5161-elaria` (active, design-accepted in place).
Accepted foundation: `66e154a9d68fcae7542045f7f6f7f70360ba2333`.
This checkpoint's resulting SHA is supplied in the delivery message. No PR, no merge,
no branch switch, no force-push. The separate console SHA `35adbbaf` is untouched.

## DONE at this checkpoint

- Recorded design's acceptance and **lane-attribution correction** in
  `docs/design/kitty-2026-11-02-checkpoint-ruling.md`: the earlier “explicit A” was
  sequencing-only, not lane authorization. Placement is accepted by this new design
  ruling; future kitty cherry-picks onto a hands-tip-based branch remain the remediation.
  The console cherry-pick plan is unaffected. Historical reports are retained with this
  explicit superseding correction, not silently rewritten.
- Added `K3-send-key-exclude-active-unenforced-0.47.1` to both the `send-key` verb's
  hazards and its `--exclude-active` option hazards in the generator and inventory JSON.
  Regenerated the human reference. `send-key` remains K3, including HER-window acts.
  `set-os-window-title` remains absent; Hyprland setup remains version-matched 0.57 Lua.
- Extended the fresh pre-send ls/identity/focus observation and independent adjudication
  to **both** `send-text` and `send-key`. A late PID/program change, active broadcast
  target or new gate denial prevents dispatch. A successful key-send response still
  does not count as an independently observed effect. Snapshot exclusion is **not**
  claimed atomic or trustworthy as a substitute for the broken upstream flag.
- Added **8 synthetic regressions** (67 kitty tests total). They cover machine hazards,
  K3 despite HER IDs/session hand-open, four late target/focus changes, late gate denial,
  and successful dispatch remaining UNVERIFIED without effect evidence.
- Inspected production/frozen entrypoints read-only and documented the precise
  protected-file mounting wall. No attempt was made to evade the hold.

## Gates — verbatim, including the failed run

New/kitty tests:

```text
67 passed in 0.61s
```

Ruff:

```text
All checks passed!
```

First full-suite attempt (**NOT a clean gate**):

```text
ERROR tests/test_gate_fix_round.py::test_hold_to_talk_ptt_start_stop_still_works
2170 passed, 6 skipped, 1 error in 103.44s (0:01:43)
```

Teardown at unchanged `tests/conftest.py:91` attempted
`task.get_coro().__qualname__` on an `async_generator_athrow` object, producing
`AttributeError`. No test body failed. This is a recorded intermittent teardown defect,
not a claim that its underlying cause has been diagnosed or fixed. Neither the shared
fixture nor daemon was modified, and no assertion/skip was weakened to obtain green.

Focused rerun:

```text
1 passed in 0.28s
```

Full-suite rerun (clean):

```text
2170 passed, 6 skipped in 101.69s (0:01:41)
```

Arithmetic: accepted 2162 + 8 = 2170. Gates are **local runner only**. No automated CI
was added or claimed; no live kitty, owner hardware/content or model endpoint was used.

## DEFECTS FOUND / wall

`Daemon._handlers()` in protected `src/assistant/daemon.py` is a fixed dispatch table;
`Daemon.handle()` establishes the kernel-authenticated owner principal before routing.
There is no public registration hook for a new kitty host. The frozen hands bridge has
fixed synthetic methods/fixtures, and `SandboxCore` explicitly requires `FakeRunner`.
Adding a standalone module is not honest production wiring into these entrypoints.

**Stopped before protected/frozen edits.** No copied/replacement daemon, monkey-patch,
second service, synthetic-runner substitution or legacy T3 override. A bounded mount
proposal is documented in the design ledger; it is not implemented or authorized.
The first full-suite attempt's teardown error is also recorded above, not concealed
by the clean rerun.

## NEXT GATE / exact design decision requested

**A — Preserve the absolute protected-file hold.** Continue additive implementation
and stub tests only; production host mounting remains held and the owner scene stays
NOT READY. Other additive work is not technically blocked by this wiring decision.

**B — Authorize a narrow exception for `src/assistant/daemon.py` only:** minimal kitty
lifecycle state; fixed bound-method IPC delegates; use of `_require_ipc_owner()`; and
shutdown cleanup in `Daemon.aclose()`. All substantive checker/policy/recovery/protocol
logic stays in additive `hands/kitty/` modules. No startup connection, automatic hand
opening, model-origin approval, other protected/frozen edit, new daemon or live sandbox
kitty test. Any need to broaden scope triggers another stop-and-ask.

This is a request to design through the owner, not an assumed thaw. Neither option
changes existing T3, password secrecy, no-PR or hardware holds.

## Remaining scope and drift-script status

Trusted-host wiring, full per-verb target/effect coverage, durable recovery/cancellation,
Fedora/OpenSSH reconciliation and scene finalization remain unfinished. No claim is
made that this small checkpoint completed those tasks or that they all require a
protected edit.

`tools/kitty/drift.py` is unchanged from the accepted checkpoint. Its parser regressions
pass in the local suite. **No owner invocation/report or verbatim installed version has
been received**, so drift remains unreconciled. Ring 2 upstream ssh/transfer/remote-file
metadata is present; installed Fedora membership and OpenSSH options/defaults are not
yet established. `docs/kitty-owner-scene.md` remains **NOT READY TO RUN**; no hardware
session was scheduled. The builder has not declared it ready.

## Diff / extra-diff accounting

9 files changed, 364 insertions(+), 10 deletions(-) (relative to accepted `66e154a9`).

All 247 pre-kitty baseline files at `35adbbaf` are byte-identical. Only kitty-order files
from the accepted foundation and the two new kitty ledger/report documents change.
ZERO protected/frozen integration edits; extra diff **NONE**. Clause pin rechecked
before work: 14322 bytes, SHA256
`8be8a4a94e958e1fd0323d8e687418f73e6cfd407a5a08bb6720b75769ffb6bc`, unchanged.

## Artifact paths

- `docs/design/kitty-2026-11-02-checkpoint-ruling.md` — correction, errata, wall and exact A/B proposal.
- `src/assistant/hands/kitty/data/inventory.json` — explicit K3 hazard at verb and option level.
- `src/assistant/hands/kitty/data/inventory.schema.json` — unchanged schema, validation passes.
- `docs/kitty-inventory.md` — regenerated human reference.
- `docs/kitty-setup.md` — design attribution corrected; protected mount boundary disclosed.
- `src/assistant/hands/kitty/bridge.py` — both-send fresh observation/adjudication.
- `tests/test_kitty_hands.py` — 67 synthetic tests.
- `tools/kitty/build_inventory.py`, `tools/kitty/render_inventory.py` — reproducible hazard/ledger output.
- `tools/kitty/drift.py`, `docs/kitty-owner-scene.md` — unchanged; drift outstanding, scene NOT READY.
