"""Test isolation: every test runs against temp XDG dirs with NO api key.

This is the §12.9 contract made executable: clone the repo anywhere,
`pytest` passes offline. GEMINI_API_KEY is explicitly removed even if
the developer's shell has one, so a green suite can never secretly
depend on the live API.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_MODE", "mock")
    home = tmp_path / "home"
    (home / ".config" / "assistant").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("ASSIST_FIXTURES", str(tmp_path / "fixtures"))
    monkeypatch.delenv("ASSIST_CONFIG", raising=False)
    yield tmp_path
    # sanity: the environment really has no key during the suite
    assert "GEMINI_API_KEY" not in os.environ


@pytest.fixture(autouse=True)
def journal_stream(monkeypatch):
    """Schema lines (§4.8) go to a per-test buffer, never pytest's stdout.

    Keeps `assist` CLI JSON assertions safe from daemon log interleaving and
    hands tests the captured lines directly.
    """
    import io

    from assistant import journal_log

    buffer = io.StringIO()
    journal_log.bind(buffer)
    yield buffer
    journal_log.reset()


@pytest.fixture
def config():
    from assistant.config import load_config

    config = load_config()
    # F17 (owner ruling 2026-11-15): an unnamed capture node is refused on
    # EVERY machine, so a fixture daemon that expects to capture describes a
    # machine whose node is named — exactly like the owner's laptop, where
    # `[capture] mic_target` is the node the doctor reports.
    config.raw.setdefault("capture", {})["mic_target"] = "test-mic"
    return config


def pytest_pyfunc_call(pyfuncitem):
    """Run `async def` test functions via asyncio.run — no plugin dependency.

    The suite needs no runtime models or API key (the default dev group is
    pytest + ruff). Sync tests are untouched; coroutine tests simply await
    inside the loop asyncio.run provides.
    """
    import asyncio
    import inspect

    testfunction = pyfuncitem.obj
    if inspect.iscoroutinefunction(testfunction):
        kwargs = {name: pyfuncitem.funcargs[name]
                  for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(testfunction(**kwargs))
        return True
    return None


@pytest.fixture
def running_daemon(config):
    """Real daemon on a real Unix socket, event loop in a thread."""
    import asyncio
    import threading

    from assistant.daemon import Daemon
    from assistant.ipc import serve

    daemon = Daemon(config)
    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(serve(
        config.socket_path, daemon.handle,
        on_disconnect=daemon._subscribers.discard))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield daemon, server

    async def _shutdown():
        server.close()
        await daemon.aclose()
        await asyncio.wait_for(server.wait_closed(), timeout=3)
        await asyncio.sleep(0)
        current = asyncio.current_task()
        clients = [task for task in asyncio.all_tasks()
                   if task is not current and not task.done()
                   and getattr(task.get_coro(), "__qualname__", "")
                   == "serve.<locals>._client"]
        if clients:
            await asyncio.wait_for(
                asyncio.gather(*clients, return_exceptions=True), timeout=3)

    asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=8)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=3)
    loop.close()
