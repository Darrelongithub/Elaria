# WP7 accd33a readback findings — Agent V

Recorded 2026-11-19. **FROZEN / source-readback only; not live readiness.**

## Provenance and limits

Source revision: `accd33a38035dfdf5f4dece42cc67f70e97c4ce0` on
`arena/storage`. Work branch: `arena/3aa09968-elaria`, based on
`ed20344fc55806b8c83db756cd04984e86b89e5c`. The storage branch was read
through the GitHub API, not checked out, rebased, reset, or modified.

The letter references an uncommitted findings document. It is absent from both
this checkout and the source commit's tracked tree. **This is a newly reconstructed
readback, not recovery of that missing document.** Its unknown contents remain owed
by the owner/orchestrator. Absence from a Git tree cannot establish whether an
uncommitted copy exists on another machine.

IF-5 was checked against the v3 pack manifest before edits; SHA-256:
`42d216204d0c0f50bb44dad4aba3888a3f7d9bbc38f3c4e740d416db281af810`.
Contracts are not copied into the repository.

## Readback: numbers, source locations, evidence boundary

| Item | Source observation at accd33a | Boundary / responsible agent |
| --- | --- | --- |
| Live context | `backup_cli.py:212–249`, `build_context`, creates verifier/backend/quota reading but supplies **0** `restorer`, `trim_mover`, or `purge_mover` arguments. | Injected fixture capabilities are not proof of production wiring. T must wire and test these edges; V changes no logic. |
| Resolver | `backup_cli.py:273–307`, `_resolve_artifact`, tries **3** forms: expanded, filesystem-resolved, and audio-root/basename. It supplies **0** suffix-appending or prefix-resolution steps. | A full filename resolving does not prove the owner's extensionless prefix resolves. T owns deterministic `.wav`/prefix handling and ambiguity refusal. |
| Benchmark repository forms | `storage-benchmark.sh` passes the same `repo` to restic `-r` and rclone `lsf` (e.g. lines 241, 247–248). | Restic's `rclone:` transport prefix and rclone's remote syntax are distinct. This is a source-level concern, not a measured tool failure. T must separate arguments and pin tests. |
| Historical suite | accd33a commit message reports **2227 passed / 6 skipped / 172.61 s**, ruff clean. Report 028 records **2207 / 6 / 168.08 s** at its earlier revision. | Historical author measurements, **0** reruns of either storage suite here. Neither number describes this branch. |
| Historical live gate | Report 028 records **3 met / 4 blocked** across **7** conditions. | Historical ledger, not renewed live acceptance. No owner benchmark, restore, drill, or listening receipt obtained in this activation. |
| F24 | Required remote headroom **2,719,664,640 B** = scratch **1,719,664,640 B** + margin **1,000,000,000 B**. | `remote_free=unknown` is refusal, not a fabricated quota. Only owner evidence can open the live gate. |

## Seven-row gate ledger (no fresh live receipts)

1. Benchmark ruled go: pending owner numbers, including latency budget.
2. Kept wav cold/flip/grace-trash: pending T wiring plus owner execution.
3. Crash points: historical report 028 says 23 passed; not rerun here.
4. Fetch/listening within budget: pending cold record, prefix resolution, budget,
   and the owner's ear. A successful restore alone is not listening acceptance.
5. Monthly drill: pending cold record and owner run. Empty drill exit 0 is not a pass.
6. Ladder chain including integrity: historical 64 tests; not rerun here.
7. Credential hygiene: no credentials introduced by V; no comprehensive secret audit
   claimed from an empty text search.

## Coordination / owed work

- T: verify/fix the three source-readback concerns above and return measured tests;
  publish wiring dry-run receipts with no live transfer before owner execution.
- S: status counts MANIFEST records, not discovered files; `artifacts=0` before
  indexing cannot distinguish an empty manifest from a wrong scan root. Scan the
  assistant data root, not an audio-only configurable root.
- Z: shared config/store/schema/daemon integration remains exclusively Z-owned.
  No request to edit those files is implied by this record.
- Owner: recover the original uncommitted findings document if available; configure
  `[backup]` remote naming locally (`elaria-mega`, subject to readback), provide
  quota and owner-run results. Never send credentials or real recordings here.

## Time and negative evidence

The historical named capture's 14-day window ended on 2026-11-16. On 2026-11-19,
calendar eligibility is no longer the old wait, but **elapsed time proves none of
remote configuration, cold transition, integrity, drill, or delivery**. The live
sequence remains **0 → 1 → 3 → 5 → 4**. No live commands were run in this activation.
`sent_cold` is classification, not evidence that a move occurred. Hash mismatch or
failed restic check must be recorded as failure, never repaired into a pass-shaped
claim. An empty stop log with 0 live operations cannot establish stop-condition
coverage.
