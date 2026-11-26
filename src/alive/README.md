# Elaria Alive Layer — `src/alive/`

**Deterministic · LLM-free · authority-free.** "Elaria's voicemail that can
also ring you." It holds stated-commitment reminders, an append-only
instruction inbox, and its own identity — and it can do five verbs and no
others: *remind*, *receive*, *acknowledge-as-queued*, *queue*, and (for
strangers) *converse-and-collect-a-proposal* under zero authority.

It is NOT full Elaria. It has no model, no tools, no memory of the owner, no
way to act. Everything it writes is a signed, immutable, hash-named
envelope; the laptop verifies and replays instructions through the normal
`cloud_queue` → `awaiting_approval` → spoken-yes path. If the host is
compromised, the attacker gets two revocable tokens and non-secret
reminders — never the voiceprint, never the owner's keys, never
`assistant.db`, never any authority.

**Status of this directory:** built and tested against fake Meta payloads
and a fake transport. NO real token, number, Drive folder or host has been
touched. Real registration, provisioning and the first real reminder are
the owner's laptop-side step, and are NOT claimed here.

## Layout

| file | what it is |
|---|---|
| `envelope.py` | the signed wire format (shared with `assistant/alive_sync.py`) |
| `config.py` | single-recipient, egress allowlist, caps — refuses bad config |
| `store.py` | SQLite state: dedup, 24h service windows, delivery statuses, write-ahead reminder rows, counters, mutes |
| `templates.py` | S-0 utility template pack (`elaria_meeting_v1`, `elaria_deadline_v1`, `elaria_commitment_due_v1`, `elaria_already_sent_knock_v1`) |
| `transport.py` | real WhatsApp Cloud API adapter (24h window enforced; paid-template cap; KES-cents journaling); `FakeTransport` for tests |
| `concierge.py` | S-0 deterministic stranger responder (no LLM, ever) |
| `mirror.py` | verified reader for the laptop's commitments snapshot |
| `reminders.py` | write-ahead, capped reminder firing (`tick()`) |
| `webhook.py` | serverless-shaped receiver: signature → tier → envelope |
| `sync.py` | sync backends: `FixtureSyncBackend` (labelled fixture) and `RcloneSyncBackend` (pinned minimal surface) |
| `heartbeat.py` | the one mutable object, mac'd |
| `serve.py` | dev runner; production = any free serverless route |
| `provision.py` | key generation + the self-check |

## What the host may hold (closed list)

commitments mirror (read) · inbox envelopes ≤ 72 h · reminder log · its own
heartbeat. Nothing else. The laptop never holds the WA token; the host never
holds the owner's keys.

## Owner laptop step — bring-up checklist (in order)

1. **Platform decision** is settled per the manager gate: WhatsApp Cloud
   API + S-0 templates (the owner updates the SIM registration themselves;
   keep-alive is theirs).
2. Create the Meta Business portfolio, WABA, and the dedicated number
   under Fork 4 (Elaria's own asset). Set the Meta **spend limit** to the
   minimum. Create a **System User** token scoped to that one WABA.
3. Create **Elaria's own Google account**, one folder `elaria-sync/`,
   shared read/write to the owner's account. The host's rclone remote
   uses Elaria's token pinned to that folder; the laptop's uses the
   owner's token pinned to the same folder (`root_folder_id`).
4. Submit the four S-0 utility templates (`python -m alive.provision templates`)
   in WhatsApp Manager (`elaria_meeting_v1`, `elaria_deadline_v1`,
   `elaria_commitment_due_v1`, `elaria_already_sent_knock_v1`). Full step-by-step
   registration runbook: `reports/RPT-E-whatsapp-runbook-20261126T083500Z.md`.
5. On the host: copy `src/alive/` → install deps →
   `python -m alive.provision init` → fill `alive.toml` (mode 0600) →
   `python -m alive.provision doctor alive.toml` → **B16 acceptance
   test**: grep the host for `voxceleb`, `assistant.db`, `voiceprint`,
   `GEMINI`, the owner's Google token — all must be absent.
6. Bind `webhook.handle_request` to a free serverless route
   (Cloudflare Workers-class) as `POST /webhook` + `GET /webhook`, with
   cron/timer calling `reminders.tick()` every 60 s and
   `heartbeat.write_heartbeat()` every 15 min. Point the Meta webhook
   at it (HTTPS :443, valid CA). Subscribe to `messages`.
7. Laptop: copy `src/assistant/alive_sync.py` into the daemon deployment;
   cluster U wires the startup hook (ingest on online transition +
   "line asleep since" line + knock "already sent" variant) — one
   `create_task` and one conditional, per the design's ownership map.
8. Laptop exports: `export_commitments` on session end + on commitment
   change; `export_public_card` if the owner wants the front door;
   `export_t1_hashes` for approved contacts.
9. First week: use the Meta **test number** ($0, 5 recipients,
   dev-only) and a fixture folder before switching to the real one.

## Remediation card (if the host is lost)

Revoke the WA System User token → revoke the Google token for
`elaria-sync/` → delete the Tailscale/serverless node → rotate `mac_key`
and `from_hash_salt` (laptop + host together) → owner reviews the last
72 h of instructions the host saw. Done. The owner's phone keeps working;
the laptop is unchanged.

## What this deliberately cannot do

No acting, no sending as the owner, no spending (template cap in code),
no editing anything, no voice, no LLM, no interpreting the owner. Every
action happens on the laptop, after her spoken yes. A stranger who talks
her into something gets a proposal envelope labelled `stranger`, read
aloud by full Elaria, and nothing else.

## Tests

```
PYTHONPATH=src pytest tests/test_e_alive_layer.py tests/test_e_alive_sync.py
```

Sandbox only: fake payloads, fake transport, fixture remote. Nothing here
touches a network.
