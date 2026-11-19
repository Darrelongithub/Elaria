from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from assistant.embeddings import HashingEmbedder
from assistant.memory import Memory, MemoryRecord, SQLiteMemoryNamespace


class _DummyStore:
    def add_fact(self, **_kwargs):
        return 1

    def forget_facts(self, _topic):
        return 0

    def list_facts(self, kind=None):
        return []


def test_recall_ranked_combines_similarity_and_recency():
    conn = sqlite3.connect(":memory:")
    ns = SQLiteMemoryNamespace(conn)
    embedder = HashingEmbedder()
    mem = Memory(_DummyStore(), embedder, namespace=ns)

    now = datetime(2026, 11, 19, 12, 0, 0, tzinfo=UTC)
    # Two equally similar memories, one recent and one 60 days old
    vec_invoice = embedder.embed(["March electricity invoice PDF"])[0]
    vec_other = embedder.embed(["unrelated gardening notes"])[0]

    ns.put(MemoryRecord(
        memory_id="old-invoice",
        kind="document",
        text="March electricity invoice PDF",
        created_at="2026-09-20T12:00:00+00:00",
        updated_at="2026-09-20T12:00:00+00:00",
        embedding=vec_invoice,
    ))
    ns.put(MemoryRecord(
        memory_id="new-invoice",
        kind="document",
        text="March electricity invoice PDF",
        created_at="2026-11-19T11:00:00+00:00",
        updated_at="2026-11-19T11:00:00+00:00",
        embedding=vec_invoice,
    ))
    ns.put(MemoryRecord(
        memory_id="new-unrelated",
        kind="note",
        text="unrelated gardening notes",
        created_at="2026-11-19T11:55:00+00:00",
        updated_at="2026-11-19T11:55:00+00:00",
        embedding=vec_other,
    ))

    res = mem.recall_ranked("March electricity invoice", now=now, min_similarity=0.1)
    assert res.journaled is True
    assert res.empty_reason is None
    assert [h.ref for h in res.hits[:2]] == ["new-invoice", "old-invoice"]
    assert res.hits[0].score > res.hits[1].score
    assert all(h.trusted is False for h in res.hits)


def test_recall_ranked_empty_corpus_states_non_discrimination():
    conn = sqlite3.connect(":memory:")
    ns = SQLiteMemoryNamespace(conn)
    mem = Memory(_DummyStore(), HashingEmbedder(), namespace=ns)

    res = mem.recall_ranked("anything")
    assert res.hits == []
    assert res.empty_reason is not None
    assert "empty_corpus" in res.empty_reason
    assert "cannot discriminate" in res.empty_reason
