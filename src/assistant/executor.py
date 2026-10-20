"""Executor (§3.7/§4) — the ONLY module allowed to move user files.

Phase 4. Every write passes the full safety spine, in this order:
  1. Root must be mode=live in config — the owner's explicit flip after
     shadow logs they agreed with (§4.3). Shadow roots are refused here,
     in code, not by convention.
  2. Halt flag checked BEFORE every single op (§4.4: one keypress,
     honoured within one file operation).
  3. File identity re-verified against the index (sha256/size/mtime):
     changed since indexing → refuse + report, never act (§4.1).
  4. Policy check (protected paths, never-overwrite, recent-guard §4.1).
  5. Blast-radius caps: max ops per run / per hour (§4.4).
  6. Write-ahead intent row → syscall → sha256 verify → commit (§4.2).
     A crash between intent and commit is recoverable: daemon startup
     already reports outstanding intents.

There is no `rm` in this module and no overwrite. Deletes (there are
none in filing) would be trash-with-manifest. Collisions with different
content route the incoming file to `_Conflicts/` — journaled, visible,
reversible. Undo (below) reverses committed ops in reverse order and
is itself journaled, so undo is undoable.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .cost import iso_now
from .safety import (
    Journal,
    assert_within_sandbox,
    check_blast_radius,
    check_operation,
    is_halted,
    is_safe_filename,
    sha256_file,
)


@dataclass
class ApplyReport:
    plan_id: int
    applied: int = 0
    conflicts: int = 0
    skipped: int = 0
    refused: list[dict] = field(default_factory=list)
    halted: bool = False
    capped: bool = False
    op_ids: list[int] = field(default_factory=list)


class Executor:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        self.journal = Journal(store)
        organise = config.section("organise")
        policy = config.section("policy")
        self.protected = policy.get("protected") or []
        self.recent_guard = int(policy.get("recently_modified_guard_minutes", 15))
        self.max_per_run = int(organise.get("max_ops_per_run", 200))
        self.max_per_hour = int(organise.get("max_ops_per_hour", 500))
        self.tripwire_pct = int(organise.get("tree_tripwire_pct", 25))
        self.trash_dir = config.data_dir / "trash"
        self.runtime = config.socket_path.parent

    # -- public -----------------------------------------------------------------
    def apply_plan(self, plan_id: int, root_spec: dict, *,
                   include_review: bool = False,
                   allow_tripwire: bool = False,
                   sandbox_root: Path | None = None) -> ApplyReport:
        """Apply a ready plan's auto items (+ approved review items).

        `allow_tripwire` is the owner's explicit 'yes, move >25% of my
        tree' — the structural pause-and-ask (§4.4) made a parameter."""
        if root_spec.get("mode") != "live":
            raise PermissionError(
                f"root {root_spec['path']} is mode={root_spec.get('mode')!r}, not "
                "'live'. Shadow first (§4.3): read the shadow logs, then flip "
                "the root to live in config.toml yourself — deliberately.")
        plan = self.store.get_plan(plan_id)
        if plan is None or plan["status"] != "ready":
            raise ValueError(f"plan {plan_id} is not ready to apply")
        root = Path(root_spec["path"])
        if sandbox_root is not None:
            # Show-off mode: the demo may only ever act inside its own folder,
            # checked here (before any read of plan items) and again per op.
            assert_within_sandbox(root, sandbox_root)
        items = [i for i in self.store.plan_items(plan_id)
                 if i["decision"] == "auto"
                 or (include_review and i["decision"] == "review")]
        items = [i for i in items if i["dest"]]
        report = ApplyReport(plan_id=plan_id)

        total_indexed = len(self.store.documents_in_root(str(root)))
        blast = check_blast_radius(len(items), total_indexed,
                                   max_ops_per_run=self.max_per_run,
                                   tripwire_pct=self.tripwire_pct)
        if not blast.allowed and not allow_tripwire:
            report.refused.append({"reason": blast.reason,
                                   "hint": "pass allow_tripwire after reading the plan"})
            report.capped = True
            return report
        hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        hourly_budget = self.max_per_hour - self.store.ops_since(hour_ago)

        for item in items:
            if is_halted(self.runtime):
                report.halted = True
                break
            if report.applied + report.conflicts >= self.max_per_run or hourly_budget <= 0:
                report.capped = True
                break
            outcome = self._apply_item(item, root, plan_id,
                                       sandbox_root=sandbox_root)
            if outcome == "applied":
                report.applied += 1
                hourly_budget -= 1
            elif outcome == "conflict":
                report.conflicts += 1
                hourly_budget -= 1
            elif isinstance(outcome, dict):
                report.refused.append(outcome)
            else:
                report.skipped += 1
        if report.applied or report.conflicts:
            self.store.set_plan_status(plan_id, "applied")
        return report

    @staticmethod
    def assert_demo_path(path: str | Path, sandbox_root: str | Path) -> Path:
        """Public face of the demo guard, for callers before they plan."""
        return assert_within_sandbox(path, sandbox_root)

    # -- one op, fully journaled --------------------------------------------------
    @staticmethod
    def _copy_file_no_overwrite(src: Path, dst: Path) -> None:
        """Exclusive-create copy for the cross-device path. `xb` makes a
        destination that raced us a hard failure, never an overwrite."""
        with src.open("rb") as source, dst.open("xb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
            target.flush()
            os.fsync(target.fileno())
        shutil.copystat(src, dst)

    @classmethod
    def _create_destination_no_overwrite(cls, src: Path, dst: Path) -> str:
        """Create dst without clobbering anything; DO NOT unlink src here.

        Returns the placement kind (`link`, `symlink`, or `copy`). Keeping
        creation separate lets `_journaled_move` hash-verify the new
        destination before the explicitly journaled source-unlink step.
        Same-filesystem regular files use link(2), which is atomic and
        fails if dst appeared after the policy check (BH-A1) — safer than
        rename(2), whose POSIX semantics silently replace an existing dst.
        """
        if os.path.lexists(dst):
            raise FileExistsError(f"destination appeared after policy check: {dst}")
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
            return "symlink"
        if not src.is_file():
            raise OSError(f"refusing to move non-regular file: {src}")
        try:
            os.link(src, dst)
            return "link"
        except OSError as exc:
            if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EMLINK,
                                 errno.EOPNOTSUPP):
                raise
        cls._copy_file_no_overwrite(src, dst)
        return "copy"

    def _apply_item(self, item: dict, root: Path, plan_id: int,
                    *, sandbox_root: Path | None = None):
        src = Path(item["src"])
        new_name = item["new_name"] or src.name
        # Defence in depth: the executor is the last line before a syscall,
        # so it re-validates plan data even if a planner/verifier was fooled.
        # new_name must be a bare filename and dest a relative taxonomy path;
        # the resolved destination must stay inside the resolved root.
        if not is_safe_filename(new_name):
            return {"src": str(src),
                    "reason": f"unsafe new_name {new_name!r} — not a bare filename"}
        dest_value = item["dest"]
        dest_parts = Path(dest_value).parts if isinstance(dest_value, str) else ()
        if (not isinstance(dest_value, str) or Path(dest_value).is_absolute()
                or not dest_parts
                or any(part in ("", ".", "..") or "\\" in part for part in dest_parts)):
            return {"src": str(src),
                    "reason": f"unsafe destination folder {dest_value!r}"}
        dest_dir = root / dest_value
        dst = dest_dir / new_name
        if sandbox_root is not None:
            assert_within_sandbox(src, sandbox_root)
            assert_within_sandbox(dst, sandbox_root)
        root_resolved = root.resolve()
        dst_resolved = dst.resolve()
        if root_resolved != dst_resolved and root_resolved not in dst_resolved.parents:
            return {"src": str(src),
                    "reason": f"destination escapes the root: {dst_resolved}"}

        # Already in place (verify-only proposal): nothing to do, honestly.
        if src.resolve() == dst_resolved:
            return "skipped"
        if not src.exists():
            return {"src": str(src), "reason": "source vanished since planning — re-index"}

        # Identity: never act on a changed/unindexed file (§4.1).
        doc = self.store.document_by_path(str(src))
        if doc is None or doc["status"] != "indexed":
            return {"src": str(src), "reason": "unindexed or stale — refused, re-index first"}
        current_hash = sha256_file(src)
        if current_hash != doc["sha256"] or src.stat().st_size != doc["size"]:
            return {"src": str(src),
                    "reason": "file changed since indexing (sha256/size) — refused (§4.1)"}

        decision = check_operation("move", src, dst, protected=self.protected,
                                   recent_guard_minutes=self.recent_guard)
        if decision.action == "conflict":
            return self._to_conflicts(item, src, root, plan_id, current_hash)
        if not decision.allowed:
            return {"src": str(src), "reason": decision.reason}

        return self._journaled_move(src, dst, plan_id, current_hash)

    def _journaled_move(self, src: Path, dst: Path, plan_id: int | None,
                        sha_before: str, *, op: str = "move") -> str:
        dst.parent.mkdir(parents=True, exist_ok=True)
        # lstat (not stat) so a symlink journals its own size, not its target's.
        op_id = self.journal.begin(op, str(src), str(dst), plan_id=plan_id,
                                   sha_before=sha_before, nbytes=src.lstat().st_size)
        try:
            placement = self._create_destination_no_overwrite(src, dst)
            sha_after = sha256_file(dst)
            if sha_after != sha_before:
                self.journal.fail(
                    op_id,
                    "sha256 mismatch after destination creation — source kept; "
                    "destination left for inspection, NOT deleted")
                return {"src": str(src),
                        "reason": "destination hash mismatch before source unlink "
                                  f"(journal op {op_id}); inspect {dst}"}
            if placement == "copy":
                # Explicit phase boundary (§4.2): copied + verified, source
                # still present. A crash here is an outstanding intent with
                # two complete copies — never zero.
                self.journal.mark_copied(op_id, sha_after)
            src.unlink()
            self.journal.commit(op_id, sha_after=sha_after)
            return "applied"
        except Exception as exc:
            self.journal.fail(op_id, f"{type(exc).__name__}: {exc}")
            return {"src": str(src), "reason": str(exc)}

    def _to_conflicts(self, item, src: Path, root: Path, plan_id: int, sha: str) -> str:
        conflicts = root / "_Conflicts"
        candidate = conflicts / src.name
        counter = 2
        while os.path.lexists(candidate):  # never overwrite, even in _Conflicts
            candidate = conflicts / f"{src.stem} ({counter}){src.suffix}"
            counter += 1
        # A _Conflicts symlink must not become a second escape hatch.
        if root.resolve() not in candidate.resolve().parents:
            return {"src": str(src),
                    "reason": "_Conflicts route refused: destination escapes the root: "
                              f"{candidate.resolve()}"}
        # The conflicts route is still a write: it passes the same policy
        # spine as the original destination (protected + recent-guard),
        # rather than inheriting the earlier check on a different path.
        decision = check_operation(
            "move", src, candidate, protected=self.protected,
            recent_guard_minutes=self.recent_guard)
        if not decision.allowed:
            return {"src": str(src),
                    "reason": f"_Conflicts route refused: {decision.reason}"}
        result = self._journaled_move(src, candidate, plan_id, sha)
        return "conflict" if result == "applied" else result

    # -- trash (the only 'delete' shape allowed) ----------------------------------
    def trash(self, path: Path, *, plan_id: int | None = None) -> dict:
        """Move to assistant trash with a manifest. Nothing is ever rm'd."""
        path = Path(path)
        self.trash_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        dest = self.trash_dir / f"{stamp}-{path.name}"
        sha = sha256_file(path)
        result = self._journaled_move(path, dest, plan_id, sha, op="trash")
        manifest = self.trash_dir / "manifest.jsonl"
        with manifest.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": iso_now(), "original": str(path),
                                     "trashed_as": str(dest), "sha256": sha,
                                     "result": result}) + "\n")
        return {"trashed_as": str(dest), "result": result, "manifest": str(manifest)}

    # -- undo: journaled reversal, itself undoable (§4.2) ----------------------------
    def undo(self, *, op_id: int | None = None, plan_id: int | None = None,
             since_iso: str | None = None) -> dict:
        if op_id is not None:
            op = self.store.get_operation(op_id)
            operations = [op] if op and op["status"] == "committed" else []
        else:
            operations = self.store.committed_operations(
                plan_id=plan_id, since_iso=since_iso)
        undone, problems = 0, []
        for op in reversed(operations):  # reverse order, like unwinding a stack
            if is_halted(self.runtime):
                problems.append({"reason": "halted mid-undo — remaining ops untouched"})
                break
            src, dst = Path(op["dst"]), Path(op["src"])  # swap: dst is current home
            if not src.exists():
                problems.append({"op": op["id"], "reason": f"{src} no longer exists"})
                continue
            if op["sha256_after"] and sha256_file(src) != op["sha256_after"]:
                problems.append({"op": op["id"],
                                 "reason": "content changed since the op — undo "
                                           "refused rather than clobber your edits"})
                continue
            if dst.exists() and sha256_file(dst) != (op["sha256_after"] or ""):
                problems.append({"op": op["id"],
                                 "reason": f"original location {dst} now occupied "
                                           "by different content — refused"})
                continue
            # Reuse the one journaled move path: create + verify destination
            # first, only then unlink the current home (cross-device safe).
            result = self._journaled_move(
                src, dst, op["plan_id"], op["sha256_after"] or sha256_file(src),
                op=op["op"])
            if result == "applied":
                self.store.mark_rolled_back(op["id"])
                undone += 1
            else:
                problems.append({
                    "op": op["id"],
                    "reason": result["reason"] if isinstance(result, dict) else str(result)})
        return {"undone": undone, "problems": problems,
                "note": "undo is itself journaled — undoing the undo is possible"}

    def verify(self, *, since_iso: str | None = None) -> dict:
        """Re-walk committed destinations; hashes must match the journal."""
        ok, bad = 0, []
        for op in self.store.committed_operations(since_iso=since_iso):
            dst = Path(op["dst"])
            if not dst.exists():
                bad.append({"op": op["id"], "path": str(dst), "reason": "missing"})
            elif op["sha256_after"] and sha256_file(dst) != op["sha256_after"]:
                bad.append({"op": op["id"], "path": str(dst), "reason": "hash drift"})
            else:
                ok += 1
        return {"verified_ok": ok, "problems": bad}


def parse_since(spec: str) -> str:
    """'2h' / '24h' / '7d' / ISO-8601 → ISO-8601 UTC (for undo --since)."""
    spec = spec.strip()
    now = datetime.now(UTC)
    if spec.endswith("h") and spec[:-1].isdigit():
        return (now - timedelta(hours=int(spec[:-1]))).isoformat()
    if spec.endswith("d") and spec[:-1].isdigit():
        return (now - timedelta(days=int(spec[:-1]))).isoformat()
    if spec.endswith("m") and spec[:-1].isdigit():
        return (now - timedelta(minutes=int(spec[:-1]))).isoformat()
    return datetime.fromisoformat(spec).isoformat()
