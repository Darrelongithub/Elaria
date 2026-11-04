#!/usr/bin/env python3
"""Checksum-gated console launcher. No installs, daemon start, checkout or configuration edits.

Run from an existing environment with websockets 14–17. --check only checks the artifact,
dependency and existing daemon readiness; it performs no chat/model/voice call.
This starts a NEW explicit loopback-only server, NOT console/serve.py (which stays unchanged).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import importlib.metadata
import importlib.util
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

# Payload pins updated as part of the committed release, never repaired at runtime.
PAYLOAD_SHA256 = {
    'bridge.py': '265a351afd8e0dfb5452d33b6e7ce974522d6a992722782ddc52f8d1472cb2f3',
    'bridge-client.js': '2499ab87625c06cbb2691e616641b0c2d1ca3b24dfdabd9f3cd4abeb7c2538b4',
    'index.html': 'fe4154f502b918c9cfd0e1e5eb60c0107a339e30b3268e28726c2c68449afad9',
    'elaria-visualizer.js': '5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447',
    'requirements-bridge.txt': '933f7c32527437c77992e09403255a1a4d15078bd00d3200c7d62dad4c6b36ea',
}


def verify_assets(root):
    if not PAYLOAD_SHA256:
        raise ValueError('Release payload pins missing; refusing to launch')
    for name, expected in PAYLOAD_SHA256.items():
        file = root / name
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Checksum mismatch: {name}; stop, do not repair in place')
    version = importlib.metadata.version('websockets')
    if not 14 <= int(version.split('.')[0]) < 18:
        raise ValueError('Requires websockets >=14,<18; no automatic installation performed')
    if not hasattr(socket, 'SO_PEERCRED'):
        raise ValueError('This owner-authenticated launcher requires Linux SO_PEERCRED')
    return version


def window_size(value):
    match = re.fullmatch(r'([0-9]{3,4}),([0-9]{3,4})', value)
    if not match or not (320 <= int(match[1]) <= 8192 and 240 <= int(match[2]) <= 4320):
        raise argparse.ArgumentTypeError('window size must be W,H; W=320..8192, H=240..4320')
    return f'{int(match[1])},{int(match[2])}'


def browser_executable(explicit=None):
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            raise ValueError('--browser must name an absolute Chromium-compatible executable')
    else:
        found = next((p for name in ('google-chrome-stable', 'google-chrome',
                                    'chromium', 'chromium-browser')
                      if (p := shutil.which(name))), None)
        if not found:
            raise ValueError('No Chrome/Chromium found; use manual mode or --browser. No install.')
        path = Path(found)
    path = path.resolve(strict=True)
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Browser executable is not an executable regular file')
    return str(path)


def private_launch_files(parent, url, *, browser=False):
    # Never reuse a Chrome profile or overwrite an earlier launch link.
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('Daemon socket directory must be owner-owned and private (0700) '
                         'for launch files; no permissions are changed')
    directory = Path(tempfile.mkdtemp(prefix='elaria-console-', dir=parent))
    link = directory / 'open.html'
    fd = os.open(link, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        target = html.escape(url, quote=True)
        file.write('<!doctype html><meta charset="utf-8">'
                   '<meta name="referrer" content="no-referrer">'
                   f'<meta http-equiv="refresh" content="0;url={target}">'
                   '<title>Private Elaria launch link</title>'
                   f'<a href="{target}">Open this launch on this machine</a>')
    profile = None
    if browser:
        profile = directory / 'profile'
        profile.mkdir(mode=0o700)
    return link, profile


def detach_browser(executable, link, profile, size):
    # The private file redirects to THIS launch URL, keeping its token out of process argv too.
    # Fixed argv, no shell, no inherited terminal/server FDs, no credential/agent env.
    allowed = ('HOME', 'USER', 'LOGNAME', 'PATH', 'LANG', 'LC_ALL', 'LC_CTYPE',
               'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_RUNTIME_DIR',
               'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP', 'DBUS_SESSION_BUS_ADDRESS')
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    return subprocess.Popen(
        [executable, f'--app={link.as_uri()}', f'--user-data-dir={profile}', f'--window-size={size}',
         '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
         '--disable-sync', '--disable-component-update'],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env, close_fds=True, start_new_session=True)


async def reap_browser(process):
    # Nonblocking reaping only. Never wait in an executor (which can block asyncio shutdown),
    # and never terminate/kill the detached browser when the bridge stops.
    while process.poll() is None:
        await asyncio.sleep(0.5)
    print('Browser process exited; the bridge remains running.', flush=True)


async def run(module, root, args):
    runtime = os.environ.get('XDG_RUNTIME_DIR')
    if args.socket:
        path = Path(args.socket)
    elif runtime and Path(runtime).is_absolute():
        path = Path(runtime) / 'assistant.sock'
    else:
        raise ValueError('Set XDG_RUNTIME_DIR or explicitly supply --socket; no path guessing')
    if not path.is_absolute():
        raise ValueError('Daemon socket path must be absolute')
    bridge = module.Bridge(path, root, port=args.port)
    if args.check:
        problem = await bridge.probe()
        if problem:
            print('NOT READY: ' + problem)
            return 2
        print('PASS: artifacts pinned; owner IPC reachable; daemon reports live + online. '
              'No model, browser or audio proof claimed.')
        return 0
    executable = browser_executable(args.browser) if args.open else None
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    server = await bridge.start()
    browser_monitor = None
    try:
        async with server:
            url = f'{bridge.origin}/#pair={bridge.token}'
            link, profile = private_launch_files(path.parent, url, browser=args.open)
            if executable:
                process = detach_browser(executable, link, profile, args.window_size or '1440,900')
                browser_monitor = asyncio.create_task(reap_browser(process))
            print(f'Private launch file: {link}', flush=True)
            print('Open that local file on this machine if needed; keep it private. '
                  'No pairing token is printed. Old links expire when this bridge stops.', flush=True)
            if executable:
                print('Browser launch requested in a detached app window; appearance is not verified.',
                      flush=True)
            print('Loopback only; serve.py is NOT started. Text-only; levels are synthesised, '
                  'not measured audio.', flush=True)
            print('No model call until you send text. Ctrl-C stops only this bridge, not the daemon '
                  'or browser. Closing the browser does not stop the bridge.', flush=True)
            await stopped.wait()
    finally:
        if browser_monitor:
            browser_monitor.cancel()
            await asyncio.gather(browser_monitor, return_exceptions=True)
        if bridge.busy or bridge.uncertain:
            print('WARNING: a daemon turn may still complete. Inspect conversation; do not replay.')
        await bridge.shutdown()
    # Do not remove a profile underneath a still-running detached browser. Runtime files
    # remain private; their cleanup is a separate explicit action after both processes stop.

    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', help='Explicit existing owner daemon socket; absolute path')
    parser.add_argument('--port', type=int, default=8744, help='Loopback port (default 8744)')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Verify only; no web server or chat turn')
    mode.add_argument('--open', action='store_true', help='Launch a detached Chrome/Chromium app window')
    parser.add_argument('--browser', help='With --open: absolute Chromium-compatible executable')
    parser.add_argument('--window-size', type=window_size,
                        help='With --open: W,H in pixels (default 1440,900; window manager may override)')
    args = parser.parse_args()
    if (args.browser or args.window_size) and not args.open:
        parser.error('--browser and --window-size require --open')
    if not 1024 <= args.port <= 65535:
        parser.error('port must be 1024..65535')
    root = Path(__file__).resolve().parent
    try:
        verify_assets(root)
        # Load only the pinned sibling. Never import a second assistant implementation.
        spec = importlib.util.spec_from_file_location('elaria_console_bridge', root / 'bridge.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return asyncio.run(run(module, root, args))
    except (OSError, ValueError, ImportError, importlib.metadata.PackageNotFoundError) as exc:
        print('STOP: console bridge preflight failed (' + type(exc).__name__ + ').', file=sys.stderr)
        # Known preflight reasons only: no API error, credentials, owner text or socket contents.
        if isinstance(exc, ValueError):
            print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
