# Sheet 1 · Storage Purge — Dry-Run Contract (U · CLEANUP)

## Safety rule (verbatim, owner-mandated)
**PURGE IS DRY-RUN BY DEFAULT.** Every purge path defaults to listing what
it WOULD delete, never deleting, unless an explicit `--apply` flag is
passed AND every candidate is classified `THROWAWAY`. All purge tests
use THROWAWAY FIXTURES ONLY — never real user data, never the live
store.

## Module map (U-owned)
| File | Role |
|---|---|
| `src/assistant/cleanup.py` | Adds `DataClass`, `PurgeCandidate`, `PurgeReport`, `StoragePurgePlanner`, `load_purge_planner`, `plan_candidates` alongside the existing transcript `CleanupPass` (which is preserved untouched for A/transcribe consumers). |
| `src/assistant/preflight.py` | Fail-closed gates: forbidden roots, relative paths, symlink-escape, shape checks. Every purge entry point runs preflight first. |
| `src/assistant/drill.py` | Four end-to-end drills on generated throwaway trees, runnable via `python -m assistant.drill`. |
| `tests/test_cleanup_u_purge.py` | 26 pytest cases covering classification, dry-run invariants, apply-refusal gates, retention thresholds, preflight, blast-radius cap, journal attributability, and all four drill scenarios. |

## Dry-run invariants (assert-checked)
1. `dry_run()` returns `PurgeReport(dry_run=True)`.
2. `removed_count == 0` AND `removed_bytes == 0` after every dry run — asserted.
3. No filesystem mutation (unlink/rmdir) occurs on the dry-run path.
4. `apply(apply_flag=False)` is equivalent to `dry_run()`.

## Apply gates (all must hold, fail-closed)
1. `apply_flag is True` (explicit caller consent).
2. A journal is supplied (D-attributable per IF-5).
3. Every candidate is classified `DataClass.THROWAWAY` — any
   `RETAINED`/`PROTECTED`/`UNKNOWN` in scope ⇒ refusal with the first
   offender named.
4. Blast-radius cap (`max_ops_per_run`, default 512) is respected.
5. Each removal is wrapped in `journal.begin` → `unlink` → `journal.commit`;
   OSError ⇒ `journal.fail` and is recorded, never silently swallowed.

## Data classification (fail-closed defaults)
| Class | Meaning | Default retention | Purge eligible? |
|---|---|---|---|
| THROWAWAY | Generated/transient (wake_clips, audition_candidates, drill-tmp, benchmark-tmp, sockets/pids, cores) | 7 days | Yes (apply) |
| RETAINED | User content (transcripts, recordings, notes) | ~10 years | Listed only, NEVER removed |
| PROTECTED | Config/DB/keys/weights/voiceprints | ~10 years | Listed only, NEVER removed |
| UNKNOWN | Anything not matching a rule | ~10 years | Listed only, NEVER removed |

## Preflight gates
- Forbidden roots (/, /home, /etc, /usr, /var except /var/tmp, /opt, /boot, /proc, /sys, /dev, $HOME-as-root) → refused.
- Relative paths → refused.
- Symlink resolution outside a scoped root → refused.
- /tmp and /var/tmp are permitted (drill territory).

## Hook request (HR-U-1)
filed → Z pending. Asks Z to author:
- `[storage_purge]` config section with retention keys (mirroring the
  defaults already embedded in `load_purge_planner` as a fallback).
- A single-authored deletion path on `store.py` that the apply()
  method will call through when integrated, so journaling is
  coordinated and the DB/ledger stays consistent. Until HR-U-1 lands,
  apply() only removes filesystem artifacts under THROWAWAY-classified
  dirs it is given (via planner roots) — never touching the store DB.

## How to run (all throwaway)
```
# Drills (built-in throwaway temp trees)
PYTHONPATH=src python3 -m assistant.drill

# Unit tests (tmp_path fixtures only)
PYTHONPATH=src pytest tests/test_cleanup_u_purge.py -v
```

## Evidence (current run)
- `python -m assistant.drill` → all 4 drills PASS.
- `pytest tests/test_cleanup_u_purge.py` → 26 passed.
- Existing transcript-cleanup tests (`test_phase1_dictation.py`,
  `test_phase7_kiswahili.py`, `test_bughunt_corpora.py`) → 767 passed,
  5 skipped, 0 failed (the existing CleanupPass path is preserved
  byte-for-byte in behaviour; U's additions are additive).
