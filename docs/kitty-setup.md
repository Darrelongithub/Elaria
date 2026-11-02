# Kitty hands — owner setup draft (2026-11-02)

**HELD / TESTED-ONLY.** This is a setup reference, not permission to activate a live
adapter. The additive library has no daemon/console registration and no default
independent checker. Complete the integration and drift gates before the owner scene.
Nothing here has been applied to kitty, Hyprland, system services or owner files.

Authority: owner sequencing-only addendum > builder block v1.1 > unchanged clause v2.
Current lane: `arena/b65d5161-elaria`, accepted in place by the **2026-11-02 design
checkpoint ruling**, additive after `35adbba`; NO PR. The earlier “explicit A” was
sequencing-only and named no lane. See `docs/design/kitty-2026-11-02-checkpoint-ruling.md`.
At branch-creation/merge era, cherry-pick kitty commits onto a hands-tip-based branch;
the separate console `35adbbaf` cherry-pick plan is unchanged. Never force-push.

## 1. Record actual versions before changing anything

Owner TERMINAL, not EARS:

```sh
kitten --version
rpm -q kitty kitty-kitten kitty-shell-integration kitty-terminfo
rpm -ql kitty kitty-kitten kitty-shell-integration kitty-terminfo
ssh -V
hyprctl version
```

Keep output owner-side. Bring back only version/package metadata and the small drift
report, not terminal contents, environment, credentials or personal paths. The design
record's `0.47.1-1.fc44` is not a substitute for verbatim output. Fedora base/update and
four-way package-split claims were not independently verified in this sandbox.

## 2. Password posture (three explicit verb lists)

The exact v0.47.1 lists are below. **The angle-bracket strings are documentation
markers, NOT usable passwords. Never install them literally.** Generate three distinct
48-character random values on the owner's machine; do not paste them into chat,
commit them, put them in process argv, or export them in the environment.

```text
allow_remote_control password
listen_on unix:${XDG_RUNTIME_DIR}/elaria-kitty-{kitty_pid}.sock
remote_control_password "<OWNER_GENERATED_K1>" get-colors get-text ls scroll-window
remote_control_password "<OWNER_GENERATED_K2>" close-tab close-window create-marker detach-tab detach-window disable-ligatures focus-tab focus-window get-colors get-text goto-layout last-used-layout launch ls new-window remove-marker resize-os-window resize-window run scroll-window select-window send-text set-background-opacity set-colors set-enabled-layouts set-font-size set-spacing set-tab-color set-tab-title set-user-vars set-window-title
remote_control_password "<OWNER_GENERATED_K3>" action close-tab close-window create-marker detach-tab detach-window disable-ligatures env focus-tab focus-window get-colors get-text goto-layout kitten last-used-layout launch load-config ls new-window remove-marker resize-os-window resize-window run scroll-window select-window send-key send-text set-background-image set-background-opacity set-colors set-enabled-layouts set-font-size set-spacing set-tab-color set-tab-title set-user-vars set-window-logo set-window-title signal-child
```

K2 includes `send-text` for reversible acts in HER journaled windows. Passwords cannot
restrict targets; this is why bridge target/nature gates remain mandatory. K3 includes
all 39 known verbs because irreversible acts can use any of them. No wildcard silently
authorizes future verbs. New verbs are K3 in the bridge and need explicit owner-side
password-list reconciliation after an upgrade. No verb is permanently excluded.

`socket` and `socket-only` are **not** substitutes: they unconditionally authorize
socket requests. Do not configure an empty password or `*` grant. Do not combine this
with a permissive existing password line. Audit the whole effective configuration.

An owner-only generation example follows. It creates **inactive** private password
files and a separate snippet; it does not edit kitty.conf or reload anything. Execute
only deliberately in the repository's root on the owner's machine. No password is
printed. Existing files cause failure rather than replacement. The snippet is private
because it contains the same secrets as the tier files.

```python
import json, os, secrets, stat
from pathlib import Path

os.umask(0o077)
root = Path.home() / '.config/assistant/kitty-secrets'
root.mkdir(mode=0o700, parents=True, exist_ok=True)
assert not root.is_symlink()
assert root.stat().st_uid == os.getuid()
assert stat.S_IMODE(root.stat().st_mode) == 0o700
inventory = json.loads(Path('src/assistant/hands/kitty/data/inventory.json').read_text())
verbs = inventory['verbs']
k1 = {v for v, spec in verbs.items() if spec['tier'] == 'K1'}
k2 = k1 | {v for v, spec in verbs.items() if spec['tier'] == 'K2'} | {'send-text'}
lines = ['allow_remote_control password',
         'listen_on unix:${XDG_RUNTIME_DIR}/elaria-kitty-{kitty_pid}.sock']
for tier, allowed in [('K1', k1), ('K2', k2), ('K3', set(verbs))]:
    password = secrets.token_hex(24)
    with (root / (tier + '.pass')).open('x') as output:
        output.write(password + '\n')
    lines.append('remote_control_password "' + password + '" ' + ' '.join(sorted(allowed)))
with (root / 'kitty-rc.conf').open('x') as output:
    output.write('\n'.join(lines) + '\n')
```

After manual review, the owner may add a single `include` for that snippet to
kitty.conf. Do not print the effective configuration into shared logs. Restart kitty:
`listen_on` is not reloadable. If an existing permissive RC configuration was present,
remove it manually only after backup/review; this repo does not change it for you.

## 3. Socket / public-key preflight

- Fedora's expected runtime is `/run/user/$UID`, owned by the user, mode **0700**.
  If `XDG_RUNTIME_DIR` is unset, stop. Never fall back to `/tmp` or discover by probing
  a glob. Choose the exact socket for the intended kitty instance.
- The bridge requires its socket directly under that runtime directory. Before **every**
  connect it walks ancestors without following symlinks, rejects group/world-writable
  or foreign-owned ancestors, checks the 0700 parent, and checks lstat/S_ISSOCK/own UID.
  It connects via an anchored directory fd and checks Linux SO_PEERCRED plus inode identity.
- Password files must be owned, regular, single-link, **0600**; no symlink ancestors or
  files, no empty password, no fallback to another tier. Read on each request, not import.
- The public key is the intended instance's `KITTY_PUBLIC_KEY` (`1:...`) obtained within
  that instance. It is public, but it must not come from untrusted terminal output.
  Don't guess it or reuse a key from another instance. Clock skew over five minutes
  causes encrypted requests to fail.
- This is same-UID local trust, not protection from a compromised owner account. Passwords
  plus private paths do not isolate processes that can read all the owner's files.
- The transport uses the local Python `cryptography` package for X25519/AES-GCM. An owner
  may provision Fedora's `python3-cryptography` in the chosen runtime. Missing dependency
  fails closed. No package, pyproject or environment changes are applied by the bridge.

## 4. Hyprland v0.57.0 focus rule — version-correct Lua

The clause's historical line is **not** a valid 0.57 install instruction:

```text
# Historical only; do not install on 0.57:
windowrulev2 = noinitialfocus, initialTitle:^\[ELARIA
```

v0.57.0 uses Lua. The owner-reviewed equivalent in `hyprland.lua` is:

```lua
hl.window_rule({
    name = "elaria-no-initial-focus",
    match = { initial_title = [[^\[ELARIA.*]] },
    no_initial_focus = true,
})
```

The `.*` is intentional for whole-string regex matching. Verify the installed version
and configuration parser first. Source check: v0.57.0 `Rule.cpp` accepts `initial_title`,
`WindowRuleEffectContainer.cpp` exposes `no_initial_focus` and `stay_focused`, and
`LuaBindingsConfigRules.cpp` exposes `hl.window_rule`. No live compositor test was run.

Every launch is prepared with `keep_focus=true` and `[ELARIA ...]` title stamps before
plan hashing. For an OS window, both OS and child/window titles are stamped. Tabs and
kitty windows are not separate Hyprland surfaces: the Lua rule does not replace
`--keep-focus`. `stay_focused` is different: it pins focus to an existing surface. Audit
broad owner rules for conflicts and do not add `stay_focused` to HER arrivals. Test both
her arrival and the owner's deliberate later focus change; never change rules silently.

## 5. Separate bridge settings — every key

`~/.config/assistant/kitty-bridge.toml`, owned regular file **0600**. Not assistant's
schema-validated config.toml. Paths below are examples: replace UID/PID and account
paths with actual absolute paths. No tilde/environment expansion is performed.

```toml
socket = "/run/user/1000/elaria-kitty-12345.sock"
journal = "/home/OWNER/.local/state/assistant/kitty/events.jsonl"
timeout_seconds = 5.0
max_response_bytes = 8388608

[password_files]
K1 = "/home/OWNER/.config/assistant/kitty-secrets/K1.pass"
K2 = "/home/OWNER/.config/assistant/kitty-secrets/K2.pass"
K3 = "/home/OWNER/.config/assistant/kitty-secrets/K3.pass"
```

| Key | Meaning / default |
|---|---|
| `socket` | Required exact socket, directly under current XDG_RUNTIME_DIR; no discovery. |
| `journal` | Required private JSONL file; owner provisions its parent as 0700. Service creates file 0600. |
| `timeout_seconds` | Per-request bound, default 5, range `(0,60]`; no retry. |
| `max_response_bytes` | Total response bound, default 8 MiB; allowed 1 KiB–64 MiB. |
| `password_files.K1` | Required absolute runtime-read K1 password path. |
| `password_files.K2` | Required absolute runtime-read K2 password path. |
| `password_files.K3` | Required absolute runtime-read K3 password path. |

Unknown keys, inline passwords and any `hand_open` setting are rejected. Stream input
currently has a one-shot 1 MiB bound. Timeout/crash means **effect unknown, no replay**.

## 6. Trusted-host contract and outstanding integration gate

**Protected-file wall identified at the next checkpoint:** the existing daemon has a
fixed `Daemon._handlers()` table and no plugin registration hook. Its authenticated IPC
boundary is in protected `src/assistant/daemon.py`. The frozen hands bridge/core are
synthetic-only, not an alternate production host. A real host mount needs a specific
ruling; a copied/replacement daemon, monkey-patch or second daemon is not a workaround.
No protected file has been changed. Other additive module work remains possible.

The additive API is `Bridge(transport, checker, journal, verifier=...)`. Its `Act.plan()`
uses the existing immutable `Plan/Step` canonical hash; `Authorizer` calls existing
`hands.gate.adjudicate` at planning and pre-execution. K tiers do not replace T tiers:
legacy T2 still needs exact Yes; legacy T3 is refused even with a K3 approval.

- The checker is a trusted independent effect assessor. Model/tool output must not supply
  it, supply `Assessment`, call `open_hand`, or call `decide`. There is **no** default
  permissive checker. A lambda that returns a fixed safe tier is a test fixture, not a
  production integration. The frozen synthetic GateChecker cannot assess live kitty.
- `open_hand(owner_phrase="kitty hand open", reference=OPAQUE_REF)` is a deliberate,
  session-scoped owner-input act. New Bridge instances start closed.
- K3 consent binds whole plan, exact payload, and ID/PID/cmdline/foreground-process/
  creation identity fingerprint. No is terminal for that plan. Mutation after approval
  makes the approval stale. Newline/CR/escape execution characters need explicit per-act
  execution acknowledgement; unknown bracketed-paste state needs program acknowledgement.
- Read `ls` and `get-text` before sends, recheck identity immediately before sending,
  observe `ls/get-text` after. A newly observed exact text delta is **not execution proof**.
  Existing text, missing targets, no echo or a lying success stay `unverified`.
- Journal target cmdlines are represented by exact SHA256 and argument count, plus a
  foreground-process hash, not raw arguments: raw command lines can contain passwords.
  The private consent disclosure may use the transient exact command line. This avoids
  violating the secret-free event requirement; no terminal text is journaled.
- Journal sink must be durable. `EventJournal` fsyncs private JSONL; `kitty.act` records are
  console-renderable, but delivery into the frozen console/registry is **not implemented**.
- The library intentionally has no CLI that could bypass the trusted host. Production
  checker, owner-input binding, durable restart/replay reconciliation, cancellation, broad
  selector/effect coverage and live registration remain integration work. Stop for an
  explicit ruling before touching any protected/frozen integration file.

## 7. Upgrade drift

Owner-only, help/version calls (no remote-control connection):

```sh
python tools/kitty/drift.py --output "$HOME/kitty-drift-2026-11-02"
```

Choose a new output directory outside the repo each time. It stores private verbatim
version/help records and a small `report.json`: missing/new verbs, option/default deltas,
help hashes and parser errors. Exit 0 is only a metadata match. Manually reconcile
semantics, installed SSH/Fedora membership and all errors before the owner scene and
before any “done” claim. Never upload password files or raw ls/get-text outputs.
