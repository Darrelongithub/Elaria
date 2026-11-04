# Console handoff — 2026-11-04

**Existing typed mutations and indexed-file recall are already reachable; no new hands route
was built. WS1/WS3/WS4 are implemented and locally tested. WS2 and WS5 await owner rulings.**

## DONE

- Research gate committed **before fixes**: `85e2001`,
  `docs/phase-reports/console-2026-11-04-research.md`.
- Shell sizing/labels committed separately: `ddd6ab3`,
  `docs/phase-reports/console-2026-11-04-shell-layout-labels.md`.
- This handoff accompanies the detached-launcher change. The original owner-relayed acceptance
  of eight live replies, two-to-eight seconds apart, including the orb, stands. New layout
  and native app-window appearance are not silently owner-certified.

### WS1 / WS3 summary

Direct integration-stage-flex regression hypothesis rejected by source diff and wide browser
containment measurements. Legacy narrow grid auto-placement and floating-stage overflow
were reproduced. Fixed in shell only: 36vw wide panel, bounded 80% stage region, explicit grid
placement, chat-priority narrow behavior, bottom footer/lamps. Full panes leave the footer
visible. The engine and fit:1.8 are unchanged. The stage-region percentage is not a promise
that animated luminous pixels occupy exactly 80% in every state/aspect ratio.

Three-line banner removed; preserved homes are per-reply non-model labels, footer cadence/
text-only labels, pane PENDING/SHELL COPY badges, and the shared-conversation note in BRIDGE.md.
Independent badges, empty-feed reset, sample/live precedence and same-class stale copy fixed.
Eleven shell-copy memory cards remain. No placeholder feed was added to manufacture LIVE. Final copy review also removed two
standalone-stub overclaims (that rendering/persistence were proved, and that the browser had
made zero requests). Those text-only follow-ups do not change the measured geometry.

### WS4 — detached launch

Committed executable: `console/run_bridge.py`.

**SHA256: `ed227a7d50effb874e303f95462f3dc127c9bd79a71a8d9b34f86980815b091c`**

Checksum-first single-line invocations for app, manual, preflight and external-copy use are
in **console/BRIDGE.md**. The launcher checks all five sibling payload hashes before importing
the bridge. A mismatch stops; no fetch/install/repair is attempted.

`--open` uses installed Chrome/Chromium or an explicit absolute `--browser` path, with
app mode, a unique 0700 per-launch profile, and window-size flags (1440,900 default; optional
W,H override). It never shares two instances' profile directory. Direct argv, new POSIX
session, closed inherited FDs, null stdin/stdout/stderr, limited desktop/session environment;
no model key, agent or shell-startup environment is handed to the child. No shell invocation.

**No token is printed or placed in process argv.** Chrome's app URL names a private 0600
launch file, which immediately navigates to the freshly generated pairing URL. It is not a
stored/static-root URL. Manual mode opens the same private file. The file/profile parent is
a new 0700 directory beside the socket; unsafe parent permissions cause refusal, not chmod.

An actual-browser check caught a necessary detail: the existing cross-site gate rejected
file→HTTP navigation with **403**. The fix permits only the **public token-free root's
cross-site top-level navigation shape**. Protected shell/WS paths, non-loopback Host,
foreign/null Origin, cross-site fetches/iframes and framing restrictions remain guarded.
Post-fix, actual Chromium reached the current authenticated shell through the private file;
root-only and stale links stayed locked. No new RPC or method allowlist entry was added.

A blocking fake browser proved both lifecycle directions:

1. Terminal-style SIGINT to the bridge process group stopped the bridge, while the browser
   in its separate session remained alive.
2. Closing the fake browser left the bridge alive **and usable for a fresh WS handshake**.

Reaping uses nonblocking poll; no executor thread waits on a detached browser at shutdown.
No profile is deleted while its browser may still be using it. If the port is occupied,
launch refuses without creating a profile, killing an existing process or changing a service.

**Explicit costs:** new profiles have separate browser-local display history. Old display
caches are not overwritten or imported; daemon context is unchanged. Private files/profiles
remain until explicit cleanup after both processes stop or runtime-directory cleanup. This
is not an OS sandbox. Native Chrome app appearance/desktop window sizing remain owner checks;
headless Chromium did not exercise native app-window startup. The flags themselves were
owner-relayed design verification dated 2026-11-03, not a new owner-hardware measurement.

## TESTED-ONLY evidence

- Python **3.11.2**, websockets **17.4**. Owner Python 3.14.8 not run here.
- Focused bridge/launcher suite: **121 passed, 2 skipped**, 11.53s. Skips are the two explicit
  opt-in real-browser gates; no test downloads/installs a browser.
- Full local stub suite: **2520 passed, 8 skipped**, 106.67s. Ruff passed.
- Actual private-file/current-link/root-lock/stale-link browser gate: **1 passed**, 3.76s,
  separately opted in with Chromium **153.0.8010.0**. Synthetic IPC/status only; no model turn.
- Six-size geometry and resize gate passed earlier with the same layout and pinned engine;
  measured results are in the WS1/WS3 report. DOM smoke 114/114, sessions 23/23, client wire
  and independent label regressions passed.
- Lifecycle, unique profiles/modes, direct argv/env isolation, bad flags/geometry, private
  parent refusal, busy-port noninterference and public-root-only navigation exemption covered.
- An initial new test leaked its **synthetic** key variables into the frozen fixture's teardown;
  its own monkeypatch scope was fixed. No shared fixture or production policy was changed.
  The earlier research-run intermittent shared teardown error/rerun is recorded in that report.

## DEFECTS / OPEN — not concealed by labels

**WS2 remains open.** Unrestricted model prose can still make unsupported capability claims.
The existing live-provenance test proves origin, not truth or effect. A prompt, keyword
classifier, disclaimer, or three canned answers cannot establish universal impossibility.

Owner decision needed:

- **A — hard constrained mode:** display only a closed capability catalogue / evidence-backed
  structured results / deterministic refusals; withhold unrestricted model assertions.
  Estimated **2–4 hours** for the interface boundary and acceptance tests, with no new action
  route. This necessarily changes the accepted free-form conversational experience.
- **B — scoped authoritative capability surface:** retain non-authoritative model chat alongside
  a deterministic capability/result surface. Estimated **2–4 hours**. This can constrain the
  authoritative capability path, **but does not meet an absolute ban on false words in chat**;
  it requires an explicit owner re-scoping, not a silent claim that WS2 is solved.

The three required acceptance questions remain open pending that choice: “what can you do?”,
“can you confirm you can do those rn?”, and a file request. No consent is inferred from this
handoff and no capability/action facade has been built ahead of the ruling.

**R5: history_limit remains 1.** It trims only the returned conversation envelope, after _ask
has already used its separate eight-message retrieval / up-to-six-message prompt window.
Increasing it would add local response data, not fix prompt amnesia. Broader prompt history
would be a separate protected-daemon/privacy/token-cost decision. Fresh browser profiles do
not change the daemon context. Options and filtering details are in the research report.

**WS5 audit is complete; build remains held.** Audited exact mainline
`a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1`, without checking it out or merging it.

- console.say → _ask → intent dispatch already reaches memory writes, connectivity changes,
  queue draining, plan/index creation and explicitly scoped undo. Bare undo refuses scope.
  Scoped undo uses executor safety/operation locking, **not a fresh owner approval dialogue**.
- Typed input bypasses the ASR gate. The 0.6953/0.85 asymmetry is real; the gated mutating tuple
  contains undo only. No threshold change, universal-gate claim or new execution route.
- find/where/search and recalled context already use indexed paths/snippets. Organise can
  read/index configured roots. These are not proof of an arbitrary fresh-file reader or
  calendar/schedule management. Misses may fall through to a model and are not verified hits.
- Smallest proposal: **one lookup-index verb**, an additive bounded consumer of existing
  docs.search, rendering explicit structured hits/misses with index provenance and no model
  fallback. **2–4 hours** for wiring, privacy/posture and bounds validation, result display and
  stub tests, then owner verification. No fresh-file read or sending is included. Extending
  the bridge's two-method allowlist still requires an explicit ruling; if privacy/scope cannot
  be proved without protected changes, stop/ask rather than widening that scope.

**Next ruling:** approve that one index-lookup wiring job, or keep hands held. Kitty adapters,
scene work (NOT READY) and NectarLink remain explicitly out.

## Binding holds / integrity

Drafts first: compose → owner review/approval → only then send. Nothing leaves the phone
without approval; no send adapter or autonomy tier before draft review. Graduation requires
a separate ruling. Draft review itself is not yet built.

No service commands or unit edits: **elaria-console.service's enabled-state hold is preserved**.
No daemon/transcription/live-client/CLI/config/ladder/storage/hands/shared-fixture edits in
these workstreams. No engine edits. No owner checkout switch, install, real provider call,
new hands RPC, PR or force push. The historical kitty stash was not applied/recreated.

Pinned engine SHA256:
`5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.

Current UI index SHA256:
`0544e13a8c79f426baba84c904ea48a738a8ff00a7cc8d3514c3a912ddb53d26`.

Current bridge SHA256:
`fc5e78999c025ea8d0fb382c96c18e5d4a491eed1e1ae567ba91a39340c11ba7`.
