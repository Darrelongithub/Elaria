# OWNER SITTING SHEET — WP7 live operations, in order

**Ruling applied (2026-11-08):** the builder's sandbox is incapable of the live operations **by policy, not by omission**. MEGA is network-blocked there (curl exit 35 while github.com returns 200), restic and rclone are absent, and your audio directory is deliberately not in it. The grant was permission; it was never a route. **Therefore operations 1–5 are owner-run packets on your machine.**

**Issued:** 2026-11-08 · **Branch:** `arena/storage` · **PR:** #24
**Rule throughout:** numbers-only or records-only returns. **Never a path, never a filename, never content.**

---

## The order — do not reorder

| Step | What | Packet | Depends on |
|---|---|---|---|
| **0** | Check restic and rclone present; install if absent | this sheet | nothing |
| **1** | The benchmark | `sheet1-benchmark-packet.md` (`ec1a293`) | step 0 |
| **3** | Flip `20261102-100558-61258b` cold | `op3-cold-flip-packet.md` | steps 0, 1 — **and the window: not before 2026-11-16 10:06** |
| **5** | One live monthly drill | `op5-monthly-drill-packet.md` | step 3 — something must be cold to drill |
| **4** | The fetch line, and your one-line ear | issued after step 3 | step 3 |
| **2** | The end-to-end restic-over-MEGA ratio | computed by the builder | step 1's numbers only — **no new traffic** |

Steps 4 and 5 can overlap: the drill does not need your ear, only the cold artifact.

---

## STEP 0 — the tools

```bash
command -v restic && restic version || sudo dnf install -y restic
command -v rclone && rclone version || sudo dnf install -y rclone
```

**rclone must be at or above 1.41.0** — the MEGA backend was added in 1.41 and is Tier 2. **1.75.2 is the pinned target.** If your distro ships older, the machinery reports a declared skip rather than guessing; install a newer build if you can, and tell me the version you ended up with.

Confirm a remote is configured — you created `elaria-mega` yourself in `rclone config`, and the MEGA password is obfuscated by rclone inside your own 0600 file, outside the repo:

```bash
cd ~/Elaria && assist backup status
```

It must **not** say `remote_free=unknown (no remote configured)`. If it does, set `rclone_remote` in `[backup]` first.

---

## STEP 1 — the benchmark

```bash
cd ~/Elaria && sha256sum -c docs/live-scene/sheet1.SHA256SUMS && bash scripts/storage-benchmark.sh
```

The `sha256sum -c` half proves the files are byte-identical to the committed ones. **If it prints anything but two `OK` lines, stop and report it.**

**Pre-flight:** restic and rclone present and at version; `RESTIC_REPOSITORY_BASE`, `RESTIC_PASSWORD_FILE` (your 0600 file) and `RCLONE_CONFIG` exported in your own shell. **No credential is ever typed inline.**

**What it does, and the caps — Sheet 1's, verbatim:**

| | |
|---|---|
| Synthetic upload | **~1 GB** across two scratch repos (16 MiB pack, and 32 MiB pack) |
| Local tree | one **~500 MB**, random and incompressible |
| Small-file fetch | **×10** at 4096 bytes, at both pack sizes |
| Restore | one **~500 MB** per repo |
| `restic check` | once per repo |
| `restic check --read-data-subset` | capped at **≤5% or ≤500 MB, whichever is smaller** |

**Expected duration — named honestly.** I cannot give you a wall-clock figure, because *measuring it is the entire point of this step.* What I can name is the work: **~1 GB up, ~500 MB down per repo, two `restic check` passes, and four slow MEGA listings.** On a free account this can take a long time. **Leave it running and come back** — Sheet 1's own guidance. The script prints per-step timings as it goes, so you can see it is alive rather than stalled.

**F24 note:** the benchmark is not itself gated on remote headroom, but operation 3 is. If the benchmark leaves `remote_free` low, step 3 will refuse and tell you by how much.

**Returns:** Sheet 1's return sheet, **numbers only** — rows 1–23, including the end-to-end ratio, the latency figures that rule the fetch budget, and whether the remote was ever login-blocked. Paste the numbers; do not paste anything else.

---

## STEP 3 — the cold flip

**Pre-flight:** steps 0 and 1 done; `remote_free` ≥ **2,719,664,640 B (2.53 GiB)** — that is **1,719,664,640 B of scratch** (500 MiB × 2 repos of payload, plus restic's temp space at 128 MiB × (4 backend connections + 1)) **plus a 1 GB margin**; and **the window has elapsed**.

```bash
cd ~/Elaria && assist backup run --dry-run
```

Then, only when that reports `send_cold=1`:

```bash
cd ~/Elaria && assist backup run
```

**The window, stated plainly:** the named wav is from **2026-11-02 10:05:58** and the hot window is **14 days**. It becomes sendable cold on **2026-11-16 after 10:06**. **Run before then and it reports `send_cold=0` and changes nothing** — the window holding, not a failure.

**Verify it flipped the right thing and nothing else:** `send_cold` must read exactly **1**; in your own audio directory the only file older than 14 days must be the named wav; after the real run it must be gone from the audio directory and in trash; and `assist backup status` must show the cold count up by exactly 1. **If `send_cold` is not 1, stop and report.**

**Returns:** records only. The tool's output is path-blind by design — counts and bytes, never names. You verify against your own filesystem, which you own.

---

## STEP 5 — the live monthly drill

```bash
cd ~/Elaria && assist backup check --kind monthly --record
```

**Pre-flight:** something is cold (step 3); local free space ≥ artifact size + **1 GB margin** — the F24 gate checks this **before any restore write** and names the requirement in the record; restic present, or the `restic check` half is a **declared skip**, never a pass.

**Returns:** records only — the drill's own line, and `assist backup check --kind monthly --last` for the recorded outcome. **Failed drills record exactly as passes do**, because a journal that only shows passes is not evidence.

---

## STEP 4 — the fetch line, and your ear

Issued by the builder once step 3 has flipped something cold. It will be one line:

```bash
cd ~/Elaria && assist backup fetch 20261102-100558-61258b
```

**All I need back is one line:** did it play, and roughly how long did it take. The latency budget for `assist backup fetch` is ruled **only** from Sheet 1's rows 12–15 — nothing else may set it, and until those numbers exist no fetch-latency claim exists anywhere.

---

## THE MEGA-TRASH CAVEAT, REPEATED

The rclone MEGA backend puts deletions into MEGA's trash unless `--mega-hard-delete` is set, so **freed space may not appear immediately. That is a property of the backend, not a leak.**

---

## CLEANUP IS YOURS AND NEVER AUTOMATIC

**Auto-delete does not exist in this lane.** When the benchmark is finished, Sheet 1's cleanup block removes the scratch repos — deliberately, by you. The trim move in step 3 is not deletion; the purge after the 14-day grace is the only path to a single copy, and it is a recorded decision, never an automatic one.

---

## STOP CONDITIONS — self-firing, at any step

1. **MEGA login-blocks or rate-limits** → stop, report.
2. **`restic init` or the first backup cannot complete in a sane window** → a no-go on the backend. Report it; do not work around it.
3. **A credential appears** in any output, log, journal or file outside your own 0600 files → stop, report.
4. **Any real owner content leaves the laptop other than the named wav** → stop, report.
5. **`remote_free` drops below 10 GB** → the capacity-floor knock fires, reading exactly *"Elaria wants to talk"* with zero content.
6. **`send_cold` is not exactly 1** in step 3 → stop, report.
7. **The restored hash MISMATCHES, or `restic check` fails** → stop, report. Do not re-run for a better answer; the failure *is* the answer, and it is recorded.

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
