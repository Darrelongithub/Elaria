# Agent H — WATCH-BUILD-2: ingestion filter + RAM store

## Scope and sync

Read `DISPATCH-WATCH-BUILD.md`, `DISPATCH-WATCH.md`, and the WATCH design.
Fetched `origin/main`: already up to date at
`078bf0edb1a227a531f859d1d07afbab162be401`. Work stays on the
session-assigned branch `arena/5e00af19-elaria`.

**WATCH-BUILD-2 only.** No watcher child, supervisor, overlay indicator,
grounding rewire, new config, provider calls, or `OWNERS.yaml` changes.

## Implementation

Two new daemon-side modules, pure and testable without a bus:

- `src/assistant/watch_ingest.py` — design §6 filter. Role is read before
  any property: `PASSWORD_TEXT` short-circuits to a `Tombstone` (role +
  rect only; `get_name`/`get_description`/`get_text`/`get_value` never
  called). SECRET name hits (any role) become tombstones with the name
  dropped after the test. Names capped at 64 chars. D1 geometry-only
  roles (`label`/`static`/`paragraph`/`terminal`/`document`) store
  geometry with `name=None`; controls keep names. Titles/apps are
  SECRET-screened and 64-char capped, else `""` (§6.5). `Tombstone` has
  no `name`/`value`/`text` attribute by construction (§6.2 type proof).
  `ingest_delta()` re-applies the screen to dict deltas as defence in
  depth. Journal lines carry metadata only (window key, role, reason).
- `src/assistant/watch_store.py` — design §5.1 `WatchStore`. `Window`
  (key/pid/app/title/rect/output/workspace/visible/focus_rank/seq/
  synced_at/state) and `Node`/`Tombstone` records in RAM only: no file
  I/O, no pickle, no database. Caps enforced: 128 windows (oldest-synced
  evicted), 256 nodes per window (truncate), 20k total (oldest windows
  frozen). Seq-gap marks the window `stale`; duplicates are ignored;
  `mark_live()` clears stale after resync. `view()` returns live-window
  nodes only. `clear()` drops everything (halt path for BUILD-4).

Zero cloud API budget: neither module imports a provider client, HTTP
client, subprocess, or socket (AST-asserted below).

## Evidence

- Canary fake password node records and raises on name, description,
  text, value, interface getters, role-name, and child traversal access.
  Both component/no-component paths pass with zero forbidden accesses;
  tombstone carries role + rect only, no name attribute exists.
- SECRET name screen, 64-char cap, D1 geometry-only (5 roles), control
  names kept (8 roles), title/app filtering, delta defence-in-depth.
- Journal-lines-contain-no-names: tombstone + stale lines emitted,
  canaries absent from all lines.
- Caps: 128 windows, 256 per window, 20k total; seq-gap → stale,
  duplicate ignored, resync clears; view excludes stale; clear empties.
- RAM-only: no pickle/sqlite3/file-write/open in either module.
- AST import test (rail 4): no `executor`/`hands`/`intents`/`nus_pointer`/
  provider-client imports; no network stdlib.
- `pytest -q tests/test_bug_hw2_atspi.py tests/test_nus*.py
  tests/test_bug_hw1*.py tests/test_h_watch_build2.py` — **149 passed**
  (119 HW2/NUS + 30 new). `httpx` installed in the sandbox to resolve
  two fixture setup errors (no source change, same as BUILD-1).
- `ruff check` on the three new files — passed. `git diff --check` —
  clean.

Sandbox fixtures only: no live AT-SPI bus/Hyprland or hardware validation
claimed. No full-suite result claimed. Later WATCH lanes remain untouched.
