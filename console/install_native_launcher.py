#!/usr/bin/python3
"""Explicit owner-side v4 installer; default is verify-only. Never edits hyprland.lua.

No sudo, dnf, fetch, branch change, service control or launch is performed by this installer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

# Updated only with a committed release, alongside the handoff's installer checksum.
PINS = {'native_launch.py': '1f575357774f3eade4fdf7cdc69ee36f2f3998ff94c61f77ab84f28bcbf56bb8', 'native_window.py': 'e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e', 'elaria-console-launch.sh': '1a7a54a763039d296111c6ebd843b2f9f79f6152d595ae71fb4ea18293fb0413'}
OWNER_HOME = Path('/home/darrel')
BIND_TARGET = OWNER_HOME / '.config/hypr/elaria-console-launch.sh'


def verified_sources(root):
    if len(PINS) != 3:
        raise ValueError('STOP: incomplete native installer release pins.')
    result = {}
    for name, expected in PINS.items():
        file = root / name
        info = file.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
            raise ValueError('STOP: native install source is not a bounded regular file.')
        content = file.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError('STOP: native install source checksum mismatch.')
        result[name] = content
    return result


def owned_directory(path, *, create=False):
    if path.resolve() != path:
        raise ValueError('STOP: symlinked install directory refused.')
    if create and not path.exists():
        path.mkdir(mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('STOP: install directory must be owner-owned and not group/world writable.')


def replace_file(destination, content):
    try:
        info = destination.lstat()
    except FileNotFoundError:
        info = None
    if info and (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1):
        raise ValueError('STOP: unsafe existing install target; no replacement.')
    fd, temporary = tempfile.mkstemp(prefix='.native-install-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            os.fchmod(file.fileno(), 0o700)
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def targets_for(home):
    return {home / '.config/elaria-console-native-v4/native_launch.py': 'native_launch.py',
            home / '.config/elaria-console-native-v4/native_window.py': 'native_window.py',
            home / '.config/hypr/elaria-console-launch.sh': 'elaria-console-launch.sh'}


def installed_digest(path, expected):
    # Check the actual installed inode/bytes, not source bytes or mere path existence.
    owned_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o700 or info.st_size > 1024 * 1024):
            raise ValueError('installed file must be owned, single-link, regular, mode 0700 and bounded: ' + str(path))
        digest = hashlib.sha256(file.read(1024 * 1024 + 1)).hexdigest()
    if digest != expected:
        raise ValueError('installed checksum mismatch: ' + str(path))
    return digest


def check_installed(home=OWNER_HOME, report=None):
    """Inspect every fixed target independently; missing is not a verification error.

    Exit 3 describes current absence, never historical proof of 'never installed'.
    Invalid/unreadable targets take precedence over absence or partial installation.
    """
    rows = []
    for path, name in targets_for(home).items():
        row = {'path': str(path), 'expected': PINS[name]}
        try:
            owned_directory(home)
            owned_directory(home / '.config')
            owned_directory(path.parent)
            if name != 'elaria-console-launch.sh' and stat.S_IMODE(path.parent.stat().st_mode) != 0o700:
                raise ValueError('native bundle directory must be private 0700: ' + str(path.parent))
            digest = installed_digest(path, PINS[name])
        except FileNotFoundError as exc:
            # A dangling symlink is invalid, not absent: owned_directory and
            # O_NOFOLLOW reject those before this branch can call it missing.
            row.update(status='MISSING', reason=('target_file_absent' if exc.filename == str(path)
                                                else 'target_directory_absent'))
        except (OSError, ValueError) as exc:
            row.update(status='INVALID', reason=f'{type(exc).__name__}: {exc}')
        else:
            row.update(status='VERIFIED', sha256=digest)
            if report:
                report('VERIFIED', path, digest)
        rows.append(row)
    missing = sum(row['status'] == 'MISSING' for row in rows)
    invalid = sum(row['status'] == 'INVALID' for row in rows)
    code = 2 if invalid else 3 if missing == 3 else 4 if missing else 0
    return {'exit': code, 'rows': rows, 'verified': 3 - missing - invalid,
            'missing': missing, 'invalid': invalid}


def report_installed_check(result):
    for row in result['rows']:
        if row['status'] != 'VERIFIED':
            print(f"{row['status']} path={row['path']} reason={row['reason']}",
                  file=sys.stderr if row['status'] == 'INVALID' else sys.stdout, flush=True)
    code = result['exit']
    counts = (f"completed file receipts={result['verified']} missing={result['missing']} "
              f"invalid={result['invalid']}")
    if code == 0:
        print('PASS exit=0: 3 installed files verified; read-only, nothing written. This does not prove the active bind.', flush=True)
    elif code == 3:
        reasons = {row['reason'] for row in result['rows']}
        reason = next(iter(reasons)) if len(reasons) == 1 else 'all_targets_absent'
        print(f'NOT_INSTALLED exit=3 reason={reason}; {counts}. '
              'All three targets are absent now; prior installation history is unknown. '
              'Read-only, nothing written; no rollback/fallback.', flush=True)
    elif code == 4:
        print(f'PARTIAL_INSTALL exit=4 reason=some_targets_absent; {counts}. '
              'Partial writes may remain from an earlier install; read-only, nothing written; '
              'no rollback/fallback.', flush=True)
    else:
        print(f'STOP exit=2 action=check-installed reason=installed_state_invalid; {counts}. '
              'Partial writes may remain from an earlier install; read-only, nothing written; '
              'no rollback/fallback. See every target verdict above.', file=sys.stderr, flush=True)
    return code


def emit_bind():
    # Lua-only 0.57 expression; emit, never append, rewrite configuration or reload.
    return 'hl.bind(' + json.dumps('SUPER + SPACE') + ', hl.dsp.exec_cmd(' + json.dumps(str(BIND_TARGET)) + '))'


def install(root, home=OWNER_HOME, report=None):
    # This function takes a test-only path argument; CLI deliberately exposes no target override.
    content = verified_sources(root)
    owned_directory(home)
    config = home / '.config'
    owned_directory(config, create=True)
    hypr = config / 'hypr'
    owned_directory(hypr, create=True)
    bundle = config / 'elaria-console-native-v4'
    owned_directory(bundle, create=True)
    if stat.S_IMODE(bundle.stat().st_mode) != 0o700:
        raise ValueError('STOP: native bundle directory must be private 0700; no chmod fallback.')
    # Gate every existing destination BEFORE changing any installed payload.
    targets = {path: content[name] for path, name in targets_for(home).items()}
    for target in targets:
        if target.is_symlink() or (target.exists() and
                (not target.is_file() or target.stat().st_uid != os.getuid() or target.stat().st_nlink != 1)):
            raise ValueError('STOP: unsafe existing install target; no replacement.')
    # Shim last. Interrupted helper updates can only mismatch/stop, not run unpinned code.
    for target, data in targets.items():
        replace_file(target, data)
        digest = installed_digest(target, hashlib.sha256(data).hexdigest())
        if report:
            report('WRITTEN', target, digest)
    for directory in (bundle, hypr):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    result = check_installed(home)  # recheck all targets after directory durability barriers
    if result['exit']:
        problems = [row for row in result['rows'] if row['status'] != 'VERIFIED']
        raise ValueError('final installed readback failed: ' + json.dumps(problems, sort_keys=True))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--install', action='store_true', help='Explicitly replace the fixed owner bind target')
    mode.add_argument('--check-installed', action='store_true', help='Read-only: verify fixed installed paths, hashes and modes')
    mode.add_argument('--emit-bind', action='store_true', help='Print only the generated one-line Lua bind; no config write/reload')
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code:
            print('STOP exit=2: invalid arguments; no install attempted.', file=sys.stderr, flush=True)
        raise
    root = Path(__file__).resolve().parent
    receipts = []

    def report(verb, path, digest):
        receipts.append(path)
        print(f'{verb} path={path} sha256={digest} mode=0700', flush=True)

    action = 'install' if args.install else 'check-installed' if args.check_installed else 'verify-source'
    try:
        if args.emit_bind:
            print(emit_bind(), flush=True)
            return 0
        print(f'START action={action}; no config edit, reload or window launch.', flush=True)
        if args.install:
            install(root, home=OWNER_HOME, report=report)
            print('PASS exit=0: 3 installed files verified; no config edit or reload. Bind verification is a separate step.', flush=True)
        elif args.check_installed:
            return report_installed_check(check_installed(home=OWNER_HOME, report=report))
        else:
            verified_sources(root)
            print('PASS exit=0: native installer payload pins only; nothing installed or launched.', flush=True)
        return 0
    except Exception as exc:
        next_step = ('Use --check-installed for read-only installed state.' if args.install
                     else 'Read-only operation failed; no install attempted.')
        print(f'STOP exit=2 action={action}: {type(exc).__name__}: {exc}; '
              f'completed file receipts={len(receipts)}. Partial writes may remain if install began; '
              f'no rollback/fallback. {next_step}', file=sys.stderr, flush=True)
        return 2


if __name__ == '__main__':
    sys.exit(main())
