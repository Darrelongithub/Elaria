# DISPATCH-BUILD-2 — second build wave (manager, 2026-11-25)

BUILD-1 (pointer) and BUILD-2 (errand runner) are landed and
manager-verified. This wave wires the pointer to a voice, adds the
mouse behind the owner's gates, **completes storage**, then builds
the cloud trio. Order below is build order; lanes are independent
enough to run in parallel where noted. Standing rules unchanged:
thresholds frozen, OWNERS.yaml untouched by agents, one eye-check
per wiring claim, declared API budget per lane, sandbox numbers
labelled sandbox, hardware claims are the owner's eyes only.

## BUILD-3 — Agent H (ask → point: make the pointer askable)

> You are Agent H. BUILD-1 proved the ring lands; now make it
> askable. (1) Register a read-only `point` skill in the errand
> runner's vocabulary (`src/assistant/errand.py`): an instruction
> like "where is the delete button / point at Settings" becomes an
> errand step that captures, grounds via AT-SPI first, and draws.
> (2) Assign the VLM fallback a budget role under
> `reports/SPEC-PROVIDER-ROUTING.md`: grounding is diverted
> material, NEVER the personality tier, never the 20/day flash
> escalation; declare the per-day cap in config next to `[quota]`
> and journal every grounding call. VLM coordinates stay labelled
> unidentified (confidence from code gates, "best guess" spoken
> below sure). (3) Wire the same skill to the console/voice ask
> path so `assist` and the daemon can invoke it outside an errand.
> NO clicking, NO acting — point only. Eye-checks: fixture
> instruction → ring IPC fired with fixture bounds; sensitive
> target refused; VLM-disabled mode → AT-SPI-only, honest
> "I couldn't find it". New `arena/*` branch, PR, merge yourself,
> and end with the owner's on-laptop eye check in order.

## BUILD-4 — Agent O (mouse act, behind owner tier-3 gates)

> You are Agent O. Build mouse acting on the shared observation
> layer from `reports/RPT-O-mouse-blueprint-20261125T113104Z.md`,
> under the owner's rulings in `reports/DISPATCH-MOUSE.md` GATE
> DECISIONS (read them first; they are binding): tier-3 per-digest
> in-person confirmation ONLY — a spoken/typed digest of the exact
> planned actions, approved as a batch, never per-click nagging
> and never standing permission; expected-effect verification
> after each action (re-observe; mismatch = stop, report, do not
> improvise); a kill condition that halts mid-digest on any
> unexpected screen state; Hyprland 0.56+ rules apply (NO
> string-formatted `hyprctl dispatch` coordinates — Lua injection
> surface; IPC positions cursor, cannot click; all enforcement is
> ours). Clicks are danger verbs: fail closed AND logged; journal
> BEFORE action. Eye-checks with fake compositor/input fixtures:
> approved digest executes in order; unapproved digest does
> nothing; screen change mid-digest halts before the next click;
> kill condition fires. No real input injection in sandbox.
> New `arena/*` branch, PR, merge yourself.

## BUILD-5 — Agent S (storage completion: backup you can restore from)

> You are Agent S. Storage phase 1 is LANDED (`storage.py`,
> `tiering.py`, `backup.py`, `remote.py` with the rclone backend,
> PR #110). Complete it to owner-usable: (1) Backup verification —
> an artifact may flip to "backed-up" ONLY after a hash-confirmed
> copy lands on the remote (owner's own Google Drive via rclone;
> in sandbox use the fixture `LocalPathBackend`, labelled fixture
> everywhere — never report a sandbox backup as real). (2) A
> restore drill: scripted restore of a backed-up artifact into a
> scratch dir, hash-compared, journaled — if the drill fails, the
> backup state must say so loudly. (3) Owner surface: `assist
> backup {status,run,verify,restore}` wired to the existing
> `backup_cli.py`, plus tiering hooks so hot/warm/cold movement
> triggers backup of newly-cold artifacts. (4) Failure posture:
> remote unreachable = journaled, retried, reported; silence is
> never success. Eye-checks: fixture remote round-trip flips
> state only after hash match; corrupted fixture copy is caught
> by verify and does NOT flip; restore drill reproduces the exact
> bytes. Real Drive credentials are the owner's laptop step —
> build everything up to that seam, no network in sandbox.
> New `arena/*` branch, PR, merge yourself.

## BUILD-6 — Agent E (alive layer: cloud heartbeat build)

> You are Agent E. Build your own design
> (`reports/RPT-E-alive-layer-20261125T122137Z.md`, gate PASS,
> manager defaults adopted in `reports/DISPATCH-ALIVE.md`):
> free-serverless-shaped webhook receiver + append-only queue +
> commitment mirror, WhatsApp Cloud API S-0 templates only,
> stranger tiers T0/T1/T2 by transport-authenticated number,
> laptop drains via `cloud_queue.enqueue_external` →
> `awaiting_approval` → spoken yes → all existing gates.
> NO authority on the host: egress allowlist, single-recipient
> config, template cap in code, signed envelopes, no audio stack.
> Sandbox: fake Meta webhook payloads + fake transport; real
> registration is the owner's laptop step. New `arena/*` branch,
> PR, merge yourself.

## BUILD-7 — Agent REACH (internet fetcher, Phase 0 build)

> You are Agent REACH. Build the Phase-0 fetcher from your design
> (`reports/RPT-REACH-phase0-20261125T122452Z.md`, gate PASS):
> egress allowlist GitHub API + generic web/news only, every
> request journaled, fetched content lands as provenance-tagged
> untrusted data (IF-6 structural split — it cannot reach a
> tool/plan/intent path), terminal journaled outcomes for
> `PLATFORM_BLOCKED`/`NEED_LOGIN`/rate-limit, never evaded.
> Interestingness stays reason-gated and budgeted (declare the
> summarisation budget; never the personality tier). Sandbox:
> fixture HTTP only, no live network calls in tests.
> New `arena/*` branch, PR, merge yourself.

## BUILD-8 — Agent I (provider routing build)

> You are Agent I. Build the routing seam from your design
> (`reports/RPT-I-provider-routing-20261125-design.md`, gate
> PASS): personality pin enforced at the call boundary IN CODE
> (Gemini only; no failover — she gets quieter, never someone
> else), diverted-material adapters behind the same boundary,
> per-provider quota rows (never inheriting Gemini's verified
> marker; 0 ≠ unlimited), `provider` column in the cost ledger,
> degradation ladder as designed. The Piper-vs-Gemini voice
> question is the OWNER's ears — do not touch audible identity;
> build everything up to that seam. No provider enabled without
> the owner's account verification (free/no-card confirmed on the
> account page). New `arena/*` branch, PR, merge yourself.
