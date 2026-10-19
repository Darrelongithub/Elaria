"""Phase 3 (§3.7/§4.3): indexer + Tier 0 cascade + shadow plans.

The safety invariant under test everywhere here: building a plan changes
NOTHING on disk. The quality invariant: Tier 0 alone (zero API calls)
places the deterministic majority — done-when is >50% of loose files.
"""

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from assistant.indexer import extract_text
from assistant.organiser import OrganiserService
from assistant.planner import suggest_taxonomy, tier0_propose
from assistant.store import Store
from assistant.watcher import PollingWatcher

TAXONOMY = ["Finance", "Work", "Personal", "Photos", "Reference", "_Unsorted", "_Conflicts"]


def make_tree(root: Path) -> Path:
    """A realistic messy root: obvious files, ambiguous files, traps."""
    root.mkdir(parents=True)
    (root / "Finance").mkdir()  # existing taxonomy folder (empty at top)
    files = {
        # deterministic majority — Tier 0 should place these
        "invoice-kamau-march.pdf": "Invoice no 42 total due",
        "2026-03-15_tax-return.pdf": "tax return filing",
        "Screenshot_20261001.png": "",
        "payslip-october.txt": "net pay statement",
        "contract-freelance.txt": "agreement between parties",
        "lecture-notes-week3.txt": "lecture notes on compilers",
        "photo-beach-trip.jpg": "",
        "random-musings.txt": "dear diary, the invoice for the boat arrived",
        # genuinely ambiguous — must abstain, never guess
        "untitled-thing.xyz": "???",
        "a1b2c3.bin": "",
        # traps: temp download + hidden + ignored dir + already filed
        "half-downloaded.iso.crdownload": "partial",
    }
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    (root / ".hidden-secret.txt").write_text("nope")
    ignored = root / "private-stuff"
    ignored.mkdir()
    (ignored / ".assistant-ignore").write_text("")
    (ignored / "diary.txt").write_text("never index me")
    filed = root / "Finance" / "old-invoice-2025.txt"
    filed.write_text("already home")
    return root


def tree_fingerprint(root: Path) -> dict:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def organiser(config, tmp_path, root):
    config.raw["organise"] = {
        **config.raw["organise"],
        "roots": [{"path": str(root), "mode": "shadow", "taxonomy": TAXONOMY}],
    }
    store = Store(tmp_path / "t.db")
    return OrganiserService(config, store), store


# -- indexer ------------------------------------------------------------------------
def test_indexer_respects_ignore_hidden_and_temp(config, tmp_path):
    root = make_tree(tmp_path / "docs")
    svc, store = organiser(config, tmp_path, root)
    stats = svc.index_roots()[0]
    paths = {d["path"] for d in store.documents_in_root(str(root))}
    assert not any("private-stuff" in p for p in paths)       # .assistant-ignore
    assert not any(".hidden" in p for p in paths)             # hidden
    assert not any(p.endswith(".crdownload") for p in paths)  # partial download
    assert stats["skipped"] and stats["indexed"] >= 9
    invoice = store.document_by_path(str(root / "invoice-kamau-march.pdf"))
    assert invoice["sha256"] and invoice["status"] == "indexed"


def test_indexer_detects_change_and_missing(config, tmp_path):
    root = make_tree(tmp_path / "docs")
    svc, store = organiser(config, tmp_path, root)
    svc.index_roots()
    second = svc.index_roots()[0]
    assert second["indexed"] == 0 and second["unchanged"] > 0  # idempotent
    target = root / "payslip-october.txt"
    target.write_text("CHANGED content entirely")
    os.utime(target, (time.time() + 5, time.time() + 5))
    (root / "a1b2c3.bin").unlink()
    third = svc.index_roots()[0]
    assert third["changed"] == 1 and third["missing_marked"] == 1
    assert store.document_by_path(str(root / "a1b2c3.bin"))["status"] == "missing"


def test_never_send_files_index_locally_but_flagged(config, tmp_path):
    root = make_tree(tmp_path / "docs")
    medical = root / "medical-results.txt"
    medical.write_text("invoice for the clinic visit")
    config.raw["privacy"]["never_send_to_cloud"] = [str(medical)]
    svc, store = organiser(config, tmp_path, root)
    svc.index_roots()
    doc = store.document_by_path(str(medical))
    assert doc["never_send"] == 1  # searchable locally, never shipped
    hits = store.search_documents("clinic")
    assert any(h["path"] == str(medical) for h in hits)


def test_fts_search_finds_content(config, tmp_path):
    root = make_tree(tmp_path / "docs")
    svc, store = organiser(config, tmp_path, root)
    svc.index_roots()
    hits = store.search_documents("compilers")
    assert hits and "lecture-notes" in hits[0]["path"]


def test_docx_extraction_via_stdlib(tmp_path):
    import zipfile
    path = tmp_path / "memo.docx"
    xml = ('<?xml version="1.0"?><w:document xmlns:w="x">'
           '<w:body><w:p><w:r><w:t>Quarterly invoice summary</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", xml)
    text, extractor = extract_text(path)
    assert "invoice summary" in text and extractor == "docx"


# -- Tier 0 rules ---------------------------------------------------------------------
@pytest.mark.parametrize("filename,expected_dest", [
    ("invoice-acme.pdf", "Finance"),
    ("payslip-may.txt", "Finance"),
    ("Screenshot_20260101.png", "Photos"),
    ("contract-2026.txt", "Work"),
    ("finance-plan-2027.txt", "Finance"),  # folder-keyword rule
])
def test_tier0_rules_place_the_obvious(filename, expected_dest):
    proposal = tier0_propose(f"/r/{filename}", "", TAXONOMY)
    assert proposal.dest == expected_dest and proposal.tier == 0
    assert proposal.decision in ("auto", "review")


def test_tier0_abstains_rather_than_guesses():
    proposal = tier0_propose("/r/zxqv-thing.xyz", "", TAXONOMY)
    assert proposal.decision == "abstain" and proposal.dest is None


def test_tier0_never_invents_folders():
    # Taxonomy without a finance-ish folder: 'invoice' alone cannot conjure one.
    proposal = tier0_propose("/r/invoice-x.pdf", "", ["Music", "_Unsorted", "_Conflicts"])
    assert proposal.dest in (None, "Music")  # pdf extension can't match Music -> abstain
    assert proposal.dest is None


# -- shadow plans ------------------------------------------------------------------------
def test_shadow_plan_writes_nothing_and_tier0_places_majority(config, tmp_path):
    root = make_tree(tmp_path / "docs")
    svc, store = organiser(config, tmp_path, root)
    before = tree_fingerprint(root)
    result = svc.build_plan(config.organise_roots()[0])
    assert tree_fingerprint(root) == before, "SHADOW PLAN MOVED A FILE"
    stats = result["stats"]
    assert stats["api_calls"] == 0
    # Phase 3 done-when: Tier 0 alone places >50% of loose files (§9).
    assert stats["tier0_placement_pct"] > 50
    shadow = Path(result["shadow_log"]).read_text()
    assert "nothing has moved" in shadow and "invoice-kamau-march" in shadow
    plan = store.get_plan(result["plan_id"])
    assert plan["status"] == "ready" and plan["mode"] == "shadow"
    items = {Path(i["src"]).name: i for i in store.plan_items(result["plan_id"])}
    assert items["old-invoice-2025.txt"]["rule"] == "already-filed"
    assert items["untitled-thing.xyz"]["decision"] == "abstain"
    assert "private-stuff" not in json.dumps(items)


def test_live_root_is_refused_in_phase3(config, tmp_path):
    root = make_tree(tmp_path / "docs")
    svc, _store = organiser(config, tmp_path, root)
    spec = {**config.organise_roots()[0], "mode": "live"}
    with pytest.raises(ValueError, match="SHADOW plans only"):
        svc.build_plan(spec)


def test_no_roots_means_no_indexing(config, tmp_path):
    store = Store(tmp_path / "t.db")
    assert OrganiserService(config, store).index_roots() == []  # opt-in only


def test_taxonomy_suggestion_reads_existing_folders(tmp_path):
    root = make_tree(tmp_path / "docs")
    suggestions = suggest_taxonomy(root)
    names = [s["folder"] for s in suggestions]
    assert "Finance" in names and "_Unsorted" in names and "_Conflicts" in names


# -- watcher ------------------------------------------------------------------------------
def test_watcher_debounces_until_settled(tmp_path):
    root = tmp_path / "watched"
    root.mkdir()
    clock = [time.time()]  # must share an epoch with real mtimes
    watcher = PollingWatcher(root, debounce_s=10.0, now=lambda: clock[0])
    (root / "download.bin").write_bytes(b"partial")
    events = watcher.scan()
    assert events.created and not events.settled_changed  # in burst window
    clock[0] += 5
    (root / "download.bin").write_bytes(b"more bytes written")  # still arriving
    events = watcher.scan()
    assert not events.settled_changed
    clock[0] += 11
    events = watcher.scan()
    assert events.settled_changed == [str(root / "download.bin")]


def test_watcher_ignores_temp_suffixes(tmp_path):
    root = tmp_path / "watched"
    root.mkdir()
    watcher = PollingWatcher(root, debounce_s=0.0, now=lambda: 5000.0)
    (root / "file.iso.crdownload").write_bytes(b"x")
    assert not watcher.scan().any


# -- daemon + CLI ------------------------------------------------------------------------------
def test_daemon_plan_build_is_async_and_shadow(config, tmp_path, running_daemon):
    import time as _time

    from assistant.ipc import call

    root = make_tree(tmp_path / "docs")
    daemon, _server = running_daemon
    daemon.config.raw["organise"] = {
        **daemon.config.raw["organise"],
        "roots": [{"path": str(root), "mode": "shadow", "taxonomy": TAXONOMY}]}
    before = tree_fingerprint(root)
    reply = call(config.socket_path, "plan.build")
    plan_id = reply["started"][0]["plan_id"]
    assert reply["network"] is False  # ack semantics preserved (§18)
    deadline = _time.time() + 30
    while _time.time() < deadline:
        data = call(config.socket_path, "plan.show", {"plan_id": plan_id})
        if data["plan"]["status"] != "building":
            break
        _time.sleep(0.2)
    assert data["plan"]["status"] == "ready"
    assert data["plan"]["placed_tier0"] > 0
    assert tree_fingerprint(root) == before  # daemon path also moves nothing
    results = call(config.socket_path, "docs.search", {"query": "compilers"})
    assert results["results"]


def test_cli_plan_build_local_fallback(tmp_path):
    import subprocess
    import sys

    root = make_tree(tmp_path / "docs")
    home = Path(os.environ["HOME"])
    config_file = home / ".config" / "assistant" / "config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    taxonomy = ", ".join(f'"{t}"' for t in TAXONOMY)
    config_file.write_text(
        f'[[organise.roots]]\npath = "{root}"\nmode = "shadow"\ntaxonomy = [{taxonomy}]\n')
    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}
    before = tree_fingerprint(root)
    out = subprocess.run([sys.executable, "-m", "assistant.cli", "plan", "build"],
                         check=False, capture_output=True, text=True, env=env, timeout=120)
    assert out.returncode == 0, out.stderr
    assert "zero API calls" in out.stdout and "Nothing moved" in out.stdout
    assert tree_fingerprint(root) == before
    assert list((home / ".local/share/assistant/shadow").glob("plan-*.md"))
