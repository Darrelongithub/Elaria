# OPERATION 3 — owner-run packet: flip `20261102-100558-61258b` cold

**Ruling applied:** operations 1–5 are **owner-run packets on the owner's machine**. The builder's sandbox is incapable of the live operations *by policy*, not by omission — MEGA is network-blocked here (curl exit 35 while github.com returns 200), restic and rclone are absent, and the owner's audio directory is deliberately not in the sandbox. The grant was permission; it was never a route.

**Artifact:** `20261102-100558-61258b` — the owner's explicit pick. **No substitution, no additional artifact.**
**Issued:** 2026-11-08 · **Branch:** `arena/storage` · **PR:** #24

---

## READ THIS FIRST — the window arithmetic, or the run will do nothing

The tiering engine sends an artifact cold when it is **older than 14 days** (`hot_window_days`, FINAL-CENSUS), or when the HOT set exceeds 2 GB — whichever binds first. At the measured growth of 11–13 MiB/day the **14-day window binds long before the cap** (14 days of growth is ~0.15–0.18 GiB against a 2 GiB cap).

The named wav's name encodes its capture: **2026-11-02 10:05:58**.

| Run on | Age | Result |
|---|---|---|
| 2026-11-08 (the grant date) | 5 d | **HOT — nothing is sent** |
| 2026-11-15 | 12 d | **HOT — nothing is sent** |
| **2026-11-16, after 10:06** | 14 d | **COLD — sendable** |
| 2026-11-17 or later | 15 d+ | **COLD — sendable** |

**If you run operation 3 before 2026-11-16 10:06, it will report `send_cold=0` and change nothing.** That is not a failure — it is the window holding. Run the dry-run first and it will tell you before anything moves.

---

## The one line

```bash
cd ~/Elaria && assist backup run --dry-run
```

Then, only when that reports `send_cold=1`:

```bash
cd ~/Elaria && assist backup run
```

---

## Pre-flight — stated, because a gate that is skipped is not a gate

| # | Check | Command | Refuse when |
|---|---|---|---|
| 1 | **restic present** | `restic version` | absent |
| 2 | **rclone present and at/above the 1.41.0 floor** | `rclone version` | absent, or below 1.41.0 (the MEGA backend needs ≥1.41; 1.75.2 is the pinned target) |
| 3 | **A remote is configured** | `assist backup status` | `remote_free=unknown (no remote configured)` |
| 4 | **F24 remote headroom** | read automatically by `run` | `remote_free` unreadable, or below **2,719,664,640 B (2.53 GiB)** = 1,719,664,640 B scratch + 1 GB margin |

**Check 4 is the F24 gate and it runs before any planning**, so a run that cannot finish never starts. The scratch is *derived, not asserted*: 500 MiB × 2 repos of payload, plus restic's temp space at 128 MiB × (4 backend connections + 1) — every term checkable against `scripts/storage-benchmark.sh`.

An **unreadable** `remote_free` is a refusal, never a pass. The gate reads it through the pinned `rclone about <remote>:<path> --json`; if rclone is absent the reading is unreadable and the run refuses.

---

## How to verify it flipped the RIGHT artifact and nothing else

The tool's output is **path-blind by design** — counts and bytes, never names. That is the privacy fence, and it is not a limitation to work around. You verify against your own filesystem, which you own:

1. The dry-run must report **`send_cold=1`** and `binding=age`.
2. In your own audio directory, the **only** file older than 14 days must be the named wav.
3. After the real run, the named wav must be **gone from the audio directory** and present in trash.
4. `assist backup status` must show the manifest's cold count went **up by exactly 1**.

**If `send_cold` is anything other than 1, stop and report it.** Do not proceed on the assumption it is the right one.

---

## What the record looks like

The manifest records the flip path-blind. Expect, in order: `local → uploaded → flipped → trashed`. The `flipped` record names **which backend confirmed it** — increment 4's provenance requirement made structural, so a fixture's confirmation can never read as real remote confirmation.

The trim moves the file to **local trash under a stamped name**, and the grace clock starts. **Two copies exist during the grace**, and that silence is the copy-count invariant holding, not a missed action. The purge happens only after `trim_grace_days` (14, still INTERIM-PENDING-SHEETS).

---

## Stop conditions — self-firing, no decision needed

1. **MEGA login-blocks or rate-limits** at any point → stop, report.
2. **`restic init` or the first backup cannot complete in a sane window** → that is a no-go on the backend. Report it; do not work around it.
3. **A credential appears** in any output, log or file outside your own 0600 files → stop, report.
4. **Any real owner content leaves the laptop other than the named wav** → stop, report.
5. **`remote_free` drops below 10 GB** → the capacity-floor knock fires, reading exactly *"Elaria wants to talk"* with zero content. Stop, report.
6. **`send_cold` is not exactly 1** → stop, report.

---

## What comes back to me

**Records only, never paths.** Paste the tool's output from the dry-run and the real run, and the one-line answer to: *did the named wav leave the audio directory, and did anything else?*

---

## Cleanup — never automatic

**Auto-delete does not exist in this lane.** The trim move to local trash is not deletion. The purge after the grace is the only path to a single copy, and it is a recorded decision, never an automatic one.

**The MEGA-trash caveat, repeated:** the rclone MEGA backend puts deletions into MEGA's trash unless `--mega-hard-delete` is set, so freed space may not appear immediately. **That is a property of the backend, not a leak.**

---

## Checksums
```
4eaca9f76aceee08a8bd972f46c67ed0720a3be12eb08c203a399b8725a1e6fb  scripts/storage-benchmark.sh
5daedf0d540c9392af7ce4bc938748fd30d5a31d36497e3d056897839e9faf22  scripts/storage-census-check.py
3b896526f1bde522e37e51d8804add0012490f30d7b12ef5d546c3dc8cf913bb  scripts/warm-cold-transition.py
dfbc44efbce3be1c45a45f3d8dec1ee2a4572bb35e5023279691d715a28b0362  src/assistant/preflight.py
31c9e602337ef7b3233f4115ff8116ab55b358f2106f5698c014607dd9cf8086  src/assistant/backup_cli.py
c7c8cfc985afa997d734865cfff0d37d01559d625e216c8ef49860bd1e7fce4e  src/assistant/remote.py
```
