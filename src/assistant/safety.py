"""Safety spine primitives (§4) — policy + journal + halt, from Phase 0.

The executor arrives in Phase 4, but the *rules* exist now so nothing
later has to retrofit them: never overwrite, never `rm`, never touch
protected paths or recently-modified files, write-ahead intent before
any syscall, and a halt flag honoured between operations.

Phase 0 ships the policy checks, the journal writers and the halt flag,
all pure/local. Nothing in this module moves a file.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .cost import iso_now
from .store import Store


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    action: str = "allow"  # allow | deny | conflict (both files -> _Conflicts/)


def expand(path: str | Path) -> Path:
    return Path(path).expanduser()


def assert_within_sandbox(path: str | Path, sandbox_root: str | Path) -> Path:
    """The demo-sandbox choke point (§19.3).

    Show-off demonstrations may act ONLY inside the designated demo folder. The
    executor calls this before any syscall in sandbox mode, so a real user path
    is refused at the last line of defence — not by prompt or convention.
    """
    resolved = Path(path).expanduser().resolve()
    root = Path(sandbox_root).expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        raise PermissionError(
            f"demo sandbox refused: {resolved} is outside {root}. Show-off "
            "demonstrations act only on the demo folder; real paths are never "
            "touched (§19.3).")
    return resolved


def is_safe_filename(value: object) -> bool:
    """A model/plan-supplied name must be ONE filename, never a path.

    Reject separators and dot-segments outright rather than silently
    taking ``Path(value).name``: a hostile ``../../x`` or absolute path
    is a failed verification, not a rename to ``x``.
    """
    return (
        isinstance(value, str)
        and value not in ("", ".", "..")
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and Path(value).name == value
    )


def is_protected(path: str | Path, protected: list[str]) -> bool:
    target = expand(path).resolve()
    for entry in protected:
        root = expand(entry).resolve()
        if target == root or root in target.parents:
            return True
    return False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_operation(
    op: str,
    src: str | Path,
    dst: str | Path | None,
    *,
    protected: list[str],
    recent_guard_minutes: int = 15,
    now: float | None = None,
) -> PolicyDecision:
    """Validate one proposed op against §4.1. Pure checks; no writes."""
    if op == "delete":
        return PolicyDecision(False, "there is no rm — use op 'trash' (§4.1)", "deny")
    source = expand(src)
    if is_protected(source, protected):
        return PolicyDecision(False, f"protected path: {source}", "deny")
    if dst is not None and is_protected(dst, protected):
        return PolicyDecision(False, f"protected destination: {expand(dst)}", "deny")
    if source.exists():
        age_s = (now or time.time()) - source.stat().st_mtime
        if age_s < recent_guard_minutes * 60:
            return PolicyDecision(
                False,
                f"modified {age_s:.0f}s ago — inside the {recent_guard_minutes}min "
                "guard window (§4.1); refuse and re-index later",
                "deny",
            )
    if dst is not None:
        dest = expand(dst)
        if dest.exists():
            # Never overwrite. Identical content is a no-op duplicate;
            # different content sends both to _Conflicts/ (§4.1).
            if source.exists() and sha256_file(source) == sha256_file(dest):
                return PolicyDecision(False, "destination already holds identical content", "deny")
            return PolicyDecision(
                False,
                "destination exists with different content — both go to _Conflicts/, "
                "never overwrite (§4.1)",
                "conflict",
            )
    return PolicyDecision(True, "within policy")


def check_blast_radius(planned_ops: int, tree_size: int, *, max_ops_per_run: int,
                       tripwire_pct: int) -> PolicyDecision:
    """Structural tripwire (§4.4): a runaway classifier looks exactly like
    a legitimate big cleanup until you check the numbers."""
    if planned_ops > max_ops_per_run:
        return PolicyDecision(
            False, f"plan has {planned_ops} ops, cap is {max_ops_per_run} per run (§4.4)", "deny"
        )
    if tree_size > 0 and (planned_ops / tree_size) * 100 > tripwire_pct:
        return PolicyDecision(
            False,
            f"plan would move {planned_ops}/{tree_size} files "
            f"({planned_ops / tree_size * 100:.0f}% > {tripwire_pct}% tripwire) — pause and ask (§4.4)",
            "deny",
        )
    return PolicyDecision(True, "blast radius within caps")


class Journal:
    """Write-ahead intent (§4.2): the row lands BEFORE the syscall."""

    def __init__(self, store: Store):
        self._store = store

    def begin(self, op: str, src: str, dst: str | None, *, plan_id: int | None = None,
              sha_before: str | None = None, nbytes: int | None = None) -> int:
        with self._store._lock:  # same-process store; keeps journal atomic with ledger
            cur = self._store._conn.execute(
                "INSERT INTO operations (plan_id, ts, op, src, dst, sha256_before, bytes, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'intent')",
                (plan_id, iso_now(), op, src, dst, sha_before, nbytes),
            )
            self._store._conn.commit()
            return int(cur.lastrowid)

    def _set_status(self, op_id: int, status: str, *, sha_after: str | None = None,
                    error: str | None = None) -> None:
        with self._store._lock:
            self._store._conn.execute(
                "UPDATE operations SET status = ?, sha256_after = COALESCE(?, sha256_after), "
                "error = ? WHERE id = ?",
                (status, sha_after, error, op_id),
            )
            self._store._conn.commit()

    def mark_copied(self, op_id: int, sha_after: str) -> None:
        """Cross-device phase boundary: destination bytes exist and have
        been hash-verified, but the source name has not been unlinked yet.
        This remains an outstanding intent until `commit`."""
        self._set_status(op_id, "copied", sha_after=sha_after)

    def commit(self, op_id: int, sha_after: str | None = None) -> None:
        self._set_status(op_id, "committed", sha_after=sha_after)

    def fail(self, op_id: int, error: str) -> None:
        self._set_status(op_id, "failed", error=error)


# -- halt flag (§4.4: panic must be one keypress, honoured within one op) ----
def halt_path(runtime: Path) -> Path:
    return runtime / "assistant.halt"


def set_halt(runtime: Path) -> Path:
    runtime.mkdir(parents=True, exist_ok=True)
    path = halt_path(runtime)
    path.write_text(iso_now() + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def clear_halt(runtime: Path) -> None:
    halt_path(runtime).unlink(missing_ok=True)


def is_halted(runtime: Path) -> bool:
    return halt_path(runtime).exists()
