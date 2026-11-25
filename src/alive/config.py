"""Alive-layer configuration.

The alive host is provisioned with a DIFFERENT OS user, a DIFFERENT Google
account and a DIFFERENT Meta asset than the laptop, and key material that is
disjoint except the one shared ``mac_key``. This module refuses to start on
the misconfigurations that would break that rule — silent downgrade is not a
failure mode this layer has.

Hard rules enforced here, in code:

* exactly ONE owner recipient (E.164). A second recipient in config is a
  start-up error, not a warning. There is no "reply to everyone" path;
* the WA token is bound to ONE phone number id; outbound is only ever
  addressed to the single configured recipient for reminders, or to the
  single sender of the current stranger turn for concierge replies;
* egress is allowlisted: the only HTTPS host the WhatsApp adapter may open
  is ``graph.facebook.com`` (override for tests only);
* the S-0 concierge is the only responder; there is no LLM client config
  and no model tier anywhere in this file — the alive layer must never
  grow an LLM (Elaria's rules AND the 15 Jan 2026 Meta policy);
* utility templates are capped in code (``max_templates_per_day``);
* T1 allowlist comes from the laptop export, never typed by hand here.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: The ONLY host the WhatsApp adapter may open. Everything else is refused
#: at the client boundary, before any packet leaves.
EGRESS_ALLOWLIST = ("graph.facebook.com",)

#: Graph API version pinned by the build. Bump deliberately, never at runtime.
GRAPH_API_VERSION = "v21.0"

#: Reminder template name the owner registers with Meta (utility template).
REMINDER_TEMPLATE = "reminder_v1"


class AliveConfigError(RuntimeError):
    """Refused to (start|use) config that breaks a hard rule."""


@dataclass(frozen=True)
class AliveConfig:
    # identity / crypto
    mac_key: str                       # shared with the laptop, provisioned once
    from_hash_salt: str                # provisioned together with mac_key
    owner_e164: str                    # the ONE principal who is the owner
    # T1 approved contacts are matched by salted hash, loaded at runtime from
    # the laptop's exported allowlist envelope — never stored raw here.

    # whatsapp cloud api (S-0: approved templates only, no free-form blast)
    wa_phone_number_id: str = ""
    wa_token: str = ""                 # file mode 0600, never in Drive
    wa_app_secret: str = ""            # webhook signature verification
    verify_token: str = ""             # hub.challenge handshake

    # limits — all enforced in code, all overridable ONLY in this file
    max_templates_per_day: int = 10    # utility templates (B14)
    owner_messages_per_day: int = 200  # owner instruction envelopes (B10)
    stranger_turns_per_day_per_sender: int = 20
    stranger_messages_per_month: int = 800  # stays under the 1,000 free
    late_grace_seconds: int = 30 * 60  # reminder firing grace (§2.4.4)
    stale_mirror_days: int = 30        # B11: firing stops past this
    expiry_hours: int = 72             # instruction envelope expiry
    max_body_bytes: int = 64 * 1024
    mute_after_never_list_hits: int = 3
    mute_window_hours: int = 24
    clock_suspect_tolerance_seconds: int = 60

    # paths / prefixes
    state_dir: Path = field(default_factory=lambda: Path("./alive-state"))
    inbox_prefix: str = "inbox"
    commitments_prefix: str = "commitments"
    reminder_log_prefix: str = "reminder_log"
    receipts_prefix: str = "receipts"
    heartbeat_prefix: str = "heartbeat"

    # behaviour
    tz: str = "Africa/Nairobi"
    freebusy_level: int = 0            # overridden by the laptop's public card
    content_free_secret_reminders: bool = False  # owner decision, default OFF
    fast_lane: bool = False            # owner decision, default OFF — never auto-approve

    def __post_init__(self):
        if not self.mac_key or len(self.mac_key) < 16:
            raise AliveConfigError("mac_key missing or too short; provision with `python -m alive.provision`")
        if not self.from_hash_salt or len(self.from_hash_salt) < 8:
            raise AliveConfigError("from_hash_salt missing; provision it together with mac_key")
        if not str(self.owner_e164).startswith("+") or not self.owner_e164[1:].isdigit():
            raise AliveConfigError("owner_e164 must be a single E.164 number, e.g. +2547...")
        for prefix in (self.inbox_prefix, self.commitments_prefix, self.reminder_log_prefix,
                       self.receipts_prefix, self.heartbeat_prefix):
            if "/" in prefix.strip("/") or not prefix.strip():
                raise AliveConfigError(f"bad prefix {prefix!r}: single path segment, no slashes")
        if self.commitments_prefix == self.inbox_prefix:
            raise AliveConfigError("inbox and commitments prefixes must differ (single-writer rule)")
        if not (0 <= self.freebusy_level <= 2):
            raise AliveConfigError("freebusy_level must be 0, 1 or 2 (3 is never a level)")
        if self.fast_lane:
            raise AliveConfigError(
                "fast_lane is refused by this build: alive_inbox jobs always land "
                "awaiting_approval on the laptop. The owner decision to relax this "
                "does not exist yet.")

    # -- tier resolution ---------------------------------------------------------
    def tier_for(self, sender_e164: str, *, sender_hash: str | None = None,
                 t1_hashes: set[str] | None = None) -> str:
        """T0 owner / T1 approved / T2 everyone else. Transport-authenticated
        sender only — never display name, never content. T1 membership is by
        salted hash of the allowlisted number; the raw list never leaves the
        laptop."""
        from .envelope import from_hash  # local import: keep config import light

        if str(sender_e164) == self.owner_e164:
            return "T0"
        digest = sender_hash or from_hash(str(sender_e164), self.from_hash_salt)
        if t1_hashes and digest in t1_hashes:
            return "T1"
        return "T2"


def load_config(path: str | Path) -> AliveConfig:
    """Load TOML config. Any structural problem is a hard refusal."""
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    section = raw.get("alive", raw)  # tolerate a bare [alive] table or flattened file

    recipients = section.get("recipients", [])
    if isinstance(recipients, str) or len(recipients) > 1:
        raise AliveConfigError(
            "config names more than one recipient — refusing to start. "
            "The alive layer addresses exactly one owner number.")
    owner = section.get("owner_e164") or (recipients[0] if recipients else None)

    caps = section.get("caps", {})

    def cap(name, default):
        value = caps.get(name, default)
        if not isinstance(value, int) or value < 0:
            raise AliveConfigError(f"caps.{name} must be a non-negative integer")
        return value

    state_dir = Path(section.get("state_dir", "./alive-state")).expanduser()
    cfg = AliveConfig(
        mac_key=str(section.get("mac_key", "")),
        from_hash_salt=str(section.get("from_hash_salt", "")),
        owner_e164=str(owner or ""),
        wa_phone_number_id=str(section.get("wa_phone_number_id", "")),
        wa_token=str(section.get("wa_token", "")),
        wa_app_secret=str(section.get("wa_app_secret", "")),
        verify_token=str(section.get("verify_token", "")),
        max_templates_per_day=cap("max_templates_per_day", 10),
        owner_messages_per_day=cap("owner_messages_per_day", 200),
        stranger_turns_per_day_per_sender=cap("stranger_turns_per_day_per_sender", 20),
        stranger_messages_per_month=cap("stranger_messages_per_month", 800),
        late_grace_seconds=cap("late_grace_seconds", 30 * 60),
        stale_mirror_days=cap("stale_mirror_days", 30),
        expiry_hours=cap("expiry_hours", 72),
        max_body_bytes=cap("max_body_bytes", 64 * 1024),
        mute_after_never_list_hits=cap("mute_after_never_list_hits", 3),
        mute_window_hours=cap("mute_window_hours", 24),
        clock_suspect_tolerance_seconds=cap("clock_suspect_tolerance_seconds", 60),
        state_dir=state_dir,
        inbox_prefix=str(section.get("inbox_prefix", "inbox")),
        commitments_prefix=str(section.get("commitments_prefix", "commitments")),
        reminder_log_prefix=str(section.get("reminder_log_prefix", "reminder_log")),
        receipts_prefix=str(section.get("receipts_prefix", "receipts")),
        heartbeat_prefix=str(section.get("heartbeat_prefix", "heartbeat")),
        tz=str(section.get("tz", "Africa/Nairobi")),
        freebusy_level=int(section.get("freebusy_level", 0)),
        content_free_secret_reminders=bool(section.get("content_free_secret_reminders", False)),
        fast_lane=bool(section.get("fast_lane", False)),
    )
    return cfg
