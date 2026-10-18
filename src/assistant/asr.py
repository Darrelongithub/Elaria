"""ASR seam (§12.7) — the backend is a config change, not a rewrite.

Phase 0 ships the seam and the fallback chain resolver only:

    gemini_live ──429/disconnect──► gemini_batch ──offline──► local
     (primary,                        (same quality,             (small,
      streaming)                        ~1–3s latency)            English only)

Real backends land in Phase 1 (Live) behind this exact interface.
Languages are pinned explicitly from config — never auto-detected
(Whisper's silent-translation failure mode, §12.4) — and English-only
until Kiswahili flips on in Phase 7 via config alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PhasePending(NotImplementedError):
    """Honest stub: designed, seamed, scheduled — not secretly fake."""
    def __init__(self, backend: str, phase: str):
        super().__init__(f"ASR backend '{backend}' is {phase} (blueprint §9). "
                         "The seam exists now so Phase 1 fills it without "
                         "touching callers.")


@dataclass
class Transcript:
    text: str
    language: str
    backend: str
    confidence: float | None = None


class ASRBackend(Protocol):
    name: str

    def transcribe(self, audio_path: str, language: str) -> Transcript: ...


class _PendingBackend:
    def __init__(self, name: str, phase: str):
        self.name, self._phase = name, phase

    def transcribe(self, audio_path: str, language: str) -> Transcript:
        raise PhasePending(self.name, self._phase)


class MockASR:
    """Deterministic test backend — proves the seam with zero audio/network."""

    name = "mock"

    def transcribe(self, audio_path: str, language: str) -> Transcript:
        return Transcript(text=f"[mock transcript of {audio_path}]",
                          language=language, backend=self.name, confidence=1.0)


BACKEND_PHASES = {"gemini_live": "Phase 1", "gemini_batch": "Phase 1/6", "local": "offline fallback (§13.9)"}


def backend_chain(config) -> list[ASRBackend]:
    asr = config.section("asr")
    names = [asr.get("primary", "gemini_live")] + list(asr.get("fallback") or [])
    chain: list[ASRBackend] = []
    for name in names:
        chain.append(MockASR() if name == "mock"
                     else _PendingBackend(name, BACKEND_PHASES.get(name, "unscheduled")))
    return chain


def primary_language(config) -> str:
    languages = config.section("asr").get("languages") or ["en"]
    return str(languages[0])


def assert_output_language(transcript: Transcript, expected: list[str]) -> bool:
    """Catch silent translation (§12.4/§12.5). Phase 0: tag check only;
    the real language-mix gate arrives with the cleanup pass in Phase 1."""
    return transcript.language in expected
