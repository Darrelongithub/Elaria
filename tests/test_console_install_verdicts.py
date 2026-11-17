"""Owner asks 32/33: synthetic-only absence/partial checks and clipboard-safe pins."""
import hashlib
import re
import shutil
import subprocess

import pytest
from test_console_install_receipts import owner
from test_console_native_launch import ROOT, load_installer


def test_absent_install_reports_all_three_without_creating_anything(tmp_path, monkeypatch, capsys):
    installer = load_installer()
    home = owner(tmp_path)
    before = sorted(str(p) for p in home.rglob('*'))
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    assert installer.main(['--check-installed']) == 3
    result = capsys.readouterr()
    assert not result.err and result.out.count('MISSING path=') == 3
    assert 'NOT_INSTALLED exit=3' in result.out and 'completed file receipts=0' in result.out
    for path in installer.targets_for(home):
        assert str(path) in result.out
    assert 'Use --check-installed' not in result.out
    assert 'prior installation history is unknown' in result.out
    assert before == sorted(str(p) for p in home.rglob('*'))


def test_missing_config_directory_is_first_class_absence(tmp_path, monkeypatch, capsys):
    installer = load_installer()
    home = tmp_path / 'owner'
    home.mkdir()
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    assert installer.main(['--check-installed']) == 3
    output = capsys.readouterr().out
    assert 'NOT_INSTALLED exit=3 reason=target_directory_absent' in output
    assert output.count('MISSING path=') == 3 and not list(home.iterdir())


def test_missing_helpers_do_not_hide_verified_wrapper(tmp_path, monkeypatch, capsys):
    installer = load_installer()
    home = owner(tmp_path)
    installer.install(ROOT / 'console', home)
    shutil.rmtree(home / '.config/elaria-console-native-v4')
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    assert installer.main(['--check-installed']) == 4
    output = capsys.readouterr()
    assert output.out.count('MISSING path=') == 2
    assert 'VERIFIED path=' + str(home / '.config/hypr/elaria-console-launch.sh') in output.out
    assert 'PARTIAL_INSTALL exit=4' in output.out and 'completed file receipts=1' in output.out


@pytest.mark.parametrize('defect', ['symlink', 'mode', 'bytes', 'unreadable'])
def test_invalid_first_target_does_not_hide_later_targets(tmp_path, monkeypatch, capsys, defect):
    installer = load_installer()
    home = owner(tmp_path)
    installer.install(ROOT / 'console', home)
    first = home / '.config/elaria-console-native-v4/native_launch.py'
    if defect == 'symlink':
        first.unlink()
        first.symlink_to(home / 'absent')
    elif defect == 'mode':
        first.chmod(0o600)
    elif defect == 'bytes':
        first.write_text('drift')
    else:
        real = installer.installed_digest
        def read(path, expected):
            if path == first:
                raise PermissionError('synthetic unreadable target')
            return real(path, expected)
        monkeypatch.setattr(installer, 'installed_digest', read)
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    assert installer.main(['--check-installed']) == 2
    output = capsys.readouterr()
    assert output.out.count('VERIFIED path=') == 2 and str(first) in output.err
    assert 'invalid=1' in output.err and 'Use --check-installed' not in output.err


def test_unsafe_parent_is_invalid_not_missing(tmp_path, monkeypatch, capsys):
    installer = load_installer()
    home = owner(tmp_path)
    (home / '.config/elaria-console-native-v4').symlink_to(home / 'absent')
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    assert installer.main(['--check-installed']) == 2
    output = capsys.readouterr()
    assert output.err.count('INVALID path=') == 2 and output.out.count('MISSING path=') == 1


def test_install_final_recheck_failure_still_stops(tmp_path, monkeypatch, capsys):
    installer = load_installer()
    home = owner(tmp_path)
    monkeypatch.setattr(installer, 'OWNER_HOME', home)
    real = installer.check_installed
    def check(home):
        (home / '.config/hypr/elaria-console-launch.sh').unlink()
        return real(home)
    monkeypatch.setattr(installer, 'check_installed', check)
    assert installer.main(['--install']) == 2
    output = capsys.readouterr()
    assert 'PASS exit=0' not in output.out and 'final installed readback failed' in output.err


def fallback_tree(tmp_path):
    root = tmp_path / 'release with spaces'
    console = root / 'console'
    console.mkdir(parents=True)
    for name in ['install_native_launcher.py', 'native-launcher.sha256', 'verify-native-installer.sh']:
        shutil.copyfile(ROOT / 'console' / name, console / name)
    return root, console / 'verify-native-installer.sh'


def test_fallback_literal_matches_installer_and_manifest(tmp_path):
    root, script = fallback_tree(tmp_path)
    digest = hashlib.sha256((root / 'console/install_native_launcher.py').read_bytes()).hexdigest()
    assert "expected='" + digest + "'" in script.read_text()
    assert digest + '  console/install_native_launcher.py' in (root / 'console/native-launcher.sha256').read_text()
    result = subprocess.run(['sh', str(script)], capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert f'actual={digest} expected={digest}' in result.stdout
    assert 'path=' + str(root / 'console/install_native_launcher.py') in result.stdout


@pytest.mark.parametrize('change', ['literal', 'malformed', 'source', 'absent'])
def test_fallback_mismatch_is_diagnostic_and_never_executes(tmp_path, change):
    root, script = fallback_tree(tmp_path)
    installer = root / 'console/install_native_launcher.py'
    expected = hashlib.sha256(installer.read_bytes()).hexdigest()
    if change in ('literal', 'malformed'):
        value = '0' * 64 if change == 'literal' else 'broken literal'
        script.write_text(re.sub(r"expected='[0-9a-f]{64}'", f"expected='{value}'", script.read_text()))
    elif change == 'source':
        installer.write_text("raise RuntimeError('MUST NEVER EXECUTE')\n")
    else:
        installer.unlink()
    result = subprocess.run(['sh', str(script), '--install'], capture_output=True, text=True, check=False)
    assert result.returncode == 2 and 'MUST NEVER EXECUTE' not in result.stderr
    assert 'VERIFY path=' in result.stdout and 'actual=' in result.stdout and 'expected=' in result.stdout
    reasons = {'literal': 'literal_disagrees_with_matching_manifest',
               'malformed': 'malformed_expected_literal', 'source': 'source_or_expected_pin_disagreement',
               'absent': 'source_unreadable'}
    assert 'reason=' + reasons[change] in result.stdout
    if change == 'literal':
        assert 'actual=' + expected in result.stdout
