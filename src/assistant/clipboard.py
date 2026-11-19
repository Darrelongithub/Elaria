"""Clipboard — wl-copy ONLY. X11 tools (xclip/xsel) fail silently on
Wayland and are deliberately not even attempted (§3.3). Absence of
wl-copy is reported in the result, never raised: dictation must still
land in the inbox on a headless box.

H's DECISION on this file (2026-11-19, round 1) — KEEP, it is not a stub:
`transcribe.py` calls `copy_text()` on every accepted dictation (config
`[transcribe] copy_to_clipboard`, default true), so "finish vs freeze" was a
false choice — this is a live path that was simply untested. Finished to the
tested minimum instead of frozen, and the minimum is exactly what
tests/test_h_clipboard_decision.py pins:

  * wl-copy absent  → `copied: False` + the reason, no raise (headless stays usable);
  * wl-copy present → exactly ONE subprocess call, argv `wl-copy -- <text>`;
  * wl-copy fails   → `copied: False` + the failure text, and the dictation still
    lands in the inbox (a clipboard error must never eat a transcript).

Deliberately NOT built, on-defect-only (§5 no new autonomy): clipboard *history*,
image/file formats, a paste-back action, an xclip fallback, or a daemon-side
listener on the clipboard. If any of those is wanted it needs an owner ruling
first — reading a clipboard is untrusted input, which would put this file on the
IF-6 rail, and that is not a change to sneak into a dressing lane.
"""

from __future__ import annotations

import shutil
import subprocess


def copy_text(text: str, runner=subprocess.run) -> dict:
    if not shutil.which("wl-copy"):
        return {"copied": False, "reason": "wl-copy not found (wl-clipboard) — "
                "clipboard is a Fedora/Wayland-session feature; inbox note still written"}
    try:
        runner(["wl-copy", "--", text], check=True, timeout=10)
        return {"copied": True, "reason": "wl-copy"}
    except Exception as exc:  # clipboard failure must not lose a dictation
        return {"copied": False, "reason": f"wl-copy failed: {exc}"}
