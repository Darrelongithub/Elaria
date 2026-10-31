"""Standalone synthetic IPC preflight, not a Qt/laptop rendering claim."""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path

import pytest

from assistant import ipc
from assistant.hands.bridge import BridgeApp, BridgeServer
from assistant.hands.sandbox import SyntheticSpace
from assistant.safety import sha256_file

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui/quickshell/hands"


class Caller:
    def __init__(self, app):
        self.app = app
        self.i = 0

    def params(self, **kw):
        self.i += 1
        return {"epoch": self.app.epoch, "nonce": f"test-{self.i}", **kw}

    def call(self, method, **kw):
        return self.app.dispatch("hands." + method, self.params(**kw))

    def parked(self, fixture="composite"):
        self.call("posture", posture="normal")
        self.call("intent", text="Arrange a synthetic fixture", fixture=fixture)
        return self.call("run", planHash=self.app.plan.digest)


async def rpc(path, method="hands.snapshot", params=None, **top):
    reader, writer = await asyncio.open_unix_connection(str(path))
    try:
        writer.write(json.dumps({"id": 1, "method": method, "params": params or {}, **top}).encode() + b"\n")
        await writer.drain()
        return json.loads(await asyncio.wait_for(reader.readline(), timeout=5))
    finally:
        writer.close()
        await writer.wait_closed()


def rows(app):
    return [line.split(" ", 6) for line in app.log_path.read_text().splitlines()]


@pytest.mark.parametrize("mode,choice", [
    ("typed", "yes"), ("typed", "no"), ("button", "yes"), ("button", "no"),
    ("postures", "yes"), ("lost-reply", "yes"), ("lost-reply", "no"), ("trap", "yes"),
])
def test_actual_shipped_js_over_real_unix_socket(mode, choice, monkeypatch):
    node = shutil.which("node")
    assert node, "preflight requires Node; do not silently count a skipped bridge"
    original = ipc._write_reply
    lost = []

    async def drop_ack(writer, reply):
        phase = reply.get("result", {}).get("phase")
        if mode == "lost-reply" and phase in {"complete", "ended"} and not lost:
            lost.append(reply["id"])
            writer.close()
            return
        await original(writer, reply)

    monkeypatch.setattr(ipc, "_write_reply", drop_ack)

    async def run():
        with BridgeApp() as app:
            async with BridgeServer(app) as server:
                assert stat.S_IMODE(server.path.stat().st_mode) == 0o600
                proc = await asyncio.create_subprocess_exec(
                    node, str(ROOT / "tests/support/hands_bridge_driver.js"), str(UI),
                    str(server.path), mode, choice, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE)
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
                except BaseException:
                    proc.kill()
                    await proc.wait()
                    raise
                assert proc.returncode == 0, stderr.decode()
                evidence = json.loads(stdout)
                assert len(lost) == (1 if mode == "lost-reply" else 0)
                trace = rows(app)
                assert all(len(r) in {6, 7} and r[4] == "-" for r in trace)
                assert "Arrange the synthetic fixture" not in app.log_path.read_text()
                if mode == "trap":
                    assert any(r[2:6:3] == ["hands.inject", "inject"] for r in trace)
                    assert any(r[2] == "hands.step" and r[5] == "refused" for r in trace)
                    assert not app.runner.calls
                    assert not app.space.store.committed_operations()
                    trap = app.space.work / Path(app.plan.steps[0].argv[0]).parent / "trap.txt"
                    assert sha256_file(trap) == sha256_file(ROOT / "fixtures/hands/traps/document.txt")
                else:
                    a, b = app.plan.steps
                    assert not (app.space.work / a.argv[0]).exists()
                    assert (app.space.work / a.argv[1]).read_text() == "synthetic note 0\n"
                    assert (app.space.work / b.argv[1]).read_text() == "preserve this synthetic occupied target\n"
                    if choice == "yes":
                        assert not (app.space.work / b.argv[0]).exists()
                        assert (app.space.work / b.argv[-1]).read_text() == "synthetic note 1\n"
                    else:
                        assert (app.space.work / b.argv[0]).read_text() == "synthetic note 1\n"
                        assert not (app.space.work / b.argv[-1]).exists()
                    decisions = [r[5] for r in trace if r[2] == "hands.decision" and r[5] != "stale"]
                    assert decisions == [choice]
                assert evidence["methods"].count("hands.intent") == (1 if mode == "trap" else 2)
            assert not server.peers and not server.path.exists()
    asyncio.run(run())


@pytest.mark.parametrize("posture,visible", [
    ("normal", True), ("company", True), ("class", True), ("locked", False),
    ("unknown", False), ("unsupported", False), (None, False), ([], False),
])
def test_server_r8_redaction_preserves_aged_ask_and_refuses_hidden_decisions(posture, visible):
    with BridgeApp() as app:
        caller = Caller(app)
        ask = caller.parked()["ask"]
        with app.queue._db:
            app.queue._db.execute("UPDATE asks SET created=created-31536000")
        snap = caller.call("posture", posture=posture)
        assert (snap["ask"] is not None) == visible
        assert snap["notification"] == ("elaria needs a yes" if posture == "normal" else None)
        assert snap["askAgeSeconds"] >= 31536000
        assert app.queue.pending()[0]["id"] == ask["id"]
        if not visible:
            wire = json.dumps(snap)
            for private in (ask["planHash"], ask["disclosure"], str(app.space.work), "fixture-"):
                assert private not in wire
            assert not snap["lines"] and not snap["events"] and not snap["plan"]
            caller.call("decision", askId=ask["id"], planHash=ask["planHash"], decision="yes")
            caller.call("intent", text="synthetic only", fixture="composite")
            caller.call("run", planHash=ask["planHash"])
            assert len(app.runner.calls) == 1
            assert app.queue.pending()[0]["id"] == ask["id"]
        caller.call("posture", posture="normal")
        done = caller.call("decision", askId=ask["id"], planHash=ask["planHash"], decision="yes")
        assert done["phase"] == "complete" and len(app.runner.calls) == 2


def test_receipts_never_replay_or_return_old_private_snapshot():
    with BridgeApp() as app:
        caller = Caller(app)
        ask = caller.parked()["ask"]
        p = caller.params(askId=ask["id"], planHash=ask["planHash"], decision="yes")
        app.dispatch("hands.decision", p)
        assert len(app.runner.calls) == 2
        caller.call("posture", posture="locked")
        duplicate = app.dispatch("hands.decision", p)
        assert duplicate["ask"] is None and duplicate["plan"] == []
        assert duplicate["posture"] == "locked"
        conflict = app.dispatch("hands.decision", {**p, "decision": "no"})
        assert conflict["plan"] == []
        assert len(app.runner.calls) == 2
        assert len(app.space.store.committed_operations()) == 2
        caller.call("posture", posture="normal")
        assert "different data" in app.dispatch("hands.decision", {**p, "decision": "no"})["notice"]


def test_started_receipt_and_budget_fail_closed_without_eviction():
    from assistant.indexer import sha256_bytes

    with BridgeApp() as app:
        c = Caller(app)
        ask = c.parked()["ask"]
        p = c.params(askId=ask["id"], planHash=ask["planHash"], decision="yes")
        digest = sha256_bytes(json.dumps(["hands.decision", p], sort_keys=True, separators=(",", ":")).encode())
        assert app.storage.begin(app.epoch, p["nonce"], digest) == "new"
        s = app.dispatch("hands.decision", p)
        assert "uncertain" in s["notice"] and len(app.runner.calls) == 1
        app.storage.LIMIT = 0
        assert "budget" in c.call("decision", askId=ask["id"], planHash=ask["planHash"], decision="yes")["notice"]
        assert len(app.runner.calls) == 1


def test_reopen_same_minted_lab_requires_explicit_posture_and_never_runs_on_connect():
    with SyntheticSpace() as space:
        with BridgeApp(space) as first:
            c = Caller(first)
            ask = c.parked()["ask"]
            old_epoch = first.epoch
            stale = c.params(askId=ask["id"], planHash=ask["planHash"], decision="yes")
        with BridgeApp(space) as second:
            assert second.epoch != old_epoch
            assert second.snapshot()["ask"] is None
            assert second.queue.pending()[0]["id"] == ask["id"]
            assert not second.runner.calls
            c = Caller(second)
            s = c.call("posture", posture="normal")
            assert s["ask"]["planHash"] == ask["planHash"]
            second.dispatch("hands.decision", stale)
            assert not second.runner.calls
            c.call("decision", askId=ask["id"], planHash=ask["planHash"], decision="yes")
            assert [call[0] for call in second.runner.calls] == [1]
            assert len(space.store.committed_operations()) == 2


def test_reopen_interrupted_claim_does_not_infer_completion_or_retry():
    with SyntheticSpace() as space:
        with BridgeApp(space) as first:
            c = Caller(first)
            ask = c.parked()["ask"]
            first.queue.decide(ask["id"], ask["planHash"], "yes")
            assert first.queue.claim(first.state["errand"], first.plan, 1, needs_yes=True)
            first.state["phase"] = "running"
            first.storage.save(first.state)
        with BridgeApp(space) as second:
            c = Caller(second)
            c.call("posture", posture="normal")
            s = c.call("run", planHash=second.plan.digest)
            assert s["phase"] == "unknown" and not second.runner.calls
            assert second.queue.step_state(second.state["errand"], second.plan, 1) == "unknown"
            assert len(space.store.committed_operations()) == 1


def test_only_one_app_owns_a_minted_lab():
    with (SyntheticSpace() as space, BridgeApp(space),
          pytest.raises(RuntimeError, match="lock held")):
        BridgeApp(space)


@pytest.mark.parametrize("bad", [Path("/tmp"), object(), "synthetic"])
def test_caller_cannot_supply_arbitrary_tree(bad):
    with pytest.raises(TypeError, match="minted synthetic"):
        BridgeApp(bad)


@pytest.mark.parametrize("decision", ["yes", "no"])
def test_wrong_ask_and_old_plan_cannot_authorize_or_decline(decision):
    with BridgeApp() as app:
        c = Caller(app)
        ask = c.parked()["ask"]
        c.call("decision", askId=ask["id"] + 1, planHash=ask["planHash"], decision=decision)
        c.call("decision", askId=ask["id"], planHash="0" * 64, decision=decision)
        assert app.queue.pending()[0]["id"] == ask["id"]
        assert len(app.runner.calls) == 1


def test_cancel_records_intent_and_boundary_actual_and_cannot_revive():
    with BridgeApp() as app:
        c = Caller(app)
        ask = c.parked()["ask"]
        s = c.call("cancel")
        assert s["phase"] == "ended" and s["ask"] is None
        c.call("decision", askId=ask["id"], planHash=ask["planHash"], decision="yes")
        assert len(app.runner.calls) == 1
        assert [r[5] for r in rows(app) if r[2] == "hands.cancel"] == ["cancel-intent", "cancelled"]


def test_planner_spacing_parks_without_spin_or_fixture_writes():
    now = [100.0]
    with BridgeApp(clock=lambda: now[0]) as app:
        c = Caller(app)
        c.parked()
        c.call("cancel")
        before = sorted(app.space.work.rglob("*"))
        s = c.call("intent", text="A new synthetic errand", fixture="composite")
        assert s["phase"] == "planning-parked" and "next eligible" in s["notice"]
        assert sorted(app.space.work.rglob("*")) == before
        assert app.queue._db.execute("SELECT count(*) FROM model_calls").fetchone()[0] == 1
        now[0] += 12.01
        assert c.call("intent", text="A new synthetic errand", fixture="composite")["phase"] == "ready"
        assert app.queue._db.execute("SELECT count(*) FROM model_calls").fetchone()[0] == 2


@pytest.mark.parametrize("text", ["yes", " NO ", " YEſ "])
def test_bare_confirmation_never_becomes_owner_intent_without_focused_ask(text):
    with BridgeApp() as app:
        c = Caller(app)
        c.call("posture", posture="normal")
        assert c.call("intent", text=text, fixture="composite")["notice"] == "no ask is selected"
        assert not app.plan and not app.runner.calls


@pytest.mark.parametrize("method,extra", [
    ("hands.run", {"plan": {}}), ("hands.intent", {"text": "data", "fixture": "../../real"}),
    ("hands.decision", {"askId": True, "planHash": "0" * 64, "decision": "yes"}),
    ("hands.decision", {"askId": 1, "planHash": "0" * 64, "decision": []}),
    ("hands.run", {"planHash": []}), ("hands.intent", {"text": "", "fixture": "composite"}),
    ("hands.intent", {"text": "data", "fixture": "composite", "root": "/real"}),
    ("hands.posture", {"posture": "normal", "uid": os.getuid()}),
    ("exec", {"argv": ["bash", "-c", "exit"]}),
])
def test_malformed_or_ambient_authority_requests_are_refused_without_side_effects(method, extra):
    async def run():
        with BridgeApp() as app:
            c = Caller(app)
            async with BridgeServer(app) as server:
                reply = await rpc(server.path, method, c.params(**extra))
                assert reply["ok"] is False
                assert "synthetic bridge refused" in reply["error"]
                assert not app.plan and not app.runner.calls and app.state["phase"] == "idle"
    asyncio.run(run())


def test_kernel_peer_identity_not_claimed_uid_authorizes_ipc():
    async def run():
        with BridgeApp() as app:
            async with BridgeServer(app) as server:
                assert (await rpc(server.path))["ok"] is True
                server.owner_uid = os.getuid() + 1
                denied = await rpc(server.path, uid=server.owner_uid, authenticated=True)
                assert denied["ok"] is False and "not the local owner" in denied["error"]
                assert app.posture == "unknown"
    asyncio.run(run())


@pytest.mark.parametrize("kind", ["file", "directory", "symlink", "dangling-symlink"])
def test_bridge_never_unlinks_non_socket_endpoint(tmp_path, kind):
    endpoint = tmp_path / "endpoint"
    if kind == "file":
        endpoint.write_text("keep synthetic bytes")
    elif kind == "directory":
        endpoint.mkdir()
    else:
        target = tmp_path / "target"
        if kind == "symlink":
            target.write_text("keep synthetic bytes")
        endpoint.symlink_to(target)

    async def run():
        with BridgeApp() as app, pytest.raises(PermissionError, match="non-socket"):
            await BridgeServer(app, endpoint).start()
    asyncio.run(run())
    assert endpoint.exists() or endpoint.is_symlink()


def test_idle_peers_are_closed_and_endpoint_can_be_rebound():
    async def run():
        with BridgeApp() as app:
            server = await BridgeServer(app).start()
            reader, writer = await asyncio.open_unix_connection(str(server.path))
            assert (await rpc(server.path))["ok"]
            with pytest.raises(RuntimeError, match="already running"):
                await BridgeServer(app, server.path).start()
            await server.close()
            assert await asyncio.wait_for(reader.read(), 1) == b""
            writer.close()
            await writer.wait_closed()
            assert not server.peers and not server.path.exists()
            async with BridgeServer(app, server.path):
                assert (await rpc(server.path))["ok"]
    asyncio.run(run())


def test_bridge_effect_surface_has_no_network_task_process_or_notification(monkeypatch):
    real_popen = subprocess.Popen
    observed = []

    def read_only_git(args, *a, **kw):
        observed.append(args)
        assert isinstance(args, list) and Path(args[0]).name == "git"
        assert not kw.get("shell")
        return real_popen(args, *a, **kw)

    class UnixOnly(socket.socket):
        def __init__(self, family=socket.AF_INET, *args, **kwargs):
            assert family == socket.AF_UNIX, "no service network traffic authorized"
            super().__init__(family, *args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", read_only_git)
    monkeypatch.setattr(socket, "socket", UnixOnly)

    async def run():
        with BridgeApp() as app:
            c = Caller(app)
            async with BridgeServer(app) as server:
                await rpc(server.path, "hands.posture", c.params(posture="normal"))
                await rpc(server.path, "hands.intent", c.params(
                    text="notify-send 'private'; bash -c 'exit'; https://invalid.example", fixture="composite"))
                assert app.plan is not None
                s = (await rpc(server.path, "hands.run", c.params(planHash=app.plan.digest)))["result"]
                ask = s["ask"]
                s = (await rpc(server.path, "hands.decision", c.params(
                    askId=ask["id"], planHash=ask["planHash"], decision="yes")))["result"]
                assert s["phase"] == "complete"
                assert s["metrics"]["desktopNotifications"] == 0
                assert "invalid.example" not in app.log_path.read_text()
    asyncio.run(run())
    assert all(Path(command[0]).name == "git" for command in observed)


def js(expression):
    code = (UI / "harness.js").read_text() + (UI / "bridge.js").read_text()
    result = subprocess.run([shutil.which("node"), "-e", code +
                             "\nconsole.log(JSON.stringify(" + expression + "));"],
                            capture_output=True, text=True, timeout=5, check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize("line", ["not json", "null", "[]", '{"id":1,"ok":false}', "x" * 262145])
def test_controller_rejects_invalid_frames_without_private_content(line):
    # The oversized case uses construction in Node rather than an oversized argv.
    literal = "'x'.repeat(262145)" if len(line) > 262144 else json.dumps(line)
    result = js("(function(){var c=createController('test');c.connect(0);"
                f"c.receive({literal});c.tick(5000);"
                "return [c.snapshot.ask,c.snapshot.plan,c.connected,c.pending];})()")
    assert result == [None, [], False, None]


def test_controller_timeout_and_reconnect_emit_only_snapshot_not_saved_mutation():
    result = js("""(function(){var c=createController('test');c.connect(0);
        c.receive(JSON.stringify({id:1,ok:true,result:{synthetic:true,epoch:'a'.repeat(32),
            posture:'normal',locked:false,plan:[],lines:[],ask:null}}));
        var sent=c.request('hands.intent',{text:'synthetic',fixture:'composite'},1);
        var blocked=c.request('hands.intent',{text:'duplicate',fixture:'composite'},2);
        c.tick(5001);var warning=c.notice;var reconnect=JSON.parse(c.connect(6000));
        var late=c.receive(JSON.stringify({id:2,ok:true,result:{synthetic:true}}));
        return [!!sent,blocked,warning,reconnect.method,reconnect.params,late,c.snapshot.ask];})()""")
    assert result[:2] == [True, None]
    assert "outcome unknown" in result[2]
    assert result[3:] == ["hands.snapshot", {}, False, None]


def test_receipt_budget_cannot_prevent_privacy_suppression():
    with BridgeApp() as app:
        c = Caller(app)
        c.parked()
        app.storage.LIMIT = 0
        s = c.call("posture", posture="locked")
        assert s["locked"] and s["ask"] is None and s["plan"] == []
        assert len(app.queue.pending()) == 1


def test_second_gate_refuses_changed_facts_even_after_bound_yes():
    with BridgeApp() as app:
        c = Caller(app)
        ask = c.parked()["ask"]
        destination = app.space.work / app.plan.steps[1].argv[-1]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("synthetic late occupant")
        s = c.call("decision", askId=ask["id"], planHash=ask["planHash"], decision="yes")
        assert s["phase"] == "ended" and s["notice"] == "refused"
        assert len(app.runner.calls) == 1 and len(app.space.store.committed_operations()) == 1
        assert destination.read_text() == "synthetic late occupant"
        assert any(r[2] == "hands.gate" and r[5] == "refused" for r in rows(app))


@pytest.mark.parametrize("choice", ["yes", "no"])
def test_reopened_terminal_version_cannot_run_again(choice):
    with SyntheticSpace() as space:
        with BridgeApp(space) as first:
            c = Caller(first)
            ask = c.parked()["ask"]
            c.call("decision", askId=ask["id"], planHash=ask["planHash"], decision=choice)
        with BridgeApp(space) as second:
            c = Caller(second)
            c.call("posture", posture="normal")
            c.call("run", planHash=ask["planHash"])
            c.call("decision", askId=ask["id"], planHash=ask["planHash"], decision="yes")
            assert not second.runner.calls and not second.snapshot()["ask"]
            assert len(space.store.committed_operations()) == (2 if choice == "yes" else 1)


def test_failed_constructor_releases_lab_lease(monkeypatch):
    from assistant.hands.bridge_state import BridgeState

    original = BridgeState.load
    with SyntheticSpace() as space:
        def broken_load(self):
            raise ValueError("synthetic corrupt state")

        monkeypatch.setattr(BridgeState, "load", broken_load)
        with pytest.raises(ValueError, match="synthetic corrupt"):
            BridgeApp(space)
        monkeypatch.setattr(BridgeState, "load", original)
        with BridgeApp(space) as app:
            assert app.state["phase"] == "idle"


def test_close_preserves_replacement_non_socket_file():
    async def run():
        with BridgeApp() as app:
            server = await BridgeServer(app).start()
            server.path.unlink()
            server.path.write_text("synthetic replacement; do not unlink")
            await server.close()
            assert server.path.read_text() == "synthetic replacement; do not unlink"
    asyncio.run(run())


def test_controller_keeps_unknown_outcome_across_repeated_disconnect_and_new_epoch():
    result = js("""(function(){var c=createController('test');c.connect(0);
        function snap(epoch) {return {synthetic:true,epoch:epoch.repeat(32),posture:'normal',
            locked:false,plan:[],lines:[],ask:null,notice:'fresh lab'};}
        c.receive(JSON.stringify({id:1,ok:true,result:snap('a')}));
        c.request('hands.intent',{text:'synthetic',fixture:'composite'},1);
        c.disconnect('transport error');c.disconnect('transport disconnected');
        var first=c.notice;var req=JSON.parse(c.connect(2));
        c.receive(JSON.stringify({id:req.id,ok:true,result:snap('b')}));
        var next=c.notice;req=JSON.parse(c.refresh(3));
        c.receive(JSON.stringify({id:req.id,ok:true,result:snap('b')}));
        return [first,next,c.notice,c.pending,c.snapshot.ask];})()""")
    assert all("outcome" in notice and "unknown" in notice for notice in result[:3])
    assert result[3:] == [None, None]


def test_real_cli_lifecycle_is_ephemeral_and_old_epoch_cannot_approve_new_lab(tmp_path):
    import sys

    async def launch(endpoint):
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "assistant.hands.bridge", "--socket", str(endpoint),
            env={"PATH": os.environ["PATH"], "PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path)},
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            line = await asyncio.wait_for(proc.stdout.readline(), 5)
            assert b"Synthetic hands bridge ready" in line
        except BaseException:
            proc.kill()
            await proc.wait()
            raise
        return proc

    async def run():
        endpoint = tmp_path / "bridge.sock"
        proc = await launch(endpoint)
        try:
            s = (await rpc(endpoint))["result"]
            epoch = s["epoch"]
            await rpc(endpoint, "hands.posture", {"epoch": epoch, "nonce": "cli-1", "posture": "normal"})
            s = (await rpc(endpoint, "hands.intent", {"epoch": epoch, "nonce": "cli-2",
                "text": "Synthetic folder only", "fixture": "composite"}))["result"]
            root = Path(s["plan"][0]["cwd"]).parent
            assert root.name.startswith("elaria-hands-synthetic-") and root.exists()
            s = (await rpc(endpoint, "hands.run", {"epoch": epoch, "nonce": "cli-3",
                                                   "planHash": s["planHash"]}))["result"]
            ask = s["ask"]
            assert s["metrics"]["operationRows"] == 1
        finally:
            proc.terminate()
            _, stderr = await asyncio.wait_for(proc.communicate(), 10)
        assert proc.returncode == 0, stderr.decode()
        assert not root.exists() and not endpoint.exists()
        proc = await launch(endpoint)
        try:
            s = (await rpc(endpoint, "hands.decision", {"epoch": epoch, "nonce": "cli-4",
                "askId": ask["id"], "planHash": ask["planHash"], "decision": "yes"}))["result"]
            assert s["epoch"] != epoch and s["phase"] == "idle" and s["posture"] == "unknown"
            assert s["metrics"]["operationRows"] == s["metrics"]["runnerInvocations"] == 0
        finally:
            proc.terminate()
            _, stderr = await asyncio.wait_for(proc.communicate(), 10)
        assert proc.returncode == 0, stderr.decode()
    asyncio.run(run())
