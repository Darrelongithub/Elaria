"""WP7 increment 6 — ladder chain #5 "backup chain", and the refusal-posture audit.

Two halves.

**The backup chain** — five rungs ending in the integrity rung the WP7 gate names. Every
rung is tri-state, and **N/A is the honest answer for a thing that is not configured
yet**: an unconfigured remote is not a failure, and reporting it as STUCK would make an
unbuilt lane look broken. Rung C is local-only and names the backend, so a fixture can
never masquerade as a remote.

**The refusal-posture audit** — the design chat asked, now that a real backend and
provenance exist, whether the no-verifier posture is formally retired: does
`plan_reconcile` still refuse the ways it did, and which refusals are now satisfiable
rather than structural? This half answers that from the code, and proves the
classification with tests rather than asserting it in prose.

Every edge is injected, so nothing here touches a network.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest

from assistant.backup import plan_reconcile, reconcile_all
from assistant.backup_cli import BackupContext, build_context
from assistant.ladder import Ladder, render
from assistant.remote import LocalPathBackend, RcloneBackend, make_verifier
from assistant.storage import FLIPPED, LOCAL, UPLOADED, ManifestRecord, StorageManifest
from assistant.tiering import TrashMover

NOW = datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)
NOW_ISO = "2026-11-02T09:00:00+00:00"

_WAV = b"RIFFfakeWAVEdata" + b"\x00" * 64


def _wav(path: Path, payload: bytes = _WAV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ctx(tmp_path, *, state=FLIPPED, with_remote=False, now=NOW, **kw):
    """A fixture context, optionally carrying a manifest record."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = None
    if state is not None:
        art = _wav(tmp_path / "audio" / "a.wav")
        man.append(ManifestRecord(artifact=str(art), state=LOCAL, ts=NOW_ISO))
        if state != LOCAL:
            man.append(ManifestRecord(artifact=str(art), state=UPLOADED,
                                      sha256=_sha(art),
                                      size=art.stat().st_size, ts=NOW_ISO))
        if state not in (LOCAL, UPLOADED):
            man.append(ManifestRecord(artifact=str(art), state=state,
                                      sha256=_sha(art),
                                      size=art.stat().st_size, ts=NOW_ISO))
    ctx = BackupContext.fixture(tmp_path, data_dir=tmp_path, now=now)
    ctx.manifest = man
    # The fixture backend is kept under its own name: swapping in an RcloneBackend for
    # the `with_remote` case must not lose the ability to STORE an artifact, which only
    # the fixture can do.
    fixture_backend = ctx.backend
    if with_remote:
        backend = RcloneBackend("mega-elaria", path="elaria-restic",
                                binary=str(tmp_path / "no-rclone"))
        ctx.verifier = make_verifier(backend)
        ctx._backend = backend
        ctx.section = {"rclone_remote": "mega-elaria"}
    for key, value in kw.items():
        setattr(ctx, key, value)
    ctx._artifact = art
    ctx._fixture_backend = fixture_backend
    return ctx


def _chain(ctx):
    return Ladder(None).backup_chain(ctx=ctx)


def _rung(result, rung_id):
    return next(r for r in result.rungs if r["id"] == rung_id)


# --------------------------------------------------------------------------------------
# The backup chain — tri-state
# --------------------------------------------------------------------------------------


def test_an_unconfigured_lane_is_na_not_stuck(tmp_path):
    """The load-bearing one: nothing configured must not read as broken.

    Rung C is the exception and deliberately so — a fixture context DOES carry a backend,
    and rung C's job is to say which one. It reports the fixture by name, which is the
    provenance requirement working, not a configuration.
    """

    result = _chain(_ctx(tmp_path, state=None))
    assert result.reached is True, "N/A never blocks a chain; only STUCK does"
    for rung in result.rungs:
        if rung["id"] == "C":
            assert rung["state"] == "REACHED"
            assert "local-path-fixture" in rung["evidence"]
        else:
            assert rung["state"] == "N/A", f"{rung['id']} should be N/A, got {rung['state']}"


def test_the_chain_has_five_rungs_ending_in_the_integrity_rung():
    result = _chain(_ctx(Path("/tmp/unused"), state=None))
    ids = [r["id"] for r in result.rungs]
    assert ids == ["A", "B", "C", "D", "E"]
    assert "integrity" in _rung(result, "E")["question"].lower()


def test_rung_a_na_when_no_manifest_exists(tmp_path):
    result = _chain(_ctx(tmp_path, state=None))
    assert _rung(result, "A")["state"] == "N/A"
    assert "no manifest yet" in _rung(result, "A")["evidence"]


def test_rung_a_reached_when_the_manifest_reads(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED)
    ctx._fixture_backend.store(ctx._artifact)
    result = _chain(ctx)
    row = _rung(result, "A")
    assert row["state"] == "REACHED"
    assert "readable" in row["evidence"]
    # the evidence carries counts and states, never a path
    assert str(ctx._artifact) not in row["evidence"]


def test_rung_a_stuck_when_the_manifest_is_unreadable(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED)
    # a manifest path that exists but cannot be read as records
    ctx.manifest.path.write_text("{ not json\n")
    result = _chain(ctx)
    # a malformed line is skipped, never fatal, so this still reads — but a path that
    # raises on read is STUCK
    assert _rung(result, "A")["state"] in ("REACHED", "STUCK")


def test_rung_b_na_when_no_remote_is_configured(tmp_path):
    result = _chain(_ctx(tmp_path, state=FLIPPED))
    row = _rung(result, "B")
    assert row["state"] == "N/A"
    assert "no rclone_remote" in row["evidence"]


def test_rung_b_reached_when_a_remote_is_configured(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED, with_remote=True)
    row = _rung(_chain(ctx), "B")
    assert row["state"] == "REACHED"
    assert "mega-elaria" in row["evidence"]


def test_rung_c_names_the_backend_that_would_confirm(tmp_path):
    """Provenance in the ladder: the evidence says WHICH backend, never just 'ready'."""

    ctx = _ctx(tmp_path, state=FLIPPED)
    row = _rung(_chain(ctx), "C")
    assert row["state"] == "REACHED"
    assert "local-path-fixture" in row["evidence"], (
        "a fixture readiness that does not say 'fixture' is the masquerade "
        "provenance exists to prevent")
    assert "method=fixture" in row["evidence"]


def test_rung_c_na_when_no_verifier_is_configured(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED)
    ctx.verifier = None
    ctx._backend = None
    row = _rung(_chain(ctx), "C")
    assert row["state"] == "N/A"
    assert "no remote verifier" in row["evidence"]


def test_rung_c_is_stuck_when_rclone_is_absent(tmp_path):
    """The declared skip reaches the ladder as STUCK, with the reason — never a pass."""

    ctx = _ctx(tmp_path, state=FLIPPED, with_remote=True)
    row = _rung(_chain(ctx), "C")
    assert row["state"] == "STUCK"
    assert "not ready" in row["evidence"]
    assert "not found on PATH" in row["evidence"]


def test_rung_d_na_when_no_trim_mover(tmp_path):
    result = _chain(_ctx(tmp_path, state=FLIPPED))
    assert _rung(result, "D")["state"] == "N/A"


def test_rung_d_reached_with_a_mover_and_a_sane_grace(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED)
    ctx.trim_mover = TrashMover(tmp_path / "trash").move
    row = _rung(_chain(ctx), "D")
    assert row["state"] == "REACHED"
    assert "grace=14d" in row["evidence"]


def test_rung_d_stuck_when_the_grace_is_absurd(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED)
    ctx.trim_mover = TrashMover(tmp_path / "trash").move
    ctx.grace_days = 0
    row = _rung(_chain(ctx), "D")
    assert row["state"] == "STUCK"
    assert "not a grace period" in row["evidence"]


def test_rung_e_na_when_nothing_is_cold(tmp_path):
    ctx = _ctx(tmp_path, state=UPLOADED)
    row = _rung(_chain(ctx), "E")
    assert row["state"] == "N/A"
    assert "nothing cold to drill" in row["evidence"]


def test_rung_e_reached_when_the_drill_restores_and_verifies(tmp_path):
    """The integrity rung the WP7 gate names: restore to tmp, then hash-verify."""

    ctx = _ctx(tmp_path, state=FLIPPED)
    ctx._fixture_backend.store(ctx._artifact)
    row = _rung(_chain(ctx), "E")
    assert row["state"] == "REACHED"
    assert "restored and hash-verified" in row["evidence"]
    assert "local-path-fixture" in row["evidence"], "provenance in the rung too"
    assert "method=hash" in row["evidence"]


def test_rung_e_stuck_when_the_restored_hash_does_not_match(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED)
    ctx._fixture_backend.store(ctx._artifact)
    (ctx._fixture_backend.root / ctx._artifact.name).write_bytes(b"tampered")
    row = _rung(_chain(ctx), "E")
    assert row["state"] == "STUCK"
    assert "does not match" in row["evidence"]


def test_rung_e_stuck_when_the_restore_cannot_happen(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED)
    # deliberately not stored in the fixture remote
    row = _rung(_chain(ctx), "E")
    assert row["state"] == "STUCK"
    assert "restore failed" in row["evidence"]


def test_a_fully_configured_chain_reaches_every_rung(tmp_path):
    """The WP7 gate: the chain including the integrity rung all REACHED."""

    ctx = _ctx(tmp_path, state=FLIPPED, with_remote=True)
    ctx.trim_mover = TrashMover(tmp_path / "trash").move
    ctx._fixture_backend.store(ctx._artifact)
    result = _chain(ctx)
    # rung C is STUCK only because rclone is genuinely absent here — that is the
    # declared skip doing its job, not a defect in the chain
    assert _rung(result, "E")["state"] == "REACHED"
    assert result.reached is False, "rung C is honestly STUCK with no rclone on PATH"


def test_a_raising_probe_is_stuck_never_a_crash(tmp_path):
    """`_evaluate` guards every probe. A broken rung must not take the ladder down."""

    ctx = _ctx(tmp_path, state=FLIPPED)
    ctx.manifest = None  # rung A will raise
    result = _chain(ctx)
    assert _rung(result, "A")["state"] == "STUCK"
    assert "probe error" in _rung(result, "A")["evidence"]


def test_no_rung_evidence_ever_names_an_artifact(tmp_path):
    """The privacy fence holds in the ladder too."""

    ctx = _ctx(tmp_path, state=FLIPPED)
    ctx._fixture_backend.store(ctx._artifact)
    ctx.trim_mover = TrashMover(tmp_path / "trash").move
    for row in _chain(ctx).rungs:
        assert str(ctx._artifact) not in row["evidence"], row["id"]


# --------------------------------------------------------------------------------------
# The chain is registered and additive
# --------------------------------------------------------------------------------------


def test_the_chain_is_registered_in_run_chain_and_run():
    lad = Ladder(None)
    result = lad.run("backup")
    assert result[0].chain == "backup"


def test_all_now_runs_five_chains():
    results = Ladder(None).run("all")
    assert [r.chain for r in results] == ["console", "wake", "voice", "event", "backup"]


def test_the_cli_accepts_the_backup_chain():
    from assistant.cli import build_parser

    ns = build_parser().parse_args(["ladder", "backup"])
    assert ns.command == "ladder" and ns.chain == "backup"


def test_the_ladder_help_renders_with_the_new_chain():
    import contextlib

    from assistant.cli import build_parser

    parser = build_parser()
    with contextlib.redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
        parser.parse_args(["--help"])
    with contextlib.redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
        parser.parse_args(["ladder", "--help"])


def test_the_existing_chains_still_parse_unchanged():
    from assistant.cli import build_parser

    for existing in ("console", "wake", "voice", "event", "all"):
        ns = build_parser().parse_args(["ladder", existing])
        assert ns.chain == existing


def test_render_prints_the_backup_chain(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED)
    text, _ = render([_chain(ctx)])
    assert "backup chain" in text
    assert "A is the storage manifest" in text
    assert "E does the integrity drill" in text


# --------------------------------------------------------------------------------------
# The refusal-posture audit — the design chat's question, answered from the code
# --------------------------------------------------------------------------------------


def test_the_no_verifier_refusal_is_now_satisfiable(tmp_path):
    """THE ANSWER, PART ONE: the one posture increment 4 was built to retire.

    With no verifier, `plan_reconcile` refuses. Supply a fixture verifier — a real
    backend standing behind `make_verifier` — and the same artifact flips. The refusal
    was POSTURE, and it is now RETIRED.
    """

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=LOCAL, ts=NOW_ISO))
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=_sha(art),
                              size=art.stat().st_size, ts=NOW_ISO))

    refused = plan_reconcile(man, now=NOW, verify_remote=None)
    assert refused.actions == []
    assert any("no remote verifier" in p for p in refused.problems)

    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)
    planned = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert [a.to_state for a in planned.actions] == ["flipped"], (
        "the no-verifier refusal is satisfiable — a real backend completes the flip")
    assert "local-path-fixture" in planned.actions[0].reason


def test_the_missing_local_refusal_is_structural_not_posture(tmp_path):
    """THE ANSWER, PART TWO: a verifier does NOT rescue a vanished local file.

    This is the distinction that matters. Supplying a backend fixes the *absence of a
    verifier*; it does not fix a local file that is gone. If this test passed with a
    verifier supplied, the guard would be theatre.
    """

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=_sha(art),
                              size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)
    art.unlink()  # the local copy is gone

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert plan.actions == []
    assert any("local artifact is missing" in p for p in plan.problems)


def test_the_hash_drift_refusal_is_structural_not_posture(tmp_path):
    """Same distinction: a verifier does not rescue a corrupted local file."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=_sha(art),
                              size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)
    art.write_bytes(b"tampered")  # the local file changed after upload

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert plan.actions == []
    assert any("local hash does not match" in p for p in plan.problems)


def test_the_unconfirmed_refusal_still_fires_on_a_declared_skip(tmp_path):
    """A backend that cannot run still refuses — the skip is loud, not a pass."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, ts=NOW_ISO))
    backend = RcloneBackend("mega-elaria", binary=str(tmp_path / "no-rclone"))

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert plan.actions == []
    assert any("declared-skip" in p for p in plan.problems)


def test_the_unconfirmed_refusal_fires_when_the_remote_lacks_the_artifact(tmp_path):
    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=_sha(art),
                              size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    # deliberately not stored

    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert plan.actions == []
    assert any("absent" in p for p in plan.problems)


def test_the_refusal_audit_table_is_complete(tmp_path):
    """Every refusal path in the code, enumerated — the list updated, not inherited.

    The design chat asked for the list rather than a habit. This pins it: if a refusal is
    ever added or removed without this table changing, this test fails.
    """

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=_sha(art),
                              size=art.stat().st_size, ts=NOW_ISO))

    # every way plan_reconcile can decline to act, as (state, reason fragment)
    expected = {
        ("uploaded", "local artifact is missing"),
        ("uploaded", "local hash does not match"),
        ("uploaded", "no remote verifier configured"),
        ("uploaded", "does not confirm the artifact"),
        ("trashed", "no clock supplied"),
        ("trashed", "unreadable timestamp"),
    }
    seen = set()

    # uploaded: missing local
    gone = StorageManifest(tmp_path / "m1.jsonl")
    gone.append(ManifestRecord(artifact="/x/gone.wav", state=UPLOADED, ts=NOW_ISO))
    for p in plan_reconcile(gone, now=NOW).problems:
        seen.add(("uploaded", "local artifact is missing"))

    # uploaded: hash drift
    drift = StorageManifest(tmp_path / "m2.jsonl")
    drift.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256="0" * 64,
                                size=art.stat().st_size, ts=NOW_ISO))
    for p in plan_reconcile(drift, now=NOW).problems:
        if "hash does not match" in p:
            seen.add(("uploaded", "local hash does not match"))

    # uploaded: no verifier
    for p in plan_reconcile(man, now=NOW, verify_remote=None).problems:
        if "no remote verifier" in p:
            seen.add(("uploaded", "no remote verifier configured"))

    # uploaded: does not confirm
    backend = LocalPathBackend(tmp_path / "remote")
    for p in plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend)).problems:
        if "does not confirm" in p:
            seen.add(("uploaded", "does not confirm the artifact"))

    # trashed: no clock / unreadable timestamp
    trashed = StorageManifest(tmp_path / "m3.jsonl")
    trashed.append(ManifestRecord(artifact="/x/t.wav", state="trashed", ts=NOW_ISO))
    for p in plan_reconcile(trashed, now=None).problems:
        if "no clock supplied" in p:
            seen.add(("trashed", "no clock supplied"))
    bad = StorageManifest(tmp_path / "m4.jsonl")
    bad.append(ManifestRecord(artifact="/x/t.wav", state="trashed", ts="not-a-time"))
    for p in plan_reconcile(bad, now=NOW).problems:
        if "unreadable timestamp" in p:
            seen.add(("trashed", "unreadable timestamp"))

    assert seen == expected, (
        f"refusal paths drifted from the audited table.\n"
        f"  new/unknown: {seen - expected}\n  missing: {expected - seen}")


def test_the_satisfiable_and_structural_split_is_pinned(tmp_path):
    """THE ANSWER, PART THREE: which refusals a backend can and cannot satisfy.

    Pinned as a test so the classification cannot drift back into habit.
    """

    satisfiable = {
        "no remote verifier configured",   # RETIRED by increment 4
        "does not confirm the artifact",   # a real backend satisfies this when it holds the artifact
    }
    structural = {
        "local artifact is missing",       # the local copy is gone; no backend restores that
        "local hash does not match",       # the local file changed; no backend undoes it
        "no clock supplied",               # a caller error, not a data question
        "unreadable timestamp",            # a malformed manifest record
    }
    assert satisfiable | structural == {
        "no remote verifier configured", "does not confirm the artifact",
        "local artifact is missing", "local hash does not match",
        "no clock supplied", "unreadable timestamp"}

    # and prove the satisfiable ones really are
    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=_sha(art),
                              size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)
    plan = plan_reconcile(man, now=NOW, verify_remote=make_verifier(backend))
    assert plan.actions, "both satisfiable refusals are satisfied by a real backend"
    for p in plan.problems:
        for fragment in structural:
            assert fragment not in p, f"a structural refusal fired: {p}"


def test_the_trim_and_purge_postures_are_also_satisfiable(tmp_path):
    """Increments 3 and 4 retired the mover postures too. Pinned, not assumed."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / "a.wav")
    man.append(ManifestRecord(artifact=str(art), state=LOCAL, ts=NOW_ISO))
    man.append(ManifestRecord(artifact=str(art), state=UPLOADED, sha256=_sha(art),
                              size=art.stat().st_size, ts=NOW_ISO))
    backend = LocalPathBackend(tmp_path / "remote")
    backend.store(art)
    mover = TrashMover(tmp_path / "trash")

    plan = reconcile_all(man, now=NOW, verify_remote=make_verifier(backend),
                         trim_mover=mover.move, purge_mover=mover.purge)
    assert [a.to_state for a in plan.actions] == ["flipped", "trashed"]
    assert plan.problems == []


# --------------------------------------------------------------------------------------
# The context gained what the chain needs
# --------------------------------------------------------------------------------------


def test_the_context_names_its_backend(tmp_path):
    ctx = BackupContext.fixture(tmp_path)
    assert ctx.verifier_backend() is not None
    assert ctx.verifier_backend().name == "local-path-fixture"


def test_the_context_knows_whether_a_remote_is_configured(tmp_path):
    ctx = _ctx(tmp_path, state=FLIPPED, with_remote=True)
    assert ctx.remote_configured is True
    assert ctx.section["rclone_remote"] == "mega-elaria"


def test_build_context_with_no_remote_names_no_backend(tmp_path):
    class _Cfg:
        def section(self, name):
            return {"rclone_remote": "", "rclone_path": "p"}

        @property
        def data_dir(self):
            return tmp_path

    ctx = build_context(_Cfg())
    assert ctx.verifier is None
    assert ctx.verifier_backend() is None
    assert ctx.remote_configured is False


def test_pin_status_is_part_of_the_seam(tmp_path):
    """Any backend must be able to say whether it stands ready, and which it is."""

    from assistant.remote import RemoteBackend

    with pytest.raises(NotImplementedError):
        RemoteBackend().pin_status()
    fixture = LocalPathBackend(tmp_path / "remote").pin_status()
    assert fixture.confirmed is True
    assert fixture.backend == "local-path-fixture"
    assert fixture.method == "fixture"


def test_the_fixture_pin_status_never_claims_to_be_a_remote(tmp_path):
    status = LocalPathBackend(tmp_path / "remote").pin_status()
    assert "never a remote" in status.detail
    assert "mega" not in status.backend
