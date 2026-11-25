"""Alive-sync — the laptop's half of the always-alive layer.

The alive host (see ``src/alive/``) holds a filtered mirror of stated
commitments and an append-only instruction inbox, and nothing else. This
module is the laptop side of that contract:

* **export** — a full, filtered commitments snapshot into
  ``commitments/`` (hash-named, immutable, mac'd), plus the optional
  public card and the T1 allowlist (hashed, never raw numbers);
* **ingest** — verify (name hash + mac + version + owner from_hash for
  instructions), quarantine what fails, surfacing for explicit yes what
  expired, and replaying live instructions through the EXISTING
  ``cloud_queue.enqueue_external`` → ``awaiting_approval`` → spoken-yes
  path. The body is untrusted data, exactly like a phone-link text;
* **receipts** — after every drain, a receipt envelope lists ingested and
  quarantined ids; the alive host prunes against it;
* **reminder_log** — read-only for the laptop ("already sent to your phone
  at 06:55" knock variant);
* **line status** — heartbeat age for the "my phone line has been asleep
  since …" honesty line.

Security posture (binding, from the design):

* laptop-written prefixes: ``commitments/``, ``receipts/`` — the laptop
  refuses to write anywhere else;
* alive-written prefixes: ``inbox/``, ``reminder_log/``, ``heartbeat/`` —
  the laptop only reads (and prunes inbox after receipts confirm ingest);
* a file that fails verification is quarantine + journal, NEVER ingest,
  NEVER silent;
* ``proposal`` envelopes' ``principal`` field is IGNORED on ingest —
  proposals are labelled by ``kind``, defence in depth behind the mac;
* expired envelopes are surfaced, never executed without a fresh yes;
* stranger turns have NO code path to ``enqueue_external`` — the only
  sink is the caller-read ``proposals``/``stranger_turns`` lists.

No network here: the backend is either the fixture (local directory,
labelled) or ``alive.sync.RcloneSyncBackend(role="laptop")`` against the
owner's Drive folder. The daemon wiring (startup hook, knock line, the
"asleep since" line) is cluster U's one-create_task request, by design.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

try:  # the alive package deploys with the laptop source tree, not the wheel
    from alive import envelope as envelope_mod
    from alive.sync import FixtureSyncBackend, RcloneSyncBackend  # noqa: F401  (re-export)
except ImportError as exc:  # pragma: no cover - deployment guard
    raise ImportError(
        "assistant.alive_sync needs the sibling 'alive' package on the path "
        "(src/alive in this repo). Copy both src/assistant and src/alive to the "
        "laptop deployment, or run from a source checkout."
    ) from exc

from . import journal_log
from .cost import iso_now
from .disclosure import is_sensitive
from .initiative import COMMITMENT_ORIGINS

ALIVE_ACTION = "alive_inbox"
LAPTOP_WRITE_PREFIXES = ("commitments", "receipts")
ALIVE_WRITE_PREFIXES = ("inbox", "reminder_log", "heartbeat")
INBOX_ENVELOPE_KINDS = ("instruction", "stranger_turn", "proposal", "unsupported")


class AliveSyncError(RuntimeError):
    pass


class AliveSyncState:
    """Tiny local ledger: which envelopes we ingested, which we quarantined,
    and the laptop's own export seq. One file, mode 0600, never in Drive."""

    def __init__(self, state_dir: Path | str):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.state_dir / "alive_sync_state.sqlite3"
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ingested (
              name TEXT PRIMARY KEY, ingested_at TEXT NOT NULL, seq INTEGER
            );
            CREATE TABLE IF NOT EXISTS quarantined (
              name TEXT PRIMARY KEY, reason TEXT NOT NULL, quarantined_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def close(self):
        with self._lock:
            self._conn.close()

    def already_seen(self, name: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM ingested WHERE name=? UNION SELECT 1 FROM quarantined WHERE name=?",
                (name, name)).fetchone()
            return row is not None

    def note_ingested(self, name: str, seq: int | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO ingested(name, ingested_at, seq) VALUES (?, ?, ?)",
                (name, iso_now(), seq))
            self._conn.commit()

    def note_quarantined(self, name: str, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO quarantined(name, reason, quarantined_at) VALUES (?, ?, ?)",
                (name, reason[:300], iso_now()))
            self._conn.commit()

    def next_seq(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key='seq'").fetchone()
            seq = int(row["value"]) + 1 if row else 1
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES('seq', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(seq),))
            self._conn.commit()
            return seq


@dataclass
class AliveSyncConfig:
    state_dir: Path
    mac_key: str
    from_hash_salt: str
    owner_e164: str
    tz: str = "Africa/Nairobi"
    expiry_hours: int = 72
    content_free_secret_reminders: bool = False
    quarantine_dir: Path | None = None
    # {fact_id: {"due": iso|None, "remind_at": [iso, ...]}} — the daemon does
    # not yet store reminder times for commitments in a structured field;
    # until it does, items export with no times and fire nothing on the host.
    remind_hints: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.mac_key or len(self.mac_key) < 16:
            raise AliveSyncError("mac_key missing or too short")
        if not self.from_hash_salt or len(self.from_hash_salt) < 8:
            raise AliveSyncError("from_hash_salt missing")
        if not str(self.owner_e164).startswith("+"):
            raise AliveSyncError("owner_e164 must be E.164")


# --------------------------------------------------------------------------------------
# export (laptop → alive host)
# --------------------------------------------------------------------------------------

def _commitment_items(store, config: AliveSyncConfig) -> list[dict]:
    items: list[dict] = []
    knocks = store.list_knocks(status="pending", limit=100) + \
             store.list_knocks(status="snoozed", limit=100)
    knock_by_commitment: dict[int, int] = {}
    for knock in knocks:
        commitment_id = knock.get("commitment_id")
        if commitment_id is not None:
            knock_by_commitment.setdefault(int(commitment_id), int(knock["id"]))

    for fact in store.list_facts(kind="commitment"):
        evidence_raw = fact.get("evidence") or "{}"
        try:
            evidence = json.loads(evidence_raw)
        except ValueError:
            evidence = {}
        origin = str(evidence.get("origin", ""))
        if origin not in COMMITMENT_ORIGINS:
            continue  # she never reminds about something she invented
        topic = str(fact.get("text", "")).strip()
        if not topic:
            continue
        if is_sensitive(topic):
            # never mirrored; the owner may opt into a content-free reminder
            if config.content_free_secret_reminders:
                items.append({
                    "id": int(fact["id"]),
                    "topic": f"(private item #{int(fact['id'])})",
                    "due": None, "remind_at": [],
                    "origin": origin,
                    "knock_id": knock_by_commitment.get(int(fact["id"])),
                    "content_free": True,
                })
            continue
        hint = config.remind_hints.get(int(fact["id"])) or \
               config.remind_hints.get(str(fact["id"])) or {}
        remind_at = hint.get("remind_at") or []
        if isinstance(remind_at, str):
            remind_at = [remind_at]
        items.append({
            "id": int(fact["id"]),
            "topic": topic[:300],
            "due": hint.get("due"),
            "remind_at": [str(x) for x in remind_at][:10],
            "origin": origin,
            "knock_id": knock_by_commitment.get(int(fact["id"])),
            "content_free": False,
        })
    return items


def export_commitments(store, backend, config: AliveSyncConfig, state: AliveSyncState,
                       *, now: datetime | None = None) -> dict:
    """Write a full, filtered commitments snapshot. Returns a summary."""
    now = now or datetime.now(UTC)
    items = _commitment_items(store, config)
    laptop_seq = state.next_seq()
    body = {
        "v": 1,
        "kind": "commitments",
        "generated_at": iso_now(),
        "laptop_seq": laptop_seq,
        "items": items,
    }
    data, name = _signed_file(body, config, now, laptop_seq)
    _put_laptop(backend, "commitments", name, data)
    latest = json.dumps({"file": name, "sha256": envelope_mod.name_hash(data),
                         "generated_at": body["generated_at"]},
                        sort_keys=True).encode("utf-8")
    _put_laptop(backend, "commitments", "LATEST", latest)
    journal_log.log_event("alive_mirror_exported", verdict="ok",
                          detail=f"items={len(items)} file={name}")
    return {"file": name, "items": len(items), "laptop_seq": laptop_seq}


def export_public_card(backend, config: AliveSyncConfig, state: AliveSyncState,
                       *, name: str, for_name: str, role_line: str,
                       freebusy_level: int, never_disclose: list[str],
                       now: datetime | None = None) -> dict:
    """Export the pre-approved public card (front door). Absent card = L0."""
    now = now or datetime.now(UTC)
    if freebusy_level not in (0, 1, 2):
        raise AliveSyncError("freebusy_level must be 0, 1 or 2; 3 never exists")
    laptop_seq = state.next_seq()
    body = {
        "v": 1,
        "kind": "public_card",
        "name": str(name)[:80],
        "for": str(for_name)[:80],
        "role_line": str(role_line)[:200],
        "freebusy_level": int(freebusy_level),
        "never_disclose": [str(x)[:60] for x in never_disclose][:20],
        "generated_at": iso_now(),
        "laptop_seq": laptop_seq,
    }
    data, filename = _signed_file(body, config, now, laptop_seq)
    _put_laptop(backend, "commitments", filename, data)
    journal_log.log_event("alive_public_card_exported", verdict="ok",
                          detail=f"level={freebusy_level} file={filename}")
    return {"file": filename, "freebusy_level": freebusy_level}


def export_t1_hashes(backend, config: AliveSyncConfig, state: AliveSyncState,
                     numbers: list[str], *, now: datetime | None = None) -> dict:
    """Export the T1 approved-contact allowlist as salted hashes.

    Raw numbers never enter the sync folder."""
    now = now or datetime.now(UTC)
    hashes = sorted({envelope_mod.from_hash(str(n).strip(), config.from_hash_salt)
                     for n in numbers if str(n).strip().startswith("+")})[:50]
    laptop_seq = state.next_seq()
    body = {
        "v": 1,
        "kind": "t1_allowlist",
        "hashes": hashes,
        "generated_at": iso_now(),
        "laptop_seq": laptop_seq,
    }
    data, filename = _signed_file(body, config, now, laptop_seq)
    _put_laptop(backend, "commitments", filename, data)
    journal_log.log_event("alive_t1_exported", verdict="ok",
                          detail=f"count={len(hashes)} file={filename}")
    return {"file": filename, "count": len(hashes)}


def _put_laptop(backend, prefix: str, name: str, data: bytes) -> None:
    """The laptop may only ever write into its own two prefixes."""
    if prefix not in LAPTOP_WRITE_PREFIXES:
        raise AliveSyncError(
            f"laptop refuses to write into {prefix!r}: allowed {LAPTOP_WRITE_PREFIXES}")
    backend.put(prefix, name, data)


def _signed_file(body: dict, config: AliveSyncConfig, now: datetime,
                 seq: int) -> tuple[bytes, str]:
    signed = envelope_mod.sign(body, config.mac_key)
    data = envelope_mod.envelope_bytes(signed)
    name = envelope_mod.envelope_name(now, seq, data)
    return data, name


# --------------------------------------------------------------------------------------
# ingest (alive host → laptop)
# --------------------------------------------------------------------------------------

@dataclass
class IngestResult:
    queued: list[dict] = field(default_factory=list)     # cloud_queue job ids + envelope
    proposals: list[dict] = field(default_factory=list)  # verified, principal ignored
    stranger_turns: int = 0
    unsupported: int = 0
    expired: list[dict] = field(default_factory=list)    # need explicit yes
    quarantined: list[dict] = field(default_factory=list)
    skipped_known: int = 0
    receipt: str | None = None

    def as_dict(self) -> dict:
        return {
            "queued": self.queued,
            "proposals": self.proposals,
            "stranger_turns": self.stranger_turns,
            "unsupported": self.unsupported,
            "expired": self.expired,
            "quarantined": self.quarantined,
            "skipped_known": self.skipped_known,
            "receipt": self.receipt,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        parts = []
        if self.queued:
            parts.append(f"{len(self.queued)} queued for approval")
        if self.proposals:
            parts.append(f"{len(self.proposals)} proposal(s) to hear")
        if self.expired:
            parts.append(f"{len(self.expired)} expired, need your yes")
        if self.quarantined:
            parts.append(f"{len(self.quarantined)} unverifiable, quarantined")
        if not parts:
            return "Alive line: nothing new."
        return "Alive line: " + "; ".join(parts) + "."


def _quarantine(config: AliveSyncConfig, state: AliveSyncState, name: str,
                reason: str, data: bytes | None) -> None:
    state.note_quarantined(name, reason)
    quarantine_dir = Path(config.quarantine_dir or (Path(config.state_dir) / "alive_quarantine"))
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    if data is not None:
        try:
            (quarantine_dir / name).write_bytes(data)
        except OSError:
            pass
    journal_log.log_event("alive_envelope_quarantined", level="warn",
                          verdict="quarantined", detail=f"{name}: {reason}")


def ingest(backend, cloud_queue, config: AliveSyncConfig, state: AliveSyncState,
           *, now: datetime | None = None) -> IngestResult:
    """Drain the inbox into the EXISTING approval path. Idempotent."""
    now = now or datetime.now(UTC)
    result = IngestResult()

    names = backend.list("inbox")
    owner_hash = envelope_mod.from_hash(config.owner_e164, config.from_hash_salt)

    for name in sorted(names):  # name sort == chronological (prefix is the stamp)
        if state.already_seen(name):
            result.skipped_known += 1
            continue
        try:
            data = backend.get("inbox", name)
        except Exception as exc:
            # remote read failed — do NOT mark seen; next drain retries
            result.quarantined.append({"name": name, "reason": f"remote read failed: {exc}"})
            continue

        envelope, error = envelope_mod.load_verified(name, data, config.mac_key)
        if envelope is None:
            _quarantine(config, state, name, error or "verification failed", data)
            result.quarantined.append({"name": name, "reason": error})
            continue

        kind = envelope.get("kind")
        if kind not in INBOX_ENVELOPE_KINDS:
            _quarantine(config, state, name, f"unexpected kind {kind!r}", data)
            result.quarantined.append({"name": name, "reason": f"unexpected kind {kind!r}"})
            continue

        if kind == "instruction" and envelope.get("from_hash") != owner_hash:
            # valid mac, wrong principal: defence in depth behind the mac
            _quarantine(config, state, name, "instruction from_hash is not the owner", data)
            result.quarantined.append({"name": name, "reason": "from_hash mismatch"})
            continue

        expired = envelope_mod.is_expired(envelope, now)
        if expired:
            state.note_ingested(name, envelope.get("seq"))
            result.expired.append({
                "name": name, "id": envelope.get("id"), "kind": kind,
                "sent_at": envelope.get("sent_at"), "body": envelope.get("body"),
                "note": "expired before the laptop was on — needs an explicit yes",
            })
            continue

        if kind == "instruction":
            body = str(envelope.get("body", ""))
            job_id = cloud_queue.enqueue_external(
                action=ALIVE_ACTION,
                description=f"alive inbox (from your phone, queued): {body[:100]}",
                payload={
                    "alive_envelope": envelope,
                    "kind": "alive_inbox",
                    "trusted": False,  # same discipline as phone_link inbound
                    "suspected_injection": bool(envelope.get("suspected_injection")),
                })
            state.note_ingested(name, envelope.get("seq"))
            result.queued.append({"job_id": job_id, "name": name,
                                  "id": envelope.get("id"),
                                  "body": body,
                                  "suspected_injection": bool(
                                      envelope.get("suspected_injection"))})
            journal_log.log_event("alive_instruction_replayed", verdict="awaiting_approval",
                                  detail=f"job={job_id} seq={envelope.get('seq')}")
        elif kind == "proposal":
            proposal = envelope.get("proposal") or {}
            # defence in depth: principal from the envelope is IGNORED; the
            # proposal is labelled by kind. It is NEVER enqueued.
            result.proposals.append({
                "name": name, "id": envelope.get("id"),
                "principal": "stranger",
                "display_name_claimed": str(proposal.get("display_name_claimed", ""))[:120],
                "plan": proposal.get("plan") or {},
                "turns": proposal.get("turns") or [],
                "never_list_hits": envelope.get("never_list_category"),
                "sent_at": envelope.get("sent_at"),
            })
            state.note_ingested(name, envelope.get("seq"))
            journal_log.log_event("alive_proposal_received", verdict="needs_owner",
                                  detail=f"id={envelope.get('id')}")
        elif kind == "stranger_turn":
            result.stranger_turns += 1
            state.note_ingested(name, envelope.get("seq"))
        else:  # unsupported
            result.unsupported += 1
            state.note_ingested(name, envelope.get("seq"))

    result.receipt = _write_receipt(backend, config, state, now, result)
    return result


def _write_receipt(backend, config: AliveSyncConfig, state: AliveSyncState,
                   now: datetime, result: IngestResult) -> str | None:
    laptop_seq = state.next_seq()
    body = {
        "v": 1,
        "kind": "receipt",
        "ingested": [q.get("id") for q in result.queued]
                    + [p.get("id") for p in result.proposals],
        "quarantined": [q.get("name") for q in result.quarantined],
        "expired": [e.get("id") for e in result.expired],
        "at": iso_now(),
        "laptop_seq": laptop_seq,
    }
    try:
        data, name = _signed_file(body, config, now, laptop_seq)
        _put_laptop(backend, "receipts", name, data)
        return name
    except Exception as exc:
        journal_log.log_event("alive_receipt_failed", level="warn",
                              verdict="degraded", detail=str(exc))
        return None


# --------------------------------------------------------------------------------------
# read-only views (reminder log, line status)
# --------------------------------------------------------------------------------------

def read_reminder_log(backend, config: AliveSyncConfig) -> list[dict]:
    """Verified reminder_log entries, oldest first. For the 'already sent to
    your phone at 06:55' knock. Unverifiable entries are omitted (and noted)."""
    entries: list[dict] = []
    try:
        names = backend.list("reminder_log")
    except Exception:
        return entries
    for name in sorted(names):
        try:
            data = backend.get("reminder_log", name)
        except Exception:
            journal_log.log_event("alive_reminder_log_unreadable", level="warn",
                                  verdict="skipped", detail=name)
            continue
        envelope, error = envelope_mod.load_verified(name, data, config.mac_key)
        if envelope is None or envelope.get("kind") != "reminder_log":
            journal_log.log_event("alive_reminder_log_quarantined", level="warn",
                                  verdict="quarantined", detail=f"{name}: {error}")
            continue
        entries.append({
            "commitment_id": envelope.get("commitment_id"),
            "remind_at": envelope.get("remind_at"),
            "sent_at": envelope.get("sent_at"),
            "template": envelope.get("template"),
            "wamid": envelope.get("wamid"),
            "status": envelope.get("status"),
        })
    return entries


def line_status(backend, config: AliveSyncConfig, *, now: datetime | None = None,
                max_age_seconds: int = 2700) -> dict:
    """Is the alive line awake? Heartbeat age is the single liveness truth."""
    now = now or datetime.now(UTC)
    try:
        data = backend.get("heartbeat", "alive.json")
    except Exception as exc:
        return {"awake": False, "reason": f"heartbeat unreadable: {exc}",
                "asleep_since": None}
    try:
        envelope = json.loads(data.decode("utf-8"))
    except ValueError:
        return {"awake": False, "reason": "heartbeat is not JSON", "asleep_since": None}
    if not envelope_mod.verify_mac(envelope, config.mac_key):
        return {"awake": False, "reason": "heartbeat mac does not verify",
                "asleep_since": None}
    try:
        ts = datetime.fromisoformat(str(envelope.get("ts")))
    except ValueError:
        return {"awake": False, "reason": "heartbeat timestamp unparseable",
                "asleep_since": None}
    age = (now - ts).total_seconds()
    if age > max_age_seconds:
        return {"awake": False,
                "reason": f"heartbeat is {int(age // 60)} minutes old",
                "asleep_since": envelope.get("ts")}
    return {"awake": True, "reason": None, "asleep_since": None,
            "platform_blocked": bool(envelope.get("platform_blocked")),
            "clock_suspect": bool(envelope.get("clock_suspect"))}
