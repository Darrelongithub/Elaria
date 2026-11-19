# Producer seams 3, 5, 6 — the "seams bite" grant

Date: 2026-11-05 · Branch: `arena/c2a7085d-elaria` · Grant: "GO TO COMPLETION" on the seams-bite scope line · Commit: **`7b374d1`**
Design and estimates: `docs/design/2026-11-05-producer-seam-estimates.md` §9, re-derived against the console's table (`342fdd9`). That mapping is authoritative and nothing here re-derives it.
Evidence class: **[TESTED-ONLY]** — real store, real socket daemon, no model calls, no hardware, no key.

Baseline before this change: **2,054 passed, 6 skipped** at `9ea87ea`. After: **2,072 passed, 6 skipped** at `7b374d1` (2,054 + 18 new). `ruff check .` clean. Base runtime unchanged; suite run on the full recorded dependency set via `uv sync` + `uv run --no-sync` (local runner only — no hosted CI claim).

Diff: `src/assistant/daemon.py` **+164/−37**, `src/assistant/store.py` **+30/−8**, `tests/test_producer_seams.py` **new, 355 lines**. `cli.py` untouched, verified by the commit's file list.

> **Estimate overrun, stated plainly.** §9 put the three-seam bite at *~59 lines / ~16 pins*. Actual: **194 insertions / 37 deletions, 18 pins**. The overrun is 3× on lines and has one cause: "the receipt must be present on the wire" is true of *typed* turns too, and a typed turn's only wire is `_ask`'s reply — which reaches the console through `_run_intent`. That method returned a 2-tuple at 15 return sites, so a receipt channel had to be threaded through all of them plus the payload. The estimate priced the handlers and not the channel. I am reporting this rather than shrinking the seam to fit a number.

---

## DONE — against the completion criteria

| criterion | result |
|---|---|
| suite and ruff green on the full recorded dependency set | **2,072 passed / 6 skipped** at `7b374d1`, `ruff check .` → *All checks passed* |
| every built seam's receipt present on the wire | seams 3, 5, 6 each carry structured fields on the RPC reply and on the typed-intent reply (`daemon.py:3834–3839`, `3890–3905`) |
| consumed by no caller that invents | every pre-existing key keeps its type (`forgotten` int, `fact_id` int, `stored` str); `cli.py` reads `forgotten` and prints it, unchanged and unmodified |
| a clause-by-clause pin table in the report | §Pins below, and in the test file's docstring |
| additive only, no new RPC, no schema change, no `cli.py` change | three files in the commit; no new handler; `sqlite_master` has no new table (pinned) |

### Seam 3 — the causal message id (`daemon.py:3650`, `3814`, `3820`, `3834–3835`, `1279–1293`, `3267`)

`SessionService.append` already returned `{"conversation_id", "message_id", …}` (`console.py:43–48`) and every caller threw it away. Now the user row (`3650`) and the assistant row (`3814`) are captured, and the turn payload carries `message_id` and `user_message_id` taken from those writes, with the `conversation.message` broadcast carrying the id (`3820`). Two declarations of absence replace what would otherwise be invented ids: a guest turn writes **no** row (BH-J1) so it declares `message_id: null` (`3267`); a knock whose first line was appended by the initiative path declares `message_id_absent` rather than sampling history after the fact (`1288–1293`).

### Seam 5 — the claim is the row (`daemon.py:2974`, `2985–3014`, `3890`)

The old path was the overclaiming disease in code: `_memory_remember` returned a hardcoded `"stored"` sentence beside an id nobody read, and the typed-intent branch discarded the id and echoed the user's text back as if echoing were storing. Now the handler reads the row back **active** via `_read_fact` (`2974`, a scan of `list_facts` — the store's only fact reader, and the corpus is small by design per §16), and raises *"…refusing to claim it was stored"* if the id does not read back. The payload is the row: `fact_id, kind, source, confidence, active, retention, restore, stored`. Retention and restore are **declarations, not queries**: `until_forgotten`, and `row_preserved_no_api` — the row survives deactivation and no API restores it, so the wire must not promise one. The typed-intent reply names the fact (`3890–3894`) and no longer echoes the remembered text.

### Seam 6 — forget names exactly what it deactivated (`store.py:845–874`, `daemon.py:3016–3057`, `3896–3905`)

`forget_facts` returned a rowcount, so the affected ids were unknowable the moment it returned. `forget_facts_detailed` (`store.py:850`) now reads the ids under the **same lock and the same predicate** as the `UPDATE`, in one transaction — `SELECT` rather than `RETURNING`, so no SQLite version floor — and `forget_facts` is a one-line wrapper keeping its `int` contract for the four existing callers. The receipt carries `forgotten` (the database's rowcount), `fact_ids`, and a per-fact `{id, kind, ts, state}` whose state is **read back** after the update: `inactive`, or `still-active` if the write did not take, or `unknown` if the row vanished — an anomaly made visible, never smoothed. Per **D4** (ruled convention-first) the decision identity is `corr_id` + `corr_ts`, and the payload declares what the schema cannot give: `versions: "absent — facts carry no version column"` and `durable_receipt: "absent — no receipts table; corr_id + corr_ts is the decision identity"`. A pin asserts the declaration is true of the schema, not just of the string.

### Pins — one per acceptance clause

All in `tests/test_producer_seams.py` [TESTED-ONLY].

| clause | pins |
|---|---|
| 1 the id is this turn's append, and a second turn gets its own | `test_turn_message_id_is_this_turns_append`, `test_second_turn_gets_its_own_message_id` |
| 2 a turn that writes no row declares a null, never a sample | `test_guest_turn_declares_no_message_id` |
| 3 remember's claim is the store's verified row | `test_remember_receipt_is_the_row`, `test_remember_does_not_claim_when_the_store_cannot_read_it_back`, `test_remember_does_not_claim_an_inactive_row` |
| 4 retention and restore declared; no API restores | `test_remember_declares_retention_and_restore` |
| 5 forget's ids are knowable, state read back | `test_forget_names_exactly_the_deactivated_ids`, `test_forget_by_id_deactivates_only_that_row` |
| 6 the count is the database's and agrees with the ids | `test_forget_count_matches_ids_and_zero_match_declares_nothing`, `test_forget_percent_stays_literal` |
| 7 declared absences; D4's corr_id + corr_ts | `test_forget_declares_absent_versions_and_no_receipts_table`, `test_forget_corr_id_and_ts_bind_the_decision` |
| 8 typed-intent paths name ids or say nothing matched | `test_remember_intent_names_the_fact_and_carries_its_receipt`, `test_forget_intent_names_ids_or_says_nothing_matched`, `test_other_intents_carry_no_receipt` |
| 9 additive only, and no new RPC to reconstruct any of it | `test_pre_existing_keys_keep_their_types`, `test_no_new_rpc_was_added_to_reconstruct_these_fields` |

**Containment statement (unchanged by this grant).** These seams are producer fields on the daemon route. `cli.py` is untouched: `assist undo --since …` with the daemon down still calls `Executor.undo` in the CLI process, and `assist forget` / `assist memory` still read only the keys they always read. Containment remains **console/daemon-route, not global** — the pilot's statement stands exactly as written at `5ee6853`.

## DEFECTS FOUND

1. **The estimate priced the handlers and not the channel.** `_run_intent`'s 2-tuple is the reason typed turns had no way to carry a receipt; threading a third element through 15 returns is most of the overrun. Any future "receipt on the wire" estimate for an intent-served turn should start at +40%, not at the handler's line count.
2. **Two `_run_intent` return sites resisted a text-level rewrite** — multi-line returns where the tuple's second element begins on its own line — and the result was a live `ValueError: not enough values to unpack (expected 3, got 2)` on `console.say status`. **The socket pin caught it, not review.** Recorded because mechanical edits of tuple-shaped returns are unsafe here: the compiler does not check this, only the pin does.
3. **`list_facts` is the store's only fact reader.** Seam 5 verifies by scanning it. Correct for a corpus this size, but it is a load-bearing assumption: if facts ever grow into the thousands, verification needs a `get_fact(id)` index read, and that is a store change nobody has granted.
4. **A forget receipt is not durable, by ruling.** `corr_id` + `corr_ts` live only on the reply; a console that drops the reply cannot recover them, and the facts table records nothing about who deactivated a row. That is D4's accepted trade, restated here so it is not mistaken for a store of record.
5. **`memory.py` was left alone** although §5's estimate mentioned it. `MemoryService.remember` returning the id *is* the service's result; stronger verification happens against the store. Changing the service's return type would have touched callers and tests for no additional truth, so the change stopped at the daemon.
6. **A knock's first line can be appended by the initiative path** (`daemon.py:1279–1293`), where its id is not captured; sampling history for it would be exactly the non-causal sample this seam existed to kill. Declared absent instead. A future change could return the id from `initiative.py:443` — that file is outside this grant.

Nothing else was touched: no `cli.py`, no `memory.py`, no `ipc.py`, no schema, no new handler. Seams 1, 2, 4 and 7 remain design-only.

## NEXT GATE

The remaining four seams stay design-only until a second word. Noted for whoever grants it: **seam 2 depends on seam 1** (D1 in §9) — the console requires those references be *tied to the request*, and that binding is seam 1's `corr_id`; granting 2 alone buys a second correlation concept in the process. Seam 2 is also the only one that touches a payload *shape* (an optional `refused` object at `ipc.py:213`), so it deserves to be quoted as its own scope.

## OPEN QUESTIONS

1. **Does the console persist `corr_id`?** The forget receipt is durable only in the console's hands. If the review card does not keep it, a decision-level identity exists for the length of one reply. This is a console-lane decision, not a producer one.
2. **Should the store refuse to forget silently at 0?** Today a no-match forget is reported as `forgotten: 0, fact_ids: []` — truthful, and the reply says *"Nothing matched"*. Whether a miss should instead raise (a typed-command refusal) is a policy question, not a producer field, and I did not take it.
3. **`state: "still-active"` has no caller.** It is the anomaly branch of the read-back and no test can force it without breaking the lock discipline. It is pinned only by construction; if a future refactor removes the single-transaction guarantee, nothing will notice except real use.
4. **The `outcome` vocabulary** from §9's last open question is still unclaimed, and it is seam 1's to settle.
