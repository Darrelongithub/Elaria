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

    # Phase 7: language pinning + code-switch guard state (§12.4/§12.5).
    from .asr import code_switching_enabled, configured_languages
    from .cleanup import SW_MARKERS, load_extra_markers

    languages = configured_languages(config)
    codeswitch = code_switching_enabled(config)
    marker_count = len(SW_MARKERS | load_extra_markers(config))
    if "sw" in languages and codeswitch:
        lang_detail = (f"pinned: {languages} — code-switching guards ARMED "
                       f"({marker_count} Swahili markers, ≥50% retention gate; "
                       "bilingual batch prompt; Kiswahili intent ladder)")
    elif "sw" in languages:
        lang_detail = ("pinned: " + str(languages) + " — 'sw' present but "
                       "preserve_code_switching=false: batch prompt stays "
                       "primary-only; set it true for bilingual dictation")
    else:
        lang_detail = (f"pinned: {languages} (English first, §9). Phase 7 flip: "
                       "languages=[\"sw\",\"en\"] + preserve_code_switching=true — "
                       "guards are built and dormant until then")
    checks.append(_check("languages", True, lang_detail))

    # Phase 8: connectivity posture, ONE local voice, offline ASR + queue.
    # Doctor reads persisted preference but does not force a health probe.
    from .asr import local_asr_status
    from .modes import ModeManager
    from .store import Store as _DoctorStore
    from .tts import SpeechService

    doctor_store = _DoctorStore(config.db_path)
    try:
        connectivity = ModeManager(config, doctor_store).status(refresh=False)
        voice = SpeechService(config, doctor_store).status()
        queue_counts = doctor_store.cloud_job_counts()
    finally:
        doctor_store.close()
    checks.append(_check(
        "connectivity mode", True,
        f"preference={connectivity.preference}, effective={connectivity.effective_mode} "
        f"— {connectivity.reason}; switch with `assist mode offline|online|auto`"))
    checks.append(_check(
        "voice routing", voice["available"],
        f"{voice['voice_mode'].replace('-', ' ')} — backend={voice['backend']}, "
        f"voice={voice['voice_id']}, cached acks={voice['cached_acks'] or 'none'}: "
        f"{voice['reason']}. "
        f"One-voice rule DEFERRED, not cancelled: {voice.get('gemini_voice')} via Gemini "
        f"native audio is the only voice; offline: {voice.get('offline_output')}; a cloud "
        f"failure is reported silence, never local audio. Local voice dormant - "
        f"{voice.get('dormant_local_voice', {}).get('enable_with', '')} to un-dormant; "
        f"endgame switch: {voice.get('switch_back')}"))
    offline_asr = local_asr_status(config)
    checks.append(_check(
        "offline ASR", offline_asr["available"],
        f"engine={offline_asr['engine']}, model={offline_asr['model']} — "
        f"{offline_asr['reason']}; {offline_asr['supported_note']}"))
    checks.append(_check(
        "cloud queue", True,
        f"durable SQLite queue counts={queue_counts or 'empty'}; external actions stay approval-gated"))

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
def _local_store(config):
    from .store import Store
    return Store(config.db_path)


def _memory_command(args, config) -> int:
    from .embeddings import backfill_embeddings, make_embedder
    from .memory import Memory

    def local():
        store = _local_store(config)
        return store, Memory(store, make_embedder(config))

    if args.command == "remember":
        try:
            out = call(config.socket_path, "memory.remember",
                       {"text": args.text, "kind": args.kind}, timeout=10.0)
        except (DaemonUnavailable, RuntimeError, OSError):
            store, memory = local()
            out = {"fact_id": memory.remember(args.text, kind=args.kind)}
            store.close()
        print(f"Remembered as fact #{out['fact_id']} (stated). Inspect: assist memory")
        return 0
    if args.command == "memory":
        try:
            facts = call(config.socket_path, "memory.list",
                         {"kind": args.kind} if args.kind else {}, timeout=10.0)["facts"]
        except (DaemonUnavailable, RuntimeError, OSError):
            store, memory = local()
            facts = memory.beliefs(args.kind)
            store.close()
        for fact in facts:
            tag = f"{fact['source']}" + (f", conf {fact['confidence']}" if fact["source"] == "inferred" else "")
            print(f"#{fact['id']} [{fact['kind']}/{tag}] {fact['text']}"
                  + (f"  (evidence: {fact['evidence']})" if fact.get("evidence") else ""))
        print(f"{len(facts)} active fact(s). Delete any: assist forget <id-or-topic>")
        return 0
    if args.command == "forget":
        try:
            out = call(config.socket_path, "memory.forget",
                       {"topic": args.topic}, timeout=10.0)
        except (DaemonUnavailable, RuntimeError, OSError):
            store, memory = local()
            out = {"forgotten": memory.forget(args.topic)}
            store.close()
        print(f"Forgotten: {out['forgotten']} fact(s). No argument, as designed.")
        return 0
    # embed
    try:
        out = call(config.socket_path, "embed.run", timeout=600.0)
    except (DaemonUnavailable, RuntimeError, OSError):
        store = _local_store(config)
        embedder = make_embedder(config)
        out = {"embedded": backfill_embeddings(store, embedder), "embedder": embedder.name}
        store.close()
    print(f"Embedded {out['embedded']} chunk(s) with {out['embedder']} (local, no quota).")
    return 0


def _meeting_command(args, config) -> int:
    from pathlib import Path

    if args.meeting_action == "setup":
        from .capture import list_pw_nodes
        from .meeting import meeting_setup_text
        nodes = list_pw_nodes()
        print(meeting_setup_text(nodes, config.section("meeting").get("system_target")))
        return 0
    if args.meeting_action == "transcribe":
        from .gemini_client import GeminiClient
        from .meeting import MeetingService
        from .modes import ModeManager
        store = _local_store(config)
        manager = ModeManager(config, store)
        manager.refresh()  # one-shot CLI: no resident monitor to snapshot from
        result = MeetingService(
            config, store, GeminiClient(config, store),
            mode_manager=manager).transcribe_dual(
            Path(args.mic_wav), Path(args.system_wav), title=args.title,
            pyannote_refine=args.pyannote)
        store.close()
        print(result.transcript)
        print(f"\nNote: {result.note_path} · diarization: {result.backend}", file=sys.stderr)
        return 0
    # start / stop need the daemon (it owns the session)
    method = f"meeting.{args.meeting_action}"
    params = {"title": args.title} if args.meeting_action == "stop" else {}
    try:
        out = call(config.socket_path, method, params, timeout=900.0)
    except DaemonUnavailable as exc:
        print(f"daemon unavailable (meeting capture lives there): {exc}", file=sys.stderr)
        return 1
    if args.meeting_action == "start":
        print("Meeting capture ON (mic + system, separate channels). "
              "Stop: assist meeting stop")
    else:
        print(out.get("transcript_preview", ""))
        print(f"\nNote: {out.get('note_path')} · turns: {out.get('turns')} · "
              f"{out.get('backend')}")

    return 0


def _mode_command(args, config) -> int:
    value = getattr(args, "mode_value", None)
    try:
        if value:
            out = call(config.socket_path, "mode.set", {"mode": value}, timeout=10.0)
        else:
            out = call(config.socket_path, "mode.status", timeout=5.0)
    except (DaemonUnavailable, RuntimeError, OSError):
        from .modes import ModeManager

        store = _local_store(config)
        manager = ModeManager(config, store)
        status = (manager.request_preference(value) if value else manager.status())
        out = {"connectivity": status.as_dict(), "cloud_queue": store.cloud_job_counts(),
               "note": "stored locally; daemon will observe it"}
        store.close()
    print(json.dumps(out, indent=2))
    return 0


def _voice_command(args, config) -> int:
    from .tts import SpeechService

    action = args.voice_action
    if action == "status":
        method, params = "speech.status", {}
    elif action == "warm":
        method, params = "speech.warm", {}
    elif action == "audition":
        method, params = "speech.audition", ({"text": args.text} if args.text else {})
    elif action == "select":
        method, params = "speech.select", {"candidate": args.candidate}
    else:
        method, params = "speech.say", {"text": args.text, "play": not args.no_play}
    try:
        out = call(config.socket_path, method, params,
                   timeout=600.0 if action in ("audition", "warm", "say") else 15.0)
    except (DaemonUnavailable, RuntimeError, OSError):
        store = _local_store(config)
        speech = SpeechService(config, store)
        try:
            if action == "status":
                out = {"voice": speech.status()}
            elif action == "warm":
                out = {"warmed": speech.warm_ack_cache(), "voice": speech.status()}
            elif action == "audition":
                out = {"audition": speech.generate_auditions(args.text)}
            elif action == "select":
                selected = speech.select_voice(args.candidate)
                out = {"selected": selected.as_dict(), "voice": speech.status()}
            else:
                out = {"speech": speech.speak(args.text, play=not args.no_play).as_dict()}
        finally:
            store.close()
    print(json.dumps(out, indent=2))
    if action == "audition":
        for candidate in out.get("audition", {}).get("candidates", []):
            print(f"{candidate['voice_id']}: {candidate['status']} · "
                  f"{candidate.get('audio_path') or candidate.get('error', '')}")
    return 0


def _queue_command(args, config) -> int:
    action = args.queue_action
    try:
        if action == "list":
            out = call(config.socket_path, "queue.list",
                       {"status": args.status, "limit": args.limit},
                       timeout=15.0)
        elif action == "drain":
            out = call(config.socket_path, "queue.drain", timeout=900.0)
        elif action == "approve":
            out = call(config.socket_path, "queue.approve",
                       {"job_id": args.job_id}, timeout=15.0)
        else:
            out = call(config.socket_path, "queue.enqueue_external",
                       {"action": args.action_name, "description": args.description},
                       timeout=15.0)
    except (DaemonUnavailable, RuntimeError, OSError):
        from .gemini_client import GeminiClient
        from .modes import ModeManager
        from .offline_queue import CloudQueue

        store = _local_store(config)
        queue = CloudQueue(config, store, GeminiClient(config, store),
                           ModeManager(config, store))
        try:
            if action == "list":
                out = {"jobs": queue.list_jobs(args.status, args.limit),
                       "counts": store.cloud_job_counts()}
            elif action == "drain":
                out = queue.drain()
            elif action == "approve":
                out = {"job": queue.approve(args.job_id)}
            else:
                out = {"job_id": queue.enqueue_external(args.action_name, args.description),
                       "status": "awaiting_approval"}
        finally:
            store.close()
    if action == "list":
        for job in out.get("jobs", []):
            print(f"#{job['id']} [{job['status']}] {job['kind']} · {job.get('payload', {})}")
        print(f"Counts: {out.get('counts') or 'empty'}")
    else:
        print(json.dumps(out, indent=2))
    return 0


def _plan_command(args, config) -> int:
    """`assist plan …` — plans via daemon (async) or locally."""
    import time as _time

    if args.plan_action == "apply":
        params = {"plan_id": args.plan_id, "include_review": args.include_review,
                  "allow_tripwire": args.allow_tripwire}
        try:
            report = call(config.socket_path, "plan.apply", params, timeout=900.0)
        except (DaemonUnavailable, RuntimeError, OSError) as exc:
            if isinstance(exc, RuntimeError) and "socket" not in str(exc):
                print(f"assist: {exc}", file=sys.stderr)
                return 1
            from dataclasses import asdict

            from .executor import Executor
            store = _local_store(config)
            plan = store.get_plan(args.plan_id)
            spec = next((r for r in config.organise_roots()
                         if plan and r["path"] == plan["root"]), None)
            if spec is None:
                print("plan root not in config", file=sys.stderr)
                return 1
            try:
                report = asdict(Executor(config, store).apply_plan(
                    args.plan_id, spec, include_review=args.include_review,
                    allow_tripwire=args.allow_tripwire))
            except PermissionError as perm:
                print(f"assist: {perm}", file=sys.stderr)
                return 1
            store.close()
        print(f"Applied plan #{args.plan_id}: {report['applied']} filed, "
              f"{report['conflicts']} conflict(s) to _Conflicts, "
              f"{report['skipped']} skipped, {len(report['refused'])} refused"
              + (" [HALTED]" if report["halted"] else "")
              + (" [CAPPED]" if report["capped"] else ""))
        for refusal in report["refused"]:
            print(f"  refused: {refusal}")
        print(f"Undo any time: assist undo --plan {args.plan_id}")
        return 0

    if args.plan_action == "list":
        try:
            plans = call(config.socket_path, "plan.list", timeout=10.0)["plans"]
        except (DaemonUnavailable, RuntimeError, OSError):
            from .store import Store
            store = Store(config.db_path)
            plans = store.list_plans()
            store.close()
        for plan in plans:
            print(f"#{plan['id']} [{plan['status']}/{plan['mode']}] {plan['root']} — "
                  f"tier0 placed {plan['placed_tier0']}/{plan['total']}, "
                  f"abstained {plan['abstained']} · {plan.get('shadow_log_path') or ''}")
        return 0

    if args.plan_action == "show":
        try:
            data = call(config.socket_path, "plan.show",
                        {"plan_id": args.plan_id, "decision": args.decision}, timeout=30.0)
        except (DaemonUnavailable, RuntimeError, OSError):
            from .store import Store
            store = Store(config.db_path)
            plan = store.get_plan(args.plan_id)
            data = {"plan": plan, "items": store.plan_items(args.plan_id, args.decision)}
            store.close()
        plan = data["plan"]
        if plan is None:
            print(f"no plan {args.plan_id}", file=sys.stderr)
            return 1
        print(f"Plan #{plan['id']} [{plan['status']}] root={plan['root']} mode={plan['mode']}")
        print(f"Shadow log: {plan.get('shadow_log_path')}")
        for item in data["items"]:
            print(f"  [{item['decision']:8}] {item['src']} -> {item['dest'] or '—'} "
                  f"({item['confidence']}, {item['rule']}): {item['reason']}")
        return 0

    # build: daemon runs async (§18) — poll plan.show until ready.
    try:
        build_params = {"root": args.root, "tiers": args.tiers}
        started = call(config.socket_path, "plan.build", build_params,
                       timeout=10.0)["started"]
    except (DaemonUnavailable, RuntimeError, OSError):
        from .gemini_client import GeminiClient
        from .modes import ModeManager
        from .offline_queue import CloudQueue
        from .organiser import OrganiserService
        from .store import Store
        store = Store(config.db_path)
        client = GeminiClient(config, store)
        manager = ModeManager(config, store)
        offline = manager.status().is_offline
        service = OrganiserService(config, store, client)
        queue = CloudQueue(config, store, client, manager)
        for spec in config.organise_roots():
            if args.root and spec["path"] != args.root:
                continue
            result = service.build_plan(spec, with_llm_tiers=args.tiers and not offline)
            _print_plan_summary(result)
            if args.tiers and offline:
                job_id = queue.enqueue_plan_tiers(spec["path"], result["plan_id"])
                print(f"Offline: Tier 1/2 judgement queued as job #{job_id}.")
        store.close()
        return 0
    for entry in started:
        plan_id = entry["plan_id"]
        print(f"Building shadow plan #{plan_id} for {entry['root']}…", file=sys.stderr)
        if entry.get("tiers") == "queued-offline":
            print("Offline: Tier 0 now; Tier 1/2 judgement will be queued.", file=sys.stderr)
        while True:
            data = call(config.socket_path, "plan.show", {"plan_id": plan_id}, timeout=30.0)
            if data["plan"]["status"] != "building":
                break
            _time.sleep(0.5)
        plan = data["plan"]
        if plan["status"] == "failed":
            print(f"plan #{plan_id} failed: {plan.get('error')}", file=sys.stderr)
            return 1
        stats = json.loads(plan.get("stats_json") or "{}")
        _print_plan_summary({"plan_id": plan_id, "stats": stats,
                             "shadow_log": plan.get("shadow_log_path")})
    return 0


def _print_plan_summary(result: dict) -> None:
    stats = result["stats"]
    print(f"Shadow plan #{result['plan_id']}: Tier 0 placed "
          f"{stats['placed_tier0']} of {stats['loose_files']} loose files "
          f"({stats['tier0_placement_pct']}%, zero API calls); "
          f"{stats['abstained']} abstained for Tier 1/2 (Phase 4).")
    print(f"Nothing moved. Read and judge: {result['shadow_log']}")


def build_parser() -> argparse.ArgumentParser:
    """Every `assist` command surface, built in one place.

    Split out of `main()` so tests can construct the parser and render every
    help string without spawning a subprocess: since Python 3.14 argparse
    validates %-formatting in `help=` eagerly inside `add_argument()`, one
    unescaped `%` used to take the *entire* CLI down at construction time
    (bugs.md BH-G4). On 3.11-3.13 the same string only crashed when that one
    subcommand's `--help` was formatted, so it went unnoticed.
    """
    parser = argparse.ArgumentParser(prog="assist", description=f"Elaria assistant CLI v{__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    doctor_p = sub.add_parser("doctor", help="honest environment check (§11)")
    doctor_p.add_argument("--json", action="store_true")
    status_p = sub.add_parser("status", help="daemon health")
    status_p.add_argument("--waybar", action="store_true", help="Waybar custom-module JSON")
    status_p.add_argument("--follow", action="store_true",
                          help="with --waybar: stream a line per state change (no poll lag)")
    sub.add_parser("cost", help="request/token spend from the ledger")
    mode_p = sub.add_parser("mode", help="connectivity: show or set auto|online|offline")
    mode_p.add_argument("mode_value", nargs="?", choices=["auto", "online", "offline"])
    ask_p = sub.add_parser("ask", help="one conversational turn (governor + harness)")
    ask_p.add_argument("text")
    ask_p.add_argument("--speak", action="store_true",
                       help="speak the reply through the configured voice for this mode")
    voice_p = sub.add_parser(
        "voice", help="speech routing: status, acks, auditions (online voice is interim)")
    voice_sub = voice_p.add_subparsers(dest="voice_action", required=True)
    voice_sub.add_parser("status", help="show the single local TTS routing")
    say_p = voice_sub.add_parser("say", help="speak text through the one local voice")
    say_p.add_argument("text")
    say_p.add_argument("--no-play", action="store_true", help="synthesize only")
    voice_sub.add_parser("warm", help="pre-synthesize the four standard acks")
    audition_p = voice_sub.add_parser("audition", help="generate candidate voice samples")
    audition_p.add_argument("--text", help="custom audition script")
    select_p = voice_sub.add_parser("select", help="select the ONE canonical voice")
    select_p.add_argument("candidate")
    queue_p = sub.add_parser("queue", help="durable offline cloud-work queue")
    queue_sub = queue_p.add_subparsers(dest="queue_action", required=True)
    queue_list = queue_sub.add_parser("list")
    queue_list.add_argument("--status")
    queue_list.add_argument("--limit", type=int, default=100)
    queue_sub.add_parser("drain", help="process auto-drainable jobs (approval stays gated)")
    queue_approve = queue_sub.add_parser("approve", help="approve one gated external job")
    queue_approve.add_argument("job_id", type=int)
    queue_ext = queue_sub.add_parser("add-external", help="park an external action for approval")
    queue_ext.add_argument("action_name")
    queue_ext.add_argument("description")
    sub.add_parser("halt", help="panic switch (§4.4)")
    sub.add_parser("resume", help="clear the halt flag")
    ptt_p = sub.add_parser("ptt", help="push-to-talk (bind press/release in Hyprland)")
    ptt_p.add_argument("action", choices=["start", "stop", "toggle"])
    ptt_p.add_argument("--mode", choices=["narration", "conversation", "command"],
                       help="session mode for start; command routes via the local ladder")
    ptt_p.add_argument("--source", help="capture source override")
    ptt_p.add_argument("--speak", action="store_true",
                       help="for command stop: speak the reply locally")
    tr_p = sub.add_parser("transcribe", help="batch-transcribe a WAV (post tier, §3.6)")
    tr_p.add_argument("file")
    sub.add_parser("index", help="index configured roots (local only, shadow-safe)")
    plan_p = sub.add_parser("plan", help="shadow organisation plans (Phase 3: no writes)")
    plan_sub = plan_p.add_subparsers(dest="plan_action", required=True)
    build_p = plan_sub.add_parser("build", help="index + cascade -> plan (no writes)")
    build_p.add_argument("--root", help="only this root path")
    build_p.add_argument("--tiers", action="store_true",
                         help="also run Tier 1/2 LLM classification on abstentions")
    apply_p = plan_sub.add_parser("apply", help="EXECUTE a plan (live roots only, Phase 4)")
    apply_p.add_argument("plan_id", type=int)
    apply_p.add_argument("--include-review", action="store_true")
    # `%%` renders as one `%`. argparse %-formats every help string, and
    # since Python 3.14 it does so eagerly in add_argument() — a bare `%`
    # here is not a cosmetic typo, it is a CLI that cannot be constructed.
    apply_p.add_argument("--allow-tripwire", action="store_true",
                         help="explicitly allow moving >tripwire%% of the tree (§4.4)")
    review_p = sub.add_parser("review", help="the 0.60-0.89 queue (§4.4)")
    review_sub = review_p.add_subparsers(dest="review_action", required=True)
    review_sub.add_parser("list")
    approve_p = review_sub.add_parser("approve")
    approve_p.add_argument("item_id", type=int)
    reject_p = review_sub.add_parser("reject")
    reject_p.add_argument("item_id", type=int)
    undo_p = sub.add_parser("undo", help="reverse committed ops (itself journaled)")
    undo_p.add_argument("op_id", nargs="?", type=int)
    undo_p.add_argument("--plan", type=int)
    undo_p.add_argument("--since", help="e.g. 2h, 24h, 7d")
    verify_p = sub.add_parser("verify", help="re-walk journal destinations, check hashes")
    verify_p.add_argument("--since", help="e.g. 24h")
    show_p = plan_sub.add_parser("show", help="show a plan and its proposals")
    show_p.add_argument("plan_id", type=int)
    show_p.add_argument("--decision", choices=["auto", "review", "unsorted", "abstain"])
    plan_sub.add_parser("list", help="list recent plans")
    tax_p = sub.add_parser("taxonomy", help="bootstrap helper for §10.2")
    tax_sub = tax_p.add_subparsers(dest="taxonomy_action", required=True)
    suggest_p = tax_sub.add_parser("suggest", help="propose taxonomy from existing folders")
    suggest_p.add_argument("root")
    search_p = sub.add_parser("search", help="full-text search the local index (FTS5)")
    search_p.add_argument("query")
    rem_p = sub.add_parser("remember", help="store a stated fact (§16)")
    rem_p.add_argument("text")
    rem_p.add_argument("--kind", default="profile",
                       choices=["profile", "preference", "commitment", "relationship"])
    mem_p = sub.add_parser("memory", help="show everything believed about you (§16)")
    mem_p.add_argument("--kind")
    forget_p = sub.add_parser("forget", help="delete facts by id or topic — no argument")
    forget_p.add_argument("topic")
    sub.add_parser("embed", help="backfill local chunk embeddings (Phase 5)")
    meeting_p = sub.add_parser("meeting", help="dual-channel meeting capture (Phase 6)")
    meeting_sub = meeting_p.add_subparsers(dest="meeting_action", required=True)
    meeting_sub.add_parser("start", help="begin meeting capture (via daemon)")
    m_stop = meeting_sub.add_parser("stop", help="stop + labelled transcript")
    m_stop.add_argument("--title")
    m_tr = meeting_sub.add_parser(
        "transcribe", help="labelled transcript from two channel WAVs (rehearsal)")
    m_tr.add_argument("mic_wav")
    m_tr.add_argument("system_wav")
    m_tr.add_argument("--title")
    m_tr.add_argument("--pyannote", action="store_true",
                      help="refine far side with pyannote (extra + HF_TOKEN)")
    meeting_sub.add_parser("setup", help="PipeWire node discovery + loopback plan")
    dictate_p = sub.add_parser("dictate", help="terminal push-to-talk: Enter to stop")
    dictate_p.add_argument("--command", dest="command_flag", action="store_true",
                           help="route the final transcript through the local intent ladder")
    dictate_p.add_argument("--speak", action="store_true",
                           help="speak a command reply through the one local voice")
    events_p = sub.add_parser("events", help="stream daemon events (overlay/Waybar feed)")
    events_p.add_argument("--overlay", action="store_true",
                          help="stream pre-computed overlay states for the Quickshell pill")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
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
            if args.waybar and args.follow:
                from .waybar import stream_waybar
                try:
                    for line in stream_waybar(config.socket_path):
                        print(json.dumps(line), flush=True)
                except KeyboardInterrupt:
                    pass
                return 0
            try:
                status = call(config.socket_path, "status", timeout=3.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                from .modes import ModeManager

                store = _local_store(config)
                connectivity = ModeManager(config, store).status(refresh=False)
                status = {"running": False, "mode": "down",
                          "name": config.section("persona").get("name", "Elaria"),
                          "connectivity": connectivity.as_dict(),
                          "connectivity_mode": connectivity.effective_mode,
                          "cloud_queue": store.cloud_job_counts()}
                store.close()
            if args.waybar:
                from .waybar import format_waybar
                print(json.dumps(format_waybar(status)))
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

        if args.command == "mode":
            return _mode_command(args, config)

        if args.command == "voice":
            return _voice_command(args, config)

        if args.command == "queue":
            return _queue_command(args, config)

        if args.command == "ask":
            result = call(config.socket_path, "ask",
                          {"text": args.text, "speak": args.speak}, timeout=120.0)
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

        if args.command == "transcribe":
            try:
                result = call(config.socket_path, "transcribe.file",
                              {"path": args.file}, timeout=180.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                # Same module, no extra design (§3.6): run the service locally.
                import asyncio as _asyncio
                from pathlib import Path as _Path

                from .gemini_client import GeminiClient
                from .modes import ModeManager
                from .offline_queue import CloudQueue
                from .store import Store
                from .transcribe import DictationService
                store = Store(config.db_path)
                client = GeminiClient(config, store)
                manager = ModeManager(config, store)
                manager.refresh()  # one-shot CLI: no resident monitor
                service = DictationService(
                    config, store, client, mode_manager=manager,
                    offline_queue=CloudQueue(config, store, client, manager))
                session = _asyncio.run(service.transcribe_file(_Path(args.file).expanduser()))
                result = {"text": (session.cleaned_text
                                   if (session.cleaned_text and not session.flagged)
                                   else session.raw_text),
                          "backend": session.backend, "inbox_path": session.inbox_path}
                store.close()
            print(result.get("text", ""))
            print(f"\n[backend: {result.get('backend')} · inbox: {result.get('inbox_path')}]",
                  file=sys.stderr)
            return 0

        if args.command == "index":
            try:
                result = call(config.socket_path, "index.run", timeout=600.0)
                roots = result["roots"]
            except (DaemonUnavailable, RuntimeError, OSError):
                from .organiser import OrganiserService
                from .store import Store
                store = Store(config.db_path)
                roots = OrganiserService(config, store).index_roots()
                store.close()
            if not roots:
                print("No organise roots configured — nothing indexed. Add "
                      "[[organise.roots]] to config.toml (shadow mode, §4.3).")
            for stats in roots:
                print(json.dumps(stats, indent=2))
            return 0

        if args.command == "plan":
            return _plan_command(args, config)

        if args.command == "review":
            if args.review_action == "list":
                try:
                    items = call(config.socket_path, "review.list", timeout=30.0)["review_items"]
                except (DaemonUnavailable, RuntimeError, OSError):
                    store = _local_store(config)
                    items = [i for p in store.list_plans(5)
                             for i in store.plan_items(p["id"], "review")]
                    store.close()
                for item in items:
                    print(f"#{item['id']} ({item['confidence']}, {item['rule']}) "
                          f"{item['src']} -> {item['dest']}: {item['reason']}")
                print(f"{len(items)} item(s) waiting. approve/reject by id.")
            else:
                verdict = args.review_action
                try:
                    call(config.socket_path, "review.decide",
                         {"item_id": args.item_id, "verdict": verdict}, timeout=10.0)
                except (DaemonUnavailable, RuntimeError, OSError):
                    store = _local_store(config)
                    store.set_item_decision(args.item_id,
                                            "auto" if verdict == "approve" else "rejected")
                    store.close()
                print(f"item {args.item_id}: {verdict}d")
            return 0

        if args.command == "undo":
            params = {"op_id": args.op_id, "plan_id": args.plan, "since": args.since}
            if not any(params.values()):
                print("undo needs an op id, --plan, or --since", file=sys.stderr)
                return 2
            try:
                result = call(config.socket_path, "undo", params, timeout=900.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                from .executor import Executor, parse_since
                store = _local_store(config)
                result = Executor(config, store).undo(
                    op_id=args.op_id, plan_id=args.plan,
                    since_iso=parse_since(args.since) if args.since else None)
                store.close()
            print(f"Undone: {result['undone']} op(s). {result['note']}")
            for problem in result["problems"]:
                print(f"  problem: {problem}")
            return 0 if not result["problems"] else 1

        if args.command == "verify":
            try:
                result = call(config.socket_path, "verify",
                              {"since": args.since} if args.since else {}, timeout=300.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                from .executor import Executor, parse_since
                store = _local_store(config)
                result = Executor(config, store).verify(
                    since_iso=parse_since(args.since) if args.since else None)
                store.close()
            print(f"Verified OK: {result['verified_ok']} · problems: {len(result['problems'])}")
            for problem in result["problems"]:
                print(f"  {problem}")
            return 0 if not result["problems"] else 1

        if args.command == "taxonomy":
            from pathlib import Path as _Path

            from .planner import suggest_taxonomy
            suggestions = suggest_taxonomy(_Path(args.root).expanduser())
            print("# Proposed taxonomy (review, trim, then freeze in config.toml — §10.2):")
            print("taxonomy = [" + ", ".join(f'"{s["folder"]}"' for s in suggestions) + "]")
            for s in suggestions:
                print(f"#   {s['folder']}: {s['files_below']} file(s) below"
                      + (f" — {s['note']}" if s.get("note") else ""))
            return 0

        if args.command == "search":
            try:
                result = call(config.socket_path, "docs.search",
                              {"query": args.query}, timeout=30.0)
            except (DaemonUnavailable, RuntimeError, OSError):
                from .store import Store
                store = Store(config.db_path)
                result = {"results": store.search_documents(args.query),
                          "engine": "fts5" if store.fts5_available else "like"}
                store.close()
            for hit in result["results"]:
                print(f"{hit['path']}\n    {hit['snip']}")
            if not result["results"]:
                print("(no matches — indexed everything you expected? `assist index`)")
            return 0

        if args.command in ("remember", "memory", "forget", "embed"):
            return _memory_command(args, config)

        if args.command == "meeting":
            return _meeting_command(args, config)

        if args.command == "dictate":
            started = call(config.socket_path, "ptt.start",
                           {"mode": "command" if args.command_flag else "narration"},
                           timeout=5.0)
            note = " (SIMULATED capture — no PipeWire here)" if started.get("simulated_capture") else ""
            input(f"Listening{note}… press Enter to stop. ")
            stopped = call(config.socket_path, "ptt.stop",
                           {"speak": args.speak}, timeout=90.0)
            result = stopped.get("result") or {}
            print(result.get("narration", ""))
            print(result.get("text", result.get("error", "(no transcript)")))
            print(f"[inbox: {result.get('inbox_path')} · clipboard: "
                  f"{(result.get('clipboard') or {}).get('copied')}]", file=sys.stderr)
            return 0

        if args.command == "events":
            try:
                if args.overlay:
                    from .overlay import stream_overlay_states
                    for state in stream_overlay_states(config.socket_path):
                        print(json.dumps(state), flush=True)
                else:
                    from .ipc import subscribe_events
                    for event in subscribe_events(config.socket_path):
                        print(json.dumps(event), flush=True)
            except KeyboardInterrupt:
                pass
            return 0

        if args.command == "ptt":
            action = args.action
            if action == "toggle":
                action = "stop" if call(config.socket_path, "status", timeout=3.0).get("mode") == "listening" else "start"
            params = {}
            if action == "start":
                if args.mode:
                    params["mode"] = args.mode
                if args.source:
                    params["source"] = args.source
            elif args.speak:
                params["speak"] = True
            result = call(config.socket_path, f"ptt.{action}", params,
                          timeout=90.0 if action == "stop" else 3.0)
            print(json.dumps(result))
            return 0
    except (DaemonUnavailable, RuntimeError, OSError) as exc:
        print(f"assist: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
