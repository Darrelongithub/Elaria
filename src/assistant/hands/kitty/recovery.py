"""Private single-writer write-ahead ledger. No payload, password, argv or text persistence.

The open file descriptor is locked for the host lifetime. A malformed/truncated ledger
fails closed; it is never truncated, repaired or replayed automatically.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import threading
from pathlib import Path

from .policy import Consent
from .transport import directory_fd

HASH = re.compile(r'[0-9a-f]{64}\Z')


class RecoveryLedger:
    def __init__(self, path: Path):
        self.lock = threading.RLock()
        self.fd = None
        self.records = []
        with directory_fd(path.parent) as parent:
            info = os.fstat(parent)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError('ledger parent must be owned 0700')
            fd = os.open(path.name, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW
                         | os.O_NONBLOCK, 0o600, dir_fd=parent)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1
                        or info.st_size > 32 * 1024 * 1024):
                    raise PermissionError('invalid private ledger')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                raw = os.pread(fd, info.st_size, 0)
                if len(raw) != info.st_size or (raw and not raw.endswith(b'\n')):
                    raise ValueError('incomplete ledger; manual inspection required')
                for line in raw.splitlines():
                    event = json.loads(line)
                    self.validate(event)
                    self.records.append(event)
                os.fsync(fd)
                os.fsync(parent)  # persist creation before any intent can be acknowledged
                self.fd = fd
            except BaseException:
                os.close(fd)
                raise

    @staticmethod
    def validate(event):
        if (type(event) is not dict or event.get('kind') != 'kitty.act'
                or not HASH.fullmatch(event.get('plan_hash', ''))):
            raise ValueError('invalid ledger record')
        if event.get('phase') not in {'intent', 'result', 'decision', 'cancel-intent', 'cancel-result', 'gate'}:
            raise ValueError('invalid ledger phase')
        if event.get('phase') == 'gate' and (type(event.get('mismatches')) is not int
                or event['mismatches'] not in range(3)):
            raise ValueError('invalid gate counter')
        if event.get('phase') == 'decision':
            if (event.get('choice') not in {'yes', 'no'} or type(event.get('consent')) is not dict
                    or set(event['consent']) != {'ref', 'plan_hash', 'target_fingerprint',
                        'exact_payload_hash', 'execute_newline', 'program_acknowledged'}):
                raise ValueError('invalid decision record')
            c = event['consent']
            if (c['plan_hash'] != event['plan_hash']
                    or any(not isinstance(c[k], str) or not HASH.fullmatch(c[k])
                           for k in ('plan_hash', 'target_fingerprint', 'exact_payload_hash'))
                    or not re.fullmatch(r'[0-9a-f]{24}', c['ref'])
                    or any(type(c[k]) is not bool for k in ('execute_newline', 'program_acknowledged'))):
                raise ValueError('invalid consent metadata')

    def __call__(self, event):
        self.validate(event)
        wire = (json.dumps(event, sort_keys=True, ensure_ascii=True, allow_nan=False) + '\n').encode()
        with self.lock:
            if self.fd is None:
                raise RuntimeError('ledger is closed')
            if os.fstat(self.fd).st_size + len(wire) > 32 * 1024 * 1024:
                raise RuntimeError('ledger bound reached; stop for reviewed archival')
            view = memoryview(wire)
            try:
                while view:
                    n = os.write(self.fd, view)
                    if n <= 0:
                        raise OSError('short ledger write')
                    view = view[n:]
                os.fsync(self.fd)
            except BaseException:
                self.close()  # never append past a possibly torn write in this process
                raise
            self.records.append(json.loads(wire))

    def restore(self, authorizer, endpoint_ref=None):
        """Restore terminal denials, exact unspent Yes and spent/unknown acts; never hand-open."""
        authorizer.close_hand()
        for event in self.records:
            plan = event['plan_hash']
            phase = event['phase']
            if phase == 'gate':
                authorizer.mismatches[plan] = max(authorizer.mismatches.get(plan, 0), event['mismatches'])
            elif phase == 'decision':
                if event['choice'] == 'no':
                    authorizer.denied.add(plan)
                    authorizer.consent.pop(plan, None)
                elif plan not in authorizer.denied and event.get('endpoint_ref') == endpoint_ref:
                    authorizer.consent[plan] = Consent(**event['consent'])
            elif phase == 'cancel-intent':
                authorizer.denied.add(plan)
                authorizer.consent.pop(plan, None)
            elif phase == 'intent' and event.get('operation') != 'probe':
                # Old records lack operation: conservatively treat their intent as spent.
                authorizer.consumed.add(plan)
        for plan in authorizer.consumed:
            authorizer.consent.pop(plan, None)

    def close(self):
        with self.lock:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
