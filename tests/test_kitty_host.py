"""Narrow granted daemon mount, native assessor and durable recovery; all RC peers fake."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import threading
from dataclasses import asdict

import pytest
from test_kitty_hands import FakeKitty, checker
from test_kitty_hands import private as private  # noqa: PLC0414 - pytest fixture registration

from assistant.hands.kitty.bridge import Bridge
from assistant.hands.kitty.checker import OPAQUE, NativeChecker, validate_payload
from assistant.hands.kitty.host import KittyMount, Session, native_effect
from assistant.hands.kitty.policy import (
    Act,
    Authorizer,
    Consent,
    canonical,
    digest,
    inventory,
)
from assistant.hands.kitty.recovery import RecoveryLedger
from assistant.hands.kitty.surface import resolve
from assistant.ipc import IpcPrincipal, call


def event(plan, **extra):
    return {'kind': 'kitty.act', 'plan_hash': plan, 'phase': 'intent', **extra}


def principal():
    return IpcPrincipal(os.getpid(), os.getuid(), os.getgid())


def build_session(private, fake=None, assessor=None):
    ledger = RecoveryLedger(private / 'kitty.jsonl')
    return Session(fake or FakeKitty(), assessor or NativeChecker(), ledger, digest('synthetic endpoint'))


def prepare(verb='ls', payload=None, ids=None, tier=0, nonce=None):
    result = {'op': 'prepare', 'verb': verb, 'payload': payload or {}, 'target_ids': ids or [], 'model_tier': tier}
    if nonce:
        result['nonce'] = nonce
    return result


def test_ledger_lifetime_lock_and_reacquire(private):
    path = private / 'ledger'
    ledger = RecoveryLedger(path)
    with pytest.raises(OSError):
        RecoveryLedger(path)
    ledger(event(digest('act'), operation='act'))
    ledger.close()
    restored = RecoveryLedger(path)
    auth = Authorizer(checker())
    restored.restore(auth)
    assert digest('act') in auth.consumed
    assert auth.hand_ref is None
    restored.close()


@pytest.mark.parametrize('body', [b'{', b'{}\n', b'not-json\n'])
def test_corrupt_ledger_never_repairs_or_opens_dispatch(private, body):
    path = private / 'ledger'
    path.write_bytes(body)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        RecoveryLedger(path)
    assert path.read_bytes() == body


@pytest.mark.parametrize('phase,operation,spent', [('intent', 'act', True), ('result', 'act', False),
                                                   ('intent', 'probe', False), ('intent', None, True)])
def test_crash_recovery_spends_intent_not_new_probe(private, phase, operation, spent):
    path = private / 'ledger'
    ledger = RecoveryLedger(path)
    key = digest('synthetic plan')
    ledger(event(key, phase=phase, operation=operation))
    ledger.close()
    ledger = RecoveryLedger(path)
    auth = Authorizer(checker())
    ledger.restore(auth)
    assert (key in auth.consumed) is spent
    ledger.close()


def test_exact_yes_recovers_no_is_terminal_and_endpoint_cannot_change(private):
    ledger = RecoveryLedger(private / 'ledger')
    key, endpoint = digest('plan'), digest('endpoint')
    consent = Consent(secrets.token_hex(12), key, digest('target'), digest('payload'), True, True)
    record = event(key, phase='decision', choice='yes', consent=asdict(consent), endpoint_ref=endpoint)
    ledger(record)
    auth = Authorizer(checker())
    ledger.restore(auth, endpoint)
    assert auth.consent[key] == consent and auth.hand_ref is None
    other = Authorizer(checker())
    ledger.restore(other, digest('other endpoint'))
    assert other.consent == {}
    ledger(record | {'choice': 'no'})
    ledger(record)
    restored = Authorizer(checker())
    ledger.restore(restored, endpoint)
    assert key in restored.denied and key not in restored.consent
    ledger.close()


def test_cancel_intent_survives_crash_even_without_cancel_result(private):
    ledger = RecoveryLedger(private / 'ledger')
    key = digest('plan')
    ledger(event(key, phase='cancel-intent'))
    ledger.close()
    ledger = RecoveryLedger(private / 'ledger')
    auth = Authorizer(checker())
    ledger.restore(auth)
    assert key in auth.denied
    ledger.close()


def test_native_classifier_accounts_for_every_pinned_verb_and_unknown_fails_closed():
    assessor = NativeChecker()
    assert set(assessor.coverage()) == set(inventory()['verbs'])
    assert len(assessor.coverage()) == 39
    result = assessor(Act('future-verb', '{}'), 'plan', ())
    assert result.denied and result.nature == 'unknown'


@pytest.mark.parametrize('verb', sorted(OPAQUE))
def test_opaque_effects_not_approved_by_asserted_safe_model_tier(verb):
    result = NativeChecker()(Act(verb, '{}'), 'plan', ())
    assert result.denied


@pytest.mark.parametrize('payload', [{'all_env_vars': 'false'}, {'output_format': 1}, {'unsafe_field': True}])
def test_wire_types_and_unknown_fields_fail_strict(payload):
    with pytest.raises(ValueError):
        validate_payload(Act('ls', canonical(payload)), inventory())


def test_native_halt_blocks_even_k1():
    assert NativeChecker(halted=lambda: True)(Act('ls', '{}'), 'plan', ()).denied
    assert NativeChecker()(Act('ls', '{}'), 'plan', ()).legacy_tier == 0
    p = Act('set-colors', canonical({'colors': {}, 'configured': True}))
    a = NativeChecker()(p, 'plan', ())
    assert a.nature == 'irreversible' and a.legacy_tier == 2


def targets():
    return [{'id': 1, 'pid': 101, 'cmdline': ['synthetic'], 'tab_id': 20, 'os_id': 30},
            {'id': 2, 'pid': 102, 'cmdline': ['synthetic'], 'tab_id': 20, 'os_id': 30},
            {'id': 3, 'pid': 103, 'cmdline': ['synthetic'], 'tab_id': 21, 'os_id': 31}]


@pytest.mark.parametrize('verb,payload,ids,expected', [
    ('get-text', {'match': 'id:1'}, (1,), [1]),
    ('close-tab', {'match': 'id:20'}, (1,), [1, 2]),
    ('resize-os-window', {'match': 'id:1'}, (1,), [1, 2]),
    ('set-colors', {'match_tab': 'id:20'}, (1,), [1, 2]),
    ('ls', {}, (), [1, 2, 3]),
    ('set-colors', {'all': True}, (1, 2, 3), [1, 2, 3]),
])
def test_explicit_target_scope_expansion(verb, payload, ids, expected):
    assert [w['id'] for w in resolve(Act(verb, canonical(payload), ids), targets())] == expected


@pytest.mark.parametrize('payload,ids', [({}, (1,)), ({'match': 'title:.*'}, (1,)),
                                        ({'match': 'id:2'}, (1,)), ({'self': True}, (1,)),
                                        ({'all': True}, (1,))])
def test_selectors_cannot_widen_or_silently_use_active(payload, ids):
    with pytest.raises(PermissionError):
        resolve(Act('set-colors', canonical(payload), ids), targets())


def test_native_effect_requires_intended_delta_same_identity():
    act = Act('set-window-title', canonical({'match': 'id:1', 'title': 'synthetic new'}), (1,))
    before = [targets()[0] | {'title': 'old'}]
    after = [before[0] | {'title': 'synthetic new'}]
    assert native_effect(act, before, after, {'ok': True})
    assert not native_effect(act, after, after, {'ok': True})
    assert not native_effect(act, before, [after[0] | {'pid': 999}], {'ok': True})


async def test_mount_is_inert_authenticates_and_rejects_request_supplied_authority(private):
    calls = []
    mount = KittyMount(private, factory=lambda *_: calls.append('attach'))
    assert not calls
    with pytest.raises(PermissionError):
        await mount.handle({'uid': os.getuid()}, {'op': 'status'})
    with pytest.raises(PermissionError):
        await mount.handle(IpcPrincipal(1, os.getuid() + 1, 0), {'op': 'status'})
    assert (await mount.handle(principal(), {'op': 'status'}))['attached'] is False
    with pytest.raises(ValueError):
        await mount.handle(principal(), {'op': 'attach', 'public_key': 'public', 'checker': 'safe'})
    with pytest.raises(ValueError):
        await mount.handle(principal(), {'op': 'open-hand', 'phrase': 'kitty hand open'})
    assert not calls
    await mount.aclose()


async def test_mount_k1_journal_crash_recovery_and_no_automatic_hand(private):
    mount = KittyMount(private, factory=lambda *_: build_session(private))
    await mount.handle(principal(), {'op': 'attach', 'public_key': 'synthetic-public'})
    description = await mount.handle(principal(), prepare())
    assert description['tier'] == 'K1' and not description['requires_consent']
    await mount.handle(principal(), {'op': 'run', 'plan_hash': description['plan_hash']})
    await mount.handle(principal(), {'op': 'open-hand', 'phrase': 'kitty hand open'})
    await mount.aclose()
    second = KittyMount(private, factory=lambda *_: build_session(private))
    assert not (await second.handle(principal(), {'op': 'attach', 'public_key': 'synthetic-public'}))['hand_open']
    with pytest.raises(ValueError):
        await second.handle(principal(), prepare(nonce=description['nonce']))
    await second.aclose()


async def test_mount_decisions_durable_exact_and_request_shape_locked(private):
    mount = KittyMount(private, factory=lambda *_: build_session(private))
    await mount.handle(principal(), {'op': 'attach', 'public_key': 'synthetic-public'})
    data = prepare('set-colors', {'colors': {}, 'configured': True, 'match_window': 'id:1'}, [1], 2)
    plan = await mount.handle(principal(), data)
    assert plan['tier'] == 'K3' and plan['requires_consent']
    request = {'op': 'decide', 'plan_hash': plan['plan_hash'], 'choice': 'no',
               'execute_newline': False, 'program_acknowledged': False}
    await mount.handle(principal(), request)
    with pytest.raises(ValueError):
        await mount.handle(principal(), request | {'choice': 'yes'})
    await mount.aclose()
    second = KittyMount(private, factory=lambda *_: build_session(private))
    await second.handle(principal(), {'op': 'attach', 'public_key': 'synthetic-public'})
    with pytest.raises(ValueError):
        await second.handle(principal(), data | {'nonce': plan['nonce']})
    await second.aclose()


def test_real_daemon_mount_is_bound_authenticated_and_has_no_startup_io(config, running_daemon):
    daemon, _ = running_daemon
    assert daemon._kitty_mount.session is None
    assert daemon._handlers()['kitty.request'].__self__ is daemon
    with pytest.raises(PermissionError):
        asyncio.run(daemon.handle('kitty.request', {'op': 'status'}))
    result = call(config.socket_path, 'kitty.request', {'op': 'status'})
    assert result == {'attached': False, 'hand_open': False, 'scene_ready': False}
    assert daemon._kitty_mount.session is None


def test_real_daemon_owner_ipc_routes_only_through_new_mount(config, running_daemon, private):
    daemon, _ = running_daemon
    # Lifecycle dependency injection for a local stub test; no method monkey-patch.
    daemon._kitty_mount = KittyMount(private, factory=lambda *_: build_session(private))
    # config.socket_path follows the env, so use the endpoint actually bound by the fixture.
    # This test's private fixture may run after running_daemon; obtain the existing server path.
    socket_path = running_daemon[1].sockets[0].getsockname()
    from pathlib import Path
    endpoint = Path(socket_path)
    assert call(endpoint, 'kitty.request', {'op': 'attach', 'public_key': 'synthetic'})['attached']
    plan = call(endpoint, 'kitty.request', prepare())
    reply = call(endpoint, 'kitty.request', {'op': 'run', 'plan_hash': plan['plan_hash']})
    assert reply['verification'] == 'response-observed'
    assert call(endpoint, 'ping', {})['pong']
    assert call(endpoint, 'kitty.request', {'op': 'detach'}) == {'attached': False}


def test_cancel_before_dispatch_is_terminal_and_durable(private):
    session = build_session(private)
    prepared = session.prepare(prepare())
    key = prepared['plan_hash']
    assert session.bridge.cancel(key)['verification'] == 'stopped-before-dispatch'
    with pytest.raises(RuntimeError):
        session.run(key)
    session.close()
    recovered = build_session(private)
    assert key in recovered.bridge.authorizer.denied
    recovered.close()


def test_async_cancel_same_request_id_and_no_false_undo(private):
    entered, release = threading.Event(), threading.Event()
    fake = FakeKitty()

    class Peer:
        def request(self, verb, payload, tier, **kw):
            if kw.get('cancel'):
                assert kw['async_id'] == self.async_id
                release.set()
                return None
            if verb == 'select-window':
                self.async_id = kw['async_id']
                entered.set()
                assert release.wait(3)
                return 1
            return fake.request(verb, payload, tier, **kw)

    ledger = RecoveryLedger(private / 'ledger')
    bridge = Bridge(Peer(), checker(), ledger)
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    act = Act('select-window', canonical({'match': 'id:20'}), (1,))
    plan = act.plan(1)
    errors = []

    def execute():
        try:
            bridge.execute(act, plan)
        except Exception as exc:
            errors.append(type(exc).__name__)

    worker = threading.Thread(target=execute)
    worker.start()
    try:
        assert entered.wait(3)
        outcome = bridge.cancel(plan.digest)
        assert outcome['verification'] == 'async-cancel-sent-effect-unknown'
    finally:
        release.set()
        worker.join(3)
        ledger.close()
    assert not worker.is_alive() and not errors
    recovered = RecoveryLedger(private / 'ledger')
    auth = Authorizer(checker())
    recovered.restore(auth)
    assert plan.digest in auth.consumed and plan.digest in auth.denied
    assert 'cancel-intent' in [r['phase'] for r in recovered.records]
    recovered.close()


def test_journal_contains_metadata_not_input(private):
    session = build_session(private)
    marker = 'synthetic private title content'
    request = prepare('set-window-title', {'title': marker, 'match': 'id:1'}, [1], 1)
    plan = session.prepare(request)
    session.bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    session.run(plan['plan_hash'])
    session.close()
    records = (private / 'kitty.jsonl').read_text()
    assert marker not in records
    assert all(json.loads(line)['kind'] == 'kitty.act' for line in records.splitlines())


def test_mismatch_counter_survives_restart_and_second_mismatch_halts(private):
    session = build_session(private, assessor=checker(1))
    params = prepare(tier=0)
    description = session.prepare(params)
    key = description['plan_hash']
    assert session.bridge.authorizer.mismatches[key] == 1
    session.close()
    recovered = build_session(private, assessor=checker(1))
    assert recovered.bridge.authorizer.mismatches[key] == 1
    with pytest.raises(PermissionError):
        recovered.prepare(params | {'nonce': description['nonce']})
    assert recovered.bridge.authorizer.mismatches[key] == 2
    recovered.close()


async def test_disconnect_does_not_release_worker_or_allow_duplicate_run(private):
    entered, release = threading.Event(), threading.Event()

    class WaitingPeer(FakeKitty):
        def request(self, verb, payload, tier, **kw):
            # Preparation probes do not block; hold only the dispatched ls request.
            if verb == 'ls' and 'cancel_event' in kw:
                entered.set()
                assert release.wait(3)
            return super().request(verb, payload, tier, **kw)

    fake = WaitingPeer()
    mount = KittyMount(private, factory=lambda *_: build_session(private, fake))
    await mount.handle(principal(), {'op': 'attach', 'public_key': 'synthetic'})
    description = await mount.handle(principal(), prepare())
    request = {'op': 'run', 'plan_hash': description['plan_hash']}
    waiter = asyncio.create_task(mount.handle(principal(), request))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        with pytest.raises(ValueError):
            await mount.handle(principal(), request)
    finally:
        release.set()
        await mount.aclose()
    assert mount.session is None and mount.worker.done()


def test_durable_ownership_recovers_only_same_endpoint(private):
    endpoint = digest('endpoint')
    identity = digest('window identity')
    ledger = RecoveryLedger(private / 'ledger')
    ledger(event(digest('create'), phase='result', verification='created-id-and-stamp-observed',
                 endpoint_ref=endpoint, ownership=[identity]))
    session = Session(FakeKitty(), NativeChecker(), ledger, endpoint)
    assert identity in session.bridge.owned
    session.close()
    other = Session(FakeKitty(), NativeChecker(), RecoveryLedger(private / 'ledger'), digest('other'))
    assert other.bridge.owned == set()
    other.close()


async def test_explicit_hand_close_revokes_unspent_yes_across_restart(private):
    mount = KittyMount(private, factory=lambda *_: build_session(private))
    await mount.handle(principal(), {'op': 'attach', 'public_key': 'synthetic'})
    data = prepare('set-colors', {'colors': {}, 'configured': True, 'match_window': 'id:1'}, [1], 2)
    description = await mount.handle(principal(), data)
    key = description['plan_hash']
    await mount.handle(principal(), {'op': 'decide', 'plan_hash': key, 'choice': 'yes',
                                     'execute_newline': False, 'program_acknowledged': False})
    await mount.handle(principal(), {'op': 'close-hand'})
    await mount.aclose()
    second = build_session(private)
    assert key in second.bridge.authorizer.denied and key not in second.bridge.authorizer.consent
    second.close()
