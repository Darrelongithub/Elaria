"""F26 startup argv/env and per-connect PID tests. No real Kitty or compositor invoked."""
import hashlib
import os
import socket
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from test_kitty_hands import private as private  # noqa: PLC0414 -- secure socket fixture

from assistant.hands.headless import instance as native
from assistant.hands.headless.consent import write_json
from assistant.hands.kitty import transport


def test_dedicated_start_is_fixed_non_shell_child_private_env_socket_cwd(tmp_path, monkeypatch):
    runtime = tmp_path / 'dedicated-runtime'; runtime.mkdir(mode=0o700)
    obj = native.DedicatedKitty(runtime, 'a' * 32)
    calls = []
    obj.audit = lambda *args: calls.append(('audit', args))
    monkeypatch.setenv('KITTY_LISTEN_ON', '/daily-terminal/never-use')
    monkeypatch.setenv('KITTY_RC_PASSWORD', 'synthetic-never-inherit')
    monkeypatch.setenv('SSH_AUTH_SOCK', '/never/agent')
    monkeypatch.setenv('GEMINI_API_KEY', 'synthetic-never-inherit')
    monkeypatch.setenv('WAYLAND_DISPLAY', 'synthetic-wayland')

    @contextmanager
    def directories(_path):
        yield None  # /tmp fixture ONLY; real transport tests reject /tmp

    monkeypatch.setattr(native, 'directory_fd', directories)
    monkeypatch.setattr(native, 'executable', lambda path: (path, hashlib.sha256(path.encode()).hexdigest()))
    monkeypatch.setattr(native.subprocess, 'run', lambda argv, **kw: SimpleNamespace(returncode=0, stdout=b'kitty 0.47.1 created by Kovid Goyal'))

    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        obj.socket.touch()  # transport is stubbed; do not claim this regular file passes real socket checks
        write_json(obj.root / 'ready.json', {'worker_pid': 456, 'public_key': 'synthetic-public-key'})
        return SimpleNamespace(pid=123, poll=lambda: None)

    monkeypatch.setattr(native.subprocess, 'Popen', popen)
    monkeypatch.setattr(native, 'Transport', lambda *args, **kwargs: calls.append(('transport', args, kwargs)))
    monkeypatch.setattr(obj, 'window_id', lambda: 17)
    monkeypatch.setattr(obj, 'marker', lambda nonce: len(nonce) == 32)
    result = obj.start()
    argv, options = calls[0]
    assert argv[0] == '/usr/bin/kitty' and '--single-instance' not in argv and '--detach' not in argv
    assert argv[argv.index('--listen-on') + 1] == 'unix:' + str(obj.socket)
    assert options['cwd'] == obj.work and options['start_new_session'] and options['close_fds']
    assert set(options['env']) <= {'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_RUNTIME_DIR', 'PATH', 'LANG', 'HOME', 'XDG_CONFIG_HOME'}
    assert options['env']['HOME'] == str(obj.root)
    assert obj.child_argv[:2] == ['/usr/bin/python3', '-IB']
    assert obj.root.joinpath('kitty.conf').stat().st_mode & 0o777 == 0o600
    assert 'allow_remote_control password' in obj.root.joinpath('kitty.conf').read_text()
    assert 'ls get-text send-text' in obj.root.joinpath('kitty.conf').read_text()
    assert calls[1][2]['expected_pid'] == 123 and result['boot_marker']
    assert 'synthetic-never-inherit' not in repr(calls)
    monkeypatch.delenv('GEMINI_API_KEY')  # shared fixture invariant


def test_wrong_same_uid_peer_pid_refused_before_any_payload(private, monkeypatch):
    path = private / 'rc.sock'
    password = private / 'password'; password.write_text('synthetic'); password.chmod(0o600)
    monkeypatch.setattr(transport, 'encrypt', lambda *_a: b'NEVER-SEND')
    listener = socket.socket(socket.AF_UNIX); listener.bind(str(path)); listener.listen(1)
    try:
        rc = transport.Transport(path, private, {k: password for k in ('K1', 'K2', 'K3')},
                                 'synthetic', expected_pid=os.getpid() + 100000)
        with pytest.raises(transport.TransportError):
            rc.request('ls', {}, 'K1')
        conn, _ = listener.accept()
        with conn:
            assert conn.recv(64) == b''
    finally:
        listener.close()


def test_start_missing_binary_never_falls_back_to_daily_terminal(tmp_path, monkeypatch):
    obj = native.DedicatedKitty(tmp_path, 'a' * 32)
    monkeypatch.setattr(native, 'executable', lambda _p: (_ for _ in ()).throw(FileNotFoundError()))
    @contextmanager
    def directories(_p):
        yield None
    monkeypatch.setattr(native, 'directory_fd', directories)
    tmp_path.chmod(0o700)
    with pytest.raises(FileNotFoundError):
        obj.start()
    assert obj.process is None and not obj.root.exists()
