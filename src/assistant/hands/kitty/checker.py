"""Independent native-RC assessor for the mounted host, never supplied by request JSON.

Opaque process/program effects still need dedicated trusted effect adapters. They are
refused, not made safe by a model assertion or a Yes. This is an explicit completion
hold, not a permanent capability whitelist. See coverage() for every pinned verb.
"""
from __future__ import annotations

import math

from .policy import Assessment, inventory

OPAQUE = frozenset({'action', 'kitten', 'launch', 'new-window', 'run', 'load-config',
                    'env', 'send-text', 'send-key', 'signal-child', 'create-marker'})


def validate_payload(act, catalogue):
    entry = catalogue['verbs'].get(act.verb)
    if entry is None:
        raise ValueError('unclassified wire protocol')
    fields = {f['name']: f for f in entry['payload']}
    p = act.payload
    if p.keys() - fields.keys() or any(f['required'] and k not in p for k, f in fields.items()):
        raise ValueError('unknown or missing wire field')
    for key, value in p.items():
        kind = fields[key]['type'].split('=')[0]
        if kind == 'bool':
            valid = type(value) is bool
        elif kind == 'int':
            valid = type(value) is int
        elif kind == 'float':
            valid = type(value) in {int, float} and math.isfinite(value)
        elif kind == 'str' or kind.startswith('choices.'):
            valid = isinstance(value, str) and '\x00' not in value
            if valid and kind.startswith('choices.') and '{' not in kind:
                valid = value in kind.split('.')[1:]
        elif kind.startswith('list.'):
            typ = {'str': str, 'int': int}.get(kind[5:])
            valid = type(value) is list and typ is not None and all(type(v) is typ for v in value)
        elif kind.startswith('dict.'):
            valid = type(value) is dict and all(isinstance(k, str) for k in value)
        else:
            valid = False
        if not valid:
            raise ValueError('wire field type or choice mismatch')
    if p.get('allow_remote_control') or p.get('remote_control_password'):
        raise PermissionError('child remote-control grant refused')


class NativeChecker:
    def __init__(self, *, halted=lambda: False):
        self.catalogue = inventory()
        self.halted = halted

    def coverage(self):
        return {verb: 'needs-trusted-effect-adapter' if verb in OPAQUE else 'native-state'
                for verb in self.catalogue['verbs']}

    def __call__(self, act, phase, targets):
        try:
            validate_payload(act, self.catalogue)
        except (ValueError, TypeError, PermissionError):
            return Assessment(None, 'unknown', denied=True)
        if self.halted() or act.verb in OPAQUE:
            return Assessment(None, 'unknown', denied=True)
        entry = self.catalogue['verbs'][act.verb]
        if entry['tier'] == 'K1':
            return Assessment(0, 'observational')
        # Persistent/global configuration changes cannot be authorized by session hand-open.
        if act.payload.get('configured') or act.payload.get('reset'):
            return Assessment(2, 'irreversible')
        return Assessment(1, 'reversible')
