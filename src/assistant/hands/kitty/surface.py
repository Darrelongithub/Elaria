"""Explicit ID target binding for native RC. No active-window or regex guessing.

Full arbitrary-selector normalization remains a completion gate. Requiring a resolved
ID expression does not imply that a known native command has been effect-verified.
"""
from __future__ import annotations

from .policy import inventory

TABS = frozenset({'close-tab', 'focus-tab', 'set-tab-title', 'set-tab-color', 'goto-layout',
                  'last-used-layout', 'set-enabled-layouts', 'detach-tab', 'select-window'})
OS_WINDOWS = frozenset({'resize-os-window', 'set-background-image', 'set-background-opacity'})
GLOBAL = frozenset({'env', 'load-config', 'run'})
CREATORS = frozenset({'launch', 'new-window'})


def expression(ids):
    return ' or '.join(f'id:{i}' for i in sorted(set(ids)))


def resolve(act, snapshot):
    entry = inventory()['verbs'].get(act.verb)
    if entry is None:
        raise PermissionError('new verb requires target adapter review')
    p = act.payload
    by_id = {w['id']: w for w in snapshot}
    if any(i not in by_id for i in act.target_ids):
        raise PermissionError('target disappeared')
    selected = [by_id[i] for i in act.target_ids]
    if p.get('self'):
        raise PermissionError('TTY-relative self is not an AF_UNIX target identity')
    fields = {f['name'] for f in entry['payload']}
    selector = 'match_window' if 'match_window' in fields else 'match'
    if act.verb in GLOBAL:
        if act.target_ids:
            raise PermissionError('global act must not imply a narrower scope')
        return list(snapshot)
    if act.verb == 'ls' and not p.get('match') and not p.get('match_tab'):
        if act.target_ids:
            raise PermissionError('ls selection differs from wire request')
        return list(snapshot)
    if act.verb == 'set-font-size':
        if p.get('all') is not True or set(act.target_ids) != set(by_id):
            raise PermissionError('font-size active-OS selection needs an explicit adapter')
        return list(snapshot)
    if act.verb in CREATORS:
        raise PermissionError('creation destination/source adapter remains under review')
    if p.get('all'):
        if set(act.target_ids) != set(by_id) or p.get(selector) or p.get('match_tab'):
            raise PermissionError('global selection must disclose every affected ID')
        return list(snapshot)
    if not selected:
        raise PermissionError('explicit resolved IDs required')
    if act.verb in TABS:
        tabs = {w['tab_id'] for w in selected}
        selected = [w for w in snapshot if w['tab_id'] in tabs]
        wanted = expression(tabs)
    elif p.get('match_tab'):
        tabs = {w['tab_id'] for w in selected}
        if p.get(selector) or p['match_tab'] != expression(tabs):
            raise PermissionError('ambiguous tab/window selector')
        return [w for w in snapshot if w['tab_id'] in tabs]
    else:
        wanted = expression(act.target_ids)
    if p.get(selector) != wanted or p.get('match_tab'):
        raise PermissionError('selector does not bind disclosed IDs')
    if act.verb in OS_WINDOWS:
        os_ids = {w['os_id'] for w in selected}
        selected = [w for w in snapshot if w['os_id'] in os_ids]
    # Secondary destination/source selectors must be independently audited, never ignored.
    if p.get('target_tab') or p.get('source_window') or p.get('next_to'):
        raise PermissionError('compound target requires a trusted adapter')
    return selected
