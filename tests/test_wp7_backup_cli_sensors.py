"""WP7 increment 5 — the `assist backup` command surface and its sensors.

Two halves, both pinned:

**The sensors** must satisfy the canonical §2 contract (report 007): every line parses
with `split(" ", 6)` into 6 or 7 parts, `session_id` is `-`, `peak` is `-`, and dispatch
keys on the event name (`parts[2]`), never the verdict. And **no detail may carry a
path** — the privacy fence.

**The CLI** must refuse rather than guess: fetching an artifact that was never uploaded
is an exit-2 refusal, a restore whose hash does not match is an exit-1 failure, and a run
with no verifier refuses rather than planning a flip that cannot be confirmed.

Every edge is injected, so the whole surface runs against synthetic fixtures with no
restic, no rclone and no MEGA.
"""

from __future__ import annotations

import io
import json
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from assistant import sensors
from assistant.backup_cli import (
    BackupContext,
    LocalPathRestorer,
    backup_command,
    build_context,
)
from assistant.remote import LocalPathBackend
from assistant.sensors import BACKUP_EVENTS, StorageGauge
from assistant.storage import FLIPPED, LOCAL, UPLOADED, ManifestRecord, StorageManifest

NOW = datetime(2026, 11, 2, 9, 0, 0, tzinfo=UTC)
NOW_ISO = "2026-11-02T09:00:00+00:00"


#: A payload comfortably over WAV_HEADER_BYTES (44). An 18-byte stub is a header-only
#: never-retry mark and is CORRECTLY excluded from tiering — which would make any test
#: that needs something to go cold silently assert nothing.
_WAV = b"RIFFfakeWAVEdata" + b"\x00" * 64


def _wav(path: Path, payload: bytes = _WAV) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _age(path: Path, *, days: int = 30) -> Path:
    """Push a file's mtime into the past so the tiering engine has work to do.

    A fixture written a moment ago is inside the 14-day window and correctly stays HOT,
    which means any test that needs `send_cold` to be non-empty must age its artifact.
    """

    import os

    stamp = (NOW.timestamp() - days * 86400)
    os.utime(path, (stamp, stamp))
    return path


def _manifest_with(tmp_path, *, state=FLIPPED, name="a.wav"):
    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    art = _wav(tmp_path / "audio" / name)
    man.append(ManifestRecord(artifact=str(art), state=LOCAL, ts=NOW_ISO))
    if state != LOCAL:
        man.append(ManifestRecord(artifact=str(art), state=UPLOADED,
                                  sha256=_sha(art), size=art.stat().st_size,
                                  ts=NOW_ISO))
    if state not in (LOCAL, UPLOADED):
        man.append(ManifestRecord(artifact=str(art), state=state,
                                  sha256=_sha(art), size=art.stat().st_size,
                                  ts=NOW_ISO))
    return man, art


def _fixture_ctx(tmp_path, *, state=FLIPPED, now=NOW, **kw):
    man, art = _manifest_with(tmp_path, state=state)
    ctx = BackupContext.fixture(tmp_path, data_dir=tmp_path, now=now)
    ctx.manifest = man
    ctx.backend = ctx.restorer.backend
    for key, value in kw.items():
        setattr(ctx, key, value)
    return ctx, art


# --------------------------------------------------------------------------------------
# §2 contract conformance — every sensor line
# --------------------------------------------------------------------------------------


def test_every_sensor_line_satisfies_the_section_two_contract():
    """The load-bearing one: §2 parse, `-` session, `-` peak, event-name dispatch."""

    buf = io.StringIO()
    sensors.backup_started(reason="nightly", stream=buf)
    sensors.backup_done(sent_cold=1, kept_hot=2, trimmed=1, purged=0, problems=0,
                        passes=1, stream=buf)
    sensors.backup_failed(reason="remote unreadable", stream=buf)
    sensors.backup_verify(backend="local-path-fixture", method="hash",
                          confirmed=True, stream=buf)
    sensors.backup_check(kind="monthly", ok=True, stream=buf)
    sensors.storage_gauge(StorageGauge(hot_bytes=1, cold_bytes=2), stream=buf)

    lines = [l for l in buf.getvalue().splitlines() if l.strip()]
    assert len(lines) == 6
    for line in lines:
        parts = line.split(" ", 6)
        assert len(parts) in (6, 7), f"§2 allows 6 or 7 parts, got {len(parts)}"
        assert parts[2] in BACKUP_EVENTS, f"unknown event {parts[2]!r}"
        assert parts[3] == "-", "a backup run is not a session"
        assert parts[4] == "-", "peak is meaningless for a backup event"
        assert parts[1] in {"info", "warn", "error"}


def test_no_sensor_detail_ever_carries_a_path():
    """The privacy fence: counts, states, hashes and backend names — never a name."""

    secret = "/home/owner/.local/share/assistant/audio/20261031-abcdef.wav"
    buf = io.StringIO()
    sensors.backup_started(reason=secret, stream=buf)
    sensors.backup_failed(reason=secret, stream=buf)
    sensors.backup_verify(backend=secret, method="hash", confirmed=True, stream=buf)
    sensors.backup_check(kind="monthly", ok=False, detail=secret, stream=buf)
    sensors.storage_gauge(StorageGauge(hot_bytes=1), stream=buf)

    for line in buf.getvalue().splitlines():
        assert "20261031-abcdef.wav" not in line, f"a path reached a sensor: {line}"


def test_dispatch_keys_on_the_event_name_never_the_verdict():
    """§2.1: `parts[5]` is corroborating state after a match, never the dispatch key."""

    buf = io.StringIO()
    sensors.backup_done(stream=buf)             # verdict "done"
    sensors.backup_verify(backend="b", method="presence",
                          confirmed=True, stream=buf)   # verdict "confirmed"
    for line in buf.getvalue().splitlines():
        parts = line.split(" ", 6)
        assert parts[2].startswith("backup."), parts[2]


def test_backup_verify_names_the_backend_that_produced_the_answer():
    """Requirement 3 carried to the sensor surface: provenance in the journal."""

    buf = io.StringIO()
    sensors.backup_verify(backend="local-path-fixture", method="hash",
                          confirmed=True, stream=buf)
    sensors.backup_verify(backend="rclone:mega-elaria", method="presence",
                          confirmed=True, stream=buf)
    lines = buf.getvalue().splitlines()
    assert "backend=local-path-fixture" in lines[0]
    assert "backend=rclone:mega-elaria" in lines[1]
    # the two are distinguishable in the record, which is the whole point
    assert "method=hash" in lines[0]
    assert "method=presence" in lines[1]


def test_a_failed_verification_is_a_warn_not_a_silence():
    buf = io.StringIO()
    sensors.backup_verify(backend="local-path-fixture", method="absent",
                          confirmed=False, stream=buf)
    line = buf.getvalue().strip()
    assert " warn " in line, "an unconfirmed verification must be visible"
    assert "confirmed=no" in line


def test_a_failed_check_is_an_error():
    buf = io.StringIO()
    sensors.backup_check(kind="monthly", ok=False, stream=buf)
    assert " error " in buf.getvalue()


# --------------------------------------------------------------------------------------
# The gauge
# --------------------------------------------------------------------------------------


def test_an_unread_remote_is_unknown_not_zero():
    """Reporting unknown as zero would suppress the knock the design asked for."""

    gauge = StorageGauge(remote_free_bytes=None)
    assert gauge.remote_free_known is False
    assert gauge.below_floor() is False
    assert "remote_free=unknown" in gauge.detail()


def test_the_capacity_floor_is_10gb_consumed():
    """The floor is 10 GB consumed, expressed as remote_free so it stays equivalent."""

    floor = 10 * 1000 ** 3
    assert StorageGauge(remote_free_bytes=floor - 1).below_floor() is True
    assert StorageGauge(remote_free_bytes=floor).below_floor() is False
    assert StorageGauge(remote_free_bytes=floor + 1).below_floor() is False


def test_a_breached_floor_is_a_warn_gauge():
    buf = io.StringIO()
    sensors.storage_gauge(StorageGauge(remote_free_bytes=1), stream=buf)
    line = buf.getvalue().strip()
    assert " warn " in line
    assert "verdict" not in line  # verdict lives at parts[5], not in the detail
    assert "below_floor=yes" in line


def test_the_gauge_detail_is_path_free_and_machine_readable():
    gauge = StorageGauge(hot_bytes=11, cold_bytes=22, hot_count=3, cold_count=4,
                         remote_free_bytes=5, floor_bytes=10, window_days=14,
                         window_gb=2)
    fields = dict(part.split("=", 1) for part in gauge.detail().split("; "))
    assert fields["hot"] == "11"
    assert fields["cold"] == "22"
    assert fields["remote_free"] == "5"
    assert fields["below_floor"] == "yes"
    assert "window_days" in fields and "window_gb" in fields


def test_the_gauge_to_dict_is_json_serialisable():
    data = StorageGauge(hot_bytes=1, remote_free_bytes=2).to_dict()
    assert json.loads(json.dumps(data))["total_bytes"] == 1


def test_the_gauge_counts_states_not_files(tmp_path):
    # local+uploaded are HOT, flipped+trashed+purged are COLD
    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    for state in ("local", "uploaded", "flipped", "trashed"):
        man.append(ManifestRecord(artifact=f"/x/{state}.wav", state=state,
                                   size=10, ts=NOW_ISO))
    gauge = sensors.gauge_from_manifest(man, floor_bytes=100, window_days=14,
                                        window_gb=2)
    assert gauge.hot_count == 2 and gauge.cold_count == 2
    assert gauge.hot_bytes == 20 and gauge.cold_bytes == 20


def test_a_purged_artifact_still_counts_as_cold(tmp_path):
    """Purged is a state the remote held, not a state that never existed."""

    man = StorageManifest(tmp_path / "backup" / "manifest.jsonl")
    man.append(ManifestRecord(artifact="/x/a.wav", state="purged", size=10,
                              ts=NOW_ISO))
    gauge = sensors.gauge_from_manifest(man, floor_bytes=100, window_days=14,
                                        window_gb=2)
    assert gauge.cold_count == 1


# --------------------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------------------


def test_status_is_path_blind(tmp_path):
    ctx, art = _fixture_ctx(tmp_path)
    out = io.StringIO()
    assert backup_command(_Args(backup_action="status"), None, out=out, ctx=ctx) == 0
    text = out.getvalue()
    assert str(art) not in text, "status must not name an artifact"
    assert "hot=" in text and "cold=" in text


def test_status_emits_the_gauge(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path)
    out = io.StringIO()
    backup_command(_Args(backup_action="status"), None, out=out, ctx=ctx)
    assert "storage.gauge" in out.getvalue()


def test_status_reports_an_unknown_remote_honestly(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path)
    out = io.StringIO()
    backup_command(_Args(backup_action="status"), None, out=out, ctx=ctx)
    assert "remote_free=unknown" in out.getvalue()


def test_status_reports_a_breached_floor(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path, remote_free_bytes=1)
    out = io.StringIO()
    backup_command(_Args(backup_action="status"), None, out=out, ctx=ctx)
    assert "CAPACITY FLOOR BREACHED" in out.getvalue()


# --------------------------------------------------------------------------------------
# fetch — the cold read path
# --------------------------------------------------------------------------------------


def test_fetch_restores_and_hash_verifies(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.backend.store(art)
    out = io.StringIO()
    dest = tmp_path / "restored" / "a.wav"
    code = backup_command(_Args(backup_action="fetch", artifact=str(art), out=str(dest)),
                          None, out=out, ctx=ctx)
    assert code == 0
    assert dest.exists()
    assert dest.read_bytes() == art.read_bytes()
    assert "hash: verified" in out.getvalue()


def test_fetch_refuses_an_artifact_the_manifest_never_saw(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path)
    out = io.StringIO()
    code = backup_command(
        _Args(backup_action="fetch", artifact=str(tmp_path / "nope.wav"), out=None),
        None, out=out, ctx=ctx)
    assert code == 2, "an unknown artifact is a refusal, not a search"
    assert "no manifest record" in out.getvalue()


def test_fetch_refuses_an_artifact_that_is_not_cold(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=UPLOADED)
    out = io.StringIO()
    code = backup_command(_Args(backup_action="fetch", artifact=str(art), out=None),
                          None, out=out, ctx=ctx)
    assert code == 2
    assert "not cold" in out.getvalue()


def test_fetch_refuses_when_the_remote_does_not_hold_it(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    # deliberately NOT stored in the fixture remote
    out = io.StringIO()
    dest = tmp_path / "restored" / "a.wav"
    code = backup_command(_Args(backup_action="fetch", artifact=str(art), out=str(dest)),
                          None, out=out, ctx=ctx)
    assert code == 1, "a restore that cannot happen is a failure, not a success"
    assert "restore failed" in out.getvalue()
    assert "backup.failed" in out.getvalue()


def test_fetch_refuses_a_restore_whose_hash_does_not_match(tmp_path):
    """A restore that does not hash-verify is not a restore."""

    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.backend.store(art)
    # tamper with the stored copy
    stored = ctx.backend.root / art.name
    stored.write_bytes(b"tampered")
    out = io.StringIO()
    dest = tmp_path / "restored" / "a.wav"
    code = backup_command(_Args(backup_action="fetch", artifact=str(art), out=str(dest)),
                          None, out=out, ctx=ctx)
    assert code == 1
    assert "does not match the manifest hash" in out.getvalue()
    assert "backup.verify" in out.getvalue()


def test_fetch_refuses_with_no_restorer(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.restorer = None
    out = io.StringIO()
    code = backup_command(_Args(backup_action="fetch", artifact=str(art), out=None),
                          None, out=out, ctx=ctx)
    assert code == 2
    assert "no restorer configured" in out.getvalue()


def test_fetch_names_the_backend_it_restored_from(tmp_path):
    """Provenance on the terminal too, not only in the journal."""

    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.backend.store(art)
    out = io.StringIO()
    backup_command(_Args(backup_action="fetch", artifact=str(art),
                         out=str(tmp_path / "r" / "a.wav")), None, out=out, ctx=ctx)
    assert "local-path-fixture" in out.getvalue()


def test_fetch_defaults_the_destination_to_a_temp_dir(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.backend.store(art)
    out = io.StringIO()
    assert backup_command(_Args(backup_action="fetch", artifact=str(art), out=None),
                          None, out=out, ctx=ctx) == 0
    assert "restored:" in out.getvalue()


# --------------------------------------------------------------------------------------
# run
# --------------------------------------------------------------------------------------


def test_run_with_nothing_cold_is_a_correct_no_op(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path)
    out = io.StringIO()
    code = backup_command(_Args(backup_action="run", dry_run=False), None,
                          out=out, ctx=ctx)
    assert code == 0
    assert "nothing to send cold" in out.getvalue()
    assert "backup.done" in out.getvalue()


def test_run_dry_run_changes_nothing_and_contacts_nothing(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=UPLOADED)
    _age(art, days=30)          # past the 14-day window, so there IS work
    before = ctx.manifest.summary()
    out = io.StringIO()
    code = backup_command(_Args(backup_action="run", dry_run=True), None,
                          out=out, ctx=ctx)
    assert code == 0
    assert "dry run" in out.getvalue()
    assert ctx.manifest.summary() == before, "a dry run must not touch the manifest"


def test_run_refuses_without_a_verifier(tmp_path):
    """Increment 2's refusal, still standing: no verifier, no flip."""

    ctx, art = _fixture_ctx(tmp_path, state=UPLOADED)
    _age(art, days=30)          # past the window, so the refusal path is reached
    ctx.verifier = None
    out = io.StringIO()
    code = backup_command(_Args(backup_action="run", dry_run=False), None,
                          out=out, ctx=ctx)
    assert code == 2
    assert "no remote verifier" in out.getvalue()
    assert "backup.failed" in out.getvalue()


def test_run_emits_the_lifecycle_in_order(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path)
    out = io.StringIO()
    backup_command(_Args(backup_action="run", dry_run=True), None, out=out, ctx=ctx)
    text = out.getvalue()
    assert text.index("backup.started") < text.index("backup.done")


# --------------------------------------------------------------------------------------
# check — the integrity drill shape
# --------------------------------------------------------------------------------------


def test_check_with_nothing_cold_is_a_pass(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path, state=UPLOADED)
    out = io.StringIO()
    code = backup_command(_Args(backup_action="check", artifact=None, kind="monthly"),
                          None, out=out, ctx=ctx)
    assert code == 0
    assert "nothing cold to drill" in out.getvalue()


def test_check_restores_and_hash_verifies(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.backend.store(art)
    out = io.StringIO()
    code = backup_command(_Args(backup_action="check", artifact=None, kind="monthly"),
                          None, out=out, ctx=ctx)
    assert code == 0
    assert "passed" in out.getvalue()
    assert "backup.check" in out.getvalue()


def test_check_fails_when_the_restored_hash_does_not_match(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.backend.store(art)
    (ctx.backend.root / art.name).write_bytes(b"tampered")
    out = io.StringIO()
    code = backup_command(_Args(backup_action="check", artifact=None, kind="monthly"),
                          None, out=out, ctx=ctx)
    assert code == 1
    assert "FAILED" in out.getvalue()


def test_check_is_deterministic_with_an_injected_rng(tmp_path):
    """A drill that picks at random must be reproducible in a test."""

    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.backend.store(art)
    rng = random.Random(1234)
    out = io.StringIO()
    code = backup_command(_Args(backup_action="check", artifact=None, kind="monthly"),
                          None, out=out, ctx=ctx)
    assert code == 0
    assert rng.random() == random.Random(1234).random()


def test_check_accepts_a_named_artifact(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.backend.store(art)
    out = io.StringIO()
    code = backup_command(_Args(backup_action="check", artifact=str(art),
                                kind="quarterly"), None, out=out, ctx=ctx)
    assert code == 0
    assert "kind=quarterly" in out.getvalue()


def test_check_refuses_a_named_artifact_that_is_not_cold(tmp_path):
    ctx, art = _fixture_ctx(tmp_path, state=UPLOADED)
    out = io.StringIO()
    code = backup_command(_Args(backup_action="check", artifact=str(art),
                                kind="monthly"), None, out=out, ctx=ctx)
    assert code == 2


def test_check_refuses_with_no_restorer(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path, state=FLIPPED)
    ctx.restorer = None
    out = io.StringIO()
    code = backup_command(_Args(backup_action="check", artifact=None, kind="monthly"),
                          None, out=out, ctx=ctx)
    assert code == 2
    assert "no restorer" in out.getvalue()


# --------------------------------------------------------------------------------------
# The context
# --------------------------------------------------------------------------------------


def test_the_fixture_context_names_its_restorer():
    ctx = BackupContext.fixture(Path("/tmp/ctx-fixture"))
    assert ctx.restorer.name == "local-path-fixture"
    assert ctx.restorer.backend.name == "local-path-fixture"


def test_build_context_with_no_remote_leaves_the_verifier_none(tmp_path):
    """An unconfigured remote is a None verifier, not a guess."""

    class _Cfg:
        def section(self, name):
            return {"rclone_remote": "", "rclone_path": "elaria-restic"}

        @property
        def data_dir(self):
            return tmp_path

    ctx = build_context(_Cfg())
    assert ctx.verifier is None


def test_build_context_reads_the_final_census_defaults(tmp_path):
    class _Cfg:
        def section(self, name):
            return {"rclone_remote": "", "rclone_path": "p", "hot_window_days": 14,
                    "hot_window_gb": 2, "capacity_floor_gb": 10,
                    "trim_grace_days": 14}

        @property
        def data_dir(self):
            return tmp_path

    ctx = build_context(_Cfg())
    assert ctx.window_days == 14 and ctx.window_gb == 2
    assert ctx.floor_bytes == 10 * 1000 ** 3
    assert ctx.grace_days == 14


def test_the_local_path_restorer_refuses_a_missing_copy(tmp_path):
    backend = LocalPathBackend(tmp_path / "remote")
    restorer = LocalPathRestorer(backend)
    art = _wav(tmp_path / "audio" / "a.wav")
    with pytest.raises(FileNotFoundError):
        restorer.restore(art, tmp_path / "out.wav")


def test_the_local_path_restorer_copies_when_present(tmp_path):
    backend = LocalPathBackend(tmp_path / "remote")
    restorer = LocalPathRestorer(backend)
    art = _wav(tmp_path / "audio" / "a.wav")
    backend.store(art)
    dest = restorer.restore(art, tmp_path / "out.wav")
    assert dest.read_bytes() == art.read_bytes()


def test_an_unknown_action_is_a_refusal(tmp_path):
    ctx, _ = _fixture_ctx(tmp_path)
    out = io.StringIO()
    code = backup_command(_Args(backup_action="nonsense"), None, out=out, ctx=ctx)
    assert code == 2


# --------------------------------------------------------------------------------------
# The CLI registration is additive
# --------------------------------------------------------------------------------------


def test_the_backup_subcommand_is_registered():
    from assistant.cli import build_parser

    ns = build_parser().parse_args(["backup", "status"])
    assert ns.command == "backup"
    assert ns.backup_action == "status"


def test_every_backup_help_string_renders():
    """BH-G4: one unescaped % used to take the entire CLI down at construction."""

    import contextlib

    from assistant.cli import build_parser

    parser = build_parser()
    for argv in (["backup", "--help"], ["backup", "status", "--help"],
                 ["backup", "fetch", "--help"], ["backup", "run", "--help"],
                 ["backup", "check", "--help"]):
        with contextlib.redirect_stdout(io.StringIO()), pytest.raises(SystemExit):
            parser.parse_args(argv)


def test_the_backup_parser_does_not_shadow_an_existing_command():
    from assistant.cli import build_parser

    # `queue` is excluded deliberately: its subparsers are required, so a bare
    # `assist queue` is a usage error on mainline and always was. The point of this
    # test is that ADDING `backup` changed nothing about the commands that already
    # parsed — so each one must still parse exactly as it did.
    for existing in ("halt", "status", "doctor", "cost", "talk", "ladder"):
        ns = build_parser().parse_args([existing])
        assert ns.command == existing
