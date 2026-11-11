# Sheet 1 Part B — owner-run benchmark packet

**Operation #1 of the WP7 bounded live-traffic scope (report 025).**
**Issued:** 2026-11-04 · **Branch:** `arena/storage` @ `53b492f` · **PR:** #24
**Nothing here touches MEGA from this sandbox. You run it, on your machine, against your account.**

---

## The one line

```bash
cd ~/Elaria && sha256sum -c docs/live-scene/sheet1.SHA256SUMS && bash scripts/storage-benchmark.sh
```

The `sha256sum -c` half is the checksum-before-run: it proves the two files you are about to
run are byte-identical to the ones I committed. **If it prints anything other than two
`OK` lines, stop and report it — do not run the script.**

---

## What you must set first — in your own shell, never inline

Three variables, read from your own environment. No credential is ever typed on a command
line, and the script never prints, logs or transmits one.

```bash
export RESTIC_REPOSITORY_BASE="elaria-mega:elaria-bench"
export RESTIC_PASSWORD_FILE="$HOME/.config/elaria/restic-passphrase"   # your 0600 file
export RCLONE_CONFIG="$HOME/.config/rclone/rclone.conf"                # your 0600 file
```

The rclone remote name is `elaria-mega`, created by you in `rclone config` (Sheet 1 Part A).
The MEGA password is obfuscated by rclone itself inside that 0600 file, outside this repo.

---

## What the run does, and its caps — Sheet 1's, verbatim

| | |
|---|---|
| Synthetic upload | **~1 GB** across two scratch repos (`-default` at 16 MiB pack, `-pack32` at 32 MiB) |
| Local tree | one **~500 MB**, random and incompressible |
| Small-file fetch | **×10** at 4096 bytes, at both pack sizes |
| Restore | one **~500 MB** per repo |
| `restic check` | once per repo |
| `restic check --read-data-subset` | capped at **≤5% or ≤500 MB, whichever is smaller** |

**It prints numbers only** — durations, byte counts, ratios. If it ever prints anything that
looks like a secret, stop and report it as a defect.

**Expect to leave it running and come back.** On the free tier this can take a long time.

---

## Stop conditions — self-firing, no decision needed from you

1. **MEGA login-blocks or rate-limits** at any point → stop, report.
2. **`restic init` or the first backup cannot complete in a sane window** → that is a no-go on
   the MEGA backend. Report it; do not work around it.
3. **A credential appears** in any output, log or file outside your own 0600 files → stop, report.
4. **`remote_free` drops below 10 GB** → stop, report. That is the capacity-floor knock.

**Cleanup is yours and never automatic.** When you are done, Sheet 1's cleanup block removes
the scratch repos. Note the MEGA backend puts deletions into MEGA's trash unless
`--mega-hard-delete` is set, so freed space may not appear immediately — a property of the
backend, not a leak.

---

## What comes back to me

Sheet 1's return sheet, **numbers only**: rows 1–23, including the end-to-end ratio I need
for operation #2, the latency figures that rule the fetch budget, and whether the remote was
ever login-blocked. Paste the numbers; do not paste anything else.

---

## Checksum manifest — `docs/live-scene/sheet1.SHA256SUMS`

```
4eaca9f76aceee08a8bd972f46c67ed0720a3be12eb08c203a399b8725a1e6fb  scripts/storage-benchmark.sh
242939c1f77c9dd0bd70b9f86bdb15ee8145951c99283f18b62aaf870ef3dec1  docs/phase-reports/001-owner-scene-sheet-1-mega-and-benchmark.md
```
