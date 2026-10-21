"""BH-K31 (minor batch): status swallowed a diagnostics failure.

`_status` wrapped the last-capture lookup in `except Exception:
last_capture = None` — indistinguishable from "no capture ever
happened". A broken persona-events read (exactly when you are
debugging capture) vanished silently.

Fix: surface the failure in the payload (`{"error": ...}`); the
aggregator stays up, but the hole is visible instead of silent.
"""

from __future__ import annotations

import asyncio

from assistant.daemon import Daemon


def test_status_surfaces_last_capture_failure(config, monkeypatch):
    daemon = Daemon(config)
    monkeypatch.setattr(
        daemon.store, "list_persona_events",
        lambda **k: (_ for _ in ()).throw(RuntimeError("db is gone")))
    status = asyncio.run(daemon._status({}))
    assert status["running"] is True
    assert status["last_capture"] == {"error": "RuntimeError: db is gone"}
    daemon.store.close()
