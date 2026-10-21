"""BH-K14 — event subscribers must be removed when their client disconnects.

`ipc.serve` never told the daemon a client went away: the StreamWriter
stayed in `Daemon._subscribers` until some later broadcast happened to
fail writing to it. `status` reported ghost subscribers (owner observed
2), and with no broadcasts the set only ever grew. Cleanup belongs at
disconnect time, in the connection's finally.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import socket
import threading
import time

from assistant.daemon import Daemon
from assistant.ipc import serve


def test_subscriber_discarded_on_disconnect_without_any_broadcast(config):
    daemon = Daemon(config)
    loop = asyncio.new_event_loop()
    kwargs = {}
    if "on_disconnect" in inspect.signature(serve).parameters:
        kwargs["on_disconnect"] = daemon._subscribers.discard
    server = loop.run_until_complete(
        serve(config.socket_path, daemon.handle, **kwargs))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect(str(config.socket_path))
        sock.sendall(b'{"id": 1, "method": "events.subscribe", "params": {}}\n')
        reply = b""
        while b"\n" not in reply:
            reply += sock.recv(4096)
        assert json.loads(reply.splitlines()[0])["ok"] is True
        assert len(daemon._subscribers) == 1

        sock.close()  # client goes away; NO broadcast happens afterwards
        deadline = time.monotonic() + 3.0
        while daemon._subscribers and time.monotonic() < deadline:
            time.sleep(0.02)
        assert daemon._subscribers == set(), (
            "a disconnected subscriber must be discarded at disconnect "
            "time, not whenever the next broadcast trips over it")
    finally:
        async def _shutdown():
            server.close()
            await daemon.aclose()

        asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=3)
        loop.close()
        daemon.store.close()
