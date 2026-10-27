"""Configuration loading — XDG paths only, no hardcoded absolutes.

Phase 0 build order #1 (GETTING-STARTED Step 5). Resolution order:
  config file:  $ASSIST_CONFIG > $XDG_CONFIG_HOME/assistant/config.toml
  API key:      $GEMINI_API_KEY > ~/.config/assistant/gemini.env (0600)
  Gemini mode:  $GEMINI_MODE > config [gemini] mode > auto
                (auto = "mock" when no key is present, "live" with a key)

The key value is never logged, never printed, and never stored in
config.toml (Step 1). Only its presence and file permissions are reported.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

VALID_MODES = ("live", "record", "mock")


def _xdg(env: str, fallback: Path) -> Path:
    value = os.environ.get(env)
    return Path(value).expanduser() if value else fallback


def config_home() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config")


def data_home() -> Path:
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")


def state_home() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state")


def runtime_dir() -> Path:
    """$XDG_RUNTIME_DIR, with a per-user /tmp fallback for headless/test envs.

    On Fedora under systemd --user this is always set (/run/user/$UID).
    The fallback exists so tests and containers can still exercise IPC;
    doctor reports which one was used.
    """
    value = os.environ.get("XDG_RUNTIME_DIR")
    if value:
        return Path(value)
    return Path(f"/tmp/assistant-{os.getuid()}")


def ensure_private_dir(path: Path) -> Path:
    """Create an application-owned directory with owner-only traversal (I5)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def canonical_voices(config) -> tuple[str, ...]:
    """`[gemini] allowed_voices`, defaulting to `("Flare",)`.

    The one-voice rule as data: the list is the whole policy, so approving a
    different voice is a config edit the owner makes on purpose (VB-4) and never
    something a stray `voice = "..."` achieves by itself.

    A value that is not a string or a list is an invalid config and
    `validate_config()`/`doctor` names the key; at runtime it falls back to the
    shipped answer rather than crashing the speech path (BH-I2). Falling back
    to Flare cannot widen the policy: no other voice can be selected by
    accident.
    """
    gemini = config.section("gemini") if config else {}
    allowed = gemini.get("allowed_voices")
    if allowed is None:
        # Absent means the shipped answer, not "whatever `voice` says": a typo in
        # `voice` must never widen the rule by itself. An explicit empty list is
        # respected as written, which refuses every voice - a loud config error.
        allowed = ["Flare"]
    if isinstance(allowed, str):
        allowed = [allowed]
    if not isinstance(allowed, (list, tuple)):
        allowed = ["Flare"]
    return tuple(str(item) for item in allowed
                 if isinstance(item, str) and item.strip())


def resolve_voice(config, requested: str | None = None) -> tuple[str, bool]:
    """(effective voice, allowed). An unapproved voice resolves to "" — refused."""
    gemini = config.section("gemini") if config else {}
    configured = str(requested or gemini.get("voice") or "Flare").strip()
    canonical = canonical_voices(config)
    matched = next((name for name in canonical if name.lower() == configured.lower()), None)
    return (matched or ""), (matched is not None)


# The Live model that owns native audio, validated against the real catalogue at
# warm time (Stage A, 2026-10-20). `gemini-3.8-live` is the GA Live model and the
# documented default for low-latency voice agents; the older
# `gemini-3.1-flash-live-preview` is the Flash Live preview. Both are checked
# against a real `models.list` before a session is opened, and the catalogue for
# the resolved model is checked at warm time, so this default is never trusted
# blindly.
DEFAULT_VOICE_MODEL = "gemini-3.8-live"

# The TTS-preview default that `model_voice` used to point at. It is the reason
# Flare was unsupported; it must never shadow the explicit key (BH-H4).
REMOVED_TTS_MODEL = "gemini-2.5-flash-preview-tts"


def voice_model(config) -> str:
    """`[gemini] gemini_voice_model`, with the old `model_voice` as an alias.

    `model_voice` used to point at a TTS-preview model, which is exactly the bug
    that made Flare unsupported. It is still read (so an owner's existing file
    does not silently revert to a default) but new configs use the explicit key,
    and the removed old default never shadows `gemini_voice_model` (BH-H4).

    Precedence is decided by *intent*, not by value equality (BH-I1): if the
    owner's file names `gemini_voice_model` (or sets it to anything other than
    the shipped default), that key wins even when a stale `model_voice` row is
    still present. Without this, a file carrying both keys kept speaking the
    legacy model while `doctor` said the new key was in charge.
    """
    gemini = config.section("gemini") if config else {}
    explicit = gemini.get("gemini_voice_model")
    legacy = gemini.get("model_voice")
    named_modern = (
        config.explicit("gemini", "gemini_voice_model")
        or (explicit is not None and str(explicit) != DEFAULT_VOICE_MODEL)
    )
    if named_modern and explicit:
        return str(explicit)
    if legacy and legacy != REMOVED_TTS_MODEL:
        return str(legacy)
    return str(explicit or legacy or DEFAULT_VOICE_MODEL)


def quota_is_verified(quota: dict) -> bool:
    """Does `[quota]` carry owner-verified numbers?

    A `verified = true` marker alone is not enough: the doctor must be able to
    read real figures from config, not print a badge over guesses. Accept either
    the marker (with per-model rows present) or a `verified_at` stamp.
    """
    if not isinstance(quota, dict):
        return False
    marked = bool(quota.get("verified") or quota.get("verified_at"))
    has_rows = isinstance(quota.get("models"), dict) and bool(quota["models"])
    has_legacy_rows = any(key.endswith("_rpd") for key in quota)
    return marked and (has_rows or has_legacy_rows)


def quota_rows(quota: dict) -> list[dict]:
    """Normalised quota rows from config — never invented here.

    Supports both the structured `[quota.models.*]` shape and the flat
    `flash_rpd` / `flash_lite_rpd` / `transcribe_*` keys. Returns only what the
    config actually carries; an absent figure is None, never a remembered guess.
    """
    if not isinstance(quota, dict):
        return []
    rows: list[dict] = []
    models = quota.get("models")
    if isinstance(models, dict):
        for name, row in models.items():
            if not isinstance(row, dict):
                continue
            rows.append({
                "model": name,
                "rpm": row.get("rpm"),
                "tpm": row.get("tpm"),
                "rpd": row.get("rpd"),
                "rpd_cap": row.get("rpd_cap"),
                "unlimited_rpm": bool(row.get("rpm") in (0, "unlimited")),
                "unlimited_rpd": bool(row.get("rpd") in (0, "unlimited")),
            })
    if rows:
        return rows
    key_map = {
        "flash": "flash",
        "flash_lite": "flash-lite",
        "transcribe_live": "transcribe-live",
        "transcribe_batch": "transcribe-batch",
    }
    for prefix, label in key_map.items():
        rpm = quota.get(f"{prefix}_rpm")
        tpm = quota.get(f"{prefix}_tpm")
        rpd = quota.get(f"{prefix}_rpd")
        cap = quota.get(f"{prefix}_rpd_cap")
        if rpm is None and tpm is None and rpd is None and cap is None:
            continue
        rows.append({
            "model": label, "rpm": rpm, "tpm": tpm, "rpd": rpd,
            "rpd_cap": cap,
            "unlimited_rpm": rpm in (0, "unlimited"),
            "unlimited_rpd": rpd in (0, "unlimited"),
        })
    return rows


def _deep_merge(base: dict, override: dict) -> dict:
    import copy

    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


# Defaults mirror config.toml.example / blueprint Appendix A. Anything the
# blueprint marks open in §10 defaults to its stated recommendation and is
# flagged in README.md for the owner's confirmation — Phase 0 does not
# silently settle later-phase decisions.
DEFAULTS: dict = {
    "gemini": {
        # §4.1 PIN FIX (owner-approved 2026-10-25, Phase 0 audit): these were
        # `-latest` aliases, which can resolve server-side to a retired model
        # (gemini-2.5-flash-lite was retired 2026-10-20) — the reply-regression
        # root-cause candidate. Everything is now a pinned registry id; the
        # alias policy allows `-latest` only for non-identity chat
        # experimentation, never for these roles. Registry: model_registry.py.
        "model_default": "gemini-3.5-flash-lite",
        "model_organise": "gemini-3.5-flash-lite",
        "model_cleanup": "gemini-3.5-flash-lite",
        "model_chat": "gemini-3.5-flash-lite",
        # §4.1 file fallback: used only when the transcription primary is
        # unavailable (wired into the event/file paths in WP5).
        "model_file_fallback": "gemini-3.5-flash-lite",
        "model_transcribe_live": "gemini-3.5-transcribe-live",
        # Batch/pre-recorded transcription is a dedicated model, not a chat
        # Flash-Lite. Gemini 3.5 Transcribe (2026-08-26) is the real batch model;
        # its Live sibling above is already pinned. Both are checked against a
        # live models.list by `assist voice models` / doctor-on-owner-machine.
        "model_transcribe_batch": "gemini-3.5-transcribe",
        # INTERIM speaking voice (owner choice 2026-10-20). Flare is the only
        # voice Elaria ever speaks with; offline is text-only and the local Piper
        # voice is dormant (see [tts]). Native audio is produced by a LIVE model,
        # never by a TTS-preview model: Flare is a Live voice, and
        # `gemini-2.5-flash-preview-tts` rejects it with
        # "Voice name Flare is not supported" (Stage A live repro).
        "gemini_voice_model": DEFAULT_VOICE_MODEL,
        "voice": "Flare",
        "voice_sample_rate": 24000,
        # The one-voice rule, expressed in config (VB-4): `[gemini] voice` must be
        # one of these or she refuses to speak and `assist doctor` fails. Widening
        # this list is the ONLY way to change her voice — no code edit, and no
        # silent adoption of whatever string is in `voice`.
        "allowed_voices": ["Flare"],
        # §4.1: escalation is gemini-3.8-flash (free ~20 RPD), escalation-only
        # by doctrine. Start at chat/intent, climb one tier on verified failure.
        "escalation_ladder": ["gemini-3.5-flash-lite", "gemini-3.8-flash"],
        "escalate_after_failures": 2,
        "max_scaffold_calls": 6,
        # BUG F / Bug 8 (2026-10-20): the old single 4 s total-turn bound
        # cancelled `asyncio.to_thread(generate)` — which does NOT stop the
        # worker thread. The call completed and hit the ledger while the
        # timeout path substituted a canned reply. Deadlines are now split:
        # a streaming FIRST-TOKEN deadline (a transport that has produced
        # nothing is dead) and a GENEROUS total bound (a generation that
        # started is delivered verbatim).
        "chat_first_token_s": 5.0,
        "chat_timeout_s": 30.0,
        "mode": "mock",
    },
    # Owner-verified quota shape (Step 0, 2026-10-20). These are MEASURED numbers
    # from the owner's AI Studio rate-limit page, not defaults: Flash 5 RPM /
    # 250K TPM / 20 RPD; Flash-Lite 15 RPM / 250K TPM / 500 RPD; Transcribe Live
    # unlimited RPM / 20K TPM; batch Transcribe 25 RPD. `verified = true` is the
    # marker that stops doctor/cost printing the old assumed figures — when it is
    # absent or false the warning comes back, loudly and by design (§11).
    "quota": {
        "verified": True,
        "verified_at": "2026-10-20",
        "verified_source": "owner's AI Studio rate-limit page",
        "models": {
            "flash": {"rpm": 5, "tpm": 250_000, "rpd": 20},
            # §4.1: chat/intent free tier is ~500 RPD; the CONFIG cap is 400
            # (`rpd_cap`) so housekeeping + file fallback share deliberate
            # headroom under the free ceiling. `rpd` stays the owner-measured
            # figure; enforcement takes the stricter of the two.
            "flash-lite": {"rpm": 15, "tpm": 250_000, "rpd": 500,
                           "rpd_cap": 400},
            "transcribe-live": {"rpm": 0, "tpm": 20_000, "rpd": 0},
            "transcribe-batch": {"rpm": None, "tpm": None, "rpd": 25},
        },
        # Flat aliases remain readable by older code/configs and by the client's
        # limiter. `0` means "not rate-limited" (Transcribe Live).
        "flash_rpm": 5,
        "flash_tpm": 250_000,
        "flash_rpd": 20,
        "flash_lite_rpm": 15,
        "flash_lite_tpm": 250_000,
        "flash_lite_rpd": 500,
        "transcribe_live_rpm": 0,
        "transcribe_live_tpm": 20_000,
        "transcribe_live_rpd": 0,
        "transcribe_batch_rpd": 25,
        "flash_lite_rpd_cap": 400,   # §4.1 chat/intent config cap (under the 500 free)
        "max_requests_per_day": 1200,
        "max_requests_per_minute": 12,
    },
    "asr": {
        "primary": "gemini_live",
        "fallback": ["gemini_batch", "local"],
        # Phase 8 offline ASR (§13.9): local Whisper behind the same seam.
        # English is the supported offline path; other pinned languages are
        # passed through explicitly and remain best-effort (never detected).
        "offline_backend": "faster-whisper",  # faster-whisper | whisper.cpp | mock
        "offline_model": "small",
        "offline_device": "cpu",
        "offline_compute_type": "int8",
        "whisper_cpp_command": "whisper-cli",
        "whisper_cpp_model": "",
        "offline_low_confidence_threshold": 0.65,
        "offline_queue_cleanup": True,
        "languages": ["en"],
        "preserve_code_switching": False,
        "assert_output_language": True,
    },
    "connectivity": {
        # auto follows Gemini/network health; offline is FORCED_OFFLINE and
        # must not probe or call the network at all (§13.9 privacy posture).
        "mode": "auto",  # auto | online | offline
        "health_host": "generativelanguage.googleapis.com",
        "health_port": 443,
        "health_timeout_s": 1.5,
        "health_check_interval_s": 20,
        "drain_on_reconnect": True,
    },
    "tts": {
        # ONE-VOICE RULE — DEFERRED, NOT CANCELLED (owner decision 2026-10-20).
        # Endgame is still exactly one locally owned voice in every mode, adopted
        # in a single switch. Until then this is INTERIM: `online_voice = "gemini"`
        # makes Gemini native audio (Flare) her speaking voice for online
        # conversation. Offline nothing is spoken at all (see `offline_voice`), so
        # the Piper voice below stays dormant - not an offline voice, not a
        # fallback. Set `online_voice = "local"` to restore the strict one-voice
        # posture; that one key is the whole switch back.
        "online_voice": "gemini",  # gemini (interim) | local (the endgame posture)
        # OFFLINE HAS NO VOICE (owner amendment 2026-10-20): offline replies are
        # text only - Waybar, overlay, notification, log. Nothing is spoken from a
        # local model in normal operation. `local` keeps the Piper path wired but
        # dormant, for the future owned-voice endgame; `none` is the shipped truth.
        "offline_voice": "none",   # none (text only) | local (dormant endgame path)
        "enabled": True,
        "backend": "piper",  # piper | mock (tests/dev only)
        # Owner-selected 2026-10-19 after two audition rounds. The first
        # shortlist (Jenny/Lessac/Kathleen) was rejected outright.
        "voice_id": "en_GB-southern_english_female-low",
        "model": "~/.local/share/piper/en_GB-southern_english_female-low.onnx",
        "config": "~/.local/share/piper/en_GB-southern_english_female-low.onnx.json",
        "speaker": 0,
        "length_scale": 0.92,  # Piper native pace control (<1 is brisker)
        "command": "piper",
        "player": "auto",  # auto | pw-play | paplay | aplay | none
        "speak_acks": True,
        "speak_replies": False,
        "cache_dir": "",
        "audition_dir": "",
        "audition_candidates": [
            {
                "id": "en_GB-southern_english_female-low",
                "model": "~/.local/share/piper/en_GB-southern_english_female-low.onnx",
                "config": "~/.local/share/piper/en_GB-southern_english_female-low.onnx.json",
                "speaker": 0,
                "length_scale": 0.92,
                "notes": "SELECTED canonical voice: rough edge over polish.",
            },
            {
                "id": "en_GB-cori-high",
                "model": "~/.local/share/piper/en_GB-cori-high.onnx",
                "config": "~/.local/share/piper/en_GB-cori-high.onnx.json",
                "speaker": 0,
                "length_scale": 0.92,
                "notes": "Round-2 alternate if the selected voice fails exact-script checks.",
            },
            {
                "id": "en_GB-alba-medium",
                "model": "~/.local/share/piper/en_GB-alba-medium.onnx",
                "config": "~/.local/share/piper/en_GB-alba-medium.onnx.json",
                "speaker": 0,
                "length_scale": 0.92,
                "notes": "Round-2 alternate if the selected voice fails exact-script checks.",
            },
            {
                "id": "en_US-kristin-medium",
                "model": "~/.local/share/piper/en_US-kristin-medium.onnx",
                "config": "~/.local/share/piper/en_US-kristin-medium.onnx.json",
                "speaker": 0,
                "length_scale": 0.92,
                "notes": "Round-2 alternate if the selected voice fails exact-script checks.",
            },
            {
                "id": "en_US-ljspeech-high",
                "model": "~/.local/share/piper/en_US-ljspeech-high.onnx",
                "config": "~/.local/share/piper/en_US-ljspeech-high.onnx.json",
                "speaker": 0,
                "length_scale": 0.92,
                "notes": "Round-2 polished contrast; not selected.",
            },
        ],
    },
    # SILENCE HOTFIX (hardware 2026-10-24): she must never speak to silence.
    # A dictate/PTT/wake session whose measured INPUT PEAK stays below this
    # floor is silence, whatever the transcriber hallucinated from room noise
    # — silent close, no voice reply, no ladder, and one plain line in the
    # journal ("she heard nothing"). Same mechanism as capture.stats / the
    # doctor level check (capture.pcm_peak); the owner's speech is proven at
    # peak 0.8624, so real words clear the floor by an order of magnitude.
    # Voice reply path ONLY: event transcription keeps its own NO_SIGNAL_PEAK
    # marker and never consults this floor.
    "voice": {
        "silence_floor": 0.05,
    },
    "capture": {
        "source": "mic",
        # BUG 6 (2026-10-20): dictate/meeting capture resolves its pw-record
        # --target from here first (then [meeting] mic_target). Empty = the
        # PipeWire default source. Find the node name with `wpctl status` +
        # `wpctl inspect <id>` (node.name, NOT object.id).
        "mic_target": "",
        "sample_rate": 16000,
        "chunk_ms": 30,
        # No bytes at all for this long = a dead capture process (pw-record
        # emits samples even in digital silence). The session ends with
        # "no speech captured" instead of hanging (BUG 6).
        "stall_timeout_s": 8.0,
        "retention_days": 30,
    },
    # Wake-knock package (2026-10-20). Always-on acoustic path: a real
    # keyword model arms it, the dual-use pending buffer feeds the voiceprint
    # verdict, and RAM-only buffers + MADV_DONTDUMP keep the audio out of
    # crashes and logs. No energy fallback is a wake path.
    "hotword": {
        "phrase": "Elaria",
        # Capture sample rate for the wake path (BH-K20: read by the
        # daemon, previously undeclared).
        "sample_rate": 16000,
        # Installed systemd unit path for the crash-safety report
        # ("" = standard locations).
        "unit_path": "",
        # Pre-wake ring: capped at 2.0 s in code regardless of this value.
        "ring_window_s": 2.0,
        # Post-trigger pending window: clamped to the 2-3 s band in code.
        "pending_window_s": 2.5,
        # Below this much detected speech in the pending window, Stage B
        # falls back to wake-clip-only scoring (insufficient-speech branch).
        "pending_speech_threshold_s": 0.5,
        "speech_rms": 0.01,
        # Real keyword spotter (.onnx). Empty/missing => `hotword start`
        # refuses cleanly. There is no energy/loudness fallback.
        "keyword_model": "",
        "keyword_threshold": 0.5,
        "keyword_window_s": 1.0,
        # ECAPA backend (hardware-side): a command `cmd <clip.wav>` printing
        # {"embedding": [...]} (cosine vs ecapa_reference) or {"score": 0..1}.
        "ecapa_cmd": "",
        "ecapa_reference": "",
        "ecapa_high": 0.75,
        "ecapa_uncertain": 0.5,
        # Fail-closed policy when no embedding can be computed: raise the
        # wake-knock (default) or ignore. Never listen, either way.
        "missing_embedding_action": "wake_knock",
        # Watchdog: no frames for this long while armed -> disarm + "stalled".
        "stall_timeout_s": 2.0,
        # Wake clips OFF by default. Opt-in: <= 5 s per clip, 0700 dir,
        # 24 h purge; failed-verify audio is never saved without
        # debug_save_failed.
        "save_wake_clips": False,
        "clip_dir": "",
        "clip_max_s": 5.0,
        "clip_retention_h": 24.0,
        "debug_save_failed": False,
        # Endpointing for the wake path — parameters of the SHARED
        # SilenceLadder (transcribe.py), not a second implementation.
        "checkin_after_s": 30.0,
        "resume_s": 0.4,
        "grace_s": 8.0,
    },
    "transcribe": {
        # §3.5: rolling local buffer replayed into a resumed session so a
        # mid-sentence reset doesn't lose the utterance.
        "reconnect_replay_s": 30,
        # Rotate before the ~10min Live connection lifetime (§3.5 table).
        "live_session_max_s": 540,
        # WP0 watchdog (§4.2): any PTT/live session still holding the mic at
        # this ceiling is auto-closed with a visible marker — a missed release
        # bind once held the mic ~9 minutes. Five minutes, by spec; a config
        # key so the ceiling is checkable, never guessable.
        "ptt_session_ceiling_s": 300.0,
        "save_audio": True,               # disk is free; re-transcription isn't
        "inbox_dir": "",
        "copy_to_clipboard": True,        # wl-copy only (Wayland, §3.3)
        # Adaptive endpointing (§13.8 soft check-in): per-mode silence
        # before the single "Is that all?" — narration waits far longer.
        "checkin_after_s": {"command": 4, "conversation": 6, "narration": 20},
        # VB-5/VB-6: speech must last this long to count as a resumption (so a
        # breath between silences cannot re-arm the check-in), and silence this
        # long AFTER the check-in closes the session instead of holding the mic.
        "speech_resume_s": 0.4,
        "checkin_grace_s": 8.0,
        # Scene-3b-REDO stream E: the bounded post-release wait for the final
        # transcript. Named and configurable — the budget shows up in every
        # final.wait schema line, so a silent lengthening can never hide.
        "final_wait_s": 12.0,
        # Stream G.4 (2026-10-27): the adaptive early-abandon grace. When
        # the server's voice-activity END has arrived with zero transcript
        # family, the documented prompt final is already overdue — wait
        # only this long more, never the full final_wait_s ceiling.
        "final_abandon_grace_s": 3.0,
        # VB-8: a command transcript below this ASR confidence (or flagged by
        # cleanup) is never executed. Unknown confidence still allows read-only
        # intents, never a mutating one.
        "command_min_confidence": 0.85,
        "vad_rms_threshold": 0.01,        # never stream silence (§8)
    },
    "cleanup": {
        "enabled": True,
        "max_divergence_pct": 35,         # diff-gate (§12.5): rewrite != repair
        "keep_raw": True,                 # raw is the record, cleaned the convenience
        "min_chars": 40,                  # short utterances aren't worth a call (§13.4)
        "glossary_file": "~/.config/assistant/glossary.toml",
    },
    "presence": {
        # Stage B / §19.1. Class mode is a MANUAL toggle; the schedule only
        # suggests it (an assistant that changes its social posture because the
        # clock moved is the exact initiative §19.2 forbids).
        "class_mode": False,
        "class_schedule_suggest": True,
        # e.g. [{days=["mon","tue","wed","thu","fri"], start="08:00",
        #        end="15:00", label="lecture block"}]
        "class_schedule": [],
    },
    "console": {
        "history_limit": 200,      # one conversation; no per-channel fork
        "snapshot_limit": 20,
    },
    "disclosure": {
        # Owner rule 2026-10-20: memory is allowed, leaking is not. Behaviour is
        # speakable; secrets and private plans are not — not even to the owner
        # while they have company. Awareness comes from the owner saying they are
        # not alone, and from show-off mode. A guest voice gets no memory at all.
        "owner_name": "",            # how she refers to you in a deflection
    },
    "showoff": {
        # §19.3. Entry happens through a voiceprint-verified command only; this
        # section carries no grant of authority, only the demo's own bounds.
        "timeout_s": 600,            # ~10 minutes, then it ends itself
        "sandbox": "",               # "" -> <data_dir>/demo-sandbox
        # The ONLY owner facts visible to guests. Empty by default: private
        # memory (§16) is closed in this mode, not merely discouraged.
        "demo_safe_facts": [],
        "announce": True,
    },
    "initiative": {
        # §19.2 as amended: NO BUDGET. There is deliberately no per-day count,
        # spacing rule or rate key in this section — the reason gate controls
        # knocks (a stored, citable reason or no knock at all).
        "snooze_hours": 24,             # "later" -> commitment memory
        "retire_after_ignores": 3,      # same topic ignored 3x retires it
        "urgent_in_class_mode": True,   # class mode = urgent-only, silently
        # A knock has its OWN notification identity and its OWN short sound.
        # Nothing else ever uses these (§19.2: not errors, not completions).
        # The identity/title/body are FIXED in code (notification privacy,
        # owner order 2026-10-26) — there is deliberately no content knob.
        "sound": "~/.local/share/assistant/sounds/knock.wav",
        "notify": True,
        "play_sound": True,
    },
    "persona": {
        "name": "Elaria",
        "candour": 0.7,
        "verbosity": "normal",
        "humour": "witty",
        "humour_profile": "~/.local/share/assistant/persona/humour.toml",
        "proactive": True,
        "proactive_max_per_day": 3,
        "pushback_budget_per_day": 5,
        "quiet_hours": "23:00-07:00",
    },
    "privacy": {"tier": "free", "never_send_to_cloud": []},
    "meeting": {
        # PipeWire targets per channel (§3.4/Step 3C). Verify node names
        # with `assist meeting setup` on the real machine.
        "mic_target": "",
        "system_target": "",          # usually "<your-sink>.monitor"
        "pyannote_refine": False,     # needs extra: diarize + HF_TOKEN
    },
    "event": {
        # Event transcriber (Blueprint v2). Defaults = §0 decision-table row 3
        # (the proven batch engine). `assist event spike` measures the real
        # row on the owner's account; these keys follow its decision.
        "route": "batch",             # batch | transcribe-live
        "segment_minutes": 30.0,      # row 3: 30 · row 1: 10 · row 2: shortened
        "tokens_per_second": 32.0,    # pacing estimate; replaced by the spike
        "tpm_ceiling": 20_000.0,      # transcribe-live TPM ceiling ([quota])
        "daily_call_budget": 25,      # batch route: 25 calls/day (§3)
        "max_attempts": 3,
        "deferred_retries": 2,
        "stop_grace_s": 120.0,
        "sleep_inhibit": True,
        "mic_target": "",             # falls back to [meeting]/[capture]
    },
    "memory": {
        # §10.5: local embeddings. 'hashing' = stdlib lexical baseline;
        # 'sentence-transformers' = real semantics (extra: embeddings).
        "embedder": "hashing",
        "embedding_model": "all-MiniLM-L6-v2",
        "embed_on_index": True,
    },
    "organise": {
        "mode": "shadow",
        "confidence_auto": 0.90,
        "confidence_review": 0.60,
        "tier0_min_confidence": 0.85,  # below: would escalate to LLM tiers (§3.7)
        "max_ops_per_run": 200,
        "max_ops_per_hour": 500,
        # LLM planner batch sizes (Tier 1 sweeps wide, Tier 2 narrow).
        "tier1_batch_size": 50,
        "tier2_batch_size": 10,
        "tree_tripwire_pct": 25,
        # NO roots by default: nothing is indexed until the owner names a
        # root in config (new roots ALWAYS start in shadow mode, §4.3).
        "roots": [],
        "watch": False,
        "watch_interval_s": 60,
        "max_extract_chars": 200_000,
    },
    "policy": {
        "protected": ["~/.ssh", "~/.gnupg", "~/.config", "~/.local/share/assistant"],
        "recently_modified_guard_minutes": 15,
    },
    "tools": {"shell": "confirm"},
    "voice_test": {
        "keyword": "Elaria",
        # The biometric template: where it lives and what produced it. `doctor`
        # validates size, JSON, schema, dimension, model AND file mode against
        # these (VB-9) — it no longer asks only whether the file exists.
        "voiceprint_path": "~/voiceprint.json",
        "embedding_dim": 192,
        "speaker_threshold": 0.75,
        "keyword_threshold": 0.5,
        "save_near_miss_clips": False,
    },
}


@dataclass
class Config:
    raw: dict
    config_path: Path
    config_found: bool
    api_key_present: bool
    api_key_source: str  # "env" | "file" | "none"
    api_key_file_mode: int | None  # permission bits of gemini.env, if read
    gemini_mode: str
    gemini_mode_source: str  # "env" | "config" | "auto-no-key" | "auto-key"
    _api_key: str | None = field(default=None, repr=False)
    # Keys the owner's file actually names (not merged defaults). Intent matters
    # where two spellings of the same setting exist (BH-I1).
    explicit_keys: dict[str, set[str]] = field(default_factory=dict, repr=False)

    # -- section accessors -------------------------------------------------
    def section(self, name: str) -> dict:
        value = self.raw.get(name, {})
        # A section poisoned to a scalar is an invalid config that
        # `validate_config()` reports by name; readers still get a mapping so a
        # daemon/doctor run degrades instead of crashing on `dict("x")`.
        return dict(value) if isinstance(value, dict) else {}

    def explicit(self, section: str, key: str) -> bool:
        """Did the owner's config file name this key (vs a merged default)?"""
        return key in self.explicit_keys.get(section, set())

    def model_for_role(self, role: str) -> str:
        gemini = self.section("gemini")
        if role == "voice":
            return voice_model(self)
        return str(gemini.get(f"model_{role}")
                   or gemini.get("model_default") or "")

    def voice_model(self) -> str:
        """The Live model that owns native audio (Stage A: `gemini_voice_model`)."""
        return voice_model(self)

    @property
    def api_key(self) -> str | None:
        """The key itself. Callers must never log or print this."""
        return self._api_key

    def organise_roots(self) -> list[dict]:
        """Normalised [[organise.roots]] entries: expanded paths, per-root
        mode defaulting to shadow (§4.3 — new roots NEVER start live),
        frozen taxonomy with the _Unsorted escape hatch guaranteed.

        Invalid entries are refused by name (BH-I2). A made-up mode used to be
        stored verbatim in the plan row and a missing `path` raised a bare
        `KeyError`; both are config errors the owner must see, not crashes.
        """
        organise = self.section("organise")
        entries = organise.get("roots") or []
        if not isinstance(entries, list):
            raise TypeError(
                "[organise] roots must be a list of [[organise.roots]] tables")
        roots = []
        for index, entry in enumerate(entries):
            where = f"[organise.roots] entry {index}"
            if not isinstance(entry, dict):
                raise TypeError(f"{where} must be a table, not {type(entry).__name__}")
            raw_path = entry.get("path")
            if not isinstance(raw_path, str) or not raw_path.strip():
                raise ValueError(
                    f"{where} is missing a non-empty `path` "
                    "(organise.roots.path is required)")
            mode = str(entry.get("mode", "shadow")).strip().lower() or "shadow"
            if mode not in ("shadow", "live"):
                raise ValueError(
                    f"{where} has mode={entry.get('mode')!r}; organise.roots.mode "
                    "must be 'shadow' or 'live' (new roots start in shadow, §4.3)")
            raw_taxonomy = entry.get("taxonomy") or []
            if isinstance(raw_taxonomy, str):
                raw_taxonomy = [raw_taxonomy]
            if not isinstance(raw_taxonomy, (list, tuple)):
                raise TypeError(
                    f"{where} taxonomy must be a string or a list of strings")
            taxonomy = [str(t) for t in raw_taxonomy if str(t).strip()]
            for required in ("_Unsorted", "_Conflicts"):
                if required not in taxonomy:
                    taxonomy.append(required)
            roots.append({
                "path": str(Path(raw_path).expanduser()),
                "mode": mode,
                "taxonomy": taxonomy,
            })
        return roots

    # -- paths -------------------------------------------------------------
    @property
    def data_dir(self) -> Path:
        return data_home() / "assistant"

    @property
    def state_dir(self) -> Path:
        return state_home() / "assistant"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def inbox_dir(self) -> Path:
        """Configured transcript inbox, defaulting to the XDG data root (I7)."""
        configured = self.section("transcribe").get("inbox_dir")
        if configured:
            return Path(configured).expanduser()
        return self.data_dir / "inbox"

    @property
    def socket_path(self) -> Path:
        return runtime_dir() / "assistant.sock"

    @property
    def fixtures_dir(self) -> Path:
        override = os.environ.get("ASSIST_FIXTURES")
        if override:
            return Path(override).expanduser()
        # Dev checkout: fixtures/ sits next to pyproject.toml. Installed:
        # fall back to the data dir so record mode still has somewhere sane.
        repo_fixtures = Path(__file__).resolve().parents[2] / "fixtures"
        if repo_fixtures.parent.joinpath("pyproject.toml").exists():
            return repo_fixtures
        return self.data_dir / "fixtures"

    def humour_profile_path(self) -> Path | None:
        """Locate humour.toml: persona dir first, then repo root (dev).

        A poisoned `[persona] humour_profile` (wrong type, or a section that is
        not a table) must leave the governor at its restraint default rather
        than crash every `assist` invocation (BH-I2).
        """
        configured_value = self.section("persona").get("humour_profile")
        configured = (Path(str(configured_value)).expanduser()
                      if configured_value else None)
        if configured is not None and configured.exists():
            return configured
        repo_root = Path(__file__).resolve().parents[2] / "humour.toml"
        if repo_root.exists():
            return repo_root
        cwd = Path.cwd() / "humour.toml"
        return cwd if cwd.exists() else None

    def ensure_dirs(self) -> None:
        ensure_private_dir(self.data_dir)
        ensure_private_dir(self.state_dir)
        runtime_dir().mkdir(parents=True, exist_ok=True)


def _read_env_file(path: Path) -> tuple[str | None, int | None]:
    """Parse GEMINI_API_KEY=... from gemini.env. Returns (key, file_mode)."""
    if not path.exists():
        return None, None
    mode = path.stat().st_mode & 0o777
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_API_KEY="):
            value = line.split("=", 1)[1].strip().strip('"').strip("'")
            return (value or None), mode
    return None, mode


def load_config() -> Config:
    config_path = Path(
        os.environ.get("ASSIST_CONFIG", config_home() / "assistant" / "config.toml")
    ).expanduser()
    raw = _deep_merge(DEFAULTS, {})
    found = config_path.exists()
    explicit_keys: dict[str, set[str]] = {}
    if found:
        try:
            with config_path.open("rb") as handle:
                user_raw = tomllib.load(handle)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            # BH-K24: name the file — a bare TOML error ("line 1 column 8")
            # left owners guessing WHICH config every command died on.
            raise ValueError(
                f"cannot parse config {config_path}: {exc}") from exc
        raw = _deep_merge(raw, user_raw)
        explicit_keys = {
            section: set(values)
            for section, values in user_raw.items()
            if isinstance(values, dict)
        }

    env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    file_key, file_mode = _read_env_file(config_home() / "assistant" / "gemini.env")
    if env_key:
        api_key, source = env_key, "env"
    elif file_key:
        api_key, source = file_key, "file"
    else:
        api_key, source = None, "none"

    env_mode = os.environ.get("GEMINI_MODE", "").strip().lower()
    file_gemini = raw.get("gemini") if isinstance(raw.get("gemini"), dict) else {}
    if env_mode in VALID_MODES:
        mode, mode_source = env_mode, "env"
    elif (file_gemini.get("mode") in VALID_MODES
          and "mode" in explicit_keys.get("gemini", set())):
        mode, mode_source = file_gemini["mode"], "config"
    elif api_key:
        mode, mode_source = "live", "auto-key"
    else:
        # §12.9 guardrail: a missing key means "no network", never a crash.
        mode, mode_source = "mock", "auto-no-key"

    return Config(
        raw=raw,
        config_path=config_path,
        config_found=found,
        api_key_present=api_key is not None,
        api_key_source=source,
        api_key_file_mode=file_mode,
        gemini_mode=mode,
        gemini_mode_source=mode_source,
        _api_key=api_key,
        explicit_keys=explicit_keys,
    )


def load_humour_profile(config: Config) -> dict:
    """Parse humour.toml (the calibrated taste profile, §13.7).

    Returns {} when absent or malformed — the governor must degrade to safe
    restraint, never crash, and never invent a personality the owner didn't approve.
    """
    path = config.humour_profile_path()
    if path is None:
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (tomllib.TOMLDecodeError, OSError):
        return {}


_KNOWN_DEPRECATED_KEYS: dict[tuple[str, str], str] = {
    ("gemini", "model_voice"): "deprecated alias for [gemini] gemini_voice_model",
    ("initiative", "class_mode_urgent_only"): "deprecated alias for [initiative] urgent_in_class_mode",
    ("voice_test", "embedding_model"): "optional voiceprint model pin",
}


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number_error(errors: list[str], path: str, value, *,
                  minimum: float | None = None,
                  maximum: float | None = None,
                  integer: bool = False) -> None:
    """One shape check that never raises on a poisoned value."""
    if value is None:
        return
    if not _is_number(value) or (integer and int(value) != value):
        errors.append(f"{path}={value!r} must be {'an integer' if integer else 'a number'}")
        return
    if minimum is not None and value < minimum:
        errors.append(f"{path}={value!r} must be >= {minimum}")
    if maximum is not None and value > maximum:
        errors.append(f"{path}={value!r} must be <= {maximum}")


def _bool_error(errors: list[str], path: str, value) -> None:
    if value is not None and not isinstance(value, bool):
        errors.append(f"{path}={value!r} must be true or false")


def _string_list_error(errors: list[str], path: str, value) -> None:
    if value is None:
        return
    if isinstance(value, str):
        return
    if (not isinstance(value, (list, tuple))
            or any(not isinstance(item, str) or not item.strip() for item in value)):
        errors.append(f"{path}={value!r} must be a string or a list of non-empty strings")


def _valid_hhmm(value) -> bool:
    try:
        hour, minute = str(value).split(":")
        return 0 <= int(hour) < 24 and 0 <= int(minute) < 60
    except (TypeError, ValueError):
        return False


def validate_config(config: Config) -> dict:
    """Validate `config.raw` against `DEFAULTS` for unknown keys, deprecated
    aliases, negative quotas, wrong types and invalid mode/posture values.

    The rule is "doctor names the key, the daemon does not crash": every check
    below reports `[section] key` and tolerates a value of any type (BH-H22,
    BH-I2). Warnings are still configuration drift; errors are values no code
    path can honour.
    """
    warnings: list[str] = []
    errors: list[str] = []
    raw = config.raw if config else {}
    if not isinstance(raw, dict):
        return {"ok": False, "errors": ["config root must be a table"],
                "warnings": [], "detail": "INVALID: config root must be a table"}

    for sec, sec_val in raw.items():
        if sec not in DEFAULTS:
            warnings.append(f"unknown section [{sec}]")
            continue
        default_sec = DEFAULTS[sec]
        if not isinstance(sec_val, dict):
            errors.append(f"section [{sec}] must be a table, not "
                          f"{type(sec_val).__name__}")
            continue
        if not isinstance(default_sec, dict):
            continue
        for key, value in sec_val.items():
            if key.startswith("_"):
                continue
            if (sec, key) in _KNOWN_DEPRECATED_KEYS:
                warnings.append(f"[{sec}] {key}: {_KNOWN_DEPRECATED_KEYS[(sec, key)]}")
            elif key not in default_sec:
                warnings.append(f"unknown key [{sec}] {key}")
            elif isinstance(default_sec[key], dict) and not isinstance(value, dict):
                errors.append(f"[{sec}] {key} must be a table")

    # -- enums: the values code branches on ---------------------------------
    enum_keys = {
        ("gemini", "mode"): VALID_MODES,
        ("connectivity", "mode"): ("auto", "online", "offline"),
        ("tts", "online_voice"): ("gemini", "local", "none"),
        ("tts", "offline_voice"): ("none", "local"),
        ("tts", "backend"): ("piper", "mock"),
        ("organise", "mode"): ("shadow", "live"),
    }
    for (sec, key), allowed in enum_keys.items():
        section = raw.get(sec)
        if not isinstance(section, dict) or key not in section:
            continue
        value = section.get(key)
        if str(value).lower() not in allowed:
            errors.append(
                f"[{sec}] {key}={value!r} must be one of: {', '.join(allowed)}")

    # -- gemini / voice identity --------------------------------------------
    gemini = raw.get("gemini") if isinstance(raw.get("gemini"), dict) else {}
    _string_list_error(errors, "[gemini] allowed_voices", gemini.get("allowed_voices"))
    for key in ("voice", "gemini_voice_model", "model_voice"):
        value = gemini.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"[gemini] {key}={value!r} must be a string")
    _number_error(errors, "[gemini] voice_sample_rate", gemini.get("voice_sample_rate"),
                  minimum=1, integer=True)

    # -- tts ----------------------------------------------------------------
    tts = raw.get("tts") if isinstance(raw.get("tts"), dict) else {}
    _number_error(errors, "[tts] speaker", tts.get("speaker"), minimum=0, integer=True)
    _number_error(errors, "[tts] length_scale", tts.get("length_scale"), minimum=0.01)
    _bool_error(errors, "[tts] speak_acks", tts.get("speak_acks"))
    _bool_error(errors, "[tts] speak_replies", tts.get("speak_replies"))
    _bool_error(errors, "[tts] enabled", tts.get("enabled"))
    if tts.get("player") is not None and not isinstance(tts.get("player"), str):
        errors.append(f"[tts] player={tts.get('player')!r} must be a string")
    candidates = tts.get("audition_candidates")
    if candidates is not None:
        if not isinstance(candidates, list):
            errors.append("[tts] audition_candidates must be a list of tables")
        else:
            for index, entry in enumerate(candidates):
                if not isinstance(entry, dict) or not str(entry.get("id") or "").strip():
                    errors.append(
                        f"[tts] audition_candidates[{index}] needs a non-empty `id`")

    # -- capture / transcribe ------------------------------------------------
    capture = raw.get("capture") if isinstance(raw.get("capture"), dict) else {}
    _number_error(errors, "[capture] sample_rate", capture.get("sample_rate"),
                  minimum=1, integer=True)
    _number_error(errors, "[capture] chunk_ms", capture.get("chunk_ms"),
                  minimum=1, integer=True)
    transcribe = raw.get("transcribe") if isinstance(raw.get("transcribe"), dict) else {}
    _number_error(errors, "[transcribe] command_min_confidence",
                  transcribe.get("command_min_confidence"), minimum=0.0, maximum=1.0)
    _number_error(errors, "[transcribe] live_session_max_s",
                  transcribe.get("live_session_max_s"), minimum=1)
    _number_error(errors, "[transcribe] speech_resume_s",
                  transcribe.get("speech_resume_s"), minimum=0.0)
    _number_error(errors, "[transcribe] checkin_grace_s",
                  transcribe.get("checkin_grace_s"), minimum=0.0)

    # -- hotword (wake-knock package) ---------------------------------------
    hotword = raw.get("hotword") if isinstance(raw.get("hotword"), dict) else {}
    _number_error(errors, "[hotword] ring_window_s", hotword.get("ring_window_s"),
                  minimum=0.1, maximum=2.0)
    _number_error(errors, "[hotword] pending_window_s",
                  hotword.get("pending_window_s"), minimum=2.0, maximum=3.0)
    _number_error(errors, "[hotword] keyword_window_s",
                  hotword.get("keyword_window_s"), minimum=0.1, maximum=2.0)
    _number_error(errors, "[hotword] pending_speech_threshold_s",
                  hotword.get("pending_speech_threshold_s"), minimum=0.0)
    _number_error(errors, "[hotword] ecapa_high", hotword.get("ecapa_high"),
                  minimum=0.0, maximum=1.0)
    _number_error(errors, "[hotword] ecapa_uncertain", hotword.get("ecapa_uncertain"),
                  minimum=0.0, maximum=1.0)
    _number_error(errors, "[hotword] stall_timeout_s",
                  hotword.get("stall_timeout_s"), minimum=0.1)
    if str(hotword.get("missing_embedding_action", "wake_knock")) not in (
            "wake_knock", "ignore"):
        errors.append("[hotword] missing_embedding_action must be "
                      "'wake_knock' or 'ignore'")
    _bool_error(errors, "[hotword] save_wake_clips",
                hotword.get("save_wake_clips"))
    _bool_error(errors, "[hotword] debug_save_failed",
                hotword.get("debug_save_failed"))

    # -- connectivity ---------------------------------------------------------
    connectivity = (raw.get("connectivity")
                    if isinstance(raw.get("connectivity"), dict) else {})
    _number_error(errors, "[connectivity] health_port", connectivity.get("health_port"),
                  minimum=1, maximum=65535, integer=True)
    _number_error(errors, "[connectivity] health_timeout_s",
                  connectivity.get("health_timeout_s"), minimum=0.01)
    _number_error(errors, "[connectivity] health_check_interval_s",
                  connectivity.get("health_check_interval_s"), minimum=1)

    # -- console / presence / initiative / showoff ---------------------------
    console = raw.get("console") if isinstance(raw.get("console"), dict) else {}
    _number_error(errors, "[console] history_limit", console.get("history_limit"),
                  minimum=1, integer=True)
    _number_error(errors, "[console] snapshot_limit", console.get("snapshot_limit"),
                  minimum=1, integer=True)

    presence = raw.get("presence") if isinstance(raw.get("presence"), dict) else {}
    _bool_error(errors, "[presence] class_mode", presence.get("class_mode"))
    _bool_error(errors, "[presence] class_schedule_suggest",
                presence.get("class_schedule_suggest"))
    schedule = presence.get("class_schedule")
    if schedule is not None:
        if not isinstance(schedule, list):
            errors.append("[presence] class_schedule must be a list of tables")
        else:
            for index, window in enumerate(schedule):
                if not isinstance(window, dict):
                    errors.append(f"[presence] class_schedule[{index}] must be a table")
                    continue
                for key in ("start", "end"):
                    if not _valid_hhmm(window.get(key)):
                        errors.append(
                            f"[presence] class_schedule[{index}].{key}="
                            f"{window.get(key)!r} must be HH:MM")

    initiative = raw.get("initiative") if isinstance(raw.get("initiative"), dict) else {}
    _number_error(errors, "[initiative] snooze_hours", initiative.get("snooze_hours"),
                  minimum=0)
    _number_error(errors, "[initiative] retire_after_ignores",
                  initiative.get("retire_after_ignores"), minimum=1, integer=True)
    _bool_error(errors, "[initiative] urgent_in_class_mode",
                initiative.get("urgent_in_class_mode"))

    showoff = raw.get("showoff") if isinstance(raw.get("showoff"), dict) else {}
    _number_error(errors, "[showoff] timeout_s", showoff.get("timeout_s"), minimum=1)
    _string_list_error(errors, "[showoff] demo_safe_facts", showoff.get("demo_safe_facts"))

    # -- organise roots (per-root posture) -----------------------------------
    organise = raw.get("organise") if isinstance(raw.get("organise"), dict) else {}
    roots = organise.get("roots")
    if roots is not None:
        if not isinstance(roots, list):
            errors.append("[organise] roots must be a list of tables")
        else:
            for index, entry in enumerate(roots):
                where = f"[organise.roots] entry {index}"
                if not isinstance(entry, dict):
                    errors.append(f"{where} must be a table")
                    continue
                path = entry.get("path")
                if not isinstance(path, str) or not path.strip():
                    errors.append(f"{where} is missing a non-empty `path`")
                if "mode" in entry and str(entry.get("mode")).lower() not in ("shadow", "live"):
                    errors.append(
                        f"{where} mode={entry.get('mode')!r} must be shadow or live")
                taxonomy = entry.get("taxonomy")
                if taxonomy is not None:
                    _string_list_error(errors, f"{where} taxonomy", taxonomy)

    # -- quota numbers (the owner-measured limits) ---------------------------
    quota = raw.get("quota") if isinstance(raw.get("quota"), dict) else {}
    for qkey in ("max_requests_per_day", "max_requests_per_minute",
                 "flash_rpm", "flash_tpm", "flash_rpd",
                 "flash_lite_rpm", "flash_lite_tpm", "flash_lite_rpd",
                 "flash_lite_rpd_cap",
                 "transcribe_live_rpm", "transcribe_live_tpm", "transcribe_live_rpd",
                 "transcribe_batch_rpd"):
        _number_error(errors, f"[quota] {qkey}", quota.get(qkey), minimum=0)
    models = quota.get("models")
    if models is not None and not isinstance(models, dict):
        errors.append("[quota] models must be a table of per-model rows")
    elif isinstance(models, dict):
        for mname, mrow in models.items():
            if not isinstance(mrow, dict):
                errors.append(f"[quota.models.{mname}] must be a table")
                continue
            for key in mrow:
                if key not in ("rpm", "tpm", "rpd", "rpd_cap"):
                    warnings.append(f"unknown key [quota.models.{mname}] {key}")
            for rkey in ("rpm", "tpm", "rpd", "rpd_cap"):
                rval = mrow.get(rkey)
                if rval in (None, "unlimited"):
                    continue
                if not _is_number(rval) or rval < 0:
                    errors.append(
                        f"[quota.models.{mname}] {rkey}={rval!r} must be >= 0 "
                        "or 'unlimited'")
    # BH-K18: the flat aliases and the structured rows are two statements
    # of the same limits; where both speak and disagree, say so (the
    # client enforces the stricter — silence here hid real drift).
    if isinstance(models, dict):
        _FLAT_FOR = {"flash": "flash", "flash-lite": "flash_lite",
                     "transcribe-live": "transcribe_live",
                     "transcribe-batch": "transcribe_batch"}
        for mname, mrow in models.items():
            prefix = _FLAT_FOR.get(str(mname).lower().replace("_", "-"))
            if not prefix or not isinstance(mrow, dict):
                continue
            for rkey in ("rpm", "tpm", "rpd", "rpd_cap"):
                rval, fval = mrow.get(rkey), quota.get(f"{prefix}_{rkey}")
                if _is_number(rval) and _is_number(fval) and rval != fval:
                    warnings.append(
                        f"[quota] {prefix}_{rkey}={fval} and "
                        f"[quota.models.{mname}] {rkey}={rval} disagree — "
                        "the stricter value is enforced")

    if errors:
        detail = "INVALID: " + "; ".join(errors + warnings)
    elif warnings:
        detail = "warnings: " + "; ".join(warnings)
    else:
        detail = "all sections, keys, and quota bounds match schema"
    return {
        "ok": not errors and not warnings,
        "errors": errors,
        "warnings": warnings,
        "detail": detail,
    }
