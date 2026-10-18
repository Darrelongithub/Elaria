"""`assist` — the thin IPC client (§3.1, §3.9). Primary, honest interface.

Kept deliberately light (stdlib + ipc) so Hyprland binds can exec it at
~5ms. `doctor`/`cost` also work with the daemon DOWN — doctor is the
first thing you run when something breaks, so it must not depend on the
thing that might be broken (GETTING-STARTED Step 5.8).

`assist doctor` converts "I think it's set up" into facts, including the
two facts this environment could NOT establish for the owner:
  - Hyprland version -> Lua (0.55+) vs legacy .conf bind syntax (§3.3)
  - Free-tier quota shape -> reported as ASSUMED-UNVERIFIED until checked
    at aistudio.google.com/rate-limit on the owner's account (§11, Step 0)
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import load_config, load_humour_profile
from .ipc import DaemonUnavailable, call


# --------------------------------------------------------------------------
# doctor checks — each returns (status, label, detail); status in ok/warn/fail
# --------------------------------------------------------------------------
def _check(name: str, ok: bool, detail: str, warn_only: bool = True) -> dict:
    status = "ok" if ok else ("warn" if warn_only else "fail")
    return {"check": name, "status": status, "detail": detail}


def hyprland_info(runner=subprocess.run) -> dict:
    """Parse `hyprctl version` -> config-syntax verdict (§3.3, §11.4)."""
    if not shutil.which("hyprctl"):
        return {"present": False, "detail": "hyprctl not found — not a Hyprland "
                "session (expected inside containers/SSH; run doctor on the "
                "Fedora desktop for the real answer)"}
    try:
        out = runner(["hyprctl", "version"], capture_output=True, text=True, timeout=10)
        match = re.search(r"v?(\d+)\.(\d+)", out.stdout)
        if not match:
            return {"present": True, "version": out.stdout.strip().splitlines()[0]
                    if out.stdout else "unknown", "syntax": "unknown"}
        major, minor = int(match.group(1)), int(match.group(2))
        lua = (major, minor) >= (0, 55)
        return {"present": True, "version": f"{major}.{minor}",
                "syntax": "lua (hl.bind)" if lua else "legacy .conf (bind/bindr)",
                "detail": "use the " + ("Lua" if lua else ".conf") +
                          " bind snippet from README/GETTING-STARTED Step 6"}
    except Exception as exc:
        return {"present": True, "detail": f"hyprctl failed: {exc}"}


def run_doctor(config) -> dict:
    checks: list[dict] = []
    checks.append(_check(
        "python", sys.version_info >= (3, 11),
        f"{platform.python_version()} ({sys.executable}) — Fedora target is 3.12 via uv"))
    checks.append(_check(
        "config file", config.config_found,
        f"{config.config_path} {'found' if config.config_found else 'absent — running on defaults; copy config.toml.example'}"))
    # Key: presence + permissions only. The value is NEVER printed (Step 1).
    if config.api_key_present:
        detail = f"present via {config.api_key_source}"
        if config.api_key_file_mode is not None:
            detail += f", gemini.env mode {oct(config.api_key_file_mode)}"
            if config.api_key_file_mode & 0o077:
                detail += " — TOO OPEN: chmod 600 (mentors never get credentials, §12.9)"
        checks.append(_check("api key", not (config.api_key_file_mode or 0) & 0o077, detail))
    else:
        checks.append(_check(
            "api key", False,
            "absent — GEMINI_MODE=mock, zero network (by design, §12.9). "
            "Owner only: create ~/.config/assistant/gemini.env (0600), one project, one key (§12.8)"))
    checks.append(_check(
        "gemini mode", True,
        f"{config.gemini_mode} (source: {config.gemini_mode_source})"))

    # Quota shape — the load-bearing assumption (§12.3, Step 0).
    quota = config.section("quota")
    checks.append(_check(
        "quota shape", False,
        f"ASSUMED, UNVERIFIED: Flash {quota.get('flash_rpm')} RPM / 250k TPM / ~1500 RPD; "
        f"Flash-Lite {quota.get('flash_lite_rpm')} RPM / ~1000 RPD; Live 3 concurrent / 1M TPM. "
        "VERIFY on YOUR account at aistudio.google.com/rate-limit: (1) Live models free-tier "
        "eligible, (2) exact RPM/TPM/RPD, (3) exact model IDs — then fix config.toml. "
        "If free Live is NOT available, stop: transcription falls back to batch (§12.7) "
        "and Phase 1 changes shape."))
    checks.append(_check(
        "model ids", False,
        "configured: " + ", ".join(sorted({
            config.model_for_role(r) for r in
            ("default", "organise", "cleanup", "chat", "transcribe_live", "transcribe_batch")}))
        + " — unverified until a live models.list (names churn, §11.3)"))

    hypr = hyprland_info()
    checks.append(_check(
        "hyprland", hypr["present"],
        f"{hypr.get('version', '')} {hypr.get('syntax', '')} {hypr.get('detail', '')}".strip()))
    instance = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    socket2 = Path(runtime) / "hypr" / instance / ".socket2.sock" if instance and runtime else None
    checks.append(_check(
        "hyprland event socket", bool(socket2 and socket2.exists()),
        str(socket2) if socket2 else "HYPRLAND_INSTANCE_SIGNATURE unset (not in a Hyprland session)"))

    for tool, package in (("pw-record", "pipewire-utils"), ("wpctl", "wireplumber"),
                          ("wl-copy", "wl-clipboard"), ("notify-send", "libnotify"),
                          ("uv", "uv")):
        checks.append(_check(f"tool: {tool}", shutil.which(tool) is not None,
                             f"{shutil.which(tool) or 'missing'} — Fedora: sudo dnf install {package}"))

    from .capture import list_nodes
    nodes = list_nodes()
    checks.append(_check(
        "pipewire nodes", bool(nodes.get("available")),
        ("sources: " + ", ".join(n["display_name"] for n in
         nodes.get("nodes", {}).get("Sources", [])) if nodes.get("available")
         else nodes.get("reason", "unavailable"))
        + " · capture source=config 'mic' (§10.1 open; mic-first is the blueprint recommendation)"))

    profile_path = config.humour_profile_path()
    profile = load_humour_profile(config)
    spoken = profile.get("spoken_delivery", {})
    checks.append(_check(
        "humour profile", profile_path is not None,
        (f"{profile_path} — voiceprint consistency {spoken.get('voiceprint_consistency')}, "
         f"negative corpus {spoken.get('false_trigger_corpus_hours')}h (measured baseline, §13.10)"
         if profile_path else "humour.toml not found — governor falls back to restraint")))
    voiceprint = Path.home() / "voiceprint.json"
    checks.append(_check(
        "voiceprint.json", voiceprint.exists(),
        ("present (path only — biometric template stays out of git, §13.10)"
         if voiceprint.exists() else
         "absent — enrolment pending; assist-voice-test needs it for speaker scores")))

    try:
        status = call(config.socket_path, "status", timeout=2.0)
        daemon_detail = f"running, mode={status.get('mode')}, uptime={status.get('uptime_s')}s"
        daemon_ok = True
    except (DaemonUnavailable, RuntimeError, OSError) as exc:
        daemon_detail, daemon_ok = f"down ({exc})", False
    checks.append(_check("daemon", daemon_ok, daemon_detail))

    blockers = [c for c in checks if c["status"] == "fail"]
    return {"checks": checks, "blockers": len(blockers),
            "summary": f"{sum(c['status'] == 'ok' for c in checks)}/{len(checks)} ok, "
                       f"{sum(c['status'] == 'warn' for c in checks)} warning(s)"}


def _print_doctor(report: dict) -> None:
    icons = {"ok": " OK ", "warn": "WARN", "fail": "FAIL"}
    for check in report["checks"]:
        print(f"[{icons[check['status']]}] {check['check']}: {check['detail']}")
    print(f"\n{report['summary']}. Paste this output into every bug report (§12.9).")


# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="assist", description=f"Elaria assistant CLI v{__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_p = sub.add_parser("doctor", help="honest environment check (§11)")
    doctor_p.add_argument("--json", action="store_true")
    status_p = sub.add_parser("status", help="daemon health")
    status_p.add_argument("--waybar", action="store_true", help="Waybar custom-module JSON")
    sub.add_parser("cost", help="request/token spend from the ledger")
    ask_p = sub.add_parser("ask", help="one conversational turn (governor + harness)")
    ask_p.add_argument("text")
    sub.add_parser("halt", help="panic switch (§4.4)")
    sub.add_parser("resume", help="clear the halt flag")
    ptt_p = sub.add_parser("ptt", help="push-to-talk (Phase 1 capture; ack is local now)")
    ptt_p.add_argument("action", choices=["start", "stop", "toggle"])
    args = parser.parse_args(argv)
    config = load_config()

    try:
        if args.command == "doctor":
            report = run_doctor(config)
            print(json.dumps(report, indent=2) if args.json else "", end="")
            if not args.json:
                _print_doctor(report)
            return 0 if report["blockers"] == 0 else 2

        if args.command == "status":
            try:
                status = call(config.socket_path, "status", timeout=3.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                status = {"running": False, "mode": "down",
                          "name": config.section("persona").get("name", "Elaria")}
            if args.waybar:
                state = status.get("mode", "down") if status.get("running") else "down"
                print(json.dumps({"text": f"Elaria: {state}", "class": state,
                                  "tooltip": json.dumps(status)}))
            else:
                print(json.dumps(status, indent=2))
            return 0 if status.get("running") else 1

        if args.command == "cost":
            try:
                data = call(config.socket_path, "cost", timeout=3.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                # Ledger reads fine without the daemon — cost must always answer.
                from .cost import day_start_iso, month_start_iso
                from .store import Store
                store = Store(config.db_path)
                data = {"month": store.llm_summary(month_start_iso()),
                        "today": store.llm_summary(day_start_iso()),
                        "quota": config.section("quota"),
                        "tier": config.section("privacy").get("tier", "free")}
                data["today"]["live_calls"] = store.calls_since(day_start_iso())
                store.close()
            from .cost import format_cost_report
            print(format_cost_report(data["month"], data["today"], data["quota"], data["tier"]))
            return 0

        if args.command == "ask":
            result = call(config.socket_path, "ask", {"text": args.text}, timeout=60.0)
            print(result["reply"])
            return 0

        if args.command == "halt":
            try:
                call(config.socket_path, "halt", timeout=3.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                from .safety import set_halt
                set_halt(config.socket_path.parent)  # flag file works daemon-down too
            print("Halted. The flag is honoured between every operation; `assist resume` clears it.")
            return 0

        if args.command == "resume":
            try:
                call(config.socket_path, "resume", timeout=3.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                from .safety import clear_halt
                clear_halt(config.socket_path.parent)
            print("Resumed.")
            return 0

        if args.command == "ptt":
            action = args.action
            if action == "toggle":
                action = "stop" if call(config.socket_path, "status", timeout=3.0).get("mode") == "listening" else "start"
            result = call(config.socket_path, f"ptt.{action}", timeout=3.0)
            print(json.dumps(result))
            return 0
    except (DaemonUnavailable, RuntimeError, OSError) as exc:
        print(f"assist: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
