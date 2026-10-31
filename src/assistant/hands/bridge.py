"""Standalone synthetic GUI/queue bridge. Unix IPC only; no desktop dispatch.

Every task runner is fake; only minted synthetic trees can mutate through the
existing library. A plan is disclosed in a separate response before Run. No
caller may supply a plan, root, executable, principal, or real posture source.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
import stat
import time
from contextlib import ExitStack
from pathlib import Path

from assistant.config import runtime_dir
from assistant.indexer import sha256_bytes
from assistant.ipc import _acquire_daemon_lock, _release_daemon_lock, ipc_peer_principal, serve

from .bridge_state import BridgeState
from .core import SandboxCore
from .injection import DataInput
from .plan import Plan, Step
from .planner import MockPlanner, OwnerIntent
from .queue import ParkedQueue
from .runner import FakeRunner
from .sandbox import SyntheticSpace
from .sink import ThinSink

POSTURES = frozenset({"normal", "company", "class", "locked", "unknown"})
METHOD_FIELDS = {
    "hands.posture": {"posture"},
    "hands.intent": {"text", "fixture"},
    "hands.run": {"planHash"},
    "hands.decision": {"askId", "planHash", "decision"},
    "hands.cancel": set(),
}


class BridgeApp:
    """One bounded synthetic lab; no general-purpose request-to-command adapter."""

    def __init__(self, space: SyntheticSpace | None = None, *, clock=time.monotonic):
        if space is not None and type(space) is not SyntheticSpace:
            raise TypeError("only minted synthetic state is permitted")
        self.owns_space = space is None
        self.space = space or SyntheticSpace()
        self._resources = ExitStack()
        if self.owns_space:
            self._resources.callback(self.space.close)
        try:
            self._lease = _acquire_daemon_lock(self.space.control / "bridge-app")
            self._resources.callback(_release_daemon_lock, self._lease)
            self.queue = ParkedQueue(self.space)
            self._resources.callback(self.queue.close)
            self.storage = BridgeState(self.queue)
            self._resources.callback(self.storage.close)
            self.state = self.storage.load()
            self.clock = clock
            self.epoch = secrets.token_hex(16)
            self.posture = "unknown"  # reopening never infers an unlocked session
            self.notice = "Synthetic session connected. Select an explicit mock posture."
            self.log_path = self.space.control / "hands.log"
            fd = os.open(self.log_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
            self.log = os.fdopen(fd, "a", encoding="utf-8")
            self._resources.callback(self.log.close)
            self.sink = ThinSink(self.log)
            self.runner = FakeRunner(self.space)
            self.core = SandboxCore(self.space, self.queue, self.runner, self.sink)
            self.plan = self.queue.load(self.state["errand"]) if self.state["errand"] else None
            if self.state["phase"] in {"running", "preparing"}:
                self.queue.recover_interrupted()
                self.state["phase"] = "unknown"
                self.storage.save(self.state)
            self.closed = False
        except BaseException:
            self._resources.close()
            raise

    def _pending(self):
        if self.state["errand"] and self.queue.cancelled(self.state["errand"]):
            return []
        return [a for a in self.queue.pending() if a["errand"] == self.state["errand"]]

    def snapshot(self) -> dict:
        visible = self.posture in {"normal", "company", "class"}
        pending = self._pending()
        ask = None
        age = max(0, int(time.time() - pending[0]["created"])) if pending else None
        if visible and pending and self.plan is not None:
            a = pending[0]
            s = self.plan.steps[a["step"]]
            disclosure = s.disclosure()
            ask = {"id": a["id"], "planHash": a["plan_hash"], "state": a["state"],
                   "kind": a["kind"], "ageSeconds": age, "paths": list(s.argv),
                   "disclosure": f"Tool: {s.tool}\nArgv: {disclosure['argv']}\nCwd: {s.cwd}\n"
                                 + "Env diff: " + json.dumps(disclosure["env_diff"], ensure_ascii=False),
                   "warning": "Exact hash-bound synthetic decision. Informed consent is not sandboxing."}
        operations = self.space.store.committed_operations()
        event_lines = []
        if visible:
            for line in self.log_path.read_text(encoding="utf-8").splitlines()[-12:]:
                fields = line.split(" ", 6)
                if len(fields) >= 6 and fields[3] == self.state["errand"]:
                    event_lines.append(fields[2] + " · " + fields[5])
        return {
            "synthetic": True, "connected": True, "epoch": self.epoch,
            "posture": self.posture, "locked": not visible, "phase": self.state["phase"],
            "heading": self.state["phase"] if visible else "the private console is hidden",
            "notice": self.notice if visible else "private content hidden; pending asks are retained",
            "lines": self.core.reporter.lines[-30:] if visible else [], "events": event_lines,
            "plan": ([{"i": s.i, "tier": s.tier, "tool": s.tool, **s.disclosure()}
                      for s in self.plan.steps] if visible and self.plan else []),
            "planHash": self.plan.digest if visible and self.plan else None,
            "ask": ask, "askAgeSeconds": age,
            "notification": "elaria needs a yes" if pending and self.posture == "normal" else None,
            "metrics": {"operationRows": len(operations), "runnerInvocations": len(self.runner.calls),
                        "telemetryWritten": self.sink.written, "telemetryDropped": self.sink.dropped,
                        "liveModelCalls": 0, "taskProcessSpawns": 0, "desktopNotifications": 0},
        }

    def _prepare(self, text: str, fixture: str):
        if self.state["phase"] in {"ready", "parked", "running", "unknown"}:
            self.notice = "Finish or cancel the current synthetic errand first."
            return
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError("invalid synthetic intent")
        if text.strip().casefold() in {"yes", "no"}:
            self.notice = "no ask is selected"  # never turn a confirmation into a new intent
            return
        if fixture not in {"composite", "trap"}:
            raise ValueError("invalid synthetic fixture")
        errand = secrets.token_hex(6)
        prefix = f"fixture-{errand}"
        plan = Plan((
            Step(0, 1, "move", (f"{prefix}/note0.txt", f"{prefix}/filed/note0.txt"), str(self.space.work)),
            Step(1, 2, "resolve_collision", (f"{prefix}/note1.txt", f"{prefix}/filed/note1.txt",
                 f"{prefix}/_Conflicts/note1.txt"), str(self.space.work)),
        ))
        result = MockPlanner(self.queue, [plan.canonical], sink=self.sink).advance(
            OwnerIntent(text), day="synthetic-lab", now=self.clock(), cap=32)
        if result.status != "planned":
            self.state.update(phase="planning-parked", errand=None)
            self.plan = None
            self.storage.save(self.state)
            self.notice = ("Synthetic planning parked: " + result.reason
                           + (f"; next eligible {result.next_eligible:.2f}" if result.next_eligible else ""))
            return
        self.state.update(phase="preparing", errand=None, fixture=fixture)
        self.storage.save(self.state)
        for i in range(8):
            self.space.seed(f"{prefix}/note{i}.txt", f"synthetic note {i}\n")
        self.space.seed(f"{prefix}/filed/note1.txt", "preserve this synthetic occupied target\n")
        if fixture == "trap":
            # Fixed repository fixture, never a caller-supplied file path.
            fixture_path = Path(__file__).resolve().parents[3] / "fixtures/hands/traps/document.txt"
            self.space.seed(f"{prefix}/trap.txt", fixture_path.read_text(encoding="utf-8"))
        # This interface only produces the fixed synthetic fixture plan. Still
        # validate paths before disclosure; never accept a plan from the caller.
        for s in plan.steps:
            if self.core.gate.derive(s, self.core.facts(s, "plan")) != s.tier:
                raise ValueError("fixture plan refused")
        self.queue.register(errand, plan)
        self.plan = plan
        self.core.reporter.lines.clear()
        self.state.update(phase="ready", errand=errand)
        self.storage.save(self.state)
        self.notice = "Synthetic fixture plan disclosed. Nothing executed; explicitly start after reading it."

    def _run(self):
        self.state["phase"] = "running"
        self.storage.save(self.state)
        data = ()
        if self.state["fixture"] == "trap":
            trap = self.space.work / Path(self.plan.steps[0].argv[0]).parent / "trap.txt"
            data = (DataInput("file", trap.read_text(encoding="utf-8")),)
        status = self.core.run(self.plan, errand=self.state["errand"], data=data)
        self.state["phase"] = "parked" if status == "parked" else (
            "complete" if status == "verified complete" else "ended")
        self.storage.save(self.state)
        self.notice = status

    def _decide(self, params):
        if (type(params["askId"]) is not int or params["decision"] not in {"yes", "no"}
                or not isinstance(params["planHash"], str)):
            raise ValueError("invalid decision")
        pending = self._pending()
        if (self.plan is None or not pending or pending[0]["id"] != params["askId"]
                or pending[0]["plan_hash"] != params["planHash"]):
            self.core.errand = self.state["errand"] or "-"
            self.core.emit("decision", "stale", hashes=[params["planHash"]])
            self.core.emit("ask", "stale", hashes=[params["planHash"]])
            self.notice = "stale decision; refreshed the current ask without replay"
            return
        self.core.errand = self.state["errand"]
        result = self.core.decision(params["askId"], params["planHash"], params["decision"])
        if result == "stale":
            self.notice = "stale decision; refreshed the current ask without replay"
        elif pending[0]["kind"] == "replan":
            self.state["phase"] = "ended"
            self.storage.save(self.state)
            self.notice = "Re-plan decision recorded. No existing step was authorized."
        elif self.state["phase"] != "unknown":
            self._run()
        else:
            self.notice = "Decision recorded; uncertain execution remains stopped for inspection."

    def dispatch(self, method: str, params: dict) -> dict:
        """Called only after server-side kernel peer verification."""
        if method == "hands.snapshot":
            if params:
                raise ValueError("snapshot takes no authority fields")
            return self.snapshot()
        if method not in METHOD_FIELDS or set(params) != METHOD_FIELDS[method] | {"epoch", "nonce"}:
            raise ValueError("unsupported bridge request shape")
        if method == "hands.intent" and (
            not isinstance(params["text"], str) or not params["text"].strip()
            or len(params["text"]) > 4096 or not isinstance(params["fixture"], str)
            or params["fixture"] not in {"composite", "trap"}
        ):
            raise ValueError("invalid synthetic intent")
        if method in {"hands.run", "hands.decision"} and (
            not isinstance(params["planHash"], str) or len(params["planHash"]) != 64
            or any(c not in "0123456789abcdef" for c in params["planHash"])
        ):
            raise ValueError("invalid plan identity")
        if method == "hands.decision" and (
            type(params["askId"]) is not int or params["askId"] < 1
            or not isinstance(params["decision"], str) or params["decision"] not in {"yes", "no"}
        ):
            raise ValueError("invalid decision")
        if params["epoch"] != self.epoch:
            self.notice = "bridge session changed; refresh before deciding"
            return self.snapshot()
        nonce = params["nonce"]
        if (not isinstance(nonce, str) or not 1 <= len(nonce) <= 80
                or any(c not in "0123456789abcdefghijklmnopqrstuvwxyz-" for c in nonce)):
            raise ValueError("invalid request identity")
        digest = sha256_bytes(json.dumps([method, params], sort_keys=True,
                                        separators=(",", ":")).encode())
        receipt = self.storage.begin(self.epoch, nonce, digest)
        if receipt != "new":
            if receipt == "full" and method == "hands.posture":
                self.posture = "unknown"  # a budget must never prevent privacy suppression
            self.notice = {"done": "request already recorded; not replayed",
                           "started": "request outcome uncertain; refreshed without replay",
                           "conflict": "request identity reused with different data; refused",
                           "full": "synthetic request budget reached; close this lab deliberately"}[receipt]
            return self.snapshot()
        try:
            if method == "hands.posture":
                value = params["posture"]
                self.posture = value if isinstance(value, str) and value in POSTURES else "unknown"
                self.notice = "Synthetic posture updated; no desktop notification dispatched."
            elif self.posture not in {"normal", "company", "class"}:
                self.notice = "private surface unavailable; decision not accepted"
            elif method == "hands.intent":
                self._prepare(params["text"], params["fixture"])
            elif method == "hands.run":
                if self.plan and self.state["phase"] == "ready" and params["planHash"] == self.plan.digest:
                    self._run()
                else:
                    self.notice = "stale start; refresh the disclosed plan"
            elif method == "hands.decision":
                self._decide(params)
            elif method == "hands.cancel":
                if self.state["errand"]:
                    self.core.errand = self.state["errand"]
                    self.core.cancel()
                    self.core.emit("cancel", "cancelled")
                    self.state["phase"] = "ended"
                    self.storage.save(self.state)
                self.notice = "cancel requested; no action automatically restarted"
            self.storage.finish(self.epoch, nonce)
        except Exception:
            # Persist uncertain rather than retrying a potentially applied action.
            self.state["phase"] = "unknown"
            self.storage.save(self.state)
            self.notice = "synthetic request failed; outcome requires inspection, not replay"
        return self.snapshot()

    def close(self):
        if not self.closed:
            self.closed = True
            self._resources.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class BridgeServer:
    """Reuses the existing IPC server; owns only its endpoint and connections."""

    def __init__(self, app: BridgeApp, path: Path | None = None):
        self.app = app
        self.path = path or app.space.control / "elaria-hands.sock"
        self.server = None
        self.peers = {}
        self.owner_uid = os.getuid()
        self._identity = None
        self.closing = False
        self._serial = asyncio.Lock()

    def _connected(self, writer):
        self.peers[writer] = asyncio.current_task()

    def _disconnected(self, writer):
        self.peers.pop(writer, None)

    async def handle(self, method, params, writer):
        principal = ipc_peer_principal(writer)
        if principal.uid != self.owner_uid:
            raise PermissionError("bridge peer is not the local owner")
        async with self._serial:
            if self.closing:
                raise PermissionError("bridge is shutting down")
            try:
                return self.app.dispatch(method, params)
            except Exception:
                self.app.posture = "unknown"
                # Shared IPC otherwise includes exception strings in responses.
                raise ValueError("synthetic bridge refused this request") from None

    async def start(self):
        if self.path.is_symlink() or (self.path.exists() and not stat.S_ISSOCK(self.path.stat().st_mode)):
            raise PermissionError("refusing a non-socket bridge endpoint")
        self.server = await serve(self.path, self.handle, event_sink=self._connected,
                                  on_disconnect=self._disconnected)
        endpoint = self.path.lstat()
        self._identity = (endpoint.st_dev, endpoint.st_ino)
        self.closing = False
        return self

    async def close(self):
        if self.server is None:
            return
        self.closing = True
        # Unlink while serve's endpoint lock is still held. There is no await
        # between unlink and close/release; a rebind cannot lose its new socket.
        try:
            endpoint = self.path.lstat()
        except FileNotFoundError:
            endpoint = None
        if (endpoint and stat.S_ISSOCK(endpoint.st_mode)
                and (endpoint.st_dev, endpoint.st_ino) == self._identity):
            self.path.unlink()
        self.server.close()
        tasks = list(self.peers.values())
        for writer in list(self.peers):
            writer.close()
        if tasks:
            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=6)
        await asyncio.wait_for(self.server.wait_closed(), timeout=6)
        self.server = None

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *args):
        await self.close()


async def _serve_cli(path: Path):
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stopped.set)
    try:
        with BridgeApp() as app:
            async with BridgeServer(app, path):
                print("Synthetic hands bridge ready; no live runners or notifications.", flush=True)
                await stopped.wait()
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main():
    parser = argparse.ArgumentParser(description="Standalone synthetic-only hands bridge (no real task runner)")
    parser.add_argument("--socket", type=Path, default=runtime_dir() / "elaria-hands.sock")
    args = parser.parse_args()
    asyncio.run(_serve_cli(args.socket))


if __name__ == "__main__":
    main()
