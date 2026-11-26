"""The webhook receiver — serverless-shaped, deterministic, LLM-free.

One pure function, ``handle_request``, is the whole receiver; ``serve.py``
binds it to a socket, and a serverless deployment binds it to a route. It
holds no authority: it can verify a Meta signature, tier the sender by
transport-authenticated E.164, write a signed envelope, fire at most one
reply, and count. Everything else — acting, deciding, promising — stays on
the laptop, behind the owner's spoken yes.

Inbound order of operations (design §2.4.1, binding):

1. size cap (413) — nothing parsed;
2. ``X-Hub-Signature-256`` over the RAW bytes, constant-time compare
   (403 + journal; nothing parsed);
3. JSON parse; per message:
   a. wamid seen before → skip (idempotent), still 200;
   b. tier from the transport-authenticated ``from`` — T0 owner /
      T1 approved (salted hash from the laptop export) / T2 stranger;
   c. T0 → instruction envelope; T1/T2 → S-0 concierge (stranger_turn /
      proposal envelope); media/unsupported → ``unsupported`` envelope,
      never downloaded;
   d. durable write: SQLite inbox row + spool file, fsync'd — if either
      fails → 503, no ack, Meta retries, journal row (I1: we never ACK
      what we did not keep);
   e. 200;
4. ack / concierge reply sent AFTER the durable write; an ack failure is
   journaled, never retried, never upgraded to a 5xx — an unsent ack is
   better than a double ack.

Stranger turns and owner instructions are different envelope kinds with
different laptop code paths. There is no code path from a stranger turn to
the instruction queue; the only sink is ``proposals`` on the laptop.

B3 note: the pre-stranger-door bug list said "stranger → no outbound
message". That line is stale since the owner ruling added the public front
door (§2.3b) and is NOT implemented; strangers get the S-0 deterministic
reply as designed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

from . import envelope as envelope_mod
from .concierge import S0Concierge
from .config import AliveConfig
from .journal import iso_now, log_event
from .mirror import busy_days, load_mirror, load_public_card, load_t1_hashes
from .store import AliveStore
from .transport import PlatformBlocked

GRAPH_SIGNATURE_HEADER = "X-Hub-Signature-256"

# phone_link.py (cluster E) trap detector, read-only adaptation — the alive
# layer interprets nothing; this flag is for the laptop's briefing only.
_SUSPECTED_INJECTION = re.compile(
    r"\b(?:delete|remove|erase|wipe|execute|run|ignore|send|upload|append|add|pretend)\b"
    r"\s+\S+"
    r'|"(?:steps|argv|env_diff)"\s*:',
    re.IGNORECASE,
)


def suspected_injection(text: str) -> bool:
    return bool(_SUSPECTED_INJECTION.search(unicodedata.normalize("NFKC", str(text))))


def verify_signature(raw_body: bytes, signature_header: str | None,
                     app_secret: str) -> bool:
    """Constant-time HMAC check over the RAW body. Fail → 403, never parse."""
    if not app_secret or not signature_header:
        return False
    prefix, _, digest = signature_header.partition("=")
    if prefix.strip() != "sha256" or not digest:
        return False
    expected = hmac.new(app_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest.strip())


def _iso_from_meta_ts(value) -> str:
    try:
        return (datetime.fromtimestamp(int(value), tz=UTC)
                .isoformat(timespec="seconds").replace("+00:00", "Z"))
    except (TypeError, ValueError, OSError, OverflowError):
        return iso_now()


def _check_clock_suspect(store: AliveStore, meta_ts, config: AliveConfig,
                         now: datetime) -> None:
    try:
        skew = abs(now.timestamp() - int(meta_ts))
    except (TypeError, ValueError, OverflowError, OSError):
        return
    if skew > config.clock_suspect_tolerance_seconds:
        if (store.kv_get("clock_suspect", "0") or "0") != "1":
            store.kv_set("clock_suspect", "1")
            log_event(config.state_dir, "clock_suspect", level="warn",
                      skew_seconds=int(skew))
    else:
        store.kv_set("clock_suspect", "0")


def _spool_write(config: AliveConfig, name: str, data: bytes) -> None:
    spool = Path(config.state_dir) / "spool"
    spool.mkdir(parents=True, exist_ok=True)
    dest = spool / name
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    with open(tmp, "rb") as fh:  # fsync before the rename, then fsync the dir
        import os
        os.fsync(fh.fileno())
    tmp.replace(dest)
    dirfd = os.open(spool, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(dirfd)
    finally:
        os.close(dirfd)


def _push_one(config, backend, name: str, data: bytes) -> bool:
    """Push one spool file to the sync folder; touch a .pushed marker on
    success. Best-effort: a Drive outage defers, it never fails the turn."""
    marker = Path(config.state_dir) / "spool" / f"{name}.pushed"
    if marker.exists():
        return True
    try:
        backend.put(config.inbox_prefix, name, data)
    except Exception as exc:
        log_event(config.state_dir, "spool_push_deferred", level="warn",
                  name=name, error=str(exc))
        return False
    try:
        marker.touch()
    except OSError:
        pass  # a missing marker just means one redundant re-push next time
    return True


def push_backlog(config, backend) -> dict:
    """Drain any spool files that never reached the sync folder (Drive was
    down, host crashed mid-push). Called on every POST so the line heals
    itself; also safe to call from a cron/timer."""
    spool = Path(config.state_dir) / "spool"
    pushed, failed = 0, 0
    if not spool.is_dir():
        return {"pushed": 0, "failed": 0}
    for path in sorted(spool.glob("*.json")):
        if (spool / f"{path.name}.pushed").exists():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            failed += 1
            continue
        if _push_one(config, backend, path.name, data):
            pushed += 1
        else:
            failed += 1
    if pushed:
        log_event(config.state_dir, "spool_backlog_pushed", pushed=pushed)
    return {"pushed": pushed, "failed": failed}


def _make_and_store_envelope(*, config, store, backend, kind, id_, sender,
                             sent_at, body_text, now, suspected=False,
                             extra=None):
    """Build, sign, write (SQLite + spool). Returns (envelope, name, data).

    Raises on durable-write failure — callers turn that into a 503."""
    seq = store.next_seq()
    envelope = envelope_mod.make_envelope(
        kind=kind, id=id_, channel="whatsapp_cloud", from_=sender,
        sent_at=sent_at, received_at=iso_now(), seq=seq, body=body_text,
        mac_key=config.mac_key, salt=config.from_hash_salt,
        expires_at=_expiry(now, config.expiry_hours),
        suspected_injection=suspected, extra=extra)
    data = envelope_mod.envelope_bytes(envelope)
    name = envelope_mod.envelope_name(now, seq, data)
    # durable write: spool file (fsync) FIRST, then the SQLite row. The
    # spool is the source the backlog pusher (push_backlog) drains into the
    # sync folder — a crash anywhere leaves a recoverable artifact, never
    # a silent loss.
    _spool_write(config, name, data)
    store.record_inbox(str(id_), kind, seq, now=now)
    _push_one(config, backend, name, data)
    return envelope, name, data


def _expiry(now: datetime, hours: int) -> str:
    from datetime import timedelta
    return (now + timedelta(hours=hours)).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _ack_text(envelope: dict, config: AliveConfig) -> str:
    body = str(envelope.get("body", "")).strip().replace("\n", " ")
    preview = body[:80] + ("…" if len(body) > 80 else "")
    expires = envelope.get("expires_at")
    return (f"Got it — queued #{envelope.get('seq')}. The laptop is off, so "
            f"nothing happens until it's on. {preview} "
            f"Expires {expires}.")


def _cached_t1_hashes(config, store, backend, now) -> set[str]:
    cached_at = store.kv_get("t1_hashes_cached_at")
    cache = store.kv_get("t1_hashes_cache")
    if cached_at and cache:
        try:
            age = (now - datetime.fromisoformat(cached_at)).total_seconds()
        except ValueError:
            age = 9999
        if age < 600:
            try:
                return set(json.loads(cache))
            except ValueError:
                pass
    try:
        hashes = load_t1_hashes(backend, config.commitments_prefix, config.mac_key)
    except Exception:
        hashes = set()
    store.kv_set("t1_hashes_cache", json.dumps(sorted(hashes)))
    store.kv_set("t1_hashes_cached_at", iso_now())
    return hashes


def _freebusy_for(config, store, backend, now) -> tuple[int, dict[int, int]]:
    """(level, busy_days) from the public card + mirror. Absent card = L0."""
    try:
        card = load_public_card(backend, config.commitments_prefix, config.mac_key)
    except Exception:
        card = None
    level = int(card.get("freebusy_level", 0)) if card else 0
    level = min(max(level, 0), 2)
    if level <= 0:
        return 0, {}
    mirror = load_mirror(backend, config.commitments_prefix, config.mac_key, now=now)
    if not mirror.verified:
        return 0, {}
    return level, busy_days(mirror, now=now)


def _handle_message(*, message: dict, config, store, backend, transport,
                    now: datetime) -> dict:
    """One inbound message → one decision. Raises nothing the caller can't
    turn into a 5xx-or-200 policy outcome."""
    if not isinstance(message, dict):
        return {"outcome": "ignored_malformed"}
    sender = str(message.get("from", "")).strip()
    if sender.isdigit():
        sender = "+" + sender
    if not sender.startswith("+") or not sender[1:].isdigit():
        return {"outcome": "ignored_malformed"}
    message_id = str(message.get("id", "")).strip()
    if not sender or not message_id:
        return {"outcome": "ignored_malformed"}

    if not store.first_time_seen(message_id, now=now):
        return {"outcome": "duplicate"}

    try:
        store.record_inbound_window(envelope_mod.from_hash(sender, config.from_hash_salt),
                                    int(message.get("timestamp")), now)
    except (TypeError, ValueError, OverflowError):
        pass  # malformed timestamps never open a service window
    _check_clock_suspect(store, message.get("timestamp"), config, now)
    sent_at = _iso_from_meta_ts(message.get("timestamp"))

    msg_type = message.get("type")
    text_body = ""
    if msg_type == "text":
        text_body = str((message.get("text") or {}).get("body", ""))[:4000]

    t1_hashes = _cached_t1_hashes(config, store, backend, now)
    sender_hash = envelope_mod.from_hash(sender, config.from_hash_salt)
    tier = config.tier_for(sender, sender_hash=sender_hash, t1_hashes=t1_hashes)

    # --- owner: instruction path -------------------------------------------
    if tier == "T0":
        used = store.increment("envelopes", tier="T0", now=now)
        if used > config.owner_messages_per_day:
            store.increment("not_stored", tier="T0", now=now)
            if (store.kv_get("inbox_full_acked", "0") or "0") != now.strftime("%Y-%m-%d"):
                store.kv_set("inbox_full_acked", now.strftime("%Y-%m-%d"))
                _safe_service_reply(transport, sender,
                                    "I'm not able to take more right now. "
                                    "I'll leave it with her.", config, store)
            log_event(config.state_dir, "owner_cap_reached", level="warn")
            return {"outcome": "capped", "tier": tier}
        kind = "instruction" if msg_type == "text" else "unsupported"
        body_text = text_body if kind == "instruction" else f"unsupported message type: {msg_type}"
        envelope, _name, _data = _make_and_store_envelope(
            config=config, store=store, backend=backend, kind=kind,
            id_=message_id, sender=sender, sent_at=sent_at,
            body_text=body_text, now=now,
            suspected=suspected_injection(text_body) if text_body else False)
        if kind == "instruction":
            _safe_service_reply(transport, sender, _ack_text(envelope, config), config, store)
        else:
            _safe_service_reply(transport, sender,
                                "I can't take files, voice notes or locations on "
                                "this line — text only.", config, store)
        log_event(config.state_dir, "instruction_queued", tier=tier,
                  seq=envelope["seq"], suspected=envelope.get("suspected_injection"))
        return {"outcome": "queued", "tier": tier, "seq": envelope["seq"]}

    # --- strangers (and approved contacts): S-0 concierge, zero authority ----
    store.increment("turns", tier="T2", now=now)  # total, for reporting
    sender_day = store.increment(f"sender:{sender_hash[:16]}", tier="T2", now=now)
    if sender_day > config.stranger_turns_per_day_per_sender:
        store.increment("not_stored", tier="T2", now=now)
        _safe_service_reply(transport, sender,
                            "I'll leave this with her.", config, store)
        log_event(config.state_dir, "stranger_cap_reached", sender_hash=sender_hash[:16])
        return {"outcome": "capped", "tier": tier}

    month = store.increment_month("service_messages", now=now)
    if month > config.stranger_messages_per_month:
        log_event(config.state_dir, "month_cap_reached", level="warn")
        _safe_service_reply(transport, sender,
                            "I'm not able to take more right now. "
                            "I'll leave it with her.", config, store)
        return {"outcome": "capped", "tier": tier}

    concierge = S0Concierge(store, config)
    if msg_type != "text":
        kind = "unsupported"
        body_text = f"unsupported message type: {msg_type}"
        outcome = None
    else:
        level, busy = _freebusy_for(config, store, backend, now)
        outcome = concierge.handle(
            sender_e164=sender, sender_hash=sender_hash, text=text_body,
            tier=tier, now=now, freebusy_level=level, busy_days=busy,
            display_name_claimed=str(message.get("_profile_name", "")))
        if outcome.proposal is not None:
            kind, body_text = "proposal", json.dumps(outcome.proposal["plan"],
                                                    ensure_ascii=False)
        else:
            kind, body_text = "stranger_turn", text_body

    extra = {"tier": tier}
    if outcome is not None:
        extra["never_list_category"] = outcome.never_list_category
        extra["memory_probe"] = outcome.memory_probe
        if outcome.proposal is not None:
            extra["proposal"] = outcome.proposal
            extra["principal"] = "stranger"  # fixed by code; no field can set it

    envelope, _name, _data = _make_and_store_envelope(
        config=config, store=store, backend=backend, kind=kind,
        id_=message_id, sender=sender, sent_at=sent_at,
        body_text=body_text, now=now, extra=extra)

    reply = outcome.reply if outcome is not None else (
        "I can't take files, voice notes or locations on this line — text only.")
    _safe_service_reply(transport, sender, reply, config, store)
    log_event(config.state_dir, "stranger_turn", tier=tier, seq=envelope["seq"],
              kind=kind, never_list=extra.get("never_list_category"))
    return {"outcome": kind, "tier": tier, "seq": envelope["seq"]}


def _safe_service_reply(transport, to: str, text: str, config, store=None) -> None:
    """Acks/replies are best-effort and journaled; never fatal, never retried."""
    try:
        transport.send_service_reply(to, text)
    except PlatformBlocked as exc:
        log_event(config.state_dir, "platform_blocked", level="error", detail=str(exc))
        if store is not None:
            store.kv_set("platform_blocked", "1")
    except Exception as exc:
        log_event(config.state_dir, "reply_failed", level="warn", error=str(exc))


def verify_hub(query: dict, config: AliveConfig):
    """The hub.challenge handshake. Returns (status, body)."""
    mode = str((query or {}).get("hub.mode", ""))
    token = str((query or {}).get("hub.verify_token", ""))
    challenge = str((query or {}).get("hub.challenge", ""))
    expected = config.verify_token or "\x00"
    if mode == "subscribe" and hmac.compare_digest(token, expected):
        return 200, challenge.encode("utf-8")
    log_event(config.state_dir, "verify_refused", level="warn")
    return 403, b"forbidden"


def handle_request(method: str, headers: dict, raw_body: bytes, *,
                   config: AliveConfig, store: AliveStore, backend,
                   transport, now: datetime | None = None,
                   query: dict | None = None):
    """Serverless-shaped entry point.

    Returns ``(status: int, body: bytes)``. No framework, no globals.
    """
    now = now or datetime.now(UTC)
    headers = {str(k).lower(): v for k, v in (headers or {}).items()}

    if method.upper() == "GET":
        return verify_hub(query or {}, config)

    if method.upper() != "POST":
        return 405, b"method not allowed"

    # heal any deferred pushes first — best-effort, never fatal
    try:
        push_backlog(config, backend)
    except Exception as exc:
        log_event(config.state_dir, "spool_backlog_failed", level="warn",
                  error=str(exc))

    # --- size cap before anything else --------------------------------------
    if len(raw_body) > config.max_body_bytes:
        log_event(config.state_dir, "oversize_body", level="warn",
                  bytes=len(raw_body))
        return 413, b"payload too large"

    # --- signature verification over RAW bytes -------------------------------
    signature = headers.get(GRAPH_SIGNATURE_HEADER.lower())
    if not verify_signature(raw_body, signature, config.wa_app_secret):
        log_event(config.state_dir, "bad_signature", level="warn")
        return 403, b"forbidden"

    # --- parse ----------------------------------------------------------------
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        log_event(config.state_dir, "unparseable_body", level="warn")
        return 400, b"bad request"

    entries = (payload.get("entry", []) if isinstance(payload, dict)
               and payload.get("object") == "whatsapp_business_account" else [])
    outcomes = []
    for entry in entries:
        for change in entry.get("changes", []):
            value = change.get("value", {}) if isinstance(change, dict) else {}
            if change.get("field") != "messages" or value.get("messaging_product") != "whatsapp":
                continue
            metadata = value.get("metadata") or {}
            if str(metadata.get("phone_number_id", "")) != config.wa_phone_number_id:
                continue
            profile_name = ""
            for contact in value.get("contacts", []) or []:
                if isinstance(contact, dict):
                    profile_name = str((contact.get("profile") or {}).get("name", ""))
                    break
            for message in value.get("messages", []):
                if isinstance(message, dict) and profile_name:
                    message = {**message, "_profile_name": profile_name}
                try:
                    outcome = _handle_message(message=message, config=config,
                                              store=store, backend=backend,
                                              transport=transport, now=now)
                except Exception as exc:
                    # durable-write failure etc: Meta must retry → 503, no ack,
                    # and the dedup insert is rolled back so the retry is
                    # re-processed rather than dropped as a duplicate (I1).
                    store.unsee(str((message or {}).get("id", "")))
                    log_event(config.state_dir, "durable_write_failed",
                              level="error", error=str(exc))
                    return 503, b"temporarily unavailable"
                outcomes.append(outcome)
    return 200, b"EVENT_RECEIVED"
