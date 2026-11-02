#!/usr/bin/env python3
"""Owner-only, one-shot metadata drift check. Runs help/version ONLY, never RC acts.

Rerun after every dnf kitty upgrade. Exit 0 means parsed metadata matches the pinned
inventory, NOT that hardware/permissions/effect semantics have been verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / 'src/assistant/hands/kitty/data/inventory.json'
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def commands(help_text):
    # Version-matched tools/cli/help.go uses THREE spaces for command names;
    # descriptions use four. Python legacy help uses two. Never mine prose words.
    return set(re.findall(r'^ {2,3}([a-z][a-z0-9-]*)\s*$', ANSI.sub('', help_text), re.MULTILINE))


def option_headers(help_text):
    result = {}
    for line in ANSI.sub('', help_text).splitlines():
        if not re.match(r'^  --?[\w-]', line):
            continue
        flags = re.findall(r'(?<![\w-])-{1,2}[\w-]+', line.split(' [=')[0])
        default = re.search(r'\[=(.*)\]$', line)
        for flag in flags:
            result[flag] = default[1] if default else ''
    return result


def display_default(option):
    value = option['default']
    if type(value) is bool:
        return 'yes' if value else 'no'
    if isinstance(value, list):
        return option['declared_default'] or ''
    return str(value) if value is not None else ''


def compare_options(entry, global_options, actual):
    expected = {flag: display_default(o) for o in [*global_options, *entry['options']]
                for flag in o['flags']}
    # Framework-generated help options are not RC command options.
    actual = {k: v for k, v in actual.items() if k not in {'--help', '-h', '--version'}}
    return {'missing': sorted(expected.keys() - actual.keys()),
            'new': sorted(actual.keys() - expected.keys()),
            'defaults': {k: {'pinned': expected[k], 'installed': actual[k]}
                         for k in expected.keys() & actual.keys() if expected[k] != actual[k]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kitten', default='/usr/bin/kitten', help='Installed kitten executable')
    parser.add_argument('--output', type=Path, required=True, help='New private evidence directory OUTSIDE repository')
    args = parser.parse_args()
    output = args.output.absolute()
    if output == ROOT or ROOT in output.parents or output.exists():
        parser.error('output must be a NEW directory outside this repository')
    output.mkdir(mode=0o700, parents=True)
    data = json.loads(INVENTORY.read_text())
    environment = {k: v for k, v in os.environ.items() if not k.startswith('KITTY_')}
    environment.update(LC_ALL='C.UTF-8', TERM='dumb', NO_COLOR='1')

    def run(arguments, filename):
        try:
            result = subprocess.run([args.kitten, *arguments], capture_output=True, text=True,
                                    timeout=20, check=False, env=environment)
            record = {'argv': arguments, 'returncode': result.returncode,
                      'stdout': result.stdout, 'stderr': result.stderr}
        except (OSError, subprocess.TimeoutExpired) as exc:
            record = {'argv': arguments, 'returncode': None, 'stdout': '', 'stderr': type(exc).__name__}
        path = output / filename
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2)
        return record

    version = run(['--version'], 'version.json')
    root = run(['@', '--help'], 'commands.json')
    found = commands(root['stdout'])
    expected = set(data['verbs'])
    report = {'owner_version_verbatim': version['stdout'], 'version_stderr_verbatim': version['stderr'],
              'pinned': data['upstream_version'], 'missing_verbs': sorted(expected - found),
              'new_verbs': sorted(found - expected), 'option_deltas': {}, 'help_sha256': {}, 'errors': [],
              'hardware_proven': False, 'requires_manual_semantics_review': True}
    if version['returncode'] != 0 or root['returncode'] != 0 or not found:
        report['errors'].append('version/help failed or command list not parsed')
    if not re.search(r'(?<![\d.])' + re.escape(data['upstream_version']) + r'(?![\d.])', version['stdout']):
        report['errors'].append('installed version differs or could not be parsed')
    for verb in sorted(expected | found):
        help_record = run(['@', verb, '--help'], verb + '.json')
        text = help_record['stdout']
        report['help_sha256'][verb] = hashlib.sha256(text.encode()).hexdigest()
        if help_record['returncode'] != 0:
            report['errors'].append(verb + ': help failed')
            continue
        if verb in expected:
            diff = compare_options(data['verbs'][verb], data['global_options'], option_headers(text))
            if any(diff.values()):
                report['option_deltas'][verb] = diff
    report['metadata_match'] = not any(report[k] for k in ('missing_verbs', 'new_verbs', 'option_deltas', 'errors'))
    summary = output / 'report.json'
    fd = os.open(summary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != 'help_sha256'}, indent=2))
    return 0 if report['metadata_match'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
