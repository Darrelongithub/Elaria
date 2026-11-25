# BUILD-1 — NUS pointer (Agent H)

This build adds a point-only, owner-authenticated `assist point` path and
connects daemon capture-state transitions to the NUS Quickshell instance.
`observation.Frame`/`Resolution` are the mouse lane's shared read-only
contract: both IDs must match; the screenshot does not authorize actions.
No input is injected and neither overlay takes keyboard focus.

**Provider cap: 0 calls, 0 tokens, $0, 0 uploaded bytes.** The registry in
this checkout does not pin an image-input role. The unidentified bbox
validator/renderer is implemented and exercised locally, but no live VLM
caller is enabled. There is no substitution through the personality tier.
A future pinned diverted-material adapter must explicitly authorize egress,
apply IF-6, bound and journal its call, and retain the same frame/snapshot
pair. Missing or ambiguous accessibility evidence therefore returns “I
couldn't find it” today. There is no voice-intent or session egress-consent
hook in this build; the owner CLI grants one local frame per invocation.

Portal Screenshot has no monitor selector. On a single output the portal
is tried first; cancellation, denial, and timeout are not bypassed. In a
multi-output layout `grim -o` selects the focused output without guessing
where that monitor falls in a portal mosaic. The portal result is unlinked
by the helper, and grim writes into a private automatically removed temp
directory. Pixels are not journaled. Known secret controls are locally
excluded; rectangle results are not inferred from AT-SPI when its window
geometry disagrees with the compositor.

## Owner laptop eye check (not run in the sandbox)

1. Install Fedora's `python3-gobject`, `at-spi2-core`, the Hyprland desktop
   portal and `grim`. Install `systemd/elaria-nus.service` into
   `~/.config/systemd/user/`, adjust `-p` and `[nus_pointer].surface_path`
   together if the checkout is not `~/Elaria`, then run
   `systemctl --user daemon-reload` and
   `systemctl --user enable --now elaria-nus.service` from the graphical
   session. Set `[nus_pointer] enabled = true` and restart `assistant.service`.
2. Start a normal listening turn. The pill should show listening while the
   daemon is listening, speaking while muted for its reply, and hide on
   release. Check that focus stays where it was before each transition.
3. Open a toolkit app that exposes an accessible named button (e.g. a GTK
   “Cancel” button). In a terminal run
   `sleep 3; assist point --allow-local-frame 'Cancel'` and switch to that
   app before the delay expires. If a portal consent prompt appears, approve
   it and check focus; changed focus during capture may require retrying.
   The violet orb and breathing ring should mark the button, with a tight
   outline at its actual bounds. The button must not activate. Check that
   the marker disappears on focus change or within 12 seconds.
4. Repeat for a nonexistent label and then for a password/PIN control. No
   ring should appear; expect “I couldn't find it”. Try a second display
   and fractional scaling; if an outline is offset, missing, or lands on
   the wrong control, this is a failed eye check, not a pass.

Sandbox tests exercise fixture capture → AT-SPI bounds → IPC → QML binding,
confidence and sensitivity refusal, and actual daemon state transitions
through a fake `qs` runner. They do not validate rendered pixels or hardware.
