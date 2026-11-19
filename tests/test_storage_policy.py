"""Agent S: storage policy boundaries, without a daemon, remote or real recordings."""

import io
import os
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from assistant.backup_cli import BackupContext, backup_command
from assistant.storage import LOCAL, UPLOADED, ManifestRecord, StorageManifest
from assistant.tiering import Candidate, classify

NOW = datetime(2026, 11, 19, tzinfo=UTC)
F24_BYTES = 2_719_664_640  # IF-5: scratch + reserve, in bytes


class StoragePolicyTests(unittest.TestCase):
    def test_size_pressure_does_not_hide_age_boundary(self):
        old, boundary, fresh = candidates = [
            Candidate(Path(str(days)), size, NOW - timedelta(days=days))
            for days, size in [(4, 9), (3, 5), (0, 999_999_990)]
        ]
        # Evicting old alone is enough for size; boundary must still go for age.
        mixed = classify(candidates, now=NOW, window_days=3, window_gb=1)
        self.assertEqual((mixed.binding, mixed.send_cold), ('size', [old, boundary]))
        self.assertEqual((mixed.keep_hot, mixed.hot_bytes), ([fresh], fresh.size))
        relaxed = classify(candidates, now=NOW, window_days=5, window_gb=2)
        self.assertEqual((relaxed.binding, relaxed.keep_hot), ('none', candidates))

    def test_unindexed_files_and_partial_or_superseded_records(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = root / 'unindexed'
            item.write_bytes(b'x')
            manifest = StorageManifest(root / 'manifest.jsonl')
            self.assertEqual(manifest.summary()['artifacts'], 0)
            self.assertFalse(manifest.exists())
            for state in (LOCAL, UPLOADED):
                manifest.append(ManifestRecord(str(item), state, size=1))
            with manifest.path.open('a') as stream:
                stream.write(ManifestRecord('partial', LOCAL, size=3).to_json())
            with patch.object(manifest, 'current', wraps=manifest.current) as read:
                summary = manifest.summary()
                read.assert_called_once_with()
            self.assertEqual(summary['artifacts'], 1)
            self.assertEqual(summary['by_state'], {UPLOADED: 1})
            self.assertEqual(summary['bytes_by_state'], {UPLOADED: 1})

    def test_headroom_refuses_before_a_transition(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = root / 'aged'
            item.write_bytes(b'fixture')
            stamp = (NOW - timedelta(days=30)).timestamp()
            os.utime(item, (stamp, stamp))
            manifest = StorageManifest(root / 'manifest.jsonl')
            manifest.append(ManifestRecord(str(item), UPLOADED, size=item.stat().st_size))
            before = manifest.path.read_bytes()
            verify = Mock(side_effect=AssertionError('must refuse before verification'))
            ctx = BackupContext(manifest, data_dir=root, now=NOW, verifier=verify)
            for free in (None, F24_BYTES - 1):
                with self.subTest(free=free):
                    ctx.with_remote_free(free)
                    out = io.StringIO()
                    args = SimpleNamespace(backup_action='run', dry_run=False)
                    self.assertEqual(backup_command(args, None, ctx=ctx, out=out), 2)
                    self.assertIn(f'required={F24_BYTES}', out.getvalue())
                    self.assertEqual(manifest.path.read_bytes(), before)
                    self.assertEqual(item.read_bytes(), b'fixture')
                    verify.assert_not_called()
            ctx.with_remote_free(F24_BYTES)
            self.assertTrue(ctx.remote_preflight().ok)
