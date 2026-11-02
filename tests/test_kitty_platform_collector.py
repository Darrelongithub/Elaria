"""Metadata collector tests: synthetic processes/package docs ONLY, no owner/system probes."""
from __future__ import annotations

import bz2
import gzip
import importlib.util
import json
import lzma
import os
import stat
import subprocess
from pathlib import Path

import pytest
from test_kitty_hands import private as private  # noqa: PLC0414 - pytest fixture registration

SPEC = importlib.util.spec_from_file_location('kitty_platform', Path(__file__).resolve().parents[1] / 'tools/kitty/collect_platform.py')
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)

DOC = b'.TH SSH 1\n.SH SYNTHETIC\nSynthetic package documentation.\n'


@pytest.fixture
def home(private, monkeypatch):
    monkeypatch.setenv('HOME', str(private))
    return private


class StubQueries:
    def __init__(self, suffix='.gz'):
        self.suffix, self.calls, self.overrides = suffix, [], {}

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        record = {'argv': list(argv), 'returncode': 0, 'stdout': 'synthetic metadata\n',
                  'stderr': '', 'error': None, 'truncated': False}
        names = {cmd: name for name, cmd in collector.COMMANDS}
        if argv in names:
            name = names[argv]
            if name == 'ssh-usage':
                record.update(returncode=255, stdout='', stderr='usage: ssh [synthetic options] destination\n')
            elif name in {'kitty-version', 'ssh-version'}:
                record['stdout'] = 'synthetic version (not owner evidence)\n'
            elif name.startswith('files-'):
                record['stdout'] = '/synthetic/package/member\n'
                if name == 'files-openssh-clients':
                    record['stdout'] += '\n'.join(str(collector.MAN_ROOT / base) + self.suffix
                                                  for base in collector.PAGES.values()) + '\n'
            record.update(self.overrides.get(name, {}))
        else:
            assert argv in collector.DECOMPRESSORS.values()
            data = kwargs['input_data']
            decoder = {'.gz': gzip.decompress, '.xz': lzma.decompress, '.bz2': bz2.decompress}.get(self.suffix)
            record['stdout'] = (decoder(data) if decoder else DOC).decode()
            record.update(self.overrides.get('decompression', {}))
        return record


def compressed(suffix, doc=DOC):
    return {'.gz': gzip.compress, '.xz': lzma.compress, '.bz2': bz2.compress}.get(suffix, lambda b: b)(doc)


def collect(home, stub=None, reader=None):
    stub = stub or StubQueries()
    reader = reader or (lambda _: compressed(stub.suffix))
    report = collector.collect(home / 'evidence', runner=stub, reader=reader)
    return report, stub


@pytest.mark.parametrize('suffix', ['', '.gz', '.xz', '.bz2', '.zst'])
def test_complete_synthetic_packet_never_claims_compatibility_or_hardware(home, suffix):
    report, stub = collect(home, StubQueries(suffix))
    assert report['collection_complete'] and not report['compatibility_verified']
    assert not report['hardware_proven'] and report['requires_manual_reconciliation']
    assert report['source_pin'] == 'upstream kitty 0.47.1'
    assert report['owner_design_package_pin'] == '0.47.1-1.fc44'
    assert len(stub.calls) == 12 + (2 if suffix else 0)
    assert len(list((home / 'evidence').glob('*.json'))) == 15
    for name in collector.PAGES:
        record = json.loads((home / 'evidence' / (name + '-manual.json')).read_text())
        assert record['status'] == 'collected' and record['text'] == DOC.decode()
        assert record['source_sha256'] and record['text_sha256']


def test_fixed_queries_no_rc_no_connection_no_config_or_agent(home, monkeypatch):
    with monkeypatch.context() as env_patch:
        for key in ['SSH_AUTH_SOCK', 'KITTY_PASSWORD', 'GEMINI_API_KEY', 'LD_PRELOAD', 'PYTHONPATH']:
            env_patch.setenv(key, 'synthetic-private-value')
        report, stub = collect(home)
    assert [argv for argv, _ in stub.calls[:12]] == [argv for _, argv in collector.COMMANDS]
    for argv, kwargs in stub.calls:
        assert not any(arg in {'@', '-G', '--config'} for arg in argv)
        assert kwargs['cwd'] == home / 'evidence/empty-home'
        env = kwargs['environment']
        assert set(env) == {'PATH', 'LC_ALL', 'TERM', 'NO_COLOR', 'HOME', 'XDG_CONFIG_HOME'}
        assert env['HOME'] == str(home / 'evidence/empty-home') and env['LC_ALL'] == 'C.UTF-8'
        assert 'synthetic-private-value' not in str(env)
    assert 'owner-kitty-config' in report['not_inspected']
    assert 'effective-settings' in report['not_inspected']


def test_bare_ssh_usage_255_is_recorded_not_failure(home):
    report, _ = collect(home)
    assert report['collection_complete']
    record = json.loads((home / 'evidence/ssh-usage.json').read_text())
    assert record['returncode'] == 255 and 'usage: ssh ' in record['stderr']


@pytest.mark.parametrize('override', [{'returncode': 1}, {'returncode': 0}, {'stderr': 'unexpected'},
                                      {'error': 'timeout'}, {'truncated': True}])
def test_unexpected_usage_result_is_a_finding(home, override):
    stub = StubQueries()
    stub.overrides['ssh-usage'] = override
    report, _ = collect(home, stub)
    assert not report['collection_complete']
    assert any(f['instrument'] == 'ssh-usage' for f in report['findings'])


@pytest.mark.parametrize('name', ['package-versions', 'binary-owners', 'kitty-version', 'ssh-version',
                                  'ssh-query-categories', 'files-kitty'])
def test_missing_binaries_unowned_paths_or_packages_are_findings_not_installs(home, name):
    stub = StubQueries()
    stub.overrides[name] = {'returncode': 1, 'stdout': '', 'stderr': 'synthetic missing package or executable'}
    report, _ = collect(home, stub)
    assert not report['collection_complete']
    assert any(f['instrument'] == name for f in report['findings'])
    assert all(argv[0] not in {'dnf', '/usr/bin/dnf', 'pip'} for argv, _ in stub.calls)


@pytest.mark.parametrize('override', [{'error': 'timeout'}, {'truncated': True}, {'returncode': 1},
                                      {'stdout': '', 'stderr': ''}])
def test_unsuccessful_membership_never_authorizes_document_reads(home, override):
    stub = StubQueries()
    stub.overrides['files-openssh-clients'] = override
    reads = []
    report, _ = collect(home, stub, lambda p: reads.append(p))
    assert reads == [] and not report['collection_complete']


def test_unrelated_package_membership_cannot_authorize_ssh_manual_read(home):
    stub = StubQueries()
    stub.overrides['files-openssh-clients'] = {'stdout': '/unrelated/file\n'}
    stub.overrides['files-kitty'] = {'stdout': '/usr/share/man/man1/ssh.1.gz\n'}
    reads = []
    report, _ = collect(home, stub, lambda p: reads.append(p))
    assert not reads and not report['collection_complete']


@pytest.mark.parametrize('path', ['/etc/passwd', '/home/synthetic/.ssh/config',
                                  '/usr/share/man/man1/../ssh.1.gz', '/usr/share/man/fr/man1/ssh.1.gz',
                                  '/usr/share/man/man1/ssh.1.gz/extra', '/usr/share/man/man1/ssh.1.lz4'])
def test_membership_cannot_choose_arbitrary_or_unreviewed_paths(path):
    assert collector.document_candidates([path], 'man1/ssh.1') == []
    with pytest.raises(PermissionError):
        collector.read_document(path)


def test_ambiguous_compressions_refuse_instead_of_selecting_a_file(home):
    stub = StubQueries()
    stub.overrides['files-openssh-clients'] = {'stdout': '/usr/share/man/man1/ssh.1.gz\n/usr/share/man/man1/ssh.1.xz\n'}
    reads = []
    report, _ = collect(home, stub, lambda p: reads.append(p))
    assert not reads and not report['collection_complete']


@pytest.mark.parametrize('body', [b'.so /synthetic/never-read\n', b"'so\t/synthetic/never-read\n",
                                 b'.mso /synthetic/never-read\n', b'', b'\x00', b'\xff'])
def test_manual_includes_empty_or_invalid_text_are_not_rendered_or_followed(home, body):
    report, stub = collect(home, StubQueries(''), lambda _: body)
    assert not report['collection_complete'] and len(stub.calls) == 12
    for name in collector.PAGES:
        record = json.loads((home / 'evidence' / (name + '-manual.json')).read_text())
        assert record['status'] == 'unavailable' and record['text'] is None


@pytest.mark.parametrize('error', ['timeout', 'output-limit', 'FileNotFoundError', None])
def test_decompression_failure_is_not_a_match_or_an_install(home, error):
    stub = StubQueries()
    stub.overrides['decompression'] = {'error': error, 'returncode': 1, 'stdout': 'partial'}
    report, _ = collect(home, stub)
    assert not report['collection_complete']


def test_decompressors_receive_only_preopened_bytes_not_a_filename(home):
    _, stub = collect(home)
    for argv, kwargs in stub.calls[12:]:
        assert argv == ('/usr/bin/gzip', '-cd')
        assert kwargs['input_data'] == compressed('.gz')


def test_new_output_and_every_artifact_private_even_with_permissive_umask(home):
    old = os.umask(0)
    try:
        collect(home)
    finally:
        os.umask(old)
    root = home / 'evidence'
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE((root / 'empty-home').stat().st_mode) == 0o700
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in root.glob('*.json'))


@pytest.mark.parametrize('kind', ['directory', 'file', 'symlink'])
def test_existing_output_never_overwritten_moved_or_deleted(home, kind):
    target = home / 'evidence'
    if kind == 'directory':
        target.mkdir()
    elif kind == 'file':
        target.write_text('synthetic sentinel')
    else:
        target.symlink_to(home / 'absent')
    stub = StubQueries()
    with pytest.raises(FileExistsError):
        collector.collect(target, runner=stub)
    assert not stub.calls
    assert target.exists() or target.is_symlink()


def test_output_must_be_direct_child_of_home_and_no_parents_created(home):
    for path in [home / 'new-parent' / 'evidence', Path('relative'), home.parent / 'elsewhere']:
        with pytest.raises(ValueError):
            collector.collect(path, runner=StubQueries())
    assert not (home / 'new-parent').exists()


def test_unsafe_or_symlinked_home_refused(home, monkeypatch):
    home.chmod(0o777)
    with pytest.raises(PermissionError):
        collector.collect(home / 'evidence', runner=StubQueries())
    home.chmod(0o700)
    link = home / 'linked-home'
    link.symlink_to(home, target_is_directory=True)
    monkeypatch.setenv('HOME', str(link))
    with pytest.raises(OSError):
        collector.collect(link / 'evidence', runner=StubQueries())


def test_artifact_rewrite_refuses_and_preserves_original(home):
    evidence = collector.EvidenceDirectory(home / 'evidence')
    try:
        evidence.write('report.json', {'synthetic': 1})
        with pytest.raises(FileExistsError):
            evidence.write('report.json', {'synthetic': 2})
        assert json.loads((home / 'evidence/report.json').read_text()) == {'synthetic': 1}
    finally:
        evidence.close()


def doc_tree(home):
    root = home / 'man'
    (root / 'man1').mkdir(parents=True)
    path = root / 'man1/ssh.1'
    path.write_bytes(DOC)
    return root, path


def read_synthetic(root):
    return collector.read_document('/usr/share/man/man1/ssh.1', root=root, owner_uid=os.getuid())


def test_secure_document_reader_on_synthetic_regular_file(home):
    root, _ = doc_tree(home)
    assert read_synthetic(root) == DOC


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo', 'writable', 'foreign', 'directory', 'oversize'])
def test_unsafe_document_not_read(home, kind, monkeypatch):
    root, path = doc_tree(home)
    if kind in {'symlink', 'fifo', 'directory'}:
        path.unlink()
        if kind == 'symlink':
            target = root / 'other'
            target.write_bytes(DOC)
            path.symlink_to(target)
        elif kind == 'fifo':
            os.mkfifo(path)
        else:
            path.mkdir()
    elif kind == 'hardlink':
        os.link(path, root / 'alias')
    elif kind == 'writable':
        path.chmod(0o666)
    elif kind == 'foreign':
        with pytest.raises(PermissionError):
            collector.read_document('/usr/share/man/man1/ssh.1', root=root, owner_uid=os.getuid() + 1)
        return
    else:
        monkeypatch.setattr(collector, 'DOCUMENT_LIMIT', 2)
    with pytest.raises((OSError, ValueError)):
        read_synthetic(root)


def test_document_directory_symlink_refuses(home):
    root, _ = doc_tree(home)
    (root / 'man1').rename(root / 'actual')
    (root / 'man1').symlink_to(root / 'actual', target_is_directory=True)
    with pytest.raises(OSError):
        read_synthetic(root)


class PipeProcess:
    """A stub Popen using local pipes, NEVER spawning a program."""
    def __init__(self, stdout=b'out', stderr=b'err', *, pending=False, leader_exited=False, stdin=False):
        self.pid, self.returncode, self.writers = 123456789, (0 if leader_exited or not pending else None), []
        for name, data in [('stdout', stdout), ('stderr', stderr)]:
            r, w = os.pipe()
            os.write(w, data)
            setattr(self, name, os.fdopen(r, 'rb', buffering=0))
            if pending:
                self.writers.append(w)
            else:
                os.close(w)
        self.stdin = None
        self.reader = None
        if stdin:
            r, w = os.pipe()
            self.reader = r
            self.stdin = os.fdopen(w, 'wb', buffering=0)

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        return self.returncode

    def kill(self, *_):
        self.returncode = -9
        for fd in self.writers:
            os.close(fd)
        self.writers.clear()


def bind_process(monkeypatch, proc):
    calls = []
    def popen(argv, **kwargs):
        calls.append((argv, kwargs))
        return proc
    monkeypatch.setattr(collector.subprocess, 'Popen', popen)
    monkeypatch.setattr(collector.os, 'killpg', proc.kill)
    return calls


def test_runner_captures_status_stdout_stderr_and_uses_no_shell_or_inherited_input(home, monkeypatch):
    proc = PipeProcess()
    calls = bind_process(monkeypatch, proc)
    record = collector.run_command(('/synthetic/query',), cwd=home, environment={'LC_ALL': 'C.UTF-8'})
    assert record['stdout'] == 'out' and record['stderr'] == 'err' and record['returncode'] == 0
    assert record['error'] is None
    assert calls[0][1]['stdin'] == subprocess.DEVNULL
    assert calls[0][1]['start_new_session'] and 'shell' not in calls[0][1]
    assert calls[0][1]['close_fds'] and calls[0][1]['umask'] == 0o077
    assert calls[0][1]['env'] == {'LC_ALL': 'C.UTF-8'}


def test_runner_bounded_output_kills_only_its_private_group(home, monkeypatch):
    proc = PipeProcess(stdout=b'x' * 100, stderr=b'', pending=True)
    bind_process(monkeypatch, proc)
    monkeypatch.setattr(collector, 'OUTPUT_LIMIT', 32)
    record = collector.run_command(('/synthetic/query',), cwd=home, environment={})
    assert record['error'] == 'output-limit' and record['truncated']
    assert len(record['stdout'].encode()) + len(record['stderr'].encode()) == 32
    assert record['returncode'] == -9


@pytest.mark.parametrize('leader_exited', [False, True])
def test_runner_timeout_kills_group_even_if_leader_exited(home, monkeypatch, leader_exited):
    proc = PipeProcess(stdout=b'', stderr=b'', pending=True, leader_exited=leader_exited)
    bind_process(monkeypatch, proc)
    ticks = iter([0, 21])
    monkeypatch.setattr(collector.time, 'monotonic', lambda: next(ticks))
    record = collector.run_command(('/synthetic/query',), cwd=home, environment={})
    assert record['error'] == 'timeout' and record['returncode'] == -9
    assert not proc.writers


def test_missing_process_records_type_not_exception_content(home, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError('synthetic-secret-exception')
    monkeypatch.setattr(collector.subprocess, 'Popen', missing)
    record = collector.run_command(('/synthetic/query',), cwd=home, environment={})
    assert record['error'] == 'FileNotFoundError' and record['returncode'] is None
    assert 'synthetic-secret-exception' not in json.dumps(record)


def test_verified_document_input_is_streamed_through_pipe_not_named_file(home, monkeypatch):
    proc = PipeProcess(stdin=True)
    bind_process(monkeypatch, proc)
    try:
        record = collector.run_command(('/synthetic/decompressor',), cwd=home,
                                       environment={}, input_data=b'synthetic-compressed')
        assert record['error'] is None and os.read(proc.reader, 100) == b'synthetic-compressed'
    finally:
        os.close(proc.reader)


def test_command_and_document_counts_are_statically_bounded():
    assert len(collector.COMMANDS) == 12 and len(collector.PAGES) == 2
    assert set(collector.DECOMPRESSORS) == {'.gz', '.xz', '.bz2', '.zst'}
    assert collector.TIMEOUT == 20 and collector.OUTPUT_LIMIT == 2 * 1024 * 1024


def test_cli_has_no_executable_or_document_override(monkeypatch):
    monkeypatch.setattr('sys.argv', ['collect_platform.py', '--output', '/synthetic/out', '--ssh', '/synthetic/other'])
    with pytest.raises(SystemExit) as exc:
        collector.main()
    assert exc.value.code == 2


def test_child_home_write_is_a_finding_preserved_not_cleaned_up(home):
    stub = StubQueries()
    def writing_stub(argv, **kwargs):
        (kwargs['cwd'] / 'synthetic-cache').write_text('synthetic metadata')
        return stub(argv, **kwargs)
    report = collector.collect(home / 'evidence', runner=writing_stub, reader=lambda _: compressed('.gz'))
    assert report['child_home_changed'] and not report['collection_complete']
    assert (home / 'evidence/empty-home/synthetic-cache').exists()
    assert any(f['reason'] == 'unexpected-child-home-write' for f in report['findings'])


def test_read_exception_does_not_echo_private_content(home):
    def unreadable(_):
        raise OSError('synthetic-private-exception')
    report, _ = collect(home, reader=unreadable)
    assert not report['collection_complete']
    assert 'synthetic-private-exception' not in ''.join(p.read_text() for p in (home / 'evidence').glob('*.json'))


def test_failed_persistence_stops_further_queries_without_cleanup(home, monkeypatch):
    stub = StubQueries()
    def failed_fsync(_):
        raise OSError('synthetic-full-disk')
    monkeypatch.setattr(collector.os, 'fsync', failed_fsync)
    with pytest.raises(OSError):
        collector.collect(home / 'evidence', runner=stub)
    assert len(stub.calls) == 1
    assert (home / 'evidence/kitty-version.json').exists()
    assert not (home / 'evidence/report.json').exists()
