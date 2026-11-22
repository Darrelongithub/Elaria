/* Runs in a sandbox against a synthetic owner Unix socket and an actual loopback WebSocket. */
'use strict';
const {spawnSync} = require('node:child_process');
const result = spawnSync(process.env.PYTHON || 'python3', ['-c', String.raw`
import asyncio
import contextlib
import hashlib
import io
import json
import logging
import os
import signal
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.request import urlopen

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

import bridge
import run_bridge

pending = {'event': 'draft.pending', 'draft': {
    'draft_id': 'd-1', 'conversation_id': 'thread-1', 'recipient': '+254700000000',
    'snippet': '<em>opaque text & data</em>', 'state': 'pending', 'created_at': '2026-11-19'}}
resolved = {'event': 'draft.resolved', 'draft': {
    'draft_id': 'd-1', 'state': 'sent', 'outcome': 'synthetic receipt'}}
levels = {'event': 'capture.levels', 'raw_peak': .8, 'processed_peak': .35, 'limited_samples': 2}
approve = {'command': 'draft.approve', 'draft_id': 'd-1'}
reject = {'command': 'draft.reject', 'draft_id': 'd-2'}
deny = {'command': 'draft.reject', 'draft_id': 'denied'}
rejected = {'event': 'draft.resolved', 'draft': {
    'draft_id': 'd-2', 'state': 'rejected', 'outcome': 'synthetic rejection'}}
status = {'running': True, 'gemini_mode': 'live', 'connectivity': {
    'effective_mode': 'ONLINE', 'online': True, 'offline': False, 'forced_offline': False}}


async def receive(ws):
    return json.loads(await asyncio.wait_for(ws.recv(), 3))


async def send(ws, frame):
    await ws.send(json.dumps(frame))


async def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        path = root / 'fixture.sock'
        engine = b'<!-- synthetic engine marker -->'
        (root / 'elaria-visualizer.js').write_bytes(engine)
        (root / 'index.html').write_bytes(engine)
        (root / 'bridge-client.js').write_text('/* synthetic fixture */')
        subscribers = set()
        calls = []
        command_calls = []
        replay = True
        ready = True
        approve_delivered = False
        token = ''
        malicious_reply = False
        subscriptions = 0

        async def write(writer, frame):
            writer.write(json.dumps(frame).encode() + b'\n')
            await writer.drain()

        async def daemon(reader, writer):
            nonlocal approve_delivered, subscriptions
            try:
                req = json.loads(await reader.readline())
                method, params = req['method'], req['params']
                calls.append((method, params))
                result = {'id': req['id'], 'ok': True, 'result': {}}
                if method == 'events.subscribe':
                    subscriptions += 1
                    assert params == {'console_replay': True}
                    subscribers.add(writer)
                    result['result'] = {'subscribed': True, 'console_replay': replay}
                    await write(writer, result)
                    for frame in ([resolved, pending] if approve_delivered else [pending, pending]):
                        await write(writer, frame)
                    await write(writer, levels)
                    await reader.read()
                    return
                if method == 'status':
                    result['result'] = status if ready else {'running': False}
                elif method == 'console.command':
                    command_calls.append(params)
                    if params == approve:
                        approve_delivered = True
                        for subscriber in tuple(subscribers):
                            await write(subscriber, resolved)
                        result['result'] = {'accepted': True}
                    elif params == reject:
                        for subscriber in tuple(subscribers):
                            await write(subscriber, rejected)
                        result['result'] = {'accepted': True}
                    else:
                        assert params == deny
                        result = {'id': req['id'], 'ok': False, 'error': 'SMOKE_SECRET ' + token}
                elif method == 'console.say':
                    assert params == {'text': 'synthetic question', 'speak': False, 'history_limit': 1}
                    result['result'] = {'reply': token if malicious_reply else 'synthetic reply',
                                        'audio': 'DO NOT FORWARD', 'mode': 'live', 'via': 'local-intent'}
                else:
                    raise AssertionError('unexpected fixture method')
                await write(writer, result)
            finally:
                subscribers.discard(writer)
                writer.close()
                await writer.wait_closed()

        capture = io.StringIO()
        handler = logging.StreamHandler(capture)
        logging.getLogger().addHandler(handler)
        try:
            with patch.object(bridge, 'ENGINE_SHA', hashlib.sha256(engine).hexdigest()):
                instance = bridge.Bridge(path, root, port=0)
                token = instance.token
                ipc = await asyncio.start_unix_server(daemon, path)
                os.chmod(path, 0o600)
                async with ipc, await instance.start() as server:
                    assert [s.getsockname()[0] for s in server.sockets] == ['127.0.0.1']
                    endpoint = instance.origin.replace('http:', 'ws:') + '/elaria?token=' + token
                    public = await asyncio.to_thread(lambda: urlopen(instance.origin).read())
                    assert token.encode() not in public
                    for uri, origin in [(endpoint, 'http://localhost:1'),
                                        (endpoint.replace(token, 'redacted'), instance.origin)]:
                        try:
                            async with connect(uri, origin=origin):
                                raise AssertionError('untrusted handshake accepted')
                        except InvalidStatus as exc:
                            assert exc.response.status_code == 403 and token.encode() not in exc.response.body

                    async def enter(ws):
                        await send(ws, {'t': 'hello', 'v': 1, 'client': 'console'})
                        hello = await receive(ws)
                        assert hello['t'] == 'hello-ok' and hello['simulate'] is False
                        assert 'synthesised-text-levels' not in hello['capabilities']
                        assert 'capture.state' in hello['capabilities']
                        assert await receive(ws) == {'t': 'state', 'name': 'idle'}

                    async with connect(endpoint, origin=instance.origin) as ws:
                        await enter(ws)
                        assert [await receive(ws), await receive(ws)] == [pending, pending]
                        assert await receive(ws) == {'t': 'levels', 'role': 'input', 'level': .35,
                            'source': 'capture.levels', 'measured': True, 'raw_peak': .8,
                            'processed_peak': .35, 'limited_samples': 2}
                        await send(ws, {'t': 'send', 'id': 1, 'text': 'synthetic question',
                                        'session': 'test', 'history': []})
                        assert await receive(ws) == {'t': 'state', 'name': 'thinking'}
                        answer = await receive(ws)
                        assert answer['t'] == 'reply' and answer.get('text', '').endswith('synthetic reply') and 'audio' not in answer
                        assert await receive(ws) == {'t': 'state', 'name': 'idle'}
                        assert not command_calls
                        await send(ws, approve)
                        frames = [await receive(ws), await receive(ws)]
                        assert resolved in frames
                        assert {'t': 'draft-command-result', 'draft_id': 'd-1', 'status': 'accepted'} in frames
                        await send(ws, reject)
                        frames = [await receive(ws), await receive(ws)]
                        assert rejected in frames
                        assert {'t': 'draft-command-result', 'draft_id': 'd-2', 'status': 'accepted'} in frames
                        await send(ws, deny)
                        assert await receive(ws) == {'t': 'draft-command-result', 'draft_id': 'denied', 'status': 'refused'}
                    async with connect(endpoint, origin=instance.origin) as ws:
                        await enter(ws)
                        assert [await receive(ws), await receive(ws)] == [resolved, pending]
                        assert (await receive(ws))['t'] == 'levels'
                        assert command_calls == [approve, reject, deny]  # reconnect replays events, never commands
                        assert subscriptions == 2
                        subscriber, = subscribers
                        await write(subscriber, {'event': 'console.state', 'state': 'listening'})
                        assert await receive(ws) == {'t': 'state', 'name': 'listening'}
                        await write(subscriber, {'event': 'capture.state', 'state': 'armed',
                                                 'reason': 'hotword armed'})
                        assert await receive(ws) == {'t': 'capture-state', 'name': 'armed',
                                                    'reason': 'hotword armed'}
                        await write(subscriber, {'event': 'console.state', 'state': 'invalid'})
                        try:
                            await receive(ws)
                            raise AssertionError('invalid state silently accepted')
                        except ConnectionClosed as exc:
                            assert exc.rcvd.code == 1013
                    replay = False
                    async with connect(endpoint, origin=instance.origin) as ws:
                        await enter(ws)
                        assert (await receive(ws))['t'] == 'levels'  # legacy daemon grants no draft replay
                        await send(ws, approve)
                        assert (await receive(ws))['status'] == 'refused'
                        assert command_calls == [approve, reject, deny]
                    async with connect(endpoint, origin=instance.origin) as ws:
                        await enter(ws)
                        assert (await receive(ws))['t'] == 'levels'
                        ready = False
                        offline = json.loads(await asyncio.wait_for(ws.recv(), 5))
                        assert offline['name'] == 'offline'  # already-paired connection detects loss
                    async with connect(endpoint, origin=instance.origin) as ws:
                        await send(ws, {'t': 'hello', 'v': 1, 'client': 'console'})
                        assert (await receive(ws))['name'] == 'offline'
                    assert command_calls == [approve, reject, deny]
                    ready = True
                    async with connect(endpoint, origin=instance.origin) as ws:
                        await enter(ws)
                        assert (await receive(ws))['t'] == 'levels'
                        malicious_reply = True
                        await send(ws, {'t': 'send', 'id': 1, 'text': 'synthetic question',
                                        'session': 'test', 'history': []})
                        assert (await receive(ws))['name'] == 'thinking'
                        answer = await receive(ws)
                        assert answer.get('error') and token not in json.dumps(answer)
                await instance.shutdown()

                # Run real launcher start/stop on an ephemeral local port, without a browser.
                launch = io.StringIO()
                args = SimpleNamespace(socket=str(path), port=0, check=False, open=False)
                loop = asyncio.get_running_loop()
                def stop_soon(sig, stop):
                    if sig == signal.SIGTERM:
                        loop.call_later(.1, stop)
                with (patch.object(loop, 'add_signal_handler', stop_soon),
                      contextlib.redirect_stdout(launch), contextlib.redirect_stderr(launch)):
                    assert await run_bridge.run(bridge, root, args) == 0
                private, = root.glob('elaria*/**/*.html')
                credential = private.read_text().split('#pair=', 1)[1].split('"', 1)[0]
                assert len(credential) == 43 and credential not in launch.getvalue()
                assert private.stat().st_mode & 0o777 == 0o600
                assert private.parent.stat().st_mode & 0o777 == 0o700
            assert token not in capture.getvalue() and 'SMOKE_SECRET' not in capture.getvalue()
        finally:
            logging.getLogger().removeHandler(handler)

asyncio.run(main())
print('PASS: real loopback WS + owner IPC, replay, exact frames, gated decisions, live/offline state, measured levels, no client audio, token-free output')
`], {cwd: __dirname, stdio: 'inherit', timeout: 20000});
if (result.error) throw result.error;
process.exitCode = result.status ?? 1;
