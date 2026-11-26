"""BUILD-12 memory lifecycle — probationary inferences & owner tombstones.

These tests drive the REAL write path — `ErrandRunner`'s `skill_memory_infer`
against a real `Store` and a real `Memory` (PR #143's `propose_inferred`) —
never a hand-rolled stub. If the errand path bypasses tombstones or
deduplication again, this suite fails.
"""

from __future__ import annotations

import hashlib

import pytest

from assistant.embeddings import make_embedder
from assistant.errand import UntrustedObservation, skill_memory_infer
from assistant.memory import Memory
from assistant.store import Store

OBS_TEXT = (
    "preferred_substrate: coco_coir\n"
    "irrigation_schedule: dawn\n"
    "Owner prefers concise written status reports\n"
)


@pytest.fixture()
def memory_env(config):
    store = Store(config.db_path)
    memory = Memory(store, make_embedder(config))
    yield store, memory
    store.close()


def _obs(text: str = OBS_TEXT, *, path: str = "/ws/greenhouse.txt") -> UntrustedObservation:
    raw = text.encode("utf-8")
    return UntrustedObservation(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        byte_start=0,
        byte_end=len(raw),
        total_size=len(raw),
        text=text,
        eof=True,
        truncated=False,
    )


def _candidate(text: str, *, obs: UntrustedObservation, confidence: float = 0.99,
               kind: str = "preference") -> dict:
    return {
        "text": text,
        "kind": kind,
        "confidence": confidence,
        "evidence_quote": "preferred_substrate: coco_coir",
        "evidence_path": obs.path,
    }


def test_inference_is_pinned_probationary_and_duplicate_guarded(memory_env):
    store, memory = memory_env
    obs = _obs()
    candidate = _candidate("Owner prefers concise written status reports", obs=obs)

    res = skill_memory_infer(memory, [candidate], [obs])
    assert res["rejected"] == []
    assert len(res["stored"]) == 1
    stored = res["stored"][0]
    assert stored["source"] == "inferred"
    # Source is pinned in Python and confidence is capped at 0.85.
    rows = store.list_facts(active_only=False)
    row = next(r for r in rows if int(r["id"]) == stored["fact_id"])
    assert row["source"] == "inferred"
    assert row["confidence"] == pytest.approx(0.85)
    assert "sha256:" in str(row["evidence"]) and obs.sha256 in str(row["evidence"])

    # Exact re-proposal is a no-op.
    dup = skill_memory_infer(memory, [candidate], [obs])
    assert dup["stored"] == []
    assert dup["rejected"][0]["reason"] == "duplicate_active_fact"

    # A near-duplicate (>=80% token overlap, same kind) is refused by the
    # proposal-time deduplication, not stored twice.
    near = _candidate("Owner prefers concise status reports", obs=obs)
    near_res = skill_memory_infer(memory, [near], [obs])
    assert near_res["stored"] == []
    assert near_res["rejected"][0]["reason"] == "duplicate_active_fact"
    stored_texts = [
        f for f in store.list_facts(active_only=True)
        if f["source"] == "inferred"
    ]
    assert len(stored_texts) == 1


def test_inferred_recall_is_labelled_and_stated_wins(memory_env):
    _store, memory = memory_env
    obs = _obs()
    res = skill_memory_infer(
        memory,
        [_candidate("Prefers concise reports", obs=obs, confidence=0.7)],
        [obs],
    )
    assert res["stored"]
    inferred = memory.recall("concise reports")
    assert len(inferred) == 1 and inferred[0].probationary
    assert "UNVERIFIED INFERENCE" in inferred[0].prompt_text()
    assert inferred[0].trusted is False

    # An authenticated owner statement supersedes the tentative guess.
    memory.remember("Prefers concise reports", kind="preference",
                    source="stated", confidence=1.0)
    stated = memory.recall("concise reports")
    assert len(stated) == 1
    assert stated[0].fact_source == "stated" and not stated[0].probationary


def test_owner_rejection_tombstones_an_inference(memory_env):
    store, memory = memory_env
    obs = _obs()
    res = skill_memory_infer(
        memory,
        [_candidate("Likes short summaries", obs=obs, confidence=0.5)],
        [obs],
    )
    assert res["stored"]
    fid = res["stored"][0]["fact_id"]

    assert memory.reject_inference(fid)
    assert all(int(f["id"]) != fid for f in store.list_facts(active_only=True))

    # Re-proposing the same claim (as the next errand would) hits the
    # tombstone and is refused with a named reason.
    again = skill_memory_infer(
        memory,
        [_candidate("Likes short summaries", obs=obs, confidence=0.6)],
        [obs],
    )
    assert again["stored"] == []
    assert again["rejected"][0]["reason"] == "rejected_claim_tombstone"


def test_inference_requires_verifiable_source(memory_env):
    store, memory = memory_env
    # Direct API contract: a bad document hash is rejected outright.
    with pytest.raises(ValueError):
        memory.propose_inferred(
            "Fact", "profile", confidence=0.4,
            evidence="line 2", doc_sha256="bad")

    # The errand path refuses an observation whose digest is not a SHA-256 —
    # loudly, by name, and without storing anything.
    raw = b"abc"
    bad_obs = UntrustedObservation(
        path="/ws/bad.txt",
        sha256="not-a-sha256",
        byte_start=0,
        byte_end=len(raw),
        total_size=len(raw),
        text="abc",
        eof=True,
        truncated=False,
    )
    res = skill_memory_infer(
        memory,
        [{"text": "Likes unverified digests", "kind": "preference",
          "confidence": 0.5, "evidence_quote": "abc",
          "evidence_path": bad_obs.path}],
        [bad_obs],
    )
    assert res["stored"] == []
    assert res["rejected"][0]["reason"] == "unverifiable_document_hash"
    assert store.list_facts() == []
