"""Presence (§19.1 + IF-4) — one toggle, honestly visible, with a schedule
suggestion, plus a DEVICE-presence notion that feeds the orb.

Class mode (owner's spec, verbatim): voice out OFF, spoken acks OFF, knocks
become silent visual pulses, initiative restricted to urgent-only. The console
stays fully usable. The mode is visible in the console, in Waybar and in
`assist status`.

Device presence (H, wave 1 · corrected in round 2 against IF-4 + E's emission):
the phone state is *reported* — never acted on. H owns the read/render side; the
write side is the daemon (HR-H-1), so this module never imports, reads, edits or
polls anything on the phone side. IF-4 lists `phone-connected` as an orb state
"driven by an EXISTING daemon signal", and IF-4's own rule is that a signal the
daemon did not produce makes the orb LIE. So this module separates two facts that
are easy to collapse into one:

  * **paired**  — a durable configuration fact, from E's real rows
    (`phone.paired` / `phone.unpaired` / `phone.revoked`). It does not decay.
  * **link up** — a liveness fact. Nothing in the frozen contracts emits it yet
    (IF-3 only allowlists the *reads* that could produce it: `ping.ping`,
    `connectivity_report`). So it is never inferred from pairing, and the orb's
    `phone-connected` state stays unclaimed until HR-H-2 lands.

Reporting "not connected" for a paired-but-silent phone would be just as much a
lie as claiming it is connected: the honest reading is *paired, liveness unknown*,
and that is what the surface says.

Two decisions worth stating in code:

1. A schedule does not silently switch the mode. It produces a *suggestion* the
   owner can take with one toggle. An assistant that changes its own social
   posture because the clock says so is exactly the kind of initiative §19.2
   forbids.
2. Class mode is posture, not a lock. The console's text path and all local
   tools keep working; only speech, spoken acks, knock sound and non-urgent
   initiative change.
3. Device presence is a mirror, not a trigger. The phone-connected state is
   read, recorded and rendered; it never starts, stops or restrains anything,
   and an unrecognised event is ignored rather than interpreted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

STATE_KEY = "presence.class_mode"

#: Device-presence lives under its own state key, written only by the folds below
#: (the daemon calls them — HR-H-1). Kept separate from STATE_KEY on purpose: a
#: transient link state must never be able to masquerade as, or overwrite, the
#: owner's posture toggle.
DEVICE_STATE_KEY = "presence.device"

#: Pairing/durability tokens, taken from E's ACTUAL emission (RPT-E-r2 §D/HR-E-4:
#: phone.paired, phone.unpaired, phone.revoked) — not from a name H guessed. In
#: round 1 this lane invented `phone.connected`; that token exists nowhere in the
#: fleet, which is exactly how a surface ends up confidently wrong. Anything not
#: listed here is IGNORED, so an unrecognised token cannot manufacture a state.
PHONE_PAIRED_EVENTS: tuple[str, ...] = ("phone.paired",)
PHONE_UNPAIRED_EVENTS: tuple[str, ...] = ("phone.unpaired", "phone.revoked")

#: Everything E emits that is NOT a presence signal (HR-E-4's send/refusal/inbound
#: rows). They prove a send happened, not that the phone is awake, so they must not
#: touch this state at all — pinned by test_send_and_receive_events_are_not_presence.
NOT_PRESENCE_EVENTS: tuple[str, ...] = (
    "phone.send.attempt", "phone.send.sent", "phone.send.failed",
    "phone.refused", "phone.inbound", "phone.inbound.refused",
    "draft.pending", "draft.resolved",
)

#: A link we last heard of longer than this ago is reported as *stale*, not as
#: connected. Applied to the LIVENESS field only — pairing is durable and must not
#: decay into "unpaired" just because nobody pinged (round-1 defect, see G).
DEFAULT_DEVICE_STALE_AFTER_S = 45.0

#: IF-4's orb vocabulary, verbatim, for the states this lane can legitimately
#: claim. A consumer THROWs on an unknown state (IF-4, "no silent default"), so H
#: emits contract-listed tokens or nothing at all — never a local dialect.
ORB_STATE_PHONE_CONNECTED = "phone-connected"

_DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class ClassModeStatus:
    enabled: bool
    source: str                    # manual | off
    suggested: bool = False
    suggestion: str = ""
    schedule_label: str = ""
    voice_out: bool = True
    spoken_acks: bool = True
    knock_style: str = "sound+visual"
    initiative: str = "normal"
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "source": self.source,
            "suggested": self.suggested,
            "suggestion": self.suggestion,
            "schedule_label": self.schedule_label,
            "voice_out": self.voice_out,
            "spoken_acks": self.spoken_acks,
            "knock_style": self.knock_style,
            "initiative": self.initiative,
            "reason": self.reason,
        }


@dataclass
class DevicePresence:
    """Two facts about a phone, kept apart on purpose — never a trigger.

    `paired`    : a pairing record exists (durable; E's `phone.paired`).
    `link_up`   : the link was *seen* alive (liveness; no contract signal emits
                  this yet, so it is False by default and never inferred).
    `phone_connected` is **link_up, nothing else** — IF-4's `phone-connected` orb
    state is driven by an existing daemon signal, and pairing is not one.
    `liveness_known` tells a surface whether it may say anything at all.

    `source` is part of the contract with the surfaces: `absent` (never heard
    from), `paired` (pairing only — presence unknown), `event` (liveness seen),
    `stale` (liveness seen, then silence), `disabled` (owner switched it off),
    `corrupt` (state unreadable). Every value except `event` renders as
    NOT-connected-but-said-honestly: this fails closed, never forward.
    """

    paired: bool = False
    link_up: bool = False
    phone_connected: bool = False
    source: str = "absent"
    detail: str = ""
    observed_at: float | None = None
    age_s: float | None = None
    stale: bool = False
    liveness_known: bool = False

    @property
    def orb_states(self) -> tuple[str, ...]:
        """Contract-listed orb states only (IF-4: an unknown state THROWS)."""
        return (ORB_STATE_PHONE_CONNECTED,) if self.phone_connected else ()

    def as_dict(self) -> dict:
        return {
            "paired": self.paired,
            "link_up": self.link_up,
            "phone_connected": self.phone_connected,
            "source": self.source,
            "detail": self.detail,
            "observed_at": self.observed_at,
            "age_s": None if self.age_s is None else round(self.age_s, 1),
            "stale": self.stale,
            "liveness_known": self.liveness_known,
            "orb_states": list(self.orb_states),
        }


def format_device_line(presence: dict) -> str:
    """The one sentence every surface says about the phone (empty = say nothing).

    Takes the dict shape (`DevicePresence.as_dict()`, or whatever the daemon
    broadcast) so no surface re-derives a verdict and pill and console cannot
    disagree. Three readings must stay distinguishable in the wording, because
    they are three different claims: never heard from (`absent`), paired but
    liveness unknown (`paired`), and liveness seen then lost (`stale`). Saying
    "not connected" for the middle one would be a lie by omission.
    """
    if not presence:
        return ""
    source = str(presence.get("source") or "")
    detail = str(presence.get("detail") or "")
    if source == "disabled":
        return ""
    if presence.get("phone_connected"):
        return ("phone: connected — liveness seen via " + (detail or source)
                if detail or source != "event" else "phone: connected — liveness seen")
    if presence.get("stale"):
        return "phone: stale — " + (detail or "the link went quiet")
    if presence.get("paired") and not presence.get("liveness_known"):
        return ("phone: paired — presence unknown (no liveness signal yet"
                + (f"; {detail}" if detail else "") + ")")
    if presence.get("paired"):
        return "phone: paired, link down — " + (detail or "liveness said gone")
    if source in ("", "absent"):
        return "phone: never reported — no pairing event and no liveness signal"
    if source == "corrupt":
        return "phone: unreadable — reported as not connected rather than guessed"
    return "phone: not connected — " + (detail or source or "unknown")


def _to_datetime(value) -> datetime | None:
    """Resolve an injected clock to a `datetime`; epoch numbers are accepted.

    Returns None for a clock that is neither, rather than raising: the schedule
    suggestion is a courtesy, and it must not be able to take a surface down.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value))
    return None


def _now_epoch(value) -> float:
    """`datetime` or epoch-seconds → epoch-seconds. Clock is injected in tests.

    Raises on anything else: a presence age computed from a clock we cannot read
    would be a number pretending to be a measurement.
    """
    if isinstance(value, (int, float)):
        return float(value)
    timestamp = getattr(value, "timestamp", None)
    if callable(timestamp):
        return float(timestamp())
    raise TypeError(f"unreadable clock: {value!r}")


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        hour, minute = str(value).split(":")
        hour_i, minute_i = int(hour), int(minute)
    except (ValueError, AttributeError):
        return None
    if not (0 <= hour_i < 24 and 0 <= minute_i < 60):
        return None
    return hour_i, minute_i


def _day_matches(spec, weekday: int) -> bool:
    """Monday=0. Accepts ints, 3-letter names, or full names."""
    if isinstance(spec, (str, int)):
        spec = [spec]
    for entry in spec or []:
        if isinstance(entry, bool):
            continue
        if isinstance(entry, int):
            if entry == weekday:
                return True
        else:
            text = str(entry).strip().lower()[:3]
            if text in _DAY_NAMES and _DAY_NAMES.index(text) == weekday:
                return True
    return False


@dataclass
class PresenceService:
    config: object
    store: object
    now: object = None

    def _current_epoch(self, now=None) -> float:
        """Epoch seconds from an injected clock, the configured clock, or wall time.

        `now=None` means "nobody injected a clock": the daemon's wall clock is
        used, exactly as the class-mode side already does.
        """
        value = now
        if value is None:
            value = self.now() if callable(self.now) else self.now
        if value is None:
            value = datetime.now()
        return _now_epoch(value)

    def _settings(self) -> dict:
        return self.config.section("presence") if self.config else {}

    # -- schedule suggestion ---------------------------------------------------
    def _posture_clock(self, now=None) -> datetime:
        """A readable datetime for the schedule side, from whatever clock arrived.

        `now=None` + no injected clock means wall time — the behaviour every
        surface had before device-presence existed, kept on purpose.
        """
        value = now
        if value is None:
            value = self.now() if callable(self.now) else self.now
        if value is None:
            value = datetime.now()
        resolved = _to_datetime(value)
        if resolved is None:
            raise TypeError(f"unreadable clock: {value!r}")
        return resolved

    def schedule_match(self, now: datetime | None = None) -> dict | None:
        settings = self._settings()
        if not settings.get("class_schedule_suggest", True):
            return None
        current = self._posture_clock(now)
        weekday = current.weekday()
        minutes = current.hour * 60 + current.minute
        for window in settings.get("class_schedule") or []:
            if not isinstance(window, dict):
                continue
            days = window.get("days")
            start = _parse_hhmm(window.get("start", ""))
            end = _parse_hhmm(window.get("end", ""))
            if start is None or end is None:
                continue
            start_m = start[0] * 60 + start[1]
            end_m = end[0] * 60 + end[1]
            if start_m <= end_m:
                if days and not _day_matches(days, weekday):
                    continue
                active = start_m <= minutes < end_m
            else:                       # overnight window across midnight
                today_ok = not days or _day_matches(days, weekday)
                prev_ok = not days or _day_matches(days, (weekday - 1) % 7)
                active = (today_ok and minutes >= start_m) or (prev_ok and minutes < end_m)
            if active:
                return {
                    "label": str(window.get("label") or "class hours"),
                    "start": window.get("start"), "end": window.get("end"),
                    "days": days,
                }
        return None

    # -- status / toggle -------------------------------------------------------
    def enabled(self) -> bool:
        raw = self.store.get_state(STATE_KEY) if self.store else None
        if raw is None:
            return bool(self._settings().get("class_mode", False))
        try:
            return bool(json.loads(raw))
        except ValueError:
            return False

    def status(self, now: datetime | None = None) -> ClassModeStatus:
        enabled = self.enabled()
        window = self.schedule_match(now)
        suggested = bool(window) and not enabled
        if enabled:
            return ClassModeStatus(
                enabled=True, source="manual (owner toggle)",
                suggestion="", schedule_label=(window or {}).get("label", ""),
                voice_out=False, spoken_acks=False,
                knock_style="silent-visual", initiative="urgent-only",
                reason=("class mode: voice out OFF, spoken acks OFF, knocks are "
                        "silent visual pulses, initiative is urgent-only; the "
                        "console remains fully usable"))
        detail = ClassModeStatus(
            enabled=False, source="off",
            suggested=suggested,
            suggestion=(f"Class hours ({window['label']}, {window['start']}–{window['end']}) "
                        "— class mode would silence voice and spoken acks"
                        if window else ""),
            schedule_label=(window or {}).get("label", ""),
            voice_out=True, spoken_acks=True, knock_style="sound+visual",
            initiative="normal", reason="class mode off: normal voice and initiative")
        return detail

    def set_enabled(self, enabled: bool) -> ClassModeStatus:
        if self.store is None:
            raise RuntimeError("class mode needs the assistant store")
        self.store.set_state(STATE_KEY, json.dumps(bool(enabled)))
        return self.status()

    def toggle(self) -> ClassModeStatus:
        return self.set_enabled(not self.enabled())

    # -- device presence (IF-4 signal: reported, never acted on) ---------------
    def _device_stale_after_s(self) -> float:
        raw = self._settings().get("device_stale_after_s", DEFAULT_DEVICE_STALE_AFTER_S)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return DEFAULT_DEVICE_STALE_AFTER_S
        return value if value > 0 else DEFAULT_DEVICE_STALE_AFTER_S

    def _read_device_state(self) -> dict | None:
        raw = self.store.get_state(DEVICE_STATE_KEY) if self.store else None
        if raw is None:
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            return None                      # unreadable: reported, never guessed
        return data if isinstance(data, dict) else None

    def _record_device_state(self, record: dict) -> None:
        if self.store is not None:
            self.store.set_state(DEVICE_STATE_KEY, json.dumps(record))

    def device(self, now: datetime | None = None) -> DevicePresence:
        """The desktop's view of the phone: paired and liveness, never conflated."""
        if not self._settings().get("device_presence", True):
            return DevicePresence(source="disabled",
                                  detail="[presence] device_presence = false — "
                                         "device-presence not reported")
        stored = self._read_device_state()
        if stored is None:
            return DevicePresence(source="corrupt",
                                  detail="presence state unreadable")
        if not stored:
            return DevicePresence(source="absent")

        paired = bool(stored.get("paired"))
        link_up = bool(stored.get("link_up"))
        seen_at = stored.get("link_seen_at")
        link_detail = str(stored.get("link_detail") or "")
        pair_detail = str(stored.get("pair_detail") or "")
        # "a liveness source has spoken at least once" — an answer of NO is still an
        # answer, and it is what lets the pill say "paired, link down" instead of
        # falling back to the quieter "presence unknown".
        liveness_known = stored.get("link_reported_at") is not None

        age_s: float | None = None
        stale = False
        if link_up and isinstance(seen_at, (int, float)):
            try:
                epoch = self._current_epoch(now)
            except (TypeError, ValueError, AttributeError):
                epoch = None
            if epoch is not None:
                age_s = max(0.0, float(epoch) - float(seen_at))
                stale = age_s > self._device_stale_after_s()

        if link_up and not stale:
            return DevicePresence(paired=paired, link_up=True, phone_connected=True,
                                  source="event", detail=link_detail or "liveness seen",
                                  observed_at=seen_at, age_s=age_s,
                                  liveness_known=True)
        if stale:
            return DevicePresence(
                paired=paired, link_up=False, source="stale",
                detail=(f"last seen {age_s:.0f}s ago (> {self._device_stale_after_s():.0f}s) "
                        "— the link went quiet, so it is not claimed as connected"),
                observed_at=seen_at, age_s=age_s, stale=True, liveness_known=True)
        if not paired:
            return DevicePresence(source="unpaired",
                                  detail=pair_detail or "no pairing record (unpaired/revoked)",
                                  liveness_known=liveness_known)
        if liveness_known:
            return DevicePresence(paired=True, source="link-down",
                                  detail=link_detail or "liveness said gone",
                                  observed_at=seen_at, age_s=age_s, liveness_known=True)
        return DevicePresence(paired=True, source="paired",
                              detail=pair_detail or "paired; nothing has proven the link alive",
                              liveness_known=False)

    def apply_event(self, event: dict, now: datetime | None = None) -> DevicePresence:
        """Fold E's PAIRING rows into device-presence. Nothing else changes anything.

        Recognised: `phone.paired`, `phone.unpaired`, `phone.revoked` (E's own
        emission, RPT-E-r2 §D). Everything else — including E's send/refusal/inbound
        rows and IF-2's draft events — is ignored outright: a send proves the link
        was up at a moment in the past, which is not the same claim as "the phone is
        here", and IF-4 forbids a signal the daemon did not produce. Pairing never
        sets `link_up`, and an unpair clears it (a revoked device is not present).
        """
        kind = str((event or {}).get("event") or "")
        if kind not in PHONE_PAIRED_EVENTS and kind not in PHONE_UNPAIRED_EVENTS:
            return self.device(now)                      # unknown: state untouched
        stored = self._read_device_state() or {}
        record = dict(stored) if isinstance(stored, dict) else {}
        paired = kind in PHONE_PAIRED_EVENTS
        origin = str(event.get("source") or "phone-sidecar")
        record["paired"] = paired
        record["pair_detail"] = f"{kind} via {origin}"
        if not paired:
            # Revocation clears presence AND the liveness history: a later re-pair
            # must start from "unknown", not from "the old link said down minutes ago".
            record["link_up"] = False
            for stale_key in ("link_seen_at", "link_detail", "link_reported_at"):
                record.pop(stale_key, None)
        self._record_device_state(record)
        return self.device(now)

    def apply_liveness(self, *, link_up: bool, source: str = "",
                       now: datetime | None = None) -> DevicePresence:
        """The named entry point for the signal that does not exist yet (HR-H-2).

        H provides the record/derive/render side only: the *producer* is the daemon
        turning one of IF-3's allowlisted reads (`ping.ping`, `connectivity_report`
        via `state`) into a status field. H never adds that read itself — a
        timer-driven poll of the sidecar would be a new autonomous action, and the
        write set / signal schema are Z's to author (IF-4 change control).
        """
        stored = self._read_device_state() or {}
        record = dict(stored) if isinstance(stored, dict) else {}
        record["link_up"] = bool(link_up)
        record["link_reported_at"] = self._current_epoch(now)
        record["link_detail"] = source or ("liveness signal" if link_up else "liveness said gone")
        if link_up:
            record["link_seen_at"] = record["link_reported_at"]
        self._record_device_state(record)
        return self.device(now)

    def device_line(self, presence: DevicePresence) -> str:
        """One line for every surface, so the pill and the console cannot disagree."""
        return format_device_line(presence.as_dict())

    def snapshot(self, now: datetime | None = None) -> dict:
        """What the orb / `assist status` / the console render for presence.

        Shaped for Z: HR-H-1 asks for exactly one daemon line,
        `status["device_presence"] = presence.snapshot()["device_presence"]`
        (console.py puts `status["class_mode"]` the same way today), and HR-H-2
        asks that the liveness read be written through `apply_liveness`. The
        `orb_states` key carries IF-4's own token (`phone-connected`) so K never
        has to re-derive or rename it. Nothing in this dict drives a decision; it
        is a mirror.

        The injected clock may be a `datetime` or epoch seconds: the schedule
        suggestion resolves it through `_posture_clock` instead of crashing a
        surface over a `weekday()` call it never needed.
        """
        return {
            "class_mode": self.status(now).as_dict(),
            "device_presence": self.device(now).as_dict(),
        }

