"""Fixed non-shell child of the dedicated Kitty instance; not a server or assistant.

stdin accepts ONLY a random request nonce. No echo, shell, eval, model or arbitrary argv.
Launch paths are daemon-generated private files; command effects stay inside ./work.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tty
from pathlib import Path


def load_contract():
    spec = importlib.util.spec_from_file_location('fixed_hands_contract', Path(__file__).with_name('contract.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.getuid() or info.st_nlink != 1):
            raise ValueError('unsafe-worker-request')
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('oversize-worker-request')
    return json.loads(raw)


def save(path, value):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream); stream.flush(); os.fsync(stream.fileno())
    os.rename(temporary, path)


def execute(value, root, inventory, nonces, emit):
    """No test transport here: fixed argv executes real mkdir/rmdir in the minted cwd only."""
    contract = load_contract()
    if hashlib.sha256(Path(inventory).read_bytes()).hexdigest() != contract.INVENTORY_SHA:
        raise ValueError('inventory-drift')
    contract.validate(value)
    steps = value['plan']['steps']
    if (len(nonces) != len(steps) or any(not re.fullmatch('[a-f0-9]{32}', n) for n in nonces)
            or len(set(nonces)) != len(nonces)):
        raise ValueError('invalid-markers')
    observations = []
    for step, proof, nonce in zip(steps, value['evidence'], nonces, strict=True):
        if (Path(root).parent / 'assistant.halt').exists():
            raise ValueError('halted-at-step-boundary')
        if hashlib.sha256(Path(inventory).read_bytes()).hexdigest() != contract.INVENTORY_SHA:
            raise ValueError('inventory-drift-before-step')
        if step['cwd'] != str(Path(root) / 'work'):
            raise ValueError('outside-instance-workspace')
        single = dict(value, plan={'steps': [dict(step, i=0)]}, evidence=[proof])
        contract.validate(single)
        binary = os.open(step['argv'][0], os.O_RDONLY | os.O_NOFOLLOW)
        cwd = os.open(step['cwd'], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with os.fdopen(os.dup(binary), 'rb') as stream:
                sha = hashlib.sha256(stream.read()).hexdigest()
            info = os.fstat(cwd)
            if sha != proof['binary_sha256'] or [info.st_dev, info.st_ino, info.st_mode, info.st_uid] != value['cwd_identity']:
                raise ValueError('preexec-identity-drift')
            completed = subprocess.run(step['argv'], executable=f'/proc/self/fd/{binary}',
                                       cwd=f'/proc/self/fd/{cwd}', pass_fds=(binary, cwd),
                                       env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(root)},
                                       stdin=subprocess.DEVNULL, capture_output=True, timeout=5, check=False)
        finally:
            os.close(binary); os.close(cwd)
        after = contract.target_state(Path(step['argv'][2]))
        row = {'nonce': nonce, 'exit_code': completed.returncode,
               'stdout_sha256': hashlib.sha256(completed.stdout).hexdigest(),
               'stderr_sha256': hashlib.sha256(completed.stderr).hexdigest(),
               'target_state': after, 'target_sha256': contract.digest(after)}
        observations.append(row)
        emit('ELARIA_OK_' + nonce)
        if completed.returncode != 0:
            break  # no automatic retry and no later chain segments after a failure
    return observations


def main():
    root, instance, boot_nonce, inventory = sys.argv[1:]
    root = Path(root)
    if root.resolve() != root or not re.fullmatch('[a-f0-9]{32}', instance + ''):
        return 2
    tty.setraw(0)  # disables input echo: seeing sent input cannot counterfeit marker readback
    save(root / 'ready.json', {'public_key': os.environ['KITTY_PUBLIC_KEY'], 'worker_pid': os.getpid()})
    os.environ.clear()
    emit = lambda text: os.write(1, (text + '\r\n').encode())
    emit('ELARIA_OK_' + boot_nonce)
    spent = set()
    while True:
        # readline under raw tty is bounded; no shell/terminal command is interpreted here.
        raw = sys.stdin.buffer.readline(80)
        if not raw:
            return 0
        nonce = raw.decode('ascii', errors='replace').strip()
        if not re.fullmatch('[a-f0-9]{32}', nonce) or nonce in spent:
            continue
        spent.add(nonce)
        try:
            request = read_private(root / (nonce + '.request.json'))
            rows = execute(request['value'], root, inventory, request['nonces'], emit)
            save(root / (nonce + '.result.json'), {'observations': rows})
        except Exception:
            save(root / (nonce + '.result.json'), {'observations': [], 'unknown': True})
        if len(spent) >= 256:
            return 0  # explicit bounded session; never restart/replay requests automatically


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.exit(2)  # no traceback/env/request contents in the terminal
