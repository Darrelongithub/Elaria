# RPT-P-phone-wire-2 — On-Demand Phone Lane Wiring & S-C2 Fix (`PHONE-WIRE-2`)

- **Agent:** P
- **Branch:** `arena/3b697785-elaria` (base `68abecd`)
- **Date:** 2026-11-27
- **Dispatches & Contracts:** `reports/DISPATCH-PHONE-WIRE.md` (`PHONE-WIRE-2`), `docs/contracts/IF-3-OWNER-AMENDMENT.md`, `reports/OWNER-RULING-SMS-REPLIES-20261126.md`, `console/CONSUMER-CONTRACT.md`
- **Bugs closed:** `GAP-HW3`, `S-C2`

---

## 1. S-C2 Status (Recovered vs Redone)

**Redone cleanly.** No round-1 uncommitted checkout, branch, or stash existed in the repository or `origin`. The fix was implemented directly in `src/assistant/phone_link.py` and verified end-to-end:

- `PhoneLink.__init__` normalizes `self.device_id` (`None` when unset/blank, stripped string when bound).
- `PhoneLink.send_approved(..., device=...)` checks explicit `device=` **before** any pairing registry lookup or IPC packet:
  - Empty/whitespace `device=` is refused locally (`phone.refused` journaled, `Refused` raised).
  - When `self.device_id` is configured and explicit `device=` names any other device, it is refused locally (`phone.refused` journaled with `device_id` and `configured_device_id`, `Refused` raised, **zero** IPC packets sent).
- Defense-in-depth enforces the same configured-device binding inside `PhoneLink._call_plugin()` and pre-flight inside `PhoneService.approve_draft()`.

---

## 2. What Was Wired

| File | Change |
|---|---|
| `src/assistant/phone_link.py` | S-C2 fix in `send_approved` and `_call_plugin`; `inspect_state()` read-only helper (uses existing sidecar `"state"` query only); context manager (`__enter__`/`__exit__`) guaranteeing `close()`. **Verb allowlist (`READ_VERBS` = 8 verbs, `WRITE_VERBS` = `{"sms.send_sms"}`) unchanged.** |
| `src/assistant/config.py` + `config.toml.example` | Added `[phone]` section (`enabled = false` default, `socket_path = ""`, `device_id = ""`, `connect_timeout_s = 5.0`, `request_timeout_s = 10.0`, `draft_ttl_s = 900.0`, `max_inbox_threads = 20`, `max_thread_messages = 20`), `Config.phone_socket_path()` / `phone_device_id()` / `phone_drafts_db_path()` / `phone_pairs_path()`, and `validate_config()` rules. |
| `src/assistant/phone_service.py` | Strictly on-demand `PhoneService` orchestration: zero persistent connection, zero reconnect loop, zero background polling. Thread-safe local SQLite IF-1 `DraftStore` (`0600`) and `PairingRegistry` (`0600`). Canonical IF-6 trap detector (`hands/injection.py` + `phone_link.suspected_inbound`), IF-6 safe journaling (`SafetyJournal` `untrusted_input.load` + paired `begin`/`observe` without raw SMS/notification content), 2026-11-27 owner notification privacy ruling (`notifications()` existence-only default, bare count in guest/company/showoff mode, explicit owner-only local `--reveal` excluded from all cloud calls & memory), personality-only drafting through `ProviderRouter.personality` (pinned Gemini `gemini-3.5-flash-lite`; diverted `MaterialEnvelope` requires `revoice_material` + overlap/canary guards), and exact IF-2 console wire framing (`format_console_draft_frame`). |
| `src/assistant/daemon.py` | Instantiates `self.phone = PhoneService(...)` idle at startup; registers owner-gated (`_require_ipc_owner()`) IPC methods `phone.status`, `phone.inbox`, `phone.notifications`, `phone.draft`, `phone.drafts`, `phone.approve`, `phone.reject`, `phone.revoke`, and `console.command`; wires `events.subscribe({console_replay: true})` replay and live `draft.pending` / `draft.resolved` broadcasts; closes local `DraftStore` in `aclose()`. |
| `src/assistant/cli.py` | Added `assist phone {status,inbox,notifications,draft,drafts,approve,reject,revoke}` CLI surface. |
| `tests/test_bug7_cli_smoke.py` | Added all 8 `assist phone` leaf subcommands to `_smoke_table`. |
| `tests/test_p_phone_wire.py` | 18 end-to-end tests and fake-sidecar eye-checks (including all 4 clauses of the 2026-11-27 notification privacy ruling). |
| `bugs.md` | Marked `S-C2` and `GAP-HW3` fixed. |

---

## 3. Invariant & Eye-Check Verification

All 18 tests in `tests/test_p_phone_wire.py` pass against real Unix sockets (`FakeAndroidPeer` + live `Daemon` + real `assist` CLI + real `console/bridge.py::validate_draft_event`):

| Check | Result |
|---|---|
| S-C2 explicit `device=` mismatch refused locally (`PhoneLink` + `Daemon`), 0 IPC packets, journaled | PASS |
| On-demand lifecycle: 0 connections at boot, 0 background polling, `open_connections == 0` after every call; `drafts`/`reject` never touch sidecar | PASS |
| Sidecar absent -> `assist phone status` / `phone.status` / `phone.inbox` report `down` honestly, daemon never crashes | PASS |
| Eye-check 1: inbound SMS produces a `pending` draft via pinned Gemini personality route and sends NOTHING (`peer.sends == []`) | PASS |
| Eye-check 2: `approve` fires **exactly one** `sms.send_sms` with locked recipient & stored body; repeat approve refused; owner edit supersedes immutably | PASS |
| Eye-check 3: `reject` and TTL expiry (`expire_sweeper`) send NOTHING; silence sends NOTHING | PASS |
| Eye-check 4: prompt-injecting inbound SMS flagged (`suspected=True`), journaled (`phone.inbound.refused`, raw body never in journal), locked to original sender, cannot reach send path unapproved; credential/disclosure leak blocked | PASS |
| Eye-check 5: sidecar death mid-draft preserves draft in local `0600` SQLite and crashes nothing; approve while sidecar dead leaves draft pending; sidecar send-refusal marks `failed (send-error)` without crashing or retrying | PASS |
| Owner privacy ruling (2026-11-27 notifications): existence-only `(app, sender, count)` default, bare count only in company/guest/showoff mode, explicit owner local-only `--reveal` (journaled without bodies, excluded from all cloud calls & memory, voice-reveal fail-closed) | PASS |
| Personality provider pin: `ProviderRouter.personality` Gemini-only; diverted `MaterialEnvelope` verbatim copy refused (`RouteRefused`); quota exhaustion & poisoned/forbidden model refused | PASS |
| Owner-gated IPC (`SO_PEERCRED`): non-owner UID refused with `PermissionError` on every `phone.*` method and `console.command`; `halt` blocks `phone.approve` | PASS |
| Console IF-2 compatibility: `events.subscribe({console_replay: true})` + live `draft.pending`/`draft.resolved` frames pass `console/bridge.py::validate_draft_event` and `console.command` works end-to-end | PASS |
| Verb allowlist unchanged (`READ_VERBS` = 8, `WRITE_VERBS` = `{"sms.send_sms"}`); zero `caelestia`/`evdev` imports; `OWNERS.yaml` untouched | PASS |
| Repo test suite: `3,612 passed, 0 failed` (`ruff check` clean across all modified files) | PASS |

---

## 4. Owner Hardware & Pairing Script (Arch / Hyprland)

The sidecar is the pinned GPL-3.0 upstream release **`maylton/caelestia-connect` `v1.1.1`** (never vendored or imported into Elaria — spoken to strictly over AF_UNIX IPC at `$XDG_RUNTIME_DIR/caelestia-connect/ipc.sock`, mode `0600`).

### Step 1 — Download, verify SHA-256, and install the pinned sidecar (`v1.1.1`)

```bash
# Pinned release from docs/contracts/IF-3-OWNER-AMENDMENT.md:
#   tag:    v1.1.1
#   commit: b49ca2c9f76dd6feccf40fb6b82fc98db344c613
#   sha256: fa305344123b481d9ba09b5aee46b31a9cb46ad73fef6ef8dfa3d83ae4ee8bd6

mkdir -p ~/.local/src
curl -fsSL -o ~/.local/src/caelestia-connect-v1.1.1.tar.gz \
  https://github.com/maylton/caelestia-connect/archive/refs/tags/v1.1.1.tar.gz

echo "fa305344123b481d9ba09b5aee46b31a9cb46ad73fef6ef8dfa3d83ae4ee8bd6  $HOME/.local/src/caelestia-connect-v1.1.1.tar.gz" \
  | sha256sum -c -

tar -xzf ~/.local/src/caelestia-connect-v1.1.1.tar.gz -C ~/.local/src
cd ~/.local/src/caelestia-connect-1.1.1
# Install into an isolated venv or via pipx (never inside Elaria's checkout):
python3 -m venv ~/.local/share/caelestia-connect-venv
~/.local/share/caelestia-connect-venv/bin/pip install .
```

### Step 2 — Enable `[phone]` in `~/.config/assistant/config.toml`

Add (or uncomment) in `~/.config/assistant/config.toml`:

```toml
[phone]
enabled = true
# Leave empty to use default $XDG_RUNTIME_DIR/caelestia-connect/ipc.sock
socket_path = ""
# After Step 4 below, paste your phone's exact device id here to lock S-C2 binding:
device_id = ""
draft_ttl_s = 900.0
```

Validate config and restart Elaria's daemon:

```bash
assist doctor
systemctl --user restart assistd.service
```

Verify idle-by-default behavior BEFORE starting the sidecar:

```bash
assist phone status
# Expected: exit 1, "sidecar: down", assistd stays healthy (`assist status` shows up)
```

### Step 3 — Start the sidecar on demand & pair your phone (owner's act)

1. Install **KDE Connect** on your Android phone (same LAN/Wi-Fi as your laptop) and grant it SMS permission inside the Android app.
2. Start the sidecar daemon in a terminal (or on-demand user unit — do **not** `systemctl --user enable` it if you want strictly manual on-demand lifetime):

```bash
~/.local/share/caelestia-connect-venv/bin/caelestia-connectd
```

3. Verify the socket exists with `0600` permissions:

```bash
ls -l "$XDG_RUNTIME_DIR/caelestia-connect/ipc.sock"
```

4. Pair in the sidecar / KDE Connect app (**owner's deliberate act** — confirm the verification key on both devices):
   - Open KDE Connect on your phone, tap your laptop, and accept the pairing request in the sidecar UI/CLI (`caelestia-connect` client).
   - **Privacy hygiene (2026-11-27 owner ruling):** in the Android KDE Connect app → select your laptop → **Notification sync** plugin → allowlist only apps that should mirror at all (**never** banking/authenticator apps). On Elaria's side, `assist phone notifications` surfaces existence counts only by default (bodies hidden unless you explicitly run `assist phone notifications --reveal`, which is local-only and excluded from all cloud calls).

### Step 4 — Confirm the pair in Elaria & pin `device_id`

```bash
assist phone status
```

- Confirm output shows `sidecar: up`, `paired: yes`, and your phone's name and `[<device_id>]`.
- Copy `<device_id>` into `[phone] device_id = "<device_id>"` in `~/.config/assistant/config.toml` and restart `assistd` so S-C2 device binding is locked to your phone.

### Step 5 — Receive a text, inspect inbox, draft reply (NOTHING sent yet)

1. Send a test SMS from a second phone/contact to your paired Android phone (e.g., `"Are you free in ten minutes?"`).
2. Pull the inbox on demand:

```bash
assist phone inbox
# Note the numeric thread id (e.g. thread=42)
assist phone inbox --thread 42
```

- Confirm the message appears labelled `[UNTRUSTED]` and **no SMS was sent**.

3. Draft a reply in Elaria's voice via the pinned Gemini personality route:

```bash
assist phone draft --thread 42
assist phone drafts
```

- Confirm the pending draft shows the **full recipient number**, the proposed body, `state: pending`, and **still no SMS has been sent**.

### Step 6 — Approve (or edit / reject) and confirm receipt on the phone

- **To send as drafted:**
  ```bash
  assist phone approve <DRAFT_ID>
  ```
- **Or to edit before sending (preserves locked recipient):**
  ```bash
  assist phone approve <DRAFT_ID> --body "Yes, ten minutes works."
  ```
- **Or to cancel without sending:**
  ```bash
  assist phone reject <DRAFT_ID> --reason "replied directly"
  ```

Verify:
1. Exactly **one** SMS arrives on the sender's phone matching the approved body.
2. Re-running `assist phone approve <DRAFT_ID>` is **refused** (cannot double-send).
3. `assist phone drafts --all` shows the draft in `sent` (or `failed (rejected)`).
4. Audit journal records every transition without logging raw inbound SMS content:
   ```bash
   assist events --recent 15
   ```

### Step 7 — Tear down sidecar & confirm honest down state

Stop `caelestia-connectd` (`Ctrl-C` in its terminal), then run:

```bash
assist phone status
assist status
```

- Confirm `assist phone status` reports `sidecar: down` honestly (exit 1), `assist phone drafts --all` still reads local drafts from SQLite, and `assistd` remains healthy with zero crash or reconnect loop.
