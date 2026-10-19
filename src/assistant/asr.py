"""ASR seam (§12.7) — the backend is a config change, not a rewrite.

    gemini_live ──429/disconnect──► gemini_batch ──offline──► local
     (primary,                        (same quality,             (small,
      streaming)                        ~1–3s latency)            English only)

Phase 1 state: Live transport factory + batch transcription are wired
through `GeminiClient` (ledgered, fixture-able). Local Whisper stays an
honest pending stub — §12.6: on the owner's UHD 620 it's an offline
emergency fallback at best, and unusable for Kiswahili regardless.

Languages are pinned explicitly from config — never auto-detected
(Whisper's silent-translation failure mode, §12.4) — English-only until
Kiswahili flips on in Phase 7 via config alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .fixtures import FixtureStore
from .live_client import (
    FixtureLiveTransport,
    GenaiLiveTransport,
    LiveTransport,
    ScriptedLiveTransport,
)


class PhasePending(NotImplementedError):
    """Honest stub: designed, seamed, scheduled — not secretly fake."""
    def __init__(self, backend: str, phase: str):
        super().__init__(f"ASR backend '{backend}' is {phase} (blueprint §9). "
                         "The seam exists now so filling it never touches callers.")


@dataclass
class Transcript:
    text: str
    language: str
    backend: str
    confidence: float | None = None


class BatchBackend(Protocol):
    name: str

    def transcribe(self, audio_path: str, language: str) -> Transcript: ...


def configured_languages(config) -> list[str]:
    """The pinned language set (§12.4: pinned, NEVER auto-detected).
    Phase 7 flips this to ["sw", "en"] in config — nothing else moves."""
    languages = config.section("asr").get("languages") or ["en"]
    return [str(lang) for lang in languages]


def code_switching_enabled(config) -> bool:
    return bool(config.section("asr").get("preserve_code_switching")) and \
        len(configured_languages(config)) > 1


class GeminiBatchBackend:
    name = "gemini_batch"

    def __init__(self, client, config=None):
        self._client = client
        self._config = config

    def transcribe(self, audio_path: str, language: str) -> Transcript:
        if self._config is not None:
            languages = configured_languages(self._config)
            result = self._client.transcribe_batch(
                Path(audio_path), languages[0], also_languages=languages[1:],
                preserve_code_switching=code_switching_enabled(self._config))
            return Transcript(text=result["text"],
                              language=",".join(languages), backend=self.name)
        result = self._client.transcribe_batch(Path(audio_path), language)
        return Transcript(text=result["text"], language=language, backend=self.name)


class _LocalPending:
    name = "local"

    def transcribe(self, audio_path: str, language: str) -> Transcript:
        raise PhasePending("local", "offline-only fallback (§13.9); whisper.cpp "
                                   "`small`, English only, not yet wired")


class MockASR:
    """Deterministic test backend — proves the seam with zero audio/network."""

    name = "mock"

    def transcribe(self, audio_path: str, language: str) -> Transcript:
        return Transcript(text=f"[mock transcript of {audio_path}]",
                          language=language, backend=self.name, confidence=1.0)


def batch_chain(config, client) -> list[BatchBackend]:
    """Ordered file-transcription fallbacks (live streaming is separate)."""
    asr = config.section("asr")
    names = [n for n in (asr.get("fallback") or []) if n != "gemini_live"]
    chain: list[BatchBackend] = []
    for name in names or ["gemini_batch"]:
        if name == "gemini_batch":
            chain.append(GeminiBatchBackend(client, config))
        elif name == "mock":
            chain.append(MockASR())
        else:
            chain.append(_LocalPending())
    return chain


def transcribe_file(config, client, audio_path: str) -> Transcript:
    """Walk the fallback chain until one backend produces text (§12.7:
    quota exhaustion degrades instead of failing)."""
    language = primary_language(config)
    errors: list[str] = []
    for backend in batch_chain(config, client):
        try:
            return backend.transcribe(audio_path, language)
        except Exception as exc:
            errors.append(f"{backend.name}: {exc}")
    raise RuntimeError("all ASR backends failed — " + " | ".join(errors))


def make_live_transport(config, *, fixture_name: str | None = None) -> LiveTransport:
    """Factory for the streaming path, by effective GEMINI_MODE."""
    if fixture_name:
        return FixtureLiveTransport(FixtureStore(config.fixtures_dir), fixture_name)
    if config.gemini_mode == "mock":
        return ScriptedLiveTransport()
    model = config.model_for_role("transcribe_live")
    return GenaiLiveTransport(config.api_key, model, primary_language(config))


def primary_language(config) -> str:
    return configured_languages(config)[0]


def assert_output_language(transcript: Transcript, expected: list[str]) -> bool:
    """Catch silent translation (§12.4/§12.5). Tag check here (bilingual
    tags like 'sw,en' must be a subset of the configured set); the
    content-level marker gate lives in cleanup.language_mix_preserved."""
    produced = {part.strip() for part in transcript.language.split(",")}
    return produced <= set(expected)
