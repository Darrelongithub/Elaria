"""Phrase hotword layer — start-anchored wake matching on transcripts (§13.4).

Adopted from the external hotword submission (HOTWORD-REVIEW.md A1), with its
conflicting parts deliberately absent: no acoustic/energy trigger (a loud sound
must never open a command session — speaker-verified activation stays the only
authority), no fixed-sleep auto-stop.

The whole layer is pure text matching: zero tokens, zero network. It sits in
front of `intents.route()` on the ask/talk path so a wake phrase addresses her
without changing the grammar underneath:

    "Elaria, status"          -> strip wake -> "status"  -> local intent
    "Elaria, cost"            -> strip wake -> "cost"    -> local intent
    "Elaria"                  -> check-in (the settled terse greeting)
    "What can you do, Elaria" -> NO match (mid-sentence mentions never trigger)
    "Elariaish ideas"         -> NO match (word boundary required)

Start-anchoring is the whole safety property: a false local match answers with
total confidence, so the wake phrase only counts at the very start of the turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Longest first so "hey elaria" wins over "elaria".
WAKE_PHRASES: tuple[str, ...] = ("hey elaria", "ok elaria", "hi elaria", "elaria")

# After the phrase: end of string, or a separator (never a word character —
# "Elariaish"/"Elarians" must not wake).
_WAKE_BOUNDARY = re.compile(r"^(?P<rest>.*)$", re.DOTALL)
_SEPARATORS = ",.!?;:—-\"'()[]{} \t"


@dataclass(frozen=True)
class WakeMatch:
    phrase: str          # the wake phrase that matched (lowercased)
    remainder: str       # what is left after stripping the phrase + separators
    is_checkin: bool     # "Elaria" (or "hey Elaria") alone: a check-in, not a command


def match_wake(text: str) -> WakeMatch | None:
    """Start-anchored wake match, or None. Mid-sentence mentions never trigger."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    lowered = stripped.lower()
    for phrase in WAKE_PHRASES:
        if not lowered.startswith(phrase):
            continue
        tail = stripped[len(phrase):]
        if tail and tail[0].isalnum():
            continue  # "Elariaish …" — not a wake phrase
        remainder = tail.lstrip(_SEPARATORS).strip()
        return WakeMatch(phrase=phrase, remainder=remainder,
                         is_checkin=not remainder)
    return None


def effective_text(text: str) -> str:
    """The turn to route/answer: wake phrase stripped, original otherwise.

    A wake phrase is addressing her, not content: "Elaria, status" must reach
    the intent ladder as "status" (zero Gemini calls). Non-wake turns pass
    through untouched.
    """
    match = match_wake(text)
    return match.remainder if match is not None else text
