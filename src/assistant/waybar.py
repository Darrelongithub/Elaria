"""Waybar surface (§3.9) — state at a glance, click to toggle.

One formatter, two delivery modes sharing it:
  one-shot  `assist status --waybar`           (Waybar `exec`, interval poll)
  follow    `assist status --waybar --follow`  (Waybar `exec` streaming:
             a fresh JSON line the moment the daemon broadcasts a change,
             so the listening state lights up without poll lag — §18's
             'hotkey → it's listening <150ms' applies to the *visible*
             state too, not just the ack)

Classes emitted here are styled in ui/waybar/style.css — keep them in sync:
idle | listening | transcribing | halted | down | mock | offline |
forced-offline (combinable).

The offline marker follows §13.9 rule 1: one small suffix, while the
tooltip carries the exact connectivity mode, queue and local voice.
"""

from __future__ import annotations

import json
import socket

from .ipc import DaemonUnavailable, call


def format_waybar(status: dict) -> dict:
    """Daemon status dict → Waybar custom-module JSON."""
    if not status.get("running"):
        return {"text": "○ Elaria down", "class": "down",
                "tooltip": "assistd is not running — systemctl --user start assistant"}
    mode = status.get("mode", "idle")
    classes = [mode]
    if status.get("halted"):
        classes = ["halted"]
        mode_label = "halted"
    else:
        mode_label = mode
    glyph = {"idle": "○", "listening": "●", "transcribing": "◐",
             "halted": "■"}.get(mode_label, "○")
    suffix = ""
    if status.get("gemini_mode") == "mock":
        classes.append("mock")
        suffix = " ·mock"
    connectivity = status.get("connectivity") or {}
    connectivity_mode = str(status.get("connectivity_mode")
                            or connectivity.get("effective_mode") or "")
    if connectivity_mode == "FORCED_OFFLINE":
        classes.append("forced-offline")
        suffix = " ·forced offline"
    elif connectivity_mode == "OFFLINE":
        classes.append("offline")
        suffix = " ·offline"
    last = status.get("last_transcript") or {}
    tooltip_lines = [
        f"Elaria — {mode_label} (gemini: {status.get('gemini_mode')})",
        (f"uptime {status.get('uptime_s', 0):.0f}s · live calls today: "
         f"{status.get('quota_today_live_calls', 0)}"),
    ]
    if connectivity_mode:
        tooltip_lines.append(
            f"connectivity: {connectivity_mode.lower().replace('_', ' ')} "
            f"(preference: {connectivity.get('preference', 'auto')})")
    queue_counts = status.get("cloud_queue") or {}
    if queue_counts:
        tooltip_lines.append("cloud queue: " + ", ".join(
            f"{k}={v}" for k, v in sorted(queue_counts.items())))
    voice = status.get("voice") or {}
    if voice:
        tooltip_lines.append(
            f"voice: local {voice.get('backend')} / {voice.get('voice_id')}")
    if status.get("capture"):
        tooltip_lines.append(f"capture: {status['capture']}")
    if last.get("snippet"):
        tooltip_lines.append(f"last: “{last['snippet']}”")
    return {
        "text": f"{glyph} Elaria{suffix}",
        "alt": mode_label,
        "class": classes,
        "tooltip": "\n".join(tooltip_lines),
    }


def stream_waybar(socket_path, *, interval_s: float = 5.0):
    """Yield Waybar JSON dicts: immediately on daemon events, plus a
    periodic refresh so uptime/quota stay honest if events go quiet.

    Uses the same events subscription as the overlay — one connection,
    newline-delimited. Daemon-down yields the 'down' shape and keeps
    trying on the refresh tick rather than dying (Waybar would only
    restart us anyway; a self-healing stream is kinder)."""
    yield format_waybar(_safe_status(socket_path))
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(interval_s)
                sock.connect(str(socket_path))
                sock.sendall(b'{"id": 1, "method": "events.subscribe", "params": {}}\n')
                buffer = b""
                while True:
                    try:
                        chunk = sock.recv(65536)
                    except TimeoutError:
                        yield format_waybar(_safe_status(socket_path))
                        continue
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if not line.strip():
                            continue
                        message = json.loads(line)
                        if "event" in message:  # a broadcast, not our subscribe reply
                            yield format_waybar(_safe_status(socket_path))
        except (OSError, DaemonUnavailable):
            yield format_waybar({"running": False})
            # Fall through to reconnect loop after a short backoff tick.
            import time
            time.sleep(min(interval_s, 2.0))


def _safe_status(socket_path) -> dict:
    try:
        return call(socket_path, "status", timeout=2.0)
    except Exception:
        return {"running": False}
