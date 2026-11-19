# WP7 gate — F24 pre-flights built; the live grant still blocked by the sandbox

**Date:** 2026-11-08 · **Branch:** `arena/storage` @ `52908da` (pushed) · **PR:** #24
**Suite:** 2207 passed / 6 skipped in 168.08 s · **ruff:** All checks passed
**Frozen branch (condition 3):** `origin arena/e7a1cca5-elaria = b181712563c1577f5faea4e59fe5f7e104a89ed1`, verified before and after this activation. Untouched.

---

## The grant, and the three blockers re-measured

The owner's grant landed 2026-11-08, quoted verbatim:

> **"mega-live yes. wav: 20261102-100558-61258b"**

It reached design chat via a paste of his terminal where bash had rightly refused to execute it. No machine acts on those words but his, and his has not either — only his permission has. The wav is named; no substitution.

**Re-measured this activation, unchanged:**

| Blocker | Measurement |
|---|---|
| **MEGA is network-blocked** | `curl https://mega.nz/` → exit 35; `github.com` → HTTP 200. DNS resolves for both. |
| **restic and rclone are ABSENT** | `command -v` returns nothing for both. |
| **The named wav is not here** | `find / -name "20261102-100558*"` → nothing; `audio/` does not exist. |

The grant is permission. It is not a network route, a credential, or a copy of his wav.

---

## What was built: the F24 pre-flights

Spec v6 added two pre-flights and called them non-optional. Both are the same idea in two places: **check the space before you need it, and refuse rather than half-do it.**

### 1. The remote headroom gate — the knock prevents, it does not interrupt

`src/assistant/preflight.py`, wired into `_run()` before any planning.

- Reads `remote_free` and refuses to start below scratch-plus-margin headroom.
- **An unreadable `remote_free` is a refusal, not a pass** — the same posture as a missing restic being a declared skip. A gate that waves through a reading it never got is not a gate.
- **The scratch is derived, not asserted:** 500 MiB × 2 repos of payload, plus restic's temp space at 128 MiB × (4 connections + 1) = **1,719,664,640 B (1.60 GiB)**. With the 1 GB margin, **2,719,664,640 B (2.53 GiB) required**. A reader can check every term against `scripts/storage-benchmark.sh`.
- **A dry run is exempt.** It makes no remote traffic, so gating it on the remote would be the gate over-reaching.
- The capacity floor (10 GB consumed) is deliberately *not* the same test: a 20 GB tier sitting exactly at the floor still has room to run.

### 2. The local headroom gate — names the requirement in the record

Wired into `_check()` before any restore write.

Verified live, with an absurd margin:

```
backup check: REFUSED - headroom=REFUSED; reason=below local restore headroom;
              free=20368838656; required=10000000000008044 (scratch=8044 + margin=10000000000000000)
```

Exit 2. The record names the total **and its derivation**. A restore that dies at 90% because the disk filled has written a partial file and proved nothing — and a partial write is worse than no write, because it looks like a result.

---

## DONE table — the gate's seven conditions

| # | Gate condition | State | Evidence |
|---|---|---|---|
| 1 | Benchmark numbers ruled go | **BLOCKED — owner-run** | Packet `ec1a293` re-confirmed; unrun. **Now also gated by F24**: the run refuses below 2.53 GiB headroom. |
| 2 | Kept-wav goes cold, flip + grace-trash | **BLOCKED — no network, no wav, no restic** | Machinery proven (`warm-cold-transition.py`); live transition unrun. |
| 3 | Crash-point tests green | **MET** | 23 passed. |
| 4 | Owner re-listens in the ruled budget | **BLOCKED — downstream of #2** | Budget needs Sheet 1 rows 12–15. |
| 5 | One live monthly drill passes | **BLOCKED — owner-run** | Drill machinery proven (increment 8). **Now also gated by F24**: the drill pre-checks local free space before any restore write. |
| 6 | Ladder chain #5 incl. integrity rung | **MET** | 64 tests. |
| 7 | Zero credentials | **MET** | Grep returns nothing; no MEGA password anywhere. |

Three met, four blocked on the network. **Two of the four now have their F24 pre-flight in place**, so when the live environment does exist, the first thing it will do is check it can finish.

---

## One existing test needed a real fix

`test_run_refuses_without_a_verifier` set `ctx.verifier = None` but left `remote_free_bytes = None`. Since F24 the run now refuses at the headroom gate *first* — which is the point of a gate that prevents. The test now supplies ample headroom so it reaches the verifier check it was always testing. The original refusal is still covered, and the new precedence is pinned separately.

---

## Stop-condition log

**EMPTY.** No live operation ran, so no stop condition fired.

---

## Terminal state

**The build is complete at increment 8, plus the F24 pre-flights. Gate 1 remains open on its four live conditions, and the reason is measured rather than assumed: MEGA is network-blocked here, restic and rclone are absent, and the owner's wav is deliberately not in this sandbox.**

What has changed since the grant: the machinery for the cold transition, the drill, and now both F24 gates is proven and tested. What remains unproven is the network leg, and no amount of builder work in this sandbox can prove it.

**`trim_grace_days` remains INTERIM-PENDING-SHEETS**, the only interim value in `[backup]`. This cycle produced no grace-trash data — no live cycle ran — so the finalization question is **not raised** and the gate's grace-trash condition stays **provisional in writing**. No silent finalization.

**Cleanup is the owner's decision and never automatic.** When the benchmark does run: the rclone MEGA backend puts deletions into MEGA's trash unless `--mega-hard-delete` is set, so freed space may not appear immediately — a property of the backend, not a leak.

**The merge is not mine.** It stays design-gated behind the owner's SC-H1 and the merge hold. PR #24 remains open with 30 commits; nothing merges until the design chat rules the mainline gate passed.

---

## Commits this activation

| SHA | Content |
|---|---|
| `52908da` | F24 pre-flights; firing-nine record |
