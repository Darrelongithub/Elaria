# DISPATCH-BUGFIX-4 — hardware-found grounding bug (manager, 2026-11-27)

## FIX-HW2 — Agent H · `BUG-HW2` · AT-SPI window-relative extents rejected

> You are Agent H. Fix `BUG-HW2` in `bugs.md`. Proven on the
> owner's Hyprland laptop: portal screenshot healthy, AT-SPI bus
> healthy, GTK apps register — but windows report extents
> WINDOW-RELATIVE (zenity: `active=True`, extents `(0,0,300,166)`
> vs its Hyprland position elsewhere), and
> `src/assistant/_observation_linux.py:atspi()` rejects any window
> whose SCREEN extents differ from `hyprctl activewindow` bounds
> by >8 px. Result: `_elements()` returns `[]` for every real
> window; she honestly says "I couldn't find it" at visible
> buttons. Fix: (1) accept a window when its extents SIZE matches
> Hyprland's size within tolerance AND either (a) origin matches
> (true screen coords — current path) or (b) origin is ~ (0,0)
> (window-relative) — in case (b) translate the window origin and
> EVERY element rect by the Hyprland `at` origin before building
> `Element`s. (2) Keep rejecting genuine disagreements: size
> mismatch beyond tolerance, multiple candidate windows, extents
> neither screen-matching nor window-relative. No guessed
> coordinates — translation is arithmetic on two trusted sources
> (Hyprland window geometry + AT-SPI relative tree), not
> estimation. (3) The helper currently fails silently upstream
> (`_elements` errors are swallowed into `snapshot = ()` in
> `observation.capture`): journal WHY a window was rejected
> (structured reason counts) so the next hardware report is
> self-diagnosing. (4) Fixture tests `test_bug_hw2_*`: relative
> tree → correctly translated element bounds reaching `ground()`;
> size-mismatched window → still rejected; screen-coords window
> → unchanged behaviour; ambiguous → rejected. Frozen: confidence
> gates, sensitive refusals, point-only (no acting). Sync main
> first. New `arena/*` branch, merged PR or it didn't happen.
> Never edit OWNERS.yaml. End with the owner's retest script
> (zenity Cancel test, then nonexistent label, then password
> field) — his eyes close this bug.
