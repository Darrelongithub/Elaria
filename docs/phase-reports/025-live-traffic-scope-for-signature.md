# WP7 — bounded live-traffic scope, for the owner's signature

**Date:** 2026-11-04 · **Branch:** `arena/storage` @ `240bb3d` · **PR:** #24
**Status:** DRAFT — awaiting the owner's grant word through design chat. **No live operation has run and none will before that word arrives.**

This authorises **exactly four MEGA-touching operations, in one order, under Sheet 1's caps, with two owner-time items among them.** Anything not listed here is out of scope and stays unrun.

---

## The four operations, in order

| # | Operation | Touches MEGA? | Whose time | Depends on |
|---|---|---|---|---|
| **1** | **Sheet-1 benchmark** — `scripts/storage-benchmark.sh` against two scratch repos | **Yes** — ~1 GB synthetic upload | Owner | nothing |
| **2** | **End-to-end restic-over-MEGA ratio** — computed from operation 1's numbers | No new traffic | Builder | 1 |
| **3** | **Kept-wav cold transition** — one resolved kept wav goes cold: flip + grace-trash trim | **Yes** — one real artifact | Owner authorises, builder runs | 2 |
| **4** | **Owner re-listen** — `assist backup fetch <artifact>` | **Yes** — one download | Owner | 3 |
| **5** | **One live monthly drill** — restore to tmp + hash-verify + `restic check` | **Yes** — one bounded read | Builder | 3 |

**The order is the dependency order, and it is not negotiable in the other direction.** The benchmark comes first because nothing should touch MEGA before we know the backend works at all. The ratio comes second because the capacity model — and therefore whether operation 3 is even sensible at current volume — depends on it. The cold transition comes third because it is the first *real* artifact to leave the laptop, and it should not happen until the ratio is known. The re-listen comes fourth because there must be something cold to fetch. The drill comes last because it is the verification that all of the above actually worked end to end.

## The caps — Sheet 1's, verbatim

Nothing in this scope exceeds a cap Sheet 1 already set:

- **~1 GB total synthetic upload**, split across two scratch repos (default 16 MiB pack, and 32 MiB pack).
- **One local ~500 MB tree** built by the script, random and incompressible.
- **Small-file fetch ×10** at 4096 bytes each, at both pack sizes.
- **One ~500 MB restore** per repo.
- **`restic check`** per repo.
- **`restic check --read-data-subset` capped at ≤5% or ≤500 MB, whichever is smaller.**
- **Free tier is 20 GB**; downloads count against a **rolling per-IP quota**, so the re-listen and the drill are budgeted from Sheet 1's measured rows 12–21 and nothing else.

**Latency budget:** ruled from Sheet 1's rows 12–15 only. Until then, no claim about fetch latency exists anywhere — not in code, docs, or chat.

## The two owner-time items — one line each

- **Operation 3, the cold transition:** *Name one resolved kept wav to send cold, in one line, and I will do the rest.*
- **Operation 4, the re-listen:** *Run `assist backup fetch <artifact>` and listen, then tell me in one line whether it played.*

## The stop condition

**The scope stops immediately — without a further decision, and without me asking — if any one of these happens:**

1. MEGA login-blocks or rate-limits the account at any point (Sheet 1 row 23).
2. `restic init` or the first backup cannot complete inside a sane window — that is a **no-go on the backend**, and the options go back to the owner with the numbers attached, never a silent workaround.
3. **Any credential appears** in a log line, sensor event, journal entry, phase report, PR or chat message.
4. **Any real owner content leaves the laptop** other than the single wav authorised in operation 3.
5. The capacity-floor knock fires — `remote_free` below 10 GB, reading exactly *"Elaria wants to talk"* with zero content.

**Cleanup is an owner decision and never automatic.** Auto-delete does not exist in this lane. When the benchmark is finished, the owner removes the scratch repos himself; the MEGA backend's trash means freed space may not appear immediately, which is a property of the backend and not a leak.

## Explicitly NOT in scope

FLAC · a second storage target · MEGA S4 (paid, out of scope under $0) · any scheduled quarterly drill (owner-initiated only, by ruling) · any second wav going cold · any change to the nightly or monthly timers · anything touching `daemon.py`, `transcribe.py`, `live_client.py`, `HANDOFF.md` or `tests/conftest.py`.

## Signature

| | |
|---|---|
| Owner authorises operations **1–5** as scoped | ☐ |
| Owner authorises the **order** as written | ☐ |
| Owner names the **one wav** for operation 3 | ______________________ |
| Owner confirms the **stop condition** is understood | ☐ |
| **Grant word received through design chat** | ☐ |

*Nothing above runs until that last box is ticked by a relayed owner word.*
