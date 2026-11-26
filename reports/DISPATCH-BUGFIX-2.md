# DISPATCH-BUGFIX-2 — P0 fixes from Hunter A (manager, 2026-11-26)

Two P0s in the learn/discover core (`bugs.md`). Fix before any new
feature lane. Regression tests named after the bug ID, failing
before and passing after; frozen thresholds untouched; merged PR
or it didn't happen. Sync main first; never edit OWNERS.yaml.

## FIX-A1 — Agent Z · `BUG-A1` · memory promotion integrity

> You are Agent Z. Fix `BUG-A1` (`reports/BUGHUNT-A-20261126.md`):
> (1) gap/clarifying answers promote an UNRELATED inferred fact to
> `source='stated'` conf=1.0 (`errand.py` links the most recent
> inferred record when a question has no linked fact) — a question
> may only ever promote facts it names; a gap answer creates a
> fact for the gap attribute or nothing; (2) conflict answers
> ignore `answer_text` and promote the losing tentative text
> verbatim — promotion must reflect the owner's chosen value;
> (3) `skill_memory_infer()` bypasses `Memory.propose_inferred()`
> tombstones/dedup (zero production callers) — route it through,
> and rewrite the masking tests in
> `tests/test_build12_memory_lifecycle.py` to drive the real
> `ErrandRunner`/`skill_memory_infer` path instead of a stub.
> Regression tests `test_bug_a1_*` from all three repros.

## FIX-A2 — Agent Z · `BUG-A2` · discovery IPC containment

> You are Agent Z. Fix `BUG-A2` (`reports/BUGHUNT-A-20261126.md`):
> `fs.locate`/`file.inspect`/`file.read` daemon IPC handlers and
> the errand `file.inspect` step bypass `[discovery]` roots,
> `_require_ipc_owner()`, and showoff lockdown. Bring every
> file-reading entry point under the same containment as
> `errand.start`: owner check, configured roots only
> (caller-supplied roots may narrow, never widen), showoff refusal,
> protected-path rules, and `SafetyJournal` untrusted-input notes
> where content is returned. One shared containment helper, used
> by all entry points — no per-handler re-implementations.
> Regression tests `test_bug_a2_*` from both repros (errand +
> daemon/showoff).

## Queue after these (bugs.md order)

P1 lanes, dispatched next: FIX-B5/B6 (sensitive/injection on the
embodied path, Agent H), FIX-B8/B10 (wake/voice fail-opens,
Agent J), FIX-A3/A4/A12 (provider quota integrity, Agent I),
FIX-C1/C2/C4 (edges, Agents REACH/E/S), FIX-B7 (headless consent
journal ordering, Agent P), FIX-A5–A9 (Agent Z/B), then P2s.
