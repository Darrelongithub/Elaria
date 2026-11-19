#!/usr/bin/env python3
"""Capture-path source check — which node capture would open, and at what volume.

Owner-runnable, read-only, stdlib only, no network, no credentials. It answers
two questions and nothing else:

1. **Which node capture would open right now** — resolved by the SAME order the
   daemon uses (`params` → `[capture] mic_target` → `[meeting] mic_target` →
   PipeWire default; see `daemon._ptt_start`), plus whether that node is listed
   by PipeWire at this moment.
2. **What is that node's capture volume**, as a percentage? The gain-reduction
   packet must record the current value BEFORE changing it so the change is
   reversible. `default_volume_percent` is reported separately, because the
   default source's level is a number the owner may still need to record.

THE REFUSAL POLICY IS A FLAG, NOT A CLAIM (`--policy`):

  as-built   (default) report what this tree's daemon actually does. On the
             current base tree an unset `mic_target` falls back to the PipeWire
             default source, so `fallback_to_default 1` and
             `capture_would_refuse 0`. That is a fact about this checkout.
  f17        evaluate the owner's F17 ruling: with `mic_target` unset, capture
             is REFUSED — `refusal f17_no_node`, `capture_would_refuse 1`, and
             the default source is still reported (as a fact about the machine)
             but is never presented as something capture would use.

Why the flag instead of one hardcoded answer: a probe that asserts a ruling the
checked-out code does not implement is a lie with a straight face. `as-built`
says what happens IF you run the daemon from this tree; `f17` says what happens
once the ruling is wired. `f17_refusal_implemented` reports which tree state the
probe believes it is standing in — never inferred, always printed.

The config read is the daemon's own (`$ASSIST_CONFIG`, else
`$XDG_CONFIG_HOME/assistant/config.toml`); `config_path` / `config_found` say
which file was read, so `-1` here means "not read", never "not set". It never
writes, never sets anything, never needs the daemon.

Output is one `key value` line each; an unreadable string or number is `-1`, and
`available 0` means `pactl` is absent or failed and `reason` says which.

Usage:
  capture_source_check.py
  capture_source_check.py --config config.toml --node alsa_input...Mic1__source
  capture_source_check.py --policy f17
  capture_source_check.py --pin-line          # the exact mic_target line
  capture_source_check.py --pactl-json sources.json --pactl-info info.txt
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
POLICIES = ("as-built", "f17")

EMPTY_FAILS_TO_DISCRIMINATE = (
    "`available 0` cannot tell apart: pactl missing, pactl present but the "
    "PipeWire socket is down, or a permissions failure — the `reason` line "
    "carries whichever this run saw, and nothing about it generalises to the "
    "next run"
)


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


def resolve_node(override: str, configured: str, policy: str = "as-built"
                 ) -> tuple[str, str, int]:
    """`(node, refusal, fallback_to_default)` for the named policy.

    as-built: the daemon's real order ends at `None`, which means "let
    pw-record pick", i.e. the PipeWire default source. That is not a refusal and
    must not be printed as one.

    f17: no default-source fallback. An unnamed node is a refusal, full stop —
    so capture is never described as measuring a mic the owner did not name.
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}; expected one of {POLICIES}")
    node = override or configured
    if node:
        return node, "", 0
    if policy == "f17":
        return "", "f17_no_node", 0
    return "", "", 1


def config_home(environ: dict | None = None) -> Path:
    """Same rule as `assistant.config.config_home` — the daemon's own home.

    `environ` is a testable seam: injecting it must change EVERY variable this
    lookup reads, not just the first one, or a test that passes a fake home is
    quietly reading the real one.
    """
    env = os.environ if environ is None else environ
    value = env.get("XDG_CONFIG_HOME", "")
    return Path(value).expanduser() if value else Path.home() / ".config"


def default_config_path(environ: dict | None = None) -> Path:
    """`$ASSIST_CONFIG`, else `$XDG_CONFIG_HOME/assistant/config.toml`."""
    env = os.environ if environ is None else environ
    configured = env.get("ASSIST_CONFIG", "")
    if configured:
        return Path(configured).expanduser()
    return config_home(env) / "assistant" / "config.toml"


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
           default: str | None = None,
           policy: str = "as-built") -> dict:
    """The reading, as numbers and names. Tests pass `sources`/`default`."""
    if sources is None:
        sources, err = read_sources(pactl)
        if not sources:
            return {"available": False, "reason": err or "no sources"}
    if default is None:
        default = read_default(pactl)
    return _report_from(sources, default, config, override, policy)


def _report_from(sources: list[dict], default: str, config: Path | None,
                 override: str, policy: str = "as-built") -> dict:
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}; expected one of {POLICIES}")
    configured = configured_node_from(config)
    node, refusal, fallback = resolve_node(override, configured, policy)
    match = next((src for src in sources if src["name"] == node), None) if node else None
    default_match = next((src for src in sources if src["name"] == default), None)
    monitors = [src for src in sources if src["monitor"]]
    # What capture will really open: the named node, or the machine's default.
    effective = node or (default if fallback else "")
    return {
        "available": True,
        "policy": policy,
        "f17_refusal_implemented": 0 if policy == "as-built" else 1,
        "config_path": str(config) if config else UNKNOWN,
        "config_found": 1 if (config is not None and config.exists()) else 0,
        "configured_node": configured or UNKNOWN,
        "node": node or UNKNOWN,
        # The node capture will actually open, named — never left implicit.
        "effective_node": effective or UNKNOWN,
        "fallback_to_default": fallback,
        "capture_would_refuse": 0 if (node or fallback) else 1,
        "refusal": refusal or UNKNOWN,
        "node_found": 1 if match else 0,
        "node_is_monitor": 1 if (match and match["monitor"]) else 0,
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

    A paste-exact line beats a transcription: the answer is only as good as the
    string the owner types into `[capture]`. A `.monitor` is refused here too —
    pinning a loopback would be the flat-envelope bug made permanent.
    """
    if not node:
        return UNKNOWN
    match = next((src for src in sources if src["name"] == node), None)
    if match is None or match["monitor"]:
        return UNKNOWN
    return f'mic_target = "{node}"'


RENDER_KEYS = ("policy", "f17_refusal_implemented", "config_path", "config_found",
               "configured_node", "node", "effective_node", "fallback_to_default",
               "capture_would_refuse", "refusal", "node_found", "node_is_monitor",
               "node_is_mic1", "volume_percent", "default_source",
               "default_volume_percent", "monitor_sources", "sources")


def render(result: dict) -> str:
    lines = [f"available {1 if result.get('available') else 0}"]
    if not result.get("available"):
        lines.append(f"reason {result.get('reason') or UNKNOWN}")
        lines.append(f"note empty_fails_to_discriminate {EMPTY_FAILS_TO_DISCRIMINATE}")
        return "\n".join(lines)
    for key in RENDER_KEYS:
        lines.append(f"{key} {result[key]}")
    for index, name in enumerate(result["monitor_names"]):
        lines.append(f"monitor_source_{index} {name}")
    if result["node_found"] == 0 and result["node"] != UNKNOWN:
        lines.append("note node_not_listed_now")
    if result["fallback_to_default"]:
        lines.append("note unset_mic_target_falls_back_to_default_source")
    if result["refusal"] != UNKNOWN:
        lines.append("note refusal_means_do_not_guess_a_node")
    lines.append("note read_only")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("usage: capture_source_check.py [--config PATH] [--node NAME] "
              "[--policy as-built|f17] [--pactl BIN] [--pactl-json FILE] "
              "[--pactl-info FILE] [--pin-line] | --checksum", file=sys.stderr)
        return 2
    if argv and argv[0] == "--checksum":
        print(write_manifest())
        return 0
    args: dict[str, str] = {}
    flags = {"--pin-line"}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in flags:
            index += 1
            continue
        if token in ("--config", "--node", "--policy", "--pactl", "--pactl-json",
                     "--pactl-info"):
            if index + 1 >= len(argv):
                print(f"error value_required {token}", file=sys.stderr)
                return 2
            args[token] = argv[index + 1]
            index += 2
            continue
        print(f"error unknown_argument {token}", file=sys.stderr)
        return 2
    policy = args.get("--policy", "as-built")
    if policy not in POLICIES:
        print(f"error unknown_policy {policy}", file=sys.stderr)
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
        print(pin_line(node, sources))
        return 0
    result = report(args.get("--pactl", "pactl"), config, args.get("--node", ""),
                    sources=sources, default=default, policy=policy)
    print(render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
