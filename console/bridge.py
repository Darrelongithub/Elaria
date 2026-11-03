"""Local §5 WebSocket -> existing owner-authenticated daemon IPC; NOT an assistant.

No model SDK, configuration/key loading, microphone, storage or hands implementation.
Levels below are SYNTHESISED TEXT CADENCE, never measured audio. The visualizer is untouched.
Only status and console.say are sent to the existing newline-JSON Unix client interface.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import secrets
import socket
import stat
import struct
from contextlib import suppress
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

ENGINE_SHA = '5e32329105aac85368806d06f98ace0d2c04681f324b5d7349a9763f1efb6447'
MAX_FRAME = 65536
MAX_TEXT = 8192
PROBE_SECONDS = 3
TURN_SECONDS = 35  # probe + turn + delivery margin < the shell's 45-second abandonment
HEALTH_SECONDS = 3
MAX_CLIENTS = 4


class IPCFailure(Exception):
    def __init__(self, *, uncertain=False):
        super().__init__('Daemon IPC unavailable or invalid; no automatic replay.')
        self.uncertain = uncertain


async def daemon_call(path: Path, method: str, params: dict, timeout: float) -> dict:
    """Bounded client of the EXISTING IPC protocol, including interleaved event frames.

    Verify the socket and Linux peer UID before sending. A lost response after a send is
    uncertain, NOT a cancellation/rollback. No daemon error body or event content is forwarded.
    """
    if method not in {'status', 'console.say'}:
        raise ValueError('bridge IPC method not allowed')
    writer = None
    sent = False
    try:
        async with asyncio.timeout(timeout):
            info = path.lstat()
            if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600):
                raise IPCFailure()
            reader, writer = await asyncio.open_unix_connection(path, limit=1024 * 1024)
            peer = writer.get_extra_info('socket')
            _, uid, _ = struct.unpack('3i', peer.getsockopt(socket.SOL_SOCKET,
                                                         socket.SO_PEERCRED, 12))
            if uid != os.getuid():
                raise IPCFailure()
            payload = {'id': 1, 'method': method, 'params': params}
            sent = True
            writer.write((json.dumps(payload) + '\n').encode())
            await writer.drain()
            while line := await reader.readline():
                frame = json.loads(line)
                if not isinstance(frame, dict):
                    raise TypeError('invalid frame')
                if 'ok' not in frame and 'event' in frame:
                    continue
                if (frame.get('id') != 1 or frame.get('ok') is not True
                        or not isinstance(frame.get('result'), dict)):
                    raise ValueError('invalid or rejected response')
                return frame['result']
            raise EOFError()
    except (OSError, ValueError, TypeError, RecursionError, EOFError, TimeoutError, IPCFailure) as exc:
        raise IPCFailure(uncertain=sent and method == 'console.say') from exc
    finally:
        if writer is not None:
            writer.close()
            with suppress(OSError, TimeoutError):
                await asyncio.wait_for(writer.wait_closed(), 1)


def readiness(status: dict) -> str | None:
    if status.get('running') is not True:
        return 'Daemon is not running.'
    if status.get('gemini_mode') != 'live':
        return 'Daemon is not in live mode. No mock/fixture turn was sent.'
    if status.get('connectivity_mode') != 'online':
        return 'Daemon is offline or connectivity is unknown. No turn was sent.'
    return None


def reply_message(result: dict, request_id: int) -> dict:
    """Never relabel fixture, queued, withheld or fallback text as model output."""
    reply = {'t': 'reply', 'id': request_id}
    via = result.get('via')
    if not isinstance(via, str):
        return {**reply, 'error': '[UNCONFIRMED] Missing reply provenance.'}
    try:
        if isinstance(result.get('reply'), str):
            result['reply'].encode('utf-8')
    except UnicodeError:
        return {**reply, 'error': '[INVALID] Daemon reply is not valid UTF-8.'}
    if result.get('withheld') is not None or via == 'withheld':
        reply['error'] = '[WITHHELD] The daemon withheld this reply; not a model answer.'
    elif result.get('mode') != 'live' or result.get('fixture') is not None:
        reply['error'] = '[NOT LIVE] Mock, fixture or unconfirmed mode; reply not presented.'
    elif via == 'local-queue' or result.get('queued_job_id') is not None:
        reply['error'] = '[QUEUED] Daemon queued the turn; no model answer. Do not replay it.'
    elif via == 'local-timeout-fallback':
        reply['error'] = '[TIMEOUT] No model answer; daemon fallback not presented.'
    elif not isinstance(result.get('reply'), str) or not result['reply'].strip():
        reply['error'] = '[EMPTY] No text reply from the daemon.'
    elif len(result['reply'].encode('utf-8')) > MAX_FRAME // 2:
        reply['error'] = '[BOUND] Reply exceeds the bridge display limit; not truncated.'
    elif via in {'gemini', 'gemini-unparsed-command', 'showoff'} and result.get('model'):
        reply.update(text=result['reply'], provenance='live-model')
    elif via in {'local-intent', 'local-memory', 'company-awareness',
                 'guest-deflection', 'showoff-refusal'}:
        reply.update(text='[LOCAL DAEMON — not a model answer]\n' + result['reply'],
                     provenance='local-daemon')
    else:
        reply['error'] = '[UNCONFIRMED] Unrecognised reply provenance; not a model answer.'
    return reply


def validate_send(message: dict) -> str | None:
    if set(message) - {'t', 'id', 'text', 'session', 'history'}:
        return 'Unsupported send fields; no turn sent.'
    text = message.get('text')
    if not isinstance(text, str) or not text.strip() or len(text.encode('utf-8')) > MAX_TEXT:
        return 'Text must be nonempty and at most 8192 UTF-8 bytes; no turn sent.'
    history = message.get('history', [])
    if not isinstance(history, list) or len(history) > 20:
        return 'History must be an array of at most 20 entries; no turn sent.'
    if not isinstance(message.get('session', ''), str):
        return 'Session label must be text; no turn sent.'
    return None


class Bridge:
    def __init__(self, socket_path: Path, assets: Path, *, port=8744, rpc=daemon_call):
        self.socket_path, self.assets, self.port, self.rpc = socket_path, assets, port, rpc
        self.token = secrets.token_urlsafe(32)  # local pairing token, NEVER a model API key
        self.clients = set()
        self.turns = set()
        self.busy = False
        self.uncertain = False
        # Load only exact assets, never route a caller-controlled filesystem path.
        engine = (assets / 'elaria-visualizer.js').read_bytes()
        if hashlib.sha256(engine).hexdigest() != ENGINE_SHA:
            raise ValueError('gate_verbatim: engine SHA mismatch; refusing to serve')
        self.shell = (assets / 'index.html').read_bytes()
        if engine not in self.shell:
            raise ValueError('gate_verbatim: built shell does not contain the pinned engine')
        self.bootstrap = (assets / 'bridge-client.js').read_bytes()
        self.logger = logging.getLogger('elaria.console.bridge')
        self.logger.handlers = [logging.NullHandler()]
        self.logger.propagate = False  # never log handshake URLs/pairing tokens or turn bodies

    @property
    def origin(self):
        return f'http://127.0.0.1:{self.port}'

    def response(self, code, body=b'', content_type='text/plain; charset=utf-8'):
        headers = Headers({
            'Content-Type': content_type, 'Content-Length': str(len(body)),
            'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
            'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'SAMEORIGIN',
            'Content-Security-Policy': (
                "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; "
                "frame-src 'self'; frame-ancestors 'self'; img-src 'self' data:; "
                f"connect-src ws://127.0.0.1:{self.port}; base-uri 'none'; form-action 'none'"),
        })
        return Response(code, HTTPStatus(code).phrase, headers, body)

    def page(self):
        return ('''<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elaria — local text wire</title><style>
html,body{margin:0;height:100%;background:#110d1c;color:#dbd2ed;font:12px monospace}
body{display:flex;flex-direction:column}header{padding:8px 14px;line-height:1.6}
iframe{flex:1;border:0;width:100%;min-height:0}b{color:#e3bd80}
</style><script src="/bridge-client.js" defer></script></head><body>
<header><b id="wire-status" role="status">Connecting to the local daemon…</b><br>
Text-only · levels are synthesised text cadence, NOT measured audio · speech unavailable.<br>
Transcript/audio PENDING · memory is the labelled shell copy · tabs share one daemon conversation.
</header><iframe id="console" title="Elaria console"></iframe></body></html>''').encode()

    def process_request(self, connection, request):
        try:
            host = request.headers.get('Host')
            origin = request.headers.get('Origin')
            site = request.headers.get('Sec-Fetch-Site')
            url = urlsplit(request.path)
            if host != f'127.0.0.1:{self.port}' or url.scheme or url.netloc or url.fragment:
                return self.response(403)
            if origin not in (None, self.origin) or site == 'cross-site':
                return self.response(403)
            if url.path in {'/elaria', '/console'}:
                params = parse_qs(url.query, strict_parsing=True)
                if (set(params) != {'token'}
                        or len(params['token']) != 1
                        or not secrets.compare_digest(params['token'][0].encode(), self.token.encode())):
                    return self.response(403)
                if url.path == '/console':
                    return self.response(200, self.shell, 'text/html; charset=utf-8')
                if origin != self.origin:
                    return self.response(403)
                if len(self.clients) >= MAX_CLIENTS:
                    return self.response(503)
                return None
            if url.query or request.headers.get('Upgrade'):
                return self.response(404)
            if url.path == '/':
                return self.response(200, self.page(), 'text/html; charset=utf-8')
            if url.path == '/bridge-client.js':
                return self.response(200, self.bootstrap, 'text/javascript; charset=utf-8')
            return self.response(404)
        except (ValueError, KeyError):
            return self.response(403)

    async def emit(self, ws, **message):
        await asyncio.wait_for(ws.send(json.dumps(message, ensure_ascii=False)), 2)

    async def level(self, ws, role, value):
        # Owner ruling: synthesised text levels are accepted, never called measured audio.
        await self.emit(ws, t='levels', role=role, level=value,
                        source='synthesised-text', measured=False)

    async def probe(self):
        try:
            status = await self.rpc(self.socket_path, 'status', {}, PROBE_SECONDS)
            return readiness(status)
        except IPCFailure:
            return 'Daemon unavailable. No turn sent.'

    async def health(self, ws):
        while True:
            await asyncio.sleep(HEALTH_SECONDS)
            problem = await self.probe()
            if problem:
                await self.emit(ws, t='state', name='offline', reason=problem)
                await ws.close(code=1013, reason='Daemon not live-ready; reconnect later')
                return
            elif not self.busy and not self.uncertain:
                await self.emit(ws, t='state', name='idle')

    async def turn(self, ws, message):
        request_id = message['id']
        try:
            problem = await self.probe()
            if problem:
                await self.emit(ws, t='reply', id=request_id, error=problem)
                await self.emit(ws, t='state', name='offline', reason=problem)
                return
            await self.emit(ws, t='state', name='thinking')
            await self.level(ws, 'input', 0.35)
            await self.level(ws, 'input', 0)
            # Browser session/history are display context ONLY. The daemon owns conversation
            # and authority. No arbitrary method, speaker, hand, consent or speech flag passes.
            result = await self.rpc(self.socket_path, 'console.say', {
                'text': message['text'], 'speak': False, 'history_limit': 1,
            }, TURN_SECONDS)
            reply = reply_message(result, request_id)
            await self.emit(ws, **reply)
            if 'text' in reply:
                # This is the shell's text-display state, NOT evidence that TTS is playing.
                await self.emit(ws, t='state', name='speaking', source='text-display')
                length = len(reply['text'])
                duration = min(6.5, max(0.3, length * 0.024))
                start = asyncio.get_running_loop().time()
                while (elapsed := asyncio.get_running_loop().time() - start) < duration:
                    await self.level(ws, 'output', round(0.22 + 0.4 * abs(math.sin(elapsed * 9)), 3))
                    await asyncio.sleep(0.05)
            await self.level(ws, 'output', 0)
            await self.emit(ws, t='state', name='idle')
        except IPCFailure as exc:
            self.uncertain = self.uncertain or exc.uncertain
            with suppress(ConnectionClosed, TimeoutError):
                await self.emit(ws, t='reply', id=request_id,
                                error=('Outcome unknown; daemon may have processed the turn. '
                                   'Inspect its conversation before restarting this bridge. No replay.'
                                   if exc.uncertain else 'Daemon unavailable; no turn sent.'))
                await self.emit(ws, t='state', name='offline')
        except (ConnectionClosed, TimeoutError):
            pass  # Connection loss is NOT a reason to replay a completed or pending turn.
        except Exception:
            # Unexpected bridge failures are visible and never become an implicit retry.
            self.uncertain = True
            with suppress(ConnectionClosed, TimeoutError):
                await self.emit(ws, t='reply', id=request_id,
                                error='Bridge failure; outcome unknown. Inspect daemon conversation; no replay.')
                await self.emit(ws, t='state', name='offline')
        finally:
            self.busy = False

    async def handle(self, ws):
        if len(self.clients) >= MAX_CLIENTS:
            await ws.close(code=1013)
            return
        self.clients.add(ws)
        monitor = None
        last_id = 0
        try:
            raw = await asyncio.wait_for(ws.recv(), 5)
            hello = json.loads(raw)
            if (not isinstance(raw, str) or not isinstance(hello, dict)
                    or hello.get('t') != 'hello' or type(hello.get('v')) is not int
                    or hello['v'] != 1 or hello.get('client') != 'console'):
                await self.emit(ws, t='bye', reason='Expected console hello protocol v1.')
                return
            problem = await self.probe()
            if problem:
                await self.emit(ws, t='state', name='offline', reason=problem)
                await ws.close(code=1013, reason='Daemon not live-ready; reconnect later')
                return
            await self.emit(ws, t='hello-ok', v=1, name='elaria-daemon (text only)',
                            capabilities=['text', 'state', 'synthesised-text-levels'])
            await self.emit(ws, t='state', name=('offline' if self.uncertain else
                                                'thinking' if self.busy else 'idle'))
            await self.level(ws, 'input', 0)
            await self.level(ws, 'output', 0)
            monitor = asyncio.create_task(self.health(ws))
            async for raw in ws:
                message = json.loads(raw)
                if (not isinstance(raw, str) or not isinstance(message, dict)
                        or message.get('t') != 'send' or type(message.get('id')) is not int
                        or not 0 < message['id'] <= 2**53 - 1):
                    await self.emit(ws, t='bye', reason='Invalid §5 send message.')
                    return
                request_id = message['id']
                problem = validate_send(message)
                if request_id <= last_id:
                    problem = 'Duplicate or stale ID; no replay sent.'
                last_id = max(last_id, request_id)
                if self.busy:
                    problem = 'A turn is still in progress; no second turn sent.'
                if self.uncertain:
                    problem = 'Previous outcome unknown. Inspect daemon conversation before restarting bridge.'
                if problem:
                    await self.emit(ws, t='reply', id=request_id, error=problem)
                    continue
                self.busy = True
                task = asyncio.create_task(self.turn(ws, message))
                self.turns.add(task)
                task.add_done_callback(self.turns.discard)
        except (json.JSONDecodeError, UnicodeError, ValueError, RecursionError):
            with suppress(ConnectionClosed, TimeoutError):
                await self.emit(ws, t='bye', reason='Invalid JSON/protocol message.')
        except (ConnectionClosed, TimeoutError):
            pass
        finally:
            if monitor:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
            self.clients.discard(ws)
            # Do NOT cancel/replay the daemon turn when the browser disconnects.

    async def start(self):
        server = await serve(self.handle, '127.0.0.1', self.port,
                             process_request=self.process_request,
                             origins=[self.origin] if self.port else None,
                             compression=None, max_size=MAX_FRAME, max_queue=4,
                             ping_interval=10, ping_timeout=10, close_timeout=1,
                             logger=self.logger, server_header=None)
        self.port = server.sockets[0].getsockname()[1]
        return server

    async def shutdown(self):
        # Closing the IPC client doesn't guarantee daemon cancellation. No restart/replay.
        for task in list(self.turns):
            task.cancel()
        await asyncio.gather(*self.turns, return_exceptions=True)
