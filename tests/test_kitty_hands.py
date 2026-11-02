"""Synthetic only: encrypted AF_UNIX peer, never kitty, GPU, models or owner data."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import socket
import stat
import tempfile
import threading
from pathlib import Path

import pytest

from assistant.hands.kitty.bridge import Bridge, make_act, windows_from_ls
from assistant.hands.kitty.journal import EventJournal
from assistant.hands.kitty.policy import (
    Act,
    Assessment,
    Authorizer,
    Consent,
    canonical,
    digest,
    fingerprint,
    inventory,
    tier_for,
)
from assistant.hands.kitty.settings import load_settings
from assistant.hands.kitty.transport import (
    PREFIX,
    SUFFIX,
    Transport,
    TransportError,
    directory_fd,
    endpoint,
    read_password,
)


@pytest.fixture
def private(monkeypatch):
    # /tmp is deliberately prohibited, INCLUDING in tests of real socket acceptance.
    parent = Path(__file__).resolve().parents[1] / '.venv'
    parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='kitty-', dir=parent) as name:
        path = Path(name)
        path.chmod(0o700)
        monkeypatch.setenv('XDG_RUNTIME_DIR', str(path))
        yield path


class FakeKitty:
    def __init__(self):
        self.windows = [{'id': 1, 'pid': 101, 'cmdline': ['/usr/bin/cat'], 'title': 'HIS',
                         'is_active': False, 'foreground_processes': [], 'created_at': 1}]
        self.text = {1: ''}
        self.calls = []
        self.lie = False
        self.fail = False

    def request(self, verb, payload, tier, **kwargs):
        self.calls.append((verb, json.loads(canonical(payload)), tier))
        if self.fail:
            raise RuntimeError('synthetic transport failure')
        if verb == 'ls':
            return json.dumps([{'id': 10, 'tabs': [{'id': 20, 'windows': self.windows}]}])
        if verb == 'get-text':
            return self.text[int(payload['match'].split(':')[1])]
        if verb == 'send-text' and not self.lie:
            for match in payload['match'].split(' or '):
                self.text[int(match.split(':')[1])] += payload['data'][5:]
        if verb == 'launch':
            self.windows.append({'id': 2, 'pid': 102, 'cmdline': payload['args'],
                                 'title': payload['window_title'], 'is_active': False,
                                 'foreground_processes': [], 'created_at': 2})
            self.text[2] = ''
            return '2'
        if verb == 'close-window':
            ident = int(payload['match'].split(':')[1])
            self.windows = [w for w in self.windows if w['id'] != ident]
        return None


def checker(tier=1, nature='reversible', bp=False):
    return lambda *_: Assessment(tier, nature, bracketed_paste=bp)


def grant(bridge, act, plan, targets, *, newline=False, ack=True, answer='yes'):
    consent = Consent(secrets.token_hex(12), plan.digest, fingerprint(targets), digest(act.payload),
                      newline, ack)
    bridge.authorizer.decide(consent, owner_answer=answer)
    return consent


def prepared_send(text='synthetic text', *, tier=1, bp=False):
    fake, events = FakeKitty(), []
    bridge = Bridge(fake, checker(tier, bp=bp), events.append)
    act = make_act('send-text', {'data': 'text:' + text}, (1,))
    plan = act.plan(tier)
    targets = bridge.inspect(act, plan)
    return bridge, fake, events, act, plan, targets


def test_inventory_all_39_are_explicit_and_unknown_is_k3():
    data = inventory()
    assert len(data['verbs']) == 39
    assert data['owner_version_verbatim'] is None
    assert data['unknown_verb_tier'] == 'K3'
    for verb, entry in data['verbs'].items():
        assert entry['tier'] in {'K1', 'K2', 'K3'}
        assert entry['hazards'] and entry['source_sha256']
        assert entry['source'].endswith(verb.replace('-', '_') + '.py')
        assert len({p['name'] for p in entry['payload']}) == len(entry['payload'])
    act = Act('future-verb', '{}')
    assert tier_for(act, Assessment(1, 'reversible'), [], set(), data) == 'K3'


@pytest.mark.parametrize('verb', ['ls', 'get-text', 'get-colors', 'scroll-window'])
def test_read_tiers_and_credential_escalation(verb):
    act = Act(verb, '{}')
    assert tier_for(act, Assessment(0, 'observational'), [], set(), inventory()) == 'K1'
    assert tier_for(act, Assessment(3, 'credential-access'), [], set(), inventory()) == 'K3'


def test_schema():
    jsonschema = pytest.importorskip('jsonschema')
    root = Path(__file__).resolve().parents[1] / 'src/assistant/hands/kitty/data'
    jsonschema.validate(inventory(), json.loads((root / 'inventory.schema.json').read_text()))


def test_typed_defaults_and_danger_flags():
    data = inventory()
    opts = {o['flags'][0]: o for o in data['verbs']['launch']['options']}
    assert opts['--keep-focus']['default'] is False
    assert opts['--allow-remote-control']['default'] is False
    assert 'never-grant-rc' in opts['--allow-remote-control']['hazards']
    assert opts['--env']['default'] == []
    text = {o['flags'][0]: o for o in data['verbs']['send-text']['options']}
    assert text['--bracketed-paste']['default'] == 'disable'
    assert {'ssh', 'transfer', 'remote_file'} <= data['kittens'].keys()
    assert all(data['kittens'][k]['options'] for k in ('ssh', 'transfer', 'remote_file'))


def test_no_consent_is_not_session_consent():
    bridge, fake, _, act, plan, _ = prepared_send()
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert 'send-text' not in [c[0] for c in fake.calls]


def test_per_act_consent_target_text_and_complete_journal():
    bridge, fake, events, act, plan, targets = prepared_send()
    ref = grant(bridge, act, plan, targets).ref
    result = bridge.execute(act, plan)
    assert result['verification'] == 'text-delta-observed-not-execution-proof'
    send = next(c for c in fake.calls if c[0] == 'send-text')
    assert send[1]['bracketed_paste'] == 'auto'
    assert send[1]['data'] == 'text:synthetic text'
    assert send[2] == 'K3'
    assert all({'verb', 'tier', 'target', 'plan_hash', 'consent_ref', 'timestamp', 'verification'} <= e.keys()
               for e in events)
    assert all(e['kind'] == 'kitty.act' for e in events)
    results = [e for e in events if e['verb'] == 'send-text']
    assert results[-1]['consent_ref'] == ref
    assert results[-1]['target'][0]['cmdline']['sha256'] == digest(['/usr/bin/cat'])
    assert 'synthetic text' not in json.dumps(events)
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert len([c for c in fake.calls if c[0] == 'send-text']) == 1


@pytest.mark.parametrize('text', ['echo synthetic\n', 'first\nsecond', 'x\r', '\x1b[201~x'])
def test_execution_characters_need_exact_per_act_ack(text):
    bridge, fake, _, act, plan, targets = prepared_send(text)
    grant(bridge, act, plan, targets, newline=False)
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert 'send-text' not in [c[0] for c in fake.calls]
    grant(bridge, act, plan, targets, newline=True)
    bridge.execute(act, plan)
    assert next(c[1]['data'] for c in fake.calls if c[0] == 'send-text') == 'text:' + text


def test_unknown_program_requires_ack():
    bridge, fake, _, act, plan, targets = prepared_send()
    grant(bridge, act, plan, targets, ack=False)
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert 'send-text' not in [c[0] for c in fake.calls]


def test_observed_bracketed_paste_allows_no_program_ack():
    bridge, _, _, act, plan, targets = prepared_send(bp=True)
    grant(bridge, act, plan, targets, ack=False)
    assert 'text-delta' in bridge.execute(act, plan)['verification']


@pytest.mark.parametrize('change', ['pid', 'cmdline', 'foreground_processes', 'created_at'])
def test_target_identity_changes_stale_consent(change):
    bridge, fake, _, act, plan, targets = prepared_send()
    grant(bridge, act, plan, targets)
    fake.windows[0][change] = {'pid': 999, 'cmdline': ['/usr/bin/vim'],
                               'foreground_processes': [{'pid': 999, 'cmdline': ['vim']}],
                               'created_at': 999}[change]
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert 'send-text' not in [c[0] for c in fake.calls]


def test_no_is_terminal_even_after_yes_attempt():
    bridge, fake, _, act, plan, targets = prepared_send()
    grant(bridge, act, plan, targets, answer='no')
    with pytest.raises(PermissionError):
        grant(bridge, act, plan, targets)
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert 'send-text' not in [c[0] for c in fake.calls]


@pytest.mark.parametrize('legacy', [3, None])
def test_legacy_forbidden_and_both_missing_are_not_k3_overrides(legacy):
    fake, events = FakeKitty(), []
    bridge = Bridge(fake, checker(legacy), events.append)
    act = make_act('send-text', {'data': 'text:synthetic'}, (1,))
    plan = act.plan(legacy)
    grant(bridge, act, plan, [])
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert fake.calls == []


def test_two_mismatches_halt_and_t2_still_requires_yes():
    a = Authorizer(checker(2))
    act = Act('ls', '{}')
    plan = act.plan(1)
    _, first = a.assess(act, plan, 'plan', [])
    assert first.ask
    with pytest.raises(PermissionError):
        a.assess(act, plan, 'pre-exec', [])
    b = Authorizer(checker(2))
    act = Act('focus-window', canonical({'match': 'id:1'}), (1,))
    plan = act.plan(2)
    assessment, verdict = b.assess(act, plan, 'plan', [])
    b.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    with pytest.raises(PermissionError):
        b.authorize(act, plan, 'K2', assessment, verdict, [])


def test_lying_success_and_preexisting_text_are_not_verified():
    for lie in (True, False):
        bridge, fake, _, act, plan, targets = prepared_send()
        fake.lie = lie
        if not lie:
            fake.text[1] = 'synthetic text'
        grant(bridge, act, plan, targets)
        assert bridge.execute(act, plan)['verification'] == 'unverified'


def test_launch_invariants_session_and_her_only_close():
    fake, events = FakeKitty(), []
    bridge = Bridge(fake, checker(), events.append)
    act = make_act('launch', {'args': ['/usr/bin/cat'], 'allow_remote_control': True})
    plan = act.plan(1)
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    assert bridge.execute(act, plan)['verification'] == 'created-id-and-stamp-observed'
    sent = next(c[1] for c in fake.calls if c[0] == 'launch')
    assert sent['keep_focus'] is True and sent['window_title'].startswith('[ELARIA ')
    assert 'allow_remote_control' not in sent
    close = Act('close-window', canonical({'match': 'id:2'}), (2,))
    assert bridge.execute(close, close.plan(1))['verification'] == 'target-absence-observed'
    his = Act('close-window', canonical({'match': 'id:1'}), (1,))
    with pytest.raises(RuntimeError):
        bridge.execute(his, his.plan(1))


@pytest.mark.parametrize('payload', [{'keep_focus': False}, {'window_title': 'NOT ELARIA'},
                                    {'allow_remote_control': True}, {'remote_control_password': [secrets.token_urlsafe(24)]}])
def test_malicious_launch_bypassing_helper_refused(payload):
    fake = FakeKitty()
    bridge = Bridge(fake, checker(), lambda _: None)
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    good = make_act('launch', {'args': ['/usr/bin/cat']}).payload | payload
    act = Act('launch', canonical(good))
    with pytest.raises(RuntimeError):
        bridge.execute(act, act.plan(1))
    assert 'launch' not in [c[0] for c in fake.calls]


def test_broadcast_requires_exclusion_and_no_active_ids():
    bridge, fake, _, _, _, _ = prepared_send()
    fake.windows.append(dict(fake.windows[0], id=2, pid=102, is_active=True))
    fake.text[2] = ''
    act = make_act('send-text', {'data': 'text:synthetic'}, (1, 2))
    assert act.payload['exclude_active'] is True
    with pytest.raises(RuntimeError):
        bridge.execute(act, act.plan(1))
    assert 'send-text' not in [c[0] for c in fake.calls]


def test_close_tab_includes_unowned_children():
    fake = FakeKitty()
    bridge = Bridge(fake, checker(), lambda _: None)
    fake.windows.append(dict(fake.windows[0], id=2, pid=102))
    snapshot = windows_from_ls(fake.request('ls', {}, 'K1'))
    bridge.owned.add(fingerprint([snapshot[0]]))
    act = Act('close-tab', canonical({'match': 'id:20'}), (1,))
    targets = bridge.targets(act, snapshot)
    assert len(targets) == 2
    assert tier_for(act, Assessment(1, 'reversible'), targets, bridge.owned, bridge.catalogue) == 'K3'


def test_journal_failure_before_send_prevents_dispatch():
    bridge, fake, _, act, plan, targets = prepared_send()
    grant(bridge, act, plan, targets)
    def broken(event):
        if event['verb'] == 'send-text':
            raise OSError('synthetic disk full')
    bridge.journal = broken
    with pytest.raises(OSError):
        bridge.execute(act, plan)
    assert 'send-text' not in [c[0] for c in fake.calls]


def test_real_private_journal(private):
    journal = EventJournal(private / 'events.jsonl')
    event = {'kind': 'kitty.act', 'verification': 'pending', 'value': 'a\nb'}
    journal(event)
    assert stat.S_IMODE(journal.path.stat().st_mode) == 0o600
    lines = journal.path.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0]) == event


@pytest.mark.parametrize('mode', [0o644, 0o660, 0o400, 0o777])
def test_password_file_mode_rejected(private, mode):
    path = private / 'pw'
    path.write_text(secrets.token_urlsafe(36))
    path.chmod(mode)
    with pytest.raises(PermissionError):
        read_password(path)


def test_secret_file_symlink_hardlink_and_fifo_rejected(private):
    path = private / 'pw'
    path.write_text(secrets.token_urlsafe(36))
    path.chmod(0o600)
    assert read_password(path)
    link = private / 'sym'
    link.symlink_to(path)
    with pytest.raises(OSError):
        read_password(link)
    os.link(path, private / 'hard')
    with pytest.raises(PermissionError):
        read_password(path)
    fifo = private / 'fifo'
    os.mkfifo(fifo, 0o600)
    with pytest.raises(PermissionError):
        read_password(fifo)


def test_socket_rejection_classes(private, monkeypatch):
    path = private / 'rc.sock'
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        with endpoint(path, private):
            pass
        private.chmod(0o755)
        with pytest.raises(PermissionError), endpoint(path, private):
            pass
        private.chmod(0o700)
        link = private / 'link'
        link.symlink_to(path)
        with pytest.raises(PermissionError), endpoint(link, private):
            pass
        regular = private / 'regular'
        regular.touch()
        with pytest.raises(PermissionError), endpoint(regular, private):
            pass
        with pytest.raises(PermissionError), endpoint(path, private.parent):
            pass
        monkeypatch.setattr(os, 'getuid', lambda: 123456)
        with pytest.raises(PermissionError), endpoint(path, private):
            pass


@pytest.mark.parametrize('path', ['/tmp/forbidden', '/tmp', '/var/../tmp', 'relative'])
def test_no_tmp_or_nonliteral_runtime(path):
    with pytest.raises(PermissionError), directory_fd(Path(path)):
        pass


def test_world_writable_and_symlink_ancestors(private):
    bad = private / 'bad'
    bad.mkdir(mode=0o777)
    bad.chmod(0o777)
    with pytest.raises(PermissionError), directory_fd(bad):
        pass
    good = private / 'good'
    good.mkdir(mode=0o700)
    link = private / 'symlink'
    link.symlink_to(good)
    with pytest.raises(PermissionError), directory_fd(link):
        pass


def test_settings_have_no_auto_open_or_inline_secret(private):
    path = private / 'bridge.toml'
    text = f'socket="{private}/rc.sock"\njournal="{private}/events"\n'
    tail = '[password_files]\n' + '\n'.join(f'{k}="{private}/{k}"' for k in ('K1', 'K2', 'K3'))
    path.write_text(text + tail)
    path.chmod(0o600)
    assert load_settings(path).timeout_seconds == 5
    path.write_text(text + 'hand_open=true\n' + tail)
    with pytest.raises(ValueError):
        load_settings(path)


def test_encrypted_json_socket_and_preflight_every_connect(private):
    pytest.importorskip('cryptography')
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = X25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    secret = secrets.token_urlsafe(36)
    paths = {}
    for tier in ('K1', 'K2', 'K3'):
        paths[tier] = private / tier
        paths[tier].write_text(secret)
        paths[tier].chmod(0o600)
    path = private / 'rc.sock'
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    listener.listen(1)
    listener.settimeout(3)
    checked, errors = [], []

    def peer():
        try:
            conn, _ = listener.accept()
            with conn:
                data = b''
                while not data.endswith(SUFFIX):
                    data += conn.recv(65536)
                assert secret.encode() not in data
                envelope = json.loads(data[len(PREFIX):-len(SUFFIX)])
                shared = key.exchange(X25519PublicKey.from_public_bytes(base64.b85decode(envelope['pubkey'])))
                plain = AESGCM(hashlib.sha256(shared).digest()).decrypt(base64.b85decode(envelope['iv']),
                    base64.b85decode(envelope['encrypted']) + base64.b85decode(envelope['tag']), None)
                cmd = json.loads(plain)
                assert cmd.pop('password') == secret
                assert type(cmd.pop('timestamp')) is int
                checked.append(cmd)
                conn.sendall(PREFIX + b'{"ok":true,"data":"[]"}' + SUFFIX)
        except Exception as exc:
            errors.append(type(exc).__name__)  # no secret-bearing exception messages

    thread = threading.Thread(target=peer)
    thread.start()
    transport = Transport(path, private, paths, '1:' + base64.b85encode(public).decode())
    try:
        assert transport.request('ls', {}, 'K1') == '[]'
        thread.join(4)
        assert not thread.is_alive() and not errors
        assert checked[0]['cmd'] == 'ls' and checked[0]['version'] == [0, 47, 1]
        path.unlink()
        path.write_text('not a socket')
        with pytest.raises(TransportError) as error:
            transport.request('ls', {}, 'K1')
        assert secret not in str(error.value)
    finally:
        listener.close()
        thread.join(4)


def test_drift_parser_is_header_only_and_reports_defaults():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'tools/kitty/drift.py'
    spec = importlib.util.spec_from_file_location('kitty_drift_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.commands('Commands:\n   ls\n    List things\n   send-text\n    Text\n') == {'ls', 'send-text'}
    header = module.option_headers('  --test, -t [=yes]\n    Description mentions --not-an-option\n  --help, -h\n')
    assert header == {'--test': 'yes', '-t': 'yes', '--help': '', '-h': ''}
    entry = {'options': [{'flags': ['--test', '-t'], 'default': False, 'declared_default': None}]}
    report = module.compare_options(entry, [], header)
    assert report['defaults']['--test'] == {'pinned': 'no', 'installed': 'yes'}
    assert report['missing'] == [] and report['new'] == []


def test_wire_helper_fields_agree_with_inventory():
    data = inventory()
    for verb, payload, ids in [('launch', {'args': ['/usr/bin/cat']}, ()),
                               ('send-text', {'data': 'text:synthetic'}, (1,)),
                               ('send-key', {'keys': ['left']}, (1,)),
                               ('new-window', {'args': ['/usr/bin/cat']}, ())]:
        act = make_act(verb, payload, ids)
        assert set(act.payload) <= {field['name'] for field in data['verbs'][verb]['payload']}


def test_late_checker_escalation_needs_fresh_per_act_consent():
    bridge, fake, _, act, plan, targets = prepared_send(bp=True)
    bridge.owned.add(fingerprint(targets))
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    bridge.authorizer.checker = lambda _, phase, __: Assessment(
        1, 'irreversible' if phase == 'pre-send' else 'reversible', bracketed_paste=True)
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert 'send-text' not in [c[0] for c in fake.calls]


def test_restart_is_closed_and_no_forged_title_ownership():
    fake = FakeKitty()
    fake.windows[0]['title'] = '[ELARIA forged]'
    bridge = Bridge(fake, checker(), lambda _: None)
    assert bridge.authorizer.hand_ref is None and bridge.owned == set()
    act = Act('close-window', canonical({'match': 'id:1'}), (1,))
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    with pytest.raises(RuntimeError):
        bridge.execute(act, act.plan(1))
    bridge.authorizer.close_hand()
    assert bridge.authorizer.hand_ref is None


def test_run_is_silent_and_exit_success_not_effect_proof():
    fake, events = FakeKitty(), []
    bridge = Bridge(fake, checker(), events.append)
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    act = Act('run', canonical({'cmdline': ['/usr/bin/true'], 'data': ''}))
    result = bridge.execute(act, act.plan(1))
    assert result['verification'] == 'unverified'
    assert all(e['silent'] for e in events if e['verb'] == 'run')


def test_plan_byte_change_invalidates_approval():
    bridge, fake, _, act, plan, targets = prepared_send()
    grant(bridge, act, plan, targets)
    changed = Act(act.verb, canonical(act.payload | {'data': 'text:different'}), (1,), act.nonce)
    with pytest.raises(RuntimeError):
        bridge.execute(changed, plan)
    assert 'send-text' not in [c[0] for c in fake.calls]


def test_bridge_end_to_end_encrypted_socket(private):
    pytest.importorskip('cryptography')
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    private_key = X25519PrivateKey.generate()
    public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    passwords, paths = {}, {}
    for tier in ('K1', 'K2', 'K3'):
        passwords[tier] = secrets.token_urlsafe(36)
        paths[tier] = private / tier
        paths[tier].write_text(passwords[tier])
        paths[tier].chmod(0o600)
    address = private / 'peer.sock'
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(address))
    listener.listen(10)
    listener.settimeout(0.1)
    stopped = threading.Event()
    fake, errors, seen_tiers = FakeKitty(), [], []

    def peer():
        while not stopped.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                with conn:
                    raw = b''
                    while part := conn.recv(65536):
                        raw += part
                    for frame in raw.split(SUFFIX)[:-1]:
                        envelope = json.loads(frame[len(PREFIX):])
                        shared = private_key.exchange(X25519PublicKey.from_public_bytes(base64.b85decode(envelope['pubkey'])))
                        body = AESGCM(hashlib.sha256(shared).digest()).decrypt(base64.b85decode(envelope['iv']),
                            base64.b85decode(envelope['encrypted']) + base64.b85decode(envelope['tag']), None)
                        command = json.loads(body)
                        tier = next(t for t, password in passwords.items() if password == command['password'])
                        seen_tiers.append((command['cmd'], tier))
                        result = fake.request(command['cmd'], command['payload'], tier)
                        if not command['no_response']:
                            response = json.dumps({'ok': True, 'data': result}).encode()
                            conn.sendall(PREFIX + response + SUFFIX)
            except Exception as exc:
                errors.append(type(exc).__name__)

    thread = threading.Thread(target=peer)
    thread.start()
    events = []
    try:
        transport = Transport(address, private, paths, '1:' + base64.b85encode(public).decode())
        bridge = Bridge(transport, checker(), events.append)
        act = make_act('send-text', {'data': 'text:synthetic encrypted probe'}, (1,))
        plan = act.plan(1)
        targets = bridge.inspect(act, plan)
        grant(bridge, act, plan, targets)
        assert 'text-delta' in bridge.execute(act, plan)['verification']
        assert ('send-text', 'K3') in seen_tiers
        assert all(t == 'K1' for v, t in seen_tiers if v in {'ls', 'get-text'})
        assert all(password not in json.dumps(events) for password in passwords.values())
        assert not errors
    finally:
        stopped.set()
        thread.join(3)
        listener.close()
        assert not thread.is_alive()


def test_foreign_socket_uid_is_rejected_independently_of_parent(private, monkeypatch):
    path = private / 'owned-parent.sock'
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        original = os.lstat
        def foreign(name, *args, **kwargs):
            result = original(name, *args, **kwargs)
            if name == path.name:
                fields = list(result)
                fields[4] = os.getuid() + 1
                return os.stat_result(fields)
            return result
        monkeypatch.setattr(os, 'lstat', foreign)
        with pytest.raises(PermissionError), endpoint(path, private):
            pass


def test_both_invalid_evidence_refuses_before_any_observation():
    fake = FakeKitty()
    bridge = Bridge(fake, lambda *_: Assessment('invalid', 'unknown'), lambda _: None)
    act = Act('ls', '{}')
    with pytest.raises(RuntimeError):
        bridge.execute(act, act.plan(None))
    assert fake.calls == []


def test_generator_and_human_reference_are_deterministic():
    import importlib.util
    path = Path(__file__).resolve().parents[1] / 'tools/kitty/render_inventory.py'
    spec = importlib.util.spec_from_file_location('kitty_render_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.render(inventory()) == (path.parents[2] / 'docs/kitty-inventory.md').read_text()


@pytest.mark.parametrize('runtime', [None, '/tmp', '/different/runtime'])
def test_runtime_must_be_current_environment(private, monkeypatch, runtime):
    path = private / 'current.sock'
    with socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(path))
        if runtime is None:
            monkeypatch.delenv('XDG_RUNTIME_DIR')
        else:
            monkeypatch.setenv('XDG_RUNTIME_DIR', runtime)
        with pytest.raises(PermissionError), endpoint(path, private):
            pass


def test_adopted_send_key_hazard_is_machine_readable_at_both_levels():
    data = inventory()
    entry = data['verbs']['send-key']
    flag = 'K3-send-key-exclude-active-unenforced-0.47.1'
    assert data['upstream_version'] == '0.47.1'
    assert entry['tier'] == 'K3'
    assert flag in entry['hazards']
    option = next(o for o in entry['options'] if '--exclude-active' in o['flags'])
    assert flag in option['hazards']
    assert 'set-os-window-title' not in data['verbs']


def prepared_key_broadcast():
    fake, events = FakeKitty(), []
    fake.windows.append(dict(fake.windows[0], id=2, pid=102, created_at=2))
    bridge = Bridge(fake, checker(), events.append)
    act = make_act('send-key', {'keys': ['left']}, (1, 2))
    plan = act.plan(1)
    targets = bridge.inspect(act, plan)
    return bridge, fake, events, act, plan, targets


def test_send_key_is_k3_even_with_her_ids_and_session_hand_open():
    bridge, fake, _, act, plan, targets = prepared_key_broadcast()
    bridge.owned.update(fingerprint([w]) for w in targets)
    bridge.authorizer.open_hand(owner_phrase='kitty hand open', reference=secrets.token_hex(12))
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert 'send-key' not in [c[0] for c in fake.calls]
    grant(bridge, act, plan, targets)
    assert bridge.execute(act, plan)['verification'] == 'unverified'
    assert next(c[2] for c in fake.calls if c[0] == 'send-key') == 'K3'


@pytest.mark.parametrize('change', ['pid', 'cmdline', 'foreground_processes', 'is_active'])
def test_send_key_fresh_snapshot_blocks_changed_program_or_active_broadcast(change):
    bridge, fake, events, act, plan, targets = prepared_key_broadcast()
    grant(bridge, act, plan, targets)

    def changing(_, phase, __):
        if phase == 'pre-exec':
            fake.windows[0][change] = {
                'pid': 999, 'cmdline': ['/usr/bin/vim'],
                'foreground_processes': [{'pid': 999, 'cmdline': ['vim']}], 'is_active': True,
            }[change]
        return Assessment(1, 'reversible')

    bridge.authorizer.checker = changing
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert 'send-key' not in [c[0] for c in fake.calls]
    assert events[-1]['verification'] == 'refused'


def test_send_key_runs_pre_send_adjudication_and_denial_beats_exact_yes():
    bridge, fake, _, act, plan, targets = prepared_key_broadcast()
    grant(bridge, act, plan, targets)
    phases = []

    def deny_late(_, phase, __):
        phases.append(phase)
        return Assessment(3 if phase == 'pre-send' else 1, 'reversible')

    bridge.authorizer.checker = deny_late
    with pytest.raises(RuntimeError):
        bridge.execute(act, plan)
    assert phases == ['plan', 'pre-exec', 'pre-send']
    assert 'send-key' not in [c[0] for c in fake.calls]


def test_send_key_success_has_fresh_probe_but_not_a_false_effect_claim():
    bridge, fake, events, act, plan, targets = prepared_key_broadcast()
    grant(bridge, act, plan, targets)
    fake.calls.clear()
    phases = []

    def observe(_, phase, __):
        phases.append(phase)
        return Assessment(1, 'reversible')

    bridge.authorizer.checker = observe
    result = bridge.execute(act, plan)
    assert phases == ['plan', 'pre-exec', 'pre-send']
    assert [c[0] for c in fake.calls] == ['ls', 'ls', 'send-key', 'ls']
    assert result['verification'] == 'unverified'
    assert events[-1]['verification'] == 'unverified'
    # The flag is still supplied, but neither API success nor snapshot exclusion is proof
    # that the active window cannot change between this snapshot and the actual key event.
    assert fake.calls[2][1]['exclude_active'] is True
