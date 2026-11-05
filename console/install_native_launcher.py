#!/usr/bin/python3
"""Explicit owner-side v4 installer; default is verify-only. Never edits hyprland.lua.

No sudo, dnf, fetch, branch change, service control or launch is performed by this installer.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import stat
import sys
import tempfile
from pathlib import Path

# Updated only with a committed release, alongside the handoff's installer checksum.
PINS = {'native_launch.py': 'abe107748dc65b1cd6784fe093a348c7d43999273d26cbdec5413518619c2b44', 'native_window.py': 'e29800e8201e00b34b3d9c73af6b700f085da6ed50c69dcacbe16c0d4aa4771e', 'elaria-console-launch.sh': '8c86ca34bb2aa15fb0f38e40a15e11200def5d3cd046bf3a34aa90e9a47e9da5'}
OWNER_HOME = Path('/home/darrel')


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


def install(root, home=OWNER_HOME):
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
    targets = {bundle / 'native_launch.py': content['native_launch.py'],
               bundle / 'native_window.py': content['native_window.py'],
               hypr / 'elaria-console-launch.sh': content['elaria-console-launch.sh']}
    for target in targets:
        if target.is_symlink() or (target.exists() and
                (not target.is_file() or target.stat().st_uid != os.getuid() or target.stat().st_nlink != 1)):
            raise ValueError('STOP: unsafe existing install target; no replacement.')
    # Shim last. Interrupted helper updates can only mismatch/stop, not run unpinned code.
    for target, data in targets.items():
        replace_file(target, data)
    for directory in (bundle, hypr):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='Explicitly replace the fixed owner bind target')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parent
    try:
        if args.install:
            install(root)
            print('Installed native v4 bind target and private helpers; no config edit or window launch.')
        else:
            verified_sources(root)
            print('PASS: native installer payload pins only; nothing installed or launched.')
        return 0
    except Exception:
        print('STOP: native install verification/ownership failed; no fallback or auto-repair.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
