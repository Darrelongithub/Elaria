#!/usr/bin/python3 -IB
"""LOW PRIORITY — committed, local-object delivery packet; no chat shell reconstruction.

Default: extract/check the accepted five-file snapshot into a new private HOME kit.
Only --run then executes the verified collector. Owner/design chooses the schedule;
this packet does not release the kitty scene. Run from any working directory.

Invocation (kept in this committed file, NOT relayed as executable chat text):
    /usr/bin/python3 -I -B owner_run_platform.py
    /usr/bin/python3 -I -B owner_run_platform.py --run
Optional --repo changes only the local source checkout (default HOME/Elaria).

BOOTSTRAP: retrieve this packet from its reported commit and independently check its
reported SHA256 BEFORE invoking Python. A packet cannot authenticate its own first
execution. Never remove a failed gate or edit the script to repair a failed run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import selectors
import signal
import stat
import subprocess
import tempfile
import time
from pathlib import Path

SOURCE_COMMIT = 'a0e1aa8bba11e15ae6de9150b5a158a966acc2d6'
FILES = (
    ('tools/kitty/collect_platform.py', 16455, '7e2d8679a3c18aa35968c06aab469082f9d17cfa8fb1ccaace3f5a4c85261c63'),
    ('tests/test_kitty_platform_collector.py', 18799, '38a5cd9f3b630f8a030b9e71d3e3446fda21cfe78e5394f9183dbf78a9ae45d2'),
    ('docs/kitty-platform-collector.md', 8252, 'c7f84e3e14935b95cc7fcebb523475e0052c8bc487ea028194f70e4f37f10522'),
    ('docs/design/kitty-2026-11-02-checkpoint-ruling.md', 10972, '088ce851db72a5b0aa66a8011660d651d75c3806dc249d39670e7c38b51eea9a'),
    ('docs/phase-reports/kitty-2026-11-02-platform-collector.md', 9797, '5c5a5d7ead0d0de76578b5b06154506caee5cf785799b56587bc439b6ae8a472'),
)
GIT_TIMEOUT = 20
GIT_STDERR_LIMIT = 4096


class PacketError(Exception):
    """Fixed diagnostic codes only. Do not echo repository/configuration error text."""


def private_home():
    home = Path.home()
    if not home.is_absolute() or '..' in home.parts or home.resolve() != home:
        raise PacketError('home-must-be-absolute-and-without-symlinks')
    info = home.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise PacketError('home-must-be-owned-and-not-group-world-writable')
    return home


def git_environment(empty_home):
    return {'PATH': '/usr/bin:/bin', 'HOME': str(empty_home), 'XDG_CONFIG_HOME': str(empty_home),
            'LC_ALL': 'C.UTF-8', 'TERM': 'dumb', 'NO_COLOR': '1',
            'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_NO_LAZY_FETCH': '1', 'GIT_NO_REPLACE_OBJECTS': '1',
            'GIT_OPTIONAL_LOCKS': '0', 'GIT_TERMINAL_PROMPT': '0'}


def read_git_blob(repo, path, size, empty_home):
    """Local Git only. Unsupported --no-lazy-fetch stops; NEVER retry without it.

The explicit option is important: an old Git can silently ignore a new environment
variable, but cannot silently ignore an unknown command-line option. No promisor fetch,
replacement refs, optional locks, checkout, hooks, filters, textconv or shell is requested.
"""
    argv = ('/usr/bin/git', '--no-lazy-fetch', '--no-replace-objects', '--no-optional-locks',
            '-c', 'protocol.allow=never', '-c', 'core.fsmonitor=false', '-C', str(repo),
            'cat-file', 'blob', SOURCE_COMMIT + ':' + path)
    proc = None
    reaped = False
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    selector = selectors.DefaultSelector()
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=git_environment(empty_home),
                                cwd=empty_home, close_fds=True, start_new_session=True, umask=0o077)
        for name in buffers:
            stream = getattr(proc, name)
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        deadline = time.monotonic() + GIT_TIMEOUT
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PacketError('git-read-timeout')
            for key, _ in selector.select(min(remaining, 0.2)):
                limit = size if key.data == 'stdout' else GIT_STDERR_LIMIT
                available = limit - len(buffers[key.data])
                chunk = os.read(key.fd, min(65536, available + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                elif len(chunk) > available:
                    raise PacketError('git-output-limit')
                else:
                    buffers[key.data].extend(chunk)
        proc.wait(timeout=max(0.001, deadline - time.monotonic()))
        reaped = True
        if proc.returncode != 0:
            raise PacketError('git-local-object-unavailable-or-git-option-unsupported')
        return bytes(buffers['stdout'])
    except subprocess.TimeoutExpired:
        raise PacketError('git-read-timeout') from None
    except OSError:
        raise PacketError('git-process-or-pipe-failed') from None
    finally:
        selector.close()
        if proc is not None:
            # A descendant may hold a pipe after the Git leader exits. Kill the private
            # group even then. The packet never fetches or runs owner-supplied helpers.
            try:
                if not reaped:
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        raise PacketError('git-reap-timeout') from None
            finally:
                proc.stdout.close()
                proc.stderr.close()


def verify_bytes(raw, size, expected):
    if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected:
        raise PacketError('size-or-sha256-mismatch')


def write_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def verify_kit(kit):
    for path, size, expected in FILES:
        fd = os.open(kit / path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                    or info.st_size != size):
                raise PacketError('unsafe-extracted-file')
            raw = bytearray()
            while chunk := os.read(fd, size + 1 - len(raw)):
                raw.extend(chunk)
                if len(raw) > size:
                    raise PacketError('extracted-file-grew')
            verify_bytes(raw, size, expected)
        finally:
            os.close(fd)


def exec_collector(argv, environment, kit):
    """Replace the packet; do not add a parent timeout that could orphan collector jobs.

The unchanged, verified collector owns its query/output/deadline controls. The packet
creates no service and no wrapper process that lives alongside it. Query stdin remains
DEVNULL; stdout is only the collector's bounded-summary schema, never manual contents.
"""
    os.chdir(kit)
    fd = os.open('/dev/null', os.O_RDONLY)
    try:
        os.dup2(fd, 0)
    finally:
        if fd != 0:
            os.close(fd)
    os.umask(0o077)
    os.execve(argv[0], argv, environment)


def run_packet(repo=None, *, execute=False, blob_reader=read_git_blob, executor=exec_collector):
    home = private_home()
    repo = Path(repo) if repo is not None else home / 'Elaria'
    if not repo.is_absolute() or '..' in repo.parts or not repo.is_dir():
        raise PacketError('local-repository-path-unavailable')
    kit = Path(tempfile.mkdtemp(prefix='kitty-platform-kit-', dir=home))
    print(json.dumps({'kit_directory': str(kit), 'source_commit': SOURCE_COMMIT,
                      'priority': 'low', 'collector_started': False}), flush=True)
    empty_home = kit / 'git-empty-home'
    empty_home.mkdir(mode=0o700)
    for path, size, expected in FILES:
        raw = blob_reader(repo, path, size, empty_home)
        verify_bytes(raw, size, expected)  # no write of unverified payload bytes
        parent = kit
        for part in Path(path).parts[:-1]:
            parent /= part
            parent.mkdir(mode=0o700, exist_ok=True)
        write_new(kit / path, raw)
    if any(empty_home.iterdir()):
        raise PacketError('unexpected-git-home-write')
    verify_kit(kit)
    output = home / ('kitty-platform-evidence-' + secrets.token_hex(8))
    delivery = {'source_commit': SOURCE_COMMIT, 'all_five_files_verified': True,
                'execution_requested': execute, 'collection_complete': False,
                'hardware_proven': False, 'files': [
                    {'path': p, 'bytes': n, 'sha256': h} for p, n, h in FILES]}
    write_new(kit / 'delivery.json', (json.dumps(delivery, indent=2) + '\n').encode())
    print(json.dumps({'delivery_verified': True, 'execution_requested': execute,
                      'kit_directory': str(kit), 'evidence_directory_if_run': str(output),
                      'note': 'delivery verification is not collection or compatibility proof'}), flush=True)
    if execute:
        verify_kit(kit)  # gate again immediately before handing off; never run test/docs files
        argv = ('/usr/bin/python3', '-I', '-B', str(kit / FILES[0][0]), '--output', str(output))
        environment = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8',
                       'TERM': 'dumb', 'NO_COLOR': '1'}
        executor(argv, environment, kit)
    return kit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, help='Local checkout only; defaults to HOME/Elaria')
    parser.add_argument('--run', action='store_true', help='Explicit scheduled owner choice to run after all gates pass')
    args = parser.parse_args()
    try:
        run_packet(args.repo, execute=args.run)
    except PacketError as exc:
        print(json.dumps({'stopped': True, 'reason': str(exc),
                          'action': 'stop and report; do not edit, retry gates away or clean up evidence'}))
        return 2
    except OSError:
        print(json.dumps({'stopped': True, 'reason': 'local-filesystem-or-exec-failure',
                          'action': 'stop and report; partial private kit may remain'}))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
