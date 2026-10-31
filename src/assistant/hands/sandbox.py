"""Minted temporary workspace; no caller-provided real-tree mutation root.

The ONLY file mutation implementation is assistant.executor.Executor. This
adapter creates synthetic organiser plan rows, not a competing move/trash
algorithm. Live actor/taxonomy/broker integration remains held.
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from assistant.cost import iso_now
from assistant.executor import Executor
from assistant.safety import assert_within_sandbox, check_blast_radius, check_operation, sha256_file
from assistant.store import Store


class _FixtureConfig:
    def __init__(self, space):
        self.data_dir = space.control
        self.socket_path = space.control / "synthetic.sock"

    def section(self, name):
        return {"policy": {"protected": [str(self.data_dir)],
                           "recently_modified_guard_minutes": 15},
                "organise": {"max_ops_per_run": 200, "max_ops_per_hour": 500,
                             "tree_tripwire_pct": 25}}.get(name, {})


class _ExactDestinationExecutor(Executor):
    """Reuse the whole library; disable ONLY its implicit destination rewrite.

    The signed plan must name the actual destination. A late collision returns
    a refusal; a separate resolve_collision plan names an explicit new path.
    """

    def _to_conflicts(self, item, src, root, plan_id, sha, *, report=None):
        return {"src": str(src), "reason": "destination changed; exact-path re-plan required"}


class SyntheticSpace:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="elaria-hands-synthetic-")
        self.root = Path(self._tmp.name)
        self.work = self.root / "work"
        self.control = self.root / "control"
        self.work.mkdir(mode=0o700)
        self.control.mkdir(mode=0o700)
        self.store = Store(self.control / "store.db")
        self.executor = _ExactDestinationExecutor(_FixtureConfig(self), self.store)

    def seed(self, relative: str, content: str, *, age_s: float = 3600) -> Path:
        """Test-only fixture creation, not an executor tool. Never exposed to plans."""
        path = assert_within_sandbox(self.work / relative, self.work)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
        self.index(path)
        return path

    def index(self, path: Path):
        path = assert_within_sandbox(path, self.work)
        stat = path.stat()
        return self.store.upsert_document(
            path=str(path), root=str(self.work), sha256=sha256_file(path), size=stat.st_size,
            mtime=stat.st_mtime, mime="text/plain", ext=path.suffix, indexed_ts=iso_now(),
            never_send=True, text_chunks=[])

    def move(self, src: Path, dst: Path) -> dict:
        src = assert_within_sandbox(src, self.work)
        dst = assert_within_sandbox(dst, self.work)
        doc = self.store.document_by_path(str(src))
        if doc is None:
            raise PermissionError("unindexed source")
        folder = str(dst.parent.relative_to(self.work))
        if folder == ".":
            raise PermissionError("synthetic organiser adapter needs a destination subfolder")
        spec = {"path": str(self.work), "mode": "live", "taxonomy": [folder]}
        pid = self.store.create_plan(iso_now(), str(self.work), "live")
        self.store.add_plan_items(pid, [{"doc_id": doc["id"], "src": str(src), "dest": folder,
            "new_name": dst.name, "confidence": 1.0, "tier": 0, "rule": "hands-synthetic",
            "reason": "synthetic operation", "decision": "auto"}])
        self.store.finish_plan(pid, total=1, placed=1, abstained=0, shadow_log_path=None,
                               stats_json="{}")
        report = self.executor.apply_plan(pid, spec, sandbox_root=self.work)
        # No allow_tripwire, include_review or safety override.
        return {"applied": report.applied, "conflicts": report.conflicts,
                "op_ids": tuple(report.op_ids), "refused": bool(report.refused),
                "capped": report.capped, "halted": report.halted}

    def trash(self, src: Path) -> dict:
        from datetime import UTC, datetime, timedelta

        src = assert_within_sandbox(src, self.work)
        # Compose the existing gate/cap primitives, not a second lock or trash
        # implementation. The library trash call re-enters the held gate.
        with self.executor._operation_gate():
            blast = check_blast_radius(1, len(self.store.documents_in_root(str(self.work))),
                max_ops_per_run=self.executor.max_per_run, tripwire_pct=self.executor.tripwire_pct)
            since = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            if not blast.allowed or self.store.ops_since(since) >= self.executor.max_per_hour:
                raise PermissionError("synthetic trash cap reached")
            decision = check_operation("trash", src, None, protected=self.executor.protected,
                                       recent_guard_minutes=self.executor.recent_guard)
            doc = self.store.document_by_path(str(src))
            if not decision.allowed or doc is None or doc["sha256"] != sha256_file(src):
                raise PermissionError("trash source changed or outside policy")
            return self.executor.trash(src)

    def close(self):
        self.store.close()
        self._tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
