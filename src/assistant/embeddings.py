"""Local embeddings (§10.5 decided: local — free, unlimited, no quota).

Two providers behind one seam:
  HashingEmbedder           deterministic stdlib hashed bag-of-words.
                            Runs anywhere (CI, containers, the UHD 620
                            at 3am), needs no downloads. It is honestly
                            NOT deep semantics — it captures lexical
                            overlap, which hybrid FTS+vector still
                            exploits (reworded queries partially match).
  SentenceTransformerEmbedder  real semantics via sentence-transformers
                            (`uv sync --extra embeddings`), CPU-feasible
                            for a personal corpus. Selected by config.

Vectors are float32 BLOBs in doc_chunks — sqlite-vec can index the same
column later without reshaping data; brute-force cosine over a personal
corpus (10^4–10^5 chunks) is milliseconds-to-seconds and honest.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
from typing import Protocol

_DIM = 384
_WORDS = re.compile(r"[a-z0-9]+")


def pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


class Embedder(Protocol):
    name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    name = "hashing-bow (stdlib, lexical)"
    dimension = _DIM

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vector = [0.0] * self.dimension
            for token in _WORDS.findall(text.lower()):
                digest = hashlib.sha256(token.encode()).digest()
                slot = int.from_bytes(digest[:2], "little") % self.dimension
                sign = 1.0 if digest[2] % 2 == 0 else -1.0
                vector[slot] += sign
            norm = math.sqrt(sum(v * v for v in vector)) or 1.0
            out.append([v / norm for v in vector])
        return out


class SentenceTransformerEmbedder:  # pragma: no cover - optional heavy dep
    name = "sentence-transformers"
    dimension = 384

    def __init__(self, model: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "real semantic embeddings need: uv sync --extra embeddings "
                "(or set memory.embedder = 'hashing' for the stdlib baseline)") from exc
        self._model = SentenceTransformer(model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


def make_embedder(config) -> Embedder:
    choice = config.section("memory").get("embedder", "hashing")
    if choice == "sentence-transformers":
        return SentenceTransformerEmbedder(
            config.section("memory").get("embedding_model", "all-MiniLM-L6-v2"))
    return HashingEmbedder()


def backfill_embeddings(store, embedder: Embedder, *, batch: int = 200) -> int:
    """Embed every chunk lacking a vector. Returns count embedded."""
    done = 0
    while missing := store.chunks_missing_embeddings(batch):
        vectors = embedder.embed([c["text"] for c in missing])
        for chunk, vector in zip(missing, vectors):
            store.set_chunk_embedding(chunk["id"], pack(vector))
        done += len(missing)
    return done
