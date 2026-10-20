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
    ("halt", re.compile(r"^\s*(?:halt|stop everything|panic stop)(?:\s+(?:now|please))*\s*[!.]*\s*$", re.IGNORECASE)),
    ("status", re.compile(r"^\s*(status|are you (up|running|alive)|health)\s*\??\s*$", re.IGNORECASE)),
    ("mode_offline", re.compile(r"^\s*(go offline|offline mode|force offline|disconnect)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_online", re.compile(r"^\s*(go online|online mode|reconnect)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_auto", re.compile(r"^\s*(auto mode|connectivity auto|automatic mode)\s*[!.]*\s*$", re.IGNORECASE)),
    ("queue_status", re.compile(r"^\s*(queue status|what'?s queued|what is queued|show (the )?queue)\s*\??\s*$", re.IGNORECASE)),
    ("queue_drain", re.compile(r"^\s*(drain (the )?queue|process (the )?queue)\s*[!.]*\s*$", re.IGNORECASE)),
    ("cost", re.compile(r"^\s*(?:cost|spend|quota|usage|(?:api|gemini|token|my)\s+(?:cost|spend|quota|usage)|how much (?:have|did) (?:i|we) (?:spend|use)(?:\s+today|\s+this\s+month)?)\s*[?.!]*\s*$", re.IGNORECASE)),
    ("undo", re.compile(r"^\s*undo(?:\s+since\s+(\S+))?\s*[!.]*\s*$", re.IGNORECASE)),
    ("remember", re.compile(r"^\s*remember\s+(?:that\s+)?(.+?)\s*$", re.IGNORECASE | re.DOTALL)),
    ("forget", re.compile(r"^\s*forget\s+(?:about\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("where", re.compile(r"^\s*(?:where(?:'s| is| are)|find(?: me)?|locate)\s+(.+?)\s*\??\s*$", re.IGNORECASE)),
    ("search", re.compile(r"^\s*search\s+(?:for\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("organise", re.compile(r"^\s*(?:organi[sz]e|sort(?:\s+out)?|tidy)\s+(.+?)\s*$", re.IGNORECASE)),
    # Phase 7: the ladder speaks Kiswahili too — same narrow grammar.
    # (simama = stop, hali = status, gharama = cost, kumbuka = remember,
    # sahau = forget, iko wapi = where is, tafuta = search, panga = organise,
    # rudisha = restore/undo.)
    ("halt", re.compile(r"^\s*(simama|wacha yote|simamisha yote)\s*[!.]*\s*$", re.IGNORECASE)),
    ("status", re.compile(r"^\s*(hali|uko sawa|unaendelea vipi)\s*\??\s*$", re.IGNORECASE)),
    ("mode_offline", re.compile(r"^\s*(enda nje ya mtandao|hali ya nje ya mtandao)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_online", re.compile(r"^\s*(rudi mtandaoni|enda mtandaoni|hali ya mtandaoni)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_auto", re.compile(r"^\s*(hali ya kiotomatiki|kiotomatiki)\s*[!.]*\s*$", re.IGNORECASE)),
    ("queue_status", re.compile(r"^\s*(hali ya foleni|foleni ikoje|onyesha foleni)\s*\??\s*$", re.IGNORECASE)),
    ("queue_drain", re.compile(r"^\s*(tenda foleni|chakata foleni)\s*[!.]*\s*$", re.IGNORECASE)),
    ("cost", re.compile(r"^\s*(?:gharama|nimetumia kiasi gani|quota)\s*[?.!]*\s*$", re.IGNORECASE)),
    ("undo", re.compile(r"^\s*(rudisha|tenda upya)(?:\s+tangu\s+(\S+))?\s*[!.]*\s*$", re.IGNORECASE)),
    ("remember", re.compile(r"^\s*kumbuka\s+(?:kwamba\s+)?(.+?)\s*$", re.IGNORECASE | re.DOTALL)),
    ("forget", re.compile(r"^\s*sahau\s+(?:kuhusu\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("where", re.compile(r"^\s*(?:iko wapi|wapi)\s+(.+?)\s*\??\s*$", re.IGNORECASE)),
    ("search", re.compile(r"^\s*tafuta\s+(.+?)\s*$", re.IGNORECASE)),
    ("organise", re.compile(r"^\s*(?:panga|ratibu)\s+(.+?)\s*$", re.IGNORECASE)),
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
