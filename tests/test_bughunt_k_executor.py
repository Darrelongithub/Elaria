"""BH-K15/K16/K17 — executor journal integrity under concurrency & crashes.

K15: nothing serialised Executor operations across processes. The daemon
    (plan.apply in a thread) and a concurrent CLI invocation read the same
    hourly budget (ops_since) before either journaled, double-spending the
    cap, and could race the same plan. A non-blocking cross-process gate
    now refuses the second runner outright.
K16: Executor.trash used a second-resolution destination name and
    reported `trashed_as` (and wrote it to the manifest) even when the
    journaled move had FAILED (e.g. a same-second same-name collision) —
    claiming a file was in trash while it sat untouched at the origin.
K17: undo of a `copied` op (crash between copy-verify and source unlink:
    both copies exist, identical) fell into _journaled_move, whose
    no-overwrite correctly refused — surfacing a misleading FileExists
    problem instead of reconciling the duplicate.
"""

from __future__ import annotations

import fcntl
from pathlib import Path

import pytest

from assistant.executor import Executor, sha256_file
from assistant.store import Store


def _executor(config, tmp_path):
    store = Store(tmp_path / "t.db")
    return Executor(config, store), store


# ---------------------------------------------------------------------------
# BH-K15
# ---------------------------------------------------------------------------

def test_executor_refuses_to_race_another_process(config, tmp_path):
    executor, store = _executor(config, tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me")
    lock_path = store.db_path.with_name(store.db_path.name + ".executor.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="in progress"):
            executor.trash(victim)
    assert victim.exists(), "a refused operation must not have moved anything"
    # And once the gate is free the same operation proceeds.
    out = executor.trash(victim)
    assert out["result"] == "applied" and out["trashed_as"]
    assert not victim.exists()
    store.close()


# ---------------------------------------------------------------------------
# BH-K16
# ---------------------------------------------------------------------------

def test_trash_same_name_twice_both_land_and_report_truly(config, tmp_path):
    executor, store = _executor(config, tmp_path)
    try:
        src = tmp_path / "report.txt"
        src.write_text("first")
        one = executor.trash(src)
        src.write_text("second")  # same name, immediately (same second)
        two = executor.trash(src)
        assert one["result"] == "applied" and two["result"] == "applied"
        assert one["trashed_as"] != two["trashed_as"], (
            "same-second same-name trash must uniquify, not collide")
        assert Path(one["trashed_as"]).read_text() == "first"
        assert Path(two["trashed_as"]).read_text() == "second"
        assert not src.exists()
    finally:
        store.close()


# ---------------------------------------------------------------------------
# BH-K17
# ---------------------------------------------------------------------------

def test_undo_of_copied_op_reconciles_identical_duplicate(config, tmp_path):
    executor, store = _executor(config, tmp_path)
    try:
        original = tmp_path / "invoice.txt"
        moved = tmp_path / "Finance" / "invoice.txt"
        moved.parent.mkdir()
        content = "invoice due"
        original.write_text(content)
        moved.write_text(content)  # crash after copy-verify, before unlink
        sha = sha256_file(original)
        op_id = executor.journal.begin(
            "move", str(original), str(moved), plan_id=None,
            sha_before=sha, nbytes=len(content))
        executor.journal.mark_copied(op_id, sha)
        assert store.get_operation(op_id)["status"] == "copied"

        out = executor.undo(op_id=op_id)
        assert out["problems"] == [], out
        assert out["undone"] == 1
        assert original.read_text() == content, "the original location keeps the bytes"
        assert not moved.exists(), "the duplicate is retired, exactly once"
        assert store.get_operation(op_id)["status"] == "rolled_back"
        # The duplicate went through the journaled trash (recoverable),
        # it was not silently unlinked.
        trash_ops = [o for o in store.committed_operations()
                     if o["op"] == "trash" and o["src"] == str(moved)]
        assert len(trash_ops) == 1
    finally:
        store.close()
