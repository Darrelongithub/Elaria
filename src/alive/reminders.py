"""Reminder firing — write-ahead, capped, honest.

Rules (design §2.4.4, binding):

* the alive layer is the ONLY sender on the messaging channel;
* per ``(commitment_id, remind_at)`` a write-ahead row exists before the
  send. A crash between the row and the send leaves ``status='pending'``,
  which on restart is moved to ``unknown`` — NEVER re-sent;
* nothing fires more than ``late_grace_seconds`` after ``remind_at``;
  a late one is logged ``missed``;
* the utility-template cap is enforced HERE in code; above it the layer
  stops and logs (B14), and the laptop is told via the reminder log;
* a snapshot older than ``stale_mirror_days`` stops firing (B11), and the
  owner is told once — honestly — that the list is stale;
* ``PLATFORM_BLOCKED`` is terminal: stop sending, journal, wait for the
  owner. No other path, no other number, no retry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from . import envelope as envelope_mod
from .config import REMINDER_TEMPLATE, AliveConfig
from .journal import iso_now, log_event
from .mirror import is_stale, load_mirror
from .store import AliveStore
from .transport import PlatformBlocked, TransportError, TemplateCapReached




def _parse_ts(value):
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def send_reminder(*, backend, config: AliveConfig, store: AliveStore,
                  transport, item, remind_at: str, now: datetime) -> str:
    """Fire one reminder. Returns the outcome string; journals before send."""
    commitment_id = int(item.id)

    # template cap — enforced in code, every call, no exceptions
    sent_today = store.count_today("templates", tier="T0", now=now)
    if sent_today >= config.max_templates_per_day:
        store.record_fired(commitment_id, remind_at, "capped", now=now)
        log_event(config.state_dir, "template_cap_reached", level="warn",
                  commitment_id=commitment_id, cap=config.max_templates_per_day)
        return "capped"

    if item.content_free and not config.content_free_secret_reminders:
        # belt and braces: content-free secrets never fire unless the owner
        # explicitly opted in — the laptop exporter is the primary filter.
        log_event(config.state_dir, "content_free_suppressed",
                  commitment_id=commitment_id)
        store.record_fired(commitment_id, remind_at, "missed", now=now)
        return "missed"

    topic = item.topic if not item.content_free else f"(private item #{commitment_id})"
    store.record_fired(commitment_id, remind_at, "pending", now=now)  # write-ahead
    log_event(config.state_dir, "reminder_sending", commitment_id=commitment_id,
              remind_at=remind_at, template=REMINDER_TEMPLATE)
    try:
        response = transport.send_utility_template(
            config.owner_e164, REMINDER_TEMPLATE, [topic, remind_at])
    except TemplateCapReached:
        store.record_fired(commitment_id, remind_at, "capped", now=now)
        return "capped"
    except PlatformBlocked as exc:
        store.record_fired(commitment_id, remind_at, "unknown", now=now)
        store.kv_set("platform_blocked", "1")
        log_event(config.state_dir, "platform_blocked", level="error",
                  detail=str(exc))
        return "platform_blocked"
    except TransportError as exc:
        store.record_fired(commitment_id, remind_at, "failed", now=now)
        log_event(config.state_dir, "reminder_failed", level="error",
                  commitment_id=commitment_id, error=str(exc))
        return "failed"

    wamid = None
    try:
        wamid = response["messages"][0]["id"]
    except (KeyError, IndexError, TypeError):
        wamid = None
    store.record_fired(commitment_id, remind_at, "sent", wamid=wamid, now=now)
    store.increment("templates", tier="T0", now=now)
    store.increment_month("service_messages", now=now)

    # reminder_log envelope — the only record the laptop will see
    body = {
        "v": 1, "kind": "reminder_log",
        "commitment_id": commitment_id, "template": REMINDER_TEMPLATE,
        "wamid": wamid, "status": "sent",
        "cost_note": "unknown; check Meta billing",
        "sent_at": iso_now(), "remind_at": remind_at,
    }
    seq = store.next_seq()
    signed = envelope_mod.sign(body, config.mac_key)
    data = envelope_mod.envelope_bytes(signed)
    name = envelope_mod.envelope_name(now, seq, data)
    try:
        backend.put(config.reminder_log_prefix, name, data)
    except Exception as exc:
        # The send happened; the log write failed. LOUD, not silent.
        log_event(config.state_dir, "reminder_log_write_failed", level="error",
                  commitment_id=commitment_id, error=str(exc))
    return "sent"


def tick(*, backend, config: AliveConfig, store: AliveStore,
         transport, now: datetime | None = None) -> dict:
    """One firing pass. Idempotent; safe to call every minute."""
    now = now or datetime.now(UTC)
    result = {"status": "ok", "sent": 0, "missed": 0, "capped": 0,
              "skipped": 0, "stale": False}

    if store.platform_blocked():
        result["status"] = "platform_blocked"
        return result
    if store.clock_suspect():
        result["status"] = "clock_suspect"
        log_event(config.state_dir, "firing_paused_clock_suspect", level="warn")
        return result

    mirror = load_mirror(backend, config.commitments_prefix, config.mac_key, now=now)
    if not mirror.verified:
        result["status"] = "mirror_unavailable"
        result["error"] = mirror.error
        return result

    if is_stale(mirror, config.stale_mirror_days, now=now):
        result["stale"] = True
        if (store.kv_get("stale_notified", "0") or "0") != "1":
            store.kv_set("stale_notified", "1")
            try:
                if store.count_today("templates", tier="T0", now=now) >= config.max_templates_per_day:
                    raise TemplateCapReached("daily cap reached")
                transport.send_utility_template(
                    config.owner_e164, "mirror_stale_v1",
                    [f"{mirror.generated_at:%Y-%m-%d}"])
                store.increment("templates", tier="T0", now=now)
                store.increment_month("service_messages", now=now)
            except (PlatformBlocked, TransportError) as exc:
                if isinstance(exc, PlatformBlocked):
                    store.kv_set("platform_blocked", "1")
                log_event(config.state_dir, "stale_notice_failed", level="error",
                          error=str(exc))
            log_event(config.state_dir, "mirror_stale_notices_owner",
                      generated_at=str(mirror.generated_at))
        result["status"] = "stale"
        return result

    if (store.kv_get("stale_notified", "0") or "0") == "1":
        store.kv_set("stale_notified", "0")  # fresh again: reset the one-shot

    grace = timedelta(seconds=config.late_grace_seconds)
    for item in mirror.items:
        for remind_at in item.remind_at:
            fire_at = _parse_ts(remind_at)
            if fire_at is None:
                continue
            row = store.fired_row(item.id, remind_at)
            if row is not None:
                if row["status"] == "pending":
                    # crash between write-ahead and send: honest uncertainty
                    store.record_fired(item.id, remind_at, "unknown", now=now)
                    log_event(config.state_dir, "reminder_unknown_after_crash",
                              level="warn", commitment_id=item.id,
                              remind_at=remind_at)
                continue
            if now > fire_at + grace:
                store.record_fired(item.id, remind_at, "missed", now=now)
                log_event(config.state_dir, "reminder_missed", commitment_id=item.id,
                          remind_at=remind_at)
                result["missed"] += 1
                continue
            if now >= fire_at:
                outcome = send_reminder(backend=backend, config=config, store=store,
                                        transport=transport, item=item,
                                        remind_at=remind_at, now=now)
                if outcome == "sent":
                    result["sent"] += 1
                elif outcome == "capped":
                    result["capped"] += 1
                elif outcome == "platform_blocked":
                    result["status"] = "platform_blocked"
                    return result
                else:
                    result["skipped"] += 1
    return result
