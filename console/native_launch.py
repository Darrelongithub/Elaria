#!/usr/bin/python3
"""Native launcher v4. Fixed owner paths, local-only pinned worktree, no browser fallback.

Installed behind the unchanged Hyprland bind. Never run this against owner paths in tests.
"""
from __future__ import annotations

import ast
import base64
import fcntl
import hashlib
import http.client
import importlib.util
import os
import resource
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlsplit

COMMIT = 'fcd55ca1bce34d8a1f479bf2d035cc866c4a482f'
BRIDGE_SHA = 'ed227a7d50effb874e303f95462f3dc127c9bd79a71a8d9b34f86980815b091c'
NATIVE_SHA = 'e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e'
KEY_PATTERNS = (r'^extensions\.partialclone$', r'^remote\..*\.promisor$',
                r'^remote\..*\.partialclonefilter$')
PORT = 8744


class Stop(Exception):
    """Constant public reason only; never wrap child output or secret-bearing exceptions."""


class Paths(NamedTuple):
    repo: Path
    worktree: Path
    bridge_python: Path
    native_python: Path
    native: Path
    runtime: Path
    log: Path


def owner_paths():
    return Paths(Path('/home/darrel/Elaria'), Path('/tmp/elaria-bridge'),
                 Path('/home/darrel/Elaria/.venv/bin/python'), Path('/usr/bin/python3'),
                 Path(__file__).resolve().with_name('native_window.py'),
                 Path('/run/user') / str(os.getuid()), Path('/tmp/elaria-launch.log'))


def child_env(paths):
    allowed = ('USER', 'LOGNAME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'DISPLAY', 'WAYLAND_DISPLAY',
               'XAUTHORITY', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP', 'DBUS_SESSION_BUS_ADDRESS')
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env.update(HOME=str(paths.repo.parent), PATH='/usr/bin:/bin',
               XDG_RUNTIME_DIR=str(paths.runtime), GIT_TERMINAL_PROMPT='0')
    return env


def private_directory(path):
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise Stop('STOP: runtime/bundle directory must be owner-owned 0700.')


def private_fd(path):
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW |
                 os.O_NONBLOCK | os.O_CLOEXEC, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
        os.close(fd)
        raise Stop('STOP: unsafe log/lock file; no launch.')
    os.fchmod(fd, 0o600)  # tighten an owner-owned legacy v3 log; never truncate it
    return fd


def note(fd, message):
    os.write(fd, (time.strftime('%H:%M:%S ') + message + '\n').encode())


def git_read(paths, *arguments, ok=(0,)):
    command = ['/usr/bin/git', '-c', 'protocol.allow=never', '--no-replace-objects',
               '-c', 'core.hooksPath=/dev/null', '-c', 'core.attributesFile=/dev/null',
               '-C', str(paths.repo), *arguments]
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                            env=dict(child_env(paths), GIT_ALLOW_PROTOCOL=''), timeout=30, check=False)
    if result.returncode not in ok:
        raise Stop('STOP: local Git verification/recovery failed; no fetch or repair fallback.')
    return result


def no_promisor(paths):
    version = git_read(paths, '--version').stdout.decode('ascii').strip()
    for pattern in KEY_PATTERNS:
        result = git_read(paths, 'config', '--name-only', '--get-regexp', pattern, ok=(0, 1))
        if result.returncode == 0:
            raise Stop('STOP: partial-clone/promisor configuration present; local-only recovery refused.')
    return version


def pinned_file(path, expected):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_size > 1024 * 1024
                or hashlib.sha256(file.read()).hexdigest() != expected):
            raise Stop('STOP: pinned executable checksum/ownership mismatch; no launch.')


def ensure_worktree(paths, log):
    version = no_promisor(paths)
    note(log, version + '; three promisor key-name checks absent; protocol.allow=never')
    git_read(paths, 'cat-file', '-e', COMMIT + '^{commit}')  # missing local object is a hard stop
    if not paths.worktree.exists() and not paths.worktree.is_symlink():
        records = git_read(paths, 'worktree', 'list', '--porcelain').stdout.decode().split('\n\n')
        stale = [r for r in records if r.splitlines() and r.splitlines()[0] == 'worktree ' + str(paths.worktree)]
        if any(any(line.startswith('locked') for line in r.splitlines()) for r in stale):
            raise Stop('STOP: pinned worktree registration is locked; no override.')
        # A reboot may remove /tmp while leaving this one registration. --force only reuses
        # that missing path; no prune/remove/reset of other worktrees, branches or dirty files.
        args = ['worktree', 'add', '--detach']
        if stale:
            args.append('--force')
        git_read(paths, *args, str(paths.worktree), COMMIT)
        note(log, 'pinned worktree recreated from local objects')
    info = paths.worktree.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise Stop('STOP: unsafe existing worktree; no repair.')
    # Verify target HEAD, not the main checkout; never switch or reset either checkout.
    target = paths._replace(repo=paths.worktree)
    no_promisor(target)
    if git_read(target, 'rev-parse', 'HEAD').stdout.decode().strip() != COMMIT:
        raise Stop('STOP: worktree is not at the exact pinned commit; no reset.')
    launcher = paths.worktree / 'console/run_bridge.py'
    pinned_file(launcher, BRIDGE_SHA)
    # Read only the checksum-verified launcher's literal pins; don't execute/import it here.
    tree = ast.parse(launcher.read_text())
    pins = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'PAYLOAD_SHA256'
                        for target in node.targets))
    for name, digest in pins.items():
        if Path(name).name != name:
            raise Stop('STOP: invalid pinned asset name.')
        pinned_file(paths.worktree / 'console' / name, digest)


def listener_pid(port=PORT):
    """Locate only the loopback listener's owner process, not every process's argv.

    /proc/net/tcp and fd symlinks are metadata. Never read cmdlines of unrelated processes.
    A listener with unknown ownership/identity is occupied, not an invitation to start again.
    """
    inodes = set()
    for row in Path('/proc/net/tcp').read_text().splitlines()[1:]:
        columns = row.split()
        address, number = columns[1].split(':')
        if int(number, 16) == port and columns[3] == '0A':
            if address != '0100007F' or int(columns[7]) != os.getuid():
                raise Stop('STOP: bridge port has an unexpected listener.')
            inodes.add(columns[9])
    if not inodes:
        # IPv6/wildcard listeners must not be mistaken for an absent IPv4 bridge.
        for row in Path('/proc/net/tcp6').read_text().splitlines()[1:]:
            columns = row.split()
            if int(columns[1].split(':')[1], 16) == port and columns[3] == '0A':
                raise Stop('STOP: bridge port has an unexpected IPv6 listener.')
        return None
    owners = set()
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            for fd in (directory / 'fd').iterdir():
                if os.readlink(fd) in {f'socket:[{inode}]' for inode in inodes}:
                    owners.add(int(directory.name))
        except (OSError, PermissionError):
            continue
    if len(owners) != 1:
        raise Stop('STOP: cannot identify a unique owner bridge listener.')
    return owners.pop()


def bridge_identity(pid, paths):
    process = Path('/proc') / str(pid)
    try:
        argv = (process / 'cmdline').read_bytes().split(b'\0')
        args = [os.fsdecode(arg) for arg in argv if arg]
        if not args or Path(args[0]).resolve() != paths.bridge_python.resolve():
            return False
        for index, arg in enumerate(args[1:], 1):
            if arg in {'console/run_bridge.py', str(paths.worktree / 'console/run_bridge.py')}:
                script = Path(arg)
                if not script.is_absolute():
                    script = Path(os.readlink(process / 'cwd')) / script
                # Existing v2/v3 may have --open; reuse its bridge, never invoke that option.
                return script == paths.worktree / 'console/run_bridge.py' and index <= 3
    except OSError:
        return False
    return False


def live_pairing(url):
    parsed = urlsplit(url)
    if parsed.port != PORT:
        return False
    key = base64.b64encode(os.urandom(16)).decode('ascii')
    expected = base64.b64encode(hashlib.sha1(
        (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
    connection = http.client.HTTPConnection('127.0.0.1', PORT, timeout=1)
    try:
        connection.request('GET', '/elaria?token=' + parsed.fragment.removeprefix('pair='), headers={
            'Host': f'127.0.0.1:{PORT}', 'Origin': f'http://127.0.0.1:{PORT}',
            'Upgrade': 'websocket', 'Connection': 'Upgrade', 'Sec-WebSocket-Version': '13',
            'Sec-WebSocket-Key': key})
        response = connection.getresponse()
        return response.status == 101 and response.getheader('Sec-WebSocket-Accept') == expected
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()  # no hello, turn, model, or dispatch; just the pairing gate challenge


def find_live_file(paths, host):
    candidates = list(paths.runtime.glob('elaria-console-*/open.html'))
    if len(candidates) > 128:
        raise Stop('STOP: too many launch files; bounded discovery refused.')
    deadline = time.monotonic() + 8
    # Never select solely by mtime. Every candidate must pass private-file and live-token checks.
    for candidate in candidates:
        if time.monotonic() > deadline:
            break
        try:
            if live_pairing(host.read_launch_file(candidate)):
                return candidate
        except (OSError, ValueError, host.NativeStop):
            continue
    raise Stop('STOP: running bridge has no validated live private launch file.')


def start_bridge(paths, host, log):
    offset = os.fstat(log).st_size
    process = subprocess.Popen(
        [str(paths.bridge_python), '-IB', 'console/run_bridge.py', '--socket',
         str(paths.runtime / 'assistant.sock'), '--port', str(PORT)],
        cwd=paths.worktree, env=child_env(paths), stdin=subprocess.DEVNULL,
        stdout=log, stderr=log, close_fds=True, start_new_session=True)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise Stop('STOP: headless bridge exited; no native window opened.')
        data = os.pread(log, 32769, offset)
        if len(data) > 32768:
            raise Stop('STOP: bridge startup output exceeded bound; inspect private log.')
        for line in data.splitlines():
            if line.startswith(b'Private launch file: '):
                candidate = Path(os.fsdecode(line[len(b'Private launch file: '):]))
                if (candidate.parent.parent != paths.runtime or candidate.name != 'open.html'
                        or not candidate.parent.name.startswith('elaria-console-')):
                    raise Stop('STOP: unexpected launch-file location.')
                if listener_pid() == process.pid and live_pairing(host.read_launch_file(candidate)):
                    return candidate
        time.sleep(.05)
    # Do not terminate a possibly usable bridge or replay its startup implicitly.
    raise Stop('STOP: bridge startup outcome unknown; no retry or window fallback.')


def launch(paths, log):
    private_directory(paths.runtime)
    private_directory(paths.native.parent)
    pinned_file(paths.native, NATIVE_SHA)
    check = subprocess.run([str(paths.native_python), '-IB', str(paths.native), '--check'],
                           env=child_env(paths), stdin=subprocess.DEVNULL, capture_output=True,
                           timeout=15, check=False)
    if check.returncode:
        raise Stop('STOP: native GI/WebKit unavailable; sudo dnf install -y python3-gobject webkit2gtk4.1')
    spec = importlib.util.spec_from_file_location('elaria_v4_native', paths.native)
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    lock = private_fd(paths.runtime / 'elaria-native-launch.lock')
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Stop('STOP: another launch is in progress; no duplicate bridge start.') from None
        ensure_worktree(paths, log)
        pid = listener_pid()
        if pid is None:
            note(log, 'bridge ABSENT; starting detached HEADLESS (no --open)')
            link = start_bridge(paths, host, log)
        else:
            if not bridge_identity(pid, paths):
                raise Stop('STOP: port is not the pinned bridge; no replacement or duplicate.')
            link = find_live_file(paths, host)
            note(log, 'bridge PRESENT; validated live private launch file')
        subprocess.Popen([str(paths.native_python), '-IB', str(paths.native), '--launch-file', str(link)],
                         env=child_env(paths), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        note(log, 'native window requested in independent session; hardware appearance unverified')
    finally:
        os.close(lock)


def main():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    log = None
    try:
        paths = owner_paths()
        log = private_fd(paths.log)
        note(log, 'native launcher v4 invoked')
        launch(paths, log)
        return 0
    except Stop as exc:
        if log is not None:
            note(log, str(exc))
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        message = 'STOP: native launch failed; no browser, fetch, reset or retry fallback.'
        if log is not None:
            note(log, message)
        print(message, file=sys.stderr)
        return 2
    finally:
        if log is not None:
            os.close(log)


if __name__ == '__main__':
    sys.exit(main())
