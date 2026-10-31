"""WP7 increment 2 — reconcile-on-start and the three crash points.

Each test kills the sequence at a specific point by leaving the manifest and the
filesystem in the state a crash would leave them, then asserts reconcile finishes it
safely. Nothing here uses restic, rclone, MEGA or a real trash directory: the remote
verifier and the trim mover are injected, and the clock is fake.

The tests that matter most are the ones asserting reconcile *refuses* — a flip asserted
without a confirmed remote copy is the failure this module exists to prevent, so a
missing verifier must defer rather than guess.
"""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from assistant.backup import plan_reconcile, reconcile, reconcile_all
from assistant.storage import (
    FLIPPED,
    LOCAL,
    PURGED,
    TRASHED,
    UPLOADED,
    ManifestRecord,
    StorageManifest,
)

NOW = datetime(2026, 10, 31, 12, 0, 0, tzinfo=UTC)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _man(tmp_path):
    return StorageManifest(tmp_path / "backup" / "manifest.jsonl")


def _write(path: Path, payload: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    from assistant.safety import try_sha256_file
    return try_sha256_file(path)


# -- crash point 1: killed between upload and flip ---------------------------

def test_crash_between_upload_and_flip_completes_the_flip(tmp_path):
    """The manifest says uploaded; the flip never landed. Reconcile finishes it."""
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    sha = _write(art, b"synthetic-audio-bytes")
    man.append(ManifestRecord(artifact=str(art), state=LOCAL, sha256=sha, size=21))
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=sha, size=21))

    seen = []

    def verify(path):
        seen.append(path)
        return True

    plan = plan_reconcile(man, now=NOW, verify_remote=verify)
    assert len(plan.actions) == 1
    assert plan.actions[0].from_state == UPLOADED
    assert plan.actions[0].to_state == FLIPPED
    assert plan.problems == []
    assert seen == [str(art)], "reconcile must actually re-verify, not assume"

    reconcile(man, plan)
    assert man.state_of(art) == FLIPPED


def test_flip_is_refused_when_local_hash_drifts(tmp_path):
    """A changed local file means the recorded upload no longer describes reality."""
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    sha = _write(art, b"original")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=sha, size=8))
    art.write_bytes(b"tampered")  # same path, different bytes

    plan = plan_reconcile(man, now=NOW, verify_remote=lambda p: True)
    assert plan.actions == []
    assert len(plan.problems) == 1
    assert "hash" in plan.problems[0]
    assert man.state_of(art) == UPLOADED, "nothing was recorded"


def test_flip_is_refused_when_remote_does_not_confirm(tmp_path):
    """The remote is the only other copy. If it is not there, do not flip."""
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    sha = _write(art, b"bytes")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=sha, size=5))

    plan = plan_reconcile(man, now=NOW, verify_remote=lambda p: False)
    assert plan.actions == []
    assert "remote" in plan.problems[0]
    assert man.state_of(art) == UPLOADED


def test_flip_is_refused_when_no_verifier_is_configured(tmp_path):
    """No verifier means no confirmation. Deferring is the safe answer, not guessing.

    This is the posture increment 2 must hold before increment 4 supplies a real remote:
    without one, an `uploaded` artifact is left exactly where the crash left it.
    """
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    sha = _write(art, b"bytes")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=sha, size=5))

    plan = plan_reconcile(man, now=NOW)
    assert plan.actions == []
    assert "no remote verifier" in plan.problems[0]
    assert man.state_of(art) == UPLOADED


def test_flip_is_refused_when_local_artifact_vanished(tmp_path):
    man = _man(tmp_path)
    art = tmp_path / "gone.wav"
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED,
                              sha256="ab" * 32, size=5))
    plan = plan_reconcile(man, now=NOW, verify_remote=lambda p: True)
    assert plan.actions == []
    assert "missing" in plan.problems[0]


# -- crash point 2: killed between flip and trim ------------------------------

def test_crash_between_flip_and_trim_plans_the_trim(tmp_path):
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=FLIPPED, sha256="ab" * 32))

    plan = plan_reconcile(man, now=NOW)
    assert [(a.from_state, a.to_state) for a in plan.actions] == [(FLIPPED, TRASHED)]


def test_trim_is_idempotent(tmp_path):
    """Running reconcile twice must not move the artifact twice.

    Idempotency is structural: the state machine has no `trashed -> trashed` edge, so once
    an artifact is trashed no further trim is ever planned.
    """
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=FLIPPED, sha256="ab" * 32))

    moved = []

    def mover(path):
        moved.append(path)
        return tmp_path / "trash" / path.name

    reconcile(man, plan_reconcile(man, now=NOW), trim_mover=mover)
    assert len(moved) == 1
    assert man.state_of(art) == TRASHED

    second = reconcile(man, plan_reconcile(man, now=NOW), trim_mover=mover)
    assert len(moved) == 1, "a second run must not move it again"
    assert second.actions == []
    assert man.state_of(art) == TRASHED


def test_trim_without_a_mover_defers_rather_than_lying(tmp_path):
    """No mover configured: report it, do not silently claim the trim happened."""
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=FLIPPED, sha256="ab" * 32))
    plan = reconcile(man, plan_reconcile(man, now=NOW))
    assert man.state_of(art) == FLIPPED, "state must not advance without the move"
    assert any("no trim mover" in p for p in plan.problems)


def test_trim_failure_leaves_the_flip_durable(tmp_path):
    """A failed move must not roll back the flip — the decision already landed."""
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=FLIPPED, sha256="ab" * 32))

    def boom(path):
        raise OSError("disk full")

    plan = reconcile(man, plan_reconcile(man, now=NOW), trim_mover=boom)
    assert man.state_of(art) == FLIPPED
    assert any("trim failed" in p for p in plan.problems)


# -- crash point 3: the flip is durable before any trim ----------------------

def test_flip_is_fsynced_before_the_trim_mover_runs(tmp_path):
    """The ordering the spec demands, proved by observation order.

    The mover records what the manifest says at the moment it is called. If the flip were
    not durable first, the mover would still see `uploaded`. Startup runs to quiescence,
    so this exercises the real multi-pass path rather than a single step.
    """
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    sha = _write(art, b"bytes")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=sha, size=5))

    observed = []
    reconcile_all(man, now=NOW, verify_remote=lambda p: True,
                  trim_mover=lambda p: observed.append(man.state_of(p)) or p)
    assert observed == [FLIPPED], "the trim must see the flip already durable"
    assert man.state_of(art) == TRASHED


def test_one_pass_advances_at_most_one_state(tmp_path):
    """A single pass must not skip a verification step.

    This is why startup loops instead of advancing several states at once: a crash
    mid-reconcile then leaves every artifact at most one step further on, with each step
    separately verified before the next is attempted.
    """
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    sha = _write(art, b"bytes")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=sha, size=5))

    first = plan_reconcile(man, now=NOW, verify_remote=lambda p: True)
    assert [(a.from_state, a.to_state) for a in first.actions] == [(UPLOADED, FLIPPED)]
    reconcile(man, first)
    assert man.state_of(art) == FLIPPED

    second = plan_reconcile(man, now=NOW)
    assert [(a.from_state, a.to_state) for a in second.actions] == [(FLIPPED, TRASHED)]


def test_ordering_holds_across_a_fresh_process(tmp_path):
    """A cold reader must see the flip before the trim — durability, not memory."""
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    sha = _write(art, b"bytes")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=sha, size=5))

    reconcile_all(man, now=NOW, verify_remote=lambda p: True,
                  trim_mover=lambda p: p)
    # re-open cold: a brand-new manifest object reading the same file
    cold = StorageManifest(man.path)
    assert cold.state_of(art) == TRASHED


def test_reconcile_all_reaches_quiescence(tmp_path):
    """Startup terminates, and a second startup finds nothing to do."""
    man = _man(tmp_path)
    for i in range(3):
        art = tmp_path / f"a{i}.wav"
        sha = _write(art, f"bytes-{i}".encode())
        man.append(ManifestRecord(artifact=str(art), state=UPLOADED,
                                  sha256=sha, size=7))
    plan = reconcile_all(man, now=NOW, verify_remote=lambda p: True,
                         trim_mover=lambda p: p)
    assert plan.problems == []
    assert all(man.state_of(tmp_path / f"a{i}.wav") == TRASHED for i in range(3))
    again = reconcile_all(man, now=NOW, verify_remote=lambda p: True,
                          trim_mover=lambda p: p)
    assert again.actions == []
    assert again.problems == []


# -- grace and purge ---------------------------------------------------------

def test_grace_running_means_two_copies_and_no_action(tmp_path):
    """Inside the grace the artifact has two copies. Silence is the invariant holding."""
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=TRASHED,
                              ts=_iso(NOW - timedelta(days=3))))
    plan = plan_reconcile(man, now=NOW, grace_days=14)
    assert plan.actions == []
    assert plan.problems == []


def test_grace_elapsed_purges(tmp_path):
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=TRASHED,
                              ts=_iso(NOW - timedelta(days=15))))
    plan = plan_reconcile(man, now=NOW, grace_days=14)
    assert [(a.from_state, a.to_state) for a in plan.actions] == [(TRASHED, PURGED)]
    reconcile(man, plan)
    assert man.state_of(art) == PURGED


def test_purge_is_terminal_and_never_replanned(tmp_path):
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=PURGED, ts=_iso(NOW)))
    for _ in range(3):
        plan = plan_reconcile(man, now=NOW + timedelta(days=400), grace_days=14)
        assert plan.actions == []
    assert man.state_of(art) == PURGED


# -- privacy fence -----------------------------------------------------------

def test_plan_summary_carries_no_paths(tmp_path):
    """The plan names artifacts so it can act; the summary must not."""
    man = _man(tmp_path)
    for name in ("secret-owner.wav", "private.wav"):
        art = tmp_path / name
        man.append(ManifestRecord(artifact=str(art), state=FLIPPED,
                                  sha256="ab" * 32))
    plan = plan_reconcile(man, now=NOW)
    blob = str(plan.summary())
    for name in ("secret-owner", "private", "wav"):
        assert name not in blob
    assert plan.summary()["actions"] == 2


# -- correct no-ops ----------------------------------------------------------

def test_absent_manifest_reconciles_to_nothing(tmp_path):
    man = _man(tmp_path)
    plan = plan_reconcile(man, now=NOW, verify_remote=lambda p: True)
    assert plan.actions == []
    assert plan.problems == []
    assert plan.summary() == {"actions": 0, "problems": 0, "by_transition": {}}


def test_local_artifact_is_left_alone(tmp_path):
    """`local` is the normal first-run state. Reconcile must not touch it."""
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=LOCAL, sha256="ab" * 32))
    plan = plan_reconcile(man, now=NOW, verify_remote=lambda p: True)
    assert plan.actions == []
    assert plan.problems == []
    assert man.state_of(art) == LOCAL


def test_manifest_file_is_owner_only(tmp_path):
    man = _man(tmp_path)
    art = tmp_path / "a.wav"
    man.append(ManifestRecord(artifact=str(art), state=FLIPPED, sha256="ab" * 32))
    assert os.stat(man.path).st_mode & 0o777 == 0o600
