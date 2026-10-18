"""Fixture harness: mock | record | live (§12.9 — mandatory, not optional).

An LLM app is non-deterministic, so the reproduce-and-fix loop only works
if model responses can be frozen and replayed. Fixtures are keyed by a
SHA-256 of the canonical request, so a replayed call returns exactly what
it returned on recording day. A mentor running GEMINI_MODE=mock gets the
owner's exact behaviour — no key, no quota, no network.

  live    real API, real responses
  record  real API + every request/response pair saved to fixtures/
  mock    no network — replay fixtures; on a miss, return a deterministic
          synthetic response (clearly flagged) so a fresh clone still runs.
          Set strict=True in tests that must prove a fixture exists.

Live-API sessions are message *sequences*, not single pairs (§12.9):
record_sequence/replay_sequence handle those as JSONL scripts for Phase 1.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def fixture_key(model: str, contents, config: dict | None = None) -> str:
    canonical = json.dumps(
        {"model": model, "contents": contents, "config": config or {}},
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FixtureMiss(KeyError):
    pass


class FixtureStore:
    def __init__(self, directory: Path, strict: bool = False):
        self.directory = Path(directory)
        self.strict = strict

    def _path(self, key: str) -> Path:
        return self.directory / f"{key}.json"

    def record(self, key: str, request: dict, response: dict) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        path.write_text(
            json.dumps({"request": request, "response": response}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def replay(self, key: str, request: dict) -> dict:
        path = self._path(key)
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            response = dict(data["response"])
            response.setdefault("fixture", {"key": key, "synthetic": False})
            return response
        if self.strict:
            raise FixtureMiss(
                f"no fixture {key} in {self.directory} — record it with "
                "GEMINI_MODE=record on a machine with a key, then commit fixtures/"
            )
        return synthetic_response(key, request)

    # -- Live-session sequences (Phase 1 replay scripts) --------------------
    def record_sequence(self, name: str, messages: list[dict]) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"seq-{name}.jsonl"
        path.write_text(
            "\n".join(json.dumps(m, ensure_ascii=False) for m in messages) + "\n",
            encoding="utf-8",
        )
        return path

    def replay_sequence(self, name: str) -> list[dict]:
        path = self.directory / f"seq-{name}.jsonl"
        if not path.exists():
            raise FixtureMiss(f"no session fixture seq-{name}.jsonl in {self.directory}")
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def synthetic_response(key: str, request: dict) -> dict:
    """Deterministic stand-in for an unrecorded request in mock mode.

    Same request => same response, forever (seeded by the fixture key).
    Always flagged synthetic so it can never be mistaken for model output
    in a bug report — a fixture *is* a bug report, a synth is not.
    """
    contents = request.get("contents", "")
    if isinstance(contents, list):
        contents = " ".join(str(c) for c in contents)
    digest = key[:8]
    text = (
        f"[mock-synthetic {digest}] No recorded fixture for this request. "
        f"Prompt began: {str(contents)[:80]!r}. Record real behaviour with "
        "GEMINI_MODE=record where a key exists."
    )
    return {
        "text": text,
        "usage": {"tokens_in": max(1, len(str(contents)) // 4), "tokens_out": 24},
        "fixture": {"key": key, "synthetic": True},
    }
