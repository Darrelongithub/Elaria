"""Memory (§16) — offline, on your disk, yours. Plus hybrid recall.

Types: profile facts, preferences, commitments, relationship state.
Rules enforced in code:
- Stated beats inferred: `remember` stores source='stated'; anything
  inferred carries confidence + evidence and starts probationary
  (it may bias suggestions, never irreversible actions).
- Fully inspectable: `memory list` shows everything believed about
  you; `forget <topic>` deletes (deactivates) with no argument. A
  memory it can't show you is a memory it doesn't get to keep.
- Recall is LOCAL: FTS5 keyword + embedding cosine, merged by
  reciprocal-rank fusion (§3.8 — hybrid beats pure vector on exact
  strings like filenames). Gemini, when finally asked in `ask`, sees
  a few retrieved snippets — never the database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cost import iso_now
from .embeddings import Embedder, cosine, unpack

_STOPWORDS = {"where", "is", "the", "that", "this", "my", "me", "find", "show",
              "a", "an", "of", "for", "to", "in", "on", "what", "did", "do",
              "about", "from", "was", "were", "are", "i", "you", "it"}


@dataclass
class RecallHit:
    source: str  # document | fact | transcript
    ref: str     # path / fact id / transcript id
    text: str
    score: float


def _query_terms(query: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", query.lower())
            if t not in _STOPWORDS and len(t) >= 2]


class Memory:
    def __init__(self, store, embedder: Embedder):
        self.store = store
        self.embedder = embedder

    # -- facts ------------------------------------------------------------------
    def remember(self, text: str, kind: str = "profile", *, source: str = "stated",
                 confidence: float = 1.0, evidence: str | None = None) -> int:
        if source == "inferred" and not evidence:
            raise ValueError("inferred memories must show their evidence (§16)")
        return self.store.add_fact(ts=iso_now(), kind=kind, text=text.strip(),
                                   source=source, confidence=confidence,
                                   evidence=evidence)

    def forget(self, topic: str) -> int:
        return self.store.forget_facts(topic)

    def beliefs(self, kind: str | None = None) -> list[dict]:
        return self.store.list_facts(kind=kind)

    # -- hybrid recall -------------------------------------------------------------
    def recall(self, query: str, limit: int = 6) -> list[RecallHit]:
        terms = _query_terms(query)
        scores: dict[str, RecallHit] = {}

        def bump(key, hit: RecallHit, rank_component: float):
            if key in scores:
                scores[key].score += rank_component
            else:
                hit.score = rank_component
                scores[key] = hit

        # FTS arm (keyword exactness — filenames, names, codes). Terms go
        # through the store's OR arm so they stay literal search text; the
        # store, not this module, decides how to quote them for FTS5 (BH-E2).
        if terms:
            try:
                hits = self.store.search_documents_any(terms, limit=limit * 2)
            except Exception:
                hits = []
            for rank, hit in enumerate(hits):
                bump(hit["path"], RecallHit("document", hit["path"], hit["snip"], 0.0),
                     1.0 / (60 + rank))
        # Vector arm (rewordings the keyword arm misses). A relevance floor
        # keeps nonsense queries answerable-honestly: nearest ≠ relevant.
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
        # Facts: substring over active beliefs (tiny corpus, exact is right).
        lowered = query.lower()
        for fact in self.store.list_facts():
            fact_terms = set(_query_terms(fact["text"]))
            overlap = len(fact_terms & set(terms)) if terms else 0
            if overlap or (lowered and lowered in fact["text"].lower()):
                bump(f"fact:{fact['id']}",
                     RecallHit("fact", f"#{fact['id']} ({fact['kind']}, {fact['source']})",
                               fact["text"], 0.0),
                     0.02 + 0.01 * overlap)
        # Filename exactness (§3.8: hybrid exists because pure vectors fumble
        # exact strings — 'march' in a filename is a direct hit, weight it).
        if terms:
            term_set = set(terms)
            for hit in scores.values():
                if hit.source == "document":
                    name_terms = set(re.findall(r"[a-z0-9]+", hit.ref.lower()))
                    hit.score += 0.02 * len(name_terms & term_set)
        # Transcripts: your own dictated words are memory too.
        for transcript in self.store.recent_transcripts(50):
            text = transcript["raw_text"] or ""
            if terms and any(t in text.lower() for t in terms):
                bump(f"transcript:{transcript['id']}",
                     RecallHit("transcript", transcript.get("inbox_path") or "",
                               text[:200], 0.0), 0.015)
        return sorted(scores.values(), key=lambda h: -h.score)[:limit]

    def answer_where(self, query: str) -> str | None:
        """'Where's that invoice from March' — answered locally or not
        at all. Returns None when recall is weak ( caller may escalate
        to the model with snippets; a local miss must never bluff)."""
        hits = self.recall(query, limit=3)
        documents = [h for h in hits if h.source == "document"]
        if not documents:
            return None
        lines = [f"Found {len(documents)} candidate(s) locally:"]
        for hit in documents:
            lines.append(f"- {hit.ref}")
        return "\n".join(lines)
