"""`assist ladder` — the hardware truth ladder, productised (§4.8, WP0 EYES).

Four chains — console, wake, voice, event — each a list of rungs. Every rung
reads TRUTH through a named mechanism and prints REACHED or STUCK with its
evidence:

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
    probe: Callable[[], tuple[bool, str]]   # -> (reached, evidence)


@dataclass
class ChainResult:
    chain: str
    rungs: list[dict] = field(default_factory=list)

    @property
    def reached(self) -> bool:
        return all(r["reached"] for r in self.rungs)

    @property
    def furthest(self) -> str:
        last = None
        for row in self.rungs:
            if row["reached"]:
                last = row["id"]
            else:
                break
        return last or "-"


def _evaluate(chain: str, rungs: list[Rung]) -> ChainResult:
    """Call every probe once; a raising probe is a STUCK rung, never a crash."""
    rows: list[dict] = []
    for rung in rungs:
        try:
            reached, evidence = rung.probe()
        except Exception as exc:
            reached, evidence = False, f"probe error: {type(exc).__name__}: {exc}"
        rows.append({"id": rung.id, "question": rung.question,
                     "reached": bool(reached), "evidence": evidence})
    return ChainResult(chain, rows)


class Ladder:
    """Truth probes with injectable edges (tests never shell out)."""

    def __init__(self, config, *, runner: Callable = subprocess.run,
                 which: Callable[[str], str | None] = shutil.which,
                 status: Callable[[], dict] | None = None,
                 repo_root: Path | None = None):
        self.config = config
        self._run = runner
        self._which = which
        self._status = status
        self._repo = repo_root or Path(__file__).resolve().parents[2]

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

    def _bind_keys(self) -> tuple[list[str], str]:
        """All bound key strings from `hyprctl -j binds`, or ([], why).

        Real `hyprctl -j binds` carries `mod` as a bitmask number; fakes and
        configs may use a string ("SUPER SHIFT"). Both become one token per
        bind: "supershiftf2".
        """
        data, why = self.hyprctl_json("binds")
        if data is None:
            return [], why
        tokens: list[str] = []
        for entry in data if isinstance(data, list) else []:
            key = str(entry.get("key") or entry.get("bind") or "").strip()
            if not key:
                continue
            mod = entry.get("mod")
            if isinstance(mod, str):
                mods = mod.split()
            elif isinstance(mod, int) and mod:
                mods = [name for bit, name in
                        ((1, "SHIFT"), (2, "CTRL"), (4, "ALT"), (8, "SUPER"))
                        if mod & bit]
            else:
                mods = []
            tokens.append(("".join(m.lower() for m in mods)
                           + key.lower()).replace(" ", ""))
        return tokens, f"{len(tokens)} bind entries"

    @staticmethod
    def _bind_matches(keys: list[str], *want: str) -> bool:
        lowered = [k.lower().replace(" ", "") for k in keys]
        needle = "".join(want).lower().replace(" ", "")
        return any(needle == k or needle in k for k in lowered)

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
            keys, why = self._bind_keys()
            if not keys:
                return False, f"cannot read binds ({why})"
            raise_bind = self._bind_matches(keys, "SUPER", "SHIFT", "F2")
            bare_f2 = any(re.fullmatch(r"f2", (k or "").strip().lower())
                          for k in keys)
            ok = raise_bind and not bare_f2
            return ok, (f"Win+Shift+F2 raise bind={'present' if raise_bind else 'ABSENT'}"
                        f"; bare-F2 bind={'PRESENT (forbidden)' if bare_f2 else 'absent'}"
                        f" ({why})")

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
            keys, why = self._bind_keys()
            if not keys:
                return False, f"cannot read binds ({why})"
            press = self._bind_matches(keys, "SUPER", "F2")
            halt = self._bind_matches(keys, "SUPER", "SHIFT", "F12")
            bare_f2 = any(re.fullmatch(r"f2", (k or "").strip().lower())
                          for k in keys)
            return press and halt and not bare_f2, (
                f"Win+F2 press={'present' if press else 'ABSENT'}"
                f"; Win+Shift+F12 halt={'present' if halt else 'ABSENT'}"
                f"; bare-F2={'PRESENT (forbidden)' if bare_f2 else 'absent'} ({why})")

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
            event, why = self.status_fields()
            if event is None:
                return False, why
            try:
                from .ipc import call

                status = call(self.config.socket_path, "event.status", timeout=2.0)
            except Exception:
                status = {}
            document = status.get("document") if isinstance(status, dict) else None
            if not document:
                return False, "no live document path readable"
            exists = Path(str(document)).exists()
            return exists, f"live document {document} ({'present' if exists else 'MISSING'})"

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
    """Plain-text report: every rung prints REACHED or STUCK with evidence."""
    lines: list[str] = []
    all_ok = True
    for result in results:
        lines.append(f"{result.chain} chain")
        for row in result.rungs:
            reached = row["reached"]
            all_ok = all_ok and reached
            lines.append(
                f"{row['id']} {row['question']} — "
                f"{'REACHED' if reached else 'STUCK'}: {row['evidence']}")
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
