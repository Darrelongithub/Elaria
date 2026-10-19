"""Adversarial bug-hunt corpus: safety spine, executor, undo (areas A–C).

Expected-safe behaviour is asserted against on-disk/journal STATE, never
against exit codes. Known bugs are strict-xfail with BUGHUNT.md IDs: when
one starts passing, the suite goes red until the marker is retired.
"""

from __future__ import annotations

import errno
import hashlib
import json
import multiprocessing
import os
import random
import time
from pathlib import Path

import pytest

from assistant.executor import Executor
from assistant.indexer import Indexer
from assistant.planner_llm import _parse_batch
from assistant.safety import is_halted, is_protected, set_halt
from assistant.store import Store

OLD = time.time() - 86400 * 3
TAXONOMY = ["Finance", "Photos", "_Unsorted", "_Conflicts"]
FIXTURES = json.loads(
    (Path(__file__).parent / "bughunt_fixtures" / "evil_inputs.json").read_text())


def aged(path: Path, data: bytes | str = b"content") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode()
    path.write_bytes(data)
    os.utime(path, (OLD, OLD))
    return path


def setup(config, tmp_path: Path, root: Path, *, protected=None):
    config.raw["organise"] = {
        **config.raw["organise"], "max_ops_per_run": 500, "max_ops_per_hour": 5000,
        "roots": [{"path": str(root), "mode": "live", "taxonomy": TAXONOMY}]}
    if protected is not None:
        config.raw["policy"] = {**config.raw["policy"], "protected": protected}
    store = Store(tmp_path / "hunt.db")
    spec = config.organise_roots()[0]
    return store, Executor(config, store), spec


def index(config, store, spec):
    stats = Indexer(config, store).index_root(spec)
    assert "error" not in stats
    return stats


def manual_plan(store: Store, root: Path, proposals: list[dict]) -> int:
    from assistant.cost import iso_now

    plan_id = store.create_plan(iso_now(), str(root), "live")
    items = []
    for proposal in proposals:
        doc = store.document_by_path(str(proposal["src"]))
        items.append({
            "doc_id": doc["id"] if doc else None,
            "src": str(proposal["src"]),
            "dest": proposal.get("dest", "Finance"),
            "new_name": proposal.get("new_name", Path(proposal["src"]).name),
            "confidence": 0.99, "tier": 0, "rule": "bughunt-manual",
            "reason": "adversarial fixture", "decision": "auto"})
    store.add_plan_items(plan_id, items)
    store.finish_plan(plan_id, total=len(items), placed=len(items), abstained=0,
                      shadow_log_path=None, stats_json="{}")
    return plan_id


def tree_state(root: Path) -> dict[str, tuple[str, str]]:
    state = {}
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            state[rel] = ("link", os.readlink(path))
        elif path.is_file():
            state[rel] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
    return state


# -- A: invariant fuzz -----------------------------------------------------------

@pytest.mark.parametrize("seed", range(20))
def test_random_evil_trees_apply_verify_undo_byte_identical(config, tmp_path, seed):
    rng = random.Random(seed)
    root = tmp_path / "docs"
    (root / "Finance").mkdir(parents=True)
    files = []
    decorations = ["", " (final) (2)", "—ünïcodé—✓", "\nnewline", "..dots",
                   "'", '"q"', ";semi", "$dollar", "-🧾"]
    for i in range(18):
        name = f"invoice-{seed}-{i}{rng.choice(decorations)}.txt"
        if i == 0:
            name = "invoice-" + ("x" * 220) + ".txt"  # near NAME_MAX, legal
        payload = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 300)))
        files.append(aged(root / name, payload))
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    before = tree_state(root)
    plan_id = manual_plan(store, root, [{"src": p} for p in files])

    report = executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert report.applied == len(files), report.refused
    assert executor.verify()["problems"] == []
    undo = executor.undo(plan_id=plan_id)
    assert undo["problems"] == [] and undo["undone"] == len(files)
    assert tree_state(root) == before


def test_duplicate_basenames_collide_to_conflicts_and_undo_restores(config, tmp_path):
    root = tmp_path / "docs"
    first = aged(root / "a" / "invoice.txt", "first")
    second = aged(root / "b" / "invoice.txt", "second")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    before = tree_state(root)
    plan_id = manual_plan(store, root, [{"src": first}, {"src": second}])

    report = executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert report.applied == 1 and report.conflicts == 1
    assert (root / "Finance" / "invoice.txt").read_bytes() == b"first"
    assert (root / "_Conflicts" / "invoice.txt").read_bytes() == b"second"
    undo = executor.undo(plan_id=plan_id)
    assert undo["problems"] == [] and undo["undone"] == 2
    assert tree_state(root) == before


def test_conflicts_route_reruns_policy_for_its_own_destination(config, tmp_path):
    root = tmp_path / "docs"
    first = aged(root / "a" / "invoice.txt", "first")
    second = aged(root / "b" / "invoice.txt", "second")
    store, executor, spec = setup(
        config, tmp_path, root, protected=[str(root / "_Conflicts")])
    index(config, store, spec)
    before = tree_state(root)
    plan_id = manual_plan(store, root, [{"src": first}, {"src": second}])

    report = executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert report.applied == 1 and report.conflicts == 0
    assert any("_Conflicts route refused: protected destination" in r["reason"]
               for r in report.refused)
    assert second.exists() and second.read_bytes() == b"second"
    assert not (root / "_Conflicts" / "invoice.txt").exists()
    undo = executor.undo(plan_id=plan_id)
    assert undo["problems"] == [] and tree_state(root) == before


def test_conflicts_symlink_cannot_escape_root(config, tmp_path):
    root = tmp_path / "docs"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    root.mkdir()
    (root / "_Conflicts").symlink_to(outside, target_is_directory=True)
    first = aged(root / "a" / "invoice.txt", "first")
    second = aged(root / "b" / "invoice.txt", "second")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [{"src": first}, {"src": second}])

    report = executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert report.applied == 1 and report.conflicts == 0
    assert any("destination escapes the root" in r["reason"] for r in report.refused)
    assert second.exists() and second.read_bytes() == b"second"
    assert not (outside / "invoice.txt").exists()


def test_destination_appearing_after_policy_check_is_never_overwritten(
        config, tmp_path):
    """BH-A1 (TOCTOU): the no-overwrite rule must hold at syscall time,
    not merely when check_operation ran milliseconds earlier."""
    root = tmp_path / "docs"
    src = aged(root / "invoice.txt", "incoming")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [{"src": src}])
    victim = root / "Finance" / "invoice.txt"

    real_begin = executor.journal.begin

    def begin_then_race(*args, **kwargs):
        op_id = real_begin(*args, **kwargs)
        aged(victim, "victim created after the policy check")
        return op_id

    executor.journal.begin = begin_then_race
    executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert victim.read_bytes() == b"victim created after the policy check"
    assert src.exists() and src.read_bytes() == b"incoming"


def test_cross_device_move_is_copy_verify_mark_then_unlink(
        config, tmp_path, monkeypatch):
    root = tmp_path / "docs"
    src = aged(root / "invoice.txt", "cross-device bytes")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [{"src": src}])
    dst = root / "Finance" / "invoice.txt"

    monkeypatch.setattr(
        "assistant.executor.os.link",
        lambda *_a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    real_mark = executor.journal.mark_copied
    seen = {}

    def mark_and_observe(op_id, sha_after):
        real_mark(op_id, sha_after)
        seen["src_existed_at_copied"] = src.exists()
        seen["dst_existed_at_copied"] = dst.exists()
        seen["status_at_copied"] = store.get_operation(op_id)["status"]
        seen["outstanding_at_copied"] = [o["id"] for o in store.outstanding_intents()]

    executor.journal.mark_copied = mark_and_observe
    report = executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert report.applied == 1 and dst.read_bytes() == b"cross-device bytes"
    assert not src.exists()
    op = store.committed_operations(plan_id=plan_id)[0]
    assert seen == {
        "src_existed_at_copied": True,
        "dst_existed_at_copied": True,
        "status_at_copied": "copied",
        "outstanding_at_copied": [op["id"]],
    }


def test_cross_device_corrupt_copy_never_unlinks_source(
        config, tmp_path, monkeypatch):
    root = tmp_path / "docs"
    src = aged(root / "invoice.txt", "the only good copy")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [{"src": src}])

    monkeypatch.setattr(
        "assistant.executor.os.link",
        lambda *_a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    monkeypatch.setattr(
        "assistant.executor.shutil.copyfileobj",
        lambda _src, dst, length=None: dst.write(b"corrupt copy"))
    report = executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert report.applied == 0
    assert any("destination hash mismatch before source unlink" in r["reason"]
               for r in report.refused)
    assert src.exists() and src.read_bytes() == b"the only good copy"
    assert (root / "Finance" / "invoice.txt").read_bytes() == b"corrupt copy"
    op = store._conn.execute("SELECT * FROM operations").fetchone()
    assert op["status"] == "failed"


def test_schema_valid_llm_output_cannot_escape_with_new_name(config, tmp_path):
    payload = json.dumps(FIXTURES["llm_new_name_traversal"])
    assert _parse_batch(payload, set(TAXONOMY), {"/r/invoice.txt"}) is None

    root = tmp_path / "docs"
    src = aged(root / "invoice.txt", "stay inside the tree")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [
        {"src": src, "dest": "Finance", "new_name": "../../escaped.txt"}])
    executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert src.exists()
    assert not (tmp_path / "escaped.txt").exists()


def test_taxonomy_symlink_cannot_smuggle_file_outside_root(config, tmp_path):
    root = tmp_path / "docs"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True)
    root.mkdir()
    (root / "Finance").symlink_to(outside, target_is_directory=True)
    src = aged(root / "invoice.txt", "do not smuggle")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [{"src": src}])
    executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert src.exists()
    assert not (outside / "invoice.txt").exists()


@pytest.mark.xfail(strict=True, reason="BH-A4: protected paths ignore $VAR expansion")
def test_protected_path_env_var_spelling_is_honoured(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    secret = aged(fake_home / "secret" / "id.txt", "secret")
    monkeypatch.setenv("HOME", str(fake_home))
    assert is_protected(secret, ["$HOME/secret"])


# -- B: crash boundaries / hostile filesystem -------------------------------------

@pytest.mark.xfail(strict=True, reason="BH-B1: intent-phase ops are not undoable/recoverable")
def test_kill_after_move_before_commit_can_be_undone(config, tmp_path):
    root = tmp_path / "docs"
    src = aged(root / "invoice.txt", "moved then process died")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [{"src": src}])

    def die_before_commit(*_args, **_kwargs):
        raise KeyboardInterrupt("simulated kill -9 at commit boundary")

    executor.journal.commit = die_before_commit
    with pytest.raises(KeyboardInterrupt):
        executor.apply_plan(plan_id, spec, allow_tripwire=True)
    moved = root / "Finance" / "invoice.txt"
    assert moved.exists() and not src.exists()
    assert store.outstanding_intents(), "journal must at least be honest"

    fresh = Executor(config, store)  # restart
    undo = fresh.undo(plan_id=plan_id)
    assert undo["undone"] == 1 and src.exists() and not moved.exists()


@pytest.mark.xfail(strict=True, reason="BH-B2: partial cross-device copy is left behind")
def test_disk_full_mid_move_leaves_no_partial_destination(config, tmp_path, monkeypatch):
    root = tmp_path / "docs"
    src = aged(root / "invoice.txt", "complete source")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [{"src": src}])

    def disk_full(_src, dst, length=None):
        dst.write(b"partial-")
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(
        "assistant.executor.os.link",
        lambda *_a: (_ for _ in ()).throw(OSError(errno.EXDEV, "cross-device")))
    monkeypatch.setattr("assistant.executor.shutil.copyfileobj", disk_full)
    executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert src.exists()
    assert not (root / "Finance" / "invoice.txt").exists()


@pytest.mark.xfail(strict=True, reason="BH-B3: unscoped undo unwinds all history")
def test_bare_undo_refuses_without_scope(config, tmp_path):
    root = tmp_path / "docs"
    old = aged(root / "invoice-old.txt", "old plan")
    new = aged(root / "invoice-new.txt", "new plan")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    first = manual_plan(store, root, [{"src": old}])
    executor.apply_plan(first, spec, allow_tripwire=True)
    second = manual_plan(store, root, [{"src": new}])
    executor.apply_plan(second, spec, allow_tripwire=True)

    with pytest.raises(ValueError, match="scope"):
        executor.undo()
    assert (root / "Finance" / "invoice-old.txt").exists()
    assert (root / "Finance" / "invoice-new.txt").exists()


@pytest.mark.xfail(strict=True, reason="BH-B4: broken symlink crashes index_root")
def test_broken_symlink_is_skipped_not_fatal(config, tmp_path):
    root = tmp_path / "docs"
    aged(root / "invoice.txt", "good")
    (root / "dangling.txt").symlink_to(root / "missing-target.txt")
    store, _executor, spec = setup(config, tmp_path, root)
    stats = Indexer(config, store).index_root(spec)
    assert stats["indexed"] >= 1
    assert any("symlink" in key or "broken" in key for key in stats["skipped"])


def _index_fifo(config, spec, db_path: str) -> None:  # child process target
    Indexer(config, Store(Path(db_path))).index_root(spec)


@pytest.mark.xfail(strict=True, reason="BH-B5: FIFO/special file can hang the indexer")
def test_fifo_is_skipped_instead_of_blocking_indexer(config, tmp_path):
    root = tmp_path / "docs"
    aged(root / "invoice.txt", "good")
    os.mkfifo(root / "evil.fifo")
    _store, _executor, spec = setup(config, tmp_path, root)
    proc = multiprocessing.get_context("fork").Process(
        target=_index_fifo, args=(config, spec, str(tmp_path / "fifo.db")))
    proc.start()
    proc.join(timeout=3)
    alive = proc.is_alive()
    if alive:
        proc.terminate()
        proc.join(timeout=3)
    assert not alive, "indexer blocked forever reading a FIFO"


@pytest.mark.xfail(strict=True, reason="BH-B6: never_send flag goes stale on unchanged files")
def test_never_send_added_later_reflags_unchanged_documents(config, tmp_path):
    root = tmp_path / "docs"
    secret = aged(root / "invoice.txt", FIXTURES["secrets"]["never_send_marker"])
    store, _executor, spec = setup(config, tmp_path, root)
    config.raw["privacy"] = {**config.raw["privacy"], "never_send_to_cloud": []}
    index(config, store, spec)
    assert store.document_by_path(str(secret))["never_send"] == 0

    config.raw["privacy"] = {
        **config.raw["privacy"], "never_send_to_cloud": [str(root)]}
    index(config, store, spec)  # file unchanged; flag must still update
    assert store.document_by_path(str(secret))["never_send"] == 1


# -- C: halt / trash ---------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="BH-C1: halt is not re-checked before the syscall")
def test_halt_landing_after_policy_check_prevents_the_move(
        config, tmp_path, monkeypatch):
    root = tmp_path / "docs"
    src = aged(root / "invoice.txt", "halt raced me")
    store, executor, spec = setup(config, tmp_path, root)
    index(config, store, spec)
    plan_id = manual_plan(store, root, [{"src": src}])

    from assistant import safety as safety_module

    real_check = safety_module.check_operation

    def check_then_halt(*args, **kwargs):
        decision = real_check(*args, **kwargs)
        set_halt(executor.runtime)
        return decision

    monkeypatch.setattr("assistant.executor.check_operation", check_then_halt)
    executor.apply_plan(plan_id, spec, allow_tripwire=True)
    assert is_halted(executor.runtime)
    assert src.exists() and not (root / "Finance" / "invoice.txt").exists()


@pytest.mark.xfail(strict=True, reason="BH-C2: trash bypasses protected/halt policy")
def test_trash_refuses_protected_paths_and_halt(config, tmp_path):
    protected_root = tmp_path / "protected"
    doomed = aged(protected_root / "keep.txt", "protected")
    root = tmp_path / "docs"
    aged(root / "invoice.txt", "ordinary")
    _store, executor, _spec = setup(
        config, tmp_path, root, protected=[str(protected_root)])
    set_halt(executor.runtime)
    result = executor.trash(doomed)
    assert doomed.exists()
    assert result["result"] != "applied"
