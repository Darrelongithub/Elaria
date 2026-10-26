"""`assist ladder` — the hardware truth ladder, productised (§4.8, WP0 EYES).

Four chains — console, wake, voice, event — each a list of rungs. Every rung
reads TRUTH through a named mechanism and prints REACHED, STUCK or N/A with
its evidence (N/A = the rung does not apply right now; only STUCK fails a
chain):

- binds    via `hyprctl -j` (JSON, never grepped prose),
- scripts  via `test -x`,
- units    via `systemctl`,
- console surface via the journal "Configuration Loaded" proxy PLUS a
  layer-namespace check (rung E; quickshell panels are layer surfaces —
  they never appear in `hyprctl clients`, and `hyprctl layers` namespaces
  do not grep as "quickshell"),
- wake     via `assist status` fields (dictation_active, ptt_session_id,
  live-session holder list),
- event    via segment/marker counts.

The console chain is the historical A–E (`elaria-ladder console` still works
as an entry point; it runs this same productised ladder). Nothing here fixes
anything: the ladder observes, and a STUCK rung is a diagnosis, not an error
to route around.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# The console panel's layer-shell namespace (ui/quickshell/console/shell.qml).
CONSOLE_NAMESPACE = "elaria-console"
# The overlay pill's namespace (ui/quickshell/shell.qml).
OVERLAY_NAMESPACE = "elaria-overlay"


@dataclass
class Rung:
    id: str                    # "A".."E" (console chain) or a word
    question: str              # what the rung asks, in plain words
    # -> (reached, evidence). True = REACHED, False = STUCK, None = N/A
    # (the rung does not apply right now — e.g. event rung E with no event
    # running). N/A never blocks a chain; only STUCK does.
    probe: Callable[[], tuple[bool | None, str]]


@dataclass
class BindEntry:
    """One bind from `hyprctl -j binds`: its canonical key token + release flag."""
    token: str                 # "supershiftf2" style — mods resolved, joined
    release: bool              # True for `bindr`-style release binds


@dataclass
class ChainResult:
    chain: str
    rungs: list[dict] = field(default_factory=list)

    @property
    def reached(self) -> bool:
        return all(r.get("state") != "STUCK" for r in self.rungs)

    @property
    def furthest(self) -> str:
        last = None
        for row in self.rungs:
            if row.get("state") == "REACHED":
                last = row["id"]
            else:
                break
        return last or "-"


def _evaluate(chain: str, rungs: list[Rung]) -> ChainResult:
    """Call every probe once; a raising probe is a STUCK rung, never a crash.

    Tri-state (scene-1 fix): True → REACHED, False → STUCK, None → N/A.
    """
    rows: list[dict] = []
    for rung in rungs:
        try:
            reached, evidence = rung.probe()
        except Exception as exc:
            reached, evidence = False, f"probe error: {type(exc).__name__}: {exc}"
        state = ("REACHED" if reached is True
                 else "N/A" if reached is None else "STUCK")
        rows.append({"id": rung.id, "question": rung.question,
                     "reached": reached is True, "state": state,
                     "evidence": evidence})
    return ChainResult(chain, rows)


class Ladder:
    """Truth probes with injectable edges (tests never shell out)."""

    def __init__(self, config, *, runner: Callable = subprocess.run,
                 which: Callable[[str], str | None] = shutil.which,
                 status: Callable[[], dict] | None = None,
                 repo_root: Path | None = None,
                 hypr_config: Path | None = None):
        self.config = config
        self._run = runner
        self._which = which
        self._status = status
        self._repo = repo_root or Path(__file__).resolve().parents[2]
        # Hyprland config file (for $variable definitions). None = the
        # standard location; tests inject a temp file.
        self._hypr_config = hypr_config

    # -- truth mechanisms ----------------------------------------------------
    def _sh(self, argv: list[str]) -> tuple[int, str]:
        """Run a probe command; (returncode, stdout+stderr) — never raises."""
        if not argv or self._which(argv[0]) is None:
            return 127, f"{argv[0] if argv else '?'} not found"
        try:
            out = self._run(argv, capture_output=True, text=True, timeout=10)
            return out.returncode, (out.stdout or "") + (out.stderr or "")
        except Exception as exc:
            return 1, f"{type(exc).__name__}: {exc}"

    def hyprctl_json(self, command: str) -> tuple[dict | None, str]:
        """`hyprctl -j <command>` → parsed JSON or (None, why)."""
        code, text = self._sh(["hyprctl", "-j", command])
        if code != 0:
            return None, text.strip() or f"hyprctl -j {command} exited {code}"
        try:
            return json.loads(text), "ok"
        except ValueError:
            return None, f"hyprctl -j {command} did not return JSON"

    def status_fields(self) -> tuple[dict | None, str]:
        """`assist status` from the daemon socket (truth, not inference)."""
        if self._status is not None:
            try:
                return self._status(), "ok"
            except Exception as exc:
                return None, f"{type(exc).__name__}: {exc}"
        try:
            from .ipc import call

            return call(self.config.socket_path, "status", timeout=2.0), "ok"
        except Exception as exc:
            return None, f"daemon not answering: {type(exc).__name__}: {exc}"

    def journal_text(self, unit: str) -> tuple[str, str]:
        """The unit's journal for this boot (the Configuration Loaded proxy)."""
        return self._sh(["journalctl", "--user", "-u", unit, "-b",
                         "--no-pager", "-n", "200"])[1], "journalctl"

    # -- Hyprland config variables ($mainMod-style) ---------------------------
    _VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")

    def _hypr_config_files(self) -> list[Path]:
        """The Hyprland config file plus every `source =` include, cycle-safe."""
        start = self._hypr_config or (Path.home() / ".config/hypr/hyprland.conf")
        seen: set[Path] = set()
        out: list[Path] = []

        def walk(path: Path) -> None:
            try:
                resolved = path.expanduser().resolve()
            except Exception:
                return
            if resolved in seen or not resolved.is_file():
                return
            seen.add(resolved)
            out.append(resolved)
            try:
                text = resolved.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return
            for line in text.splitlines():
                stripped = line.split("#", 1)[0].strip()
                match = re.match(r"source\s*=\s*(.+)$", stripped)
                if match:
                    target = Path(match.group(1).strip()).expanduser()
                    if not target.is_absolute():
                        target = resolved.parent / target
                    walk(target)

        walk(start)
        return out

    def _hypr_variables(self) -> dict[str, str]:
        """Config-file variable definitions: `set = name, value` and `$name = value`.

        Scene-1 fix: `hyprctl -j binds` reports mods as WRITTEN — a
        `$mainMod SHIFT` bind never tokenised to "supershiftf2" before these
        definitions were resolved (the owner's scene-1 ladder claimed
        Win+F2 / Win+Shift+F2 / Win+Shift+F12 all ABSENT while live).
        """
        variables: dict[str, str] = {}
        for path in self._hypr_config_files():
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: S112 - an unreadable config file contributes no variables; the rung evidence reports what stays unresolved
                continue
            for line in text.splitlines():
                stripped = line.split("#", 1)[0].strip()
                match = re.match(r"set\s*=\s*([^,=]+)\s*,\s*(.*)$", stripped)
                if match:
                    variables[match.group(1).strip()] = match.group(2).strip()
                    continue
                match = re.match(r"\$([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", stripped)
                if match:
                    variables[match.group(1)] = match.group(2).strip()
        return variables

    def _expand_vars(self, text: str, variables: dict[str, str],
                     depth: int = 4) -> str:
        """`$mainMod` / `${mainMod}` → the config value (values may nest)."""
        out = text
        for _ in range(depth):
            def sub(match: re.Match) -> str:
                name = match.group(1) or match.group(2)
                return variables.get(name, match.group(0))

            new = self._VAR.sub(sub, out)
            if new == out:
                break
            out = new
        return out

    def _bind_entries(self) -> tuple[list[BindEntry], str]:
        """Every bind from `hyprctl -j binds`, or ([], why).

        Truth forms handled: `mod` as a bitmask number (real hyprctl), as a
        literal string ("SUPER SHIFT"), or as a variable string ("$mainMod
        SHIFT" — resolved against the config-file variable definitions);
        `mods` as a string or list is accepted too. One token per bind:
        "supershiftf2". Release binds (`bindr`) carry `release: true`.
        """
        data, why = self.hyprctl_json("binds")
        if data is None:
            return [], why
        variables = self._hypr_variables()
        entries: list[BindEntry] = []
        unresolved: set[str] = set()
        for entry in data if isinstance(data, list) else []:
            key = str(entry.get("key") or entry.get("bind") or "").strip()
            if not key:
                continue
            mod = entry.get("mod")
            if mod is None:
                mod = entry.get("mods")
            if isinstance(mod, (list, tuple)):
                mod = " ".join(str(m) for m in mod)
            if isinstance(mod, str):
                expanded = self._expand_vars(mod, variables)
                for name in self._VAR.findall(mod):
                    var = name[0] or name[1]
                    if var not in variables:
                        unresolved.add(f"${var}")
                mods = [m for m in re.split(r"[\s+]+", expanded) if m]
            elif isinstance(mod, int) and mod:
                mods = [name for bit, name in
                        ((1, "SHIFT"), (2, "CTRL"), (4, "ALT"), (8, "SUPER"))
                        if mod & bit]
            else:
                mods = []
            key_expanded = self._expand_vars(key, variables)
            token = ("".join(m.lower() for m in mods)
                     + key_expanded.lower()).replace(" ", "")
            release = bool(entry.get("release"))
            entries.append(BindEntry(token=token, release=release))
        why = f"{len(entries)} bind entries"
        if unresolved:
            why += f"; unresolved vars: {', '.join(sorted(unresolved))}"
        return entries, why

    @staticmethod
    def _bind_matches(keys: list[str], *want: str) -> bool:
        lowered = [k.lower().replace(" ", "") for k in keys]
        needle = "".join(want).lower().replace(" ", "")
        return any(needle == k or needle in k for k in lowered)

    @staticmethod
    def _bare_f2(entries: list[BindEntry]) -> tuple[bool, bool]:
        """(press_bare, release_bare) — bare-F2 with no modifiers.

        Forbidden = a bare-F2 press/dispatch bind. A legacy `bindr = , F2`
        release-stop is tolerated until WP3 (WARN, never STUCK).
        """
        press = any(e.token == "f2" and not e.release for e in entries)
        release = any(e.token == "f2" and e.release for e in entries)
        return press, release

    @staticmethod
    def _bare_f2_evidence(press: bool, release: bool, why: str) -> str:
        text = f"bare-F2 press bind={'PRESENT (forbidden)' if press else 'absent'}"
        if release:
            text += "; WARN legacy release-stop bind (WP3 replaces)"
        return f"{text} ({why})"

    # -- shared rung probes --------------------------------------------------
    def probe_scripts(self, *scripts: str) -> tuple[bool, str]:
        missing, present = [], []
        for name in scripts:
            if name == "quickshell":
                path = self._which("quickshell")
            elif "/" in name:
                path = name if Path(name).is_file() else None
            else:
                path = self._which(name)
            (present if path else missing).append(f"{name}={path or 'missing'}")
        return (not missing, "; ".join(present + ([f"MISSING: {', '.join(missing)}"]
                                                  if missing else [])))

    def probe_units(self, *units: str) -> tuple[bool, str]:
        rows, ok = [], True
        for unit in units:
            code_a, active = self._sh(["systemctl", "--user", "is-active", unit])
            _code_e, enabled = self._sh(["systemctl", "--user", "is-enabled", unit])
            active, enabled = active.strip(), enabled.strip()
            if code_a != 0 or active != "active":
                ok = False
            rows.append(f"{unit}: active={active or 'unknown'} enabled={enabled or 'unknown'}")
        return ok, "; ".join(rows)

    def probe_console_surface(self) -> tuple[bool, str]:
        """Rung E, rewritten (§3c): journal "Configuration Loaded" proxy PLUS
        the layer-namespace check. `hyprctl clients` is never consulted —
        quickshell panels are layer surfaces."""
        text, _ = self.journal_text("elaria-console.service")
        config_loaded = "Configuration Loaded" in text
        qml_error = bool(re.search(r"(?:error|failed)[^\n]*\.qml|\.qml[^\n]*(?:error|failed)",
                                   text, re.IGNORECASE))
        layers, why = self.hyprctl_json("layers")
        namespace_seen = False
        layer_kind = ""
        if isinstance(layers, dict):
            for entries in layers.values():
                if not isinstance(entries, dict):
                    continue
                for name, info in entries.items():
                    if name == CONSOLE_NAMESPACE or (
                            isinstance(info, dict)
                            and info.get("namespace") == CONSOLE_NAMESPACE):
                        namespace_seen = True
                        layer_kind = str(info.get("layer", "")) if isinstance(info, dict) else ""
        evidence = (
            f"journal 'Configuration Loaded'={'yes' if config_loaded else 'no'}"
            + (f"; QML error line seen={qml_error}" if qml_error else "")
            + f"; layer namespace {CONSOLE_NAMESPACE}="
            + ("present" + (f" on {layer_kind}" if layer_kind else "")
               if namespace_seen else f"ABSENT ({why})"))
        return config_loaded and namespace_seen and not qml_error, evidence

    def probe_status_fields(self, *fields: str) -> tuple[bool, str]:
        status, why = self.status_fields()
        if status is None:
            return False, why
        missing = [f for f in fields if f not in status]
        values = ", ".join(f"{f}={status.get(f)!r}" for f in fields)
        return (not missing, values + (f"; MISSING: {', '.join(missing)}" if missing else ""))

    def probe_event_counts(self) -> tuple[bool, str]:
        status, why = self.status_fields()
        if status is None:
            return False, why
        try:
            from .ipc import call

            event = call(self.config.socket_path, "event.status", timeout=2.0)
        except Exception:
            event = (status.get("event") or {}) if isinstance(status, dict) else {}
        if not isinstance(event, dict) or not event:
            return False, f"no event status readable ({why})"
        segments = event.get("segments_written", event.get("segments"))
        markers = event.get("marker_count", event.get("markers"))
        running = event.get("running")
        return True, (f"event running={running!r} segments={segments!r} "
                      f"markers={markers!r}")

    # -- chains --------------------------------------------------------------
    def console_chain(self) -> ChainResult:
        def rung_a():
            return self.probe_scripts("assist", "assistd", "quickshell")

        def rung_b():
            return self.probe_units("assistant.service", "elaria-console.service")

        def rung_c():
            entries, why = self._bind_entries()
            if not entries:
                return False, f"cannot read binds ({why})"
            raise_bind = self._bind_matches([e.token for e in entries],
                                            "SUPER", "SHIFT", "F2")
            press, release = self._bare_f2(entries)
            ok = raise_bind and not press
            return ok, (f"Win+Shift+F2 raise bind={'present' if raise_bind else 'ABSENT'}"
                        f"; {self._bare_f2_evidence(press, release, why)}")

        def rung_d():
            active, unit_evidence = self.probe_units("elaria-console.service")
            text, _ = self.journal_text("elaria-console.service")
            qml_error = bool(re.search(
                r"(?:error|failed)[^\n]*\.qml|\.qml[^\n]*(?:error|failed)",
                text, re.IGNORECASE))
            return (active and not qml_error,
                    unit_evidence + f"; QML error in journal={'yes' if qml_error else 'no'}")

        def rung_e():
            return self.probe_console_surface()

        return _evaluate("console", [
            Rung("A", "are the launcher scripts and quickshell in place?", rung_a),
            Rung("B", "are assistant and the console unit loaded?", rung_b),
            Rung("C", "is the console bind wired, with no bare-F2 bind?", rung_c),
            Rung("D", "is the console service up with clean QML?", rung_d),
            Rung("E", "is the surface registered — she is on screen?", rung_e),
        ])

    def wake_chain(self) -> ChainResult:
        def rung_a():
            entries, why = self._bind_entries()
            if not entries:
                return False, f"cannot read binds ({why})"
            tokens = [e.token for e in entries]
            press_bind = self._bind_matches(tokens, "SUPER", "F2")
            halt = self._bind_matches(tokens, "SUPER", "SHIFT", "F12")
            bare_press, bare_release = self._bare_f2(entries)
            return press_bind and halt and not bare_press, (
                f"Win+F2 press={'present' if press_bind else 'ABSENT'}"
                f"; Win+Shift+F12 halt={'present' if halt else 'ABSENT'}"
                f"; {self._bare_f2_evidence(bare_press, bare_release, why)}")

        def rung_b():
            return self.probe_scripts("assist", "assistd")

        def rung_c():
            return self.probe_units("assistant.service")

        def rung_d():
            return self.probe_status_fields("hotword", "session_ceiling_s")

        def rung_e():
            return self.probe_status_fields(
                "dictation_active", "ptt_session_id", "session_holders")

        return _evaluate("wake", [
            Rung("A", "are the PTT + halt binds wired (no bare-F2)?", rung_a),
            Rung("B", "are the assist binaries executable?", rung_b),
            Rung("C", "is the daemon unit active?", rung_c),
            Rung("D", "does status carry wake posture and the ceiling?", rung_d),
            Rung("E", "do the session-holder fields read truth?", rung_e),
        ])

    def voice_chain(self) -> ChainResult:
        def rung_a():
            return self.probe_units("assistant.service")

        def rung_b():
            return self.probe_status_fields("voice", "gemini_mode")

        def rung_c():
            status, why = self.status_fields()
            if status is None:
                return False, why
            voice = status.get("voice") or {}
            acks = voice.get("cached_acks") or []
            return bool(acks), f"cached acks={acks or 'none'} ({voice.get('reason', '')})"

        def rung_d():
            status, why = self.status_fields()
            if status is None:
                return False, why
            voice = status.get("voice") or {}
            identity = voice.get("voice_identity") or {}
            allowed = identity.get("allowed", None)
            return bool(allowed), (
                f"voice identity allowed={allowed!r} "
                f"({identity.get('effective') or identity.get('configured') or 'unknown'}); "
                f"{why}")

        def rung_e():
            status, why = self.status_fields()
            if status is None:
                return False, why
            voice = status.get("voice") or {}
            mode = voice.get("voice_mode")
            return bool(mode) and mode != "silent", f"voice_mode={mode!r} ({why})"

        return _evaluate("voice", [
            Rung("A", "is the daemon unit active?", rung_a),
            Rung("B", "does status carry voice + gemini_mode?", rung_b),
            Rung("C", "is the ack earcon cached (<300 ms path)?", rung_c),
            Rung("D", "is the voice identity the approved one?", rung_d),
            Rung("E", "is the speaking route live, not silent?", rung_e),
        ])

    def event_chain(self) -> ChainResult:
        def rung_a():
            return self.probe_scripts("assist")

        def rung_b():
            return self.probe_units("assistant.service")

        def rung_c():
            return self.probe_event_counts()

        def rung_d():
            event, why = self.status_fields()
            if event is None:
                return False, why
            holders = [h for h in (event.get("session_holders") or [])
                       if h.get("kind") == "event"]
            return True, (f"event holder rows={len(holders)}; "
                          f"segment/marker counts come from event.status ({why})")

        def rung_e():
            # Scene-1 fix: N/A when no event is running; STUCK only when an
            # event IS running and its live document is unreadable.
            status, why = self.status_fields()
            event = {}
            try:
                from .ipc import call

                event = call(self.config.socket_path, "event.status", timeout=2.0)
            except Exception:
                event = ((status or {}).get("event") or {})
            if not isinstance(event, dict) or not event:
                return None, f"N/A — no event running (event state unreadable: {why})"
            if not event.get("running"):
                return None, "N/A — no event is running"
            document = event.get("document")
            if not document:
                return False, ("event is running but no live document path "
                               "is readable")
            exists = Path(str(document)).exists()
            return exists, (f"live document {document} "
                            f"({'present' if exists else 'MISSING'})")

        return _evaluate("event", [
            Rung("A", "is the assist binary executable?", rung_a),
            Rung("B", "is the daemon unit active?", rung_b),
            Rung("C", "do segment/marker counts read truth?", rung_c),
            Rung("D", "does the daemon see the event holder?", rung_d),
            Rung("E", "does the live document exist on disk?", rung_e),
        ])

    def run_chain(self, name: str) -> ChainResult:
        chains = {"console": self.console_chain, "wake": self.wake_chain,
                  "voice": self.voice_chain, "event": self.event_chain}
        return chains[name]()

    def run(self, name: str = "all") -> list[ChainResult]:
        names = ("console", "wake", "voice", "event") if name == "all" else (name,)
        return [self.run_chain(n) for n in names]


def render(results: list[ChainResult]) -> tuple[str, bool]:
    """Plain-text report: every rung prints REACHED, STUCK or N/A with evidence.

    N/A = the rung does not apply right now (e.g. event rung E with no event
    running). Only STUCK fails a chain.
    """
    lines: list[str] = []
    all_ok = True
    for result in results:
        lines.append(f"{result.chain} chain")
        for row in result.rungs:
            state = row.get("state") or ("REACHED" if row["reached"] else "STUCK")
            if state == "STUCK":
                all_ok = False
            lines.append(
                f"{row['id']} {row['question']} — "
                f"{state}: {row['evidence']}")
        lines.append(f"furthest rung reached: {result.furthest}"
                     + ("" if result.reached else " — chain STUCK"))
        lines.append("")
    return "\n".join(lines).rstrip(), all_ok


def main(argv: list[str] | None = None) -> int:
    """Entry point for `assist ladder` and the legacy `elaria-ladder` name."""
    import argparse

    from .config import load_config

    parser = argparse.ArgumentParser(
        prog="elaria-ladder",
        description="hardware truth ladder (chains: console, wake, voice, event)")
    parser.add_argument("chain", nargs="?", default="all",
                        choices=("console", "wake", "voice", "event", "all"))
    args = parser.parse_args(argv)
    ladder = Ladder(load_config())
    text, ok = render(ladder.run(args.chain))
    print(text)
    return 0 if ok else 1
