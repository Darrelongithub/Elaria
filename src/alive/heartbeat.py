"""Heartbeat — the only mutable object in the sync folder, and it carries a mac.

A compromised Drive that fakes liveness is defeated by the laptop requiring
a valid ``mac`` on ``heartbeat/alive.json``; the laptop's own honesty check
("my phone line has been asleep since …") is driven off this file plus its
staleness, never off vibes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import envelope as envelope_mod
from .config import AliveConfig
from .journal import log_event
from .store import AliveStore

VERSION = "0.1.0"


def write_heartbeat(*, backend, config: AliveConfig, store: AliveStore,
                    now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    body = {
        "v": 1,
        "kind": "heartbeat",
        "ts": now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "version": VERSION,
        "platform_blocked": store.platform_blocked(),
        "clock_suspect": store.clock_suspect(),
        "templates_today": store.count_today("templates", tier="T0", now=now),
        "service_messages_month": store.count_month("service_messages", now=now),
        "not_stored": (store.count_today("not_stored", tier="T0", now=now)
                       + store.count_today("not_stored", tier="T2", now=now)),
    }
    signed = envelope_mod.sign(body, config.mac_key)
    data = envelope_mod.envelope_bytes(signed)
    backend.put(config.heartbeat_prefix, "alive.json", data)
    log_event(config.state_dir, "heartbeat_written")
    return signed
