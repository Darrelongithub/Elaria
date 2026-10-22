"""BUG A [I9] class (ADOPT-2): every IPC handler must resolve to a real bound
method and be callable BY NAME through the real handlers dict.

The external hotword submission shipped `self._hotword_stop` (an asyncio.Event)
shadowing a `_hotword_stop` (method): `hotword.stop` resolved to a non-callable
and died with TypeError at dispatch, and no test caught it. This file is the
net: any instance attribute that shadows a handler method, or any handler that
is not callable, fails CI. Every handler is then invoked by name over the real
Unix socket — a dead entry point (the bug class that hid `assist meeting setup`'s
ImportError behind 1,280 passing tests) fails here instead.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from assistant.ipc import DaemonUnavailable, call


def _handler_names(daemon) -> list[str]:
    return sorted(daemon._handlers())


# ---------------------------------------------------------------------------
# 1. Resolution: no attribute/method collision can exist
# ---------------------------------------------------------------------------
def test_every_ipc_handler_resolves_to_a_bound_method(running_daemon):
    daemon, _server = running_daemon
    handlers = daemon._handlers()
    assert len(handlers) > 40, "the dispatch table looks truncated"
    instance_attrs = set(vars(daemon))
    for name, handler in handlers.items():
        assert callable(handler), (
            f"handler {name!r} resolved to {handler!r} — an instance attribute "
            "is shadowing its method (BUG A collision class)")
        assert inspect.ismethod(handler), (
            f"handler {name!r} is not a bound method: {handler!r}")
        assert handler.__self__ is daemon, (
            f"handler {name!r} is bound to {handler.__self__!r}, not the daemon")
        method_name = handler.__name__
        assert method_name not in instance_attrs, (
            f"instance attribute {method_name!r} shadows the handler method "
            "of the same name — dispatch would resolve to the attribute")


def test_handlers_dict_matches_every_async_handler_method(running_daemon):
    """I9: a method that looks like a handler but is missing from the dict (or
    vice versa) is the same bug class one step removed."""
    daemon, _server = running_daemon
    handlers = daemon._handlers()
    bound = {h.__name__ for h in handlers.values()}
    for name, attr in inspect.getmembers(daemon, predicate=inspect.ismethod):
        if not name.startswith("_") or name.startswith("__"):
            continue
        if not inspect.iscoroutinefunction(attr):
            continue
        params = inspect.signature(attr).parameters
        if list(params) != ["params"]:
            continue
        assert name in bound, (
            f"{name} is an async one-param handler-like method but is not in "
            "the dispatch table — either register it or it is dead code")


# ---------------------------------------------------------------------------
# 2. Invocation: every handler answers by name (empty params must not crash
#    with TypeError/'not callable'; domain errors are fine)
# ---------------------------------------------------------------------------
def test_every_ipc_handler_answers_by_name(config, running_daemon):
    daemon, _server = running_daemon
    for name in _handler_names(daemon):
        try:
            out = call(config.socket_path, name, {}, timeout=20.0)
            assert isinstance(out, dict), f"{name} returned {type(out)}"
        except TypeError as exc:  # the exact BUG A failure mode
            pytest.fail(f"handler {name} raised TypeError: {exc}")
        except Exception as exc:
            text = str(exc)
            assert "not callable" not in text, (
                f"handler {name} is not callable at dispatch: {text}")
            # Domain failures (missing params, bad state) are legitimate
            # answers from a live entry point; anything else is a dead one.
            assert isinstance(exc, (ValueError, KeyError, RuntimeError,
                                    OSError, DaemonUnavailable, asyncio.TimeoutError)), (
                f"handler {name} died with {type(exc).__name__}: {text}")
        # The mode-switch / halt surfaces must leave the daemon usable: a
        # blanket smoke must not depend on iteration order.
        call(config.socket_path, "resume", timeout=5.0)


def test_unknown_method_names_the_supported_set(config, running_daemon):
    _daemon, _server = running_daemon
    with pytest.raises(RuntimeError, match="supported"):
        call(config.socket_path, "definitely.not.a.method", {}, timeout=5.0)
