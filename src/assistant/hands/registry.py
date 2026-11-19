"""Exhaustive R4 v1 event/verdict contract. No executable dispatch registry."""
from types import MappingProxyType

EVENTS = MappingProxyType({
    "hands.plan": frozenset({"ok", "refused"}),
    "hands.step": frozenset({"ok", "refused", "cancelled", "timeout", "degraded"}),
    "hands.gate": frozenset({"ok", "mismatch-escalated", "refused"}),
    "hands.ask": frozenset({"ok", "stale"}),
    "hands.decision": frozenset({"yes", "no", "stale"}),
    "hands.exec": frozenset({"ok", "failed", "timeout"}),
    "hands.verify": frozenset({"ok", "mismatch"}),
    "hands.cancel": frozenset({"cancel-intent", "cancelled", "refused"}),
    "hands.report": frozenset({"ok"}),
    "hands.inject": frozenset({"inject"}),
})
