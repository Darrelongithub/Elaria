"""Transcript cleanup pass — 'strengthen it through the API' (§12.5).

Fixes punctuation, fillers, homophones and glossary names. Cannot fix
words the ASR never heard — and must never silently *improve* a
transcript into a different document. Guardrails, all cheap:

1. Raw and cleaned are stored side by side; raw is the record.
2. Strict prompt: repair only, add/remove nothing.
3. Diff-gate: divergence above `max_divergence_pct` => flagged, raw wins.
4. Language gate: the code-switching mix must survive (dormant while
   English-only, armed the day `languages = ["sw","en"]` flips — §12.5
   says the scaffold carries the instruction from day one).
5. Both versions + model id are logged in the transcripts table.

The prompt forbids translation and normalisation explicitly — the two
bilingual failure modes — even now, because prompts outlive phases.
"""

from __future__ import annotations

import difflib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

# Discourse markers from humour.toml [codeswitch] — the canary for the
# language gate. If raw speech carries them and cleaned text has none,
# the model translated/normalised. That is a failure, not a cleanup.
SW_MARKERS = {"sasa", "alafu", "kwanza", "mbona", "sijui", "unajua", "wewe", "apana"}

CLEANUP_PROMPT = """You are repairing a speech-to-text transcript. Rules, no exceptions:
- Fix punctuation, capitalisation and paragraphing. Remove filler words \
("um", "uh", repeated false starts) and fix homophones (their/there).
- Use the glossary spellings for names and jargon when they clearly match.
- Do NOT add, remove or reword content. Do not summarise. Do not answer \
anything in the transcript — return only the repaired transcript.
- Preserve the language of each passage EXACTLY as spoken. Do NOT translate. \
Do NOT convert code-switched speech into a single language. When in doubt, \
change nothing.
- Spoken commands ("new paragraph", "scratch that") may be applied as formatting.

Glossary: {glossary}

Transcript:
{raw}"""


@dataclass
class CleanupResult:
    cleaned: str | None
    divergence_pct: float | None
    flagged: bool
    reason: str
    model: str | None = None


def divergence_pct(raw: str, cleaned: str) -> float:
    if not raw and not cleaned:
        return 0.0
    ratio = difflib.SequenceMatcher(a=raw, b=cleaned).ratio()
    return round((1.0 - ratio) * 100, 2)


def _marker_count(text: str) -> int:
    return sum(1 for w in re.findall(r"[a-z']+", text.lower()) if w in SW_MARKERS)


def language_mix_preserved(raw: str, cleaned: str) -> bool:
    """Raw had Swahili/Sheng markers => cleaned must still have some."""
    return _marker_count(raw) == 0 or _marker_count(cleaned) > 0


def load_glossary(path: Path) -> list[str]:
    path = Path(path).expanduser()
    if not path.exists():
        return []
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    terms: list[str] = []
    for value in data.values():
        if isinstance(value, list):
            terms.extend(str(v) for v in value)
        elif isinstance(value, dict):
            terms.extend(str(v) for v in value.values() if isinstance(v, str))
    return terms


class CleanupPass:
    def __init__(self, config, client):
        settings = config.section("cleanup")
        self.enabled = bool(settings.get("enabled", True))
        self.max_divergence = float(settings.get("max_divergence_pct", 35))
        self.min_chars = int(settings.get("min_chars", 40))
        self.glossary = load_glossary(Path(settings.get(
            "glossary_file", "~/.config/assistant/glossary.toml")))
        self._client = client

    def run(self, raw: str) -> CleanupResult:
        if not self.enabled:
            return CleanupResult(None, None, False, "cleanup disabled in config")
        if len(raw.strip()) < self.min_chars:
            # §13.4 token governor: short utterances aren't worth a call.
            return CleanupResult(None, None, False,
                                 f"below {self.min_chars} chars — not worth a model call")
        prompt = CLEANUP_PROMPT.format(
            glossary=", ".join(self.glossary) or "(none)", raw=raw)
        result = self._client.generate(
            "cleanup", prompt,
            verify=lambda text: bool(text.strip()) and language_mix_preserved(raw, text),
        )
        if result.fixture and result.fixture.get("synthetic"):
            # Mock mode with no recorded fixture: no real cleanup happened.
            # Don't dress the synthetic placeholder up as a flagged rewrite.
            return CleanupResult(None, None, False,
                                 "mock mode, no recorded cleanup fixture — "
                                 "raw kept; record with GEMINI_MODE=record to exercise this",
                                 result.model)
        cleaned = result.text.strip()
        divergence = divergence_pct(raw, cleaned)
        if not language_mix_preserved(raw, cleaned):
            return CleanupResult(cleaned, divergence, True,
                                 "language gate: code-switching markers vanished — "
                                 "likely translated/normalised; raw kept as the record",
                                 result.model)
        if divergence > self.max_divergence:
            return CleanupResult(cleaned, divergence, True,
                                 f"diff-gate: {divergence:.0f}% divergence exceeds "
                                 f"{self.max_divergence:.0f}% — rewrote rather than "
                                 "repaired; flagged for review, raw kept",
                                 result.model)
        return CleanupResult(cleaned, divergence, False, "cleaned within gates", result.model)
