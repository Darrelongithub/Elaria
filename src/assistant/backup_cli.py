"""WP7 cold storage & backup — the `assist backup` command surface (increment 5).

Four actions, each a thin shell over modules that already exist and are already tested:

- `status` — the manifest summary and the storage gauge. Path-blind.
- `fetch <artifact>` — the cold read path: manifest lookup, restore, hash-verify.
- `run` — one backup pass: tier, plan, reconcile.
- `check` — the integrity-drill shape: restore a cold artifact to a temp dir and
  hash-verify it.

**Every edge is injected.** The manifest, the remote verifier, the trim and purge movers,
the restorer and the clock are all parameters with defaults, which is what lets the whole
command surface run against synthetic fixtures with no restic, no rclone and no MEGA — and
what stops it reaching for a network it has no business reaching on its own. This is the
same discipline `backup.py` established, carried to the CLI.

**The cold read path refuses rather than guesses.** `fetch` on an artifact that was never
uploaded is a refusal with an exit code, not an attempt to find something that is not
there. A restore whose hash does not match the manifest is a failure, not a warning.

PRIVACY FENCE (report 006 §6): the journal never receives a path. Terminal output does
name the artifact, because the owner typed it and needs to know where the copy landed —
but that is the owner's own screen, not a log line, a sensor, a report, a PR or a chat
message.

Evidence tags: `[TESTED-ONLY]`. Nothing here contacts a network in the sandbox.
"""

from __future__ import annotations

import random
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from . import sensors
from .backup import plan_reconcile, reconcile_all
from .remote import LocalPathBackend, Verification, make_verifier
from .storage import StorageManifest
from .tiering import (
    DEFAULT_WINDOW_DAYS,
    DEFAULT_WINDOW_GB,
    scan,
)

__all__ = [
    "BackupContext",
    "LocalPathRestorer",
    "Restorer",
    "backup_command",
    "build_context",
]

#: States from which an artifact may be fetched cold: the remote holds it.
_COLD_STATES = frozenset({"flipped", "trashed", "purged"})


class Restorer(Protocol):
    """Puts a copy of an artifact back on local disk. `name` is its provenance."""

    name: str

    def restore(self, artifact: Path, dest: Path) -> Path:
        ...


class LocalPathRestorer:
    """The fixture restorer, over `LocalPathBackend`. Says so in its name."""

    name = "local-path-fixture"

    def __init__(self, backend: LocalPathBackend, *, name: str | None = None):
        self.backend = backend
        if name is not None:
            self.name = name

    def restore(self, artifact: Path, dest: Path) -> Path:
        stored = self.backend.root / Path(artifact).name
        if not stored.exists():
            raise FileNotFoundError("artifact not present in the fixture remote")
        dest.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.copy2(stored, dest)
        return dest


class BackupContext:
    """Everything a backup command needs, with nothing it must not have.

    The defaults build a context that talks to no remote at all: an empty manifest, a
    fixture verifier, no movers, and the real clock. A caller that wants a real run
    supplies a `RcloneBackend`-backed verifier and real movers.
    """

    def __init__(self, manifest: StorageManifest, *, data_dir: Path | None = None,
                 verifier: Callable[[Path], Verification] | None = None,
                 trim_mover=None, purge_mover=None,
                 restorer: Restorer | None = None,
                 remote_free_bytes: int | None = None,
                 now=None, window_days: int = DEFAULT_WINDOW_DAYS,
                 window_gb: int = DEFAULT_WINDOW_GB,
                 floor_bytes: int = 10 * 1000 ** 3,
                 grace_days: int = 14,
                 section: dict | None = None, backend=None):
        self.manifest = manifest
        self.data_dir = Path(data_dir) if data_dir else Path(".")
        self.verifier = verifier
        self.trim_mover = trim_mover
        self.purge_mover = purge_mover
        self.restorer = restorer
        self.remote_free_bytes = remote_free_bytes
        self.now = now
        self.window_days = window_days
        self.window_gb = window_gb
        self.floor_bytes = floor_bytes
        self.grace_days = grace_days
        # The `[backup]` section this context was built from, and the backend standing
        # behind `verifier`. The ladder chain needs both: one to say whether a remote
        # is configured, the other to name WHICH backend would confirm. A context that
        # cannot say which backend it trusts cannot be probed for provenance.
        self.section = dict(section) if section else {}
        self._backend = backend

    @property
    def remote_configured(self) -> bool:
        return bool((self.section.get("rclone_remote") or "").strip())

    @property
    def backend(self):
        """The backend behind `verifier`, or None when there is none to name.

        Public because a caller probing provenance has every right to ask which backend
        a context trusts without reaching into a private attribute.
        """

        return self._backend

    def verifier_backend(self):
        """The backend behind `verifier`. Retained as a method for the ladder's call."""

        return self._backend

    # -- construction -------------------------------------------------------------------

    @classmethod
    def fixture(cls, root: Path, *, data_dir: Path | None = None,
                now=None) -> BackupContext:
        """A context backed entirely by local fixtures. No remote is contacted."""

        backend = LocalPathBackend(root / "remote")
        return cls(
            StorageManifest(root / "backup" / "manifest.jsonl"),
            data_dir=data_dir or root,
            verifier=make_verifier(backend),
            # The backend is passed explicitly, not just the verifier built from it.
            # Without it the ladder's rung C cannot say WHICH backend would confirm,
            # and provenance — the thing increment 4 exists for — silently vanishes.
            backend=backend,
            restorer=LocalPathRestorer(backend),
            now=now,
        )

    def with_remote_free(self, value: int | None) -> BackupContext:
        self.remote_free_bytes = value
        return self

    # -- derived ------------------------------------------------------------------------

    def gauge(self):
        return sensors.gauge_from_manifest(
            self.manifest, floor_bytes=self.floor_bytes,
            window_days=self.window_days, window_gb=self.window_gb,
            remote_free_bytes=self.remote_free_bytes)


def build_context(config, *, now=None) -> BackupContext:
    """Build a context from the live config. Talks to no remote until told to.

    `rclone_remote` empty means not configured yet, and the verifier is left `None` —
    which is the no-verifier posture `plan_reconcile` already refuses to flip without.
    Guessing a remote would be worse than having none.
    """

    section = config.section("backup")
    manifest = StorageManifest(config.data_dir / "backup" / "manifest.jsonl")
    remote = (section.get("rclone_remote") or "").strip()
    verifier = None
    backend = None
    if remote:
        from .remote import RcloneBackend

        backend = RcloneBackend(remote, path=section.get("rclone_path") or "")
        verifier = make_verifier(backend)
    return BackupContext(
        manifest,
        data_dir=config.data_dir,
        verifier=verifier,
        backend=backend,
        section=section,
        now=now,
        window_days=int(section.get("hot_window_days", DEFAULT_WINDOW_DAYS)),
        window_gb=int(section.get("hot_window_gb", DEFAULT_WINDOW_GB)),
        floor_bytes=int(section.get("capacity_floor_gb", 10)) * 1000 ** 3,
        grace_days=int(section.get("trim_grace_days", 14)),
    )


# --------------------------------------------------------------------------------------
# The actions
# --------------------------------------------------------------------------------------


def _status(ctx: BackupContext, out) -> int:
    """Path-blind status: the manifest summary and the gauge."""

    gauge = ctx.gauge()
    sensors.storage_gauge(gauge, stream=out)
    print(ctx.manifest.summary(), file=out)
    print(f"hot={gauge.hot_bytes}B cold={gauge.cold_bytes}B "
          f"artifacts={gauge.hot_count + gauge.cold_count}", file=out)
    if not gauge.remote_free_known:
        print("remote_free=unknown (no remote configured)", file=out)
    elif gauge.below_floor():
        print("CAPACITY FLOOR BREACHED — the designed pressure gauge has fired",
              file=out)
    return 0


def _fetch(ctx: BackupContext, artifact: str, *, dest: str | None, out) -> int:
    """The cold read path: manifest lookup, restore, hash-verify."""

    path = Path(artifact).expanduser()
    record = ctx.manifest.current().get(str(path))
    if record is None:
        print("backup fetch: no manifest record for that artifact", file=out)
        return 2
    if record.state not in _COLD_STATES:
        print(f"backup fetch: that artifact is {record.state}, not cold; "
              f"nothing to restore", file=out)
        return 2
    if ctx.restorer is None:
        print("backup fetch: no restorer configured; nothing can be restored",
              file=out)
        return 2

    target = Path(dest).expanduser() if dest else Path(
        tempfile.mkdtemp(prefix="elaria-restore-")) / path.name
    try:
        restored = ctx.restorer.restore(path, target)
    except (OSError, FileNotFoundError) as exc:
        sensors.backup_failed(reason=f"restore failed ({type(exc).__name__})",
                              stream=out)
        print(f"backup fetch: restore failed ({type(exc).__name__})", file=out)
        return 1

    from .safety import try_sha256_file

    actual = try_sha256_file(restored)
    expected = record.sha256
    if expected and actual != expected:
        sensors.backup_verify(backend=ctx.restorer.name, method="hash",
                              confirmed=False, stream=out)
        print("backup fetch: restored copy does not match the manifest hash; "
              "refusing to call this a restore", file=out)
        return 1

    sensors.backup_verify(backend=ctx.restorer.name, method="hash",
                          confirmed=True, stream=out)
    print(f"restored: {restored}", file=out)
    print(f"backend: {ctx.restorer.name}  hash: verified", file=out)
    return 0


def _run(ctx: BackupContext, *, out, dry_run: bool = False) -> int:
    """One backup pass: tier, plan, reconcile. Emits the run lifecycle."""

    sensors.backup_started(reason="nightly" if not dry_run else "manual dry-run",
                           stream=out)
    try:
        # scan() walks the tree AND classifies — it is the belt, and the directory poll
        # is truth. Classifying its result again would be classifying a decision.
        decision = scan(ctx.data_dir, now=ctx.now or _fallback_now(),
                        data_dir=ctx.data_dir, window_days=ctx.window_days,
                        window_gb=ctx.window_gb)
    except OSError as exc:
        sensors.backup_failed(reason=f"scan failed ({type(exc).__name__})", stream=out)
        print(f"backup run: scan failed ({type(exc).__name__})", file=out)
        return 1

    if not decision.send_cold:
        sensors.backup_done(sent_cold=0, kept_hot=len(decision.keep_hot),
                            stream=out)
        print(decision.summary(), file=out)
        print("nothing to send cold", file=out)
        return 0

    if dry_run:
        sensors.backup_done(sent_cold=len(decision.send_cold),
                            kept_hot=len(decision.keep_hot), stream=out)
        print(decision.summary(), file=out)
        print("dry run: no manifest change, no remote traffic", file=out)
        return 0

    if ctx.verifier is None:
        sensors.backup_failed(reason="no remote verifier configured", stream=out)
        print("backup run: no remote verifier configured; refusing to plan a flip "
              "that cannot be confirmed", file=out)
        return 2

    plan = plan_reconcile(ctx.manifest, now=ctx.now or _fallback_now(),
                          verify_remote=ctx.verifier,
                          grace_days=ctx.grace_days)
    if dry_run:
        pass
    else:
        reconcile_all(ctx.manifest, now=ctx.now or _fallback_now(),
                      verify_remote=ctx.verifier, trim_mover=ctx.trim_mover,
                      purge_mover=ctx.purge_mover, grace_days=ctx.grace_days)

    sensors.backup_done(
        sent_cold=len(decision.send_cold), kept_hot=len(decision.keep_hot),
        trimmed=sum(1 for a in plan.actions if a.to_state == "trashed"),
        purged=sum(1 for a in plan.actions if a.to_state == "purged"),
        problems=len(plan.problems), passes=1, stream=out)
    print(decision.summary(), file=out)
    print(plan.summary(), file=out)
    return 0


def _check(ctx: BackupContext, *, artifact: str | None, kind: str, out,
           rng: random.Random | None = None,
           journal=None, restic=None,
           now=None) -> int:
    """The integrity-drill shape: restore a cold artifact and hash-verify it.

    Increment 8 adds two OPTIONAL seams, both defaulting to None so every existing caller
    and test is unchanged:

    * `journal` - a `DrillJournal`. When given, the outcome is recorded so "one live
      monthly drill passes" is something that can be looked up afterwards rather than
      something somebody remembers.
    * `restic` - a `ResticCheck`. When given, `restic check` runs after the restore and
      the hash-verify, proving the repository is internally consistent as well as the
      artifact being retrievable. **A missing restic is a DECLARED skip, not a pass and
      not a failure** - the restore and the hash are what prove the owner can get their
      audio back, and claiming more than that would be the silent-pass failure increment 4
      exists to prevent.
    """

    if ctx.restorer is None:
        sensors.backup_check(kind=kind, ok=False,
                             detail="reason=no restorer configured", stream=out)
        print("backup check: no restorer configured", file=out)
        _record_drill(journal, kind=kind, ok=False, ctx=ctx, restic=restic,
                      detail="no restorer configured", now=now)
        return 2

    cold = [r for r in ctx.manifest.current().values()
            if r.state in _COLD_STATES]

    if artifact:
        # Named first: a caller who names an artifact deserves an answer about THAT
        # artifact, not a summary of the whole set.
        chosen = ctx.manifest.current().get(str(Path(artifact).expanduser()))
        if chosen is None:
            sensors.backup_check(kind=kind, ok=False,
                                 detail="reason=no manifest record", stream=out)
            print("backup check: no manifest record for that artifact", file=out)
            _record_drill(journal, kind=kind, ok=False, ctx=ctx,
                          restic=restic, detail="no manifest record", now=now)
            return 2
        if chosen.state not in _COLD_STATES:
            sensors.backup_check(kind=kind, ok=False,
                                 detail="reason=artifact not cold", stream=out)
            print("backup check: that artifact is not cold", file=out)
            _record_drill(journal, kind=kind, ok=False, ctx=ctx,
                          restic=restic, detail="artifact not cold", now=now)
            return 2
    elif not cold:
        sensors.backup_check(kind=kind, ok=True,
                             detail="cold_n=0; nothing to drill", stream=out)
        print("backup check: nothing cold to drill", file=out)
        _record_drill(journal, kind=kind, ok=True, ctx=ctx, restic=restic,
                      detail="nothing cold to drill", now=now)
        return 0
    else:
        chosen = (rng or random.Random()).choice(cold)

    target = Path(tempfile.mkdtemp(prefix="elaria-drill-")) / Path(
        chosen.artifact).name
    try:
        restored = ctx.restorer.restore(Path(chosen.artifact), target)
    except (OSError, FileNotFoundError) as exc:
        sensors.backup_check(kind=kind, ok=False,
                             detail=f"reason=restore failed ({type(exc).__name__})",
                             stream=out)
        print(f"backup check: restore failed ({type(exc).__name__})", file=out)
        _record_drill(journal, kind=kind, ok=False, ctx=ctx, restic=restic,
                      detail=f"restore=failed ({type(exc).__name__})", now=now)
        return 1

    from .safety import try_sha256_file

    actual = try_sha256_file(restored)
    ok = bool(chosen.sha256) and actual == chosen.sha256
    sensors.backup_check(
        kind=kind, ok=ok,
        detail=f"backend={ctx.restorer.name}; method=hash; "
               f"hash_ok={'yes' if ok else 'no'}",
        stream=out)
    print(f"backup check: {'passed' if ok else 'FAILED'} "
          f"(restored 1 artifact, hash {'verified' if ok else 'MISMATCH'})",
          file=out)
    _record_drill(journal, kind=kind, ok=ok, ctx=ctx, restic=restic,
                  detail=f"restore=ok; hash={'ok' if ok else 'MISMATCH'}",
                  now=now)
    return 0 if ok else 1


def _record_drill(journal, *, kind: str, ok: bool, ctx: BackupContext,
                  restic=None, detail: str, now=None) -> bool:
    """Append one drill record. Returns False when there is no journal to write to.

    Path-free: the record carries the artifact's EXTENSION and the backend that confirmed,
    never a name or a path.
    """

    if journal is None:
        return False
    from .drill import DrillRecord

    backend = ctx.backend.name if ctx.backend is not None else "none"
    if restic is not None:
        method = "restore+hash+restic-check"
    else:
        method = "restore+hash"
    return journal.append(DrillRecord(
        ts=(now or _fallback_now()).isoformat(),
        kind=kind,
        ok=ok,
        backend=backend,
        method=method,
        label="wav",
        detail=detail,
    ))


def _fallback_now():
    """The real clock, used only when no clock was injected."""

    from datetime import UTC, datetime

    return datetime.now(UTC)


# --------------------------------------------------------------------------------------
# The entry point
# --------------------------------------------------------------------------------------


def _watch(ctx: BackupContext, *, root: str | None, out) -> int:
    """One trigger poll. Reports whether a backup should wake; performs none.

    Path-free by construction: the output carries counts and extension labels only. The
    `audio kept at {path}` detail is read to address an artifact and never printed.
    """

    from assistant.backup_triggers import BackupWatcher

    watch_root = Path(root) if root else ctx.data_dir / "audio"
    watcher = BackupWatcher(
        root=watch_root,
        cursor_path=ctx.data_dir / ".backup-journal-cursor",
        data_dir=ctx.data_dir,
        poll_s=int(ctx.section.get("watcher_poll_s", 30) or 30),
        defer_above_mb=int(ctx.section.get("defer_above_mb", 100) or 100),
    )
    decision = watcher.poll()
    if not decision.woke:
        print("watch: nothing to back up", file=out)
        return 0
    labels = ", ".join(decision.labels) or "nothing"
    print(f"watch: wake ({decision.reason}); {decision.count} artifact(s); "
          f"kinds: {labels}", file=out)
    if decision.deferred:
        print(f"watch: deferred to AC/unmetered: {', '.join(decision.deferred)}",
              file=out)
    return 0


def _drill_journal(ctx: BackupContext):
    """The drill journal, at 0600 outside the repo.

    Lives beside the manifest, not inside the repo: the manifest stores artifact paths and
    is never committed, and the drill record must share that discipline.
    """

    from .drill import DrillJournal

    return DrillJournal(ctx.manifest.path.parent / "drills.jsonl")


def _last_drill(ctx: BackupContext, *, kind: str, out) -> None:
    """`assist backup check --last`: the most recent recorded drill, path-blind."""

    from .drill import DrillJournal

    record = DrillJournal(ctx.manifest.path.parent / "drills.jsonl").last(kind=kind)
    if record is None:
        print(f"backup check: no {kind} drill recorded yet", file=out)
        return
    print(f"backup check: last {kind} drill "
          f"{'passed' if record.ok else 'FAILED'} at {record.ts} "
          f"(backend={record.backend}; method={record.method})", file=out)


def backup_command(args, config, *, out=None, ctx: BackupContext | None = None) -> int:
    """`assist backup <action>`. Returns a process exit code."""

    import sys

    out = out if out is not None else sys.stdout
    ctx = ctx if ctx is not None else build_context(config)
    action = getattr(args, "backup_action", "status")

    if action == "status":
        return _status(ctx, out)
    if action == "fetch":
        return _fetch(ctx, args.artifact, dest=getattr(args, "out", None), out=out)
    if action == "run":
        return _run(ctx, out=out, dry_run=bool(getattr(args, "dry_run", False)))
    if action == "check":
        if getattr(args, "last", False):
            _last_drill(ctx, kind=getattr(args, "kind", "monthly"), out=out)
            return 0
        return _check(ctx, artifact=getattr(args, "artifact", None),
                      kind=getattr(args, "kind", "monthly"), out=out,
                      journal=_drill_journal(ctx) if getattr(args, "record", False)
                      else None,
                      now=ctx.now)
    if action == "watch":
        return _watch(ctx, root=getattr(args, "root", None), out=out)
    print(f"backup: unknown action {action!r}", file=out)
    return 2
