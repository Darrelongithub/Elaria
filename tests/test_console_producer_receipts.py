"""4218ef0 consumer contract; real receipt metadata, no producer/protected edits."""
import asyncio
import copy
import os
import subprocess

import pytest
from test_console_wire_bridge import (
    ANSWER,
    FakeRPC,
    hello,
    observed,
    read_until,
    running,
    send,
    wire,
)
from test_console_wire_bridge import bridge_module as bridge

REMEMBER = {'receipt': 'remember', 'fact_id': 7, 'kind': 'profile', 'source': 'stated',
            'confidence': .9, 'active': True, 'retention': 'until_forgotten',
            'restore': 'row_preserved_no_api', 'stored': 'must not copy arbitrary text'}
FORGET = {'receipt': 'forget', 'forgotten': 2, 'fact_ids': [7, 8],
          'facts': [{'id': 7, 'kind': 'profile', 'ts': 'synthetic', 'state': 'inactive'},
                    {'id': 8, 'kind': 'profile', 'ts': 'synthetic', 'state': 'still-active'}],
          'corr_id': 'a' * 32, 'corr_ts': '2026-10-31T12:00:00+00:00',
          'declared': {'versions': 'absent — facts carry no version column',
                       'durable_receipt': 'absent — no receipts table'}}


def result(receipt):
    return {**ANSWER, 'via': 'local-intent', 'reply': 'Producer reply', 'receipt': receipt,
            'message_id': 42, 'user_message_id': 41, 'conversation_id': 3}


def test_actual_remember_fields_and_causal_ids_not_obsolete_gaps_or_tail():
    data = result(REMEMBER)
    data['conversation'] = {'id': 3, 'messages': [{'id': 999, 'role': 'assistant',
        'channel': 'console', 'via': 'local-intent', 'text': 'Producer reply'}]}
    notes = observed(data, 'remember something')
    for fragment in ['fact #7', 'kind=profile', 'source=stated', 'active=true', 'confidence=0.9',
                     'until_forgotten', 'row_preserved_no_api', 'assistant message: #42',
                     'user message: #41']:
        assert fragment in notes
    assert 'not supplied' not in notes.replace('Operation journal reference: not supplied', '')
    assert '#999' not in notes and 'must not copy' not in notes


@pytest.mark.parametrize('count', [0, 2])
def test_forget_receipt_keeps_real_states_and_correlation(count):
    receipt = copy.deepcopy(FORGET)
    receipt.update(forgotten=count, fact_ids=receipt['fact_ids'][:count], facts=receipt['facts'][:count])
    notes = observed(result(receipt), 'forget something')
    assert 'a' * 32 in notes and receipt['corr_ts'] in notes
    assert 'versions and durable receipt absent' in notes and 'Deactivation-not-erasure' in notes
    if count:
        assert 'Fact #7' in notes and 'readback=inactive' in notes
        assert 'Fact #8' in notes and 'readback=still-active' in notes
    else:
        assert 'no match; no fact was deactivated' in notes


@pytest.mark.parametrize('receipt', [None, {}, {'receipt': 'remember'},
    {**REMEMBER, 'active': False}, {**REMEMBER, 'confidence': float('nan')},
    {**REMEMBER, 'fact_id': True}, {**REMEMBER, 'kind': '<img onerror=oops>'},
    {**FORGET, 'fact_ids': [7, 7]}, {**FORGET, 'forgotten': True},
    {**FORGET, 'facts': [None, {}]}, {**FORGET, 'corr_id': 'untrusted html'}])
def test_missing_malformed_receipts_fail_closed_without_prose_inference(receipt):
    assert bridge.fact_receipt_rows(receipt) is None
    notes = observed(result(receipt), 'remember something')
    assert 'Fact ID and kind: not supplied or invalid' in notes
    assert '<img' not in notes


def test_receipts_not_shown_for_model_or_withheld_or_mock():
    for patch in [{'via': 'gemini'}, {'withheld': {'reason': 'synthetic'}}, {'fixture': 'mock'}]:
        notes = observed({**result(REMEMBER), **patch}, 'remember something')
        assert 'fact #7' not in notes


def test_null_causal_ids_do_not_fall_back_to_tail():
    data = result(None)
    data.update(message_id=None, user_message_id=None)
    notes = observed(data, 'hello')
    assert 'Causal assistant message: absent' in notes and 'Causal user message: absent' in notes
    assert 'conversation-tail' not in notes


async def test_structured_receipt_survives_real_wire_without_audio():
    rpc = FakeRPC(result={**result(REMEMBER), 'audio': 'synthetic-never-play'})
    async with running(rpc) as instance, wire(instance) as ws:
        await hello(ws)
        await read_until(ws, 'hello-ok')
        await send(ws, text='remember something')
        reply, _ = await read_until(ws, 'reply')
        assert 'fact #7' in '\n'.join(reply['attribution']) and 'audio' not in reply
        assert rpc.says[0][1] == {'text': 'remember something', 'speak': False, 'history_limit': 1}


def test_pinned_real_remember_forget_methods_produce_accepted_metadata():
    """Unchanged local immutable methods on synthetic storage; NOT live backend wiring."""
    import ast
    import types
    import uuid

    from assistant.cost import iso_now

    command = ['git', '-c', 'protocol.allow=never', '--no-replace-objects', 'cat-file', 'blob',
               '4218ef02be7627e787a2a5fe457ae553b80381ae:src/assistant/daemon.py']
    run = subprocess.run(command, capture_output=True, env={**os.environ, 'GIT_ALLOW_PROTOCOL': ''}, check=False)
    if run.returncode:
        pytest.skip('pinned producer object not local; no automatic fetch')
    cls = next(n for n in ast.parse(run.stdout).body if isinstance(n, ast.ClassDef) and n.name == 'Daemon')
    methods = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name in {'_read_fact', '_memory_remember', '_memory_forget'}]
    assert len(methods) == 3
    ns = {'asyncio': asyncio, 'uuid': uuid, 'iso_now': iso_now}
    code = compile(ast.fix_missing_locations(ast.Module(body=methods, type_ignores=[])),
                   '<pinned-receipt-seam>', 'exec')
    exec(code, ns)  # noqa: S102 -- immutable local test source only
    row = {'id': 7, 'kind': 'profile', 'source': 'stated', 'confidence': .9, 'active': True, 'ts': iso_now()}

    def forget(_topic):
        row['active'] = False
        return 1, [7]

    obj = types.SimpleNamespace(store=types.SimpleNamespace(list_facts=lambda **_kw: [row],
                                forget_facts_detailed=forget),
                                memory=types.SimpleNamespace(remember=lambda *_a, **_kw: 7))
    obj._read_fact = types.MethodType(ns['_read_fact'], obj)
    remembered = asyncio.run(ns['_memory_remember'](obj, {'text': 'synthetic'}))
    forgotten = asyncio.run(ns['_memory_forget'](obj, {'topic': 'synthetic'}))
    assert bridge.fact_receipt_rows({'receipt': 'remember', **remembered})
    assert 'readback=inactive' in '\n'.join(bridge.fact_receipt_rows({'receipt': 'forget', **forgotten}))
