# DISPATCH-BUGFIX-5 — grounding residuals (manager, 2026-11-27)

## FIX-HW2B — Agent H · `BUG-HW2B` · descendant offsets + label duplicates

> You are Agent H. Fix `BUG-HW2B` in `bugs.md` — the two
> residuals your HW2 fix exposed on the owner's hardware (his
> elements dump: every element at window origin `(811,475)`;
> `Cancel` button + contained `Cancel` label → `semantic_target`
> returned None). (1) Descendant coordinates: GTK/Wayland
> `get_extents(Atspi.CoordType.SCREEN)` returns `(0,0,w,h)` for
> non-window nodes. Use WINDOW-relative extents for descendants
> (true in-window offsets), translated by the accepted window
> origin; verify against the window's own rect (descendant must
> lie within the window — reject the frame's elements, loudly
> journalled, if they escape it). Keep SCREEN handling for the
> window itself and both HW2 acceptance paths (screen-matching /
> window-relative + size match); keep rejecting true
> disagreements. (2) Name resolution: in `semantic_target`, when
> same-name matches include an actionable element (role button /
> push button / menu item / etc.) and other matches fully
> CONTAINED within it (e.g. its label child), collapse to the
> actionable element. Two genuinely distinct same-name elements
> (neither containing the other) still refuse as ambiguous.
> Sensitive-role handling unchanged — a collapsed target over a
> sensitive element still refuses downstream as before. Fixture
> tests `test_bug_hw2b_*` reproducing the owner's exact dump
> shape (dialog > panels > button+label) → Cancel resolves to
> the BUTTON's true bounds; two separate Cancel buttons → None;
> descendant escaping the window → frame rejected with reason
> journalled. Frozen: confidence gates, point-only. Sync main
> first. Merged PR or it didn't happen. Never edit OWNERS.yaml.
> End with the owner's zenity retest script.
