from __future__ import annotations

import sqlite3

import pytest

from assistant.embeddings import HashingEmbedder
from assistant.memory import MemoryRecord, SQLiteMemoryNamespace


def test_memory_record_round_trip():
    conn = sqlite3.connect(":memory:")
    ns = SQLiteMemoryNamespace(conn)
    embedder = HashingEmbedder()
    vec = embedder.embed(["Nairobi coffee roasters"])[0]

    rec = MemoryRecord(
        memory_id="mem-001",
        kind="preference",
        text="Prefers Kenyan AA single-origin coffee",
        source="stated",
        confidence=1.0,
        evidence=None,
        created_at="2026-11-18T10:00:00+00:00",
        updated_at="2026-11-18T10:00:00+00:00",
        embedding=vec,
        metadata={"origin": "user", "tag": "coffee"},
    )
    ns.put(rec)
    loaded = ns.get("mem-001")

    assert loaded is not None
    assert loaded.memory_id == rec.memory_id
    assert loaded.kind == "preference"
    assert loaded.text == rec.text
    assert loaded.source == "stated"
    assert loaded.confidence == pytest.approx(1.0)
    assert loaded.metadata == {"origin": "user", "tag": "coffee"}
    assert loaded.active is True
    assert loaded.trusted is False
    assert loaded.embedding is not None
    assert len(loaded.embedding) == len(vec)
    assert loaded.embedding == pytest.approx(vec, abs=1e-6)


def test_inferred_memory_requires_evidence():
    conn = sqlite3.connect(":memory:")
    ns = SQLiteMemoryNamespace(conn)
    bad = MemoryRecord(
        memory_id="mem-bad",
        kind="profile",
        text="Lives in Nairobi",
        source="inferred",
        confidence=0.6,
        evidence=None,
    )
    with pytest.raises(ValueError, match="evidence"):
        ns.put(bad)


def test_deactivate_hides_from_list_active():
    conn = sqlite3.connect(":memory:")
    ns = SQLiteMemoryNamespace(conn)
    ns.put(MemoryRecord(memory_id="m1", kind="profile", text="fact one"))
    ns.put(MemoryRecord(memory_id="m2", kind="profile", text="fact two"))

    assert {r.memory_id for r in ns.list_active()} == {"m1", "m2"}
    assert ns.deactivate("m1") is True
    assert ns.deactivate("m1") is False
    assert [r.memory_id for r in ns.list_active()] == ["m2"]
