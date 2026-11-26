from __future__ import annotations

import hashlib

from assistant.memory import Memory


class Facts:
    def __init__(self):
        self.rows = []
        self.rejected = set()

    def add_fact(self, **row):
        row["id"] = len(self.rows) + 1
        row["active"] = 1
        self.rows.append(row)
        return row["id"]

    def list_facts(self, kind=None, active_only=True):
        return [r for r in self.rows if (not active_only or r["active"])
                and (kind is None or kind == r["kind"])]

    def forget_facts(self, _topic):
        return 0

    def is_fact_claim_rejected(self, claim_hash):
        return claim_hash in self.rejected

    def reject_fact_claim(self, *, fact_hash, **_kwargs):
        self.rejected.add(fact_hash)

    def deactivate_facts(self, ids):
        for row in self.rows:
            if row["id"] in ids:
                row["active"] = 0

    def search_documents_any(self, *_args, **_kwargs):
        return []

    def embedded_chunks(self):
        return []

    def recent_transcripts(self, *_args, **_kwargs):
        return []


class Embedder:
    name = "unused"


def test_inference_is_pinned_probationary_and_duplicate_guarded():
    facts = Facts()
    memory = Memory(facts, Embedder())
    digest = hashlib.sha256(b"source").hexdigest()
    fid = memory.propose_inferred("Prefers concise reports", "preference",
                                  confidence=.99, evidence="line 4",
                                  doc_sha256=digest)
    assert fid == 1
    row = facts.rows[0]
    assert row["source"] == "inferred" and row["confidence"] == .85
    assert digest in row["evidence"]
    assert memory.propose_inferred("Prefers concise reports", "preference",
                                   confidence=.8, evidence="line 8",
                                   doc_sha256=digest) is None


def test_inferred_recall_is_labelled_and_stated_wins():
    facts = Facts()
    memory = Memory(facts, Embedder())
    facts.add_fact(ts="2026-11-26T00:00:00+00:00", kind="preference",
                   text="Prefers concise reports", source="inferred",
                   confidence=.7, evidence="sha256:abc span:line 4")
    inferred = memory.recall("concise reports")
    assert len(inferred) == 1 and inferred[0].probationary
    assert "UNVERIFIED INFERENCE" in inferred[0].prompt_text()
    assert inferred[0].trusted is False
    facts.add_fact(ts="2026-11-26T00:00:00+00:00", kind="preference",
                   text="Prefers concise reports", source="stated", confidence=1.0)
    stated = memory.recall("concise reports")
    assert len(stated) == 1
    assert stated[0].fact_source == "stated" and not stated[0].probationary


def test_owner_rejection_tombstones_an_inference():
    facts = Facts()
    memory = Memory(facts, Embedder())
    digest = hashlib.sha256(b"source").hexdigest()
    fid = memory.propose_inferred("Likes short summaries", "preference",
                                  confidence=.5, evidence="line 9",
                                  doc_sha256=digest)
    assert memory.reject_inference(fid)
    assert facts.rows[0]["active"] == 0
    assert memory.propose_inferred("Likes short summaries", "preference",
                                   confidence=.6, evidence="line 12",
                                   doc_sha256=digest) is None


def test_inference_requires_verifiable_source():
    memory = Memory(Facts(), Embedder())
    try:
        memory.propose_inferred("fact", "profile", confidence=.4,
                                evidence="line 2", doc_sha256="bad")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid evidence hash accepted")
