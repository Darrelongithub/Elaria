"""Dev/owner-host runner: WSGI app + reminder tick loop.

Production shape (owner's laptop step, NOT sandbox): a free serverless
route binding ``webhook.handle_request`` to POST /webhook and GET /webhook,
with the cron/timer calling ``reminders.tick`` + ``heartbeat.write_heartbeat``
every 60 s / 15 min. This file is the reference wiring, runnable anywhere
with ``python -m alive.serve`` for local verification — it is not how the
line is deployed, and it is never part of the laptop.
"""

from __future__ import annotations

from urllib.parse import parse_qs

from . import heartbeat
from .config import load_config
from .journal import log_event
from .store import AliveStore
from .sync import FixtureSyncBackend
from .transport import FakeTransport, WhatsAppCloudTransport
from .webhook import handle_request


class AliveWSGIApp:
    def __init__(self, config, store, backend, transport):
        self.config = config
        self.store = store
        self.backend = backend
        self.transport = transport

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        query = {k: v[0] for k, v in parse_qs(environ.get("QUERY_STRING", "")).items()}
        length = int(environ.get("CONTENT_LENGTH") or 0)
        raw = environ["wsgi.input"].read(length) if length else b""
        headers = {k[5:].replace("_", "-"): v
                   for k, v in environ.items() if k.startswith("HTTP_")}

        if path not in ("/webhook", "/"):
            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"not found"]

        status, body = handle_request(
            method, headers, raw,
            config=self.config, store=self.store, backend=self.backend,
            transport=self.transport, query=query)
        start_response(f"{status} OK" if status < 400 else f"{status} Error",
                       [("Content-Type", "text/plain")])
        return [body]


def main(argv=None) -> int:
    import argparse
    import wsgiref.simple_server

    parser = argparse.ArgumentParser(description="Run the alive layer (dev/owner host)")
    parser.add_argument("config", help="path to alive.toml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--fixture-remote", default=None,
                        help="local directory standing in for the Drive folder "
                             "(labelled fixture; the real host uses rclone)")
    parser.add_argument("--fake-transport", action="store_true",
                        help="record sends instead of calling Meta (sandbox/dev)")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    store = AliveStore(config.state_dir)
    if args.fixture_remote:
        backend = FixtureSyncBackend(args.fixture_remote)
    else:
        from .sync import RcloneSyncBackend
        backend = RcloneSyncBackend(remote="elaria-sync", root_folder="elaria-sync")
    transport = (
        FakeTransport(config=config, store=store, enforce_window=True)
        if args.fake_transport
        else WhatsAppCloudTransport(config, store=store)
    )

    app = AliveWSGIApp(config, store, backend, transport)
    log_event(config.state_dir, "serve_started", host=args.host, port=args.port,
              fixture=bool(args.fixture_remote), fake_transport=args.fake_transport)
    # One tick at startup + on each minute is the deploy target's cron's job;
    # the dev runner does a single heartbeat so the file exists.
    heartbeat.write_heartbeat(backend=backend, config=config, store=store)
    wsgiref.simple_server.make_server(args.host, args.port, app).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
