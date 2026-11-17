#!/usr/bin/env python3
"""Capture-path source check — what capture opened, and at what volume.

Owner-runnable, read-only, stdlib only, no network, no credentials. It answers
the two questions the 2026-11-15 evidence left open and nothing else:

1. Which node capture would open right now and whether it would open one at
   all. **F17 (owner ruling 2026-11-15) has no default-source fallback**: with
   `[capture] mic_target` unset, capture is REFUSED, so this script prints
   `node -1`, `capture_would_refuse 1`, `refusal f17_no_node` — it never
   presents the PipeWire default as something capture would use. The default
   source is still reported, under its own name, because it is a fact about the
   machine; it is not a capture target while the node is unnamed. The node's
   monitor state answers question (b) for the 20261102 flat envelope: a steady
   loud source beside the voice (monitor/loopback of playback).
2. What is that node's capture volume right now, as a percentage? The
   gain-reduction packet must record the current value before changing it, so
   the change is reversible. `default_volume_percent` is reported separately,
   because the default source's level is still a number the owner may need to
   record even when capture refuses to use that node.

The config file is the daemon's own (`$ASSIST_CONFIG`, else
`$XDG_CONFIG_HOME/assistant/config.toml`), and `config_path` / `config_found`
say which file was read — a `-1` here means "not read", never "not set". It
never writes, never sets anything, and never needs the daemon.

Output is one `key value` line each. An unreadable string is `-1`, an
unreadable number is `-1`; `available 0` means `pactl` is absent or failed and
the `reason` line says which. `node_is_monitor 0` on a named Mic1 input is the
answer to (b) being "not a loopback" — for THIS node, at THIS moment.

Usage:
  capture_source_check.py
  capture_source_check.py --config config.toml --node alsa_input...Mic1__source
  capture_source_check.py --pin-line                 # the exact mic_target line
  capture_source_check.py --pactl-json sources.json --pactl-info info.txt  # replay
  capture_source_check.py --checksum

Integrity: `scripts/capture_source_check.py.sha256` holds this file's digest
under its repository-relative name, so `sha256sum -c
scripts/capture_source_check.py.sha256` verifies from the repository root.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

UNKNOWN = "-1"


# ---------------------------------------------------------------------------
# parsing (pure functions — the tests pin these against captured text)
# ---------------------------------------------------------------------------
def parse_json_sources(text: str) -> list[dict]:
    """`pactl -f json list sources` -> [{name, volume_percent, monitor}]."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    sources: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        percent = -1.0
        volume = item.get("volume")
        if isinstance(volume, dict):
            values = []
            for channel in volume.values():
                if isinstance(channel, dict):
                    raw = str(channel.get("value_percent", "")).strip("% ")
                    try:
                        values.append(float(raw))
                    except ValueError:
                        continue
            if values:
                percent = max(values)
        monitor = bool(item.get("monitor_of_sink")) or name.endswith(".monitor")
        sources.append({"name": name, "volume_percent": percent,
                        "monitor": monitor})
    return sources


def parse_text_sources(text: str) -> list[dict]:
    """Fallback for `pactl list sources` plain text (older pactl)."""
    sources: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("Source #"):
            if current:
                sources.append(current)
            current = {"name": "", "volume_percent": -1.0, "monitor": False}
        elif current is None:
            continue
        elif stripped.startswith("Name:"):
            current["name"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Monitor of Sink:") and \
                stripped.split(":", 1)[1].strip() not in ("", "n/a"):
            current["monitor"] = True
        elif stripped.startswith("Volume:") and current["volume_percent"] < 0:
            percents = [float(match) for match in
                        re.findall(r"(\d+(?:\.\d+)?)%", stripped)]
            if percents:
                current["volume_percent"] = max(percents)
    if current:
        sources.append(current)
    for source in sources:
        source["monitor"] = source["monitor"] or source["name"].endswith(".monitor")
    return [source for source in sources if source["name"]]


def parse_info_default(text: str) -> str:
    """`pactl info` -> `Default Source:` value ('' when absent)."""
    for line in text.splitlines():
        if line.strip().startswith("Default Source:"):
            return line.split(":", 1)[1].strip()
    return ""


def resolve_node(override: str, configured: str) -> tuple[str, str]:
    """The node capture would use, or a refusal — F17 has no default fallback.

    Returns `(node, refusal)`. A configured node (or an explicit override) is
    the node; nothing else is. The system default source is NOT a capture
    target: `audio_gateway.resolve_target` refuses on every machine, so a
    diagnostic that fell back to the default would measure a microphone the
    daemon would never open.
    """
    node = override or configured
    return (node, "") if node else ("", "f17_no_node")


def config_home() -> Path:
    """Same rule as `assistant.config.config_home` — the daemon's own home."""
    value = os.environ.get("XDG_CONFIG_HOME", "")
    return Path(value).expanduser() if value else Path.home() / ".config"


def default_config_path(environ: dict | None = None) -> Path:
    """`$ASSIST_CONFIG`, else `$XDG_CONFIG_HOME/assistant/config.toml`."""
    env = os.environ if environ is None else environ
    configured = env.get("ASSIST_CONFIG", "")
    if configured:
        return Path(configured).expanduser()
    return config_home() / "assistant" / "config.toml"


def configured_node_from(path: Path | None) -> str:
    """`[capture] mic_target` from a TOML config, or '' — never raises."""
    if path is None or not path.exists():
        return ""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - py<3.11 has no owner here
        return ""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    capture = data.get("capture")
    if not isinstance(capture, dict):
        return ""
    return str(capture.get("mic_target") or "")


# ---------------------------------------------------------------------------
# reading (the only part that touches the machine)
# ---------------------------------------------------------------------------
def _run(argv: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=10,
                              check=False)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", f"{type(exc).__name__}: {exc}"


def read_sources(pactl: str) -> tuple[list[dict], str]:
    code, out, err = _run([pactl, "-f", "json", "list", "sources"])
    if code == 0 and out.strip():
        parsed = parse_json_sources(out)
        if parsed:
            return parsed, ""
    code, out, err = _run([pactl, "list", "sources"])
    if code == 0 and out.strip():
        parsed = parse_text_sources(out)
        if parsed:
            return parsed, ""
    return [], (err.strip() or f"pactl exit {code}")


def read_default(pactl: str) -> str:
    code, out, _ = _run([pactl, "info"])
    if code != 0:
        return ""
    return parse_info_default(out)


def checksum() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def manifest_name() -> str:
    here = Path(__file__).resolve()
    return f"{here.parent.name}/{here.name}"


def write_manifest(target: Path | None = None) -> Path:
    path = target or Path(__file__).with_suffix(".py.sha256")
    path.write_text(f"{checksum()}  {manifest_name()}\n")
    return path


def report(pactl: str, config: Path | None, override: str,
           sources: list[dict] | None = None,
           default: str | None = None) -> dict:
    """The reading, as numbers and names. Tests pass `sources`/`default`."""
    if sources is None:
        sources, err = read_sources(pactl)
        if not sources:
            return {"available": False, "reason": err or "no sources"}
    if default is None:
        default = read_default(pactl)
    return _report_from(sources, default, config, override)


def _report_from(sources: list[dict], default: str, config: Path | None,
                 override: str) -> dict:
    configured = configured_node_from(config)
    node, refusal = resolve_node(override, configured)
    match = next((src for src in sources if src["name"] == node), None) if node else None
    default_match = next((src for src in sources if src["name"] == default), None)
    monitors = [src for src in sources if src["monitor"]]
    return {
        "available": True,
        "config_path": str(config) if config else UNKNOWN,
        "config_found": 1 if (config is not None and config.exists()) else 0,
        "configured_node": configured or UNKNOWN,
        "node": node or UNKNOWN,
        "capture_would_refuse": 0 if node else 1,
        "refusal": refusal or UNKNOWN,
        "node_found": 1 if match else 0,
        "node_is_monitor": 1 if (match and match["monitor"]) else 0,
        # Named after the OWNER's ruling, not a guess: F17 pins Mic1.
        "node_is_mic1": 1 if node and "mic1" in node.lower() else 0,
        "volume_percent": (f"{match['volume_percent']:.1f}"
                           if match and match["volume_percent"] >= 0 else UNKNOWN),
        "default_source": default or UNKNOWN,
        "default_volume_percent": (f"{default_match['volume_percent']:.1f}"
                                   if default_match
                                   and default_match["volume_percent"] >= 0
                                   else UNKNOWN),
        "monitor_sources": len(monitors),
        "sources": len(sources),
        "monitor_names": [src["name"] for src in monitors],
    }


def pin_line(node: str, sources: list[dict]) -> str:
    """The exact `mic_target` line for a real mic node, else -1.

    A paste-exact line beats a transcription: the Ask-13 answer is only as good
    as the string the owner types into `[capture]`. A `.monitor` is refused
    here too — pinning a loopback would be (b) made permanent.
    """
    if not node:
        return UNKNOWN
    match = next((src for src in sources if src["name"] == node), None)
    if match is None or match["monitor"]:
        return UNKNOWN
    return f'mic_target = "{node}"'


def render(result: dict) -> str:
    lines = [f"available {1 if result.get('available') else 0}"]
    if not result.get("available"):
        lines.append(f"reason {result.get('reason') or UNKNOWN}")
        return "\n".join(lines)
    for key in ("config_path", "config_found", "configured_node", "node",
                "capture_would_refuse", "refusal", "node_found",
                "node_is_monitor", "node_is_mic1", "volume_percent",
                "default_source", "default_volume_percent", "monitor_sources",
                "sources"):
        lines.append(f"{key} {result[key]}")
    for index, name in enumerate(result["monitor_names"]):
        lines.append(f"monitor_source_{index} {name}")
    if result["node_found"] == 0:
        lines.append("note node_not_listed_now")
    lines.append("note read_only")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("usage: capture_source_check.py [--config PATH] [--node NAME] "
              "[--pactl BIN] [--pactl-json FILE] [--pactl-info FILE] "
              "[--pin-line] | --checksum", file=sys.stderr)
        return 2
    if argv and argv[0] == "--checksum":
        print(write_manifest())
        return 0
    args = {}
    flags = {"--pin-line"}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in flags:
            index += 1
            continue
        if token in ("--config", "--node", "--pactl", "--pactl-json",
                     "--pactl-info"):
            if index + 1 >= len(argv):
                print(f"error value_required {token}", file=sys.stderr)
                return 2
            args[token] = argv[index + 1]
            index += 2
            continue
        print(f"error unknown_argument {token}", file=sys.stderr)
        return 2
    config = (Path(args["--config"]).expanduser() if "--config" in args
              else default_config_path())
    sources = None
    default = None
    if "--pactl-json" in args:
        sources = parse_json_sources(Path(args["--pactl-json"]).read_text(
            encoding="utf-8"))
    if "--pactl-info" in args:
        default = parse_info_default(Path(args["--pactl-info"]).read_text(
            encoding="utf-8"))
    if "--pin-line" in argv:
        if sources is None:
            sources, _ = read_sources(args.get("--pactl", "pactl"))
        node = args.get("--node") or configured_node_from(config)
        if node and not any(src["name"] == node for src in sources):
            # Not listed right now (unplugged, renamed): still a paste-exact
            # line, because it is what the owner asked to pin — but say so.
            print(f'mic_target = "{node}"', file=sys.stderr)
            print(UNKNOWN)
            return 0
        line = pin_line(node, sources)
        print(line)
        return 0
    result = report(args.get("--pactl", "pactl"), config, args.get("--node", ""),
                    sources=sources, default=default)
    print(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
