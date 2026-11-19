from __future__ import annotations

from pathlib import Path

from assistant.indexer import EXCLUDED_DIRNAMES, Indexer


class _DummyCfg:
    def section(self, _name: str) -> dict:
        return {}


class _DummyStore:
    pass


def test_indexer_excludes_voice_cache_without_descending(tmp_path: Path):
    assert "voice-cache" in EXCLUDED_DIRNAMES
    vc = tmp_path / "voice-cache"
    vc.mkdir()
    (vc / "secret.txt").write_text("should not be indexed")
    (tmp_path / "notes.txt").write_text("hello world")

    idx = Indexer(_DummyCfg(), _DummyStore())
    walked = list(idx.iter_files(tmp_path))

    reasons = {p.name: reason for p, reason in walked}
    assert reasons.get("voice-cache") == "voice-cache"
    assert "secret.txt" not in reasons
    assert reasons["notes.txt"] is None
