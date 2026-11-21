# R · hands fixtures and records

Cluster R owns these proving grounds and the paper trail. Every text file under
`fixtures/hands/` is **inert untrusted observation data**. It is never a command,
never a script, and never an instruction to the agent or to the runtime.

- Contract: `IF-6` — untrusted-input rail, frozen at
  `6961c7f8b72d223d053bd20a45d8401e0466d358565ecf19952aaf5ee0ca351f`.
- A trap marked `ARMED` contains a deliberately adversarial string. Loading it
  must produce a recorded refusal, zero mutating actions, a planner observation
  tagged as data, and a journal row.
- `filed/note.txt` and `messy/note.txt` are benign negative controls; they are
  not armed and carry no instruction-like payload.
- `inventory.json` is the trap-arm manifest: it pins each fixture path, armed
  state, SHA-256, and expected refusal.
- `pilot-scenes.md` maps the five owner-ruling criteria 1:1 to five spec-only
  scenes. Execution is owner-only in Wave 2; this cluster runs no hardware.
- `console/undo-review-test.js` is the local, deterministic acceptance test. Run it
  with `node console/undo-review-test.js` from the repository root.

Records are annotated with dated append-only notes; historical bodies are never
silently rewritten. R owns no production code. O owns the injection rail, P the
headless host, Q the kitty inventory, and Z the shared wire files.
