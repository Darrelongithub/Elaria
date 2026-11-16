"""Real console wire -> real mounted consent code -> synthetic instance; no hardware claim."""
import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest
from test_console_wire_bridge import FakeRPC, hello, read_until, running, send, wire
from test_console_wire_bridge import bridge_module as bridge
from test_hands_headless import OWNER, SyntheticInstance

from assistant.hands.headless import host
from assistant.hands.headless.consent import private_dir


class HandsRPC(FakeRPC):
    def __init__(self, mount):
        super().__init__()
        self.mount = mount
        self.status['company'] = {'company': False, 'restricted': False}

    async def __call__(self, path, method, params, timeout):
        if method == 'hands.request':
            self.calls.append((method, params, timeout))
            return await self.mount.handle(OWNER, params)
        if method == 'console.say':
            self.calls.append((method, params, timeout))
            return await self.mount.typed(lambda: OWNER, params)
        return await super().__call__(path, method, params, timeout)


@pytest.fixture
def hands(tmp_path, monkeypatch):
    monkeypatch.setattr(host, 'DedicatedKitty', SyntheticInstance)
    return host.HandsMount(private_dir(tmp_path / 'runtime-hands'))


async def control(ws, id, **fields):
    import json
    await ws.send(json.dumps({'t': 'hands-control', 'id': id, **fields}))


async def test_console_intent_card_yes_once_real_consent_chain_and_no_receipt_in_text(hands):
    rpc = HandsRPC(hands)
    async with running(rpc) as instance, wire(instance) as ws:
        await hello(ws); await read_until(ws, 'hello-ok')
        await control(ws, 1, action='open'); await read_until(ws, 'reply')
        await send(ws, 2, text='hands mkdir proof')
        reply, _ = await read_until(ws, 'reply')
        assert 'text' not in reply and 'audio' not in reply and 'error' not in reply
        ask = reply['hands']['ask']; assert 'token' not in ask and 'review_id' in ask
        assert hands.instance.calls == 0
        assert len(instance.hands_asks) == 1
        params = {'action': 'answer', 'review_id': ask['review_id'], 'digest': ask['digest'], 'decision': 'allow-once'}
        await control(ws, 3, **params)
        reply, _ = await read_until(ws, 'reply')
        assert reply['hands']['events'][-1]['verification'] == 'observed'
        assert hands.instance.calls == 1
        await control(ws, 4, **params); reply, _ = await read_until(ws, 'reply')
        assert 'hands_error' in reply and hands.instance.calls == 1
        await send(ws, 5, text='hands rm -rf /'); reply, _ = await read_until(ws, 'reply')
        assert reply['hands']['events'][-1]['phase'] == 'DENIAL'
        assert 'text' not in reply and 'error' not in reply
        assert all(call[1]['speak'] is False and call[1]['history_limit'] == 1 for call in rpc.says)
    await hands.aclose()


async def test_no_private_posture_no_dispatch_no_cross_connection_approval(hands):
    rpc = HandsRPC(hands)
    async with running(rpc) as instance, wire(instance) as ws, wire(instance) as other:
        await hello(ws); await read_until(ws, 'hello-ok')
        await hello(other); await read_until(other, 'hello-ok')
        await control(ws, 1, action='open'); await read_until(ws, 'reply')
        await send(ws, 2, text='hands mkdir proof'); reply, _ = await read_until(ws, 'reply')
        ask = reply['hands']['ask']
        await control(other, 1, action='answer', review_id=ask['review_id'], digest=ask['digest'], decision='allow-once')
        reply, _ = await read_until(other, 'reply'); assert 'hands_error' in reply
        rpc.status['company']['restricted'] = True
        await control(ws, 3, action='answer', review_id=ask['review_id'], digest=ask['digest'], decision='allow-once')
        reply, _ = await read_until(ws, 'reply'); assert 'hands_error' in reply
        assert hands.instance.calls == 0
    await hands.aclose()


async def test_old_backend_never_gets_hands_text_as_model_prompt():
    rpc = FakeRPC()
    rpc.status['company'] = {'company': False, 'restricted': False}
    async with running(rpc) as instance, wire(instance) as ws:
        await hello(ws); await read_until(ws, 'hello-ok')
        await send(ws, 1, text='hands mkdir proof')
        reply, _ = await read_until(ws, 'reply')
        assert 'hands_error' in reply and not rpc.says and 'error' not in reply


@pytest.mark.parametrize('decision', ['allow-always', 'yes', 'allow-once;rm', None])
async def test_unsupported_decisions_and_disabled_always_never_execute(hands, decision):
    rpc = HandsRPC(hands)
    async with running(rpc) as instance, wire(instance) as ws:
        await hello(ws); await read_until(ws, 'hello-ok')
        await control(ws, 1, action='open'); await read_until(ws, 'reply')
        await send(ws, 2, text='hands mkdir proof'); reply, _ = await read_until(ws, 'reply')
        ask = reply['hands']['ask']
        await control(ws, 3, action='answer', review_id=ask['review_id'], digest=ask['digest'], decision=decision)
        reply, _ = await read_until(ws, 'reply')
        assert 'hands' in reply or 'hands_error' in reply
        assert not (hands.instance.work / 'proof').exists()
    await hands.aclose()


def test_sidebar_private_consent_and_denial_dom():
    root = Path(__file__).resolve().parents[1]
    if not shutil.which('node') or not (root / 'console/node_modules/jsdom').exists():
        pytest.skip('local DOM dependency jsdom required')
    result = subprocess.run(['node', 'console/hands-sidebar-test.js'], cwd=root,
                            capture_output=True, text=True, timeout=35, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


async def test_missing_rpc_response_is_unknown_for_effect_not_status(tmp_path):

    async def drop(reader, writer):
        await reader.readline()
        writer.close(); await writer.wait_closed()

    socket = tmp_path / 'assistant.sock'
    server = await asyncio.start_unix_server(drop, socket); socket.chmod(0o600)
    try:
        for action in ['answer', 'open', 'close', 'status']:
            with pytest.raises(bridge.IPCFailure) as error:
                await bridge.daemon_call(socket, 'hands.request', {'action': action}, 1)
            assert error.value.uncertain is (action != 'status')
    finally:
        server.close(); await server.wait_closed()
