# Agent H — WATCH-BUILD-1: password geometry only

## Scope and sync

Read `DISPATCH-WATCH-BUILD.md`, `DISPATCH-WATCH.md`, and the WATCH design.
Fetched `origin/main` and ran `git merge --ff-only origin/main`: already up
to date at `eaa5a3579bf54e209676d4a99527ac4f7bd084fd`. Work stays on the
session-assigned branch `arena/3f67fc91-elaria`.

**WATCH-BUILD-1 only.** No watcher, ingestion store, supervisor, new config,
provider calls, or `OWNERS.yaml` changes.

## Fix

The existing one-shot AT-SPI walker checks `get_role()` before reading any
accessible name. `PASSWORD_TEXT` uses the canonical `password text` role,
its validated rectangle, a constant empty name, and the existing sensitive
flag in the unchanged wire format. It never calls name, description, text,
or value getters for that node. Password subtrees are not descended into,
preventing child labels from reintroducing sensitive identity/content.
Nodes without component geometry contribute no row, as before.

Existing coordinate acceptance, descendant containment rejection, and
non-sensitive HW2B contained-label resolution remain unchanged. Sensitive
geometry still blocks direct targets and overlapping controls. Tests that
previously looked up a password's private name now assert it cannot resolve;
a forged direct target is still refused by `ground()`.

## Evidence

- Canary fake password node records and raises on name, description, text,
  value, their interface getters, role-name, and child traversal access.
  Both component/no-component paths pass with zero forbidden accesses.
- Canary absent from raw helper stdout/stderr, materialised frame, and
  journal lines. A rejected extra window ensures the journal assertion
  exercises an actual metadata rejection line.
- Geometry tombstone and sensitive-overlap refusal asserted.
- `.venv/bin/pytest -q tests/test_bug_hw2_atspi.py tests/test_nus*.py tests/test_bug_hw1*.py`
  — **119 passed**. The first run had 117 passes and two fixture setup errors
  due to absent `httpx` in the fresh test environment; installing that runtime
  dependency resolved both without source changes.
- `.venv/bin/ruff check src/assistant/_observation_linux.py tests/test_bug_hw2_atspi.py`
  — passed.
- `git diff --check` — clean.

Sandbox fixtures only: no live AT-SPI bus/Hyprland or hardware validation
claimed. No full-suite result claimed. Later WATCH lanes remain untouched.
