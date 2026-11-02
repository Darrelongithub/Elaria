"""Committed packet gates with synthetic blobs/processes; never execute Git or collector."""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_kitty_hands import private as private  # noqa: PLC0414 - pytest fixture registration
from test_kitty_platform_collector import PipeProcess

SPEC = importlib.util.spec_from_file_location('kitty_owner_packet', Path(__file__).resolve().parents[1] / 'tools/kitty/owner_run_platform.py')
packet = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packet)
PINNED_FILES = packet.FILES


@pytest.fixture
def setup(private, monkeypatch):
    monkeypatch.setenv('HOME', str(private))
    (private / 'Elaria').mkdir()
    # Test-only substitution: the executable packet exposes no manifest/ref override.
    blobs = {p: ('synthetic fixture for ' + p).encode() for p, _, _ in PINNED_FILES}
    monkeypatch.setattr(packet, 'FILES', tuple((p, len(b), hashlib.sha256(b).hexdigest()) for p, b in blobs.items()))
    calls, executions = [], []
    def reader(repo, path, size, empty_home):
        calls.append((repo, path, size, empty_home))
        return blobs[path]
    def execute(argv, environment, kit):
        executions.append((argv, environment, kit))
        packet.verify_kit(kit)
    return private, blobs, calls, executions, reader, execute


def test_pinned_manifest_identity_and_exact_five_paths():
    assert packet.SOURCE_COMMIT == 'a0e1aa8bba11e15ae6de9150b5a158a966acc2d6'
    assert sum(n for _, n, _ in PINNED_FILES) == 64275
    assert len(PINNED_FILES) == 5
    assert [p for p, _, _ in PINNED_FILES] == [
        'tools/kitty/collect_platform.py', 'tests/test_kitty_platform_collector.py',
        'docs/kitty-platform-collector.md', 'docs/design/kitty-2026-11-02-checkpoint-ruling.md',
        'docs/phase-reports/kitty-2026-11-02-platform-collector.md']
    assert PINNED_FILES[0][2] == '7e2d8679a3c18aa35968c06aab469082f9d17cfa8fb1ccaace3f5a4c85261c63'


def test_default_prepares_only_without_collector_or_evidence_directory(setup):
    home, blobs, calls, executions, reader, execute = setup
    kit = packet.run_packet(blob_reader=reader, executor=execute)
    assert len(calls) == 5 and not executions
    assert kit.parent == home and not list(home.glob('kitty-platform-evidence-*'))
    for p, b in blobs.items():
        assert (kit / p).read_bytes() == b
    receipt = json.loads((kit / 'delivery.json').read_text())
    assert receipt['all_five_files_verified'] and not receipt['execution_requested']
    assert not receipt['collection_complete'] and not receipt['hardware_proven']


def test_explicit_run_gates_all_five_and_executes_only_collector(setup):
    home, _, calls, executions, reader, execute = setup
    kit = packet.run_packet(execute=True, blob_reader=reader, executor=execute)
    assert len(calls) == 5 and len(executions) == 1
    argv, env, actual_kit = executions[0]
    assert actual_kit == kit
    assert argv[:3] == ('/usr/bin/python3', '-I', '-B')
    assert argv[3] == str(kit / PINNED_FILES[0][0]) and argv[4] == '--output'
    assert Path(argv[5]).parent == home
    assert env == {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'TERM': 'dumb', 'NO_COLOR': '1'}
    assert json.loads((kit / 'delivery.json').read_text())['execution_requested']


@pytest.mark.parametrize('index', range(5))
@pytest.mark.parametrize('corruption', ['same-size', 'short', 'long'])
def test_any_blob_mismatch_stops_before_execution_no_fallback(setup, index, corruption):
    home, _blobs, calls, executions, reader, execute = setup
    chosen = packet.FILES[index][0]
    def corrupt(*args):
        value = reader(*args)
        if args[1] == chosen:
            return {'same-size': b'x' * len(value), 'short': value[:-1], 'long': value + b'x'}[corruption]
        return value
    with pytest.raises(packet.PacketError, match='size-or-sha256-mismatch'):
        packet.run_packet(execute=True, blob_reader=corrupt, executor=execute)
    assert len(calls) == index + 1 and not executions
    kit, = home.glob('kitty-platform-kit-*')
    assert not (kit / chosen).exists() and not (kit / 'delivery.json').exists()
    assert not list(home.glob('kitty-platform-evidence-*'))
    assert list(home.glob('kitty-platform-kit-*'))  # no cleanup or repair


def test_missing_object_stops_no_fetch_or_second_source(setup):
    _, _, calls, executions, reader, execute = setup
    def missing(*args):
        reader(*args)
        raise packet.PacketError('git-local-object-unavailable-or-git-option-unsupported')
    with pytest.raises(packet.PacketError):
        packet.run_packet(execute=True, blob_reader=missing, executor=execute)
    assert len(calls) == 1 and not executions


def test_final_disk_verification_detects_tampering_before_exec(setup, monkeypatch):
    _, _, _, executions, reader, execute = setup
    original = packet.write_new
    def tampering_write(path, raw):
        original(path, raw)
        if path.name == 'delivery.json':
            (path.parent / packet.FILES[0][0]).write_bytes(b'altered')
    monkeypatch.setattr(packet, 'write_new', tampering_write)
    with pytest.raises(packet.PacketError):
        packet.run_packet(execute=True, blob_reader=reader, executor=execute)
    assert not executions


def test_packet_files_and_directories_private_even_under_umask_zero(setup):
    _, _, _, _, reader, execute = setup
    old = os.umask(0)
    try:
        kit = packet.run_packet(blob_reader=reader, executor=execute)
    finally:
        os.umask(old)
    for path in [kit, *kit.rglob('*')]:
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_fresh_kit_each_time_no_overwrite_or_removal(setup):
    _, _, _, _, reader, execute = setup
    first = packet.run_packet(blob_reader=reader, executor=execute)
    before = {str(p.relative_to(first)): p.read_bytes() for p in first.rglob('*') if p.is_file()}
    second = packet.run_packet(blob_reader=reader, executor=execute)
    assert first != second
    assert before == {str(p.relative_to(first)): p.read_bytes() for p in first.rglob('*') if p.is_file()}


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'writable'])
def test_unsafe_verified_file_refuses(setup, kind):
    _, _, _, _, reader, execute = setup
    kit = packet.run_packet(blob_reader=reader, executor=execute)
    path = kit / packet.FILES[0][0]
    if kind == 'symlink':
        raw = path.read_bytes()
        path.unlink()
        other = kit / 'other'
        packet.write_new(other, raw)
        path.symlink_to(other)
    elif kind == 'hardlink':
        os.link(path, kit / 'alias')
    else:
        path.chmod(0o644)
    with pytest.raises((OSError, packet.PacketError)):
        packet.verify_kit(kit)


def test_owner_checkout_bytes_remain_untouched(setup):
    home, _, _, _, reader, execute = setup
    sentinel = home / 'Elaria' / 'mainline-scene-sentinel'
    sentinel.write_text('synthetic mainline data')
    packet.run_packet(execute=True, blob_reader=reader, executor=execute)
    assert sentinel.read_text() == 'synthetic mainline data'
    assert list((home / 'Elaria').iterdir()) == [sentinel]


def test_git_home_write_is_finding_not_ignored(setup):
    _, _, _, executions, reader, execute = setup
    def writing_reader(*args):
        (args[3] / 'unexpected').write_text('synthetic')
        return reader(*args)
    with pytest.raises(packet.PacketError, match='unexpected-git-home-write'):
        packet.run_packet(execute=True, blob_reader=writing_reader, executor=execute)
    assert not executions


@pytest.mark.parametrize('kind', ['missing-repo', 'relative-repo', 'writable-home', 'symlink-home'])
def test_bad_local_paths_refuse_without_queries(setup, monkeypatch, kind):
    home, _, calls, executions, reader, execute = setup
    repo = None
    if kind == 'missing-repo':
        repo = home / 'absent'
    elif kind == 'relative-repo':
        repo = Path('relative')
    elif kind == 'writable-home':
        home.chmod(0o777)
    else:
        link = home / 'linked-home'
        link.symlink_to(home, target_is_directory=True)
        monkeypatch.setenv('HOME', str(link))
    with pytest.raises(packet.PacketError):
        packet.run_packet(repo, blob_reader=reader, executor=execute)
    assert not calls and not executions
    home.chmod(0o700)


def bind_process(monkeypatch, proc):
    calls, kills = [], []
    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return proc
    def kill(*args):
        kills.append(args)
        proc.kill(*args)
    monkeypatch.setattr(packet.subprocess, 'Popen', popen)
    monkeypatch.setattr(packet.os, 'killpg', kill)
    return calls, kills


def test_git_argv_is_pinned_read_only_no_lazy_fetch_even_on_partial_clone(private, monkeypatch):
    proc = PipeProcess(stdout=b'blob', stderr=b'')
    calls, kills = bind_process(monkeypatch, proc)
    assert packet.read_git_blob(private, 'tools/kitty/collect_platform.py', 4, private) == b'blob'
    argv, kwargs = calls[0]
    assert argv == ('/usr/bin/git', '--no-lazy-fetch', '--no-replace-objects', '--no-optional-locks',
                    '-c', 'protocol.allow=never', '-c', 'core.fsmonitor=false', '-C', str(private),
                    'cat-file', 'blob', packet.SOURCE_COMMIT + ':tools/kitty/collect_platform.py')
    assert kwargs['stdin'] == subprocess.DEVNULL and kwargs['close_fds'] and kwargs['umask'] == 0o077
    assert kwargs['start_new_session'] and 'shell' not in kwargs
    assert kwargs['env']['GIT_NO_LAZY_FETCH'] == '1'
    assert kwargs['env']['GIT_CONFIG_GLOBAL'] == '/dev/null'
    assert not kills  # don't signal a reaped leader's potentially reused group ID


@pytest.mark.parametrize('code', [129, 128, 1])
def test_unsupported_git_or_missing_object_is_terminal_without_retry(private, monkeypatch, code):
    proc = PipeProcess(stdout=b'', stderr=b'synthetic private diagnostic')
    proc.returncode = code
    calls, _ = bind_process(monkeypatch, proc)
    with pytest.raises(packet.PacketError, match='git-local-object-unavailable-or-git-option-unsupported'):
        packet.read_git_blob(private, 'fixed', 10, private)
    assert len(calls) == 1


@pytest.mark.parametrize('stream', ['stdout', 'stderr'])
def test_git_output_bounded_and_group_killed(private, monkeypatch, stream):
    proc = PipeProcess(stdout=b'x' * 100 if stream == 'stdout' else b'',
                       stderr=b'x' * 100 if stream == 'stderr' else b'', pending=True)
    _, kills = bind_process(monkeypatch, proc)
    monkeypatch.setattr(packet, 'GIT_STDERR_LIMIT', 32)
    with pytest.raises(packet.PacketError, match='git-output-limit'):
        packet.read_git_blob(private, 'fixed', 32, private)
    assert len(kills) == 1 and proc.returncode == -9


@pytest.mark.parametrize('leader_exited', [False, True])
def test_git_timeout_closes_descendant_pipes_even_after_leader_exits(private, monkeypatch, leader_exited):
    proc = PipeProcess(stdout=b'', stderr=b'', pending=True, leader_exited=leader_exited)
    _, kills = bind_process(monkeypatch, proc)
    ticks = iter([0, 21])
    monkeypatch.setattr(packet.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(packet.PacketError, match='git-read-timeout'):
        packet.read_git_blob(private, 'fixed', 32, private)
    assert len(kills) == 1 and not proc.writers


def test_positive_git_environment_excludes_owner_and_credentials(private, monkeypatch):
    with monkeypatch.context() as env:
        for name in ['SSH_AUTH_SOCK', 'KITTY_PASSWORD', 'GIT_CONFIG_COUNT', 'GEMINI_API_KEY', 'LD_PRELOAD']:
            env.setenv(name, 'synthetic-secret')
        result = packet.git_environment(private)
    assert 'synthetic-secret' not in str(result)
    assert result['HOME'] == str(private) and result['GIT_CONFIG_NOSYSTEM'] == '1'
    assert result['GIT_TERMINAL_PROMPT'] == '0'


def test_packet_python_imports_stdlib_only():
    tree = ast.parse(Path(packet.__file__).read_text())
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(item.name.split('.')[0] for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module.split('.')[0])
    assert imports <= sys.stdlib_module_names


@pytest.mark.parametrize('argument', ['--commit', '--sha256', '--collector', '--fetch', '--python'])
def test_no_cli_pin_or_executable_override(monkeypatch, argument):
    monkeypatch.setattr(sys, 'argv', ['owner_run_platform.py', argument, 'synthetic'])
    with pytest.raises(SystemExit) as exc:
        packet.main()
    assert exc.value.code == 2


def test_exec_handoff_has_fixed_interpreter_no_wrapper_or_inherited_input(private, monkeypatch):
    seen = []
    with monkeypatch.context() as patch:
        patch.setattr(packet.os, 'chdir', lambda p: seen.append(('cwd', p)))
        patch.setattr(packet.os, 'open', lambda p, flags: 123)
        patch.setattr(packet.os, 'dup2', lambda a, b: seen.append(('dup2', a, b)))
        patch.setattr(packet.os, 'close', lambda fd: seen.append(('close', fd)))
        patch.setattr(packet.os, 'umask', lambda mode: seen.append(('umask', mode)))
        patch.setattr(packet.os, 'execve', lambda exe, argv, env: seen.append(('exec', exe, argv, env)))
        argv = ('/usr/bin/python3', '-I', '-B', '/synthetic/verified/collect_platform.py', '--output', '/synthetic/evidence')
        env = {'HOME': '/synthetic/home'}
        packet.exec_collector(argv, env, private)
    assert ('dup2', 123, 0) in seen and ('umask', 0o077) in seen
    assert seen[-1] == ('exec', '/usr/bin/python3', argv, env)


@pytest.mark.parametrize('run', [False, True])
def test_cli_requires_explicit_run_flag(monkeypatch, run):
    seen = []
    monkeypatch.setattr(sys, 'argv', ['owner_run_platform.py'] + (['--run'] if run else []))
    monkeypatch.setattr(packet, 'run_packet', lambda repo, execute: seen.append((repo, execute)))
    assert packet.main() == 0 and seen == [(None, run)]


def test_write_failure_stops_before_collector_and_retains_partial_kit(setup, monkeypatch):
    home, _, calls, executions, reader, execute = setup
    def full(_):
        raise OSError('synthetic disk full')
    monkeypatch.setattr(packet.os, 'fsync', full)
    with pytest.raises(OSError):
        packet.run_packet(execute=True, blob_reader=reader, executor=execute)
    assert len(calls) == 1 and not executions
    kit, = home.glob('kitty-platform-kit-*')
    assert (kit / packet.FILES[0][0]).exists() and not (kit / 'delivery.json').exists()
