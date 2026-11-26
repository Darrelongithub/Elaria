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
from .config import AliveConfig, AliveConfigError, normalise_e164
from .journal import iso_now, log_event
from .mirror import busy_days, load_mirror, load_public_card, load_t1_hashes
from .store import AliveStore
from .transport import PLATFORM_BLOCKED_CODES, OutsideServiceWindow, PlatformBlocked

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


def _valid_inbound_dt(meta_ts, now: datetime) -> datetime | None:
    """Return UTC datetime iff ``meta_ts`` is a valid epoch integer in ``[0, now]``."""
    try:
        ts_int = int(meta_ts)
    except (TypeError, ValueError, OverflowError):
        return None
    if ts_int < 0 or ts_int > now.timestamp():
        return None
    try:
        return datetime.fromtimestamp(ts_int, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


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
        pass
    return True


def push_backlog(config, backend) -> dict:
    """Drain any spool files that never reached the sync folder."""
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
    """Build, sign, write (SQLite + spool). Returns (envelope, name, data)."""
    seq = store.next_seq()
    envelope = envelope_mod.make_envelope(
        kind=kind, id=id_, channel="whatsapp_cloud", from_=sender,
        sent_at=sent_at, received_at=iso_now(), seq=seq, body=body_text,
        mac_key=config.mac_key, salt=config.from_hash_salt,
        expires_at=_expiry(now, config.expiry_hours),
        suspected_injection=suspected, extra=extra)
    data = envelope_mod.envelope_bytes(envelope)
    name = envelope_mod.envelope_name(now, seq, data)
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


def _extract_inbound_text(message: dict) -> tuple[str | None, str]:
    """Extract text-like user reply content from Meta Cloud API ``messages[]`` objects."""
    msg_type = str(message.get("type") or "").strip().lower()
    if msg_type == "text":
        body = str((message.get("text") or {}).get("body", ""))[:4000]
        return ("text", body)
    if msg_type == "button":
        btn = message.get("button") if isinstance(message.get("button"), dict) else {}
        body = str(btn.get("text") or btn.get("payload") or "")[:4000]
        return ("text", body) if body else ("unsupported", "")
    if msg_type == "interactive":
        inter = message.get("interactive") if isinstance(message.get("interactive"), dict) else {}
        sub = inter.get("type")
        if sub == "button_reply" and isinstance(inter.get("button_reply"), dict):
            body = str(inter["button_reply"].get("title") or inter["button_reply"].get("id") or "")[:4000]
            return ("text", body) if body else ("unsupported", "")
        if sub == "list_reply" and isinstance(inter.get("list_reply"), dict):
            body = str(inter["list_reply"].get("title") or inter["list_reply"].get("id") or "")[:4000]
            return ("text", body) if body else ("unsupported", "")
        return ("unsupported", "")
    if msg_type == "reaction":
        return (None, "")
    return ("unsupported", "")


def _handle_status(*, status_obj: dict, config: AliveConfig, store: AliveStore) -> None:
    """Process one item from ``value.statuses[]`` (sent/delivered/read/failed)."""
    if not isinstance(status_obj, dict):
        return
    wamid = str(status_obj.get("id") or "").strip()
    state = str(status_obj.get("status") or "").strip().lower()
    if not wamid or not state:
        return
    ts_iso = _iso_from_meta_ts(status_obj.get("timestamp"))
    pricing = status_obj.get("pricing") if isinstance(status_obj.get("pricing"), dict) else {}
    billable = pricing.get("billable") if isinstance(pricing.get("billable"), bool) else None
    category = str(pricing.get("category") or "") or None
    errors = status_obj.get("errors") if isinstance(status_obj.get("errors"), list) else []
    error_code = None
    if errors and isinstance(errors[0], dict):
        raw_code = errors[0].get("code")
        if isinstance(raw_code, int):
            error_code = raw_code
    store.record_delivery_status(
        wamid, state, ts=ts_iso, billable=billable, category=category, error_code=error_code)
    if state == "failed":
        log_event(
            config.state_dir,
            "wa_delivery_failed",
            level="warn",
            wamid=wamid,
            error_code=error_code,
        )
        if error_code in PLATFORM_BLOCKED_CODES:
            store.kv_set("platform_blocked", "1")
            log_event(
                config.state_dir,
                "platform_blocked",
                level="error",
                detail=f"async status failed with code={error_code}",
            )
    else:
        log_event(
            config.state_dir,
            "wa_delivery_status",
            wamid=wamid,
            status=state,
            billable=billable,
            category=category,
        )


def _handle_message(*, message: dict, config, store, backend, transport,
                    now: datetime) -> dict:
    """One inbound message → one decision. Raises nothing the caller can't
    turn into a 5xx-or-200 policy outcome."""
    if not isinstance(message, dict):
        return {"outcome": "ignored_malformed"}
    raw_sender = str(message.get("from", "")).strip()
    message_id = str(message.get("id", "")).strip()
    if not raw_sender or not message_id:
        return {"outcome": "ignored_malformed"}
    try:
        sender = normalise_e164(raw_sender)
    except AliveConfigError:
        log_event(config.state_dir, "ignored_non_e164_sender", level="warn", wamid=message_id)
        return {"outcome": "ignored_malformed"}

    if not store.first_time_seen(message_id, now=now):
        return {"outcome": "duplicate"}

    sender_hash = envelope_mod.from_hash(sender, config.from_hash_salt)
    valid_dt = _valid_inbound_dt(message.get("timestamp"), now)
    if valid_dt is not None:
        store.record_inbound_window(sender_hash, int(valid_dt.timestamp()), now)
    _check_clock_suspect(store, message.get("timestamp"), config, now)
    sent_at = _iso_from_meta_ts(message.get("timestamp"))
    msg_type = str(message.get("type") or "unknown")
    extracted_kind, text_body = _extract_inbound_text(message)

    t1_hashes = _cached_t1_hashes(config, store, backend, now)
    tier = config.tier_for(sender, sender_hash=sender_hash, t1_hashes=t1_hashes)

    if extracted_kind is None:
        log_event(config.state_dir, "reaction_ignored", tier=tier, wamid=message_id)
        return {"outcome": "ignored_reaction", "tier": tier}

    # --- owner: instruction path -------------------------------------------
    if tier == "T0":
        used = store.increment("envelopes", tier="T0", now=now)
        if used > config.owner_messages_per_day:
            store.increment("not_stored", tier="T0", now=now)
            if (store.kv_get("inbox_full_acked", "0") or "0") != now.strftime("%Y-%m-%d"):
                store.kv_set("inbox_full_acked", now.strftime("%Y-%m-%d"))
                _safe_service_reply(transport, sender,
                                    "I'm not able to take more right now. "
                                    "I'll leave it with her.", config, store,
                                    now=now)
            log_event(config.state_dir, "owner_cap_reached", level="warn")
            return {"outcome": "capped", "tier": tier}
        kind = "instruction" if extracted_kind == "text" else "unsupported"
        body_text = text_body if kind == "instruction" else f"unsupported message type: {msg_type}"
        envelope, _name, _data = _make_and_store_envelope(
            config=config, store=store, backend=backend, kind=kind,
            id_=message_id, sender=sender, sent_at=sent_at,
            body_text=body_text, now=now,
            suspected=suspected_injection(text_body) if text_body else False)
        if kind == "instruction":
            _safe_service_reply(transport, sender, _ack_text(envelope, config), config, store,
                                now=now)
        else:
            _safe_service_reply(transport, sender,
                                "I can't take files, voice notes or locations on "
                                "this line — text only.", config, store,
                                now=now)
        log_event(config.state_dir, "instruction_queued", tier=tier,
                  seq=envelope["seq"], suspected=envelope.get("suspected_injection"))
        return {"outcome": "queued", "tier": tier, "seq": envelope["seq"]}

    # --- strangers (and approved contacts): S-0 concierge, zero authority ----
    store.increment("turns", tier="T2", now=now)  # total, for reporting
    sender_day = store.increment(f"sender:{sender_hash[:16]}", tier="T2", now=now)
    if sender_day > config.stranger_turns_per_day_per_sender:
        store.increment("not_stored", tier="T2", now=now)
        _safe_service_reply(transport, sender,
                            "I'll leave this with her.", config, store,
                            now=now)
        log_event(config.state_dir, "stranger_cap_reached", sender_hash=sender_hash[:16])
        return {"outcome": "capped", "tier": tier}

    month = store.increment_month("service_messages", now=now)
    if month > config.stranger_messages_per_month:
        log_event(config.state_dir, "month_cap_reached", level="warn")
        _safe_service_reply(transport, sender,
                            "I'm not able to take more right now. "
                            "I'll leave it with her.", config, store,
                            now=now)
        return {"outcome": "capped", "tier": tier}

    concierge = S0Concierge(store, config)
    if extracted_kind != "text":
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
    _safe_service_reply(transport, sender, reply, config, store, now=now)
    log_event(config.state_dir, "stranger_turn", tier=tier, seq=envelope["seq"],
              kind=kind, never_list=extra.get("never_list_category"))
    return {"outcome": kind, "tier": tier, "seq": envelope["seq"]}


def _safe_service_reply(transport, to: str, text: str, config, store=None, *,
                        now: datetime | None = None) -> None:
    """Acks/replies are best-effort and journaled; never fatal, never retried.

    Relies on ``store``'s verified inbound window (which rejects future-skewed
    or malformed timestamps), so a spoofed/future timestamp never triggers an
    outbound session reply.
    """
    try:
        try:
            transport.send_service_reply(to, text, now=now)
        except TypeError:
            transport.send_service_reply(to, text)
    except OutsideServiceWindow as exc:
        log_event(config.state_dir, "reply_window_expired", level="warn", detail=str(exc))
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

    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account":
        log_event(config.state_dir, "ignored_non_waba_object", level="warn")
        return 200, b"EVENT_RECEIVED"

    entries = payload.get("entry") if isinstance(payload.get("entry"), list) else []
    outcomes = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes") if isinstance(entry.get("changes"), list) else []
        for change in changes:
            if not isinstance(change, dict) or change.get("field") != "messages":
                continue
            value = change.get("value", {}) if isinstance(change.get("value"), dict) else {}
            if value.get("messaging_product") != "whatsapp":
                continue
            metadata = value.get("metadata") if isinstance(value.get("metadata"), dict) else {}
            incoming_phone_id = str(metadata.get("phone_number_id") or "")
            if incoming_phone_id != config.wa_phone_number_id:
                log_event(
                    config.state_dir,
                    "ignored_wrong_phone_number_id",
                    level="warn",
                    incoming_phone_number_id=incoming_phone_id,
                )
                continue

            for status_obj in value.get("statuses") or []:
                _handle_status(status_obj=status_obj, config=config, store=store)

            # Map wa_id -> profile.name so multi-contact batches never mis-attribute names
            profile_by_waid: dict[str, str] = {}
            fallback_profile = ""
            for contact in value.get("contacts") or []:
                if isinstance(contact, dict):
                    pname = str((contact.get("profile") or {}).get("name", ""))
                    c_waid = str(contact.get("wa_id") or "").strip().lstrip("+")
                    if c_waid and pname:
                        profile_by_waid[c_waid] = pname
                    if pname and not fallback_profile:
                        fallback_profile = pname

            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                sender_digits = str(message.get("from") or "").strip().lstrip("+")
                pname = profile_by_waid.get(sender_digits, fallback_profile)
                if pname:
                    message = {**message, "_profile_name": pname}
                try:
                    outcome = _handle_message(message=message, config=config,
                                              store=store, backend=backend,
                                              transport=transport, now=now)
                except Exception as exc:
                    store.unsee(str((message or {}).get("id", "")))
                    log_event(config.state_dir, "durable_write_failed",
                              level="error", error=str(exc))
                    return 503, b"temporarily unavailable"
                outcomes.append(outcome)
    return 200, b"EVENT_RECEIVED"
