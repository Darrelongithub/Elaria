"""S-0 utility template pack for Meta WhatsApp Cloud API submission.

Binding policy posture (DISPATCH-ALIVE + DISPATCH-BUILD-3):

* S-0 only on WhatsApp: approved UTILITY templates for every business-initiated
  or outside-24h send; deterministic fixed strings for in-window replies.
* S-1 chatty/LLM mode stays OFF (Meta 15 Jan 2026 general-purpose AI policy
  grey zone + Elaria's no-authority rule).
* Outside the 24-hour customer service window, ONLY a template registered in
  ``S0_TEMPLATE_PACK`` may be sent, and ONLY to the owner's single E.164.
  Free-form cold sends are impossible in code (``OutsideServiceWindow``).

Meta Utility Template Formatting Rules enforced by ``validate_template_spec``
(cited from Meta Cloud API Message Templates reference & approval rules):

1. ``name``: lowercase ASCII letters, digits, and underscores only, 1..512 chars.
2. ``category``: ``"UTILITY"`` only — never ``"MARKETING"``.
3. ``language``: Meta locale code (``"en"``).
4. ``body``: 1..1024 chars; variables are sequential ``{{1}}..{{N}}`` with no
   gaps, no duplicates, no adjacent variables (``{{1}}{{2}}``), and NEVER at
   the very start or very end of the body text; realistic non-placeholder
   sample values provided for every variable; no URL shorteners; no promotional
   language; no needy or temporal-initiation phrasing (Elaria §19.2).
5. ``footer`` (optional): <= 60 chars, no variables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

TEMPLATE_LANGUAGE = "en"
TEMPLATE_CATEGORY = "UTILITY"

TEMPLATE_MEETING = "elaria_meeting_v1"
TEMPLATE_DEADLINE = "elaria_deadline_v1"
TEMPLATE_COMMITMENT_DUE = "elaria_commitment_due_v1"
TEMPLATE_ALREADY_SENT_KNOCK = "elaria_already_sent_knock_v1"
TEMPLATE_MIRROR_STALE = "mirror_stale_v1"

# Legacy / concise aliases mapped to the canonical S-0 template specs
LEGACY_TEMPLATE_ALIASES: dict[str, str] = {
    "reminder_v1": TEMPLATE_COMMITMENT_DUE,
    "meeting_reminder_v1": TEMPLATE_MEETING,
    "deadline_reminder_v1": TEMPLATE_DEADLINE,
    "commitment_due_v1": TEMPLATE_COMMITMENT_DUE,
    "already_sent_knock_v1": TEMPLATE_ALREADY_SENT_KNOCK,
}

REMINDER_KINDS = ("meeting", "deadline", "commitment_due", "already_sent_knock", "mirror_stale")

_NAME_RE = re.compile(r"^[a-z0-9_]{1,512}$")
_VAR_RE = re.compile(r"\{\{(\d+)\}\}")
_ADJACENT_VAR_RE = re.compile(r"\}\}\s*\{\{")
_SHORTENER_RE = re.compile(r"\b(?:bit\.ly|tinyurl\.com|t\.co|goo\.gl|ow\.ly)\b", re.IGNORECASE)
_PROMO_RE = re.compile(
    r"\b(?:discount|promo(?:tion)?|sale|buy\s+now|limited\s+offer|free\s+gift|"
    r"cashback|coupon|unsubscribe|special\s+deal)\b",
    re.IGNORECASE,
)
# Anti-psychosis / temporal-initiation guard (mirroring assistant.initiative §19.2
# without cross-importing cluster C into the standalone alive host).
_NEEDY_OR_TEMPORAL_RE = re.compile(
    r"\b(?:miss(?:ed|ing)?\s+you|lonely|loneliness|haven'?t\s+(?:talked|heard)|"
    r"been\s+a\s+while|waiting\s+for\s+you|forgot\s+about\s+me|"
    r"it'?s\s+been|since\s+we\s+last\s+spoke|long\s+time\s+no\s+see)\b",
    re.IGNORECASE,
)
_BAD_SAMPLE_RE = re.compile(
    r"^(?:test|testing|xxx+|123+|sample|placeholder|foo|bar)$",
    re.IGNORECASE,
)


class TemplateSpecError(ValueError):
    """A template spec or parameter list failed Meta/Elaria validation."""


@dataclass(frozen=True)
class TemplateSpec:
    """One Meta-submissible WhatsApp UTILITY template."""

    kind: str
    name: str
    language: str
    category: str
    body: str
    footer: str
    param_names: tuple[str, ...]
    sample_params: tuple[str, ...]
    description: str

    @property
    def param_count(self) -> int:
        return len(self.param_names)

    def render_preview(self, params: list[str] | tuple[str, ...]) -> str:
        """Render the body locally for logs/tests/runbook verification."""
        validated = validate_params(self, params)
        rendered = self.body
        for idx, value in enumerate(validated, start=1):
            rendered = rendered.replace(f"{{{{{idx}}}}}", value)
        return rendered

    def meta_submission_payload(self) -> dict:
        """Exact JSON body for ``POST /<WABA_ID>/message_templates``."""
        components: list[dict] = [
            {
                "type": "BODY",
                "text": self.body,
                "example": {"body_text": [list(self.sample_params)]},
            }
        ]
        if self.footer:
            components.append({"type": "FOOTER", "text": self.footer})
        return {
            "name": self.name,
            "language": self.language,
            "category": self.category,
            "components": components,
        }

    def graph_send_payload(
        self,
        to_e164: str,
        params: list[str] | tuple[str, ...],
        *,
        template_name_override: str | None = None,
    ) -> dict:
        """Exact JSON body for ``POST /<PHONE_NUMBER_ID>/messages``."""
        validated = validate_params(self, params)
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_e164,
            "type": "template",
            "template": {
                "name": template_name_override or self.name,
                "language": {"code": self.language},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": val} for val in validated
                        ],
                    }
                ],
            },
        }


S0_TEMPLATE_PACK: dict[str, TemplateSpec] = {
    TEMPLATE_MEETING: TemplateSpec(
        kind="meeting",
        name=TEMPLATE_MEETING,
        language=TEMPLATE_LANGUAGE,
        category=TEMPLATE_CATEGORY,
        body=(
            "Elaria meeting reminder: you asked to remember {{1}} scheduled "
            "for {{2}}. Reply here to queue a note for when your laptop is on."
        ),
        footer="Elaria reminder line (queued until laptop is on)",
        param_names=("meeting_topic", "scheduled_time"),
        sample_params=("project sync with Amina", "today at 19:00 EAT"),
        description="Scheduled meeting reminder from a stated commitment.",
    ),
    TEMPLATE_DEADLINE: TemplateSpec(
        kind="deadline",
        name=TEMPLATE_DEADLINE,
        language=TEMPLATE_LANGUAGE,
        category=TEMPLATE_CATEGORY,
        body=(
            "Elaria deadline reminder: {{1}} is due {{2}}. "
            "Reply here if you want an instruction queued for your laptop."
        ),
        footer="Elaria reminder line (queued until laptop is on)",
        param_names=("deadline_item", "due_time"),
        sample_params=("Distributed Systems lab report", "Friday 17:00 EAT"),
        description="Approaching deadline reminder from a stated commitment.",
    ),
    TEMPLATE_COMMITMENT_DUE: TemplateSpec(
        kind="commitment_due",
        name=TEMPLATE_COMMITMENT_DUE,
        language=TEMPLATE_LANGUAGE,
        category=TEMPLATE_CATEGORY,
        body=(
            "Elaria reminder: you asked me to follow up on {{1}} at {{2}}. "
            "Reply here to queue an instruction until your laptop is on."
        ),
        footer="Elaria reminder line (queued until laptop is on)",
        param_names=("commitment_topic", "remind_time"),
        sample_params=("calling Dr. Kamau about lab results", "08:30 EAT"),
        description="General stated-commitment follow-up / reminder.",
    ),
    TEMPLATE_ALREADY_SENT_KNOCK: TemplateSpec(
        kind="already_sent_knock",
        name=TEMPLATE_ALREADY_SENT_KNOCK,
        language=TEMPLATE_LANGUAGE,
        category=TEMPLATE_CATEGORY,
        body=(
            "Elaria knock update: {{1}} (already sent at {{2}}) is still "
            "waiting for your review. Reply here to queue a note for your laptop."
        ),
        footer="Elaria reminder line (queued until laptop is on)",
        param_names=("knock_topic", "first_sent_time"),
        sample_params=("meeting with Amina", "06:55 EAT"),
        description="Outside-24h knock update citing an earlier reminder send.",
    ),
    TEMPLATE_MIRROR_STALE: TemplateSpec(
        kind="mirror_stale",
        name=TEMPLATE_MIRROR_STALE,
        language=TEMPLATE_LANGUAGE,
        category=TEMPLATE_CATEGORY,
        body=(
            "Your reminder list has not been refreshed since {{1}}. "
            "Reminders are paused until your laptop syncs again."
        ),
        footer="Elaria reminder line (queued until laptop is on)",
        param_names=("last_synced_date",),
        sample_params=("2026-10-25",),
        description="One-shot notice when the mirrored commitments list is stale.",
    ),
}

S0_TEMPLATES_BY_KIND: dict[str, TemplateSpec] = {
    spec.kind: spec for spec in S0_TEMPLATE_PACK.values()
}

# Backwards-compatible map ``name -> (body, param_count)`` for callers inspecting
# raw strings + slot counts directly.
TEMPLATES: dict[str, tuple[str, int]] = {
    **{spec.name: (spec.body, spec.param_count) for spec in S0_TEMPLATE_PACK.values()},
    **{
        alias: (S0_TEMPLATE_PACK[target].body, S0_TEMPLATE_PACK[target].param_count)
        for alias, target in LEGACY_TEMPLATE_ALIASES.items()
    },
}

# Spoken / console laptop-side short knock line (GATE VERDICT: short "already sent" form)
LAPTOP_ALREADY_SENT_KNOCK_LINE = (
    "Already sent to your phone at {sent_at}: {topic}."
)


def validate_template_spec(spec: TemplateSpec) -> None:
    """Verify ``spec`` satisfies Meta utility approval rules + Elaria §19.2."""
    if not _NAME_RE.match(spec.name):
        raise TemplateSpecError(f"invalid Meta template name {spec.name!r}")
    if spec.category != "UTILITY":
        raise TemplateSpecError(
            f"template {spec.name!r} must be UTILITY, got {spec.category!r}")
    if not spec.language or not re.match(r"^[a-z]{2}(?:_[A-Z]{2})?$", spec.language):
        raise TemplateSpecError(f"invalid template language {spec.language!r}")
    body = spec.body.strip()
    if not (1 <= len(body) <= 1024):
        raise TemplateSpecError(f"template {spec.name!r} body length out of 1..1024")
    if len(spec.footer) > 60 or "{{" in spec.footer:
        raise TemplateSpecError(f"template {spec.name!r} footer exceeds 60 chars or has vars")
    if body.startswith("{{") or body.endswith("}}"):
        raise TemplateSpecError(
            f"template {spec.name!r} starts or ends with a variable (Meta rejects this)")
    if _ADJACENT_VAR_RE.search(body):
        raise TemplateSpecError(
            f"template {spec.name!r} has adjacent variables (Meta rejects this)")

    matches = [int(m.group(1)) for m in _VAR_RE.finditer(body)]
    if not matches:
        raise TemplateSpecError(f"template {spec.name!r} has no placeholders")
    if len(matches) > 10:
        raise TemplateSpecError(f"template {spec.name!r} exceeds 10 placeholders")
    expected = list(range(1, len(matches) + 1))
    if matches != expected:
        raise TemplateSpecError(
            f"template {spec.name!r} placeholders must be sequential {expected}, got {matches}")
    if len(spec.param_names) != len(matches) or len(spec.sample_params) != len(matches):
        raise TemplateSpecError(
            f"template {spec.name!r} param_names/sample_params count mismatch")
    for sample in spec.sample_params:
        clean = str(sample).strip()
        if not clean or _BAD_SAMPLE_RE.match(clean):
            raise TemplateSpecError(
                f"template {spec.name!r} has placeholder-like sample {sample!r}")
    if _SHORTENER_RE.search(body):
        raise TemplateSpecError(f"template {spec.name!r} contains a blocked URL shortener")
    if _PROMO_RE.search(body):
        raise TemplateSpecError(
            f"template {spec.name!r} contains promotional language (risks MARKETING downgrade)")
    if _NEEDY_OR_TEMPORAL_RE.search(body):
        raise TemplateSpecError(
            f"template {spec.name!r} violates §19.2 anti-psychosis / temporal-initiation rule")


def resolve_template(name_or_kind: str) -> TemplateSpec:
    """Resolve a canonical template name, kind, or legacy alias to its ``TemplateSpec``."""
    key = str(name_or_kind or "").strip()
    key = LEGACY_TEMPLATE_ALIASES.get(key, key)
    if key in S0_TEMPLATE_PACK:
        return S0_TEMPLATE_PACK[key]
    if key in S0_TEMPLATES_BY_KIND:
        return S0_TEMPLATES_BY_KIND[key]
    raise TemplateSpecError(
        f"unknown S-0 template {name_or_kind!r}; registered templates: "
        f"{sorted(S0_TEMPLATE_PACK)}")


def select_template_for_item(
    *,
    topic: str,
    due: str | None = None,
    template_kind: str | None = None,
    already_sent_at: str | None = None,
) -> TemplateSpec:
    """Pick the right S-0 template for a mirrored commitment item."""
    if already_sent_at:
        return S0_TEMPLATE_PACK[TEMPLATE_ALREADY_SENT_KNOCK]
    if template_kind:
        return resolve_template(template_kind)
    lowered = str(topic or "").lower()
    if re.search(r"\b(meeting|call|sync|standup|1:1|appointment|interview|lecture|class)\b", lowered):
        return S0_TEMPLATE_PACK[TEMPLATE_MEETING]
    if due or re.search(r"\b(deadline|due|submit|submission|report|assignment|exam|invoice|filing)\b", lowered):
        return S0_TEMPLATE_PACK[TEMPLATE_DEADLINE]
    return S0_TEMPLATE_PACK[TEMPLATE_COMMITMENT_DUE]


def _sanitise_param(value: str) -> str:
    # Meta rejects newlines, tabs, and >4 consecutive spaces inside template body parameters
    # (error #132018). Collapse whitespace cleanly and bound length.
    cleaned = re.sub(r"[\r\n\t]+", " ", str(value or ""))
    cleaned = re.sub(r" {2,}", " ", cleaned).strip()
    return cleaned[:200]


def validate_params(spec: TemplateSpec, params: list[str] | tuple[str, ...]) -> list[str]:
    """Validate and sanitise parameter values before any HTTP call."""
    if not isinstance(params, (list, tuple)):
        raise TemplateSpecError("template params must be a list or tuple of strings")
    if len(params) != spec.param_count:
        raise TemplateSpecError(
            f"template {spec.name!r} requires {spec.param_count} params "
            f"{spec.param_names}, got {len(params)}")
    out: list[str] = []
    for idx, raw in enumerate(params):
        cleaned = _sanitise_param(raw)
        if not cleaned:
            raise TemplateSpecError(
                f"template {spec.name!r} param #{idx + 1} ({spec.param_names[idx]}) is empty")
        out.append(cleaned)
    return out


def format_laptop_already_sent_knock(topic: str, sent_at: str) -> str:
    """Format the laptop-side short 'already sent' knock line."""
    clean_topic = _sanitise_param(topic) or "your reminder"
    clean_time = _sanitise_param(sent_at) or "earlier"
    return LAPTOP_ALREADY_SENT_KNOCK_LINE.format(sent_at=clean_time, topic=clean_topic)


# Validate every shipped template at import time so a broken template string
# can never even be imported, let alone deployed.
for _spec in S0_TEMPLATE_PACK.values():
    validate_template_spec(_spec)
