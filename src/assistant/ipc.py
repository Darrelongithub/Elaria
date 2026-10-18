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
    socket_path.unlink(missing_ok=True)  # stale socket from a crashed daemon

    async def _client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        if event_sink:
            event_sink(writer)
        try:
            while line := await reader.readline():
                try:
                    request = json.loads(line)
                    result = await handler(request.get("method", ""), request.get("params") or {})
                    reply = {"id": request.get("id"), "ok": True, "result": result}
                except Exception as exc:
                    reply = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                writer.write((json.dumps(reply) + "\n").encode())
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_unix_server(_client, path=str(socket_path))
    os.chmod(socket_path, 0o600)  # owner-only: the socket *is* the auth boundary
    return server


class DaemonUnavailable(RuntimeError):
    pass


def call(socket_path: Path, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    """Synchronous one-shot request from the thin CLI."""
    if not socket_path.exists():
        raise DaemonUnavailable(
            f"daemon socket not found at {socket_path} — is assistd running? "
            "(systemctl --user status assistant)"
        )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(socket_path))
            payload = json.dumps({"id": 1, "method": method, "params": params or {}}) + "\n"
            sock.sendall(payload.encode())
            buffer = b""
            while b"\n" not in buffer:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
    except OSError as exc:
        raise DaemonUnavailable(f"cannot reach daemon at {socket_path}: {exc}") from exc
    reply = json.loads(buffer.splitlines()[0]) if buffer.strip() else {"ok": False, "error": "empty reply"}
    if not reply.get("ok"):
        raise RuntimeError(reply.get("error", "daemon error"))
    return reply["result"]
