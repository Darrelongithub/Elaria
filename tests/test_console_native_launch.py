"""Task E local-only tests. Temporary repos/processes, synthetic IPC; no owner install or GUI."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_v4_test', ROOT / 'console/native_launch.py')
v4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v4)


def paths_at(tmp_path):
    runtime = tmp_path / 'private-runtime'
    runtime.mkdir(mode=0o700)
    bundle = tmp_path / 'native-bundle'
    bundle.mkdir(mode=0o700)
    return v4.Paths(tmp_path / 'repo', tmp_path / 'worktree', Path(sys.executable),
                    Path(sys.executable), bundle / 'native_window.py', runtime, tmp_path / 'launch.log')


def git(repo, *args):
    return subprocess.check_output(['/usr/bin/git', '-c', 'protocol.allow=never',
                                    '-C', str(repo), *args], stderr=subprocess.DEVNULL)


def tiny_repo(paths, monkeypatch):
    paths.repo.mkdir()
    git(paths.repo, 'init', '--initial-branch=arena/b65d5161-elaria')
    script = paths.repo / 'console/run_bridge.py'
    script.parent.mkdir()
    script.write_text('PAYLOAD_SHA256 = {}\n')
    script.chmod(0o755)
    git(paths.repo, 'add', '.')
    git(paths.repo, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
        'commit', '-m', 'synthetic local recovery fixture')
    commit = git(paths.repo, 'rev-parse', 'HEAD').decode().strip()
    monkeypatch.setattr(v4, 'COMMIT', commit)
    monkeypatch.setattr(v4, 'BRIDGE_SHA', hashlib.sha256(script.read_bytes()).hexdigest())


def test_release_constants_remain_exact_owner_ruling():
    assert v4.COMMIT == 'fcd55ca1bce34d8a1f479bf2d035cc866c4a482f'
    assert v4.BRIDGE_SHA == 'ed227a7d50effb874e303f95462f3dc127c9bd79a71a8d9b34f86980815b091c'
    assert v4.NATIVE_SHA == hashlib.sha256((ROOT / 'console/native_window.py').read_bytes()).hexdigest()
    paths = v4.owner_paths()
    assert str(paths.repo) == '/home/darrel/Elaria' and str(paths.worktree) == '/tmp/elaria-bridge'
    assert str(paths.log) == '/tmp/elaria-launch.log'


def test_missing_then_reboot_missing_worktree_recovers_local_objects_only(tmp_path, monkeypatch):
    paths = paths_at(tmp_path)
    tiny_repo(paths, monkeypatch)
    log = v4.private_fd(paths.log)
    try:
        original = git(paths.repo, 'rev-parse', 'HEAD')
        v4.ensure_worktree(paths, log)
        assert git(paths.worktree, 'rev-parse', 'HEAD') == original
        other = paths.worktree.parent / 'other-missing-worktree'
        git(paths.repo, 'worktree', 'add', '--detach', str(other), v4.COMMIT)
        shutil.rmtree(other)
        shutil.rmtree(paths.worktree)  # synthetic /tmp reboot loss; registration deliberately remains
        v4.ensure_worktree(paths, log)
        assert git(paths.worktree, 'rev-parse', 'HEAD') == original
        assert git(paths.repo, 'rev-parse', 'HEAD') == original
        assert ('worktree ' + str(other)).encode() in git(paths.repo, 'worktree', 'list', '--porcelain')
        assert git(paths.worktree, 'status', '--porcelain') == b''
        assert b'protocol.allow=never' in paths.log.read_bytes()
    finally:
        os.close(log)


@pytest.mark.parametrize('key', ['extensions.partialClone', 'remote.synthetic.promisor',
                                  'remote.synthetic.partialCloneFilter'])
def test_presence_even_false_promisor_key_stops_without_reading_value(tmp_path, monkeypatch, key):
    paths = paths_at(tmp_path)
    tiny_repo(paths, monkeypatch)
    git(paths.repo, 'config', key, 'synthetic-sensitive-value')
    with pytest.raises(v4.Stop, match='promisor') as error:
        v4.no_promisor(paths)
    assert 'synthetic-sensitive-value' not in str(error.value)
    assert not paths.worktree.exists()


@pytest.mark.parametrize('case', ['missing-object', 'dirty-launcher', 'wrong-head', 'locked-stale'])
def test_recovery_stops_without_reset_fetch_or_broad_prune(tmp_path, monkeypatch, case):
    paths = paths_at(tmp_path)
    tiny_repo(paths, monkeypatch)
    log = v4.private_fd(paths.log)
    try:
        if case == 'missing-object':
            monkeypatch.setattr(v4, 'COMMIT', '0' * 40)
        else:
            v4.ensure_worktree(paths, log)
            if case == 'dirty-launcher':
                (paths.worktree / 'console/run_bridge.py').write_text('dirty retained bytes')
            elif case == 'wrong-head':
                (paths.repo / 'new').write_text('synthetic second revision')
                git(paths.repo, 'add', '.')
                git(paths.repo, '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
                    'commit', '-m', 'second synthetic revision')
                monkeypatch.setattr(v4, 'COMMIT', git(paths.repo, 'rev-parse', 'HEAD').decode().strip())
            else:
                git(paths.repo, 'worktree', 'lock', str(paths.worktree))
                shutil.rmtree(paths.worktree)
        with pytest.raises(v4.Stop):
            v4.ensure_worktree(paths, log)
        if case == 'dirty-launcher':
            assert (paths.worktree / 'console/run_bridge.py').read_text() == 'dirty retained bytes'
    finally:
        os.close(log)


def test_transport_backstop_and_config_name_only_commands(tmp_path, monkeypatch):
    paths = paths_at(tmp_path)
    commands = []

    def run(argv, **kwargs):
        commands.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 1 if 'config' in argv else 0, b'git version 2.39.5', b'')

    monkeypatch.setattr(v4.subprocess, 'run', run)
    v4.no_promisor(paths)
    assert len(commands) == 4
    for argv, kwargs in commands:
        assert ['-c', 'protocol.allow=never'] == argv[1:3]
        assert '--no-lazy-fetch' not in argv
        assert kwargs['env']['GIT_ALLOW_PROTOCOL'] == ''
        assert not kwargs.get('shell')
        if 'config' in argv:
            assert '--name-only' in argv and '--get-regexp' in argv
    assert {argv[-1] for argv, _ in commands[1:]} == set(v4.KEY_PATTERNS)


def test_private_log_retains_old_bytes_and_refuses_symlinks(tmp_path):
    path = tmp_path / 'launch.log'
    path.write_text('old safe metadata\n')
    path.chmod(0o644)
    fd = v4.private_fd(path)
    v4.note(fd, 'new safe metadata')
    os.close(fd)
    assert path.read_text().startswith('old safe metadata\n') and path.stat().st_mode & 0o777 == 0o600
    link = tmp_path / 'symlink'
    link.symlink_to(path)
    with pytest.raises(OSError):
        v4.private_fd(link)


def test_environment_drops_keys_agents_python_and_webkit_overrides(tmp_path, monkeypatch):
    paths = paths_at(tmp_path)
    names = ['GEMINI_API_KEY', 'GOOGLE_API_KEY', 'SSH_AUTH_SOCK', 'PYTHONPATH', 'LD_PRELOAD',
             'WEBKIT_INSPECTOR_SERVER', 'GIT_CONFIG_COUNT', 'GIT_DIR']
    with monkeypatch.context() as patch:
        for name in names:
            patch.setenv(name, 'synthetic')
        patch.setenv('DISPLAY', ':synthetic')
        env = v4.child_env(paths)
        assert not set(names) & env.keys() and env['DISPLAY'] == ':synthetic'
        assert env['PATH'] == '/usr/bin:/bin'


def historical_assets(destination):
    for name in ['run_bridge.py', 'bridge.py', 'bridge-client.js', 'index.html',
                 'elaria-visualizer.js', 'requirements-bridge.txt']:
        data = git(ROOT, 'cat-file', 'blob', v4.COMMIT + ':console/' + name)
        target = destination / 'console' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if name.endswith('.py') else 0o644)


def fake_native(paths, monkeypatch):
    # Production never accepts this host: only the test overrides its exact pin.
    source = '''import json, os, signal, sys
from pathlib import Path
if '--check' in sys.argv: sys.exit(0)
class NativeStop(Exception): pass
def read_launch_file(path):
 import html,re
 return html.unescape(re.search(r'0;url=([^"\\n]+)',path.read_text())[1])
if __name__ == '__main__':
 trace=Path(__file__).parent / ('window-' + str(os.getpid()) + '.json')
 trace.write_text(json.dumps({'pid':os.getpid(),'sid':os.getsid(0),'argv':sys.argv}))
 while True: signal.pause()
'''
    paths.native.write_text(source)
    paths.native.chmod(0o700)
    monkeypatch.setattr(v4, 'NATIVE_SHA', hashlib.sha256(paths.native.read_bytes()).hexdigest())


def available_port():
    with socket.socket() as socket_:
        socket_.bind(('127.0.0.1', 0))
        return socket_.getsockname()[1]


@pytest.mark.parametrize('first_stop', ['bridge', 'window'])
async def test_headless_bridge_reuse_detachment_and_no_token_disclosure(tmp_path, monkeypatch, first_stop):
    import asyncio
    import json

    from test_console_wire_bridge import unix_daemon

    paths = paths_at(tmp_path)
    historical_assets(paths.worktree)
    fake_native(paths, monkeypatch)
    monkeypatch.setattr(v4, 'ensure_worktree', lambda *_args: None)  # covered with real temp Git above
    port = available_port()
    monkeypatch.setattr(v4, 'PORT', port)
    original_listener = v4.listener_pid
    monkeypatch.setattr(v4, 'listener_pid', lambda: original_listener(port))
    log = v4.private_fd(paths.log)
    windows, bridge_pid = [], None
    try:
        async with unix_daemon(paths.runtime) as (socket_path, calls):
            assert socket_path == paths.runtime / 'assistant.sock'
            # Blocking launcher operations run in a worker while the synthetic daemon serves IPC.
            await asyncio.to_thread(v4.launch, paths, log)
            bridge_pid = v4.listener_pid()
            assert bridge_pid and v4.bridge_identity(bridge_pid, paths)
            await asyncio.to_thread(v4.launch, paths, log)
            assert v4.listener_pid() == bridge_pid  # second press does not start another bridge
            async with asyncio.timeout(5):
                while len(list(paths.native.parent.glob('window-*.json'))) < 2:
                    await asyncio.sleep(.02)
            windows = [json.loads(p.read_text()) for p in paths.native.parent.glob('window-*.json')]
            assert len(windows) == 2
            link = next(paths.runtime.glob('elaria-console-*/open.html'))
            import re
            token = re.search(r'#pair=([A-Za-z0-9_-]{43})', link.read_text())[1]
            bridge_argv = (Path('/proc') / str(bridge_pid) / 'cmdline').read_bytes()
            assert b'--open' not in bridge_argv and token.encode() not in bridge_argv
            assert token not in paths.log.read_text() and '#pair=' not in paths.log.read_text()
            for window in windows:
                assert window['sid'] == window['pid'] != os.getsid(0)
                assert token not in ' '.join(window['argv']) and str(link) in window['argv']
            assert not calls  # upgrade challenges never send hello, status or console.say
            if first_stop == 'window':
                os.kill(windows[0]['pid'], signal.SIGTERM)
                await asyncio.sleep(.1)
                os.kill(bridge_pid, 0)
                assert await asyncio.to_thread(v4.live_pairing,
                                               f'http://127.0.0.1:{port}/#pair={token}')
            os.killpg(bridge_pid, signal.SIGINT)
            async with asyncio.timeout(5):
                while True:
                    try:
                        if v4.listener_pid() is None:
                            break
                    except v4.Stop:
                        pass  # listener disappeared between /proc snapshots; production fails closed
                    await asyncio.sleep(.05)
            os.kill(windows[-1]['pid'], 0)  # independent native process survived bridge Ctrl-C
            assert (Path('/proc') / str(windows[-1]['pid']) / 'stat').read_text().split()[2] != 'Z'
    finally:
        os.close(log)
        if bridge_pid:
            try:
                os.kill(bridge_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for window in windows:
            try:
                os.kill(window['pid'], signal.SIGTERM)
            except ProcessLookupError:
                pass



def test_live_file_selection_challenges_tokens_not_newest_file(tmp_path, monkeypatch):
    from types import SimpleNamespace

    paths = paths_at(tmp_path)
    first = paths.runtime / 'elaria-console-live'
    second = paths.runtime / 'elaria-console-stale'
    first.mkdir(); second.mkdir()
    live = first / 'open.html'; stale = second / 'open.html'
    live.write_text('synthetic-live'); stale.write_text('synthetic-newer-stale')
    os.utime(stale, (2000000000, 2000000000))
    host = SimpleNamespace(read_launch_file=lambda p: p.read_text(), NativeStop=ValueError)
    monkeypatch.setattr(v4, 'live_pairing', lambda value: value == 'synthetic-live')
    assert v4.find_live_file(paths, host) == live
    live.unlink()
    with pytest.raises(v4.Stop, match='no validated live'):
        v4.find_live_file(paths, host)


def test_unknown_port_listener_never_becomes_a_bridge(tmp_path):
    paths = paths_at(tmp_path)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); listener.listen()
        pid = v4.listener_pid(listener.getsockname()[1])
        assert pid == os.getpid() and not v4.bridge_identity(pid, paths)


def load_installer():
    spec = importlib.util.spec_from_file_location('native_install_test', ROOT / 'console/install_native_launcher.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    return installer


def test_installer_pins_chain_and_shell_syntax():
    installer = load_installer()
    payload = installer.verified_sources(ROOT / 'console')
    assert hashlib.sha256(payload['native_launch.py']).hexdigest().encode() in payload['elaria-console-launch.sh']
    shim = payload['elaria-console-launch.sh'].decode()
    assert '/home/darrel/.config/elaria-console-native-v4/native_launch.py' in shim
    assert '--open' not in shim and 'google-chrome' not in shim and 'chromium' not in shim
    for line in (ROOT / 'console/native-launcher.sha256').read_text().splitlines():
        digest, name = line.split()
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    subprocess.run(['/bin/sh', '-n', str(ROOT / 'console/elaria-console-launch.sh')], check=True)


def test_installer_only_replaces_bind_target_not_hyprland_config(tmp_path):
    installer = load_installer()
    home = tmp_path / 'synthetic-owner'
    hypr = home / '.config/hypr'
    hypr.mkdir(parents=True)
    config = hypr / 'hyprland.lua'
    binding = b'hl.bind("SUPER + SPACE", hl.dsp.exec_cmd("/home/darrel/.config/hypr/elaria-console-launch.sh"))\n'
    config.write_bytes(binding)
    (hypr / 'elaria-console-launch.sh').write_text('synthetic older wrapper')
    installer.install(ROOT / 'console', home)
    assert config.read_bytes() == binding
    assert (hypr / 'elaria-console-launch.sh').read_bytes() == (ROOT / 'console/elaria-console-launch.sh').read_bytes()
    assert (home / '.config/elaria-console-native-v4').stat().st_mode & 0o777 == 0o700
    installer.install(ROOT / 'console', home)  # idempotent explicit installation
    assert config.read_bytes() == binding


def test_installer_stops_on_symlink_target_without_modifying_helpers(tmp_path):
    installer = load_installer()
    home = tmp_path / 'synthetic-owner'
    hypr = home / '.config/hypr'
    hypr.mkdir(parents=True)
    victim = home / 'untouched'
    victim.write_text('synthetic retained bytes')
    (hypr / 'elaria-console-launch.sh').symlink_to(victim)
    with pytest.raises(ValueError):
        installer.install(ROOT / 'console', home)
    assert victim.read_text() == 'synthetic retained bytes'
    assert not (home / '.config/elaria-console-native-v4/native_launch.py').exists()


def test_installer_tampered_source_hard_stops_without_destinations(tmp_path):
    installer = load_installer()
    source = tmp_path / 'tampered'
    source.mkdir()
    for name in installer.PINS:
        shutil.copy(ROOT / 'console' / name, source / name)
    (source / 'native_launch.py').write_text('tampered')
    home = tmp_path / 'unused-owner'
    with pytest.raises(ValueError, match='checksum'):
        installer.install(source, home)
    assert not home.exists()


def test_import_failure_stops_before_worktree_or_bridge(tmp_path, monkeypatch):
    paths = paths_at(tmp_path)
    fake_native(paths, monkeypatch)
    paths.native.write_text('import sys; sys.exit(2)')
    monkeypatch.setattr(v4, 'NATIVE_SHA', hashlib.sha256(paths.native.read_bytes()).hexdigest())
    monkeypatch.setattr(v4, 'ensure_worktree', lambda *_args: pytest.fail('must stop before recovery'))
    log = v4.private_fd(paths.log)
    try:
        with pytest.raises(v4.Stop, match='sudo dnf install'):
            v4.launch(paths, log)
        assert not paths.worktree.exists()
    finally:
        os.close(log)


def test_duplicate_press_lock_prevents_two_bridge_starts(tmp_path, monkeypatch):
    import fcntl

    paths = paths_at(tmp_path)
    fake_native(paths, monkeypatch)
    lock = v4.private_fd(paths.runtime / 'elaria-native-launch.lock')
    log = v4.private_fd(paths.log)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(v4, 'ensure_worktree', lambda *_args: pytest.fail('must not start recovery'))
        with pytest.raises(v4.Stop, match='another launch'):
            v4.launch(paths, log)
    finally:
        os.close(lock)
        os.close(log)



def test_empty_transport_allowlist_overrides_protocol_specific_allow(tmp_path, monkeypatch):
    paths = paths_at(tmp_path)
    tiny_repo(paths, monkeypatch)
    git(paths.repo, 'config', 'protocol.file.allow', 'always')  # synthetic config, not owner config
    with pytest.raises(v4.Stop):
        v4.git_read(paths, 'ls-remote', str(paths.repo))  # refused before even a file transport
