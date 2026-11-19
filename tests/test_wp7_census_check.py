"""Tests for scripts/storage-census-check.py — the STEP-0 ground-truth check.

The doctrine these tests encode is increment 3's, binding house style: **assert ground
truth, never the claim.** The census is three independent computations that must agree,
and the check must refuse to report a number when they do not.

The subtlety that earns its own test: `du -sb` counts the never-retry marks as bytes and
the census must not, so the two differ *on purpose*. The check's job is to prove the
difference is exactly the marks' byte total — anything else is a real defect.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "scripts", "storage-census-check.py")


def _recording(path: str, seconds: float) -> int:
    """A real RIFF/WAVE recording, built with the `wave` module.

    Never a synthetic byte blob — that pattern has produced four quietly-wrong fixtures
    in this lane already.
    """
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * int(16000 * seconds))
    return os.path.getsize(path)


def _canonical_mark(path: str) -> int:
    """A zero-frame WavSink close(): exactly 44 canonical bytes."""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"")
    return os.path.getsize(path)


def _chunked_mark(path: str) -> int:
    """A self-consistent chunked zero-frame WAV: 62 bytes, still a never-retry mark.

    The LIST payload length must equal its declared size, and the RIFF size must match
    the body. An earlier fixture in this lane declared 10 and carried 11, which made the
    chunk walk land on the wrong chunk id.
    """
    payload = b"INFOhello!"  # exactly 10 bytes
    body = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
    body += b"LIST" + struct.pack("<I", len(payload)) + payload
    body += b"data" + struct.pack("<I", 0)  # declares zero frames
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", len(body)) + b"WAVE" + body)
    return os.path.getsize(path)


def _run(audio: str, manifest: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, SCRIPT, "--audio", audio, "--manifest", manifest, *extra],
        check=False, capture_output=True,
        text=True,
    )


class CensusCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.audio = os.path.join(self.root, "audio")
        os.makedirs(self.audio)
        self.manifest = os.path.join(self.root, "manifest.jsonl")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _manifest_with(self, records: list[dict]) -> None:
        with open(self.manifest, "w", encoding="utf-8") as fh:
            fh.writelines(json.dumps(rec) + "\n" for rec in records)

    # -- the happy path ------------------------------------------------------

    def test_all_three_computations_agree_and_exit_zero(self):
        a = _recording(os.path.join(self.audio, "keep-0.wav"), 2.0)
        b = _recording(os.path.join(self.audio, "keep-1.wav"), 3.5)
        self._manifest_with(
            [
                {"artifact": "x", "state": "local", "size": a, "tier": "hot"},
                {"artifact": "y", "state": "local", "size": b, "tier": "hot"},
            ]
        )
        r = _run(self.audio, self.manifest)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"audio bytes        : {a + b}", r.stdout)

    def test_marks_are_excluded_from_the_census_but_counted(self):
        keep = _recording(os.path.join(self.audio, "keep.wav"), 2.0)
        marks = [
            _canonical_mark(os.path.join(self.audio, f"mark-{i}.wav")) for i in range(3)
        ]
        marks.append(_chunked_mark(os.path.join(self.audio, "mark-chunked.wav")))
        self._manifest_with(
            [{"artifact": "x", "state": "local", "size": keep, "tier": "hot"}]
        )
        r = _run(self.audio, self.manifest)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # The census must be the recordings only. Every mark counts zero forever.
        self.assertIn(f"audio bytes        : {keep}", r.stdout)
        self.assertIn("never-retry marks  : 4", r.stdout)

    def test_du_gap_equals_the_marks_byte_total_exactly(self):
        """The whole point: du counts the marks, the census must not, and the gap must
        be exactly the marks' bytes. Anything else means the walk dropped a real file."""
        keep = _recording(os.path.join(self.audio, "keep.wav"), 2.0)
        mark_bytes = _canonical_mark(os.path.join(self.audio, "mark.wav"))
        self._manifest_with(
            [{"artifact": "x", "state": "local", "size": keep, "tier": "hot"}]
        )
        r = _run(self.audio, self.manifest, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["audio_bytes"], keep)
        self.assertEqual(payload["never_retry_mark_bytes"], mark_bytes)
        self.assertEqual(payload["du_minus_census"], mark_bytes)
        self.assertTrue(payload["du_gap_equals_mark_bytes"])
        # The directory inode is subtracted and disclosed, never hidden.
        self.assertEqual(payload["du_dir_inode_subtracted"],
                         payload["du_bytes_raw"] - payload["du_bytes_comparable"])
        self.assertGreater(payload["du_dir_inode_subtracted"], 0)

    def test_chunked_mark_is_detected_structurally(self):
        """A chunked zero-frame WAV is 62 bytes. A byte comparison against 44 misses it;
        the RIFF chunk walk does not. This is the defect that was already found once."""
        size = _chunked_mark(os.path.join(self.audio, "mark-chunked.wav"))
        self.assertGreater(size, 44)
        self._manifest_with([])
        r = _run(self.audio, self.manifest, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout)["never_retry_marks"], 1)

    # -- the negative paths --------------------------------------------------

    def test_a_wrong_manifest_is_refused(self):
        keep = _recording(os.path.join(self.audio, "keep.wav"), 2.0)
        # Off by one byte on purpose: a claim that does not match ground truth.
        self._manifest_with(
            [{"artifact": "x", "state": "local", "size": keep + 1, "tier": "hot"}]
        )
        r = _run(self.audio, self.manifest)
        self.assertEqual(r.returncode, 1)
        self.assertIn("manifest arithmetic does not match", r.stderr)

    def test_a_missing_audio_directory_is_refused(self):
        r = _run(os.path.join(self.root, "nope"), self.manifest)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not readable", r.stderr)

    def test_a_torn_manifest_line_is_discarded_not_counted(self):
        keep = _recording(os.path.join(self.audio, "keep.wav"), 2.0)
        with open(self.manifest, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"artifact": "x", "size": keep, "tier": "hot"}) + "\n")
            fh.write('{"artifact": "y", "size": 12')  # torn mid-write
        r = _run(self.audio, self.manifest, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["manifest_records"], 1)  # the torn line is gone
        self.assertIn("torn line at 2 discarded", payload["problems"])
        self.assertEqual(payload["errors"], [])
        self.assertEqual(payload["audio_bytes"], keep)

    # -- the privacy fence ---------------------------------------------------

    def test_no_path_or_filename_is_ever_printed(self):
        _recording(os.path.join(self.audio, "secret-recording-name.wav"), 1.0)
        _canonical_mark(os.path.join(self.audio, "secret-mark-name.wav"))
        self._manifest_with([])
        r = _run(self.audio, self.manifest, "--json")
        self.assertEqual(r.returncode, 1)  # empty manifest -> refused, but still no paths
        combined = r.stdout + r.stderr
        for leaked in ("secret-recording-name", "secret-mark-name", self.audio, self.root):
            self.assertNotIn(leaked, combined)


if __name__ == "__main__":
    unittest.main()
