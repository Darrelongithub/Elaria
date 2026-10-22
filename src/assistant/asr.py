"""ASR seam (§12.7) — the backend is a config change, not a rewrite.

    gemini_live ──429/disconnect──► gemini_batch ──offline──► local
     (primary,                        (same quality,             (small,
      streaming)                        ~1–3s latency)            English first)

Phase 8 fills the local end of the seam with faster-whisper or
whisper.cpp. It is a competent offline fallback for commands and notes,
not a claim of cloud parity: low-confidence results carry their
confidence upward so dictation can queue a Gemini redo on reconnect.

Languages are pinned explicitly from config — never auto-detected
(Whisper's silent-translation failure mode, §12.4). English is the
supported offline path; a pinned Swahili primary is passed through
explicitly and remains best-effort locally.
"""

from __future__ import annotations

import importlib.util
import json
import math
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .fixtures import FixtureStore
from .live_client import (
    FixtureLiveTransport,
    GenaiLiveTransport,
    LiveTransport,
    RecordingTransport,
    ScriptedLiveTransport,
)


@dataclass
class Transcript:
    text: str
    language: str
    backend: str
    confidence: float | None = None
    # BH-K19: False when the backend's language tag fell outside the
    # pinned set and no better backend produced text — degraded but
    # marked, so the caller can surface it instead of silently
    # trusting possibly-translated output (§12.4).
    language_ok: bool = True


class BatchBackend(Protocol):
    name: str

    def transcribe(self, audio_path: str, language: str) -> Transcript: ...


def configured_languages(config) -> list[str]:
    """The pinned language set (§12.4: pinned, NEVER auto-detected).
    Phase 7 flips this to ["sw", "en"] in config — nothing else moves."""
    languages = config.section("asr").get("languages") or ["en"]
    if isinstance(languages, str):
        languages = [languages]
    return [str(lang) for lang in languages if str(lang).strip()]


def code_switching_enabled(config) -> bool:
    return bool(config.section("asr").get("preserve_code_switching")) and \
        len(configured_languages(config)) > 1


class GeminiBatchBackend:
    name = "gemini_batch"

    def __init__(self, client, config=None):
        self._client = client
        self._config = config

    def transcribe(self, audio_path: str, language: str, *,
                   deadline: float | None = None) -> Transcript:
        deadline_option = {"deadline": deadline} if deadline is not None else {}
        if self._config is not None:
            languages = configured_languages(self._config)
            result = self._client.transcribe_batch(
                Path(audio_path), languages[0], also_languages=languages[1:],
                preserve_code_switching=code_switching_enabled(self._config),
                **deadline_option)
            return Transcript(text=result["text"],
                              language=",".join(languages), backend=self.name)
        result = self._client.transcribe_batch(
            Path(audio_path), language, **deadline_option)
        return Transcript(text=result["text"], language=language, backend=self.name)

    async def transcribe_async(self, audio_path: str, language: str, *,
                               deadline: float | None = None) -> Transcript:
        transcribe = getattr(self._client, "transcribe_batch_async", None)
        if not callable(transcribe):
            return self.transcribe(audio_path, language, deadline=deadline)
        deadline_option = {"deadline": deadline} if deadline is not None else {}
        if self._config is not None:
            languages = configured_languages(self._config)
            result = await transcribe(
                Path(audio_path), languages[0], also_languages=languages[1:],
                preserve_code_switching=code_switching_enabled(self._config),
                **deadline_option)
            return Transcript(text=result["text"],
                              language=",".join(languages), backend=self.name)
        result = await transcribe(Path(audio_path), language, **deadline_option)
        return Transcript(text=result["text"], language=language, backend=self.name)


def _segment_confidence(segments: list) -> float | None:
    """Duration-weighted exp(avg_logprob), the confidence faster-whisper
    exposes. No segment probabilities -> None (unknown, therefore queued
    by dictation's low-confidence policy rather than silently trusted)."""
    weighted = 0.0
    weights = 0.0
    for segment in segments:
        logprob = getattr(segment, "avg_logprob", None)
        if logprob is None and isinstance(segment, dict):
            logprob = segment.get("avg_logprob")
        if logprob is None:
            continue
        start = getattr(segment, "start", 0.0) if not isinstance(segment, dict) else segment.get("start", 0.0)
        end = getattr(segment, "end", 0.0) if not isinstance(segment, dict) else segment.get("end", 0.0)
        weight = max(0.1, float(end or 0.0) - float(start or 0.0))
        weighted += math.exp(max(-20.0, min(0.0, float(logprob)))) * weight
        weights += weight
    return round(weighted / weights, 4) if weights else None


class LocalWhisperBackend:
    """Local Whisper behind the existing BatchBackend seam.

    Engines are lazy/optional: faster-whisper (`--extra offline`) or a
    whisper.cpp executable. A `mock` engine exists for deterministic
    development/tests and labels itself mock in the text it returns.
    """

    name = "local"

    def __init__(self, config=None, *, model_loader=None, runner=None):
        self.config = config
        settings = config.section("asr") if config else {}
        self.engine = str(settings.get("offline_backend", "faster-whisper")).lower()
        self.model_name = str(settings.get("offline_model", "small"))
        self.device = str(settings.get("offline_device", "cpu"))
        self.compute_type = str(settings.get("offline_compute_type", "int8"))
        self.whisper_cpp_command = str(settings.get("whisper_cpp_command", "whisper-cli"))
        self.whisper_cpp_model = str(settings.get("whisper_cpp_model", ""))
        self._settings = settings
        self._model_loader = model_loader
        self._runner = runner or subprocess.run
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        if self._model_loader is not None:
            self._model = self._model_loader(self.model_name)
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "offline ASR needs faster-whisper: `uv sync --extra offline` "
                "(or set asr.offline_backend='whisper.cpp')") from exc
        self._model = WhisperModel(self.model_name, device=self.device,
                                   compute_type=self.compute_type)
        return self._model

    def transcribe(self, audio_path: str, language: str) -> Transcript:
        pinned = (language or "en").split(",")[0].strip() or "en"
        if self.engine == "mock":
            return Transcript(
                text=str(self._settings.get(
                    "offline_mock_text", "[mock offline transcript]")),
                language=pinned, backend=self.name,
                confidence=float(self._settings.get("offline_mock_confidence", 0.5)))
        if self.engine in ("whisper.cpp", "whisper-cpp", "whisper_cpp"):
            return self._transcribe_whisper_cpp(audio_path, pinned)
        model = self._load_model()
        segments_iter, _info = model.transcribe(
            audio_path, language=pinned, task="transcribe", vad_filter=True)
        segments = list(segments_iter)
        text = " ".join(
            str(getattr(s, "text", "") if not isinstance(s, dict) else s.get("text", "")).strip()
            for s in segments).strip()
        return Transcript(text=text, language=pinned, backend=self.name,
                          confidence=_segment_confidence(segments))

    def _transcribe_whisper_cpp(self, audio_path: str, language: str) -> Transcript:
        if not self.whisper_cpp_model:
            raise RuntimeError(
                "whisper.cpp offline ASR needs asr.whisper_cpp_model=/path/to/ggml-small.bin")
        command = shlex.split(self.whisper_cpp_command)
        if not command:
            raise RuntimeError("whisper.cpp command is empty")
        with tempfile.TemporaryDirectory(prefix="elaria-whisper-") as tmp:
            prefix = Path(tmp) / "transcript"
            args = [*command, "-m", str(Path(self.whisper_cpp_model).expanduser()),
                    "-f", str(audio_path), "-l", language, "-oj", "-of", str(prefix)]
            result = self._runner(args, capture_output=True, text=True, timeout=900)
            if getattr(result, "returncode", 0) != 0:
                detail = (getattr(result, "stderr", "") or getattr(result, "stdout", "") or "")
                raise RuntimeError(f"whisper.cpp failed ({result.returncode}): {detail[:300]}")
            payload = json.loads(Path(f"{prefix}.json").read_text(encoding="utf-8"))
        pieces = []
        probabilities = []
        for segment in payload.get("transcription") or []:
            pieces.append(str(segment.get("text") or "").strip())
            for token in segment.get("tokens") or []:
                if isinstance(token, dict) and token.get("p") is not None:
                    probabilities.append(float(token["p"]))
        confidence = round(sum(probabilities) / len(probabilities), 4) if probabilities else None
        return Transcript(text=" ".join(p for p in pieces if p).strip(),
                          language=language, backend=self.name, confidence=confidence)


# Backwards-compatible private name for older imports/tests.
_LocalPending = LocalWhisperBackend


class MockASR:
    """Deterministic test backend — proves the seam with zero audio/network."""

    name = "mock"

    def transcribe(self, audio_path: str, language: str) -> Transcript:
        return Transcript(text=f"[mock transcript of {audio_path}]",
                          language=language, backend=self.name, confidence=1.0)


def batch_chain(config, client, *, offline: bool = False,
                local_backend: BatchBackend | None = None) -> list[BatchBackend]:
    """Ordered file-transcription fallbacks (live streaming is separate).

    `offline=True` is structural, not advisory: the returned chain contains
    only the local backend, so forced-offline cannot reach GeminiClient.
    """
    if offline:
        return [local_backend or LocalWhisperBackend(config)]
    asr = config.section("asr")
    names = [n for n in (asr.get("fallback") or []) if n != "gemini_live"]
    chain: list[BatchBackend] = []
    for name in names or ["gemini_batch"]:
        if name == "gemini_batch":
            chain.append(GeminiBatchBackend(client, config))
        elif name == "mock":
            chain.append(MockASR())
        else:
            chain.append(local_backend or LocalWhisperBackend(config))
    return chain


def transcribe_file(config, client, audio_path: str, *, offline: bool = False,
                    local_backend: BatchBackend | None = None) -> Transcript:
    """Walk the fallback chain until one backend produces text (§12.7:
    quota exhaustion degrades instead of failing)."""
    language = primary_language(config)
    # BH-K19: [asr] assert_output_language promised this check since the
    # blueprint (§12.4) but nothing called it. Enforced here, at the one
    # seam every batch transcript crosses: an out-of-set tag is passed
    # over for the next backend, and only returned (marked) if nothing
    # better produced text.
    assert_language = bool(config.section("asr").get(
        "assert_output_language", True))
    expected = configured_languages(config)
    errors: list[str] = []
    last_empty: Transcript | None = None
    last_flagged: Transcript | None = None
    for backend in batch_chain(config, client, offline=offline,
                               local_backend=local_backend):
        try:
            result = backend.transcribe(audio_path, language)
            if result.text and result.text.strip():
                if assert_language and not assert_output_language(result, expected):
                    errors.append(
                        f"{backend.name}: language tag {result.language!r} "
                        f"outside pinned set {expected}")
                    result.language_ok = False
                    last_flagged = result
                    continue
                return result
            last_empty = result
            errors.append(f"{backend.name}: empty transcript")
        except Exception as exc:
            errors.append(f"{backend.name}: {exc}")
    if last_flagged is not None:
        return last_flagged
    if last_empty is not None:
        return last_empty
    raise RuntimeError("all ASR backends failed — " + " | ".join(errors))


def local_asr_status(config) -> dict:
    """Doctor/status view without loading a model or touching network."""
    settings = config.section("asr")
    engine = str(settings.get("offline_backend", "faster-whisper")).lower()
    if engine == "mock":
        available, reason = True, "mock local backend (development/tests)"
    elif engine in ("whisper.cpp", "whisper-cpp", "whisper_cpp"):
        command = shlex.split(str(settings.get("whisper_cpp_command", "whisper-cli")))
        model = Path(str(settings.get("whisper_cpp_model", ""))).expanduser()
        available = bool(command and shutil.which(command[0]) and str(model) and model.exists())
        reason = ("whisper.cpp command + model present" if available
                  else "whisper.cpp command/model missing")
    else:
        available = importlib.util.find_spec("faster_whisper") is not None
        reason = ("faster-whisper installed; model loads locally on first use"
                  if available else "install with `uv sync --extra offline`")
    return {
        "backend": "local",
        "engine": engine,
        "model": settings.get("offline_model", "small"),
        "available": available,
        "reason": reason,
        "languages": configured_languages(config),
        "supported_note": "English first; other pinned languages best-effort offline",
    }


def make_live_transport(config, *, fixture_name: str | None = None) -> LiveTransport:
    """Factory for the streaming path, by effective GEMINI_MODE."""
    if fixture_name:
        return FixtureLiveTransport(FixtureStore(config.fixtures_dir), fixture_name)
    if config.gemini_mode == "mock":
        return ScriptedLiveTransport()
    model = config.model_for_role("transcribe_live")
    transport = GenaiLiveTransport(config.api_key, model, primary_language(config))
    if config.gemini_mode == "record":
        # §12.9: record = real API + fixtures saved, streaming included.
        # BH-K4: this wrap was missing, so record mode never produced a
        # seq-live.jsonl — the exact evidence needed to debug the hardware
        # "no final after activity_end" report. RecordingTransport logs
        # audio as hash+size only; the sequence lands on close().
        return RecordingTransport(
            transport, FixtureStore(config.fixtures_dir), "live")
    return transport


def primary_language(config) -> str:
    return configured_languages(config)[0]


def assert_output_language(transcript: Transcript, expected: list[str]) -> bool:
    """Catch silent translation (§12.4/§12.5). Tag check here (bilingual
    tags like 'sw,en' must be a subset of the configured set); the
    content-level marker gate lives in cleanup.language_mix_preserved."""
    produced = {part.strip() for part in transcript.language.split(",")}
    return produced <= set(expected)
