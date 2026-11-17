"""Ask 34: synthetic config + fake read-only compositor; never owner config/reload."""
import hashlib
import importlib.util
import json
import subprocess

import pytest
from test_console_native_launch import ROOT, load_installer

spec = importlib.util.spec_from_file_location('bind_observer_test', ROOT / 'console/observe_native_bind.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def test_generated_line_agrees_with_installer_and_observes_line_151(tmp_path):
    source = '\n' * 150 + load_installer().emit_bind() + '\n'
    path = tmp_path / 'hyprland.lua'
    path.write_text(source)
    before = path.stat().st_mtime_ns
    report = observer.observe(tmp_path)
    assert report['matches'] == [{'file': str(path), 'line': 151, 'syntax': 'lua',
                                  'target_matches_wrapper': True, 'target_literal_known': True,
                                  'line_matches_generated': True}]
    assert report['files'][0]['sha256'] == hashlib.sha256(source.encode()).hexdigest()
    assert observer.GENERATED == load_installer().emit_bind()
    assert before == path.stat().st_mtime_ns
    assert report['duplicate_absence'] == 'UNPROVEN' and report['loaded_source_line'] == 'UNKNOWN'


def test_static_scan_reports_competing_lua_and_legacy_literals(tmp_path):
    (tmp_path / 'hyprland.lua').write_text(observer.GENERATED + '\n')
    (tmp_path / 'nested').mkdir()
    (tmp_path / 'nested/other.lua').write_text('hl.bind("SUPER+SPACE", hl.dsp.exec_cmd("/other"))\n')
    (tmp_path / 'hyprland.conf').write_text('bind = SUPER, SPACE, exec, /other\n')
    report = observer.observe(tmp_path)
    assert len(report['matches']) == 3
    assert sum(m['target_matches_wrapper'] for m in report['matches']) == 1
    assert sum(m['line_matches_generated'] for m in report['matches']) == 1
    assert '"/other"' not in json.dumps(report)  # metadata filenames aren't command strings


def test_comments_strings_and_dynamic_bind_are_not_certified(tmp_path):
    source = ('-- ' + observer.GENERATED + '\n--[=[\n' + observer.GENERATED + '\n]=]\n'
              + 'local text = [=[' + observer.GENERATED + ']=]\n'
              + 'hl.bind(mainMod .. " + SPACE", hl.dsp.exec_cmd(target))\n')
    (tmp_path / 'hyprland.lua').write_text(source)
    report = observer.observe(tmp_path)
    assert report['matches'] == [] and report['unresolved_calls'] == 1
    assert report['duplicate_absence'] == 'UNPROVEN'


def test_multiline_literal_is_semantically_matching_not_exact_generated_line(tmp_path):
    (tmp_path / 'hyprland.lua').write_text(observer.GENERATED.replace(', ', ',\n  ') + '\n')
    result = observer.observe(tmp_path)['matches'][0]
    assert result['target_matches_wrapper'] and not result['line_matches_generated']


def test_symlinks_and_unsupported_lua_report_unknown(tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'source.lua').write_text(observer.GENERATED)
    root = tmp_path / 'hypr'
    root.mkdir()
    (root / 'linked.lua').symlink_to(outside / 'source.lua')
    (root / 'linked-dir').symlink_to(outside, target_is_directory=True)
    (root / 'bad.lua').write_text('--[=[ unterminated')
    report = observer.observe(root)
    assert not report['matches']
    assert sum(f['status'] == 'UNREADABLE_OR_UNSUPPORTED' for f in report['files']) == 2
    assert any(f['status'] == 'SKIPPED_SYMLINK_DIRECTORY' for f in report['files'])


def test_bound_and_custom_chord(tmp_path, monkeypatch):
    (tmp_path / 'other.lua').write_text('hl.bind("SUPER+SHIFT+F2", hl.dsp.exec_cmd("/other"))')
    assert len(observer.observe(tmp_path, 'SUPER + SHIFT + F2')['matches']) == 1
    monkeypatch.setattr(observer, 'MAX_FILES', 1)
    assert observer.observe(tmp_path)['files'][-1]['status'] == 'SCAN_LIMIT_REACHED'


def test_live_query_reports_matching_bind_not_file_line_provenance():
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, json.dumps([
            {'modmask': 64, 'key': 'space', 'dispatcher': 'exec', 'arg': observer.TARGET,
             'release': False, 'submap': ''},
            {'modmask': 64, 'key': 'space', 'dispatcher': 'exec', 'arg': '/other private command'},
            {'modmask': 0, 'key': 'A', 'dispatcher': 'exec', 'arg': 'unrelated private command'},
        ]), '')
    report = observer.live_bindings('SUPER + SPACE', run)
    assert calls[0][0] == ['/usr/bin/hyprctl', '-j', 'binds']
    assert calls[0][1]['timeout'] == 3 and not calls[0][1].get('shell')
    assert report['status'] == 'OBSERVED' and report['matching_chord_count'] == 2
    assert report['matches'][0]['target_matches_wrapper']
    assert report['source_file_line'].startswith('UNKNOWN')
    assert 'private command' not in json.dumps(report)


@pytest.mark.parametrize('case', ['missing', 'timeout', 'error', 'schema', 'invalid-json'])
def test_live_query_failures_are_unknown_never_no_bind(case):
    def run(argv, **kwargs):
        if case == 'missing': raise FileNotFoundError()
        if case == 'timeout': raise subprocess.TimeoutExpired(argv, 3)
        return subprocess.CompletedProcess(argv, 1 if case == 'error' else 0,
                                           'not-json' if case == 'invalid-json' else '{}', '')
    assert observer.live_bindings('SUPER + SPACE', run)['status'] == 'UNKNOWN'


def test_cli_never_queries_live_without_opt_in(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(observer, 'observe', lambda **kw: {'matches': [], 'files': []})
    monkeypatch.setattr(observer, 'live_bindings', lambda *_: pytest.fail('live query not requested'))
    monkeypatch.setattr(observer, 'wrapper_state', lambda: {'status': 'MISSING'})
    assert observer.main([]) == 0
    assert 'NOT_QUERIED' in capsys.readouterr().out
    assert observer.main(['--chord', 'SUPER + SPACE']) == 0


def test_missing_root_is_not_reported_as_no_bind(tmp_path):
    with pytest.raises(ValueError, match='root absent'):
        observer.observe(tmp_path / 'missing')


def test_manifest_pins_observer_bytes():
    manifest = (ROOT / 'console/bind-observer.sha256').read_text()
    path = ROOT / 'console/observe_native_bind.py'
    assert manifest == hashlib.sha256(path.read_bytes()).hexdigest() + '  console/observe_native_bind.py\n'


def test_wrapper_absence_then_verified_bytes_and_drift(tmp_path):
    path = tmp_path / 'wrapper.sh'
    assert observer.wrapper_state(path)['status'] == 'MISSING'
    path.write_bytes((ROOT / 'console/elaria-console-launch.sh').read_bytes())
    path.chmod(0o700)
    result = observer.wrapper_state(path)
    assert result['status'] == 'MATCHES_PIN'
    assert result['expected'] == load_installer().PINS['elaria-console-launch.sh']
    path.write_text('drift')
    assert observer.wrapper_state(path)['status'] == 'INVALID'
    path.unlink()
    path.symlink_to(tmp_path / 'absent')
    assert observer.wrapper_state(path)['status'] == 'INVALID'
