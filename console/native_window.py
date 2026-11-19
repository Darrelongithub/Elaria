#!/usr/bin/python3
"""ELARIA GTK3/WebKitGTK 4.1 window. No browser fallback, service control or persistent profile.

Use the system Python (Fedora python3-gobject), not the bridge's isolated dependency venv.
Only a private launch FILE path crosses argv; its pairing URL is read and used in memory.
"""
from __future__ import annotations

import argparse
import os
import re
import resource
import stat
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

INSTALL_HINT = 'STOP: native GI/WebKit unavailable; sudo dnf install -y python3-gobject webkit2gtk4.1'
MAX_LINK_BYTES = 4096


class NativeStop(Exception):
    """Only constant, non-sensitive messages may be used with this exception."""


def window_size(value):
    match = re.fullmatch(r'([0-9]{3,4}),([0-9]{3,4})', value)
    if not match or not (320 <= int(match[1]) <= 8192 and 240 <= int(match[2]) <= 4320):
        raise argparse.ArgumentTypeError('size must be W,H; W=320..8192, H=240..4320')
    return int(match[1]), int(match[2])


class LaunchParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.targets = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'meta' and values.get('http-equiv', '').casefold() == 'refresh':
            content = values.get('content', '')
            self.targets.append(content.removeprefix('0;url=') if content.startswith('0;url=') else '')
        if tag == 'a':
            self.anchors.append(values.get('href'))


def pairing_url(document):
    """Parse data, never load the file as HTML or execute a redirect/script from it."""
    parser = LaunchParser()
    parser.feed(document)
    if len(parser.targets) != 1 or parser.anchors != parser.targets:
        raise NativeStop('STOP: invalid private launch file; no window opened.')
    url = parser.targets[0]
    match = re.fullmatch(r'http://127\.0\.0\.1:([0-9]{4,5})/#pair=([A-Za-z0-9_-]{43})', url)
    if not match or not 1024 <= int(match[1]) <= 65535:
        raise NativeStop('STOP: invalid pairing destination; no window opened.')
    return url


def read_launch_file(path):
    """No symlinks (including ancestors), FIFO blocking, shared permissions or hardlinks.

    Open relative to held directory FDs; validate the same open inode that is read. The
    immediate parent must be private/owner-owned, as must the bridge's 0600 launch file.
    This is not isolation from another process already running as the same owner.
    """
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise NativeStop('STOP: private launch file requires an absolute, non-traversing path.')
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parts[1:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW |
                                     os.O_CLOEXEC, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        info = os.fstat(directory)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise NativeStop('STOP: launch directory must be owner-owned 0700.')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=directory)
        with os.fdopen(fd, 'rb') as file:
            info = os.fstat(file.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                    or info.st_size > MAX_LINK_BYTES):
                raise NativeStop('STOP: launch file must be a private owner-owned 0600 regular file.')
            document = file.read(MAX_LINK_BYTES + 1)
            if len(document) > MAX_LINK_BYTES:
                raise NativeStop('STOP: private launch file exceeds its bound.')
            return pairing_url(document.decode('utf-8'))
    finally:
        os.close(directory)


def load_runtime():
    try:
        import gi
        gi.require_version('Gtk', '3.0')
        gi.require_version('WebKit2', '4.1')
        from gi.repository import Gtk, WebKit2
        return Gtk, WebKit2
    except Exception as from_error:
        raise NativeStop(INSTALL_HINT) from from_error


def navigation_allowed(uri, pairing):
    origin = pairing.split('/#', 1)[0]
    token = urlsplit(pairing).fragment.removeprefix('pair=')
    return uri in {pairing, origin + '/', origin + '/console?token=' + token}


def build_window(Gtk, WebKit2, pairing, size=(1440, 900)):
    """Build the actual host; no global Gtk.main so the optional integration probe can use it."""
    window = Gtk.Window(title='ELARIA')
    window.set_default_size(*size)
    context = WebKit2.WebContext.new_ephemeral()
    if not context.is_ephemeral():
        raise NativeStop('STOP: ephemeral WebKit context unavailable; no window opened.')
    context.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER)
    context.set_sandbox_enabled(True)  # never disable WebKit's process sandbox to make it work
    view = WebKit2.WebView.new_with_context(context)
    if not view.is_ephemeral():
        raise NativeStop('STOP: non-ephemeral WebKit view refused.')
    settings = view.get_settings()
    settings.set_enable_developer_extras(False)
    settings.set_enable_write_console_messages_to_stdout(False)
    settings.set_enable_html5_local_storage(False)  # shell display cache must not survive a window
    settings.set_allow_file_access_from_file_urls(False)
    settings.set_allow_universal_access_from_file_urls(False)
    settings.set_disable_web_security(False)
    # Do not force software rendering, replace the engine, relax Origin/CORS or inject pairing JS.
    window.add(view)

    def deny_permission(_view, request):
        request.deny()
        return True

    def deny_file(_view, request):
        request.cancel()
        return True

    def policy(_view, decision, kind):
        allowed = False  # includes every new-window action and malformed decision
        try:
            if kind == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
                uri = decision.get_navigation_action().get_request().get_uri()
                allowed = navigation_allowed(uri, pairing)
            elif kind == WebKit2.PolicyDecisionType.RESPONSE:
                response = decision.get_response()
                allowed = (navigation_allowed(response.get_uri(), pairing)
                           and response.get_mime_type() == 'text/html'
                           and response.get_status_code() == 200)
        except Exception:
            allowed = False
        if allowed:
            decision.use()
        else:
            decision.ignore()
        return True

    failed = False

    def fail_closed(*_args):
        nonlocal failed
        if not failed:
            failed = True
            view.stop_loading()
            window.remove(view)
            view.destroy()
            label = Gtk.Label(label='Console unavailable. Reopen using the current private launch file.')
            label.set_line_wrap(True)
            window.add(label)
            window.show_all()
        return True  # never let WebKit display an error page containing a pairing URI

    view.connect('decide-policy', policy)
    view.connect('permission-request', deny_permission)
    view.connect('run-file-chooser', deny_file)
    view.connect('create', lambda *_args: None)
    view.connect('context-menu', lambda *_args: True)
    view.connect('print', lambda *_args: True)
    view.connect('load-failed', fail_closed)
    view.connect('web-process-terminated', fail_closed)
    context.connect('download-started', lambda _context, download: download.cancel())
    window.connect('destroy', lambda *_args: Gtk.main_quit())
    window.show_all()
    view.load_uri(pairing)  # HTTP origin, not file://; fragment stays out of the HTTP request
    return window, view


def silence_runtime_output():
    # Engine/network diagnostic messages can contain URIs. No production debug channel.
    # Keep bounded preflight errors before this point; never echo a Gtk/WebKit exception.
    sys.stdout.flush()
    sys.stderr.flush()
    fd = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
    try:
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--launch-file', type=Path, help='Absolute private 0600 launch file, NOT a URL')
    parser.add_argument('--window-size', type=window_size, default=(1440, 900))
    parser.add_argument('--check', action='store_true', help='Import check only; no window or bridge call')
    args = parser.parse_args(argv)
    if args.check and args.launch_file or not args.check and not args.launch_file:
        parser.error('use --check alone or --launch-file PATH')
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        if any(key.startswith(('WEBKIT_', 'JSC_')) for key in os.environ):
            raise NativeStop('STOP: WebKit diagnostic/override environment refused.')
        # Import failures must print exactly the install hint and must never call a browser.
        Gtk, WebKit2 = load_runtime()
        if args.check:
            print('PASS: GTK3/WebKit2 4.1 imports only; rendering, pairing and hardware unverified.')
            return 0
        pairing = read_launch_file(args.launch_file)
        initialized = Gtk.init_check(None)
        if not (initialized[0] if isinstance(initialized, tuple) else initialized):
            raise NativeStop('STOP: GTK display unavailable; no browser fallback.')
        silence_runtime_output()
        build_window(Gtk, WebKit2, pairing, args.window_size)
        Gtk.main()
        return 0
    except NativeStop as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        # Never serialize untrusted paths, pairing URLs, loader diagnostics or GUI errors.
        print('STOP: native window unavailable; no browser fallback.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
