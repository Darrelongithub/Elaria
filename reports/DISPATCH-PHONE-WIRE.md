# DISPATCH-PHONE-WIRE — wire the phone lane into the daemon (2026-11-27)

Found at the hardware pass (`bugs.md` GAP-HW3): `phone_link.py`
is complete and test-proven, but nothing in the daemon or CLI
instantiates it. The owner's SMS ruling (approve-each, `reports/
OWNER-RULING-SMS-REPLIES-20261126.md`) currently has no live path.

## PHONE-WIRE — Agent P

> You are Agent P. Wire the phone lane end-to-end, daemon side.
> Existing pieces: `src/assistant/phone_link.py` (sidecar adapter
> for the pinned caelestia-connect sidecar, `sms.send_sms` the
> only write verb, post-approval only, pairing read-only — the
> sidecar's code is never imported, LICENSE-DECIDES-METHOD),
> console draft-review surface expectations (`console/`), and the
> owner ruling: inbound SMS = untrusted (IF-6) → she drafts →
> owner approves/edits/kills EACH draft → `sms.send_sms` fires;
> silence sends nothing; everything journaled. Build: (1)
> `[phone]` config (enabled=false default, sidecar socket path,
> configured device binding — note suspect S-C2 in `bugs.md`:
> an explicit `device=` argument must NOT silently override the
> configured device; resolve it as part of this lane and say how);
> (2) daemon wiring: PhoneLink lifecycle under the daemon
> (connect/reconnect with backoff, sidecar absent = phone lane
> quietly down, never a daemon crash), owner-gated IPC methods
> for status / inbound list / draft list / approve / reject, all
> behind `_require_ipc_owner()`; (3) `assist phone
> {status,inbox,drafts,approve,reject}` CLI; (4) drafting: inbound
> message → draft via the personality path only (provider pin
> rules apply; diverted material never becomes a draft verbatim);
> drafts expire. (5) Eye-checks with a fake sidecar peer (the
> test harness in `tests/test_phone_link.py` is your starting
> point): inbound text produces a draft and sends NOTHING;
> approve fires exactly one `sms.send_sms`; reject/expiry sends
> nothing; a prompt-injecting inbound text cannot reach the send
> path unapproved; sidecar death mid-draft loses nothing and
> crashes nothing. (6) Owner hardware script at the end: install/
> run the pinned sidecar, pair in the sidecar app (owner's act),
> `assist phone status` shows the pair, receive a text, approve a
> draft, confirm receipt on the phone. Sync main first. New
> `arena/*` branch, merged PR or it didn't happen. Never edit
> OWNERS.yaml. Never widen the verb set.
