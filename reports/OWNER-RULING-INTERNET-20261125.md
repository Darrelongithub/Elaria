# OWNER RULING — internet & presence (2026-11-25)

Answers to the four forks in HANDOFF §12A, ruled by the owner.
Defaults accepted on Forks 1–3; Fork 4 amended by the owner.

| Fork | Ruling |
|---|---|
| 1. Autonomous egress | **Defaults:** public reads only — official APIs + plain HTTP, no logins, every read journaled |
| 2. Acting-as-the-owner | **Never.** She never posts/likes/sends *as the owner* except through the existing approval gates (draft → approve → send) |
| 3. Workarounds | **Never.** No proxies, anti-detect, evasion. `PLATFORM_BLOCKED` / `NEED_LOGIN` / rate-limit are terminal, journaled, reported |
| 4. Channels | **Amended by owner:** the allowlist may grow, and **accounts may be created FOR HER** — Elaria may hold her *own* accounts (her own X, her own WhatsApp) in her own name/identity, created by the owner, used to read and to be reachable. Acting as *Elaria* is not acting as the owner; impersonation of the owner remains Fork-2-forbidden. Each new channel/account is assessed and added individually — no blanket permission |

## The presence ruling (same conversation)

Hosting was never about her leaving the laptop. It is about her
being **alive when the laptop is off**: the owner at school gets a
DM from her dedicated WhatsApp — "Hey, remember meeting at 7" —
replies, starts the laptop, and she says "okay, I will" and does
the work. Architecture consequence, recorded as direction:

- **Full Elaria stays on the laptop** (mic, desktop, phone sidecar,
  voice lock — unchanged).
- **An always-alive layer** (small, always-on, hosted where the
  owner chooses — a Pi, a NAS, a tiny VPS) holds only: clock /
  calendar / reminders, her own messaging identities, and a queue
  of owner instructions received while the laptop slept.
- The alive layer has **no authority**: it can remind, receive,
  acknowledge, and queue. It cannot act, send-as-owner, spend, or
  change anything. When the laptop wakes, full Elaria drains the
  queue under every existing gate.
- Backup (landed storage, rclone → owner's own Drive) is how the
  two halves stay the same person.

Design/research for the alive layer: `reports/DISPATCH-ALIVE.md`.
Internet Phase 0 (egress ruling + untrusted-input split,
interface-level): the Agent-Reach blueprint in HANDOFF §12A plus
this ruling; research dispatch in the same file's channel R-0.
