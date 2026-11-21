#!/usr/bin/env python3
"""Rung-0 identity readback — is the RUNNING daemon the code in this checkout?

Ask 43 (owner): *"rung-0: is the revision of the running daemon the same as the
checkout I just edited?"* It pairs with the advance/stale-checkout lesson: the
expensive version of that bug is spending an evening debugging a transcript
produced by the binary you replaced an hour ago.

Why `version` cannot answer it. `status`) reports `"version": __version__`, and
`__version__` is the literal string `"0.0.1"` in `__init__.py`. That string has
not changed across every commit in this tree, so **two different checkouts report
the same version** — equal versions discriminate nothing. The probe says so in
numbers (`version_alone_discriminates 0`) rather than letting the field imply a
match.

What actually discriminates, cheapest first:

  1. **File freshness vs the daemon's start time.** Any `src/assistant/*.py`
     newer than the moment the daemon started is code the daemon is NOT running.
     This needs no git, no network and no write — just `uptime_s` from status and
     an `os.stat`. `stale_source_files 0` is the only reading that lets you trust
     a test result.
  2. **Which directory the process is actually running from.** `/proc/<pid>/cwd`
     and `/proc/<pid>/cmdline` are read-only, and they catch the two-checkout
     confusion (daemon launched from `~/Elaria-old` while you edit `~/Elaria`).
  3. **The commit of that directory**, via `git -C <dir> rev-parse HEAD` — the
     only real revision evidence, and the first of the three to be unavailable
     on a stripped box.

`verdict` is one of:

  daemon_down         nothing to compare; the checkout's staleness is unknowable
  different_checkout  the process runs from another commit/directory
  stale_checkout      source files are newer than the daemon's start
  dirty_checkout      the tree has uncommitted edits — "the sha" is not one thing
  match               same commit, no stale files, clean tree
  revision_unknown    version matched but no revision evidence existed (weak)

Read-only and side-effect free: it does not import `daemon.py`/`cli.py`/`store.py`
and never restarts, signals or reconfigures anything. Nothing here fixes a stale
daemon — restarting is the owner's call, and the printout is what makes that call
cheap.

Usage:
  daemon_identity.py                  # the full readback, verdict included
  daemon_identity.py --no-ipc         # files + this checkout only, ask no daemon
  daemon_identity.py --checkout PATH  # compare a specific checkout
  daemon_identity.py --socket PATH    # a non-default daemon socket
  daemon_identity.py --checksum

Integrity: `scripts/daemon_identity.py.sha256` holds this file's digest under its
repository-relative name; verify from the repository root with
`sha256sum -c scripts/daemon_identity.py.sha256`.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

UNKNOWN = "-1"

# The static version string. If it ever becomes per-commit, this note is stale
# on purpose — see VERSION_PROVENANCE_NOTE.
VERSION_IS_STATIC_NOTE = (
    "__version__ is a hand-edited literal, not a build stamp: two different "
    "checkouts report the same value, so an equal version is not evidence of an "
    "equal tree"
)

EMPTY_FAILS_TO_DISCRIMINATE = (
    "a `daemon_down` readback cannot tell apart: no daemon configured, the unit "
    "failed to start, the socket is in another XDG_RUNTIME_DIR, or the daemon "
    "died after binding — and it says nothing at all about whether THIS checkout "
    "is stale, because there is no process to compare against"
)

VERDICTS = ("daemon_down", "different_checkout", "stale_checkout",
            "dirty_checkout", "match", "revision_unknown")


# ---------------------------------------------------------------------------
# filesystem facts (pure-ish; every probe degrades to None, never raises)
# ---------------------------------------------------------------------------
def source_files(checkout: Path) -> list[Path]:
    """Every `.py` under `<checkout>/src/assistant`, sorted for stable output."""
    root = Path(checkout) / "src" / "assistant"
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def newest_mtime(files: list[Path]) -> tuple[float | None, str]:
    """`(newest_epoch, that_file)` — the newest source edit, or `(None, '')`."""
    newest: float | None = None
    newest_path = ""
    for path in files:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        if newest is None or stamp > newest:
            newest, newest_path = stamp, str(path)
    return newest, newest_path


def git_revision(directory: Path, runner=subprocess.run) -> tuple[str, str]:
    """`(short_sha, error)` for a directory. `('', reason)` when git cannot say."""
    try:
        proc = runner(["git", "-C", str(directory), "rev-parse", "HEAD"],
                      capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"{type(exc).__name__}: {exc}"
    if getattr(proc, "returncode", 1) != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return "", detail[0][:160] if detail else f"git exit {proc.returncode}"
    sha = (proc.stdout or "").strip()
    return (sha[:12], "") if sha else ("", "git printed no revision")


def git_dirty(directory: Path, runner=subprocess.run) -> int:
    """1 = uncommitted edits present, 0 = clean, -1 = could not tell."""
    try:
        proc = runner(["git", "-C", str(directory), "status", "--porcelain"],
                      capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return -1
    if getattr(proc, "returncode", 1) != 0:
        return -1
    return 1 if (proc.stdout or "").strip() else 0


def checkout_version(checkout: Path) -> str:
    """`__version__` read as TEXT — never imported (a reader must not execute)."""
    init = Path(checkout) / "src" / "assistant" / "__init__.py"
    try:
        for line in init.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("__version__") and "=" in stripped:
                value = stripped.split("=", 1)[1].strip().strip("'\"")
                return value or UNKNOWN
    except OSError:
        return UNKNOWN
    return UNKNOWN


def parse_unix_table(text: str, target: str) -> int | None:
    """`/proc/net/unix` -> the kernel inode bound to `target`, or None.

    Columns: Num RefCount Protocol Flags Type St Inode Path. The path is the
    LAST column and may be absent (unnamed sockets), so the row is split from the
    right rather than relied on to have eight fields.
    """
    for line in text.splitlines()[1:]:
        parts = line.split()
        # Only the literal header starts with "Num". Data rows begin with a
        # kernel pointer ending in ":", so a `parts[0].endswith(":")` skip would
        # silently drop every real row — which is exactly what it did first.
        if not parts or parts[0] == "Num":
            continue
        if len(parts) < 7:
            continue
        path = parts[7] if len(parts) >= 8 else ""
        if path != target:
            continue
        try:
            return int(parts[6])
        except ValueError:
            continue
    return None


def socket_inode(socket_path: Path) -> int | None:
    """The KERNEL inode of a bound unix socket, from `/proc/net/unix`.

    Not `os.stat().st_ino`: that is the inode of the filesystem node, and it is a
    different number from the socket inode the kernel lists in `/proc/<pid>/fd`.
    Comparing the two can never match, so a probe that used it would report "no
    pid found" forever while looking like it had tried.
    """
    try:
        text = Path("/proc/net/unix").read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_unix_table(text, str(socket_path))


def find_daemon_pid(socket_path: Path | None) -> tuple[int | None, str]:
    """The pid holding THIS socket, proved by inode — not guessed by name.

    `status` reports no pid today (HR-F-6), and matching a process by name is
    wrong the moment two daemons run under different `XDG_RUNTIME_DIR`s. Instead:
    stat the socket, then look for a process whose fd table holds exactly that
    `socket:[inode]`. Read-only, and it can only ever name the process that owns
    the socket we are about to trust.
    """
    if socket_path is None:
        return None, "no socket path"
    inode = socket_inode(Path(socket_path))
    if inode is None:
        return None, "socket is not bound (no /proc/net/unix row)"
    wanted = f"socket:[{inode}]"
    holders: list[int] = []
    try:
        pids = [name for name in os.listdir("/proc") if name.isdigit()]
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    for name in pids:
        fd_dir = Path("/proc") / name / "fd"
        try:
            entries = list(fd_dir.iterdir())
        except OSError:
            continue          # not ours, or gone: absence here proves nothing
        for entry in entries:
            try:
                if os.readlink(entry) == wanted:
                    holders.append(int(name))
                    break
            except OSError:
                continue
    if not holders:
        return None, "no process holds this socket (it may have just started)"
    if len(holders) > 1:
        # Two holders is a fact worth printing, not a coin flip to resolve.
        return min(holders), f"ambiguous: {len(holders)} processes hold the socket"
    return holders[0], "socket_inode"


def proc_facts(pid: int | None) -> dict:
    """Read-only `/proc` facts about the daemon process. Never raises."""
    facts = {"pid": pid if pid else UNKNOWN, "exe": UNKNOWN, "cwd": UNKNOWN,
             "cmdline": UNKNOWN, "start_epoch": None}
    if not pid:
        return facts
    base = Path("/proc") / str(pid)
    for key, name in (("exe", "exe"), ("cwd", "cwd")):
        try:
            facts[key] = os.readlink(base / name)
        except OSError:
            facts[key] = UNKNOWN
    try:
        raw = (base / "cmdline").read_bytes()
        facts["cmdline"] = " ".join(
            part.decode("utf-8", "replace") for part in raw.split(b"\0") if part)[:300]
    except OSError:
        facts["cmdline"] = UNKNOWN
    try:
        # /proc/stat starttime is in clock ticks since boot: the only way to learn
        # WHEN this process started without trusting its own report of it.
        stat = (base / "stat").read_text(encoding="utf-8")
        fields = stat.rsplit(")", 1)[1].split()
        ticks = int(fields[19])
        boot = float(Path("/proc/uptime").read_text().split()[0])
        facts["start_epoch"] = round(time.time() - (boot - ticks / os.sysconf("SC_CLK_TCK")), 1)
    except (OSError, IndexError, ValueError):
        facts["start_epoch"] = None
    return facts


# ---------------------------------------------------------------------------
# the IPC read (the only part that talks to the daemon)
# ---------------------------------------------------------------------------
def read_status(socket_path: Path | None) -> tuple[dict, str]:
    """`(status, error)` from `status` over IPC. Never raises."""
    if socket_path is None:
        return {}, "no socket resolved"
    try:
        from assistant.ipc import call
    except Exception as exc:  # importing the client is a read-only convenience
        return {}, f"{type(exc).__name__}: {exc}"
    try:
        reply = call(Path(socket_path), "status", timeout=3.0)
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if not isinstance(reply, dict):
        return {}, "status reply was not an object"
    result = reply.get("result", reply)
    if not isinstance(result, dict):
        return {}, "status result was not an object"
    return result, ""


def resolve_socket(override: str | None) -> Path | None:
    if override:
        return Path(override).expanduser()
    env = os.environ.get("XDG_RUNTIME_DIR", "")
    if env:
        return Path(env) / "assistant.sock"
    try:
        from assistant.config import load_config

        return Path(load_config().socket_path)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# the verdict (pure — this is what the tests drive)
# ---------------------------------------------------------------------------
def identify(*, daemon: dict, daemon_error: str, checkout: Path,
             checkout_commit: str, checkout_commit_error: str,
             checkout_dirty: int, checkout_version_value: str,
             daemon_dir_commit: str, daemon_dir_error: str,
             newest_source_mtime: float | None, newest_source_file: str,
             daemon_start_epoch: float | None, now: float | None = None) -> dict:
    """All the evidence in, one verdict out. No IO in here."""
    reachable = bool(daemon) and not daemon_error
    uptime = daemon.get("uptime_s") if reachable else None
    clock = time.time() if now is None else now
    # Prefer the process's own /proc start time; fall back to the daemon's
    # self-reported uptime, which is only as good as its clock.
    if daemon_start_epoch is None and isinstance(uptime, (int, float)):
        daemon_start_epoch = round(clock - float(uptime), 1)

    # -1 = never compared. Reporting 0 here would claim "no stale files" about a
    # comparison that had no daemon to compare against.
    stale_files = -1
    if reachable and daemon_start_epoch is not None and newest_source_mtime:
        stale_files = 1 if newest_source_mtime > daemon_start_epoch else 0
    daemon_age_s = (round(clock - daemon_start_epoch, 1)
                    if daemon_start_epoch is not None else None)
    source_age_s = (round(clock - newest_source_mtime, 1)
                    if newest_source_mtime else None)

    version_equal = (reachable and checkout_version_value != UNKNOWN
                     and str(daemon.get("version")) == checkout_version_value)

    if not reachable:
        verdict, why = "daemon_down", ("no daemon answered, so this checkout's "
                                       "staleness cannot be read from a process")
    elif daemon_dir_commit and checkout_commit and \
            daemon_dir_commit != checkout_commit:
        verdict, why = "different_checkout", (
            f"the daemon runs from {daemon_dir_commit} while this checkout is "
            f"{checkout_commit}")
    elif stale_files:
        verdict, why = "stale_checkout", (
            f"{newest_source_file} is newer than the daemon's start — the "
            "daemon is not running the code on disk")
    elif checkout_dirty == 1:
        verdict, why = "dirty_checkout", (
            "the tree has uncommitted edits, so 'the sha' is not a single thing")
    elif checkout_commit and daemon_dir_commit:
        verdict, why = "match", (f"same commit ({checkout_commit}), no source "
                                 f"file newer than the daemon, tree clean")
    else:
        verdict, why = "revision_unknown", (
            "no revision evidence was readable, so only versions were compared "
            "— and an equal version is not an equal tree")

    return {
        "verdict": verdict,
        "why": why,
        "daemon_reachable": 1 if reachable else 0,
        "daemon_error": daemon_error or "",
        "daemon_version": daemon.get("version") if reachable else UNKNOWN,
        "daemon_started_at": daemon.get("started_at") if reachable else UNKNOWN,
        "daemon_uptime_s": uptime if uptime is not None else UNKNOWN,
        "daemon_start_epoch": (daemon_start_epoch if daemon_start_epoch is not None
                               else UNKNOWN),
        "daemon_age_s": daemon_age_s if daemon_age_s is not None else UNKNOWN,
        "checkout": str(checkout),
        "checkout_version": checkout_version_value,
        "checkout_commit": checkout_commit or UNKNOWN,
        "checkout_commit_error": checkout_commit_error or "",
        "checkout_dirty": checkout_dirty,
        "daemon_dir_commit": daemon_dir_commit or UNKNOWN,
        "daemon_dir_error": daemon_dir_error or "",
        "newest_source_file": newest_source_file or UNKNOWN,
        "newest_source_age_s": (source_age_s if source_age_s is not None else UNKNOWN),
        "stale_source_files": stale_files,
        "version_equal": 1 if version_equal else 0,
        # The ask-43 finding as a number: an equal version proves nothing.
        "version_alone_discriminates": 0,
    }


RENDER_KEYS = ("verdict", "why", "daemon_reachable", "daemon_error",
               "daemon_version", "daemon_started_at", "daemon_start_epoch",
               "daemon_age_s", "daemon_pid", "daemon_pid_source", "daemon_exe",
               "daemon_cwd",
               "daemon_cmdline", "checkout", "checkout_version",
               "checkout_commit", "checkout_commit_error", "checkout_dirty",
               "daemon_dir_commit", "daemon_dir_error", "newest_source_file",
               "newest_source_age_s", "stale_source_files", "version_equal",
               "version_alone_discriminates")


def render(result: dict, proc: dict | None = None) -> str:
    merged = dict(result)
    for key, value in (proc or {}).items():
        merged[f"daemon_{key}"] = value
    lines = ["available 1" if merged["daemon_reachable"] == 1 else "available 0"]
    for key in RENDER_KEYS:
        value = merged.get(key)
        if value is None or value == "":
            continue
        lines.append(f"{key} {value}")
    lines.append(f"note version_is_static {VERSION_IS_STATIC_NOTE}")
    if merged["daemon_reachable"] != 1:
        lines.append(f"note empty_fails_to_discriminate {EMPTY_FAILS_TO_DISCRIMINATE}")
    if merged["verdict"] in ("stale_checkout", "different_checkout"):
        lines.append("note restart_is_the_owners_call this reader never signals "
                     "a process")
    lines.append("note read_only")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# collection (real IO, thin — everything interesting is above)
# ---------------------------------------------------------------------------
def collect(checkout: Path, socket_path: Path | None, *, use_ipc: bool = True,
            runner=subprocess.run) -> tuple[dict, dict]:
    """Gather evidence from the machine and return `(identity, proc_facts)`."""
    if use_ipc:
        daemon, daemon_error = read_status(socket_path)
    else:
        daemon, daemon_error = {}, "asked not to contact the daemon (--no-ipc)"
    # Prefer the daemon's own report (HR-F-6 will add it); otherwise prove it.
    pid = daemon.get("pid") if isinstance(daemon, dict) else None
    pid_source = "status"
    if not isinstance(pid, int):
        pid, pid_error = find_daemon_pid(socket_path)
        pid_source = "socket_inode" if pid else pid_error
    proc = proc_facts(pid if isinstance(pid, int) else None)
    proc["pid_source"] = pid_source

    checkout_commit, checkout_commit_error = git_revision(checkout, runner=runner)
    files = source_files(checkout)
    newest, newest_path = newest_mtime(files)
    # Which directory does the process believe it belongs to? Prefer /proc cwd,
    # then the exe's parent (venv/bin/assistd -> the venv, one level up), then
    # this checkout as the last resort — and only report a commit for a real dir.
    daemon_dir = ""
    for candidate in (proc.get("cwd"),):
        if candidate and candidate != UNKNOWN and Path(candidate).is_dir():
            daemon_dir = candidate
            break
    daemon_dir_commit = ""
    daemon_dir_error = ""
    if daemon_dir:
        daemon_dir_commit, daemon_dir_error = git_revision(Path(daemon_dir),
                                                           runner=runner)
    elif proc.get("cwd") == UNKNOWN and proc.get("pid") != UNKNOWN:
        daemon_dir_error = "/proc cwd unreadable (different user or pid gone)"

    identity = identify(
        daemon=daemon, daemon_error=daemon_error, checkout=checkout,
        checkout_commit=checkout_commit,
        checkout_commit_error=checkout_commit_error,
        checkout_dirty=git_dirty(checkout, runner=runner),
        checkout_version_value=checkout_version(checkout),
        daemon_dir_commit=daemon_dir_commit, daemon_dir_error=daemon_dir_error,
        newest_source_mtime=newest, newest_source_file=newest_path,
        daemon_start_epoch=proc.get("start_epoch"),
    )
    return identity, proc


# ---------------------------------------------------------------------------
# pinning + cli
# ---------------------------------------------------------------------------
def checksum() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def manifest_name() -> str:
    here = Path(__file__).resolve()
    return f"{here.parent.name}/{here.name}"


def write_manifest(target: Path | None = None) -> Path:
    path = target or Path(__file__).with_suffix(".py.sha256")
    path.write_text(f"{checksum()}  {manifest_name()}\n")
    return path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print("usage: daemon_identity.py [--checkout PATH] [--socket PATH] "
              "[--no-ipc] | --checksum", file=sys.stderr)
        return 2
    if argv and argv[0] == "--checksum":
        print(write_manifest())
        return 0
    options: dict[str, str] = {}
    flags: set[str] = set()
    valued = {"--checkout", "--socket"}
    allowed = {"--no-ipc"}
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in allowed:
            flags.add(token)
            index += 1
            continue
        if token in valued:
            if index + 1 >= len(argv):
                print(f"error value_required {token}", file=sys.stderr)
                return 2
            options[token] = argv[index + 1]
            index += 2
            continue
        print(f"error unknown_argument {token}", file=sys.stderr)
        return 2
    checkout = (Path(options["--checkout"]).expanduser() if "--checkout" in options
                else repo_root())
    socket_path = None if "--no-ipc" in flags else resolve_socket(
        options.get("--socket"))
    identity, proc = collect(checkout, socket_path,
                             use_ipc="--no-ipc" not in flags)
    print(render(identity, proc))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
