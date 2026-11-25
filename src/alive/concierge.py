"""S-0 concierge — the deterministic front door for strangers.

No LLM, ever (Elaria's rules AND Meta's 15 Jan 2026 policy). A small state
machine: greet → collect what/when/where (up to 3 turns) → emit a
``proposal`` envelope (principal fixed to ``"stranger"``) and the fixed
non-binding line. Every negotiated plan is a proposal, never a commitment —
the owner alone can turn it into one, with her mouth, on the laptop.

Pattern tables are read-only adaptations of ``src/assistant/showoff.py``
(cluster C owns that file; we import nothing from it) rewritten to
third-person ("her") text, with attribution. If showoff's tables drift,
this file does not move — the alive host shares no runtime with the laptop.

Free/busy levels (design §2.3b.3, binding):

* L0 none — "I'll check with her." (default, and the only level when no
  public card has been exported);
* L1 day-level — "Thursday looks possible; she'll confirm." / "Thursday's
  tight; try Friday?" (recommended T2 default when a card is exported);
* L2 slot-level — T1 approved contacts only, and only when the card opts
  in. Intervals only — never topics, never locations.
* L3 content — never exists. Not configurable. Not in this file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# --- pattern tables (read-only adaptation of src/assistant/showoff.py, C) ----
# Third-person ("her") variants for asynchronous text. Attribution: the
# pattern shapes come from showoff.py (cluster C); these literals are ours.

REFUSALS_TEXT = {
    "destructive": "No. That is on the never-list.",
    "file": "Her files stay hers. I can pass a note along, nothing more.",
    "message": "I don't send messages for strangers. Anything you need to tell "
               "her, I'll pass on.",
    "settings": "Settings are hers to change. I can't touch those.",
    "purchase": "No purchases or payments through me.",
    "owner-data": "That's her story to tell, not mine to hand out.",
}
MEMORY_DEFLECTION = ("I can pass on a proposal to her; who she is and how she "
                     "lives is closed.")
LOCATION_DEFLECTION = "I'll pass on that you asked. Where she is stays hers."
CAPABILITY_LINE = ("I help with plans: tell me what, when and where, and I'll "
                   "pass it to her. She confirms everything herself.")
GREETING_LINE = ("Hi — I'm Elaria, her assistant. I can pass plans to her; "
                 "she confirms everything herself. What would you like to plan — "
                 "what, when and where?")
PROPOSAL_LINE = "I've passed it to her; she'll confirm herself."
MUTED_LINE = "I'll leave this with her."
INBOX_FULL_LINE = "I'm not able to take more right now. I'll leave it with her."
UNSUPPORTED_LINE = "I can't take files, voice notes or locations on this line — text only."

NEVER_LIST_PATTERNS = (
    ("destructive", (r"\b(rm\s+-rf|format\s+(?:the\s+)?(?:disk|drive)|wipe\s+(?:the\s+)?"
                     r"(?:disk|drive|everything)|delete\s+everything|factory\s+reset)\b")),
    ("file", (r"\b(move|delete|remove|rename|copy|open|read|show|see|give|hand|pass|get|"
              r"list|print|display|find|search|locate|organi[sz]e|sort|"
              r"look\s+at|access)\b.{0,40}\b(files?|folders?|director(?:y|ies)|drives?|"
              r"desktop|documents|downloads|photos?|pictures|attachments?)\b")),
    ("message", r"\b(send|email|text|message|dm|call|whatsapp|telegram)\b"),
    ("settings", (r"\b(change|set|update|install|uninstall|enable|disable|turn\s+"
                  r"(?:on|off)|edit)\b.{0,40}\b(settings?|config|system|permissions?|"
                  r"wifi|password|network|account)\b")),
    ("settings", r"\b(run|execute|eval)\b.{0,30}\b(command|script|shell|code)\b"),
    ("purchase", r"\b(buy|purchase|order|checkout|pay|transfer|send\s+money)\b"),
    ("owner-data", r"\b(remember|forget|save\s+this|store\s+this)\b"),
    ("owner-data", (r"\b(read|show|list|give|send|tell)\b.{0,30}\b(her|the\s+"
                    r"owner'?s?)\b.{0,30}\b(files?|messages?|e-?mails?|photos?|"
                    r"passwords?|bank|address|phone|schedule|calendar|contacts?|"
                    r"history|notes?|location)\b")),
)

MEMORY_PROBE_PATTERNS = (
    r"what\s+does\s+(?:she|the\s+owner)\s+usually\b",
    r"what\s+does\s+she\s+(?:do|like|work\s+on)\b",
    r"where\s+does\s+(?:she|the\s+owner)\s+(?:live|work|go)\b",
    r"what(?:'s|\s+is)\s+her\b",
    r"who\s+is\s+her\b",
    r"tell\s+me\s+about\s+(?:her|the\s+owner)\b",
    r"\bher\s+(?:husband|wife|family|kids?|children|habits?|routine|day|history|past|health|money|salary)\b",
    r"what\s+did\s+she\s+(?:say|do|ask)\b",
    r"how\s+does\s+she\s+(?:usually|normally)\b",
    r"\bher\s+real\s+name\b",
    r"\b(?:tell|share)\b.{0,40}\b(?:about\s+(?:me|her|the\s+owner|the\s+boss))\b",
    r"what\s+(?:are|is)\s+(?:her|the\s+owner'?s?)\s+secrets?\b",
    r"what\s+is\s+(?:she|the\s+owner)\s+working\s+on\b",
    r"\bis\s+she\s+(?:home|there|at\s+home)\b",
    r"\bwhere\s+is\s+she\b",
)

_CAPABILITY_PATTERNS = (
    r"what\s+can\s+you\s+do\b",
    r"what\s+are\s+you\s+(?:able\s+to\s+do|good\s+at)\b",
    r"what\s+do\s+you\s+do\b",
    r"how\s+do\s+you\s+(?:work|do\s+that)\b",
    r"what\s+are\s+your\s+(?:capabilities|skills)\b",
)

_AVAILABILITY_PATTERNS = (
    r"\b(busy|free|availab(?:le|ility)|when|schedule|time\s*slot|slot)s?\b",
)

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}

_NEVER_LIST = tuple((cat, re.compile(pat, re.IGNORECASE)) for cat, pat in NEVER_LIST_PATTERNS)
_MEMORY_PROBE = tuple(re.compile(pat, re.IGNORECASE) for pat in MEMORY_PROBE_PATTERNS)
_CAPABILITY = tuple(re.compile(pat, re.IGNORECASE) for pat in _CAPABILITY_PATTERNS)
_AVAILABILITY = tuple(re.compile(pat, re.IGNORECASE) for pat in _AVAILABILITY_PATTERNS)

_NON_BINDING_CONFIRM = re.compile(
    r"\b(confirmed|it'?s\s+a\s+deal|deal|booked|she'?ll\s+be\s+there|done|"
    r"locked\s+in|pencil\s*it\s+in.*(?:confirm|final)|yes,?\s+she\s+will)\b",
    re.IGNORECASE)


def _normalise(text: str) -> str:
    value = str(text or "").replace("\u2019", "'").lower()
    value = re.sub(r"[^\w\s'-]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def never_list_category(text: str) -> str | None:
    normalised = _normalise(text)
    for category, pattern in _NEVER_LIST:
        if pattern.search(normalised):
            return category
    return None


def memory_probe(text: str) -> bool:
    normalised = _normalise(text)
    return any(p.search(normalised) for p in _MEMORY_PROBE)


def is_capability_question(text: str) -> bool:
    normalised = _normalise(text)
    return any(p.search(normalised) for p in _CAPABILITY)


def asks_availability(text: str) -> bool:
    normalised = _normalise(text)
    return any(p.search(normalised) for p in _AVAILABILITY)


def weekday_in(text: str) -> int | None:
    normalised = _normalise(text)
    for name, idx in _WEEKDAYS.items():
        if re.search(rf"\b{name}\b", normalised):
            return idx
    # "tomorrow" / "today" resolved against Africa/Nairobi wall clock by caller
    return None


def non_binding_filter(reply: str) -> str:
    """Deterministic post-filter: any confirm-word becomes the proposal form."""
    if _NON_BINDING_CONFIRM.search(reply):
        return PROPOSAL_LINE
    return reply


@dataclass
class ConciergeOutcome:
    reply: str
    proposal: dict | None        # proposal payload to envelope, or None
    never_list_category: str | None
    memory_probe: bool
    muted: bool


def _plan_fields(turns: list[str]) -> dict:
    """Best-effort raw echo of what/when/where from the verbatim turns.

    Never interpreted, never resolved — the laptop reads these labels with
    the owner present, so honest raw echo beats clever extraction.
    """
    what = turns[0].strip()[:200] if turns else ""
    time_re = re.compile(
        r"\b(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|morning|afternoon|evening|"
        r"today|tomorrow|tonight|(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
        re.IGNORECASE)
    when = ""
    where = ""
    for turn in turns:
        if not when and time_re.search(turn):
            when = turn.strip()[:120]
        if (not where and turn is not turns[0]
                and re.search(r"\b(at|in|around|near)\b", turn, re.IGNORECASE)
                and time_re.search(turn) is None):
            where = turn.strip()[:120]
    return {"what": what, "when_text": when, "where_text": where}


class S0Concierge:
    """The whole responder. Stateless per call except the injected store."""

    def __init__(self, store, config):
        self.store = store
        self.config = config

    def handle(self, *, sender_e164: str, sender_hash: str, text: str,
               tier: str, now: datetime,
               freebusy_level: int = 0,
               busy_days: dict[int, int] | None = None,
               display_name_claimed: str | None = None) -> ConciergeOutcome:
        """One stranger turn → one reply (+ optional proposal payload)."""
        normalised = _normalise(text)

        # mute check first — a muted sender gets the fixed line and nothing else
        if self.store.muted(sender_hash,
                            window_hours=self.config.mute_window_hours,
                            threshold=self.config.mute_after_never_list_hits,
                            now=now):
            return ConciergeOutcome(MUTED_LINE, None, None, False, True)

        # never-list attempts: refusal + counter; text never reaches a model (there is none)
        category = never_list_category(normalised)
        if category is not None:
            self.store.add_never_list_hit(sender_hash, category, now=now)
            reply = REFUSALS_TEXT.get(category, "I'll leave this with her.")
            return ConciergeOutcome(reply, None, category, False, False)

        # memory / whereabouts probes: deflection, never an answer
        if memory_probe(normalised):
            if re.search(r"\b(home|where\s+(?:does\s+)?(?:she|the\s+owner)\s+"
                         r"(?:live|lives|work|works|go|goes)|where\s+is\s+she)\b",
                         normalised):
                return ConciergeOutcome(LOCATION_DEFLECTION, None, None, True, False)
            return ConciergeOutcome(MEMORY_DEFLECTION, None, None, True, False)

        # capability question
        if is_capability_question(normalised):
            return ConciergeOutcome(CAPABILITY_LINE, None, None, False, False)

        # free/busy: L0 says nothing; L1 day-level; L2 (T1 only) intervals; never content
        if asks_availability(normalised):
            return ConciergeOutcome(
                self._freebusy_answer(normalised, tier, freebusy_level, busy_days or {}),
                None, None, False, False)

        # plan collection: up to 3 turns, verbatim
        turns = self.store.append_draft_turn(sender_hash, text.strip()[:500], now=now)
        if len(turns) >= 3:
            self.store.clear_draft(sender_hash)
            proposal = {
                "kind": "proposal",
                "principal": "stranger",
                "display_name_claimed": (display_name_claimed or "").strip()[:120],
                "plan": _plan_fields(turns),
                "turns": [t[:500] for t in turns],
            }
            return ConciergeOutcome(PROPOSAL_LINE, proposal, None, False, False)
        if len(turns) == 1:
            return ConciergeOutcome(GREETING_LINE, None, None, False, False)
        return ConciergeOutcome(
            "Got it. Anything else for the plan — time, place? "
            f"({len(turns)}/3)", None, None, False, False)

    def _freebusy_answer(self, normalised: str, tier: str, level: int,
                         busy_days: dict[int, int]) -> str:
        if level <= 0:
            return "I'll check with her."
        if tier == "T2" and level >= 2:
            level = 1  # L2 is T1-only; L3 does not exist
        day = weekday_in(normalised)
        if day is None:
            return "I'll check with her."
        if level == 1:
            busy = busy_days.get(day, 0)
            if busy >= 2:
                return "That day looks tight; she'll confirm. A different day might work better."
            return "That day looks possible; she'll confirm."
        # level == 2 (T1 approved contacts only): interval answer stays generic
        # in this build — the mirror carries point-in-time commitments, not
        # interval arithmetic yet, and intervals-are-not-topics is a rule we
        # keep even when the data is thin.
        busy = busy_days.get(day, 0)
        if busy >= 2:
            return "That day looks tight; she'll confirm the exact times herself."
        return "That day looks open; she'll confirm the exact times herself."
