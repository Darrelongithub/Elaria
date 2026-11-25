"""F24 pre-flights: headroom that PREVENTS, rather than an interruption that stops.

Spec v6 added two pre-flights and called them non-optional. They are the same idea in
two places: **check the space before you need it, and refuse rather than half-do it.**

1. **The remote headroom gate.** Before an operation that will write to the remote,
   read `remote_free` and compare it against the scratch that operation needs plus a
   margin. Below that, refuse to start. The capacity-floor knock must prevent, not
   interrupt: a knock that fires halfway through an upload has already cost the owner
   the upload, and a run that starts without knowing it can finish is the same
   silent-pass failure increment 4 exists to prevent.

2. **The local headroom gate.** Before a drill writes a restored artifact anywhere,
   check the local free space of the destination and name the required headroom in the
   record. A restore that fails at 90% because the disk filled has written a partial
   file and proved nothing.

Both gates name the numbers. A refusal that says "insufficient space" without saying
how much was needed and how much was there sends whoever reads it to measure it again.

PRIVACY
-------
Neither gate ever handles a path it does not need to. `local_free_bytes` takes a
directory, never an artifact, and nothing here returns or records a filename.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024

# The benchmark's own shape, taken from scripts/storage-benchmark.sh: a ~500 MB tree
# into each of two repos, so ~1 GB of synthetic upload, plus restic's temp space at
# pack_size x (backend connections + 1). At the ruled 128 MiB pack size and 4 backend
# connections that is 128 x 5 = 640 MiB. These are the benchmark's parameters, not
# invented ones, and they are what `bench_scratch_bytes` derives from.
BENCH_TREE_MIB = 500
BENCH_REPOS = 2
RESTIC_PACK_MIB = 128
RESTIC_BACKEND_CONNECTIONS = 4


def bench_scratch_bytes(*, pack_mib: int = RESTIC_PACK_MIB,
                        connections: int = RESTIC_BACKEND_CONNECTIONS) -> int:
    """Bytes the benchmark needs on the remote, derived rather than asserted.

    Two halves: the synthetic payload itself, and restic's temp space, which the tuning
    documentation gives as `pack size x (backend connections + 1)`. Both are the
    benchmark's own parameters, so the number a reader can check against the script.
    """
    payload = BENCH_TREE_MIB * MIB * BENCH_REPOS
    temp = pack_mib * (connections + 1) * MIB
    return payload + temp


@dataclass
class HeadroomDecision:
    """Whether there is room, and the numbers that decided it."""

    ok: bool
    reason: str
    free_bytes: int | None = None
    required_bytes: int = 0
    scratch_bytes: int = 0
    margin_bytes: int = 0

    def detail(self) -> str:
        """A path-blind one-line record of the decision. Safe for a journal or sensor."""
        free = "unknown" if self.free_bytes is None else str(self.free_bytes)
        return (f"headroom={'ok' if self.ok else 'REFUSED'}; reason={self.reason}; "
                f"free={free}; required={self.required_bytes} "
                f"(scratch={self.scratch_bytes} + margin={self.margin_bytes})")


def remote_headroom(remote_free_bytes: int | None, *,
                    scratch_bytes: int, margin_bytes: int) -> HeadroomDecision:
    """The remote gate. Refuses to proceed without a readable `remote_free`.

    An unknown `remote_free` is a refusal, not a pass. A gate that waves through a
    reading it never got is the failure this module exists to prevent, and it is the
    same posture as a missing restic being a declared skip rather than a pass.
    """
    required = scratch_bytes + margin_bytes
    if remote_free_bytes is None:
        return HeadroomDecision(ok=False, reason="remote_free unreadable",
                                free_bytes=None, required_bytes=required,
                                scratch_bytes=scratch_bytes, margin_bytes=margin_bytes)
    if remote_free_bytes < required:
        return HeadroomDecision(ok=False, reason="below scratch-plus-margin headroom",
                                free_bytes=remote_free_bytes, required_bytes=required,
                                scratch_bytes=scratch_bytes, margin_bytes=margin_bytes)
    return HeadroomDecision(ok=True, reason="headroom sufficient",
                            free_bytes=remote_free_bytes, required_bytes=required,
                            scratch_bytes=scratch_bytes, margin_bytes=margin_bytes)


def local_free_bytes(directory: str | Path) -> int | None:
    """Free bytes on the filesystem holding `directory`. None when unreadable.

    Takes a directory, never an artifact: the gate needs the filesystem, not the file.
    """
    try:
        return shutil.disk_usage(Path(directory)).free
    except OSError:
        return None


def restore_headroom_bytes(artifact_size: int, *, margin_bytes: int) -> int:
    """Bytes a restore needs locally: the artifact itself, plus a margin.

    The margin is not padding. A restore that lands with a few kilobytes to spare has
    left no room for the filesystem's own bookkeeping, and a partial write is worse
    than no write because it looks like a result.
    """
    if artifact_size < 0:
        raise ValueError(f"artifact size cannot be negative: {artifact_size}")
    return artifact_size + margin_bytes


def local_headroom(directory: str | Path, *, required_bytes: int,
                   artifact_bytes: int = 0,
                   margin_bytes: int = 0) -> HeadroomDecision:
    """The local gate. Refuses to start a restore without the room for it.

    `artifact_bytes` and `margin_bytes` are recorded so the decision's `detail()` says
    what the requirement was built from. A record reading `required=N (scratch=0 +
    margin=0)` names the total but not its derivation, which sends whoever reads it to
    work it out again.
    """
    free = local_free_bytes(directory)
    if free is None:
        return HeadroomDecision(ok=False, reason="local free space unreadable",
                                free_bytes=None, required_bytes=required_bytes,
                                scratch_bytes=artifact_bytes, margin_bytes=margin_bytes)
    if free < required_bytes:
        return HeadroomDecision(ok=False, reason="below local restore headroom",
                                free_bytes=free, required_bytes=required_bytes,
                                scratch_bytes=artifact_bytes, margin_bytes=margin_bytes)
    return HeadroomDecision(ok=True, reason="local headroom sufficient",
                            free_bytes=free, required_bytes=required_bytes,
                            scratch_bytes=artifact_bytes, margin_bytes=margin_bytes)


@dataclass
class PreflightReport:
    """What both gates said, in the order they were asked."""

    remote: HeadroomDecision | None = None
    local: HeadroomDecision | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        for gate in (self.remote, self.local):
            if gate is not None and not gate.ok:
                return False
        return True

    def detail(self) -> str:
        parts = []
        if self.remote is not None:
            parts.append(f"remote[{self.remote.detail()}]")
        if self.local is not None:
            parts.append(f"local[{self.local.detail()}]")
        parts.extend(self.notes)
        return "; ".join(parts)
