"""F37 minimal daemon call-out target. All consent, typed routing and lifecycle live here.

Authenticated owner IPC only. No model-generated plan, daily-terminal attach, arbitrary
socket, executable, cwd or consent-file path is accepted from a request.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import time
from pathlib import Path

from assistant.hands.gate import adjudicate
from assistant.hands.plan import Plan
from assistant.safety import is_halted

from ..kitty import policy
from .consent import Consent, Journal
from .contract import digest, plan, validate
from .instance import DedicatedKitty


class HandsMount:
    def __init__(self, runtime):
        self.runtime = Path(runtime)
        self.id = secrets.token_hex(16)
        self.instance = None
        self.journal = self.consent = None
        self.lock = asyncio.Lock()
        self.closed = False

    def initialize(self):
        if self.journal is None:
            root = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'assistant/hands-headless'
            self.journal = Journal(root)
            self.consent = Consent(root, self.journal, self.id)
            self.recover_unknown('restart-outcome-unknown')

    def recover_unknown(self, reason):
        observed = {row.get('action') for row in self.journal.rows if row['phase'] == 'OBSERVATION'}
        for row in list(self.journal.rows):
            if row['phase'] == 'ACTION' and row['seq'] not in observed:
                self.journal.append(row['instance'], 'OBSERVATION', reason, action=row['seq'],
                                    verification='unknown', exit_code=None, stdout_sha256=None,
                                    target_sha256=None)

    def deny(self, reason):
        reason = str(reason)
        if reason.startswith('inventory hash drift:'):
            reason = 'inventory-hash-drift-repin-reapproval-required'
        if not re.fullmatch('[a-z0-9-]{1,100}', reason):
            reason = 'preflight-failed'
        self.journal.append(self.id, 'DENIAL', reason)
        return self.snapshot()

    def expire(self):
        for token, (_, sha, deadline) in list(self.consent.asks.items()):
            if time.monotonic() >= deadline:
                del self.consent.asks[token]
                self.journal.append(self.id, 'DENIAL', 'ask-expired-fallback-deny', plan_hash=sha)

    def snapshot(self, ask=None):
        self.expire()
        rows = [{k: row[k] for k in ('seq', 'instance', 'phase', 'reason', 'hash', 'ts',
                 'plan_hash', 'action', 'exit_code', 'stdout_sha256', 'target_sha256', 'verification') if k in row}
                for row in self.journal.rows[-32:]]
        return {'instance': self.id, 'open': self.instance is not None and not self.instance.fault,
                'inventory_sha256': policy.INVENTORY_SHA256, 'events': rows, 'ask': ask,
                'total_events': len(self.journal.rows), 'omitted_events': max(0, len(self.journal.rows) - len(rows)),
                'prompt_always': self.consent.load()['promptAlways'], 'askFallback': 'deny',
                'hardware': 'owner-hardware-pending'}

    def check_active(self):
        policy.inventory()
        if is_halted(self.runtime):
            raise ValueError('daemon-halted')
        if self.instance is None or self.instance.fault:
            raise ValueError('dedicated-hand-not-open')

    async def execute(self, value):
        self.check_active()
        self.consent.check(value)
        # Independent nature-at-plan and concrete-argv-at-dispatch evidence, not a Yes override.
        assessment = adjudicate(2, validate(value))
        if assessment.tier != 2 or assessment.verdict != 'ok':
            raise ValueError('independent-adjudication-refused')
        canonical_plan = Plan.parse(json.dumps(value['plan']))
        self.consent.used(value)
        action_ids = []
        for step, proof in zip(value['plan']['steps'], value['evidence'], strict=True):
            row = self.journal.append(self.id, 'ACTION', 'approved-empty-directory-adapter',
                plan_hash=digest(value), r5_plan_hash=canonical_plan.digest, argv=step['argv'], cwd=step['cwd'],
                inventory_verb='send-text', observer_verb='get-text', binary_sha256=proof['binary_sha256'],
                inventory_sha256=value['inventory_sha256'], assessor='concrete-argv-v1',
                nature='reversible-empty-directory', evidence_ref=digest(proof))
            action_ids.append(row['seq'])
        try:
            rows = await asyncio.to_thread(self.instance.execute, value)
        except Exception:
            self.instance.fault = True
            rows = []
        for i, action in enumerate(action_ids):
            row = rows[i] if i < len(rows) else {}
            verification = row.get('verification', 'unknown')
            if verification not in {'observed', 'failed', 'unknown'}:
                verification = 'unknown'
            self.journal.append(self.id, 'OBSERVATION', 'marker-readback-' + verification,
                action=action, plan_hash=digest(value), verification=verification,
                exit_code=row.get('exit_code'), stdout_sha256=row.get('stdout_sha256'),
                target_sha256=row.get('target_sha256'), marker=('ELARIA_OK_' + row['nonce']) if row.get('nonce') else None,
                marker_observed=verification in {'observed', 'failed'})
        return self.snapshot()

    async def handle(self, principal, params):
        if principal is None or principal.uid != os.getuid():
            raise PermissionError('hands-requires-authenticated-owner')
        async with self.lock:
            if self.closed:
                raise ValueError('hands-mount-closed')
            self.initialize()
            try:
                if not isinstance(params, dict):
                    raise TypeError('request-object-required')
                self.expire()
                action = params.get('action')
                if action == 'status' and set(params) == {'action'}:
                    return self.snapshot()
                if action == 'close' and set(params) == {'action'}:
                    self.consent.asks.clear()
                    if self.instance:
                        await asyncio.to_thread(self.instance.close)
                    self.journal.append(self.id, 'CONSENT', 'hand-closed-no-replay')
                    return self.snapshot()
                if action == 'open' and set(params) == {'action'}:
                    policy.inventory()
                    if self.instance is not None or is_halted(self.runtime):
                        raise ValueError('hand-already-open-faulted-or-halted')
                    self.instance = DedicatedKitty(self.runtime, self.id)
                    self.instance.audit = lambda verb, phase, sha: self.journal.append(
                        self.id, 'READ', 'verification-probe', verb=verb, probe_phase=phase, response_sha256=sha)
                    row = self.journal.append(self.id, 'ACTION', 'owner-open-dedicated-instance')
                    try:
                        evidence = await asyncio.to_thread(self.instance.start)
                        self.journal.append(self.id, 'OBSERVATION', 'startup-marker-observed',
                                            action=row['seq'], verification='observed', **evidence)
                    except Exception:
                        self.instance.fault = True
                        self.journal.append(self.id, 'OBSERVATION', 'startup-unknown-no-retry',
                                            action=row['seq'], verification='unknown')
                        raise ValueError('dedicated-start-failed-owner-hardware-pending') from None
                    return self.snapshot()
                if action == 'prompt-always' and set(params) == {'action', 'enabled'}:
                    self.consent.set_prompt_always(params['enabled'])
                    return self.snapshot()
                if action == 'revoke' and set(params) == {'action', 'path'}:
                    self.consent.revoke(params['path'])
                    return self.snapshot()
                if action == 'prepare' and set(params) == {'action', 'text'}:
                    self.consent.asks.clear()
                    self.check_active()
                    value = plan(params['text'], self.instance.work, self.instance.owned)
                    self.journal.append(self.id, 'PLAN', 'nature-assessed-reversible-empty-directory',
                                        plan_hash=digest(value), assessor='intent-effect-v1',
                                        evidence_ref=digest(value['evidence']))
                    if self.consent.covered(value):
                        return await self.execute(value)
                    ask = self.consent.prepare(value)
                    self.journal.append(self.id, 'ASK', 'allowlist-miss-allow-once-default', plan_hash=ask['digest'])
                    return self.snapshot(ask)
                if action == 'answer' and set(params) == {'action', 'token', 'digest', 'decision'}:
                    self.check_active()
                    value = self.consent.answer(params['token'], params['digest'], params['decision'])
                    return await self.execute(value)
                raise ValueError('unsupported-request')
            except Exception as exc:
                return self.deny(exc)

    async def typed(self, require_owner, params):
        text = params.get('text')
        if not isinstance(text, str) or not text.lower().startswith('hands '):
            return None
        # Exact grammar only. This path is before _ask and never asks a model to generate commands.
        principal = require_owner()
        controls = {'hands open': {'action': 'open'}, 'hands close': {'action': 'close'},
                    'hands status': {'action': 'status'},
                    'hands always on': {'action': 'prompt-always', 'enabled': True},
                    'hands always off': {'action': 'prompt-always', 'enabled': False}}
        request = controls.get(text, {'action': 'prepare', 'text': text})
        if text.startswith('hands revoke '):
            request = {'action': 'revoke', 'path': text[len('hands revoke '):]}
        result = await self.handle(principal, request)
        # F21/F34: no spoken ask or denial narrative in centre chat. Consumer renders sidebar only.
        return {'reply': '', 'via': 'hands-adapter', 'hands': result, 'channel': 'console'}

    async def aclose(self):
        async with self.lock:
            self.closed = True
            if self.consent:
                for _, sha, _ in self.consent.asks.values():
                    self.journal.append(self.id, 'DENIAL', 'shutdown-fallback-deny', plan_hash=sha)
                self.consent.asks.clear()
            if self.instance:
                await asyncio.to_thread(self.instance.close)
            if self.journal:
                self.recover_unknown('shutdown-outcome-unknown')
