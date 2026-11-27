# DISPATCH-WATCH-BUILD — continuous watching, staged builds (2026-11-27)

Design: `reports/RPT-H-watch-design-20261127T092452Z.md` (Agent H).
Ruling + five rails: `reports/DISPATCH-WATCH.md`. Read both before
any lane. **Zero cloud API budget for the whole programme** —
watching and element grounding make no provider calls, ever
(design §9; enforced by import tests and the owner's
`llm_calls` zero-delta check).

Owner decisions (adopted defaults from design §0 — the owner may
overrule any of these before the lane that depends on it starts):
- **D1:** accept the §6.4 recommendation — names kept only for
  control roles + the HW2B contained-label case; `label`/`static`/
  `paragraph`/`terminal`/`document` roles are geometry-only.
- **D2:** staleness bound X = **2.0 s at draw time** (§5.2).
- **D3:** attempt `mlock`; if refused, journal warning + `assist
  doctor` surface, keep watching (not fail-closed).
- **D4:** "company mode" = any privacy posture (showoff, class
  mode, forced-offline) — all stop the watcher.
- **D5:** cross-output windows: identity spoken, no ring.

Lanes run **in order**; each is one agent, one merged PR.
Sync `origin/main` first, new `arena/*` branch, never edit
OWNERS.yaml. Every lane ships the tests its rail demands
(design §3) — a lane without its canary tests is not done.

## WATCH-BUILD-1 — Agent H: rail-1 fix to TODAY's path (independent, ship first)

> Fix the defect the design found in current code:
> `_observation_linux.py` reads `get_name()` on PASSWORD_TEXT
> nodes and carries the name into the daemon frame. Make
> sensitive roles short-circuit BEFORE any name/description/
> text/value read, in the one-shot helper (and any shared walk
> code): a password node contributes role + rect only. Canary
> test: fake node whose property getters raise/record access —
> assert no getter fires for password nodes and no name appears
> in output or journal. Existing HW2/HW2B tests stay green.
> This lane does NOT build the watcher.

## WATCH-BUILD-2 — Agent H: ingestion filter + RAM store (daemon side)

> Implement design §6 + §5.1 as daemon-side modules: the ingest
> filter (role-before-property, tombstones, SECRET name screen,
> 64-char caps, D1 geometry-only text roles, title filtering
> §6.5) and the `WatchStore` (Window/Node records, caps
> 128 windows / 256 per window / 20k total, seq-gap → stale,
> RAM-only, never serialised). Pure and testable without a bus:
> canary suite from §3 rail 1 incl. journal-lines-contain-no-
> names assertion; AST import test (rail 4): no imports of
> executor/hands/intents/pointer-draw/provider clients.

## WATCH-BUILD-3 — Agent H: the watcher child (event-driven deltas)

> Extend `_observation_linux.py` with `watch` mode per §4.1–4.2:
> system-python GI child, AT-SPI structural events only (never
> text events/payloads), Hyprland socket2 window lifecycle,
> NDJSON deltas ≤64 KiB with per-window `seq`, stderr metadata-
> only (sanitised tracebacks), `RLIMIT_CORE=0` +
> `PR_SET_DUMPABLE=0`, exits on stdout broken pipe. Flood
> controls §8.4 (token buckets, 200 ms coalescing, stale after
> 5 s sustained). Tests drive it with fake event sources; no
> real bus in CI.

## WATCH-BUILD-4 — Agent H: supervisor, state machine, visible indicator

> `WatchSupervisor` + state machine §4.3–4.5: OFF→ARMING→
> WATCHING, DARK/PAUSED, one `stop(reason)` path (halt flag +
> `_halt()`, showoff/privacy postures, logind lock/sleep,
> overlay-gone), SIGTERM→200 ms→SIGKILL, store cleared ≤500 ms,
> resume never automatic (explicit resume + full resync §4.6).
> Overlay: `watching` indicator shown ONLY while WATCHING;
> supervisor arms only after overlay ack; overlay EOF stops the
> watcher (§4.4). `assist watch status` CLI. `watch.state`
> journal lines: state + reason only. Per-trigger tests §3
> rail 3; overlay-EOF test §3 rail 2. Watching is OFF by
> default; enabling is an explicit owner config + resume act.

## WATCH-BUILD-5 — Agent H: live grounding (cross-window, clarify, staleness)

> Rewire the ask path per §7 + §5.2–5.3: `_elements()` reads the
> live store; focus becomes ordering hint only; the ACTIVE gate
> is replaced (visible-on-focused-output + SHOWING); matches in
> >1 window return `clarify` (window identities spoken, no
> ring, no click) and the owner's answer re-runs window-scoped
> under unchanged HW2B rules; occlusion refusal §7.3; draw-time
> 2.0 s staleness check with single-window revalidation
> (150 ms bound) before any `draw()`; cross-output = identity
> only (D5). One-shot `atspi()` stays as dark-watcher fallback.
> Tests: two-window same-label clarify flow, stale-window
> refusal ("can't confirm it's still there", no ring), occluded
> target refusal, HW2/HW2B suites green, sensitive tombstone
> overlap refusal unchanged.

## WATCH-BUILD-6 — owner hardware (no agent): measurement + eye-check

> Owner runs design §10–§11 on the laptop, after 1–5 merge:
> hardware recorded; watching dot visible; two-zenity Cancel
> clarify → ring on the named window only; password dialog →
> sensitive refusal + clean journal grep; halt/lock/showoff/bus-
> death all take the dot dark; 10 min + five asks with zero
> `llm_calls` delta; S1–S6 resource numbers vs the proposed
> budgets (child ≤0.5% idle CPU, ≤64 MB RSS idle, ≤128 MB under
> 500-window stress, halt clears ≤500 ms). Report pasted to the
> manager; only the owner's numbers close WATCH. Hibernation
> caveat (§8.10/D3) is stated to the owner before first enable.

**Programme rule:** if any lane's measurements or canaries
contradict the design budgets, the lane stops and reports —
budgets are falsifiable, not aspirational (design §10). Pixels
remain per-ask throughout; nothing in any lane enables
continuous screenshots or VLM grounding.
