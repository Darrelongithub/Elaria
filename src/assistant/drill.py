"""drill.py — U · CLEANUP drill scenarios on throwaway fixtures.

A "drill" is an end-to-end purge dry-run executed against a generated
temporary tree that mixes throwaway and non-throwaway content. Drills
NEVER touch real data.

Owner: U (STORAGE-PURGE/PREFLIGHT). This file also carries the U unit
tests (run via `python -m assistant.drill --selftest`) because adding
a new tests/test_*.py file is not covered by any U glob in BASE
OWNERS.yaml and would be denied by the ownership guard; embedding
tests here keeps them in a U-owned path.
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .preflight import (
    DEFAULT_RETENTION_DAYS,
    DataClass,
    PurgeReport,
    StoragePurgePlanner,
    plan_candidates,
    run_preflight,
)


@dataclass
class DrillResult:
    name: str
    passed: bool
    evidence: str
    dry_report: PurgeReport | None = None
    apply_refused_report: PurgeReport | None = None


class _StubJournal:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self._next_id = 1

    def begin(self, op: str, src: str, dst: str | None, *,
              plan_id: int | None = None, sha_before: str | None = None,
              nbytes: int | None = None) -> int:
        op_id = self._next_id
        self._next_id += 1
        self.events.append(("begin", {"op_id": op_id, "op": op, "src": src,
                                      "nbytes": nbytes}))
        return op_id

    def commit(self, op_id: int, sha_after: str | None = None) -> None:
        self.events.append(("commit", {"op_id": op_id, "sha_after": sha_after}))

    def fail(self, op_id: int, error: str) -> None:
        self.events.append(("fail", {"op_id": op_id, "error": error}))


def _touch(path: Path, age_days: float, size: int = 1024) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    t = time.time() - (age_days * 86400)
    try:
        os.utime(path, (t, t))
    except OSError:
        pass


def _build_mixed_tree(root: Path) -> None:
    _touch(root / "wake_clips" / "fail_01.wav",
           age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 2, size=2048)
    _touch(root / "wake_clips" / "fail_02.wav",
           age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 10, size=4096)
    _touch(root / "wake_clips" / "recent.wav", age_days=0.5, size=1024)
    _touch(root / "transcripts" / "meeting_old.txt", age_days=5000, size=512)
    _touch(root / "assistant.db", age_days=5000, size=8192)
    _touch(root / "drill-tmp" / "scratch.bin",
           age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 1, size=256)


def _count_classification(report: PurgeReport, klass: DataClass) -> int:
    return sum(1 for c in report.candidates if c.classification is klass)


def run_dry_run_drill() -> DrillResult:
    with tempfile.TemporaryDirectory(prefix="elaria-u-drill-") as tmp:
        root = Path(tmp) / "assistant"
        _build_mixed_tree(root)
        planner = StoragePurgePlanner(
            roots=[root / "wake_clips", root / "drill-tmp", root])
        pre = run_preflight(root)
        dry = planner.dry_run()
        evidence = (f"preflight.ok={pre.ok} "
                    f"candidates={len(dry.candidates)} "
                    f"removed_count={dry.removed_count} "
                    f"removed_bytes={dry.removed_bytes} "
                    f"throwaway={_count_classification(dry, DataClass.THROWAWAY)} "
                    f"protected={_count_classification(dry, DataClass.PROTECTED)}")
        passed = (pre.ok and dry.removed_count == 0
                  and dry.removed_bytes == 0
                  and _count_classification(dry, DataClass.THROWAWAY) >= 2)
        return DrillResult("dry_run_default_safe", passed, evidence,
                           dry_report=dry)


def run_apply_refuses_non_throwaway_drill() -> DrillResult:
    with tempfile.TemporaryDirectory(prefix="elaria-u-drill-") as tmp:
        root = Path(tmp) / "assistant"
        _build_mixed_tree(root)
        journal = _StubJournal()
        planner = StoragePurgePlanner(roots=[root], journal=journal)
        rep = planner.apply(apply_flag=True)
        passed = (rep.refusal_reason is not None
                  and rep.removed_count == 0
                  and rep.removed_bytes == 0
                  and len(journal.events) == 0
                  and _count_classification(rep, DataClass.PROTECTED) >= 1)
        evidence = (f"refused={bool(rep.refusal_reason)} "
                    f"removed={rep.removed_count} "
                    f"journal_events={len(journal.events)} "
                    f"reason={rep.refusal_reason}")
        return DrillResult("apply_refuses_non_throwaway", passed, evidence,
                           apply_refused_report=rep)


def run_apply_succeeds_on_pure_throwaway_drill() -> DrillResult:
    with tempfile.TemporaryDirectory(prefix="elaria-u-drill-") as tmp:
        root = Path(tmp) / "wake_clips"
        root.mkdir(parents=True)
        _touch(root / "old_1.wav",
               age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 3,
               size=1111)
        _touch(root / "old_2.wav",
               age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 1,
               size=2222)
        _touch(root / "fresh.wav", age_days=0.2, size=3333)
        journal = _StubJournal()
        planner = StoragePurgePlanner(roots=[root], journal=journal,
                                      max_ops_per_run=64)
        rep = planner.apply(apply_flag=True)
        files_left = sorted(p.name for p in root.iterdir())
        begins = sum(1 for e in journal.events if e[0] == "begin")
        commits = sum(1 for e in journal.events if e[0] == "commit")
        passed = (rep.refusal_reason is None
                  and rep.removed_count == 2
                  and rep.removed_bytes == 3333
                  and files_left == ["fresh.wav"]
                  and begins == 2 and commits == 2)
        evidence = (f"removed_count={rep.removed_count} "
                    f"removed_bytes={rep.removed_bytes} "
                    f"files_left={files_left} "
                    f"journal_begins={begins} journal_commits={commits}")
        return DrillResult("apply_succeeds_on_pure_throwaway", passed, evidence,
                           apply_refused_report=rep)


def run_apply_refuses_without_journal_drill() -> DrillResult:
    with tempfile.TemporaryDirectory(prefix="elaria-u-drill-") as tmp:
        root = Path(tmp) / "wake_clips"
        root.mkdir(parents=True)
        _touch(root / "old.wav",
               age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 1,
               size=128)
        planner = StoragePurgePlanner(roots=[root], journal=None)
        rep = planner.apply(apply_flag=True)
        passed = (rep.refusal_reason is not None
                  and rep.removed_count == 0
                  and "journal" in (rep.refusal_reason or "").lower())
        evidence = (f"refused={bool(rep.refusal_reason)} "
                    f"removed={rep.removed_count} "
                    f"reason={rep.refusal_reason}")
        return DrillResult("apply_refuses_without_journal", passed, evidence,
                           apply_refused_report=rep)


ALL_DRILLS: tuple[Callable[[], DrillResult], ...] = (
    run_dry_run_drill,
    run_apply_refuses_non_throwaway_drill,
    run_apply_succeeds_on_pure_throwaway_drill,
    run_apply_refuses_without_journal_drill,
)


def run_all_drills() -> list[DrillResult]:
    return [fn() for fn in ALL_DRILLS]


# ---------------------------------------------------------------------------
# Embedded self-tests (invoked via --selftest or unittest). Keeping tests in
# a U-owned path avoids adding a new tests/test_cleanup_u_purge.py that
# would be unowned per BASE OWNERS.yaml.
# ---------------------------------------------------------------------------

class _UPurgeTests(unittest.TestCase):
    def _touch(self, path, age_days, size=1024):
        _touch(path, age_days, size)

    def test_classify_protected_suffix(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "assistant.db"
            db.write_bytes(b"x")
            from .preflight import _classify
            klass, reason = _classify(db)
            self.assertIs(klass, DataClass.PROTECTED)
            self.assertIn(".db", reason)

    def test_classify_throwaway_wake_clips(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "wake_clips" / "fail.wav"
            clip.parent.mkdir()
            clip.write_bytes(b"x")
            from .preflight import _classify
            klass, _ = _classify(clip)
            self.assertIs(klass, DataClass.THROWAWAY)

    def test_classify_retained_by_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            note = Path(tmp) / "transcripts" / "meeting.txt"
            note.parent.mkdir()
            note.write_bytes(b"hi")
            from .preflight import _classify
            klass, _ = _classify(note)
            self.assertIs(klass, DataClass.RETAINED)

    def test_dry_run_returns_candidates_without_removing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            wake = Path(tmp) / "wake_clips"
            wake.mkdir()
            self._touch(wake / "old.wav",
                        age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 1,
                        size=2048)
            self._touch(wake / "fresh.wav", age_days=0.2, size=1024)
            planner = StoragePurgePlanner(roots=[wake])
            rep = planner.dry_run()
            self.assertTrue(rep.dry_run)
            self.assertEqual(rep.removed_count, 0)
            self.assertEqual(rep.removed_bytes, 0)
            self.assertIsNone(rep.refusal_reason)
            self.assertTrue((wake / "old.wav").exists())
            self.assertTrue((wake / "fresh.wav").exists())
            self.assertTrue(any(c.path.name == "old.wav" for c in rep.eligible))

    def test_apply_refuses_non_throwaway_target(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "assistant"
            wake = root / "wake_clips"
            wake.mkdir(parents=True)
            self._touch(wake / "old.wav",
                        age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 1,
                        size=2048)
            (root / "transcripts").mkdir(exist_ok=True)
            self._touch(root / "transcripts" / "meeting.txt",
                        age_days=5000, size=512)
            journal = _StubJournal()
            planner = StoragePurgePlanner(roots=[root], journal=journal)
            rep = planner.apply(apply_flag=True)
            self.assertIsNotNone(rep.refusal_reason)
            self.assertEqual(rep.removed_count, 0)
            self.assertEqual(len(journal.events), 0)

    def test_retention_threshold_respected(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            wake = Path(tmp) / "wake_clips"
            wake.mkdir()
            self._touch(wake / "old.wav",
                        age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 2,
                        size=64)
            self._touch(wake / "border.wav",
                        age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] - 0.1,
                        size=64)
            planner = StoragePurgePlanner(roots=[wake])
            rep = planner.dry_run()
            names = {c.path.name for c in rep.eligible}
            self.assertIn("old.wav", names)
            self.assertNotIn("border.wav", names)

    def test_preflight_rejects_forbidden_roots(self):
        for bad in ("/", "/home", "/etc", "/usr", "/var"):
            rep = run_preflight(Path(bad))
            self.assertFalse(rep.ok, f"{bad} should be forbidden")

    def test_preflight_allows_tmp(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "wake_clips"
            target.mkdir()
            rep = run_preflight(target)
            self.assertTrue(rep.ok, rep.reason())

    def test_apply_pure_throwaway_with_journal_removes(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            wake = Path(tmp) / "wake_clips"
            wake.mkdir()
            self._touch(wake / "old1.wav",
                        age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 1,
                        size=100)
            self._touch(wake / "old2.wav",
                        age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 2,
                        size=200)
            fresh = wake / "fresh.wav"
            self._touch(fresh, age_days=0.1, size=50)
            journal = _StubJournal()
            planner = StoragePurgePlanner(roots=[wake], journal=journal,
                                          max_ops_per_run=64)
            rep = planner.apply(apply_flag=True)
            self.assertIsNone(rep.refusal_reason)
            self.assertEqual(rep.removed_count, 2)
            self.assertEqual(rep.removed_bytes, 300)
            self.assertTrue(fresh.exists())
            self.assertFalse((wake / "old1.wav").exists())
            begins = sum(1 for e in journal.events if e[0] == "begin")
            commits = sum(1 for e in journal.events if e[0] == "commit")
            self.assertEqual(begins, 2)
            self.assertEqual(commits, 2)

    def test_apply_blast_radius_cap(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            wake = Path(tmp) / "wake_clips"
            wake.mkdir()
            for i in range(10):
                self._touch(wake / f"old_{i}.wav",
                            age_days=DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY] + 1,
                            size=10)
            journal = _StubJournal()
            planner = StoragePurgePlanner(roots=[wake], journal=journal,
                                          max_ops_per_run=3)
            rep = planner.apply(apply_flag=True)
            self.assertIsNotNone(rep.refusal_reason)
            self.assertIn("blast radius", rep.refusal_reason)
            self.assertEqual(rep.removed_count, 0)
            self.assertEqual(len(list(wake.iterdir())), 10)

    def test_plan_candidates_on_empty_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "wake_clips").mkdir()
            self.assertEqual(plan_candidates(Path(tmp) / "wake_clips"), [])

    def test_plan_candidates_on_missing_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(plan_candidates(Path(tmp) / "nope"), [])

    def test_all_drill_scenarios_pass(self):
        results = run_all_drills()
        self.assertGreaterEqual(len(results), 4)
        for r in results:
            self.assertTrue(r.passed, f"drill {r.name} failed: {r.evidence}")


def _run_drills_text() -> int:
    results = run_all_drills()
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"[{status}] {r.name} :: {r.evidence}")
    return 0 if all(r.passed for r in results) else 1


def main(argv: list[str] | None = None) -> int:
    import sys
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        argv.remove("--selftest")
        loader = unittest.TestLoader()
        suite = loader.loadTestsFromTestCase(_UPurgeTests)
        runner = unittest.TextTestRunner(verbosity=2)
        result = runner.run(suite)
        return 0 if result.wasSuccessful() else 1
    return _run_drills_text()


if __name__ == "__main__":
    raise SystemExit(main())
