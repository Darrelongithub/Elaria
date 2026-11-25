# DISPATCH — NUS pointer + Claude-style mouse (research first)

Owner's product description (2026-11-25): *"When u call NUS it
overlays like a small window and if u ask it, let's say in this
screen, 'where do i delete this', it points and circles. That's
what I wanted — and in her overlay we make it stylistic with her
orb there. Mouse I want like Claude Desktop."*

Governed by `reports/PROCEDURE-NEW-IDEAS.md`: research → blueprint
→ stress → fact-check → research → bug-test → stress → final
bug-check → build. **No agent builds anything in this dispatch.**
Research deliverables only; the manager gates the build afterwards.

Platform filter for everything: **Fedora + Hyprland (Wayland)**.
X11-only solutions are evidence, not candidates. Licence decides
method: record every candidate's licence; copyleft/permissive/
proprietary determines take-code vs take-blueprint vs take-nothing.

---

## CHANNEL R1 — Agent H: find NUS and the pointing overlays

> You are Agent H, RESEARCH ONLY — write no product code. In your
> Elaria checkout read `reports/PROCEDURE-NEW-IDEAS.md` and
> `reports/DISPATCH-NUS-POINTER.md`. Task: (1) Identify the original
> "NUS" project this surface was taken from (`ui/quickshell/nus/`,
> `src/assistant/nus_surface.py` carry the name but no upstream
> reference) — find its repo, licence, and how its overlay
> pointing/circling works. If it cannot be identified with
> evidence, say so and say what you searched. (2) Survey GitHub for
> Wayland/Hyprland overlays that draw attention markers (rings,
> highlights, pointers) at model-chosen screen coordinates:
> candidates might involve wlr-layer-shell, Quickshell, GtkLayerShell,
> screen capture via grim / zwlr_screencopy / xdg-desktop-portal,
> and coordinate grounding from a vision model. For each: repo,
> licence, last activity, Wayland-native or X11, how coordinates
> are produced and drawn, and whether code or only blueprint is
> takeable. (3) Draft OUR blueprint in
> `reports/RPT-H-nus-pointer-blueprint-*.md`: ask-by-voice →
> screenshot (consent + privacy posture: what leaves the machine,
> what never does) → vision model grounds the target → orb-styled
> ring/circle drawn on the layer-shell overlay → fades. Include the
> failure table: wrong element circled, stale screenshot, multi-
> monitor coordinates, app moved mid-draw. Then run the procedure
> on your own blueprint: stress notes, fact-check of every external
> claim (with sources), bug-test list (screenshot leaking another
> app's secrets, circled phishing UI, prompt injection from screen
> text — screen content is UNTRUSTED per IF-6). Deliverable is the
> report only. PR + merge yourself. Never edit OWNERS.yaml.

## CHANNEL R2 — Agent O: Claude-Desktop-style mouse, on Wayland

> You are Agent O, RESEARCH ONLY — write no product code. In your
> Elaria checkout read `reports/PROCEDURE-NEW-IDEAS.md`,
> `src/assistant/hands/` (the consent gate your design must live
> behind), and `reports/AUDIT-20261125.md` §Hands. Task: research
> how Claude-Desktop-style computer use (see screen → move → click
> → type → verify) is implemented by open projects on Linux,
> filtered to Wayland/Hyprland: input injection via /dev/uinput /
> evdev / ydotool / wtype / Hyprland IPC (`dispatch mouse`),
> screenshots via portal/screencopy, and how existing agents
> ground click targets. For each candidate project: repo, licence,
> activity, injection mechanism, and take-code vs take-blueprint.
> Then draft OUR blueprint in
> `reports/RPT-O-mouse-blueprint-*.md`: mouse steps as new hands
> plan verbs behind the EXISTING digest-bound owner-yes gate
> (tier-3, never auto), target stated semantically in the plan
> ("the Delete button in Files") and resolved to coordinates at
> execution, screenshot-before + screenshot-after verification,
> hard refusals (unidentified targets, credential fields, payment
> UI, drags across windows). Run the procedure on your own
> blueprint: stress, fact-check with sources, bug-test (consent
> bypass via plan mutation, coordinate races, injection from
> screen text — UNTRUSTED per IF-6, runaway click loops with a
> kill condition). Report only. PR + merge yourself. Never edit
> OWNERS.yaml, never pip-install evdev, never create uinput rules.

## Manager gate after R1 + R2 land

Re-read both blueprints as their enemy (procedure step 8), merge
into one build dispatch with the take-code/take-blueprint decision
per component, THEN issue build lanes. The orb styling (her visual
identity on the ring/orb) is part of the build lane, with the
owner's eyes as its acceptance — never a sandbox claim.
