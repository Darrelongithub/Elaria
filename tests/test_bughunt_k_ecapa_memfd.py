"""BH-K27 (minor batch): ECAPA scoring wrote wake audio to /tmp.

The whole wake path is RAM-only by design (anonymous mmap buffers,
MADV_DONTDUMP, "crash leaves nothing"), but `EcapaCommandScorer`
handed the clip to the external command through a
`NamedTemporaryFile(delete=False)` in the default temp dir: a SIGKILL
between write and unlink left wake audio on disk, and /tmp is not
tmpfs everywhere.

Fix: the clip travels in an anonymous memfd inherited by the child
(`/proc/self/fd/N`), with a /dev/shm named file only as a non-Linux
fallback. Nothing named ever touches a persistent filesystem.
"""

from __future__ import annotations

import sys

from assistant.voiceprint import EcapaCommandScorer

_SCORER = '''
import json, sys
path = sys.argv[1]
data = open(path, "rb").read()
assert data[:4] == b"RIFF", data[:8]
print(json.dumps({"score": 0.9, "path": path, "bytes": len(data)}))
'''


def test_clip_reaches_the_backend_without_a_disk_path(tmp_path):
    script = tmp_path / "fake_ecapa.py"
    script.write_text(_SCORER)
    seen = tmp_path / "seen.txt"
    scorer = EcapaCommandScorer(f"{sys.executable} {script}")
    # The fake backend also records the path it was handed.
    script.write_text(_SCORER.replace(
        'print(json.dumps({"score": 0.9, "path": path, "bytes": len(data)}))',
        f'open({str(seen)!r}, "w").write(path)\n'
        'print(json.dumps({"score": 0.9}))'))

    score = scorer.score_owner(b"\x01\x00" * 8000)
    assert score == 0.9, scorer.last_error
    handed = seen.read_text()
    assert handed.startswith(("/proc/self/fd/", "/dev/shm/")), handed
    assert "/tmp/" not in handed
