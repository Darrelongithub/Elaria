# Report 021 - Increments 5 and 6 delivered, and the refusal-posture question answered

**Date:** 2026-11-02 (Africa/Nairobi)
**Branch:** `arena/storage`, HEAD after this report: increment 6 committed
**PR:** #24 (base `arena/c2a7085d-elaria` @ `bf5ef2b`)
**Frozen branch (condition 3):** `origin arena/e7a1cca5-elaria = b181712563c1577f5faea4e59fe5f7e104a89ed1` - verified before and after this activation. Untouched. Local ref still `ed20344` (fresh-clone artifact); not pushed, not "corrected".

**Fourth base movement.** The PR base moved `bf5ef2b` -> `be9183c` ("probe raw pass: name
part types + the audio_transcription accessor"), touching only
`scripts/file_leg_probe.py` and `tests/test_file_leg_probe.py`. My branch's merge-base
with the base is `f915d8e` and is unchanged - no history rewrite, I am simply behind by
mainline progress. **This is a bare base movement: it triggers nothing.** The sole early
trigger is a NAMED shape/phrasing change from mainline, and it did not fire:
`src/assistant/journal_log.py` is **byte-identical** between the last-verified tip
`bf5ef2b` and `be9183c`, `audio kept at` is still **4** occurrences (daemon.py:1,
transcribe.py:3), and Drift 2 does not recur. The two-clause §2 check was re-run against
the new tip and both clauses hold (6 parts with no detail, 7 with; `parts[2]` is the event
name and dispatch keys on it, never `parts[5]`). Per the duplicate/stale-relay ruling the
suite was re-measured unconditionally: 2104/6/0, ruff clean. No re-dating, no re-measure
of the baseline, no GATE 1e re-verification.

---

## DONE

Two increments landed since report 019. The design chat asked, for the next report, for
**increment 5's substance, its suite delta, its boundary audit, and whether it introduced
anything that touches the verification provenance**, plus **increment 6**, plus an answer
to the refusal-posture question. This is that report.

### Increment 5 - `assist backup` CLI + sensors (`cb8d636`, pushed)

The design chat has not yet seen this increment's substance. It is:

- `src/assistant/sensors.py` (274 lines) - the six `backup.*` events and `storage.gauge`,
  every line conforming to the canonical §2 contract: `split(" ", 6)` into 6 or 7 parts,
  `session_id` = `-`, `peak` = `-`, and dispatch keyed on the event name (`parts[2]`),
  never the verdict.
- `src/assistant/backup_cli.py` (392 lines) - `run`, `status`, `fetch`, `check`, the
  `BackupContext` builder, and the local-path restorer fixture.
- `tests/test_wp7_backup_cli_sensors.py` (45 tests) - §2 contract conformance and the
  CLI's refusal postures.
- `tests/test_bug7_cli_smoke.py` +8 entries (4 leaves) so every new parser leaf has a
  smoke invocation. The test was not weakened.

**Boundary audit for increment 5.** It touched `sensors.py` (new), `backup_cli.py` (new),
`cli.py` (2 lines, additive - the registration and the dispatch), and the smoke table
(+8/0). It did **not** touch any verification code, because verification is increment 4's
and this increment only *calls* it. The one thing it added that reaches verification is
`BackupContext.verifier_backend()`, which is the seam the ladder chain now hangs its
provenance on - see increment 6. No forbidden file touched.

**Its suite delta:** 2017 -> **2062** (+45), ruff clean. That was the committed baseline.

### Increment 6 - ladder chain #5 "backup chain" (this activation)

`backup_chain(self, *, ctx=None)` in `src/assistant/ladder.py`: five rungs A-E, the last
being **the integrity rung the WP7 gate names** - restore a cold artifact to a temp dir
and hash-verify it.

Tri-state throughout. **N/A is the honest answer for a thing not configured yet.** An
unconfigured remote is not a failure; calling it STUCK would make an unbuilt lane look
broken. Only a real fault is STUCK. In this lane's sandbox no remote is configured, so
the chain reaches N/A rather than reaching for a network.

**Rung C is deliberately local-only** (`pin_status()` = `rclone version`, no network), so
a truth ladder never silently reaches MEGA. Probing a real artifact against MEGA is the
integrity rung's job and is an owner-initiated act.

**Provenance is carried in every rung's evidence.** Rung C names the backend, so a
fixture reads `local-path-fixture ready; method=fixture` and can never masquerade as a
remote. A fixture flip records `(local-path-fixture, hash)`; a rclone flip records
`(rclone:mega-elaria, presence)`.

`tests/test_wp7_ladder_backup_chain.py` (39 tests) covers the tri-state rungs, provenance
in every rung's evidence, the privacy fence, and the integrity rung including tamper and
restore-failure STUCK paths.

**Its suite delta:** 2062 -> **2104** (+42: +39 the new file, +3 the regression tests
below), ruff clean.

---

## THE REFUSAL-POSTURE AUDIT - the design chat's question, answered

The design chat required the five refusal postures be **updated and reclassified
(satisfiable vs structural) rather than carried forward by habit, because increment 4
changed the answer.** I enumerated the refusal paths from `backup.py` directly rather than
carrying the five forward. **There are thirteen, not five.**

**The no-verifier posture (`backup.py:122`) is FORMALLY RETIRED.** Proven by test:
`plan_reconcile(man, now, verify_remote=None)` refuses; supply
`make_verifier(LocalPathBackend)` and the same artifact flips. A fixture flip now lands as
`(local-path-fixture, hash)`, a real one as `(rclone:mega-elaria, presence)`. **That
provenance threading is what actually retired it** - the refusal is gone because a
verifier can now be *named*, not merely supplied.

### SATISFIABLE (4) - real conditions a real configuration can meet

| Line | Refuses when | Satisfied by |
|---|---|---|
| 122 | no remote verifier supplied | increment 4 - **RETIRED** |
| 129 | verifier does not confirm | a real backend that holds the artifact; a declared skip still correctly refuses |
| 200 | no trim mover | increment 3 |
| 221 | no purge mover | increment 3 |

### STRUCTURAL (9) - must never be satisfied

| Line | Refuses when | Why it must never be satisfiable |
|---|---|---|
| 111 | local artifact missing | nothing to back up; satisfying it would mean inventing data |
| 117 | local hash differs from the manifest record | the copy drifted; uploading it would back up corruption |
| 150 | no clock supplied | reconcile is time-dependent; guessing "now" is un-auditable |
| 157 | timestamp unreadable | same |
| 195 | flip refused by the state machine | the transition is illegal |
| 206 | trim failed | the hot copy is not in trash yet |
| 228 | purge failed | the file is still there |
| 236 | purge target already absent | **informational - the goal is met** |
| 330 | did not reach quiescence in 8 passes | a cycle; satisfying it would mean looping forever |

### The load-bearing distinction, pinned as a test

**A verifier does NOT rescue L111 or L117.** If it did, those guards would be theatre.
Retiring the *absence of a verifier* does not retire the *data-loss guards*.

This is pinned as a test so the classification cannot drift back into habit - which is
precisely what the design chat warned against. The audit includes a **table-completeness
test that fails if any refusal path is added or removed**, so the answer cannot silently
rot when `backup.py` changes.

---

## DEFECTS FOUND

### D7 has fired - and it is not mine

The intermittent `ERROR` on
`tests/test_gate_fix_round.py::test_hold_to_talk_ptt_start_stop_still_works` is now
characterised. It is **pre-existing, intermittent, and in a file this lane may not edit.**

```
tests/conftest.py:108: AttributeError
    clients = [task for task in asyncio.all_tasks()
               if task is not current and not task.done()
               and task.get_coro().__qualname__ == "serve.<locals>._client"]
E   AttributeError: 'async_generator_athrow' object has no attribute '__qualname__'
```

`task.get_coro()` returns an `async_generator_athrow` when an async-generator fixture is
being torn down concurrently with the daemon-shutdown coroutine, and
`.__qualname__` is unguarded on that path.

Evidence, all measured this activation:

- **Frequency:** 1/20 runs with my changes; **3/20 runs at `60f0060` with my changes
  stashed**. Statistically indistinguishable - it is noise, not this increment.
- **Pre-existing:** reproduces at `60f0060` before any increment-6 change.
- **A flake, not a deterministic failure:** the full suite ran clean at 2101/6/0 twice,
  and again at 2104/6/0 now.
- **The unguarded line at `tests/conftest.py:108` is the one report 005 recorded as
  "present-but-not-firing."** It has now fired. The books said the defect was present, not
  fixed; that record was correct and this is the confirmation.

`tests/conftest.py` is on the lane's forbidden list, so I have not fixed it. The fix is
one line - `getattr(task.get_coro(), "__qualname__", None) == ...` - and it belongs to the
mainline lane, not this one. **Flagging it as a mainline action item.**

### The content assumption the design chat asked about - FOUND, and fixed

The design chat's note: *if any storage test or fixture rests on an assumption about
content that nobody has verified, now is a cheap moment to say so in the report.*

**It did. `WAV_HEADER_BYTES = 44` in `tiering.py` rested on an unverified assumption, and
it was wrong for a real case.** I proved it empirically rather than asserting it:

- A canonical PCM WAV's `data` payload begins at byte **44** - correct.
- **A WAV carrying a LIST/INFO chunk with ZERO frames is 62 bytes and the old
  `is_header_only_wav()` returned `False`** - i.e. it read a real never-retry mark as a
  recording. Such a file would have been tiered, trimmed and purged as if it were audio,
  and counted against the capacity model.

The old implementation compared a total size, which is right only for the canonical
header. **Fixed** by walking the RIFF chunk structure and reading the `data` chunk's
declared size - which is what actually says whether there are frames. Still cheap: one
bounded read of 4096 bytes, no full parse, no hashing. Three regression tests pin it,
including the chunked-zero-frame case and a non-RIFF file.

**This is the fourth time a fixture in this lane has been quietly wrong** (an 18-byte
stub, a 64-byte blob, and now this). Fixing the classifier exposed that
`tests/test_wp7_backup_cli_sensors.py`'s `_WAV = b"RIFFfakeWAVEdata" + b"\x00"*64` parses
as a real RIFF with a zero-length `data` chunk - so it read as a *mark*, not a recording,
and two tests silently asserted nothing. The fixture is now built with the `wave` module,
so it cannot accidentally look like something it is not.

**The honest answer to the design chat's question, in full:**

- **No storage-lane module parses audio content at all** - no `wave` read, no
  `readframes`, no `struct.unpack` in `tiering.py`, `storage.py`, `remote.py`,
  `sensors.py` or `backup.py`. So no test rests on a fixture containing intelligible
  speech, and none should.
- **But the 44-byte constant did rest on an unverified assumption about real WAV header
  structure**, and it was load-bearing: it decides what "counts zero forever."
- The tiering fixtures are still synthetic byte blobs that are **not valid WAVs and
  contain no speech**. The census numbers (11-13 MiB/day) come from real wavs nobody has
  listened to, and the compression band 0.475/0.582 is [TESTED-ONLY] on real wavs, **not**
  an end-to-end restic-over-MEGA round trip.

---

## Boundary census - increment 6

8 files, **259 insertions / 20 deletions**. The 20 removed lines, exhaustively:

| File | Removed | What it was |
|---|---|---|
| `src/assistant/cli.py` | 2 | the argparse `choices` tuple and the `help` string |
| `src/assistant/ladder.py` | 2 | argparse `description` string and `choices` tuple |
| `src/assistant/backup_cli.py` | 1 | a hardcoded `grace_days: int = 14` default, now read from config |
| `src/assistant/tiering.py` | 6 | the old size-comparison body of `is_header_only_wav` |
| `tests/test_wp7_backup_cli_sensors.py` | 7 | my own increment-5 fixture and one redundant line |
| `tests/test_wp0_ladder.py` | 2 | the `20 # 4 chains x 5 rungs` assertion and the chain tuple |
| `src/assistant/remote.py` | 0 | purely additive |
| `tests/test_wp7_tiering_trim.py` | 0 | purely additive |

**The additive-only rule cannot be honoured *literally* at the argparse registration** -
a new chain must appear in the `choices=` tuple or the command does not work. That is 4
of the 20 removed lines, all inside `main()`/parser construction. `run_chain()` and
`run()` were restructured to be *genuinely* additive - append after the literal, never
splice into it - so nothing else in the dispatch changed.

`tests/test_wp0_ladder.py` (2 removed) is a **designed extension point**: it pins
"20 rungs / 4 chains" precisely so a new chain must be declared. It is not on the
forbidden list. `tests/conftest.py` was not touched.

**Forbidden files, verified untouched against `60f0060`:** `src/assistant/daemon.py`,
`src/assistant/transcribe.py`, `src/assistant/live_client.py`, `HANDOFF.md`,
`tests/conftest.py`. **Zero changes to all five.**

---

## Suite

| Tree | Passed | Skipped | Failed | Ruff |
|---|---|---|---|---|
| pristine `f915d8e` | 1913 | 6 | 0 | clean |
| increment 5 (`cb8d636`) - committed baseline | 2062 | 6 | 0 | clean |
| **increment 6 (this activation)** | **2104** | **6** | **0** | **clean** |

Report 005's 1913/6/1-error is superseded; D7 did not fire in that run, and the error
count was the same flake described above.

---

## NEXT GATE

Report 021 carries, for the design chat's verification:

1. **Increment 5's substance** (above) - never before seen by the design chat.
2. **Increment 6** - ladder chain #5, all five rungs, ending in the integrity rung.
3. **The refusal-posture audit** - 13 paths, reclassified, with the table-completeness
   test that stops it rotting.
4. **The D7 finding** - a mainline action item, not mine to fix.
5. **The content-assumption note** - the 44-byte assumption was load-bearing and wrong;
   now fixed and pinned.

Gate 1 remains unchanged: **no live MEGA traffic, no merge.** Increments 5 and 6 are
**not verified** until the design chat rules on them. After that ruling sit only
increments 7 (post-close hook + nightly timer + WP5 monthly trigger shape) and 8 (monthly
restore-drill scaffolding) before the WP7 gate can be assembled.

---

## OPEN QUESTIONS

1. **D7 - who fixes it?** One line in `tests/conftest.py`, forbidden to this lane. Needs
   a mainline owner. Until then the suite carries a ~5-15% teardown error rate on that
   one file, which is noise but not free.
2. **Does the owner's pipeline ever emit chunked WAVs?** The fix is correct either way,
   but if it never does, the 44-byte case was the only real one and the risk was
   theoretical. If it does, this prevented a real misclassification. Unverified.
3. **Report 020's §9 obligations** remain open pending the design chat's ruling on the
   harness incident; this activation saw no recurrence, and the frozen branch verified
   clean before and after.
