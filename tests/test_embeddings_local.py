from __future__ import annotations

import http.client
import socket
import urllib.request

import pytest

from assistant.embeddings import (
    EgressRulingError,
    HashingEmbedder,
    backfill_embeddings,
    make_embedder,
)


class _Cfg:
    def __init__(self, mem_cfg: dict):
        self._mem = mem_cfg

    def section(self, name: str) -> dict:
        return self._mem if name == "memory" else {}


class _FakeChunkStore:
    def __init__(self):
        self.rows = [{"id": 1, "text": "local memory chunk"}]
        self.saved = {}

    def chunks_missing_embeddings(self, _batch: int):
        rows = self.rows
        self.rows = []
        return rows

    def set_chunk_embedding(self, chunk_id: int, blob: bytes):
        self.saved[chunk_id] = blob


def test_local_embedder_makes_zero_network_calls(monkeypatch):
    def _forbid(*_args, **_kwargs):
        raise AssertionError("network egress is forbidden in local-first mode")

    monkeypatch.setattr(socket, "socket", _forbid)
    monkeypatch.setattr(urllib.request, "urlopen", _forbid)
    monkeypatch.setattr(http.client, "HTTPConnection", _forbid)

    embedder = make_embedder(_Cfg({"embedder": "hashing"}))
    assert isinstance(embedder, HashingEmbedder)

    vecs = embedder.embed(["hello world", "offline memory"])
    assert len(vecs) == 2
    assert len(vecs[0]) == embedder.dimension

    store = _FakeChunkStore()
    assert backfill_embeddings(store, embedder) == 1
    assert 1 in store.saved


@pytest.mark.parametrize("provider", ["openai", "gemini", "cohere", "voyage", "api", "remote"])
def test_network_embedding_providers_fail_closed(provider: str):
    cfg = _Cfg({"embedder": provider, "api_key": "sk-should-never-be-used"})
    with pytest.raises(EgressRulingError, match="egress ruling"):
        make_embedder(cfg)
