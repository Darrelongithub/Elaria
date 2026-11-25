"""BUILD-5 eye-checks: synthetic WAVs and LocalPathBackend only; no network."""
import io
import os
from types import SimpleNamespace

from test_wp7_live_upload_safety import setup_audio

from assistant.backup_cli import _run, backup_command
from assistant.storage import UPLOADED


def command(ctx, action, **kwargs):
    out = io.StringIO()
    args = SimpleNamespace(backup_action=action, **kwargs)
    result = backup_command(args, None, ctx=ctx, out=out)
    return result, out.getvalue()


def test_fixture_round_trip_drill_and_restore_exact_bytes(tmp_path):
    ctx, artifact = setup_audio(tmp_path)
    original = artifact.read_bytes()
    code, text = command(ctx, 'run', artifact=str(artifact))
    assert code == 0 and 'local-path-fixture' in text
    assert [r.state for r in ctx.manifest.records()] == ['local', 'uploaded', 'flipped', 'trashed']
    code, text = command(ctx, 'verify', artifact=str(artifact))
    assert code == 0 and 'local-path-fixture' in text
    code, text = command(ctx, 'drill', artifact=str(artifact), kind='monthly')
    assert code == 0 and 'hash verified' in text and 'local-path-fixture' in text
    dest = tmp_path / 'restored.wav'
    code, text = command(ctx, 'restore', artifact=str(artifact), out=str(dest))
    assert code == 0 and dest.read_bytes() == original and 'local-path-fixture' in text
    journal = ctx.manifest.path.parent / 'drills.jsonl'
    assert '"kind": "monthly"' in journal.read_text()


def test_corrupted_fixture_never_flips_and_verify_is_loud(tmp_path, monkeypatch):
    ctx, artifact = setup_audio(tmp_path)
    def corrupt(path):
        ctx.backend.root.mkdir(parents=True, exist_ok=True)
        (ctx.backend.root / path.name).write_bytes(b'wrong fixture bytes')
    monkeypatch.setattr(ctx.backend, 'store', corrupt)
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 1
    assert ctx.manifest.state_of(artifact) == UPLOADED and artifact.exists()
    code, text = command(ctx, 'verify', artifact=str(artifact))
    assert code == 1 and 'FAILED' in text and 'local-path-fixture' in text
    code, text = command(ctx, 'status')
    assert code == 0 and 'BACKUP HEALTH WARNING' in text
    assert ctx.manifest.state_of(artifact) == UPLOADED


def test_failed_restore_drill_is_journaled_and_visible_in_status(tmp_path):
    ctx, artifact = setup_audio(tmp_path)
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 0
    (ctx.backend.root / artifact.name).write_bytes(b'corruption')
    code, text = command(ctx, 'drill', artifact=str(artifact), kind='monthly')
    assert code == 1 and 'FAILED' in text
    code, text = command(ctx, 'status')
    assert code == 0 and 'BACKUP HEALTH WARNING' in text and 'FAILED' in text
    assert '"ok": false' in (ctx.manifest.path.parent / 'drills.jsonl').read_text()


def test_unreachable_fixture_retried_journaled_and_reported(tmp_path, monkeypatch):
    ctx, artifact = setup_audio(tmp_path)
    attempts = []
    def unavailable(path):
        attempts.append(path)
        raise OSError('unreachable')
    monkeypatch.setattr(ctx.backend, 'store', unavailable)
    code, text = command(ctx, 'run', artifact=str(artifact))
    assert code == 1 and len(attempts) == 3 and 'FAILED' in text and 'retrying' in text
    assert artifact.exists() and ctx.manifest.state_of(artifact) == 'local'
    assert (ctx.manifest.path.parent / 'drills.jsonl').read_text().count('"ok": false') == 3
    assert 'BACKUP HEALTH WARNING' in command(ctx, 'status')[1]


def test_watch_run_cold_scans_all_newly_cold_fixture_captures(tmp_path):
    ctx, artifact = setup_audio(tmp_path)
    second = artifact.with_name('second.wav')
    second.write_bytes(artifact.read_bytes() + b'fixture')
    old = artifact.stat().st_mtime
    os.utime(second, (old, old))
    code, text = command(ctx, 'watch', run_cold=True)
    assert code == 0, text
    assert not artifact.exists() and not second.exists()
    assert ctx.manifest.state_of(artifact) == ctx.manifest.state_of(second) == 'trashed'
    assert 'local-path-fixture' in text


def test_retry_recovers_from_transient_fixture_failure(tmp_path, monkeypatch):
    ctx, artifact = setup_audio(tmp_path)
    store = ctx.backend.store
    calls = []
    def transient(path):
        calls.append(path)
        if len(calls) == 1:
            raise OSError('fixture unavailable')
        return store(path)
    monkeypatch.setattr(ctx.backend, 'store', transient)
    code, text = command(ctx, 'run', artifact=str(artifact))
    assert code == 0 and len(calls) == 2 and 'retrying' in text
    assert ctx.manifest.state_of(artifact) == 'trashed'
    assert 'BACKUP HEALTH WARNING' in command(ctx, 'status')[1]


def test_drill_never_claims_success_when_journal_write_fails(tmp_path, monkeypatch):
    from assistant.wp7_drill import DrillJournal
    ctx, artifact = setup_audio(tmp_path)
    assert _run(ctx, out=io.StringIO(), artifact=str(artifact)) == 0
    monkeypatch.setattr(DrillJournal, 'append', lambda self, record: False)
    code, text = command(ctx, 'drill', artifact=str(artifact), kind='monthly')
    assert code == 1 and 'journal unavailable' in text
