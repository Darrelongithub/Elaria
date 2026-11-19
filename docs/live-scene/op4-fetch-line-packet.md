# OPERATION 4 — owner-run packet: the fetch line, and your ear

**Ruling applied:** operations 1–5 are **owner-run packets on the owner's machine**. The builder's sandbox cannot perform this: MEGA is network-blocked here, restic and rclone are absent, and the owner's audio is deliberately not in the sandbox.

**Issued:** 2026-11-08 · **Branch:** `arena/storage` · **PR:** #24
**Status:** held until operation 3 has flipped something cold. Issued now so the line is ready the moment the window opens.

---

## READ THIS FIRST — there is nothing to fetch until operation 3 lands

**This fetch has nothing to restore until operation 3 has flipped something cold.** Operation 3 is itself time-gated: the named wav `20261102-100558-61258b` is sendable cold **only from 2026-11-16 after 10:06**, because it was captured 2026-11-02 10:05:58 and the hot window is 14 days.

**Run this before then and it will say `that artifact is <state>, not cold; nothing to restore` and exit 2.** That is the gate holding — the artifact is still hot, and there is no cold copy to bring back.

**That is not a failed restore.** Do not read it as one, and do not re-run it hoping for a different answer. Go back to `op3-cold-flip-packet.md` and check the window.

Check first:

```bash
cd ~/Elaria && assist backup status
```

**The cold count must be at least 1.**

---

## The one line

```bash
cd ~/Elaria && assist backup fetch 20261102-100558-61258b
```

**A bare filename works.** The lookup resolves it against the manifest — exactly, or against the audio root — and it never searches for a *similar* name, because a basename match across several captures would hand you audio you did not ask for. If the name is not in the manifest it refuses rather than guessing.

To put the restored copy somewhere specific instead of a temp directory:

```bash
cd ~/Elaria && assist backup fetch 20261102-100558-61258b --out ~/Music/check.wav
```

---

## What it does

Manifest lookup → restore → **hash-verify against the recorded sha256**. The restore and the hash are what prove you can get your audio back.

**It will refuse to call it a restore if the hash does not match.** That refusal is the correct behaviour, not a bug to work around.

---

## What I need back — one line

**Did it play, and roughly how long did it take?**

The latency budget for `assist backup fetch` is ruled **only** from Sheet 1's rows 12–15. Nothing else may set it, and until those numbers exist no fetch-latency claim exists anywhere — not in code, docs, or chat.

**Paste the `backend:` line from the output. Do not paste the `restored:` line** — that one carries your filesystem path, and it does not need to leave your machine. The backend line names which backend answered, which is the part that matters.

---

## Pre-flight

| # | Check | Refuse when |
|---|---|---|
| 1 | Something is cold | the artifact is not cold — see the leading section |
| 2 | restic and rclone present, rclone ≥ 1.41.0 | absent or below the floor |
| 3 | A remote is configured | `remote_free=unknown (no remote configured)` |

---

## Stop conditions — self-firing

1. **The restored hash MISMATCHES** → stop, report. Do not re-run for a better answer; the mismatch *is* the answer.
2. **MEGA login-blocks or rate-limits** → stop, report.
3. **A credential appears** in any output, log or file outside your own 0600 files → stop, report.
4. **`remote_free` drops below 10 GB** → the capacity-floor knock fires, reading exactly *"Elaria wants to talk"* with zero content.

---

## Cleanup — never automatic

The restored copy lands in a temp directory (or wherever you point `--out`) and **stays there for you to inspect and delete yourself. Auto-delete does not exist in this lane.** Nothing in this packet deletes anything.

**The MEGA-trash caveat, repeated:** the rclone MEGA backend puts deletions into MEGA's trash unless `--mega-hard-delete` is set, so freed space may not appear immediately. That is a property of the backend, not a leak.

---

## Checksums
