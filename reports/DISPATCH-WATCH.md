# DISPATCH-WATCH — continuous local screen awareness (owner ruling, 2026-11-27)

Owner overruled snapshot-only posture: *"She should continuously
watch my screen… nothing ever leaves my laptop?"* Manager
clarification (accepted framing): pixels are the sensitive
artefact; the accessibility TREE is not. Ruling:

- **Continuous AT-SPI watching: YES.** Always-on local watcher of
  window element trees (names, roles, bounds) for all open
  windows. Local only, RAM-only (rolling, like the audio ring
  buffer), never persisted, never uploaded, never sent to any
  provider. Grounding reads the live tree — no focus-first
  requirement; ambiguity across windows is resolved by window
  identity spoken aloud ("the Cancel in Files or in Settings?").
- **Continuous screenshots: NO.** Pixels stay snapshot-per-ask,
  deleted after grounding, exactly as today. VLM grounding stays
  disabled unless separately enabled by the owner (budgeted
  diverted role, labelled unidentified).

Non-negotiable rails for the design:
1. **Password/sensitive nodes never enter the watched tree**
   (filter at ingestion by role + the existing SECRET patterns;
   the tree in RAM must be incapable of holding a secret).
2. **Visible when watching.** The pill/surface shows an
   observing state; a watcher that hides itself is a fail.
3. **Instant off.** Halt (SUPER+SHIFT+F12 / `assist halt`) and
   showoff/company modes stop the watcher; screen lock stops it;
   watcher state transitions are journaled (state, never content).
4. **No authority change.** Watching confers zero authority —
   pointing still needs an ask; acting still needs its tier
   gates. IF-6: element names/labels remain untrusted data.
5. **Resource honesty:** measure CPU/RAM on owner-class hardware;
   event-driven (AT-SPI events), not polling; declare the budget
   (expect zero API) in the blueprint.

## WATCH-DESIGN — Agent H (blueprint first, no code)

> You are Agent H. Design continuous local screen awareness per
> `reports/DISPATCH-WATCH.md` (owner ruling + the five rails —
> read them first; they are the spec). Today: one-shot
> `_observation_linux.py atspi` helper invoked per ask
> (post-HW2B: WINDOW-relative descendant translation, size-match
> acceptance, rejection journaling). Design: an event-driven
> AT-SPI watcher process (system-python GI bridge like the
> helper) streaming tree deltas to the daemon; data model for a
> multi-window live tree with staleness bounds (a ring must never
> be drawn from a tree older than X without revalidation —
> propose X and defend it); how `ground()`/`semantic_target`
> change when the tree is live (window-identity disambiguation,
> cross-window search, focus as a hint not a gate); the sensitive
> filter at ingestion (prove a password field's *existence* can
> be known while its identity/value can never be stored);
> failure modes (a11y bus death, app crash mid-tree, 500-window
> stress, event floods) with the watcher failing silent-and-dark
> (no watching indicator = no watching); resource measurement
> plan for owner hardware; and the owner eye-check script.
> Cite the current code paths you replace or keep. API BUDGET:
> declare it (expected zero cloud — state it and prove the design
> needs none). Deliverable `reports/RPT-H-watch-design-*.md`,
> new `arena/*` branch, merged PR. Blueprint only — no code.
> Never edit OWNERS.yaml.
