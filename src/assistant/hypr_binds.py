"""Hyprland bind emission — Lua-first, because 0.57 deleted the legacy format.

The defect this closes (owner ruling 2026-11-15): the installer's single config
touch was written as legacy Hyprland syntax (`bind = , Escape, exec, ...`).
The owner's Hyprland 0.57 reads ONLY `hyprland.lua` — the `bind`/`bindr`
format was deleted upstream — so that line would have been silently ignored on
the owner's machine. A binder that emits a format the compositor cannot read is
worse than no binder: it looks installed.

The rule here, in order:

1. **Lua by default.** Unknown version, no `hyprctl`, no session: emit Lua.
   The current generation is Lua; the fallback must not be the dead dialect.
2. **Legacy only on positive detection of a pre-0.55 Hyprland.**
3. One emitter, one bind set. The shipped snippets in `ui/hyprland/` are
   generated from `emit_binds()` and pinned byte-for-byte, so documentation
   cannot drift from what the installer hands the owner.

`assist ptt cancel` is the F30/Escape line: a cancel is a stop with destruction
(the partial buffer is zeroized and the capture node released), and it is part
of the canonical set here so it cannot be forgotten again.
"""

from __future__ import annotations

import re
import shutil
import subprocess

#: Syntax names. `lua` is the default and the only format modern Hyprland reads.
LUA = "lua"
LEGACY = "conf"

#: The first Hyprland release whose config is Lua (`hl.bind`).
LUA_SINCE = (0, 55)

#: The canonical bind set, in emission order. `release` means push-to-talk's
#: second half; `ignore_mods` is the Lua form of the `bindri` flag and is what
#: makes the stop order-robust (scene 3b, 2026-10-26: both legacy orders leaked
#: the mic on hardware).
BINDS: tuple[dict, ...] = (
    {"chord": "SUPER + grave", "command": "assist ptt start",
     "release": False, "note": "push-to-talk: press starts"},
    {"chord": "SUPER + grave", "command": "assist ptt stop --stop-source bind",
     "release": True, "note": "push-to-talk: release stops"},
    {"chord": "Escape", "command": "assist ptt cancel",
     "release": False, "note": "F30 cancel: stop + zeroize + release the node"},
    {"chord": "SUPER + SHIFT + F12", "command": "assist halt",
     "release": False, "note": "panic switch (§4.4)"},
)


def _legacy_chord(chord: str) -> str:
    """"SUPER + grave" -> "SUPER, grave" (the .conf FIELD order)."""
    parts = [part.strip() for part in chord.split("+") if part.strip()]
    *mods, key = parts
    return f"{' '.join(mods)}, {key}"


def emit_binds(syntax: str = LUA) -> str:
    """The bind snippet for `syntax`, without a header comment.

    Anything that is not positively `LEGACY` emits Lua: the dead dialect must
    never be the accidental default.
    """
    lines: list[str] = []
    for bind in BINDS:
        if syntax == LEGACY:
            verb = "bindri" if bind["release"] else "bind"
            lines.append(f"{verb} = {_legacy_chord(bind['chord'])}, exec, "
                         f"{bind['command']}")
        else:
            line = (f'hl.bind("{bind["chord"]}", '
                    f'hl.dsp.exec_cmd("{bind["command"]}")')
            if bind["release"]:
                line += ", { release = true, ignore_mods = true }"
            else:
                line += ")"
            lines.append(line if line.endswith(")") else line + ")")
    return "\n".join(lines) + "\n"


def parse_version(text: str) -> tuple[int, int] | None:
    """`Hyprland, built from ... v0.57.1` -> (0, 57). None when unreadable."""
    match = re.search(r"v?(\d+)\.(\d+)", text or "")
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def syntax_for_version(version: tuple[int, int] | None) -> str:
    """Lua-first: only a positively-detected old Hyprland gets the legacy form."""
    if version is None:
        return LUA
    return LUA if version >= LUA_SINCE else LEGACY


def detect(runner=subprocess.run) -> dict:
    """Ask the running compositor which config syntax it reads.

    Absent `hyprctl` (container, SSH, CI) is not an error: the answer is Lua,
    with the reason stated.
    """
    if not shutil.which("hyprctl"):
        return {"present": False, "version": None, "syntax": LUA,
                "detected": False,
                "detail": "hyprctl not found — not a Hyprland session (expected "
                          "in containers/SSH); emitting Lua, the current format"}
    try:
        out = runner(["hyprctl", "version"], capture_output=True, text=True,
                     timeout=10)
    except Exception as exc:
        return {"present": True, "version": None, "syntax": LUA,
                "detected": False, "detail": f"hyprctl failed: {exc} — emitting Lua"}
    version = parse_version(out.stdout or "")
    syntax = syntax_for_version(version)
    return {
        "present": True,
        "version": f"{version[0]}.{version[1]}" if version else None,
        "syntax": syntax,
        "detected": version is not None,
        "detail": (f"Hyprland {version[0]}.{version[1]} reads "
                   f"{'Lua (hl.bind)' if syntax == LUA else 'legacy .conf'}"
                   if version else "version unreadable — emitting Lua, the "
                                   "current format"),
    }
