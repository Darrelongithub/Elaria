"""Phase 4 (§4/§3.7): executor, review, undo, verify, Tier 1/2.

Done-when under test: file hundreds of files, then undo --since ALL of
it cleanly. Plus the refusal paths: shadow roots, changed files,
protected paths, tripwires, halt — the spine must say no correctly."""

import json
import os
import time
from pathlib import Path

import pytest

from assistant.executor import Executor, parse_since
from assistant.gemini_client import GeminiClient
from assistant.organiser import OrganiserService
from assistant.planner_llm import LlmPlanner, _parse_batch
from assistant.safety import is_halted, set_halt
from assistant.store import Store

TAXONOMY = ["Finance", "Work", "Personal", "Photos", "_Unsorted", "_Conflicts"]
OLD = time.time() - 86400 * 3  # well outside the 15-minute guard (§4.1)


def aged(path: Path, text: str = "content") -> Path:
    path.write_text(text, encoding="utf-8")
    os.utime(path, (OLD, OLD))
    return path


def setup_root(config, tmp_path, root: Path, mode: str = "live"):
    config.raw["organise"] = {**config.raw["organise"],
                              "roots": [{"path": str(root), "mode": mode,
                                         "taxonomy": TAXONOMY}]}
    config.raw["policy"] = {**config.raw["policy"],
                            "recently_modified_guard_minutes": 15}
    store = Store(tmp_path / "t.db")
    return OrganiserService(config, store), Executor(config, store), store


def small_tree(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "Finance").mkdir()
    aged(root / "invoice-march.txt", "invoice due")
    aged(root / "payslip-may.txt", "net pay")
    aged(root / "holiday-photo.jpg", "jpeg-ish")
    aged(root / "q9-thing.xyz", "ambiguous")           # abstain: never applied
    aged(root / "Finance" / "already-home.txt", "stay")
    return root


def test_shadow_root_apply_is_refused(config, tmp_path):
    root = small_tree(tmp_path / "docs")
    svc, executor, _store = setup_root(config, tmp_path, root, mode="shadow")
    plan = svc.build_plan(config.organise_roots()[0])
    with pytest.raises(PermissionError, match="Shadow first"):
        executor.apply_plan(plan["plan_id"], config.organise_roots()[0])
    assert (root / "invoice-march.txt").exists()  # unmoved


def test_apply_journals_moves_and_undo_reverses(config, tmp_path):
    root = small_tree(tmp_path / "docs")
    svc, executor, store = setup_root(config, tmp_path, root)
    plan = svc.build_plan(config.organise_roots()[0])
    report = executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                                 allow_tripwire=True)
    assert report.applied >= 2 and not report.halted
    assert (root / "Finance" / "invoice-march.txt").exists()
    assert (root / "Photos" / "holiday-photo.jpg").exists()
    assert (root / "q9-thing.xyz").exists()  # abstention never filed by force
    committed = store.committed_operations(plan_id=plan["plan_id"])
    assert committed and all(o["sha256_after"] for o in committed)
    assert executor.verify()["problems"] == []

    undo = executor.undo(plan_id=plan["plan_id"])
    assert undo["problems"] == [] and undo["undone"] == len(committed)
    assert (root / "invoice-march.txt").exists()
    assert not (root / "Finance" / "invoice-march.txt").exists()
    # Undo itself journaled: the originals are now rolled_back.
    assert store.committed_operations(plan_id=plan["plan_id"]) != committed


def test_changed_file_is_refused_mid_apply(config, tmp_path):
    root = small_tree(tmp_path / "docs")
    svc, executor, _store = setup_root(config, tmp_path, root)
    plan = svc.build_plan(config.organise_roots()[0])
    target = root / "invoice-march.txt"
    target.write_text("EDITED after planning — different bytes now")
    os.utime(target, (OLD, OLD))
    report = executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                                 allow_tripwire=True)
    assert any("changed since indexing" in r["reason"] for r in report.refused)
    assert target.exists() and target.read_text().startswith("EDITED")


def test_collision_routes_to_conflicts_never_overwrites(config, tmp_path):
    root = small_tree(tmp_path / "docs")
    # Destination already occupied by DIFFERENT content.
    aged(root / "Finance" / "invoice-march.txt", "the original already filed")
    svc, executor, _store = setup_root(config, tmp_path, root)
    plan = svc.build_plan(config.organise_roots()[0])
    report = executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                                 allow_tripwire=True)
    assert report.conflicts == 1
    assert (root / "Finance" / "invoice-march.txt").read_text() == "the original already filed"
    assert (root / "_Conflicts" / "invoice-march.txt").read_text() == "invoice due"


def test_tripwire_blocks_without_explicit_allow(config, tmp_path):
    root = small_tree(tmp_path / "docs")
    svc, executor, _store = setup_root(config, tmp_path, root)
    plan = svc.build_plan(config.organise_roots()[0])
    report = executor.apply_plan(plan["plan_id"], config.organise_roots()[0])
    assert report.capped and report.applied == 0  # >25% of tree: pause & ask


def test_halt_stops_between_operations(config, tmp_path):
    root = small_tree(tmp_path / "docs")
    svc, executor, _store = setup_root(config, tmp_path, root)
    plan = svc.build_plan(config.organise_roots()[0])
    set_halt(executor.runtime)
    assert is_halted(executor.runtime)
    report = executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                                 allow_tripwire=True)
    assert report.halted and report.applied == 0


def test_review_queue_gates_mid_confidence(config, tmp_path):
    root = tmp_path / "docs"
    root.mkdir(parents=True)
    aged(root / "mystery-document.pdf", "some pdf bytes")  # extension-class 0.70
    svc, executor, store = setup_root(config, tmp_path, root)
    config.raw["organise"]["roots"][0]["taxonomy"] = [
        "Reference", "Finance", "_Unsorted", "_Conflicts"]
    plan = svc.build_plan(config.organise_roots()[0])
    items = store.plan_items(plan["plan_id"], "review")
    assert items and items[0]["rule"] == "extension-class"
    report = executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                                 allow_tripwire=True)
    assert report.applied == 0  # review items are NOT auto-applied
    store.set_item_decision(items[0]["id"], "auto")  # owner approved
    svc.indexer.index_root(config.organise_roots()[0])
    store.set_plan_status(plan["plan_id"], "ready")
    report = executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                                 allow_tripwire=True)
    assert report.applied == 1


def test_500_files_round_trip(config, tmp_path):
    """The Phase 4 done-when, at scout scale: file them, undo them ALL."""
    root = tmp_path / "big"
    root.mkdir(parents=True)
    for i in range(500):
        kind = ["invoice", "payslip", "photo", "contract"][i % 4]
        aged(root / f"{kind}-{i:03d}.txt", f"{kind} number {i}")
    config.raw["organise"] = {**config.raw["organise"], "max_ops_per_run": 600,
                              "max_ops_per_hour": 5000}
    svc, executor, _store = setup_root(config, tmp_path, root)
    plan = svc.build_plan(config.organise_roots()[0])
    assert plan["stats"]["tier0_placement_pct"] > 90
    report = executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                                 allow_tripwire=True)
    assert report.applied == 500 and executor.verify()["problems"] == []
    undo = executor.undo(since_iso=parse_since("1h"))
    assert undo["undone"] == 500 and undo["problems"] == []
    loose = [p for p in root.iterdir() if p.is_file()]
    assert len(loose) == 500  # every file home again


def test_trash_never_rms(config, tmp_path):
    doomed = aged(tmp_path / "doomed.txt", "bye")
    _svc, executor, _store = setup_root(config, tmp_path, small_tree(tmp_path / "d"))
    result = executor.trash(doomed)
    assert not doomed.exists()
    assert Path(result["trashed_as"]).exists()
    manifest = Path(result["manifest"]).read_text()
    assert "doomed.txt" in manifest


def test_parse_since():
    assert parse_since("2h") < parse_since("30m") < parse_since("2999-01-01")


# -- Tier 1/2 --------------------------------------------------------------------------
class JsonTransport:
    def __init__(self):
        self.calls = []

    def generate(self, model, contents, config):
        self.calls.append(model)
        assert isinstance(contents, str)
        entries = []
        for line in contents.splitlines():
            if line.startswith("- path: "):
                path = line.split("- path: ")[1].strip()
                entries.append({"path": path, "dest": "Finance",
                                "new_name": Path(path).name, "confidence": 0.88,
                                "reason": "looks financial"})
        return {"text": json.dumps(entries),
                "usage": {"tokens_in": 50, "tokens_out": 40}}


def test_tier1_classifies_abstentions_within_taxonomy(config, tmp_path):
    store = Store(tmp_path / "t.db")
    client = GeminiClient(config, store, transport=JsonTransport(),
                          sleep=lambda _: None)
    items = [{"src": "/r/mystery-ledger-thing.dat", "dest": None, "new_name": None,
              "confidence": 0.0, "tier": 0, "rule": "abstain", "reason": "-",
              "decision": "abstain", "doc_id": None}]
    LlmPlanner(config, store, client).classify_abstained(items, TAXONOMY)
    assert items[0]["dest"] == "Finance" and items[0]["tier"] in (1, 2)
    assert store.llm_summary()["calls"] >= 1  # ledgered like every call


def test_tier_verifier_rejects_invented_folders():
    evil = json.dumps([{"path": "/r/a.txt", "dest": "MadeUpFolder",
                        "confidence": 0.99, "reason": "trust me"}])
    assert _parse_batch(evil, set(TAXONOMY), {"/r/a.txt"}) is None
    overconfident = json.dumps([{"path": "/r/a.txt", "dest": "Finance",
                                 "confidence": 1.7, "reason": "sure"}])
    assert _parse_batch(overconfident, set(TAXONOMY), {"/r/a.txt"}) is None


def test_build_with_tiers_counts_api_calls(config, tmp_path):
    root = small_tree(tmp_path / "docs")
    store = Store(tmp_path / "t.db")
    config.raw["organise"] = {**config.raw["organise"],
                              "roots": [{"path": str(root), "mode": "shadow",
                                         "taxonomy": TAXONOMY}]}
    client = GeminiClient(config, store, transport=JsonTransport(), sleep=lambda _: None)
    result = OrganiserService(config, store, client).build_plan(
        config.organise_roots()[0], with_llm_tiers=True)
    assert result["stats"]["api_calls"] >= 1
    items = {Path(i["src"]).name: i for i in store.plan_items(result["plan_id"])}
    assert items["q9-thing.xyz"]["tier"] in (1, 2)  # ambiguity resolved by LLM tier
