# Native deployment — Task G

This **installer release** deploys console commit **25ef8e67aee59598999941ff79ee7765e2480135**.
It cannot itself be obtained from 25ef8e6: that immutable commit contains the older installer.
Use the separately issued G commit for these helper files; do not mix releases. This guide
is not evidence of owner installation or hardware acceptance. Native target remains 25ef8e6
even when later consumer work lands on this branch.

From the G release root, checksum-first, one physical line (explicit owner install):

`test "$(sha256sum console/install_native_launcher.py)" = '85d79b9ed977db72ab7791c142a4f41c53cb3036775307935c16ff202701d85c  console/install_native_launcher.py' && /usr/bin/python3 -IB console/install_native_launcher.py --install`

The installer verifies the entire helper bundle first. It writes only the fixed native
helpers and `/home/darrel/.config/hypr/elaria-console-launch.sh`. The owner-reported line-149
bind stays unchanged. No Chrome/Chromium invocation or fallback exists in that bind path.
No service enablement, daemon, Hyprland configuration, or unrelated browser is changed.

For an explicitly manual **headless** bridge start from the verified 25ef8e6 worktree root
(not the later branch payload), the updated launch line is:

`test "$(sha256sum console/run_bridge.py)" = '594bde664e62da42f391bf83b09a4b1ae913387d1ee27031f0e1376dace71791  console/run_bridge.py' && /home/darrel/Elaria/.venv/bin/python -IB console/run_bridge.py`

Normal use is the existing Win+Space bind, not this manual command and not `--open`.
The coordinator starts the bridge headless when absent, then opens GTK ELARIA with WebKitGTK.
**The first press can be slow while the bridge boots; this is expected, not a broken bind.**
The private 0600 launch file is parsed into memory; WebKit loads its loopback **HTTP** URL
directly, never `file://`. Tokens are not passed in argv or printed. Native host uses
an ephemeral context, disabled local storage and normal web security. New F25 probes check
fragment pairing, HTTP origin, blocked local storage, token-free session/cookie storage,
fresh-context cookie isolation and cross-origin rejection; execution requires real WebKitGTK.

## Exact migration and hard stops

The new coordinator verifies 25ef8e6 exists locally, with no fetch. A missing /tmp worktree
is reconstructed at that exact pin, including the stale missing-registration reboot case.
An existing tree advances **only** from the historical fcd55ca1bce34d8a1f479bf2d035cc866c4a482f,
with its ed227a7d50effb874e303f95462f3dc127c9bd79a71a8d9b34f86980815b091c launcher intact,
a clean tree including untracked files, detached HEAD, and no port listener. Any mismatch
stops. No reset, broad prune, main-checkout change, fetch or service kill occurs.

If the old bridge still runs, stop **only that bridge** with Ctrl-C in its own terminal,
then press Win+Space again. Unknown listener ownership is a STOP, not permission to kill.
A live token alone is insufficient: the served shell must match the 25ef8e6 index checksum.
Window and bridge remain independently detached. The enabled elaria-console.service hold stands.

Missing native prerequisites produce exactly:
`sudo dnf install -y python3-gobject webkit2gtk4.1`
This is an owner prerequisite, not an agent-run install. Missing Git objects/interpreter,
present promisor/filter key names, dirty/wrong worktree or checksum mismatch are hard stops.
Git 2.39.5 retains the name-only absence-of-promisor check plus protocol.allow=never.

## Acceptance still required

Actual Win+Space → GTK ELARIA showing the F undo-review card at 25ef8e6, no newly launched
Chrome/Chromium process, direct HTTP pairing, WebKit storage/origin checks, native geometry
and reboot recovery need owner evidence. Local fake-host/IPC tests are TESTED-ONLY.
Do not call this deployed or HW-PROVEN until that evidence exists. Window orchestration is
not part of this procedure. Historical Appendix A and its old hashes remain unchanged in
`docs/phase-reports/console-2026-11-05-native-launcher-v4.md`.
