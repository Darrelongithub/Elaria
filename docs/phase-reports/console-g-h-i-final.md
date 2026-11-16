# Final report — G deployment, H mouth, I headless hands

**Local builds finished; owner deployment/hardware and the F37 merge gate are not claimed.**
This is the single combined final report. Estimates were issued before work: G 90–150 minutes,
H 60–90 minutes, I 4–6 hours. The consent-authority and inventory STOPs were honoured, then
resolved by the owner's complete §1c/§1d/§1e/§1g text and explicit inventory correction.

## Commits / release boundary

| Task | Separate implementation commit |
| --- | --- |
| G — native deployment helper targeting 25ef8e6 | `1b7c1329439b2aa19870db423c0f7eb0a5b8be58` |
| H — sole playback owner and real producer receipts | `4b6acf047cca1fc207b2decafc3025f1908c31a9` |
| I — dedicated instance, exact-argv consent, observations/sidebar | `a7801fae9ee5e0d36af66f42ccc061848ba854c1` |

All three were pushed only to **arena/b65d5161-elaria**. No PR, merge or force-push.
G/H were accepted by owner relay after verification against origin. I is TESTED-ONLY.

**Do not collapse the release split:** the installer release is G (also byte-identical in H/I),
but the console it deploys is **25ef8e67aee59598999941ff79ee7765e2480135**. That immutable
commit contains the F undo card but the *old installer*. Use G's installer to deploy 25ef8e6;
do not run the old installer from 25ef8e6 and expect it to acquire G's pin. H/I are later
consumer builds, **not silently installed by G**. Their backend integration/hardware scene
remains a separate gate. Builds, source-method tests and wire fixtures are not owner wiring.

## DONE table

| Task / criterion | Status | Evidence / limit |
| --- | --- | --- |
| G exact fcd55ca → 25ef8e6 target | DONE / build | Clean detached historical tree only; target local object and payload hashes required; dirty/wrong/live tree stops |
| G same Win+Space wrapper path | DONE / build | `/home/darrel/.config/hypr/elaria-console-launch.sh`; no line-149 Lua edit or reload |
| G native-only bind | DONE / local | No Chrome/Chromium invocation or fallback; no unrelated browser killed |
| G checksum-first installer and updated launch line | ISSUED below | Installer hash is inside the executable line; installer verifies its entire helper bundle |
| G historical Appendix A and reboot recovery | DONE / local | Historical pins retained; missing /tmp worktree reconstructed at new target from local objects; no fetch/reset/broad prune |
| G old live process cannot masquerade as new shell | DONE / local | Valid token plus served-index hash required; old live bridge blocks migration |
| G slow first press explained | DONE | Expected headless bridge boot, explicitly logged/documented |
| G F25 HTTP/fragment/storage/cookies probe | BUILT, runtime UNVERIFIED | Host loads direct loopback HTTP, never file://; WebKitGTK probe remains honestly skipped here |
| G actual owner installer, Win+Space GTK ELARIA/F card and process census | OWNER-HARDWARE-PENDING | No owner machine access or installer run occurred in this sandbox |
| H F29 explicit audio drop | DONE / client-side | Bridge, wire adapter and direct renderer discard reply audio; no client Audio/play/attachElement path |
| H speaking only from levels | DONE / client-side | Reply/state/audio alone cannot enter speaking; synthetic cadence remains labelled; no measured/speech claim |
| H audio pane | DEFERRED | Existing sample/metadata renderer is not a production manifest feed or player |
| H causal IDs and remember/forget receipts | DONE / consumer | Uses landed 4218ef0 producer metadata, not obsolete blanket gaps or inferred history-tail IDs |
| I F37 daemon mount | DONE / bounded | Exactly eight additive lines, zero deletions; all consent/routing machinery in unprotected hands module |
| I dedicated Kitty only | DONE / implementation + fixtures | Daemon-started process, private socket/workspace, PID-bound encrypted connections, fixed non-shell child; no daily-terminal attach |
| I strict parsed argv contract | DONE / bounded | Exact sha256:argv pattern; canonical executable; unsupported syntax/effect families refused |
| I both consent populations | DONE / local | Owner-curated ruling entries and default-off prompt-seeded always; both revocable by named path; allow-once ephemeral |
| I hash/TOCTOU/chain gates | DONE / local | Binary and inventory hashes, cwd/operands, all top-level segments; no interpreter allowlist; worker checks each boundary |
| I missing prompt / No / expiry / replay | DONE / local | Fallback deny, terminal consumption, reasoned journal entries; no retry on unknown outcome |
| I marker readback / truthful observation | DONE / local | Missing marker yields unknown even when the directory exists; ACK is never success |
| I intent → argv → consent → execute → observe | DONE / bounded demo | Actual temporary mkdir/rmdir effects, recording RC transport; ACTION/OBSERVATION correlation and refusal tested |
| I F21/F34 sidebar | DONE / DOM + wire | Silent private cards; denial/action/observation summaries and general reply attribution only in sessions sidebar |
| I actual Kitty/Fedora/owner reversible demo | OWNER-HARDWARE-PENDING | Real Kitty/display was not invoked; installed-package, Python 3.14 and hardware reconciliation are not claimed |
| I window orchestration | PARKED / UNRETRIED | No focus/layout/input-injection/Hyprland experiment; existing fault remains pinned |
| F37 rebase and disjoint merge-region check | DECLARED / MERGE HOLD | Must happen against the then-current mainline tip before any merge; no merge happened here |
| Full suite / locked Ruff / protected bytes | DONE / local | 2757 passed, 9 skipped; Ruff 0.17.2; engine unchanged; only quoted daemon exception |

## Owner lines — checksum first, one physical line each

### G installer: explicit fixed-path owner install

From a verified G release root (commit **1b7c1329439b2aa19870db423c0f7eb0a5b8be58**), or a
verified later release carrying the identical native bundle, this is the issued install line:

`test "$(sha256sum console/install_native_launcher.py)" = '85d79b9ed977db72ab7791c142a4f41c53cb3036775307935c16ff202701d85c  console/install_native_launcher.py' && /usr/bin/python3 -IB console/install_native_launcher.py --install`

**Not run here.** It writes the fixed wrapper and two private helpers only. No Hyprland
configuration, main checkout, service enablement, daemon, model key or unrelated browser is
changed. `elaria-console.service` remains under the enabled-state hold. This does not certify
an unseen rewritten command. Mismatch, missing source/interpreter/object, unsafe permissions
or promisor/filter configuration is a hard stop, not permission to repair/fetch implicitly.

### Updated bridge launch line for the authorised 25ef8e6 payload

From the verified **25ef8e6** worktree root, for an explicitly manual **headless** start:

`test "$(sha256sum console/run_bridge.py)" = '594bde664e62da42f391bf83b09a4b1ae913387d1ee27031f0e1376dace71791  console/run_bridge.py' && /home/darrel/Elaria/.venv/bin/python -IB console/run_bridge.py`

Normal owner use is the unchanged Win+Space bind, not `--open`. Native coordinator reads the
0600 launch file into memory and loads the loopback HTTP URL directly. Token is not passed
in argv, stdout or window metadata. The first press may be slow while the bridge boots;
**expected, not a broken bind**. If the old bridge is running, stop only that bridge with
Ctrl-C in its own terminal, then press again. Unknown listeners are not killed.

F25 runtime prerequisite message remains exactly:
`sudo dnf install -y python3-gobject webkit2gtk4.1`
No system package install was attempted. This sandbox's system Python reports GI/WebKit
unavailable. The new probe checks actual HTTP origin and fragment pairing, disabled local
storage, token-free session/cookie storage, fresh ephemeral-context cookie isolation and
cross-origin refusal. Probe code is not a passing WebKitGTK run. Actual GTK window/title,
F-card interaction, geometry, reboot and Chrome/Chromium process census remain owner evidence.

## Hash-copy inventory — for design's atomic reference update

Repository-wide search at I's commit found these retained old launch-hash references.
Historical reports must not have their evidence silently rewritten. Update active deployment
references together; annotate historical reports when necessary. This report deliberately
contains both old and new hashes as an audit trail, not another ambiguous launch instruction.

| File / lines at I commit | Copy / treatment |
| --- | --- |
| `console/BRIDGE.md:36,42,55,61,86` | Active branch commands now carry I's `eb580bac…`; the former H `b1f7a632…` copies were all replaced. Commands are headless; historical Chrome prose is not the bind handoff |
| `console/BRIDGE.md:274` | Abbreviated `594bde66…` deployment target and historical `ed227a7d` retained and explicitly labelled |
| `console/NATIVE-DEPLOYMENT.md:21` | Full `594bde66…` is the **current G deployment target**, not a stale I build pin |
| `console/NATIVE-DEPLOYMENT.md:37` | Full `ed227a7d…` is the verified historical migration source, intentionally retained |
| `docs/phase-reports/console-2026-11-04-exposure-consent-matrix.md:227` | Historical full `ed227a7d…` |
| `docs/phase-reports/console-2026-11-04-launcher-handoff.md:36` | Historical full `ed227a7d…` handoff pin |
| `docs/phase-reports/console-2026-11-05-native-launcher-v4.md:18` | Historical full `ed227a7d…`; Appendix A preserved |
| Same native-v4 report `:152,156,163` | Historical installer `00ce89cb…`, including its old executable lines; superseded by the G install line above |
| Same native-v4 report `:160,162` | Historical coordinator `abe10774…` and shim `8c86ca34…`; retained evidence, not current helper pins |
| `docs/phase-reports/console-2026-11-06-e-f-final.md:18,33,160` | Historical abbreviated `ed227a7d` deployment split |
| Same E/F final report `:155` | Full `594bde66…` F payload pin; still correct for G's target |

No matching copies were found in protected `HANDOFF.md` or `docs/hands-handoff.md`.
This inventory covers the repository, not unknown external chat/Drive copies; no external
atomic update is claimed. Runtime historical constants remain intentionally in
`console/native_launch.py:24-25` and their tests. Current native bundle is:

- native_launch.py: `1f575357774f3eade4fdf7cdc69ee36f2f3998ff94c61f77ab84f28bcbf56bb8`
- native_window.py: `e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e`
- shim: `1a7a54a763039d296111c6ebd843b2f9f79f6152d595ae71fb4ea18293fb0413`
- installer: `85d79b9ed977db72ab7791c142a4f41c53cb3036775307935c16ff202701d85c`

I's separate current-build launcher is **eb580bace404f5774b2a675a11e7d3e1bb0a16fc47036ddbba878a8ae40b70ad**;
bridge **95e9ce88ba01829c6a9bdc19ae89dd36c0ad10b7706c3c5a60cc0471e0797b5d**;
index **8d4ed20c656f3b60d4c63f41293377509ded0ae5faa46bb9c72c5e747967077c**.
Those are not substituted into G's immutable target without another deployment ruling.

## Inventory correction — verbatim owner ruling

> the foundation report's a8d9… hash matches no committed artifact, and design chat's earlier ruling that the 7e0f01ff gate was stale is HEREBY CORRECTED — the gate matched reality and the report's hash was the fiction.

The verified bytes remain **514,801 bytes**, SHA256
**7e0f01ff2396c292f05528261d349142f1c6e08eed948847ee1300633a1aafcd**.
Design chat's independent origin verification at 25ef8e6 and the builder's local immutable
object/working-file reads agree. The foundation report's defective original value was
**annotated, not overwritten** (`a7801fa:docs/phase-reports/kitty-2026-11-02-foundation.md:76`).
The new policy gate, immutable ask, standing entries and worker checks bind the verified pin.
Future inventory revisions fail closed until explicit re-pin and re-approval. Ground-truth
and drift tests: `a7801fa:tests/test_kitty_inventory_pin.py:11,19,33`.

## I's bounded contract, attribution and demonstrations

Full technical contract: `docs/hands-headless.md`. `headless-exact-argv-v1` accepts only
canonical parsed argv arrays for two assessed empty-directory primitives in the minted
instance workspace. argPattern is `sha256:` of canonical argv JSON, not a shell regex/glob.
Unsupported interpreters, scripts, quoting, substitutions, pipelines, destructive commands
and unassessed families are recorded refusals. This is **not** a universal terminal safety
classifier or a claim that all Kitty verbs are now implemented.

| Family | Assessor / reason / verdict | Test/reference at a7801fa |
| --- | --- | --- |
| Empty-directory create | intent-effect-v1 + concrete-argv-v1; absent target/private cwd; T2/ask or exact standing consent | `tests/test_hands_headless.py:29,186`; `src/assistant/hands/headless/contract.py:105,129` |
| Empty-directory reversal | same independent checks; only this instance's observed empty target; T2/ask | `tests/test_hands_headless.py:29,186`; `src/assistant/hands/headless/instance.py:134` |
| Chains | all independent segments validated and consent-covered before any execute; dependent/unsupported segments refuse | `tests/test_hands_headless.py:47,53,349,354` |
| Interpreters/scripts/unknown/irreversible intent | unsupported effect/alias; deny, no execution or Yes override | `tests/test_hands_headless.py:116,225,363`; `src/assistant/hands/headless/contract.py:78` |
| Binary/inventory/cwd/operand drift | fail closed, visible reason; standing permission is not auto-migrated | `tests/test_hands_headless.py:84,102,338,370` |
| Kitty identity and observation | dedicated child/socket/window only; nonce plus independent target readback; absent marker → unknown | `tests/test_hands_headless.py:236,275`; `tests/test_hands_dedicated_start.py:16,61,78` |

Four local demonstration beats, all **TESTED-ONLY**, not an owner scene:

1. Explicit session open uses a recording dedicated-instance fixture; no daily-terminal attach.
2. Typed `hands mkdir proof` prepares an immutable card. Before Yes: zero executions. One exact
   allow-once leads to an actual `/usr/bin/mkdir` in a temporary private workspace, with ACTION
   followed by correlated OBSERVATION, exit code, stdout digest and resulting state hash.
3. `hands rmdir proof` receives its own approval and removes only that observed empty directory.
   In a separate fault test the directory exists but its marker is deliberately hidden: outcome
   is **unknown**, not success, and the instance faults without retry.
4. `hands rm -rf /` is refused before execution; DENIAL carries its reason into the sessions
   sidebar. No model answer, raw output, spoken consent prompt or centre-chat denial is fabricated.

Real daemon/IPC and real console-wire tests exercise the mounted route with the recording
instance; DOM tests exercise the actual shell's card focus/expiry/replay/placement. Fixed
worker execution is real but local temporary-workspace only. Owner Kitty/Fedora reconciliation,
Python 3.14, actual marker readback and the reversible/refusal hardware scene remain pending.
Kitty may need a display and create its own dedicated native window: “headless hands” does
not assert a compositor-free Kitty runtime. No real Kitty process was invoked here.

Consent is one private 0600 allowlist file plus private append-only journal events. Ruling
entries and default-off prompt entries both support named-path revocation. Pending asks are
memory-only and terminally consumed; stale/expired/missing prompts deny. The journal replays
across restarts, marking orphan ACTIONs unknown, never replaying them. UI shows the latest
32 events with total count, not a fictitious full history. Journal capacity stops new actions
rather than truncating. Private runtime artifacts are retained; no broad cleanup is attempted.

## F37 protected mount and integration hold

Exactly the previously quoted eight added lines, distributed among lifecycle/handlers/typed route:

```python
from .hands.headless.host import HandsMount
self._hands_mount = HandsMount(config.socket_path.parent)
"hands.request": self._hands_request,
async def _hands_request(self, params: dict) -> dict:
    return await self._hands_mount.handle(self._require_ipc_owner(), params)
if (hands := await self._hands_mount.typed(self._require_ipc_owner, params)) is not None:
    return hands
await self._hands_mount.aclose()
```

`a7801fa:tests/test_hands_headless.py:300` requires removing exactly these lines to reproduce
accepted H's daemon.py byte-for-byte. Consent mechanics, grammar, file writes, decisions and
execution never expanded into protected code. No transcribe/live_client/cli/config/ladder,
pyproject, HANDOFF, protected storage or frozen fixtures/QML edits. history_limit remains 1.
The absolute maker engine remains SHA256
`5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.

**Rebase-before-merge was declared before editing.** Before any eventual merge, re-read the
actual mainline tip, rebase this same branch, and have design verify disjoint guard/pilot/seam
versus hands-call-out regions. This report is not that merge-time verification. No silent
merge, PR or force-push. No second assistant, model backend, phone bridge, NectarLink, window
orchestration retry or production monkeypatch was added. Same-UID/root compromise and OS-lock
identity are not solved by private directories or browser focus; no OS-sandbox claim is made.

## Gates and wall-time trend / F36

| Gate | Result | Wall time |
| --- | --- | --- |
| Accepted E | 2641 passed, 9 skipped | 120.25 s |
| Accepted F | 2669 passed, 9 skipped | 129.59 s |
| G | 2676 passed, 9 skipped | 133.40 s |
| H | 2698 passed, 9 skipped | 141.66 s |
| I final code gate | **2757 passed, 9 skipped** | **155.62 s** |
| Intervening report gate | 1 failed, 2756 passed, 9 skipped — listener collision below | 155.05 s |
| Final report revalidation, unchanged code | **2757 passed, 9 skipped** | **154.93 s** |

I code gate versus H: +59 tests and +13.96 seconds (~9.9%); final report revalidation was
+13.27 seconds (~9.4%) versus H. These are observed local runs, not a controlled benchmark. Ruff **0.17.2** passes. JS syntax/build, GLSL uniform checks and
absolute gate_verbatim pass; native manifest verifies; diff whitespace/protected-byte gates pass.
**Intervening failure retained:** the native fake-host process test's second listener check
refused port 32985. Inspection found both the test's 127.0.0.1 listener (UID 1001) and a
root-owned 169.254.0.21 listener on that port. The latter's origin was not investigated.
The production guard correctly rejected mixed listener ownership; it was not relaxed,
filtered or retried inside production code. Only the two verified synthetic fixture children
were cleaned up, after matching owner UID, cwd/argv and their exact temporary fixture paths.
The focused two-case recheck passed, followed by the full green report revalidation above.
The fixture's ephemeral-port availability assumption is not a universal collision guarantee;
this report does not hide the failed run or claim that environmental race was eliminated.

The WebKitGTK skip is explicit (`tests/test_console_native_window.py:222`); no fake DOM/host
or screenshot is relabelled native hardware. Sandbox Python is **3.11.2**, not owner 3.14.

Git **2.39.5**: three configuration **key-name-only** checks found no partialClone, promisor
or partialCloneFilter keys. No Git upgrade. The no-lazy-fetch guarantee holds by absence of
promisor, with protocol.allow=never verification reads. Explicit fetches were only this own
branch and the named producer objects for source tests; no implicit lazy fetch or owner tree
operation. After snapshot metadata reset, accepted H files were compared byte-for-byte before
metadata-only mixed reset; the two intended inventory guard/annotation edits were preserved.

Owner lines are issued above. Installation, real Win+Space, native F25 and the I owner scene
remain pending evidence. **Do not label any of them HW-PROVEN from this report.**
