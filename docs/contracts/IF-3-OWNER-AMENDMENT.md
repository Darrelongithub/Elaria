# IF-3 OWNER AMENDMENT — ON-DEMAND SIDECAR LIFECYCLE & `v1.1.1` PIN

- **Date:** 2026-11-22
- **Supersedes / refines:** `contracts/IF-3-caelestia-adapter.md` (`0e997b2c321d1430b51e613f2782c9207cbd0107938608815759d0368f6da058`) where IF-3 implies a permanently running sidecar daemon (`caelestia-connectd`).
- **Status:** Owner-approved rider (does not alter the byte-stable published SHA of `IF-3-caelestia-adapter.md` in the pack).
- **Upstream pin:** `maylton/caelestia-connect` tag `v1.1.1`, commit `b49ca2c9f76dd6feccf40fb6b82fc98db344c613`, tarball SHA-256 `fa305344123b481d9ba09b5aee46b31a9cb46ad73fef6ef8dfa3d83ae4ee8bd6`.

## 1. Idle by Default (Contract Invariant, Not a Settings Toggle)

`caelestia-connectd` MUST NOT run continuously at session login and MUST NOT keep persistent KDE Connect v8 UDP beacons, TCP keepalives, TLS sockets, or Bluetooth RFCOMM links open while idle.

- Elaria's phone workflow is strictly **pull-on-demand** (read conversations/messages, battery, connectivity, telephony, notifications, ping) plus **owner-initiated approved push** (`sms.send_sms` only after IF-1 `approved` state).
- Because keeping the sidecar idle when unused eliminates background radio wakeups and battery drain across both laptop and phone, idle-by-default is an architectural contract invariant — not a user-facing settings option.

## 2. On-Demand Activation & Teardown

1. **Disabled at login:** `systemctl --user disable --now caelestia-connectd.service` (installed via `install.sh --no-shell` or packaged unit without automatic `graphical-session.target` startup).
2. **Active window only when triggered:** Elaria starts `caelestia-connectd.service` on demand (and stops it on completion) strictly for:
   - explicit owner/assistant pull requests (`READ_VERBS`),
   - an owner-approved `sms.send_sms` push via `PhoneLink.send_approved()`,
   - an explicit owner pairing, revocation, or unpair-sync window.
3. **Teardown:** After the pull/push completes (and any short KDE Connect v8 send ACK grace window `<= 15s` closes), Elaria stops `caelestia-connectd.service` so no background daemon, socket, or LAN/Bluetooth radio session lingers.

## 3. Transport, Sync, and Revocation Semantics Under On-Demand Links

1. **Idle socket absence is normal:** Outside an active window, `$XDG_RUNTIME_DIR/caelestia-connect/ipc.sock` is absent and `TransportError` from `PhoneLink` is the expected idle signal — not a fault to hide by auto-spawning an always-on daemon.
2. **Catch-up pull on wake:** Because the daemon does not listen continuously for push events, inbound SMS threads missed while idle are fetched explicitly on the next active window via `sms.request_conversations` / `sms.request_conversation` + `sms.conversations` / `sms.messages`, delivered through IF-6 as untrusted data.
3. **Independent IF-1 draft store:** `DraftStore` remains durable in local SQLite (`0600`) regardless of sidecar state; `create_draft()`, `approve()`, `reject()`, and `expire_sweeper()` never require `caelestia-connectd` to be running.
4. **Revocation propagation & `pending-unpair`:** Calling `PhoneLink.revoke(device_id)` emits `device.unpair` to the sidecar before clearing local pairing state. If the sidecar is unreachable at revocation time, local refusal stands immediately (`is_revoked(device_id) == True`), the pairing is marked `pending-unpair` on disk (`pairs.json`, `0600`), and `device.unpair` is retried automatically on the next link-up before any reads/sends rely on sidecar state.
5. **Local pairing check pre-IPC:** `PhoneLink.send_approved(..., device=...)` verifies local pairing & revocation state (`PairingRegistry`) before issuing any IPC frame, refusing revoked or unpaired devices locally with zero packets sent.
