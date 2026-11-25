"""Drive sync backends for the alive host.

The system of record for cross-host movement is the owner's own sync folder
(``drive:elaria-sync/`` per the design). Two backends implement the same
small surface; tests use the fixture exclusively.

* ``FixtureSyncBackend`` — a local directory standing in for the remote.
  Labelled fixture everywhere (``name == "local-path-fixture"``); its output
  can never be reported as a real Drive sync.
* ``RcloneSyncBackend`` — the real thing. It speaks a MINIMAL pinned verb
  surface (``version``, ``lsjson --hash``, ``copyto``, ``cat``), self-contained
  here because the alive host does not share a filesystem with the laptop's
  ``src/assistant/remote.py``. The laptop-side copyto/cat pins are requested
  from cluster T to fold into ``RCLONE_COMMAND_SURFACE``; until that lands,
  this table is the pin, it is exhaustive, and anything not in it raises.

Nothing here contacts a network in tests, and nothing here runs unless the
owner provisioned a real remote. The laptop side has the mirror image of
this file in ``assistant/alive_sync.py`` — the two share only
``alive.envelope`` (the format), never code paths.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

FIXTURE_BACKEND_NAME = "local-path-fixture"

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}\.json$|^LATEST$")


class SyncError(RuntimeError):
    pass


class SyncRemoteUnreachable(SyncError):
    pass


def _check_name(prefix: str, name: str) -> None:
    if prefix.strip("/") != prefix or "/" in prefix or not prefix:
        raise SyncError(f"bad prefix {prefix!r}")
    if not _SAFE_NAME.match(name):
        raise SyncError(f"bad object name {name!r}")


class FixtureSyncBackend:
    """Local directory as a stand-in remote. Test fixture. Never a remote."""

    name = FIXTURE_BACKEND_NAME
    is_fixture = True

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, prefix: str, name: str, data: bytes) -> None:
        _check_name(prefix, name)
        target = self.root / prefix
        target.mkdir(parents=True, exist_ok=True)
        dest = target / name
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)

    def get(self, prefix: str, name: str) -> bytes:
        _check_name(prefix, name)
        path = self.root / prefix / name
        try:
            return path.read_bytes()
        except OSError as exc:
            raise SyncError(f"fixture get failed for {prefix}/{name}: {exc}") from exc

    def list(self, prefix: str) -> list[str]:
        _check_name(prefix, "LATEST")  # validates prefix only
        path = self.root / prefix
        if not path.is_dir():
            return []
        return sorted(p.name for p in path.iterdir()
                      if p.is_file() and _SAFE_NAME.match(p.name))

    def delete(self, prefix: str, name: str) -> bool:
        _check_name(prefix, name)
        path = self.root / prefix / name
        if path.exists():
            path.unlink()
            return True
        return False

    def describe(self) -> dict:
        return {"backend": self.name, "kind": "fixture", "root": str(self.root)}


# -- real backend: minimal pinned surface --------------------------------------
#
# argv templates; {remote}, {path}, {binary} substituted by _argv(). Anything
# not in this table cannot be run — that is the enforcement.

RCLONE_SURFACE = {
    "version": ("{binary}", "version"),
    "lsjson": ("{binary}", "lsjson", "{remote}:{path}", "--files-only"),
    "lsjson_hash": ("{binary}", "lsjson", "{remote}:{path}", "--files-only", "--hash"),
    "copyto_upload": ("{binary}", "copyto", "{src}", "{remote}:{dst}"),
    "cat": ("{binary}", "cat", "{remote}:{path}"),
    # laptop role only — the alive host never deletes from the folder
    "deletefile": ("{binary}", "deletefile", "{remote}:{path}"),
}

RCLONE_PINNED_VERSION = "1.75.2"


class RcloneSyncBackend:
    """The real rclone backend for the alive host's Drive folder.

    The subprocess runner is injectable so tests can pin behaviour without a
    binary and without a network. Tests never call this with the default
    runner.
    """

    is_fixture = False

    def __init__(self, remote: str, root_folder: str, *, binary: str = "rclone",
                 timeout_s: int = 60,
                 runner=subprocess.run,
                 role: str = "host"):
        if role not in ("host", "laptop"):
            raise SyncError(f"unknown role {role!r}: 'host' or 'laptop'")
        self.remote = remote
        self.root_folder = root_folder.strip("/")
        self.binary = binary
        self.timeout_s = timeout_s
        self._runner = runner
        self.role = role

    @property
    def name(self) -> str:
        return f"rclone:{self.remote}"

    def _argv(self, verb: str, **subs: str) -> list[str]:
        template = RCLONE_SURFACE.get(verb)
        if template is None:
            raise SyncError(f"rclone verb {verb!r} is not in the pinned surface; refusing")
        try:
            return [part.format(binary=self.binary, remote=self.remote, **subs)
                    for part in template]
        except KeyError as exc:
            raise SyncError(f"missing substitution {exc} for verb {verb!r}") from exc

    def _run(self, verb: str, **subs: str) -> subprocess.CompletedProcess:
        argv = self._argv(verb, **subs)
        try:
            return self._runner(argv, capture_output=True, timeout=self.timeout_s,
                                check=False)
        except FileNotFoundError as exc:
            raise SyncRemoteUnreachable("rclone binary not found on this host") from exc
        except subprocess.TimeoutExpired as exc:
            raise SyncRemoteUnreachable(f"rclone {verb} timed out after {self.timeout_s}s") from exc

    def put(self, prefix: str, name: str, data: bytes) -> None:
        _check_name(prefix, name)
        src = Path(self.root_tmp() / name)
        src.write_bytes(data)
        try:
            result = self._run("copyto_upload", src=str(src),
                               dst=f"{self.root_folder}/{prefix}/{name}")
        finally:
            try:
                src.unlink()
            except OSError:
                pass
        if result.returncode != 0:
            raise SyncRemoteUnreachable(
                f"rclone copyto failed ({result.returncode}); remote not touched, "
                f"envelope kept in spool")

    def root_tmp(self) -> Path:
        path = Path.home() / ".alive-spool"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get(self, prefix: str, name: str) -> bytes:
        _check_name(prefix, name)
        result = self._run("cat", path=f"{self.root_folder}/{prefix}/{name}")
        if result.returncode != 0:
            raise SyncRemoteUnreachable(f"rclone cat failed ({result.returncode})")
        return result.stdout

    def list(self, prefix: str) -> list[str]:
        _check_name(prefix, "LATEST")
        result = self._run("lsjson_hash", path=f"{self.root_folder}/{prefix}")
        if result.returncode != 0:
            raise SyncRemoteUnreachable(f"rclone lsjson failed ({result.returncode})")
        try:
            entries = json.loads(result.stdout.decode("utf-8") or "[]")
        except ValueError as exc:
            raise SyncError("rclone lsjson returned non-JSON") from exc
        return sorted(e["Name"] for e in entries
                      if isinstance(e, dict) and _SAFE_NAME.match(e.get("Name", "")))

    def delete(self, prefix: str, name: str) -> bool:
        # Pruning is the LAPTOP's job (receipts older than 7 days). The alive
        # host never deletes from Drive — enforced here, in code.
        if self.role != "laptop":
            raise SyncError("the alive host never deletes from the sync folder")
        _check_name(prefix, name)
        result = self._run("deletefile", path=f"{self.root_folder}/{prefix}/{name}")
        if result.returncode != 0:
            raise SyncRemoteUnreachable(f"rclone deletefile failed ({result.returncode})")
        return True

    def describe(self) -> dict:
        return {"backend": self.name, "kind": "rclone", "root_folder": self.root_folder}
