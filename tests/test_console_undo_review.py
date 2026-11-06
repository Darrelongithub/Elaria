"""Focused console consumer pins, synthetic IPC only; no protected producer edit."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import subprocess

import pytest
from test_console_wire_bridge import FakeRPC, hello, read_until, running, send, wire
from test_console_wire_bridge import bridge_module as bridge

SNAPSHOT = {'op_id': 41, 'plan_id': 4, 'ts': '2026-11-01T12:00:00+00:00', 'op': 'move',
            'src': '/synthetic/original.txt', 'dst': '/synthetic/current.txt',
            'sha256_before': 'a' * 64, 'sha256_after': 'a' * 64, 'status': 'committed'}


def prepared(snapshot=None):
    snapshot = copy.deepcopy(SNAPSHOT if snapshot is None else snapshot)
    return {'token': 'b' * 32, 'snapshot': snapshot,
            'ask_sha256': hashlib.sha256(json.dumps(snapshot, sort_keys=True,
                                                  separators=(',', ':')).encode()).hexdigest(),
            'prepared_at': '2026-11-06T12:00:00+00:00', 'age_s': 0.0, 'expires_in_s': 600.0}


class PilotRPC(FakeRPC):
    def __init__(self):
        super().__init__()
        self.status['company'] = {'company': False, 'restricted': False}
        self.ask = prepared()
        self.applies = []
        self.reject_prepare = None
        self.reject_apply = None

    async def __call__(self, path, method, params, timeout):
        if method == 'undo.prepare':
            self.calls.append((method, params, timeout))
            if self.reject_prepare:
                raise bridge.UndoRefused(self.reject_prepare)
            return copy.deepcopy(self.ask)
        if method == 'undo.apply':
            self.applies.append(params)
            if self.reject_apply:
                raise self.reject_apply
            return {'decision': params['decision'], 'undone': int(params['decision'] == 'yes'),
                    'problems': [], 'ask_sha256': self.ask['ask_sha256'], 'age_s': 1.0}
        return await super().__call__(path, method, params, timeout)


async def card(ws, text='undo since 2h'):
    await hello(ws)
    await read_until(ws, 'hello-ok')
    await send(ws, request_id=1, text=text)
    return (await read_until(ws, 'reply'))[0]


async def decide(ws, review, decision='yes', request_id=2, **fields):
    payload = {'t': 'undo-decision', 'id': request_id, 'review_id': review['review_id'],
               'ask_sha256': review['ask_sha256'], 'decision': decision, **fields}
    await ws.send(json.dumps(payload))
    return (await read_until(ws, 'reply'))[0]


@pytest.mark.parametrize('text,scope', [
    ('undo since 2h', {'since': '2h'}), ('Elaria, undo since 2h', {'since': '2h'}),
    ('rudisha tangu 2h', {'since': '2h'}), ('tenda upya tangu 2h', {'since': '2h'}),
    ('undo review #41', {'op_id': 41}),
])
async def test_scoped_typed_undo_only_prepares_until_focused_decision(text, scope):
    rpc = PilotRPC()
    async with running(rpc) as _, wire(_) as ws:
        reply = await card(ws, text)
        assert reply['undo_review']['snapshot'] == SNAPSHOT
        assert rpc.ask['token'] not in json.dumps(reply)
        assert not rpc.says and not rpc.applies
        assert next(c[1] for c in rpc.calls if c[0] == 'undo.prepare') == scope


@pytest.mark.parametrize('decision', ['yes', 'no'])
async def test_answer_dispatches_apply_once_and_replay_reads_already_answered(decision):
    rpc = PilotRPC()
    async with running(rpc) as service, wire(service) as ws:
        review = (await card(ws))['undo_review']
        reply = await decide(ws, review, decision)
        assert 'already answered' in reply['text']
        replay = await decide(ws, review, decision, 3)
        assert 'already-answered' in replay['error']
        assert rpc.applies == [{'token': rpc.ask['token'], 'decision': decision}]
        assert not rpc.says


@pytest.mark.parametrize('change', ['expiry', 'digest', 'foreign-connection', 'new-scope', 'privacy', 'failed-edit'])
async def test_stale_unfocused_or_lapsed_ask_cannot_apply(change):
    rpc = PilotRPC()
    async with running(rpc) as service, wire(service) as ws:
        review = (await card(ws))['undo_review']
        if change == 'expiry':
            service.undo_asks[next(iter(service.undo_asks))][review['review_id']]['deadline'] = 0
        elif change == 'digest':
            review['ask_sha256'] = '0' * 64
        elif change == 'privacy':
            rpc.status['company']['company'] = True
        elif change in {'new-scope', 'failed-edit'}:
            if change == 'failed-edit':
                rpc.reject_prepare = 'nothing-undoable'
            await send(ws, request_id=2, text='undo review #42')
            await read_until(ws, 'reply')
        if change == 'foreign-connection':
            async with wire(service) as other:
                await hello(other); await read_until(other, 'hello-ok')
                reply = await decide(other, review)
        else:
            reply = await decide(ws, review, request_id=3)
        assert 'error' in reply and not rpc.applies


@pytest.mark.parametrize('failure', [bridge.IPCFailure(uncertain=True), bridge.UndoRefused('drifted/refused')])
async def test_unknown_or_drifted_decision_is_never_rearmed(failure):
    rpc = PilotRPC(); rpc.reject_apply = failure
    async with running(rpc) as service, wire(service) as ws:
        review = (await card(ws))['undo_review']
        assert 'error' in await decide(ws, review)
        assert 'error' in await decide(ws, review, request_id=3)
        assert len(rpc.applies) == 1


async def test_old_backend_without_seam_fails_closed_not_console_say():
    rpc = PilotRPC(); rpc.reject_prepare = 'refused-or-seam-unavailable'
    async with running(rpc) as service, wire(service) as ws:
        reply = await card(ws)
        assert 'seam-unavailable' in reply['error'] and not rpc.says and not rpc.applies


async def test_unknown_privacy_blocks_preparation():
    rpc = PilotRPC(); rpc.status.pop('company')
    async with running(rpc) as service, wire(service) as ws:
        assert 'private-posture' in (await card(ws))['error']
        assert not any(c[0].startswith('undo.') for c in rpc.calls)


async def test_bare_undo_remains_byte_identical_forwarding():
    rpc = PilotRPC()
    async with running(rpc) as service, wire(service) as ws:
        await card(ws, 'undo')
        assert rpc.says[0][1] == {'text': 'undo', 'speak': False, 'history_limit': 1}
        assert not rpc.applies and bridge.undo_scope('undo') is None


@pytest.mark.parametrize('mutate', [
    lambda a: a.update(token='c' * 64), lambda a: a.update(ask_sha256='c'*64),
    lambda a: a.update(expires_in_s=601), lambda a: a.update(age_s=float('nan')),
    lambda a: a['snapshot'].update(root='/invented'), lambda a: a['snapshot'].update(op_id=True),
])
def test_prepare_snapshot_schema_digest_and_expiry_are_bound(mutate):
    ask = prepared(); mutate(ask)
    with pytest.raises(bridge.UndoRefused):
        bridge.validate_undo(ask)


def test_refusal_filter_never_echoes_private_paths_tokens_or_details():
    assert bridge.undo_refusal('ValueError: /secret/path token=abc already answered') == 'already-answered'
    assert bridge.undo_refusal('ValueError: /secret/private') == 'refused-or-seam-unavailable'


def test_actual_pinned_seam_methods_without_protected_file_edits(tmp_path):
    """Read exact local source, run its unchanged seam on a synthetic recording service.

    No daemon monkeypatch, checkout or fetch. Missing local object is an explicit skip in CI.
    """
    import ast
    import time
    import types
    import uuid
    from pathlib import Path

    from assistant.cost import iso_now

    command = ['git', '-c', 'protocol.allow=never', '--no-replace-objects', 'cat-file', 'blob',
               'e7316b985e4463d961a2ec51af6a4023360a261c:src/assistant/daemon.py']
    run = subprocess.run(command, capture_output=True, env={**os.environ, 'GIT_ALLOW_PROTOCOL': ''}, check=False)
    if run.returncode:
        pytest.skip('pinned producer object not local; no automatic fetch permitted')
    tree = ast.parse(run.stdout)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Daemon')
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name in {'_undo_prepare', '_undo_apply', '_undo_preverify', '_undo_drift', '_undo'}]
    # Method bodies are unchanged; import-relative helpers resolve to the existing local library.
    isolated = ast.Module(body=methods, type_ignores=[])
    ns = {'__package__': 'assistant', 'asyncio': asyncio, 'hashlib': hashlib, 'json': json,
          'time': time, 'uuid': uuid, 'iso_now': iso_now, 'Path': Path}
    ns['log_event'] = lambda *_a, **_kw: None
    exec(compile(ast.fix_missing_locations(isolated), '<pinned-mainline-seam>', 'exec'), ns)  # noqa: S102 -- exact pinned local test source, never caller input
    current = tmp_path / 'current'; original = tmp_path / 'original'
    current.write_text('synthetic unchanged bytes')
    row = dict(SNAPSHOT, id=41, src=str(original), dst=str(current),
               sha256_before=hashlib.sha256(current.read_bytes()).hexdigest(),
               sha256_after=hashlib.sha256(current.read_bytes()).hexdigest())
    events, executions = [], []
    store = types.SimpleNamespace(get_operation=lambda _op: dict(row),
                                  log_persona_event=lambda *_args: events.append(_args))
    obj = types.SimpleNamespace(store=store, executor=types.SimpleNamespace(undo=lambda **kw: executions.append(kw) or {'undone':1,'problems':[]}),
                                _undo_asks={}, UNDO_ASK_TTL_S=600.0,
                                _require_ipc_owner=lambda: types.SimpleNamespace(uid=os.getuid(),pid=os.getpid()))
    for node in methods:
        setattr(obj, node.name, types.MethodType(ns[node.name], obj))
    for decision in ['no', 'yes']:
        ask = asyncio.run(obj._undo_prepare({'op_id': 41}))
        bridge.validate_undo(ask)
        result = asyncio.run(obj._undo_apply({'token':ask['token'], 'decision':decision}))
        assert result['decision'] == decision
        with pytest.raises(ValueError, match='already answered'):
            asyncio.run(obj._undo_apply({'token':ask['token'], 'decision':'yes'}))
    assert len(events) == 1 and executions == [{'op_id':41}]
    ask = asyncio.run(obj._undo_prepare({'op_id':41}))
    obj._undo_asks[ask['token']]['expires_at'] = 0
    with pytest.raises(ValueError, match='lapsed'):
        asyncio.run(obj._undo_apply({'token':ask['token'],'decision':'yes'}))
    ask = asyncio.run(obj._undo_prepare({'op_id':41}))
    row['status'] = 'copied'
    with pytest.raises(ValueError, match='nothing was undone'):
        asyncio.run(obj._undo_apply({'token':ask['token'],'decision':'yes'}))
    assert executions == [{'op_id':41}]
    store.undoable_operations = lambda **_kw: [row, row]
    with pytest.raises(ValueError, match='one operation'):
        asyncio.run(obj._undo_prepare({'since':'2h'}))
    current.write_text('synthetic drifted bytes')
    with pytest.raises(ValueError, match='cannot offer'):
        asyncio.run(obj._undo_prepare({'op_id':41}))
    with pytest.raises(ValueError, match='undo requires an explicit scope'):
        # Real library executor's bare refusal is pinned separately in mainline; here assert
        # the guard never delegates a scoped call, even if a JSON Yes is supplied.
        from assistant.executor import Executor
        Executor._undo_gated(types.SimpleNamespace(), op_id=None, plan_id=None, since_iso=None)
    with pytest.raises(ValueError, match='scoped undo is refused'):
        asyncio.run(obj._undo({'since':'2h','decision':'yes'}))


def test_private_card_dom_gates():
    import shutil

    from test_console_wire_bridge import ASSETS

    if not shutil.which('node') or not (ASSETS / 'node_modules/jsdom').exists():
        pytest.skip('local DOM gate needs jsdom')
    run = subprocess.run(['node', str(ASSETS / 'undo-review-test.js')], capture_output=True,
                         text=True, timeout=30, check=False)
    assert run.returncode == 0, run.stdout + run.stderr
