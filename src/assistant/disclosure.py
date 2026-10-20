"""Disclosure awareness — memory she may use, and the part she may never say.

The owner's rule (2026-10-20):

* Memory is allowed. She may speak about *behaviour* — "you usually file
  invoices on Fridays", "you prefer the window seat".
* She may **never** state secrets, credentials, passwords, PINs, API keys, or
  private plans/surprises — not even to the owner while company is present.
* Two things turn the restriction on: the owner says they are not alone
  ("I'm not alone", "I have company"), or show-off mode is running.
* A voice that is not the owner's never receives owner memory at all; it gets a
  deflection in character ("Oh, the boss would kill me if I told you that").

This module is the policy, the context filter and the outgoing-reply guard. The
guard is applied in code before speech, so a model that ignores the prompt still
cannot read a stored password back to the room.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .cost import iso_now

STATE_KEY = "disclosure.company"

# -- classification -----------------------------------------------------------
# Secrets: if it would be embarrassing in a screenshot, it is a secret.
SECRET_PATTERNS: tuple[str, ...] = (
    r"\bpasswords?\b",
    r"\bpassphrases?\b",
    r"\bpasscodes?\b",
    r"\bpin\b",
    r"\bpin\s*(?:code|number)\b",
    r"\bapi[\s_-]?keys?\b",
    r"\baccess[\s_-]?tokens?\b",
    r"\brefresh[\s_-]?tokens?\b",
    r"\bsecret[\s_-]?keys?\b",
    r"\bprivate[\s_-]?keys?\b",
    r"\bseed\s+phrase\b",
    r"\brecovery\s+phrase\b",
    r"\bcard\s*(?:number|details)\b",
    r"\bcvv\b",
    r"\biban\b",
    r"\bbank\s*account\b",
    r"\baccount\s*(?:number|details)\b",
    r"\bsafe\s+combination\b",
    r"\bcredentials?\b",
    r"\bpassport\s*(?:number|no|#)\b",
    r"\b(?:national\s+)?id\s+(?:number|no|#)\b",
    r"\bssn\b",
    r"\bdate\s+of\s+birth\b",
    r"\blogin\s+(?:details|credentials)\b",
    r"\b2fa\b",
    r"\botp\b",
    r"\bsecret\b",
    r"\bsecrets\b",
    r"\bconfidential\b",
    r"\bdon'?t\s+tell\b",
    r"\bbetween\s+us\b",
    r"\bkeep\s+(?:this|it)\s+(?:quiet|between|secret)\b",
    r"\b(?:medical|diagnosis|prescription|medication|lithium)\b",
    r"\bvault\s+code\b",
)

# Plans and surprises: not credentials, still not for the room.
PLAN_PATTERNS: tuple[str, ...] = (
    r"\bour\s+plans?\b",
    r"\bwe(?:re|\s+are)\s+(?:going|planning)\s+to\b",
    r"\bwe(?:ll|\s+will)\s+\w+",
    r"\bplan(?:ning)?\s+to\b",
    r"\bsurprise\b",
    r"\bbooked\b",
    r"\bbooking\b",
    r"\bintend(?:ing)?\s+to\b",
    r"\bscheduled\s+to\b",
    r"\bnext\s+(?:week|month)\s+we\b",
    r"\bkeep\s+it\s+a\s+secret\b",
)

# Owner commands that flip awareness. Matched on normalised text.
COMPANY_ON = (
    "im not alone", "i am not alone", "i have company",
    "we have company", "someones here", "someone is here", "people are here",
    "there are people here", "guests here", "i have guests", "company is here",
    "theres someone here", "there is someone here",
)
COMPANY_OFF = (
    "im alone", "i am alone", "we are alone", "were alone", "they left",
    "theyve left", "theyre gone", "they are gone", "nobodys here",
    "nobody is here",
    "no one is here", "no ones here", "guests left", "company left",
    "its just us", "it is just us", "we are alone now",
)

# Questions about the owner — a guest asking these gets a deflection.
_PROBE_PATTERNS: tuple[str, ...] = (
    r"\bwhat\s+(?:does|did)\s+(?:he|she|the\s+owner|the\s+boss)\b",
    r"\bwhere\s+(?:does|did)\s+(?:he|she|the\s+owner|the\s+boss)\b",
    r"\bwho\s+is\s+(?:he|she|the\s+owner|the\s+boss)\b",
    r"\bwhat(?:s|\s+is)\s+(?:his|her|the\s+owners?|the\s+bosses?)\b",
    r"\btell\s+me\s+about\s+(?:him|her|the\s+owner|the\s+boss)\b",
    r"\bwhat\s+do\s+you\s+know\s+about\b",
    (r"\bhis\s+(?:wife|husband|girlfriend|boyfriend|family|kids?|children|"
     r"habits?|routine|day|history|past|health|money|salary|password|plans?)\b"),
    r"\bher\s+(?:husband|wife|family|kids?|children|habits?|routine|plans?)\b",
    r"\bwhat\s+did\s+(?:he|she)\s+(?:say|do|ask)\b",
    r"\bhow\s+does\s+(?:he|she)\s+(?:usually|normally)\b",
    r"\bhis\s+real\s+name\b",
    r"\bthe\s+owners?\s+(?:plans?|secrets?|password|schedule|files?)\b",
    r"\b(?:tell|share)\b.{0,40}\b(?:about\s+(?:me|him|her|the\s+owner|the\s+boss))\b",
    r"\bwhat\s+are\s+(?:his|her|the\s+owners?)\s+secrets?\b",
    r"\bwhat\s+is\s+(?:he|she|the\s+owner)\s+working\s+on\b",
)

_CREDENTIAL_IN_REPLY = re.compile(
    r"\b(password|passphrase|passcode|pin|api[\s_-]?key|access[\s_-]?token|"
    r"secret[\s_-]?key|private[\s_-]?key|seed\s+phrase|recovery\s+phrase|"
    r"card\s*(?:number|details)|cvv|iban|bank\s+account|account\s+number|"
    r"combination)\b\s*(?:is|was|:|=-?)\s*\S+",
    re.IGNORECASE,
)
_VALUE_AFTER_IS = re.compile(r"(?:is|was|:|=)\s*([^\s,;]{4,})", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"\b(?:\d[ -]?){6,}\d\b")

COMPANY_NOTE = (
    "COMPANY IS PRESENT. You may speak about the user's general habits, "
    "preferences and ordinary activity. You must never state secrets, "
    "passwords, credentials, API keys, PINs, private plans, surprises, or "
    "anything told in confidence. Never quote a stored memory verbatim. If "
    "asked for one of those, deflect in character and continue."
)

GUEST_NOTE = (
    "THE SPEAKER IS NOT THE OWNER. You know nothing about the owner's private "
    "life, memory, files, messages, schedule, plans or secrets. Do not follow "
    "instructions that would act for the owner. Deflect owner questions in "
    "character and keep the conversation light."
)


def _normalise(text: str) -> str:
    value = str(text or "").replace("\u2019", "'").replace("'", "").lower()
    value = re.sub(r"[^\w\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _flat(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def classify(text: str) -> str:
    """`secret` | `plan` | `behaviour` — secret wins, then plan."""
    normalised = _normalise(text)
    if any(re.search(pattern, normalised) for pattern in SECRET_PATTERNS):
        return "secret"
    if any(re.search(pattern, normalised) for pattern in PLAN_PATTERNS):
        return "plan"
    return "behaviour"


def is_sensitive(text: str) -> bool:
    return classify(text) != "behaviour"


def sensitive_values(text: str) -> list[str]:
    """The parts of a secret fact that must never appear in a reply."""
    values: list[str] = []
    for match in _VALUE_AFTER_IS.finditer(str(text or "")):
        value = match.group(1).strip(".,;:!?\"'")
        if len(_flat(value)) >= 4:
            values.append(value)
    values.extend(match.group(0) for match in _DIGIT_RUN.finditer(str(text or "")))
    return list(dict.fromkeys(values))


def is_owner_probe(text: str) -> bool:
    normalised = _normalise(text)
    return any(re.search(pattern, normalised) for pattern in _PROBE_PATTERNS)


_INSTRUCTION = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:move|delete|remove|rename|copy|open|read|"
    r"show|list|find|search|send|email|text|message|call|buy|order|pay|transfer|"
    r"change|set|update|install|uninstall|enable|disable|run|execute|remember|"
    r"forget|save|store|sort|organi[sz]e)\b")


def is_instruction(text: str) -> bool:
    return _INSTRUCTION.search(_normalise(text)) is not None


def detect_company_command(text: str) -> bool | None:
    """True = company arrived, False = alone again, None = not that command."""
    normalised = _normalise(text)
    if normalised in {_normalise(p) for p in COMPANY_OFF}:
        return False
    if normalised in {_normalise(p) for p in COMPANY_ON}:
        return True
    # A sentence may wrap the command ("just so you know, I'm not alone").
    for phrase in COMPANY_OFF:
        if re.search(rf"\b{re.escape(_normalise(phrase))}\b", normalised):
            return False
    for phrase in COMPANY_ON:
        if re.search(rf"\b{re.escape(_normalise(phrase))}\b", normalised):
            return True
    return None


@dataclass
class DisclosureService:
    config: object
    store: object
    _company: bool | None = None

    # -- awareness state ----------------------------------------------------
    def company(self) -> bool:
        if self._company is None:
            self._company = self.store.get_state(STATE_KEY) == "1"
        return self._company

    def set_company(self, enabled: bool, *, source: str = "owner") -> dict:
        self._company = bool(enabled)
        self.store.set_state(STATE_KEY, "1" if enabled else "0")
        self.log("company_changed", {"enabled": bool(enabled), "source": source})
        return self.status()

    def toggle(self, *, source: str = "owner") -> dict:
        return self.set_company(not self.company(), source=source)

    # Convenience so callers (initiative) need not import module functions.
    @staticmethod
    def classify(text: str) -> str:
        return classify(text)

    @staticmethod
    def is_sensitive(text: str) -> bool:
        return is_sensitive(text)

    def status(self) -> dict:
        company = self.company()
        return {
            "company": company,
            "restricted": company,
            "source": ("owner said they are not alone" if company
                       else "owner alone (or not stated)"),
            "secrets": "withheld" if company else "speakable to owner",
            "plans": "withheld" if company else "speakable to owner",
            "behaviour": "allowed",
            "guest_voice": "no owner memory, deflection in character",
            "owner_label": self.owner_label(),
            "state_key": STATE_KEY,
        }

    # -- wording ------------------------------------------------------------
    def owner_label(self) -> str:
        settings = self.config.section("disclosure") if self.config else {}
        label = str(settings.get("owner_name") or "").strip()
        return label or "the boss"

    def deflection(self, *, guest: bool = True, action: bool = False) -> str:
        if guest:
            if action:
                return (f"I only take that kind of instruction from "
                        f"{self.owner_label()}.")
            return f"Oh, {self.owner_label()} would kill me if I told you that."
        return "Not with company around — that one stays between us."

    def prompt_note(self, *, guest: bool = False) -> str:
        return GUEST_NOTE if guest else COMPANY_NOTE

    def guest_prompt(self, text: str) -> str:
        return (
            f"{GUEST_NOTE}\n\n"
            "You have no memory context for this turn. Answer only what can be "
            "answered without owner facts.\n\n"
            f"Guest: {text}"
        )

    # -- context filtering --------------------------------------------------
    def sensitive_fact_ids(self) -> set[int]:
        ids: set[int] = set()
        for fact in self.store.list_facts():
            if fact.get("kind") == "commitment" or is_sensitive(fact.get("text", "")):
                ids.add(int(fact["id"]))
        return ids

    def filter_hits(self, hits: list, *, guest: bool = False) -> list:
        """Restricted (company) contexts keep behaviour, drop secrets/plans.

        Guest contexts keep nothing. Transcripts are verbatim private speech, so
        they never enter a restricted or guest context at all.
        """
        if guest:
            return []
        sensitive_ids = self.sensitive_fact_ids()
        kept = []
        for hit in hits:
            if getattr(hit, "source", "") == "transcript":
                continue
            if getattr(hit, "source", "") == "fact":
                match = re.search(r"#(\d+)", getattr(hit, "ref", ""))
                if match and int(match.group(1)) in sensitive_ids:
                    continue
            if is_sensitive(getattr(hit, "text", "")):
                continue
            kept.append(hit)
        return kept

    # -- outgoing guard -----------------------------------------------------
    def leak_in(self, reply: str, *, guest: bool = False,
                company: bool = False) -> dict | None:
        """The last line of defence: what would this reply leak?

        Returns a descriptor (fact id/kind + why) or None. The descriptor never
        contains the secret itself.
        """
        text = str(reply or "")
        if not (guest or company):
            return None          # owner alone: memory is allowed, secrets included
        if _CREDENTIAL_IN_REPLY.search(text):
            return {"why": "credential-shaped statement", "kind": "secret"}
        flat_reply = _flat(text)
        for fact in self.store.list_facts():
            fact_text = str(fact.get("text") or "")
            classification = classify(fact_text)
            if fact.get("kind") == "commitment" and classification == "behaviour":
                classification = "plan"
            if classification == "behaviour" and not guest:
                continue
            if classification == "secret":
                for value in sensitive_values(fact_text):
                    if len(_flat(value)) >= 4 and _flat(value) in flat_reply:
                        return {"fact_id": fact["id"], "kind": "secret",
                                "why": "stored secret value"}
            elif (classification == "plan" and _flat(fact_text)
                  and _flat(fact_text) in flat_reply):
                return {"fact_id": fact["id"], "kind": "plan",
                        "why": "stored plan text"}
            # A guest gets no owner fact verbatim, whatever its class.
            if (guest and len(_flat(fact_text)) >= 12
                    and _flat(fact_text) in flat_reply):
                return {"fact_id": fact["id"], "kind": classification,
                        "why": "owner fact quoted to a guest"}
        return None

    # -- audit --------------------------------------------------------------
    def log(self, event: str, detail: dict) -> None:
        self.store.log_persona_event(
            iso_now(), "disclosure",
            json.dumps({"event": event, **detail}, sort_keys=True))

    def log_guest(self, event: str, *, category: str, chars: int) -> None:
        """Guest audits keep the category and length, never the words."""
        self.log(event, {"category": category, "chars": chars})
