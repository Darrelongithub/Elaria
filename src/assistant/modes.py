"""Connectivity mode manager (Phase 8, §13.9).

Preferences and effective modes are deliberately different nouns:

    preference   auto | online | offline          (what the owner selected)
    effective    ONLINE | OFFLINE | FORCED_OFFLINE (what code must obey now)

`offline` is a privacy posture as much as a network state: in
FORCED_OFFLINE this module does not even run its health probe. Auto mode
uses a short, throttled Gemini-endpoint TCP probe plus failures observed
by live transports. Mock Gemini mode uses a local healthy probe by
default because fixtures are not network calls.

A requested switch during dictation/meeting capture is parked, not
applied underneath the session. The daemon calls
`apply_pending_after_session()` once capture has finished.
"""

from __future__ import annotations

import socket
import time
from collections.abc import Callable
from dataclasses import dataclass

ONLINE = "ONLINE"
OFFLINE = "OFFLINE"
FORCED_OFFLINE = "FORCED_OFFLINE"
PREFERENCES = ("auto", "online", "offline")

_PREFERENCE_KEY = "connectivity.preference"
_PENDING_KEY = "connectivity.pending_preference"
_NETWORK_MARKERS = (
    "network is unreachable", "network unreachable", "name or service not known",
    "temporary failure in name resolution", "nodename nor servname", "dns",
    "connection refused", "connection reset", "connection aborted",
    "timed out", "timeout", "offline", "unavailable", "503",
)


def looks_like_network_failure(error: object) -> bool:
    """Conservative classifier: quota/429 is not a dead router, and a
    transient Live disconnect that can rotate is not automatically one."""
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return True
    text = str(error).lower()
    if "quota" in text or "429" in text or "rate" in text:
        return False
    return any(marker in text for marker in _NETWORK_MARKERS)


def socket_health_probe(host: str, port: int = 443, timeout_s: float = 1.5) -> bool:
    """One short TCP reachability check. No API call, no key, no payload."""
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout_s)):
            return True
    except OSError:
        return False


@dataclass
class ModeStatus:
    preference: str
    effective_mode: str
    network_healthy: bool | None
    reason: str
    checked_at_s: float | None = None
    pending_preference: str | None = None
    switch_parked: bool = False

    @property
    def is_online(self) -> bool:
        return self.effective_mode == ONLINE

    @property
    def is_offline(self) -> bool:
        return self.effective_mode in (OFFLINE, FORCED_OFFLINE)

    def as_dict(self) -> dict:
        return {
            "preference": self.preference,
            "effective_mode": self.effective_mode,
            # Friendly duplicate for CLI/Waybar consumers.
            "mode": self.effective_mode.lower(),
            "online": self.is_online,
            "offline": self.is_offline,
            "forced_offline": self.effective_mode == FORCED_OFFLINE,
            "network_healthy": self.network_healthy,
            "reason": self.reason,
            "checked_at_s": self.checked_at_s,
            "pending_preference": self.pending_preference,
            "switch_parked": self.switch_parked,
        }


class ModeManager:
    def __init__(self, config, store=None, *, probe: Callable[[], bool] | None = None,
                 clock: Callable[[], float] = time.monotonic):
        self.config = config
        self.store = store
        self._clock = clock
        settings = config.section("connectivity") if config else {}
        self._interval_s = float(settings.get("health_check_interval_s", 20))
        if probe is not None:
            self._probe = probe
        elif getattr(config, "gemini_mode", "mock") == "mock":
            # Fixture mode is local by construction; probing a real socket
            # would make tests and offline development lie about network use.
            self._probe = lambda: True
        else:
            host = str(settings.get("health_host", "generativelanguage.googleapis.com"))
            port = int(settings.get("health_port", 443))
            timeout = float(settings.get("health_timeout_s", 1.5))
            self._probe = lambda: socket_health_probe(host, port, timeout)
        self._healthy: bool | None = None
        self._checked_at: float | None = None
        self._reason = "health not checked yet"

    # -- persistence ---------------------------------------------------------
    @property
    def preference(self) -> str:
        stored = self.store.get_state(_PREFERENCE_KEY) if self.store else None
        value = stored or self.config.section("connectivity").get("mode", "auto")
        value = str(value).lower()
        return value if value in PREFERENCES else "auto"

    @property
    def pending_preference(self) -> str | None:
        stored = self.store.get_state(_PENDING_KEY) if self.store else None
        return stored if stored in PREFERENCES else None

    def _set_stored_preference(self, value: str) -> None:
        if self.store:
            self.store.set_state(_PREFERENCE_KEY, value)

    def _set_pending_preference(self, value: str | None) -> None:
        if self.store:
            # The tiny state table has no delete API; empty means no pending.
            self.store.set_state(_PENDING_KEY, value or "")

    # -- health ---------------------------------------------------------------
    def refresh(self, *, force: bool = False) -> ModeStatus:
        preference = self.preference
        if preference == "offline":
            # Hard rule for the forced-offline test and the privacy posture:
            # no probe, no DNS, no socket.
            return self.status(refresh=False)
        now = self._clock()
        stale = self._checked_at is None or now - self._checked_at >= self._interval_s
        if force or stale:
            try:
                self._healthy = bool(self._probe())
                self._reason = ("Gemini endpoint reachable" if self._healthy
                                else "Gemini endpoint unreachable")
            except Exception as exc:
                self._healthy = False
                self._reason = f"health probe failed: {exc}"
            self._checked_at = now
        return self.status(refresh=False)

    def observe_success(self, source: str = "gemini") -> ModeStatus:
        self._healthy = True
        self._checked_at = self._clock()
        self._reason = f"{source} succeeded"
        return self.status(refresh=False)

    def observe_failure(self, error: object, source: str = "gemini") -> ModeStatus:
        if looks_like_network_failure(error):
            self._healthy = False
            self._checked_at = self._clock()
            self._reason = f"{source} network failure: {error}"
        return self.status(refresh=False)

    # -- effective mode ---------------------------------------------------------
    def status(self, *, refresh: bool = True) -> ModeStatus:
        if refresh:
            return self.refresh()
        preference = self.preference
        pending = self.pending_preference
        if preference == "offline":
            effective = FORCED_OFFLINE
            reason = "owner forced offline; network calls and probes are disabled"
        elif preference == "online":
            effective = ONLINE
            reason = "owner selected online"
            if self._healthy is False:
                reason += "; last health check was unhealthy, calls may fail"
        elif self._healthy is False:
            effective = OFFLINE
            reason = self._reason
        else:
            effective = ONLINE
            reason = self._reason if self._healthy else "auto: assuming online until checked"
        return ModeStatus(
            preference=preference,
            effective_mode=effective,
            network_healthy=self._healthy,
            reason=reason,
            checked_at_s=self._checked_at,
            pending_preference=pending,
            switch_parked=pending is not None,
        )

    @property
    def effective_mode(self) -> str:
        return self.status().effective_mode

    def is_online(self, *, refresh: bool = True) -> bool:
        return self.status(refresh=refresh).is_online

    def is_offline(self, *, refresh: bool = True) -> bool:
        return self.status(refresh=refresh).is_offline

    # -- switching ---------------------------------------------------------------
    def request_preference(self, value: str, *, active_session: bool = False) -> ModeStatus:
        """Set auto/online/offline. During a session, park the request;
        the current capture keeps the mode snapshot it started with."""
        value = str(value).lower()
        if value not in PREFERENCES:
            raise ValueError("mode preference must be auto, online, or offline")
        if active_session and value != self.preference:
            self._set_pending_preference(value)
            status = self.status(refresh=False)
            status.reason = (f"switch to {value} parked until the active "
                             "session finishes")
            return status
        self._set_pending_preference(None)
        self._set_stored_preference(value)
        if value != "offline":
            # A fresh owner decision deserves a fresh health answer.
            self._checked_at = None
            return self.refresh(force=True)
        return self.status(refresh=False)

    def apply_pending_after_session(self) -> ModeStatus:
        pending = self.pending_preference
        if pending is None:
            return self.status(refresh=False)
        self._set_pending_preference(None)
        return self.request_preference(pending, active_session=False)
