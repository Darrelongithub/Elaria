# Phase report 001 — OWNER SCENE SHEET 1: MEGA account + backend benchmark

**Date:** 2026-10-27
**Issued:** EARLY, before any WP7 code exists. The numbers come back before the
machinery gets built.
**Purpose:** give the design chat a factual basis to rule go / no-go on (a) the
MEGA backend via restic's `rclone:` transport, and (b) the latency target for
`assist backup fetch`.

**Privacy contract for this scene.** Nothing below ever asks the owner to paste a
password, a passphrase, an email address, a file name, or any backed-up content
into chat. The owner performs credential steps himself, in his own browser and
his own terminal. The only thing that comes back to the builder is **numbers**:
durations, byte counts, ratios, counts. If a block below would ever have printed
a secret, it has been rewritten so that it does not.

**Evidence tags used below:** [HW-PROVEN] measured here · [TESTED-ONLY] runs in a
harness but not on the owner's laptop · [UNVERIFIED] claimed, not yet measured ·
[BROKEN] known bad.

---

## PART A — EARS STEPS (owner's ears; no terminal, no physical action)

These steps are about what the owner hears, sees and decides. **No paste-able
command appears in this part.** Do them at the laptop, in order.

**A1. Open the MEGA account in the browser.**
Go to the MEGA signup page and create the free account. Free tier is **20 GB
permanent**; achievement/bonus storage is temporary and expires, and it is
ignored by the capacity model on purpose — the runway math must not be flattered
by storage that will vanish. [HW-PROVEN policy text, cited in report 000 §3.3]

**A2. Confirm the account is really free-tier 20 GB.**
Note the *number only* (e.g. "20 GB") for the return sheet. Do not note
anything else about the account.

**A3. Decide the recovery-key escrow before any data exists.**
MEGA is end-to-end encrypted: no password and no recovery key means no account,
ever. Save the recovery key somewhere that is not this laptop. This is a
decision step, not a command step.

**A4. Decide the restic passphrase escrow.**
The restic repository passphrase lives in a **0600 file on the laptop** and the
owner also keeps a **paper escrow OFF the machine**. Both, not either. Decide now
where the paper copy lives. If the passphrase is lost, the repository is
unreadable and every cold copy is gone — there is no recovery path, by design.

**A5. Set the expectation for what "good" sounds like.**
Read report 000 §3.2 once. The rclone MEGA backend is Tier 2, does not support
mtimes or hashes, permits duplicate names, and can *block logins under heavy
use* for about a week. A slow or failed benchmark is a **known property of the
backend**, not a bug in Elaria, and it will be reported as data — never quietly
worked around.

**A6. Set the expectation for the latency target.**
"Fetch in seconds" is an **[UNVERIFIED-TARGET]**. The design chat rules the
budget *from the numbers in this scene*. Until then, no code, no doc, and no
chat message claims any fetch latency.

**A7. Reserve the time.** Part B's terminal steps upload ~1 GB of synthetic data
in two repos plus one local 500 MB tree, and run two `restic check` passes. On a
MEGA free account this can take a long time. Expect to leave it running and come
back.

---

## PART B — TERMINAL STEPS (paste-safe; owner runs these himself)

Every block is self-contained and safe to paste. **No physical action appears
inside any block.** Every credential is read from the owner's own environment or
his own 0600 file; nothing is typed inline.

> **Guard rail, read once before B1.** `scripts/storage-benchmark.sh` never
> prints, logs or transmits a credential. It reads `RESTIC_REPOSITORY`,
> `RESTIC_PASSWORD_FILE` and the rclone remote name from the environment the
> owner sets in his own shell. It prints durations, byte counts and ratios
> only. If it ever prints anything that looks like a secret, stop and report it
> as a defect.

### B1 — Install the two system binaries (dnf; $0)

```bash
sudo dnf install -y restic rclone
```

### B2 — Verify the versions actually installed

```bash
restic version; rclone version
```

Paste **only the two version lines** into the return sheet.

### B3 — Configure the MEGA remote interactively

Run this and answer its prompts. The password is typed into rclone's own hidden
prompt; it is never echoed and never appears in a paste-able block.

```bash
rclone config
```

Choose: `n` (new remote) → name it `elaria-mega` → storage type `mega` → paste
your MEGA user → `y` (type my own password) → type the password at the prompt →
accept.

rclone writes `pass = *** ENCRYPTED ***` into `rclone.conf`. **That is
obfuscation, not encryption** — anyone who can read the file can recover the
password with `rclone reveal`. This is an accepted, documented risk, and it is
why the next step exists.

### B4 — Lock the config file down and confirm it is outside the repo

```bash
chmod 600 ~/.config/rclone/rclone.conf
ls -l ~/.config/rclone/rclone.conf
```

Paste the `ls -l` line. It must begin with `-rw-------`.

### B5 — Prove the remote is reachable, and prove nothing secret leaks

```bash
rclone about elaria-mega:
```

Paste **only the numbers** the command prints (total / used / free / trash). Do
not paste anything else.

### B6 — Create the restic passphrase file, 0600, outside the repo

Pick a long random passphrase. It is generated on the laptop and never leaves it.

```bash
install -d -m 700 ~/.config/elaria
( set -o pipefail; tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 48; echo ) \
  > ~/.config/elaria/restic-passphrase
chmod 600 ~/.config/elaria/restic-passphrase
```

Then write the same passphrase onto paper and store it off the machine (A4).

### B7 — Run the benchmark

This is the builder-written instrument. It creates **two** scratch repositories
so the pack-size comparison is clean, uploads a synthetic ~500 MB tree into each
at a different pack size, times a small-file fetch ten times, restores ~500 MB,
runs `restic check`, and runs `restic check --read-data-subset` capped at 5% or
500 MB — whichever is smaller.

```bash
cd /path/to/Elaria   # the repo checkout
export RESTIC_REPOSITORY_BASE="elaria-mega:elaria-bench"
export RESTIC_PASSWORD_FILE="$HOME/.config/elaria/restic-passphrase"
bash scripts/storage-benchmark.sh 2>&1 | tee ~/elaria-bench-$(date +%Y%m%d-%H%M%S).log
```

The `tee` copy stays on the laptop. **Paste the script's stdout into chat, not
the log file**, and check before pasting that it contains no credential.

The script refuses to run if either scratch repo already exists, so a re-run
never silently overwrites a previous measurement.

### B8 — Report what happened

Paste the script's stdout block. It is the return sheet. If any step fails, that
failure *is* the result — paste the error line and stop; do not retry until the
design chat has seen it.

---

## RETURN SHEET (what comes back to the builder — numbers only)

Fill this in from B8's stdout. **No content, no filenames, no paths that
identify a recording, no credentials.**

| # | Measurement | Value |
|---|---|---|
| 1 | `restic version` | |
| 2 | `rclone version` | |
| 3 | `rclone.conf` mode | |
| 4 | MEGA free tier total / used / free (GB) | |
| 5 | `restic init` over `rclone:` — repo A (default pack) wall-time | |
| 6 | `restic init` over `rclone:` — repo B (32 MiB pack) wall-time | |
| 7 | Repo A backup wall-time, ~500 MB tree | |
| 8 | Repo A bytes uploaded | |
| 9 | Repo B backup wall-time, ~500 MB tree | |
| 10 | Repo B bytes uploaded | |
| 11 | Pack size A / pack size B actually used (from `restic cat config`) | |
| 12 | Small-file fetch latency ×10 — repo A (each, seconds) | |
| 13 | Small-file fetch latency ×10 — repo B (each, seconds) | |
| 14 | Mean / p50 / max small-file fetch, repo A | |
| 15 | Mean / p50 / max small-file fetch, repo B | |
| 16 | ~500 MB restore wall-time, repo A | |
| 17 | ~500 MB restore wall-time, repo B | |
| 18 | `restic check` wall-time + result, repo A | |
| 19 | `restic check` wall-time + result, repo B | |
| 20 | `restic check --read-data-subset` wall-time + bytes read + result, repo A | |
| 21 | `restic check --read-data-subset` wall-time + bytes read + result, repo B | |
| 22 | Any error line, verbatim | |
| 23 | Did the remote get login-blocked at any point? (y/n) | |

---

## WHAT THE DESIGN CHAT RULES FROM THIS SHEET

1. **Backend go / no-go.** If `restic init` or the first backup cannot complete
   inside a sane window, or the remote gets blocked, that is a no-go on the MEGA
   backend — and the options that go back to the owner are a different provider
   or revised tier expectations, **with these numbers attached**. Never a silent
   workaround.
2. **Pack size.** Default (16 MiB) vs 32 MiB, from rows 7–11. Larger packs mean
   fewer objects, which is the one lever that helps a Tier-2 backend; the cost
   is temp space (pack size × connections + 1) and SSD wear.
3. **Latency budget for `assist backup fetch`.** From rows 12–15. This is the
   only source of the budget. Nothing else may set it.
4. **Drill cost.** From rows 18–21 — how expensive a monthly restore+check
   actually is against a rolling, per-IP download quota.

---

## CLEANUP (owner decision, never automatic)

Auto-delete never exists. When the owner is finished with the benchmark, he
removes the scratch repos himself, deliberately:

```bash
export RESTIC_REPOSITORY="elaria-mega:elaria-bench-default"
export RESTIC_PASSWORD_FILE="$HOME/.config/elaria/restic-passphrase"
restic unlock --remove-all
rclone purge elaria-mega:elaria-bench-default
rclone purge elaria-mega:elaria-bench-pack32
```

Note that the rclone MEGA backend puts deletions into MEGA's trash unless
`--mega-hard-delete` is set, so the freed space may not appear immediately.
That is a property of the backend, not a leak.
