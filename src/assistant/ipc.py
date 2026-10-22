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
import inspect
import json
import os
import socket
import struct
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

try:                                  # Linux/Fedora target; tests may run anywhere
    import fcntl
except ImportError:                   # pragma: no cover - non-Unix developer box
    fcntl = None

Handler = Callable[[str, dict], Awaitable[dict]]

# A client that stops reading must not park a connection task forever. Five
# seconds is orders of magnitude above a normal local drain, and the peer is
# already gone by then.
REPLY_DRAIN_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class IpcPrincipal:
    """Kernel-authenticated identity of a connected Unix-socket peer (I5).

    This value is constructed only from SO_PEERCRED, never from request JSON.
    The daemon decides whether the UID is its local owner before authorizing a
    state-changing handler.
    """

    pid: int
    uid: int
    gid: int


def ipc_peer_principal(writer: asyncio.StreamWriter) -> IpcPrincipal:
    """Read the connecting process identity from the kernel (I5).

    Linux is the supported runtime. If the transport cannot provide kernel
    credentials, fail closed rather than treating a caller-supplied identity
    field or the socket pathname alone as an authenticated principal.
    """
    peer_socket = writer.get_extra_info("socket")
    if peer_socket is None or not hasattr(socket, "SO_PEERCRED"):
        raise PermissionError("kernel-authenticated IPC credentials are unavailable")
    try:
        raw = peer_socket.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", raw)
    except (OSError, struct.error) as exc:
        raise PermissionError(
            f"could not authenticate the IPC peer: {exc}") from exc
    if pid <= 0 or uid < 0 or gid < 0:
        raise PermissionError("kernel returned invalid IPC peer credentials")
    return IpcPrincipal(pid=pid, uid=uid, gid=gid)


def _lock_path(socket_path: Path) -> Path:
    return socket_path.with_name(socket_path.name + ".lock")


def _acquire_daemon_lock(socket_path: Path):
    """Serialise the check-unlink-bind window with an advisory file lock.

    Probing the socket and unlinking a stale one are two syscalls: two daemons
    starting together could both see "stale", both unlink, and one could unlink
    the socket the other had just bound. The lock closes that window (BH-I8).
    The kernel releases it if the process dies, so a stale file is harmless.
    """
    if fcntl is None:                 # pragma: no cover
        return None
    # The handle must outlive this call and is closed by the server's close(),
    # so a context manager would release the lock immediately.
    handle = open(_lock_path(socket_path), "a+", encoding="utf-8")  # noqa: SIM115
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError(
            f"another daemon is already running (lock held on "
            f"{_lock_path(socket_path)})") from None
    return handle


def _release_daemon_lock(handle) -> None:
    if handle is None:
        return
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    finally:
        handle.close()


def _attach_lock_release(server, handle) -> None:
    """Release the daemon lock when the asyncio server is closed."""
    if handle is None:
        return
    original_close = server.close
    released = False

    def close() -> None:
        nonlocal released
        try:
            original_close()
        finally:
            if not released:
                released = True
                _release_daemon_lock(handle)

    server.close = close          # asyncio.Server has no __slots__


async def _write_reply(writer: asyncio.StreamWriter, reply: dict,
                       *, drain_timeout: float = REPLY_DRAIN_TIMEOUT_S) -> None:
    """Write one reply and bound the drain.

    `await writer.drain()` waits for the peer to consume the kernel buffer; a
    client that never reads can therefore hold the handler task forever
    (BH-I9). A missed drain deadline is treated as a disconnect.
    """
    writer.write((json.dumps(reply) + "\n").encode())
    try:
        await asyncio.wait_for(writer.drain(), timeout=drain_timeout)
    except TimeoutError:
        raise ConnectionResetError(
            "client stopped reading (reply drain timed out)") from None


def parse_event_line(line: bytes) -> dict | None:
    """One newline-delimited event frame, or None if it is not a JSON object.

    The event stream is a convenience surface: a torn or malformed frame is
    skipped by every consumer instead of killing the Waybar/console feed
    (BH-I13). Malformed *request* frames are still answered with `ok: false`.
    """
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


async def serve(socket_path: Path, handler: Handler,
                event_sink: Callable[[asyncio.StreamWriter], None] | None = None,
                on_disconnect: Callable[[asyncio.StreamWriter], None] | None = None):
    """Start the daemon's Unix server. Returns the asyncio Server."""
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = _acquire_daemon_lock(socket_path)
    try:
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
                    f"another daemon is already running and listening on "
                    f"{socket_path}")
            socket_path.unlink(missing_ok=True)  # stale socket from a crashed daemon
    except BaseException:
        _release_daemon_lock(lock_handle)
        raise

    accepts_writer = len(inspect.signature(handler).parameters) >= 3

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
                    method_name = str(request.get("method", ""))
                    if accepts_writer:
                        result = await handler(method_name, params, writer)
                    else:
                        result = await handler(method_name, params)
                    reply = {"id": req_id, "ok": True, "result": result}
                except Exception as exc:
                    reply = {"id": req_id, "ok": False,
                             "error": f"{type(exc).__name__}: {exc}"}
                await _write_reply(writer, reply)
        except (ConnectionResetError, BrokenPipeError, asyncio.CancelledError):
            pass
        finally:
            # BH-K14: tell the owner this connection is gone NOW. Without
            # this, event subscribers lingered in the daemon's set until
            # some later broadcast happened to fail writing to them —
            # ghost subscribers in `status`, growing without bound.
            if on_disconnect is not None:
                # Teardown must finish; the close below matters more.
                with suppress(Exception):
                    on_disconnect(writer)
            try:
                writer.close()
            except RuntimeError:
                pass

    try:
        server = await asyncio.start_unix_server(_client, path=str(socket_path))
    except BaseException:
        _release_daemon_lock(lock_handle)
        raise
    os.chmod(socket_path, 0o600)  # owner-only: the socket *is* the auth boundary
    _attach_lock_release(server, lock_handle)
    return server


class DaemonUnavailable(RuntimeError):
    """The daemon could not be contacted before a request was sent."""


class DaemonOutcomeUnknown(RuntimeError):
    """A request may have been applied, but no authoritative reply arrived.

    Callers must not replay the operation against local state: the daemon may
    already have committed it before the connection timed out or broke.
    """


class DaemonError(RuntimeError):
    """The daemon ANSWERED and refused (ok: false) — BH-K12.

    Distinct from DaemonUnavailable (the request was never sent) and
    DaemonOutcomeUnknown (a sent request got no authoritative reply): a refusal
    is an answer. Callers that fall back to local state when the daemon is
    unreachable must never silently re-run an operation the live daemon just
    refused; the three-way distinction makes that enforceable. Subclasses
    RuntimeError so generic error printers keep working and see the daemon's
    real message.
    """


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
                message = parse_event_line(line)
                if message is not None:
                    yield message


def _parse_reply_frame(raw_line: bytes) -> dict:
    """A reply frame, or a malformed-frame error for `call()` to classify."""
    try:
        parsed = json.loads(raw_line)
    except ValueError as exc:
        raise DaemonUnavailable(
            f"malformed reply from daemon at this socket: {raw_line[:80]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise DaemonUnavailable(
            f"malformed reply from daemon (not a JSON object): {raw_line[:80]!r}")
    return parsed


def call(socket_path: Path, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    """Synchronous one-shot request from the thin CLI.

    `timeout` is a TOTAL deadline (BUG 6d, hardware report 2026-10-20). The
    daemon streams event frames on the same connection as the reply, and a
    per-recv timeout reset by every frame let `assist dictate` sit inside
    `ptt.result` far past its wait_s budget while events trickled by. One
    deadline covers connect, send and the entire reply wait. Failures before
    `sendall` are `DaemonUnavailable`; after send may have begun they are
    `DaemonOutcomeUnknown`, which must not trigger a local replay.
    """
    if not socket_path.exists():
        raise DaemonUnavailable(
            f"daemon socket not found at {socket_path} — is assistd running? "
            "(systemctl --user status assistant)"
        )
    deadline = (time.monotonic() + timeout) if timeout is not None else None
    reply: dict | None = None
    request_started = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(socket_path))
            payload = json.dumps({"id": 1, "method": method, "params": params or {}}) + "\n"
            request_started = True  # sendall can partially write before raising
            sock.sendall(payload.encode())
            buffer = b""
            while reply is None:
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    if not raw_line.strip():
                        continue
                    parsed = _parse_reply_frame(raw_line)
                    if "ok" in parsed:
                        reply = parsed
                        break
                if reply is not None:
                    break
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise DaemonUnavailable(
                            f"daemon at {socket_path} did not reply to "
                            f"'{method}' within {timeout:g}s")
                    sock.settimeout(remaining)
                chunk = sock.recv(65536)
                if not chunk:
                    if buffer.strip():
                        parsed = _parse_reply_frame(buffer.splitlines()[0])
                        if "ok" in parsed:
                            reply = parsed
                    break
                buffer += chunk
    except DaemonUnavailable as exc:
        if request_started:
            raise DaemonOutcomeUnknown(
                f"daemon at {socket_path} may have processed '{method}', but "
                f"no valid reply arrived: {exc}") from exc
        raise
    except OSError as exc:
        if request_started:
            raise DaemonOutcomeUnknown(
                f"daemon at {socket_path} may have processed '{method}', but "
                f"the reply was not confirmed: {exc}") from exc
        raise DaemonUnavailable(f"cannot reach daemon at {socket_path}: {exc}") from exc
    if reply is None:
        if request_started:
            raise DaemonOutcomeUnknown(
                f"daemon at {socket_path} closed without replying to '{method}'; "
                "the operation may already have been applied")
        raise DaemonUnavailable(f"daemon at {socket_path} returned no reply")
    if not reply.get("ok"):
        raise DaemonError(reply.get("error", "daemon error"))
    return reply["result"]
