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

import json
import random
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from . import sensors
from . import wp7_preflight as preflight
from .backup import ReconcilePlan, plan_reconcile, reconcile
from .remote import LocalPathBackend, Verification, make_verifier
from .safety import try_sha256_file
from .storage import LOCAL, UPLOADED, ManifestRecord, StorageManifest
from .tiering import (
    DEFAULT_WINDOW_DAYS,
    DEFAULT_WINDOW_GB,
    TrashMover,
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


class ResticRestorer:
    """Read a single absolute snapshot path, not a matching basename or a tree."""

    def __init__(self, backend, timeout: str, manifest: StorageManifest):
        self.manifest = manifest
        self.name = f"restic:{backend.name}"
        self.repo = f"rclone:{backend.remote}:{backend.path}"
        self.timeout = timeout

    def restore(self, artifact: Path, dest: Path) -> Path:
        if not artifact.is_absolute() or ".." in artifact.parts:
            raise OSError("expected an absolute manifest path")
        record = self.manifest.current().get(str(artifact))
        match = re.search(r"(?:^|;)snapshot=([0-9a-f]{8,64})(?:;|$)", record.detail if record else "")
        if not match:
            raise OSError("manifest has no pinned snapshot")
        snapshot = match.group(1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as sink:
            staged = Path(sink.name)
        try:
            with staged.open("wb") as output:
                subprocess.run(["restic", "-r", self.repo, "-o", f"rclone.timeout={self.timeout}",
                                "dump", snapshot, str(artifact)], stdout=output,
                               stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                               check=True, timeout=600)
            staged.replace(dest)
        except subprocess.SubprocessError as exc:
            raise OSError("restic dump failed") from exc
        finally:
            staged.unlink(missing_ok=True)
        return dest


class AudioMovers:
    """Constrain the generic TrashMover to files in the dedicated backup trees."""

    def __init__(self, data_dir: Path):
        self.root = data_dir.resolve()
        self.audio = self.root / "audio"
        self.trash = self.root / "backup" / "trash"
        self.mover = TrashMover(self.trash)

    def trim(self, path: Path) -> Path:
        if (path.resolve() != path or not path.is_relative_to(self.audio)
                or not path.is_file() or path.suffix.lower() != ".wav"
                or self.trash.resolve() != self.trash):
            raise OSError("not a regular capture in the audio tree")
        return self.mover.move(path)

    def purge(self, path: Path) -> bool:
        if path.resolve() != path or path.parent != self.trash or not path.is_file():
            raise OSError("not a regular file in backup trash")
        return self.mover.purge(path)


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

    # -- F24 pre-flights ---------------------------------------------------------------
    # The capacity-floor knock must PREVENT, not interrupt. A gate read after the
    # upload has already cost the owner the upload.

    def remote_preflight(self, *, scratch_bytes: int | None = None,
                         margin_bytes: int | None = None) -> preflight.HeadroomDecision:
        """Whether the remote has room for this run's scratch, before it starts.

        `scratch_bytes` defaults to the benchmark's own derived figure; `margin_bytes`
        defaults to the `[backup] bench_headroom_margin_gb` key. Both are named in the
        decision, so a refusal can be checked rather than re-measured.
        """

        if scratch_bytes is None:
            scratch_bytes = preflight.bench_scratch_bytes(
                pack_mib=int(self.section.get("restic_pack_size_mib", 128)),
                connections=preflight.RESTIC_BACKEND_CONNECTIONS)
        if margin_bytes is None:
            margin_bytes = int(self.section.get("bench_headroom_margin_gb", 1)) * 1000 ** 3
        return preflight.remote_headroom(
            self.remote_free_bytes, scratch_bytes=scratch_bytes,
            margin_bytes=margin_bytes)

    def local_preflight(self, *, required_bytes: int,
                        artifact_bytes: int = 0, margin_bytes: int = 0,
                        directory: str | Path | None = None
                        ) -> preflight.HeadroomDecision:
        """Whether the local filesystem can hold a restore of `required_bytes`."""

        target = Path(directory) if directory is not None else self.data_dir
        return preflight.local_headroom(target, required_bytes=required_bytes,
                                        artifact_bytes=artifact_bytes,
                                        margin_bytes=margin_bytes)

    # -- derived ------------------------------------------------------------------------

    def gauge(self):
        return sensors.gauge_from_manifest(
            self.manifest, floor_bytes=self.floor_bytes,
            window_days=self.window_days, window_gb=self.window_gb,
            remote_free_bytes=self.remote_free_bytes)


def build_context(config, *, now=None, read_quota: bool = True) -> BackupContext:
    """Build a context from the live config. Talks to no remote until told to.

    `rclone_remote` empty means not configured yet, and the verifier is left `None` —
    which is the no-verifier posture `plan_reconcile` already refuses to flip without.
    Guessing a remote would be worse than having none.
    """

    section = config.section("backup")
    manifest = StorageManifest(config.data_dir / "backup" / "manifest.jsonl")
    remote = (section.get("rclone_remote") or "").strip()
    verifier = None
    restorer = None
    backend = None
    remote_free_bytes = None
    if remote:
        from .remote import RcloneBackend

        backend = RcloneBackend(remote, path=section.get("rclone_path") or "")
        restorer = ResticRestorer(backend, section.get("restic_timeout", "5m"), manifest)

        def verifier(artifact):
            # rclone lsjson sees restic pack objects, not files inside snapshots.
            # Never authorize a trim from a coincidentally matching object name.
            pin = backend.pin_status()
            if not pin.confirmed:
                return pin
            record = manifest.current().get(str(artifact))
            if record is None or not record.sha256:
                return Verification(restorer.name, False, "hash", "missing manifest hash")
            try:
                with tempfile.TemporaryDirectory(prefix="elaria-verify-") as scratch:
                    restored = restorer.restore(Path(artifact), Path(scratch) / "artifact")
                    matches = try_sha256_file(restored) == record.sha256
            except OSError:
                return Verification(restorer.name, False, "hash", "snapshot read failed")
            return Verification(restorer.name, matches, "hash", "match" if matches else "mismatch")

        # F24: the headroom gate needs a READING, not an assumption. Without this the
        # gate would refuse every real run forever, because nothing produced its input —
        # and a gate that can never open is a gate that has been silently switched off.
        # `read_quota=False` lets a caller build a context without touching the remote.
        if read_quota:
            remote_free_bytes = backend.remote_free()
    movers = AudioMovers(config.data_dir) if remote else None
    return BackupContext(
        manifest,
        restorer=restorer,
        trim_mover=movers.trim if movers else None,
        purge_mover=None,  # Deletion requires a separate owner decision.
        data_dir=config.data_dir,
        verifier=verifier,
        backend=backend,
        section=section,
        now=now,
        window_days=int(section.get("hot_window_days", DEFAULT_WINDOW_DAYS)),
        window_gb=int(section.get("hot_window_gb", DEFAULT_WINDOW_GB)),
        floor_bytes=int(section.get("capacity_floor_gb", 10)) * 1000 ** 3,
        grace_days=int(section.get("trim_grace_days", 14)),
        remote_free_bytes=remote_free_bytes,
    )


# --------------------------------------------------------------------------------------
# The actions
# --------------------------------------------------------------------------------------


def _status(ctx: BackupContext, out) -> int:
    """Path-blind status: the manifest summary and the gauge."""

    gauge = ctx.gauge()
    sensors.storage_gauge(gauge, stream=out)
    print(ctx.manifest.summary(), file=out)
    print("backup state: uploaded is unverified; flipped/trashed/purged indicate "
          "a prior flip, not proof of current remote health", file=out)
    print(f"backend: {ctx.backend.name if ctx.backend is not None else 'not configured'}", file=out)
    print(f"hot={gauge.hot_bytes}B cold={gauge.cold_bytes}B "
          f"artifacts={gauge.hot_count + gauge.cold_count}", file=out)
    if gauge.hot_count + gauge.cold_count == 0:
        print("0 manifest records; not a count of discovered files", file=out)
    if not gauge.remote_free_known:
        print("remote_free=unknown (no quota reading)", file=out)
    elif gauge.below_floor():
        print("CAPACITY FLOOR BREACHED — the designed pressure gauge has fired",
              file=out)
    events = _drill_journal(ctx).records()
    failures = sum(not event.ok for event in events)
    if failures:
        print(f"BACKUP HEALTH WARNING: {failures} recorded failure(s); "
              "review the health journal; later passes do not clear prior failures", file=out)
    last = events[-1] if events else None
    if last:
        print(f"last backup health event: {last.kind} "
              f"{'passed' if last.ok else 'FAILED'} (backend={last.backend})", file=out)
    else:
        print("backup health: no recorded verification or restore drill", file=out)
    return 0


def _resolve_artifact(ctx: BackupContext, artifact: str) -> tuple[Path | None, str]:
    """Prefer exact manifest keys and stems; accept only a unique bare WAV prefix."""
    current = ctx.manifest.current()
    if not artifact.strip():
        return None, "no manifest record"
    given = Path(artifact).expanduser()
    audio = ctx.data_dir / "audio"
    candidates = [given]
    try:
        candidates.append(given.resolve())
    except (OSError, RuntimeError):
        pass
    if not given.is_absolute() and ".." not in given.parts:
        candidates.append(ctx.data_dir / given if given.parts[:1] == ("audio",) else audio / given)
    for path in candidates:
        names = [path]
        if path.name and not path.suffix:
            names.append(path.with_name(path.name + ".wav"))
        for candidate in names:
            if str(candidate) in current:
                return candidate, str(candidate)
    if given.name == artifact and not given.suffix and given.name:
        matches = [p for key in current if (p := Path(key)).parent == audio
                   and p.suffix == ".wav" and p.stem.startswith(artifact)]
        if len(matches) == 1:
            return matches[0], str(matches[0])
        if len(matches) > 1:
            return None, "ambiguous artifact prefix"
    return None, "no manifest record"


def _fetch(ctx: BackupContext, artifact: str, *, dest: str | None, out) -> int:
    """The cold read path: manifest lookup, restore, hash-verify."""

    path, _key = _resolve_artifact(ctx, artifact)
    record = ctx.manifest.current().get(str(path)) if path is not None else None
    if record is None:
        print(f"backup fetch: {_key} for that artifact", file=out)
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
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() or target.is_symlink():
            print("backup fetch: REFUSED - destination already exists", file=out)
            return 2
        margin = int(ctx.section.get("restore_headroom_margin_gb", 1)) * 1000 ** 3
        required = preflight.restore_headroom_bytes(record.size or 0, margin_bytes=margin)
        gate = ctx.local_preflight(required_bytes=required, artifact_bytes=record.size or 0,
                                   margin_bytes=margin, directory=target.parent)
        if not gate.ok:
            print(f"backup fetch: REFUSED - {gate.detail()}", file=out)
            return 2
        with tempfile.TemporaryDirectory(dir=target.parent) as scratch:
            restored = ctx.restorer.restore(path, Path(scratch) / "artifact")
            if not record.sha256 or try_sha256_file(restored) != record.sha256:
                sensors.backup_verify(backend=ctx.restorer.name, method="hash",
                                      confirmed=False, stream=out)
                print("backup fetch: restored copy does not match the manifest hash", file=out)
                return 1
            restored.replace(target)
    except (OSError, FileNotFoundError) as exc:
        sensors.backup_failed(reason=f"restore failed ({type(exc).__name__})",
                              stream=out)
        print(f"backup fetch: restore failed ({type(exc).__name__})", file=out)
        return 1

    sensors.backup_verify(backend=ctx.restorer.name, method="hash",
                          confirmed=True, stream=out)
    print(f"restored: {target}", file=out)
    print(f"backend: {ctx.restorer.name}  hash: verified", file=out)
    return 0


def _hash_confirmed(verifier, path: Path) -> bool:
    try:
        verdict = verifier(path)
        return isinstance(verdict, Verification) and verdict.confirmed and verdict.method == "hash"
    except (OSError, subprocess.SubprocessError):
        return False


def _verify(ctx: BackupContext, artifact: str, *, out) -> int:
    path, reason = _resolve_artifact(ctx, artifact)
    record = ctx.manifest.current().get(str(path)) if path else None
    if record is None or record.state not in _COLD_STATES | {UPLOADED}:
        print(f"backup verify: REFUSED - {reason if record is None else 'not uploaded'}", file=out)
        return 2
    if ctx.restorer is None or not record.sha256:
        print("backup verify: FAILED - no restorer or recorded hash", file=out)
        _record_drill(_drill_journal(ctx), kind="verify", ok=False, ctx=ctx,
                      detail="no restorer or recorded hash", now=ctx.now)
        return 1
    margin = int(ctx.section.get("restore_headroom_margin_gb", 1)) * 1000 ** 3
    required = preflight.restore_headroom_bytes(record.size or 0, margin_bytes=margin)
    gate = ctx.local_preflight(required_bytes=required, artifact_bytes=record.size or 0,
                               margin_bytes=margin, directory=tempfile.gettempdir())
    if not gate.ok:
        print(f"backup verify: REFUSED - {gate.detail()}", file=out)
        _record_drill(_drill_journal(ctx), kind="verify", ok=False, ctx=ctx,
                      detail="local headroom refused", now=ctx.now)
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix="elaria-verify-") as scratch:
            restored = ctx.restorer.restore(path, Path(scratch) / "artifact")
            ok = try_sha256_file(restored) == record.sha256
    except (OSError, subprocess.SubprocessError):
        ok = False
    backend = ctx.restorer.name
    sensors.backup_verify(backend=backend, method="hash", confirmed=ok, stream=out)
    recorded = _record_drill(_drill_journal(ctx), kind="verify", ok=ok, ctx=ctx,
                             detail="remote hash match" if ok else "remote hash FAILED", now=ctx.now)
    print(f"backup verify: {'hash matched' if ok else 'FAILED - remote hash mismatch or unreadable'} "
          f"(backend={backend}; state unchanged)", file=out)
    if not recorded:
        print("backup verify: FAILED - health journal unavailable", file=out)
    return 0 if ok and recorded else 1


def _run(ctx: BackupContext, *, out, dry_run: bool = False,
         artifact: str | None = None, allow_multiple: bool = False) -> int:
    """Back up exactly one explicitly selected audio file; never purge automatically."""
    now = ctx.now or _fallback_now()
    audio = (ctx.data_dir / "audio").resolve()
    decision = scan(audio, now=now, data_dir=ctx.data_dir,
                    window_days=ctx.window_days, window_gb=ctx.window_gb)
    print(decision.summary(), file=out)
    if dry_run:
        print("dry run: classification only; no manifest change or upload", file=out)
        return 0
    if not artifact:
        print("backup run: REFUSED - specify one exact --artifact", file=out)
        return 2
    path = Path(artifact).expanduser()
    if (not path.is_absolute() or path.resolve() != path or path.parent != audio
            or path.suffix.lower() != ".wav" or not path.is_file()):
        print("backup run: REFUSED - expected an exact regular WAV in the audio directory", file=out)
        return 2
    if not any(c.path == path for c in decision.send_cold) or (
            not allow_multiple and len(decision.send_cold) != 1):
        print("backup run: REFUSED - selected file must be the only cold candidate", file=out)
        return 2
    gate = ctx.remote_preflight()
    if not gate.ok or ctx.remote_free_bytes is None or ctx.remote_free_bytes < ctx.floor_bytes:
        print(f"backup run: REFUSED - {gate.detail()}; floor={ctx.floor_bytes}", file=out)
        return 2
    if ctx.verifier is None or ctx.restorer is None or ctx.trim_mover is None:
        print("backup run: REFUSED - upload, verification and trim must be configured", file=out)
        return 2

    # The local journal is durable before remote traffic. A failed upload stays LOCAL.
    record = ctx.manifest.current().get(str(path))
    digest = try_sha256_file(path)
    if not digest:
        print("backup run: REFUSED - local hash unreadable", file=out)
        return 2
    size = path.stat().st_size
    if ctx.remote_free_bytes < ctx.floor_bytes + size:
        print("backup run: REFUSED - upload would breach capacity floor", file=out)
        return 2
    required = preflight.restore_headroom_bytes(size, margin_bytes=1000 ** 3)
    local = ctx.local_preflight(required_bytes=required, artifact_bytes=size,
                                 margin_bytes=1000 ** 3, directory=tempfile.gettempdir())
    if not local.ok:
        print(f"backup run: REFUSED - {local.detail()}", file=out)
        return 2
    if record is None:
        record = ManifestRecord(str(path), LOCAL, sha256=digest, size=size, tier="hot")
        ctx.manifest.append(record)
    if record.state == LOCAL:
        if record.sha256 != digest or record.size != size:
            print("backup run: REFUSED - local file changed since journal entry", file=out)
            return 2
        try:
            if isinstance(ctx.backend, LocalPathBackend):
                ctx.backend.store(path)
                detail = "backend=local-path-fixture"
            elif isinstance(ctx.restorer, ResticRestorer):
                proc = subprocess.run(
                    ["restic", "-r", ctx.restorer.repo, "-o", f"rclone.timeout={ctx.restorer.timeout}",
                     "backup", "--json", "--", str(path)],
                    capture_output=True, text=True, stdin=subprocess.DEVNULL,
                    check=True, timeout=3600)
                summaries = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
                snapshots = [row.get("snapshot_id") for row in summaries
                             if row.get("message_type") == "summary"]
                snapshot = snapshots[-1] if snapshots else None
                if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{8,64}", snapshot):
                    raise ValueError("missing snapshot id")
                detail = f"snapshot={snapshot}"
            else:
                raise OSError("uploader not configured")
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            print("backup run: upload failed; local copy retained", file=out)
            return 1
        if try_sha256_file(path) != digest:
            print("backup run: local file changed during upload; local copy retained", file=out)
            return 1
        uploaded = ManifestRecord(str(path), UPLOADED, sha256=digest, size=size,
                                  tier="cold", detail=detail)
        if not ctx.manifest.append(uploaded, expect_from=LOCAL):
            print("backup run: manifest refused upload record", file=out)
            return 1
    elif record.state not in (UPLOADED, "flipped"):
        print("backup run: REFUSED - selected artifact is already beyond upload", file=out)
        return 2
    elif record.sha256 != digest or record.size != size:
        print("backup run: REFUSED - local file changed since journal entry", file=out)
        return 2

    # Reconcile ONLY the explicitly authorized artifact. Never execute purge actions.
    start_step = 1 if record.state == "flipped" else 0
    for step in range(start_step, 2):
        # A changed source must never be removed, even after the flip record.
        if step == 1 and (try_sha256_file(path) != digest or not _hash_confirmed(ctx.verifier, path)):
            print("backup run: verification changed before trim; local copy retained", file=out)
            return 1
        plan = plan_reconcile(ctx.manifest, now=now, verify_remote=ctx.verifier,
                              grace_days=ctx.grace_days, only_artifact=str(path))
        selected = [action for action in plan.actions if action.artifact == str(path)
                    and action.to_state in ("flipped", "trashed")]
        if not selected:
            print("backup run: verification or trim refused; local copy retained", file=out)
            return 1
        result = reconcile(ctx.manifest, ReconcilePlan(actions=selected), now=now,
                           trim_mover=ctx.trim_mover, purge_mover=None)
        if result.problems:
            print("backup run: reconcile refused", file=out)
            return 1
    print(f"backup run: uploaded, verified and moved to grace trash "
          f"(backend={ctx.backend.name if ctx.backend else 'unknown'})", file=out)
    return 0


def _check(ctx: BackupContext, *, artifact: str | None, kind: str, out,
           rng: random.Random | None = None,
           journal=None, restic=None,
           now=None, hash_only: bool = False) -> int:
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
        sensors.backup_check(kind=kind, ok=False,
                             detail="cold_n=0; nothing to drill", stream=out)
        print("backup check: nothing cold to drill", file=out)
        _record_drill(journal, kind=kind, ok=False, ctx=ctx, restic=restic,
                      detail="nothing cold to drill", now=now)
        return 2
    else:
        chosen = (rng or random.Random()).choice(cold)

    # F24 local pre-flight, before the restore write. A restore that dies at 90%
    # because the disk filled has written a partial file and proved nothing, so the
    # required headroom is named in the record rather than left to be discovered.
    margin = int(ctx.section.get("restore_headroom_margin_gb", 1)) * 1000 ** 3
    required = preflight.restore_headroom_bytes(
        chosen.size if chosen.size is not None else 0, margin_bytes=margin)
    local_gate = ctx.local_preflight(required_bytes=required,
                                      artifact_bytes=chosen.size or 0,
                                      margin_bytes=margin, directory=tempfile.gettempdir())
    if not local_gate.ok:
        sensors.backup_check(kind=kind, ok=False,
                             detail=f"reason=local headroom ({local_gate.reason}); "
                                    f"required={required}B",
                             stream=out)
        print(f"backup check: REFUSED - {local_gate.detail()}", file=out)
        _record_drill(journal, kind=kind, ok=False, ctx=ctx, restic=restic,
                      detail=f"refused=local headroom; required={required}B; "
                             f"reason={local_gate.reason}",
                      now=now)
        return 2

    print(f"backup check: {local_gate.detail()}", file=out)
    try:
        with tempfile.TemporaryDirectory(prefix="elaria-drill-") as scratch:
            target = Path(scratch) / Path(chosen.artifact).name
            restored = ctx.restorer.restore(Path(chosen.artifact), target)
            actual = try_sha256_file(restored)
    except (OSError, FileNotFoundError) as exc:
        sensors.backup_check(kind=kind, ok=False,
                             detail=f"reason=restore failed ({type(exc).__name__})",
                             stream=out)
        print(f"backup check: restore failed ({type(exc).__name__})", file=out)
        _record_drill(journal, kind=kind, ok=False, ctx=ctx, restic=restic,
                      detail=f"restore=failed ({type(exc).__name__})", now=now)
        return 1

    ok = bool(chosen.sha256) and actual == chosen.sha256
    hash_result = "verified" if ok else "MISMATCH"
    check_result = "declared skip"
    if ok and restic is None and not hash_only:
        ok = False
    if ok and restic is not None:
        ok, check_detail = restic.run()
        check_result = ("passed" if ok else
                        "declared skip (restic unavailable)" if check_detail.startswith(
                            "restic unavailable") else "FAILED")
    sensors.backup_check(
        kind=kind, ok=ok,
        detail=f"backend={ctx.restorer.name}; method=hash; "
               f"hash={hash_result}; restic={check_result}",
        stream=out)
    print(f"backup check: {'passed' if ok else 'FAILED'} "
          f"(restored 1 artifact, hash {hash_result}; restic check: {check_result})",
          file=out)
    recorded = _record_drill(journal, kind=kind, ok=ok, ctx=ctx, restic=restic,
                             detail=f"restore=ok; hash={hash_result}; restic={check_result}",
                             now=now)
    if journal is not None and not recorded:
        print("backup check: FAILED - drill journal unavailable", file=out)
        return 1
    return 0 if ok else 1


def _record_drill(journal, *, kind: str, ok: bool, ctx: BackupContext,
                  restic=None, detail: str, now=None) -> bool:
    """Append one drill record. Returns False when there is no journal to write to.

    Path-free: the record carries the artifact's EXTENSION and the backend that confirmed,
    never a name or a path.
    """

    if journal is None:
        return False
    from .wp7_drill import DrillRecord

    backend = ctx.backend.name if ctx.backend is not None else "none"
    if restic is not None:
        method = "restore+hash+restic-check"
    else:
        method = "restore+hash"
    recorded = journal.append(DrillRecord(
        ts=(now or _fallback_now()).isoformat(),
        kind=kind,
        ok=ok,
        backend=backend,
        method=method,
        label="wav",
        detail=detail,
    ))
    if not recorded:
        sensors.backup_failed(reason="drill journal unavailable")
    return recorded


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

    from .wp7_drill import DrillJournal

    return DrillJournal(ctx.manifest.path.parent / "drills.jsonl")


def _last_drill(ctx: BackupContext, *, kind: str, out) -> None:
    """`assist backup check --last`: the most recent recorded drill, path-blind."""

    from .wp7_drill import DrillJournal

    record = DrillJournal(ctx.manifest.path.parent / "drills.jsonl").last(kind=kind)
    if record is None:
        print(f"backup check: no {kind} drill recorded yet", file=out)
        return
    print(f"backup check: last {kind} drill "
          f"{'passed' if record.ok else 'FAILED'} at {record.ts} "
          f"(backend={record.backend}; method={record.method})", file=out)


def _run_with_retry(ctx: BackupContext, args, *, out) -> int:
    """Explicit pass over newly cold WAVs; retry failures without losing local files."""
    auto = getattr(args, "all_cold", False)
    artifact = getattr(args, "artifact", None)
    if auto and artifact:
        print("backup run: REFUSED - choose --artifact or --all-cold", file=out)
        return 2
    if auto:
        decision = scan((ctx.data_dir / "audio").resolve(), now=ctx.now or _fallback_now(),
                        data_dir=ctx.data_dir, window_days=ctx.window_days,
                        window_gb=ctx.window_gb)
        paths = [str(c.path) for c in decision.send_cold]
        if not paths:
            print("backup run: no cold candidates", file=out)
            return 0
    else:
        paths = [artifact]
    sensors.backup_started(reason="tier scan", stream=out)
    failed = False
    for path in paths:
        code = 1
        for attempt in range(1, 4):
            try:
                code = _run(ctx, out=out, artifact=path, allow_multiple=auto)
            except (OSError, subprocess.SubprocessError):
                code = 1
                print("backup run: remote or journal error; inspect local state", file=out)
            if code == 0:
                break
            sensors.backup_failed(reason=f"attempt {attempt} failed; code={code}", stream=out)
            if not _record_drill(_drill_journal(ctx), kind="backup-run", ok=False, ctx=ctx,
                                 detail=f"attempt={attempt}; code={code}", now=ctx.now):
                print("backup run: FAILED - health journal unavailable", file=out)
                return 1
            if code == 2:
                # Unknown quota may be a transient unreachable remote. Re-read it,
                # but never bypass either the capacity or free-space gate.
                if (ctx.remote_free_bytes is None and ctx.backend is not None
                        and hasattr(ctx.backend, "remote_free") and attempt < 3):
                    ctx.remote_free_bytes = ctx.backend.remote_free()
                else:
                    break
            if attempt < 3:
                print(f"backup run: retrying ({attempt + 1}/3)", file=out)
        failed |= code != 0
    if failed:
        print("backup run: FAILED - see health journal; retry on next run", file=out)
        return 1
    if not _record_drill(_drill_journal(ctx), kind="backup-run", ok=True, ctx=ctx,
                         detail=f"backed_up={len(paths)}", now=ctx.now):
        print("backup run: FAILED - health journal unavailable", file=out)
        return 1
    sensors.backup_done(sent_cold=len(paths), trimmed=len(paths), stream=out)
    return 0


def backup_command(args, config, *, out=None, ctx: BackupContext | None = None) -> int:
    """`assist backup <action>`. Returns a process exit code."""

    import sys

    out = out if out is not None else sys.stdout
    action = getattr(args, "backup_action", "status")
    if ctx is None:
        read_quota = (action == "status"
                      or (action == "run" and not getattr(args, "dry_run", False))
                      or (action == "watch" and getattr(args, "run_cold", False)))
        ctx = build_context(config, read_quota=read_quota)

    if action == "status":
        return _status(ctx, out)
    if action in ("fetch", "restore"):
        return _fetch(ctx, args.artifact, dest=getattr(args, "out", None), out=out)
    if action == "verify":
        return _verify(ctx, args.artifact, out=out)
    if action == "run":
        if getattr(args, "dry_run", False):
            return _run(ctx, out=out, dry_run=True)
        # Serialize state transitions across processes; never follow a lock-file symlink.
        import fcntl
        import os

        from .config import ensure_private_dir
        try:
            ensure_private_dir(ctx.manifest.path.parent)
            lock = os.open(ctx.manifest.path.parent / "run.lock",
                           os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return _run_with_retry(ctx, args, out=out)
            finally:
                os.close(lock)
        except (OSError, BlockingIOError):
            print("backup run: REFUSED - another run holds the lock or lock unavailable", file=out)
            return 2
    if action in ("check", "drill"):
        if getattr(args, "last", False):
            _last_drill(ctx, kind=getattr(args, "kind", "monthly"), out=out)
            return 0
        restic = None
        if getattr(args, "kind", "monthly") == "monthly" and isinstance(ctx.restorer, ResticRestorer):
            from .wp7_drill import ResticCheck

            restic = ResticCheck(ctx.restorer.repo, remote=ctx.backend.remote,
                                 path=ctx.backend.path, timeout=ctx.restorer.timeout)
        return _check(ctx, artifact=getattr(args, "artifact", None), restic=restic,
                      kind=getattr(args, "kind", "monthly"), out=out,
                      journal=_drill_journal(ctx) if action == "drill" or getattr(args, "record", False)
                      else None,
                      now=ctx.now, hash_only=action == "drill" and restic is None)
    if action == "watch":
        if getattr(args, "run_cold", False):
            if getattr(args, "root", None):
                print("backup watch: REFUSED - --run-cold uses the configured audio root", file=out)
                return 2
            # Evaluate age/size even if the directory watcher sees no new writes.
            from types import SimpleNamespace
            return backup_command(SimpleNamespace(backup_action="run", all_cold=True,
                                                   artifact=None, dry_run=False),
                                  config, out=out, ctx=ctx)
        return _watch(ctx, root=getattr(args, "root", None), out=out)
    print(f"backup: unknown action {action!r}", file=out)
    return 2
