"""Task I portable tests: real bounded argv effects in temp trees, never real Kitty/display."""
import copy
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant.hands.headless import contract, host, worker
from assistant.hands.headless.consent import Consent, Journal, private_dir, read_json, write_json
from assistant.hands.kitty import policy
from assistant.ipc import IpcPrincipal

OWNER = IpcPrincipal(os.getpid(), os.getuid(), os.getgid())


@pytest.fixture
def work(tmp_path):
    return private_dir(tmp_path / 'instance' / 'work')


@pytest.fixture
def gate(tmp_path):
    root = private_dir(tmp_path / 'control')
    return Consent(root, Journal(root), 'synthetic-instance')


def test_exact_argv_contract_and_real_reversible_worker_demo(work):
    value = contract.plan('hands mkdir proof', work, {})
    assert value['plan']['steps'][0]['argv'] == [str(Path('/usr/bin/mkdir').resolve()), '--', str(work / 'proof')]
    assert value['evidence'][0]['argPattern'] == contract.pattern(value['plan']['steps'][0]['argv'])
    markers = []
    rows = worker.execute(value, work.parent, policy.DATA / 'inventory.json', ['a' * 32], markers.append)
    assert markers == ['ELARIA_OK_' + 'a' * 32] and rows[0]['exit_code'] == 0
    owned = {'proof': rows[0]['target_sha256']}
    undo = contract.plan('hands rmdir proof', work, owned)
    rows = worker.execute(undo, work.parent, policy.DATA / 'inventory.json', ['b' * 32], markers.append)
    assert rows[0]['target_state'] == {'state': 'absent'} and not (work / 'proof').exists()


@pytest.mark.parametrize('text', ['hands rm -rf /', 'hands bash -c true', 'hands python3 x.py',
    'hands mkdir a; rm -rf /', 'hands mkdir a || mkdir b', 'hands mkdir a | cat',
    'hands mkdir $(id)', 'hands mkdir ../x', 'hands mkdir /tmp/x', 'hands mkdir a > file',
    'hands mkdir a && python3 evil', 'hands mkdir a && mkdir a', 'hands mkdir a &&',
    'hands mkdir a\nrm -rf x', 'hands mkdir --help', 'hands mkdir a # ignored'])
def test_shell_chains_and_unsupported_or_irreversible_intents_deny_all(text, work):
    with pytest.raises(ValueError):
        contract.plan(text, work, {})
    assert not list(work.iterdir())


def test_chain_every_segment_needs_exact_permission(work, gate):
    value = contract.plan('hands mkdir a && mkdir b', work, {})
    gate.set_prompt_always(True)
    ask = gate.prepare(contract.plan('hands mkdir a', work, {}))
    gate.answer(ask['token'], ask['digest'], 'allow-always')
    assert not gate.covered(value)
    ask = gate.prepare(value)
    accepted = gate.answer(ask['token'], ask['digest'], 'allow-always')
    assert gate.covered(accepted)
    assert len(gate.load()['entries']) == 2


def test_once_default_always_off_terminal_no_and_restart(work, gate):
    value = contract.plan('hands mkdir a', work, {})
    ask = gate.prepare(value)
    assert ask['default'] == 'allow-once' and not ask['allow_always'] and ask['askFallback'] == 'deny'
    with pytest.raises(ValueError, match='disabled'):
        gate.answer(ask['token'], ask['digest'], 'allow-always')
    with pytest.raises(ValueError, match='already'):
        gate.answer(ask['token'], ask['digest'], 'allow-once')
    ask = gate.prepare(value)
    with pytest.raises(ValueError, match='owner-denied'):
        gate.answer(ask['token'], ask['digest'], 'deny')
    ask = gate.prepare(value)
    gate.answer(ask['token'], ask['digest'], 'allow-once')
    assert gate.load()['entries'] == []
    new = Consent(gate.path.parent, Journal(gate.path.parent), 'new-instance')
    assert new.asks == {} and not new.covered(value)
    assert gate.path.stat().st_mode & 0o777 == 0o600


def test_expiry_cwd_and_operand_toctou_fail(work, gate):
    value = contract.plan('hands mkdir a', work, {})
    ask = gate.prepare(value)
    snapshot, sha, _ = gate.asks[ask['token']]
    gate.asks[ask['token']] = snapshot, sha, 0
    with pytest.raises(ValueError, match='expiry'):
        gate.answer(ask['token'], ask['digest'], 'allow-once')
    ask = gate.prepare(value)
    (work / 'a').mkdir()
    with pytest.raises(ValueError, match='operand-state-drift'):
        gate.answer(ask['token'], ask['digest'], 'allow-once')
    (work / 'a').rmdir()
    ask = gate.prepare(value)
    work.rename(work.with_name('old-work')); work.mkdir(mode=0o700)
    with pytest.raises(ValueError, match='cwd-or-operand-drift'):
        gate.answer(ask['token'], ask['digest'], 'allow-once')


def test_inventory_repin_invalidates_standing_and_pending(work, gate, monkeypatch):
    value = contract.plan('hands mkdir a', work, {})
    gate.set_prompt_always(True)
    ask = gate.prepare(value); gate.answer(ask['token'], ask['digest'], 'allow-always')
    state = gate.load(); state['entries'][0]['inventory_sha256'] = 'f' * 64
    write_json(gate.path, state)
    with pytest.raises(ValueError, match='standing-consent-inventory-drift'):
        gate.covered(value)
    ask = gate.prepare(value)
    monkeypatch.setattr(policy, 'INVENTORY_SHA256', 'f' * 64)
    with pytest.raises(ValueError, match='inventory hash drift'):
        gate.answer(ask['token'], ask['digest'], 'allow-once')


def test_binary_hash_and_interpreter_never_approved(work, gate):
    value = contract.plan('hands mkdir a', work, {})
    for binary in ['/usr/bin/python3', '/usr/bin/bash', '/usr/bin/env']:
        changed = copy.deepcopy(value)
        changed['plan']['steps'][0]['argv'][0] = str(Path(binary).resolve())
        with pytest.raises(ValueError):
            gate.prepare(changed)
    value['evidence'][0]['binary_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='binary-or-argv-drift'):
        gate.prepare(value)


def test_ruling_seed_revocation_and_last_used(work, gate):
    value = contract.plan('hands mkdir a', work, {})
    step, proof = value['plan']['steps'][0], value['evidence'][0]
    state = gate.load()
    state['entries'] = [{'path': step['argv'][0], 'argPattern': proof['argPattern'],
                         'binary_sha256': proof['binary_sha256'], 'inventory_sha256': policy.INVENTORY_SHA256,
                         'source': 'ruling', 'lastUsed': 0}]
    write_json(gate.path, state)
    assert gate.covered(value) and not gate.load()['promptAlways']
    gate.used(value); assert gate.load()['entries'][0]['lastUsed'] > 0
    gate.revoke(step['argv'][0]); assert not gate.covered(value)
    assert gate.journal.rows[-1]['reason'] == 'revoked'


def test_journal_replay_tamper_and_private_symlink(work, gate):
    gate.journal.append('i', 'DENIAL', 'irreversible-intent')
    assert Journal(gate.path.parent).rows == gate.journal.rows
    content = gate.journal.path.read_text().replace('irreversible-intent', 'made-up-success')
    gate.journal.path.write_text(content)
    with pytest.raises(ValueError, match='integrity'):
        Journal(gate.path.parent)
    target = gate.path.with_name('other'); gate.path.rename(target); gate.path.symlink_to(target)
    with pytest.raises(OSError):
        read_json(gate.path)


class SyntheticInstance:
    """No Kitty IPC claim. Real worker effects; tests must separately pin RC marker logic."""
    def __init__(self, runtime, instance):
        self.root = private_dir(Path(runtime) / ('synthetic-' + instance))
        self.work = private_dir(self.root / 'work'); self.owned = {}; self.fault = False
        self.calls = 0

    def start(self):
        return {'synthetic': True, 'boot_marker': True}

    def execute(self, value):
        self.calls += 1
        rows = worker.execute(value, self.root, policy.DATA / 'inventory.json',
                              [f'{i:032x}' for i in range(len(value['plan']['steps']))], lambda _s: None)
        for row, step, proof in zip(rows, value['plan']['steps'], value['evidence'], strict=True):
            row['verification'] = 'observed'
            name = Path(step['argv'][2]).name
            if proof['verb'] == 'mkdir': self.owned[name] = row['target_sha256']
            else: self.owned.pop(name, None)
        return rows

    def close(self):
        self.fault = True


@pytest.fixture
def mount(tmp_path, monkeypatch):
    monkeypatch.setattr(host, 'DedicatedKitty', SyntheticInstance)
    runtime = private_dir(tmp_path / 'runtime-hands')
    return host.HandsMount(runtime)


async def test_full_typed_intent_plan_argv_approval_execute_observe_and_refusal(mount):
    assert await mount.typed(lambda: OWNER, {'text': 'hello'}) is None
    await mount.typed(lambda: OWNER, {'text': 'hands open'})
    reply = await mount.typed(lambda: OWNER, {'text': 'hands mkdir proof'})
    assert reply['reply'] == '' and reply['hands']['ask'] and mount.instance.calls == 0
    ask = reply['hands']['ask']
    answer = await mount.handle(OWNER, {'action': 'answer', 'token': ask['token'], 'digest': ask['digest'], 'decision': 'allow-once'})
    assert answer['events'][-2]['phase'] == 'ACTION'
    assert answer['events'][-1]['verification'] == 'observed'
    assert answer['events'][-1]['action'] == answer['events'][-2]['seq']
    assert (mount.instance.work / 'proof').is_dir()
    reply = await mount.typed(lambda: OWNER, {'text': 'hands rmdir proof'})
    ask = reply['hands']['ask']
    await mount.handle(OWNER, {'action': 'answer', 'token': ask['token'], 'digest': ask['digest'], 'decision': 'allow-once'})
    assert not (mount.instance.work / 'proof').exists()
    reply = await mount.typed(lambda: OWNER, {'text': 'hands rm -rf /'})
    assert reply['reply'] == '' and reply['hands']['events'][-1]['phase'] == 'DENIAL'
    assert mount.instance.calls == 2
    await mount.aclose()


async def test_owner_binding_no_ask_fallback_expiry_halt_and_replay(mount):
    with pytest.raises(PermissionError):
        await mount.handle(SimpleNamespace(uid=os.getuid() + 1), {'action': 'open'})
    await mount.handle(OWNER, {'action': 'open'})
    result = await mount.handle(OWNER, {'action': 'prepare', 'text': 'hands mkdir a'})
    ask = result['ask']; snapshot, sha, _ = mount.consent.asks[ask['token']]
    mount.consent.asks[ask['token']] = snapshot, sha, time.monotonic() - 1
    result = await mount.handle(OWNER, {'action': 'status'})
    assert result['events'][-1]['reason'] == 'ask-expired-fallback-deny'
    result = await mount.handle(OWNER, {'action': 'answer', 'token': ask['token'], 'digest': ask['digest'], 'decision': 'allow-once'})
    assert result['events'][-1]['phase'] == 'DENIAL' and mount.instance.calls == 0
    (mount.runtime / 'assistant.halt').touch()
    result = await mount.handle(OWNER, {'action': 'prepare', 'text': 'hands mkdir a'})
    assert result['events'][-1]['reason'] == 'daemon-halted'
    await mount.aclose()


@pytest.mark.parametrize('path', ['/usr/bin/python3', '/usr/bin/bash', '/usr/bin/env'])
def test_persisted_interpreter_entry_refused_even_if_never_matched(work, gate, path):
    value = contract.plan('hands mkdir a', work, {})
    gate.set_prompt_always(True)
    ask = gate.prepare(value); gate.answer(ask['token'], ask['digest'], 'allow-always')
    state = gate.load(); state['entries'][0]['path'] = str(Path(path).resolve())
    write_json(gate.path, state)
    with pytest.raises(ValueError, match='invalid-allowlist-entry'):
        gate.covered(value)


@pytest.mark.parametrize('marker_present', [True, False])
def test_real_adapter_rc_chain_requires_nonce_readback_not_ack(tmp_path, marker_present):
    from assistant.hands.headless.instance import DedicatedKitty

    instance = DedicatedKitty(tmp_path, 'a' * 32)
    private_dir(instance.root); private_dir(instance.work)
    instance.audit = lambda *_a: None  # recording RC fixture only
    instance.process = SimpleNamespace(pid=123, poll=lambda: None)
    instance.worker_pid = 456
    instance.child_argv = ['fixed', 'non-shell-worker']
    screen, calls = [], []

    class RC:
        def request(self, verb, payload, tier):
            calls.append((verb, payload, tier))
            if verb == 'ls':
                return [{'tabs': [{'windows': [{'id': 17, 'pid': 456, 'cmdline': instance.child_argv,
                                                'title': '[ELARIA hands ' + instance.instance + ']'}]}]}]
            if verb == 'get-text':
                return '\n'.join(screen) if marker_present else 'ack is not an observation'
            assert verb == 'send-text' and payload['match'] == 'id:17'
            request_id = payload['data'].removeprefix('text:').strip()
            request = read_json(instance.root / (request_id + '.request.json'))
            rows = worker.execute(request['value'], instance.root, policy.DATA / 'inventory.json',
                                  request['nonces'], screen.append)
            write_json(instance.root / (request_id + '.result.json'), {'observations': rows})
            return None  # send-text silent success; only readback may establish an effect

    instance.transport = RC()
    value = contract.plan('hands mkdir proof', instance.work, {})
    result = instance.execute(value)
    assert result[0]['verification'] == ('observed' if marker_present else 'unknown')
    assert (instance.work / 'proof').exists()  # effect exists in both; missing marker still cannot certify it
    assert result[0]['stdout_sha256'] is not None if marker_present else result[0]['stdout_sha256'] is None
    assert [verb for verb, _, _ in calls] == ['ls', 'send-text', 'ls', 'get-text']
    if not marker_present:
        with pytest.raises(ValueError, match='not-live'):
            instance.window_id()


def test_dedicated_identity_rejects_daily_terminal_even_with_same_uid(tmp_path):
    from assistant.hands.headless.instance import DedicatedKitty

    instance = DedicatedKitty(tmp_path, 'a' * 32)
    instance.audit = lambda *_a: None  # no hardware claim
    instance.process = SimpleNamespace(pid=1, poll=lambda: None)
    instance.worker_pid = 2; instance.child_argv = ['fixed-worker']
    instance.transport = SimpleNamespace(request=lambda *_a: [{'tabs': [{'windows': [
        {'id': 5, 'pid': 777, 'cmdline': ['/bin/bash'], 'title': 'owner terminal'}]}]}])
    with pytest.raises(ValueError, match='dedicated-target-identity-drift'):
        instance.window_id()


async def test_daemon_mount_is_authenticated_inert_and_typed_route_never_calls_model(config, running_daemon):
    from assistant.ipc import call

    daemon, _ = running_daemon
    assert daemon._hands_mount.journal is None and daemon._hands_mount.instance is None
    result = call(config.socket_path, 'console.say', {'text': 'hands status', 'speak': True})
    assert result['reply'] == '' and result['hands']['askFallback'] == 'deny'
    assert daemon._hands_mount.instance is None
    with pytest.raises(PermissionError):
        await daemon._hands_request({'action': 'open'})


def test_mount_is_exactly_eight_additive_lines_only():
    import subprocess

    baseline = subprocess.run(['git', '-c', 'protocol.allow=never', '--no-replace-objects', 'show',
                               '4b6acf047cca1fc207b2decafc3025f1908c31a9:src/assistant/daemon.py'],
                              capture_output=True, text=True, check=False)
    if baseline.returncode:
        pytest.skip('local accepted baseline object unavailable; no fetch')
    current = Path('src/assistant/daemon.py').read_text()
    inserted = [
        '        from .hands.headless.host import HandsMount\n',
        '        self._hands_mount = HandsMount(config.socket_path.parent)\n',
        '            "hands.request": self._hands_request,\n',
        '    async def _hands_request(self, params: dict) -> dict:\n',
        '        return await self._hands_mount.handle(self._require_ipc_owner(), params)\n',
        '        if (hands := await self._hands_mount.typed(self._require_ipc_owner, params)) is not None:\n',
        '            return hands\n', '        await self._hands_mount.aclose()\n']
    for line in inserted:
        assert current.count(line) == 1
        current = current.replace(line, '', 1)
    assert current == baseline.stdout


def test_restart_records_unmatched_action_unknown_never_replays(tmp_path, monkeypatch):
    state = private_dir(tmp_path / 'state')
    monkeypatch.setenv('XDG_STATE_HOME', str(state))
    root = private_dir(state / 'assistant/hands-headless')
    journal = Journal(root)
    action = journal.append('old-instance', 'ACTION', 'synthetic-crash-after-send')
    mount = host.HandsMount(tmp_path / 'runtime')
    mount.initialize()
    row = mount.journal.rows[-1]
    assert row['phase'] == 'OBSERVATION' and row['verification'] == 'unknown' and row['action'] == action['seq']
    assert mount.instance is None
    again = host.HandsMount(tmp_path / 'runtime'); again.initialize()
    assert len(again.journal.rows) == len(mount.journal.rows)


def test_standing_binary_drift_is_visible_denial_not_silent_miss(work, gate):
    value = contract.plan('hands mkdir a', work, {})
    gate.set_prompt_always(True); ask = gate.prepare(value)
    gate.answer(ask['token'], ask['digest'], 'allow-always')
    state = gate.load(); state['entries'][0]['binary_sha256'] = 'f' * 64
    write_json(gate.path, state)
    with pytest.raises(ValueError, match='standing-consent-binary-drift'):
        gate.covered(value)


@pytest.mark.parametrize('text', ['hands mkdir "a"', "hands mkdir a '&&' mkdir b", 'hands mkdir a\t&& mkdir b'])
def test_unsupported_quoting_is_not_mistaken_for_top_level_chain(work, text):
    with pytest.raises(ValueError, match='unsupported-shell-syntax'):
        contract.plan(text, work, {})


def test_worker_halt_between_chain_segments_stops_next_effect(work):
    value = contract.plan('hands mkdir a && mkdir b', work, {})
    def marker(_text):
        (work.parent.parent / 'assistant.halt').touch()
    with pytest.raises(ValueError, match='halted-at-step-boundary'):
        worker.execute(value, work.parent, policy.DATA / 'inventory.json', ['a' * 32, 'b' * 32], marker)
    assert (work / 'a').is_dir() and not (work / 'b').exists()


def test_binary_symlink_canonicalized_but_interpreter_alias_refused(work, monkeypatch):
    original = contract.executable
    monkeypatch.setattr(contract, 'executable', lambda path: original('/usr/bin/python3'))
    with pytest.raises(ValueError, match='interpreter-or-binary-alias-refused'):
        contract.plan('hands mkdir a', work, {})


async def test_inventory_denial_reason_is_visible_and_no_execution(mount, monkeypatch):
    await mount.handle(OWNER, {'action': 'open'})
    monkeypatch.setattr(policy, 'INVENTORY_SHA256', '0' * 64)
    result = await mount.handle(OWNER, {'action': 'prepare', 'text': 'hands mkdir a'})
    assert result['events'][-1]['reason'] == 'inventory-hash-drift-repin-reapproval-required'
    assert mount.instance.calls == 0
    await mount.aclose()
