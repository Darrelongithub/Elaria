# DISPATCH — Mouse, Claude-Desktop-style (STANDALONE lane)

Split out of `DISPATCH-NUS-POINTER.md` on 2026-11-25 (owner
correction: the mouse is its own lane, not a sub-channel of NUS).
Governed by `reports/PROCEDURE-NEW-IDEAS.md`: research → blueprint
→ stress → fact-check → bug-test → stress → final bug-check →
build. Research only in this dispatch.

Owner's words: *"Mouse I want it to be like Claude Desktop"* — see
screen → reason about target → move → click → type → verify.

## Manager's seed scan (2026-11-25, agents MUST fact-check this)

Lead candidate: **computer-use-linux** (agent-sh org, MIT licence
per its README — verify). It "reads accessibility trees, takes
screenshots, and drives clicks, scrolls, and keystrokes" Wayland-
first, with explicit Hyprland support (`hyprctl clients -j`,
`hyprctl dispatch focuswindow`), input via the RemoteDesktop portal
with ydotool/ydotoold (/dev/uinput) as deterministic fallback,
AT-SPI for semantic targets, screenshots via portal. Security note
from its own docs: ydotoold's socket is arbitrary-input-as-you —
0600, per-user, never system-wide. Multiple forks exist
(netherguy4, nisavid, others) — agents must identify the canonical
upstream and its activity, not a random fork.

Other seeds to check: UI grounding models (ScreenSpot-style,
UI-TARS), ydotool/wtype directly, Hyprland IPC dispatch, and what
Claude Desktop itself documents about its loop (screenshot →
coordinate → action → verify).

## CHANNEL M1 — Agent O: mouse research + blueprint

> You are Agent O, RESEARCH ONLY — write no product code. In your
> Elaria checkout read `reports/PROCEDURE-NEW-IDEAS.md`,
> `reports/DISPATCH-MOUSE.md` (including the seed scan — fact-check
> every claim in it, starting with computer-use-linux: canonical
> repo, licence file not README, last commit, Hyprland support as
> shipped not as promised), and `src/assistant/hands/` — the
> consent gate your blueprint must live BEHIND. Survey the field
> (at least: computer-use-linux, one grounding-model project, raw
> ydotool/wtype, Hyprland IPC) in a comparison table: licence,
> activity, Wayland-native?, injection path, semantic targets
> (AT-SPI) vs raw coordinates, take-code / take-blueprint /
> take-nothing per licence. Then draft OUR blueprint in
> `reports/RPT-O-mouse-blueprint-*.md`: mouse verbs as hands plan
> steps behind the existing digest-bound owner-yes (tier-3, never
> auto), semantic target in the plan resolved to coordinates at
> execution, screenshot before/after, hard refusals (unidentified
> target, credential/payment UI, cross-window drag), a kill
> condition for click loops, and ydotoold treated as holding a
> loaded weapon (socket perms, who may connect). Run the procedure
> on your own draft: stress notes, fact-check with sources,
> bug-test (plan mutation after consent, coordinate race when the
> window moves, screen-text prompt injection — UNTRUSTED per IF-6,
> replayed click plans). Report only. PR + merge yourself. Never
> edit OWNERS.yaml; never install anything system-wide.

## Manager gate

Same as NUS: I re-read the blueprint as its enemy, then write the
build dispatch. Mouse and NUS-pointer share the screenshot +
grounding layer — the two blueprints must name how they share it
instead of building it twice.
