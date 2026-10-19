# Elaria change log for the adversarial hunt

Every repository change made during the hunt is recorded here. Bug details
and expected-vs-actual state live in `bugs.md`; this file is the chronological
record of code, test, fixture, and documentation changes.

## 2026-10-19 — pushed checkpoint `6733f17`

### Safety/executor fixes

- Replaced executor `shutil.move()` with no-overwrite destination creation:
  atomic hard-link placement for regular files when supported, symlink
  recreation for links, and exclusive-create copy fallback for cross-device
  or hard-link-unsupported filesystems.
- Split cross-device moves into copy → hash-verify → journal `copied` →
  unlink source → journal `committed`.
- Added `Journal.mark_copied()` and taught the store that `copied` is an
  outstanding intent and counts toward recent operation caps.
- Reused the same journaled move path for undo.
- Added `safety.is_safe_filename()` and enforced it for model-supplied
  `new_name` values in `planner_llm._parse_batch()` and again in the executor.
- Added executor validation for relative, non-escaping `dest` values and for
  resolved destinations staying inside the resolved organise root.
- Made `_Conflicts/` rerun `check_operation()` for its own candidate
  destination, use `lexists()` for collision selection, and refuse symlink
  escapes outside the root.

### Tests and fixtures

- Added `tests/test_bughunt_safety.py` covering randomized hostile trees,
  duplicate collisions, TOCTOU destination creation, `new_name` traversal,
  taxonomy and `_Conflicts/` symlink escapes, cross-device copy ordering,
  corrupt-copy source preservation, and strict-xfail repros for Areas A–C.
- Added `tests/bughunt_fixtures/evil_inputs.json` with traversal model
  output, must-not-act phrases, hostile filenames, and secret markers.
- Verification at that checkpoint: 224 passed, 9 xfailed; ruff clean.

## 2026-10-19 — wider hunt continuation (in progress)

- Created `bugs.md` as the reproduced-bug ledger and this file as the
  hunt change ledger.
- Began Areas D–G probes across planner/intents/config, store/memory/queue,
  audio/meeting/TTS, and daemon/IPC/CLI/persona surfaces. Entries below are
  appended as each probe becomes a committed test or fix.

### Immediate data-loss/wrong-record fixes

- `src/assistant/store.py`: escaped SQL `LIKE` metacharacters in
  `forget_facts()` (`\`, `%`, `_`) with `ESCAPE '\'`, fixing BH-E1.
- `src/assistant/meeting.py`: added exclusive-create copies, independent
  mic/system canonicalization, collision-suffixed meeting stamps across
  mic/system/note artifacts, and exclusive-create meeting notes, fixing
  BH-F4 and BH-F5.

### New hunt tests

- `tests/test_bughunt_systems.py`: added state-based repros/pass checks for
  planner batch exactness, boolean confidence, intent over/under-matching,
  string-as-sequence config, shared config defaults, malformed humour TOML,
  memory wildcard forgetting, raw FTS syntax, local-vs-network error
  classification, queue history starvation, crashed `running` jobs,
  store-less mode switching, missing ledger verification, concurrent queue
  drains, ASR empty fallback, WAV sample-rate reporting, PipeWire target
  guarding, meeting overwrite/channel copies, Piper config availability,
  TTS destination cache reuse, Live rotation, cleanup persistence, IPC
  event/reply interleaving, watcher debounce, speaker-threshold selection,
  and daemon review decisions.
- `tests/test_bughunt_safety.py`: added executor/organiser repros for
  plan/root mismatch, outside-root sources, invented destinations,
  nested already-filed flattening, destination directories, empty
  `ApplyReport.op_ids`, unreadable directories, and missing-root plans.
- `tests/test_bughunt_corpora.py`: added 738 parameterized boundary cases
  across safe filenames, protected paths, LLM verifier mutations, Tier 0
  rules, English/Kiswahili intent grammar and negation wrappers, cleanup
  marker-retention thresholds, persona tone ratios, PCM/embeddings maths,
  meeting segmentation, store search/forget punctuation, relative-time
  parsing, overlay states, TTS cache keys, blast radius, confidence
  decisions, shadow-cost rates, token estimates, and diarization overlap.
- `tests/bughunt_fixtures/evil_inputs.json`: added unsafe filename forms,
  action bases, negation/quotation wrappers, malformed LLM payloads, and
  FTS syntax attacks. Corrected the NUL filename to a JSON `\u0000`
  escape after the first edit produced a literal control byte.
- Applied ruff's import/order fixes to the two new hunt test modules.

### Bug ledger

- Populated `bugs.md` with BH-A5–A10, BH-B7–B9, BH-C3, BH-D1–D6,
  BH-E1–E7, BH-F1–F9, and BH-G1–G3, including fixed/open status,
  severity, minimal test repro, and expected-vs-actual state.
- Added `BUGHUNT.md` as the final summary/report linking the detailed bug
  and change ledgers.

### Verification

- Full keyless/mock suite: **973 passed, 5 skipped, 52 xfailed** from
  **1,030 collected** tests.
- Ruff over `src/` and `tests/`: all checks passed.
- `git diff --check`: clean.
