"""Overlay state machine (§3.9) — the pill's brain lives here, tested,
so the Quickshell QML (ui/quickshell/shell.qml) stays a dumb renderer:
clients are disposable, policy isn't (§1.1).

    assist events --overlay   →  one JSON state per line:
    {"visible": true, "kind": "listening", "text": "…partial…",
     "pulsing": true, "class": "listening"}

QML binds: visibility ← visible, label ← text, CSS-ish class ← class,
pulse animation ← pulsing. It contains NO decision logic of its own —
and, critically for Wayland, the window itself is layer-shell with
keyboardFocus NONE (enforced in QML, guarded by tests): an overlay
that steals focus mid-sentence is worse than no overlay (§3.3).

State rules:
  session.started     → visible, listening, gentle pulse (§18: you see
                        it listening <150ms after the hotkey)
  transcript.interim  → live partial text (parse-while-you-speak)
  session.checkin     → soft "Is that all?" visual pulse (§13.8 — the
                        silence ladder's quiet rung, never a nag)
  transcript.final    → final text, lingers briefly so it can be read
  session.ended       → start the linger countdown, then hide
  error               → error kind, lingers longer (it matters more)
Unknown events are ignored — forward compatibility is free.

All local, all synchronous: nothing here can add latency to the ack
path; the overlay renders *behind* the ack, never in front of it.
"""

from __future__ import annotations

import json
import socket
import time
from dataclasses import asdict, dataclass

FINAL_LINGER_S = 4.0
ERROR_LINGER_S = 8.0


@dataclass
class OverlayState:
    visible: bool = False
    kind: str = "hidden"  # hidden | listening | checkin | final | error
    text: str = ""
    pulsing: bool = False

    @property
    def css_class(self) -> str:
        return self.kind

    def to_json(self) -> dict:
        data = asdict(self)
        data["class"] = self.css_class
        return data


class OverlayReducer:
    """Daemon events → overlay states. Pure + clock-injected = testable."""

    def __init__(self, final_linger_s: float = FINAL_LINGER_S,
                 error_linger_s: float = ERROR_LINGER_S, now=time.monotonic):
        self.state = OverlayState()
        self.final_linger_s = final_linger_s
        self.error_linger_s = error_linger_s
        self._now = now
        self._hide_at: float | None = None

    def apply(self, event: dict) -> OverlayState:
        kind = event.get("event", "")
        if kind == "session.started":
            self.state = OverlayState(True, "listening", "", True)
            self._hide_at = None
        elif kind == "transcript.interim":
            self.state = OverlayState(True, "listening",
                                      str(event.get("text", "")), True)
            self._hide_at = None
        elif kind == "session.checkin":
            self.state = OverlayState(
                True, "checkin", str(event.get("prompt", "Is that all?")), True)
            self._hide_at = None
        elif kind == "transcript.final":
            self.state = OverlayState(True, "final",
                                      str(event.get("text", "")), False)
            self._hide_at = self._now() + self.final_linger_s
        elif kind == "session.ended":
            if self.state.kind != "final":
                self._hide_at = self._now()  # nothing to read: hide promptly
        elif kind in ("error",) or event.get("error"):
            message = str(event.get("error") or event.get("text") or "something went wrong")
            self.state = OverlayState(True, "error", message, False)
            self._hide_at = self._now() + self.error_linger_s
        # Unknown events: state untouched (overlay needn't know everything).
        return self.state

    def tick(self) -> OverlayState:
        """Advance time-based transitions (auto-hide after linger)."""
        if self._hide_at is not None and self._now() >= self._hide_at:
            self.state = OverlayState()
            self._hide_at = None
        return self.state


def stream_overlay_states(socket_path, *, tick_s: float = 0.5, now=time.monotonic):
    """Yield overlay-state dicts as daemon events arrive (+ linger ticks).

    Owns its socket; on daemon loss it yields the hidden state and keeps
    retrying — an overlay must never become a zombie window showing
    stale 'listening' forever."""
    reducer = OverlayReducer(now=now)
    last_emitted = reducer.state.to_json()
    yield last_emitted

    def changed(payload: dict) -> bool:
        nonlocal last_emitted
        if payload == last_emitted:
            return False
        last_emitted = payload
        return True

    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(tick_s)
                sock.connect(str(socket_path))
                sock.sendall(b'{"id": 1, "method": "events.subscribe", "params": {}}\n')
                buffer = b""
                while True:
                    try:
                        chunk = sock.recv(65536)
                    except TimeoutError:
                        reducer.tick()
                        payload = reducer.state.to_json()
                        if changed(payload):
                            yield payload
                        continue
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        message = json.loads(line)
                        if "event" in message:
                            payload = reducer.apply(message).to_json()
                            if changed(payload):
                                yield payload
        except OSError:
            if reducer.state.visible:
                reducer.state = OverlayState()  # daemon gone: hide, don't lie
                payload = reducer.state.to_json()
                if changed(payload):
                    yield payload
            time.sleep(1.0)
