#!/usr/bin/env python3
"""Render the offline human reference from the pinned machine inventory."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def render(data):
    lines = [
        '# Kitty inventory — build research 2026-11-02', '',
        '**Status: source-researched / TESTED-ONLY; not owner-version or Fedora-membership verified.**', '',
        'Upstream v0.47.1, commit `fb5255b1ae4f0249ba832d6a773348fd103449ce`.',
        'Owner ruling: `0.47.1-1.fc44`; actual `kitten --version`: **NOT RECEIVED**.',
        'Do not substitute this version claim for verbatim owner output. No live kitty was run.', '',
        'Authority: owner 2026-11-02 sequencing-only addendum > builder v1.1 > KITTY-CLAUSE v2.',
        'Clause SHA256: `8be8a4a94e958e1fd0323d8e687418f73e6cfd407a5a08bb6720b75769ffb6bc` (unchanged).',
        'PR23, console cherry-pick and SC-H1 remain independent held tracks, not build prerequisites.',
        'Lane placement is accepted in place by the 2026-11-02 design checkpoint ruling, NOT by the earlier sequencing-only A. See `docs/design/kitty-2026-11-02-checkpoint-ruling.md`.', '',
        '## Scope and trust', '',
        '- Ring 1 contains all 39 upstream `kitty/rc` commands, including deprecated `new-window`.',
        '- Ring 2 enumerates upstream bundled kittens and companion tools; Fedora package membership still needs `rpm -ql` evidence.',
        '- Ring 3 includes the five requested configuration entries, packaging limits and Hyprland version findings.',
        '- Every tier below is a **minimum**, not a task whitelist. Unknown verbs default K3.',
        '- Close HER journaled IDs is K2; close HIS or mixed tabs is K3. Reversible typing in HER windows can be K2; HIS input is K3.',
        '- Any irreversible/credential/unknown effect escalates K3. Existing T3 holds still refuse: a K3 Yes never overrides them.',
        '- SSH options depend on the installed OpenSSH binary. The pinned fallback flags and complete kitty-specific ssh.conf/copy surface are included; installed SSH help/man reconciliation is still open.',
        '- Defaults are the command-line defaults; an absent Python string default is None but generated Go CLI uses an empty string. `declared_default` retains explicit source metadata.',
        '- `send-key` on 0.47.1 carries `K3-send-key-exclude-active-unenforced-0.47.1` at verb and option level. Broadcast exclusion is untrustworthy even when `exclude_active=true`; a snapshot cannot make it atomic.',
        '- CLI fields are not wire fields. Protocol specs and options are separately recorded. Raw source expressions are retained rather than guessed.', '',
        '## Primary sources and appendix cross-check', '',
        '- [kitty pinned source](https://github.com/kovidgoyal/kitty/tree/v0.47.1): `kitty/rc/*.py`, `kitty/launch.py`, `kitty/simple_cli_definitions.py`, `gen/go_code.py`, `tools/cli/help.go`, `kittens/*`.',
        '- [Protocol](https://github.com/kovidgoyal/kitty/blob/v0.47.1/docs/rc_protocol.rst): DCS JSON, X25519/SHA256/AES-256-GCM, base85, async and streaming.',
        '- [Password enforcement](https://github.com/kovidgoyal/kitty/blob/v0.47.1/kitty/boss.py): password mode works over sockets; socket/socket-only bypass socket password checks.',
        '- [Hyprland v0.57.0](https://github.com/hyprwm/Hyprland/tree/v0.57.0), commit `0aa6745f705f2c4b0a5004eb019ef76e5bbdb426`: Lua ConfigManager, example/hyprland.lua, Rule.cpp, WindowRuleEffectContainer.cpp and LuaBindingsConfigRules.cpp confirm the replacement rule in setup.',
        '- [RA-15](https://github.com/jantman/robot-army/issues/125), [mcp-radar 107](https://github.com/Danyw24/mcp-radar/issues/107), [compass 88](https://github.com/tuna-os/compass/issues/88): read at build time; corroborate predictable /tmp paths, symlink and cross-UID hazards. These are reports, not owner-machine measurements.',
        '- [dotfiles PR6](https://github.com/snaraj/dotfiles/pull/6): reviewed as third-party application/paste evidence, not transferable proof for this owner or pinned kitty.',
        '- Clause discussion 5320 was not retrievable via the issues API (404; discussion endpoint is distinct). No claim it is absent.',
        '- Fedora package pages, external man mirrors, forums and agent-CLI comparison pages were outside this sandbox internet allowlist. Their claims were NOT independently re-verified; pinned upstream implementation takes precedence for implementation facts.', '',
        '### Build-time errata (the Drive clause is NOT rewritten)', '',
    ]
    lines += ['- ' + text for text in data['errata']]
    lines += ['', '## Ring 1 — every remote-control verb', '', '| Verb | Minimum | Purpose |', '|---|---|---|']
    lines += [f'| `{name}` | {entry["tier"]} | {entry["summary"]} |' for name, entry in data['verbs'].items()]

    def opts(options):
        if not options:
            lines.append('No command-local flags declared (framework help still applies).')
        for option in options:
            lines.extend(['', '##### ' + ', '.join('`' + f + '`' for f in option['flags']), '',
                          (f'Type: `{option["type"]}`; CLI default: `{json.dumps(option["default"])}`; '
                          f'explicit source default: `{json.dumps(option["declared_default"])}`.'),
                          'Choices: ' + (', '.join(option['choices']) or 'not enumerated') + '.',
                          'Option hazards: ' + (', '.join(option['hazards']) or 'inherits act hazards') + '.', '',
                          option['semantics'], ''])

    lines.extend(['', '### Global CLI flags (inherited by every RC command)', ''])
    opts(data['global_options'])
    lines += ['', data['common_options_note'], '']
    for name, entry in data['verbs'].items():
        lines.extend(['', f'### `{name}` — {entry["tier"]}', '', entry['semantics'] or entry['summary'], '',
                      'Hazards: ' + ', '.join(entry['hazards']) + '.',
                      f'Async: {entry["async"]}; streaming: {entry["stream"]}; no-response declaration: {entry["no_response"]}.',
                      'Argument declaration: `' + entry['argument_spec_source'] + '`.',
                      f'Source: `{entry["source"]}`, SHA256 `{entry["source_sha256"]}`.', '',
                      '#### Wire payload (upstream declaration)', '', '```text', entry['protocol_spec'].strip(), '```', '',
                      '#### Complete declared CLI options'])
        opts(entry['options'])
    lines += ['', '## Ring 2 — bundled kittens and companion tools', '',
              'Upstream membership only. `tools/cmd/tool/main.go` provides compiled entry points; Python-only kittens use `kitty +kitten NAME`.', '',
              '| Name | Purpose | Source |', '|---|---|---|']
    lines += [f'| `{name}` | {e["purpose"]} | `{e["source"]}` |' for name, e in data['kittens'].items()]
    for name in ('ssh', 'transfer', 'remote_file'):
        entry = data['kittens'][name]
        lines.extend(['', '### ' + name, '', entry['purpose'], '', entry.get('options_scope', ''), ''])
        opts(entry['options'])
        if name == 'ssh':
            lines += ['', entry['passthrough_semantics'], '',
                      '| OpenSSH fallback flag | Argument |', '|---|---|']
            lines += [f'| `-{k}` | `{v}` |' for k, v in entry['passthrough_flags'].items()]
            lines += ['', '#### Kitty SSH configuration (`--kitten option=value` / ssh.conf)', '']
            for key, setting in entry['config'].items():
                lines += ['##### ' + key, '', 'Default: `' + json.dumps(setting['default']) + '`.', '', setting['semantics'], '']
    lines += ['', '## Ring 3 — kitty.conf / Fedora / Hyprland', '']
    for key, setting in data['config'].items():
        lines += ['### ' + key, '', 'Upstream default: `' + json.dumps(setting['default']) + '`.', '', setting['semantics'], '']
    lines += [
        '### Packaging and upgrade gate', '',
        'The owner design record identifies Fedora 44 updates `0.47.1-1.fc44`, base `0.43.1`, and packages `kitty`, `kitty-kitten`, `kitty-shell-integration`, `kitty-terminfo`. These are **ruling-supplied facts**, not installed-package measurements here.',
        'Owner collects `rpm -q kitty kitty-kitten kitty-shell-integration kitty-terminfo`, package file lists, `kitten --version`, and `ssh -V`. Never use `kitten update-self` to bypass RPM-managed upgrades.',
        'Run `tools/kitty/drift.py` after **every dnf kitty upgrade**, then manually reconcile command/options/defaults, semantic changes, Fedora membership and OpenSSH delegation before calling this lane done.', '',
        '### Hyprland focus interop', '',
        'See `docs/kitty-setup.md`: v0.57.0 uses `hl.window_rule`, `initial_title`, `no_initial_focus`. The legacy windowrulev2 spelling is historical, not the install instruction for 0.57. `stay_focused` pins an existing surface and is not interchangeable with no-initial-focus. Audit broad stay-focused rules; do not install one on HER windows.', '',
        '### License and reproduction', '',
        'Upstream option/protocol/config prose is GPL-3.0, copyright Kovid Goyal and contributors. `src/assistant/hands/kitty/data/COPYING.kitty` accompanies the extracted text.',
        'Build scripts parse Python AST and literal option declarations only; they do not import or execute upstream kitty. Download v0.47.1 source, run `tools/kitty/build_inventory.py SOURCE src/assistant/hands/kitty/data/inventory.json`, then `tools/kitty/render_inventory.py`.',
    ]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    data = json.loads((ROOT / 'src/assistant/hands/kitty/data/inventory.json').read_text())
    (ROOT / 'docs/kitty-inventory.md').write_text(render(data))
