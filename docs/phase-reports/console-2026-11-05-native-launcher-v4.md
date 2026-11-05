# Task E — native launcher v4, 2026-11-05

**BUILD FINISHED / NOT OWNER-WIRED / NOT HARDWARE-ACCEPTED.** WS6-interim remains open for
its owner scene. Estimate before work and on resume: **2–3 hours**; no growth beyond that
estimate is claimed. Separate Task E commit; no PR, no force-push or owner-machine invocation.

## 1. Authority and exact deployment split

Appendix A is the approved **behaviour**, not byte-preservation, contract. Its supplied v3
SHA256 is `d2e4c916281db03f850f9df3d1f140efb975283158064f79f009aa0df0577b6b`; it is not
installed, executed or fetched by this implementation. The owner ruled that v2/v3 uncertainty
requires no further wrapper errand. This resolves the historical STOP in the Task D report.

Preserved exactly:

- Owner repo/interpreter: `/home/darrel/Elaria` and its `.venv/bin/python`.
- Detached worktree: `/tmp/elaria-bridge`, recreated at **fcd55ca1bce34d8a1f479bf2d035cc866c4a482f**.
- `console/run_bridge.py` SHA256 **ed227a7d50effb874e303f95462f3dc127c9bd79a71a8d9b34f86980815b091c**.
- Log: `/tmp/elaria-launch.log` (append, owner-only; a legacy owner-owned regular log is
  tightened to 0600 without truncation). Runtime launch files remain 0600 in 0700 directories.
- Bind target: `/home/darrel/.config/hypr/elaria-console-launch.sh`.
- Bridge absent → headless bridge, capture its private-launch-file line, then native window.
  Bridge present → another native window on a validated live launch file.
- Independent process sessions: bridge Ctrl-C does not kill windows; window close does not
  stop the bridge. The daemon and enabled elaria-console.service are not stopped or edited.

The unchanged owner-reported `hyprland.lua:149` entry is:

`hl.bind("SUPER + SPACE", hl.dsp.exec_cmd("/home/darrel/.config/hypr/elaria-console-launch.sh"))`

**No config edit is needed or performed.** This exact path, not a new binding or tool name,
is the install target. The installer contains no Hyprland reload, service or keybind command.

**Deliberate version split:** this path continues to run the historical fcd55ca1 bridge and
shell, not this branch's later A–C payload. A–C remain landed and unchanged, **not silently
substituted** into the worktree or advertised as wired by v4. The accepted Task D native host
is installed separately in a private helper directory. Old bridge payload and absolute engine
pins are verified; no native component overwrites them. The native path's per-reply UI features
are therefore those of the historical pin until a separate ruling changes that pin.

## 2. Artifacts and checksum chain

New files:

- `console/elaria-console-launch.sh`: same-path shim; checks the native coordinator's exact
  checksum before `/usr/bin/python3 -IB`; no browser invocation, profile, URL argv or fallback.
- `console/native_launch.py`: stdlib coordinator, historical worktree/launcher gates, lock,
  live-file validation, headless bridge start and detached native host invocation.
- `console/install_native_launcher.py`: defaults to artifact verification **only**. Explicit
  `--install` replaces the fixed wrapper and installs two pinned helper files; nothing launches.
- `console/native-launcher.sha256`: the release SHA256 chain, including the installer.
- `tests/test_console_native_launch.py`: temporary repositories, synthetic daemon/processes
  and installation targets, no real owner state or GTK claims.

The existing `console/native_window.py` and its pin are unchanged from Task D. All helper
files land in `/home/darrel/.config/elaria-console-native-v4/` (0700 directory; files 0700).
The source package is verified before any installation; symlink/wrong-owner/hardlinked targets
are refused. Helpers are atomically replaced before the shim; interruption can cause a checksum
STOP, not permission to execute a different unpinned release. No auto-update/repair fallback.

This is code for owner-side deployment, **not an installation already performed**. The
installer may create the required `.config`/`hypr`/bundle directories when absent, but edits
only the wrapper and helper files, never `hyprland.lua` or other configuration. No old wrapper
is sourced, no existing launcher body needs to be read, and no sensitive backup is made.

## 3. Git 2.39.5 STOP substitution and local-object recovery

The sandbox has **git version 2.39.5**. Its rejected `--no-lazy-fetch` invocation was the
previous correct STOP. No Git upgrade was performed. Under the owner's 2026-11-05 ruling,
configuration **key names only**, never values, were checked in this clone:

| Key-name pattern | Observed result |
| --- | --- |
| `extensions.partialClone` (`^extensions\.partialclone$`) | ABSENT |
| `remote.<name>.promisor` (`^remote\..*\.promisor$`) | ABSENT |
| `remote.<name>.partialCloneFilter` (`^remote\..*\.partialclonefilter$`) | ABSENT |

**The no-lazy-fetch guarantee holds by absence-of-promisor, rather than by flag.**

The coordinator repeats all three name-only checks before object verification/recovery,
and again against an existing/recreated target worktree. **Presence is refusal even when the
value might be false**; it never reads that value. A filtered/promisor clone must be replaced
through a separately authorised full clone or remain stopped; v4 does not clone or fetch.

Every Git verification/recovery command carries **`-c protocol.allow=never`**. As an additional
transport backstop, its subprocess environment sets **`GIT_ALLOW_PROTOCOL` to the empty
allowlist**, so protocol-specific `allow=always` configuration cannot override the general
default. Tests demonstrate file transport refusal even with a synthetic protocol-specific
allow. No additional configuration values are read for this protection. Inherited Git config
injection variables are excluded; replacement objects, checkout hooks and global attributes
are disabled for these operations. This is not a sandbox against malicious same-owner code.

Local commit existence is checked before recovery. Missing objects → STOP, no remote fetch.
Missing `/tmp/elaria-bridge` → detached worktree add at the exact SHA. Reboot may leave the
one Git registration while removing its /tmp directory: only then `worktree add --force
--detach` reuses **that missing path**. A locked registration is refused. No broad prune,
worktree remove, branch switch, dirty reset, owner checkout update or force-push occurs.
Existing wrong-HEAD/unsafe/modified pinned payloads are STOPs, not silently repaired.

Session bookkeeping, distinct from runtime recovery: Arena refreshed Git metadata to the
old base while retaining files. One explicit fetch of **this session's own branch** rehydrated
its local objects; all **314 accepted baseline entries** were then byte-checked before a
metadata-only mixed reset to 670a8d1. Verification reads used the transport backstop. This
was not a launcher fetch, owner worktree action or substitute for the local-only reboot test.

## 4. Live reuse, startup and privacy

- A private nonblocking runtime lock prevents simultaneous presses starting two bridges.
  An overlapping press stops visibly in the log; it does not queue an automatic retry.
- Listener identity comes from loopback `/proc/net/tcp` metadata and the owning process's fd
  table, then the **listener's** executable/script argv. Unrelated process argv is not read.
  Unknown/wildcard/IPv6/non-owner/ambiguous listeners cause STOP, never a second bind or kill.
- Existing v2/v3 bridges at the pinned path may be reused, including one previously started
  with --open; v4 itself **never supplies --open**, calls a browser or revives app mode.
- Candidate launch files are bounded (128 files, eight-second discovery deadline), validated
  by Task D's strict private-file reader, and challenged against the live bridge. Selection is
  not based on the newest filename or mtime; stale tokens are refused even in newer files.
- The challenge is a loopback WebSocket upgrade with token/Origin only in memory. It verifies
  the server's 101/accept response, then closes **without hello or a turn**. It does not call a
  model, console.say or even daemon status. It is liveness/pairing evidence, not native WebKit
  compatibility or backend readiness. The unchanged bridge client limit still applies.
- For absent bridges, `setsid` semantics come from Popen(start_new_session=True): headless
  legacy launcher, null stdin, log stdout/stderr, closed inherited FDs. The private-file line
  is captured from only the new bounded log segment and its token is validated before use.
  Startup is bounded; an uncertain startup is not killed, restarted or replayed automatically.
- Only the **file path**, not its content/URL/token, goes to the independent native host's
  argv. The host's fixed ELARIA title, ephemeral view and no-URI diagnostics remain Task D's.
  Both subprocess environments exclude model keys, agents, Python/Git injection and WebKit
  debug overrides. No persistent browser profile or new persistent pairing-token record.
- Missing GI/WebKit preflight stops before worktree/startup, with the one-line dnf hint. No
  Chrome fallback. Native launch is reported as **requested**, not proof of visible rendering.

Replacing this script does not kill an unrelated/pre-existing Chrome/Chromium process or
alter an existing service's invocation. **This implementation creates none; a globally clean
process census remains a hardware-scene criterion**, not a claim that v4 forcibly closes all
old apps. No service disable/change or legacy-browser kill is smuggled into a keypress.

## 5. Handoff — coordinated owner action, not already wired

Owner install prerequisite, verbatim (not run in this sandbox):

`sudo dnf install -y python3-gobject webkit2gtk4.1`

Use a copy of this committed release's console package; **do not switch the owner's main
checkout or replace the historical worktree payload**. First verify the installer checksum
against the release below. Default invocation only verifies source payloads. The explicit
install invocation writes the fixed helper/bind targets and nothing else; no window is opened,
no service is started, no packages are installed, and the Lua binding remains byte-for-byte.

Check-before-run, verify only, one physical line; mismatch is a hard stop:

`test "$(sha256sum console/install_native_launcher.py)" = '00ce89cba080dabf0a36805e8f81536d82c742ec96541ff8e47457c850f217f3  console/install_native_launcher.py' && /usr/bin/python3 -IB console/install_native_launcher.py`

Explicit same-path installation, after owner coordination, one physical line; mismatch is a hard stop:

`test "$(sha256sum console/install_native_launcher.py)" = '00ce89cba080dabf0a36805e8f81536d82c742ec96541ff8e47457c850f217f3  console/install_native_launcher.py' && /usr/bin/python3 -IB console/install_native_launcher.py --install`

Release SHA256 pins:

- `console/native_launch.py` — `abe107748dc65b1cd6784fe093a348c7d43999273d26cbdec5413518619c2b44`.
- `console/native_window.py` — `e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e`.
- `console/elaria-console-launch.sh` — `8c86ca34bb2aa15fb0f38e40a15e11200def5d3cd046bf3a34aa90e9a47e9da5`.
- `console/install_native_launcher.py` — `00ce89cba080dabf0a36805e8f81536d82c742ec96541ff8e47457c850f217f3`.

**Owner-hardware-only:** native rendering, pairing inside WebKitGTK, cross-origin posture, six native looks, actual ELARIA title/process census, Win+Space at the unchanged line-149 bind, and real reboot self-heal/close–Ctrl-C acceptance after the dnf install, coordinated through design chat.

## 6. Done criteria and source anchors

- Build/packaging/checksum chain: delivered, not installed on the owner machine.
- Same-path replacement without a Lua edit: exercised against synthetic installation targets.
- Local-object missing-worktree and stale-registration recovery: exercised in real temporary
  Git repositories, preserving another missing worktree registration and source branch HEAD.
- Historical pinned bridge, absent→headless then window, present→additional window, no duplicate:
  exercised with actual pinned historical bridge bytes, synthetic Unix IPC and a fake native process.
- Private-file reuse, stale newer-file rejection, no token in process argv/log and both Ctrl-C/
  close orders: local tests, not real GTK evidence. No backend/model/hardware success claim.
- Six native looks/pairing/origin/platform/runtime: Task D's opt-in probe remains skipped here;
  this Debian sandbox still has no GI/WebKitGTK runtime or display server.
- Task F remains a parallel lane, not implemented by this commit; remember/forget cards remain
  held behind the owner's seams word. No daemon/protected/shared-fixture/engine/history_limit
  change; A–D source stays landed; kitty parked and NectarLink out.

Pinned evidence:

- `fcd55ca1bce34d8a1f479bf2d035cc866c4a482f:console/run_bridge.py:37`:
  historical launcher payload checksum gate, retained rather than upgraded in this path.
- `fcd55ca1bce34d8a1f479bf2d035cc866c4a482f:console/run_bridge.py:77`:
  private launch-file producer and permissions; headless operation creates no browser profile.
- `fcd55ca1bce34d8a1f479bf2d035cc866c4a482f:console/run_bridge.py:124`:
  existing bridge lifecycle, headless without --open; no new daemon or model route.
- `670a8d163aaeaaba3e2ad324789cab0f837b2374:console/native_window.py:99`:
  unchanged native import hard stop and no browser fallback.
- `670a8d163aaeaaba3e2ad324789cab0f837b2374:console/native_window.py:117`:
  unchanged fixed-title, ephemeral native view; hardware acceptance remains separate.


## 7. Verification results and remaining holds

- Focused native-v4/native-host/legacy-launcher/wire suite: **242 passed, 3 skipped, 19.38s**.
- First full run: **2640 passed, 9 skipped, 1 failure, 1 teardown error, 122.11s**. The new
  close-window test encountered unexpected `/proc` listener metadata at its post-close
  assertion. That assertion now checks the known bridge PID and live pairing response instead;
  production still refuses ambiguous/unexpected listener metadata. The independent known
  `tests/conftest.py:91` async-generator teardown error also recurred; shared fixture untouched.
- Full rerun on the final implementation: **2641 passed, 9 skipped, 120.25s**. Ruff passed.
- Installer default verify-only run passed; no owner installation performed. Shell syntax,
  complete release pin chain, protected-byte audit and diff whitespace checks passed.

No native runtime/display or real backend was available, so skipped checks remain skipped,
not inferred from fake-window process tests. No native host/D-source edit, engine change,
protected source edit, backend endpoint addition, history_limit change or owner service action.
No new done claim beyond the build and the locally tested criteria listed above.
