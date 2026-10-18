"""Clipboard — wl-copy ONLY. X11 tools (xclip/xsel) fail silently on
Wayland and are deliberately not even attempted (§3.3). Absence of
wl-copy is reported in the result, never raised: dictation must still
land in the inbox on a headless box."""

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
