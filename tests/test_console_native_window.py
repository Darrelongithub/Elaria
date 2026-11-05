"""Native-host unit gates; fake GI objects are NOT WebKitGTK rendering evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / 'console/native_window.py'
spec = importlib.util.spec_from_file_location('elaria_native_test', HOST)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
PAIR = 'http://127.0.0.1:8744/#pair=' + 'a' * 43


def launch_file(tmp_path, url=PAIR):
    tmp_path.chmod(0o700)
    path = tmp_path / 'open.html'
    path.write_text('<meta http-equiv="refresh" content="0;url=' + url + '">'
                    '<a href="' + url + '">Open</a>')
    path.chmod(0o600)
    return path


def test_native_host_pin_matches():
    digest, name = (HOST.parent / 'native-window.sha256').read_text().split()
    assert name == 'console/native_window.py'
    assert hashlib.sha256(HOST.read_bytes()).hexdigest() == digest


def test_private_file_is_read_only_without_extra_writes(tmp_path):
    path = launch_file(tmp_path)
    before = path.read_bytes(), path.stat().st_mtime_ns
    entries = set(tmp_path.iterdir())
    assert native.read_launch_file(path) == PAIR
    assert before == (path.read_bytes(), path.stat().st_mtime_ns)
    assert set(tmp_path.iterdir()) == entries
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize('kind', ['public-file', 'public-parent', 'file-symlink', 'parent-symlink',
                                  'fifo', 'hardlink', 'large', 'other-owner', 'directory', 'traversal'])
def test_unsafe_launch_file_rejected(tmp_path, monkeypatch, kind):
    parent = tmp_path / 'private'
    parent.mkdir(mode=0o700)
    path = launch_file(parent)
    if kind == 'public-file':
        path.chmod(0o644)
    elif kind == 'public-parent':
        parent.chmod(0o755)
    elif kind == 'file-symlink':
        target = parent / 'target'
        path.rename(target)
        path.symlink_to(target)
    elif kind == 'parent-symlink':
        link = tmp_path / 'alias'
        link.symlink_to(parent, target_is_directory=True)
        path = link / path.name
    elif kind == 'fifo':
        path.unlink()
        os.mkfifo(path, 0o600)
    elif kind == 'hardlink':
        os.link(path, parent / 'copy')
    elif kind == 'large':
        path.write_text('x' * (native.MAX_LINK_BYTES + 1))
    elif kind == 'other-owner':
        uid = os.getuid()
        monkeypatch.setattr(native.os, 'getuid', lambda: uid + 1)
    elif kind == 'directory':
        path.unlink()
        path.mkdir(mode=0o600)
    elif kind == 'traversal':
        path = parent / '..' / 'private' / 'open.html'
    with pytest.raises((native.NativeStop, OSError)):
        native.read_launch_file(path)


@pytest.mark.parametrize('url', [
    'https://127.0.0.1:8744/#pair=' + 'a' * 43, 'file:///private',
    PAIR.replace('127.0.0.1', 'localhost'), PAIR.replace('127.0.0.1', '127.0.0.1@evil.example'),
    PAIR.replace('8744', '65536'), PAIR.replace('8744', '1023'),
    PAIR.replace('/#', '/?x=1#'), PAIR + '&extra=1', PAIR + '\n', PAIR[:-1],
])
def test_only_exact_loopback_pairing_url_accepted(tmp_path, url):
    with pytest.raises(native.NativeStop):
        native.read_launch_file(launch_file(tmp_path, url))


def test_duplicate_or_mismatched_redirect_rejected():
    for document in [f'<meta http-equiv="refresh" content="0;url={PAIR}">',
                     f'<meta http-equiv="refresh" content="0;url={PAIR}"><a href="other">x</a>',
                     f'<meta http-equiv="refresh" content="0;url={PAIR}">' * 2]:
        with pytest.raises(native.NativeStop):
            native.pairing_url(document)


def test_navigation_allowlist_includes_bootstrap_and_exact_paired_iframe_only():
    assert native.navigation_allowed(PAIR, PAIR)
    assert native.navigation_allowed('http://127.0.0.1:8744/', PAIR)
    assert native.navigation_allowed('http://127.0.0.1:8744/console?token=' + 'a' * 43, PAIR)
    for url in ['https://example.org', 'file:///tmp/open.html', 'javascript:alert(1)',
                PAIR.replace('8744', '8745'), PAIR.replace('a' * 43, 'b' * 43),
                'http://127.0.0.1:8744/console', 'about:blank']:
        assert not native.navigation_allowed(url, PAIR)


def test_missing_gi_hard_stops_with_exact_hint_and_no_browser(monkeypatch, capsys):
    monkeypatch.setattr(native.resource, 'setrlimit', lambda *_args: None)
    monkeypatch.setitem(sys.modules, 'gi', None)
    assert native.main(['--check']) == 2
    output = capsys.readouterr()
    assert output.out == '' and output.err == native.INSTALL_HINT + '\n'


def test_bad_typelib_hard_stops_with_same_hint(monkeypatch):
    def fail(*_args):
        raise ValueError('untrusted loader details')
    monkeypatch.setitem(sys.modules, 'gi', SimpleNamespace(require_version=fail))
    with pytest.raises(native.NativeStop, match='sudo dnf install'):
        native.load_runtime()


def test_no_display_has_no_fallback_or_pairing_output(tmp_path, monkeypatch, capsys):
    path = launch_file(tmp_path)
    monkeypatch.setattr(native.resource, 'setrlimit', lambda *_args: None)
    monkeypatch.setattr(native, 'load_runtime', lambda: (
        SimpleNamespace(init_check=lambda _args: (False, [])), object()))
    assert native.main(['--launch-file', str(path)]) == 2
    captured = capsys.readouterr()
    assert 'GTK display unavailable' in captured.err and PAIR not in str(captured)


class SignalStub:
    def __init__(self):
        self.signals = {}

    def connect(self, signal, callback):
        self.signals[signal] = callback


class SettingsStub:
    def __init__(self):
        self.values = {}

    def __getattr__(self, name):
        assert name.startswith('set_')
        return lambda value: self.values.__setitem__(name, value)


def test_actual_host_wiring_is_ephemeral_constant_title_and_no_service_lifecycle():
    context = SignalStub()
    context.is_ephemeral = lambda: True
    context.set_cache_model = lambda _value: None
    context.set_sandbox_enabled = lambda value: setattr(context, 'sandbox', value)
    view = SignalStub()
    view.is_ephemeral = lambda: True
    settings = SettingsStub()
    view.get_settings = lambda: settings
    view.load_uri = lambda value: setattr(view, 'uri', value)
    window = SignalStub()
    window.set_default_size = lambda *value: setattr(window, 'size', value)
    window.add = lambda child: setattr(window, 'child', child)
    window.show_all = lambda: None
    quit_calls = []

    def make_window(**kwargs):
        window.title = kwargs['title']
        return window

    Gtk = SimpleNamespace(Window=make_window, main_quit=lambda: quit_calls.append(True))
    kinds = SimpleNamespace(NAVIGATION_ACTION=0, RESPONSE=1, NEW_WINDOW_ACTION=2)
    WebKit = SimpleNamespace(WebContext=SimpleNamespace(new_ephemeral=lambda: context),
                             CacheModel=SimpleNamespace(DOCUMENT_VIEWER=1),
                             WebView=SimpleNamespace(new_with_context=lambda _context: view),
                             PolicyDecisionType=kinds)
    actual, webview = native.build_window(Gtk, WebKit, PAIR)
    assert actual is window and webview is view
    assert window.title == 'ELARIA' and window.size == (1440, 900) and view.uri == PAIR
    assert context.sandbox and not settings.values['set_disable_web_security']
    assert not settings.values['set_enable_html5_local_storage']
    assert not settings.values['set_enable_developer_extras']
    assert 'notify::title' not in view.signals
    for signal, method in [('permission-request', 'deny'), ('run-file-chooser', 'cancel')]:
        calls = []
        request = SimpleNamespace(**{method: lambda calls=calls: calls.append(True)})
        assert view.signals[signal](view, request) is True and calls == [True]
    calls = []
    decision = SimpleNamespace(ignore=lambda: calls.append('ignore'))
    assert view.signals['decide-policy'](view, decision, kinds.NEW_WINDOW_ACTION)
    assert calls == ['ignore']
    assert view.signals['decide-policy'](view, decision, kinds.NAVIGATION_ACTION)
    assert calls == ['ignore', 'ignore']  # malformed action cannot fall through to default use
    window.signals['destroy'](window)
    assert quit_calls == [True]


def test_system_runtime_check_reports_no_token():
    run = subprocess.run(['/usr/bin/python3', '-IB', str(HOST), '--check'],
                         capture_output=True, text=True, timeout=15, check=False)
    assert run.returncode in {0, 2}
    assert '#pair=' not in run.stdout + run.stderr
    if run.returncode == 2:
        assert run.stderr.strip() == native.INSTALL_HINT


async def test_real_webkit_pairing_origin_and_six_looks_opt_in(tmp_path, monkeypatch):
    import asyncio
    import json
    from urllib.parse import urlsplit

    from test_console_wire_bridge import FakeRPC, bridge_module, running

    interpreter = os.environ.get('ELARIA_WEBKIT_TEST_PYTHON')
    if not interpreter:
        pytest.skip('requires explicitly selected system GI/WebKitGTK Python and a real display')
    assert Path(interpreter).is_absolute()
    rpc = FakeRPC()
    seen = []
    original = bridge_module.Bridge.process_request

    def observe(self, connection, request):
        response = original(self, connection, request)
        seen.append((request.headers.get('Origin'), urlsplit(request.path).path,
                     response.status_code if response is not None else 101))
        return response

    monkeypatch.setattr(bridge_module.Bridge, 'process_request', observe)
    async with running(rpc) as bridge:
        path = launch_file(tmp_path, f'{bridge.origin}/#pair={bridge.token}')
        process = await asyncio.create_subprocess_exec(
            interpreter, '-IB', str(HOST.with_name('native-webkit-test.py')), str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        try:
            output, _ = await asyncio.wait_for(process.communicate(), 75)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, 'native probe failed; no engine/URI diagnostics collected'
        assert bridge.token.encode() not in output
        result = json.loads(output)
        assert result['passed'] and result['title'] and result['cross_origin_denied']
        assert len(result['looks']) == 6
        assert len(rpc.says) == 1  # synthetic only; no live model or daemon used
        foreign = bridge.origin.replace('127.0.0.1', 'localhost')
        assert (foreign, '/elaria', 403) in seen and (foreign, '/console', 403) in seen
        assert (bridge.origin, '/elaria', 101) in seen
