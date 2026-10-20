"""`assist` — the thin IPC client (§3.1, §3.9). Primary, honest interface.

Kept deliberately light (stdlib + ipc) so Hyprland binds can exec it at
~5ms. `doctor`/`cost` also work with the daemon DOWN — doctor is the
first thing you run when something breaks, so it must not depend on the
thing that might be broken (GETTING-STARTED Step 5.8).

`assist doctor` converts "I think it's set up" into facts. Since Stage A
(2026-10-20) the quota shape is read from `[quota]` in config: when the owner's
verified marker is present the real figures are printed and the old assumed
numbers are gone; without the marker the warning comes back deliberately.

Two facts still need the owner's machine:
  - Hyprland version -> Lua (0.55+) vs legacy .conf bind syntax (§3.3)
  - the exact Live model id -> `assist voice models` runs a real models.list
    and shows the voice catalogue the warm path will validate against
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

    # Quota shape — read from config, never re-invented (Step 0, 2026-10-20).
    # Once the owner's verified numbers are in [quota], the old assumed figures
    # must not be printed again: crying wolf after verification trains the user
    # to ignore the check.
    from .config import quota_is_verified, quota_rows, validate_config

    schema = validate_config(config)
    checks.append(_check(
        "config schema", schema["ok"], schema["detail"],
        warn_only=not schema["errors"]))

    quota = config.section("quota")
    if quota_is_verified(quota):
        rows = quota_rows(quota)
        def _fmt(row: dict) -> str:
            rpm = ("unlimited" if row["unlimited_rpm"] else
                   f"{row['rpm']} RPM" if row.get("rpm") not in (None, "")
                   else "RPM n/a")
            tpm = (f"{int(row['tpm']):,} TPM" if row.get("tpm") not in (None, "")
                   else "TPM n/a")
            rpd = ("unlimited" if row["unlimited_rpd"] else
                   f"{row['rpd']} RPD" if row.get("rpd") not in (None, "")
                   else "RPD n/a")
            return f"{row['model']}: {rpm} / {tpm} / {rpd}"
        checks.append(_check(
            "quota shape", True,
            f"VERIFIED {quota.get('verified_at', '')} ({quota.get('verified_source', 'owner')}): "
            + " · ".join(_fmt(row) for row in rows)
            + " — read from [quota] in config; no assumed figures printed"))
    else:
        checks.append(_check(
            "quota shape", False,
            "ASSUMED, UNVERIFIED: no verified numbers in [quota] — run the Step 0 "
            "check at aistudio.google.com/rate-limit on YOUR account, then set "
            "[quota] verified = true with rpm/tpm/rpd per model. Until then these "
            "figures are guesses and treated as such."))
    voice_model = config.voice_model()
    checks.append(_check(
        "model ids", False,
        "configured: " + ", ".join(sorted({
            config.model_for_role(r) for r in
            ("default", "organise", "cleanup", "chat", "transcribe_live",
             "transcribe_batch", "voice")}))
        + f" · voice route: {voice_model} (Live native audio)"
        + " — unverified until a live models.list (names churn, §11.3); "
          "run `assist voice models` on the owner's machine"))
    # Stage A: Flare is a LIVE voice. A TTS-preview model in this key is the
    # exact configuration that produced "Voice name Flare is not supported".
    checks.append(_check(
        "voice model", "tts" not in voice_model.lower() and "live" in voice_model.lower(),
        (f"{voice_model} — a Live model routes Flare through native audio"
         if "live" in voice_model.lower() and "tts" not in voice_model.lower() else
         f"{voice_model} is NOT a Live native-audio model. Flare is a Live voice; "
         "set [gemini] gemini_voice_model to a Live model (default "
         "gemini-3.8-live). A TTS-preview model rejects Flare with 'Voice name "
         "Flare is not supported'."),
        warn_only=False))

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

    # BUG 6: a LIVE level check — record ~1 s from the configured/default mic
    # and report bytes + peak. "The mic should work" becomes facts; a silent
    # node is named here instead of discovered as a null transcript later.
    from .capture import live_level_check

    mic_target = (config.section("capture").get("mic_target")
                  or config.section("meeting").get("mic_target") or None)
    level = live_level_check(mic_target, seconds=1.2)
    if level.get("available"):
        level_detail = (
            f"node={level.get('target')} · {level.get('bytes', 0)} bytes "
            f"({level.get('seconds', 0)}s) · peak {level.get('peak')} · "
            f"rms {level.get('rms')}"
            + (" — SIGNAL present (speak now: peak should move)"
               if level.get("signal") else
               " — digital silence: wrong node? `wpctl status`, then set "
               "[capture] mic_target (node.name, not object.id)"))
    else:
        level_detail = f"node={level.get('target')}: {level.get('reason')}"
    checks.append(_check(
        "mic level",
        bool(level.get("available") and level.get("bytes", 0) > 0),
        level_detail))

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
    identity = voice.get("voice_identity", {})
    acks = voice.get("ack_cache", {})
    # A voice that is not the canonical one is a FAILURE, not a footnote: she stays
    # silent rather than speak in it, so the doctor says so loudly (VB-4).
    voice_ok = bool(voice["available"]) and bool(identity.get("allowed", True))
    voice_detail = (
        (f"VOICE IDENTITY REFUSED — {identity.get('reason')} "
         f"(configured={identity.get('configured')}, canonical={identity.get('canonical')})\n"
         if not voice_ok else "")
        + f"{voice['voice_mode'].replace('-', ' ')} — backend={voice['backend']}, "
          f"voice={voice['voice_id']}, cached acks={voice['cached_acks'] or 'none'}: "
          f"{voice['reason']}. "
          + ("" if voice_ok else "SILENT until that is fixed — nothing is spoken.\n")
          + f"acks: {acks.get('reason', 'unknown')}\n"
          + ("legacy `tts.selected_voice` row is IGNORED while online: [gemini] voice is "
             "the only voice that speaks (the stored row describes the dormant local "
             "path)\n" if voice.get("legacy_selection_ignored_online") else ""))
    checks.append(_check(
        # A refused voice identity is a FAIL, not a warning: she is silent until
        # it is fixed, so it has to read like one (§12.9 icons).
        "voice routing", voice_ok, voice_detail + " " + (
        f"One-voice rule DEFERRED, not cancelled: {voice.get('gemini_voice')} via Gemini "
        f"native audio is the only voice; offline: {voice.get('offline_output')}; a cloud "
        f"failure is reported silence, never local audio. Local voice dormant - "
        f"{voice.get('dormant_local_voice', {}).get('enable_with', '')} to un-dormant; "
        f"endgame switch: {voice.get('switch_back')}"),
        warn_only=bool(voice["available"]) and bool(identity.get("allowed", True))))
    # VB-10: a player or recorder that outlived its daemon holds the sink and the
    # microphone, and the symptom is "the hotkey does nothing". Name the pids.
    from .proc import audio_child_names, orphaned_audio_children

    names = audio_child_names(config)
    orphans = orphaned_audio_children(names=names)
    checks.append(_check(
        "orphaned audio", not orphans,
        ("none — no audio process is parentless" if not orphans else
         "LEAKED CHILDREN: " + ", ".join(f"{o['name']}({o['pid']}) {o['cmdline'][:60]}"
                                        for o in orphans)
         + " — run `assist voice cleanup` (or restart the unit) to release the mic"),
        warn_only=False))
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
    from .voicetest import voiceprint_health, voiceprint_path

    # VB-9: a biometric template gets a real inspection, not `exists()`. Absent is
    # a warning (enrolment is the user's call); present-but-wrong is a FAILURE —
    # `load_voiceprint` would otherwise raise mid-sentence and the user would have
    # no idea the file had been broken for weeks.
    voice_test_cfg = config.section("voice_test")
    health = voiceprint_health(
        voiceprint_path(config),
        expected_dimension=voice_test_cfg.get("embedding_dim"),
        expected_model=voice_test_cfg.get("embedding_model"))
    checks.append(_check(
        "voiceprint.json", health["state"] != "absent" and health["ok"],
        (f"{health['path']}: {health['detail']}; template stays out of git (§13.10)"
         if health["state"] == "absent" else
         (f"{health['detail']}. Fix: `assist-voice-test enroll` rebuilds it and writes "
          f"0600; nothing scores against a template it cannot read."
          if not health["ok"] else
          f"{health['detail']} — parseable, dimension agrees with [voice_test] "
          f"embedding_dim, mode 0600")),
        warn_only=health["ok"]))

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
                       f"{sum(c['status'] == 'warn' for c in checks)} warning(s)"
                       + (f", {sum(c['status'] == 'fail' for c in checks)} FAILURE(S)"
                          if any(c["status"] == "fail" for c in checks) else "")}


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
        print(_forget_message(args.topic, int(out["forgotten"])))
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


def _class_command(args, config) -> int:
    """`assist class [on|off|toggle|status]` — one toggle, visible everywhere."""
    from .presence import PresenceService

    action = getattr(args, "action", "status") or "status"
    try:
        if action == "status":
            out = call(config.socket_path, "class.status", timeout=5.0)
        elif action == "toggle":
            out = call(config.socket_path, "class.toggle", timeout=5.0)
        else:
            out = call(config.socket_path, "class.set",
                       {"enabled": action == "on"}, timeout=5.0)
    except (DaemonUnavailable, RuntimeError, OSError):
        store = _local_store(config)
        presence = PresenceService(config, store)
        if action == "toggle":
            status = presence.toggle()
        elif action in ("on", "off"):
            status = presence.set_enabled(action == "on")
        else:
            status = presence.status()
        out = {"class_mode": status.as_dict(),
               "note": "stored locally; the daemon will observe it"}
        store.close()
    mode = out["class_mode"]
    if action == "status":
        print(json.dumps(out, indent=2))
    else:
        print("Class mode: " + ("ON — voice out OFF, spoken acks OFF, knocks "
                                "silent, initiative urgent-only; console fully usable"
                                if mode["enabled"] else "OFF — normal voice and initiative"))
    return 0


def _initiative(config, store=None):
    from .initiative import InitiativeService
    from .presence import PresenceService
    from .store import Store

    owned = store is None
    store = store or Store(config.db_path)
    presence = PresenceService(config, store)
    service = InitiativeService(config, store, presence=presence)
    return service, store, owned


def _knock_command(args, config) -> int:
    """`assist knock …` — the only signal that means "she wants to talk"."""
    action = getattr(args, "knock_action", None) or "list"
    if action in ("list", "status") and not getattr(args, "local", False):
        try:
            out = call(config.socket_path,
                       "knock.list" if action == "list" else "initiative.status",
                       {"status": None if getattr(args, "all", False) else "pending"},
                       timeout=5.0)
            if getattr(args, "json", False):
                print(json.dumps(out, indent=2))
                return 0
            if action == "status":
                print(json.dumps(out, indent=2))
                return 0
            knocks = out.get("knocks") or []
            if not knocks:
                print("no knocks — she has nothing with a citable reason")
            for knock in knocks:
                print(f"#{knock['id']} [{knock['kind']}/{knock['urgency']}] "
                      f"{knock['topic']}\n    reason: {knock['reason']}")
            return 0
        except (DaemonUnavailable, RuntimeError, OSError):
            pass  # the store is local and authoritative; fall through

    service, store, owned = _initiative(config)
    try:
        if action == "list":
            status = None if getattr(args, "all", False) else "pending"
            knocks = [service.get(k["id"]) if status == "pending" else k
                      for k in store.list_knocks(status, limit=100)]
            out = {"knocks": knocks, "status": service.status()}
        elif action == "status":
            out = {"initiative": service.status(),
                   "class_mode": service.presence.status().as_dict()
                   if service.presence else {}}
        elif action == "due":
            out = {"raised": service.check_due()}
        elif action == "raise":
            out = {"knock": service.raise_knock(
                topic=args.topic, reason=args.reason, kind=args.kind,
                urgency=args.urgency, referent=args.referent,
                commitment_id=args.commitment)}
        elif action == "accept":
            out = service.accept(args.id)
        elif action == "decline":
            out = service.decline(args.id)
        elif action == "later":
            out = service.later(args.id, hours=args.hours)
        elif action == "ignore":
            out = service.ignore(args.id)
        else:
            raise ValueError(f"unknown knock action {action!r}")
    except Exception as exc:
        print(_refusal_text(exc), file=sys.stderr)
        return 2
    finally:
        if owned:
            store.close()

    if getattr(args, "json", False):
        print(json.dumps(out, indent=2))
        return 0
    if action == "raise":
        print(f"knock #{out['knock']['id']} — {out['knock']['reason']}")
    elif action == "accept":
        print(f"{out['open']} · first line: {out['first_line']}")
    elif action == "decline":
        print(f"declined — no follow-up on {out['knock']['topic']!r}")
    elif action == "later":
        print(f"snoozed until {out['snoozed_until']} and written to "
              f"commitment memory (#{out['commitment']['commitment_id']})")
    elif action == "ignore":
        print(f"ignored {out['ignore_count']}×"
              + (" — topic retired" if out["retired"] else
                 f" (retires at {out['threshold']})"))
    elif action == "due":
        print(f"{out['raised'].__len__()} due follow-up(s) raised")
    else:
        print(json.dumps(out, indent=2))
    return 0


def _forget_message(topic: str, forgotten: int) -> str:
    """Say what was actually searched, not a stale no-argument promise (BH-J5)."""
    if forgotten:
        return f"Forgotten: {forgotten} fact(s) matching {topic!r}."
    return f"Forgotten: 0 fact(s) matching {topic!r}. No active fact matched."


def _refusal_text(exc: Exception) -> str:
    """One `refused:` prefix, whichever layer wrote the sentence (BH-J6)."""
    text = str(exc)
    return text if text.lower().startswith("refused") else f"refused: {text}"


def _privacy_command(args, config) -> int:
    """`assist privacy …` — awareness, not a mode.

    `status` shows whether company is present; `company`/`alone` say it directly;
    `toggle` flips it. The same words spoken to her work too ("I'm not alone").
    """
    action = getattr(args, "privacy_action", None) or "status"
    wanted = {"company": True, "alone": False}.get(action)
    try:
        if action in ("company", "alone", "toggle"):
            method = "privacy.toggle" if action == "toggle" else "privacy.set"
            params = {} if action == "toggle" else {"company": wanted}
            out = call(config.socket_path, method, params, timeout=5.0)
        else:
            out = call(config.socket_path, "privacy.status", timeout=5.0)
    except (DaemonUnavailable, RuntimeError, OSError):
        from .disclosure import DisclosureService

        store = _local_store(config)
        disclosure = DisclosureService(config, store)
        if action in ("company", "alone", "toggle"):
            status = (disclosure.toggle(source="owner command")
                      if action == "toggle" else
                      disclosure.set_company(wanted, source="owner command"))
        else:
            status = disclosure.status()
        out = {"company": status,
               "note": "stored locally; the daemon will observe it"}
        store.close()
    print(json.dumps(out, indent=2))
    return 0


def _showoff_command(args, config) -> int:
    """`assist showoff …` — owner surfaces only. Entry is voice-only by design."""
    action = getattr(args, "showoff_action", None) or "status"
    try:
        if action == "status":
            out = call(config.socket_path, "showoff.status", timeout=5.0)
        elif action == "exit":
            out = call(config.socket_path, "showoff.exit",
                       {"reason": "owner_hotkey"}, timeout=10.0)
        else:
            out = call(config.socket_path, "showoff.demo",
                       {"action": getattr(args, "demo_action", "list"),
                        "name": getattr(args, "name", None),
                        "content": getattr(args, "content", "")}, timeout=30.0)
    except (DaemonUnavailable, RuntimeError, OSError) as exc:
        if action == "status":
            out = {"showoff": {"active": False, "permissions": [],
                               "note": f"daemon unavailable: {exc}"}}
        else:
            print(f"showoff {action}: {exc}", file=sys.stderr)
            return 1
    print(json.dumps(out, indent=2))
    return 0


def _commitment_command(args, config) -> int:
    """Commitment memory: only the user (or an accepted proposal) creates one."""
    service, store, owned = _initiative(config)
    try:
        if args.commitment_action == "add":
            out = service.create_commitment(args.text, origin=args.origin)
        else:
            out = {"commitments": store.list_facts(kind="commitment")}
    except Exception as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    finally:
        if owned:
            store.close()
    print(json.dumps(out, indent=2))
    return 0


def _print_snapshot(snapshot: dict, *, messages: int = 12) -> None:
    """Human rendering of the same snapshot the QML panel binds to."""
    conversation = snapshot.get("conversation") or {}
    counts = snapshot.get("counts") or {}
    mode = snapshot.get("class_mode") or {}
    print("── Elaria · console ─────────────────────────────────────────")
    company = snapshot.get("company") or {}
    if company.get("company"):
        print("company present — secrets and private plans withheld; "
              "behaviour and ordinary memory still allowed")
    print(f"class mode: {'ON' if mode.get('enabled') else 'off'}"
          + (f" · suggestion: {mode['suggestion']}" if mode.get("suggestion") else "")
          + f" · conversation #{conversation.get('id')}"
          + f" · holding {counts.get('holding', 0)} · parked {counts.get('parked', 0)}")
    if snapshot.get("daemon", {}).get("running") is False:
        print(f"daemon down: {snapshot['daemon'].get('reason')}")
    for message in (conversation.get("messages") or [])[-messages:]:
        who = "you" if message["role"] == "user" else "elaria"
        channel = f"[{message.get('channel', 'voice')}]"
        print(f"{who} {channel}: {message['text']}")
    knocks = snapshot.get("knocks") or []
    if knocks:
        print("\nwants to talk (a knock always carries its reason):")
        for knock in knocks:
            print(f"  #{knock['id']} [{knock['urgency']}] {knock['topic']}: {knock['reason']}")
    plans = snapshot.get("pending_plans") or []
    if plans:
        print("\npending plans:")
        for plan in plans:
            print(f"  #{plan['id']} {plan['root']} · {plan['status']} "
                  f"({plan['placed']}/{plan['total']})")
    jobs = snapshot.get("job_progress") or []
    if jobs:
        print("\njob progress:")
        for job in jobs:
            print(f"  {job['label']} · {job['status']}")
    parked = snapshot.get("parked_items") or []
    if parked:
        print(f"\nparked for review: {len(parked)} item(s) — `assist review list`")
    queue = snapshot.get("offline_queue") or {}
    if queue.get("counts"):
        print("offline queue: " + ", ".join(f"{k}={v}" for k, v in sorted(queue["counts"].items())))
    holding = snapshot.get("holding") or []
    if holding:
        print("\nholding for you:")
        for item in holding:
            print(f"  #{item['id']} [{item['kind']}] {item['title']}"
                  + (f" — {item['detail']}" if item.get("detail") else ""))
    showoff = snapshot.get("showoff") or {}
    if showoff.get("active"):
        print(f"\nSHOW-OFF MODE ON — {showoff.get('announcement', '')}")
    print("─────────────────────────────────────────────────────────────")


def _talk_command(args, config) -> int:
    """`assist talk` — CLI parity with the console panel.

    One conversation: `console.say` goes through the same `_ask` handler the
    voice path uses, so a session started by voice continues here with full
    context. The panel and this command render the same daemon snapshot.
    """
    text = (getattr(args, "text", None) or "").strip()
    try:
        if text:
            result = call(config.socket_path, "console.say",
                          {"text": text}, timeout=120.0)
            print(result["reply"])
            return 0
        snapshot = call(config.socket_path, "console.state", timeout=5.0)
    except DaemonUnavailable as exc:
        print(f"assist talk: the console lives in the daemon ({exc}). "
              "Start it with: systemctl --user start assistant", file=sys.stderr)
        return 1
    except (RuntimeError, OSError) as exc:
        print(f"assist talk: {exc}", file=sys.stderr)
        return 1
    _print_snapshot(snapshot)
    print("Continue here, or /state /class on|off /company on|off /knock "
          "/accept N /decline N /later N /showoff /quit")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in ("/quit", "/exit"):
            return 0
        if line == "/help":
            print("/state · /class on|off|toggle · /company on|off · /knock · "
                  "/accept N · /decline N · /later N · /showoff status|exit · /quit")
            continue
        if line == "/state":
            try:
                _print_snapshot(call(config.socket_path, "console.state", timeout=5.0))
            except (DaemonUnavailable, RuntimeError, OSError) as exc:
                print(f"state unavailable: {exc}", file=sys.stderr)
            continue
        if line.startswith("/class"):
            parts = line.split()
            action = parts[1] if len(parts) > 1 else "status"
            try:
                if action == "status":
                    out = call(config.socket_path, "class.status", timeout=5.0)
                    print(json.dumps(out["class_mode"], indent=2))
                elif action == "toggle":
                    out = call(config.socket_path, "class.toggle", timeout=5.0)
                    print("class mode " + ("ON" if out["class_mode"]["enabled"] else "OFF"))
                else:
                    out = call(config.socket_path, "class.set",
                               {"enabled": action == "on"}, timeout=5.0)
                    print("class mode " + ("ON" if out["class_mode"]["enabled"] else "OFF"))
            except (DaemonUnavailable, RuntimeError, OSError) as exc:
                print(f"class command failed: {exc}", file=sys.stderr)
            continue
        if line.startswith("/company"):
            parts = line.split()
            action = parts[1] if len(parts) > 1 else "status"
            try:
                if action in ("on", "off"):
                    out = call(config.socket_path, "privacy.set",
                               {"company": action == "on"}, timeout=5.0)
                else:
                    out = call(config.socket_path, "privacy.status", timeout=5.0)
                print(json.dumps(out["company"], indent=2))
            except (DaemonUnavailable, RuntimeError, OSError) as exc:
                print(f"privacy command failed: {exc}", file=sys.stderr)
            continue
        if line.startswith("/knock"):
            try:
                out = call(config.socket_path, "knock.list", timeout=5.0)
                for knock in out["knocks"]:
                    print(f"#{knock['id']} [{knock['urgency']}] {knock['topic']}: "
                          f"{knock['reason']}")
                if not out["knocks"]:
                    print("no knocks — she has no reason to interrupt")
            except (DaemonUnavailable, RuntimeError, OSError) as exc:
                print(f"knock list unavailable: {exc}", file=sys.stderr)
            continue
        if line.split()[0] in ("/accept", "/decline", "/later"):
            parts = line.split()
            if len(parts) != 2 or not parts[1].lstrip("#").isdigit():
                print("usage: /accept N | /decline N | /later N")
                continue
            method = {"accept": "knock.accept", "decline": "knock.decline",
                      "later": "knock.later"}[parts[0][1:]]
            try:
                out = call(config.socket_path, method, {"id": int(parts[1].lstrip("#"))},
                           timeout=30.0)
                print(json.dumps(out, indent=2))
            except (DaemonUnavailable, RuntimeError, OSError) as exc:
                print(f"{parts[0]} failed: {exc}", file=sys.stderr)
            continue
        if line.startswith("/showoff"):
            parts = line.split()
            action = parts[1] if len(parts) > 1 else "status"
            try:
                if action in ("exit", "stop", "off"):
                    out = call(config.socket_path, "showoff.exit",
                               {"reason": "owner_stop"}, timeout=10.0)
                else:
                    out = call(config.socket_path, "showoff.status", timeout=5.0)
                print(json.dumps(out, indent=2))
            except (DaemonUnavailable, RuntimeError, OSError) as exc:
                print(f"show-off: {exc}", file=sys.stderr)
            continue
        try:
            result = call(config.socket_path, "console.say", {"text": line},
                          timeout=120.0)
            print(f"elaria [console]: {result['reply']}")
            speech = result.get("speech") or {}
            if speech.get("muted"):
                print(f"  (voice silent: {speech.get('reason', 'class mode')})")
        except (DaemonUnavailable, RuntimeError, OSError) as exc:
            print(f"assist talk: {exc}", file=sys.stderr)


def _console_command(args, config) -> int:
    if getattr(args, "follow", False):
        from .console import stream_console

        try:
            for snapshot in stream_console(config.socket_path):
                print(json.dumps(snapshot), flush=True)
        except KeyboardInterrupt:
            pass
        return 0
    try:
        snapshot = call(config.socket_path, "console.state", timeout=5.0)
    except (DaemonUnavailable, RuntimeError, OSError):
        from .console import ConsoleService
        from .presence import PresenceService

        store = _local_store(config)
        snapshot = ConsoleService(config, store,
                                  presence=PresenceService(config, store)).snapshot()
        store.close()
        snapshot.setdefault("daemon", {"running": False,
                                       "reason": "daemon down — local snapshot"})
    if getattr(args, "json", False):
        print(json.dumps(snapshot, indent=2))
    else:
        _print_snapshot(snapshot)
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
    if action == "cleanup":
        # Deliberately NOT a daemon call: reaping leftovers matters exactly when
        # the daemon is the thing that died (VB-10).
        from .proc import audio_child_names, reap_orphans

        names = audio_child_names(config)
        report = reap_orphans(names=names)
        print(json.dumps(report, indent=2))
        if report["killed"]:
            print(f"released {len(report['killed'])} orphaned audio process(es): "
                  + ", ".join(report["detail"])
                  + " — the PipeWire sink/microphone is free again")
        elif report["failed"]:
            print("could not signal: " + ", ".join(
                f"{f['name']}({f['pid']}): {f['error']}" for f in report["failed"]))
        else:
            print("no orphaned audio children: nothing is holding the sink or the mic "
                  f"(checked {'/'.join(names)})")
        return 0 if not report["remaining"] and not report["failed"] else 1
    if action == "status":
        method, params = "speech.status", {}
    elif action == "models":
        method, params = "speech.models", {}
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
                   timeout=600.0 if action in ("audition", "warm", "say") else 30.0)
    except (DaemonUnavailable, RuntimeError, OSError):
        store = _local_store(config)
        speech = SpeechService(config, store)
        try:
            if action == "status":
                out = {"voice": speech.status()}
            elif action == "models":
                from .gemini_client import GeminiClient

                out = GeminiClient(config, store).list_models()
            elif action == "warm":
                out = {"warmed": speech.warm_ack_cache(), "voice": speech.status()}
            elif action == "audition":
                out = {"audition": speech.generate_auditions(args.text)}
            elif action == "select":
                selected = speech.select_voice(args.candidate)
                out = {"selected": selected.as_dict(), "voice": speech.status()}
            else:
                out = {"speech": speech.speak(args.text, play=not args.no_play).as_dict()}
        except ValueError as exc:
            # A refused candidate/text is an ANSWER, not a crash (BUG 7 class:
            # every entry point must return, never raise into a traceback).
            print(_refusal_text(exc), file=sys.stderr)
            return 2
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
        except ValueError as exc:
            # A refused job id is an ANSWER, not a traceback (BUG 7 class).
            print(_refusal_text(exc), file=sys.stderr)
            return 2
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
    talk_p = sub.add_parser(
        "talk", help="her console: one conversation, voice + text (CLI parity)")
    talk_p.add_argument("text", nargs="?",
                        help="one console turn; omit for the interactive console")
    console_p = sub.add_parser(
        "console", help="console state: conversation, plans, parked, queue, holding")
    console_p.add_argument("--json", action="store_true")
    console_p.add_argument("--follow", action="store_true",
                           help="stream a snapshot per daemon event (Quickshell feed)")
    class_p = sub.add_parser(
        "class", help="class mode: voice out OFF, spoken acks OFF, console usable")
    class_p.add_argument("action", nargs="?", default="status",
                         choices=["on", "off", "toggle", "status"])
    knock_p = sub.add_parser(
        "knock", help="initiative: a knock always carries its stored reason")
    knock_sub = knock_p.add_subparsers(dest="knock_action")
    knock_list = knock_sub.add_parser("list", help="pending knocks (reason first)")
    knock_list.add_argument("--all", action="store_true", help="include resolved")
    knock_list.add_argument("--json", action="store_true")
    knock_list.add_argument("--local", action="store_true",
                            help="read the store directly instead of the daemon")
    knock_sub.add_parser("status", help="initiative posture (no budget, ever)")
    knock_sub.add_parser("due", help="raise follow-ups the user set in motion")
    knock_raise = knock_sub.add_parser("raise", help="raise a knock (reason required)")
    knock_raise.add_argument("--topic", required=True)
    knock_raise.add_argument("--reason", required=True)
    knock_raise.add_argument("--kind", default="follow-up",
                             choices=["follow-up", "finding", "checkin", "urgency"])
    knock_raise.add_argument("--urgency", default="normal", choices=["normal", "urgent"])
    knock_raise.add_argument("--referent", default=None)
    knock_raise.add_argument("--commitment", type=int, default=None)
    knock_raise.add_argument("--json", action="store_true")
    knock_accept = knock_sub.add_parser("accept", help="open with her reason first")
    knock_accept.add_argument("id", type=int)
    knock_accept.add_argument("--json", action="store_true")
    knock_decline = knock_sub.add_parser("decline", help="no follow-up on this topic")
    knock_decline.add_argument("id", type=int)
    knock_later = knock_sub.add_parser("later", help="snooze into commitment memory")
    knock_later.add_argument("id", type=int)
    knock_later.add_argument("--hours", type=float, default=None)
    knock_later.add_argument("--json", action="store_true")
    knock_ignore = knock_sub.add_parser("ignore", help="retire a topic after 3 ignores")
    knock_ignore.add_argument("id", type=int)
    knock_ignore.add_argument("--json", action="store_true")
    privacy_p = sub.add_parser(
        "privacy", help="disclosure awareness: is the room listening?")
    privacy_p.add_argument("privacy_action", nargs="?", default="status",
                           choices=["status", "company", "alone", "toggle"])
    showoff_p = sub.add_parser(
        "showoff", help="demo mode: owner-entered, zero standing permissions")
    showoff_sub = showoff_p.add_subparsers(dest="showoff_action")
    showoff_sub.add_parser("status", help="active? sandbox? permissions?")
    showoff_sub.add_parser("exit", help="owner hotkey / local stop")
    showoff_demo = showoff_sub.add_parser(
        "demo", help="a demonstration confined to the demo sandbox")
    showoff_demo.add_argument("--action", default="list", choices=["list", "write"])
    showoff_demo.add_argument("--name", default="demo.txt")
    showoff_demo.add_argument("--content", default="Elaria demo\n")
    commitment_p = sub.add_parser(
        "commitment", help="commitment memory: follow-ups the USER set in motion")
    commitment_sub = commitment_p.add_subparsers(dest="commitment_action")
    commitment_add = commitment_sub.add_parser("add")
    commitment_add.add_argument("text")
    commitment_add.add_argument("--origin", default="user-request",
                                choices=["user-request", "accepted-proposal",
                                         "user-later"])
    commitment_sub.add_parser("list")
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
    voice_sub.add_parser(
        "models",
        help="real models.list + voice catalogue: the exact Live model id and "
             "allowed voices (owner's machine; key needed for VERIFIED)")
    voice_sub.add_parser("warm", help="pre-synthesize the four standard acks")
    voice_sub.add_parser("cleanup",
                         help="release the mic/sink from audio processes a killed daemon left")
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
    ptt_p.add_argument("--wait", action="store_true",
                       help="for stop: also wait for the transcript (default: "
                            "acknowledge the release immediately)")
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
    forget_p = sub.add_parser("forget", help="delete facts by id or topic")
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
                from .presence import PresenceService

                status = {"running": False, "mode": "down",
                          "name": config.section("persona").get("name", "Elaria"),
                          "connectivity": connectivity.as_dict(),
                          "connectivity_mode": connectivity.effective_mode,
                          "class_mode": PresenceService(config, store).status().as_dict(),
                          "showoff": {"active": False, "permissions": []},
                          "company": {"company": False},
                          "knock": {"pending": len(store.list_knocks("pending")),
                                    "budget": "none — the reason gate is the only control",
                                    "class_mode_urgent_only":
                                        PresenceService(config, store).status().enabled},
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
                data["today"]["user_turn_calls"] = store.user_turn_calls_since(day_start_iso())
                data["today"]["housekeeping_calls"] = store.housekeeping_calls_since(day_start_iso())
                data["today"]["by_purpose"] = store.calls_by_purpose_since(day_start_iso())
                data["today"]["quota_calls"] = data["today"]["user_turn_calls"]
                data["month"]["failures_detail"] = store.failure_summary_since(
                    month_start_iso())
                # Bug 8: discards must be visible here too (daemon-down path).
                subs = []
                for row in store.list_persona_events(kind="reply_substituted",
                                                     limit=10):
                    try:
                        detail = json.loads(row.get("detail") or "{}")
                    except ValueError:
                        detail = {"reason": "unreadable"}
                    detail["ts"] = row.get("ts")
                    subs.append(detail)
                data["today"]["reply_substitutions"] = subs
                store.close()
            from .cost import format_cost_report
            print(format_cost_report(data["month"], data["today"], data["quota"], data["tier"]))
            return 0

        if args.command == "class":
            return _class_command(args, config)

        if args.command == "knock":
            return _knock_command(args, config)

        if args.command == "commitment":
            return _commitment_command(args, config)

        if args.command == "showoff":
            return _showoff_command(args, config)

        if args.command == "privacy":
            return _privacy_command(args, config)

        if args.command == "talk":
            return _talk_command(args, config)

        if args.command == "console":
            return _console_command(args, config)

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
            # BUG6: the release must be acknowledged at once. The transcript
            # arrives from the daemon afterwards — `ptt.result` waits for it
            # here so the terminal still prints a dictate turn, without ever
            # making the stop call itself block on Live/cleanup.
            stopped = call(config.socket_path, "ptt.stop",
                           {"speak": args.speak}, timeout=5.0)
            result = stopped.get("result")
            if result is None and stopped.get("processing"):
                try:
                    final = call(config.socket_path, "ptt.result",
                                 {"session_id": stopped.get("session_id"),
                                  "wait_s": 60.0}, timeout=75.0)
                    result = final.get("result")
                except (DaemonUnavailable, RuntimeError, OSError) as exc:
                    print(f"assist: transcript not delivered: {exc}", file=sys.stderr)
            result = result or {}
            if result.get("no_speech") and not (result.get("text") or "").strip():
                # BUG 6 fail-fast: an empty session says so clearly — the CLI
                # must never sit a full ptt.result budget on a dead capture.
                print(result.get("narration") or "no speech captured")
                if result.get("error"):
                    print(f"({result['error']})", file=sys.stderr)
                capture = result.get("capture") or {}
                if capture:
                    print(f"[capture: node={capture.get('node')} · "
                          f"bytes={capture.get('bytes')} · "
                          f"peak={capture.get('peak_rms')}]", file=sys.stderr)
            else:
                print(result.get("narration", ""))
                print(result.get("text") or result.get("error") or "(no transcript)")
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
            if action == "stop" and args.wait:
                params["wait_s"] = 90.0
            result = call(config.socket_path, f"ptt.{action}", params,
                          timeout=95.0 if (action == "stop" and args.wait) else 3.0)
            print(json.dumps(result))
            return 0
    except (DaemonUnavailable, RuntimeError, OSError) as exc:
        print(f"assist: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
