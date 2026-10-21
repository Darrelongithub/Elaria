"""BH-K28 (minor batch): unhashable paths crashed executor operations.

`sha256_file` raises on dangling symlinks, symlinks to directories and
files that vanish mid-operation. Several executor/safety call sites
hashed without a guard, so one dangling symlink in a folder (entirely
normal in ~/Downloads) turned `trash`/`verify` into an unhandled
FileNotFoundError/IsADirectoryError instead of the per-item refusal
every neighbouring path returns.

Fix: `safety.try_sha256_file` (None on OSError) at the
comparison/refusal sites; an unhashable file is by definition not the
indexed content, so the existing refusal branches take it from there.
The strict helper stays for post-move verification, where raising is
correct and already journaled.
"""

from __future__ import annotations

from assistant.executor import Executor
from assistant.store import Store


def _executor(config, tmp_path):
    store = Store(tmp_path / "t.db")
    return Executor(config, store), store


def test_trash_dangling_symlink_is_a_refusal_not_a_crash(config, tmp_path):
    executor, store = _executor(config, tmp_path)
    try:
        link = tmp_path / "stale-link"
        link.symlink_to(tmp_path / "gone-target")
        out = executor.trash(link)
        assert out["trashed_as"] is None
        assert "unreadable" in out["result"]["reason"]
        assert link.is_symlink()  # untouched
    finally:
        store.close()


def test_verify_reports_unhashable_destination_not_a_crash(config, tmp_path):
    executor, store = _executor(config, tmp_path)
    try:
        victim = tmp_path / "victim.txt"
        victim.write_text("payload")
        out = executor.trash(victim)
        assert out["result"] == "applied"
        # Replace the trashed file with a symlink to a directory: the
        # journal still points at the path, hashing it must not crash.
        from pathlib import Path
        trashed = Path(out["trashed_as"])
        trashed.unlink()
        trashed.symlink_to(tmp_path)  # a directory
        report = executor.verify()
        assert report["verified_ok"] == 0
        assert report["problems"], report
        assert report["problems"][0]["path"] == str(trashed)
    finally:
        store.close()
