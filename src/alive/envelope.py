"""Signed, immutable envelopes — the only thing that moves between the
alive host and the laptop.

Rules (from RPT-E-alive-layer-20261125T122137Z.md §2.4.1, binding):

* one file per message, immutable, hash-named:
  ``<prefix>/<YYYYMMDDTHHMMSSZ>_<seq>_<sha256(file)[:16]>.json``;
* the hash in the file *name* is checked by the reader against the file
  bytes; a mismatch is quarantine, never ingest, never silent;
* every envelope carries ``mac = HMAC-SHA256(mac_key, canonical_json(body))``
  where ``body`` is the envelope without the ``mac`` field;
* ``from_hash = sha256(e164 + salt)`` — the raw number never appears in
  Drive, and the owner tier is re-checked on the laptop side;
* canonical JSON is ``sort_keys`` + compact separators + UTF-8.

Nothing here contacts a network. This module is shared by the alive host
(which writes envelopes) and the laptop (which verifies them) — it is the
single source of truth for the format, so the two sides cannot drift.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import UTC, datetime

ENVELOPE_VERSION = 1

#: kinds the alive host may WRITE into inbox/
ALIVE_INBOX_KINDS = ("instruction", "stranger_turn", "proposal", "unsupported")
#: kinds the laptop may WRITE into commitments/
LAPTOP_MIRROR_KINDS = ("commitments",)
#: kinds the laptop may WRITE into receipts/
LAPTOP_RECEIPT_KINDS = ("receipt",)
#: kinds either side may verify
ALL_KINDS = ALIVE_INBOX_KINDS + LAPTOP_MIRROR_KINDS + LAPTOP_RECEIPT_KINDS
#: reminder_log / heartbeat / public_card / t1_allowlist share the same
#: signed-envelope framing but live in their own prefixes
LOG_KINDS = ("reminder_log", "heartbeat", "public_card", "t1_allowlist")

MAX_BODY_BYTES = 64 * 1024  # B: oversized body cap

_NAME_RE = re.compile(
    r"^(?P<ts>\d{8}T\d{6}Z)_(?P<seq>\d{6})_(?P<hash16>[0-9a-f]{16})\.json$")


def canonical_json(obj) -> bytes:
    """The one true serialisation. Do not paraphrase."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def name_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def from_hash(e164: str, salt: str) -> str:
    """Hash a phone number with the per-install salt. Never reversible."""
    return hashlib.sha256(f"{e164}{salt}".encode()).hexdigest()


def compute_mac(body: dict, mac_key: str) -> str:
    return hmac.new(mac_key.encode("utf-8"), canonical_json(body),
                    hashlib.sha256).hexdigest()


def sign(body: dict, mac_key: str) -> dict:
    """Return the envelope: ``body`` plus its ``mac``."""
    envelope = dict(body)
    envelope.pop("mac", None)
    envelope["mac"] = compute_mac(envelope, mac_key)
    return envelope


def verify_mac(envelope: dict, mac_key: str) -> bool:
    """Constant-time check of the envelope's ``mac``."""
    if not isinstance(envelope, dict):
        return False
    mac = envelope.get("mac")
    if not isinstance(mac, str) or not mac:
        return False
    body = {k: v for k, v in envelope.items() if k != "mac"}
    expected = compute_mac(body, mac_key)
    return hmac.compare_digest(expected, mac)


def envelope_bytes(envelope: dict) -> bytes:
    """Serialised form used for hashing and writing. Trailing newline is
    part of the contract so hash checks are stable everywhere."""
    return json.dumps(envelope, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, indent=1).encode("utf-8") + b"\n"


def envelope_name(ts: datetime, seq: int, data: bytes) -> str:
    stamp = ts.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{int(seq):06d}_{name_hash(data)[:16]}.json"


def parse_name(filename: str) -> dict | None:
    m = _NAME_RE.match(filename.rsplit("/", 1)[-1])
    if not m:
        return None
    return {"ts": m.group("ts"), "seq": int(m.group("seq")),
            "hash16": m.group("hash16")}


def check_name_hash(filename: str, data: bytes) -> bool:
    parsed = parse_name(filename)
    if parsed is None:
        return False
    return hmac.compare_digest(parsed["hash16"], name_hash(data)[:16])


def is_expired(envelope: dict, now: datetime) -> bool:
    expires = envelope.get("expires_at")
    if not expires:
        return False
    try:
        exp = datetime.fromisoformat(str(expires))
    except ValueError:
        return True  # unparseable expiry is expired, never executable
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    return now.astimezone(UTC) > exp


def make_envelope(*, kind: str, id: str, channel: str, from_: str,
                  sent_at: str, received_at: str, seq: int, body: str,
                  mac_key: str, salt: str, expires_at: str | None,
                  suspected_injection: bool = False,
                  extra: dict | None = None) -> dict:
    """Build a signed inbox envelope (alive-host side)."""
    payload = {
        "v": ENVELOPE_VERSION,
        "kind": kind,
        "id": str(id),
        "channel": channel,
        "from_hash": from_hash(from_, salt),
        "sent_at": sent_at,
        "received_at": received_at,
        "seq": int(seq),
        "body": str(body),
        "suspected_injection": bool(suspected_injection),
        "expires_at": expires_at,
    }
    if extra:
        payload.update(extra)
    return sign(payload, mac_key)


def load_verified(path: str, data: bytes, mac_key: str) -> tuple[dict | None, str | None]:
    """Reader-side: name hash + mac + JSON. Returns (envelope, error)."""
    if not check_name_hash(path, data):
        return None, "name hash does not match file bytes"
    try:
        envelope = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "body is not valid JSON"
    if not isinstance(envelope, dict):
        return None, "body is not a JSON object"
    if envelope.get("v") != ENVELOPE_VERSION:
        return None, f"unknown envelope version {envelope.get('v')!r}"
    if not verify_mac(envelope, mac_key):
        return None, "mac does not verify"
    return envelope, None
