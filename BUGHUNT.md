# Elaria adversarial bug hunt — final summary

Date: 2026-10-19  
Branch: `arena/21f29214-elaria`  
Detailed bug ledger: [`bugs.md`](bugs.md)  
Chronological change ledger: [`change.md`](change.md)

## Method

- Baseline before the wider hunt: commit `6733f17`, keyless/mock suite green.
- All hunt tests run in temporary sandbox directories and temporary SQLite
  stores. No real user folders are used.
- State is the oracle: files, journal rows, SQLite rows, queue rows, routing
  results, and returned records—not process exit codes alone.
- Open reproduced bugs are strict-xfail tests. If one begins passing, the
  suite turns red until its marker and `bugs.md` entry are retired.
- Evil inputs are committed in `tests/bughunt_fixtures/evil_inputs.json`.

## Coverage and verification

Full verification on 2026-10-19:

- **1,030 tests collected**
- **973 passed**
- **5 skipped** (parameter combinations that are not meaningful)
- **52 xfailed** (all reproduced open bugs)
- **Ruff:** all checks passed

The parameterized corpora cover path safety, LLM-output verification,
Tier 0 placement, English/Kiswahili intent grammar and negated/quoted
commands, code-switch retention thresholds, persona tone ratios, PCM and
embedding maths, meeting segmentation, SQLite search/memory state,
relative-time parsing, overlay state, TTS cache identity, blast-radius and
confidence boundaries, shadow-cost rates, and diarization overlap/merge
boundaries.

## Fixed during the hunt

Earlier safety checkpoint `6733f17`:

- BH-A1: destination racing after policy check could be overwritten.
- BH-A2: model/plan `new_name` could escape the organise root.
- BH-A3: taxonomy/`_Conflicts` symlinks could smuggle files outside root.
- `_Conflicts/` now reruns policy for its own destination.
- Cross-device moves now copy → hash-verify → journal `copied` → unlink →
  commit.

Wider Areas D–G continuation:

- BH-E1: `forget %` / `forget _` could deactivate unintended memories due
  to unescaped SQL `LIKE` wildcards.
- BH-F4: same-minute meetings could overwrite raw audio and notes.
- BH-F5: meeting system-channel canonicalization depended on the mic path.

## Highest-risk open findings

1. **BH-A5 + BH-A6** — the executor does not enforce plan/root pairing or
   require each source to be inside the root being applied.
2. **BH-A8** — a routine organise plan flattens nested already-filed files
   such as `Finance/2024/invoice.txt` into `Finance/invoice.txt`.
3. **BH-B3 + BH-C1 + BH-C2** — executor-level unscoped undo exists, halt
   can land just after the last per-item check, and `trash()` bypasses the
   protected/halt policy spine.
4. **BH-B1 + BH-B5 + BH-A9** — crash/hostile-filesystem edges can strand a
   moved file outside normal undo, hang indexing on a FIFO, or abort an
   apply when a directory occupies a destination.
5. **BH-E3 + BH-E4 + BH-E5 + BH-C3** — offline queue reliability has four
   compounding failure modes: local errors classified as network loss,
   500 completed jobs starving newer work, crashed `running` jobs never
   recovering, and concurrent drains double-processing a job.

See `bugs.md` for all 40+ reproduced finding groups, severities, minimal
repros, and expected-vs-actual state. See `change.md` for every code,
test, fixture, and documentation change made during the hunt.
