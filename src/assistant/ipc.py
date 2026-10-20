"""Unix-socket IPC — newline-delimited JSON, no network surface (§3.1).

Socket: $XDG_RUNTIME_DIR/assistant.sock, mode 0600. No TCP port exists
anywhere in this system. The CLI side is a thin stdlib-only client so
`assist` stays a ~5ms exec that Hyprland binds can call freely.

Protocol: one JSON object per line.
  request  {"id": 1, "method": "status", "params": {...}}
  response {"id": 1, "ok": true, "result": {...}} | {"ok": false, "error": "..."}
  event    {"event": "ack", ...}   (server-pushed, e.g. §18 local ack)
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from collections.abc import Awaitable, Callable
from pathlib import Path

Handler = Callable[[str, dict], Awaitable[dict]]


async def serve(socket_path: Path, handler: Handler,
                event_sink: Callable[[asyncio.StreamWriter], None] | None = None):
    """Start the daemon's Unix server. Returns the asyncio Server."""
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        live_peer = False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                probe.connect(str(socket_path))
                live_peer = True
        except OSError:
            live_peer = False
        if live_peer:
            raise RuntimeError(
                f"another daemon is already running and listening on {socket_path}"
            )
        socket_path.unlink(missing_ok=True)  # stale socket from a crashed daemon

    async def _client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if event_sink:
            event_sink(writer)
        try:
            while line := await reader.readline():
                req_id = None
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise TypeError("IPC request must be a JSON object")
                    req_id = request.get("id")
                    params = request.get("params") or {}
                    if not isinstance(params, dict):
                        raise TypeError("IPC params must be a JSON object")
                    result = await handler(str(request.get("method", "")),
                                           params, writer)
                    reply = {"id": req_id, "ok": True, "result": result}
                except Exception as exc:
                    reply = {"id": req_id, "ok": False,
                             "error": f"{type(exc).__name__}: {exc}"}
                writer.write((json.dumps(reply) + "\n").encode())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            try:
                writer.close()
            except RuntimeError:
                pass

    server = await asyncio.start_unix_server(_client, path=str(socket_path))
    os.chmod(socket_path, 0o600)  # owner-only: the socket *is* the auth boundary
    return server


class DaemonUnavailable(RuntimeError):
    pass


def subscribe_events(socket_path: Path):
    """Generator of daemon event dicts (transcript.interim, …) — the feed
    Waybar/overlay (Phase 2) and `assist events` render from."""
    import socket as _socket

    if not socket_path.exists():
        raise DaemonUnavailable(f"daemon socket not found at {socket_path}")
    sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    sock.connect(str(socket_path))
    sock.sendall(b'{"id": 1, "method": "events.subscribe", "params": {}}\n')
    buffer = b""
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            if line.strip():
                yield json.loads(line)


def call(socket_path: Path, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    """Synchronous one-shot request from the thin CLI."""
    if not socket_path.exists():
        raise DaemonUnavailable(
            f"daemon socket not found at {socket_path} — is assistd running? "
            "(systemctl --user status assistant)"
        )
    reply: dict | None = None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(socket_path))
            payload = json.dumps({"id": 1, "method": method, "params": params or {}}) + "\n"
            sock.sendall(payload.encode())
            buffer = b""
            while reply is None:
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    if not raw_line.strip():
                        continue
                    parsed = json.loads(raw_line)
                    if isinstance(parsed, dict) and "ok" in parsed:
                        reply = parsed
                        break
                if reply is not None:
                    break
                chunk = sock.recv(65536)
                if not chunk:
                    if buffer.strip():
                        parsed = json.loads(buffer.splitlines()[0])
                        if isinstance(parsed, dict) and "ok" in parsed:
                            reply = parsed
                    break
                buffer += chunk
    except OSError as exc:
        raise DaemonUnavailable(f"cannot reach daemon at {socket_path}: {exc}") from exc
    if reply is None:
        reply = {"ok": False, "error": "empty reply"}
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error", "daemon error"))
    return reply["result"]
