"""Control-plane bridge receipts/state in the existing synthetic hands.db.

Receipt 'started' is committed before a mutation. A lost acknowledgement cannot
cause a replay. This is not an operation journal or an alternative ask queue.
"""
from __future__ import annotations

import json
import sqlite3

from .queue import ParkedQueue


class BridgeState:
    LIMIT = 512  # bounded synthetic-session request history; never evict and replay

    def __init__(self, queue: ParkedQueue):
        self.db = sqlite3.connect(queue.path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS bridge_state (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS bridge_receipts (
                epoch TEXT NOT NULL, nonce TEXT NOT NULL, digest TEXT NOT NULL,
                state TEXT NOT NULL, PRIMARY KEY(epoch, nonce));
        ''')

    def load(self) -> dict:
        row = self.db.execute("SELECT value FROM bridge_state WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {"phase": "idle", "errand": None, "fixture": "composite"}

    def save(self, state: dict):
        with self.db:
            self.db.execute("INSERT INTO bridge_state VALUES(1,?) ON CONFLICT(id) "
                            "DO UPDATE SET value=excluded.value", (json.dumps(state),))

    def begin(self, epoch: str, nonce: str, digest: str) -> str:
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM bridge_receipts WHERE epoch=? AND nonce=?",
                                  (epoch, nonce)).fetchone()
            if row:
                return row["state"] if row["digest"] == digest else "conflict"
            if self.db.execute("SELECT count(*) FROM bridge_receipts").fetchone()[0] >= self.LIMIT:
                return "full"
            self.db.execute("INSERT INTO bridge_receipts VALUES(?,?,?,'started')", (epoch, nonce, digest))
            return "new"

    def finish(self, epoch: str, nonce: str):
        with self.db:
            self.db.execute("UPDATE bridge_receipts SET state='done' WHERE epoch=? AND nonce=?", (epoch, nonce))

    def close(self):
        self.db.close()
