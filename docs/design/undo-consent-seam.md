# Undo consent seam — R records note (2026-11-19)

Status: **records only; no production code owned or edited by R**.

The owner’s single-op undo review seam is a two-call console/daemon route:
`undo.prepare` resolves and pre-verifies exactly one operation, returning an
immutable snapshot plus a memory-only, single-use token; `undo.apply` answers
Yes/No, re-verifies the whole snapshot, and refuses totally on row or filesystem
drift. Bare `undo` stays refused. A No, a lapse, a replay, or drift is terminal.

Dated annotation, 2026-11-19: the 2026-11-04 design note suggested a 120 s
expiry; commit `e7316b9` implemented `UNDO_ASK_TTL_S = 600.0` and 18 test pins.
This note records that change without rewriting the earlier design record. R’s
acceptance test checks the fixtures and records only; O owns `injection.py` and
Z owns the daemon route.

Invariants R must preserve in its paper trail:

- deny-beats-consent;
- a Yes approves a snapshot, never a query;
- attribution is derived, never claimed in JSON;
- the CLI daemon-down fallback is uncontained and must be stated plainly;
- records are annotated, never silently rewritten.

Pilot execution is owner-only in Wave 2. No hardware claim is made here.
