# Producer seams — the seven console-critical seams, estimated (design only, no code)

Date: 2026-11-05 · Branch: `arena/c2a7085d-elaria` · Code read at **`e7316b9`** · Status: **design + estimates only. No code was written for any of the seven.**
Scope authority: the 2026-11-04 order's TASK 3 — *estimate and design only, until an owner grant quotes the seven-seam list as its own scope.*
Evidence class: **[TESTED-ONLY]** for everything that already exists (it is pinned in the suite); every "estimate" below is an unhurried forecast, not a measurement.

Provenance of the list, stated plainly: the canonical table lives in the console lane's Task A report `342fdd9` (`docs/phase-reports/console-2026-11-04-task-a-attribution.md`). At the time of writing, that commit was in no local ref — `git cat-file -t 342fdd9` → *not a valid object* — so the seven seams below were transcribed from **the order's own listing**.

**Re-derived since (`§9`).** `342fdd9` sits on `origin/arena/b65d5161-elaria` (the console lane's branch); a full `git fetch origin 'refs/heads/*:refs/remotes/origin/*'` brought it into the object store, and the table was read from there — read-only, cross-lane input, nothing built for that lane. The transcription maps **1:1 onto the console's seven rows in the same order**, no seam missing and none added, with five wording-level deltas that change two estimates and one dependency. §9 records them. Where this document and the console table appear to disagree, the console table is the specification and this document is the thing that gets corrected.

Two rules hold throughout, and they are the reason these are cheap:

- **Additive producer fields only.** No existing key is removed or re-purposed; no consumer is required to change; an old console that ignores the new keys sees exactly today's payload (consumers read specific keys from these dicts — `console.py:51–67`, `console.py:90–110`).
- **No new RPC.** A query-shaped RPC ("tell me what you just did") proves nothing about what actually happened and can expose unrelated rows. The facts are produced where the action happens and travel on the reply, the event, or the persona/journal row that already exists.

Line cites are `file:line @ e7316b9` (SHA:line house rule).

---

## 0. The estimates, one line each

| # | seam | estimate |
|---|---|---|
| 1 | request-bound canonical intent/outcome correlation | **~35 lines, ~8 pins** — one `ContextVar` set in `handle()`, `corr_id` + `intent` + `outcome` on the 3 turn payloads and the knock payload |
| 2 | structured operation/journal refs, explicit no-op/refused states | **~45 lines, ~10 pins** — a `refs` builder plus one optional `refused` object in the error reply (`ipc.py:213`); the only wire-shaped addition of the seven |
| 3 | causal message id from this turn's append | **~12 lines, ~5 pins** — `sessions.append` already returns `message_id` (`console.py:43–48`); capture 3 discarded return values |
| 4 | indexed-hit source/ref/timestamp + local hit/miss/fallback | **~30 lines, ~7 pins** — one dataclass field (`memory.py:31–35`), five `bump` sites, one reply field |
| 5 | remember result: fact id, kind, state, retention | **~15 lines, ~4 pins** — `remember` returns id only (`memory.py:49–55`); return the row dict and stop asserting "stored" in prose |
| 6 | forget: exact count, affected ids, correlation | **~25 lines, ~5 pins** — read ids under the same lock before the `UPDATE` (`store.py:845–865`) |
| 7 | organise: roots, plan ids, write kinds, per-plan receipts | **~45 lines, ~8 pins** — roots filter is already local (`daemon.py:2661–2666`); receipts are the async half and are the expensive part |
| | **total** | **~207 lines, ~47 pins**, across `daemon.py`, `memory.py`, `store.py`, `ipc.py`; **no schema change, no new RPC, no `cli.py` change** |

Order I would take them in if granted as one scope: **3, 5, 6, 4** (each self-contained, each testable without touching a reply shape that other pins assert), then **1**, then **2**, then **7**. Each lands as its own commit with its own pins; a seam that turns out to need the others is the seam that gets stopped and reported, not forced.

---

## 1. Request-bound canonical intent/outcome correlation — ~35 lines, ~8 pins

**What the console needs:** for one authenticated request, the canonical intent that was decided and the outcome that followed, bound to *that* request — not reconstructed from a later history sample.

**Producer today.** The authenticated dispatch point is `handle()` at `daemon.py:858`: it derives the peer principal and sets two context variables (`daemon.py:865–866`), dispatches through the handler table (`daemon.py:884–888`), and resets both in `finally` (`daemon.py:889–893`). That is the only place in the process that knows "this is one request from a kernel-authenticated peer". Nothing downstream carries an identity for it. `_ask` decides `speaker`, `decision`, and (via `_run_intent`, `daemon.py:3757+`) the routed `intent`, but the reply payload (`daemon.py:3738–3756`) carries only `via` — a coarse string like `local-intent | local-memory | gemini`. Intent and outcome are therefore *inferable* by the console from a message list, which is exactly the post-turn sampling the order rejects.

**Additive fields proposed:**
- `corr_id` — 16 hex chars, minted in `handle()` into a third `ContextVar` (`self._ipc_corr`), reset in the same `finally`. Never accepted from params; a JSON claim is not an identity (the same doctrine as the channel derivation at `daemon.py:3524–3527`).
- `intent: {"kind": str, "argument": str|null}` — `kind` verbatim from `route()` (`intents.py:62`), `argument` as routed (not the raw text).
- `outcome: str` — one of `answered | declined | escalated | queued | refused`; `queued` is the offline durable-queue rung that already sets `queued_job_id`, `refused` is the withheld/leak path.
- On the guest payloads (`daemon.py:3177`, and the show-off payload near `daemon.py:3254`): same three keys, with `corr_id` present and `intent` null — a guest turn is a turn, it just has no local intent.

**Two honesty constraints.** (a) Background producers — connectivity ticks, the plan task, warm-cache — have **no** `corr_id`. They get `null`, never a fabricated one. (b) `outcome` must be derived from what actually happened on the ladder, not from which branch was hoped for; the rungs already set `via`, and `via` is the honest source.

**Why ~35.** ContextVar declaration + set/reset (6), helper `_corr()` (3), four payload sites (3×4=12), `_run_intent` returning the routed kind instead of only `(reply, via)` (8), `_ask` outcome derivation (6).

## 2. Structured operation/journal references, with explicit no-operation and refused states — ~45 lines, ~10 pins

**What the console needs:** when a turn touched or refused work, structured references to what — operation ids, plan ids, journal correlation — and an explicit `none` when nothing was touched, so "nothing happened" is stated rather than inferred from an empty string.

**Producer today.** A refusal is an exception and the wire shape for one is a **bare string**: `ipc.py:213` → `{"id", "ok": false, "error": "TypeError: msg"}`. There is no structured slot in a refusal at all. Success payloads are equally unstructured: `_undo` returns `{undone, problems}` (`daemon.py:2782+`), `_plan_apply` returns `asdict(ApplyReport)` which already has `op_ids` (`executor.py:57–65`), and `_memory_forget` returns `{forgotten: int}` (`daemon.py:2970–2971`). Meanwhile the journal line is a fixed six-column format (`journal_log.py:80–88`) — folding structure into `detail` would mean the console parsing prose, which is the defect this seam exists to remove.

**Additive fields proposed:**
- On success payloads: `refs: {"operations": [int], "plans": [int], "journal": [str], "none": bool}`. `none: true` is asserted only where the handler genuinely touched nothing (e.g. a refused undo, a shadow-mode plan build that wrote no operation rows).
- On refusals: an optional `refused` object in the error reply — `{"kind": str, "detail": {...}}` — added in the `except` at `ipc.py:212–214`. `error` keeps its exact current string, so every existing caller and pin is untouched.

**This is the only wire-shaped change of the seven** and it is additive: a new optional key in a payload shape that already tolerates extra keys. It is also the seam most worth a second opinion, because "optional key inside the error branch" is the kind of thing that either ages well or becomes the place two producers disagree about shape.

## 3. Causal message id from this turn's append — ~12 lines, ~5 pins

**What the console needs:** the id of the row this turn wrote, taken from the write itself.

**Producer today.** It already exists and is being thrown away four times. `SessionService.append` returns `{"conversation_id", "message_id", "channel"}` (`console.py:43–48`) and every caller drops it: the user row at `daemon.py:3562`, the assistant row at `daemon.py:3724`, the knock's first line at `daemon.py:1281`, and the guest turn's `conversation_id: None` broadcast at `daemon.py:3173–3176`. The console then samples `sessions.history()` (`daemon.py:1184–1185`, `console.py:51–67`) to find out what it just received — a post-turn sample that races concurrent turns.

**Additive fields proposed:** `message_id: int` and `conversation_id: int` on the turn payloads, and `message_id` in the `conversation.message` broadcasts (`daemon.py:881` lists the event; the payloads are at `daemon.py:3174`, `3262`, `3729`, `1289`). Highest value per line of the seven: 12 lines, no new state, no new file, and it retires a class of "which bubble is mine" bugs by construction.

## 4. Structured indexed-hit source/ref/timestamp, with local hit/miss/fallback outcome — ~30 lines, ~7 pins

**What the console needs:** for a turn answered from local retrieval, the hits that were actually used — source, ref, timestamp — and whether the local index hit, missed, or fell back to the model.

**Producer today.** `RecallHit` is `source, ref, text, score` (`memory.py:31–35`) — **no timestamp**, though every underlying row has one (`facts.ts`, documents' chunk rows, transcripts' rows). Hits are assembled at five `bump` sites (`memory.py:84`, `96`, `105`, `121`, plus the filename arm just above `110`). `_memory_recall` (`daemon.py:2973–2976`) forwards source/ref/text/score. `_ask` computes `hits`/`kept` at `daemon.py:3590–3597` and then keeps only the joined string `context`; the reply says `via` but nothing about *how many* hits backed it, whether the local rung answered, or whether the model had to run. `docs.search` (`daemon.py:2730–2735`) reports its engine (`fts5` vs `like-fallback`) but no per-hit time.

**Additive fields proposed:** a fifth dataclass field `ts: str | null` wired from each source row at the five bump sites; `ts` in `_memory_recall`'s hit dicts; and on the turn payload `retrieval: {"hits": int, "kept": int, "outcome": "hit|miss|none", "engine": str|null, "fallback": "gemini"|"queue"|null}`. `miss` is a real answer: a turn that ran local retrieval and found nothing must say so, otherwise "no hits" and "no retrieval attempted" are indistinguishable to the console, and the second is a bug the first hides.

## 5. Remember result: fact id, kind, resulting state, retention semantics — ~15 lines, ~4 pins

**What the console needs:** what was actually stored, from the service's own result.

**Producer today — and this is the sharpest finding of the seven.** `_memory_remember` (`daemon.py:2962–2965`) returns `{"fact_id": ..., "stored": "stated — inspect anytime: assist memory"}` — a **hardcoded sentence**, not a statement about the row. Worse, the typed-intent path at `daemon.py:3786–3788` does not even keep the id:

```python
if intent.kind == "remember" and intent.argument:
    await self._memory_remember({"text": intent.argument})
    return (f"Remembered (stated fact): {intent.argument}", "local-intent")
```

So the turn claims "Remembered" and echoes the text back, regardless of what the store did, and the fact id is discarded. `MemoryService.remember` returns an int (`memory.py:49–55`), `add_fact` inserts with `active` defaulting active, `source` defaulting `stated`, `confidence` 1.0 (`store.py:823–831`).

**Additive fields proposed:** `remember: {"fact_id": int, "kind": str, "source": str, "active": true, "retention": "until_forgotten", "evidence": str|null}` on the payload, and the intent branch stops composing its own claim — it reports the handler's result. Retention is stated as a *semantics token*, not a promise: facts persist until `forget` deactivates them; nothing else expires them today.

## 6. Forget: exact count, affected ids, and operation correlation — ~25 lines, ~5 pins

**What the console needs:** which facts were deactivated, not just how many.

**Producer today.** `forget_facts` (`store.py:845–865`) runs one `UPDATE facts SET active = 0 WHERE active = 1 AND …` and returns `cur.rowcount`. After the call, the affected ids are unknowable — there is no record of *which* facts a forget took, so no receipt, no partial-undo, and no way for the console to say "these three, by name". Callers: `daemon.py:2971`, `daemon.py:3790` (whose prose is `Forgotten ({count} fact(s) deactivated)`), `cli.py:765/769`, and two test call sites that assert `== 1`.

**Additive fields proposed:** `SELECT id FROM facts WHERE …` under the same `self._lock` before the `UPDATE` (same predicate, same transaction — no `RETURNING`, so no SQLite-version floor), a companion `forget_facts_detailed(topic) -> (count, ids)` with `forget_facts` reduced to `return forget_facts_detailed(...)[0]`, and `{"forgotten": n, "fact_ids": [int], "corr_id": str}` on the handler payload (plus `refs.operations: []` and `refs.none: true` from §2 when the count is zero). **Exact count means the rowcount the database reports**, never the number of rows the caller *meant* to hit — `forget %` matches nothing today precisely because `%` is escaped, and that stays true.

## 7. Organise: resolved root set, started plan ids, write kinds, separate completed/failed receipts — ~45 lines, ~8 pins

**What the console needs:** which roots were actually resolved, which plans were started, what kinds of writes happened, and receipts that separate what completed from what failed.

**Producer today.** `_plan_build` (`daemon.py:2658–2717`) resolves `roots` from config with an optional `root` filter (`2661–2666`), creates a plan row per root synchronously (`2664–2676`), and appends `{"plan_id", "root", "status": "building", "tiers": …}` to `started` (`2712–2715`) — so plan ids and roots are **already in the reply**; what is missing is (a) the roots that were configured but *not* resolved to a plan, and (b) any receipt, because the build runs as a background task whose only outcomes are broadcasts: `plan.proposed` / `plan.progress` (`organiser.py:69`, `100`, `111`), `plan.tiers_queued` (`daemon.py:2687–2693`), and `error` + a `finish_plan` for the failure path (`daemon.py:2701–2709`). The reply says "building" forever; the console's own `snapshot()` (`console.py:90–110`) ends up reading plan status out of the database to compensate. The write half, `_plan_apply` (`daemon.py:2746–2762`), returns `asdict(ApplyReport)` which already carries `applied`, `conflicts`, `refused`, `op_ids` (`executor.py:57–65`) — good — but no per-op *kinds*.

**Additive fields proposed:** `organise: {"roots_resolved": [str], "roots_skipped": [{"path", "why"}], "plans": [{"plan_id", "root", "mode", "receipt": null|{"status", "total", "placed", "abstained", "error"}}], "write_kinds": {"move": n, "rename": n, "copy": n, "mkdir": n, "trash": n}}`. Receipts are filled by the existing background task into a small dict keyed by plan id (the daemon already keeps `self._plan_tasks`, `daemon.py:2713–2715`), and read back on the next `plan.show`/`plan.list` reply — **no new RPC**, the same read the console already performs. `write_kinds` is derived from `op_ids` against the operations rows, so it reports what was written, not what the plan proposed.

**Why ~45 and why it goes last.** It is the only seam whose facts are produced *after* the reply. The cheap 30 lines are roots + plan ids + kinds; the last 15 are the receipt bookkeeping, and that is where a "completed" and a "failed" can be accidentally merged into one field — the exact thing the order says to keep separate. I would rather overrun here than collapse the two.

---

## What this document is not

- **Not a grant.** No code exists for any of the seven; the tree at `e7316b9` is unchanged by this document. Writing even seam 3 (12 lines) needs the owner grant that quotes the seven-seam list as its scope.
- **Not a console design.** How the console renders any of this is the console lane's; the daemon owns emitting, the console owns asking and showing.
- **Not a schema change.** Nothing here adds a column, a table, or a migration. The two facts that genuinely need persistence (forget ids, plan receipts) are answered from rows that already exist, or held in memory for the life of the reply.
- **Not free.** ~207 lines and ~47 pins is a week of careful work in a lane that has already overrun one estimate this cycle (the pilot: 165 lines against ~115 forecast). If the owner wants a smaller first bite, seams 3 + 5 + 6 are ~52 lines and retire the three claims that are *currently unverifiable* — the discarded message id, the hardcoded "stored", and the forget without a receipt.

## Open questions

1. **Which list is authoritative? — resolved.** The console's `342fdd9` table was read on 2026-11-05 (§9). It is authoritative; this document now matches it, with the deltas in §9 folded into the estimates below. A grant should quote the console's seven rows.
2. **Is an optional key in the error branch acceptable wire drift?** Seam 2 is the only one that touches a payload shape rather than adding a field to a dict the console already reads. If that is too much for one grant, seam 2 can be split: `refs` on success first, `refused` on errors later.
3. **Receipts in memory or in the row?** Seam 7's receipts live in daemon memory keyed by plan id, which means a daemon restart between build and read loses them (the plan row still has status/total/placed/abstained, so the loss is bounded). Persisting them would be a schema decision, and this document does not ask for one.
4. **`outcome` vocabulary.** `answered | declined | escalated | queued | refused` is my proposal. If the console has already drawn a status vocabulary, its words should win — one vocabulary, not two that need translating.

---

## 9. Re-derivation against the console table (`342fdd9`) — the delta, recorded

Obtained on 2026-11-05 from `342fdd9:docs/phase-reports/console-2026-11-04-task-a-attribution.md` (commit on `origin/arena/b65d5161-elaria`, brought in by a full-head fetch). Read-only; no file, branch or commit of that lane was touched. The console's table is headed *"Mainline seam requests — not implemented or invented"*, with columns *Missing evidence | Minimum producer seam requested | Current surface*.

### The mapping — 1:1, same order, nothing missing, nothing invented

| # | console row ("missing evidence") | console's "minimum producer seam requested" | this document's seam | verdict |
|---|---|---|---|---|
| 1 | Actual executed intent and request correlation | "Request-bound canonical intent/outcome, with correlation carried from authenticated dispatch through reply" | §1 | **identical** |
| 2 | Operation journal attribution | "Structured operation/journal references, explicit no-operation/refused state where applicable, **tied to the request**" | §2 | **+ "tied to the request"** |
| 3 | Causal message reference | "Message ID from this turn's append, not a post-turn history sample" | §3 | **identical** |
| 4 | Indexed hits | "Structured source/ref/index **timestamp or revision** and local hit/miss/fallback outcome" | §4 | **+ "or revision"** |
| 5 | Remember result | "Fact ID, kind, resulting state and **retention/restore** semantics from the actual service result" | §5 | **+ "restore"** |
| 6 | Forget result | "Structured exact count, affected IDs/**versions**/state and operation/**decision** correlation **for the later pilot**" | §6 | **+ versions, state, decision correlation, pilot binding** |
| 7 | Organise result | "Resolved root set, started plan IDs, write kinds and separate completed/failed **build** receipts" | §7 | **receipts are for the build, not the apply** |

**No eighth seam. No seam in this document that the console did not ask for.** The transcription was faithful in substance; five rows were narrower than the console's wording, and those narrowings are the delta below. Each is resolved *in this document*, not deferred to code.

### The five deltas, and what each costs

**D1 — seam 2 must be "tied to the request" (estimate: a dependency, and +8 lines if granted alone).** The console requires the references be bound to the request that produced them, not merely present in a reply. That binding is seam 1's `corr_id`. Consequence: **seam 2 depends on seam 1.** Granted together, the cost is unchanged (~45). Granted alone, seam 2 must mint and carry its own request binding — a second correlation concept in the process, which is the worse outcome — **+8 lines, ~53**. Recommendation: if seam 2 is ever granted, seam 1 is granted with it.

**D2 — seam 4 allows "index timestamp *or* revision" (estimate unchanged, ~34).** Checked against the schema rather than assumed: `documents` carries **`indexed_ts`** (`store.py:156`) and **`sha256`** (`store.py:151`), and `doc_chunks` (`store.py:161–166`) is a child of that row, so a chunk hit joins to both without a schema change. There is **no row revision and no version column anywhere in the store**, so "revision" can only honestly mean *content revision* — the document's `sha256` prefix — never a counter. Both halves of the console's "or" are therefore answerable today; the estimate moves ~30 → **~34** to thread `indexed_ts` and `sha256[:16]` through the vector arm's join and the keyword arm's `search_documents` rows.

**D3 — seam 5 owes "restore" semantics, not only retention (estimate ~15 → ~17, one extra pin).** `facts.active` (`store.py:204`) is set to 0 by forget; the row and its text stay. So the truthful declaration is: **deactivation is reversible at the row level and no API restores it today** — no duration guarantee, no restore verb, and `forget` is not erasure. That is a second declared token (`"restore": "row_preserved_no_api"`) plus a pin asserting the row still exists, inactive, after a forget. This is also the honest form of the console's own "deactivation-not-erasure" disclosure, and it must not become a promise that a restore path exists.

**D4 — seam 6 asks for versions, state and a pilot binding (estimate ~25 → ~30, one extra pin).** Three separate answers:
- *versions*: **there are none.** `facts` is `id, ts, kind, text, source, confidence, evidence, active` (`store.py:196–205`) — no version, exactly as with `operations` (owner answer 3 deferred a version column as its own schema decision). The receipt therefore **declares the absence** rather than inventing a counter.
- *state*: answerable — `{id, state: "inactive", ts}` per affected fact, since the row survives with `active = 0`.
- *operation/decision correlation "for the later pilot"*: this is the one place the console's wording points at something that **does not exist yet**. A forget touches `facts`, not `operations`, so there is no operation row to bind to; the request-level `corr_id` is the only correlation available. If the later forget pilot needs a decision-level receipt identity, that identity is a **new object** — either a receipts table (schema decision) or a decided convention on `corr_id` + `ts`. Flagged as an open question; **+5 lines** covers `state` and the absence declaration, not a receipt table.

**D5 — seam 7's receipts are *build* receipts (estimate unchanged, ~45; field labels corrected).** The console asks for "separate completed/failed **build** receipts". My §7 drafted `write_kinds` from the *apply* path (`op_ids` against the operations rows) — that is an apply receipt and must be labelled as one. Corrected shape: `organise.build: {plan_id, status, total, placed, abstained, error}` per plan, concurrently with `organise.apply: {applied, conflicts, refused, op_ids, write_kinds}`. The separation the order demanded ("separate completed/failed") is between **completed and failed builds**; keeping build and apply receipts in separate objects is the cleaner reading of both, and is what the field names now say.

### Revised totals

| # | seam | was | now | why |
|---|---|---|---|---|
| 1 | correlation | ~35 / 8 | **~35 / 8** | unchanged |
| 2 | structured refs | ~45 / 10 | **~45 / 10** with 1 · **~53 / 12** alone | D1 |
| 3 | message id | ~12 / 5 | **~12 / 5** | unchanged |
| 4 | indexed hits | ~30 / 7 | **~34 / 7** | D2 |
| 5 | remember | ~15 / 4 | **~17 / 5** | D3 |
| 6 | forget | ~25 / 5 | **~30 / 6** | D4 |
| 7 | organise | ~45 / 8 | **~45 / 8** | labels only, D5 |
| | **total** | ~207 / 47 | **~218 / 49** | seams granted together, 1 before 2 |

The three-seam first bite is unaffected in size and one pin heavier: **3 + 5 + 6 is ~59 lines and ~16 pins** (was ~52 / ~14), still the cheapest path to retiring the three currently-unverifiable claims — the discarded message id, the hardcoded "stored", the unknowable forget.

### Two corroborations worth recording

- The console independently found the **same seam-5 defect** from the consumer side: *"`a6cc150:src/assistant/daemon.py:3582` — local intent formatting discards remember's service ID and exposes only prose for others."* That is the producer-side finding in §5, reached without either lane reading the other's work. Two lanes converging on it from opposite ends is the strongest evidence in either report that it is real.
- The console's report cites `a6cc150` line numbers (`daemon.py:3565`, `3582`); this document cites `e7316b9`. Same file, sixty-odd commits later, so the numbers differ — **no contradiction, and no renumbering of their cites**: SHA:line means each cite is true at its own SHA.
- Unprompted convergence on the rule that makes all seven cheap: the console added *no* extra memory/plan/docs RPC to reconstruct these fields, on exactly the ground this document opens with — such queries "would not prove attribution and could expose unrelated data."

### What this section changes about the standing instruction

Nothing about the holds. `342fdd9` was read, not merged, not checked out, and no file from that lane exists in this tree; the seven seams remain unbuilt. The delta is recorded where the estimate lives so that whichever word arrives — *seams bite*, *seams yes*, *seams no* — the numbers being granted are the re-derived ones, not the transcription's.

One new open question, from D4: **if the forget pilot needs a decision-level receipt identity, is that a receipts table (schema decision) or a convention over `corr_id` + `ts`?** I recommend the convention first — it needs no migration and answers "which forget was this" for any single request — and a table only if a later lane demonstrates a case the convention cannot express.
