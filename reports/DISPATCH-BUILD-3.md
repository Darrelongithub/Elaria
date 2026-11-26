# DISPATCH-BUILD-3 — third wave (manager, 2026-11-25)

Owner priority order: **provider routing first** (every other lane
spends through it), then the WhatsApp layer (omitted from the
manager's leftover list — corrected here), then the remaining
scavenger gaps and the capability-request protocol. Persona lane
still awaits the owner's explicit dispatch go-ahead.

## BUILD-9 — Agent I (provider routing ACTIVATION — do this first)

> You are Agent I. BUILD-8 landed the seam
> (`src/assistant/provider_router.py`, personality pin in code,
> `provider` ledger column); nothing is enabled and no diverted
> workload uses it yet. Activate it, in this order:
> (1) **Verification checklist, per candidate provider** (Groq,
> OpenRouter `:free`, Cloudflare Workers AI): the exact account-page
> facts the OWNER must confirm (free tier active, NO card on file,
> model-specific limits, data terms). Output this as a one-page
> owner checklist in your report — you cannot verify his accounts,
> and you must not create accounts or hold credentials.
> (2) **Wire the real diverted workloads through the router** —
> this is the point of the lane: planner classification/extraction
> (`planner_llm.py` material path), REACH summarisation budget,
> and the pointer's VLM grounding role (BUILD-3) must call the
> router's material dispatcher, not ad-hoc clients. Any workload
> still bypassing the router is a failed lane — grep for it.
> (3) **Adapters** for the candidates behind the dispatcher,
> disabled by default, enabled per-provider by config ONLY after
> the owner's checklist item for that provider is marked verified
> in `[quota.providers.*]` (zero/absent cap = unavailable, never
> unlimited — keep BUILD-8 semantics).
> (4) **Owner surface:** `assist cost` must answer "what did today
> cost, per provider, per purpose" from the ledger, and the
> degradation ladder must be observable (which rung are we on,
> why). Tests: personality still pinned under diverted-provider
> 429s AND outages; a diverted provider returning prompt-injection
> text stays data (IF-6) and is re-voiced or dropped, never
> spoken raw; ladder walks down and recovers. API budget: restate
> the per-provider caps you ship as defaults. New `arena/*`
> branch, PR, merge yourself. Never edit OWNERS.yaml.

### BUILD-9 STATUS (manager, 2026-11-26): NOT LANDED — re-dispatched

Agent I reported a partial execution (owner checklist drafted;
planner/pointer-VLM/REACH routing, Cloudflare adapter, `assist
cost` and ladder surfaces incomplete; tests not run). **No
artefact reached this repo** — no file, commit, PR, or merge — so
nothing is verified and BUILD-9 remains OPEN in full. The candour
is noted and correct; the lane is re-issued below as BUILD-9R.
Rule restated for all agents: a lane is done when its PR is
merged, not when a summary exists. If your sandbox lacks a tool
(e.g. pytest), install it (`pip install --break-system-packages
pytest`) or say so in the PR — never end uncommitted.

## BUILD-9R — Agent I (provider routing activation, complete)

> You are Agent I. BUILD-9 was reported partial and NOTHING
> landed (no PR) — this re-issue is the whole lane, to merged
> completion. Start from BUILD-8 on main
> (`src/assistant/provider_router.py`, personality pin in code).
> (1) Owner checklist: one page in your report — per candidate
> (Groq, OpenRouter `:free`, Cloudflare Workers AI) the exact
> account-page facts the owner confirms (free tier active, NO
> card on file, model limits, data terms). You create no accounts
> and hold no credentials. (2) Route the REAL diverted workloads
> through `ProviderRouter.material()`: planner
> classification/extraction material path, REACH summarisation,
> pointer VLM grounding role. Grep-prove no workload bypasses the
> router; a bypass = failed lane. (3) Adapters for all three
> candidates, disabled by default, enabled only via a verified
> flag in `[quota.providers.*]` (zero/absent cap = unavailable).
> (4) Owner surfaces: `assist cost` answers per-provider
> per-purpose spend from the ledger; degradation-ladder state is
> observable (current rung + why). (5) Tests, RUN and reported
> with numbers: personality pinned under diverted 429/outage;
> injected diverted text stays data, re-voiced or dropped, never
> spoken raw; ladder degrades and recovers. Deliver on a new
> `arena/*` branch as a MERGED PR — commit your work; an
> uncommitted summary does not close this lane. If a step is
> impossible in your sandbox, land the rest and file the blocker
> IN THE PR, not in chat. Never edit OWNERS.yaml.

## BUILD-10 — Agent E (WhatsApp layer — the real transport)

> You are Agent E. BUILD-6 built the alive layer against a FAKE
> transport. Now build the real WhatsApp side, up to the owner's
> registration seam: (1) WhatsApp Cloud API transport adapter
> (send template / send session message, webhook payload parsing
> already exists — verify it against Meta's documented payload
> shapes with fixtures, cite the docs), business number = the
> owner's spare SIM, registered by the OWNER. (2) The S-0 template
> pack: author the exact reminder/knock templates (meeting,
> deadline, commitment-due, already-sent knock) as code-reviewed
> strings ready for Meta template submission, with the
> outside-24h-window rule enforced in the transport (template or
> nothing; a free-form cold send must be impossible, tested).
> (3) Owner runbook: the numbered registration steps (Meta app,
> number registration on the spare SIM, token custody on the
> laptop, webhook URL = the serverless endpoint, test-number
> limits) written for a non-expert, in
> `reports/RPT-E-whatsapp-runbook-*.md`, ending with the on-laptop
> eye check: owner messages her number → laptop off → she answers
> in-window free; >24h silence → template knock arrives.
> (4) Cost guard: per-day paid-template cap in code (default
> small; KES-cents arithmetic in the runbook), journaled per send.
> S-1 chatty mode stays OFF (Meta grey zone). New `arena/*`
> branch, PR, merge yourself.

## BUILD-11 — Agent Z (scavenger gaps GAP-2 + GAP-3)

> You are Agent Z. Close the two gaps that make the owner's
> scavenger instruction real: GAP-2 read-only discovery roots
> (configured roots, path/filename index search, archive-manifest
> inspection, protected paths untouched) and GAP-3 full
> large/structured-file streaming (chunked, schema-inspected,
> loud failure — the >200KB silent truncation dies). Treated as
> untrusted data end-to-end (IF-6); prove generality with a
> second fixture domain, no chat-shaped code. From
> `reports/RPT-B-scavenger-gaps-20261125T161536Z.md`. New `arena/*`
> branch, PR, merge yourself.

## BUILD-12 — Agent B (GAP-6 + GAP-7: ask-and-learn lifecycle)

> You are Agent B. Build the full clarifying-question /
> pending-verification state machine (GAP-6) and the inferred-
> memory lifecycle (GAP-7): grouped questions, only authenticated
> owner confirmation promotes `inferred → stated`; inferences stay
> probationary (confidence < 1.0, always outranked by stated,
> conflict = ask, stale = decay/expire). From your own audit
> `reports/RPT-B-scavenger-gaps-20261125T161536Z.md`. New `arena/*`
> branch, PR, merge yourself.

## BUILD-13 — Agent Z (GAP-4 + capability-request protocol)

> You are Agent Z. Two items: (1) GAP-4 local-first map-reduce
> comprehension over multi-chunk/multi-file material within the
> `[quota]` ladder (rolling limiter; cheapest tier first; cost
> journaled per chunk). (2) The capability-request protocol
> (owner ruling): when a task needs a tool/package/permission she
> lacks, she files ONE structured ask (what, why, what it unlocks,
> risk, cost) and waits — she never downloads, installs, or
> self-modifies autonomously; approval is per-request and
> journaled; denial is final for that request. New `arena/*`
> branch, PR, merge yourself.
