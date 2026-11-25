"""Sandbox eye checks: actual daemon/transport, fixture pixels/tree, no display."""
import asyncio
import struct
from pathlib import Path

from assistant.daemon import Daemon
from assistant.nus_pointer import Pointer, draw
from assistant.nus_surface import NusDispatch
from assistant.observation import Element, Output, capture, ground, semantic_target

QML = Path('ui/quickshell/nus/shell.qml').read_text()


def fixture():
    output = Output('DP-1', (-800, 0, 800, 600), 1.25)
    desktop = lambda: ('window', output, 1)
    png = b'\x89PNG\r\n\x1a\n\0\0\0\rIHDR' + struct.pack('>II', 1000, 750)

    def portal(selected, count):
        assert (selected, count) == (output, 1)
        return png

    def observe():
        return capture(desktop=desktop, screenshot=portal, elements=lambda: (
            Element('delete', 'Delete', 'push button', (-720, 75, 40, 30)),
            Element('secret', 'PIN', 'entry', (-640, 75, 40, 30)),
        ))

    return observe, desktop


def test_fixture_portal_and_atspi_bounds_reach_ring_ipc():
    observe, desktop = fixture()
    calls = []
    pointer = Pointer(NusDispatch('/nus', calls.append), capture=observe, desktop=desktop)

    async def run():
        result = await pointer.point('Delete')
        assert result.bbox == (-720, 75, 40, 30)
        assert result.frame_id and result.snapshot_id

    asyncio.run(run())
    assert calls[-1][6:] == ['pointAt', 'DP-1', '80', '75', '40', '30', 'sure', '12000', '0']
    assert 'root.pointBounds = Qt.rect(x, y, w, h)' in QML
    assert 'readonly property rect bounds: root.pointBounds' in QML
    assert 'x: bounds.x + bounds.width / 2' in QML


def test_rejected_targets_never_reach_ring():
    frame, _ = fixture()[0]()
    surface = NusDispatch('/nus', lambda args: (_ for _ in ()).throw(AssertionError(args)))
    target = semantic_target(frame, 'Delete')
    assert draw(surface, frame, dict(target, confidence=.299)) is None
    assert draw(surface, frame, dict(target, snapshot_id='stale')) is None
    assert draw(surface, frame, semantic_target(frame, 'PIN')) is None
    guess = dict(target, kind='bbox', x=.1, y=.125, w=.05, h=.05, confidence=.49)
    assert draw(surface, frame, guess) is None
    assert ground(frame, dict(guess, confidence=.5)).label == 'unidentified · best guess'
    assert draw(surface, frame, dict(guess, confidence=.9, x=.2)) is None  # overlaps PIN
    assert draw(surface, frame, dict(guess, confidence=.9, w=.8, h=.5)) is None


def test_daemon_capture_transitions_reach_fake_qs_in_order():
    calls, events = [], []
    daemon = Daemon.__new__(Daemon)
    daemon._nus_surface = NusDispatch('/nus', calls.append)

    async def broadcast(event):
        events.append(event)

    daemon.broadcast = broadcast

    async def run():
        daemon._nus_state_lock = asyncio.Lock()
        for state in ('armed', 'verifying', 'open', 'open', 'muted', 'released'):
            await daemon._emit_capture_state(state)
        await daemon._emit_capture_state('released', reason='only reason changed')

    asyncio.run(run())
    assert [args[6:] for args in calls] == [['setCaptureState', state] for state in (
        'idle', 'verifying', 'listening', 'speaking', 'released')]
    assert len(events) == 6
    assert 'root.surfaceVisible = state !== "released"' in QML
