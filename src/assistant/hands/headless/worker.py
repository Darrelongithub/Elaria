"""P · HANDS-HEADLESS — remote-control worker enforcing the worker contract.

Build step 2/3 of P-HEADLESS.md: the worker turns a validated
``RemoteRequest`` into a kitty remote-control invocation. Only the three
contract verbs reach execution; everything else is refused before any
subprocess is spawned.

Execution goes through an injectable runner (default: ``subprocess.Popen``
with ``start_new_session=True`` and a restricted env supplied by the host).
Spawned processes are tracked so the host can send the death signal to their
process groups when the daemon dies.

Output of ``get-text`` is untrusted input (IF-6): it is returned as an
observation for the planner, never re-executed as a command.
"""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

from .consent import ConsentFlow, Journal
from .contract import WorkerContract

Runner = Callable[[list[str], dict[str, str], bool], SimpleNamespace]


@dataclass(frozen=True)
class RemoteRequest:
    """One remote-control request: verb, assessed options, optional payload."""

    verb: str
    options: dict[str, str] = field(default_factory=dict)
    payload: str = ""


def default_runner(argv: list[str], env: dict[str, str], start_new_session: bool):
    """Run ``argv`` in a fresh session with the given env; track the process."""
    proc = subprocess.Popen(
        argv,
        env=env,
        start_new_session=start_new_session,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        raise RuntimeError(f"remote-control call timed out: {' '.join(argv)}")
    return SimpleNamespace(
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        process=proc,
    )


class Worker:
    """Enforces the worker contract over the three remote-control verbs."""

    def __init__(
        self,
        contract: WorkerContract,
        journal: Journal,
        kitty_path: str,
        env: dict[str, str] | None = None,
        runner: Runner | None = None,
        consent_flow: ConsentFlow | None = None,
    ) -> None:
        self.contract = contract
        self.journal = journal
        self.kitty_path = kitty_path
        self.env = env if env is not None else {"PATH": os.environ.get("PATH", "")}
        self._runner: Runner = runner or default_runner
        self._consent = consent_flow or ConsentFlow(journal)
        self._live: list[object] = []

    def build_argv(self, request: RemoteRequest) -> list[str]:
        """Validate the request against the contract and shape the argv."""
        self.contract.check_request(request.verb, request.options)
        argv = [self.kitty_path, "+rc", request.verb]
        if request.verb == "get-text":
            argv += ["--extent", request.options["extent"]]
        elif request.verb == "send-text":
            argv += ["--text", request.payload]
        return argv

    def execute(self, request: RemoteRequest):
        """Run one request through the consent flow; journal act+observation."""
        argv = self.build_argv(request)  # contract gate first
        action = {"verb": request.verb, "argv": argv}

        def operate():
            result = self._runner(argv, self.env, True)
            proc = getattr(result, "process", None)
            if proc is not None:
                self._live.append(proc)
            return result

        def observe(result):
            return {
                "returncode": getattr(result, "returncode", None),
                "stdout_bytes": len(getattr(result, "stdout", "") or ""),
                "stderr_bytes": len(getattr(result, "stderr", "") or ""),
            }

        return self._consent.perform(action, operate, observe=observe)

    def terminate_all(self) -> int:
        """Send SIGTERM to every tracked process group (death signal).

        Returns the number of process groups signalled. Missing processes are
        ignored — they are already gone, which is the desired end state.
        """
        signalled = 0
        for proc in list(self._live):
            pid = getattr(proc, "pid", None)
            if pid is None:
                continue
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                signalled += 1
            except (ProcessLookupError, PermissionError):
                pass
        self._live.clear()
        return signalled
