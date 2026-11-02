"""Inert-until-attach kitty mount on the EXISTING daemon's authenticated IPC.

No server, model, subprocess or desktop dispatch. Request JSON cannot provide a checker,
transport, identity, journal path or approval reference. Construction performs no I/O.
The native assessor deliberately fails closed on unresolved opaque program effects.
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import secrets
from dataclasses import asdict
from pathlib import Path

from assistant.hands.gate import adjudicate
from assistant.ipc import IpcPrincipal
from assistant.safety import is_halted

from .bridge import Bridge
from .checker import NativeChecker
from .policy import Act, Consent, canonical, digest, fingerprint, tier_for
from .recovery import HASH, RecoveryLedger
from .settings import load_settings
from .surface import resolve
from .transport import Transport


def native_effect(act, before, after, response):
    """Only claim observed changes supported by ls. Everything else remains unverified."""
    old, new = ({w['id']: w for w in rows} for rows in (before, after))
    if not act.target_ids or any(i not in old or i not in new for i in act.target_ids):
        return False
    if any(fingerprint([old[i]]) != fingerprint([new[i]]) for i in act.target_ids):
        return False
    field = {'set-window-title': 'title', 'set-tab-title': 'tab_title',
             'goto-layout': 'layout', 'focus-window': 'is_focused', 'focus-tab': 'tab_is_focused'}.get(act.verb)
    if field is None:
        return False
    wanted = True if act.verb.startswith('focus-') else act.payload.get('layout' if act.verb == 'goto-layout' else 'title')
    return (wanted is not None and all(new[i].get(field) == wanted for i in act.target_ids)
            and any(old[i].get(field) != wanted for i in act.target_ids))


class Session:
    def __init__(self, transport, checker, ledger, endpoint_ref):
        self.ledger = ledger
        self.bridge = Bridge(transport, checker, ledger, resolver=resolve,
                             verifier=native_effect, endpoint_ref=endpoint_ref)
        ledger.restore(self.bridge.authorizer, endpoint_ref)
        self.bridge.authorizer.audit = self.record_gate
        # HER identity is recovered only from durable successful creation at the SAME endpoint.
        for record in ledger.records:
            if (record.get('endpoint_ref') == endpoint_ref
                    and record.get('verification') == 'created-id-and-stamp-observed'
                    and record.get('phase') == 'result'):
                for item in record.get('ownership', []):
                    if not isinstance(item, str) or not HASH.fullmatch(item):
                        raise ValueError('invalid ownership record')
                    self.bridge.owned.add(item)
        self.pending = {}

    def record_gate(self, plan_hash, mismatches):
        self.bridge.event(verb='gate', tier='K3', plan_hash=plan_hash, targets=[], consent_ref=None,
                          verification='adjudicated', phase='gate', mismatches=mismatches)

    @classmethod
    def attach(cls, public_key, runtime):
        if (not isinstance(public_key, str) or not public_key.startswith('1:')
                or len(public_key) > 128 or len(base64.b85decode(public_key[2:])) != 32):
            raise ValueError('invalid public key')
        config_home = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
        settings = load_settings(config_home / 'assistant/kitty-bridge.toml')
        runtime = Path(runtime)
        if str(runtime) != os.environ.get('XDG_RUNTIME_DIR'):
            raise PermissionError('daemon and kitty runtime must agree')
        transport = Transport(settings.socket, runtime, dict(settings.passwords), public_key,
                              timeout=settings.timeout_seconds, max_response_bytes=settings.max_response_bytes)
        ledger = RecoveryLedger(settings.journal)
        try:
            return cls(transport, NativeChecker(halted=lambda: is_halted(runtime)), ledger,
                       digest([str(settings.socket), public_key]))
        except BaseException:
            ledger.close()
            raise

    def prepare(self, params):
        if set(params) not in ({'op', 'verb', 'payload', 'target_ids', 'model_tier'},
                               {'op', 'verb', 'payload', 'target_ids', 'model_tier', 'nonce'}):
            raise ValueError('invalid prepare shape')
        nonce = params.get('nonce', secrets.token_hex(16))
        if (not isinstance(nonce, str) or not re.fullmatch(r'[0-9a-f]{32}', nonce)
                or type(params['target_ids']) is not list or type(params['payload']) is not dict):
            raise ValueError('invalid act shape')
        act = Act(params['verb'], canonical(params['payload']), tuple(params['target_ids']), nonce)
        plan = act.plan(params['model_tier'])
        if plan.digest in self.bridge.authorizer.consumed or plan.digest in self.bridge.authorizer.denied:
            raise PermissionError('spent or terminally denied plan')
        targets = self.bridge.inspect(act, plan)
        assessment = self.bridge.authorizer.evaluate(act, plan, 'disclose', targets)
        verdict = adjudicate(plan.steps[0].tier, assessment.legacy_tier)
        if assessment.denied or verdict.verdict == 'refused':
            raise PermissionError('disclosure refused')
        tier = tier_for(act, assessment, targets, self.bridge.owned, self.bridge.catalogue)
        self.pending[plan.digest] = (act, plan, targets)
        return {'plan_hash': plan.digest, 'nonce': nonce, 'verb': act.verb, 'payload': act.payload,
                'targets': targets, 'tier': tier, 'requires_consent': tier == 'K3' or verdict.ask,
                'requires_session_hand': tier == 'K2',
                'hazards': self.bridge.catalogue['verbs'].get(act.verb, {}).get('hazards', ['unclassified-K3'])}

    def decision(self, params):
        if set(params) != {'op', 'plan_hash', 'choice', 'execute_newline', 'program_acknowledged'}:
            raise ValueError('invalid decision shape')
        if (params['choice'] not in {'yes', 'no'} or any(type(params[k]) is not bool
                for k in ('execute_newline', 'program_acknowledged'))):
            raise ValueError('exact choice and explicit booleans required')
        act, plan, targets = self.pending[params['plan_hash']]
        auth = self.bridge.authorizer
        if plan.digest in auth.consumed or plan.digest in auth.denied:
            raise PermissionError('spent or denied plan')
        consent = Consent(secrets.token_hex(12), plan.digest, fingerprint(targets), digest(act.payload),
                          params['execute_newline'], params['program_acknowledged'])
        self.bridge.event(verb=act.verb, tier='K3', plan_hash=plan.digest, targets=targets,
                          consent_ref=consent.ref, verification='recorded', phase='decision',
                          choice=params['choice'], consent=asdict(consent))
        auth.decide(consent, owner_answer=params['choice'])
        return {'decision': params['choice'], 'plan_hash': plan.digest, 'consent_ref': consent.ref}

    def revoke_hand(self):
        auth = self.bridge.authorizer
        try:
            for key, consent in tuple(auth.consent.items()):
                self.bridge.event(verb='hand-close', tier='K3', plan_hash=key, targets=[],
                                  consent_ref=consent.ref, verification='revoked', phase='decision',
                                  choice='no', consent=asdict(consent))
                auth.denied.add(key)
        finally:
            auth.close_hand()

    def run(self, plan_hash):
        act, plan, _ = self.pending[plan_hash]
        return self.bridge.execute(act, plan)

    def close(self):
        self.bridge.authorizer.close_hand()
        self.pending.clear()
        self.ledger.close()


class KittyMount:
    """Single host lifecycle, dependency-injectable in local stub tests only."""
    def __init__(self, runtime: Path, *, factory=Session.attach):
        self.runtime, self.factory = runtime, factory
        self.session = None
        self.worker = None
        self.serial = asyncio.Lock()
        self.closed = False
        self.running_hash = None
        self.cleanup_failed = False

    async def handle(self, principal, params):
        if type(principal) is not IpcPrincipal or principal.uid != os.getuid():
            raise PermissionError('authenticated local owner required')
        try:
            if type(params) is not dict or self.closed:
                raise PermissionError('mount closed or invalid request')
            op = params.get('op')
            # Cancellation must remain reachable while a worker waits on kitty.
            if op == 'cancel':
                if set(params) != {'op', 'plan_hash'} or not HASH.fullmatch(params['plan_hash']):
                    raise ValueError('invalid cancel')
                if self.session is None or params['plan_hash'] not in self.session.pending:
                    raise PermissionError('unknown prepared act')
                return await asyncio.to_thread(self.session.bridge.cancel, params['plan_hash'])
            async with self.serial:
                if self.worker is not None and not self.worker.done():
                    raise PermissionError('act in flight; only cancel is available')
                if op == 'status' and set(params) == {'op'}:
                    return {'attached': self.session is not None, 'hand_open': bool(
                        self.session and self.session.bridge.authorizer.hand_ref), 'scene_ready': False}
                if op == 'attach' and set(params) == {'op', 'public_key'}:
                    if self.session is not None:
                        raise PermissionError('already attached')
                    self.session = self.factory(params['public_key'], self.runtime)
                    return {'attached': True, 'hand_open': False, 'scene_ready': False}
                if self.session is None:
                    raise PermissionError('explicit attach required')
                if op == 'detach' and set(params) == {'op'}:
                    self.session.close()
                    self.session = None
                    return {'attached': False}
                if op == 'open-hand' and set(params) == {'op', 'phrase'}:
                    self.session.bridge.authorizer.open_hand(owner_phrase=params['phrase'], reference=secrets.token_hex(12))
                    return {'hand_open': True}
                if op == 'close-hand' and set(params) == {'op'}:
                    self.session.revoke_hand()
                    return {'hand_open': False}
                if op == 'prepare':
                    self.running_hash = None
                    worker = asyncio.create_task(asyncio.to_thread(self.session.prepare, params))
                elif op == 'decide':
                    return self.session.decision(params)
                else:
                    if op != 'run' or set(params) != {'op', 'plan_hash'} or not HASH.fullmatch(params['plan_hash']):
                        raise ValueError('unsupported kitty request')
                    if params['plan_hash'] not in self.session.pending:
                        raise PermissionError('unknown prepared act')
                    self.running_hash = params['plan_hash']
                    worker = asyncio.create_task(asyncio.to_thread(self.session.run, self.running_hash))
                self.worker = worker
                worker.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            # Disconnect/cancel of an IPC waiter must not release the worker/ledger or replay.
            return await asyncio.shield(worker)
        except Exception:
            raise ValueError('kitty request refused or effect unknown; inspect private journal') from None

    async def aclose(self):
        self.closed = True
        async with self.serial:
            session = self.session
            if session is None:
                return
            try:
                if self.worker is not None and not self.worker.done():
                    if self.running_hash is not None:
                        await asyncio.to_thread(session.bridge.cancel, self.running_hash)
                    try:
                        await asyncio.shield(self.worker)
                    except Exception:
                        self.cleanup_failed = True  # never let cleanup alter old handlers
            except Exception:
                self.cleanup_failed = True
                # Do not close the writer beneath an already dispatched worker.
                if self.worker is not None and not self.worker.done():
                    try:
                        await asyncio.shield(self.worker)
                    except Exception:
                        self.cleanup_failed = True
            finally:
                try:
                    session.close()
                except Exception:
                    self.cleanup_failed = True
                self.session = None
