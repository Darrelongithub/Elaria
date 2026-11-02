"""Kitty act policy layered on (not substituted for) existing R3/R5 hands gates.

Trusted integration supplies independent assessments at plan time and immediately
before execution. There is deliberately no permissive default checker or hand-open
configuration. This library does not wire the frozen daemon/console.
"""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from assistant.hands.gate import adjudicate
from assistant.hands.plan import Plan, Step

DATA = Path(__file__).with_name("data")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def inventory():
    data = json.loads((DATA / "inventory.json").read_text())
    if data["schema_version"] != 1 or data["unknown_verb_tier"] != "K3":
        raise ValueError("unsupported inventory")
    for entry in data["verbs"].values():
        if entry["tier"] not in {"K1", "K2", "K3"} or not entry["hazards"]:
            raise ValueError("invalid inventory entry")
    return data


@dataclass(frozen=True)
class Act:
    verb: str
    payload_json: str
    target_ids: tuple[int, ...] = ()
    nonce: str = field(default_factory=lambda: secrets.token_hex(16))

    def __post_init__(self):
        if (not self.verb or not all(c.islower() or c.isdigit() or c == "-" for c in self.verb)
                or type(self.target_ids) is not tuple
                or any(type(i) is not int or i <= 0 for i in self.target_ids)
                or len(set(self.target_ids)) != len(self.target_ids)):
            raise ValueError("invalid act")
        if type(json.loads(self.payload_json)) is not dict or canonical(self.payload) != self.payload_json:
            raise ValueError("payload must be canonical JSON object")

    @property
    def payload(self):
        return json.loads(self.payload_json)  # callers cannot mutate the immutable plan

    def plan(self, legacy_tier: int | None) -> Plan:
        return Plan((Step(0, legacy_tier, "kitty.act", (self.verb, canonical({
            "payload": self.payload, "target_ids": self.target_ids, "nonce": self.nonce})), "/"),))


@dataclass(frozen=True)
class Assessment:
    """Independent trusted checker result, not model-supplied request fields."""
    legacy_tier: int | None
    nature: str  # observational / reversible / irreversible / credential-access / unknown
    denied: bool = False
    bracketed_paste: bool = False  # positive observed evidence only; never infer from program name
    assessor: str | None = None
    reason: str | None = None
    evidence_ref: str | None = None
    evidence: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Consent:
    ref: str
    plan_hash: str
    target_fingerprint: str
    exact_payload_hash: str
    execute_newline: bool = False
    program_acknowledged: bool = False


def fingerprint(windows):
    return digest([{k: w.get(k) for k in ("id", "pid", "cmdline", "tab_id", "os_id", "foreground_processes", "created_at")}
                   for w in sorted(windows, key=lambda w: w["id"])])


def tier_for(act: Act, assessment: Assessment, targets, owned, catalogue) -> str:
    tier = catalogue["verbs"].get(act.verb, {}).get("tier", "K3")
    if act.verb in {"close-window", "close-tab"}:
        tier = "K2" if targets and all(fingerprint([w]) in owned for w in targets) else "K3"
    if act.verb == "send-text" and targets and all(fingerprint([w]) in owned for w in targets):
        tier = "K2"
    if act.verb == "launch" and act.payload.get("type") in {"clipboard", "primary"}:
        tier = "K3"
    if assessment.nature not in {"observational", "reversible"}:
        tier = "K3"
    if act.verb == "send-text" and any(c in act.payload.get("data", "") for c in "\r\n\x1b"):
        tier = "K3"
    return tier


class Authorizer:
    def __init__(self, checker, *, audit=None, assessment_audit=None):
        if not callable(checker):
            raise TypeError("independent checker is required")
        self.checker = checker
        self.audit = audit
        self.assessment_audit = assessment_audit
        self.hand_ref = None
        self.denied = set()
        self.consumed = set()
        self.mismatches = {}
        self.consent = {}

    def open_hand(self, *, owner_phrase: str, reference: str):
        if owner_phrase != "kitty hand open" or not reference:
            raise PermissionError("explicit session hand-open required")
        self.hand_ref = reference

    def close_hand(self):
        self.hand_ref = None
        self.consent.clear()

    def decide(self, consent: Consent, *, owner_answer: str):
        # Trusted owner-input adapter only. Model/tool output must never call this API.
        if owner_answer.strip().casefold() == "no":
            self.denied.add(consent.plan_hash)
            self.consent.pop(consent.plan_hash, None)
        elif owner_answer.strip().casefold() == "yes" and consent.plan_hash not in self.denied:
            self.consent[consent.plan_hash] = consent
        else:
            raise PermissionError("exact yes/no required; no is terminal")

    def evaluate(self, act, plan, phase, targets):
        """Record checker attribution even on denial, before consent can be considered."""
        if plan != act.plan(plan.steps[0].tier):
            raise PermissionError("act does not match whole plan")
        # Do not expose checker exception text: it can contain the requested content.
        # The boundary is NOT an effect adapter; it can only attest a refusal.
        from .attribution import attribute, trace
        reason = None
        try:
            result = self.checker(act, phase, tuple(targets))
            trace(result, phase)
        except Exception:
            reason = "checker-failed-or-invalid-evidence"
        if reason is not None:
            result = attribute(Assessment(None, "unknown", denied=True),
                               assessor="kitty.assessment-boundary/v1", reason=reason,
                               act=act, phase=phase, targets=targets, basis={})
        if self.assessment_audit is not None:
            self.assessment_audit(act, plan, phase, targets, result)
        return result

    def assess(self, act, plan, phase, targets):
        if plan != act.plan(plan.steps[0].tier):
            raise PermissionError("act does not match whole plan")
        result = self.evaluate(act, plan, phase, targets)
        tier = 3 if result.nature == "credential-access" else result.legacy_tier
        verdict = adjudicate(plan.steps[0].tier, tier, self.mismatches.get(plan.digest, 0))
        self.mismatches[plan.digest] = verdict.mismatches
        if self.audit is not None:
            self.audit(plan.digest, verdict.mismatches)
        if result.denied or verdict.verdict == "refused" or plan.digest in self.denied:
            raise PermissionError("existing hands denial beats kitty consent")
        return result, verdict

    def authorize(self, act, plan, tier, assessment, verdict, targets):
        if plan.digest in self.consumed or plan.digest in self.denied:
            raise PermissionError("no replay or deny override")
        if tier == "K2" and self.hand_ref is None:
            raise PermissionError("session hand is closed")
        consent = self.consent.get(plan.digest)
        if (tier == "K3" or verdict.ask) and (consent is None or consent.plan_hash != plan.digest
                or consent.exact_payload_hash != digest(act.payload)
                or consent.target_fingerprint != fingerprint(targets)):
            raise PermissionError("exact act/target consent required")
        if act.verb == "send-text":
            text = act.payload.get("data", "")
            if not text.startswith("text:"):
                raise PermissionError("use raw text protocol, not CLI escaping or base64")
            text = text[5:]
            # CR, embedded newline and escape sequences are not made safe by removing a suffix.
            if any(c in text for c in "\r\n\x1b") and not (consent and consent.execute_newline):
                raise PermissionError("execution characters require per-act consent")
            if not assessment.bracketed_paste and not (consent and consent.program_acknowledged):
                raise PermissionError("running program must be acknowledged")
        return consent.ref if consent and (tier == "K3" or verdict.ask) else self.hand_ref if tier == "K2" else None
