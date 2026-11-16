"""F31 ground-truth catalogue pin, not the historical report's claimed checksum."""
import hashlib

import pytest

from assistant.hands.kitty import policy

PIN = '7e0f01ff2396c292f05528261d349142f1c6e08eed948847ee1300633a1aafcd'


def test_inventory_bytes_match_owner_verified_pin_exactly():
    raw = (policy.DATA / 'inventory.json').read_bytes()
    assert len(raw) == 514801
    assert hashlib.sha256(raw).hexdigest() == policy.INVENTORY_SHA256 == PIN
    assert policy.inventory()['schema_version'] == 1


@pytest.mark.parametrize('change', ['whitespace', 'semantic', 'invalid-json'])
def test_inventory_drift_refuses_before_parsing_or_action(tmp_path, monkeypatch, change):
    raw = (policy.DATA / 'inventory.json').read_bytes()
    if change == 'whitespace':
        raw += b'\n'
    elif change == 'semantic':
        raw = raw.replace(b'"K3"', b'"K1"', 1)
    else:
        raw = b'not json'
    (tmp_path / 'inventory.json').write_bytes(raw)
    monkeypatch.setattr(policy, 'DATA', tmp_path)
    with pytest.raises(ValueError, match='inventory hash drift.*re-approval'):
        policy.inventory()


def test_verified_read_is_parsed_without_rereading(monkeypatch):
    from pathlib import Path

    raw = (policy.DATA / 'inventory.json').read_bytes()
    reads = []

    def read(_path):
        reads.append(True)
        return raw if len(reads) == 1 else b'changed after check'

    monkeypatch.setattr(Path, 'read_bytes', read)
    assert policy.inventory()['schema_version'] == 1
    assert len(reads) == 1
