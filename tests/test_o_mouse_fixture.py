"""BUILD-4 sandbox eye-checks. No capture or injection on a real desktop."""
from dataclasses import replace

import pytest

from assistant.hands.gate import adjudicate
from assistant.hands.plan import Plan, Step
from assistant.hands.queue import ParkedQueue
from assistant.hands.runner import FakeMouseInput, MouseSeat, mouse_screen, run_mouse_fixture
from assistant.hands.sandbox import SyntheticSpace
from assistant.observation import Element, Frame, Output
from assistant.safety import halt_path


@pytest.mark.parametrize(('scenario', 'outcome', 'points'), [
    ('approved', 'complete', [(15, 15), (35, 15)]),
    ('unapproved', 'refused/unapproved', []),
    ('changed', 'halted/unexpected-screen', [(15, 15)]),
    ('external-stop', 'halted/kill', [(15, 15)]),
    ('deadline', 'halted/kill', [(15, 15)]),
    ('guest', 'refused/no-authority', []),
    ('locked', 'halted/unsafe-seat', []),
    ('absent', 'halted/unsafe-seat', []),
    ('unsafe', 'halted/unsafe-seat', []),
    ('sensitive', 'halted/ungrounded', []),
    ('ambiguous', 'halted/ungrounded', []),
    ('coordinate', 'refused/invalid-click', []),
])
def test_mouse_fixture(scenario, outcome, points):
    elements = (Element('one', 'First', 'button', (10, 10, 10, 10), scenario == 'sensitive'),
                Element('two', 'Second', 'button', (30, 10, 10, 10)))
    if scenario == 'ambiguous':
        elements += (replace(elements[0], id='third'),)
    frame = Frame('frame', 'snapshot', 'pixels', 100, 100,
                  Output('fixture', (0, 0, 100, 100), 1), 0, elements, 'app')
    seats = [MouseSeat(replace(frame, png_sha256=str(i)), 'window', scenario != 'locked',
                       scenario != 'absent', scenario != 'unsafe') for i in range(3)]
    with SyntheticSpace() as space:
        queue = ParkedQueue(space)
        hashes = list(map(mouse_screen, seats))
        plan = Plan(tuple(Step(i, 3, 'click', ('window', 'button', name, *hashes[i:i+2]),
                               str(space.work)) for i, name in enumerate(
                                   ('10,20' if scenario == 'coordinate' else 'First', 'Second'))))
        sink = FakeMouseInput()
        now = [0]
        def during():
            i = len(sink.calls)
            assert queue._db.execute('SELECT verdict FROM observations ORDER BY id DESC LIMIT 1').fetchone()[0] == f'click/{i-1}/before'
            if scenario == 'changed':
                seats[i] = replace(seats[i], frame=replace(frame, png_sha256='unexpected'))
            if scenario == 'external-stop':
                halt_path(space.control).touch()
            if scenario == 'deadline':
                now[0] = 90
        sink.during = during
        def prompt(batch, token):
            assert batch.encode() == plan.canonical and token.startswith(plan.digest + ' ')
            return 'yes' if scenario == 'unapproved' else token
        kwargs = dict(sink=sink, owner_prompt=prompt, principal='guest' if scenario == 'guest' else 'owner',
                      clock=lambda: now[0])
        assert run_mouse_fixture(queue, 'errand', plan, capture=lambda: seats[len(sink.calls)], **kwargs) == outcome
        assert sink.calls == points
        if scenario == 'approved':
            queue.close()
            queue = ParkedQueue(space)
            assert run_mouse_fixture(queue, 'errand', plan, capture=lambda: seats[0], **kwargs) == 'refused/replay-or-budget'
            assert sink.calls == points
        queue.close()


def test_normal_gate_has_no_tier_three_authority():
    assert adjudicate(3, 3).verdict == 'refused'
    assert adjudicate(3, 3, _mouse_key=True).verdict == 'refused'
