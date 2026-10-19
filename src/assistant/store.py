"""SQLite store — the ledger comes first (GETTING-STARTED Step 5.2).

Phase 0 creates: `llm_calls` (cost ledger, §3.2 — written on EVERY model
call), `operations` (safety-spine journal, §4.2 — schema now, executor in
Phase 4), `persona_events` (governor decision log, §13.2) and `state`
(small key/value for daemon + relationship state). Later phases add
conversations/documents/etc. (§3.8) without reshaping these.

One file: ~/.local/share/assistant/assistant.db. No network code path
exists in this module — memory is offline by architecture (§16).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import ClassVar

SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,               -- ISO-8601 UTC
  correlation_id TEXT NOT NULL,   -- groups harness retries/escalations
  role TEXT NOT NULL,             -- chat | organise | cleanup | ...
  model TEXT NOT NULL,
  mode TEXT NOT NULL,             -- live | record | mock
  tokens_in INTEGER NOT NULL DEFAULT 0,
  tokens_out INTEGER NOT NULL DEFAULT 0,
  tokens_estimated INTEGER NOT NULL DEFAULT 0,  -- 1 when API gave no usage
  audio_seconds REAL NOT NULL DEFAULT 0,
  cost_usd REAL NOT NULL DEFAULT 0,   -- shadow cost at paid rates; 0 billed on free tier
  latency_ms REAL NOT NULL DEFAULT 0,
  ok INTEGER NOT NULL DEFAULT 1,
  verified INTEGER,               -- harness verification outcome (§17), NULL if n/a
  attempt INTEGER NOT NULL DEFAULT 1,
  fixture_key TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS operations (
  id INTEGER PRIMARY KEY,
  plan_id INTEGER,
  ts TEXT,
  op TEXT,            -- move | rename | copy | mkdir | trash
  src TEXT, dst TEXT,
  sha256_before TEXT, sha256_after TEXT, bytes INTEGER,
  status TEXT,        -- intent | committed | failed | rolled_back
  error TEXT
);

CREATE TABLE IF NOT EXISTS persona_events (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,          -- decision | pushback | ack | tone
  detail TEXT NOT NULL         -- JSON; decisions + reasons, never canned lines
);

CREATE TABLE IF NOT EXISTS transcripts (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  session_id TEXT NOT NULL,
  audio_path TEXT,              -- raw audio is the truth; always kept (§12.5)
  raw_text TEXT NOT NULL,       -- the record
  cleaned_text TEXT,            -- the convenience (NULL if cleanup skipped)
  language TEXT NOT NULL,
  backend TEXT NOT NULL,        -- gemini_live | gemini_batch | local | mock
  model TEXT,
  duration_s REAL NOT NULL DEFAULT 0,
  divergence_pct REAL,          -- cleanup diff-gate measurement (§12.5)
  flagged INTEGER NOT NULL DEFAULT 0,  -- 1 = divergence/language gate tripped
  inbox_path TEXT
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  path TEXT UNIQUE NOT NULL,
  root TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  mime TEXT,
  ext TEXT,
  indexed_ts TEXT NOT NULL,
  never_send INTEGER NOT NULL DEFAULT 0,  -- §10.7: content stays off the cloud
  status TEXT NOT NULL DEFAULT 'indexed'  -- indexed | changed | missing
);

CREATE TABLE IF NOT EXISTS doc_chunks (
  id INTEGER PRIMARY KEY,
  doc_id INTEGER NOT NULL REFERENCES documents(id),
  chunk_no INTEGER NOT NULL,
  text TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  root TEXT NOT NULL,
  mode TEXT NOT NULL,              -- shadow (Phase 3) | live (Phase 4)
  status TEXT NOT NULL,            -- building | ready | failed
  total INTEGER NOT NULL DEFAULT 0,
  placed_tier0 INTEGER NOT NULL DEFAULT 0,
  abstained INTEGER NOT NULL DEFAULT 0,
  shadow_log_path TEXT,
  stats_json TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS plan_items (
  id INTEGER PRIMARY KEY,
  plan_id INTEGER NOT NULL REFERENCES plans(id),
  doc_id INTEGER,
  src TEXT NOT NULL,
  dest TEXT,                       -- proposed destination FOLDER (taxonomy)
  new_name TEXT,
  confidence REAL,
  tier INTEGER,                    -- 0 in Phase 3; 1/2 join in Phase 4
  rule TEXT,
  reason TEXT,
  decision TEXT NOT NULL           -- auto | review | unsorted | abstain (§4.4)
);

CREATE TABLE IF NOT EXISTS state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self.fts5_available = self._init_fts5()
            self._conn.commit()

    def _init_fts5(self) -> bool:
        """FTS5 keyword search over chunks (§3.8 hybrid retrieval starts
        here; vectors join in Phase 5). Guarded: some SQLite builds lack
        FTS5 — search then degrades to LIKE, never to a crash."""
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS doc_chunks_fts "
                "USING fts5(text, content='doc_chunks', content_rowid='id')")
            return True
        except Exception:
            return False

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- cost ledger (§3.2: a ledger write on every call) -------------------
    def log_llm_call(self, **fields) -> int:
        columns = [
            "ts", "correlation_id", "role", "model", "mode", "tokens_in",
            "tokens_out", "tokens_estimated", "audio_seconds", "cost_usd",
            "latency_ms", "ok", "verified", "attempt", "fixture_key", "error",
        ]
        values = [fields.get(c) for c in columns]
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO llm_calls ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' * len(columns))})",
                values,
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def llm_summary(self, since_iso: str | None = None) -> dict:
        where = "WHERE ts >= ?" if since_iso else ""
        params = (since_iso,) if since_iso else ()
        with self._lock:
            row = self._conn.execute(
                f"""SELECT COUNT(*) AS calls,
                           COALESCE(SUM(tokens_in),0) AS tokens_in,
                           COALESCE(SUM(tokens_out),0) AS tokens_out,
                           COALESCE(SUM(audio_seconds),0) AS audio_seconds,
                           COALESCE(SUM(cost_usd),0) AS cost_usd,
                           COALESCE(SUM(ok=0),0) AS failures
                    FROM llm_calls {where}""",
                params,
            ).fetchone()
            by_model = self._conn.execute(
                f"""SELECT model, mode, COUNT(*) AS calls,
                           COALESCE(SUM(tokens_in+tokens_out),0) AS tokens,
                           COALESCE(SUM(cost_usd),0) AS cost_usd
                    FROM llm_calls {where}
                    GROUP BY model, mode ORDER BY calls DESC""",
                params,
            ).fetchall()
        return {
            "calls": row["calls"],
            "tokens_in": row["tokens_in"],
            "tokens_out": row["tokens_out"],
            "audio_seconds": row["audio_seconds"],
            "cost_usd": row["cost_usd"],
            "failures": row["failures"],
            "by_model": [dict(r) for r in by_model],
        }

    def calls_since(self, since_iso: str, model: str | None = None) -> int:
        query = "SELECT COUNT(*) AS n FROM llm_calls WHERE ts >= ? AND mode != 'mock'"
        params: tuple = (since_iso,)
        if model:
            query += " AND model = ?"
            params = (since_iso, model)
        with self._lock:
            return int(self._conn.execute(query, params).fetchone()["n"])

    # -- transcripts (raw + cleaned side by side, §12.5) ----------------------
    _TRANSCRIPT_COLUMNS: ClassVar[list[str]] = [
        "ts", "session_id", "audio_path", "raw_text", "cleaned_text", "language",
        "backend", "model", "duration_s", "divergence_pct", "flagged", "inbox_path",
    ]

    def log_transcript(self, **fields) -> int:
        values = [fields.get(c) for c in self._TRANSCRIPT_COLUMNS]
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO transcripts ({', '.join(self._TRANSCRIPT_COLUMNS)}) "
                f"VALUES ({', '.join('?' * len(self._TRANSCRIPT_COLUMNS))})",
                values,
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def recent_transcripts(self, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM transcripts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    # -- documents / chunks (indexer, §3.7-3.8) -------------------------------
    def upsert_document(self, *, path, root, sha256, size, mtime, mime, ext,
                        indexed_ts, never_send, text_chunks: list[str]) -> int:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO documents (path, root, sha256, size, mtime, mime, ext,
                                          indexed_ts, never_send, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'indexed')
                   ON CONFLICT(path) DO UPDATE SET root=excluded.root,
                     sha256=excluded.sha256, size=excluded.size, mtime=excluded.mtime,
                     mime=excluded.mime, ext=excluded.ext, indexed_ts=excluded.indexed_ts,
                     never_send=excluded.never_send, status='indexed'
                   RETURNING id""",
                (path, root, sha256, size, mtime, mime, ext, indexed_ts, never_send),
            )
            doc_id = int(cur.fetchone()[0])
            self._conn.execute("DELETE FROM doc_chunks WHERE doc_id = ?", (doc_id,))
            self._conn.executemany(
                "INSERT INTO doc_chunks (doc_id, chunk_no, text) VALUES (?, ?, ?)",
                [(doc_id, i, chunk) for i, chunk in enumerate(text_chunks)],
            )
            if self.fts5_available:
                self._conn.execute(
                    "INSERT INTO doc_chunks_fts (doc_chunks_fts) VALUES ('rebuild')")
            self._conn.commit()
            return doc_id

    def document_by_path(self, path: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE path = ?", (path,)).fetchone()
        return dict(row) if row else None

    def documents_in_root(self, root: str, *, active_only: bool = True) -> list[dict]:
        query = "SELECT * FROM documents WHERE root = ?"
        if active_only:
            query += " AND status != 'missing'"
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY path", (root,)).fetchall()
        return [dict(r) for r in rows]

    def mark_missing(self, paths: list[str]) -> None:
        with self._lock:
            self._conn.executemany(
                "UPDATE documents SET status = 'missing' WHERE path = ?",
                [(p,) for p in paths])
            self._conn.commit()

    def document_preview(self, doc_id: int, chars: int = 600) -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT text FROM doc_chunks WHERE doc_id = ? ORDER BY chunk_no LIMIT 1",
                (doc_id,)).fetchone()
        return row["text"][:chars] if row else ""

    def search_documents(self, query: str, limit: int = 10) -> list[dict]:
        """FTS5 keyword search (LIKE fallback). Local-only: zero tokens."""
        with self._lock:
            if self.fts5_available:
                rows = self._conn.execute(
                    """SELECT d.path, snippet(doc_chunks_fts, 0, '[', ']', '…', 12) AS snip
                       FROM doc_chunks_fts f JOIN doc_chunks c ON c.id = f.rowid
                       JOIN documents d ON d.id = c.doc_id
                       WHERE doc_chunks_fts MATCH ? AND d.status != 'missing'
                       ORDER BY rank LIMIT ?""",
                    (query, limit)).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT d.path, substr(c.text, 1, 120) AS snip
                       FROM doc_chunks c JOIN documents d ON d.id = c.doc_id
                       WHERE c.text LIKE ? AND d.status != 'missing' LIMIT ?""",
                    (f"%{query}%", limit)).fetchall()
        return [dict(r) for r in rows]

    # -- plans (shadow mode first, §4.3) -------------------------------------
    def create_plan(self, ts: str, root: str, mode: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO plans (ts, root, mode, status) VALUES (?, ?, ?, 'building')",
                (ts, root, mode))
            self._conn.commit()
            return int(cur.lastrowid)

    def finish_plan(self, plan_id: int, *, total: int, placed: int, abstained: int,
                    shadow_log_path: str | None, stats_json: str,
                    error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE plans SET status = ?, total = ?, placed_tier0 = ?, "
                "abstained = ?, shadow_log_path = ?, stats_json = ?, error = ? "
                "WHERE id = ?",
                ("failed" if error else "ready", total, placed, abstained,
                 shadow_log_path, stats_json, error, plan_id))
            self._conn.commit()

    def add_plan_items(self, plan_id: int, items: list[dict]) -> None:
        columns = ["doc_id", "src", "dest", "new_name", "confidence",
                   "tier", "rule", "reason", "decision"]
        with self._lock:
            self._conn.executemany(
                f"INSERT INTO plan_items (plan_id, {', '.join(columns)}) "
                f"VALUES (?, {', '.join('?' * len(columns))})",
                [(plan_id, *[item.get(c) for c in columns]) for item in items])
            self._conn.commit()

    def get_plan(self, plan_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return dict(row) if row else None

    def list_plans(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM plans ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def plan_items(self, plan_id: int, decision: str | None = None) -> list[dict]:
        query = "SELECT * FROM plan_items WHERE plan_id = ?"
        params: tuple = (plan_id,)
        if decision:
            query += " AND decision = ?"
            params = (plan_id, decision)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY src", params).fetchall()
        return [dict(r) for r in rows]

    # -- safety-spine journal (§4.2) ----------------------------------------
    def outstanding_intents(self) -> list[dict]:
        """Intents with no commit — daemon startup recovery inspects these."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM operations WHERE status = 'intent' ORDER BY id"
            ).fetchall()
        return [dict(r) for r in rows]

    # -- persona governor log + tiny state ----------------------------------
    def log_persona_event(self, ts: str, kind: str, detail_json: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO persona_events (ts, kind, detail) VALUES (?, ?, ?)",
                (ts, kind, detail_json),
            )
            self._conn.commit()

    def get_state(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO state (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()
