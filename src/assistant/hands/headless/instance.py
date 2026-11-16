"""F26 dedicated daemon-owned Kitty only. Never attach/discover/configure a daily terminal.

No --single-instance, shell, focus/window orchestration or new assistant daemon. Hardware
runtime is owner-only; local tests inject a recording instance, not a counterfeit success.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import subprocess
import time
from pathlib import Path

from ..kitty import policy
from ..kitty.checker import validate_payload
from ..kitty.transport import Transport, directory_fd
from .consent import private_dir, read_json, write_json
from .contract import digest, executable, target_state, validate


class DedicatedKitty:
    def __init__(self, runtime, instance):
        self.runtime, self.instance = Path(runtime), instance
        self.root = self.runtime / ('elaria-hands-' + instance)
        self.work = self.root / 'work'
        self.socket = self.runtime / ('elaria-hands-' + instance + '.sock')
        self.process = None
        self.transport = None
        self.pins = {}
        self.owned = {}
        self.fault = False
        self.audit = None

    def start(self):
        if self.process is not None or self.fault:
            raise ValueError('instance-already-started-or-faulted')
        policy.inventory()
        with directory_fd(self.runtime):
            private_dir(self.runtime)
        if self.root.exists() or self.socket.exists() or self.socket.is_symlink():
            raise ValueError('instance-path-already-exists')
        kitty, kitty_sha = executable('/usr/bin/kitty')
        python, python_sha = executable('/usr/bin/python3')
        version = subprocess.run([kitty, '--version'], capture_output=True, timeout=5,
                                 env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, check=False)
        if version.returncode or not version.stdout.startswith(b'kitty 0.47.1 '):
            raise ValueError('installed-kitty-version-not-inventory-version')
        private_dir(self.root); private_dir(self.work)
        password = secrets.token_urlsafe(36)
        passfile = self.root / 'rc-password'
        self._file(passfile, password.encode())
        config = self.root / 'kitty.conf'
        self._file(config, ('allow_remote_control password\nremote_control_password "' + password +
                           '" ls get-text send-text\nshell_integration disabled\nconfirm_os_window_close 0\n').encode())
        for name in ('worker.py', 'contract.py'):
            destination = self.root / name
            self._file(destination, Path(__file__).with_name(name).read_bytes())
            self.pins[str(destination)] = hashlib.sha256(destination.read_bytes()).hexdigest()
        self.pins[kitty], self.pins[python] = kitty_sha, python_sha
        boot_nonce = secrets.token_hex(16)
        self.child_argv = [python, '-IB', str(self.root / 'worker.py'), str(self.root),
                           self.instance, boot_nonce, str(policy.DATA / 'inventory.json')]
        argv = [kitty, '--config', str(config), '--listen-on', 'unix:' + str(self.socket),
                '--class', 'elaria-hands', '--title', '[ELARIA hands ' + self.instance + ']',
                '--directory', str(self.work), *self.child_argv]
        env = {key: os.environ[key] for key in ('DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR') if key in os.environ}
        env.update(PATH='/usr/bin:/bin', LANG='C.UTF-8', HOME=str(self.root), XDG_CONFIG_HOME=str(self.root))
        self.process = subprocess.Popen(argv, cwd=self.work, env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        close_fds=True, start_new_session=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                break
            if (self.root / 'ready.json').exists() and self.socket.exists():
                ready = read_json(self.root / 'ready.json')
                self.worker_pid = ready['worker_pid']
                self.transport = Transport(self.socket, self.runtime,
                                           {tier: passfile for tier in ('K1', 'K2', 'K3')},
                                           ready['public_key'], expected_pid=self.process.pid)
                self.window = self.window_id()
                if self.marker(boot_nonce):
                    return {'boot_marker': True, 'kitty_sha256': kitty_sha,
                            'worker_sha256': self.pins[str(self.root / 'worker.py')]}
                break
            time.sleep(.05)
        self.fault = True
        raise ValueError('dedicated-instance-start-unknown-no-retry')

    @staticmethod
    def _file(path, content):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())

    def rc(self, verb, payload, tier):
        catalogue = policy.inventory()
        validate_payload(policy.Act(verb, policy.canonical(payload)), catalogue)
        if self.audit is None:
            raise ValueError('verification-journal-unavailable')
        if tier == 'K1':
            self.audit(verb, 'attempt', None)
        result = self.transport.request(verb, payload, tier)
        if tier == 'K1':
            self.audit(verb, 'returned', digest(result))
        return result

    def window_id(self):
        if self.fault or self.process is None or self.process.poll() is not None:
            raise ValueError('dedicated-instance-not-live')
        policy.inventory()
        for path, expected in self.pins.items():
            if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
                raise ValueError('instance-executable-drift')
        tree = self.rc('ls', {}, 'K1')
        if isinstance(tree, str):
            tree = json.loads(tree)
        windows = [window for os_window in tree for tab in os_window['tabs'] for window in tab['windows']]
        if (len(windows) != 1 or windows[0].get('pid') != self.worker_pid
                or windows[0].get('cmdline') != self.child_argv
                or not windows[0].get('title', '').startswith('[ELARIA hands ' + self.instance)):
            raise ValueError('dedicated-target-identity-drift')
        return windows[0]['id']

    def marker(self, nonce):
        window = self.window_id()
        text = self.rc('get-text', {'match': 'id:' + str(window),
                                      'extent': 'all', 'ansi': False}, 'K1')
        return isinstance(text, str) and ('ELARIA_OK_' + nonce) in text.splitlines()

    def execute(self, value):
        validate(value)
        if any(step['cwd'] != str(self.work) for step in value['plan']['steps']):
            raise ValueError('foreign-workspace-refused')
        # Every send freshly binds process/socket/window identity; no daily-terminal target input.
        window = self.window_id()
        request = secrets.token_hex(16)
        nonces = [secrets.token_hex(16) for _ in value['plan']['steps']]
        write_json(self.root / (request + '.request.json'), {'value': value, 'nonces': nonces})
        try:
            self.rc('send-text', {'match': 'id:' + str(window), 'data': 'text:' + request + '\n',
                                   'exclude_active': False, 'bracketed_paste': 'disable'}, 'K2')
            deadline = time.monotonic() + 8
            result_path = self.root / (request + '.result.json')
            while not result_path.exists() and time.monotonic() < deadline and self.process.poll() is None:
                time.sleep(.05)
            rows = read_json(result_path).get('observations', [])
            if len(rows) != len(nonces):
                raise ValueError('incomplete-observation')
            for row, nonce, step, proof in zip(rows, nonces, value['plan']['steps'], value['evidence'], strict=True):
                if row['nonce'] != nonce or not self.marker(nonce):
                    raise ValueError('marker-absent')
                current = target_state(Path(step['argv'][2]))
                if row['target_state'] != current or row['target_sha256'] != digest(current):
                    raise ValueError('target-readback-drift')
                expected = 'empty-directory' if proof['verb'] == 'mkdir' else 'absent'
                row['verification'] = 'observed' if row['exit_code'] == 0 and current['state'] == expected else 'failed'
                name = Path(step['argv'][2]).name
                if row['verification'] == 'observed':
                    if proof['verb'] == 'mkdir':
                        self.owned[name] = row['target_sha256']
                    else:
                        self.owned.pop(name, None)
            return rows
        except Exception:
            self.fault = True  # outcome unknown; no implicit retry, fresh instance requires explicit owner action
            return [{'verification': 'unknown', 'exit_code': None, 'stdout_sha256': None,
                     'target_sha256': None, 'nonce': nonce} for nonce in nonces]

    def close(self):
        if self.process is not None and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL); self.process.wait(timeout=3)
        self.fault = True
        # Private runtime artifacts remain for inspection; no recursive cleanup of targets.
