"""A6/R5 private control-plane queue. All paths come from a SyntheticSpace.

SQLite transactions serialize decisions/claims. No expiration, auto-approval,
blind replay, or automatic resumption of an uncertain running step.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time

from .plan import Plan
from .sandbox import SyntheticSpace


class ParkedQueue:
    def __init__(self, space: SyntheticSpace):
        if type(space) is not SyntheticSpace:
            raise TypeError("only minted synthetic state is permitted")
        self.path = space.control / "hands.db"
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
        self._db = sqlite3.connect(self.path, timeout=5, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript('''
            CREATE TABLE IF NOT EXISTS errands (
                id TEXT PRIMARY KEY, plan_hash TEXT NOT NULL, plan BLOB NOT NULL,
                mismatches INTEGER NOT NULL DEFAULT 0, cancelled INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS asks (
                id INTEGER PRIMARY KEY, errand TEXT NOT NULL, plan_hash TEXT NOT NULL,
                step INTEGER NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS steps (
                errand TEXT NOT NULL, plan_hash TEXT NOT NULL, step INTEGER NOT NULL,
                state TEXT NOT NULL, PRIMARY KEY(errand, plan_hash, step));
            CREATE TABLE IF NOT EXISTS model_calls (
                day TEXT NOT NULL, model TEXT NOT NULL, at REAL NOT NULL);
        ''')

    def register(self, errand: str, plan: Plan):
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT plan_hash FROM errands WHERE id=?", (errand,)).fetchone()
            if row and row["plan_hash"] != plan.digest:
                self._db.execute("UPDATE asks SET state='stale' WHERE errand=? AND state IN ('pending','yes')",
                                 (errand,))
                self._db.execute("UPDATE errands SET plan_hash=?,plan=? WHERE id=?",
                                 (plan.digest, plan.canonical, errand))
            elif row is None:
                self._db.execute("INSERT INTO errands(id,plan_hash,plan) VALUES(?,?,?)",
                                 (errand, plan.digest, plan.canonical))

    def load(self, errand: str) -> Plan:
        with self._lock:
            row = self._db.execute("SELECT * FROM errands WHERE id=?", (errand,)).fetchone()
        if row is None:
            raise KeyError("unknown errand")
        plan = Plan.parse(row["plan"])
        if plan.digest != row["plan_hash"]:
            raise ValueError("stored plan hash mismatch")
        return plan

    def current(self, errand: str, digest: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT plan_hash FROM errands WHERE id=?", (errand,)).fetchone()
            return row is not None and row["plan_hash"] == digest

    def park(self, errand: str, plan: Plan, step: int, *, kind: str = "execute") -> dict:
        if kind not in {"execute", "replan"}:
            raise ValueError("invalid ask kind")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if not self.current(errand, plan.digest):
                raise ValueError("stale plan")
            row = self._db.execute("SELECT * FROM asks WHERE errand=? AND plan_hash=? "
                                   "AND step=? AND kind=? ORDER BY id DESC LIMIT 1",
                                   (errand, plan.digest, step, kind)).fetchone()
            if row is None or row["state"] == "stale":
                self._db.execute("INSERT INTO asks(errand,plan_hash,step,kind,state,created) "
                                 "VALUES(?,?,?,?,'pending',?)",
                                 (errand, plan.digest, step, kind, time.time()))
                row = self._db.execute("SELECT * FROM asks WHERE id=last_insert_rowid()").fetchone()
            return dict(row)

    def decide(self, ask_id: int, digest: str, decision: str) -> str:
        if decision not in {"yes", "no"}:
            raise ValueError("not a decision")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT * FROM asks WHERE id=?", (ask_id,)).fetchone()
            if (row is None or row["plan_hash"] != digest or row["state"] != "pending"
                    or not self.current(row["errand"], digest)):
                return "stale"
            self._db.execute("UPDATE asks SET state=? WHERE id=?", (decision, ask_id))
            return decision

    def pending(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("SELECT * FROM asks WHERE state='pending' ORDER BY id")]

    def step_state(self, errand: str, plan: Plan, step: int) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT state FROM steps WHERE errand=? AND plan_hash=? AND step=?",
                                   (errand, plan.digest, step)).fetchone()
            return row["state"] if row else None

    def claim(self, errand: str, plan: Plan, step: int, *, needs_yes: bool) -> bool:
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if (not self.current(errand, plan.digest) or self.cancelled(errand)
                    or self.step_state(errand, plan, step) is not None):
                return False
            if needs_yes:
                row = self._db.execute("SELECT state FROM asks WHERE errand=? AND plan_hash=? "
                    "AND step=? AND kind='execute' ORDER BY id DESC LIMIT 1", (errand, plan.digest, step)).fetchone()
                if row is None or row["state"] != "yes":
                    return False
            self._db.execute("INSERT INTO steps VALUES(?,?,?,'running')", (errand, plan.digest, step))
            return True

    def finish(self, errand: str, plan: Plan, step: int, state: str):
        if state not in {"done", "failed", "timeout", "unknown"}:
            raise ValueError("invalid terminal step state")
        with self._lock, self._db:
            self._db.execute("UPDATE steps SET state=? WHERE errand=? AND plan_hash=? AND step=? "
                             "AND state='running'", (state, errand, plan.digest, step))

    def recover_interrupted(self):
        """Explicit service-restart reconciliation: unknown, NEVER re-run."""
        with self._lock, self._db:
            self._db.execute("UPDATE steps SET state='unknown' WHERE state='running'")

    def mismatches(self, errand: str, value: int | None = None) -> int:
        with self._lock, self._db:
            if value is not None:
                self._db.execute("UPDATE errands SET mismatches=? WHERE id=?", (value, errand))
            return self._db.execute("SELECT mismatches FROM errands WHERE id=?", (errand,)).fetchone()[0]

    def cancel(self, errand: str):
        with self._lock, self._db:
            self._db.execute("UPDATE errands SET cancelled=1 WHERE id=?", (errand,))

    def cancelled(self, errand: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT cancelled FROM errands WHERE id=?", (errand,)).fetchone()
            return row is not None and bool(row[0])

    def reserve_mock(self, *, day: str, model: str, now: float, cap: int,
                     external_used: int, reserved: int) -> tuple[bool, str, float | None]:
        """Synthetic clock/day/caps supplied by tests; no provider reset assumptions."""
        import math
        if (not math.isfinite(now) or now < 0
                or any(type(v) is not int or v < 0 for v in (cap, external_used, reserved))):
            raise ValueError("invalid mock budget")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            used = self._db.execute("SELECT count(*) FROM model_calls WHERE day=? AND model=?",
                                    (day, model)).fetchone()[0]
            if max(0, cap - external_used - used - reserved) == 0:
                return False, "daily-budget", None
            last = self._db.execute("SELECT max(at) FROM model_calls").fetchone()[0]
            if last is not None and now < last + 12.01:
                return False, "paced", last + 12.01
            self._db.execute("INSERT INTO model_calls VALUES(?,?,?)", (day, model, now))
            return True, "reserved", None

    def close(self):
        self._db.close()
