# OPERATION 5 — owner-run packet: one live monthly integrity drill

**Ruling applied:** operations 1–5 are **owner-run packets on the owner's machine**. The builder's sandbox cannot perform this: MEGA is network-blocked here, restic and rclone are absent, and the owner's audio is deliberately not in the sandbox.

**Cadence:** monthly. This is the run the nightly/monthly timer carries; the quarterly drill stays owner-initiated by ruling.
**Issued:** 2026-11-08 · **Branch:** `arena/storage` · **PR:** #24

---

## The one line

```bash
cd ~/Elaria && assist backup check --kind monthly --record
```

To read back the most recent recorded monthly drill without running one:

```bash
cd ~/Elaria && assist backup check --kind monthly --last
```

---

## What it does

Restores a cold artifact to a temp directory, hash-verifies it against the manifest, then runs `restic check` to prove the repository is internally consistent as well as the artifact being retrievable. The outcome is appended to the drill journal at 0600, **outside the repo, beside the manifest**, path-free by construction.

**Failed drills record exactly as passes do**, because a journal that only shows passes is not evidence.

**A missing restic is a DECLARED SKIP — not a pass and not a failure.** The restore and the hash are what prove you can get your audio back; claiming more than that would be the silent-pass failure increment 4 exists to prevent.

---

## Pre-flight — each stated, because a skipped gate is not a gate

| # | Check | When | Refuse when |
|---|---|---|---|
| 1 | **F24 local headroom** | before any restore write | free space < artifact size + **1 GB margin** |
| 2 | **restic present** | before `restic check` | absent → **declared skip**, recorded as such |
| 3 | **rclone present, ≥1.41.0** | before the restore | absent, or below the floor → declared skip |
| 4 | **A cold artifact exists** | before the restore | none cold → records `nothing cold to drill`, exit 0 |

**Check 1 is the F24 local gate and it runs before the restore write.** The required headroom is **named in the record**, so a refusal can be checked rather than re-measured. A restore that dies at 90% because the disk filled has written a partial file and proved nothing — and **a partial write is worse than no write, because it looks like a result.**

The gate reads the destination's free space with the artifact's recorded size plus the margin. Verified shape:

```
backup check: REFUSED - headroom=REFUSED; reason=below local restore headroom;
              free=<bytes>; required=<bytes> (scratch=<artifact size> + margin=1073741824)
```

**Check 4 note:** `nothing cold to drill` is a *pass with a reason*, not a failure — but it is also not evidence that anything was retrievable. If operation 3 has not yet flipped anything cold, this drill proves nothing about your audio, only that the machinery ran. Read the record, not the exit code.

---

## To drill a specific artifact

```bash
cd ~/Elaria && assist backup check 20261102-100558-61258b --kind monthly --record
```

Naming an artifact is validated **first**: if there is no manifest record, or the artifact is not cold, the drill says so rather than silently picking another one.

---

## Stop conditions — self-firing

1. **MEGA login-blocks or rate-limits** → stop, report.
2. **A credential appears** in any output, log, journal or file outside your own 0600 files → stop, report.
3. **The restored hash MISMATCHES** → stop, report. Do not re-run to get a better answer; the mismatch *is* the answer, and it is recorded.
4. **`restic check` fails** → stop, report. Same reasoning.
5. **The local headroom gate refuses** → free space or fix it, then re-run. Do not disable the gate.

---

## What comes back to me

**Records only, never paths.** Paste:

- the drill's own output line (`backup check: passed` / `FAILED` / `REFUSED`)
- `assist backup check --kind monthly --last` — the recorded outcome, path-blind

The record carries the backend that produced it, the method, and the outcome. It never carries a path.

---

## Cleanup — never automatic

The drill restores to a **temp directory** and leaves it there for you to inspect and delete yourself. **Auto-delete does not exist in this lane.** Nothing in this packet deletes anything.

**The MEGA-trash caveat, repeated:** the rclone MEGA backend puts deletions into MEGA's trash unless `--mega-hard-delete` is set, so freed space may not appear immediately. That is a property of the backend, not a leak.

---

## Checksums
```
4eaca9f76aceee08a8bd972f46c67ed0720a3be12eb08c203a399b8725a1e6fb  scripts/storage-benchmark.sh
5daedf0d540c9392af7ce4bc938748fd30d5a31d36497e3d056897839e9faf22  scripts/storage-census-check.py
3b896526f1bde522e37e51d8804add0012490f30d7b12ef5d546c3dc8cf913bb  scripts/warm-cold-transition.py
dfbc44efbce3be1c45a45f3d8dec1ee2a4572bb35e5023279691d715a28b0362  src/assistant/preflight.py
4052ad568985ac3906e2bfa73955c2f789d1ef7cfec726884bb1e0dab4d3482c  src/assistant/backup_cli.py
c7c8cfc985afa997d734865cfff0d37d01559d625e216c8ef49860bd1e7fce4e  src/assistant/remote.py
```
