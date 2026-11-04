# WS1 / WS3 shell-only delivery — 2026-11-04

Research-first gate: commit `85e2001`, `console-2026-11-04-research.md` in this directory.
No hands implementation. WS2 hard-guarantee boundary and WS5 capability choice remain OPEN;
WS4 launcher detachment is a separate change. history_limit remains 1.

## DONE — TESTED-ONLY, owner visual review still required

- Wide right panel is 36vw. Stage region has 80% maximum panel height while retaining
  flex:1 1 auto / min-height:0; renderer fit remains 1.8. This specifies the **stage region**,
  not a fixed luminous-pixel percentage across every animated state/aspect ratio.
- Explicit grid columns fix the reproduced <=940px zero-width-chat auto-placement defect.
- <=1040px rail yields to 28vw; <=680px the large orb is omitted instead of floating/cropping
  over chat. Sidebar is closed by default below 940px, opens on request, and has close/Esc
  controls. Hidden sidebar controls are inert. Intentional transcript/content scroll remains.
- Global footer is bottom-pinned and remains visible under full-pane views; four lamps moved
  there. The orb engine is byte-identical, including the embedded built copy.
- Three-line outer banner removed. Normal wrapper is a full-size iframe. Missing/expired
  pairing links still get an explicit blocking message; connection health uses shell lamps.

### Removed-banner fact map

| Fact | Designated current home |
| --- | --- |
| non-model/error outcomes | unchanged per-reply labels |
| synthesised text cadence, not measured audio | footer |
| text-only, no speech | footer |
| PENDING / SHELL COPY | each pane's badge (also its expanded view badge) |
| shared daemon conversation | BRIDGE.md, not the visible shell |

Empty feeds now reset to pending/shell-copy. Transcript/audio/memory badges are independent;
a sample toggle cannot relabel a real feed. No fabricated feed was added. Memory live-card
copy no longer calls those cards baked-in. Absent feeds no longer say the bridge does not
exist. “Driven by real levels”, the overbroad “never leaves this machine”, and stale
narrow-rail/current-census claims were removed/replaced. Seed prose is labelled local shell
preview rather than masquerading as a new model reply. Eleven design memory cards remain.

This label work does **not** solve unrestricted-model capability hallucination. That requires
the explicit output-boundary ruling described in the research report; it is not hidden behind
footer wording or three canned answers. Existing typed mutations remain documented, not
silently disabled, reclassified as approval-gated, or newly built.

## Verification

- Build: JS parse, GLSL and absolute gate_verbatim passed.
- Engine SHA256: `5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447`.
- DOM smoke: 114 passed; session regression: 23 passed; wire client regression passed.
- New labels regression: independent feeds; empty reset; mixed sample/live provenance;
  footer; connected/offline status wording; narrow sidebar control.
- Focused Python bridge suite: **100 passed, 1 skipped** (opt-in browser gate).
- Full local stub suite: **2499 passed, 7 skipped**, 105.65s. Shared fixtures unchanged.
- Ruff and diff whitespace checks passed. No provider, microphone, speech or owner hardware
  calls. Existing local browser tooling only; no browser/dependency auto-install in tests.

Optional `console/layout-test.js` ran against the synthetic bridge in actual headless
Chromium 153/software rendering, not jsdom. It checked canvas/container equality, zero
orb/document overflow, visible composer/footer/lamps, explicit sidebar open/close, full-pane
footer preservation, and renderer aspect changes through 1920→800→390→1440 resizing.

| Viewport | Panel width / height | Stage client width / height | Chat width | Footer height |
| --- | --- | --- | --- | --- |
| 1920×1080 | 691.19 / 1043 | 690 / 834 | 930.81 | 37 |
| 1440×900 | 518.39 / 863 | 517 / 690 | 623.61 | 37 |
| 1024×768 | 286.72 / 731 | 286 / 585 | 463.28 | 37 |
| 800×600 | 224 / 563 | 223 / 450 | 576 | 37 |
| 390×844 | omitted | omitted | 390 | 53 |
| 320×480 | omitted | omitted | 320 | 69 |

The first browser run found that an open narrow sidebar could cover its original toggle;
an explicit close button was added and the complete gate rerun passed. No screenshot/pixel
quality or owner-wide clipping reproduction is claimed from geometry assertions. The owner's
prior functional demo acceptance stands; the changed layout still needs their visual check.

## Unchanged boundaries

No daemon/transcription/live client/CLI/config/ladder/storage/hands/shared fixture edits.
No new RPC route, dispatch or authority. No engine change. No service command/config change;
elaria-console.service remains under the owner's enabled-state hold. Kitty/NectarLink held.
Draft review must precede any future messaging send adapter or autonomy. No PR or force push.
