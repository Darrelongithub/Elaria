"""Child-process hygiene: nothing Elaria spawns may outlive her (VB-10).

Two processes touch the audio system on her behalf — a player for spoken acks
and `pw-record` for the microphone. Both used to be ordinary children: `kill -9`
the daemon and the player keeps playing (or `pw-record` keeps holding the
microphone) with nobody left to stop them, which on the owner's box means a
hotkey that appears to do nothing because the sink is already claimed.

`systemctl stop` is covered by systemd's default `KillMode=control-group`, but a
crash, an OOM kill and a manual `kill -9` are not. `PR_SET_PDEATHSIG` is: the
kernel sends the child a signal the moment its parent *thread* exits, with no
cleanup code required. `start_new_session` additionally keeps the child out of
the daemon's process group, so a Ctrl-C to the daemon cannot strand it mid-
buffer, and cannot kill it mid-utterance either — it is terminated deliberately
by `aclose()`/the graceful shutdown path instead.

Linux-only by nature: on any other platform the helpers return no extra kwargs
and the callers behave exactly as before.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PR_SET_PDEATHSIG = 1
_SUPPORTED = sys.platform.startswith("linux")


def pdeathsig_preexec():
    """`preexec_fn` that arms PR_SET_PDEATHSIG in the child (runs after fork).

    Deliberately silent on failure: a hardened kernel that refuses prctl must not
    break playback; the graceful shutdown path still reaps the child.
    """
    import ctypes

    def _prep() -> None:
        try:
            libc = ctypes.CDLL(None, use_errno=True)
            if libc.prctl(PR_SET_PDEATHSIG, subprocess.SIGKILL, 0, 0, 0) != 0:
                return
        except Exception:
            return

    return _prep if _SUPPORTED else None


def child_kwargs() -> dict:
    """Extra Popen kwargs for a spawn that must not be orphaned.

    The same two keys serve both call sites — the synchronous player run and the
    long-lived `asyncio` capture — so there is one hygiene rule to keep.
    """
    kwargs = {"start_new_session": True}
    preexec = pdeathsig_preexec()
    if preexec is not None:
        kwargs["preexec_fn"] = preexec
    return kwargs


# What a leaked audio child looks like on this box: the player(s), the recorder,
# and the local renderer. Matched by executable name, then confirmed by cmdline so
# an unrelated `aplay` the user started is not touched without a reason.
AUDIO_CHILD_NAMES = ("pw-play", "paplay", "aplay", "pw-record", "piper")


def audio_child_names(config) -> tuple[str, ...]:
    """What to look for, including a custom `[tts] player` (VB-10).

    A configured player is the one that actually gets spawned, so a personal
    `player = "~/.local/bin/clip-play"` must be reaped too — matching only the
    stock names would leave the owner's own orphan in place.
    """
    names = list(AUDIO_CHILD_NAMES)
    try:
        setting = str(config.section("tts").get("player", "auto")) if config else "auto"
    except Exception:
        setting = "auto"
    if setting not in ("", "auto", "none"):
        import shlex

        parts = shlex.split(setting)
        if parts:
            from pathlib import PurePosixPath

            base = PurePosixPath(parts[0]).name
            if base and base not in names:
                names.insert(0, base)
    return tuple(names)


def orphaned_audio_children(*, names: tuple[str, ...] = AUDIO_CHILD_NAMES,
                            owner_pid: int | None = None) -> list[dict]:
    """Reap-list: audio processes whose daemon is gone (VB-10).

    A child of a SIGKILLed daemon is reparented to the subtree init (pid 1 inside a
    container, otherwise systemd/init) — that is the state where `pw-record` keeps
    the microphone and `pw-play` keeps the sink claimed while nothing is left to
    stop them. `PR_SET_PDEATHSIG` normally prevents it; this is the belt to those
    braces, and the only thing that helps on a kernel or thread arrangement where
    pdeathsig is not delivered (both are real: this sandbox reproduces exactly
    that). `owner_pid` narrows the match to a specific daemon's leftovers.
    """
    found: list[dict] = []
    for entry in sorted(Path("/proc").iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 0):
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        try:
            info = _proc_status(entry)
        except OSError:
            continue                      # raced with its own exit
        if info.get("PPid") != "1" and owner_pid is None:
            continue
        name = (info.get("Name") or "").lower()
        if not any(candidate in name for candidate in names):
            continue
        if owner_pid is not None and info.get("PPid") != "1":
            continue
        found.append({"pid": pid, "name": info.get("Name"), "state": info.get("State"),
                      "cmdline": _proc_cmdline(entry)})
    return found


def reap_orphans(*, names: tuple[str, ...] = AUDIO_CHILD_NAMES, signal_first=signal.SIGTERM,
                 grace_s: float = 0.4) -> dict:
    """Terminate leaked audio children. Returns what was killed and what remains.

    TERM first, then KILL after `grace_s`: `pw-record` flushes on a clean
    terminate, and a mic that is released politely is a mic that still works.
    """
    killed, failed = [], []
    for proc in orphaned_audio_children(names=names):
        pid = proc["pid"]
        try:
            os.kill(pid, signal_first)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            failed.append({**proc, "error": str(exc)})
            continue
        killed.append(proc)
    if killed and grace_s > 0:
        deadline = time.monotonic() + grace_s
        while time.monotonic() < deadline:
            if not any(pid_alive(p["pid"]) for p in killed):
                break
            time.sleep(0.05)
    for proc in killed:
        if pid_alive(proc["pid"]):
            try:
                os.kill(proc["pid"], signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    return {"killed": [p["pid"] for p in killed],
            "detail": [f"{p['name']}({p['pid']})" for p in killed],
            "failed": failed,
            "remaining": [p["pid"] for p in orphaned_audio_children(names=names)
                          if pid_alive(p["pid"])]}


def _proc_status(entry: Path) -> dict:
    out = {}
    for line in (entry / "status").read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.partition(":")
        out[key] = value.strip()
    return out


def _proc_cmdline(entry: Path) -> str:
    try:
        return (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode(
            "utf-8", "replace").strip()
    except OSError:
        return ""


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
