"""Pinned model registry (§4.1 of the Blueprint v2 wiring spec).

One table, asserted by `assist doctor`. The ids here are PINNED — never
aliases. The alias policy: `-latest` aliases are allowed only for
non-identity chat experimentation, which is outside these roles.

Every id that is configured for a role below or invoked against the API must
appear in this table; anything else is a defect and doctor reports it.
Forbidden ids hard-fail when they are CONFIGURED or INVOKED (owner decision
2026-10-25: guard constants, catalogue history, negative-test fixtures and
prose mentions of retired models are reported as information, never a
self-trigger — the scan list must name the enemy to reject it).

Phase 0 audit: docs/phase-reports/2026-10-25-phase0-model-id-audit.md
"""

from __future__ import annotations

import re

# -- the §4.1 registry (pinned IDs by role) --------------------------------
VOICE_CONVERSATION = "gemini-3.8-live"
PTT_TRANSCRIPTION = "gemini-3.5-transcribe-live"
EVENT_TRANSCRIPTION = "gemini-3.5-transcribe"
FILE_FALLBACK = "gemini-3.5-flash-lite"
CHAT_INTENT = "gemini-3.5-flash-lite"
ESCALATION = "gemini-3.8-flash"
CACHED_TTS = "gemini-3.8-flash-lite-tts"

#: role label -> pinned id. Roles the daemon resolves through
#: `Config.model_for_role()` map 1:1 (plus housekeeping's three keys).
PINNED_ROLES: dict[str, str] = {
    "voice": VOICE_CONVERSATION,
    "transcribe_live": PTT_TRANSCRIPTION,
    "transcribe_batch": EVENT_TRANSCRIPTION,
    "file_fallback": FILE_FALLBACK,
    "chat": CHAT_INTENT,
    "default": CHAT_INTENT,
    "organise": CHAT_INTENT,
    "cleanup": CHAT_INTENT,
    "escalation": ESCALATION,
    "cached_tts": CACHED_TTS,
}

#: every id that may legitimately appear in config or on the wire
ALLOWED_IDS: frozenset[str] = frozenset(PINNED_ROLES.values())

# -- the forbidden list (§4.1): retired / rejected models ------------------
# Named here so the scan can reject them; these constants are the ONLY place
# they are allowed to live as data (plus negative-test fixtures).
FORBIDDEN_IDS: frozenset[str] = frozenset({
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-3.1-flash-live-preview",
    "gemini-2.5-flash-lite",
})


class ForbiddenModelError(RuntimeError):
    """A forbidden model id reached an API call path. Refused, never sent."""


def normalise_model_id(raw: str) -> str:
    """`models/gemini-x` / whitespace / underscores -> canonical id form."""
    return str(raw).strip().rsplit("/", 1)[-1].lower().replace("_", "-")


def is_forbidden(model: str) -> bool:
    return normalise_model_id(model) in FORBIDDEN_IDS


def is_registered(model: str) -> bool:
    return normalise_model_id(model) in {normalise_model_id(m) for m in ALLOWED_IDS}


def assert_model_permitted(model: str) -> str:
    """Runtime guard for every API invocation. Raises on a forbidden id.

    A non-registry id is NOT blocked here (doctor reports it as a defect;
    blocking it at runtime would break owner experimentation mid-call) — but
    a forbidden id never reaches the wire, by construction.
    """
    if is_forbidden(model):
        raise ForbiddenModelError(
            f"refusing to call forbidden model {model!r}: it is on the §4.1 "
            "forbidden list (retired or rejected). Pin a registry id from "
            "the [gemini] section — see `assist doctor`.")
    return model


_ID_RE = re.compile(r"gemini-[a-z0-9][a-z0-9.\-]*[a-z0-9]", re.IGNORECASE)


def scan_config_values(config) -> list[dict]:
    """Scan every configured string for model-shaped ids.

    Returns one row per occurrence: {section, key, id, verdict}. Verdicts:
      forbidden  — hard fail (configured or on its way to being invoked)
      registered — matches the §4.1 registry
      unregistered — a defect: not in the table (aliases land here)
    """
    findings: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    def _walk(section: str, key: str, value) -> None:
        if isinstance(value, str):
            for found in _ID_RE.findall(value):
                ident = found.lower()
                triple = (section, key, ident)
                if triple in seen:
                    continue
                seen.add(triple)
                if is_forbidden(ident):
                    verdict = "forbidden"
                elif is_registered(ident):
                    verdict = "registered"
                else:
                    verdict = "unregistered"
                findings.append({"section": section, "key": key, "id": ident,
                                 "verdict": verdict})
        elif isinstance(value, dict):
            for sub, subval in value.items():
                _walk(section, f"{key}.{sub}" if key else str(sub), subval)
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                _walk(section, f"{key}[{i}]", item)

    for section, body in (config.raw or {}).items():
        if isinstance(body, dict):
            for key, value in body.items():
                _walk(str(section), str(key), value)
        else:
            _walk(str(section), "", body)
    return findings


def role_drift_rows(config) -> list[dict]:
    """Role-fit drift: a configured `model_<role>` naming a REGISTERED id
    that is pinned to a DIFFERENT role (mini order M-3, 2026-10-31).

    The W1 root cause ran through this gap: `gemini-3.5-flash-lite` is a
    registered id (chat), so a config pointing the files route at it passed
    the membership scan while the leg transcribed with a chat model. A
    missing/empty key is NOT drift — `model_for_role` resolves those to the
    registry pin; only an explicitly configured wrong-for-role value rows
    here. Voice is excluded: it resolves through `voice_model()` legacy
    precedence and doctor's voice checks own it.
    """
    gemini = config.section("gemini")
    rows: list[dict] = []
    for role, pinned in sorted(PINNED_ROLES.items()):
        if role == "voice":
            continue
        key = f"model_{role}"
        raw = gemini.get(key)
        if raw is None or not str(raw).strip():
            continue
        configured = str(raw).strip()
        if normalise_model_id(configured) != normalise_model_id(pinned):
            rows.append({"role": role, "key": key,
                         "configured": configured, "pinned": pinned})
    return rows


def registry_report(config) -> dict:
    """Doctor-facing summary of the registry state of the configuration."""
    findings = scan_config_values(config)
    forbidden = [f for f in findings if f["verdict"] == "forbidden"]
    unregistered = [f for f in findings if f["verdict"] == "unregistered"]
    ladder = (config.section("gemini").get("escalation_ladder") or [])
    ladder_unregistered = [
        str(m) for m in ladder
        if not is_registered(str(m))]
    role_drift = role_drift_rows(config)
    return {
        "forbidden": forbidden,
        "unregistered": unregistered,
        "ladder_unregistered": ladder_unregistered,
        "role_drift": role_drift,
        "registered": [f for f in findings if f["verdict"] == "registered"],
        "ok": (not forbidden and not unregistered
               and not ladder_unregistered and not role_drift),
    }
