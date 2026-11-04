"""Scoped-undo fail-closed guard (owner ruling 2026-11-04).

"make her hands work": scoped undo fails closed at the canonical daemon
entry until the single-op undo review pilot exists (consent matrix
c327df7, §5). This is a narrow order-scoped grant on daemon.py — 8
added lines, the kitty mount's footprint ceiling — and nothing else.

What is pinned here:
- every scope (since / op_id / plan_id) is refused BEFORE any executor
  call, so no file can move on a refusal;
- the refusal is a plain-language ValueError — the same idiom bare undo
  already uses, surfacing as a structured {"ok": false} over IPC;
- bare undo is untouched: the executor's own refusal ("undo requires an
  explicit scope") still fires, byte-for-byte;
- the typed-intent route and the language aliases in intents.py land on
  the same guard (they all resolve to the daemon entry);
- containment boundary: cli.py's direct fallback (DaemonUnavailable →
  Executor(...).undo) does NOT pass through this guard — console/daemon
  route containment only, as the ruling states.
[TESTED-ONLY]
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from assistant import intents
from assistant.config import load_config
from assistant.daemon import Daemon
from assistant.executor import Executor
from assistant.store import Store

REFUSAL = re.compile(r"scoped undo is refused until the review pilot exists")


class _RecordingExecutor:
    """Stands in for the real executor: any call is a mutation attempt."""

    def __init__(self):
        self.calls: list[dict] = []

    def undo(self, **kwargs):
        self.calls.append(kwargs)
        return {"undone": 1, "problems": [], "note": "MUTATED"}


def _entry(executor):
    """The real Daemon._undo bound to a stub carrying only `executor`."""
    daemon = object.__new__(Daemon)
    daemon.executor = executor
    return daemon, daemon._undo


# --------------------------------------------------- scoped undo refuses
@pytest.mark.parametrize("params", [
    {"since": "2026-11-03"},
    {"since": "24h"},
    {"op_id": 7},
    {"plan_id": 3},
    {"op_id": 7, "since": "24h"},
])
def test_scoped_undo_is_refused_before_any_mutation(params):
    executor = _RecordingExecutor()
    _daemon, undo = _entry(executor)
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(undo(params))
    assert REFUSAL.search(str(excinfo.value)), str(excinfo.value)
    assert executor.calls == [], "a refusal must never reach the executor"


def test_the_refusal_says_nothing_moved_and_is_plain_language():
    executor = _RecordingExecutor()
    _daemon, undo = _entry(executor)
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(undo({"op_id": 1}))
    message = str(excinfo.value)
    assert "nothing undone" in message and "no file moved" in message
    assert "review pilot" in message
    assert message == message.strip()


# ------------------------------------------------ bare undo is preserved
def _real_executor(tmp_path):
    config = load_config()
    config.raw.setdefault("store", {})["db_path"] = str(tmp_path / "guard.db")
    store = Store(Path(config.db_path))
    return Executor(config, store), store


def test_bare_undo_keeps_the_executors_own_refusal(tmp_path):
    """Preserved exactly: no scope means the executor's message, unchanged
    — the guard must not intercept or reword it."""
    executor, store = _real_executor(tmp_path)
    try:
        _daemon, undo = _entry(executor)
        with pytest.raises(ValueError) as excinfo:
            asyncio.run(undo({}))
        assert str(excinfo.value) == (
            "undo requires an explicit scope (op_id, plan_id, or since_iso)")
    finally:
        store.close()


def test_empty_since_string_is_still_the_bare_path(tmp_path):
    """`{"since": ""}` is falsy at the entry — it stays on the scopeless
    path (executor refusal), not the guard's."""
    executor, store = _real_executor(tmp_path)
    try:
        _daemon, undo = _entry(executor)
        with pytest.raises(ValueError) as excinfo:
            asyncio.run(undo({"since": ""}))
        assert "requires an explicit scope" in str(excinfo.value)
    finally:
        store.close()


# ------------------------------------- the two routes that share the entry
def test_typed_intent_scoped_undo_is_refused():
    intent = intents.route("undo since yesterday")
    assert intent is not None and intent.kind == "undo"
    executor = _RecordingExecutor()
    daemon, _undo = _entry(executor)
    # _run_intent's call shape for a scoped undo (daemon.py:3630)
    params = {"since": intent.argument} if intent.argument else {}
    with pytest.raises(ValueError) as excinfo:
        asyncio.run(daemon._undo(params))
    assert REFUSAL.search(str(excinfo.value))
    assert executor.calls == []


@pytest.mark.parametrize("phrase", [
    "undo", "undo since 24h", "rudisha tangu jana", "tenda upya tangu jana",
])
def test_language_aliases_resolve_to_the_guarded_entry(phrase):
    """intents.py carries English and Swahili aliases; all resolve to kind
    'undo', so the daemon entry covers them structurally."""
    intent = intents.route(phrase)
    assert intent is not None and intent.kind == "undo"
    executor = _RecordingExecutor()
    daemon, _undo = _entry(executor)
    params = {"since": intent.argument} if intent.argument else {}
    if params:
        with pytest.raises(ValueError) as excinfo:
            asyncio.run(daemon._undo(params))
        assert REFUSAL.search(str(excinfo.value))
    assert executor.calls == []
