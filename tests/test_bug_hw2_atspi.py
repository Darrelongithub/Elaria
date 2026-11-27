import json
import struct
import sys
from types import SimpleNamespace as NS

import pytest

from assistant import _observation_linux, observation


class Node:
    def __init__(self, rect, *children, name='', role='frame'):
        self.rect, self.children, self.name, self.role = rect, children, name, role

    def get_state_set(self):
        return NS(contains={'active', 'showing'}.__contains__)

    def get_component_iface(self):
        return self

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
