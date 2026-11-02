"""Independent native-RC assessor for the mounted host, never supplied by request JSON.

Opaque process/program effects still need dedicated trusted effect adapters. They are
refused, not made safe by a model assertion or a Yes. This is an explicit completion
hold, not a permanent capability whitelist. See coverage() for every pinned verb.
"""
from __future__ import annotations

import math

from .adapters.marker import CreateMarkerAdapter
from .attribution import attribute
from .policy import Assessment, digest, inventory

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
        self.marker = CreateMarkerAdapter()

    def coverage(self):
        return {verb: ('partial-create-marker-adapter' if verb == 'create-marker' else
                       'needs-trusted-effect-adapter' if verb in OPAQUE else 'native-state')
                for verb in self.catalogue['verbs']}

    def __call__(self, act, phase, targets):
        def verdict(tier, nature, reason, *, denied=False):
            return attribute(Assessment(tier, nature, denied=denied), assessor='kitty.native/v1',
                             reason=reason, act=act, phase=phase, targets=targets,
                             basis={'catalogue_sha256': digest(self.catalogue)})

        try:
            validate_payload(act, self.catalogue)
        except (ValueError, TypeError, PermissionError):
            return verdict(None, 'unknown', 'wire-schema-evidence-invalid', denied=True)
        if self.halted():
            return verdict(None, 'unknown', 'hands-halted', denied=True)
        if act.verb == 'create-marker':
            return self.marker(act, phase, targets, self.catalogue)
        if act.verb in OPAQUE:
            # NOT an implemented adapter. Name the missing family; never turn the
            # absence of an assessor into a generic approved effect classification.
            return verdict(None, 'unknown', act.verb + '-adapter-not-implemented', denied=True)
        entry = self.catalogue['verbs'][act.verb]
        if entry['tier'] == 'K1':
            return verdict(0, 'observational', 'native-observational')
        # Persistent/global configuration changes cannot be authorized by session hand-open.
        if act.payload.get('configured') or act.payload.get('reset'):
            return verdict(2, 'irreversible', 'native-persistent-change')
        return verdict(1, 'reversible', 'native-state-change')
