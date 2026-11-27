# DISPATCH-PHONE-WIRE — wire the phone lane into the daemon (2026-11-27)

Found at the hardware pass (`bugs.md` GAP-HW3): `phone_link.py`
is complete and test-proven, but nothing in the daemon or CLI
instantiates it. The owner's SMS ruling (approve-each, `reports/
OWNER-RULING-SMS-REPLIES-20261126.md`) currently has no live path.

### STATUS (manager, 2026-11-27): partial + MANAGER CORRECTION

First execution: S-C2 fixed (explicit `device=` differing from
the configured binding is refused + journaled before any packet;
119 phone-link tests pass) — but **uncommitted, no PR**, so not
landed. **Correction (agent-caught, manager-owned):** the
lifecycle below originally said "connect/reconnect with backoff"
— WRONG. The owner-approved IF-3 amendment
(`docs/contracts/IF-3-OWNER-AMENDMENT.md`) mandates a strictly
**on-demand** sidecar: pull on demand + owner-initiated approved
push, never a continuously running connection. Item (2) is
amended accordingly in PHONE-WIRE-2.

### OWNER PRIVACY RULING — notifications (2026-11-27)

Owner paired the phone via KDE Connect and found every
notification exposed on the desktop — messages included. His
phone posture is "hide sensitive content"; Elaria must inherit
it. Binding on PHONE-WIRE-2 and any notification surface:
(1) notification BODIES are sensitive content — she may surface
existence only (app + sender + count, e.g. "2 messages from
Mum"), never body text on console/overlay/spoken output by
default; (2) revealing a body requires the owner's explicit
in-the-moment ask (voiceprint-gated like any owner authority),
is journaled, and is never part of a proactive knock/summary;
(3) notification content is untrusted data (IF-6) AND sensitive
— both rails, always; it never enters long-term memory as
`stated`, never leaves with diverted providers, and bodies are
excluded from any cloud call (local handling only); (4) stranger/
guest/showoff modes: not even existence metadata beyond a count.
Owner-side interim hygiene (his settings, today): KDE Connect
phone app → device → Notification sync plugin → allowlist only
the apps that should mirror at all; banking/auth apps never.

## PHONE-WIRE-2 — Agent P (complete, on-demand)

> You are Agent P. PHONE-WIRE round 1 landed nothing (S-C2 fix
> exists only in an uncommitted checkout — first recover or redo
> it, say which in the PR). Complete the lane per the original
> dispatch with this amendment: the sidecar lifecycle is
> **ON-DEMAND** per `docs/contracts/IF-3-OWNER-AMENDMENT.md` —
> connect per owner-initiated interaction (status/inbox/draft/
> approve), disconnect after; no persistent connection, no
> reconnect loop, no background polling. Sidecar absent =
> `assist phone status` reports down honestly. Everything else
> stands: `[phone]` config (enabled=false default), owner-gated
> IPC, `assist phone {status,inbox,drafts,approve,reject}`,
> personality-path drafting with expiry, fake-sidecar eye-checks
> (approve fires exactly one `sms.send_sms`; reject/expiry/
> injection send nothing; sidecar absence crashes nothing), and
> the owner pairing script ending the report. Completion = a
> MERGED PR containing the S-C2 fix AND the wiring. Sync main
> first. Never edit OWNERS.yaml. Never widen the verb set.

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
