# DISPATCH — internet eyes + always-alive layer (research first)

Governed by `reports/PROCEDURE-NEW-IDEAS.md` and bounded by
`reports/OWNER-RULING-INTERNET-20261125.md`. Research/blueprint
only in both channels; builds come after the manager gate.

## CHANNEL R-0 — Agent REACH: internet eyes, Phase 0 design

> You are Agent REACH. In your Elaria checkout read
> `reports/OWNER-RULING-INTERNET-20261125.md` and the Agent-Reach
> design summary (HANDOFF §12A, in `reports/RPT-Z-manager-20261125.md`
> references + `src/assistant/reach/` — REACH cluster already owns
> `reports/RPT-REACH-*` and `src/assistant/reach/**`). Deliverable:
> a Phase-0-blueprint report `reports/RPT-REACH-phase0-*.md` that
> turns the ruling into an implementable design WITHOUT writing the
> fetcher: (1) the egress contract — public reads only, exact
> channel allowlist starting GitHub API + generic web/news, every
> request journaled before it leaves; (2) the untrusted-input
> split — fetched content enters as data with provenance and can
> never reach a tool/plan/intent path (structural, citing how
> `hands/injection.py` and memory's IF-6 rail already enforce the
> analogous rule); (3) her own accounts — how an Elaria-owned
> account (e.g. her X) is created by the owner, credentialed,
> read-only by default, and journaled, and what separate ruling a
> first post-as-Elaria would need; (4) "interestingness" — how she
> may proactively surface something (initiative budget, stated
> interests, sources attached, never a feed of slop); (5) the
> terminal outcomes `PLATFORM_BLOCKED` / `NEED_LOGIN` /
> rate-limit as first-class journaled results. Fact-check every
> external claim (API availability without login, X's public read
> surface as of now) with sources; stress + bug-test your own
> design per the procedure (prompt injection via a news page is
> your headline case). Report only. PR + merge yourself. Never
> edit OWNERS.yaml; make NO network calls from code you write —
> this lane writes none.

## CHANNEL A-1 — Agent E: the always-alive layer (design)

> You are Agent E. In your Elaria checkout read
> `reports/OWNER-RULING-INTERNET-20261125.md` (the presence ruling)
> and `reports/DISPATCH-ALIVE.md`. The product: Elaria is alive
> when the laptop is off. Example: owner at school gets a WhatsApp
> DM from HER dedicated number — "Hey, remember meeting at 7" —
> owner replies with an instruction, later starts the laptop, and
> she says "okay, I will" and executes it under all normal gates.
> Deliverable: design report `reports/RPT-E-alive-layer-*.md`:
> (1) what the alive layer holds (clock/calendar/reminders from
> stated commitments, her own messaging identity, an instruction
> queue) and its hard no-authority list (no acting, no sending as
> the owner, no irreversible anything, no voice); (2) where it can
> live (Pi / NAS / small VPS / the phone itself) with an honest
> comparison — cost $0 preferred, owner's hardware first; (3) the
> dedicated WhatsApp question, fact-checked with sources: official
> paths only (WhatsApp Business Platform, a second number on the
> owner's phone, or other) — no unofficial automation that risks
> the owner's accounts, ever (Fork 3 applies); (3b) the
> stranger-facing mode from the owner ruling: her number is given
> to strangers to chat and make plans, so design the identity
> tiers — owner-authenticated messages queue as instructions,
> stranger messages are conversation only and can never become
> commands (injection is the headline attack: a stranger talking
> her into emailing, deleting, disclosing, or committing the
> owner); disclose nothing about the owner beyond what the owner
> pre-approves (free/busy granularity is a question your report
> must answer); every negotiated plan lands as a non-binding
> proposal for owner approval — cite and extend the existing
> guest contract in `src/assistant/showoff.py` rather than
> inventing a second one; (4) the wake/sync
> protocol: queue format, ordering, expiry ("okay I will" means
> acknowledged-and-queued, never promised-done), how full Elaria
> drains it on laptop start, and how the two halves reconcile
> memory via the landed rclone backup (hashes confirmed, never
> silent divergence); (5) failure modes: alive layer down (she is
> simply asleep — never a false "I'm here"), VPS compromise (it
> holds reminders and a queue, never voiceprint/keys/authority),
> duplicate reminders. Stress/fact/bug-check your design per the
> procedure. Report only. PR + merge yourself. Never edit
> OWNERS.yaml.

---

## GATE VERDICT — A-1 alive layer (manager, 2026-11-25, PR #116)

**PASS.** Enemy-read notes: the no-authority list is tied to
enforcements, not promises; stranger/owner tiers are fixed by
transport identity and different envelope kinds, so injection has
no path to command even if every filter fails; compromise yields
two revocable tokens and non-secret reminders, nothing else.
Manager adopts the agent's safe defaults as binding for any
build: responder **S-0** on WhatsApp (templates only, no LLM
concierge there) *or* S-1 on Telegram if the owner picks
Telegram; free/busy **L1 (day-level)** for strangers; reminder
fast-lane **OFF**; content-free secret reminders **OFF**; laptop
knock = short "already sent" form.
**Two owner decisions remain**: (1) platform — WhatsApp
(KES-cents, Meta grey-zone G1) vs Telegram bot ($0,
policy-clean); (2) host — Pi Zero 2 W (~$25–35 one-time) vs
existing NAS/old phone ($0, fragile) vs Oracle free VM ($0,
third-party custody).
