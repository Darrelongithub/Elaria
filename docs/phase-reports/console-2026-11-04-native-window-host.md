# Native window host — Task D implementation, Task E blocked

Owner ruling 2026-11-04; implementation session 2026-11-05. **WS6-interim remains OPEN.**
Estimate before work: D 2–3 hours, E 2–3 hours, separate commits. No estimate expansion;
this delivery stops short of runtime/hardware acceptance and the missing v3 integration.

## Status and scope

**Task D: implementation + local unit tests, NOT WebKitGTK-verified.** A small committed
`console/native_window.py` builds a GTK3 window with fixed OS title **ELARIA**, default client
size 1440×900 (window manager may override), using WebKit2 4.1. No browser lookup, launch,
app mode, external URL opener or fallback. No Quickshell revival, new toolchain or paid service.

**Task E: BLOCKED / not implemented.** The accepted v3 Win+Space/worktree-recovery wrapper
is absent from this checkout and was not supplied. Its exact code, checksum and bound entry
point are needed before preserving its reboot self-heal in v4. Do not substitute a guessed
clone/worktree/reset/install routine, owner path or fresh branch. No keybind/config/service
has been edited. In particular, elaria-console.service remains untouched/enabled as required.
The existing run_bridge.py is unchanged; its old Chrome --open path is rejected by this new
owner ruling, not a v4 candidate. **Do not use that old --open path for acceptance.**

The Fedora package ground below is owner/design-chat verified, not rediscovered here:
Fedora 44 webkit2gtk4.1 2.54.2-1.fc44 supplies WebKit2-4.1.typelib, GTK3 + libsoup3;
python3-gobject supplies GI and gtk3 supplies its typelib. This sandbox is Debian 12, has no
GI/WebKitGTK or Xvfb, and cannot run the native window. No system package was installed here.

## Install line and checksum boundary

Owner-supplied install line (not run here):

`sudo dnf install -y python3-gobject webkit2gtk4.1`

Use `/usr/bin/python3`, which can see the RPM-provided GI loader; do not assume the bridge's
isolated venv can import system GI. The bridge retains its existing websockets environment.
Missing GI, GTK3 or WebKit2 4.1 yields exit 2 and this single line, with no fallback:

`STOP: native GI/WebKit unavailable; sudo dnf install -y python3-gobject webkit2gtk4.1`

Native host SHA256: **`e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e`**.
`console/native-window.sha256` records the same pin; tests verify it. The manifest must come
from the trusted commit, not an untrusted replacement. No runtime auto-repair or self-update.

Check-before-run, imports only, one physical line:

`test "$(sha256sum console/native_window.py)" = 'e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e  console/native_window.py' && /usr/bin/python3 -IB console/native_window.py --check`

For an already running, approved headless bridge only, `ELARIA_LAUNCH_FILE` must be the exact
private-file path from that live bridge's “Private launch file:” line, **never its contents or
URL**. Missing variable/checksum mismatch stops. This is a manual host entry, **not v4 or the
Win+Space handoff**, and is not asserted to have run on hardware:

`test -n "${ELARIA_LAUNCH_FILE:-}" && test "$(sha256sum console/native_window.py)" = 'e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e  console/native_window.py' && /usr/bin/python3 -IB console/native_window.py --launch-file "$ELARIA_LAUNCH_FILE"`

## Privacy and lifecycle contract implemented in the host

- The only pairing-related argv value is a private **file path**. Read-only FD-relative
  traversal rejects symlinks in every component, traversal, wrong owner, non-0700 immediate
  parent, non-0600 file, hardlinks, FIFO/device/directory and oversized data (4096-byte bound).
  No writes, chmod, link copying or discovery of neighbouring launch files.
- Parse the known refresh/anchor destination as data; require exactly one matching pair and
  an exact loopback HTTP URL with valid port and 43-character pairing fragment. Never execute
  the launch HTML. No remote host, query, userinfo, file URI or extra fragment accepted.
- URL is used in memory via WebView.load_uri. It is not passed to a subprocess, persisted,
  printed or installed as window title/metadata. No page-title binding. No host history,
  credentials, preferences, cookies or persistent profile are restored. Per-window WebKit
  context/view are explicitly ephemeral, checked, with DOM local storage disabled too.
- This deliberately means shell display-cache/session receipts do not survive native-window
  closure. A–C source/rendering and the daemon's shared conversation/facts are unchanged;
  ephemeral display is **not erasure of daemon history or provider copies**.
- Core dumps are disabled for the host; URI-bearing runtime stdout/stderr are silenced before
  loading a pairing URL. Only bounded preflight messages are printed. WebKit/JSC diagnostic
  override environment is refused. This does not claim protection from the owner, root, OS
  swap, tracing or a compromised engine; it is not an OS sandbox certificate.
- WebKit process sandbox and web security stay enabled. No file/universal access allowances,
  developer extras or console-to-stdout. File chooser, downloads, permission requests,
  new windows, external navigation, context-menu and print actions are denied.
- Only this launch's root/paired document are allowed as navigations. Unknown/malformed policy
  decisions fail closed. Native load/process errors replace the view with a generic message,
  never WebKit's default URI-bearing error page.
- Destroying the GTK window quits **only its own GTK loop**. The host has no daemon/bridge PID,
  kill, service-control or shutdown operation. WS4 detached launcher process-group behavior
  still belongs to E; no new process-lifecycle acceptance is claimed from these unit tests.

## WebKitGTK versus Chrome: known design differences, unverified runtime differences

| Topic | Implemented native choice | Verification state |
| --- | --- | --- |
| Entry | Read private launch file in Python; direct in-memory HTTP load with fragment | Parser/policy unit-tested; actual WebKit fragment bootstrap **NOT RUN** |
| Origin | Real loopback HTTP origin, not a file:// page or injected HTML with null origin | No bridge Origin, Host, CSP, protected /console or /elaria gate weakened |
| File navigation | Chrome's historical file→HTTP redirect is no longer used by the native host | No new Sec-Fetch exception requested; WebKit's actual headers **UNVERIFIED** |
| Pairing/§5 wire | Existing bridge-client.js/iframe and WebSocket protocol, not a second client implementation | Existing socket tests pass; WebKitGTK handshake/text turn **NOT RUN** |
| Privacy | Ephemeral WebContext/view + local storage disabled, no disk profile | API/source + stubs checked, not an installed-package storage trace |
| GPU/layout | Existing absolute-pinned engine, WebKit default WebGL behavior | No force-software workaround; all six native looks **NOT RUN** |
| Failure | Hard stop, generic display/import diagnostics, never launch Chrome | Missing-GI failure exercised locally |

**No observed claim that “WebKitGTK required X that Chrome did not” can yet be made.**
The native implementation intentionally changes entry and storage above; actual compatibility
requirements remain an acceptance gap. If real WebKitGTK requires a gate relaxation, stop
for review rather than disabling security or silently changing origin/transport.

## Optional real-runtime gate, not executed here

`console/native-webkit-test.py` is a test-only GI helper invoked by the opt-in pytest case in
`tests/test_console_native_window.py`. It uses a synthetic loopback bridge, never the owner's
daemon/model. It runs the real host, fragment bootstrap, accepted §5 WebSocket and one synthetic
text turn with attribution; a separate ephemeral foreign-origin document tests that WebKit
HTTP and WebSocket attempts are denied by the unchanged bridge gates. It checks six client
sizes: 1920×1080, 1440×900, 1024×768, 800×600, 390×844, 320×480. A real display is required;
window-manager size clamping is a test failure, not permission to claim the requested look.

The probe checks renderer canvas at the accepted wide sizes, chat priority, outer overflow,
footer position/copy, input and lamps, and the wide 36%/80% relationships. It is geometry and
transport evidence, not the owner's visual/monitor/zoom acceptance. Narrow transcript scrolling
is not forbidden by an outer-window no-scrollbar check. It emits booleans/geometry only and
captures no owner content. Select an absolute GI-capable interpreter with
`ELARIA_WEBKIT_TEST_PYTHON` only for that synthetic test; no automatic package/browser download.

Remaining acceptance: actual WebKit API/runtime/storage behavior; fragment/§5/origin probe;
six owner-observed native looks; exact title/process census without Chrome/Chromium; the
accepted v3→v4 bind and detached lifecycle; live-file reuse; reboot/worktree self-heal. Closing
a window must not kill its bridge, and Ctrl-C to a bridge must not kill any detached windows.
A second keypress must open a fresh native view of the current launch, not a stale token.

## Source anchors and scope audit

- `52a8ce1dc6c155047a1153ad9d1a3a2221404fbe:console/run_bridge.py:77`:
  current private launch-file producer; not a v4 bind/reboot implementation.
- `52a8ce1dc6c155047a1153ad9d1a3a2221404fbe:console/bridge.py:400`:
  unchanged pairing/Origin/Host gates to preserve, not bypass in WebKit.
- `52a8ce1dc6c155047a1153ad9d1a3a2221404fbe:console/bridge-client.js:9`:
  current fragment pairing bootstrap and exact existing shell adapter.
- Upstream **WebKit/WebKit**, `e8fb2ea5c8336081c16e4029d830af6a069bc70b:Source/WebKit/UIProcess/API/glib/WebKitWebContext.cpp:796`:
  ephemeral context contract. Upstream source, **not Fedora binary evidence**.
- Same upstream SHA, `e8fb2ea5c8336081c16e4029d830af6a069bc70b:Source/WebKit/UIProcess/API/gtk/WebKitWebViewGtk.cpp:349`:
  new_with_context API; this is not proof the installed typelib resolves on owner hardware.

All 309 accepted baseline entries were byte-checked before restoring refreshed Git metadata
to the accepted 52a8ce1 tip. No protected/daemon/shared-fixture/engine change, no history_limit
change, no A–C code change, no service/keybind/install/worktree action, no PR, kitty parked,
NectarLink out. Native source is new; the only existing-file edit is a warning on BRIDGE.md
that historical Chrome --open instructions are not the new handoff.


## Verification and next input

Local native-host unit gates: **29 passed, 1 skipped** (real WebKitGTK opt-in).
Focused native/launcher/wire run: **219 passed, 3 skipped, 17.30s**.
Full suite on the final implementation: **2618 passed, 9 skipped, 113.13s**; Ruff passed.
The explicit system-Python import check returned exit 2 with exactly the one-line dnf hint;
no GI runtime, display, owner model, native window or Chrome process was launched for it.
The optional real-runtime probe was written and syntax/lint checked, **not executed**.

**STOP / requested input for E:** supply the accepted v3 wrapper (file/committed path and SHA)
and its actual Win+Space binding entry point. Preserve its verified recovery logic rather
than inventing it. Real WebKitGTK/display validation and owner acceptance remain separate
holds; no claim of a native-ready release, reboot self-heal, or successful native keybind.
