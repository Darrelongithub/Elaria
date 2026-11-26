# DISPATCH-BUGHUNT — three parallel bug hunters (manager, 2026-11-26)

Read-only hunt. **No fixes, no refactors, no threshold changes.**
Every bug ever found goes to `bugs.md` at repo root — via the
consolidation step below, so three hunters never collide on one
file. Each hunter writes findings to their own file; the manager
verifies and consolidates into `bugs.md`.

## Rules for all hunters
- Sync first: `git fetch origin && git merge origin/main`.
- A bug claim needs evidence: `file:line`, the exact failure mode,
  and either a reproduction (test/run output) or a labelled
  static-analysis argument. "Looks wrong" without a failure mode
  is not a bug — file it as SUSPECT, separate section.
- Check the bug isn't already known: search `reports/RPT-*`,
  existing test names, and GitHub issues before filing.
- Severity: **P0** safety/authority breach or data loss ·
  **P1** wrong behaviour on a real path · **P2** edge-case wrong ·
  **P3** cosmetic/dead code. The orphaned `structured_reader.py`
  (PRs #138/#139) is already known — don't re-file it.
- Bugs in TESTS count (a test that can't fail is a bug in the
  safety net). Sandbox limits are not bugs — hardware claims stay
  the owner's eyes.
- Deliverable per hunter: `reports/BUGHUNT-<lane>-20261126.md`
  with entries: `BUG-<lane><n> · severity · file:line · failure
  mode · evidence · suggested owner`. New `arena/*` branch, PR,
  merge yourself. Never edit OWNERS.yaml or `bugs.md`.

## Lanes (disjoint by construction)

**Hunter A — core brain:** `daemon.py`, `errand.py`, `memory.py`,
`provider_router.py`, `cost.py`, `config.py`, `store.py`,
`intents.py`, `planner_llm.py`, `gemini_client.py`. Hunt for:
quota/ladder bypasses, personality-pin leaks, errand bound
escapes (steps/time/API), inferred-memory promotion without
owner confirmation, ledger gaps (calls that aren't journaled),
async races in pause/resume/cancel.

**Hunter B — embodied:** `observation.py`, `nus_pointer.py`,
`hands/**`, `disclosure.py`, wake/voiceprint paths, `safety.py`.
Hunt for: any path where pointing becomes acting, tier-3 digest
replay/expiry holes, expected-effect verification that can pass
on a stale frame, sensitive-target refusals that a renamed label
evades, injection through element names/labels, fail-open
(instead of closed-and-logged) danger verbs.

**Hunter C — edges:** `src/alive/**`, `alive_sync.py`, `reach/**`,
`storage.py`, `backup.py`, `remote.py`, `tiering.py`, phone-link
modules, `console/**`. Hunt for: WhatsApp window/cap accounting
errors, envelope signature/replay gaps, stranger-tier confusion,
fetcher allowlist/redirect escapes, journal-after-fetch ordering,
backup states that flip without hash proof, restore paths that
can overwrite live data, phone verbs other than `sms.send_sms`.

## Consolidation (manager, after all three land)
Manager re-runs or statically confirms each P0/P1, dedupes,
and writes `bugs.md`: one table (ID, severity, where, failure,
status, fix owner), SUSPECTS in an appendix. Fix lanes are
dispatched from `bugs.md` by severity — P0s first, each fix its
own PR with a regression test named after the bug ID.
