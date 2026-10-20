"""Her console (§19.1) — one conversation, one state machine, two channels.

The console is not a second assistant. It is another window onto the daemon's
single conversation store:

    voice turn  -> messages(channel='voice')   ┐
    console turn -> messages(channel='console') ┴─ same conversation_id

There is deliberately no per-channel history. `SessionService.active_id()`
always returns the latest conversation row and creates one only when none
exists, so starting by voice and continuing in the console (or the reverse)
cannot fork context. The Stage B tests assert exactly that by reading ids.

`ConsoleService.snapshot()` is what the Quickshell panel and `assist console`
render: conversation, pending plans, parked review items, offline queue, job
progress, the holding shelf and the current class/show-off posture. State
decisions stay here (tested headless); QML only binds.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime

from .cost import iso_now
from .ipc import DaemonUnavailable, call

ACTIVE_JOB_STATUSES = ("pending", "running", "approved", "awaiting_approval")
ACTIVE_PLAN_STATUSES = ("building", "ready")


class SessionService:
    """The shared conversation store — no forked histories, by construction."""

    def __init__(self, store, *, history_limit: int = 200):
        self.store = store
        self.history_limit = history_limit

    def active_id(self, ts: str | None = None) -> int:
        return self.store.get_or_create_conversation(ts or iso_now())

    def append(self, role: str, text: str, *, channel: str = "voice",
               via: str | None = None, ts: str | None = None) -> dict:
        conversation_id = self.active_id(ts)
        message_id = self.store.add_message(
            conversation_id, ts or iso_now(), role, text, via=via, channel=channel)
        return {"conversation_id": conversation_id, "message_id": message_id,
                "channel": channel}

    def history(self, *, limit: int | None = None) -> dict:
        conversation = self.store.latest_conversation()
        if conversation is None:
            return {"id": None, "started": None, "messages": []}
        messages = self.store.conversation_messages(
            int(conversation["id"]), limit or self.history_limit)
        return {"id": int(conversation["id"]), "started": conversation["ts"],
                "messages": [
                    {"id": m["id"], "ts": m["ts"], "role": m["role"],
                     "text": m["text"], "via": m.get("via"),
                     "channel": m.get("channel") or "voice"}
                    for m in messages
                ]}


@dataclass
class ConsoleService:
    config: object
    store: object
    presence: object = None
    initiative: object = None
    showoff: object = None
    disclosure: object = None
    sessions: SessionService | None = None

    def __post_init__(self):
        if self.sessions is None:
            self.sessions = SessionService(
                self.store, history_limit=int(self._settings().get("history_limit", 200)))

    def _settings(self) -> dict:
        return self.config.section("console") if self.config else {}

    # -- the snapshot both surfaces render ---------------------------------
    def snapshot(self, *, now: datetime | None = None) -> dict:
        limit = int(self._settings().get("snapshot_limit", 20))
        plans = self.store.list_plans(limit)
        pending_plans = [
            {"id": plan["id"], "root": plan["root"], "status": plan["status"],
             "mode": plan["mode"], "total": plan["total"],
             "placed": plan["placed_tier0"], "abstained": plan["abstained"],
             "ts": plan["ts"]}
            for plan in plans if plan["status"] in ACTIVE_PLAN_STATUSES
        ]
        parked: list[dict] = []
        for plan in plans[:5]:
            for item in self.store.plan_items(plan["id"]):
                if item.get("decision") in ("review", "unsorted"):
                    parked.append({
                        "id": item["id"], "plan_id": item["plan_id"],
                        "src": item["src"], "dest": item.get("dest"),
                        "confidence": item.get("confidence"),
                        "decision": item["decision"], "reason": item.get("reason"),
                    })
        jobs = self.store.list_cloud_jobs(status=None, limit=50)
        queue_counts = self.store.cloud_job_counts()
        active_jobs = [job for job in jobs if job["status"] in ACTIVE_JOB_STATUSES]
        job_progress = [
            {"kind": "plan", "plan_id": plan["id"], "status": plan["status"],
             "done": plan["placed_tier0"], "total": plan["total"],
             "label": f"plan #{plan['id']} · {plan['root']}"}
            for plan in pending_plans if plan["status"] == "building"
        ] + [
            {"kind": job["kind"], "job_id": job["id"], "status": job["status"],
             "attempts": job["attempts"], "label": f"job #{job['id']} · {job['kind']}"}
            for job in active_jobs
        ]
        holding = self.store.list_holdings("active", limit=limit)
        knocks = []
        if self.initiative is not None:
            knocks = self.initiative.pending()
        class_mode = (self.presence.status(now).as_dict()
                      if self.presence is not None else {"enabled": False})
        showoff = (self.showoff.status(now) if self.showoff is not None
                   else {"active": False})
        company = (self.disclosure.status() if self.disclosure is not None
                   else {"company": False})
        return {
            "ts": iso_now(),
            "conversation": self.sessions.history(),
            "pending_plans": pending_plans,
            "parked_items": parked[:limit],
            "offline_queue": {"counts": queue_counts, "jobs": active_jobs[:limit]},
            "job_progress": job_progress,
            "holding": holding,
            "knocks": knocks,
            "class_mode": class_mode,
            "showoff": showoff,
            "company": company,
            "counts": {
                "pending_plans": len(pending_plans),
                "parked": len(parked),
                "queue": len(active_jobs),
                "holding": len(holding),
                "knocks": len(knocks),
            },
        }


def _safe_snapshot(socket_path) -> dict:
    try:
        return call(socket_path, "console.state", timeout=3.0)
    except Exception as exc:  # daemon down: the console stays honest, not blank
        return {"ts": iso_now(), "daemon": {"running": False, "reason": str(exc)},
                "conversation": {"id": None, "messages": []},
                "pending_plans": [], "parked_items": [], "job_progress": [],
                "offline_queue": {"counts": {}, "jobs": []}, "holding": [],
                "knocks": [], "class_mode": {"enabled": False},
                "showoff": {"active": False},
                "company": {"company": False, "note": "daemon down"},
                "counts": {"pending_plans": 0, "parked": 0, "queue": 0,
                           "holding": 0, "knocks": 0}}


def stream_console(socket_path, *, interval_s: float = 5.0):
    """Yield a snapshot immediately and on every daemon event (Waybar pattern).

    A console that only polls feels dead while a job runs; a console that only
    listens freezes when the daemon restarts. This does both with one socket:
    events trigger an immediate snapshot, a timeout re-snapshots so uptime and
    progress stay truthful, and a daemon-down state is yielded rather than
    crashing the panel.
    """
    yield _safe_snapshot(socket_path)
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(interval_s)
                sock.connect(str(socket_path))
                sock.sendall(b'{"id": 1, "method": "events.subscribe", "params": {}}\n')
                buffer = b""
                while True:
                    try:
                        chunk = sock.recv(65536)
                    except TimeoutError:
                        yield _safe_snapshot(socket_path)
                        continue
                    if not chunk:
                        yield _safe_snapshot(socket_path)
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        try:
                            message = json.loads(line)
                        except ValueError:
                            continue
                        if isinstance(message, dict) and "event" in message:
                            yield _safe_snapshot(socket_path)
        except (OSError, DaemonUnavailable):
            yield _safe_snapshot(socket_path)
            import time

            time.sleep(min(interval_s, 2.0))
