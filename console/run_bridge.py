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
import importlib.metadata
import importlib.util
import os
import signal
import socket
import sys
from pathlib import Path

# Payload pins updated as part of the committed release, never repaired at runtime.
PAYLOAD_SHA256 = {
    'bridge.py': '4223ea9801b357a2806daa7a640884e7939696d5ffbd52366684cadd4926f1d9',
    'bridge-client.js': '0d596baaa0a94478102ddeba36d9e2b165a30fd76b84181200e5c59c519c1420',
    'index.html': '04c71a22b3ee9dc5a1f1a5bd26aa8cf3e1ac1b4dd9b761968e68e2c6d3c395e9',
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
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)
    server = await bridge.start()
    print(f'Private console URL: {bridge.origin}/#pair={bridge.token}', flush=True)
    print('Keep this local pairing URL private. Loopback only; serve.py is NOT started.', flush=True)
    print('Text-only. Levels are synthesised, NOT measured. Other panes retain their labels.',
          flush=True)
    print('No model call until you send text. Ctrl-C stops this bridge, not the daemon.', flush=True)
    try:
        async with server:
            await stopped.wait()
    finally:
        if bridge.busy or bridge.uncertain:
            print('WARNING: a daemon turn may still complete. Inspect conversation; do not replay.')
        await bridge.shutdown()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', help='Explicit existing owner daemon socket; absolute path')
    parser.add_argument('--port', type=int, default=8744, help='Loopback port (default 8744)')
    parser.add_argument('--check', action='store_true', help='Verify only; no web server or chat turn')
    args = parser.parse_args()
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
