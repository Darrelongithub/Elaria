#!/usr/bin/env python3
"""Fedora/OpenSSH metadata collector. BUILT FOR REVIEW; NOT AUTHORISED FOR OWNER RUN.

No RC acts/connections, owner kitty/SSH config reads, shell, installs or executable overrides.
Python stdlib only; fixed system query/decompression binaries must already exist.
Exit 0 = collection complete, NOT compatible, reconciled, semantic or hardware proof.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

PACKAGES = ('kitty', 'kitty-kitten', 'kitty-shell-integration', 'kitty-terminfo',
            'openssh', 'openssh-clients')
COMMANDS = (
    ('kitty-version', ('/usr/bin/kitty', '--version')),
    ('binary-owners', ('/usr/bin/rpm', '-qf', '/usr/bin/kitty', '/usr/bin/kitten', '/usr/bin/ssh')),
    ('package-versions', ('/usr/bin/rpm', '-q', *PACKAGES)),
    *((f'files-{p}', ('/usr/bin/rpm', '-ql', p)) for p in PACKAGES),
    ('ssh-version', ('/usr/bin/ssh', '-V')),
    ('ssh-usage', ('/usr/bin/ssh',)),
    ('ssh-query-categories', ('/usr/bin/ssh', '-Q', 'help')),
)
DECOMPRESSORS = {
    '.gz': ('/usr/bin/gzip', '-cd'),
    '.bz2': ('/usr/bin/bzip2', '-dc'),
    '.xz': ('/usr/bin/xz', '-dc', '--memlimit-decompress=64MiB'),
    '.zst': ('/usr/bin/zstd', '-dc', '--memory=64MB'),
}
PAGES = {'ssh': 'man1/ssh.1', 'ssh_config': 'man5/ssh_config.5'}
MAN_ROOT = Path('/usr/share/man')
TIMEOUT = 20
OUTPUT_LIMIT = 2 * 1024 * 1024  # stdout + stderr per process
DOCUMENT_LIMIT = 2 * 1024 * 1024  # compressed input and plain documents


class DocumentError(ValueError):
    """Only internal, fixed diagnostic codes; never a subprocess/OS exception message."""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def run_command(argv, *, cwd, environment, input_data=None):
    """Bound time AND captured bytes. Input is only verified package-document bytes.

Never use communicate() with unlimited output, a shell, inherited stdin or environment.
On failure kill the private process group and bound the reap wait. Partial output is
retained with an explicit error; it is not parsed as successful membership/evidence.
"""
    result = {'argv': list(argv), 'returncode': None, 'stdout': '', 'stderr': '',
              'error': None, 'truncated': False}
    buffers = {'stdout': bytearray(), 'stderr': bytearray()}
    proc = None
    selector = selectors.DefaultSelector()
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                                env=environment, start_new_session=True, close_fds=True, umask=0o077)
        for name in buffers:
            pipe = getattr(proc, name)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        sent = 0
        if input_data is not None:
            os.set_blocking(proc.stdin.fileno(), False)
            selector.register(proc.stdin, selectors.EVENT_WRITE, 'stdin')
        deadline = time.monotonic() + TIMEOUT
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, TIMEOUT)
            for key, _ in selector.select(min(remaining, 0.2)):
                if key.data == 'stdin':
                    try:
                        if sent < len(input_data):
                            sent += os.write(key.fd, input_data[sent:sent + 65536])
                        if sent == len(input_data):
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                    except BrokenPipeError:
                        selector.unregister(key.fileobj)
                        key.fileobj.close()
                        result['error'] = 'input-pipe-closed'
                    continue
                available = OUTPUT_LIMIT - sum(map(len, buffers.values()))
                chunk = os.read(key.fd, min(65536, available + 1))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                buffers[key.data].extend(chunk[:available])
                if len(chunk) > available:
                    result['truncated'] = True
                    raise OverflowError('bounded-output')
        proc.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        result['error'] = 'timeout'
    except OverflowError:
        result['error'] = 'output-limit'
    except OSError as exc:
        result['error'] = type(exc).__name__  # no environment/path/exception-content dump
    finally:
        selector.close()
        if proc is not None:
            # Also kill descendants if the leader exited while its pipes stayed open.
            if result['error'] is not None or proc.poll() is None:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    result['error'] = 'reap-timeout'
            result['returncode'] = proc.poll()
            for name in ('stdin', 'stdout', 'stderr'):
                pipe = getattr(proc, name)
                if pipe is not None:
                    pipe.close()
        for name, value in buffers.items():
            result[name] = value.decode('utf-8', errors='replace')
    return result


def directory_fd(path):
    """Open every directory component without following symlinks."""
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('absolute non-traversing directory required')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


class EvidenceDirectory:
    """Only a new direct child of HOME. No recursive parent creation or cleanup."""
    def __init__(self, path):
        path, home = Path(path), Path.home()
        if (not path.is_absolute() or path.parent != home or path.name in {'', '.', '..'}):
            raise ValueError('output must be a NEW direct child of HOME')
        parent = directory_fd(home)
        try:
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise PermissionError('HOME must be owned and not group/world writable')
            os.mkdir(path.name, mode=0o700, dir_fd=parent)  # existing, including symlink: refuse
            fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        finally:
            os.close(parent)
        self.fd, self.path = fd, path
        try:
            os.mkdir('empty-home', mode=0o700, dir_fd=fd)
        except BaseException:
            os.close(fd)
            raise

    def write(self, name, record):
        if '/' in name or not name.endswith('.json'):
            raise ValueError('fixed evidence filename required')
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=self.fd)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(record, handle, ensure_ascii=True, allow_nan=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(self.fd)

    def close(self):
        os.close(self.fd)


def document_candidates(membership, basename):
    """Only exact, unlocalized system manual paths. No .so/include traversal or rendering."""
    permitted = {str(MAN_ROOT / basename) + suffix for suffix in ('', *DECOMPRESSORS)}
    return sorted(set(membership) & permitted)


def read_document(member, *, root=MAN_ROOT, owner_uid=0):
    """The caller first requires successful OpenSSH RPM membership. No arbitrary read API in CLI.

root/owner_uid are test seams, never CLI inputs. Production accepts root-owned, regular,
single-link, non-group/world-writable package documentation only; all symlinks refuse.
"""
    allowed = {str(MAN_ROOT / base) + suffix for base in PAGES.values() for suffix in ('', *DECOMPRESSORS)}
    if member not in allowed:
        raise PermissionError('not an approved manual path')
    relative = Path(member).relative_to(MAN_ROOT)
    fd = directory_fd(root / relative.parent)
    try:
        info = os.fstat(fd)
        if info.st_uid != owner_uid or info.st_mode & 0o022:
            raise PermissionError('untrusted manual directory')
        source = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            before = os.fstat(source)
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner_uid
                    or before.st_mode & 0o022 or before.st_nlink != 1
                    or before.st_size > DOCUMENT_LIMIT):
                raise DocumentError('untrusted-or-oversized-manual')
            chunks, size = [], 0
            while chunk := os.read(source, min(65536, DOCUMENT_LIMIT + 1 - size)):
                chunks.append(chunk)
                size += len(chunk)
                if size > DOCUMENT_LIMIT:
                    raise DocumentError('manual-grew-beyond-limit')
            after = os.fstat(source)
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns) or size != after.st_size:
                raise DocumentError('manual-changed-during-read')
            return b''.join(chunks)
        finally:
            os.close(source)
    finally:
        os.close(fd)


def collect(output, *, runner=run_command, reader=read_document):
    """No host probes in tests: inject synthetic runner and package-doc reader."""
    evidence = EvidenceDirectory(output)
    findings, commands, manuals = [], {}, {}
    # Do not inherit HOME, XDG*, KITTY*, SSH_AUTH_SOCK, loader variables, proxy or API keys.
    # RPM may consult per-user macros; point it at this new empty, private home instead.
    environment = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'TERM': 'dumb', 'NO_COLOR': '1',
                   'HOME': str(evidence.path / 'empty-home'),
                   'XDG_CONFIG_HOME': str(evidence.path / 'empty-home')}
    membership = set()
    try:
        for name, argv in COMMANDS:
            record = runner(argv, cwd=evidence.path / 'empty-home', environment=environment)
            evidence.write(name + '.json', record)
            commands[name] = name + '.json'
            expected_code = 255 if name == 'ssh-usage' else 0
            ok = (record['error'] is None and not record['truncated']
                  and record['returncode'] == expected_code
                  and bool(record['stdout'].strip() or record['stderr'].strip()))
            if name == 'ssh-usage' and 'usage: ssh ' not in record['stderr']:
                ok = False
            if not ok:
                findings.append({'instrument': name, 'reason': 'query-incomplete-or-unexpected-result'})
            if ok and name in {'files-openssh', 'files-openssh-clients'}:
                membership.update(record['stdout'].splitlines())
        for name, base in PAGES.items():
            candidates = document_candidates(membership, base)
            record = {'path': None, 'status': 'unavailable', 'source_sha256': None,
                      'text_sha256': None, 'text': None, 'decompression': None}
            if len(candidates) != 1:
                record['reason'] = 'missing-or-ambiguous-package-document'
            else:
                member = candidates[0]
                record['path'] = member
                try:
                    raw = reader(member)
                    if len(raw) > DOCUMENT_LIMIT:
                        raise DocumentError('manual-input-limit')
                    record['source_sha256'] = hashlib.sha256(raw).hexdigest()
                    suffix = next((s for s in DECOMPRESSORS if member.endswith(s)), '')
                    if suffix:
                        decoded = runner(DECOMPRESSORS[suffix], cwd=evidence.path / 'empty-home',
                                         environment=environment, input_data=raw)
                        record['decompression'] = decoded
                        if decoded['error'] is not None or decoded['truncated'] or decoded['returncode'] != 0:
                            raise DocumentError('decompression-failed')
                        text = decoded['stdout']
                    else:
                        text = raw.decode('utf-8', errors='strict')
                    if not text.strip() or '\ufffd' in text or '\x00' in text:
                        raise DocumentError('manual-text-invalid')
                    # Keep raw roff as documentation; never follow .so, run troff or invoke a pager.
                    if any(re.match(r"[.'](?:so|mso)(?:\s|$)", line.lstrip()) for line in text.splitlines()):
                        raise DocumentError('manual-include-unresolved')
                    record.update(status='collected', text=text,
                                  text_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest())
                except DocumentError as exc:
                    record['reason'] = exc.reason
                except (OSError, ValueError) as exc:
                    record['reason'] = type(exc).__name__  # private paths/content cannot leak through errors
            if record['status'] != 'collected':
                findings.append({'instrument': name + '-manual', 'reason': record['reason']})
            evidence.write(name + '-manual.json', record)
            manuals[name] = name + '-manual.json'
        # A positive environment is isolation from personal settings, not an OS sandbox.
        # Unexpected writes within the empty child home are findings, never cleaned up.
        child_home_changed = any((evidence.path / 'empty-home').iterdir())
        if child_home_changed:
            findings.append({'instrument': 'empty-home', 'reason': 'unexpected-child-home-write'})
        report = {'schema_version': 1, 'instrument': 'kitty-platform-metadata/v1',
                  'python_version': sys.version.split()[0], 'child_home_changed': child_home_changed,
                  'collection_complete': not findings, 'compatibility_verified': False,
                  'hardware_proven': False, 'requires_manual_reconciliation': True,
                  'source_pin': 'upstream kitty 0.47.1', 'owner_design_package_pin': '0.47.1-1.fc44',
                  'commands': commands, 'manuals': manuals, 'findings': findings,
                  'not_inspected': ['owner-kitty-config', 'effective-settings', 'rc-sockets',
                                    'owner-ssh-config', 'keys', 'agents', 'terminal-content',
                                    'downstream-patch-equivalence', 'rpm-file-integrity', 'binary-content-identity'],
                  'limits': {'query_count': len(COMMANDS), 'max_decompression_calls': len(PAGES),
                             'seconds_per_process': TIMEOUT, 'reap_seconds': 2,
                             'bytes_per_process': OUTPUT_LIMIT, 'bytes_per_document_input': DOCUMENT_LIMIT}}
        evidence.write('report.json', report)
        return report
    finally:
        evidence.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='NEW direct child of HOME; no parent creation, repair or cleanup')
    args = parser.parse_args()
    try:
        report = collect(args.output)
    except (OSError, ValueError) as exc:
        print(json.dumps({'collection_complete': False, 'error': type(exc).__name__,
                          'note': 'partial evidence may remain; no cleanup or overwrite performed'}))
        return 2
    print(json.dumps(report, indent=2))
    return 0 if report['collection_complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
