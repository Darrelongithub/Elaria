"""Local §5 WebSocket -> existing owner-authenticated daemon IPC; NOT an assistant.

No model SDK, configuration/key loading, microphone, storage or hands implementation.
Levels below are SYNTHESISED TEXT CADENCE, never measured audio. The visualizer is untouched.
Only status, console.say and the pinned undo.prepare/undo.apply pilot seam are exposed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
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


class UndoRefused(Exception):
    pass


def undo_refusal(error):
    # Never expose daemon errors containing owner paths, tokens or snapshot data in chat/logs.
    error = str(error)[:8192]
    for marker, label in [('already answered', 'already-answered'), ('lapsed', 'lapsed'),
                          ('nothing was undone', 'drifted/refused'),
                          ('nothing undoable', 'nothing-undoable'), ('one operation', 'single-op-only'),
                          ('unknown undo ask', 'unknown-ask')]:
        if marker in error:
            return label
    return 'refused-or-seam-unavailable'


class IPCFailure(Exception):
    def __init__(self, *, uncertain=False):
        super().__init__('Daemon IPC unavailable or invalid; no automatic replay.')
        self.uncertain = uncertain


async def daemon_call(path: Path, method: str, params: dict, timeout: float) -> dict:
    """Bounded client of the EXISTING IPC protocol, including interleaved event frames.

    Verify the socket and Linux peer UID before sending. A lost response after a send is
    uncertain, NOT a cancellation/rollback. No daemon error body or event content is forwarded.
    """
    if method not in {'status', 'console.say', 'undo.prepare', 'undo.apply'}:
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
                if frame.get('id') == 1 and frame.get('ok') is False and method.startswith('undo.'):
                    raise UndoRefused(undo_refusal(frame.get('error')))
                if (frame.get('id') != 1 or frame.get('ok') is not True
                        or not isinstance(frame.get('result'), dict)):
                    raise ValueError('invalid or rejected response')
                return frame['result']
            raise EOFError()
    except (OSError, ValueError, TypeError, RecursionError, EOFError, TimeoutError, IPCFailure) as exc:
        raise IPCFailure(uncertain=sent and method in {'console.say', 'undo.apply'}) from exc
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
    # ModeStatus.is_online uses the preference-resolved effective_mode enum.
    # `mode` is only its lowercase display alias; network health is NOT preference.
    connectivity = status.get('connectivity')
    if (not isinstance(connectivity, dict)
            or connectivity.get('effective_mode') != 'ONLINE'
            or connectivity.get('online') is not True
            or connectivity.get('offline') is not False
            or connectivity.get('forced_offline') is not False):
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
    elif via == 'local':
        reply['error'] = '[OFFLINE] Show-off turn stayed local; no model answer.'
    elif via == 'local-timeout-fallback':
        reply['error'] = '[TIMEOUT] No model answer; daemon fallback not presented.'
    elif not isinstance(result.get('reply'), str) or not result['reply'].strip():
        reply['error'] = '[EMPTY] No text reply from the daemon.'
    elif len(result['reply'].encode('utf-8')) > MAX_FRAME // 2:
        reply['error'] = '[BOUND] Reply exceeds the bridge display limit; not truncated.'
    elif via in {'gemini', 'gemini-unparsed-command', 'showoff'} and result.get('model'):
        reply.update(text=result['reply'], provenance='live-model')
    elif via in {'local-intent', 'local-memory', 'local-awareness', 'local-hotword-checkin',
                 'guest-deflection', 'showoff-refusal'}:
        reply.update(text='[LOCAL DAEMON — not a model answer]\n' + result['reply'],
                     provenance='local-daemon')
    else:
        reply['error'] = '[UNCONFIRMED] Unrecognised reply provenance; not a model answer.'
    return reply


# Advisory input-shape observer, not a dispatcher or authority. Pinned grammar source:
# a6cc1507fb798bcbe1d9998bfcc8f2cb69cff8e1:src/assistant/intents.py:25-59.
# The daemon's returned via is authoritative for reply provenance; its executed kind is absent.
OBSERVED_PATTERNS = [
    ("halt", re.compile(r"^\s*(?:halt|stop everything|panic stop)(?:\s+(?:now|please))*\s*[!.]*\s*$", re.IGNORECASE)),
    ("status", re.compile(r"^\s*(status|are you (up|running|alive)|health)\s*\??\s*$", re.IGNORECASE)),
    ("mode_offline", re.compile(r"^\s*(go offline|offline mode|force offline|disconnect)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_online", re.compile(r"^\s*(go online|online mode|reconnect)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_auto", re.compile(r"^\s*(auto mode|connectivity auto|automatic mode)\s*[!.]*\s*$", re.IGNORECASE)),
    ("queue_status", re.compile(r"^\s*(queue status|what'?s queued|what is queued|show (the )?queue)\s*\??\s*$", re.IGNORECASE)),
    ("queue_drain", re.compile(r"^\s*(drain (the )?queue|process (the )?queue)\s*[!.]*\s*$", re.IGNORECASE)),
    ("cost", re.compile(r"^\s*(?:cost|spend|quota|usage|(?:api|gemini|token|my)\s+(?:cost|spend|quota|usage)|how much (?:have|did) (?:i|we) (?:spend|use)(?:\s+today|\s+this\s+month)?)\s*[?.!]*\s*$", re.IGNORECASE)),
    ("undo", re.compile(r"^\s*undo(?:\s+since\s+(\S+))?\s*[!.]*\s*$", re.IGNORECASE)),
    ("remember", re.compile(r"^\s*remember\s+(?:that\s+)?(.+?)\s*$", re.IGNORECASE | re.DOTALL)),
    ("forget", re.compile(r"^\s*forget\s+(?:about\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("where", re.compile(r"^\s*(?:where(?:'s| is| are)|find(?: me)?|locate)\s+(.+?)\s*\??\s*$", re.IGNORECASE)),
    ("search", re.compile(r"^\s*search\s+(?:for\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("organise", re.compile(r"^\s*(?:organi[sz]e|sort(?:\s+out)?|tidy)\s+(.+?)\s*$", re.IGNORECASE)),
    # Phase 7: the ladder speaks Kiswahili too — same narrow grammar.
    # (simama = stop, hali = status, gharama = cost, kumbuka = remember,
    # sahau = forget, iko wapi = where is, tafuta = search, panga = organise,
    # rudisha = restore/undo.)
    ("halt", re.compile(r"^\s*(simama|wacha yote|simamisha yote)\s*[!.]*\s*$", re.IGNORECASE)),
    ("status", re.compile(r"^\s*(hali|uko sawa|unaendelea vipi)\s*\??\s*$", re.IGNORECASE)),
    ("mode_offline", re.compile(r"^\s*(enda nje ya mtandao|hali ya nje ya mtandao)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_online", re.compile(r"^\s*(rudi mtandaoni|enda mtandaoni|hali ya mtandaoni)\s*[!.]*\s*$", re.IGNORECASE)),
    ("mode_auto", re.compile(r"^\s*(hali ya kiotomatiki|kiotomatiki)\s*[!.]*\s*$", re.IGNORECASE)),
    ("queue_status", re.compile(r"^\s*(hali ya foleni|foleni ikoje|onyesha foleni)\s*\??\s*$", re.IGNORECASE)),
    ("queue_drain", re.compile(r"^\s*(tenda foleni|chakata foleni)\s*[!.]*\s*$", re.IGNORECASE)),
    ("cost", re.compile(r"^\s*(?:gharama|nimetumia kiasi gani|quota)\s*[?.!]*\s*$", re.IGNORECASE)),
    ("undo", re.compile(r"^\s*(rudisha|tenda upya)(?:\s+tangu\s+(\S+))?\s*[!.]*\s*$", re.IGNORECASE)),
    ("remember", re.compile(r"^\s*kumbuka\s+(?:kwamba\s+)?(.+?)\s*$", re.IGNORECASE | re.DOTALL)),
    ("forget", re.compile(r"^\s*sahau\s+(?:kuhusu\s+)?(.+?)\s*$", re.IGNORECASE)),
    ("where", re.compile(r"^\s*(?:iko wapi|wapi)\s+(.+?)\s*\??\s*$", re.IGNORECASE)),
    ("search", re.compile(r"^\s*tafuta\s+(.+?)\s*$", re.IGNORECASE)),
    ("organise", re.compile(r"^\s*(?:panga|ratibu)\s+(.+?)\s*$", re.IGNORECASE)),
]


def observed_intent(text):
    text = re.sub(r"^(?:(?:hey|hi|hello)\s+)?elaria\b[\s,!:.-]*", '', text.strip(),
                  flags=re.IGNORECASE)
    return next((kind for kind, pattern in OBSERVED_PATTERNS if pattern.match(text)), None)



# Consumer registry, not an execution dispatcher. Source/limits in the Task B report.
# A route existing is NOT readiness, approval, completion, or a fresh-file capability.
CAPABILITIES = {
    'status': 'Daemon status snapshot; not proof that other operations work now.',
    'cost': 'Recorded usage/quota snapshot; not a live billing guarantee.',
    'where': 'Indexed references, with possible model fallback; no fresh-file read.',
    'search': 'Indexed matches, with possible model fallback; no fresh-file analysis.',
    'remember': 'Existing typed fact storage; fact ID/kind receipt is missing on this wire.',
    'forget': 'Existing typed matching-fact deactivation, not erasure; affected IDs missing.',
    'halt': 'Existing daemon halt route; acknowledgement is not proof of every effect stopping.',
    'undo': 'Single-op private prepare/review/apply card; bare undo unchanged. No approval in chat.',
    'organise': 'Existing configured-root index/plan building; metadata writes, no apply here.',
}
BRIDGE_FACTS = (
    'Bridge facts: text-only; no speech, file reader, calendar or messaging-send adapter. '
    'Status, console.say and the explicit undo prepare/apply review seam are the only RPCs used. '
    'Registry entries describe routes, not current readiness or permission. '
    'No prior model claim is confirmed. This answer does not probe or execute the daemon.'
)
CAPABILITY_QUERY = re.compile(
    r"^(?:(?:what|which)\s+(?:can|could|do|will)\s+you\b|"
    r"what\s+are\s+your\s+(?:capabilities|abilities|functions)\b|"
    r"(?:can|could|would|will)\s+you\b|are\s+you\s+able\b|"
    r"do\s+you\s+(?:support|have\s+access|know\s+how)\b)"
)
# Explicit finite request frames, NOT a semantic classifier or all-paraphrase guarantee.
UNREGISTERED_REQUEST = re.compile(
    r"^(?:please\s+)?(?:open|read|analyse|analyze|summarise|summarize|inspect|review|load|scan|"
    r"schedule|reschedule|book|send|text|email|message|whatsapp|dm|notify|reply|"
    r"create|delete|move|rename|copy|execute|run|install|launch|browse|download|upload|call)\b|"
    r"^(?:please\s+)?(?:check|show|manage|update|access|what(?:'s| is))\b.*\bcalendar\b"
)


def capability_boundary(text):
    """Return only static registry/bridge facts, or None for the existing conversational path.

    Existing typed intent shapes win BEFORE inspection, so unsupported-action words in
    remember/search/etc payloads cannot become a refusal or a different operation.
    """
    if observed_intent(text):
        return None
    normalized = re.sub(r"^(?:(?:hey|hi|hello)\s+)?elaria\b[\s,!:.-]*", '', text.strip(),
                        flags=re.IGNORECASE)
    normalized = ' '.join(normalized.casefold().split()).rstrip('?.!')
    namespace = re.match(r'^(capability|capabilities|help)(?:\s+(.*))?$', normalized)
    question = CAPABILITY_QUERY.match(normalized)
    unsupported = UNREGISTERED_REQUEST.search(normalized)
    if not (namespace or question or unsupported):
        return None
    name = namespace[2] if namespace else None
    if not name and question:
        simple = re.fullmatch(r'(?:can|could|would|will) you (\w+)', normalized)
        name = simple[1] if simple else None
    if name in CAPABILITIES:
        heading = 'Registered route (not execution or readiness):'
        entries = [name]
    else:
        heading = ('Capability boundary: unregistered requests are refused; no prior prose claim is confirmed. '
                   'Fresh-file analysis, calendar and messaging-send requests are refused here. '
                   'Registered routes only:')
        entries = list(CAPABILITIES)
    return ('[BRIDGE REGISTRY — deterministic, no model call]\n' + heading + '\n' +
            '\n'.join(f'- {name}: {CAPABILITIES[name]}' for name in entries) + '\n' + BRIDGE_FACTS)


def positive_id(value):
    return type(value) is int and 0 < value <= 2**53 - 1


def attribution(result, reply, text, observation):
    """Bounded metadata separate from model prose. No extra RPCs or hidden content leakage.

    The history tail is sampled AFTER _ask and can race another caller. Even a matching tail
    is only a candidate conversation reference, never a request-bound operation receipt.
    """
    rows = [f'Bridge observation: {observation} (not a durable journal receipt).']
    kind = observed_intent(text)
    rows.append('Input shape (advisory): ' + (kind or 'unclassified; executed intent not on wire') + '.')
    rows.append('Operation journal reference: not supplied by console.say; mainline seam required.')
    if 'text' not in reply:
        rows.append('Reply not displayed; execution/effect not established. No automatic replay.')
        return rows
    via = result.get('via')
    rows.append('Reply provenance: ' + str(reply.get('provenance')) + ' / ' + str(via) + '.')
    if reply.get('provenance') == 'live-model':
        rows.append('Model prose is not a capability confirmation, approval or effect receipt.')
    conversation = result.get('conversation')
    cid = result.get('conversation_id')
    if positive_id(cid):
        rows.append(f'Daemon conversation reference: #{cid} (not an operation reference).')
    else:
        rows.append('Daemon conversation reference: unavailable.')
    messages = conversation.get('messages') if isinstance(conversation, dict) else None
    tail = messages[0] if isinstance(messages, list) and len(messages) == 1 else None
    if (positive_id(cid) and isinstance(conversation, dict) and conversation.get('id') == cid and isinstance(tail, dict)
            and positive_id(tail.get('id')) and tail.get('role') == 'assistant'
            and tail.get('channel') == 'console' and tail.get('via') == via
            and tail.get('text') == result.get('reply')):
        rows.append(f'Returned conversation-tail message: #{tail["id"]}; matching text, '
                    'NOT request-bound (concurrent turns may race).')
    else:
        rows.append('Message reference: unavailable or tail not correlated; no attribution inferred.')
    local = reply.get('provenance') == 'local-daemon'
    body = result.get('reply', '')
    if kind in {'where', 'search'}:
        if not local or via != 'local-memory':
            rows.append('Lookup outcome: model fallback / non-index response; no verified index hit.')
        else:
            rows.append('Lookup outcome: daemon local-memory reply, not a fresh-file read.')
            lines = body.splitlines()
            valid = False
            if kind == 'where' and lines:
                match = re.fullmatch(r'Found ([1-3]) candidate\(s\) locally:', lines[0])
                valid = bool(match and len(lines[1:]) == int(match[1])
                             and all(x.startswith('- ') for x in lines[1:]))
            elif kind == 'search' and lines and lines[0] == 'Local matches:':
                valid = 0 < len(lines[1:]) <= 6 and all(
                    re.match(r'^- \[(document|fact|transcript)\] ', x) for x in lines[1:])
            if valid and all(len(x) <= 700 for x in lines[1:]):
                rows.extend('Daemon-reported hit text (unstructured): ' + x[2:] for x in lines[1:])
            else:
                rows.append('Structured indexed refs: unavailable; inspect the local reply, not an inferred receipt.')
    if kind == 'remember':
        rows.extend(['Fact ID and kind: not supplied on this wire; mainline receipt seam required.',
                     ('Retention limit: deactivation is not erasure; stored text/history can remain. '
                     'No retention duration or exact restore guarantee is supplied.')])
    if kind == 'forget':
        count = re.fullmatch(r'Forgotten \(([0-9]{1,19}) fact\(s\) deactivated\).', body)
        rows.append('Affected count (daemon-reported, not independently verified): ' +
                    (count[1] if local and via == 'local-intent' and count else 'unavailable') + '.')
        rows.append('Deactivation-not-erasure: fact text and conversation history may remain.')
    if kind == 'organise':
        rows.append('Resolved root set: not supplied on this wire; do not infer it from the request.')
        rows.append('Audited semantics (not an execution receipt): configured-root reads; '
                    'index/chunk/status, plan/item and shadow-log writes; no apply in this intent.')
        plan = re.fullmatch(r'Shadow plan\(s\) ((?:#[0-9]+(?:, )?)+) building — nothing moves '
                            r'without your review \+ apply. Watch `assist events`\.', body)
        if local and via == 'local-intent' and plan and len(plan[1]) <= 500:
            rows.append('Plan references from daemon reply: ' + plan[1] + '; started is not completed.')
    if kind == 'undo':
        rows.append('Undo gate belongs to mainline; this bridge does not establish approval or reversal.')
    return rows


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



# e7316b985e4463d961a2ec51af6a4023360a261c:src/assistant/daemon.py:2844
UNDO_FIELDS = {'op_id', 'plan_id', 'ts', 'op', 'src', 'dst',
               'sha256_before', 'sha256_after', 'status'}


def undo_scope(text):
    text = re.sub(r"^(?:(?:hey|hi|hello)\s+)?elaria\b[\s,!:.-]*", '', text.strip(), flags=re.IGNORECASE)
    # Existing scoped typed forms. Bare forms deliberately do NOT enter the new route.
    match = re.fullmatch(r'(?:undo\s+since|(?:rudisha|tenda upya)\s+tangu)\s+(\S+?)\s*[!.]*', text, re.IGNORECASE)
    if match:
        return {'since': match[1]}
    match = re.fullmatch(r'undo review #([1-9][0-9]{0,14})', text, re.IGNORECASE)
    return {'op_id': int(match[1])} if match else None


def validate_undo(result):
    if not isinstance(result, dict) or set(result) != {
            'token', 'ask_sha256', 'snapshot', 'prepared_at', 'age_s', 'expires_in_s'}:
        raise UndoRefused('invalid-prepare-envelope')
    if len(json.dumps(result).encode()) > MAX_FRAME // 2:
        raise UndoRefused('oversized-prepare')
    snap = result['snapshot']
    if (not isinstance(snap, dict) or set(snap) != UNDO_FIELDS
            or not positive_id(snap['op_id'])
            or snap['plan_id'] is not None and not positive_id(snap['plan_id'])
            or snap['op'] not in {'move', 'rename', 'copy', 'mkdir', 'trash'}
            or snap['status'] not in {'intent', 'copied', 'committed'}):
        raise UndoRefused('invalid-single-operation-snapshot')
    for key in ['ts', 'src', 'dst']:
        if not isinstance(snap[key], str) or not 0 < len(snap[key]) <= 4096:
            raise UndoRefused('invalid-snapshot-field')
    for key in ['sha256_before', 'sha256_after']:
        if snap[key] is not None and (not isinstance(snap[key], str) or not re.fullmatch('[0-9a-f]{64}', snap[key])):
            raise UndoRefused('invalid-snapshot-hash')
    digest = hashlib.sha256(json.dumps(snap, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if result['ask_sha256'] != digest:
        raise UndoRefused('snapshot-digest-mismatch')
    if not isinstance(result['token'], str) or not re.fullmatch('[0-9a-f]{32}', result['token']):
        raise UndoRefused('invalid-seam-token')
    if not isinstance(result['prepared_at'], str) or len(result['prepared_at']) > 80:
        raise UndoRefused('invalid-preparation-time')
    if any(type(result[k]) not in (int, float) or not math.isfinite(result[k]) for k in ['age_s', 'expires_in_s']):
        raise UndoRefused('invalid-expiry')
    if not 0 <= result['age_s'] < result['expires_in_s'] <= 600:
        raise UndoRefused('invalid-expiry')
    return snap


class Bridge:
    def __init__(self, socket_path: Path, assets: Path, *, port=8744, rpc=daemon_call):
        self.socket_path, self.assets, self.port, self.rpc = socket_path, assets, port, rpc
        self.token = secrets.token_urlsafe(32)  # local pairing token, NEVER a model API key
        self.clients = set()
        self.turns = set()
        self.busy = False
        self.uncertain = False
        self.observation_prefix = secrets.token_hex(6)
        self.observation_n = 0
        self.undo_asks = {}  # connection-bound, memory only; daemon tokens never enter the browser
        self.review_private = False
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
body{overflow:hidden}
iframe{display:block;border:0;width:100%;height:100%}
#wire-error:not([hidden]){position:fixed;inset:0;margin:0;padding:24px;
background:#110d1c;color:#e3bd80;z-index:1}
</style><script src="/bridge-client.js" defer></script></head><body>
<p id="wire-error" role="alert" hidden></p>
<iframe id="console" title="Elaria console"></iframe></body></html>''').encode()

    def process_request(self, connection, request):
        try:
            host = request.headers.get('Host')
            origin = request.headers.get('Origin')
            site = request.headers.get('Sec-Fetch-Site')
            url = urlsplit(request.path)
            if host != f'127.0.0.1:{self.port}' or url.scheme or url.netloc or url.fragment:
                return self.response(403)
            # A private local launch file navigates to the public, token-free bootstrap.
            # Allow only that top-level navigation shape; never relax protected assets,
            # WebSocket Origin/site checks, iframe embedding, or cross-origin fetches.
            public_navigation = (url.path == '/' and not url.query and origin is None
                                 and request.headers.get('Sec-Fetch-Mode') == 'navigate'
                                 and request.headers.get('Sec-Fetch-Dest') == 'document')
            if (origin not in (None, self.origin)
                    or (site == 'cross-site' and not public_navigation)):
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
            company = status.get('company')
            self.review_private = (isinstance(company, dict) and company.get('company') is False
                                   and company.get('restricted') is False)
            return readiness(status)
        except IPCFailure:
            self.review_private = False
            return 'Daemon unavailable. No turn sent.'

    async def health(self, ws):
        while True:
            await asyncio.sleep(HEALTH_SECONDS)
            problem = await self.probe()
            if ws in self.undo_asks:
                await self.emit(ws, t='undo-privacy', allowed=self.review_private and not problem)
            if problem:
                await self.emit(ws, t='state', name='offline', reason=problem)
                await ws.close(code=1013, reason='Daemon not live-ready; reconnect later')
                return
            elif not self.busy and not self.uncertain:
                await self.emit(ws, t='state', name='idle')

    async def prepare_undo(self, ws, request_id, scope):
        try:
            if await self.probe() or not self.review_private:
                raise UndoRefused('private-posture-unavailable')
            asks = self.undo_asks.setdefault(ws, {})
            now = asyncio.get_running_loop().time()
            for key in [key for key, ask in asks.items() if now >= ask['deadline']]:
                del asks[key]
            if len(asks) >= 16:
                raise UndoRefused('review-bound-reached')
            started = asyncio.get_running_loop().time()
            result = await self.rpc(self.socket_path, 'undo.prepare', scope, TURN_SECONDS)
            snapshot = validate_undo(result)
            if await self.probe() or not self.review_private:
                raise UndoRefused('private-posture-unavailable')
            deadline = started + result['expires_in_s'] - result['age_s']
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise UndoRefused('lapsed')
            review_id = secrets.token_hex(16)
            # A new prepared selection invalidates prior pending cards on this connection.
            for old in asks.values():
                if old['state'] == 'pending':
                    old['state'] = 'stale'
            asks[review_id] = {'token': result['token'], 'digest': result['ask_sha256'],
                               'deadline': deadline, 'state': 'pending'}
            await self.emit(ws, t='reply', id=request_id, text='[UNDO REVIEW] Private review prepared; nothing applied.',
                            provenance='undo-review', audio=None, attribution=[
                                'Producer: undo.prepare; non-model, no apply dispatched.',
                                'Ask digest: ' + result['ask_sha256'] +
                                '; journal prefix correlation only, no operation/event ID supplied.'], undo_review={
                                'review_id': review_id, 'snapshot': snapshot,
                                'ask_sha256': result['ask_sha256'], 'prepared_at': result['prepared_at'],
                                'age_s': result['age_s'] + asyncio.get_running_loop().time() - started,
                                'remaining_s': remaining})
        except UndoRefused as exc:
            await self.emit(ws, t='reply', id=request_id, error='Undo review: ' + str(exc) + '; no apply dispatched.')

    async def decide_undo(self, ws, message):
        try:
            asks = self.undo_asks.get(ws, {})
            ask = asks.get(message['review_id'])
            if ask is None:
                raise UndoRefused('no ask is selected')
            if ask['state'] != 'pending':
                raise UndoRefused('already-answered' if ask['state'] in {'answered', 'unknown'} else ask['state'])
            if message['ask_sha256'] != ask['digest']:
                ask['state'] = 'stale'
                raise UndoRefused('stale')
            if await self.probe() or not self.review_private:
                raise UndoRefused('private-posture-unavailable')
            if asyncio.get_running_loop().time() >= ask['deadline']:
                ask['state'] = 'lapsed'
                raise UndoRefused('lapsed')
            # Spend before any await to the effect path. Never re-arm on failure or timeout.
            ask['state'] = 'answered'
            result = await self.rpc(self.socket_path, 'undo.apply',
                                    {'token': ask['token'], 'decision': message['decision']}, TURN_SECONDS)
            if (not isinstance(result, dict) or result.get('decision') != message['decision']
                    or result.get('ask_sha256') != ask['digest']
                    or type(result.get('undone')) is not int or not 0 <= result['undone'] <= 1
                    or not isinstance(result.get('problems'), list)
                    or message['decision'] == 'no' and (result['undone'] != 0 or result['problems'])):
                raise IPCFailure(uncertain=True)
            # No paths/problems echoed into persistent chat; detailed snapshot stays on the card only.
            await self.emit(ws, t='reply', id=message['id'], text='[UNDO REVIEW] ' +
                            ('declined; already answered.' if message['decision'] == 'no' else
                             f"daemon reports undone={result['undone']}, problems={len(result['problems'])}; already answered. ") +
                            'Ask digest: ' + ask['digest'] + '. Transport acknowledgement is not independent effect verification.',
                            provenance='undo-review', audio=None)
        except UndoRefused as exc:
            await self.emit(ws, t='reply', id=message['id'], error='Undo review: ' + str(exc) + '.')
        except IPCFailure as exc:
            self.uncertain = self.uncertain or exc.uncertain
            await self.emit(ws, t='reply', id=message['id'], error='Undo review outcome unknown; no automatic replay.')
        except (ConnectionClosed, TimeoutError):
            pass
        except Exception:
            self.uncertain = True
            with suppress(ConnectionClosed, TimeoutError):
                await self.emit(ws, t='reply', id=message['id'], error='Undo review outcome unknown; no replay.')
        finally:
            self.busy = False

    async def turn(self, ws, message):
        request_id = message['id']
        self.observation_n += 1
        observation = f'{self.observation_prefix}:{self.observation_n}'
        notes = attribution({}, {}, message['text'], observation)
        for ask in self.undo_asks.get(ws, {}).values():
            if ask['state'] == 'pending':
                ask['state'] = 'stale'  # any new chat input invalidates the selected act
        try:
            scope = undo_scope(message['text'])
            if scope is not None:
                await self.prepare_undo(ws, request_id, scope)
                return
            registry_reply = capability_boundary(message['text'])
            if registry_reply is not None:
                await self.emit(ws, t='reply', id=request_id, text=registry_reply,
                                provenance='bridge-registry', via='bridge-registry', audio=None,
                                attribution=[
                                    f'Bridge observation: {observation} (not a durable journal receipt).',
                                    'Source: fixed bridge capability registry; no model generation.',
                                    'Operation/message journal: not applicable; no console.say sent.',
                                    'No daemon execution, runtime-readiness check or approval occurred.',
                                ])
                return
            problem = await self.probe()
            if problem:
                await self.emit(ws, t='reply', id=request_id, error=problem, attribution=notes)
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
            notes = attribution(result, reply, message['text'], observation)
            reply['attribution'] = notes
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
                await self.emit(ws, t='reply', id=request_id, attribution=notes,
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
                await self.emit(ws, t='reply', id=request_id, attribution=notes,
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
                        or message.get('t') not in {'send', 'undo-decision'} or type(message.get('id')) is not int
                        or not 0 < message['id'] <= 2**53 - 1):
                    await self.emit(ws, t='bye', reason='Invalid §5 send message.')
                    return
                request_id = message['id']
                problem = (validate_send(message) if message['t'] == 'send' else
                           None if set(message) == {'t', 'id', 'review_id', 'ask_sha256', 'decision'}
                           and isinstance(message.get('review_id'), str)
                           and isinstance(message.get('ask_sha256'), str)
                           and message.get('decision') in ('yes', 'no')
                           else 'Invalid review decision; no dispatch.')
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
                task = asyncio.create_task(self.turn(ws, message) if message['t'] == 'send'
                                           else self.decide_undo(ws, message))
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
            self.undo_asks.pop(ws, None)
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
