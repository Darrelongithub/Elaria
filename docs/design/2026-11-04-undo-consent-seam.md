# Consent seam — single-op undo review pilot (design note, 2026-11-04)

Status: **design only, no code.** Task 2 of the owner's 2026-11-04 hands
ruling ("make her hands work"), adopting the consent matrix `c327df7` §5
shape. The fail-closed guard that precedes this pilot landed at
`9ef895a` (8 added lines, `daemon.py:_undo`).

Line cites are `file:line @ 9ef895a` (SHA:line house rule).

## 1. Where the focused owner Yes/No consumer attaches

**The seam is a two-call IPC pair that replaces the guard's refusal slot
— not a dialog bolted onto the executor.**

| call | who | effect |
| --- | --- | --- |
| `undo.prepare` | console (or CLI) | resolves the scope, pre-verifies it, returns an **immutable snapshot** + a single-use token. Writes nothing. |
| `undo.apply {token, decision: yes|no}`  | console's Yes/No surface | `no` discards the token and journals the refusal; `yes` re-verifies the snapshot and only then calls `executor.undo(op_id=…)` for the single op. |

Placement in the tree:

- Both handlers register in the daemon handler table beside `"undo": self._undo`
  (`daemon.py:787`).
- Both begin with `self._require_ipc_owner()` — the established consent
  idiom (`daemon.py:843` `_require_ipc_owner`; `daemon.py:3030`, `_showoff_exit`: "params are not authority").
  A Yes carried in JSON is not an approval; the kernel-authenticated
  socket peer plus the method is.
- The guard at `daemon.py:2775` keeps refusing **every** scoped undo,
  including a `yes` that arrives without a token or with a stale one.
  The pilot does not weaken the guard; it adds one blessed path
  (`undo.apply`) that is narrower than what the guard blocks.
- The typed intent (`daemon.py:3630`) stays refused during the pilot:
  voice/typed "undo since X" never reaches the pilot. Only the
  console's explicit review surface can approve. That is the matrix's
  intent — the pilot exists to test one reviewed operation, not to
  restore the intent path.

Why the console lane owns the surface: the console already renders
daemon state and is where the owner's typed turns live. The seam is
transport, not UI; the daemon exposes it and the console decides how to
ask.

## 2. The immutable scope snapshot

Prepared by `undo.prepare`, carried back verbatim, hashed, and re-checked
at apply. **Design rule: a Yes approves a snapshot, never a query.**

Contents (one row per op, ordered as the executor will walk them —
`executor.py:462` iterates `reversed(operations)`):

```
op_id            int      store.py:98   operations.id
plan_id          int?     store.py:98
ts               iso      store.py:99
op               str      store.py:100  move | rename | copy | mkdir | trash
src, dst         path     store.py:101
sha256_before    hex?     store.py:102
sha256_after     hex?     store.py:102
status           str      store.py:103  intent | copied | committed | rolled_back
```

plus, computed at snapshot time:

- `snapshot_sha256` — SHA-256 over the canonical JSON of the rows
  (`sort_keys=True`, no whitespace). The token binds to *this* value, so
  any drift between prepare and apply is detectable by construction.
- `root` — the plan's root (`store.py:171`), the containment boundary
  the operation is judged against.
- `prepared_at` / `expires_at` — deny-by-default expiry (suggest 120 s;
  the owner must see the summary and decide, not have it sit open).

**Pre-verification at prepare (so that Yes means something).** For each
row, the same three facts the executor re-checks per op
(`executor.py:464–479`): source exists; its current hash equals
`sha256_after or sha256_before`; the original location is either absent
or holds identical content. A snapshot that fails any of these is **not
offered** — the owner is told what changed and nothing is asked. This
keeps the pilot honest: the owner never approves a move that cannot
execute.

**Single-op shape (pilot).** Exactly one row: the newest undoable op
(`store.py:1059` `undoable_operations` order, newest last). `since` and
`plan_id` spanning undo remain refused by the guard throughout the
pilot — the pilot's job is to prove one reviewed operation end to end.

## 3. Fresh target identity (the TOCTOU window)

Between Yes and execution, the filesystem can change. The pilot closes
this by **re-verifying at apply, not by trusting the snapshot**:

1. token → snapshot lookup; refuse if unknown, already used, or expired;
2. re-read the op row from the store; refuse if any field differs from
   the snapshot (this is the "version" check that exists — see §4);
3. re-stat and re-hash `src` and `dst`; refuse on any disagreement with
   the snapshot's hashes;
4. only then `executor.undo(op_id=…)`.

Refusal at any step is **total**: no partial undo, no "did what it
could". The message names the field or path that drifted. The executor's
own per-op guards (`executor.py:464–479`) remain in place as the second
line — the pilot never bypasses them, because it calls the same
`undo()` entry with a single `op_id`.

## 4. "Versions" — stated plainly: no such field exists

The matrix says the snapshot binds "op IDs, versions, hashes, fresh
target identity". **There is no `version` column in this schema** —
`store.py:96–105` gives operations `id, plan_id, ts, op, src, dst,
sha256_before, sha256_after, bytes, status, error`, and the plans table
(`store.py:168–178`) carries `status` but no version either. A grep for
`version` across `store.py` returns nothing in either table.

So the binding is **`(id, status, ts)` + the two hashes**, which is what
step 2 above compares. If the matrix wants a true monotonic version, that
is a schema addition and needs its own decision — it is not something to
smuggle into the pilot. Recommendation: run the pilot on
`(id, status, ts, hashes)` and revisit only if the pilot's journal shows
an ambiguity it cannot resolve.

## 5. Attribution — what the trail must carry

Every prepare and apply emits its own schema line (journal) and a
persona event (store), so an approval is auditable after the fact:

```
undo.prepare  verdict=prepared  detail=snapshot_sha256=<hex> ops=1 op_ids=[…] expires_in=120s
undo.apply    verdict=approved|refused  detail=snapshot_sha256=<hex> by=<console|cli> op_id=…
undo.apply    verdict=drifted   detail=field=<which> expected=… observed=…
```

`by` is derived from the registered handler and the kernel-authenticated
peer — **never** from a JSON claim (the I5 doctrine already applied at
`daemon.py:3030` and in `_ask`'s channel derivation, `daemon.py:3362`).
Per the matrix, the console lane owns surfacing this attribution in the
UI; the daemon owns emitting it.

## 6. The boundary — `cli.py:2404–2416`, stated explicitly

**This containment is the console/daemon route, not global enforcement.**

`cli.py:2404–2416` (`assist undo`) calls the daemon socket; on
`DaemonUnavailable` it imports `Executor` directly and calls
`Executor(config, store).undo(...)` **inside the CLI process, with no
daemon entry in the path.** Neither the guard at `daemon.py:2775` nor any
pilot seam above can intercept that. Consequences, plainly:

- With the daemon down, `assist undo --since …` still performs a scoped
  undo today. It is the owner's own shell on his own machine, so this is
  not a privilege escalation — but it *is* an uncontained path, and it
  must not be described as "scoped undo is impossible".
- Making it global means enforcing at a layer both routes cross: the
  `Executor.undo` entry itself (`executor.py:440`), or a policy the
  executor reads. That changes semantics for tests, the event path and
  the CLI fallback at once — which is exactly why the ruling says global
  enforcement needs its own ruling.
- Options for that later ruling, costed roughly:
  (a) executor-level consent requirement (one flag, but it would also
      block the pilot unless the pilot marks its own call);
  (b) CLI-level parity check in the `DaemonUnavailable` branch (small,
      but it only covers the CLI, not a script that imports Executor);
  (c) leave it documented and rely on the daemon being the only
      automated route (cheapest, weakest).
  Not decided here.

## 7. Open questions for the design chat / owner

1. **Expiry** — is 120 s right for the pilot, or should it match the
   knock's own timeout so there is one number to remember?
2. **`no` handling** — journal-only, or also a persona line so a refusal
   is visible in her own conversation history?
3. **Version** (§4) — accept `(id, status, ts, hashes)` or schedule a
   schema addition?
4. **CLI parity** (§6) — which of (a)/(b)/(c) for the global ruling, and
   in what order relative to the pilot.

## 8. Cost estimate (for the pilot's own order, not this note)

- Seam: `undo.prepare` + `undo.apply` handlers, token registry, snapshot
  hash, expiry, re-verification — **~90–130 lines** in `daemon.py`
  (protected: needs its own grant, and the pilot is the second granted
  change to that file, so it should be costed against the 8-line
  precedent as a larger, separately justified exception).
- Store: no schema change if §4 is accepted as-is.
- Tests: prepare/apply, expiry, replay, drift on each bound field,
  unauthenticated peer, and "no partial undo" — **~15–20 pins**,
  stub-only, no real filesystem races.
- Console lane: the review surface itself (out of my lane).
