"""An ambiguous IPC timeout must not replay a committed queue enqueue."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace


def test_bug_queue_timeout_after_commit_does_not_enqueue_again(
        config, running_daemon, monkeypatch, capsys):
    from assistant import cli
    from assistant.ipc import DaemonOutcomeUnknown, DaemonUnavailable
    from assistant.ipc import call as ipc_call
    from assistant.store import Store

    daemon, _server = running_daemon
    original_handler = daemon._queue_enqueue_external
    reply_ready = threading.Event()

    async def commit_then_delay_reply(params):
        result = await original_handler(params)
        await asyncio.sleep(0.3)
        reply_ready.set()
        return result

    monkeypatch.setattr(daemon, "_queue_enqueue_external", commit_then_delay_reply)

    outcomes = []

    def short_deadline_call(socket_path, method, params=None, timeout=10.0):
        try:
            return ipc_call(socket_path, method, params, timeout=0.05)
        except DaemonOutcomeUnknown as exc:
            outcomes.append(exc)
            raise

    monkeypatch.setattr(cli, "call", short_deadline_call)
    args = SimpleNamespace(queue_action="add-external", action_name="download",
                           description="fetch the requested model", status=None,
                           limit=100)

    result = cli._queue_command(args, config)
    assert reply_ready.wait(timeout=2), "delayed daemon reply task did not settle"
    captured = capsys.readouterr()

    store = Store(config.db_path)
    try:
        jobs = store.list_cloud_jobs()
    finally:
        store.close()
    matching = [
        job for job in jobs
        if job["kind"] == "external_action"
        and json.loads(job["payload_json"]).get("action") == "download"
    ]

    assert len(matching) == 1, f"one IPC enqueue produced {len(matching)} durable jobs"
    assert len(outcomes) == 1 and "may have processed" in str(outcomes[0])
    assert not isinstance(outcomes[0], DaemonUnavailable)
    assert result == 1
    assert "not retried locally" in captured.err
