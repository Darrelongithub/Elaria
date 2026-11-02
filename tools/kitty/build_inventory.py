"""Build-time only: extract pinned kitty option/protocol declarations without importing kitty."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import shlex
from pathlib import Path

VERSION = '0.47.1'


class Extract:
    def __init__(self, root):
        self.root = root
        self.env = {}
        self.functions = {}

    def value(self, node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Tuple, ast.List)):
            return [self.value(x) for x in node.elts]
        if isinstance(node, ast.Name):
            return self.env[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self.value(node.left) + self.value(node.right)
        if isinstance(node, ast.JoinedStr):
            return ''.join(str(self.value(n.value)) if isinstance(n, ast.FormattedValue)
                           else n.value for n in node.values)
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in self.functions:
                return self.value(self.functions[node.func.id])
            if isinstance(node.func, ast.Attribute) and node.func.attr in {'replace', 'format', 'join'}:
                return getattr(self.value(node.func.value), node.func.attr)(
                    *(self.value(n) for n in node.args))
        raise ValueError(ast.unparse(node))

    def load(self, path):
        tree = ast.parse((self.root / path).read_text())
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                try:
                    v = self.value(node.value)
                except (KeyError, ValueError, TypeError, AttributeError):
                    continue
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.env[target.id] = v
            if isinstance(node, ast.FunctionDef):
                returns = [n.value for n in node.body if isinstance(n, ast.Return)]
                if len(returns) == 1:
                    self.functions[node.name] = returns[0]
        return tree


def options(text):
    entries = []
    for match in re.finditer(r'^--[^\n]+\n[\s\S]*?(?=^--|\Z)', text, re.MULTILINE):
        lines = match.group().strip().splitlines()
        flags = re.findall(r'(?<!\w)-{1,2}[\w-]+', lines[0])
        props, prose = {}, []
        for line in lines[1:]:
            m = re.fullmatch(r'(type|default|choices|dest|completion|condition)=(.*)', line.strip())
            if m:
                props[m[1]] = m[2]
            else:
                prose.append(line)
        typ = props.get('type', 'choices' if 'choices' in props else 'str')
        default = props.get('default')
        if typ.startswith('bool-'):
            default = typ == 'bool-reset' if default is None else default.lower() in {'true', 'yes', 'y'}
        elif typ == 'list':
            default = shlex.split(default) if default else []
        elif typ in {'int', 'float', 'count'}:
            default = (float if typ == 'float' else int)(default or 0)
        elif default is None:
            default = props['choices'].split(',')[0] if 'choices' in props else ''
        entries.append({'flags': flags, 'type': typ, 'default': default,
                        'declared_default': props.get('default'),
                        'hazards': option_hazards(flags),
                        'choices': props.get('choices', '').split(',') if 'choices' in props else [],
                        'metadata': props, 'semantics': '\n'.join(prose).strip()})
    return entries


def build(root):
    ex = Extract(root)
    for path in ['kitty/constants.py', 'kitty/rc/base.py', 'kitty/launch.py', 'kitty/options/utils.py']:
        ex.load(path)
    base = ast.parse((root / 'kitty/rc/base.py').read_text())
    image = next(n.value.args[0].value for n in base.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'ImageCompletion' for t in n.targets))
    ex.env['SUPPORTED_IMAGE_FORMATS'] = [x.upper() for x in image.split('ext:')[1].split(',') if x != 'jpg']
    ex.functions['launch_options_spec'] = ex.functions['options_spec']
    result = {}
    k1 = {'ls', 'get-text', 'get-colors', 'scroll-window'}
    k3 = {'action', 'env', 'kitten', 'load-config', 'send-key', 'send-text', 'signal-child',
          'set-background-image', 'set-window-logo'}
    for p in sorted((root / 'kitty/rc').glob('*.py')):
        if p.stem in {'base', '__init__'}:
            continue
        tree = ex.load(str(p.relative_to(root)))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and any(ast.unparse(b) == 'RemoteCommand' for b in n.bases))
        fields = {}
        arg_source = ''
        for node in cls.body:
            if isinstance(node, ast.Assign):
                names = [n.id for n in node.targets if isinstance(n, ast.Name)]
                if 'args' in names:
                    arg_source = ast.unparse(node.value)
                if any(n in names for n in ['protocol_spec', 'options_spec', 'short_desc', 'desc',
                                            'is_asynchronous', 'reads_streaming_data', 'disallow_responses']):
                    try:
                        value = ex.value(node.value)
                    except Exception as exc:
                        raise ValueError(f'{p.name}: {names}: {ast.unparse(node.value)}') from exc
                    fields.update(dict.fromkeys(names, value))
                    ex.env.update(dict.fromkeys(names, value))
        verb = p.stem.replace('_', '-')
        payload = []
        for line in fields.get('protocol_spec', '').splitlines():
            m = re.match(r'\s*([\w]+)(\+)?/([^:]+):\s*(.*)', line)
            if m:
                payload.append({'name': m[1], 'required': bool(m[2]), 'type': m[3], 'semantics': m[4]})
        hazards = ['target-default-may-be-active', 'effects-require-verification']
        if verb in {'send-key', 'send-text'}:
            hazards += ['silent-success', 'arbitrary-input', 'broadcast', 'his-window-K3']
        if verb == 'send-text':
            hazards += ['python-escape-cli', 'newline-execution', 'bracketed-paste-not-a-guarantee']
        if verb in {'close-window', 'close-tab', 'signal-child'}:
            hazards += ['target-blind', 'his-window-K3', 'destructive-K3']
        if verb in {'launch', 'new-window'}:
            hazards += ['arbitrary-process', 'focus-steal', 'never-grant-rc', 'stamp-required']
        if verb == 'run':
            hazards += ['silent', 'arbitrary-process', 'irreversible-effects-K3']
        if verb in {'action', 'kitten', 'load-config', 'env'}:
            hazards += ['arbitrary-effects', 'credential-access-K3']
        if verb in k1:
            hazards += ['screen-or-environment-may-contain-secrets']
        spec = fields.get('options_spec', '') or ''
        result[verb] = {'tier': 'K1' if verb in k1 else 'K3' if verb in k3 else 'K2',
                        'summary': fields.get('short_desc', ''), 'semantics': fields.get('desc', ''),
                        'options': options(spec), 'option_spec': spec, 'argument_spec_source': arg_source,
                        'payload': payload, 'protocol_spec': fields.get('protocol_spec', ''),
                        'async': fields.get('is_asynchronous', False),
                        'stream': fields.get('reads_streaming_data', False),
                        'no_response': fields.get('disallow_responses', False), 'hazards': hazards,
                        'source': str(p.relative_to(root)), 'source_sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    return result



def option_hazards(flags):
    result = []
    for flag in flags:
        if any(x in flag for x in ('match', 'all', 'self')):
            result.append('target-expansion')
        if any(x in flag for x in ('password', 'env', 'stdin', 'cwd', 'watcher', 'config', 'source')):
            result.append('sensitive-input-or-code')
        if 'remote-control' in flag:
            result.append('never-grant-rc')
        if 'response' in flag:
            result.append('response-is-not-effect-proof')
    return sorted(set(result))


def config_options(root, relative, wanted=None):
    result = {}
    ex = Extract(root)
    tree = ex.load(relative)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == 'opt' and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant)):
            continue
        name = ast.literal_eval(node.args[0]).lstrip('+')
        if wanted and name not in wanted:
            continue
        try:
            default = ast.literal_eval(node.args[1])
        except ValueError:
            default = {'source_expression': ast.unparse(node.args[1])}
        text = next((ex.value(k.value) for k in node.keywords if k.arg == 'long_text'), '')
        result[name] = {'default': default, 'semantics': text, 'source': relative}
    return result


def rings(root, verbs):
    kittens = {}
    purposes = {
        'ask': 'Interactive questions and dialogs', 'broadcast': 'Type into multiple windows',
        'choose_files': 'Graphical file chooser', 'choose_fonts': 'Choose and preview fonts',
        'clipboard': 'Read or write the system clipboard', 'command_palette': 'Search kitty actions',
        'desktop_ui': 'Desktop integration user interfaces', 'diff': 'Side-by-side file/directory diff',
        'dnd': 'Drag and drop terminal files', 'hints': 'Keyboard selection of text, URLs and paths',
        'hyperlinked_grep': 'Run ripgrep and hyperlink paths', 'icat': 'Display images in a terminal',
        'notify': 'Desktop notifications', 'pager': 'Terminal pager', 'panel': 'Desktop panel',
        'query_terminal': 'Query terminal capabilities', 'quick_access_terminal': 'Drop-down terminal',
        'remote_file': 'Download/open/edit remote SSH files; edit saves upload changes',
        'resize_window': 'Interactively resize kitty windows', 'show_key': 'Inspect keyboard events',
        'ssh': 'OpenSSH wrapper with remote terminfo, bootstrap and shell integration',
        'themes': 'Preview/apply color themes', 'transfer': 'TTY file transfer; recursive and incremental',
        'unicode_input': 'Choose Unicode characters',
    }
    for path in sorted((root / 'kittens').glob('*/main.py')):
        name = path.parent.name
        ex = Extract(root)
        ex.load(str(path.relative_to(root)))
        spec = ''
        if 'option_text' in ex.functions:
            try:
                spec = ex.value(ex.functions['option_text'])
            except (ValueError, KeyError, TypeError):
                spec = ''  # full-option requirement is asserted below for the three required kittens
        kittens[name] = {'purpose': purposes[name], 'source': str(path.relative_to(root)),
                         'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'options': options(spec), 'option_spec': spec,
                         'invocation': 'kitty +kitten ' + name,
                         'hazards': ['acts-inherit-K-tier', 'external-effects-may-require-K3']}
    for name, purpose in {
        'mouse-demo': 'Demonstrate terminal mouse reporting',
        'edit-in-kitty': 'Open files in kitty editor windows',
        'run-shell': 'Run a shell with integration (legacy T3 hold still applies)',
        'update-self': 'Update standalone kitten (not a substitute for Fedora dnf)',
    }.items():
        kittens[name] = {'purpose': purpose, 'source': 'tools/cmd/tool/main.go',
                         'invocation': 'kitten ' + name, 'options': [],
                         'hazards': ['acts-inherit-K-tier']}
    kittens['ssh']['options_scope'] = 'These are ssh.conf copy-directive options, NOT top-level SSH flags.'
    kittens['ssh']['config'] = config_options(root, 'kittens/ssh/main.py')
    tree = ast.parse((root / 'kittens/ssh/utils.py').read_text())
    fallback = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                    if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
    kittens['ssh']['passthrough_flags'] = fallback
    kittens['ssh']['passthrough_semantics'] = (
        'Invocation is identical to installed OpenSSH. Kitty discovers its flags from ssh usage; '
        'this pinned fallback is NOT proof of the owner OpenSSH option set or defaults. '
        '--kitten option=value overrides ssh.conf; all config keys and copy options are included. '
        'Collect ssh -V and the installed ssh(1)/ssh_config(5) at the owner gate.')
    assert all(kittens[k]['options'] for k in ('ssh', 'transfer', 'remote_file'))
    tree = ast.parse((root / 'kitty/remote_control.py').read_text())
    glob = next(n.value.args[0].value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'global_options_spec' for t in n.targets))
    return {
        'schema_version': 1, 'upstream_version': VERSION,
        'upstream_commit': 'fb5255b1ae4f0249ba832d6a773348fd103449ce',
        'researched_on': '2026-11-02', 'owner_rpm_ruling': '0.47.1-1.fc44',
        'owner_version_verbatim': None, 'owner_drift_reconciled': False,
        'source_url': 'https://github.com/kovidgoyal/kitty/tree/v0.47.1',
        'license': 'Upstream option/protocol prose: GPL-3.0, Kovid Goyal; see COPYING.kitty',
        'unknown_verb_tier': 'K3',
        'classification_note': 'Minimum tiers only; attribution/effect can escalate any act. K tiers never override legacy T3.',
        'global_options': options(glob),
        'common_options_note': '--help is generated by the CLI; other command-local options are extracted verbatim.',
        'verbs': verbs, 'kittens': kittens,
        'packaging_status': 'Upstream bundled inventory; exact Fedora file membership and package split await owner rpm evidence.',
        'config': config_options(root, 'kitty/options/definition.py', {
            'allow_remote_control', 'remote_control_password', 'listen_on', 'paste_actions', 'enabled_layouts'}),
        'errata': [
            'set-os-window-title is not a v0.47.1 RC verb; launch has --os-window-title for initial titles.',
            'listen_on prose omits password from allowed modes, but boss.py explicitly permits password.',
            'Hyprland v0.57.0 uses Lua, not the clause windowrulev2 spelling.',
            'Bracketed paste is application-controlled, not proof of non-execution.',
            'send-key declares exclude_active but its handler does not enforce it; bridge must exclude IDs itself.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    verbs = build(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    inventory = rings(args.source, verbs)
    args.output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n')
    print(f'{len(verbs)} remote-control verbs extracted')


if __name__ == '__main__':
    main()
