"""Class mode (§19.1) — one toggle, honestly visible, with a schedule suggestion.

Owner's spec, verbatim: voice out OFF, spoken acks OFF, knocks become silent
visual pulses, initiative restricted to urgent-only. The console stays fully
usable. The mode is visible in the console, in Waybar and in `assist status`.

Two decisions worth stating in code:

1. A schedule does not silently switch the mode. It produces a *suggestion* the
   owner can take with one toggle. An assistant that changes its own social
   posture because the clock says so is exactly the kind of initiative §19.2
   forbids.
2. Class mode is posture, not a lock. The console's text path and all local
   tools keep working; only speech, spoken acks, knock sound and non-urgent
   initiative change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

STATE_KEY = "presence.class_mode"

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
    now: object = field(default=datetime.now)

    def _settings(self) -> dict:
        return self.config.section("presence") if self.config else {}

    # -- schedule suggestion ---------------------------------------------------
    def schedule_match(self, now: datetime | None = None) -> dict | None:
        settings = self._settings()
        if not settings.get("class_schedule_suggest", True):
            return None
        current = now or self.now()
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
