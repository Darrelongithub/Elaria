"""System-Python GI bridge (Fedora python3-gobject + at-spi2-core)."""
import json
import os
import stat
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote, urlsplit


def portal():
    try:
        from gi.repository import Gio, GLib
    except ImportError:
        return 3
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error:
        return 3
    service = 'org.freedesktop.portal.Desktop'
    token = 'elaria_' + uuid.uuid4().hex
    sender = bus.get_unique_name()[1:].replace('.', '_')
    request = f'/org/freedesktop/portal/desktop/request/{sender}/{token}'
    loop = GLib.MainLoop()
    response = []

    def received(*args):
        response.extend(args[5].unpack())
        loop.quit()

    subscription = bus.signal_subscribe(service, 'org.freedesktop.portal.Request',
                                        'Response', request, None, Gio.DBusSignalFlags.NONE,
                                        received)
    try:
        returned = bus.call_sync(service, '/org/freedesktop/portal/desktop',
                                 'org.freedesktop.portal.Screenshot', 'Screenshot',
                                 GLib.Variant('(sa{sv})', ('', {
                                     'handle_token': GLib.Variant('s', token),
                                     'modal': GLib.Variant('b', False),
                                     'interactive': GLib.Variant('b', False),
                                 })), GLib.VariantType.new('(o)'),
                                 Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        if returned != request:
            return 1
        GLib.timeout_add_seconds(12, lambda: (loop.quit(), False)[1])
        loop.run()
        if not response:
            bus.call_sync(service, request, 'org.freedesktop.portal.Request', 'Close',
                          None, None, Gio.DBusCallFlags.NONE, 1000, None)
            return 1
        if response[0] != 0:
            return 1
        uri = urlsplit(response[1]['uri'])
        if uri.scheme != 'file' or uri.netloc or not uri.path.startswith('/'):
            return 1
        path = Path(unquote(uri.path))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                return 1
            path.unlink()
            sys.stdout.buffer.write(stream.read(32 * 1024 * 1024 + 1))
        return 0
    except GLib.Error as exc:
        name = Gio.DBusError.get_remote_error(exc)
        return 3 if name in {'org.freedesktop.DBus.Error.ServiceUnknown',
                             'org.freedesktop.DBus.Error.UnknownMethod',
                             'org.freedesktop.DBus.Error.UnknownInterface'} else 1
    finally:
        bus.signal_unsubscribe(subscription)


def atspi():
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi

    pid, *window_bounds = map(int, sys.argv[2:])
    Atspi.init()
    desktop = Atspi.get_desktop(0)
    rows = []
    for i in range(desktop.get_child_count()):
        app = desktop.get_child_at_index(i)
        if app.get_process_id() != pid:
            continue
        for j in range(app.get_child_count()):
            window = app.get_child_at_index(j)
            if not window.get_state_set().contains(Atspi.StateType.ACTIVE):
                continue
            component = window.get_component_iface()
            if component is None:
                continue
            r = component.get_extents(Atspi.CoordType.SCREEN)
            # Wayland toolkits sometimes report window-relative coords even
            # when SCREEN is requested. Reject disagreements instead of offsetting.
            if any(abs(a - b) > 8 for a, b in zip((r.x, r.y, r.width, r.height), window_bounds)):
                continue
            stack = [window]
            visited = 0
            while stack and visited < 1000:
                node = stack.pop()
                visited += 1
                if node is None:
                    continue
                states = node.get_state_set()
                if not states.contains(Atspi.StateType.SHOWING):
                    continue
                role = node.get_role_name()
                component = node.get_component_iface()
                if component and len(rows) < 150:
                    r = component.get_extents(Atspi.CoordType.SCREEN)
                    if r.width > 0 and r.height > 0 and r.x != -2147483648 and r.y != -2147483648:
                        rows.append([node.get_name()[:256], role, [r.x, r.y, r.width, r.height],
                                     node.get_role() == Atspi.Role.PASSWORD_TEXT])
                stack.extend(node.get_child_at_index(k)
                             for k in reversed(range(min(150, node.get_child_count()))))
    print(json.dumps(rows))
    return 0


if __name__ == '__main__':
    sys.exit(portal() if sys.argv[1] == 'portal' else atspi())
