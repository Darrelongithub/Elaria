import json
import struct
import subprocess
import sys
from types import SimpleNamespace as NS

import pytest

from assistant import _observation_linux, observation


class Node:
    def __init__(self, rect, *children, name='', role='frame',
                 states=('active', 'showing'), component=True):
        self.rect, self.children, self.name, self.role = rect, children, name, role
        self.states, self.component = states, component

    def get_state_set(self):
        return NS(contains=self.states.__contains__)

    def get_component_iface(self):
        return self if self.component else None

    def get_extents(self, coord_type):
        assert coord_type == 'screen'
        return NS(**dict(zip(('x', 'y', 'width', 'height'), self.rect)))

    def get_role(self):
        return self.role

    get_role_name = get_role

    def get_name(self):
        return self.name

    def get_child_count(self):
        return len(self.children)

    def get_child_at_index(self, i):
        return self.children[i]


@pytest.fixture
def capture_tree(monkeypatch, capsys):
    def capture(*windows):
        app = Node(None, *windows)
        app.get_process_id = lambda: 42
        atspi = NS(init=lambda: None, get_desktop=lambda _: Node(None, app),
                   CoordType=NS(SCREEN='screen'), StateType=NS(ACTIVE='active', SHOWING='showing'),
                   Role=NS(PASSWORD_TEXT='password text'))
        monkeypatch.setitem(sys.modules, 'gi', NS(require_version=lambda *_: None))
        monkeypatch.setitem(sys.modules, 'gi.repository', NS(Atspi=atspi))

        def run(args):
            if args[0] == 'hyprctl':
                return json.dumps({'pid': 42, 'at': [-600, 250], 'size': [300, 166]})
            monkeypatch.setattr(sys, 'argv', args[1:])
            assert _observation_linux.atspi() == 0
            return capsys.readouterr().out

        monkeypatch.setattr(observation, '_run', run)
        output = observation.Output('test', (-1280, 0, 1280, 720), 1)
        png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 1280, 720)
        frame, _ = observation.capture(desktop=lambda: ('focus', output, 1),
                                       screenshot=lambda *_: png)
        return frame

    return capture


def test_bug_hw2_relative_tree_reaches_ground(capture_tree):
    frame = capture_tree(Node((0, 0, 300, 166),
                              Node((210, 120, 75, 32), name='Cancel'),
                              Node((30, 60, 210, 32), name='Entry', role='password text')))
    assert frame.elements[0].bounds == (-600, 250, 300, 166)
    resolution = observation.ground(frame, observation.semantic_target(frame, 'Cancel'))
    assert resolution.bbox == (-390, 370, 75, 32)
    assert resolution.point == (-352.5, 386)
    assert observation.semantic_target(frame, 'Nonexistent label') is None
    assert frame.elements[2].bounds == (-570, 310, 210, 32)
    assert observation.ground(frame, observation.semantic_target(frame, 'Entry')) is None


def test_bug_hw2_screen_tree_unchanged(capture_tree):
    frame = capture_tree(Node((-600, 250, 300, 166), Node((-390, 370, 75, 32), name='Cancel')))
    resolution = observation.ground(frame, observation.semantic_target(frame, 'Cancel'))
    assert resolution.bbox == (-390, 370, 75, 32)


@pytest.mark.parametrize(('rects', 'counts'), [
    ([(0, 0, 309, 166)], '{"size_mismatch": 1}'),
    ([(0, 9, 300, 166)], '{"origin_mismatch": 1}'),
    ([(0, 0, 300, 166), (-600, 250, 300, 166)], '{"ambiguous": 2}'),
])
def test_bug_hw2_rejected_windows_are_journaled(capture_tree, journal_stream, rects, counts):
    frame = capture_tree(*(Node(rect, name='Private title') for rect in rects))
    assert frame.elements == ()
    line = journal_stream.getvalue()
    assert f'observation.atspi.windows - - rejected {counts}' in line
    assert 'Private title' not in line


@pytest.mark.parametrize('rect', [
    (8, -8, 308, 158),
    (-8, 8, 292, 174),
    (-592, 242, 308, 158),
    (-608, 258, 292, 174),
])
def test_bug_hw2_tolerance_boundary_preserves_exact_translation(capture_tree, rect):
    relative = abs(rect[0]) <= 8
    child = (210, 120, 75, 32) if relative else (-390, 370, 75, 32)
    frame = capture_tree(Node(rect, Node(child, name='Cancel')))
    dx, dy = (-600, 250) if relative else (0, 0)
    # Do not snap a nearly-zero origin or resize a toolkit rectangle.
    assert frame.elements[0].bounds == (rect[0] + dx, rect[1] + dy, *rect[2:])
    resolution = observation.ground(frame, observation.semantic_target(frame, 'Cancel'))
    assert resolution.bbox == (-390, 370, 75, 32)


@pytest.mark.parametrize('rect', [
    (0, 0, 291, 166), (0, 0, 300, 175), (0, 0, 300, 157),
    (0, 0, 0, 166), (0, 0, 300, -1),
    (-600, 250, 309, 166), (-600, 250, 300, 175),
])
def test_bug_hw2_size_mismatch_fails_closed(capture_tree, journal_stream, rect):
    frame = capture_tree(Node(rect, Node((210, 120, 75, 32), name='Cancel')))
    assert frame.elements == ()
    assert '"size_mismatch": 1' in journal_stream.getvalue()


@pytest.mark.parametrize('rects', [
    [(0, 0, 300, 166)] * 2,
    [(-600, 250, 300, 166)] * 2,
])
def test_bug_hw2_same_coordinate_mode_still_ambiguous(capture_tree, journal_stream, rects):
    frame = capture_tree(*(Node(rect, Node((210, 120, 75, 32), name='Cancel'))
                           for rect in rects))
    assert frame.elements == ()
    assert '"ambiguous": 2' in journal_stream.getvalue()


def test_bug_hw2_rejection_counts_do_not_discard_unique_valid_window(capture_tree, journal_stream):
    frame = capture_tree(
        Node((0, 0, 300, 166), Node((210, 120, 75, 32), name='Cancel')),
        Node((0, 0, 309, 166), name='Private size mismatch'),
        Node((100, 100, 300, 166), name='Private origin mismatch'),
        Node((0, 0, 300, 166), states=('showing',)),
        Node((0, 0, 300, 166), component=False),
    )
    resolution = observation.ground(frame, observation.semantic_target(frame, 'Cancel'))
    assert resolution.bbox == (-390, 370, 75, 32)
    assert ('{"inactive": 1, "no_component": 1, "origin_mismatch": 1, '
            '"size_mismatch": 1}') in journal_stream.getvalue()
    assert 'Private' not in journal_stream.getvalue()


def test_bug_hw2_missing_window_is_journaled(capture_tree, journal_stream):
    assert capture_tree().elements == ()
    assert '"no_pid_windows": 1' in journal_stream.getvalue()


@pytest.mark.parametrize('error', [
    OSError('Private helper path'),
    subprocess.CalledProcessError(1, 'Private command', stderr='Private helper output'),
    subprocess.TimeoutExpired('Private command', 3),
])
def test_bug_hw2_helper_failure_is_journaled_without_private_details(
        monkeypatch, journal_stream, error):
    output = observation.Output('test', (0, 0, 1280, 720), 1)
    png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR' + struct.pack('>II', 1280, 720)
    # Use the real _elements entry point through a failing subprocess boundary.
    def run(_args):
        raise error

    monkeypatch.setattr(observation, '_run', run)
    frame, _ = observation.capture(desktop=lambda: ('focus', output, 1),
                                   screenshot=lambda *_: png)
    assert frame.elements == ()
    assert (f'observation.atspi.snapshot - - unavailable {type(error).__name__}'
            in journal_stream.getvalue())
    assert 'Private' not in journal_stream.getvalue()


def test_bug_hw2_nested_relative_rects_and_sensitive_overlap(capture_tree):
    frame = capture_tree(Node((0, 0, 300, 166),
        Node((10, 40, 280, 110),
             Node((210, 120, 75, 32), name='Cancel'),
             Node((30, 60, 210, 32), name='Entry', role='password text'),
             Node((30, 60, 210, 32), name='Obscured control'),
             Node((-2147483648, 0, 20, 20), name='Invalid sentinel'))))
    assert [e.bounds for e in frame.elements] == [
        (-600, 250, 300, 166), (-590, 290, 280, 110),
        (-390, 370, 75, 32), (-570, 310, 210, 32), (-570, 310, 210, 32),
    ]
    target = observation.semantic_target(frame, 'Cancel')
    assert observation.ground(frame, target).point == (-352.5, 386)
    assert observation.ground(frame, {**target, 'confidence': .29}) is None
    assert observation.ground(frame, {**target, 'snapshot_id': 'stale'}) is None
    assert observation.ground(frame, observation.semantic_target(frame, 'Entry')) is None
    assert observation.ground(frame, observation.semantic_target(frame, 'Obscured control')) is None
