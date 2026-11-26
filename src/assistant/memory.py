"""Memory (§16) — offline, on your disk, yours. Plus hybrid & ranked recall.

Types: profile facts, preferences, commitments, relationship state, and
persistent memory records in the Z-granted `memories` SQLite namespace (IF-5).
Rules enforced in code:
- Stated beats inferred: `remember` stores source='stated'; anything
  inferred carries confidence + evidence and starts probationary
  (it may bias suggestions, never irreversible actions).
- Fully inspectable: `memory list` shows everything believed about
  you; `forget <topic>` deletes (deactivates) with no argument. A
  memory it can't show you is a memory it doesn't get to keep.
- Recall is LOCAL: FTS5 keyword + embedding cosine, merged by
  reciprocal-rank fusion (§3.8) or recency+similarity scoring.
- IF-6 untrusted-input rail: recalled content is ALWAYS data (`trusted=False`),
  never executed as a command/intent/tool call, and every recall is
  journaled via D's journal service.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .cost import iso_now
from .embeddings import Embedder, cosine, pack, unpack

_STOPWORDS = {"where", "is", "the", "that", "this", "my", "me", "find", "show",
              "a", "an", "of", "for", "to", "in", "on", "what", "did", "do",
              "about", "from", "was", "were", "are", "i", "you", "it"}

MEMORIES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id     TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    text          TEXT NOT NULL,
    source        TEXT NOT NULL,
    confidence    REAL NOT NULL,
    evidence      TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    embedding     BLOB,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    active        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_memories_active_created
    ON memories (active, created_at DESC);
"""


@dataclass(frozen=True)
class MemoryRecord:
    """Persistent memory record over the Z-granted `memories` namespace (IF-5)."""

    memory_id: str
    kind: str
    text: str
    source: str = "stated"
    confidence: float = 1.0
    evidence: str | None = None
    created_at: str = field(default_factory=iso_now)
    updated_at: str = field(default_factory=iso_now)
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    active: bool = True
    trusted: bool = False  # IF-6: recalled content is untrusted data, never an instruction


@dataclass
class RecallHit:
    source: str  # document | fact | transcript | memory
    ref: str     # path / fact id / transcript id / memory_id
    text: str
    score: float
    trusted: bool = False  # IF-6: data only, never drives a tool
    fact_source: str | None = None
    confidence: float | None = None
    evidence: str | None = None
    probationary: bool = False

    def prompt_text(self) -> str:
        if self.probationary:
            return (f"[UNVERIFIED INFERENCE conf={self.confidence:.2f} "
                    f"evidence={self.evidence}] {self.text}")
        return self.text


@dataclass
class RecallResult:
    """Ranked recall output with explicit empty-result disambiguation (IF-5)."""

    hits: list[RecallHit]
    empty_reason: str | None = None
    journaled: bool = False


class SQLiteMemoryNamespace:
    """Self-contained SQLite namespace for `memories` (HR-B-1 / IF-5 seam)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(MEMORIES_SCHEMA_SQL)
        self.conn.commit()

    def put(self, record: MemoryRecord) -> MemoryRecord:
        if record.source == "inferred" and not record.evidence:
            raise ValueError("inferred memories must show their evidence (§16)")
        blob = pack(record.embedding) if record.embedding is not None else None
        self.conn.execute(
            """
            INSERT INTO memories (
                memory_id, kind, text, source, confidence, evidence,
                created_at, updated_at, embedding, metadata_json, active
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                kind=excluded.kind,
                text=excluded.text,
                source=excluded.source,
                confidence=excluded.confidence,
                evidence=excluded.evidence,
                updated_at=excluded.updated_at,
                embedding=excluded.embedding,
                metadata_json=excluded.metadata_json,
                active=excluded.active
            """,
            (
                record.memory_id,
                record.kind,
                record.text.strip(),
                record.source,
                float(record.confidence),
                record.evidence,
                record.created_at,
                record.updated_at,
                blob,
                json.dumps(record.metadata, sort_keys=True),
                1 if record.active else 0,
            ),
        )
        self.conn.commit()
        return record

    def get(self, memory_id: str) -> MemoryRecord | None:
        row = self.conn.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list_active(self, kind: str | None = None) -> list[MemoryRecord]:
        if kind is not None:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE active = 1 AND kind = ? ORDER BY created_at DESC",
                (kind,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM memories WHERE active = 1 ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def deactivate(self, memory_id: str) -> bool:
        cur = self.conn.execute(
            "UPDATE memories SET active = 0, updated_at = ? WHERE memory_id = ? AND active = 1",
            (iso_now(), memory_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MemoryRecord:
        blob = row["embedding"]
        return MemoryRecord(
            memory_id=row["memory_id"],
            kind=row["kind"],
            text=row["text"],
            source=row["source"],
            confidence=float(row["confidence"]),
            evidence=row["evidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            embedding=unpack(blob) if blob is not None else None,
            metadata=json.loads(row["metadata_json"] or "{}"),
            active=bool(row["active"]),
            trusted=False,
        )


def _query_terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", query.lower())
            if t not in _STOPWORDS and len(t) >= 2]


def _parse_iso(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _recency_score(created_at: str, now: datetime, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    try:
        age_seconds = max(0.0, (now - _parse_iso(created_at)).total_seconds())
    except ValueError:
        return 0.0
    age_days = age_seconds / 86400.0
    return math.exp(-math.log(2.0) * age_days / half_life_days)


def _default_journal_fn() -> Callable[..., Any] | None:
    try:
        from . import journal_log  # D's journal service (present on 77143d9+)
        return getattr(journal_log, "log_event", None)
    except ImportError:
        return None


class Memory:
    def __init__(
        self,
        store,
        embedder: Embedder,
        *,
        namespace: SQLiteMemoryNamespace | None = None,
        journal: Callable[..., Any] | None = None,
    ):
        self.store = store
        self.embedder = embedder
        self.namespace = namespace
        self._journal = journal if journal is not None else _default_journal_fn()
        self.recall_journal: list[dict[str, Any]] = []

    def _emit_recall_journal(
        self,
        query: str,
        hits: list[RecallHit],
        *,
        session_id: str = "-",
        empty_reason: str | None = None,
    ) -> bool:
        q_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
        verdict = "hit" if hits else "miss"
        refs = ",".join(h.ref for h in hits[:3]) if hits else (empty_reason or "none")
        detail = f"q={q_hash} count={len(hits)} trusted=False refs={refs}"
        entry = {
            "event": "memory.recall",
            "level": "info",
            "session_id": session_id,
            "verdict": verdict,
            "detail": detail,
        }
        self.recall_journal.append(entry)
        if self._journal is not None:
            try:
                self._journal(
                    "memory.recall",
                    level="info",
                    session_id=session_id,
                    verdict=verdict,
                    detail=detail,
                )
                return True
            except Exception:
                return False
        return True

    # -- facts & namespace records ----------------------------------------------
    def remember(self, text: str, kind: str = "profile", *, source: str = "stated",
                 confidence: float = 1.0, evidence: str | None = None) -> int:
        if source == "inferred" and not evidence:
            raise ValueError("inferred memories must show their evidence (§16)")
        if self.namespace is not None:
            vec = self.embedder.embed([text.strip()])[0]
            ts = iso_now()
            self.namespace.put(
                MemoryRecord(
                    memory_id=uuid.uuid4().hex,
                    kind=kind,
                    text=text.strip(),
                    source=source,
                    confidence=confidence,
                    evidence=evidence,
                    created_at=ts,
                    updated_at=ts,
                    embedding=vec,
                )
            )
        return self.store.add_fact(ts=iso_now(), kind=kind, text=text.strip(),
                                   source=source, confidence=confidence,
                                   evidence=evidence)

    def propose_inferred(self, text: str, kind: str, *, confidence: float,
                         evidence: str, doc_sha256: str) -> int | None:
        """Persist a strictly probationary, provenance-bound candidate.

        Caller supplies a content hash and a citable evidence span. The API
        pins source in Python; callers cannot promote by choosing a source.
        """
        claim = str(text or "").strip()
        citation = str(evidence or "").strip()
        digest = str(doc_sha256 or "").strip().lower()
        if not claim or not citation or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("inference requires text, evidence, and a SHA-256 document hash")
        claim_hash = hashlib.sha256(f"{kind.lower()}:{' '.join(claim.lower().split())}".encode()).hexdigest()
        if hasattr(self.store, "is_fact_claim_rejected") and self.store.is_fact_claim_rejected(claim_hash):
            return None
        existing = self.store.list_facts(active_only=True)
        normalized = set(_query_terms(claim))
        for row in existing:
            overlap = normalized & set(_query_terms(row["text"]))
            if row["kind"] == kind and normalized and len(overlap) / len(normalized) >= .8:
                return None
        return self.store.add_fact(
            ts=iso_now(), kind=kind, text=claim, source="inferred",
            confidence=min(.85, max(0.0, float(confidence))),
            evidence=f"sha256:{digest} span:{citation}")

    def reject_inference(self, fact_id: int) -> bool:
        rows = self.store.list_facts(active_only=False)
        row = next((r for r in rows if int(r["id"]) == int(fact_id)), None)
        if row is None or row.get("source") != "inferred":
            return False
        claim_hash = hashlib.sha256(
            f"{row['kind'].lower()}:{' '.join(row['text'].lower().split())}".encode()
        ).hexdigest()
        if hasattr(self.store, "reject_fact_claim"):
            self.store.reject_fact_claim(fact_hash=claim_hash, kind=row["kind"],
                                         ts=iso_now(), evidence=row.get("evidence"))
        self.store.deactivate_facts([int(fact_id)])
        return True

    def forget(self, topic: str) -> int:
        return self.store.forget_facts(topic)

    def beliefs(self, kind: str | None = None) -> list[dict]:
        return self.store.list_facts(kind=kind)

    # -- ranked recall over SQLiteMemoryNamespace -------------------------------
    def recall_ranked(
        self,
        query: str,
        *,
        limit: int = 6,
        now: datetime | None = None,
        recency_weight: float = 0.3,
        similarity_weight: float = 0.7,
        half_life_days: float = 30.0,
        min_similarity: float = 0.1,
        session_id: str = "-",
    ) -> RecallResult:
        """Rank memories by weighted similarity + recency; journal every recall."""
        if self.namespace is None:
            raise RuntimeError("recall_ranked requires a SQLiteMemoryNamespace")
        records = self.namespace.list_active()
        if not records:
            journaled = self._emit_recall_journal(
                query, [], session_id=session_id, empty_reason="empty_corpus"
            )
            return RecallResult(
                hits=[],
                empty_reason=(
                    "empty_corpus: no active memories stored; cannot discriminate "
                    "between an absent topic and an unindexed corpus"
                ),
                journaled=journaled,
            )
        if not query.strip():
            journaled = self._emit_recall_journal(
                query, [], session_id=session_id, empty_reason="empty_query"
            )
            return RecallResult(
                hits=[],
                empty_reason="empty_query: blank query cannot rank similarity",
                journaled=journaled,
            )

        now_dt = now if now is not None else datetime.now(UTC)
        query_vec = self.embedder.embed([query])[0]
        hits: list[RecallHit] = []
        for rec in records:
            vec = rec.embedding if rec.embedding is not None else self.embedder.embed([rec.text])[0]
            sim = cosine(query_vec, vec)
            if sim < min_similarity:
                continue
            recency = _recency_score(rec.created_at, now_dt, half_life_days)
            score = similarity_weight * sim + recency_weight * recency
            hits.append(
                RecallHit(
                    source="memory",
                    ref=rec.memory_id,
                    text=rec.text,
                    score=score,
                    trusted=False,
                )
            )
        hits.sort(key=lambda h: -h.score)
        top = hits[:limit]
        empty_reason = None if top else (
            f"below_similarity_floor: {len(records)} active memories checked, "
            f"none reached min_similarity={min_similarity}; does not prove topic absence"
        )
        journaled = self._emit_recall_journal(
            query, top, session_id=session_id, empty_reason=empty_reason
        )
        return RecallResult(hits=top, empty_reason=empty_reason, journaled=journaled)

    # -- hybrid recall ----------------------------------------------------------
    def recall(self, query: str, limit: int = 6, *, session_id: str = "-") -> list[RecallHit]:
        terms = _query_terms(query)
        scores: dict[str, RecallHit] = {}

        def bump(key, hit: RecallHit, rank_component: float):
            if key in scores:
                scores[key].score += rank_component
            else:
                hit.score = rank_component
                scores[key] = hit

        if terms:
            try:
                hits = self.store.search_documents_any(terms, limit=limit * 2)
            except Exception:
                hits = []
            for rank, hit in enumerate(hits):
                bump(hit["path"], RecallHit("document", hit["path"], hit["snip"], 0.0),
                     1.0 / (60 + rank))
        chunks = self.store.embedded_chunks()
        if chunks and query.strip():
            query_vec = self.embedder.embed([query])[0]
            scored = [(cosine(query_vec, unpack(c["embedding"])), c) for c in chunks]
            ranked = [c for sim, c in sorted(scored, key=lambda s: -s[0])
                      if sim >= 0.25]
            for rank, chunk in enumerate(ranked[: limit * 2]):
                bump(chunk["path"],
                     RecallHit("document", chunk["path"], chunk["text"][:200], 0.0),
                     1.0 / (60 + rank))
        lowered = query.lower()
        facts = self.store.list_facts()
        stated_by_kind = {}
        for fact in facts:
            if fact.get("source") == "stated":
                stated_by_kind.setdefault(fact["kind"], []).append(
                    set(_query_terms(fact["text"])))
        now = datetime.now(UTC)
        for fact in facts:
            fact_terms = set(_query_terms(fact["text"]))
            overlap = len(fact_terms & set(terms)) if terms else 0
            if not (overlap or (lowered and lowered in fact["text"].lower())):
                continue
            inferred = fact.get("source") == "inferred"
            # An inference contradicted/covered by any stated fact in its kind
            # is omitted; stated knowledge always wins over tentative material.
            contradicted = inferred and any(
                bool(fact_terms & stated_terms)
                for stated_terms in stated_by_kind.get(fact["kind"], []))
            if contradicted:
                continue
            confidence = min(.85, max(0.0, float(fact.get("confidence", 1.0))))
            try:
                age_days = max(0.0, (now - _parse_iso(fact["ts"])).total_seconds() / 86400)
            except (ValueError, TypeError):
                age_days = 0.0
            if inferred and age_days >= 730:
                continue  # stale tentative claims expire from recall
            decay = math.exp(-math.log(2) * age_days / 180.0) if inferred else 1.0
            factor = confidence * .5 * decay if inferred else 1.0
            hit = RecallHit("fact", f"#{fact['id']} ({fact['kind']}, {fact['source']})",
                            fact["text"], 0.0, fact_source=fact.get("source"),
                            confidence=confidence, evidence=fact.get("evidence"),
                            probationary=inferred)
            bump(f"fact:{fact['id']}", hit,
                 (0.02 + 0.01 * overlap) * factor)
        if terms:
            term_set = set(terms)
            for hit in scores.values():
                if hit.source == "document":
                    name_terms = set(re.findall(r"[a-z0-9]+", hit.ref.lower()))
                    hit.score += 0.02 * len(name_terms & term_set)
        for transcript in self.store.recent_transcripts(50):
            text = transcript["raw_text"] or ""
            if terms and any(t in text.lower() for t in terms):
                bump(f"transcript:{transcript['id']}",
                     RecallHit("transcript", transcript.get("inbox_path") or "",
                               text[:200], 0.0), 0.015)
        result = sorted(scores.values(), key=lambda h: -h.score)[:limit]
        self._emit_recall_journal(query, result, session_id=session_id)
        return result

    def answer_where(self, query: str) -> str | None:
        """'Where's that invoice from March' — answered locally or not
        at all. Returns None when recall is weak (caller may escalate
        to the model with snippets; a local miss must never bluff)."""
        hits = self.recall(query, limit=3)
        documents = [h for h in hits if h.source == "document"]
        if not documents:
            return None
        lines = [f"Found {len(documents)} candidate(s) locally:"]
        for hit in documents:
            lines.append(f"- {hit.ref}")
        return "\n".join(lines)
