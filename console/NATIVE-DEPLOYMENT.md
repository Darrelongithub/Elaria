# Native deployment — Task G target, installer-observability follow-up

This **installer release** deploys console commit **25ef8e67aee59598999941ff79ee7765e2480135**.
It cannot itself be obtained from 25ef8e6: that immutable commit contains the older installer.
The accepted G helper payload remains unchanged. The owner-findings follow-up changes only
the installer/readback/emission interface and its manifest pin; use the follow-up release
for the commands below, not the immutable old installer at G. Do not mix source pins. This guide
is not evidence of owner installation or hardware acceptance. Native target remains 25ef8e6
even when later consumer work lands on this branch.

From the follow-up release root, checksum-first, one physical line (explicit owner install).
The shell announces checksum failure and prints the process exit status even if Python itself
produces no output. The subshell does not exit the owner's interactive shell:

`( if test "$(sha256sum console/install_native_launcher.py)" = '5cc53e6a0a84bcb45a300bc9569948db66bb4524b03485f7e151eb040d194010  console/install_native_launcher.py'; then /usr/bin/python3 -IB console/install_native_launcher.py --install; rc=$?; printf "installer process exit=%s\n" "$rc"; exit "$rc"; else printf "%s\n" "STOP exit=2: installer source checksum mismatch or unreadable file" >&2; exit 2; fi )`

The installer verifies the entire helper bundle first. It writes only the fixed native
helpers and `/home/darrel/.config/hypr/elaria-console-launch.sh`. **The installer does not
create, replace or activate a keybind.** The old handoff assumed the owner-reported line-149
bind already pointed there; that was an assumption, not an observation of the live file. No Chrome/Chromium invocation or fallback exists in that bind path.
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

## Owner finding 1 — no output is not an installation receipt

At accepted G (`1b7c132`), `--install` verifies the source pins and target ownership, then
atomically replaces these three files in order, with mode 0700:

1. `/home/darrel/.config/elaria-console-native-v4/native_launch.py` — SHA256 `1f575357774f3eade4fdf7cdc69ee36f2f3998ff94c61f77ab84f28bcbf56bb8`
2. `/home/darrel/.config/elaria-console-native-v4/native_window.py` — SHA256 `e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e`
3. `/home/darrel/.config/hypr/elaria-console-launch.sh` — SHA256 `1a7a54a763039d296111c6ebd843b2f9f79f6152d595ae71fb4ea18293fb0413`

The original G success output is exactly:
`Installed native v4 bind target and private helpers; no config edit or window launch.`
It returns 0. A caught exception prints this to stderr:
`STOP: native install verification/ownership failed; no fallback or auto-repair.`
It returns 2. There is **no internal-only installer log, existing-target skip, or normal silent
path**. Existing targets are replaced, not silently treated as installed. G did not print
individual file receipts or the specific exception; a late failure could leave partial writes.

Taking the owner's passed checksum as reported, zero stdout AND stderr is **not an expected
result of that script reaching its success or caught-error path**. It does not prove no writes
or successful writes. Whether Python was actually invoked/completed, output was redirected or
lost, or the process was externally interrupted remains unknown; a clean prompt is not an exit
code. Do not choose among those explanations without evidence. `-IB` does not request silence.
The two native components can suppress runtime output, but the installer never imports or
executes them. Their output suppression cannot explain a completed installer call's silence.

The follow-up prints flushed START, one `WRITTEN path=… sha256=… mode=0700` line after each
actual installed-file readback, then `PASS exit=0` after all three are checked again and
parent directories fsynced. A stop prints reason/exception, `exit=2`, count of completed
receipts, and an explicit partial-write warning. No rollback is pretended. Per-file receipts
are not a whole-install success; require the final PASS and the shell process status.

Read-only installed-state check, from the **new follow-up release root** (not G's old flags):

`( if test "$(sha256sum console/install_native_launcher.py)" = '5cc53e6a0a84bcb45a300bc9569948db66bb4524b03485f7e151eb040d194010  console/install_native_launcher.py'; then /usr/bin/python3 -IB console/install_native_launcher.py --check-installed; rc=$?; printf "installer process exit=%s\n" "$rc"; exit "$rc"; else printf "%s\n" "STOP exit=2: installer source checksum mismatch or unreadable file" >&2; exit 2; fi )`

It verifies actual installed bytes, ownership, single-link regular-file status and mode—not
merely existence or source hashes. It creates/replaces nothing, prints three VERIFIED lines
plus PASS/exit=0, or STOP/reason/exit=2. No hand-inspection is required to determine whether the
three installed artifacts match. It does not establish which bind the running compositor uses.
If the wrapper's earlier invocation never reached the launcher, no launcher log is expected;
when it does reach it, failures go to stderr and the private `/tmp/elaria-launch.log`.
That stderr need not be visible from a compositor keybind. Do not dump pairing files/tokens.

## Owner finding 2 — who owns the bind change

For the reported Lua-only Hyprland 0.57 session, **the owner** replaces the existing Win+Space /
SUPER+SPACE binding in `/home/darrel/.config/hypr/hyprland.lua` with the following generated
one-physical-line Lua expression. Paste it into that Lua config, **not a shell**; do not append
a competing duplicate binding. Line 149 was the earlier reported location, not a guaranteed
line number on the current machine. If the session explicitly loads another Lua root, confirm
that live root before editing; neither file existence nor a doctor snippet proves activation.

`hl.bind("SUPER + SPACE", hl.dsp.exec_cmd("/home/darrel/.config/hypr/elaria-console-launch.sh"))`

This line is emitted by the new installer's `--emit-bind` option and pinned byte-for-byte
against this document in tests. The generator writes no config and performs no reload.
Correction to the relay premise: G's installer **did not emit a bind at all**; it only installed
the wrapper/helpers. At the inspected immutable doctor revision
`678586027e613c592a1648ac3ec09d28ad6c02d5`, `hypr_binds.py` uses this `hl.bind` /
`hl.dsp.exec_cmd` syntax, but its emitted set is PTT press/release, Escape cancel and panic,
not this console binding. Doctor reports/emits; it does not apply the console change.
No doctor, CLI or protected config source was changed in this follow-up.

After an actual Lua bind edit, the owner reloads the running compositor with `hyprctl reload`
and checks its result/config errors before another Win+Space test. The installer does not
reload. **Replacing only the wrapper at an already-active same-path bind does not require a
Hyprland reload.** A stale loaded bind matters if its config was changed without a reload;
a reload cannot repair a missing wrapper or an edit made in the wrong file.

### Stale hyprland.conf duplicate

**This is the deployment: retire a confirmed obsolete duplicate as part of this fix, not at
some later unspecified deployment.** First preserve the read-only diagnosis already requested
and account for any unique settings in the duplicate. Once the live Lua configuration is
confirmed and required content is represented there, archive the obsolete `.conf` rather than
blindly delete it. No automatic rename/delete/config rewrite is performed or issued here while
the owner's diagnostic output is pending.

On the stated Lua-only 0.57, legacy `bind = …` text in `hyprland.conf` cannot become a working
bind merely because the duplicate exists. The duplicate is a plausible **wrong-file editing /
misleading evidence** cause, not proof that 0.57 secretly selected legacy syntax. The pending
doctor/live-config results, not guesswork, distinguish that from an older/different session.

No cause of the dead key is certified yet. G/H/I and d624ddf remain accepted. Actual GTK/F-card,
no-new-Chrome, HTTP, geometry and reboot evidence waits until the keybind works, so the F37
trigger remains unfired as a sequence fact. No merge/rebase action, window-orchestration retry,
service-disable change or H/I deployment repin is part of these two findings.

## Follow-up validation — TESTED-ONLY

- New installer tests: **11 passed in 0.18s**; synthetic destinations only. They cover repeat
  replacement, per-file installed-byte receipts, read-only checks, missing/drifted/mode-invalid/
  symlink/hardlink targets, partial writes, readback failure, generated Lua/doc agreement and
  process output/exit codes. No owner config is edited.
- Focused installer/native recheck: **41 passed in 1.75s**.
- Full-suite recheck: **2768 passed, 9 skipped in 155.01s**. F36 walltime trend: accepted G
  133.40s → H 141.66s → I 155.62s → accepted report recheck 154.93s → this follow-up 155.01s
  (+0.08s from that report recheck; environmental, not a performance guarantee).
- Retained failures: initial focused run **1 failed, 40 passed in 1.76s**; initial full run
  **1 failed, 2767 passed, 9 skipped in 162.96s**. Both failed in the pre-existing fake-host
  `[window]` test at the unexpected-listener guard. For the focused failure, `/proc/net/tcp`
  confirmed port 45823 had UID 1001 loopback and UID 0 non-loopback listeners; only the exact
  failed-fixture bridge child was stopped after UID/cwd/argv verification. The full-run failure
  used port 58881; by the metadata recheck neither listener remained, so its cause is not
  certified and no process was killed for that fixture. Production listener guards and native
  tests/payloads were not changed. These sandbox failures do not diagnose the owner's keybind.
- Ruff **0.17.2**, whole-repository check: pass. Manifest: all four hashes pass. Diff whitespace:
  pass. These results do not substitute for the pending owner diagnosis/GTK evidence.

### Hash-copy accounting

The active installer SHA is `5cc53e6a0a84bcb45a300bc9569948db66bb4524b03485f7e151eb040d194010`
(copied in the checksum-first lines above and `console/native-launcher.sha256`). The three G helper hashes are unchanged. The accepted historical report
`docs/phase-reports/console-g-h-i-final.md` retains G's old installer SHA
`85d79b9ed977db72ab7791c142a4f41c53cb3036775307935c16ff202701d85c` at lines 64 and 121;
those statements describe G, not this follow-up, and were not silently rewritten.
