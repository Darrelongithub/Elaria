"""BUG-B4 regression: run_mouse_fixture() verification must never pass on
stale/cached frames, and click-loop detection must catch periods >= 4.

Every repro in reports/BUGHUNT-B-20261126.md (BUG-B4) is a test here. The
report's exact stale-frame shape (pre-click frame captured_at=5.0 and
post-click frame captured_at=1.0, both frame_id='same-stale-id', at
clock()=100.0) completed the batch with a verified click before the fix.

No test launches a process, touches owner files, or leaves the sandbox.
"""
from __future__ import annotations

from dataclasses import replace

from assistant.hands.plan import Plan, Step
from assistant.hands.queue import ParkedQueue
from assistant.hands.runner import FakeMouseInput, MouseSeat, mouse_screen, run_mouse_fixture
from assistant.hands.sandbox import SyntheticSpace
from assistant.observation import Element, Frame, Output


def make_seat(png, *, frame_id='frame', captured_at=0.0, x=40.0):
    elements = (Element('one', 'First', 'button', (x, 20, 20, 10)),)
    frame = Frame(frame_id, 'snapshot', png, 100, 100,
                  Output('fixture', (0, 0, 100, 100), 1), captured_at, elements, 'app')
    return MouseSeat(frame, 'window', True, True, True)


def serve(seats):
    """Drive a batch over a fixed capture sequence; one frame per observe."""
    n = [0]

    def capture():
        i = min(n[0], len(seats) - 1)
        n[0] += 1
        return seats[i]

    return capture, n


def run(space, q, plan, seats, clock_value=0.0):
    capture, n = serve(seats)
    sink = FakeMouseInput()
    outcome = run_mouse_fixture(q, 'errand', plan, capture=capture, sink=sink,
                                owner_prompt=lambda batch, token: token,
                                principal='owner', clock=lambda: clock_value)
    return outcome, sink


def one_click_plan(space, before_seat, after_seat, *, name='First'):
    return Plan((Step(0, 3, 'click', ('window', 'button', name,
                                      mouse_screen(before_seat), mouse_screen(after_seat)),
                      str(space.work)),))


# --- the report's exact repro: same-stale-id frames around the click


def test_bug_b4_cached_stale_frames_never_complete_a_batch():
    with SyntheticSpace() as space:
        q = ParkedQueue(space)
        pre = make_seat('before', frame_id='same-stale-id', captured_at=5.0)
        post = make_seat('after', frame_id='same-stale-id', captured_at=1.0)
        plan = one_click_plan(space, pre, post)
        q.register('errand', plan)
        # initial/pre-click/recheck all serve the pre-click frame, then the
        # cached post-click frame: nothing here is a fresh capture.
        outcome, sink = run(space, q, plan, [pre, pre, pre, post], clock_value=100.0)
        assert outcome == 'halted/stale-frame'  # never 'complete'
        assert sink.calls == []
        q.close()


def test_bug_b4_post_click_verification_rejects_stale_cached_frame():
    with SyntheticSpace() as space:
        q = ParkedQueue(space)
        fresh0 = make_seat('before', frame_id='fresh-0', captured_at=1.0)
        pre = make_seat('before', frame_id='same-stale-id', captured_at=5.0)
        fresh2 = make_seat('before', frame_id='fresh-2', captured_at=6.0)
        post = make_seat('after', frame_id='same-stale-id', captured_at=1.0)
        plan = one_click_plan(space, pre, post)
        q.register('errand', plan)
        outcome, sink = run(space, q, plan, [fresh0, pre, fresh2, post], clock_value=100.0)
        # the click happened; the stale post-click buffer cannot verify it
        assert outcome == 'halted/stale-frame'
        assert sink.calls == [(50.0, 25.0)]
        q.close()


def test_bug_b4_post_click_frame_must_be_captured_after_the_click():
    with SyntheticSpace() as space:
        q = ParkedQueue(space)
        seats = [make_seat('before', frame_id=f'f{i}', captured_at=float(i + 1))
                 for i in range(3)]
        post = make_seat('after', frame_id='f3', captured_at=4.0)
        plan = one_click_plan(space, seats[1], post)
        q.register('errand', plan)
        # every capture is unique and newer than the last, yet all of them
        # predate the click moment (clock()=100.0): not captured after it.
        outcome, sink = run(space, q, plan, [*seats, post], clock_value=100.0)
        assert outcome == 'halted/stale-frame'
        assert len(sink.calls) == 1
        q.close()


def test_bug_b4_duplicate_frame_id_rejects_post_click_verification():
    with SyntheticSpace() as space:
        q = ParkedQueue(space)
        a = make_seat('before', frame_id='a', captured_at=1.0)
        b = make_seat('before', frame_id='b', captured_at=2.0)
        c = make_seat('before', frame_id='c', captured_at=3.0)
        b2 = make_seat('after', frame_id='b', captured_at=4.0)  # cached id, newer clock
        plan = one_click_plan(space, b, b2)
        q.register('errand', plan)
        outcome, sink = run(space, q, plan, [a, b, c, b2], clock_value=0.0)
        assert outcome == 'halted/stale-frame'
        assert len(sink.calls) == 1
        q.close()


# --- the report's second repro: a 4-state click cycle escapes recent[-3:]


def test_bug_b4_click_loop_of_period_four_is_caught():
    with SyntheticSpace() as space:
        q = ParkedQueue(space)
        seats = [make_seat(f'state-{i}', x=40.0 + 10 * i) for i in range(4)]
        hashes = [mouse_screen(s) for s in seats]
        steps = []
        shown = [0]
        for i in range(12):
            j = i % 4
            steps.append(Step(i, 3, 'click', ('window', 'button', 'First',
                                              hashes[j], hashes[(j + 1) % 4]), str(space.work)))
            shown += [j, j, (j + 1) % 4]  # pre, recheck, post per step
        plan = Plan(tuple(steps))
        q.register('errand', plan)
        sink = FakeMouseInput()
        n = [0]

        def capture():
            i = n[0]
            n[0] += 1
            seat = seats[shown[i]]
            return replace(seat, frame=replace(seat.frame, frame_id=f'fresh-{i}',
                                              snapshot_id=f'snap-{i}', captured_at=float(i + 1)))

        outcome = run_mouse_fixture(q, 'errand', plan, capture=capture, sink=sink,
                                    owner_prompt=lambda batch, token: token,
                                    principal='owner', clock=lambda: 0.0)
        # steps 0 and 4 repeat the identical (window, element.id, before) triple
        assert outcome == 'halted/click-loop'
        assert len(sink.calls) == 4
        q.close()


# --- control: a fresh capture chain still verifies normally


def test_bug_b4_fresh_capture_chain_still_verifies():
    with SyntheticSpace() as space:
        q = ParkedQueue(space)
        pre = make_seat('before', x=40.0)
        post = make_seat('after', x=40.0)
        plan = one_click_plan(space, pre, post)
        q.register('errand', plan)
        fresh = [make_seat('before', frame_id=f'f{i}', captured_at=float(i + 1))
                 for i in range(3)] + [make_seat('after', frame_id='f3', captured_at=4.0)]
        outcome, sink = run(space, q, plan, fresh, clock_value=0.0)
        assert outcome == 'complete'
        assert sink.calls == [(50.0, 25.0)]
        q.close()
