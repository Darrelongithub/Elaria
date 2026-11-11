# W4 — Hyprland 0.57 release-bind defect dossier (evidence only, 2026-10-31)

Scene-7 work order W4. Tags: **[HW-PROVEN]** on both incidents (owner
laptop, 2026-10-31 journals). Purpose: the evidence base for the WP3
jump decision (§5 order: jump to WP3 if rpm hyprland ≥ 0.57) and the
bind re-spec for the Lua era. No bind code changed this round — WP3
owns binds; this dossier is its input.

## The two incidents

**14:02 — simultaneous WIN+F2 release eats the stop [HW-PROVEN].**
Simultaneous release of WIN+F2 → ZERO stop events → 301 s runaway
capture (9,637,440 B = the 9.6 MB wav `20261031-140217-3b5227.wav`) →
300 s watchdog rescue (`stop.requested source=watchdog`). The release
bind never dispatched; only the watchdog ceiling ended the session.

**14:56 — F2-first release is clean; the safe direction is proven
[HW-PROVEN].** F2 released first → clean `source=bind` stop. WIN lifted
14 s later → `source=cli` + `source=bind` double stop → two clean
`stop.noop` idempotents. Session `94129ec0e4b5` stopped exactly once;
the double stop is SAFE in the over-trigger direction.

## Conclusion (the defect shape)

Release binds are **modifier-state-dependent at trigger-release**: any
release where WIN lifts before or together with F2 can eat the stop
entirely. The press path (dispatch) is unaffected — only the release
dispatch is gated on the chord still being held.

**Standing owner mitigation (until WP3):** two-step release — F2 first,
WIN held. This is a workaround, not a fix.

## Bind re-spec for the Lua era (0.57) — design input for WP3

Direction (to be implemented and proven by WP3, not here):

1. **Release dispatch must not depend on the chord.** Bind the stop to
   the bare-F2 release (catch-all, modifier-independent) while the
   PRESS stays on the WIN+F2 chord. Over-triggering is safe: 14:56
   proved the double-stop idempotent (`stop.requested` + `stop.noop`,
   one reply).
2. **Two release binds beat one fragile one** (WIN+F2 release AND bare
   F2 release → same `ptt.stop` handler). Idempotency already exists;
   the 0.56.2 flag grammar (`_RELEASE_IMPLYING_FLAGS = frozenset("rcg")`,
   D.4 truth order) is the reference for which bindr forms imply release.
3. **Keep the watchdog as the backstop**, not the mechanism — a 300 s
   rescue is a safety net, not a release path.
4. Lua-era caveat: 0.57's Lua bind layer must be checked for the same
   modifier-state gating at trigger-release (the defect may live in the
   dispatch engine, not the config grammar). The both-directions scene
   card (below) is the discriminator.

## 300 s hot-mic window: acceptable as rescue, not as design

- For **narration PTT**, 301 s of runaway hot-mic (9.6 MB captured) is a
  privacy exposure class of its own — the ceiling must stay, and the
  fix above removes the trigger.
- For **WP5 long-recording**, 300 s is too short by design. WP5 gets an
  EXPLICIT long-record mode (named mode, visible indicator distinct
  from PTT, ceiling raised or removed under that mode only) — never a
  silently larger global ceiling.
- The watchdog marker (`stop.requested source=watchdog`) is already
  journal-visible; the rescue is observable and correct.

## Scene card SC-W4 (owner hardware, ≤30 min daylight)

Re-prove the double-stop in BOTH release directions on the owner's
0.57 laptop:

1. **Direction A (F2 first, WIN held):** expect one `stop.requested
   source=bind`, one `stop.noop` (the WIN-lift 14 s later), one reply.
2. **Direction B (WIN lifted before/with F2):** on unfixed binds expect
   the eaten stop (defect repro; watchdog marker if left running — do
   NOT leave it 300 s: intervene with the CLI stop and record that
   too). After the WP3 bind fix, Direction B must produce the same
   clean one-stop + stop.noop shape as Direction A.

Both directions are decisions: an eaten stop in Direction B CONFIRMS
the defect on 0.57 and cements the WP3 jump; a clean stop implies the
Lua layer changed the semantics and the re-spec must be re-read against
the real 0.57 behavior.
