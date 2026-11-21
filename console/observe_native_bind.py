#!/usr/bin/python3
"""Read-only, bounded static bind observation; never evaluates Lua or reloads Hyprland.

Literal matches are observations, not exhaustive interpretation of arbitrary Lua/includes.
Optional --live queries only `hyprctl -j binds`; that API does not attest source file/line.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path('/home/darrel/.config/hypr')
TARGET = '/home/darrel/.config/hypr/elaria-console-launch.sh'
GENERATED = 'hl.bind("SUPER + SPACE", hl.dsp.exec_cmd(' + json.dumps(TARGET) + '))'
MAX_FILES = 128
MAX_BYTES = 1024 * 1024
MODIFIERS = {'SHIFT': 1, 'CTRL': 4, 'CONTROL': 4, 'ALT': 8, 'SUPER': 64}


def chord_parts(chord):
    parts = [p.strip().upper() for p in chord.split('+')]
    if len(parts) < 2 or not parts[-1] or any(p not in MODIFIERS for p in parts[:-1]):
        raise ValueError('use a literal modifier + key chord, e.g. SUPER + SPACE')
    mask = 0
    for modifier in parts[:-1]:
        mask |= MODIFIERS[modifier]
    return mask, parts[-1]


def lua_tokens(text):
    """Skip comments and preserve string spans; unsupported syntax stays unknown.

    No imports, includes, shell, Lua evaluation, variable expansion or config execution.
    """
    tokens = []
    i = 0
    while i < len(text):
        start = i
        if text[i].isspace():
            i += 1
            continue
        comment = text.startswith('--', i)
        long = re.match(r'\[(=*)\[', text[i + 2:] if comment else text[i:])
        if long:
            body = i + (2 if comment else 0) + len(long[0])
            closing = ']' + long[1] + ']'
            end = text.find(closing, body)
            if end < 0:
                raise ValueError('unterminated Lua long string/comment')
            i = end + len(closing)
            if not comment:
                tokens.append(('string', text[body:end], start, i))
            continue
        if comment:
            end = text.find('\n', i)
            i = len(text) if end < 0 else end + 1
            continue
        if text[i] in ('"', "'"):
            quote = text[i]
            i += 1
            value = ''
            supported = True
            while i < len(text) and text[i] != quote:
                if text[i] == '\\':
                    i += 1
                    if i == len(text):
                        break
                    if text[i] not in ('\\', '"', "'"):
                        supported = False  # Lua escapes require interpretation; do not guess
                value += text[i]
                i += 1
            if i == len(text):
                raise ValueError('unterminated Lua string')
            i += 1
            tokens.append(('string' if supported else 'unknown', value, start, i))
            continue
        name = re.match(r'[A-Za-z_][A-Za-z_0-9]*', text[i:])
        if name:
            i += len(name[0])
            tokens.append(('name', name[0], start, i))
        else:
            i += 1
            tokens.append(('punct', text[start:i], start, i))
    return tokens


def lua_matches(text, chord):
    tokens = lua_tokens(text)
    matches, unresolved = [], 0
    for index in range(len(tokens) - 4):
        call = tokens[index:index + 4]
        if [(t[0], t[1]) for t in call] != [('name', 'hl'), ('punct', '.'), ('name', 'bind'), ('punct', '(')]:
            continue
        first = tokens[index + 4]
        if first[0] != 'string':
            unresolved += 1
            continue
        try:
            candidate = chord_parts(first[1])
        except ValueError:
            unresolved += 1
            continue
        if candidate != chord:
            continue
        depth, end = 1, index + 4
        while end < len(tokens):
            if tokens[end][0] == 'punct':
                if tokens[end][1] == '(':
                    depth += 1
                elif tokens[end][1] == ')':
                    depth -= 1
                    if depth == 0:
                        break
            end += 1
        if end == len(tokens):
            raise ValueError('unterminated hl.bind call')
        args = tokens[index + 5:end]
        target = None
        expected_prefix = [('punct', ','), ('name', 'hl'), ('punct', '.'), ('name', 'dsp'),
                           ('punct', '.'), ('name', 'exec_cmd'), ('punct', '(')]
        if (len(args) == 9 and [(t[0], t[1]) for t in args[:7]] == expected_prefix
                and args[7][0] == 'string' and args[8][:2] == ('punct', ')')):
            target = args[7][1]
        line = text.count('\n', 0, call[0][2]) + 1
        matches.append({'line': line, 'syntax': 'lua', 'target_matches_wrapper': target == TARGET,
                        'target_literal_known': target is not None,
                        'line_matches_generated': text.splitlines()[line - 1] == GENERATED})
    return matches, unresolved


def conf_matches(text, chord):
    matches, unresolved = [], 0
    for line, raw in enumerate(text.splitlines(), 1):
        content = raw.split('#', 1)[0].strip()
        match = re.match(r'^bind[a-z]*\s*=\s*([^,]*),\s*([^,]*),\s*([^,]*),\s*(.*)$', content)
        if not match:
            continue
        mods, key, dispatcher, target = match.groups()
        try:
            candidate = chord_parts(' + '.join(mods.split() + [key.strip()]))
        except ValueError:
            unresolved += 1
            continue
        if candidate == chord:
            matches.append({'line': line, 'syntax': 'legacy-conf',
                            'target_matches_wrapper': dispatcher.strip() == 'exec' and target.strip() == TARGET,
                            'target_literal_known': True, 'line_matches_generated': False})
    return matches, unresolved


def read_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as file:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
            raise ValueError('not a bounded regular file')
        data = file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('file exceeds bound')
    return data


def observe(root=ROOT, chord='SUPER + SPACE'):
    parsed = chord_parts(chord)
    result = {'chord': chord, 'wrapper': TARGET, 'matches': [], 'files': [], 'unresolved_calls': 0,
              'coverage': 'bounded literal .lua/.conf scan only; dynamic Lua/includes/aliases not evaluated',
              'duplicate_absence': 'UNPROVEN', 'loaded_source_line': 'UNKNOWN',
              'generated_line_sha256': hashlib.sha256(GENERATED.encode()).hexdigest()}
    if root.resolve() != root or not root.is_dir():
        raise ValueError('config root absent, symlinked or not a directory')
    count = 0
    def walk_error(exc):
        result['files'].append({'path': exc.filename, 'status': 'UNREADABLE_DIRECTORY'})
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=walk_error):
        count += 1
        if count > MAX_FILES:
            result['files'].append({'status': 'SCAN_LIMIT_REACHED'})
            return result
        for name in list(dirs):
            if (Path(directory) / name).is_symlink():
                result['files'].append({'path': str(Path(directory) / name), 'status': 'SKIPPED_SYMLINK_DIRECTORY'})
                dirs.remove(name)
        for name in sorted(names):
            path = Path(directory) / name
            if path.suffix not in ('.lua', '.conf'):
                continue
            count += 1
            if count > MAX_FILES:
                result['files'].append({'status': 'SCAN_LIMIT_REACHED'})
                return result
            item = {'path': str(path), 'file_pin': 'UNAVAILABLE: only the generated bind line has a pin'}
            try:
                data = read_config(path)
                text = data.decode('utf-8')
                matches, unresolved = (lua_matches(text, parsed) if path.suffix == '.lua'
                                       else conf_matches(text, parsed))
                item.update(status='SCANNED', sha256=hashlib.sha256(data).hexdigest())
                result['unresolved_calls'] += unresolved
                result['matches'].extend({'file': str(path), **match} for match in matches)
            except (OSError, ValueError) as exc:
                item.update(status='UNREADABLE_OR_UNSUPPORTED', error=type(exc).__name__)
            result['files'].append(item)
    return result


def wrapper_state(path=Path(TARGET)):
    expected = '1a7a54a763039d296111c6ebd843b2f9f79f6152d595ae71fb4ea18293fb0413'
    try:
        if path.resolve() != path:
            return {'status': 'INVALID', 'reason': 'symlinked_wrapper_path'}
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o700):
            return {'status': 'INVALID', 'reason': 'wrapper_type_owner_links_or_mode'}
        digest = hashlib.sha256(read_config(path)).hexdigest()
        return {'status': 'MATCHES_PIN' if digest == expected else 'INVALID',
                'actual': digest, 'expected': expected,
                'scope': 'wrapper only; use check-installed for all helpers and directory checks'}
    except FileNotFoundError:
        return {'status': 'MISSING'}
    except (OSError, ValueError) as exc:
        return {'status': 'UNKNOWN', 'reason': type(exc).__name__}


def live_bindings(chord, runner=subprocess.run):
    unknown = {'status': 'UNKNOWN', 'source_file_line': 'UNKNOWN: binds API does not attest source location'}
    try:
        response = runner(['/usr/bin/hyprctl', '-j', 'binds'], capture_output=True, text=True, timeout=3, check=False)
        if response.returncode or len(response.stdout) > MAX_BYTES:
            return {**unknown, 'reason': 'query_failed_or_response_too_large'}
        rows = json.loads(response.stdout)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            return {**unknown, 'reason': 'unexpected_bind_schema'}
        mask, key = chord_parts(chord)
        matching = []
        for row in rows:
            if row.get('modmask') == mask and str(row.get('key', '')).upper() == key:
                matching.append({'target_matches_wrapper': row.get('dispatcher') == 'exec' and row.get('arg') == TARGET,
                                 'release': row.get('release'), 'submap': row.get('submap')})
        return {**unknown, 'status': 'OBSERVED', 'matching_chord_count': len(matching), 'matches': matching}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {**unknown, 'reason': 'query_unavailable_or_invalid'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chord', default='SUPER + SPACE')
    parser.add_argument('--live', action='store_true', help='Read-only hyprctl binds query; never reload')
    args = parser.parse_args(argv)
    try:
        result = observe(chord=args.chord)
        result['literal_match_count'] = len(result['matches'])
        result['competing_literal_candidates'] = len(result['matches']) > 1
        result['wrapper_state'] = wrapper_state()
        result['live'] = live_bindings(args.chord) if args.live else {'status': 'NOT_QUERIED'}
        # Report only metadata/match booleans, never unrelated commands or config text.
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        print('OBSERVATION exit=0; static matches are not proof of loaded source lines; no config write or reload.', flush=True)
        return 0
    except (OSError, ValueError) as exc:
        print(f'UNKNOWN exit=2 reason={type(exc).__name__}: {exc}; no config write or reload.', flush=True)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
