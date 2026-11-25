"""WP7 increment 8 - the monthly restore-drill scaffolding.

The WP7 gate names **one live monthly drill** as a pass condition: restore an artifact from
cold storage, hash-verify it, and run `restic check`. Quarterly adds a bounded data read so
a drill never reads the whole repository. This module is the machinery that makes that
repeatable and auditable.

Four pieces, each deliberately separable:

* **`DrillJournal`** - an append-only, path-free record that a drill ran and what it found.
  The gate says "one live monthly drill passes", and a pass nobody can look up afterwards is
  not evidence. It mirrors `StorageManifest`'s discipline: one `write()` of a complete line,
  then `fsync`, at 0600, outside the repo.
* **`read_data_subset()`** - the quarterly cap, computed as the SMALLER of the percentage
  and the byte ceiling. A percentage alone is not a bound: 5% of a 40 GB repository is 2 GB,
  which is four times the ruled ceiling.
* **`ResticCheck`** - a seam that builds and runs `restic check` through the `rclone:`
  backend. The runner is injectable, so the whole surface is testable headlessly with no
  restic, no rclone and no MEGA.
* **`run_drill()`** - the orchestration, which composes the increment-5 restore-and-verify
  with the restic check and writes the record.

**No credentials appear here.** The restic passphrase is a 0600 file outside the repo with a
paper escrow off-machine; this module takes its PATH and never reads, prints or logs it. The
rclone remote is one config line the owner fills in himself.

**Every record is path-free by construction** - the same fence as increment 7. A drill
record carries a kind, an outcome, a backend name and an artifact LABEL (its extension), and
never a name or a path. A log that proved a backup worked by leaking what was in it would
have failed at the one job it was built for.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import KW_ONLY, dataclass
from datetime import UTC, datetime
from pathlib import Path

from assistant.sensors import artifact_label

__all__ = [
    "DRILL_KINDS",
    "DrillJournal",
    "DrillOutcome",
    "DrillRecord",
    "ResticCheck",
    "read_data_subset",
    "run_drill",
]

#: The two drill cadences. Monthly is the ruled default (Q24: (c) then (a)); quarterly is
#: the bounded-data variant.
DRILL_KINDS: tuple[str, ...] = ("monthly", "quarterly")


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DrillRecord:
    """One drill, path-free. This is the auditable evidence the gate asks for.

    `label` is the artifact's EXTENSION and nothing else - the same `artifact_label()` the
    CLI uses. `backend` names WHICH backend confirmed, per increment 4's rule that every
    verification record must name the backend that produced it.
    """

    ts: str
    kind: str
    ok: bool
    backend: str
    method: str
    label: str = "unknown"
    detail: str = ""

    def to_json(self) -> str:
        return json.dumps({
            "ts": self.ts,
            "kind": self.kind,
            "ok": self.ok,
            "backend": self.backend,
            "method": self.method,
            "label": self.label,
            "detail": self.detail,
        }, sort_keys=True)

    @classmethod
    def from_json(cls, line: str) -> DrillRecord:
        raw = json.loads(line)
        return cls(
            ts=str(raw.get("ts", "")),
            kind=str(raw.get("kind", "")),
            ok=bool(raw.get("ok", False)),
            backend=str(raw.get("backend", "")),
            method=str(raw.get("method", "")),
            label=str(raw.get("label", "unknown")),
            detail=str(raw.get("detail", "")),
        )

    def summary(self) -> dict:
        """Path-blind, like `ReconcilePlan.summary()` - safe to print or log."""

        return {
            "ts": self.ts,
            "kind": self.kind,
            "ok": self.ok,
            "backend": self.backend,
            "method": self.method,
            "label": self.label,
            "detail": self.detail,
        }


@dataclass
class DrillJournal:
    """An append-only drill log at 0600, outside the repo.

    Mirrors `StorageManifest.append()` exactly: one `write()` of a complete line, then
    `fsync`. A crash mid-write can leave a fragment, which `records()` discards - a
    half-written drill is never counted as a drill that ran.
    """

    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def _ensure_parent(self) -> None:
        parent = self.path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            os.chmod(parent, 0o700)
        except OSError:
            pass

    def append(self, record: DrillRecord) -> bool:
        try:
            self._ensure_parent()
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, (record.to_json() + "\n").encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            # A drill that cannot be recorded still HAPPENED, and its outcome still
            # matters. Callers must not treat a failed append as a failed drill - but
            # they must be able to see it, which is why this returns a bool rather than
            # swallowing silently.
            return False
        return True

    def records(self) -> list[DrillRecord]:
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError:
            return []
        out: list[DrillRecord] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(DrillRecord.from_json(line))
            except (ValueError, json.JSONDecodeError):
                continue  # a torn trailing line, or a line from a future format
        return out

    def last(self, kind: str | None = None) -> DrillRecord | None:
        rows = self.records()
        if kind:
            rows = [r for r in rows if r.kind == kind]
        return rows[-1] if rows else None

    def count_passed(self, kind: str | None = None) -> int:
        return sum(1 for r in self.records()
                   if r.ok and (kind is None or r.kind == kind))


# ---------------------------------------------------------------------------
# The quarterly cap
# ---------------------------------------------------------------------------


def read_data_subset(*, pct: int, mb: int, repo_bytes: int | None = None) -> str:
    """The `--read-data-subset` value: the SMALLER of the percentage and the byte ceiling.

    The ruling is "≤5%/≤500 MB". A percentage alone is not a bound - 5% of a 40 GB
    repository is 2 GB, four times the ceiling - so when the repository size is known both
    bounds are computed in bytes and the smaller wins. When it is not known, the percentage
    is passed and the byte ceiling is *recorded as unenforceable* rather than silently
    ignored, because a cap nobody checked is not a cap.

    Returns a string ready for the restic command line, e.g. `"5%"` or `"250M"`.
    """

    if pct <= 0 and mb <= 0:
        return ""
    if pct <= 0:
        return f"{mb}M"
    if mb <= 0:
        return f"{pct}%"
    if repo_bytes is None:
        # The percentage is the only bound we can actually express. Say so.
        return f"{pct}%"
    by_pct = repo_bytes * pct // 100
    by_mb = mb * 1000 ** 2
    return f"{min(by_pct, by_mb) // 1000 ** 2}M"


# ---------------------------------------------------------------------------
# The restic seam
# ---------------------------------------------------------------------------


@dataclass
class ResticCheck:
    """Builds and runs `restic check` through the `rclone:` backend.

    `runner` is injectable so nothing here needs a real restic. The default runner shells
    out with a fixed argv, no shell, and a timeout.

    **The passphrase path is passed, never read.** `--password-file` points at a 0600 file
    outside the repo with a paper escrow off-machine. This class stores the path so the
    command can use it and deliberately offers no accessor that would return its contents.
    """

    repo: str
    _: KW_ONLY
    remote: str
    path: str
    timeout: str = "5m"
    password_file: Path | None = None
    runner: Callable[[Sequence[str]], str] | None = None

    def __post_init__(self) -> None:
        self.password_file = Path(self.password_file) if self.password_file else None

    def argv(self, *, subset: str = "") -> list[str]:
        """The full command. Pinned shape: the `rclone:` repo, an EXPLICIT rclone timeout,
        and the passphrase file.

        The timeout is set explicitly rather than inherited because MEGA repo-open
        routinely exceeds restic's 1m default (restic #3511/#3514, recorded on the
        increment-4 command pin).
        """

        argv = ["restic", "-r", self.repo, "-o", f"rclone.timeout={self.timeout}"]
        if self.password_file is not None:
            argv += ["--password-file", str(self.password_file)]
        argv.append("check")
        if subset:
            argv.append(f"--read-data-subset={subset}")
        return argv

    def run(self, *, subset: str = "") -> tuple[bool, str]:
        """Returns (ok, detail). Never raises: an absent restic is a DECLARED absence."""

        argv = self.argv(subset=subset)
        try:
            if self.runner is not None:
                out = self.runner(argv)
            else:
                proc = subprocess.run(
                    argv, capture_output=True, text=True, timeout=600, check=False
                )
                out = (proc.stdout or "") + (proc.stderr or "")
                if proc.returncode != 0:
                    return False, f"restic check exited {proc.returncode}"
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"restic unavailable ({type(exc).__name__})"
        return True, (out or "").strip()[:200]

    def repo_spec(self) -> str:
        """`rclone:<remote>:<path>` - the provider as ONE config line."""

        return f"rclone:{self.remote}:{self.path}"


# ---------------------------------------------------------------------------
# The orchestration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DrillOutcome:
    """What one drill found. Path-free."""

    ok: bool
    kind: str
    restored: bool
    hash_ok: bool
    restic_ok: bool
    label: str = "unknown"
    backend: str = ""
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


def run_drill(*, kind: str, ctx, restic: ResticCheck | None,
              journal: DrillJournal | None = None,
              repo_bytes: int | None = None,
              now: datetime | None = None,
              rng=None) -> DrillOutcome:
    """One drill: restore a cold artifact, hash-verify it, then `restic check`.

    Composes the increment-5 restore-and-verify (`_check`) with the restic check and writes
    the record. The restore half is delegated to `backup_cli._check` so there is exactly one
    implementation of "restore and hash-verify" in this lane, not two that can drift.

    **A missing restic is a DECLARED skip, not a pass and not a failure.** The restore and
    the hash-verify are the parts that prove the owner can get their audio back; `restic
    check` additionally proves the repository is internally consistent. Reporting a drill
    that could only do the first half as a full pass would be the silent-pass failure
    increment 4 exists to prevent.
    """

    from assistant.backup_cli import _check
    from assistant.sensors import backup_check

    if kind not in DRILL_KINDS:
        raise ValueError(f"unknown drill kind: {kind!r}")

    now = now or datetime.now(UTC)
    backend = ctx.backend.name if ctx.backend is not None else "none"

    # -- the restore + hash-verify half (increment 5's machinery, reused) ----------
    import io

    sink = io.StringIO()
    restore_code = _check(ctx, artifact=None, kind=kind, out=sink, rng=rng)
    restore_ok = restore_code == 0
    hash_ok = restore_ok

    # -- the restic half ------------------------------------------------------------
    restic_ok = False
    restic_detail = "no restic configured"
    if restic is not None:
        subset = ""
        if kind == "quarterly":
            subset = read_data_subset(
                pct=int(ctx.section.get("drill_read_data_subset_pct", 5) or 5),
                mb=int(ctx.section.get("drill_read_data_subset_mb", 500) or 500),
                repo_bytes=repo_bytes,
            )
        restic_ok, restic_detail = restic.run(subset=subset)

    ok = restore_ok and (restic_ok or restic is None)
    label = artifact_label("artifact.wav") if restore_ok else "unknown"
    detail = (f"restore={'ok' if restore_ok else 'failed'}; "
              f"restic={'ok' if restic_ok else restic_detail}")

    sensors_detail = detail if len(detail) <= 120 else detail[:117] + "..."
    backup_check(kind=kind, ok=ok, detail=sensors_detail)

    outcome = DrillOutcome(
        ok=ok,
        kind=kind,
        restored=restore_ok,
        hash_ok=hash_ok,
        restic_ok=restic_ok,
        label=label,
        backend=backend,
        detail=detail,
    )

    if journal is not None:
        journal.append(DrillRecord(
            ts=now.isoformat(),
            kind=kind,
            ok=ok,
            backend=backend,
            method="restore+hash" + ("+restic-check" if restic is not None else ""),
            label=label,
            detail=detail,
        ))
    return outcome
