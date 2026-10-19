"""Organiser service (§3.7) — index → plan → SHADOW LOG. Phase 3 stops
exactly there: this module has no code path that moves, renames or
deletes a user file. The executor (Phase 4) will consume these plans
through the safety spine; until the owner flips a root to `live` after
reading shadow logs they agree with (§4.3), plans are literature.

Shadow log = the trust-earning artifact: a readable markdown report of
what WOULD happen, grouped by decision, with per-file rule + reason +
confidence, plus the numbers that set honest thresholds — Tier 0
placement rate (Phase 3 done-when: >50%), rule histogram, tripwire.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .cost import iso_now
from .indexer import Indexer
from .planner import already_filed, tier0_propose
from .safety import check_blast_radius


class OrganiserService:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self.indexer = Indexer(config, store)
        self.shadow_dir = config.data_dir / "shadow"

    def index_roots(self) -> list[dict]:
        return [self.indexer.index_root(spec) for spec in self.config.organise_roots()]

    def build_plan(self, root_spec: dict, *, reindex: bool = True,
                   progress=None, plan_id: int | None = None) -> dict:
        """Build (and persist) a shadow plan for one root. Sync; callers
        run it off the event loop (§18: long work never blocks acks)."""
        root = root_spec["path"]
        mode = root_spec.get("mode", "shadow")
        if mode != "shadow":
            # Phase 3 is shadow-only by construction. A live root is a
            # Phase 4 conversation with the owner, not a config typo.
            raise ValueError(f"root {root} is mode={mode!r} — Phase 3 builds "
                             "SHADOW plans only (§4.3). Live execution arrives "
                             "in Phase 4 behind the executor.")
        plan_id = plan_id or self.store.create_plan(iso_now(), root, mode)
        try:
            index_stats = self.indexer.index_root(root_spec) if reindex else {}
            if progress:
                progress({"event": "plan.progress", "plan_id": plan_id,
                          "stage": "indexed", "stats": index_stats})
            documents = self.store.documents_in_root(root)
            taxonomy = root_spec["taxonomy"]
            items = []
            in_place = 0
            for doc in documents:
                filed = already_filed(doc["path"], root, taxonomy)
                if filed:
                    in_place += 1
                    items.append({"doc_id": doc["id"], "src": doc["path"],
                                  "dest": filed, "new_name": Path(doc["path"]).name,
                                  "confidence": 0.95, "tier": 0, "rule": "already-filed",
                                  "reason": f"already inside taxonomy folder '{filed}'",
                                  "decision": "auto"})
                    continue
                preview = "" if doc["never_send"] else self.store.document_preview(doc["id"])
                # never_send: content keywords would still be local-only,
                # but Tier 0 doesn't need content for them — filename rules
                # only, so the flag's meaning stays airtight end-to-end.
                proposal = tier0_propose(doc["path"], preview, taxonomy, doc_id=doc["id"])
                items.append(proposal.as_item())
            self.store.add_plan_items(plan_id, items)
            stats = self._stats(documents, items, in_place, index_stats)
            shadow_path = self._write_shadow_log(plan_id, root_spec, items, stats)
            self.store.finish_plan(
                plan_id, total=len(documents), placed=stats["placed_tier0"],
                abstained=stats["abstained"], shadow_log_path=str(shadow_path),
                stats_json=json.dumps(stats))
            if progress:
                progress({"event": "plan.proposed", "plan_id": plan_id,
                          "stats": stats, "shadow_log": str(shadow_path)})
            return {"plan_id": plan_id, "root": root, "mode": mode,
                    "stats": stats, "shadow_log": str(shadow_path)}
        except Exception as exc:
            self.store.finish_plan(plan_id, total=0, placed=0, abstained=0,
                                   shadow_log_path=None, stats_json="{}",
                                   error=f"{type(exc).__name__}: {exc}")
            raise

    def _stats(self, documents, items, in_place, index_stats) -> dict:
        total = len(documents)
        movable = [i for i in items if i["rule"] != "already-filed"]
        placed = [i for i in movable if i["decision"] in ("auto", "review", "unsorted")]
        abstained = [i for i in movable if i["decision"] == "abstain"]
        # Done-when metric (§9 Phase 3): Tier 0 alone places >50% — of the
        # files that actually need placing (loose files at root level).
        loose = max(len(movable), 1)
        organise = self.config.section("organise")
        tripwire = check_blast_radius(
            len([i for i in placed if i["decision"] == "auto"]), total,
            max_ops_per_run=int(organise.get("max_ops_per_run", 200)),
            tripwire_pct=int(organise.get("tree_tripwire_pct", 25)))
        return {
            "total_indexed": total,
            "already_filed_in_place": in_place,
            "loose_files": len(movable),
            "placed_tier0": len(placed),
            "tier0_placement_pct": round(100 * len(placed) / loose, 1),
            "abstained": len(abstained),
            "decisions": dict(Counter(i["decision"] for i in items)),
            "rules": dict(Counter(i["rule"] for i in items)),
            "tripwire": {"allowed": tripwire.allowed, "note": tripwire.reason},
            "index": index_stats,
            "api_calls": 0,  # Tier 0's whole point (§3.7) — keep it explicit
        }

    def _write_shadow_log(self, plan_id, root_spec, items, stats) -> Path:
        self.shadow_dir.mkdir(parents=True, exist_ok=True)
        path = self.shadow_dir / f"plan-{plan_id}.md"
        lines = [
            f"# Shadow plan #{plan_id} — {root_spec['path']}",
            "",
            ("Mode: **shadow** — nothing has moved. This log is what WOULD "
             "happen, for you to agree with or correct (§4.3)."),
            "",
            f"- Loose files needing placement: {stats['loose_files']}",
            (f"- Placed by Tier 0 rules (zero API calls): {stats['placed_tier0']} "
             f"({stats['tier0_placement_pct']}%)"),
            f"- Abstained (→ Tier 1/2 judgement in Phase 4): {stats['abstained']}",
            f"- Already correctly filed: {stats['already_filed_in_place']}",
            (f"- Blast-radius tripwire: {'OK' if stats['tripwire']['allowed'] else 'TRIPPED'} "
             f"— {stats['tripwire']['note']}"),
            "",
        ]
        for decision, title in (("auto", "Would auto-file (≥0.90)"),
                                ("review", "Would queue for your review (0.60–0.89)"),
                                ("unsorted", "Would park in _Unsorted (<0.60)"),
                                ("abstain", "No rule fired — needs judgement")):
            group = [i for i in items if i["decision"] == decision
                     and i["rule"] != "already-filed"]
            if not group:
                continue
            lines.append(f"## {title} — {len(group)}")
            lines.append("")
            for item in sorted(group, key=lambda i: i["src"]):
                dest = f" → `{item['dest']}/`" if item["dest"] else ""
                lines.append(
                    f"- `{Path(item['src']).name}`{dest} "
                    f"({item['confidence']:.2f}, {item['rule']}): {item['reason']}")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
