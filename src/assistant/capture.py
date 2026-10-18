"""PipeWire capture helpers (§3.4) — the Wayland-specific edge stays here.

Phase 0: detection + command construction (everything `assist doctor`
needs to report honest facts about the Fedora machine). Session-scoped
recording itself is Phase 1. One capture process per session when it
lands — never a process spawn per chunk.

The trap that costs people an evening (GETTING-STARTED Step 3):
`pw-record --target=` takes object.serial or node.name — NOT object.id.
Passing the ID silently records the default device. Node parsing below
keeps serial + name, and deliberately never uses the bare ID as a target.
"""

from __future__ import annotations

import re
import shutil
import subprocess


def tool_available(name: str) -> bool:
    return shutil.which(name) is not None


def parse_wpctl_status(text: str) -> dict[str, list[dict]]:
    """Extract {section: [{id, name, is_default}]} from `wpctl status`.

    Names here are display names; the record target must be resolved to
    node.name/object.serial via `wpctl inspect` on the real machine.
    """
    sections: dict[str, list[dict]] = {}
    current = None
    for line in text.splitlines():
        header = re.match(r"\s*(Sinks|Sources|Sink endpoints|Source endpoints):", line)
        if header:
            current = header.group(1)
            sections[current] = []
            continue
        entry = re.match(r"\s*([*]?\s*)(\d+)\.\s+(.+)", line)
        if entry and current:
            sections[current].append({
                "id": int(entry.group(2)),
                "is_default": "*" in entry.group(1),
                "display_name": entry.group(3).split("[")[0].strip(),
            })
    return sections


def list_nodes(runner=subprocess.run) -> dict:
    """Live node list on a Fedora box; structured 'unavailable' elsewhere."""
    if not tool_available("wpctl"):
        return {"available": False, "reason": "wpctl not found (wireplumber) — "
                "expected on the Fedora target, absent in containers"}
    try:
        out = runner(["wpctl", "status"], capture_output=True, text=True, timeout=10)
        return {"available": out.returncode == 0, "nodes": parse_wpctl_status(out.stdout)}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}


def pw_record_command(target: str, output_path: str, *, sample_rate: int = 16000) -> list[str]:
    """Build the mic-capture command. `target` MUST be node.name or
    object.serial — see module docstring. 16kHz mono PCM is what the
    Live API wants natively (§3.4)."""
    if target.isdigit() and len(target) < 4:
        raise ValueError(
            f"'{target}' looks like an object.id. pw-record --target wants "
            "object.serial or node.name — an ID silently records the default "
            "device instead of erroring (GETTING-STARTED Step 3)."
        )
    return ["pw-record", f"--target={target}", "--rate", str(sample_rate),
            "--channels", "1", output_path]


def pw_record_pcm_stream_command(target: str | None, *, sample_rate: int = 16000) -> list[str]:
    """Raw s16le PCM to stdout — what assist-voice-test consumes live."""
    command = ["pw-record", "--rate", str(sample_rate), "--channels", "1",
               "--format", "s16", "-"]
    if target:
        command.insert(1, f"--target={target}")
    return command
