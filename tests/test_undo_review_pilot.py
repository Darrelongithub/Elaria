"""Single-op undo review pilot — the consent seam (owner ruling 2026-11-04).

Design: docs/design/2026-11-04-undo-consent-seam.md. Answers in force:
expiry 600 s single-use and lapsed-never-Yes; a No emits exactly one
persona line with no echo of reviewed content; the version column is
deferred, so the binding is (id, status, ts) + both hashes re-read at
apply; CLI parity deferred, so containment is this daemon route only.

Every acceptance clause is pinned here, clause by clause:
  1 Yes is offered only on a pre-verified scope;
  2 apply refuses TOTALLY on any drift;
  3 No is terminal, and edits stale the ask;
  4 expiry lapses, never Yes;
  5 bare undo stays byte-identical at the guard;
  6 cli.py's direct fallback is untouched (containment statement);
  7 the written containment statement lives in the phase report.
[TESTED-ONLY] — real Executor moves on real files; no hardware claim.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextvars import ContextVar
from pathlib import Path

import pytest

from assistant.config import load_config
from assistant.daemon import Daemon
from assistant.executor import Executor
from assistant.ipc import IpcPrincipal
from assistant.organiser import OrganiserService
from assistant.store import Store

TAXONOMY = ["Finance", "Photos", "_Unsorted", "_Conflicts"]


# --------------------------------------------------------------- fixtures
def _seed(tmp_path):
    """One real applied plan -> real committed operations -> real files."""
    config = load_config()
    root = tmp_path / "docs"
    root.mkdir()
    (root / "Finance").mkdir()
    old = time.time() - 86400 * 3      # clear the recently-modified guard
    for name, data in (("invoice-march.txt", b"invoice due"),
                       ("holiday-photo.jpg", b"jpeg-ish")):
        path = root / name
        path.write_bytes(data)
        os.utime(path, (old, old))
    config.raw["organise"] = {**config.raw["organise"],
                              "roots": [{"path": str(root), "mode": "live",
                                         "taxonomy": TAXONOMY}]}
    config.raw["policy"] = {**config.raw["policy"],
                            "recently_modified_guard_minutes": 15}
    store = Store(tmp_path / "pilot.db")
    organiser = OrganiserService(config, store)
    executor = Executor(config, store)
    plan = organiser.build_plan(config.organise_roots()[0])
    executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                        allow_tripwire=True)
    ops = store.committed_operations(plan_id=plan["plan_id"])
    assert len(ops) >= 2, "fixture needs a multi-op plan for the pilot pins"
    return config, store, executor, ops


def _daemon(store, executor, *, ttl=None):
    """The real seam methods on a stub carrying only what they touch."""
    daemon = object.__new__(Daemon)
    daemon.store = store
    daemon.executor = executor
    daemon._undo_asks = {}
    if ttl is not None:
        daemon.UNDO_ASK_TTL_S = ttl
    principal = IpcPrincipal(pid=os.getpid(), uid=os.getuid(), gid=os.getgid())
    var: ContextVar = ContextVar("pilot_principal", default=None)
    var.set(principal)
    daemon._ipc_principal = var
    return daemon


def _prepare(daemon, **params):
    return asyncio.run(daemon._undo_prepare(params))


def _apply(daemon, **params):
    return asyncio.run(daemon._undo_apply(params))


class _RecordingExecutor:
    def __init__(self):
        self.calls = []

    def undo(self, **kwargs):
        self.calls.append(kwargs)
        return {"undone": 1, "problems": [], "note": "recorded"}


# ------------------------------------------- clause 1: pre-verified only
def test_prepare_refuses_without_a_scope(tmp_path):
    _cfg, store, executor, _ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    try:
        with pytest.raises(ValueError, match="needs a scope"):
            _prepare(daemon)
    finally:
        store.close()


def test_prepare_refuses_when_nothing_is_undoable(tmp_path):
    _cfg, store, executor, _ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    try:
        with pytest.raises(ValueError, match="nothing undoable"):
            _prepare(daemon, op_id=999_999)
    finally:
        store.close()


def test_prepare_refuses_a_multi_operation_scope(tmp_path):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    try:
        with pytest.raises(ValueError) as excinfo:
            _prepare(daemon, plan_id=ops[0]["plan_id"])
        message = str(excinfo.value)
        assert "one operation at a time" in message
        assert f"resolves to {len(ops)}" in message
        assert daemon._undo_asks == {}, "a refused scope issues no token"
    finally:
        store.close()


def test_prepare_refuses_when_the_source_is_gone(tmp_path, journal_stream):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    op = ops[0]
    Path(op["dst"]).unlink()
    try:
        with pytest.raises(ValueError, match="no longer exists"):
            _prepare(daemon, op_id=op["id"])
        assert daemon._undo_asks == {}, "no ask is raised on a dead scope"
    finally:
        store.close()


def test_prepare_refuses_when_content_changed_since_the_operation(tmp_path):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    op = ops[0]
    Path(op["dst"]).write_bytes(b"the owner edited this")
    try:
        with pytest.raises(ValueError, match="changed since the operation"):
            _prepare(daemon, op_id=op["id"])
        assert daemon._undo_asks == {}
    finally:
        store.close()


def test_prepare_binds_the_snapshot_and_writes_nothing(tmp_path):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    op = ops[0]
    before = store.get_operation(op["id"])
    try:
        ask = _prepare(daemon, op_id=op["id"])
        snapshot = ask["snapshot"]
        assert snapshot["op_id"] == op["id"]
        for field in ("plan_id", "ts", "op", "src", "dst", "sha256_before",
                      "sha256_after", "status"):
            assert snapshot[field] == before[field]
        assert len(ask["ask_sha256"]) == 64
        assert ask["expires_in_s"] == 600.0, "answer 1: 600 s"
        assert ask["age_s"] == 0.0
        assert Path(op["dst"]).exists(), "prepare moves nothing"
        assert store.get_operation(op["id"])["status"] == before["status"]
    finally:
        store.close()


# ------------------------------------- clause 2/3/4: apply's four verdicts
# NOTE: schema verdicts render as BARE tokens in the line — assert
# membership in line.split(), never "verdict=x". (Recorded lesson, re-hit.)
def test_yes_executes_exactly_one_operation(tmp_path, journal_stream):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    op = ops[0]
    try:
        ask = _prepare(daemon, op_id=op["id"])
        result = _apply(daemon, token=ask["token"], decision="yes")
        assert result["undone"] == 1
        assert Path(op["src"]).exists(), "the file went back"
        assert not Path(op["dst"]).exists()
        assert store.get_operation(op["id"])["status"] != "committed"
        journal = journal_stream.getvalue()
        assert "undo.apply" in journal and "approved" in journal.split()
        assert f"uid={os.getuid()}" in journal, "actor is derived, not claimed"
    finally:
        store.close()


def test_no_is_terminal_and_emits_one_plain_persona_line(tmp_path,
                                                         journal_stream):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    op = ops[0]
    try:
        ask = _prepare(daemon, op_id=op["id"])
        result = _apply(daemon, token=ask["token"], decision="no")
        assert result["undone"] == 0
        assert Path(op["dst"]).exists(), "a No moves nothing"

        rows = store._conn.execute(
            "SELECT kind, detail FROM persona_events").fetchall()
        assert len(rows) == 1, "exactly one persona line for a No"
        assert rows[0]["kind"] == "ack"
        detail = json.loads(rows[0]["detail"])
        assert detail["ack"] == "declined"
        assert "ask_sha256" in detail
        blob = json.dumps(detail)
        assert op["src"] not in blob and op["dst"] not in blob, \
            "no echo of the reviewed content"

        with pytest.raises(ValueError, match="already answered"):
            _apply(daemon, token=ask["token"], decision="no")
        assert "declined" in journal_stream.getvalue().split()
    finally:
        store.close()


def test_expired_ask_lapses_and_never_executes(tmp_path, journal_stream):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor, ttl=0.0)
    op = ops[0]
    try:
        ask = _prepare(daemon, op_id=op["id"])
        with pytest.raises(ValueError, match="lapsed"):
            _apply(daemon, token=ask["token"], decision="yes")
        assert Path(op["dst"]).exists(), "a lapsed ask does nothing"
        assert daemon._undo_asks == {}, "lapse is terminal"
        journal = journal_stream.getvalue()
        assert "lapsed" in journal.split()
        assert "never a Yes" in journal
        with pytest.raises(ValueError, match="unknown undo ask"):
            _apply(daemon, token=ask["token"], decision="yes")
    finally:
        store.close()


def test_apply_refuses_totally_on_filesystem_drift(tmp_path, journal_stream):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    op = ops[0]
    try:
        ask = _prepare(daemon, op_id=op["id"])
        Path(op["dst"]).write_bytes(b"edited between ask and answer")
        with pytest.raises(ValueError) as excinfo:
            _apply(daemon, token=ask["token"], decision="yes")
        assert "nothing was undone" in str(excinfo.value)
        assert Path(op["dst"]).exists()
        assert daemon._undo_asks[ask["token"]]["used"] is True, \
            "drift is terminal: the ask cannot be retried"
        assert "drifted" in journal_stream.getvalue().split()
    finally:
        store.close()


def test_apply_refuses_on_row_drift(tmp_path, journal_stream):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    op = ops[0]
    try:
        ask = _prepare(daemon, op_id=op["id"])
        store._conn.execute("UPDATE operations SET status='failed' WHERE id=?",
                            (op["id"],))
        store._conn.commit()
        with pytest.raises(ValueError, match="status changed"):
            _apply(daemon, token=ask["token"], decision="yes")
        assert Path(op["dst"]).exists()
    finally:
        store.close()


@pytest.mark.parametrize("params,message", [
    ({"token": "nope", "decision": "yes"}, "unknown undo ask"),
    ({"token": "", "decision": "no"}, "unknown undo ask"),
])
def test_unknown_tokens_are_refused(tmp_path, params, message):
    _cfg, store, executor, _ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    try:
        with pytest.raises(ValueError, match=message):
            _apply(daemon, **params)
    finally:
        store.close()


def test_decision_must_be_yes_or_no(tmp_path):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    try:
        ask = _prepare(daemon, op_id=ops[0]["id"])
        with pytest.raises(ValueError, match="decision 'yes' or 'no'"):
            _apply(daemon, token=ask["token"], decision="maybe")
        assert Path(ops[0]["dst"]).exists()
    finally:
        store.close()


def test_single_use_token_is_consumed_before_execution(tmp_path):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    op = ops[0]
    try:
        ask = _prepare(daemon, op_id=op["id"])
        _apply(daemon, token=ask["token"], decision="yes")
        with pytest.raises(ValueError, match="already answered"):
            _apply(daemon, token=ask["token"], decision="yes")
    finally:
        store.close()


def test_prepare_purges_expired_asks(tmp_path):
    _cfg, store, executor, ops = _seed(tmp_path)
    daemon = _daemon(store, executor, ttl=0.0)
    try:
        first = _prepare(daemon, op_id=ops[0]["id"])
        assert first["token"] in daemon._undo_asks
        _prepare(daemon, op_id=ops[1]["id"])
        assert first["token"] not in daemon._undo_asks
    finally:
        store.close()


# ------------------------------- clause 5/6: what must NOT have changed
def test_bare_undo_stays_byte_identical(tmp_path):
    _cfg, store, executor, _ops = _seed(tmp_path)
    daemon = _daemon(store, executor)
    try:
        with pytest.raises(ValueError) as excinfo:
            asyncio.run(daemon._undo({}))
        assert str(excinfo.value) == (
            "undo requires an explicit scope (op_id, plan_id, or since_iso)")
        with pytest.raises(ValueError, match="scoped undo is refused"):
            asyncio.run(daemon._undo({"op_id": 1}))
    finally:
        store.close()


def test_cli_direct_fallback_is_untouched():
    """The containment statement, pinned: cli.py's DaemonUnavailable branch
    still calls Executor.undo itself and never reaches the seam."""
    cli = (Path(__file__).resolve().parents[1] /
           "src" / "assistant" / "cli.py").read_text()
    block = cli.split('if args.command == "undo":', 1)[1].split(
        "if args.command", 1)[0]
    assert "except DaemonUnavailable" in block
    assert "Executor(config, store).undo(" in block
    assert "undo.prepare" not in block and "undo.apply" not in block
