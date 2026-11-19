"""P · HANDS-HEADLESS — host lifecycle for the headless kitty host.

Build step 3 of P-HEADLESS.md: the host consumes the remote-control config
(``allow_remote_control`` password + the ``<pw> ls get-text send-text`` verb
line), keeps ``shell_integration`` DISABLED, spawns workers in a restricted env
with ``start_new_session``, and ties worker death to the daemon.

Ordering is load-bearing: the instance gate runs and can fail BEFORE any
directory is created; directories are prepared only after the gate passes.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .consent import InMemoryJournal, Journal
from .contract import ALLOWED_VERBS, DEFAULT_EXTENT_SUBSET, WorkerContract
from .instance import (
    DEFAULT_KITTY_PATH,
    DEFAULT_PYTHON_PATH,
    DEFAULT_VERSION_PIN,
    KittyInstance,
)
from .worker import RemoteRequest, Worker

# Keys allowed to survive into the restricted worker environment. Anything else
# (tokens, credentials, home state) is dropped.
ALLOWED_ENV_KEYS = frozenset({"PATH", "LC_ALL", "LANG"})

_DAEMON_POLL_INTERVAL_S = 0.05


class HeadlessConfigError(ValueError):
    """Config fails closed: messages state what was rejected and why."""


@dataclass(frozen=True)
class HeadlessConfig:
    """Remote-control configuration for the headless host (fail-closed)."""

    allow_remote_control: bool
    remote_control_password: str
    allowed_verbs: frozenset[str] = ALLOWED_VERBS
    shell_integration: bool = False
    kitty_path: str = DEFAULT_KITTY_PATH
    python_path: str = DEFAULT_PYTHON_PATH
    kitty_sha256: str | None = None
    python_sha256: str | None = None
    version_pin: str = DEFAULT_VERSION_PIN
    extent_subset: frozenset[str] = DEFAULT_EXTENT_SUBSET
    runtime_dir: str = "~/.local/share/assistant/hands/headless"
    daemon_pid: int | None = None

    def __post_init__(self) -> None:
        if not self.allow_remote_control:
            raise HeadlessConfigError(
                "allow_remote_control is False; the headless host refuses to "
                "start with remote control disabled"
            )
        if not self.remote_control_password:
            raise HeadlessConfigError(
                "remote_control_password is empty; the host fails closed without a password"
            )
        extra = self.allowed_verbs - ALLOWED_VERBS
        if extra:
            raise HeadlessConfigError(
                f"config grants extra verbs {sorted(extra)}; only "
                f"{sorted(ALLOWED_VERBS)} are reachable at the remote-control level"
            )
        missing = ALLOWED_VERBS - self.allowed_verbs
        if missing:
            raise HeadlessConfigError(
                f"config withholds verbs {sorted(missing)}; the worker contract "
                "grants exactly ls/get-text/send-text and nothing else"
            )
        if self.shell_integration:
            raise HeadlessConfigError(
                "shell_integration is enabled; the host requires it DISABLED "
                "and fails closed otherwise"
            )
        widened = self.extent_subset - DEFAULT_EXTENT_SUBSET
        if widened:
            raise HeadlessConfigError(
                f"extent subset {sorted(widened)} widens beyond the assessed "
                f"subset {sorted(DEFAULT_EXTENT_SUBSET)}; widening requires an "
                "owner ruling (coordination ask 50)"
            )


class HeadlessHost:
    """Gate → prepare → contract → worker, with daemon-death tie-in."""

    def __init__(
        self,
        config: HeadlessConfig,
        journal: Journal | None = None,
        instance: KittyInstance | None = None,
        runner=None,
        daemon_alive=None,
    ) -> None:
        self.config = config
        self.journal: Journal = journal or InMemoryJournal()
        self._instance = instance or KittyInstance(
            kitty_path=config.kitty_path,
            python_path=config.python_path,
            kitty_sha256=config.kitty_sha256,
            python_sha256=config.python_sha256,
            version_pin=config.version_pin,
        )
        self._runner = runner
        if daemon_alive is not None:
            self._daemon_alive = daemon_alive
        elif config.daemon_pid is not None:
            pid = config.daemon_pid
            self._daemon_alive = lambda: self._pid_alive(pid)
        else:
            self._daemon_alive = None
        self._stop_event = threading.Event()
        self._watcher: threading.Thread | None = None
        self._runtime_dir: Path | None = None
        self._worker: Worker | None = None

    @property
    def worker(self) -> Worker:
        if self._worker is None:
            raise RuntimeError("host is not started; call start() first")
        return self._worker

    def build_restricted_env(self, base: dict[str, str] | None = None) -> dict[str, str]:
        """Minimal env for workers: only ALLOWED_ENV_KEYS survive."""
        source = os.environ if base is None else base
        restricted = {key: source[key] for key in ALLOWED_ENV_KEYS if key in source}
        restricted.setdefault("PATH", os.defpath)
        restricted["LC_ALL"] = "C"
        return restricted

    def start(self) -> HeadlessHost:
        """Gate first (fails closed before mkdir), then prepare and wire up."""
        check = self._instance.check()  # may raise; nothing created yet
        self._runtime_dir = self._instance.prepare(self.config.runtime_dir)
        contract = WorkerContract(
            verbs=self.config.allowed_verbs,
            extent_subset=self.config.extent_subset,
        )
        self._worker = Worker(
            contract=contract,
            journal=self.journal,
            kitty_path=self.config.kitty_path,
            env=self.build_restricted_env(),
            runner=self._runner,
        )
        self.journal.record(
            "observation",
            kind_detail="host.start",
            kitty_version_pin=check.version_pin,
            kitty_sha256=check.kitty_sha256,
            runtime_dir=str(self._runtime_dir),
        )
        if self.config.daemon_pid is not None:
            self._watcher = threading.Thread(
                target=self._watch_daemon,
                name="headless-daemon-watch",
                daemon=True,
            )
            self._watcher.start()
        return self

    def request(self, request: RemoteRequest):
        """Dispatch one remote-control request through the worker."""
        return self.worker.execute(request)

    def stop(self) -> None:
        """Stop the watcher and send the death signal to worker processes."""
        self._stop_event.set()
        if self._watcher is not None:
            self._watcher.join(timeout=2)
            self._watcher = None
        if self._worker is not None:
            signalled = self._worker.terminate_all()
            self.journal.record(
                "observation", kind_detail="host.stop", processes_signalled=signalled
            )

    def _watch_daemon(self) -> None:
        alive = self._daemon_alive or self._pid_alive
        while not self._stop_event.is_set():
            if not alive():
                self.on_daemon_dead()
                return
            self._stop_event.wait(_DAEMON_POLL_INTERVAL_S)

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def on_daemon_dead(self) -> int:
        """Death-signal tie: terminate worker process groups on daemon death."""
        signalled = self.worker.terminate_all() if self._worker else 0
        self.journal.record(
            "observation", kind_detail="daemon.death", processes_signalled=signalled
        )
        return signalled
