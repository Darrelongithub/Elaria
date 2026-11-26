# DISPATCH-SCRCPY — scrcpy phone-surface blueprint (manager, 2026-11-26)

Owner find: **scrcpy** for the phone integration layer.
Find-first verification (manager, GitHub API, 2026-11-26):
`Genymobile/scrcpy`, Apache-2.0, fork:false, 155,795★, pushed
2026-11-26, latest release v5.0.1 (2026-10-08). Licence passes
(LICENSE-DECIDES-METHOD: Apache-2.0 = blueprint and patterns
takeable; we still take the design, not embed the tool as a
runtime dependency).

## What scrcpy actually is (for the blueprint agent to confirm)

Mirrors an Android device's screen over ADB (USB or Wi-Fi ADB)
and can inject keyboard/mouse input. It streams H.264 from a
device-side server; it can run display-less (`--no-display`,
record/stream modes). It provides PIXELS ONLY — no element tree,
no semantics (Android's semantics live in its accessibility /
UIAutomator world, a separate surface to investigate).

## Why it interests us — and where it collides

Fits: the phone is her sidecar. A mirror makes the phone a second
**observation surface**: she could see the phone screen the way
the observation layer sees the desktop (frames in, grounding
labelled), e.g. "what's on my phone screen / point at the button
on my phone" with the ring drawn laptop-side over the mirror.

Collides, hard: (1) scrcpy *control* (tap/type injection) is
ACTING on the phone — today the phone's ONLY write verb is
`sms.send_sms` post-approval, and that narrowness is deliberate.
Control would be a new authority surface, admissible at most
under mouse-style tier-3 digest gates, and ONLY by a separate
owner ruling. (2) It requires USB debugging / ADB on the phone;
Wi-Fi ADB is a network-reachable powerful shell — the blueprint
must pin the surface to the scrcpy stream and treat raw ADB as
forbidden territory (never her tool), and must confront the
phone-security cost honestly. (3) Pixels-only means grounding on
the phone is VLM-class (diverted budget, labelled unidentified)
unless Android a11y proves readable — worse grounding than the
desktop's AT-SPI-first, and the blueprint must say so.

## DISPATCH — Agent P (blueprint only, no code)

> You are Agent P. Blueprint scrcpy for Elaria's phone layer —
> design only, no code, no installs. Read
> `reports/DISPATCH-SCRCPY.md`, the phone-link rules in the repo
> (sidecar never copy; `sms.send_sms` the only write verb), and the
> observation design (`src/assistant/observation.py`,
> `reports/RPT-O-mouse-blueprint-20261125T113104Z.md`). Verify
> from primary sources (tag every claim [READ]/[DOC]/[INF]):
> scrcpy v5.x architecture (server push, video stream, control
> channel — and whether video can be consumed WITHOUT the control
> channel existing), headless frame access for a programmatic
> consumer, ADB transport options and their security posture
> (USB vs Wi-Fi, authorisation model), and Android-side semantic
> alternatives (accessibility tree / UIAutomator dumps) for
> grounding. Then design: (1) mirror-as-observation — frames join
> the observation contract (`frame_id`, provenance, deleted after
> use), pointer-over-mirror as a laptop-side drawing, ZERO input
> path compiled out, not just unused; (2) IF-6: phone screen
> content is untrusted data (notifications/messages on screen are
> the injection surface — headline bug-case); (3) the honest
> cost: USB-debugging-on security trade-off for the owner's phone,
> stated plainly with mitigations (USB-only, per-host RSA auth,
> revoke-when-unused); (4) API BUDGET declaration (expect: zero
> cloud for mirroring; VLM grounding only under the existing
> diverted role/cap); (5) a SEPARATE section sketching what
> control would require IF the owner ever rules it (tier-3 digest,
> journal-before-action, kill condition) — labelled NOT PROPOSED,
> for the owner's future decision. Stress-test your design;
> file gaps. Deliverable `reports/RPT-P-scrcpy-blueprint-*.md`,
> new `arena/*` branch, merged PR. Never edit OWNERS.yaml.
