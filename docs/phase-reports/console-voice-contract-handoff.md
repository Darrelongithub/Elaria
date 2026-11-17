# Asks 35–40 — contract-only handoff

Baseline: accepted `a26dbdc31f5551b37a19e981d1cb8b78e29cafa7` on
`arena/b65d5161-elaria`. This delivery publishes a consumer interface **request** and
hands transition findings, not an implemented mainline API or a deployed feature.

## Deliverables

- [Ask 40 producer contract v1](../design/console-voice-producer-contract-v1.md):
  six indications; proposed metadata-only observation/control interface; causal
  IDs, ordering/replay/snapshot and freshness; atomic toggle; retained output
  transcript, content-verified cache, fidelity-before-playback and player evidence;
  producer/consumer/hardware gates. Missing events are explicitly producer work.
- [Asks 35–39 hands transition](../design/hands-owner-ruling-transition.md):
  sanctioned integrated release path without repinning G; assessed local inventory
  adapter design; existing-orb indication costs; current miss-ask versus ruled
  immediate refusal; independent classifier; typed revoke/always semantics;
  durable accountability, undo and exact-instance authority gaps.
- Additive supersession notes in the earlier voice preflight and hands implementation
  document. Their historical findings and test results remain unchanged.

## Scope and findings

Both current Drive specs were read in full. Their metadata matches the supplied
pins; these are not locally downloaded raw-blob hashes. Part 2 takes precedence.
Console no-audio-egress and mainline producer ownership are resolved, not pending
questions. The daemon's authorized cloud transcription/synthesis route is unchanged.

No runtime code changed: no browser media path removal is claimed yet, no synthetic
signal is relabelled as live, and no hands ask removal is claimed. Current typed
revoke does not require a card, but `always off` is not a master switch for ruling
grants. Current exact argv grants do not carry over a new random instance cwd.
No owner command list was supplied; no seeding packet or allowlist was generated.

No merge/rebase, native source pin change, service/config/keybind action, model call,
audio capture/playback, owner-hardware run or owner store access. Native G remains
pinned to 25ef8e6. F37 remains satisfied as ruled; the exact eight-line mount remains
unchanged. Reboot remains the already accepted natural-reboot residual.

## Validation

- Ruff **0.17.2**, whole repository: **pass**.
- Full suite: **2798 passed, 9 skipped in 174.12s** (pytest reported).
  Measured subprocess wall time: **174.92s** using Python monotonic clock.
- F36 trend, comparable pytest durations: accepted a26dbdc **155.23s** →
  this documentation-only tree **174.12s** (+18.89s). No timing-cause or
  performance-regression inference is made from this single sandbox run.
- Exact eight-line mount regression separately rerun: **1 passed in 0.06s**;
  local accepted H object was available, so this test did not skip.
- Four-entry native-launcher manifest and separate observer manifest: all **OK**.
- Immutable tool inventory remains 514801 bytes, SHA256
  `7e0f01ff2396c292f05528261d349142f1c6e08eed948847ee1300633a1aafcd`.
- Diff whitespace check: pass. Tracked code, fixtures, manifests and deployment
  artifacts unchanged relative to the accepted baseline.
- Earlier speech audit remains separate, untracked and unchanged, SHA256
  `95494ede54abbb4c788a94c7d0be2a33b2983876d647451f47cabd0347235593`.

Test setup note: sandbox-generated dependencies had disappeared and were restored
locally (including the same Ruff version and jsdom without saving a package/lock
change). Initial `/usr/bin/time` wrapper was unavailable; no test run began in that
attempt. The successful run above used Python's monotonic timer. No failing test was
suppressed or guard weakened.

Repository metadata note: initial HEAD/index again reflected the original base,
while accepted source persisted. After name-only partial-clone configuration checks
found no matching settings, the current branch was fetched; all 348 tracked files
were compared byte-for-byte with a26dbdc using protocol-disabled local object reads.
Only after zero differences was the index/HEAD restored via mixed reset. No file
contents or branch were switched. Immutable 9e49915 was fetched for read-only
producer audit, not merged or installed.

## Next dependency, not a new owner egress hold

Mainline publishes the producer revision, schemas, fidelity/cache receipts, player
capabilities and gate results. The consumer can then implement the agreed wire
contract and prove removal/unreachability of browser capture/playback/simulation.
Hands policy/accountability changes and a separately sanctioned integrated native
release precede any hardware claim. Passing the unchanged suite validates baseline
regressions; it does not implement or certify these requested features.
