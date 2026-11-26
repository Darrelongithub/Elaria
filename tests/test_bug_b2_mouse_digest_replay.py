"""BUG-B2 regression: tier-3 mouse plan.digest claims bind errand + expiry.

Every repro in reports/BUGHUNT-B-20261126.md (BUG-B2) is a test here:

- a digest is claimable exactly once, globally (not per-errand): replaying an
  identical plan under a fresh errand string can never re-claim it;
- the 12-click budget is per digest, never reset per errand;
- click counts reject bool/non-int;
- run_mouse_fixture() checks queue.current(errand, digest) before executing
  (including after owner_prompt, where a plan can be superseded mid-wait);
- parked asks get an enforced TTL in decide()/claim();
- the burnt claim binds its errand and expiry, enforced per click.

No test launches a process, touches owner files, or leaves the sandbox.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from assistant.hands.plan import Plan, Step
from assistant.hands.queue import ASK_TTL_S, ParkedQueue
from assistant.hands.runner import FakeMouseInput, MouseSeat, mouse_screen, run_mouse_fixture
from assistant.hands.sandbox import SyntheticSpace
from assistant.observation import Element, Frame, Output


@pytest.fixture
def queue():
    with SyntheticSpace() as space:
        queue = ParkedQueue(space)
        yield space, queue
        queue.close()


def make_plan(space, names=('First', 'Second'), states=3):
    elements = (Element('one', 'First', 'button', (10, 10, 10, 10)),
                Element('two', 'Second', 'button', (30, 10, 10, 10)))
    base = Frame('frame', 'snapshot', 'pixels', 100, 100,
                 Output('fixture', (0, 0, 100, 100), 1), 0, elements, 'app')
    seats = [MouseSeat(replace(base, png_sha256=str(i)), 'window', True, True, True)
             for i in range(states)]
    hashes = list(map(mouse_screen, seats))
    plan = Plan(tuple(Step(i, 3, 'click', ('window', 'button', name, *hashes[i:i + 2]),
                           str(space.work)) for i, name in enumerate(names)))
    return plan, seats


# --- repro: identical digest re-claimed under a fresh errand resets the budget


def test_bug_b2_digest_claim_is_exactly_once_globally(queue):
    _, q = queue
    assert q.claim_mouse_digest('errand-1', 'a' * 64, 12)
    # identical digest, fresh errand string: 24 total clicks before the fix
    assert not q.claim_mouse_digest('errand-2', 'a' * 64, 12)
    assert not q.claim_mouse_digest('errand-1', 'a' * 64, 12)


def test_bug_b2_click_budget_is_per_digest_not_per_errand(queue):
    _, q = queue
    assert q.claim_mouse_digest('errand-1', 'a' * 64, 12)
    # a different digest carries its own 12-click budget; nothing resets on errand
    assert q.claim_mouse_digest('errand-1', 'b' * 64, 12)
    assert not q.claim_mouse_digest('errand-1', 'c' * 64, 13)
    assert not q.claim_mouse_digest('errand-1', 'd' * 64, 0)


# --- repro: isinstance(True, int) passed 1 <= True <= 12


@pytest.mark.parametrize('bad', [True, False, '12', 3.0, None])
def test_bug_b2_click_count_type_is_strict(queue, bad):
    _, q = queue
    with pytest.raises(ValueError):
        q.claim_mouse_digest('errand-1', 'b' * 64, bad)


# --- the claim binds errand + expiry


def test_bug_b2_claim_binds_errand_and_expiry(queue):
    _, q = queue
    assert q.claim_mouse_digest('errand-1', 'f' * 64, 3)
    row = q.mouse_claim('f' * 64)
    assert row['errand'] == 'errand-1' and row['clicks'] == 3
    assert row['expires'] > row['created']
    assert q.claim_binds('errand-1', 'f' * 64)
    assert not q.claim_binds('errand-2', 'f' * 64)
    q._db.execute("UPDATE mouse_claims SET expires=0 WHERE digest=?", ('f' * 64,))
    assert not q.claim_binds('errand-1', 'f' * 64)


# --- run_mouse_fixture() must check queue.current(errand, digest) before executing


def test_bug_b2_run_mouse_refuses_unregistered_errand(queue):
    space, q = queue
    plan, seats = make_plan(space)
    sink = FakeMouseInput()
    outcome = run_mouse_fixture(q, 'errand', plan, capture=lambda: seats[0], sink=sink,
                                owner_prompt=lambda batch, token: token, principal='owner',
                                clock=lambda: 0.0)
    assert outcome == 'refused/stale-plan'
    assert sink.calls == []


def test_bug_b2_run_mouse_refuses_plan_superseded_during_prompt(queue):
    space, q = queue
    plan, seats = make_plan(space)
    superseded, _ = make_plan(space, names=('Second', 'First'))
    q.register('errand', plan)

    def prompt(batch, token):
        q.register('errand', superseded)  # superseded while the owner was deciding
        return token

    sink = FakeMouseInput()
    outcome = run_mouse_fixture(q, 'errand', plan, capture=lambda: seats[0], sink=sink,
                                owner_prompt=prompt, principal='owner', clock=lambda: 0.0)
    assert outcome == 'refused/stale-plan'
    assert sink.calls == []


# --- the burnt claim must keep binding its errand inside its expiry, per click


@pytest.mark.parametrize('tamper', [
    "UPDATE mouse_claims SET errand='other'",
    "UPDATE mouse_claims SET expires=0",
])
def test_bug_b2_run_mouse_halts_when_claim_stops_binding(queue, tamper):
    space, q = queue
    plan, seats = make_plan(space)
    q.register('errand', plan)
    sink = FakeMouseInput()

    def during():
        if len(sink.calls) == 1:
            q._db.execute(tamper)

    sink.during = during
    n = [0]

    def capture():
        j = n[0]
        n[0] += 1
        seat = seats[[0, 0, 0, 1, 1, 1, 2][min(j, 6)]]
        return replace(seat, frame=replace(seat.frame, frame_id=f'fresh-{j}',
                                          snapshot_id=f'snap-{j}', captured_at=float(j + 1)))

    outcome = run_mouse_fixture(q, 'errand', plan, capture=capture, sink=sink,
                                owner_prompt=lambda batch, token: token, principal='owner',
                                clock=lambda: 0.0)
    assert outcome == 'halted/stale-claim'
    assert len(sink.calls) == 1


# --- parked asks get an enforced TTL


def test_bug_b2_parked_asks_get_enforced_ttl(queue, monkeypatch):
    space, q = queue

    def at(t):
        monkeypatch.setattr('assistant.hands.queue.time.time', lambda: t)

    def fresh_plan(i):
        plan = Plan((Step(0, 2, 'type', (f'text-{i}',), str(space.work)),))
        q.register(f'errand-{i}', plan)
        return plan

    # inside the window an ask is decided and claimed normally
    plan1 = fresh_plan(1)
    at(1000.0)
    ask1 = q.park('errand-1', plan1, 0)
    assert q.decide(ask1['id'], plan1.digest, 'yes') == 'yes'
    assert q.claim('errand-1', plan1, 0, needs_yes=True)

    # past the TTL a parked ask is never decided, and expires to 'stale'
    plan2 = fresh_plan(2)
    at(2000.0)
    ask2 = q.park('errand-2', plan2, 0)
    at(2000.0 + ASK_TTL_S + 1)
    assert q.decide(ask2['id'], plan2.digest, 'yes') == 'stale'
    assert not q.claim('errand-2', plan2, 0, needs_yes=True)
    # a re-park after expiry mints a fresh ask in a fresh window
    at(3000.0)
    fresh = q.park('errand-2', plan2, 0)
    assert fresh['id'] != ask2['id'] and fresh['state'] == 'pending'
    assert q.decide(fresh['id'], plan2.digest, 'yes') == 'yes'
    assert q.claim('errand-2', plan2, 0, needs_yes=True)

    # an approval that ages out before dispatch never dispatches
    plan3 = fresh_plan(3)
    at(4000.0)
    ask3 = q.park('errand-3', plan3, 0)
    assert q.decide(ask3['id'], plan3.digest, 'yes') == 'yes'
    at(4000.0 + ASK_TTL_S + 1)
    assert not q.claim('errand-3', plan3, 0, needs_yes=True)


# --- residual: a plan superseded WHILE the batch is clicking

def test_bug_b2_run_mouse_halts_when_plan_superseded_mid_batch(queue):
    """queue.current() is re-checked per step, not only around owner_prompt.

    The owner may revise an errand at any moment; a revised plan must not keep
    clicking on the old one's authority. Before this check the batch ran to
    'complete' with both clicks of the superseded plan.
    """
    space, q = queue
    elements = (Element('one', 'First', 'button', (10, 10, 10, 10)),
                Element('two', 'Second', 'button', (30, 10, 10, 10)))
    base = Frame('frame', 'snapshot', 'pixels', 100, 100,
                 Output('fixture', (0, 0, 100, 100), 1), 0, elements, 'app')
    seats = [MouseSeat(replace(base, png_sha256=str(i)), 'window', True, True, True)
             for i in range(4)]
    hashes = list(map(mouse_screen, seats))
    plan = Plan((Step(0, 3, 'click', ('window', 'button', 'First', hashes[0], hashes[1]),
                      str(space.work)),
                 Step(1, 3, 'click', ('window', 'button', 'Second', hashes[1], hashes[2]),
                      str(space.work))))
    revised = Plan((Step(0, 3, 'click', ('window', 'button', 'Second', hashes[0], hashes[1]),
                         str(space.work)),))
    q.register('errand', plan)
    sink = FakeMouseInput()
    order = [0, 0, 0, 1, 1, 1, 2]
    n = [0]

    def capture():
        i = n[0]
        n[0] += 1
        seat = seats[order[min(i, 6)]]
        return replace(seat, frame=replace(seat.frame, frame_id=f'fresh-{i}',
                                          snapshot_id=f'snap-{i}', captured_at=float(i + 1)))

    def during():
        if len(sink.calls) == 1:
            q.register('errand', revised)  # owner revised the errand mid-batch

    sink.during = during
    outcome = run_mouse_fixture(q, 'errand', plan, capture=capture, sink=sink,
                                owner_prompt=lambda batch, token: token,
                                principal='owner', clock=lambda: 0.0)
    assert outcome == 'halted/stale-plan'
    assert len(sink.calls) == 1  # the superseded plan's second click never fires
