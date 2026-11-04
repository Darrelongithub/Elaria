"""Detached launcher gates: private temp data, fake browser, synthetic IPC only."""
from __future__ import annotations

import argparse
import asyncio
import html
import importlib.util
import json
import os
import re
import signal
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_console_wire_bridge import ASSETS, hello, read_until, unix_daemon

spec = importlib.util.spec_from_file_location('console_launcher', ASSETS / 'run_bridge.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def link_url(path):
    return html.unescape(re.search(r'0;url=([^"]+)', path.read_text())[1])


def free_port():
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        return reservation.getsockname()[1]


def fake_browser(tmp_path):
    # Deliberately acts like a blocking browser process. It is NOT a browser/UI proof.
    path = tmp_path / 'synthetic browser'
    path.write_text(f'''#!{sys.executable}
import json, os, signal, sys
from pathlib import Path
profile = Path(next(x.split('=', 1)[1] for x in sys.argv if x.startswith('--user-data-dir=')))
trace = profile / 'synthetic-process.json'
temp = trace.with_suffix('.tmp')
temp.write_text(json.dumps({{'pid':os.getpid(), 'sid':os.getsid(0), 'pgid':os.getpgrp(),
                            'argv':sys.argv, 'env_names':list(os.environ)}}))
os.replace(temp, trace)
while True:
    signal.pause()
''')
    path.chmod(0o700)
    return path


def test_each_launch_gets_private_distinct_link_and_profile(tmp_path):
    tmp_path.chmod(0o700)
    first, one = launcher.private_launch_files(tmp_path, 'http://127.0.0.1:8744/#pair=first',
                                              browser=True)
    second, two = launcher.private_launch_files(tmp_path, 'http://127.0.0.1:8744/#pair=second',
                                               browser=True)
    assert one != two and first.parent != second.parent
    assert link_url(first).endswith('#pair=first') and link_url(second).endswith('#pair=second')
    for link, profile in [(first, one), (second, two)]:
        assert stat.S_IMODE(link.stat().st_mode) == 0o600
        assert stat.S_IMODE(link.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(profile.stat().st_mode) == 0o700
    manual, profile = launcher.private_launch_files(tmp_path, 'http://127.0.0.1:8744/#pair=third')
    assert profile is None and manual.exists() and not (manual.parent / 'profile').exists()


@pytest.mark.parametrize('kind', ['public', 'symlink', 'regular', 'other-owner'])
def test_unsafe_session_parent_refused_without_writes(tmp_path, monkeypatch, kind):
    parent = tmp_path / 'parent'
    if kind == 'regular':
        parent.write_text('synthetic')
    elif kind == 'symlink':
        parent.symlink_to(tmp_path, target_is_directory=True)
    else:
        parent.mkdir(mode=0o755 if kind == 'public' else 0o700)
    before = set(tmp_path.rglob('*'))
    if kind == 'other-owner':
        uid = os.getuid()
        monkeypatch.setattr(launcher.os, 'getuid', lambda: uid + 1)
    with pytest.raises(ValueError, match='owner-owned and private'):
        launcher.private_launch_files(parent, 'synthetic')
    assert set(tmp_path.rglob('*')) == before


@pytest.mark.parametrize('size', ['1440x900', '1,900', '0,0', '99999,900', '1440,5000',
                                  '1440,900 --extra', '320,239'])
def test_window_size_rejects_bad_geometry_or_argument_injection(size):
    with pytest.raises(argparse.ArgumentTypeError):
        launcher.window_size(size)


def test_window_size_and_browser_selection_are_explicit(tmp_path, monkeypatch):
    assert launcher.window_size('1440,900') == '1440,900'
    assert launcher.window_size('320,240') == '320,240'
    executable = fake_browser(tmp_path)
    assert launcher.browser_executable(str(executable)) == str(executable)
    with pytest.raises(ValueError, match='absolute'):
        launcher.browser_executable('chromium --extra')
    executable.chmod(0o600)
    with pytest.raises(ValueError, match='executable regular file'):
        launcher.browser_executable(str(executable))
    monkeypatch.setattr(launcher.shutil, 'which', lambda name: None)
    with pytest.raises(ValueError, match='No Chrome/Chromium'):
        launcher.browser_executable()


def test_detached_argv_streams_fds_and_environment(monkeypatch, tmp_path):
    with monkeypatch.context() as patch:
        captured = []
        secret_names = ['GEMINI_API_KEY', 'GOOGLE_API_KEY', 'SSH_AUTH_SOCK', 'GPG_AGENT_INFO',
                        'BASH_ENV', 'ENV', 'PYTHONPATH', 'LD_PRELOAD']
        for key in secret_names:
            patch.setenv(key, 'synthetic-not-a-real-secret')
        patch.setenv('DISPLAY', ':synthetic')
        sentinel = object()

        def popen(argv, **kwargs):
            captured.append((argv, kwargs))
            return sentinel

        patch.setattr(launcher.subprocess, 'Popen', popen)
        link = tmp_path / 'private open.html'
        profile = tmp_path / 'private profile'
        assert launcher.detach_browser('/synthetic/browser', link, profile, '1440,900') is sentinel
        argv, kwargs = captured[0]
        assert argv[:4] == ['/synthetic/browser', '--app=' + link.as_uri(),
                            '--user-data-dir=' + str(profile), '--window-size=1440,900']
        assert not kwargs.get('shell', False)
        assert kwargs['start_new_session'] and kwargs['close_fds']
        assert all(kwargs[name] == subprocess.DEVNULL for name in ['stdin', 'stdout', 'stderr'])
        assert kwargs['env']['DISPLAY'] == ':synthetic'
        assert not set(secret_names) & kwargs['env'].keys()

@pytest.mark.parametrize('arguments', [['--open', '--check'], ['--window-size', '1440,900'],
                                      ['--browser', '/synthetic/browser']])
def test_conflicting_modes_stop_before_launch(arguments):
    result = subprocess.run([sys.executable, '-IB', str(ASSETS / 'run_bridge.py'), *arguments],
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 2 and 'error:' in result.stderr
    assert 'Private launch file:' not in result.stdout


async def test_busy_port_does_not_launch_browser_or_create_profile(tmp_path):
    browser = fake_browser(tmp_path)
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        port = occupied.getsockname()[1]
        async with unix_daemon(tmp_path) as (path, calls):
            process = await asyncio.create_subprocess_exec(
                sys.executable, '-IB', str(ASSETS / 'run_bridge.py'), '--open',
                '--browser', str(browser), '--socket', str(path), '--port', str(port),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stdout, stderr = await asyncio.wait_for(process.communicate(), 10)
            assert process.returncode == 2 and b'STOP:' in stderr
            assert not stdout and not calls and not list(tmp_path.glob('elaria-console-*'))
            assert occupied.getsockname()[1] == port  # existing listener untouched


@pytest.mark.parametrize('stop_first', ['bridge', 'browser'])
async def test_browser_and_bridge_have_independent_lifetimes(tmp_path, stop_first):
    from urllib.parse import parse_qs, urlsplit

    from test_console_wire_bridge import connect

    browser = fake_browser(tmp_path)
    browser_pid = None
    async with unix_daemon(tmp_path) as (path, calls):
        port = free_port()
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-IB', str(ASSETS / 'run_bridge.py'), '--open', '--browser', str(browser),
            '--window-size', '1280,800', '--socket', str(path), '--port', str(port),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        try:
            line = (await asyncio.wait_for(process.stdout.readline(), 10)).decode().strip()
            assert line.startswith('Private launch file: '), line
            link = Path(line.removeprefix('Private launch file: '))
            url = link_url(link)
            token = parse_qs(urlsplit(url).fragment)['pair'][0]
            trace = link.parent / 'profile' / 'synthetic-process.json'
            async with asyncio.timeout(5):
                while not trace.exists():
                    await asyncio.sleep(.02)
            data = json.loads(trace.read_text())
            browser_pid = data['pid']
            assert data['sid'] == data['pgid'] == browser_pid != process.pid
            assert '--app=' + link.as_uri() in data['argv']
            assert token not in ' '.join(data['argv'])
            assert '--window-size=1280,800' in data['argv']
            assert '--user-data-dir=' + str(trace.parent) in data['argv']
            assert not calls  # opening the fake app never calls a model or even status
            if stop_first == 'browser':
                os.kill(browser_pid, signal.SIGTERM)
                await asyncio.sleep(.6)
                assert process.returncode is None
                # The bridge remains usable after browser exit, not just a live PID.
                import inspect
                kwargs = {'proxy': None} if 'proxy' in inspect.signature(connect).parameters else {}
                async with connect(f'ws://127.0.0.1:{port}/elaria?token={token}',
                                   origin=f'http://127.0.0.1:{port}', **kwargs) as ws:
                    await hello(ws)
                    await read_until(ws, 'hello-ok')
                assert all(call['method'] == 'status' for call in calls)
            os.killpg(process.pid, signal.SIGINT)  # terminal-style Ctrl-C to bridge's group
            output, _ = await asyncio.wait_for(process.communicate(), 10)
            assert process.returncode == 0, output.decode()
            assert token.encode() not in output and b'#pair=' not in output
            assert token not in line
            if stop_first == 'bridge':
                os.kill(browser_pid, 0)  # detached blocking browser survived Ctrl-C
            assert trace.parent.is_dir()  # no cleanup under a detached browser
        finally:
            if process.returncode is None:
                process.terminate()
                await asyncio.wait_for(process.communicate(), 10)
            if browser_pid:
                try:
                    os.kill(browser_pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass


async def test_private_link_entry_does_not_relax_protected_asset_or_websocket_gates():
    from test_console_wire_bridge import request, running

    navigate = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Dest': 'document'}
    async with running() as bridge:
        code, headers, body = await asyncio.to_thread(request, bridge, '/', navigate)
        assert code == 200 and bridge.token.encode() not in body and bridge.shell not in body
        assert "frame-ancestors 'self'" in headers['Content-Security-Policy']
        for path in ['/console?token=' + bridge.token, '/elaria?token=' + bridge.token,
                     '/bridge-client.js']:
            assert (await asyncio.to_thread(request, bridge, path, navigate))[0] == 403
        for extra in [{'Origin': 'null'}, {'Origin': 'https://remote.example'},
                      {'Sec-Fetch-Dest': 'iframe'}, {'Sec-Fetch-Mode': 'cors'},
                      {'Host': 'remote.example'}]:
            assert (await asyncio.to_thread(request, bridge, '/', navigate | extra))[0] == 403


async def test_optional_browser_private_launch_link(tmp_path):
    import shutil

    from test_console_wire_bridge import running

    if not os.environ.get('ELARIA_CHROMIUM_PATH') or not shutil.which('node'):
        pytest.skip('existing local Chromium/playwright-core required; no browser download')
    async with running() as bridge:
        url = bridge.origin + '/#pair=' + bridge.token
        link, profile = launcher.private_launch_files(tmp_path, url, browser=True)
        env = dict(os.environ, ELARIA_TEST_LINK=link.as_uri(), ELARIA_TEST_URL=url,
                   ELARIA_TEST_PROFILE=str(profile))
        process = await asyncio.create_subprocess_exec(
            'node', str(ASSETS / 'launch-link-test.js'), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 60)
            assert process.returncode == 0, (stdout + stderr).decode()
            assert b'PASS:' in stdout
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
