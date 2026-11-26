"""SQLite state for the alive host.

Append/update only; nothing here is authority. The database holds:

* ``template_attempts`` — atomic cross-process reservation table for daily
  paid-template budget (ambiguous failures consume budget cleanly);
* ``seen`` — wamid dedup (7-day prune);
* ``fired`` — write-ahead reminder table. A crash between the write-ahead
  row and the send leaves ``status='unknown'``; on restart it is NEVER
  re-sent (honest uncertainty, not a guess);
* ``counters`` / ``month_counters`` — per-tier daily and monthly caps;
* ``never_list_hits`` — stranger never-list attempts for the mute rule;
* ``drafts`` — the S-0 concierge's per-sender collected turns (verbatim);
* ``service_windows`` — 24h customer-service window timestamps per sender hash;
* ``delivery_statuses`` — Meta ``statuses[]`` receipts (sent/delivered/read/failed);
* ``kv`` — seq counter, platform_blocked, clock_suspect, mirror cache.

One writer, single file, WAL, mode 0600. This file is never in Drive.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS template_attempts (
  id INTEGER PRIMARY KEY, day TEXT NOT NULL, template TEXT NOT NULL,
  status TEXT NOT NULL, wamid TEXT
);
CREATE TABLE IF NOT EXISTS seen (
  id TEXT PRIMARY KEY,
  seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fired (
  commitment_id INTEGER NOT NULL,
  remind_at TEXT NOT NULL,
  status TEXT NOT NULL,            -- pending | sent | failed | unknown | missed | capped
  wamid TEXT,
  logged_at TEXT NOT NULL,
  PRIMARY KEY (commitment_id, remind_at)
);
CREATE TABLE IF NOT EXISTS counters (
  day TEXT NOT NULL,
  tier TEXT NOT NULL,
  key TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, tier, key)
);
CREATE TABLE IF NOT EXISTS month_counters (
  month TEXT NOT NULL,
  key TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (month, key)
);
CREATE TABLE IF NOT EXISTS never_list_hits (
  id INTEGER PRIMARY KEY,
  sender_hash TEXT NOT NULL,
  category TEXT NOT NULL,
  hit_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
  sender_hash TEXT PRIMARY KEY,
  turns_json TEXT NOT NULL,
  started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inbox (
  id TEXT PRIMARY KEY,               -- envelope id (wamid / tg:...)
  kind TEXT NOT NULL,
  seq INTEGER NOT NULL,
  written_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS service_windows (
  sender_hash TEXT PRIMARY KEY,
  last_inbound_at TEXT NOT NULL      -- UTC ISO-8601 of last user-initiated message
);
CREATE TABLE IF NOT EXISTS delivery_statuses (
  wamid TEXT NOT NULL,
  status TEXT NOT NULL,              -- sent | delivered | read | failed
  ts TEXT NOT NULL,
  billable INTEGER,
  category TEXT,
  error_code INTEGER,
  PRIMARY KEY (wamid, status)
);
"""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class AliveStore:
    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "alive.sqlite3"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass  # filesystems without chmod: still owner-only by umask in production

    def close(self):
        with self._lock:
            self._conn.close()

    def reserve_template(self, template: str, cap: int, now: datetime) -> int | None:
        """Reserve atomically across processes; ambiguous failures consume budget."""
        with self._lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                count = self._conn.execute(
                    "SELECT COUNT(*) FROM template_attempts WHERE day=?", (self._day(now),)
                ).fetchone()[0]
                if count >= cap:
                    self._conn.rollback()
                    return None
                cur = self._conn.execute(
                    "INSERT INTO template_attempts(day, template, status) VALUES (?, ?, 'pending')",
                    (self._day(now), template))
                self._conn.commit()
                return cur.lastrowid
            except Exception:
                self._conn.rollback()
                raise

    def finish_template(self, attempt: int, status: str, wamid: str | None = None):
        with self._lock:
            self._conn.execute("UPDATE template_attempts SET status=?, wamid=? WHERE id=?",
                               (status, wamid, attempt))
            self._conn.commit()

    def count_template_attempts_today(self, *, now: datetime | None = None) -> int:
        now = now or _utcnow()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM template_attempts WHERE day=?",
                (self._day(now),)).fetchone()
            return int(row["n"]) if row else 0

    # -- seq -----------------------------------------------------------------
    def next_seq(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key='seq'").fetchone()
            seq = int(row["value"]) + 1 if row else 1
            self._conn.execute(
                "INSERT INTO kv(key, value) VALUES('seq', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(seq),))
            self._conn.commit()
            return seq

    # -- dedup -----------------------------------------------------------------
    def first_time_seen(self, message_id: str, *, now: datetime | None = None) -> bool:
        now = now or _utcnow()
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO seen(id, seen_at) VALUES (?, ?)", (message_id, iso(now)))
            self._conn.commit()
            inserted = cur.rowcount == 1
        cutoff = iso(now - timedelta(days=7))
        with self._lock:
            self._conn.execute("DELETE FROM seen WHERE seen_at < ?", (cutoff,))
            self._conn.commit()
        return inserted

    # -- daily / monthly counters ----------------------------------------------
    def _day(self, now: datetime) -> str:
        return now.astimezone(UTC).strftime("%Y-%m-%d")

    def increment(self, key: str, *, tier: str = "T0", now: datetime | None = None,
                  amount: int = 1) -> int:
        now = now or _utcnow()
        day = self._day(now)
        with self._lock:
            self._conn.execute(
                "INSERT INTO counters(day, tier, key, n) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(day, tier, key) DO UPDATE SET n = n + excluded.n",
                (day, tier, key, amount))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT n FROM counters WHERE day=? AND tier=? AND key=?",
                (day, tier, key)).fetchone()
            return int(row["n"])

    def count_today(self, key: str, *, tier: str = "T0", now: datetime | None = None) -> int:
        now = now or _utcnow()
        with self._lock:
            row = self._conn.execute(
                "SELECT n FROM counters WHERE day=? AND tier=? AND key=?",
                (self._day(now), tier, key)).fetchone()
            return int(row["n"]) if row else 0

    def increment_month(self, key: str, *, now: datetime | None = None, amount: int = 1) -> int:
        now = now or _utcnow()
        month = now.astimezone(UTC).strftime("%Y-%m")
        with self._lock:
            self._conn.execute(
                "INSERT INTO month_counters(month, key, n) VALUES (?, ?, ?) "
                "ON CONFLICT(month, key) DO UPDATE SET n = n + excluded.n",
                (month, key, amount))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT n FROM month_counters WHERE month=? AND key=?",
                (month, key)).fetchone()
            return int(row["n"])

    def count_month(self, key: str, *, now: datetime | None = None) -> int:
        now = now or _utcnow()
        month = now.astimezone(UTC).strftime("%Y-%m")
        with self._lock:
            row = self._conn.execute(
                "SELECT n FROM month_counters WHERE month=? AND key=?",
                (month, key)).fetchone()
            return int(row["n"]) if row else 0

    # -- never-list hits / mute -------------------------------------------------
    def add_never_list_hit(self, sender_hash: str, category: str,
                           *, now: datetime | None = None) -> int:
        now = now or _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO never_list_hits(sender_hash, category, hit_at) VALUES (?, ?, ?)",
                (sender_hash, category, iso(now)))
            cutoff = iso(now - timedelta(hours=24 * 30))
            self._conn.execute("DELETE FROM never_list_hits WHERE hit_at < ?", (cutoff,))
            self._conn.commit()
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM never_list_hits WHERE sender_hash=? AND hit_at >= ?",
                (sender_hash, iso(now - timedelta(hours=24)))).fetchone()
            return int(row["n"])

    def muted(self, sender_hash: str, *, window_hours: int = 24, threshold: int = 3,
              now: datetime | None = None) -> bool:
        now = now or _utcnow()
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM never_list_hits WHERE sender_hash=? AND hit_at >= ?",
                (sender_hash, iso(now - timedelta(hours=window_hours)))).fetchone()
            return int(row["n"]) >= threshold

    # -- concierge drafts ---------------------------------------------------------
    def draft_turns(self, sender_hash: str) -> list[str]:
        with self._lock:
            row = self._conn.execute(
                "SELECT turns_json FROM drafts WHERE sender_hash=?", (sender_hash,)).fetchone()
            if not row:
                return []
            try:
                return list(json.loads(row["turns_json"]))
            except ValueError:
                return []

    def append_draft_turn(self, sender_hash: str, turn: str,
                          *, now: datetime | None = None) -> list[str]:
        now = now or _utcnow()
        turns = self.draft_turns(sender_hash) + [turn]
        with self._lock:
            self._conn.execute(
                "INSERT INTO drafts(sender_hash, turns_json, started_at) VALUES (?, ?, ?) "
                "ON CONFLICT(sender_hash) DO UPDATE SET turns_json=excluded.turns_json",
                (sender_hash, json.dumps(turns, ensure_ascii=False), iso(now)))
            self._conn.commit()
        return turns

    def clear_draft(self, sender_hash: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM drafts WHERE sender_hash=?", (sender_hash,))
            self._conn.commit()

    # -- write-ahead reminder table ----------------------------------------------
    def fired_row(self, commitment_id: int, remind_at: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fired WHERE commitment_id=? AND remind_at=?",
                (int(commitment_id), remind_at)).fetchone()
            return dict(row) if row else None

    def record_fired(self, commitment_id: int, remind_at: str, status: str,
                     *, wamid: str | None = None, now: datetime | None = None) -> None:
        now = now or _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT INTO fired(commitment_id, remind_at, status, wamid, logged_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(commitment_id, remind_at) DO UPDATE SET "
                "status=excluded.status, wamid=COALESCE(excluded.wamid, fired.wamid), "
                "logged_at=excluded.logged_at",
                (int(commitment_id), remind_at, status, wamid, iso(now)))
            self._conn.commit()

    def unsee(self, message_id: str) -> None:
        """Roll back a dedup insert after a durable-write failure, so the
        Meta retry is re-processed instead of dropped as a 'duplicate'."""
        with self._lock:
            self._conn.execute("DELETE FROM seen WHERE id=?", (str(message_id),))
            self._conn.commit()

    # -- inbox durability (write-ahead of every inbound envelope) ---------------
    def record_inbox(self, envelope_id: str, kind: str, seq: int,
                     *, now: datetime | None = None) -> None:
        now = now or _utcnow()
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO inbox(id, kind, seq, written_at) VALUES (?, ?, ?, ?)",
                (str(envelope_id), kind, int(seq), iso(now)))
            self._conn.commit()

    # -- 24h customer service window tracking ----------------------------------
    def record_inbound_window(
        self,
        sender_hash: str,
        inbound_at: datetime | str | int,
        now: datetime | None = None,
    ) -> None:
        """Record the timestamp of a transport-authenticated user message.

        Refuses negative or future-skewed timestamps (when ``now`` is supplied)
        so a crafted/skewed timestamp cannot stretch the 24h window into the future,
        and only moves forward monotonically.
        """
        dt: datetime | None = None
        epoch_sec: int | None = None
        if isinstance(inbound_at, datetime):
            dt = inbound_at.astimezone(UTC) if inbound_at.tzinfo else inbound_at.replace(tzinfo=UTC)
            epoch_sec = int(dt.timestamp())
        elif isinstance(inbound_at, int):
            if inbound_at < 0:
                return
            epoch_sec = inbound_at
            dt = datetime.fromtimestamp(inbound_at, tz=UTC)
        else:
            raw = str(inbound_at).strip()
            if raw.isdigit():
                epoch_sec = int(raw)
                dt = datetime.fromtimestamp(epoch_sec, tz=UTC)
            else:
                try:
                    parsed = datetime.fromisoformat(raw)
                except ValueError:
                    return
                dt = parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                epoch_sec = int(dt.timestamp())

        if now is not None:
            now_utc = now.astimezone(UTC) if now.tzinfo else now.replace(tzinfo=UTC)
            if dt > now_utc:
                return

        stamp = iso(dt)
        key = "window:" + sender_hash
        with self._lock:
            row = self._conn.execute(
                "SELECT last_inbound_at FROM service_windows WHERE sender_hash=?",
                (sender_hash,)).fetchone()
            if not (row and str(row["last_inbound_at"]) >= stamp):
                self._conn.execute(
                    "INSERT INTO service_windows(sender_hash, last_inbound_at) VALUES (?, ?) "
                    "ON CONFLICT(sender_hash) DO UPDATE SET last_inbound_at=excluded.last_inbound_at",
                    (sender_hash, stamp))
            self._conn.execute(
                "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET "
                "value=CASE WHEN CAST(excluded.value AS INTEGER)>CAST(kv.value AS INTEGER) "
                "THEN excluded.value ELSE kv.value END",
                (key, str(epoch_sec)),
            )
            self._conn.commit()

    def last_inbound_at(self, sender_hash: str) -> datetime | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_inbound_at FROM service_windows WHERE sender_hash=?",
                (sender_hash,)).fetchone()
            if row:
                try:
                    dt = datetime.fromisoformat(str(row["last_inbound_at"]))
                    return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
                except ValueError:
                    pass
            kv_row = self._conn.execute(
                "SELECT value FROM kv WHERE key=?", ("window:" + sender_hash,)).fetchone()
        if not kv_row:
            return None
        try:
            return datetime.fromtimestamp(int(kv_row["value"]), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None

    def in_service_window(self, sender_hash: str, *, now: datetime | None = None,
                          window_seconds: int = 24 * 3600) -> bool:
        """True iff the sender messaged us within ``[0, window_seconds)`` (strictly < 24h)."""
        now = (now or _utcnow()).astimezone(UTC)
        last = self.last_inbound_at(sender_hash)
        if last is None:
            return False
        elapsed = (now - last.astimezone(UTC)).total_seconds()
        return 0 <= elapsed < window_seconds

    # -- webhook delivery status receipts (statuses[]) -------------------------
    def record_delivery_status(self, wamid: str, status: str, *, ts: str,
                               billable: bool | None = None,
                               category: str | None = None,
                               error_code: int | None = None) -> None:
        billable_int = None if billable is None else (1 if billable else 0)
        with self._lock:
            self._conn.execute(
                "INSERT INTO delivery_statuses(wamid, status, ts, billable, category, error_code) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(wamid, status) DO UPDATE SET "
                "ts=excluded.ts, billable=COALESCE(excluded.billable, delivery_statuses.billable), "
                "category=COALESCE(excluded.category, delivery_statuses.category), "
                "error_code=COALESCE(excluded.error_code, delivery_statuses.error_code)",
                (str(wamid), str(status), str(ts), billable_int, category, error_code))
            self._conn.commit()

    def delivery_statuses_for(self, wamid: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM delivery_statuses WHERE wamid=? ORDER BY ts ASC",
                (str(wamid),)).fetchall()
            return [dict(r) for r in rows]

    def first_fired_for_commitment(self, commitment_id: int) -> dict | None:
        """Return the earliest ``sent`` reminder row for ``commitment_id``, if any."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM fired WHERE commitment_id=? AND status='sent' "
                "ORDER BY remind_at ASC LIMIT 1",
                (int(commitment_id),)).fetchone()
            return dict(row) if row else None

    # -- kv -------------------------------------------------------------------
    def kv_get(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            return row["value"] if row else default

    def kv_set(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
            self._conn.commit()

    def platform_blocked(self) -> bool:
        return (self.kv_get("platform_blocked", "0") or "0") == "1"

    def clock_suspect(self) -> bool:
        return (self.kv_get("clock_suspect", "0") or "0") == "1"
