"""Installer output/installed readback gates; never the real owner's paths or compositor."""
import hashlib
import os
import subprocess
import sys

import pytest
from test_console_native_launch import ROOT, load_installer


def owner(tmp_path):
    home = tmp_path / 'synthetic-owner'
    (home / '.config/hypr').mkdir(parents=True)
    (home / '.config/hypr/hyprland.lua').write_text('synthetic retained Lua\n')
    (home / '.config/hypr/hyprland.conf').write_text('synthetic retained duplicate\n')
    return home


def test_cli_success_reports_each_installed_path_and_actual_hash(tmp_path, monkeypatch, capsys):
    installer = load_installer(); home = owner(tmp_path)
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    for _ in range(2):  # existing targets are replaced/read back, never a silent no-op
        assert installer.main(['--install']) == 0
        output = capsys.readouterr()
        assert not output.err and output.out.startswith('START action=install;')
        rows = [line for line in output.out.splitlines() if line.startswith('WRITTEN ')]
        assert len(rows) == 3 and 'PASS exit=0: 3 installed files verified' in output.out
        for path, name in installer.targets_for(home).items():
            assert f'path={path} sha256={installer.PINS[name]} mode=0700' in output.out
            assert hashlib.sha256(path.read_bytes()).hexdigest() == installer.PINS[name]
        assert (home / '.config/hypr/hyprland.lua').read_text() == 'synthetic retained Lua\n'
        assert (home / '.config/hypr/hyprland.conf').read_text() == 'synthetic retained duplicate\n'


def test_check_installed_reads_actual_destinations_without_any_writes(tmp_path, monkeypatch, capsys):
    installer = load_installer(); home = owner(tmp_path)
    installer.install(ROOT / 'console', home)
    before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
              for p in home.rglob('*') if p.is_file()}
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    monkeypatch.setattr(installer, 'replace_file', lambda *_a: pytest.fail('read-only mode wrote'))
    assert installer.main(['--check-installed']) == 0
    output = capsys.readouterr()
    assert output.out.count('VERIFIED path=') == 3 and 'read-only, nothing written' in output.out
    after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_mode)
             for p in home.rglob('*') if p.is_file()}
    assert before == after


@pytest.mark.parametrize('defect', ['missing', 'bytes', 'mode', 'symlink', 'hardlink'])
def test_installed_check_stops_visibly_on_each_defect(tmp_path, monkeypatch, capsys, defect):
    installer = load_installer(); home = owner(tmp_path)
    installer.install(ROOT / 'console', home)
    shim = home / '.config/hypr/elaria-console-launch.sh'
    if defect == 'missing': shim.unlink()
    elif defect == 'bytes': shim.write_text('synthetic drift')
    elif defect == 'mode': shim.chmod(0o600)
    elif defect == 'symlink':
        shim.unlink(); shim.symlink_to(ROOT / 'console/elaria-console-launch.sh')
    else: os.link(shim, home / 'linked')
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    assert installer.main(['--check-installed']) == 2
    output = capsys.readouterr()
    assert 'PASS exit=0' not in output.out and 'STOP exit=2 action=check-installed' in output.err
    assert str(shim) in output.err


def test_install_partial_write_is_not_reported_as_success(tmp_path, monkeypatch, capsys):
    installer = load_installer(); home = owner(tmp_path)
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    real = installer.replace_file
    calls = []
    def replace(path, content):
        calls.append(path)
        if len(calls) == 2: raise OSError('synthetic second-write failure')
        real(path, content)
    monkeypatch.setattr(installer, 'replace_file', replace)
    assert installer.main(['--install']) == 2
    output = capsys.readouterr()
    assert output.out.count('WRITTEN path=') == 1 and 'PASS exit=0' not in output.out
    assert 'synthetic second-write failure' in output.err and 'completed file receipts=1' in output.err
    assert 'Partial writes may remain' in output.err and 'STOP exit=2' in output.err
    assert not (home / '.config/hypr/elaria-console-launch.sh').exists()


def test_failed_readback_does_not_print_a_written_receipt(tmp_path, monkeypatch, capsys):
    installer = load_installer(); home = owner(tmp_path)
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    real = installer.replace_file
    def corrupt(path, content):
        real(path, content); path.write_text('synthetic failed readback')
    monkeypatch.setattr(installer, 'replace_file', corrupt)
    assert installer.main(['--install']) == 2
    output = capsys.readouterr()
    assert 'WRITTEN path=' not in output.out and 'checksum mismatch' in output.err
    assert 'Partial writes may remain' in output.err


def test_generator_is_one_physical_lua_line_no_config_mutation(tmp_path, monkeypatch, capsys):
    installer = load_installer()
    monkeypatch.setattr(installer, 'install', lambda *_a, **_kw: pytest.fail('emitter installed'))
    assert installer.main(['--emit-bind']) == 0
    output = capsys.readouterr()
    expected = 'hl.bind("SUPER + SPACE", hl.dsp.exec_cmd("/home/darrel/.config/hypr/elaria-console-launch.sh"))\n'
    assert output.out == expected and not output.err and installer.emit_bind() + '\n' == expected
    doc = (ROOT / 'console/NATIVE-DEPLOYMENT.md').read_text()
    assert '`' + expected.rstrip('\n') + '`' in doc


def test_process_default_and_argument_stop_have_output_and_exit_code():
    script = ROOT / 'console/install_native_launcher.py'
    good = subprocess.run([sys.executable, '-IB', str(script)], capture_output=True, text=True, check=False)
    assert good.returncode == 0 and 'PASS exit=0' in good.stdout
    bad = subprocess.run([sys.executable, '-IB', str(script), '--bad-flag'], capture_output=True, text=True, check=False)
    assert bad.returncode == 2 and 'STOP exit=2' in bad.stderr
