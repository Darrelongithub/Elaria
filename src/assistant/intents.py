"""Local intent ladder (§13.4) — every request climbs only as high as
it must: exact command → grammar/regex → local rules/memory → cache →
and only then Gemini. This router owns rungs 1–3 for conversational
input; anything it can't decide returns None and the caller assembles
context for the cheapest-model harness (§17).

Routing is pure regex over the raw text: zero tokens, zero network,
microseconds. It deliberately matches NARROWLY — a false local match
is worse than an honest model call, because the local path answers
with total confidence. Ambiguity goes up the ladder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Intent:
    kind: str                 # status | cost | where | search | remember | forget | halt | undo | organise
    argument: str = ""        # the payload (query, fact text, since spec…)
    raw: str = ""


_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("halt", re.compile(r"^\s*(halt|stop everything|panic stop)\s*[!.]*\s*$", re.IGNORECASE)),
    ("status", re.compile(r"^\s*(status|are you (up|running|alive)|health)\s*\??\s*$", re.IGNORECASE)),
    ("cost", re.compile(r"^\s*(cost|spend|quota|how much (have|did) (i|we) (spend|use)|usage)\b.*$", re.IGNORECASE)),
    ("undo", re.compile(r"^\s*undo(?:\s+since\s+(\S+))?\s*[!.]*\s*$", re.IGNORECASE)),
    ("remember", re.compile(r"^\s*remember\s+(?:that\s+)?(.+?)\s*$", re.IGNORECASE | re.DOTALL)),
    ("forget", re.compile(r"^\s*forget\s+(?:about\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("where", re.compile(r"^\s*(?:where(?:'s| is| are)|find(?: me)?|locate)\s+(.+?)\s*\??\s*$", re.IGNORECASE)),
    ("search", re.compile(r"^\s*search\s+(?:for\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("organise", re.compile(r"^\s*(?:organi[sz]e|sort(?:\s+out)?|tidy)\s+(.+?)\s*$", re.IGNORECASE)),
]


def route(text: str) -> Intent | None:
    """Rungs 1–2 (exact + grammar). None ⇒ memory/model territory."""
    stripped = text.strip()
    if not stripped:
        return None
    for kind, pattern in _PATTERNS:
        match = pattern.match(stripped)
        if match:
            argument = ""
            if match.groups():
                # Last non-None group is the payload for our patterns.
                argument = next((g for g in reversed(match.groups()) if g), "")
            return Intent(kind=kind, argument=argument.strip(), raw=text)
    return None
