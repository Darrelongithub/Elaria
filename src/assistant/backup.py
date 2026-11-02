"""WP7 cold storage & backup — reconcile-on-start and the crash-point contract (increment 2).

A backup that is only correct when nothing goes wrong is not a backup. This module is the
recovery half of the manifest's state machine: given a manifest left mid-sequence by a
crash, it works out what was in flight and finishes it *safely*.

The three crash points the spec names, and how each is handled:

1. **Killed between upload and flip.** The manifest says `uploaded`; the flip never
   landed. Reconcile **re-verifies** — the local file must still exist and hash to the
   recorded sha256, and the remote must confirm it holds the artifact — and only then
   appends `flipped`. A verification failure defers the flip and records a problem; it
   never guesses.
2. **Killed between flip and trim.** The manifest says `flipped`; the trim never ran.
   Reconcile plans the trim. Running it twice is safe because the state machine has no
   `trashed -> trashed` edge — once an artifact is `trashed` no further trim is ever
   planned. **Idempotency is structural, not a flag someone has to remember to check.**
3. **Flip must be fsync'd before any trim.** `StorageManifest.append()` fsyncs before it
   returns, and `reconcile()` appends the flip *before* it calls the trim mover. So the
   durable decision always precedes the destructive-ish step.

The verification edges are **injected**, not imported. `verify_remote` and `trim_mover`
are callables the caller supplies, which is what lets every crash point be tested against
a local fixture with no restic, no rclone and no MEGA — and what stops this module from
reaching for a network it has no business reaching on its own.

PRIVACY FENCE: a plan names artifacts by path because it has to act on them, but
`ReconcilePlan.summary()` is path-blind for exactly the reason `StorageManifest.summary()`
is — counts, states and sizes may leave the laptop; names may not. No path is ever written
to a log line, a sensor event, a report, a PR or a chat message.

Evidence tags: [TESTED-ONLY] throughout. Every crash point below is pinned by a test
against synthetic fixtures and injected fakes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .cost import iso_now
from .safety import try_sha256_file
from .storage import FLIPPED, PURGED, TRASHED, UPLOADED, StorageManifest

__all__ = ["ReconcileAction", "ReconcilePlan", "plan_reconcile", "reconcile",
           "reconcile_all"]

# A single pass advances each artifact by at most one state. The states are finite and
# monotonic (local -> uploaded -> flipped -> trashed -> purged), so quiescence is reached
# in at most len(ManifestState.ALL) passes; the bound exists only so a logic error cannot
# spin forever.
_MAX_PASSES = 8


@dataclass
class ReconcileAction:
    """One thing reconcile intends to do, and why.

    `artifact` is the **manifest key** — the path the journal records state under, and the
    path the artifact had when it was HOT. `target` is the **filesystem path to act on**,
    which differs once a trim has moved the file: after a trim the artifact lives in trash
    under a stamped name, and a purge that targets the manifest key would look for a file
    that is no longer there and silently do nothing while the manifest recorded `purged`.

    Both stay inside this process — `summary()` is the only shape allowed to leave it.
    """

    artifact: str
    from_state: str
    to_state: str
    reason: str
    target: str = ""


@dataclass
class ReconcilePlan:
    """What reconcile found and what it intends. Nothing has happened yet."""

    actions: list[ReconcileAction] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        """Path-blind aggregate: how many of what, and why. Never which."""
        by_transition: dict[str, int] = {}
        for action in self.actions:
            key = f"{action.from_state}->{action.to_state}"
            by_transition[key] = by_transition.get(key, 0) + 1
        return {"actions": len(self.actions), "problems": len(self.problems),
                "by_transition": by_transition}


def plan_reconcile(manifest: StorageManifest, *, now,
                   verify_remote=None,
                   grace_days: int = 14) -> ReconcilePlan:
    """Work out what a crashed run left in flight. Pure analysis — changes nothing.

    `now` is injectable so tests use a fake clock and never sleep. `verify_remote` is a
    callable taking an artifact path and returning whether the remote holds it; it is
    REQUIRED to complete an `uploaded -> flipped` transition, because a flip asserted
    without a confirmed remote copy is exactly the failure this module exists to prevent.
    """

    plan = ReconcilePlan()
    for artifact, record in sorted(manifest.current().items()):
        state = record.state

        if state == UPLOADED:
            # Crash point 1: the upload was recorded, the flip never landed.
            path = Path(artifact)
            if not path.exists():
                plan.problems.append(
                    f"{state}: local artifact is missing; cannot hash-verify, "
                    f"flip deferred")
                continue
            actual = try_sha256_file(path)
            if record.sha256 and actual != record.sha256:
                plan.problems.append(
                    f"{state}: local hash does not match the manifest record; "
                    f"flip deferred")
                continue
            if verify_remote is None:
                plan.problems.append(
                    f"{state}: no remote verifier configured; flip deferred "
                    f"rather than asserted")
                continue
            if not verify_remote(artifact):
                plan.problems.append(
                    f"{state}: remote does not confirm the artifact; flip deferred")
                continue
            plan.actions.append(ReconcileAction(
                artifact, UPLOADED, FLIPPED,
                "re-verified local hash and remote copy; completing the flip"))

        elif state == FLIPPED:
            # Crash point 2: the flip landed, the trim never ran.
            plan.actions.append(ReconcileAction(
                artifact, FLIPPED, TRASHED,
                "flip is durable; trim was interrupted and is safe to re-run"))

        elif state == TRASHED:
            # Grace elapsed: the only path to a single copy, and only after the grace.
            try:
                elapsed = (now - _parse_ts(record.ts)).days
            except (TypeError, ValueError):
                plan.problems.append(f"{state}: unreadable timestamp; purge deferred")
                continue
            if elapsed >= grace_days:
                plan.actions.append(ReconcileAction(
                    artifact, TRASHED, PURGED,
                    f"grace elapsed ({elapsed}d >= {grace_days}d)",
                    target=_trashed_as(record.detail) or artifact))
            # else: grace still running. Two copies remain. Nothing to do — and that
            # silence is the copy-count invariant holding, not a missed action.

    return plan


def reconcile(manifest: StorageManifest, plan: ReconcilePlan, *, now=None,
              trim_mover=None, purge_mover=None) -> ReconcilePlan:
    """Apply a plan. The flip is always fsync'd before the trim mover is called.

    `trim_mover` takes an artifact path and returns its trash location; `purge_mover` takes
    a trashed path and removes it. Both are injected so tests never touch a real trash dir
    and no filesystem change happens implicitly. When either is None that step is planned
    but not performed, which is the correct no-remote posture.

    `now` is the clock the plan was computed against, and records written here are stamped
    with it. It must be the same clock `plan_reconcile` used, or a grace period would be
    measured against one time and recorded against another — which is exactly the kind of
    split that makes a 14-day grace silently become 13 or 15.

    Returns the plan with any newly discovered problems appended, so a caller can report
    what actually happened rather than what was intended.
    """

    for action in plan.actions:
        if action.to_state == FLIPPED:
            # append() fsyncs before returning, so this decision is durable before
            # anything destructive is attempted.
            ok = manifest.append(
                _record_for(manifest, action, now=now), expect_from=UPLOADED)
            if not ok:
                plan.problems.append(
                    f"{action.from_state}: flip refused by the state machine; "
                    f"left for the next run")
        elif action.to_state == TRASHED:
            if trim_mover is None:
                plan.problems.append(
                    f"{action.from_state}: no trim mover configured; trim deferred")
                continue
            try:
                trashed_as = trim_mover(Path(action.target or action.artifact))
            except OSError as exc:
                plan.problems.append(
                    f"{action.from_state}: trim failed ({type(exc).__name__}); "
                    f"flip remains durable and the next run retries")
                continue
            record = _record_for(manifest, action, now=now)
            if trashed_as is not None:
                # Record where the file went. Without this the purge has no way to find
                # it: the manifest key is the HOT path, and the file is no longer there.
                record.detail = f"{record.detail}; trashed_as={trashed_as}"
            manifest.append(record, expect_from=FLIPPED)
        elif action.to_state == PURGED:
            # The grace has elapsed, so the remote is now the only copy that should
            # remain. The purge is recorded only once the file is actually gone, so the
            # manifest never claims a purge that did not happen.
            if purge_mover is None:
                plan.problems.append(
                    f"{action.from_state}: no purge mover configured; purge deferred")
                continue
            where = Path(action.target or action.artifact)
            try:
                gone = purge_mover(where)
            except OSError as exc:
                plan.problems.append(
                    f"{action.from_state}: purge failed ({type(exc).__name__}); "
                    f"remote copy is unaffected, next run retries")
                continue
            if gone is False:
                # The mover says the target was already absent. The goal — the file is
                # gone — is met, so the state advances, but it is reported rather than
                # passed over in silence.
                plan.problems.append(
                    f"{action.from_state}: purge target was already absent")
            manifest.append(_record_for(manifest, action, now=now),
                            expect_from=TRASHED)
    return plan


def _record_for(manifest: StorageManifest, action: ReconcileAction, *, now=None):
    """A new record for the transition, carrying the artifact's existing facts forward.

    Stamped with `now` when the caller supplies it, so a grace period is measured and
    recorded against one clock. Left to the real clock only when no clock was injected.
    """
    current = manifest.current().get(action.artifact)
    from .storage import ManifestRecord
    return ManifestRecord(
        artifact=action.artifact,
        state=action.to_state,
        ts=now.isoformat(timespec="seconds") if now is not None else iso_now(),
        sha256=current.sha256 if current else None,
        size=current.size if current else None,
        tier=current.tier if current else None,
        detail=action.reason,
    )


def _trashed_as(detail: str) -> str:
    """Where the trim mover said it put the file, or "" if it never said.

    Parsed out of the `trashed` record's detail. This is the only place the trash location
    is recovered from, and it is why `reconcile()` records it in the first place.
    """

    for part in (detail or "").split("; "):
        if part.startswith("trashed_as="):
            return part[len("trashed_as="):]
    return ""


def _parse_ts(value: str):
    from datetime import datetime
    return datetime.fromisoformat(value)


def reconcile_all(manifest: StorageManifest, *, now, verify_remote=None,
                  trim_mover=None, purge_mover=None,
                  grace_days: int = 14) -> ReconcilePlan:
    """Run reconcile to quiescence. This is what startup calls.

    One pass advances each artifact by at most **one** state, and that is deliberate: a
    crash mid-reconcile then leaves every artifact at most one step further on, with each
    step separately verified before the next is attempted. Advancing several states in one
    pass would mean a single crash could skip a verification.

    The loop therefore re-plans after every pass and stops when nothing is left to do.
    Problems are accumulated across passes so a caller reports everything that needed
    attention, not just the last pass's findings.
    """

    combined = ReconcilePlan()
    for _ in range(_MAX_PASSES):
        plan = plan_reconcile(manifest, now=now, verify_remote=verify_remote,
                              grace_days=grace_days)
        combined.problems.extend(plan.problems)
        if not plan.actions:
            return combined
        reconcile(manifest, plan, now=now, trim_mover=trim_mover,
                  purge_mover=purge_mover)
        combined.actions.extend(plan.actions)
        combined.problems.extend(
            p for p in plan.problems if p not in combined.problems)
    combined.problems.append(
        f"reconcile did not reach quiescence in {_MAX_PASSES} passes; "
        f"stopping rather than looping")
    return combined
