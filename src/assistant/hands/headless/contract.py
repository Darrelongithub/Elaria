"""P · HANDS-HEADLESS — the worker contract: the ONLY remote-control verbs.

Build step 2 of P-HEADLESS.md: only ``ls``, ``get-text`` and ``send-text`` are
reachable at the remote-control level, and ``get-text --extent`` is
CONSTRAINED to the assessed subset.

The assessed extent subset excludes the two capabilities Q's 0.49.2 re-pin
added (``alternate`` / ``alternate_scrollback``, which reach invisible screen
+ scrollback). Narrowing the subset is free; widening it requires an owner
ruling (coordination ask 50 — recorded in the report, not granted here).
"""

from __future__ import annotations

ALLOWED_VERBS = frozenset({"ls", "get-text", "send-text"})

# Assessed safe subset for ``get-text --extent``. The 0.49.2 additions
# (alternate / alternate_scrollback) are deliberately NOT in this set.
DEFAULT_EXTENT_SUBSET = frozenset({"viewport", "all"})

# Options each verb accepts, and whether the option is extent-constrained.
_VERB_OPTIONS: dict[str, frozenset[str]] = {
    "ls": frozenset(),
    "get-text": frozenset({"extent"}),
    "send-text": frozenset(),
}


class ContractViolationError(ValueError):
    """A request or configuration violates the worker contract.

    Messages are deliberately legible (failure ask 48): they state what was
    rejected, what the contract allows, and why.
    """


class WorkerContract:
    """Enforces the three-verb remote-control surface and the extent subset."""

    def __init__(
        self,
        verbs: frozenset[str] = ALLOWED_VERBS,
        extent_subset: frozenset[str] = DEFAULT_EXTENT_SUBSET,
    ) -> None:
        extra = verbs - ALLOWED_VERBS
        if extra:
            raise ContractViolationError(
                f"worker contract refuses extra verbs {sorted(extra)}; only "
                f"{sorted(ALLOWED_VERBS)} are reachable at the remote-control level"
            )
        widened = extent_subset - DEFAULT_EXTENT_SUBSET
        if widened:
            raise ContractViolationError(
                f"worker contract refuses to widen get-text --extent to "
                f"{sorted(widened)}; the assessed subset is "
                f"{sorted(DEFAULT_EXTENT_SUBSET)} and widening requires an "
                "owner ruling (coordination ask 50)"
            )
        if not verbs:
            raise ContractViolationError("worker contract has no verbs configured")
        if not extent_subset:
            raise ContractViolationError(
                "worker contract has an empty extent subset; get-text --extent "
                "would be unconstrained, which the contract forbids"
            )
        self.verbs = frozenset(verbs)
        self.extent_subset = frozenset(extent_subset)

    def allows(self, verb: str) -> bool:
        return verb in self.verbs

    def check_request(self, verb: str, options: dict[str, str] | None = None) -> None:
        """Validate one remote-control request or raise legibly."""
        options = options or {}
        if verb not in self.verbs:
            raise ContractViolationError(
                f"worker contract violation: verb {verb!r} is not allowed; only "
                f"{sorted(self.verbs)} are reachable at the remote-control level"
            )
        allowed_options = _VERB_OPTIONS[verb]
        unknown = set(options) - allowed_options
        if unknown:
            raise ContractViolationError(
                f"worker contract violation: option(s) {sorted(unknown)} are "
                f"not allowed for verb {verb!r}; allowed options are "
                f"{sorted(allowed_options) or 'none'}"
            )
        if verb == "get-text":
            extent = options.get("extent")
            if extent is None:
                raise ContractViolationError(
                    "worker contract violation: get-text requires --extent; "
                    "the assessed subset is "
                    f"{sorted(self.extent_subset)}"
                )
            if extent not in self.extent_subset:
                raise ContractViolationError(
                    f"worker contract violation: get-text --extent {extent!r} "
                    f"is outside the assessed subset {sorted(self.extent_subset)}; "
                    "narrowing is allowed, widening requires an owner ruling"
                )
