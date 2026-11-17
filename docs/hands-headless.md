# Task I — dedicated-instance headless hands

**TESTED-ONLY / OWNER-HARDWARE-PENDING.** No real Kitty/compositor, owner terminal,
window orchestration, model call, phone sidecar or NectarLink was exercised. This is a
bounded effect adapter, not certification of arbitrary terminal automation.

> **Owner Ruling C supersession:** this document describes the accepted Task I
> implementation, which still asks on an allowlist miss. The new required policy
> removes that ask: only exact on-list, assessed reversible work may execute;
> off-list/irreversible/unknown work receives an immediate recorded refusal.
> Independent classification, hashes, inventory binding, dedicated-instance
> restrictions and action/readback evidence remain. See
> [asks 35–39 transition and current-code gaps](design/hands-owner-ruling-transition.md).
> The transition is not yet implemented or hardware-proven. Historical card and
> prompt semantics below are retained as history, not reaffirmed as the new policy.

## Authority and merge boundary

Owner-supplied §1c, §1d, §1e and §1g govern. §1g supersedes F12: all routing/consent machinery
is in `src/assistant/hands/headless/`; daemon.py receives only the eight additive lines
quoted before editing. §1e/F34 supersedes F15's older placement: attribution, asks and
denial/action/observation summaries live in the **sessions sidebar**, never centre chat.
F14's adopted contract is `headless-exact-argv-v1`, specified below; unsupported is denied.
No source code was copied from OpenClaw, OpenHands or hyprcu. Their precedents are ideas,
not dependencies. No license-unverified code or GUI-input tool was imported.

**Before any merge:** rebase this same working branch onto the then-current mainline tip;
design must verify disjoint conflict regions against guard/pilot/seams at merge time. Do
not resolve daemon.py silently. No merge, PR, rebase rewriting published work or force-push
is performed by this delivery. Recheck actual refs then; the producer contract inspected
read-only is 4218ef02be7627e787a2a5fe457ae553b80381ae, not an assertion about a moving ref.
`tests/test_hands_headless.py::test_mount_is_exactly_eight_additive_lines_only` removes the
quoted eight lines and requires byte equality with accepted H's daemon.py.

## Scope and two vocabularies

Typed input grammar, handled before `_ask`, is exactly:

- `hands open` — explicit session hand-open; start one dedicated instance. No startup at daemon boot.
- `hands mkdir NAME` — create one empty directory in that instance's private work directory.
- `hands rmdir NAME` — remove only an empty directory whose creation/state was observed by this instance.
- Up to four **independent**, distinct-name segments joined by `&&`, e.g. `hands mkdir a && mkdir b`.
  Every segment must be valid and consent-covered before any segment executes.
- `hands status`, `hands close`, `hands always on`, `hands always off`.
- `hands revoke /absolute/canonical/binary/path` — revoke both populations for that named path.

NAME is ASCII `[a-zA-Z][a-zA-Z0-9_-]{0,63}`. Quotes, substitutions, redirects, pipelines,
`;`, `||`, newlines, traversal, script operands and dependent chains are **unsupported**.
This is not a partial shell evaluator. No shell string is ever executed. Irreversible and
unknown effect families receive a recorded refusal, not a permissive classification.
Broader capability needs its own assessed adapter; this is not a permanent doctrine whitelist.

The executable vocabulary is canonical `/usr/bin/mkdir -- ABSOLUTE_TARGET` or
`/usr/bin/rmdir -- ABSOLUTE_TARGET`. The Kitty vocabulary is pinned `ls`, `send-text` and
`get-text`. Native payloads pass the existing inventory schema validator. Concrete argv
is independently checked against the known empty-directory effect and private cwd identity.
R3 adjudication and the existing R5 canonical plan hash are retained; the approval digest
also binds evidence, binary SHA256, cwd identity, operand state and inventory version.
No model-supplied tier/checker can enter this route.

## Consent contract — exact-argv-v1

`argPattern` is **only** `sha256:` plus the SHA256 of compact, sorted-key UTF-8 JSON of the
parsed argv array. It is not regex, glob, prefix matching or a shell string. Unsupported
pattern forms are invalid. Executable paths are symlink-resolved; a canonical interpreter
alias, script, wrapper or arbitrary executable is refused. Fixed interpreter bootstrap for
our pinned non-shell worker is infrastructure, **never an allowlist entry** or a generic exec adapter.

One private 0600 `allowlist.json` contains contract, promptAlways and entries. Each entry has
exactly `path, argPattern, binary_sha256, inventory_sha256, source, lastUsed`; source is
`ruling` or `prompt`. Ruling-seeded entries are owner-curated in that file, not model-generated.
There is no auto-seed. Both populations are revocable with the named-path control.
Prompt-seeded allow-always is **off by default**. Turning it on is a separate explicit owner
control. Allow-once is the default, ephemeral and never persisted as standing permission.
No, expiry, changed snapshot, error and successful approval all consume the ask exactly once.

The daemon retains only one pending immutable whole-plan ask, with a 120-second deadline.
The bridge retains its token in memory and supplies a different, connection-bound review ID
to the browser. Cards require private posture, explicit reveal, visible/focused document and
focus inside the selected card. Exact Yes/No entry is separate from ordinary chat. No ask is
spoken; no client audio path exists. Blur hides private fields; disconnect/session changes
remove the card; no snapshot/token is stored in browser sessions. These are UI gates, not
OS-lock sensing or protection from a compromised same-UID process.

`askFallback=deny`: absent/unreachable/expired prompt cannot execute. Expiry, rejection,
unsupported intent and drift are journalled with reasons. Missing new backend is detected
by a hands.request status preflight before any hands text is sent to console.say; **no model
fallback**. A lost effect reply is unknown, spent, never retried automatically.

Binary hashes, inventory bytes, cwd identity and operands are rechecked at approval and
immediately before execution, including inside the worker at each chain boundary. The worker
executes an already-open binary descriptor and cwd descriptor, with shell=False, a scrubbed
environment and closed unrelated FDs. Script operands are refused rather than guessed safe.
This private workspace is not an OS sandbox; an empty HOME does not erase account-database
access. Root/same-UID compromise and kernel races are not solved by these gates.

## Ground-truth inventory correction / F31

The inventory stays byte-identical: 514,801 bytes, SHA256
`7e0f01ff2396c292f05528261d349142f1c6e08eed948847ee1300633a1aafcd`.
`policy.inventory()` checks that pin before parsing the same bytes. The standing consent
entry and immutable ask bind it; worker checks actual inventory bytes again before each step.
Future revisions require an explicit re-pin and fresh approval. Old standing hashes cause a
visible deny, never implicit migration. `tests/test_kitty_inventory_pin.py` is the ground-truth
pin/drift gate. The foundation report is annotated while its defective historical value remains.

## Dedicated Kitty lifecycle / F26 / F22

No daily-terminal socket, config, cwd, window ID, password or executable can be supplied by RPC.
The daemon creates `elaria-hands-<random-instance-id>` below the owner runtime directory, mode
0700, with its own work directory, fixed worker/contract copies, and 0600 configuration/password
and request/result files. The socket is directly under the private XDG runtime directory.
`/tmp` RC roots are refused. There is no --single-instance, attach-to-existing-terminal,
active-window selector, shell, focus command or Hyprland action.

Startup checks local Kitty 0.47.1 and pins its actual binary, the fixed Python interpreter and
worker/contract copies. That is a runtime identity gate, not installed-package reconciliation
or a Fedora hardware proof. Kitty gets only explicit private config and a scrubbed desktop env;
remote control is password-authenticated and verb-restricted. No child RC grant is issued.
Every encrypted connection checks the expected daemon-started Kitty PID as well as UID/socket
identity. Each fresh ls must return exactly the dedicated non-shell worker and stamped title.

The fixed child has terminal echo disabled and accepts only random request nonces, not shell
commands. Each effect prints a fresh `ELARIA_OK_<nonce>` **after** its bounded argv subprocess
and target readback. The adapter reads it back via get-text and independently checks the target
state/hash. A send-text acknowledgement or echoed request cannot certify the effect. Missing
marker, incomplete result, timeout or target drift produces **unknown** and faults the instance;
no implicit retry. Startup has its own fresh readiness marker. Read probes are journalled as
READ attempts/results (digest only), not recursively treated as effect actions needing new probes.

A dedicated Kitty process may require a display and create its own native window. “Headless
hands” here means noninteractive, non-shell work inside its isolated instance—not a false
claim that Kitty is a windowless compositor-free program. No real instance was started here.
Closing terminates only the daemon-created process group, not the owner terminal or service.
A closed/faulted instance is not automatically reopened or repaired in the same daemon session.
Private runtime artifacts are retained for inspection, not recursively deleted under a worker.

## Journal and sidebar / F15 / F23 / F34

State directory: `${XDG_STATE_HOME:-$HOME/.local/state}/assistant/hands-headless/`.
It holds the single consent file and `events.jsonl`, a separate private append-only hash-chain
journal—not the protected assistant store, core hands.db or legacy daily-terminal journal.
Every record identifies the instance. ACTION carries concrete argv, inventory verb, whole-plan
hash, assessor/reason and evidence reference. Its OBSERVATION carries action correlation,
exit code, stdout digest, resulting target-state hash and marker verification. Unknown values
stay null/unknown. No raw subprocess output, password or fact content is journalled.

The file is replayed and checked on restart. Unmatched ACTIONs are reconciled to unknown, never
replayed. Maximum 2,000 entries / 4 MiB; reaching the bound stops new actions, never truncates
history. The sidebar explicitly shows the latest 32 events and total count; it is a bounded
summary, not a claim to display the entire journal. General reply attribution also moved to
its single home in the sessions sidebar; original message text remains centre chat.

## Evidence and limits

Portable tests execute actual mkdir/rmdir in temporary private workspaces, using the fixed
worker, with separately labelled recording Kitty transports. The reversible demo verifies
create → marker/readback → attribution ACTION/OBSERVATION → exact empty-directory reversal.
A bulk-delete intent is refused before any execution, with a DENIAL reason in the sidebar.
A deliberately missing marker still reports unknown even when the directory exists.

Additional tests cover every chain segment, both consent populations, revocation/lastUsed,
interpreter refusal, binary/inventory/cwd/operand drift, expiry/replay, halted step boundaries,
crash reconciliation, per-connect PID rejection, immutable startup argv/env, real authenticated
daemon typed routing, real console wire binding and actual DOM focus/privacy/placement.
No production monkeypatch, model, owner terminal or compositor is involved in these tests.

Owner hardware and installed-package reconciliation remain pending. The old window-orchestration
fault stays parked/unretried. Native G still deploys 25ef8e6; H/I do not silently enter that pin.
Before an owner I scene: integrate through the F37 merge gate, verify the exact release, then
use the sidebar's explicit open, prepare `hands mkdir demo`, inspect the private plan, Allow
once, verify the real journal/marker, prepare `hands rmdir demo`, Allow once, and inspect the
recorded refusal for `hands rm -rf /`. Do not run that scene against a daily terminal, and do
not call stub tests hardware acceptance.
