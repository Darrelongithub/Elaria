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
            self._conn.commit()

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
