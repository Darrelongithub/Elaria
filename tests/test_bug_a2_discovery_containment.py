"""BUG-A2 · discovery/streaming IPC containment — regression reproductions (P0).

Reproduced defects from `reports/BUGHUNT-A-20261126.md`:

1. The errand `file.inspect` step omitted the `[discovery] roots` containment
   and the `SafetyJournal` untrusted-input note that `file.read` enforces —
   reading arbitrary files (even with no roots configured).
2. The daemon `fs.locate` / `file.inspect` / `file.read` IPC handlers
   consulted neither `[discovery] roots`, nor `_require_ipc_owner()`, nor the
   show-off lockdown — private files outside the demo sandbox were readable
   during an active show-off session, and direct `daemon.handle(...)`
   callers without a socket writer got content back.

The containment is one shared helper (`assistant.containment`), used by every
entry point: owner check (daemon IPC), configured roots only (caller-supplied
roots narrow, never widen), show-off refusal, protected-path rules inside the
readers, and `SafetyJournal` notes where content is returned.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

import pytest

from assistant.embeddings import make_embedder
from assistant.errand import ErrandRunner
from assistant.ipc import call
from assistant.memory import Memory
from assistant.safety_journal import JournalLog
from assistant.store import Store


def _make_runner(config, tmp_path):
    store = Store(config.db_path)
    memory = Memory(store, make_embedder(config))
    journal = JournalLog(tmp_path / "safety_journal.jsonl")
    runner = ErrandRunner(
        config,
        store,
        memory,
        safety_journal=journal,
        is_offline=lambda: True,
    )
    return runner, store, journal


async def _wait_status(store, errand_id, targets, *, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        row = store.get_errand(int(errand_id))
        status = row["status"] if row else None
        last = status
        if status in targets:
            return status
        await asyncio.sleep(0.02)
    raise AssertionError(f"errand #{errand_id} did not reach {targets}; last={last}")


# ---------------------------------------------------------------------------
# Errand step containment (file.inspect)
# ---------------------------------------------------------------------------
def test_bug_a2_errand_file_inspect_refuses_target_outside_roots(config, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "ok.jsonl").write_text('{"ok": true}\n', encoding="utf-8")
    outside = tmp_path / "outside_secret.jsonl"
    outside.write_text('{"secret": "OUTSIDE_SECRET"}\n', encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(allowed)]

    async def _scenario():
        runner, store, journal = _make_runner(config, tmp_path)
        try:
            started = runner.start(
                "inspect the outside file",
                roots=[str(allowed)],
                custom_plan=[{"skill": "file.inspect",
                              "args": {"target": str(outside)}}],
            )
            eid = started["errand_id"]
            await _wait_status(store, eid, {"failed"})
            steps = store.list_errand_steps(eid)
            inspect_step = next(s for s in steps if s["skill"] == "file.inspect")
            assert inspect_step["status"] == "refused"
            assert "outside authorized discovery roots" in str(inspect_step["error"])
            # No skeleton of the outside file was produced…
            report = store.get_errand(eid)
            assert "OUTSIDE_SECRET" not in str(report["report_json"])
            # …and nothing was journaled as seen for the outside target.
            journaled = list(journal.records()) if journal.path.exists() else []
            assert not any(str(outside) in str(r.get("target", ""))
                           for r in journaled)
        finally:
            await runner.aclose()
            store.close()

    asyncio.run(_scenario())


def test_bug_a2_errand_file_inspect_refuses_when_no_roots_configured(config, tmp_path):
    target = tmp_path / "loose.jsonl"
    target.write_text('{"k": "v"}\n', encoding="utf-8")
    config.raw["discovery"]["roots"] = []

    async def _scenario():
        runner, store, _journal = _make_runner(config, tmp_path)
        try:
            started = runner.start(
                "inspect the loose file",
                roots=None,  # nothing configured -> nothing authorized
                custom_plan=[{"skill": "file.inspect",
                              "args": {"target": str(target)}}],
            )
            eid = started["errand_id"]
            await _wait_status(store, eid, {"failed"})
            steps = store.list_errand_steps(eid)
            inspect_step = next(s for s in steps if s["skill"] == "file.inspect")
            assert inspect_step["status"] == "refused"
        finally:
            await runner.aclose()
            store.close()

    asyncio.run(_scenario())


def test_bug_a2_errand_file_inspect_within_roots_journals_untrusted_input(
    config, tmp_path,
):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "ok.jsonl"
    target.write_text('{"a": 1}\n{"a": 2}\n', encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(allowed)]

    async def _scenario():
        runner, store, journal = _make_runner(config, tmp_path)
        try:
            started = runner.start(
                "inspect the allowed file",
                roots=[str(allowed)],
                custom_plan=[{"skill": "file.inspect",
                              "args": {"target": str(target)}}],
            )
            eid = started["errand_id"]
            await _wait_status(store, eid, {"completed"})
            steps = store.list_errand_steps(eid)
            inspect_step = next(s for s in steps if s["skill"] == "file.inspect")
            assert inspect_step["status"] == "ok"
            notes = [r for r in journal.records()
                     if r.get("action") == "untrusted_input.load"]
            assert any(str(target) in str(r.get("target", "")) for r in notes)
            # Provenance only — never the bytes themselves.
            assert not any('"a": 1' in str(r) for r in notes)
        finally:
            await runner.aclose()
            store.close()

    asyncio.run(_scenario())


# ---------------------------------------------------------------------------
# Daemon IPC containment (fs.locate / file.inspect / file.read)
# ---------------------------------------------------------------------------
def test_bug_a2_daemon_file_handlers_refuse_outside_roots_and_journal(
    config, running_daemon, tmp_path,
):
    daemon, _server = running_daemon
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "ok.txt").write_text("allowed-content", encoding="utf-8")
    outside = tmp_path / "outside_private_diary.json"
    outside.write_text('{"diary": "MY_PRIVATE_OWNER_NOTE_OUTSIDE_ROOTS"}',
                       encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(allowed)]

    # Over the real IPC socket as the authenticated local owner:
    with pytest.raises(RuntimeError, match="outside authorized discovery roots"):
        call(config.socket_path, "file.read", {"target": str(outside)}, timeout=5.0)
    with pytest.raises(RuntimeError, match="outside authorized discovery roots"):
        call(config.socket_path, "file.inspect", {"target": str(outside)}, timeout=5.0)
    # fs.locate refuses caller roots that would widen beyond the configured ones:
    with pytest.raises(RuntimeError, match="outside authorized scope"):
        call(config.socket_path, "fs.locate",
             {"terms": ["diary"], "roots": [str(tmp_path)]}, timeout=5.0)

    # Inside the configured roots everything works.
    read_res = call(config.socket_path, "file.read",
                    {"target": str(allowed / "ok.txt")}, timeout=5.0)
    assert "allowed-content" in read_res["text"]
    inspect_res = call(config.socket_path, "file.inspect",
                       {"target": str(allowed / "ok.txt")}, timeout=5.0)
    assert inspect_res["trusted"] is False
    assert inspect_res["digest"]
    # file.inspect returns content-derived structure: it must journal it.
    notes = [r for r in daemon.safety_journal.records()
             if r.get("action") == "untrusted_input.load"]
    assert any(str(allowed / "ok.txt") in str(r.get("target", "")) for r in notes)


def test_bug_a2_daemon_caller_roots_may_only_narrow(config, running_daemon, tmp_path):
    _daemon, _server = running_daemon
    allowed = tmp_path / "allowed"
    (allowed / "sub").mkdir(parents=True)
    (allowed / "sub" / "needle.txt").write_text("needle", encoding="utf-8")
    (allowed / "top.txt").write_text("top", encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(allowed)]

    # Narrowing to a sub-root is allowed and reflected in the payload.
    narrowed = call(config.socket_path, "fs.locate",
                    {"terms": ["needle"], "roots": [str(allowed / "sub")]},
                    timeout=5.0)
    assert narrowed["roots"] == [str(allowed / "sub")]
    # Widening beyond the configured root is refused.
    with pytest.raises(RuntimeError, match="outside authorized scope"):
        call(config.socket_path, "fs.locate",
             {"terms": ["needle"], "roots": [str(tmp_path)]}, timeout=5.0)


def test_bug_a2_daemon_file_handlers_refuse_during_showoff(
    config, running_daemon, tmp_path,
):
    daemon, _server = running_daemon
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "ok.txt"
    target.write_text("allowed-content", encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(allowed)]

    now = daemon.showoff._now()
    daemon.showoff._session = {
        "id": 999,
        "started": now,
        "ends_at": now + timedelta(minutes=5),
        "command": "test-showoff",
    }
    try:
        for method, params in (
            ("fs.locate", {"terms": ["needle"], "roots": [str(allowed)]}),
            ("file.inspect", {"target": str(target)}),
            ("file.read", {"target": str(target)}),
        ):
            with pytest.raises(RuntimeError, match="show-off"):
                call(config.socket_path, method, params, timeout=5.0)
    finally:
        daemon.showoff._session = None


def test_bug_a2_direct_handle_without_writer_is_refused(
    config, running_daemon, tmp_path,
):
    daemon, _server = running_daemon
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    target = allowed / "ok.txt"
    target.write_text("allowed-content", encoding="utf-8")
    config.raw["discovery"]["roots"] = [str(allowed)]

    # No socket writer -> no authenticated principal -> refuse, fail closed.
    async def _scenario():
        for method, params in (
            ("fs.locate", {"terms": ["needle"], "roots": [str(allowed)]}),
            ("file.inspect", {"target": str(target)}),
            ("file.read", {"target": str(target)}),
        ):
            with pytest.raises(PermissionError):
                await daemon.handle(method, params)

    asyncio.run(_scenario())
