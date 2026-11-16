"""F13/F14/F31 owner consent. Private durable allowlist; immutable asks are memory-only.

No interpreter permits, no regex/glob/shell-string matches, no approval from model prose.
Same-UID tampering is outside this process boundary, as for the existing daemon.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import secrets
import stat
import time
from pathlib import Path

from ..kitty import policy
from .contract import CONTRACT, canonical, digest, pattern, validate


def private_dir(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('symlinked-control-directory')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('control-directory-not-private')
    return path


def open_private(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
        os.close(fd)
        raise ValueError('unsafe-private-file')
    return fd


def read_json(path):
    fd = open_private(path, os.O_RDONLY)
    with os.fdopen(fd, 'rb') as stream:
        raw = stream.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('private-file-bound')
    return json.loads(raw)


def write_json(path, value):
    # No truncation of an unverified destination. A crash leaves old or new complete bytes.
    path = Path(path)
    if path.exists() or path.is_symlink():
        os.close(open_private(path, os.O_RDONLY))
    temporary = path.with_name('.' + path.name + '-' + secrets.token_hex(8))
    fd = open_private(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


class Journal:
    """Append-only bounded hash chain, metadata only, replayable across daemon restarts."""
    def __init__(self, root):
        self.path = private_dir(root) / 'events.jsonl'
        self.rows = []
        if self.path.exists() or self.path.is_symlink():
            fd = open_private(self.path, os.O_RDONLY)
            with os.fdopen(fd, 'rb') as stream:
                raw = stream.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise ValueError('journal-full-stop-no-truncation')
            previous = '0' * 64
            for line in raw.splitlines():
                row = json.loads(line)
                recorded = row.pop('hash')
                if row['previous'] != previous or row['seq'] != len(self.rows) + 1 or digest(row) != recorded:
                    raise ValueError('journal-integrity-failed')
                self.rows.append(dict(row, hash=recorded)); previous = recorded

    def append(self, instance, phase, reason, **metadata):
        if len(self.rows) >= 2000:
            raise ValueError('journal-full-stop-no-truncation')
        row = {'seq': len(self.rows) + 1, 'previous': self.rows[-1]['hash'] if self.rows else '0' * 64,
               'ts': time.time(), 'instance': instance, 'phase': phase, 'reason': reason, **metadata}
        row['hash'] = digest(row)
        fd = open_private(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        with os.fdopen(fd, 'w') as stream:
            line = canonical(row) + '\n'
            if len(line.encode()) > 8192 or os.fstat(stream.fileno()).st_size + len(line.encode()) > 4 * 1024 * 1024:
                raise ValueError('journal-full-stop-no-truncation')
            stream.write(line); stream.flush(); os.fsync(stream.fileno())
        self.rows.append(row)
        return row


class Consent:
    def __init__(self, root, journal, instance):
        self.path = private_dir(root) / 'allowlist.json'
        self.journal, self.instance = journal, instance
        self.asks = {}
        if not self.path.exists() and not self.path.is_symlink():
            write_json(self.path, {'contract': CONTRACT, 'promptAlways': False, 'entries': []})
        self.load()

    def load(self):
        value = read_json(self.path)
        if (set(value) != {'contract', 'promptAlways', 'entries'} or value['contract'] != CONTRACT
                or type(value['promptAlways']) is not bool or not isinstance(value['entries'], list)
                or len(value['entries']) > 128):
            raise ValueError('invalid-allowlist-contract')
        for entry in value['entries']:
            if (set(entry) != {'path', 'argPattern', 'binary_sha256', 'inventory_sha256', 'source', 'lastUsed'}
                    or entry['source'] not in {'ruling', 'prompt'}
                    or type(entry['lastUsed']) not in {float, int} or not math.isfinite(entry['lastUsed'])
                    or entry['lastUsed'] < 0
                    or not isinstance(entry['path'], str) or Path(entry['path']).name not in {'mkdir', 'rmdir'}
                    or entry['path'] not in {str(Path('/usr/bin/mkdir').resolve()), str(Path('/usr/bin/rmdir').resolve())}
                    or not isinstance(entry['argPattern'], str) or not re.fullmatch('sha256:[a-f0-9]{64}', entry['argPattern'])
                    or any(not isinstance(entry[k], str) or not re.fullmatch('[a-f0-9]{64}', entry[k])
                           for k in ('binary_sha256', 'inventory_sha256'))):
                raise ValueError('invalid-allowlist-entry')
        return value

    def set_prompt_always(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('explicit-boolean-required')
        value = self.load(); value['promptAlways'] = enabled
        self.journal.append(self.instance, 'CONSENT', 'prompt-always-enabled' if enabled else 'prompt-always-disabled')
        write_json(self.path, value)

    def revoke(self, path):
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ValueError('named-absolute-path-required')
        path = str(Path(path).resolve())
        value = self.load()
        value['entries'] = [entry for entry in value['entries'] if entry['path'] != path]
        # A failed journal write never makes revocation silently look completed.
        self.journal.append(self.instance, 'CONSENT', 'revoked', path=path)
        write_json(self.path, value)
        self.asks.clear()

    def check(self, value):
        policy.inventory()  # hash checked on EVERY approval/pre-exec, before any permission match
        if value['inventory_sha256'] != policy.INVENTORY_SHA256:
            raise ValueError('inventory-consent-drift')
        validate(value)
        return self.load()

    def covered(self, value):
        state = self.check(value)
        # Any old inventory binding is a visible denial, not an implicit re-pinning.
        if any(e['inventory_sha256'] != policy.INVENTORY_SHA256 for e in state['entries']):
            raise ValueError('standing-consent-inventory-drift-reapproval-required')
        for step, proof in zip(value['plan']['steps'], value['evidence'], strict=True):
            if any(e['path'] == step['argv'][0] and e['argPattern'] == proof['argPattern']
                   and e['binary_sha256'] != proof['binary_sha256'] for e in state['entries']):
                raise ValueError('standing-consent-binary-drift-reapproval-required')
            if not any(entry['path'] == step['argv'][0] and entry['argPattern'] == pattern(step['argv'])
                       and entry['binary_sha256'] == proof['binary_sha256']
                       and (entry['source'] == 'ruling' or state['promptAlways']) for entry in state['entries']):
                return False
        return True

    def prepare(self, value):
        self.check(value)
        self.asks.clear()  # one focused whole-plan selection, never a batch of loose Yes tokens
        token = secrets.token_hex(16)
        snapshot = canonical(value)
        self.asks[token] = (snapshot, digest(value), time.monotonic() + 120)
        return {'token': token, 'digest': digest(value), 'plan': copy.deepcopy(value),
                'remaining_s': 120, 'allow_always': self.load()['promptAlways'],
                'default': 'allow-once', 'askFallback': 'deny'}

    def answer(self, token, expected, decision):
        ask = self.asks.pop(token, None)  # No, expiry, drift, failure and Yes all consume once
        if ask is None:
            raise ValueError('ask-already-answered-or-absent')
        snapshot, sha, deadline = ask
        if expected != sha or time.monotonic() >= deadline:
            raise ValueError('ask-drift-or-expiry')
        if decision == 'deny':
            raise ValueError('owner-denied')
        if decision not in {'allow-once', 'allow-always'}:
            raise ValueError('unsupported-decision')
        value = json.loads(snapshot)
        state = self.check(value)
        if decision == 'allow-always' and not state['promptAlways']:
            raise ValueError('prompt-seeded-always-disabled')
        self.journal.append(self.instance, 'CONSENT', decision, plan_hash=sha)
        if decision == 'allow-always':
            for step, proof in zip(value['plan']['steps'], value['evidence'], strict=True):
                entry = {'path': step['argv'][0], 'argPattern': proof['argPattern'],
                         'binary_sha256': proof['binary_sha256'], 'inventory_sha256': value['inventory_sha256'],
                         'source': 'prompt', 'lastUsed': 0}
                state['entries'] = [e for e in state['entries'] if (e['path'], e['argPattern']) !=
                                    (entry['path'], entry['argPattern'])] + [entry]
            if len(state['entries']) > 128:
                raise ValueError('allowlist-full')
            write_json(self.path, state)
        return value

    def used(self, value):
        state = self.check(value)
        patterns = {e['argPattern'] for e in value['evidence']}
        for entry in state['entries']:
            if entry['argPattern'] in patterns:
                entry['lastUsed'] = time.time()
        write_json(self.path, state)
