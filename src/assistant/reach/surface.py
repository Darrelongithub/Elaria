"""Interestingness gate — reason-gated, novelty-deduped, zero knock budget.

Emits findings via ``InitiativeService.raise_knock(kind="finding")`` only when:
1. A stored owner-stated interest matches the document.
2. The finding is novel (not already surfaced for this URL/hash).
3. Sources are attached (``doc.final_url``).

Model API budget: 0 calls/day, 0 tokens/day (never touches personality tier).
"""

from __future__ import annotations

import re

from .contract import FetchedDoc
from .observe import journal_target


class InterestingnessGate:
    """Reason-gated surfacing of fetched documents into ``initiative.raise_knock``."""

    def __init__(self, *, initiative=None):
        self.initiative = initiative
        self._seen: set[tuple[str, str]] = set()

    @staticmethod
    def _matches_interest(doc: FetchedDoc, interests: list[str]) -> str | None:
        haystack = f"{doc.title}\n{doc.excerpt}\n{doc.text}".lower()
        for raw in interests:
            interest = str(raw or "").strip()
            if not interest:
                continue
            tokens = [t for t in re.findall(r"[a-z0-9]+", interest.lower()) if len(t) >= 3]
            if tokens and all(tok in haystack for tok in tokens):
                return interest
        return None

    def evaluate(
        self,
        doc: FetchedDoc,
        *,
        interests: list[str],
        initiative=None,
    ) -> dict | None:
        """Return a knock dict if interesting & novel, else ``None``."""
        key = (doc.final_url, doc.sha256)
        if key in self._seen:
            return None

        matched = self._matches_interest(doc, interests)
        if matched is None:
            return None

        self._seen.add(key)
        svc = initiative or self.initiative
        # The match is a local observation, not a claim or a page-authored reason.
        source = journal_target(doc.final_url) or "web"
        reason = f"A fetched page matches your stated interest {matched!r} (source: {source})"

        if svc is None:
            return {
                "kind": "finding",
                "topic": f"reach:{matched}",
                "referent": source,
                "reason": reason,
                "source_url": source,
            }

        return svc.raise_knock(
            topic=f"reach:{matched}",
            reason=reason,
            kind="finding",
            referent=source,
        )
