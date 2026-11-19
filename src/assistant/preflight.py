"""preflight.py — U · CLEANUP pre-run guards + purge policy.

Before any storage purge runs (even dry-run), we must prove we are NOT
pointed at a real user data root by mistake. Each check here is a
fail-closed gate; any failure returns a PreflightReport with refusal
details and zero deletions.

This module ALSO houses the purge policy itself (DataClass,
PurgeCandidate, PurgeReport, StoragePurgePlanner, plan_candidates,
load_purge_planner). The policy lives here rather than in cleanup.py
because, per the BASE OWNERS.yaml on origin/main, cleanup.py is owned
by the D (SAFETY) cluster and U must not modify it.  All purge code is
self-contained in U-owned modules (this file + drill.py) until/unless
ownership is reassigned via an OWNERS.yaml change by Z.

Owner: U (STORAGE-PURGE/PREFLIGHT). Does NOT touch store.py / config.py /
daemon.py — those are Z-owned; this module reads the environment +
filesystem only.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ---------------------------------------------------------------------------
# Preflight report types (declared up top so purge policy and gates both
# reference the same classes).
# ---------------------------------------------------------------------------

@dataclass
class PreflightCheck:
    name: str
    passed: bool
    detail: str


@dataclass
class PreflightReport:
    ok: bool
    root_checked: Path
    checks: list[PreflightCheck] = field(default_factory=list)

    def reason(self) -> str | None:
        failed = [c for c in self.checks if not c.passed]
        if not failed:
            return None
        return "; ".join(f"{c.name}: {c.detail}" for c in failed)


# ---------------------------------------------------------------------------
# Data classification
# ---------------------------------------------------------------------------

class DataClass(str, Enum):
    """Lifecycle classification for purge candidates.

    Only THROWAWAY may ever be deleted --apply. Everything else is
    listed-but-refused so the operator can see what's accumulating
    without any risk of real loss.
    """

    THROWAWAY = "throwaway"        # generated/transient — eligible for purge
    RETAINED = "retained"          # user data — never touched by purge
    PROTECTED = "protected"        # config / weights / journal — immune
    UNKNOWN = "unknown"            # unclassified -> refused fail-closed


# Canonical name globs + classification for known throwaway roots.
THROWAWAY_GLOBS: dict[str, DataClass] = {
    "/wake_clips/": DataClass.THROWAWAY,
    "/benchmark-tmp/": DataClass.THROWAWAY,
    "/audition_candidates/": DataClass.THROWAWAY,
    "core.": DataClass.THROWAWAY,
    "/drill-tmp/": DataClass.THROWAWAY,
    ".sock": DataClass.THROWAWAY,
    ".pid": DataClass.THROWAWAY,
}

PROTECTED_DIR_NAMES = {"config", "models", "voiceprints", ".ssh", ".gnupg"}
PROTECTED_FILE_SUFFIXES = {".db", ".db-wal", ".db-shm", ".toml", ".key", ".pem"}


@dataclass(frozen=True)
class PurgeCandidate:
    path: Path
    size_bytes: int
    age_days: float
    classification: DataClass
    reason: str

    @property
    def eligible_for_apply(self) -> bool:
        return self.classification is DataClass.THROWAWAY


@dataclass
class PurgeReport:
    dry_run: bool
    root_scanned: Path
    retention_days: float
    candidates: list[PurgeCandidate] = field(default_factory=list)
    removed_count: int = 0
    removed_bytes: int = 0
    refusal_reason: str | None = None
    journal_entries: list[int] = field(default_factory=list)

    @property
    def eligible(self) -> list[PurgeCandidate]:
        return [c for c in self.candidates if c.eligible_for_apply]

    @property
    def refused_count(self) -> int:
        return len(self.candidates) - len(self.eligible)

    @property
    def eligible_bytes(self) -> int:
        return sum(c.size_bytes for c in self.eligible)

    def summary(self) -> str:
        mode = "DRY-RUN" if self.dry_run else (
            "REFUSED" if self.refusal_reason else "APPLIED")
        lines = [
            (f"[purge] mode={mode} root={self.root_scanned} "
             f"retention_days={self.retention_days}"),
            (f"[purge] candidates={len(self.candidates)} "
             f"eligible={len(self.eligible)} refused={self.refused_count} "
             f"eligible_bytes={self.eligible_bytes}"),
        ]
        if self.refusal_reason:
            lines.append(f"[purge] REFUSED: {self.refusal_reason}")
        if not self.dry_run and not self.refusal_reason:
            lines.append(f"[purge] removed_count={self.removed_count} "
                         f"removed_bytes={self.removed_bytes}")
        for c in self.eligible[:20]:
            lines.append(f"  - {c.path}  ({c.size_bytes} B, {c.age_days:.1f}d, "
                         f"{c.reason})")
        return "\n".join(lines)


DEFAULT_RETENTION_DAYS = {
    DataClass.THROWAWAY: 7.0,
    DataClass.RETAINED: 3650.0,
    DataClass.PROTECTED: 3650.0,
    DataClass.UNKNOWN: 3650.0,
}


def _classify(path: Path) -> tuple[DataClass, str]:
    sp = str(path)
    if path.suffix in PROTECTED_FILE_SUFFIXES:
        return DataClass.PROTECTED, f"protected suffix {path.suffix}"
    parts_lower = {p.lower() for p in path.parts}
    for name in PROTECTED_DIR_NAMES:
        if name in parts_lower:
            return DataClass.PROTECTED, f"protected directory segment '{name}'"
    sp_lower = sp.lower()
    for needle, klass in THROWAWAY_GLOBS.items():
        if needle in sp_lower:
            return klass, f"matches throwaway pattern {needle!r}"
    if path.name.startswith(".") and path.name.count(".") >= 2:
        return DataClass.THROWAWAY, "dotfile temp"
    return DataClass.RETAINED, "default retained (user content)"


def _age_days(path: Path, now: float) -> float:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0.0
    return max(0.0, (now - mtime) / 86400.0)


def _iter_tree(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
        dirnames.sort()
        for name in sorted(filenames):
            yield Path(dirpath) / name


def _safe_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def plan_candidates(root: Path, *,
                    retention_overrides: dict[DataClass, float] | None = None,
                    now: float | None = None) -> list[PurgeCandidate]:
    retention = dict(DEFAULT_RETENTION_DAYS)
    if retention_overrides:
        for k, v in retention_overrides.items():
            retention[k] = float(v)
    t = now if now is not None else time.time()
    root = Path(root).expanduser()
    out: list[PurgeCandidate] = []
    for p in _iter_tree(root):
        klass, reason = _classify(p)
        age = _age_days(p, t)
        threshold = retention.get(klass, DEFAULT_RETENTION_DAYS[DataClass.UNKNOWN])
        if age < threshold:
            continue
        out.append(PurgeCandidate(
            path=p,
            size_bytes=_safe_size(p),
            age_days=age,
            classification=klass,
            reason=reason,
        ))
    return out


class StoragePurgePlanner:
    """Dry-run-first planner/executor for storage cleanup.

    Default mode: dry_run returns the candidate list and NEVER removes
    anything. apply() REFUSES unless:
      (a) apply_flag is True;
      (b) every candidate under roots is THROWAWAY;
      (c) a journal is supplied so the removals are attributable
          (IF-5 / D-safety journal).

    Note: until HR-U-1 lands (Z-owned store.py deletion seam), apply()
    uses os.unlink on filesystem files under explicitly-provided
    THROWAWAY-classified roots. No DB mutation. No touching store.py.
    """

    def __init__(self, roots: Iterable[Path], *,
                 retention_overrides: dict[DataClass, float] | None = None,
                 max_ops_per_run: int = 512,
                 journal: object | None = None):
        self.roots = [Path(r).expanduser() for r in roots]
        self.retention_overrides = retention_overrides or {}
        self.max_ops_per_run = int(max_ops_per_run)
        self._journal = journal

    def _effective_throwaway_retention(self) -> float:
        return self.retention_overrides.get(
            DataClass.THROWAWAY, DEFAULT_RETENTION_DAYS[DataClass.THROWAWAY])

    def dry_run(self, *, now: float | None = None) -> PurgeReport:
        candidates: list[PurgeCandidate] = []
        for root in self.roots:
            candidates.extend(plan_candidates(
                root, retention_overrides=self.retention_overrides, now=now))
        primary_root = self.roots[0] if self.roots else Path(".")
        report = PurgeReport(
            dry_run=True,
            root_scanned=primary_root,
            retention_days=self._effective_throwaway_retention(),
            candidates=candidates,
        )
        assert report.removed_count == 0 and report.removed_bytes == 0, \
            "dry-run invariant broken: non-zero removals"
        return report

    def apply(self, *, apply_flag: bool = False,
              now: float | None = None) -> PurgeReport:
        if not apply_flag:
            return self.dry_run(now=now)
        if self._journal is None:
            rep = self.dry_run(now=now)
            rep.dry_run = False
            rep.refusal_reason = (
                "no journal supplied; deletions must be attributable via D")
            return rep
        candidates: list[PurgeCandidate] = []
        for root in self.roots:
            candidates.extend(plan_candidates(
                root, retention_overrides=self.retention_overrides, now=now))
        non_throwaway = [c for c in candidates if not c.eligible_for_apply]
        if non_throwaway:
            return PurgeReport(
                dry_run=False,
                root_scanned=self.roots[0] if self.roots else Path("."),
                retention_days=self._effective_throwaway_retention(),
                candidates=candidates,
                refusal_reason=(
                    f"{len(non_throwaway)} non-throwaway candidate(s) in "
                    "scope; refusing to apply (fail-closed). First "
                    f"offender: {non_throwaway[0].path} "
                    f"({non_throwaway[0].classification.value})"),
            )
        if len(candidates) > self.max_ops_per_run:
            return PurgeReport(
                dry_run=False,
                root_scanned=self.roots[0] if self.roots else Path("."),
                retention_days=self._effective_throwaway_retention(),
                candidates=candidates,
                refusal_reason=(
                    f"blast radius {len(candidates)} > max_ops_per_run="
                    f"{self.max_ops_per_run}; refusing (raise the cap "
                    "explicitly if intended)"),
            )
        report = PurgeReport(
            dry_run=False,
            root_scanned=self.roots[0] if self.roots else Path("."),
            retention_days=self._effective_throwaway_retention(),
            candidates=candidates,
        )
        for cand in candidates:
            op_id = self._journal.begin(
                op="purge", src=str(cand.path), dst=None,
                nbytes=cand.size_bytes)
            try:
                cand.path.unlink()
                report.removed_count += 1
                report.removed_bytes += cand.size_bytes
                report.journal_entries.append(op_id)
                self._journal.commit(op_id)
            except OSError as exc:
                self._journal.fail(op_id, str(exc))
        return report


def load_purge_planner(config, *, journal=None) -> StoragePurgePlanner:
    """Build a planner from the live Config object.

    Reads [storage_purge] section (authored by Z via HR-U-1 when
    integrated; falls back to defaults here so U builds and tests
    against stable semantics).
    """
    section: dict = {}
    try:
        section = dict(config.section("storage_purge") or {})
    except Exception:
        section = {}
    xdg_data = os.environ.get(
        "XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    roots = section.get("roots") or [
        str(Path(xdg_data) / "assistant" / "wake_clips"),
        str(Path(xdg_data) / "assistant" / "audition_candidates"),
        os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
    ]
    overrides: dict[DataClass, float] = {}
    try:
        v = float(section.get("throwaway_retention_days"))
        overrides[DataClass.THROWAWAY] = v
    except (TypeError, ValueError):
        pass
    try:
        v = float(section.get("retained_retention_days"))
        overrides[DataClass.RETAINED] = v
    except (TypeError, ValueError):
        pass
    return StoragePurgePlanner(
        roots=roots,
        retention_overrides=overrides,
        max_ops_per_run=int(section.get("max_ops_per_run", 512)),
        journal=journal,
    )


# ---------------------------------------------------------------------------
# Preflight gates
# ---------------------------------------------------------------------------

FORBIDDEN_ROOTS = {
    "/", "/home", "/root", "/etc", "/usr", "/bin", "/sbin",
    "/opt", "/boot", "/proc", "/sys", "/dev", "/var",
}
_FORBIDDEN_EXCEPTIONS_PREFIXES = ("/var/tmp/",)


def _is_under_forbidden(root: Path) -> bool:
    try:
        resolved = root.resolve()
    except OSError:
        resolved = root
    s = str(resolved)
    for prefix in _FORBIDDEN_EXCEPTIONS_PREFIXES:
        if s.startswith(prefix) or s == prefix.rstrip("/"):
            return False
    for bad in FORBIDDEN_ROOTS:
        bad_clean = bad.rstrip("/")
        if not bad_clean:
            if s == "/":
                return True
            continue
        if s == bad_clean or s.startswith(bad_clean + "/"):
            return True
    home = Path(os.path.expanduser("~")).resolve()
    return resolved == home


def _looks_like_assistant_data_root(root: Path) -> tuple[bool, str]:
    known_throwaway_leaves = {
        "wake_clips", "audition_candidates", "benchmark-tmp", "drill-tmp"}
    if not root.exists():
        return True, "path does not exist yet (scratch-ready)"
    if not root.is_dir():
        return False, "root is not a directory"
    if root.name in known_throwaway_leaves:
        return True, f"known throwaway leaf '{root.name}'"
    parts = {p for p in root.parts}
    if "assistant" in parts:
        return True, "contains 'assistant' path segment"
    if os.environ.get("XDG_RUNTIME_DIR") and \
            str(root).startswith(os.environ["XDG_RUNTIME_DIR"]):
        return True, "under XDG_RUNTIME_DIR (transient by contract)"
    return False, "root not recognized as throwaway/assistant-scoped"


def run_preflight(root: Path) -> PreflightReport:
    """Run all preflight checks for a candidate purge root."""
    root = Path(root).expanduser()
    report = PreflightReport(ok=False, root_checked=root, checks=[])

    report.checks.append(PreflightCheck(
        name="root_not_forbidden",
        passed=not _is_under_forbidden(root),
        detail=("root is under a system-critical or $HOME path"
                if _is_under_forbidden(root) else "root is scoped"),
    ))
    report.checks.append(PreflightCheck(
        name="root_is_absolute",
        passed=root.is_absolute(),
        detail="absolute path" if root.is_absolute() else "relative path",
    ))
    shape_ok, shape_detail = _looks_like_assistant_data_root(root)
    report.checks.append(PreflightCheck(
        name="root_shape_safe", passed=shape_ok, detail=shape_detail))
    symlink_safe, symlink_detail = True, "no symlink escape"
    try:
        resolved = root.resolve(strict=False)
        if _is_under_forbidden(resolved):
            symlink_safe = False
            symlink_detail = f"resolves to forbidden path {resolved}"
    except OSError as exc:
        symlink_safe = False
        symlink_detail = f"unresolvable ({exc}); refusing"
    report.checks.append(PreflightCheck(
        name="no_symlink_escape", passed=symlink_safe, detail=symlink_detail))

    report.ok = all(c.passed for c in report.checks)
    return report
