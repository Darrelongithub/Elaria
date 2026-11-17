# Native deployment — Task G target, installer-observability follow-up

This **installer release** deploys console commit **25ef8e67aee59598999941ff79ee7765e2480135**.
It cannot itself be obtained from 25ef8e6: that immutable commit contains the older installer.
The accepted G helper payload remains unchanged. The owner-findings follow-up changes only
the installer/readback/emission interface and its manifest pin; use the follow-up release
for the commands below, not the immutable old installer at G. Do not mix source pins. This guide
is not evidence of owner installation or hardware acceptance. Native target remains 25ef8e6
even when later consumer work lands on this branch.

## Owner copy/paste path — manifest first (ask 32)

Use a checkout of this follow-up release, not G or d893719 for the new checker verdicts.
The examples call that checkout `/tmp/elaria-console2`; the already-installed G helper bytes
are unchanged. **The owner has already installed and verified those helpers successfully;
this tooling update is not an instruction to reinstall them or edit the working bind.**

First, verify all four committed files. One physical line, no hash literal, redirect or `&&`:

```sh
(if cd /tmp/elaria-console2; then sha256sum -c console/native-launcher.sha256; else exit 2; fi)
```

Require **four OK lines** before proceeding. If changing directory or verification fails,
STOP: do not run either Python command. This is the guarded form of the owner's successful
`cd /tmp/elaria-console2; sha256sum -c console/native-launcher.sha256` diagnosis: a failed
`cd` must not verify an unrelated working directory. The manual steps intentionally require
observing the check before the next command; they are not an automatic fail-closed transaction. The subshell
returns 2 on a failed directory change and preserves sha256sum status. The Python lines print
the interpreter status; their trailing echo itself returns 0, so automation must use the
status-propagating fallback rather than treating echo success as Python success.

From that verified root, read-only installed check (one physical line):

```sh
/usr/bin/python3 -IB console/install_native_launcher.py --check-installed; echo exit=$?
```

Only when installation is explicitly wanted, then cold-check again afterward:

```sh
/usr/bin/python3 -IB console/install_native_launcher.py --install; echo exit=$?
```

The manifest is committed in the **same selected immutable release tree** as the files. Against
that trusted release identity it is not a weaker pin than copying its literal through chat,
and it checks all four files. Neither a same-tree manifest nor a same-tree wrapper authenticates
an arbitrary maliciously replaced tree; the trusted commit identity remains the anchor.

### Literal-pin fallback, maintained as a file

The inline-literal wrapper is retained as `console/verify-native-installer.sh`, with its literal
inside the committed script, not in an owner-facing chat command. It compares the digest alone,
never sha256sum's two-space hash/filename rendering. Run from the selected release root:

```sh
sh console/verify-native-installer.sh
```

For a single guarded operation (verification failure prevents Python invocation):

```sh
sh console/verify-native-installer.sh --check-installed
```

Explicit installation is also supported with `--install`, followed by the read-only check.
This fallback verifies the installer literal; the installer itself verifies its three payloads
before writing. Use the manifest path above to verify all four independently before execution.
The fallback script is trusted from the selected release, not self-authenticating.

Every readable-source comparison prints **resolved path, actual digest, expected digest**.
Unreadable source prints `actual=UNREADABLE`. STOP reasons distinguish malformed expected
literal, unreadable source, a literal disagreeing with a matching manifest, and other source/pin
disagreement. Agreement with the manifest is a diagnostic clue, not proof that a corrupt literal
rather than a changed release caused the discrepancy. The wrapper prints the Python exit status
and propagates it. Its failure never claims a source-integrity defect solely from a copied
comparison string. Old inline command copies remain historical in the accepted report.

The installer verifies the entire helper bundle first. It writes only the fixed native
helpers and `/home/darrel/.config/hypr/elaria-console-launch.sh`. **The installer does not
create, replace or activate a keybind.** The old handoff assumed the owner-reported line-149
bind already pointed there; that was an assumption, not an observation of the live file. No Chrome/Chromium invocation or fallback exists in that bind path.
No service enablement, daemon, Hyprland configuration, or unrelated browser is changed.

Normal use is the existing Win+Space bind, not a manual bridge start and not `--open`.
Historical headless recovery instructions remain in Appendix A; no long literal shell command
is reissued through chat here.
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

## Historical acceptance checklist — read with owner update below

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

### Installed-state verdicts (ask 33)

Use the short manifest-first commands above. `--check-installed` inspects **all three** targets
independently even if the first directory is absent or invalid. It performs no repair or writes.
Each target reports VERIFIED with its SHA/mode, MISSING with reason, or INVALID with reason.
It checks actual bytes, ownership, single-link regular-file status, mode and safe directories.

| Exit | Verdict | Meaning |
|---|---|---|
| 0 | PASS | All three match; no claim about the active bind. |
| 3 | NOT_INSTALLED | All three absent **now**; missing target directories are a first-class state. |
| 4 | PARTIAL_INSTALL | Some targets verified and others absent. |
| 2 | STOP | At least one invalid/unreadable target, or checker failure; invalid outranks missing. |

The summary carries completed file receipts and missing/invalid counts. Absence does not prove
historically “never installed”; a read-only check observes current state. Partial/invalid states
retain the partial-write warning and no-rollback/fallback boundary. The checker never recommends
running itself as the explanation of its own failure. Installation still returns 0 only after
all readbacks pass; missing files at the final recheck cause install STOP/2, not a successful write.

If the wrapper's earlier invocation never reached the launcher, no launcher log is expected;
when it does reach it, failures go to stderr and the private `/tmp/elaria-launch.log`.
That stderr need not be visible from a compositor keybind. Do not dump pairing files/tokens.

## Owner finding 2 — who owns the bind change

Only if observation finds a wrong target, **the owner** replaces the existing Win+Space /
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

## Historical d893719 validation — TESTED-ONLY (unchanged results)

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

### Historical d893719 hash-copy accounting

The d893719 installer SHA was `5cc53e6a0a84bcb45a300bc9569948db66bb4524b03485f7e151eb040d194010`
(at that revision). The three G helper hashes are unchanged. The accepted historical report
`docs/phase-reports/console-g-h-i-final.md` retains G's old installer SHA
`85d79b9ed977db72ab7791c142a4f41c53cb3036775307935c16ff202701d85c` at lines 64 and 121;
those statements describe G, not this follow-up, and were not silently rewritten.

## Owner evidence update — addenda 4–6 (historical findings annotated)

The statements above about pending evidence and an unfired F37 describe the earlier handoff,
not the current owner state. The owner now reports:

- B1: four manifest checks OK. B2: native bundle directory absent, zero completed receipts;
  the old checker stopped before reporting the wrapper. B2 alone could not prove the wrapper's
  state, nor distinguish never-written files from files later removed.
- C1: three install receipts matched pins/mode 0700. C2: three cold VERIFIED lines and PASS/0.
- D: the correct generated SUPER+SPACE line was already at **hyprland.lua:151**. No SUPER+SPACE
  bind was found in `.conf`. No bind edit was needed; the proposed edit was voided.
- G1: Win+Space opened native GTK ELARIA, owner: **“It worked.”** No reload was needed.
  Accepted operational diagnosis: a correct existing bind lacked its installed wrapper target.
  The exact shell/process failure responsible for the original silent G invocation remains
  unobserved; clipboard whitespace normalization is a hypothesis, not a certified mechanism.
- Owner ruling: both F37 conditions are satisfied, with mainline capture fix **9e49915** and
  owner install/key evidence. Natural reboot recovery is residual, **not a hold**. This records
  the ruling without inventing unprovided HTTP/storage/geometry measurements or taking merge action.

The stale `.conf` is a wrong-file-editing hazard, not the demonstrated cause. Owner compared
its door block with Lua: halt 209↔126, PTT 211↔127, console-open 213↔128. Preserve unique settings
outside the compared block before archiving the whole file; matching those three binds alone
is not an audit of every setting in the 5,965-byte file. No automatic archive is performed.

A cheap live-root clue on this machine: SUPER+ALT_L and SUPER+mouse:274 were observed only in
Lua, whereas F2 and the SHIFT chords occur in both files. Observed operation of a Lua-only
binding supports that Lua configuration having loaded; it is not byte-level proof that the
current on-disk line 151 is active (the compositor may retain an earlier load). Do not trigger
unrelated actions automatically just to test root identity. Ask 34 below distinguishes static
file evidence, loaded binding evidence, and unprovable source-line provenance.

Current installer SHA: `c0a558a7116a38ef0b0abd68ca39f6994c93253f3b15f94ce81cc276ee8185fb`.
It is copied in the four-file manifest and the literal fallback script. G helper hashes remain
unchanged; accepted historical reports and their pins remain intact.

## Read-only bind observation (ask 34)

From this release root, first verify the observer's separate committed manifest (the native
installer manifest deliberately remains four files):

```sh
sha256sum -c console/bind-observer.sha256
```

Require its OK before running the observer. Static scan, no subprocess or config execution:

```sh
/usr/bin/python3 -IB console/observe_native_bind.py
```

Optional live query; only `/usr/bin/hyprctl -j binds`, bounded by a three-second timeout:

```sh
/usr/bin/python3 -IB console/observe_native_bind.py --live
```

A different literal chord can be observed with `--chord 'SUPER + SHIFT + F2'`.
The root and wrapper target are fixed to the owner's known paths; no arbitrary config-root
argument is exposed. No Lua evaluation, source/include execution, edits, installs, reloads,
service calls or keypresses occur. Unrelated command strings/config contents are not printed.

The observation reports:
- Every supported literal match's file and line, whether its exec target is the wrapper, and
  whether the **physical bind line (excluding its line terminator)** exactly matches generated
  text. It emits the generated-line SHA and each inspected config file's SHA.
- The **whole config file has no generated expected pin**. It cannot be called byte-identical
  to a one-line generator. `file_pin=UNAVAILABLE` makes that distinction explicit.
- Multiple same-chord literal matches across recursively scanned `.lua`/`.conf` files, including
  wrong-target candidates. A legacy match is an on-disk observation, not evidence it is loaded.
- Wrapper MISSING, INVALID, UNKNOWN or MATCHES_PIN; wrapper-only readback does not replace the
  three-artifact directory/owner/hash check from `--check-installed`.
- Optional live matching-chord count, target match, release flag and submap, without dumping
  other bindings. An unavailable/malformed/failed query is UNKNOWN, not “no bind”.

**Limits are part of the result:** bounded traversal (128 file/directory budget, 1 MiB per
file), no symlink following, no interpretation of dynamic Lua, aliases, variable-composed
chords or external includes. Read errors/unsupported syntax/limits are reported. The tool can
identify competing literal candidates, but cannot prove no duplicate exists in arbitrary
executable configuration; `duplicate_absence=UNPROVEN` is always explicit. Unrecognized source
forms are not silently treated as absent. Loaded binds can confirm an effective chord/target,
but the binds API does not attest the source file/line or current on-disk bytes: that provenance
remains UNKNOWN. No reload is issued as an experiment to close that gap.

`OBSERVATION exit=0` means the report completed, not that deployment passed; inspect its
match/unknown fields. An absent/unsafe root or fatal observation failure returns UNKNOWN/2.
This supports “correct literal at line 151; wrapper absent” in one run without proposing a
bind edit. No current owner recheck is required merely because this tool was added.

## Asks 32–34 validation — TESTED-ONLY

- Focused installer/absence/manifest-fallback/bind-observer tests: **41 passed in 0.31s**.
- Full suite: **2798 passed, 9 skipped in 155.23s**. F36 trend: accepted report 154.93s →
  d893719 155.01s → this tooling follow-up 155.23s (+0.22s from the last full gate).
- Whole-repository Ruff 0.17.2, native four-file manifest, separate observer manifest and
  whitespace gate pass. No owner config or compositor was used in tests; live queries used
  fake bounded responses. Initial new-test run had 1 failed / 39 passed in 0.34s: a test
  confused the disclosed metadata filename `other.lua` with an unrelated command `/other`;
  the assertion was narrowed to the command string, not the production privacy filter.
- Source paths outside this installer/tooling scope, the visualizer engine, accepted native
  payloads, inventory and protected daemon are unchanged. This does not claim voice-surface
  implementation or audio-delivery acceptance.
