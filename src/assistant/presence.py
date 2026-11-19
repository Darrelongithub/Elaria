"""Presence (§19.1 + IF-4) — one toggle, honestly visible, with a schedule
suggestion, plus a DEVICE-presence notion that feeds the orb.

Class mode (owner's spec, verbatim): voice out OFF, spoken acks OFF, knocks
become silent visual pulses, initiative restricted to urgent-only. The console
stays fully usable. The mode is visible in the console, in Waybar and in
`assist status`.

Device presence (H, wave 1): the phone-connected state, *reported* — never
acted on. H owns the read/render side; the write side is the daemon folding
E's sidecar events in (HR-H-1), so this module never imports, reads or edits
E's files and never talks to the phone itself.

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

#: Device-presence lives under its own state key, written only by the presence
#: fold below (the daemon calls `apply_event` — HR-H-1). Kept separate from
#: STATE_KEY on purpose: a transient link state must never be able to masquerade
#: as, or overwrite, the owner's posture toggle.
DEVICE_STATE_KEY = "presence.device"

#: The event tokens a phone-connected notion may arrive under. E owns the phone
#: sidecar (IF-3); H consumes the notion through events only. Anything not listed
#: here is IGNORED: a presence feed that guesses is worse than one that stays
#: silent, so an unrecognised token can never manufacture a "connected" state.
PHONE_CONNECTED_EVENTS: tuple[str, ...] = (
    "phone.connected", "phone.pairing.paired", "pairing.paired",
)
PHONE_LOST_EVENTS: tuple[str, ...] = (
    "phone.disconnected", "phone.unpaired", "pairing.unpaired",
)

#: A link we last heard about longer than this ago is reported as *stale*, not as
#: connected. The sidecar heartbeats; silence means absence, and the surface says
#: so — "seen, then nothing" must not read as "still here".
DEFAULT_DEVICE_STALE_AFTER_S = 45.0

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
    """Is the phone here? A reported fact about a link — never a trigger.

    `source` is part of the contract with the surfaces: `event` (we folded a
    sidecar event), `state` (read back from the store after a daemon restart),
    `none` (never heard from), `stale` (heard, then silence), `disabled`
    (owner turned the notion off) and `corrupt` (state unreadable). `none`,
    `stale` and `corrupt` all render as NOT connected — this fails closed.
    """

    phone_connected: bool = False
    source: str = "none"
    detail: str = ""
    observed_at: float | None = None
    age_s: float | None = None
    stale: bool = False

    def as_dict(self) -> dict:
        return {
            "phone_connected": self.phone_connected,
            "source": self.source,
            "detail": self.detail,
            "observed_at": self.observed_at,
            "age_s": None if self.age_s is None else round(self.age_s, 1),
            "stale": self.stale,
        }


def format_device_line(presence: dict) -> str:
    """The one sentence every surface says about the phone link (empty = say nothing).

    Takes the dict shape (`DevicePresence.as_dict()`, or whatever the daemon
    broadcast) so a surface never re-derives the verdict and the pill and the
    console cannot disagree. A missing/empty dict yields "" — an absent notion
    stays absent rather than being narrated as "disconnected", which would be a
    claim about a phone we simply never heard from.
    """
    if not presence:
        return ""
    if presence.get("source") == "disabled":
        return ""
    detail = str(presence.get("detail") or "")
    if presence.get("phone_connected"):
        source = str(presence.get("source") or "event")
        return ("phone: connected — device-presence from " + source
                + (f" ({detail})" if detail else ""))
    if presence.get("stale"):
        return "phone: stale — " + (detail or "the link went quiet")
    if presence.get("source") == "none":
        return "phone: unknown — no sidecar event yet"
    return "phone: not connected — " + (detail or str(presence.get("source") or "unknown"))


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

    def device(self, now: datetime | None = None) -> DevicePresence:
        """The desktop's view of the phone link, honest about its own staleness."""
        if not self._settings().get("device_presence", True):
            return DevicePresence(source="disabled",
                                  detail="[presence] device_presence = false — "
                                         "device-presence not reported")
        stored = self._read_device_state()
        if stored is None:
            return DevicePresence(
                source="corrupt",
                detail="presence state unreadable — reported as not connected "
                       "rather than guessed")
        if not stored:
            return DevicePresence(
                source="none",
                detail="no phone-sidecar event received yet (device-presence "
                       "waits on HR-H-1)")
        connected = bool(stored.get("connected"))
        observed = stored.get("observed_at")
        detail = str(stored.get("detail") or "")
        age_s: float | None = None
        stale = False
        try:
            epoch = self._current_epoch(now)
        except (TypeError, ValueError, AttributeError):
            epoch = None
        if connected and isinstance(observed, (int, float)) and epoch is not None:
            age_s = max(0.0, float(epoch) - float(observed))
            stale = age_s > self._device_stale_after_s()
        if not connected:
            return DevicePresence(phone_connected=False, source="event",
                                  detail=detail or "link dropped",
                                  observed_at=observed, age_s=age_s, stale=False)
        if stale:
            return DevicePresence(
                phone_connected=False, source="stale",
                detail=(f"last heard {age_s:.0f}s ago (> "
                        f"{self._device_stale_after_s():.0f}s) — the link went "
                        "quiet, so it is not claimed as connected"),
                observed_at=observed, age_s=age_s, stale=True)
        return DevicePresence(phone_connected=True, source="event",
                              detail=detail or "phone link up",
                              observed_at=observed, age_s=age_s, stale=False)

    def apply_event(self, event: dict, now: datetime | None = None) -> DevicePresence:
        """Fold one daemon event into device-presence and return the new state.

        This is the whole of H's side of IF-4 for the phone: recognise, record,
        report. It does NOT touch class mode, does not start a session, does not
        fire anything and does not decide anything — an unknown event is ignored
        outright rather than interpreted.
        """
        kind = str((event or {}).get("event") or "")
        if kind not in PHONE_CONNECTED_EVENTS and kind not in PHONE_LOST_EVENTS:
            return self.device(now)          # unknown: state untouched, nothing written
        connected = kind in PHONE_CONNECTED_EVENTS
        epoch = self._current_epoch(now)
        origin = str(event.get("source") or "phone-sidecar")
        payload = {
            "connected": connected,
            "observed_at": epoch,
            "detail": f"{kind} via {origin}",
        }
        if self.store is not None:
            self.store.set_state(DEVICE_STATE_KEY, json.dumps(payload))
        return DevicePresence(
            phone_connected=connected, source="event",
            detail=payload["detail"],
            observed_at=epoch, age_s=0.0 if connected else None,
        )

    def device_line(self, presence: DevicePresence) -> str:
        """One line for every surface, so the pill and the console cannot disagree."""
        return format_device_line(presence.as_dict())

    def snapshot(self, now: datetime | None = None) -> dict:
        """What the orb / `assist status` / the console render for presence.

        Shaped for Z: HR-H-1 asks for exactly one daemon line,
        `status["device_presence"] = presence.snapshot()["device_presence"]`
        (console.py puts `status["class_mode"]` the same way today). Nothing in
        this dict drives a decision; it is a mirror.

        The injected clock may be a `datetime` or epoch seconds: the schedule
        suggestion resolves it through `_posture_clock` instead of crashing a
        surface over a `weekday()` call it never needed.
        """
        return {
            "class_mode": self.status(now).as_dict(),
            "device_presence": self.device(now).as_dict(),
        }

