# WP7 gate — the live grant, and what this sandbox can and cannot do

**Date:** 2026-11-08 · **Branch:** `arena/storage` @ `3acce3f` (pushed) · **PR:** #24
**Suite:** 2189 passed / 6 skipped in 170.32 s · **ruff:** All checks passed
**Frozen branch (condition 3):** `origin arena/e7a1cca5-elaria = b181712563c1577f5faea4e59fe5f7e104a89ed1`, verified before and after this activation. Untouched.

---

## The grant, and what it does and does not change

The owner's grant landed on 2026-11-08, quoted verbatim:

> **"mega-live yes. wav: 20261102-100558-61258b"**

It reached design chat via a paste of his terminal, where bash had rightly refused to execute it. No machine acts on those words but his, and his has not either — **only his permission has.** Recorded as his word, and the wav is named: `20261102-100558-61258b`. No substitution, no additional artifact.

**What it changes:** operations 1–5 are authorised. The wav is named. The stop conditions remain as written.

**What it does not change:** the physical facts of this sandbox. The grant is permission; it is not a network route, a credential, or a copy of his wav.

---

## Why the live operations still cannot run here — three measured reasons

| # | Fact | How it was measured |
|---|---|---|
| 1 | **MEGA is network-blocked** | `curl https://mega.nz/` → exit 35 (SSL connect error); `curl https://github.com/` → HTTP 200. DNS resolves for both, so this is a policy block, not a resolver failure. |
| 2 | **restic and rclone are ABSENT** | `command -v restic` and `command -v rclone` both return nothing. |
| 3 | **The named wav is not here** | `find / -name "20261102-100558*"` returns nothing, and `audio/` does not exist at all. As doctrine requires — the owner's real content never enters this sandbox. |

These are not matters of permission. The grant does not create a route to MEGA, install a binary, or copy a recording into a sandbox that is fenced against exactly that. **So the honest reading of the grant is: it authorises operations that this environment is built to be unable to perform.**

---

## DONE table — the gate's seven conditions, with live rows

| # | Gate condition | State | Evidence |
|---|---|---|---|
| 1 | Benchmark numbers ruled go | **BLOCKED — owner-run** | Packet `ec1a293` re-confirmed; the owner has not run it. No numbers exist to rule on. |
| 2 | A resolved kept-wav goes cold with manifest flip + grace-trash trim | **BLOCKED — no network, no wav, no restic** | The **machinery is proven**: `scripts/warm-cold-transition.py` walks `local → uploaded → flipped → trashed → purged` through the real reconcile code, against a local-path fixture. The **live transition is unrun.** |
| 3 | Crash-point tests green | **MET** | `tests/test_wp7_reconcile_crash_points.py` — 23 passed. |
| 4 | Owner re-listens via `assist backup fetch` inside the ruled latency budget | **BLOCKED — downstream of #2** | The budget is ruled from Sheet 1's rows 12–15, which do not exist yet. |
| 5 | One live monthly drill passes | **BLOCKED — owner-run** | The drill machinery is proven end-to-end (increment 8); the live drill is unrun. |
| 6 | Ladder chain #5 including the integrity rung all REACHED | **MET** | `backup_chain` at `ladder.py:764`; 64 tests. |
| 7 | Zero credentials in repo or chat | **MET** | Grep across `src/`, `scripts/`, `systemd/` returns nothing; no MEGA password anywhere. |

**Three met, four blocked — and the four are blocked on the network, not on builder work.** The machinery for two of them (#2, #5) is now proven against a fixture; only the network leg is missing.

---

## STEP 0 — issued, and what it will find

**The line:** `cd ~/Elaria && python3 scripts/storage-census-check.py --audio ~/Elaria/audio --manifest ~/.local/share/assistant/backup/manifest.jsonl`

I could not run it here: `audio/` does not exist in this sandbox. So it is issued as an owner-run packet (`docs/live-scene/step0-census-line.md`), with a checksum manifest covering all four files it touches.

**The check found two things while being built that matter for the owner's own reading of his numbers:**

1. **`du -sb <dir>` includes the directory inode's own apparent size** — 4096 on ext4. Measured: files 176,283 + directory 4,096 = `du -sb` 180,379. The script subtracts it and discloses the raw figure alongside.
2. **`du -sb` counts the never-retry marks; the census must not.** A ruling says the 44-byte header-only file counts zero forever.

So when the owner reports roughly 600 MB with four visible marks in it: **his `du -sb` will not equal the manifest arithmetic, and it should not.** The gap should be exactly the marks' bytes. Any other gap means the walk dropped a real recording — which is why the check refuses to report a number rather than reporting one it cannot reproduce.

---

## The owner-time lines

| # | Line | Answered? |
|---|---|---|
| STEP 0 | the census line above | **Issued, awaiting the run.** |
| 1 | `cd ~/Elaria && sha256sum -c docs/live-scene/sheet1.SHA256SUMS && bash scripts/storage-benchmark.sh` | **Issued, awaiting the run.** |
| 3 | *wav `20261102-100558-61258b` — the owner has named it.* | **Named. Awaiting an environment that can reach MEGA.** |
| 4 | *Run `assist backup fetch` and listen, then tell me in one line whether it played.* | **Not yet issuable** — needs the cold artifact. |

---

## Stop-condition log

**EMPTY.** No stop condition fired, because no live operation ran. Nothing stopped; nothing needed to.

---

## Defects found in my own work this activation

Three, all real, all fixed, all now pinned by tests:

1. **`du -sb <dir>` includes the directory inode** — the check was comparing two different quantities.
2. **The census must exclude never-retry marks while `du -sb` includes them** — now the difference must equal the marks' byte total exactly, to the byte.
3. **The fifth quietly-wrong fixture:** my chunked-mark fixture declared a LIST chunk of 10 bytes and carried 11, so the chunk walk landed on `!dat` instead of `data`. The same trap as the fourth. Fixed by making the fixture self-consistent.

---

## Terminal state

**The build is complete at increment 8. Gate 1 remains open on its four live conditions, and the reason is now measured rather than assumed: MEGA is network-blocked here, restic and rclone are absent, and the owner's wav is deliberately not in this sandbox.**

The machinery for the cold transition and the drill is proven against a local-path fixture. What remains unproven is the network leg, and no amount of builder work in this sandbox can prove it.

**`trim_grace_days` remains INTERIM-PENDING-SHEETS**, the only interim value in `[backup]`. This cycle produced no grace-trash data — no live cycle ran — so the finalization question is **not raised** and the gate's grace-trash condition stays **provisional in writing**. No silent finalization.

**Cleanup is the owner's decision and never automatic.** Note for when the benchmark does run: the rclone MEGA backend puts deletions into MEGA's trash unless `--mega-hard-delete` is set, so freed space may not appear immediately — a property of the backend, not a leak.

**The merge is not mine.** It stays design-gated behind the owner's SC-H1 and the merge hold. PR #24 remains open with 29 commits; nothing merges until the design chat rules the mainline gate passed.

---

## Commits this activation

| SHA | Content |
|---|---|
| `3acce3f` | STEP-0 census check + cold-transition machinery proof; firing-eight record |
