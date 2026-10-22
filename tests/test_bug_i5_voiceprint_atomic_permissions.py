"""I5 regressions: biometric enrollment is private and atomically replaced."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from assistant.voicetest import enroll


def _embedding_corpus(root: Path) -> Path:
    corpus = root / "embeddings"
    corpus.mkdir()
    (corpus / "sample.embedding.json").write_text(
        json.dumps({"embedding": [1.0, 0.0], "speech_seconds": 1.0}),
        encoding="utf-8")
    return corpus


def test_bug_i5_enrollment_is_never_world_readable_even_under_umask_0022(
        tmp_path, monkeypatch):
    """I5: no observer can see a newly enrolled template before chmod."""
    corpus = _embedding_corpus(tmp_path)
    output = tmp_path / "voiceprint.json"
    observed_modes = []
    published_modes = []
    original_chmod = Path.chmod
    original_replace = os.replace

    def inspect_before_chmod(path, mode, *args, **kwargs):
        if path == output and path.exists():
            observed_modes.append(stat.S_IMODE(path.stat().st_mode))
        return original_chmod(path, mode, *args, **kwargs)

    def inspect_atomic_publish(source, destination):
        if Path(destination) == output:
            published_modes.append(stat.S_IMODE(Path(source).stat().st_mode))
        return original_replace(source, destination)

    monkeypatch.setattr(Path, "chmod", inspect_before_chmod)
    monkeypatch.setattr(os, "replace", inspect_atomic_publish)
    old_umask = os.umask(0o022)
    try:
        enroll(corpus, output, "test-ecapa")
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert all(mode == 0o600 for mode in observed_modes), observed_modes
    assert published_modes == [0o600]


def test_bug_i5_interrupted_atomic_enrollment_preserves_existing_template(
        tmp_path, monkeypatch):
    """I5: a failed publish cannot truncate the existing biometric template."""
    corpus = _embedding_corpus(tmp_path)
    output = tmp_path / "voiceprint.json"
    previous = b'{"model":"previous","dimension":1,"centroid":[1.0]}\n'
    output.write_bytes(previous)
    real_replace = os.replace
    calls = []

    def fail_publish(source, destination):
        calls.append((Path(source), Path(destination)))
        if Path(destination) == output:
            raise OSError("injected atomic-publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_publish)
    with pytest.raises(OSError, match="injected atomic-publish failure"):
        enroll(corpus, output, "test-ecapa")

    assert calls and calls[-1][1] == output
    assert output.read_bytes() == previous
    assert not list(tmp_path.glob(".voiceprint.json.*.tmp"))
