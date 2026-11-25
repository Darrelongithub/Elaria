"""Synthetic-only coverage of the explicit, single-artifact backup path."""
import io
import os
import subprocess
import wave
from datetime import UTC, datetime, timedelta

from assistant.backup_cli import AudioMovers, BackupContext, ResticRestorer, _fetch, _run
from assistant.storage import LOCAL, ManifestRecord, StorageManifest


def setup_audio(tmp_path):
    audio = tmp_path / "data" / "audio"
    audio.mkdir(parents=True)
    artifact = audio / "capture.wav"
    with wave.open(str(artifact), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x01\x00" * 100)
    now = datetime.now(UTC)
    old = (now - timedelta(days=20)).timestamp()
    os.utime(artifact, (old, old))
    ctx = BackupContext.fixture(tmp_path / "fixture", data_dir=tmp_path / "data", now=now)
    ctx.remote_free_bytes = 20_000_000_000
    ctx.trim_mover = AudioMovers(ctx.data_dir).trim
    return ctx, artifact


def test_single_artifact_is_uploaded_verified_trashed_and_retrievable(tmp_path):
    ctx, artifact = setup_audio(tmp_path)
    expected = artifact.read_bytes()
    out = io.StringIO()
    assert _run(ctx, out=out, artifact=str(artifact)) == 0, out.getvalue()
    assert [r.state for r in ctx.manifest.records()] == ["local", "uploaded", "flipped", "trashed"]
    assert not artifact.exists()
    assert len(list((ctx.data_dir / "backup" / "trash").iterdir())) == 1
    target = tmp_path / "restored.wav"
    assert _fetch(ctx, str(artifact), dest=str(target), out=io.StringIO()) == 0
    assert target.read_bytes() == expected


def test_no_artifact_or_unknown_quota_never_uploads(tmp_path):
    ctx, artifact = setup_audio(tmp_path)
    assert _run(ctx, out=io.StringIO()) == 2
    ctx.remote_free_bytes = None
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 2
    assert artifact.exists() and not ctx.manifest.exists()


def test_multiple_cold_candidates_refuse_before_any_upload(tmp_path):
    ctx, artifact = setup_audio(tmp_path)
    second = artifact.with_name("other.wav")
    second.write_bytes(artifact.read_bytes())
    os.utime(second, (artifact.stat().st_mtime, artifact.stat().st_mtime))
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 2
    assert not ctx.manifest.exists()
    assert artifact.exists() and second.exists()


def test_failed_upload_keeps_original_and_never_records_uploaded(tmp_path, monkeypatch):
    ctx, artifact = setup_audio(tmp_path)
    def fail(_path):
        raise OSError("failure")
    monkeypatch.setattr(ctx.backend, "store", fail)
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 1
    assert artifact.exists()
    assert [r.state for r in ctx.manifest.records()] == [LOCAL]


def test_restorer_uses_pinned_snapshot_not_latest(tmp_path, monkeypatch):
    manifest = StorageManifest(tmp_path / "manifest")
    artifact = tmp_path / "audio" / "a.wav"
    manifest.append(ManifestRecord(str(artifact), "uploaded", detail="snapshot=deadbeef"))
    class Backend:
        name = "test"
        remote = "test"
        path = "repo"
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(argv)
        kwargs["stdout"].write(b"synthetic")
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(subprocess, "run", fake_run)
    restorer = ResticRestorer(Backend(), "5m", manifest)
    restored = restorer.restore(artifact, tmp_path / "out")
    assert restored.read_bytes() == b"synthetic"
    assert "deadbeef" in calls[0]
    assert "latest" not in calls[0]


def test_synthetic_restic_command_path_pins_snapshot_across_transitions(tmp_path, monkeypatch):
    from assistant.backup_cli import _check, build_context

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    rclone = bin_dir / "rclone"
    rclone.write_text('''#!/usr/bin/env python3
import sys
if sys.argv[1] == "version": print("rclone v1.75.2")
elif sys.argv[1] == "about": print('{"free":30000000000}')
else: sys.exit(1)
''')
    restic = bin_dir / "restic"
    restic.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
store = pathlib.Path(os.environ["FAKE_RESTIC_STORE"])
if "backup" in args:
    store.write_bytes(pathlib.Path(args[-1]).read_bytes())
    print(json.dumps({"message_type":"summary","snapshot_id":"deadbeef"}))
elif "dump" in args:
    if args[-2] != "deadbeef": sys.exit(9)
    sys.stdout.buffer.write(store.read_bytes())
elif "check" in args: pass
else: sys.exit(1)
''')
    rclone.chmod(0o755)
    restic.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_RESTIC_STORE", str(tmp_path / "snapshot"))
    ctx, artifact = setup_audio(tmp_path)
    expected = artifact.read_bytes()

    class Config:
        data_dir = ctx.data_dir
        def section(self, _name):
            return {"rclone_remote": "fixture", "rclone_path": "repo"}

    ctx = build_context(Config(), now=ctx.now)
    out = io.StringIO()
    assert _run(ctx, out=out, artifact=str(artifact)) == 0, out.getvalue()
    assert ctx.manifest.current()[str(artifact)].state == "trashed"
    assert "snapshot=deadbeef;" in ctx.manifest.current()[str(artifact)].detail
    target = tmp_path / "out.wav"
    assert _fetch(ctx, str(artifact), dest=str(target), out=io.StringIO()) == 0
    assert target.read_bytes() == expected
    from assistant.wp7_drill import ResticCheck
    check = ResticCheck(ctx.restorer.repo, remote="fixture", path="repo")
    assert _check(ctx, artifact=None, kind="monthly", out=io.StringIO(), restic=check) == 0


def test_fetch_never_overwrites_existing_destination(tmp_path):
    ctx, artifact = setup_audio(tmp_path)
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 0
    target = tmp_path / "out.wav"
    target.write_bytes(b"keep me")
    assert _fetch(ctx, str(artifact), dest=str(target), out=io.StringIO()) == 2
    assert target.read_bytes() == b"keep me"


def test_hash_mismatch_prevents_flip_and_trim(tmp_path, monkeypatch):
    ctx, artifact = setup_audio(tmp_path)
    def store_corrupt(path):
        ctx.backend.root.mkdir(parents=True)
        (ctx.backend.root / path.name).write_bytes(b"corrupt")
    monkeypatch.setattr(ctx.backend, "store", store_corrupt)
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 1
    assert artifact.exists()
    assert ctx.manifest.current()[str(artifact)].state == "uploaded"


def test_empty_drill_is_not_a_pass(tmp_path):
    from assistant.backup_cli import _check
    ctx, _ = setup_audio(tmp_path)
    assert _check(ctx, artifact=None, kind="monthly", out=io.StringIO()) == 2


def test_interrupted_trim_resumes_only_after_reverification(tmp_path):
    ctx, artifact = setup_audio(tmp_path)
    good_mover = ctx.trim_mover
    def fail_trim(_path):
        raise OSError("simulated interruption")
    ctx.trim_mover = fail_trim
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 1
    assert artifact.exists()
    assert ctx.manifest.current()[str(artifact)].state == "flipped"
    ctx.trim_mover = good_mover
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 0
    assert not artifact.exists()
    assert ctx.manifest.current()[str(artifact)].state == "trashed"
