"""P · HANDS-HEADLESS — remote-control worker enforcing the worker contract.

Build step 2/3 of P-HEADLESS.md: the worker turns a validated
``RemoteRequest`` into a kitty remote-control invocation. Only the three
contract verbs reach execution; everything else is refused before any
subprocess is spawned.

Execution goes through an injectable runner (default: ``subprocess.Popen``
with ``start_new_session=True`` and a restricted env supplied by the host).
BUG-B3 (2026-11-26): a runner MUST report every process to the ``on_spawn``
hook the instant ``Popen`` returns, i.e. *before* it blocks waiting for that
process. That is what makes an in-flight worker visible to
``terminate_all()`` when the daemon dies mid-command. Processes tracked this
way are pruned when their run finishes, so no finished ``Popen`` object is
retained for the host's lifetime (I10), and ``terminate_all()`` only ever
signals a process whose own object still proves liveness (``poll() is None``)
— never a bare PID that may have been reaped and recycled.

Output of ``get-text`` is untrusted input (IF-6): it is returned as an
observation for the planner, never re-executed as a command.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

from .consent import ConsentFlow, Journal
from .contract import WorkerContract

#: Called by a runner the instant a process exists, before any wait.
SpawnHook = Callable[[object], None]

#: ``(argv, env, start_new_session, on_spawn) -> result``. The runner must
#: invoke ``on_spawn(proc)`` immediately after spawning; it must NOT wait for
#: the child to exit first (BUG-B3).
Runner = Callable[[list[str], dict[str, str], bool, SpawnHook], SimpleNamespace]

_RUN_TIMEOUT_S = 60


@dataclass(frozen=True)
class RemoteRequest:
    """One remote-control request: verb, assessed options, optional payload."""

    verb: str
    options: dict[str, str] = field(default_factory=dict)
    payload: str = ""


def default_runner(
    argv: list[str],
    env: dict[str, str],
    start_new_session: bool,
    on_spawn: SpawnHook,
):
    """Run ``argv`` in a fresh session with the given env; track at spawn."""
    proc = subprocess.Popen(
        argv,
        env=env,
        start_new_session=start_new_session,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # BUG-B3: report the process NOW, while it is alive. Registering it when
    # this function returns would leave every in-flight command invisible to
    # terminate_all() for up to the timeout below.
    on_spawn(proc)
    try:
        stdout, stderr = proc.communicate(timeout=_RUN_TIMEOUT_S)
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


class ProcessTracker:
    """Spawn-time registry of live worker processes.

    Registration happens at spawn, forgetting happens when the run ends, so
    the registry holds exactly the processes that may still be running — never
    a finished ``Popen`` (I10: cleanup returns to baseline).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: list[object] = []

    def track(self, proc: object) -> None:
        with self._lock:
            self._live.append(proc)

    def forget(self, proc: object) -> None:
        with self._lock:
            self._live = [tracked for tracked in self._live if tracked is not proc]

    def snapshot(self) -> list[object]:
        with self._lock:
            return list(self._live)

    def __len__(self) -> int:
        with self._lock:
            return len(self._live)


def _proven_live(proc: object) -> bool:
    """True only when ``proc`` itself says it is still running.

    A process object without a callable ``poll`` — or one whose ``poll()``
    raises — has proven nothing, so it must never be signalled: its ``pid``
    may already be reaped and recycled (BUG-B3, PID-reuse hazard).
    """
    poll = getattr(proc, "poll", None)
    if not callable(poll):
        return False
    try:
        return poll() is None
    except (OSError, ValueError):
        return False


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
        self._tracker = ProcessTracker()

    def build_argv(self, request: RemoteRequest) -> list[str]:
        """Validate the request against the contract and shape the argv."""
        self.contract.check_request(request.verb, request.options)
        argv = [self.kitty_path, "+rc", request.verb]
        if request.verb == "get-text":
            argv += ["--extent", request.options["extent"]]
        elif request.verb == "send-text":
            argv += ["--text", request.payload]
        return argv

    def live_processes(self) -> list[object]:
        """Snapshot of the processes tracked as possibly still running."""
        return self._tracker.snapshot()

    def execute(self, request: RemoteRequest):
        """Run one request through the consent flow; journal act+observation."""
        argv = self.build_argv(request)  # contract gate first
        action = {"verb": request.verb, "argv": argv}

        def operate():
            spawned: list[object] = []

            def on_spawn(proc: object) -> None:
                spawned.append(proc)
                self._tracker.track(proc)  # visible to terminate_all mid-run

            try:
                return self._runner(argv, self.env, True, on_spawn)
            finally:
                # The run is over (success, timeout or error): nothing here is
                # ours to signal any more, and retaining it would leak (I10).
                for proc in spawned:
                    self._tracker.forget(proc)

        def observe(result):
            return {
                "returncode": getattr(result, "returncode", None),
                "stdout_bytes": len(getattr(result, "stdout", "") or ""),
                "stderr_bytes": len(getattr(result, "stderr", "") or ""),
            }

        return self._consent.perform(action, operate, observe=observe)

    def terminate_all(self) -> int:
        """Send SIGTERM to every tracked process group (death signal).

        Returns the number of process groups signalled. Only processes whose
        own object still reports ``poll() is None`` are signalled — a tracked
        process that has already exited (or that never proved liveness) is
        pruned and skipped, so a reaped/recycled PID is never signalled
        (BUG-B3). A signalled process is forgotten immediately: it has had its
        death signal, and reusing that PID object for a second ``killpg`` could
        hit a recycled process group. Missing process groups are ignored —
        they are already gone, which is the desired end state.
        """
        signalled = 0
        for proc in self._tracker.snapshot():
            if not _proven_live(proc):
                self._tracker.forget(proc)
                continue
            pid = getattr(proc, "pid", None)
            if pid is None:
                self._tracker.forget(proc)
                continue
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
                signalled += 1
            except (ProcessLookupError, PermissionError):
                pass
            finally:
                self._tracker.forget(proc)
        return signalled
