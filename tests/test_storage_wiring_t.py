"""Storage wiring regressions. All payloads, tools and remote names are fixtures."""
import hashlib
import io
import os
import subprocess
from types import SimpleNamespace

import pytest

from assistant.backup_cli import backup_command, build_context
from assistant.storage import FLIPPED, ManifestRecord


class Config:
    def __init__(self, root, remote="fixture"):
        self.data_dir = root
        self.remote = remote

    def section(self, key):
        return {"rclone_remote": self.remote, "rclone_path": "snap shots",
                "restore_headroom_margin_gb": 0}


def cold(ctx, filename):
    path = ctx.data_dir / "audio" / filename
    assert ctx.manifest.append(ManifestRecord(artifact=str(path), state=FLIPPED,
                               sha256=hashlib.sha256(b"test").hexdigest(), size=4))
    return path


def tool(tmp, name, body):
    path = tmp / name
    path.write_text("#!/bin/sh\nset -eu\n" + body)
    path.chmod(0o700)


@pytest.mark.parametrize("query", ["capture-123.wav", "capture-123", "capture-12", "audio/capture-123"])
def test_fetch_manifest_path_into_destination(tmp_path, monkeypatch, query):
    ctx = build_context(Config(tmp_path), read_quota=False)
    path = cold(ctx, "capture-123.wav")
    tool(tmp_path, "restic", 'printf "%s\\n" "$@" > "$ARGS"; printf test')
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("ARGS", str(tmp_path / "args"))
    dest = tmp_path / "another directory" / "new name.wav"
    args = SimpleNamespace(backup_action="fetch", artifact=query, out=str(dest))
    assert backup_command(args, None, ctx=ctx) == 0
    assert (tmp_path / "args").read_text().splitlines() == [
        "-r", "rclone:fixture:snap shots", "-o", "rclone.timeout=5m", "dump", "latest", str(path)]
    assert dest.read_bytes() == b"test"


def test_refusal_does_not_publish_partial_or_unverified_audio(tmp_path, monkeypatch):
    ctx = build_context(Config(tmp_path), read_quota=False)
    cold(ctx, "capture-123.wav")
    cold(ctx, "capture-456.wav")
    dest = tmp_path / "existing"
    dest.write_bytes(b"keep")
    args = SimpleNamespace(backup_action="fetch", artifact="capture-", out=str(dest))
    monkeypatch.setenv("PATH", str(tmp_path))
    out = io.StringIO()
    assert backup_command(args, None, ctx=ctx, out=out) == 2
    assert "ambiguous" in out.getvalue()
    args.artifact = "elsewhere/capture-123.wav"
    assert backup_command(args, None, ctx=ctx) == 2
    args.artifact = "capture-123"
    for status in (0, 1):
        tool(tmp_path, "restic", f'printf partial; exit {status}')
        assert backup_command(args, None, ctx=ctx) == 1
        assert dest.read_bytes() == b"keep"


def test_configured_movers_refuse_paths_outside_their_trees(tmp_path):
    ctx = build_context(Config(tmp_path), read_quota=False)
    audio = tmp_path / "audio"
    audio.mkdir()
    capture = audio / "a.wav"
    capture.write_bytes(b"test")
    with pytest.raises(OSError):
        ctx.purge_mover(capture)
    link = audio / "link.wav"
    link.symlink_to(capture)
    with pytest.raises(OSError):
        ctx.trim_mover(link)
    trash = ctx.trim_mover(capture)
    assert not capture.exists() and trash.read_bytes() == b"test"
    with pytest.raises(OSError):
        ctx.purge_mover(trash.parent)
    assert ctx.purge_mover(trash) and not trash.exists()
    unset = build_context(Config(tmp_path, remote=""))
    assert unset.trim_mover is unset.purge_mover is unset.restorer is None
    assert unset.remote_preflight().required_bytes == 2719664640
    assert not unset.remote_preflight().ok


def test_dry_run_does_not_probe_configured_remote(tmp_path, monkeypatch):
    def contacted(*args, **kwargs):
        pytest.fail("dry run invoked a remote command")

    monkeypatch.setattr(subprocess, "run", contacted)
    assert backup_command(SimpleNamespace(backup_action="run", dry_run=True), Config(tmp_path)) == 0


@pytest.mark.parametrize("base", ["fixture:test", "rclone:fixture:test"])
def test_benchmark_routes_repository_by_tool(tmp_path, base):
    tool(tmp_path, "rclone", 'echo "$*" >> "$LOG"; exit 3')
    tool(tmp_path, "restic", 'echo "$*" >> "$LOG"; exit 7')
    log = tmp_path / "argv"
    result = subprocess.run(["bash", "scripts/storage-benchmark.sh"], check=False, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "LOG": str(log),
             "RESTIC_REPOSITORY_BASE": base, "RESTIC_PASSWORD_FILE": __file__,
             "BENCH_LOCAL": str(tmp_path / "scratch"), "BENCH_BYTES": "0", "BENCH_SMALL_COUNT": "0"})
    assert result.returncode == 1 and "exit=7" in result.stdout
    first, second, init = log.read_text().splitlines()
    assert (first, second) == ("lsf fixture:test-default", "lsf fixture:test-pack32")
    assert init.startswith("-r rclone:fixture:test-default ")


def test_unknown_listing_stops_before_init(tmp_path):
    tool(tmp_path, "rclone", "exit 5")
    tool(tmp_path, "restic", 'touch "$LOG"')
    log = tmp_path / "unexpected"
    result = subprocess.run(["bash", "scripts/storage-benchmark.sh"], check=False, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "LOG": str(log),
             "RESTIC_REPOSITORY_BASE": "fixture:test", "RESTIC_PASSWORD_FILE": __file__})
    assert result.returncode == 1 and "exit=5" in result.stderr and not log.exists()


@pytest.mark.parametrize("payload,expected", [("test", True), ("wrong", False)])
def test_flip_requires_snapshot_content_not_a_remote_basename(tmp_path, monkeypatch, payload, expected):
    from datetime import UTC, datetime

    from assistant.backup import reconcile_all
    from assistant.storage import TRASHED, UPLOADED

    ctx = build_context(Config(tmp_path), read_quota=False)
    path = tmp_path / "audio" / "capture; one.wav"
    path.parent.mkdir()
    path.write_bytes(b"test")
    ctx.manifest.append(ManifestRecord(artifact=str(path), state=UPLOADED,
                                      sha256=hashlib.sha256(b"test").hexdigest()))
    tool(tmp_path, "rclone", 'test "$1" = version; echo "rclone v1.75.2"')
    tool(tmp_path, "restic", f"printf {payload}")
    monkeypatch.setenv("PATH", str(tmp_path))
    plan = reconcile_all(ctx.manifest, now=datetime.now(UTC), verify_remote=ctx.verifier,
                         trim_mover=ctx.trim_mover, purge_mover=ctx.purge_mover)
    assert bool(plan.problems) is not expected
    assert ctx.manifest.state_of(path) == (TRASHED if expected else UPLOADED)
    assert path.exists() is not expected
    if expected:
        from datetime import timedelta

        later = datetime.now(UTC) + timedelta(days=15)
        plan = reconcile_all(ctx.manifest, now=later, verify_remote=ctx.verifier,
                             trim_mover=ctx.trim_mover, purge_mover=ctx.purge_mover)
        assert not plan.problems and ctx.manifest.state_of(path) == "purged"
        assert not list((tmp_path / "backup" / "trash").iterdir())


def test_monthly_drill_does_not_retry_failed_restic_check(tmp_path, monkeypatch):
    ctx = build_context(Config(tmp_path), read_quota=False)
    path = cold(ctx, "capture.wav")
    log = tmp_path / "calls"
    tool(tmp_path, "restic", 'echo "$*" >> "$LOG"\ncase "$*" in *" check") exit 7;; esac\nprintf test')
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("LOG", str(log))
    out = io.StringIO()
    assert backup_command(SimpleNamespace(backup_action="check", kind="monthly", artifact=str(path)),
                          None, out=out, ctx=ctx) == 1
    assert len(log.read_text().splitlines()) == 2
    assert "hash verified; restic check: FAILED" in out.getvalue()
