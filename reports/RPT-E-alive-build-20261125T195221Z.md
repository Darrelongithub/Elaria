# RPT-E — Alive layer BUILD report (sandbox, fake Meta + fake transport)

**Agent E · BUILD-6 · 2026-11-25 · `arena/e779a2cd-elaria`**
Design: `reports/RPT-E-alive-layer-20261125T122137Z.md` (gate PASS),
dispatch: `reports/DISPATCH-ALIVE.md` (GATE VERDICT, S-0 binding, L1/L0,
fast-lane OFF, knock = already-sent form, host = serverless + WhatsApp
Cloud API settled by the owner update).
Evidence labels: `[TESTED]` = executed in this sandbox against fakes;
`[OBS]` = read in this checkout; `[UNOWNED]` = seam requested from another
cluster; `[OWNER-STEP]` = real-world act the owner must perform; nothing
here is a hardware or live-account result.

**One-paragraph answer.** The alive layer is built and tested as a
separate, self-contained package (`src/alive/`) plus the laptop's half
(`src/assistant/alive_sync.py`): a free-serverless-shaped webhook
receiver (verify → tier → signed envelope), an append-only queue of
immutable, mac'd, hash-named JSON envelopes, a verified commitment
mirror, write-ahead capped reminder firing, the S-0 deterministic
concierge for the stranger front door, and the laptop drain that replays
instructions through the existing `cloud_queue.enqueue_external` →
`awaiting_approval` → spoken-yes path. NOTHING here claims a live
deployment: every test runs against fake Meta payloads and a fake
transport inside this sandbox. Registration, tokens, the real Drive
folder and the first real reminder are the owner's laptop step (§6).

---

## 1. What was built (by directory)

### New package `src/alive/` — the alive host (separately deployed)

| module | job | notes |
|---|---|---|
| `envelope.py` | the signed wire format (both sides import it; the two halves cannot drift) | HMAC-SHA256 over canonical JSON; name-hash `<ts>_<seq>_<sha256[:16]>.json`; `from_hash = sha256(e164 + salt)` |
| `config.py` | TOML load; **single-recipient start-up refusal**; caps; prefixes | `fast_lane=true` is a start-up error in this build (manager binding) |
| `store.py` | SQLite state: wamid dedup (7-day), write-ahead `fired`, per-tier/per-day counters, month ceiling, never-list hits, concierge drafts, kv (seq, platform_blocked, clock_suspect, T1 cache), inbox durability row | WAL; mode 0600 |
| `transport.py` | the ONLY HTTP in the package; egress allowlist (`graph.facebook.com` only, hard gate before any socket); `send_service_reply` (in-window) and `send_utility_template` (business-initiated, **owner number only**); `PLATFORM_BLOCKED`-class errors are terminal; `FakeTransport` for tests | no LLM client exists anywhere in the package |
| `concierge.py` | S-0 deterministic stranger responder: greet → ≤3 verbatim turns → `proposal` envelope (`principal:"stranger"` fixed in code) + the fixed non-binding line; never-list → third-person refusal + hit counter (3 hits/24 h → muted); memory-probe deflection; L0/L1 day-level free/busy (L2 for T1 only; L3 does not exist) | pattern tables are read-only third-person adaptations of `showoff.py` with attribution — imported nothing from cluster C |
| `mirror.py` | verified mirror reader: newest verified snapshot wins; forged/stale → treated as ABSENT; `busy_days()` counts days only (intervals/topics never leave the function) | absent card = L0 |
| `reminders.py` | firing engine: write-ahead row → send → `sent`/`unknown`; crash leaves `unknown` and never re-sends; `late_grace` 30 min → `missed`; template cap enforced in code; stale mirror → firing stops + owner told once; clock-suspect → firing pauses | `PLATFORM_BLOCKED` → stops, journals, waits for the owner |
| `webhook.py` | `handle_request(...)` — serverless-shaped pure function; GET hub.challenge verify; POST: size cap → raw-bytes HMAC verify → per-message tier → per-tier counters → envelope → durable write (SQLite + fsync'd spool) → 200 → then ack | 503 on durable-write failure with **dedup rollback** (§4) |
| `sync.py` | `FixtureSyncBackend` (labelled fixture) + `RcloneSyncBackend` (minimal pinned surface, `host` and `laptop` roles; `deletefile` pinned for laptop pruning only) | no network in tests |
| `heartbeat.py` | the one mutable object in the sync folder, mac'd | `alive.json`, overwritten in place |
| `serve.py` | dev runner (WSGI); production is any free serverless route binding the same function | not the deployment |
| `provision.py` | `init` (keygen + skeleton) and `doctor` (config loads, single recipient, state-dir 0700, caps sane, **grep of the install tree for forbidden artifacts** — voiceprint/assistant.db/API keys) | B16-style, runnable in sandbox |
| `alive.toml.example`, `README.md` | config template; owner bring-up checklist; remediation card | |

### Laptop half — `src/assistant/alive_sync.py` (cluster E)

`export_commitments` (full snapshot every time; origin ∈
`COMMITMENT_ORIGINS` enforced from `initiative.py`; `disclosure.is_sensitive`
filter; knock linkage; reminders only from structured `remind_hints` — the
daemon stores no reminder time for commitments yet, so items export with no
`remind_at` and fire nothing until that field exists — a seam, not faked) ·
`export_public_card` (L0–L2; level 3 refused) · `export_t1_hashes` (salted
hashes only; raw numbers never enter the folder) · `ingest` (verify name
hash + mac + version + owner `from_hash` for instructions; quarantine;
expired → surfaced, never executed; instructions →
`cloud_queue.enqueue_external(action="alive_inbox", …)` →
`awaiting_approval`; **stranger turns have no code path to the queue**;
proposals returned labelled by kind, `principal` field ignored) ·
`read_reminder_log` (for the "already sent" knock) · `line_status`
(heartbeat age is the only liveness truth) · receipts after every drain.

### Tests — `tests/test_e_alive_layer.py` (31) + `tests/test_e_alive_sync.py` (20)

All `[TESTED]` in-sandbox against fixtures. Adjacent suites re-run clean:
initiative, phase8 offline voice, queue timeout duplicate, wp7 remote/storage
(232 passed total).

---

## 2. BUILD-6 requirements → where they landed

| requirement | landed at | evidence |
|---|---|---|
| free-serverless-shaped webhook receiver | `alive/webhook.py::handle_request` + `serve.py` (reference wiring) | tests B1/B1b/B2/B4/oversize |
| append-only queue | inbox prefix of immutable envelopes + `alive/store.py` durability table + spool fsync | dedup test, 503 test |
| commitment mirror | `alive/mirror.py` (host) + `alive_sync.export_commitments` (laptop) | export filter test, forged mirror test |
| WhatsApp Cloud API S-0 templates only | `transport.py` (`send_utility_template` owner-only; in-window service replies; no free-form outbound) + template cap in code | cap test (B14), egress test |
| stranger tiers T0/T1/T2 by transport-authenticated number | `config.tier_for` (T1 by salted hash from laptop export) + webhook routing | T1 L1 test, flood test (B19) |
| laptop drains via `enqueue_external` → `awaiting_approval` → spoken yes | `alive_sync.ingest` + end-to-end test through `approve()` and `drain()` | test_end_to_end_owner_instruction_to_approved_job |
| egress allowlist | `transport.assert_egress_allowed` (hard gate) + pinned rclone surface in `sync.py` | egress test |
| single-recipient config | `config.AliveConfig` / `load_config` refuse second recipient | config tests |
| template cap in code | `reminders.send_reminder` checks `max_templates_per_day` every call | B14 test |
| signed envelopes | `envelope.py` everywhere; host and laptop both verify | forgery/tamper tests (B7/B24) |
| no audio stack | nothing audio in `src/alive/`; `doctor` greps the install tree | doctor PASS output in §5 |
| fake Meta payloads + fake transport in sandbox | `tests/` throughout | — |
| real registration is owner's step | README bring-up checklist | [OWNER-STEP] |

## 3. Deviations and honest notes (read these)

1. **B3 is stale by amendment.** The pre-front-door bug list said
   "stranger → 200, zero envelopes, no outbound message". The §2.3b owner
   ruling (public front door, S-0 concierge) supersedes it; strangers DO
   get the deterministic reply and DO produce `stranger_turn`/`proposal`
   envelopes with zero authority. Noted in `webhook.py`'s docstring.
2. **The `ack` field is gone from the stored envelope.** The design's
   sketch envelope carried `ack:{sent…}`, but the envelope is immutable and
   written *before* the ack exists. Ack results are journaled instead;
   expiry travels in `expires_at`, which is what the laptop needs.
3. **Dedup rollback on durable-write failure + self-healing spool.** The
   design ordered "fsync → 503 if failed" but left ambiguous what a
   retried POST does. Naive dedup would drop the retry as a duplicate
   and lose the message (I1 violation). The write order is now spool
   (fsync) → SQLite inbox row, and `handle_request` calls
   `push_backlog()` on every POST (and `serve.py` can tick it): spool
   files that never reached the sync folder are pushed, verified and
   marked; a Drive outage is a deferred push, never data loss, never a
   5xx. On durable-write failure the `seen` insert is rolled back, so
   the Meta retry is re-processed rather than dropped. Tests:
   `test_b4_durable_write_failure_503_no_ack_and_retry_works`,
   `test_drive_outage_defers_push_and_backlog_heals`.
4. **`principal` in a proposal envelope is ignored on the laptop.** The
   laptop labels proposals by `kind` (defence in depth behind the mac).
   `test_proposal_principal_is_ignored_labelled_by_kind`.
5. **`PLATFORM_BLOCKED` also sticks from in-window replies**, not only
   templates — any Meta restriction stops the line until the owner acts
   (B13 posture).
6. **Reminder times don't exist in the store yet.** Commitments are
   `facts` rows with free text; no structured `remind_at` is captured
   anywhere in the codebase. The mirror carries `remind_at` when the
   caller supplies `remind_hints`; otherwise the item is read aloud but
   never fires. Wiring "remind me at 7" → structured time is a cluster C
   request; faking date extraction from free text would be a correctness
   hazard, so it was not done.
7. **S-1 is absent by design.** No LLM anywhere in `src/alive/`. The
   `non_binding_filter` belt exists for a future S-1, S-0 never emits
   confirm-words by construction.
8. **`alive/` is not in `OWNERS.yaml`** (design says the manager assigns
   it). Files created within the build's remit only; `OWNERS.yaml`,
   `config.toml.example`, `daemon.py`, `remote.py`, `initiative.py` and
   `showoff.py` were NOT edited. `alive_sync.py` and `tests/test_e_*`
   are cluster-E paths per the report's ownership map.

## 4. Eye-checks (all [TESTED] in sandbox; none are hardware/live claims)

Signature 403 + nothing stored · 200 on retry after 503 (rollback) ·
Drive outage → envelope durable in spool → backlog heals on the next POST ·
one envelope per wamid · owner instruction → queued + "nothing happens
until it's on" ack · injection-shaped body flagged not dropped · voice
note → `unsupported`, never downloaded · owner daily cap counts not
stores · stranger greeting → refusal → mute after 3 never-list hits ·
memory probe deflected (incl. "where does she live") · 3-turn plan →
`proposal` with `principal:"stranger"`, never an instruction · stranger
flood does not crowd out the owner · L1 card + T1 hash → day-level
answer, T2 stays L0/L1 · forged mirror → "mirror unavailable", zero
sends · stale mirror → firing stops, one honesty message, no nagging ·
late reminder → `missed`, never sent · crash between write-ahead and
send → `unknown`, never re-sent · template cap → `capped`, laptop told ·
clock suspect → firing pauses · PLATFORM_BLOCKED → terminal, sticky ·
heartbeat round-trip verifies (and a bad mac ⇒ "asleep") · forged/tampered
inbox envelopes quarantined (mac and name-hash) · expired instruction
surfaced, never executed · receipt written, re-ingest idempotent ·
end-to-end: phone instruction → `awaiting_approval` → laptop yes →
drain → approved, `executed:false` (Fork 2 holds) · doctor: clean tree,
caps sane, fast lane OFF.

## 5. Sandbox doctor output (this install tree)

```
ok   config loads (tz=Africa/Nairobi, inbox=inbox/)
ok   state_dir exists and is mode 0700
ok   no voiceprint/db/API-key artifacts under the alive package
ok   template cap in code: 10/day
ok   fast lane OFF (manager binding)
PASS doctor — clean to deploy (this is NOT a hardware claim)
```

## 6. What is NOT done / owner steps / seams handed off

- **Owner laptop step:** Meta Business portfolio + dedicated number +
  WABA + System User token (spend limit minimum), `reminder_v1` template
  registration, Elaria's Google account + `elaria-sync/` folder + rclone
  remotes (both pinned by `root_folder_id`), serverless route binding
  `handle_request` (HTTPS :443 valid CA), Meta webhook pointed at it,
  cron → `reminders.tick()` 60 s + heartbeat 15 min, host checklist +
  B16 grep on the real host, first week on the Meta test number.
- **Cluster U:** daemon startup hook (ingest on online transition,
  "line asleep since" line, knock "already sent" variant), `[alive]`
  config section in `config.toml.example`/`config.py`.
- **Cluster T:** `CommandPin` `copyto`/`cat`/`lsjson --hash` in
  `remote.py` so the laptop can retire `alive_sync`'s fallback pinned
  surface.
- **Cluster C:** structured `remind_at` on commitments (or an
  `accepted-proposal` sink wiring for ingested proposals); proposals are
  currently surfaced to the caller, never auto-accepted.
- **Cluster C (optional):** `REFUSALS_TEXT` third-person table upstream in
  `showoff.py`; this build carries its own copy.
- **Not built, by binding decision:** S-1 (no LLM), fast lane (refused in
  code), content-free secret reminders (default OFF; code path gated),
  L3 (does not exist), pruning of receipts (laptop helper lands with the
  U wiring; alive host never deletes), Telegram adapter (protocol is
  channel-agnostic; the WhatsApp adapter is the one built).
- **Not verified (impossible in sandbox):** Meta webhook delivery
  retries/window, real pricing, Kenyan egress path, rclone against real
  Drive, serverless cold-start behaviour, Tailscale/serverless ACL
  one-way rule. These are provisioning-day checks.

## 7. Ownership map after this build (no OWNERS.yaml edit made)

`src/alive/**` — unowned (manager to assign); `src/assistant/alive_sync.py`,
`tests/test_e_alive_sync.py`, `tests/test_e_alive_layer.py` — E;
`reports/RPT-E-alive-build-*` — E. No other file touched. The PR merges
after CI; the on-laptop eye check is the owner's, in this order: doctor →
fixture round-trip → test-number week → first real reminder → first stranger
plan read aloud.
