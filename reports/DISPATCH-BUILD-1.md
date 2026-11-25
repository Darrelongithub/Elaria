# DISPATCH-BUILD-1 — first builds (manager, 2026-11-25)

Two lanes cleared their gates. Build in this order; pointer lane
first. Standing rules for both: thresholds frozen, OWNERS.yaml
untouched, one eye-check test per wiring claim, agents merge their
own PRs, sandbox numbers labelled sandbox, hardware claims never.

## BUILD-1 — Agent H (pointer, no acting)

> You are Agent H. Build the NUS pointer on Elaria from
> `reports/RPT-H-nus-pointer-blueprint-20261125T113441Z.md`
> (gate-PASSED) and the shared-observation design in
> `reports/RPT-O-mouse-blueprint-20261125T113104Z.md` §3.
> Scope, exactly: (1) `observation` layer — screenshot via
> xdg-desktop-portal (grim/screencopy fallback), AT-SPI element
> tree first, VLM coordinates fallback LABELLED unidentified;
> `frame_id` + snapshot shared with the mouse lane, built once;
> screenshot files deleted after use (NUS posture), never
> uploaded except to the pinned provider as data (IF-6). (2) The
> point: the daemon accepts a grounded target and
> `ui/quickshell/nus/shell.qml` draws her orb + breathing ring at
> the element's REAL bounds (NUS mechanics: element id preferred,
> rect from the OS not the model; confidence gates IN CODE —
> element ≥0.3, bbox ≥0.4, unverified ≥0.5, below "sure" it says
> "best guess", >25% screen area refused, sensitive fields —
> password/pin/card — refused locally, never pointed at; wrong
> pointer is worse than none → "I couldn't find it"). (3) Wire
> capture.state → the existing `setCaptureState` dispatch so the
> surface actually receives commands (fix the unplugged seam:
> the daemon must SEND, transitions only), plus the systemd unit
> for the nus path. NO clicking, NO acting in this lane — point
> only, per the owner's pointer-first ruling. Eye-checks: fake
> portal/AT-SPI fixtures → ring lands on the fixture element's
> bounds; confidence below gate → no ring drawn; capture.state
> sequence reaches a fake `qs` runner in order. API budget:
> grounding calls are diverted-material under
> `reports/SPEC-PROVIDER-ROUTING.md` (never personality tier),
> declare your cap. New `arena/*` branch, PR, merge yourself.
> End with the owner's on-laptop eye check written out (what he
> should see, in order) — he will judge the orb, not you.

## BUILD-2 — Agent Z (composition: GAP-1 errand runner)

> You are Agent Z. Build the composition layer from
> `reports/RPT-B-scavenger-gaps-20261125T161536Z.md` (GAP-1, the
> top gap) — a **bounded task planner / async errand runner** so
> one typed instruction can chain internal skills (search →
> open/read → compare → remember-inferred → ask owner) as a
> bounded errand instead of starving one synchronous turn.
> Requirements from the audit (cite its file:lines in your PR):
> steps are bounded (count, time, per-step API budget under the
> `[quota]` ladder — cheapest first, and errand cost is
> journaled per step); read skills only in this lane (no writes,
> no sends — acting verbs arrive in later lanes through their
> own gates); mid-errand clarifying questions are a first-class
> stop (ask, pause, resume on authenticated owner answer —
> design for GAP-6's state machine, even if you only build the
> minimum seam); every retrieved byte is untrusted data (IF-6)
> inside the errand; owner can inspect and cancel a running
> errand; completion reports what was done, what was inferred
> (with evidence), and what remains unasked/unanswered. Prove
> composition with an eye-check: a synthetic instruction over
> fixture files chains search→read→infer→ask with NO
> chat-specific code anywhere in the path (a second fixture
> domain must work unchanged — that is the generality test).
> GAP-2/GAP-3 fixes (discovery roots, >200KB streaming) are in
> scope ONLY as the minimum the eye-check needs; file the rest
> back. New `arena/*` branch, PR, merge yourself. Never edit
> OWNERS.yaml, never lower a threshold.
