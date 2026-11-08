# STEP 0 — census ground-truth check, owner-run line

**Operation:** STEP 0 of the WP7 bounded live-traffic scope (report 025), before anything is flipped.
**Issued:** 2026-11-08 · **Branch:** `arena/storage` · **PR:** #24
**Nothing here touches MEGA. This runs on your machine, against your own audio directory.**

---

## The one line

```bash
cd ~/Elaria && python3 scripts/storage-census-check.py --audio ~/Elaria/audio --manifest ~/.local/share/assistant/backup/manifest.jsonl
```

It prints byte counts, a file count and the number of never-retry marks. **It never prints a path, a filename, or anything that could identify content.** Exit 0 means the three computations reconciled; exit 1 means they did not and it refused to report a number.

---

## Why this exists, and the two things it will tell you that `du -sb` alone will not

The census is three independent computations that must agree:

1. a Python walk of the audio directory
2. `du -sb`, the shell's own byte total
3. the manifest arithmetic, summed over the manifest's records

Two subtleties are worth knowing before you read the output, because both look like bugs and are not:

**`du -sb <dir>` includes the directory inode's own apparent size** (4096 on ext4). The script subtracts it and discloses the raw figure alongside, so the adjustment is never hidden.

**`du -sb` counts the never-retry marks; the census must not.** A ruling says the 44-byte header-only file is a never-retry mark that counts zero forever. So the two figures differ *on purpose*, and the check is that the difference equals the marks' byte total **exactly, to the byte**.

That last line is the one that matters for what you told me: you said the audio directory now totals roughly 600 MB against the census's 138,298,770 bytes, with several new captures and four visible 44-byte marks in it. If so, **your `du -sb` will not equal the manifest arithmetic, and it should not.** The gap should be exactly the marks' bytes. If the gap is any other size, the walk dropped something that is not a mark — which is a real defect, and the reason this check refuses to report a number rather than reporting one it cannot reproduce.

A chunked zero-frame WAV is 62–66 bytes, not 44, and is still a mark. The check walks the RIFF chunks structurally rather than comparing sizes, so it catches those too.

---

## What comes back to me

Paste the whole output. It is byte counts and counts only — no paths, no filenames, no content.

---

## Checksums
```
4eaca9f76aceee08a8bd972f46c67ed0720a3be12eb08c203a399b8725a1e6fb  scripts/storage-benchmark.sh
242939c1f77c9dd0bd70b9f86bdb15ee8145951c99283f18b62aaf870ef3dec1  docs/phase-reports/001-owner-scene-sheet-1-mega-and-benchmark.md
5daedf0d540c9392af7ce4bc938748fd30d5a31d36497e3d056897839e9faf22  scripts/storage-census-check.py
3b896526f1bde522e37e51d8804add0012490f30d7b12ef5d546c3dc8cf913bb  scripts/warm-cold-transition.py
```
