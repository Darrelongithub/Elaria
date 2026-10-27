"""Speech output: one voice (Flare, online) and no voice at all (offline).

Owner decisions 2026-10-20, in order:

1. INTERIM - the ONE-VOICE RULE is deferred, not cancelled. While
   `[tts] online_voice = "gemini"`, every spoken reply in every online mode is
   Gemini native audio with `[gemini] voice` (Flare). This module is still the
   only speech-output service; callers never pick a voice.
2. AMENDMENT - OFFLINE MODE HAS NO VOICE OUTPUT AT ALL. Offline replies are text
   on the Waybar, overlay, notification and log surfaces. `voice_route()` is the
   single place that decides, and `offline_voice = "none"` is the shipped truth.

The original hard rule (Elaria sounds identical online and offline; Gemini
supplies text only; a missing local voice degrades to text/silence and never to
a second cloud voice) is what this module returns to when
`[tts] online_voice = "local"` is set - one switch, no re-plumbing. Until then
the local Piper path is DORMANT: never a fallback for a cloud failure, never an
offline voice, deleted by nobody. Silence is therefore always *reported* -
`muted=True` plus a reason in `status()["reason"]` - never a bare absence, and
nothing here ever sends a *second* cloud voice.

Speed is Piper's native `--length-scale`. There is deliberately no
ffmpeg/sox/atempo-style time-stretching anywhere in this module.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import shlex
import shutil
import struct
import subprocess
import sys
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .config import canonical_voices, resolve_voice
from .config import voice_model as config_voice_model
from .journal_log import log_event
from .proc import child_kwargs

# The ack strings are load-bearing for audibility, not style. This voice cannot
# render a one-word utterance legibly: "Done." and "Sorted." recovered 0 of 6
# takes at every length_scale from 0.80 to 1.30, on two Piper versions, with and
# without silence padding, while three-word phrasings of the same meaning
# recovered 6 of 6 with zero variance. Measured in docs/voice-audition-round3.md
# ("Round 4 addendum"); `tests/test_phase8_offline_voice.py` pins these strings
# so a tidy-up cannot quietly re-break the hot path.
STANDARD_ACKS = {
    "on_it": "On it.",
    "done": "That is done.",
    "checkin": "Is that everything?",
    "not_at_this_hour": "No. Not at this hour.",
}

# Session-open acknowledgement: a locally generated neutral earcon, NOT a
# spoken sentence and NOT a model call. It stays on the cached <300 ms path.
SESSION_CUE_KIND = "session_open"

AUDITION_SCRIPT = (
    "On it. Done. Is that all? No. Not at this hour. "
    "Sasa, the March invoice is filed. The six ambiguous ones are parked, "
    "not guessed at."
)

_SELECTED_KEY = "tts.selected_voice"


class TtsUnavailable(RuntimeError):
    pass


def _as_int(value, default: int) -> int:
    """Coerce a config value without letting a poisoned file kill speech.

    `validate_config()`/`doctor` names the key (BH-I2); these readers keep the
    hot path alive in the meantime. Clamping happens at the call site so an
    out-of-range value cannot reach a subprocess argv.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class VoiceDescriptor:
    voice_id: str
    model: str = ""
    config: str = ""
    speaker: int = 0
    length_scale: float = 0.92
    backend: str = "piper"
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict, *, default_backend: str = "piper") -> VoiceDescriptor:
        speaker = _as_int(data.get("speaker") or 0, 0)
        length_scale = _as_float(data.get("length_scale") or 0.92, 0.92)
        return cls(
            voice_id=str(data.get("id") or data.get("voice_id") or "unselected"),
            model=str(data.get("model") or ""),
            config=str(data.get("config") or ""),
            speaker=max(0, speaker),
            length_scale=length_scale if length_scale > 0 else 0.92,
            backend=str(data.get("backend") or default_backend),
            notes=str(data.get("notes") or ""),
        )

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SpeechResult:
    text: str
    backend: str
    voice_id: str
    audio_path: str | None = None
    cached: bool = False
    played: bool = False
    local: bool = True
    cloud_voice: bool = False
    muted: bool = False
    error: str | None = None
    # G.6 latency marks (monotonic): synth completion and player spawn,
    # so reply→synth and synth→audible are measured, never inferred.
    synth_mark: float | None = None
    play_mark: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class TtsBackend(Protocol):
    name: str
    voice_id: str

    def synthesize(self, text: str, dest: Path) -> Path: ...


class MockTtsBackend:
    """Deterministic local test double: a real WAV file, no network."""

    name = "mock-local"

    def __init__(self, voice_id: str = "mock-elaria"):
        self.voice_id = voice_id
        self.calls: list[str] = []

    def synthesize(self, text: str, dest: Path) -> Path:
        self.calls.append(text)
        dest.parent.mkdir(parents=True, exist_ok=True)
        seed = int(hashlib.sha256((self.voice_id + text).encode()).hexdigest()[:4], 16)
        freq = 180 + (seed % 140)
        frames = []
        for i in range(3200):  # 0.2s: enough to prove routing, not audition quality
            frames.append(struct.pack("<h", int(5000 * math.sin(2 * math.pi * freq * i / 16000))))
        with wave.open(str(dest), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"".join(frames))
        return dest


class PiperTtsBackend:
    name = "piper"

    def __init__(self, descriptor: VoiceDescriptor, *, command: str = "piper", runner=None):
        self.descriptor = descriptor
        self.voice_id = descriptor.voice_id
        self.command_setting = command
        self._runner = runner or subprocess.run

    def command(self) -> list[str] | None:
        parts = shlex.split(self.command_setting) if self.command_setting else ["piper"]
        if not parts:
            return None
        exe = parts[0]
        if "/" in exe:
            return parts if Path(exe).expanduser().exists() else None
        if shutil.which(exe):
            return parts
        if exe == "piper" and importlib.util.find_spec("piper") is not None:
            return [sys.executable, "-m", "piper"]
        return None

    def availability_error(self) -> str | None:
        model = Path(self.descriptor.model).expanduser() if self.descriptor.model else None
        if self.descriptor.voice_id in ("", "unselected") or model is None:
            return "no local voice selected yet — run `assist voice audition`, then select one"
        if not model.exists():
            return f"Piper voice model not found: {model}"
        if self.descriptor.config or self._runner is subprocess.run:
            config_path = Path(self.descriptor.config or f"{model}.json").expanduser()
            if not config_path.exists():
                return f"Piper voice config not found: {config_path}"
        if self.command() is None:
            return "Piper executable not found — install with `uv sync --extra tts`"
        return None

    def synthesize(self, text: str, dest: Path) -> Path:
        error = self.availability_error()
        if error:
            raise TtsUnavailable(error)
        dest.parent.mkdir(parents=True, exist_ok=True)
        model = Path(self.descriptor.model).expanduser()
        args = [*self.command(), "--model", str(model), "--output_file", str(dest),
                "--length-scale", str(self.descriptor.length_scale),
                "--speaker", str(self.descriptor.speaker)]
        config = self.descriptor.config or f"{model}.json"
        if config:
            args += ["--config", str(Path(config).expanduser())]
        # BH-K25: scale with the work (~20 chars/s is far below Piper's
        # real rate; the floor still catches a wedged process quickly).
        synth_timeout = min(600.0, max(60.0, 30.0 + len(text) / 20.0))
        result = self._runner(args, input=text, text=True, capture_output=True,
                              timeout=synth_timeout)
        if getattr(result, "returncode", 0) != 0:
            detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
            raise TtsUnavailable(f"Piper failed ({result.returncode}): {detail[:300]}")
        if not dest.exists() or dest.stat().st_size == 0:
            raise TtsUnavailable("Piper reported success but produced no WAV file")
        return dest


class _UnavailableClient:
    """Stands in for "we could not build a Gemini client" without crashing speech."""

    mode = "unavailable"

    def __init__(self, error: Exception | str):
        self.error = str(error)

    def can_speak(self) -> bool:
        return False

    def voice_request(self, text: str, *, voice: str | None = None) -> dict:
        return {"model": "unavailable", "voice_name": voice or "", "text": text,
                "error": self.error, "response_modalities": ["AUDIO"]}


class SpeechService:
    """The only speech-output service. Callers never pick a voice."""

    def __init__(self, config, store=None, *, backend: TtsBackend | None = None,
                 runner=None, player_runner=None, client=None, is_online=None,
                 presence=None):
        self.config = config
        self.store = store
        self._client = client
        self._explicit_client = client is not None
        self._is_online = is_online
        # Stage B: class mode is posture, not a caller decision. Injecting the
        # presence service here means every speech path (ack, say, reply, warm)
        # obeys the toggle without each caller remembering to check it.
        self._presence = presence
        self.last_voice_error: str | None = None
        self._backend_override = backend
        self._runner = runner
        self._player_runner = player_runner or subprocess.run
        settings = config.section("tts") if config else {}
        cache_setting = settings.get("cache_dir")
        self.cache_dir = (Path(cache_setting).expanduser() if cache_setting
                          else config.data_dir / "voice-cache")
        audition_setting = settings.get("audition_dir")
        self.audition_dir = (Path(audition_setting).expanduser() if audition_setting
                             else config.data_dir / "voice-auditions")

    # -- voice selection -------------------------------------------------------
    def candidates(self) -> list[VoiceDescriptor]:
        settings = self.config.section("tts")
        return [VoiceDescriptor.from_dict(item, default_backend=settings.get("backend", "piper"))
                for item in settings.get("audition_candidates") or []]

    def descriptor(self) -> VoiceDescriptor:
        settings = self.config.section("tts")
        if self.store:
            raw = self.store.get_state(_SELECTED_KEY)
            if raw:
                try:
                    return VoiceDescriptor.from_dict(
                        json.loads(raw), default_backend=settings.get("backend", "piper"))
                except (ValueError, TypeError):
                    pass
        speaker = max(0, _as_int(settings.get("speaker", 0), 0))
        length_scale = _as_float(settings.get("length_scale", 0.92), 0.92)
        return VoiceDescriptor(
            voice_id=str(settings.get("voice_id", "unselected")),
            model=str(settings.get("model", "")),
            config=str(settings.get("config", "")),
            speaker=speaker,
            length_scale=length_scale if length_scale > 0 else 0.92,
            backend=str(settings.get("backend", "piper")),
        )

    def select_voice(self, candidate_id: str) -> VoiceDescriptor:
        for candidate in self.candidates():
            if candidate.voice_id == candidate_id:
                if self.store is None:
                    raise RuntimeError("voice selection needs the assistant store")
                self.store.set_state(_SELECTED_KEY, json.dumps(candidate.as_dict()))
                return candidate
        raise ValueError(f"unknown voice candidate {candidate_id!r}")

    def _make_backend(self, descriptor: VoiceDescriptor | None = None) -> TtsBackend:
        if self._backend_override is not None and descriptor is None:
            return self._backend_override
        descriptor = descriptor or self.descriptor()
        if descriptor.backend == "mock":
            return MockTtsBackend(descriptor.voice_id)
        settings = self.config.section("tts")
        return PiperTtsBackend(descriptor, command=str(settings.get("command", "piper")),
                               runner=self._runner)

    # -- voice identity: ONE voice, pinned in config (VB-1, VB-4) -----------------
    def configured_voice(self) -> str:
        """What `[gemini] voice` asks for. The shipped answer is Flare."""
        gemini = self.config.section("gemini") if self.config else {}
        return str(gemini.get("voice") or "Flare")

    def canonical_voices(self) -> tuple[str, ...]:
        """`[gemini] allowed_voices` — the one documented place the one-voice rule
        is expressed. Defaults to `("Flare",)`; changing her voice is an edit here,
        never a code change."""
        return canonical_voices(self.config)

    def voice_identity(self) -> dict:
        """Is the configured voice the canonical one? A mismatch is a REFUSAL.

        Never a silent adoption and never a shadowed winner: she says nothing,
        says why, and `assist doctor` fails the `voice routing` check until the
        config is either corrected or deliberately widened.
        """
        configured, canonical = self.configured_voice(), canonical_voices(self.config)
        effective, allowed = resolve_voice(self.config)
        model = config_voice_model(self.config)
        if allowed:
            # Regression (Stage A): `allowed` used to be True while `reason` still
            # read "refused ... not canonical". A pass must read as a pass.
            reason = (f"voice identity verified: [gemini] voice = {configured!r} is "
                      f"canonical (allowed: {', '.join(canonical)}) and routes through "
                      f"the Live model {model!r}")
        else:
            reason = (f"voice identity refused: [gemini] voice = {configured!r} is not "
                      f"canonical (allowed: {', '.join(canonical)}); she will not speak "
                      f"in an unapproved voice — correct [gemini] voice, or widen "
                      f"[gemini] allowed_voices deliberately")
        return {
            "configured": configured, "canonical": list(canonical), "allowed": allowed,
            "effective": effective, "model": model, "reason": reason,
        }

    def cloud_cache_identity(self) -> dict:
        """The audio identity of the CLOUD route: voice + model, nothing else.

        VB-1: this used to be the local Piper descriptor, so a voice change kept
        replaying the previous voice's files. The dormant path must never leak
        into a key that decides what the user hears online.
        """
        gemini = self.config.section("gemini") if self.config else {}
        return {
            "voice": self.voice_identity()["effective"],
            "model": config_voice_model(self.config),
            "sample_rate": int(gemini.get("voice_sample_rate", 24000)),
        }

    # -- status / routing ---------------------------------------------------------
    def status(self) -> dict:
        descriptor = self.descriptor()
        backend = self._make_backend()
        error = None
        if isinstance(backend, PiperTtsBackend):
            error = backend.availability_error()
        route, why = self.voice_route()
        identity = self.voice_identity()
        speaking_gemini = route == "gemini"
        silent = route == "silent"
        return {
            "enabled": bool(self.config.section("tts").get("enabled", True)),
            "backend": "gemini-native-audio" if speaking_gemini else ("none" if silent
                                                                       else backend.name),
            "voice_id": (identity["effective"] if speaking_gemini else
                        "none" if silent else backend.voice_id),
            "voice_mode": self.voice_mode_label(route),
            "posture": self._posture(),
            "one_voice_rule": "deferred (2026-10-20): one owned local voice is still the endgame",
            "switch_back": '[tts] online_voice = "local"',
            "local": route == "local",
            "cloud_voice": speaking_gemini,
            "muted": silent,
            "offline_output": "text only: Waybar, overlay, notification, log - no speech",
            "gemini_native_audio": speaking_gemini,
            "gemini_voice": identity["effective"] or "none",
            "gemini_voice_model": config_voice_model(self.config),
            "gemini_voice_api": "live",
            "class_mode": (self._presence.status().as_dict()
                           if self._presence is not None else None),
            "voice_identity": identity,
            "cache_identity": (self.cloud_cache_identity() if speaking_gemini else
                               {"voice": backend.voice_id,
                                "model": Path(self.descriptor().model).name,
                                "speaker": self.descriptor().speaker,
                                "length_scale": self.descriptor().length_scale}),
            "legacy_selection_ignored_online": bool(
                self.prefers_cloud_voice() and self.store
                and self.store.get_state(_SELECTED_KEY)),
            "ack_cache": self.ack_cache_state(),
            "dormant_local_voice": {
                "backend": backend.name, "voice_id": backend.voice_id,
                "available": error is None, "reason": error or "wired, but silent by default",
                "enable_with": '[tts] offline_voice = "local" (offline) or '
                               'online_voice = "local" (every mode)',
            },
            "voice_error": getattr(self, "last_voice_error", None),
            "available": True,
            "reason": why,
            "descriptor": descriptor.as_dict(),
            "cached_acks": [kind for kind in STANDARD_ACKS if self.cached_ack(kind)],
            "candidates": [c.voice_id for c in self.candidates()],
        }

    def route(self, text: str) -> dict:
        """Routing metadata without synthesis.

        Says which voice WOULD speak this text in the current posture: Flare
        online, nothing offline (text-only surfaces), the owned local voice only
        where a config key has explicitly un-dormanted it.
        """
        backend = self._make_backend()
        mode, _ = self.voice_route()
        return {
            "backend": {"gemini": "gemini-native-audio", "silent": "none"}.get(
                mode, backend.name),
            "voice_id": (self.voice_identity()["effective"] if mode == "gemini"
                        else ("none" if mode == "silent" else backend.voice_id)),
            "voice_mode": self.voice_mode_label(mode),
            "local": mode == "local",
            "cloud_voice": mode == "gemini",
            "muted": mode == "silent",
            "text_sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
        }

    # -- synthesis + playback -------------------------------------------------------
    def _cache_path(self, text: str, descriptor: VoiceDescriptor, backend_name: str,
                    *, identity: dict | None = None) -> Path:
        """Where this text's audio for `backend_name` lives.

        The key is the identity of the AUDIO, and only that: the cloud route keys
        on the Gemini voice + model (VB-1), the dormant local route on the local
        descriptor (voice, model, speaker, pace). A change to one route therefore
        cannot poison — or invalidate — the other (VB-2).
        """
        if identity is None:
            identity = {
                "voice": descriptor.voice_id, "model": Path(descriptor.model).name,
                "speaker": descriptor.speaker, "length_scale": descriptor.length_scale,
            }
        key = json.dumps({"text": text, "backend": backend_name, **identity},
                         sort_keys=True)
        return self.cache_dir / f"speech-{hashlib.sha256(key.encode()).hexdigest()[:20]}.wav"

    def _route_cache_path(self, text: str, route: str | None = None) -> Path:
        """Cache path for `text` under the ACTIVE route's own audio identity."""
        route = route or self.voice_route()[0]
        if route == "gemini":
            return self._cache_path(text, self.descriptor(), "gemini-native-audio",
                                    identity=self.cloud_cache_identity())
        backend = self._make_backend()
        return self._cache_path(text, self.descriptor(), backend.name)

    # -- interim online voice (Gemini native audio) --------------------------------
    def _gemini_client(self):
        """Lazy: only built when the interim online voice is actually selected."""
        if self._client is not None or self.config is None:
            return self._client
        settings = self.config.section("tts")
        if str(settings.get("online_voice", "gemini")).lower() != "gemini":
            return None
        try:
            from .gemini_client import GeminiClient
            self._client = GeminiClient(self.config, self.store)
        except Exception as exc:  # no key, no SDK - the local voice speaks
            self._client = _UnavailableClient(exc)
        return self._client

    def _posture(self) -> str:
        """'online', 'offline', or 'unknown' (no mode manager, e.g. the bare CLI)."""
        if self._is_online is None:
            return "unknown"
        return "online" if self._is_online() else "offline"

    def voice_mode_label(self, route: str) -> str:
        """What to call the current speaking posture. Silence says WHY it is silent.

        A cloud voice that is unavailable while online is a different fact from
        being offline, and conflating them would make `assist voice status` lie
        about the mode the daemon is actually in.
        """
        if route == "gemini":
            return "gemini-interim"
        if route == "local":
            return "local-one-voice"
        posture = self._posture()
        return {"offline": "offline-text-only",
                "unknown": "text-only-posture-unknown"}.get(
                    posture, "text-only-cloud-voice-unavailable")

    def prefers_cloud_voice(self) -> bool:
        """Does the config ASK for the cloud voice in this posture?

        Intent, not outcome: a refusal (unapproved voice, missing key, mock mode)
        stops the audio but does not change which voice setting is in charge. The
        precedence statement about the legacy local row is about intent, so it does
        not flicker every time the cloud becomes unreachable.
        """
        settings = self.config.section("tts") if self.config else {}
        if self._posture() == "offline":
            return False
        return str(settings.get("online_voice", "gemini")).lower() == "gemini"

    def voice_route(self) -> tuple[str, str]:
        """("gemini" | "silent" | "local", why). The one place the posture is decided.

        Owner amendment 2026-10-20: Flare is the ONLY voice in normal operation and
        offline mode has NO voice output at all (text only: Waybar, overlay,
        notification, log). The local Piper path stays in the tree but dormant - it
        speaks only when a config key explicitly asks for it, which is also the
        single switch for the future one-owned-voice endgame.

        Stage B: class mode is checked FIRST and is absolute — voice out OFF,
        spoken acks OFF — while the console stays fully usable.
        """
        if self._presence is not None:
            try:
                presence = self._presence.status()
            except Exception:            # a broken presence read must not speak
                presence = None
            if presence is not None and getattr(presence, "enabled", False):
                return "silent", (
                    "class mode: voice out OFF and spoken acks OFF; the console, "
                    "text replies and local tools remain fully usable")
        settings = self.config.section("tts") if self.config else {}
        online = str(settings.get("online_voice", "gemini")).lower()
        offline = str(settings.get("offline_voice", "none")).lower()
        online_now = self._posture() != "offline"

        if not online_now:
            if offline == "local":
                return "local", ("offline voice explicitly enabled "
                                  "(dormant local path; endgame posture)")
            return "silent", ("offline is text-only: Waybar/overlay/notification/log, "
                               "no speech (local voice is dormant)")

        if online == "local":
            return "local", "one-voice posture selected: owned local voice in every mode"
        if online == "none":
            return "silent", "online voice explicitly disabled; nothing is spoken"
        identity = self.voice_identity()
        if not identity["allowed"]:
            # Never adopt an unapproved voice silently, and never substitute the
            # dormant local one: refuse, report, and let doctor fail loudly.
            return "silent", identity["reason"]
        if self.store is not None:
            from .voice_catalogue import load_cached, validate_voice

            cached_cat = load_cached(self.store, identity["model"])
            if cached_cat is not None:
                cat_check = validate_voice(
                    identity["model"], identity["effective"], cached_cat
                )
                if not cat_check["ok"]:
                    return "silent", cat_check["error"]
        client = self._gemini_client()
        if client is None:
            return self._unavailable("no Gemini client available")
        if not client.can_speak():
            return self._unavailable(f"GEMINI_MODE={client.mode} cannot produce native audio")
        if self._is_online is None:
            # Posture unknown (no mode manager): never gamble a cloud call on it.
            return "silent", ("cannot confirm connectivity posture, so no speech - run it "
                              "through the daemon, which owns the mode")
        gemini = self.config.section("gemini")
        return "gemini", (f"INTERIM: {gemini.get('voice', 'Flare')} via Gemini native audio "
                          "is Elaria's only spoken voice; offline is text-only")

    def _unavailable(self, detail: str) -> tuple[str, str]:
        """Cloud voice missing is a reported silence, never a local workaround."""
        return "silent", (f"no speech: {detail}. Local voice is dormant by amendment "
                          "2026-10-20 (set [tts] online_voice = \"local\" to speak locally)")

    @staticmethod
    def write_wav(dest: Path, pcm: bytes, sample_rate: int) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.tmp-{os.getpid()}")
        try:
            with wave.open(str(tmp), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(int(sample_rate))
                out.writeframes(pcm)
            os.replace(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        return dest

    def _speak_with_gemini(self, text: str, path: Path) -> SpeechResult:
        """Native audio for `text`. A failure is a reported silence - the dormant
        local voice is never used to paper over a missing cloud voice."""
        client = self._gemini_client()
        if client is None:
            raise TtsUnavailable("no Gemini client available and the local voice is dormant")
        request = client.voice_request(text)
        try:
            audio = client.generate_voice(text, correlation_id="voice")
        except Exception as exc:
            self.last_voice_error = f"gemini native audio failed: {exc}"
            # §4.8: a synthesis failure is a visible marker — reported silence,
            # never a covered-over local voice. The text is kept in the journal.
            log_event("tts.failed", level="error", verdict="failed",
                      detail=(f"model_version={request.get('model')}; "
                              f"gemini native audio failed: {exc} — reported "
                              "silence; the local voice stays dormant"))
            raise TtsUnavailable(f"no speech for this turn: {exc}. The local voice is "
                                 "dormant by amendment 2026-10-20 and will not cover a "
                                 "cloud failure") from exc
        self.last_voice_error = None
        self.write_wav(path, audio["pcm"], audio.get("sample_rate", 24000))
        log_event("tts.synthesised", verdict="synthesised",
                  detail=(f"model_version={request.get('model')}; "
                          f"gemini-native-audio wrote {path} "
                          f"({len(audio.get('pcm', b'')) // 2} samples)"))
        return SpeechResult(text=text, backend="gemini-native-audio",
                            voice_id=str(request["voice_name"]), audio_path=str(path),
                            cached=False, local=False, cloud_voice=True)

    def synthesize(self, text: str, dest: Path | None = None, *,
                   use_cache: bool = True) -> SpeechResult:
        text = text.strip()
        if not text:
            raise ValueError("speech text is empty")
        backend = self._make_backend()
        route, why = self.voice_route()
        if (route == "silent" and self._backend_override is not None
                and dest is not None and self._is_online is None
                and not self._explicit_client):
            route = "local"
        if route == "silent":
            raise TtsUnavailable(why)
        key_name = "gemini-native-audio" if route == "gemini" else backend.name
        route_cache = self._route_cache_path(text, route)
        path = Path(dest).expanduser() if dest else route_cache
        cached = bool(
            use_cache
            and path == route_cache
            and path.exists()
            and path.stat().st_size > 0
        )
        if cached:
            # A cached Flare render is still a cloud voice, not a local one: the
            # flags follow the route, never the dataclass default.
            # §4.8: cache hits are their own event (WP1 splits the hit ratio
            # boilerplate vs generated text; WP0 logs the hit).
            log_event("tts.cached", verdict="cached",
                      detail=f"{key_name} cache hit at {path}")
            return SpeechResult(text=text, backend=key_name,
                                voice_id=(self.voice_identity()["effective"]
                                          if route == "gemini" else backend.voice_id),
                                audio_path=str(path), cached=True,
                                local=route != "gemini", cloud_voice=route == "gemini")
        if route == "gemini":
            return self._speak_with_gemini(text, path)
        try:
            backend.synthesize(text, path)
        except Exception as exc:
            log_event("tts.failed", level="error", verdict="failed",
                      detail=(f"{backend.name} synthesis failed: {exc} — "
                              "reported silence; no substitution"))
            raise
        log_event("tts.synthesised", verdict="synthesised",
                  detail=f"{backend.name} wrote {path}")
        return SpeechResult(text=text, backend=backend.name, voice_id=backend.voice_id,
                            audio_path=str(path), cached=False)

    @staticmethod
    def _playback_timeout_s(path: Path) -> float:
        """BH-K25: bound playback by the audio's own duration, not a flat
        120 s (which killed long utterances mid-speech and let a hung
        player sit on a 1 s chirp for two minutes)."""
        try:
            with wave.open(str(path), "rb") as wav:
                seconds = wav.getnframes() / max(1, wav.getframerate())
        except (wave.Error, OSError, EOFError):
            return 120.0
        return min(1800.0, max(15.0, seconds * 1.5 + 10.0))

    def _player_candidates(self) -> list[list[str]]:
        """Every player worth trying, in order (scene-3b, 2026-10-26).

        `auto` lists all installed players — the first binary is a PREFERENCE,
        not a commitment: a player that exists but fails (non-zero exit,
        spawn error, timeout) must not be the end of playback while another
        candidate could still make sound (the owner's paplay worked when the
        ack chain reported played:false).
        """
        setting = str(self.config.section("tts").get("player", "auto"))
        if setting == "none":
            return []
        if setting != "auto":
            parts = shlex.split(setting)
            return [parts] if parts and shutil.which(parts[0]) else []
        return [[c] for c in ("pw-play", "paplay", "aplay") if shutil.which(c)]

    def _play_with_detail(self, path: Path, *, synth_mark: float | None = None,
                          session_id: str | None = None) -> dict:
        """Play `path`, trying each candidate player in order.

        Returns {played, player, argv, returncode, error}: every failure mode
        (no player binary, spawn error, non-zero exit with the stderr tail,
        timeout) is recorded — silence with a reason, never a bare False.

        G.6: when `session_id` is given (the reply path), a successful
        spawn emits `audio.first_byte` — the playback-start sensor that
        closes the synth→audible blind spot. Acks keep their own events.
        """
        candidates = self._player_candidates()
        if not candidates:
            self.last_voice_error = (
                "no audio player available (pw-play/paplay/aplay) or "
                "[tts] player = none")
            return {"played": False, "player": None, "argv": None,
                    "returncode": None, "error": self.last_voice_error}
        attempts: list[str] = []
        last: dict = {}
        for command in candidates:
            argv = [*command, str(path)]
            # VB-10: the player is spawned with PR_SET_PDEATHSIG in its own
            # session, so a killed daemon cannot leave audio playing (or the
            # sink claimed). An injected test runner keeps the plain
            # signature — it must not have to know about prctl.
            protect = self._player_runner is subprocess.run
            spawn_mark = time.monotonic()
            try:
                result = self._player_runner(
                    argv, capture_output=True,
                    timeout=self._playback_timeout_s(path),
                    **(child_kwargs() if protect else {}))
            except (subprocess.TimeoutExpired, OSError) as exc:
                err = f"{command[0]}: {type(exc).__name__}: {exc}"
                attempts.append(err)
                last = {"played": False, "player": command[0], "argv": argv,
                        "returncode": None, "error": err}
                continue
            returncode = getattr(result, "returncode", 0)
            if returncode == 0:
                if session_id is not None:
                    since = ("" if synth_mark is None else
                             f"since_synth_s={round(spawn_mark - synth_mark, 3)}; ")
                    log_event("audio.first_byte", session_id=str(session_id),
                              verdict="audible",
                              detail=f"{since}player={command[0]}; wav={path.name}")
                last = {"played": True, "player": command[0], "argv": argv,
                        "returncode": 0, "error": "",
                        "play_mark": spawn_mark}
                return last
            stderr = getattr(result, "stderr", b"") or b""
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            err = f"{command[0]} exited {returncode}: {str(stderr).strip()[:200]}"
            attempts.append(err)
            last = {"played": False, "player": command[0], "argv": argv,
                    "returncode": returncode, "error": err}
        self.last_voice_error = "; ".join(attempts)[:400]
        return {**last, "played": False,
                "error": self.last_voice_error or "playback failed"}

    def play_audio(self, path: Path) -> bool:
        return bool(self._play_with_detail(path).get("played"))

    def speak(self, text: str, *, play: bool = True,
              session_id: str | None = None) -> SpeechResult:
        route, why = self.voice_route()
        if route == "silent":
            # Muted on purpose and reported as such - an intentional silence the
            # caller can show, not an error to chase and not a local voice sneaking
            # back in.
            return SpeechResult(text=text.strip(), backend="none", voice_id="none",
                                audio_path=None, local=False, cloud_voice=False,
                                muted=True, error=why)
        try:
            result = self.synthesize(text)
        except TtsUnavailable as exc:
            # Spoken failure is never fatal and never faked: the caller gets a muted
            # result carrying the reason, and the daemon broadcasts it as an event.
            self.last_voice_error = str(exc)
            return SpeechResult(text=text.strip(), backend="none", voice_id="none",
                                local=False, muted=True, error=str(exc))
        # G.6 marks: synthesize() has returned = synth complete (cache hits
        # included); the player spawn mark lands in _play_with_detail.
        result.synth_mark = time.monotonic()
        if play and result.audio_path:
            route_after, why_after = self.voice_route()
            if route_after == "silent":
                return SpeechResult(
                    text=text.strip(), backend="none", voice_id="none",
                    audio_path=result.audio_path, cached=result.cached,
                    played=False, local=False, cloud_voice=False,
                    muted=True, error=why_after,
                )
            detail = self._play_with_detail(Path(result.audio_path),
                                            synth_mark=result.synth_mark,
                                            session_id=session_id)
            result.played = bool(detail.get("played"))
            result.play_mark = detail.get("play_mark")
        return result

    # -- cached standard acks (§18 <300ms path) ---------------------------------------
    def _session_cue_path(self) -> Path:
        return self.cache_dir / "session-open-cue.wav"

    def ensure_session_cue(self) -> str | None:
        """Write a short neutral two-tone cue locally; no TTS and no network."""
        if self.voice_route()[0] == "silent":
            return None
        path = self._session_cue_path()
        try:
            if path.exists() and path.stat().st_size > 44:
                return str(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            rate, duration = 24000, 0.09
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(rate)
                pcm = bytearray()
                for index in range(int(rate * duration)):
                    moment = index / rate
                    envelope = min(1.0, moment / 0.01,
                                   (duration - moment) / 0.02)
                    frequency = 660.0 if moment < duration / 2 else 880.0
                    sample = int(6000 * envelope
                                 * math.sin(2 * math.pi * frequency * moment))
                    pcm += struct.pack("<h", sample)
                wav.writeframes(bytes(pcm))
            return str(path)
        except OSError:
            return None

    def _ack_path(self, kind: str) -> Path:
        """The ack file for `kind` UNDER THE ACTIVE ROUTE'S OWN IDENTITY.

        There is deliberately no fallback here. A missing Flare ack is a miss —
        reported, re-warmed, never answered with audio from another voice. The
        previous "a warmed local copy beats silence" substitution put the dormant
        Piper voice on an online turn, which is the one thing the owner forbade.
        """
        if kind == SESSION_CUE_KIND:
            return self._session_cue_path()
        route, why = self.voice_route()
        if route == "silent":
            raise TtsUnavailable(why)
        return self._route_cache_path(STANDARD_ACKS[kind], route)

    def ack_cache_state(self) -> dict:
        """Which of the four §18 acks are cached for the ACTIVE route's identity.

        Reported by `voice status` and the doctor so a cold cache is a visible
        state with a cure, never an unexplained silence (VB-2, VB-13).
        """
        route = self.voice_route()[0]
        if route == "silent":
            # Nothing is spoken, so nothing is missing - but the reason must say
            # that, not "all four cached", or the doctor implies audio that is not
            # there.
            return {"route": "silent", "complete": True, "missing": [], "speaks": False,
                    "reason": "nothing is spoken in this posture, so no acks are needed "
                              "(the reason is on the line above)"}
        missing = [kind for kind in STANDARD_ACKS if self.cached_ack(kind) is None]
        return {"route": route, "complete": not missing, "missing": missing, "speaks": True,
                "reason": ("all four acks cached for this voice identity" if not missing else
                           f"{len(missing)} ack(s) missing for the active voice — run "
                           f"`assist voice warm` (the daemon re-warms on its own)")}

    def request_rewarm(self) -> None:
        """Mark that the ACTIVE route's audio is missing. Idempotent, no I/O."""
        self._rewarm_requested = True

    def take_rewarm_request(self) -> bool:
        """Consume the flag: a long-lived host turns it into one warm cycle.

        VB-2: invalidation used to leave every ack a permanent silent miss until
        someone thought to run `assist voice warm`. The miss itself is now the
        trigger, so the hotkey path heals within one cycle.
        """
        requested = bool(getattr(self, "_rewarm_requested", False))
        self._rewarm_requested = False
        return requested

    def warm_due(self) -> dict:
        """One warm cycle, and only if the active route actually needs it.

        Returns the acks written this cycle (empty when the cache is already full
        or nothing is spoken). Renders off the hot path is the caller's job.
        """
        state = self.ack_cache_state()
        if not state["speaks"] or state["complete"]:
            self._rewarm_requested = False
            return {}
        warmed = self.warm_ack_cache()
        if not self.ack_cache_state()["missing"]:
            self._rewarm_requested = False
        return warmed

    def cached_ack(self, kind: str) -> str | None:
        if kind == SESSION_CUE_KIND:
            return self.ensure_session_cue()
        if kind not in STANDARD_ACKS:
            return None
        if self.voice_route()[0] == "silent":
            return None  # the ack path checks this, so a silent route means no sound
        path = self._ack_path(kind)
        if path.exists() and path.stat().st_size > 0:
            return str(path)
        # A miss on a route that is supposed to speak is a state with a cure, not
        # a verdict: request one warm cycle (VB-2) and let a long-lived host run
        # it off the hot path. Never substitute another voice's file.
        self.request_rewarm()
        return None

    def warm_ack_cache(self) -> dict[str, dict]:
        if self.voice_route()[0] == "silent":
            return {}  # nothing speaks, so nothing to pre-render
        if self.voice_route()[0] == "gemini":
            client = self._gemini_client()
            # Stage A: validate the model + voice against the real catalogue ONCE
            # before rendering four acks. A mismatch fails here, with the allowed
            # list, instead of four separate mid-sentence 400s.
            validator = getattr(client, "validate_speech_config", None)
            if callable(validator):
                try:
                    validator()
                except Exception as exc:
                    self.last_voice_error = f"voice validation failed: {exc}"
                    raise TtsUnavailable(f"no speech: {exc}") from exc
        # The session-open cue is sound, not a fifth spoken line; keep the
        # returned ack shape (four measured phrases) unchanged.
        self.ensure_session_cue()
        warmed = {}
        for kind, text in STANDARD_ACKS.items():
            warmed[kind] = self.synthesize(text, self._ack_path(kind)).as_dict()
        return warmed

    def play_ack(self, kind: str) -> dict:
        text = STANDARD_ACKS.get(kind, "")
        route = self.route(text)
        if self.voice_route()[0] == "silent":
            return {**route, "ack_kind": kind, "audio_path": None, "cached": False,
                    "played": False, "cache_miss": False, "muted": True,
                    "reason": self.voice_route()[1]}
        if kind == SESSION_CUE_KIND:
            cue = self.ensure_session_cue()
            if cue is None:
                return {**route, "ack_kind": kind, "audio_path": None,
                        "cached": False, "played": False, "cache_miss": True,
                        "warning": "neutral session cue could not be written"}
            detail = self._play_with_detail(Path(cue))
            return {**route, "ack_kind": kind, "audio_path": cue,
                    "cached": True, "played": detail["played"],
                    "cache_miss": False, "cue": True, "text": "",
                    "player": detail.get("player"), "argv": detail.get("argv"),
                    "error": detail.get("error") or None}
        path = self.cached_ack(kind)
        if path is None:
            # The ack budget forbids synthesising here. Report it as a cold cache
            # that needs warming (VB-2): a miss must never pass for intent, and
            # it is never filled in with another voice's file.
            self.request_rewarm()
            return {**route, "ack_kind": kind, "audio_path": None,
                    "cached": False, "played": False, "cache_miss": True,
                    "warning": "ack cache cold for the active voice — re-warming",
                    "rewarm_needed": True}
        if self.voice_route()[0] == "silent":
            return {**route, "ack_kind": kind, "audio_path": None, "cached": False,
                    "played": False, "cache_miss": False, "muted": True,
                    "reason": self.voice_route()[1]}
        detail = self._play_with_detail(Path(path))
        return {**route, "ack_kind": kind, "audio_path": path,
                "cached": True, "played": detail["played"],
                "cache_miss": False,
                "player": detail.get("player"), "argv": detail.get("argv"),
                "error": detail.get("error") or None}

    # -- auditions -----------------------------------------------------------------------
    def generate_auditions(self, text: str | None = None,
                           output_dir: Path | None = None) -> dict:
        script = text or AUDITION_SCRIPT
        output = Path(output_dir).expanduser() if output_dir else self.audition_dir
        output.mkdir(parents=True, exist_ok=True)
        entries = []
        for candidate in self.candidates():
            backend = self._make_backend(candidate)
            dest = output / f"{candidate.voice_id}.wav"
            entry = {**candidate.as_dict(), "audio_path": str(dest),
                     "traits_to_judge": ["brisk native pace", "bite", "edge", "dry"],
                     "reject_if": ["kind-polished", "corporate warmth"]}
            try:
                backend.synthesize(script, dest)
                entry["status"] = "ready"
            except Exception as exc:
                entry["status"] = "unavailable"
                entry["error"] = str(exc)
            entries.append(entry)
        manifest = {
            "script": script,
            "rule": "pick ONE; that local voice then speaks in every mode",
            "speed": "native Piper length-scale only; no time-stretching",
            "trait_references_only": ["Flare", "Vega"],
            "candidates": entries,
        }
        (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest
