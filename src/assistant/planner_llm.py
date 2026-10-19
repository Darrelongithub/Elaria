"""Planner Tiers 1–2 (§3.7) — the LLM tail, behind the §17 harness.

Only Tier-0 abstentions ever reach here (~25% Tier 1, ~4% Tier 2 on the
blueprint's expected split). The model proposes; code disposes:
- Requests batch many files per call (50 / 10) — the quota math (§12.1).
- The model may ONLY choose from the frozen taxonomy + _Unsorted.
- Output is verified deterministically (strict JSON, valid dest,
  confidence in range) inside the harness: unverifiable output retries,
  escalates Lite→Flash, and ultimately ABSTAINS — never guesses.
- never_send files are classified by filename only (no content leaves
  the machine); if filename alone is insufficient they stay abstained.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .planner import Proposal, decide

PROMPT_TEMPLATE = """Classify each file into exactly one folder from this frozen taxonomy:
{taxonomy}

Rules: pick from the taxonomy only (or "_Unsorted"). Judge from the filename
and snippet. Confidence is your honest 0..1 — low confidence is useful
information, a confident guess is not. Reply with ONLY a JSON array:
[{{"path": "...", "dest": "...", "new_name": "...", "confidence": 0.0, "reason": "..."}}]

Files:
{files}"""


def _parse_batch(text: str, allowed: set[str], expected_paths: set[str]) -> list[dict] | None:
    """Strict verifier: any structural sin invalidates the batch."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    for entry in data:
        if not isinstance(entry, dict):
            return None
        if entry.get("path") not in expected_paths:
            return None  # hallucinated or dropped file
        if entry.get("dest") not in allowed:
            return None  # invented folder — the one unforgivable sin
        confidence = entry.get("confidence")
        if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
            return None
    return data


class LlmPlanner:
    def __init__(self, config, store, client):
        self.config = config
        self.store = store
        self.client = client
        organise = config.section("organise")
        self.tier1_batch = int(organise.get("tier1_batch_size", 50))
        self.tier2_batch = int(organise.get("tier2_batch_size", 10))
        self.escalate_below = float(organise.get("tier0_min_confidence", 0.85))

    def classify_abstained(self, items: list[dict], taxonomy: list[str]) -> list[dict]:
        """Upgrade abstain items in place (returns the same list). Tier 1
        sweeps all; Tier 2 re-asks the still-weak with the bigger model."""
        pending = [i for i in items if i["decision"] == "abstain"]
        if not pending:
            return items
        self._classify(pending, taxonomy, tier=1, role="organise",
                       batch_size=self.tier1_batch)
        still_weak = [i for i in pending
                      if i["decision"] == "abstain"
                      or (i["confidence"] or 0) < self.escalate_below]
        if still_weak:
            self._classify(still_weak, taxonomy, tier=2, role="chat",
                           batch_size=self.tier2_batch)
        return items

    def _classify(self, batch_items, taxonomy, *, tier, role, batch_size):
        allowed = set(taxonomy) | {"_Unsorted"}
        for start in range(0, len(batch_items), batch_size):
            batch = batch_items[start:start + batch_size]
            descriptions = []
            for item in batch:
                doc = self.store.document_by_path(item["src"]) or {}
                snippet = ""
                if item.get("doc_id") and not doc.get("never_send"):
                    snippet = self.store.document_preview(item["doc_id"], 300)
                descriptions.append(
                    f"- path: {item['src']}\n  name: {Path(item['src']).name}\n"
                    f"  snippet: {snippet!r}")
            prompt = PROMPT_TEMPLATE.format(
                taxonomy=", ".join(taxonomy), files="\n".join(descriptions))
            expected = {i["src"] for i in batch}
            try:
                result = self.client.generate(
                    role, prompt,
                    verify=lambda text, _e=expected: _parse_batch(text, allowed, _e) is not None)
            except Exception:  # noqa: S112 — abstain stands; error already ledgered by client
                continue  # quota/transport trouble: abstain stands (§12.7 patience)
            parsed = _parse_batch(result.text, allowed, expected)
            if not parsed:
                continue  # unverifiable after escalation — honest abstention
            by_path = {entry["path"]: entry for entry in parsed}
            for item in batch:
                entry = by_path.get(item["src"])
                if not entry:
                    continue
                confidence = float(entry["confidence"])
                proposal = Proposal(item["src"], entry["dest"],
                                    entry.get("new_name") or Path(item["src"]).name,
                                    confidence, tier, f"tier{tier}-llm",
                                    str(entry.get("reason", ""))[:300],
                                    decide(confidence))
                item.update(proposal.as_item())
