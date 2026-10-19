"""One-voice local speech (Phase 8, humour.toml [elaria_voice]).

Hard rule: Elaria sounds identical online and offline. Therefore every
spoken reply in every mode goes through this one local service and the
one selected local voice. Gemini may produce text; Gemini native audio
is never Elaria's voice. If the local voice is unavailable, the honest
degradation is text/silence — never a second, cloud voice.

Speed is Piper's native `--length-scale`. There is deliberately no
ffmpeg/sox/atempo-style time-stretching anywhere in this module.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import shlex
import shutil
import struct
import subprocess
import sys
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

STANDARD_ACKS = {
    "on_it": "On it.",
    "done": "Done.",
    "checkin": "Is that all?",
    "not_at_this_hour": "No. Not at this hour.",
}

AUDITION_SCRIPT = (
    "On it. Done. Is that all? No. Not at this hour. "
    "Sasa, the March invoice is filed. The six ambiguous ones are parked, "
    "not guessed at."
)

_SELECTED_KEY = "tts.selected_voice"


class TtsUnavailable(RuntimeError):
    pass


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
        return cls(
            voice_id=str(data.get("id") or data.get("voice_id") or "unselected"),
            model=str(data.get("model") or ""),
            config=str(data.get("config") or ""),
            speaker=int(data.get("speaker") or 0),
            length_scale=float(data.get("length_scale") or 0.92),
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
    error: str | None = None

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
        result = self._runner(args, input=text, text=True, capture_output=True, timeout=120)
        if getattr(result, "returncode", 0) != 0:
            detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "").strip()
            raise TtsUnavailable(f"Piper failed ({result.returncode}): {detail[:300]}")
        if not dest.exists() or dest.stat().st_size == 0:
            raise TtsUnavailable("Piper reported success but produced no WAV file")
        return dest


class SpeechService:
    """The only speech-output service. Callers never pick a voice."""

    def __init__(self, config, store=None, *, backend: TtsBackend | None = None,
                 runner=None, player_runner=None):
        self.config = config
        self.store = store
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
        return VoiceDescriptor(
            voice_id=str(settings.get("voice_id", "unselected")),
            model=str(settings.get("model", "")),
            config=str(settings.get("config", "")),
            speaker=int(settings.get("speaker", 0)),
            length_scale=float(settings.get("length_scale", 0.92)),
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

    # -- status / routing ---------------------------------------------------------
    def status(self) -> dict:
        descriptor = self.descriptor()
        backend = self._make_backend()
        error = None
        if isinstance(backend, PiperTtsBackend):
            error = backend.availability_error()
        return {
            "enabled": bool(self.config.section("tts").get("enabled", True)),
            "backend": backend.name,
            "voice_id": backend.voice_id,
            "local": True,
            "cloud_voice": False,
            "gemini_native_audio": False,
            "available": error is None,
            "reason": error or "one local voice is configured for every mode",
            "descriptor": descriptor.as_dict(),
            "cached_acks": [kind for kind in STANDARD_ACKS if self.cached_ack(kind)],
            "candidates": [c.voice_id for c in self.candidates()],
        }

    def route(self, text: str) -> dict:
        """Routing metadata without synthesis — proves online/offline parity."""
        backend = self._make_backend()
        return {
            "backend": backend.name,
            "voice_id": backend.voice_id,
            "local": True,
            "cloud_voice": False,
            "text_sha256": hashlib.sha256(text.encode()).hexdigest()[:16],
        }

    # -- synthesis + playback -------------------------------------------------------
    def _cache_path(self, text: str, descriptor: VoiceDescriptor, backend_name: str) -> Path:
        key = json.dumps({
            "text": text, "backend": backend_name, "voice": descriptor.voice_id,
            "model": Path(descriptor.model).name, "speaker": descriptor.speaker,
            "length_scale": descriptor.length_scale,
        }, sort_keys=True)
        return self.cache_dir / f"speech-{hashlib.sha256(key.encode()).hexdigest()[:20]}.wav"

    def synthesize(self, text: str, dest: Path | None = None, *,
                   use_cache: bool = True) -> SpeechResult:
        text = text.strip()
        if not text:
            raise ValueError("speech text is empty")
        descriptor = self.descriptor()
        backend = self._make_backend()
        path = Path(dest).expanduser() if dest else self._cache_path(text, descriptor, backend.name)
        cached = bool(use_cache and path.exists() and path.stat().st_size > 0)
        if not cached:
            backend.synthesize(text, path)
        return SpeechResult(text=text, backend=backend.name, voice_id=backend.voice_id,
                            audio_path=str(path), cached=cached)

    def _player_command(self) -> list[str] | None:
        setting = str(self.config.section("tts").get("player", "auto"))
        if setting == "none":
            return None
        if setting != "auto":
            parts = shlex.split(setting)
            return parts if parts and shutil.which(parts[0]) else None
        for candidate in ("pw-play", "paplay", "aplay"):
            if shutil.which(candidate):
                return [candidate]
        return None

    def play_audio(self, path: Path) -> bool:
        command = self._player_command()
        if command is None:
            return False
        result = self._player_runner([*command, str(path)], capture_output=True, timeout=120)
        return getattr(result, "returncode", 0) == 0

    def speak(self, text: str, *, play: bool = True) -> SpeechResult:
        result = self.synthesize(text)
        if play and result.audio_path:
            result.played = self.play_audio(Path(result.audio_path))
        return result

    # -- cached standard acks (§18 <300ms path) ---------------------------------------
    def _ack_path(self, kind: str) -> Path:
        descriptor = self.descriptor()
        backend = self._make_backend()
        return self._cache_path(STANDARD_ACKS[kind], descriptor, backend.name)

    def cached_ack(self, kind: str) -> str | None:
        if kind not in STANDARD_ACKS:
            return None
        path = self._ack_path(kind)
        return str(path) if path.exists() and path.stat().st_size > 0 else None

    def warm_ack_cache(self) -> dict[str, dict]:
        warmed = {}
        for kind, text in STANDARD_ACKS.items():
            warmed[kind] = self.synthesize(text, self._ack_path(kind)).as_dict()
        return warmed

    def play_ack(self, kind: str) -> dict:
        route = self.route(STANDARD_ACKS.get(kind, ""))
        path = self.cached_ack(kind)
        if path is None:
            # The ack budget forbids synthesising here; warm at startup instead.
            return {**route, "ack_kind": kind, "audio_path": None,
                    "cached": False, "played": False, "cache_miss": True}
        return {**route, "ack_kind": kind, "audio_path": path,
                "cached": True, "played": self.play_audio(Path(path)),
                "cache_miss": False}

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
