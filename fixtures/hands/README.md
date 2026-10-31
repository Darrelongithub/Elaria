# Hands synthetic fixture inventory

[TESTED-ONLY] All files here are synthetic, not recorded model requests or owner
content. `inventory.json` records origin and SHA-256 checked with existing
`assistant.safety` primitives. The inventory-only status describes the stored
file, not an executed instruction.

- [TESTED-ONLY] `messy/note.txt` and `filed/note.txt`: same basename, different
  bytes. The core composite test creates an equivalent minted tmp tree and
  proves exact-path collision repair without overwriting the occupied target.
- [TESTED-ONLY] Six trap origins: file, filename, stdout, stderr, retrieved and
  tool_output. The core test **reads these exact inventory files** (or basename)
  and injects their data before dispatch. All four oracle conditions are checked:
  hands.inject / refusal / no runner or mutation afterward / console report.
- [TESTED-ONLY] A separate simulated stdout test retains the legitimate read and
  permits already-adjudicated subsequent steps unchanged. No step originates
  from data, no planner is called on output, and no raw trap text enters logs.

[UNVERIFIED] The conservative lexical detector is not a universal semantic
prompt-injection detector. The structural boundary is stronger than detection:
immutable plans plus no data-to-plan update API. No live or hardware proof.

[TESTED-ONLY] Never mutate the tracked fixture tree. `SyntheticSpace` mints and
cleans temporary roots; the core seeds aged synthetic files and indexes them
through Store. No recent-file or policy bypass for task execution.
