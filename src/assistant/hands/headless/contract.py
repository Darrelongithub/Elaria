"""F14 exact-argv-v1: no shell, wildcard, interpreter or executable script approvals.

Two small effect adapters, not a general command safety classifier. Unsupported is denied.
Stdlib-only: also imported by the fixed non-shell Kitty worker. No copied external code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
from pathlib import Path

CONTRACT = 'headless-exact-argv-v1'
INVENTORY_SHA = '7e0f01ff2396c292f05528261d349142f1c6e08eed948847ee1300633a1aafcd'
NAME = re.compile(r'[a-zA-Z][a-zA-Z0-9_-]{0,63}')
HEX = re.compile(r'[a-f0-9]{64}')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identity(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('noncanonical-or-symlink-path')
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('workspace-not-private-owned-directory')
    return [info.st_dev, info.st_ino, info.st_mode, info.st_uid]


def target_state(path):
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return {'state': 'absent'}
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or info.st_uid != os.getuid():
        raise ValueError('target-not-owned-directory')
    # Any content makes rmdir unassessed, not permission to recurse or read it.
    with os.scandir(path) as entries:
        if next(entries, None) is not None:
            raise ValueError('target-not-empty')
    return {'state': 'empty-directory', 'dev': info.st_dev, 'ino': info.st_ino,
            'mode': info.st_mode, 'uid': info.st_uid}


def executable(path):
    """Canonical ELF identity. Closed templates, not name-only interpreter detection."""
    path = Path(path).resolve(strict=True)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in {0, os.getuid()}:
            raise ValueError('unsafe-binary')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024 or not raw.startswith(b'\x7fELF'):
            raise ValueError('script-or-non-ELF-refused')
        return str(path), hashlib.sha256(raw).hexdigest()
    finally:
        os.close(fd)


def pattern(argv):
    if not isinstance(argv, list) or not argv or any(type(a) is not str or '\x00' in a for a in argv):
        raise ValueError('parsed-argv-array-required')
    return 'sha256:' + digest(argv)


def parse_intent(text):
    """Grammar: hands mkdir NAME [&& mkdir NAME ...], or hands rmdir NAME.

    shlex only tokenizes; no shell string is ever executed. All other operators,
    substitution, redirects, pipelines and script operands are unsupported and denied.
    """
    if not isinstance(text, str) or len(text) > 2048 or not text.startswith('hands '):
        raise ValueError('unsupported-hands-intent')
    if not re.fullmatch(r'hands [a-zA-Z0-9_ &-]+', text):
        raise ValueError('unsupported-shell-syntax')
    lexer = shlex.shlex(text[6:], posix=True, punctuation_chars=';&|<>')
    lexer.whitespace_split = True
    lexer.commenters = ''
    tokens = list(lexer)
    segments, current = [], []
    for token in tokens + ['&&']:
        if token == '&&':
            if len(current) != 2 or current[0] not in {'mkdir', 'rmdir'} or not NAME.fullmatch(current[1]):
                raise ValueError('unsupported-or-irreversible-intent')
            segments.append(tuple(current)); current = []
        else:
            current.append(token)
    if not 1 <= len(segments) <= 4 or len({name for _, name in segments}) != len(segments):
        raise ValueError('unsupported-chain-or-dependent-targets')
    return segments


def plan(text, work, owned):
    work = Path(work)
    cwd_identity = identity(work)
    steps, evidence = [], []
    for i, (verb, name) in enumerate(parse_intent(text)):
        target = work / name
        before = target_state(target)
        # Nature assessor: empty-directory changes in this minted workspace only.
        if verb == 'mkdir' and before['state'] != 'absent':
            raise ValueError('mkdir-target-exists')
        if verb == 'rmdir' and (before['state'] != 'empty-directory' or owned.get(name) != digest(before)):
            raise ValueError('rmdir-not-her-observed-empty-directory')
        binary, sha = executable('/usr/bin/' + verb)
        if Path(binary).name != verb:
            raise ValueError('interpreter-or-binary-alias-refused')
        argv = [binary, '--', str(target)]
        steps.append({'i': i, 'tier': 2, 'tool': 'exec', 'argv': argv, 'cwd': str(work), 'env_diff': {}})
        evidence.append({'verb': verb, 'binary_sha256': sha, 'argPattern': pattern(argv), 'before': before})
    value = {'contract': CONTRACT, 'inventory_sha256': INVENTORY_SHA,
             'plan': {'steps': steps}, 'cwd_identity': cwd_identity, 'evidence': evidence}
    validate(value)
    return value


def validate(value):
    """Independent concrete-argv assessor, re-run before every execute in both processes."""
    if value.get('contract') != CONTRACT or value.get('inventory_sha256') != INVENTORY_SHA:
        raise ValueError('contract-or-inventory-drift')
    steps = value['plan']['steps']
    evidence = value['evidence']
    if not 1 <= len(steps) <= 4 or len(evidence) != len(steps):
        raise ValueError('invalid-chain')
    targets = set()
    for i, (step, proof) in enumerate(zip(steps, evidence, strict=True)):
        argv = step['argv']
        verb = proof['verb']
        if verb not in {'mkdir', 'rmdir'} or step != {
                'i': i, 'tier': 2, 'tool': 'exec', 'argv': argv, 'cwd': step['cwd'], 'env_diff': {}}:
            raise ValueError('unsupported-executable-or-step')
        allowed_binary, sha = executable('/usr/bin/' + verb)
        if (Path(allowed_binary).name != verb or len(argv) != 3 or argv[:2] != [allowed_binary, '--']
                or sha != proof['binary_sha256'] or pattern(argv) != proof['argPattern']):
            raise ValueError('binary-or-argv-drift')
        cwd, target = Path(step['cwd']), Path(argv[2])
        if identity(cwd) != value['cwd_identity'] or target.parent != cwd or not NAME.fullmatch(target.name):
            raise ValueError('cwd-or-operand-drift')
        if str(target) in targets:
            raise ValueError('dependent-chain-refused')
        targets.add(str(target))
        if target_state(target) != proof['before']:
            raise ValueError('operand-state-drift')
        if proof['before']['state'] != ('absent' if verb == 'mkdir' else 'empty-directory'):
            raise ValueError('effect-not-assessed')
    return 2
