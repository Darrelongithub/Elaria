# PROCEDURE — new ideas (owner ruling, 2026-11-25, standing)

For every NEW capability, in this order. No step may be skipped, and
building is the LAST step, not the first:

1. **Find first, never scratch-first.** Look for GitHub repos or apps
   that already do exactly the thing — filtered for our platform:
   Fedora + Hyprland (Wayland). Copy their blueprint, or the whole
   code where the licence allows. (Standing rule: licence decides
   method — check the licence before admiring the code.)
2. **Make our own blueprint** from what was found: what we take,
   what we change, what we refuse, and why.
3. **Stress-test the blueprint** (where does it break at scale,
   under load, on a cold mic, on a stranger's voice?).
4. **Fact-check it** (do the referenced APIs/protocols/claims
   actually exist and behave as described?).
5. **Research it** (fill the gaps the fact-check opened).
6. **Bug-test it** (adversarial: consent bypass, replay, injection,
   fail-open paths).
7. **Stress-test it again**, with the bug-test results in hand.
8. **Final bug-check, as if you were the one who built the code** —
   read it like its author defending it, then like its enemy.
9. **Only then build** — delegated, one lane, one eye-check test.

Manager enforces the gates: a lane that arrives at "build" without
steps 1–8 evidenced in its report gets sent back, not merged.

## First capabilities under this procedure

- **NUS pointer overlay** (`reports/DISPATCH-NUS-POINTER.md`): call
  Elaria over any screen, ask "where do I delete this?", she points
  and circles it — her orb, her style. Our current `nus/shell.qml`
  pill is only a status light; the pointing/circling behaviour is
  the actual product and does not exist yet.
- **Mouse, Claude-Desktop-style** (same dispatch): see screen, move,
  click, type, verify — behind the hands consent gate, never
  beside it.
