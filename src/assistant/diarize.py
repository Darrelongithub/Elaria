"""Diarization (§12.4) — who spoke when, language-agnostically.

Two paths, one data shape (Turn):
  Channel turns  meeting mode captures mic and sink separately, so the
                 channel itself is the label: mic → 'You', sink → 'Them'.
                 Exact, free, works in any language — the default.
  pyannote       optional post-pass (`uv sync --extra diarize`) for
                 single-stream recordings with several voices on one
                 side. Slow on CPU but it's a post-pass — overnight is
                 fine. Needs a HuggingFace token for model download;
                 the error says so plainly when missing.

Gemini transcribes (strong Kiswahili/English), diarization labels —
independence is the architecture (§12.4): merge by timestamp overlap.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Turn:
    speaker: str
    start_s: float
    end_s: float
    text: str = ""


def overlap_s(a_start, a_end, b_start, b_end) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def assign_speakers(utterances: list[Turn], turns: list[Turn]) -> list[Turn]:
    """Label each utterance with the speaker turn it overlaps most.
    Unmatched utterances keep their existing speaker (channel default)."""
    for utterance in utterances:
        best, best_overlap = None, 0.0
        for turn in turns:
            amount = overlap_s(utterance.start_s, utterance.end_s,
                               turn.start_s, turn.end_s)
            if amount > best_overlap:
                best, best_overlap = turn, amount
        if best is not None:
            utterance.speaker = best.speaker
    return sorted(utterances, key=lambda u: u.start_s)


def merge_adjacent(turns: list[Turn], gap_s: float = 0.8) -> list[Turn]:
    """Glue same-speaker turns separated by a breath into one turn."""
    merged: list[Turn] = []
    for turn in sorted(turns, key=lambda t: t.start_s):
        if (merged and merged[-1].speaker == turn.speaker
                and turn.start_s - merged[-1].end_s <= gap_s):
            merged[-1].end_s = turn.end_s
            merged[-1].text = (merged[-1].text + " " + turn.text).strip()
        else:
            merged.append(Turn(turn.speaker, turn.start_s, turn.end_s, turn.text))
    return merged


def format_transcript(turns: list[Turn]) -> str:
    lines = []
    for turn in merge_adjacent(turns):
        stamp = f"{int(turn.start_s // 60):02d}:{int(turn.start_s % 60):02d}"
        lines.append(f"[{stamp}] {turn.speaker}: {turn.text}".rstrip())
    return "\n".join(lines)


class PyannoteDiarizer:  # pragma: no cover - optional dependency + HF token
    """pyannote speaker diarization for single-stream multi-speaker audio."""

    def __init__(self, model: str = "pyannote/speaker-diarization-community-1"):
        try:
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise RuntimeError(
                "pyannote diarization needs: uv sync --extra diarize — or use "
                "meeting mode's channel diarization (mic vs sink), which "
                "needs nothing installed.") from exc
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
        if not token:
            raise RuntimeError(
                "pyannote models are gated: set HF_TOKEN (free HuggingFace "
                "account + accept the model terms). Channel diarization "
                "remains available meanwhile.")
        self._pipeline = Pipeline.from_pretrained(model, token=token)

    def diarize(self, wav_path: Path) -> list[Turn]:
        result = self._pipeline(str(wav_path))
        turns = []
        for segment, _track, speaker in result.itertracks(yield_label=True):
            turns.append(Turn(speaker=str(speaker),
                              start_s=float(segment.start), end_s=float(segment.end)))
        return merge_adjacent(turns)
