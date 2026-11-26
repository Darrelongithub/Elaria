import zipfile

import pytest

from assistant.errand import skill_file_read, skill_fs_locate, inspect_observation_schema
from assistant.indexer import Indexer, extract_text
from assistant.config import Config
from assistant.store import Store


def test_stream_windows_preserve_unicode_and_schema(tmp_path):
    path = tmp_path / 'garden.csv'
    text = 'plant,notes\n' + ('🌱 rose,water weekly\n' * 20000)
    path.write_text(text)
    offset = 0
    pieces = []
    while True:
        obs = skill_file_read(str(path), offset=offset, max_bytes=257,
                              protected=[], never_send_roots=[])
        assert obs.trusted is False
        if offset == 0:
            assert inspect_observation_schema(obs)['columns'] == ['plant', 'notes']
        pieces.append(obs.text)
        if obs.eof:
            break
        assert obs.byte_end > offset
        offset = obs.byte_end
    assert ''.join(pieces) == text


def test_json_inspection_does_not_claim_partial_validation(tmp_path):
    path = tmp_path / 'inventory.json'
    path.write_text('{"items": [' + '0,' * 200 + ']}')
    first = skill_file_read(str(path), max_bytes=256, protected=[], never_send_roots=[])
    assert inspect_observation_schema(first)['status'] == 'incomplete_not_validated'
    whole = skill_file_read(str(path), max_bytes=4096, protected=[], never_send_roots=[])
    assert inspect_observation_schema(whole)['status'] == 'parse_error'


def test_discovery_protected_and_archive_manifest(tmp_path):
    secret = tmp_path / 'private'
    secret.mkdir()
    (secret / 'secret.txt').write_text('secret')
    with zipfile.ZipFile(tmp_path / 'garden.zip', 'w') as z:
        z.writestr('seed/plant.csv', 'plant,colour\nrose,red')
    found = skill_fs_locate([str(tmp_path)], terms=['plant'], protected=[str(secret)], never_send_roots=[])
    assert any('seed/plant.csv' in c['target'] for c in found['candidates'])
    assert all('secret' not in c['target'] for c in found['candidates'])
    assert not (tmp_path / 'seed').exists()


def test_oversized_extract_fails_loudly(tmp_path):
    path = tmp_path / 'huge.txt'
    path.write_text('x' * 200001)
    text, status = extract_text(path)
    assert not text and status.startswith('error:')


def test_indexer_searches_tail_of_large_file(config, tmp_path):
    root = tmp_path / 'library'
    root.mkdir()
    path = root / 'botany.txt'
    path.write_text('ordinary ' * 30000 + ' rareendmarker')
    store = Store(tmp_path / 'index.db')
    stats = Indexer(config, store).index_root({'path': str(root)})
    assert stats['indexed'] == 1
    assert store.search_documents('rareendmarker')[0]['path'] == str(path)


def test_failed_stream_rolls_back_document(tmp_path):
    store = Store(tmp_path / 'index.db')
    def broken():
        yield 'first'
        raise ValueError('broken stream')
    with pytest.raises(ValueError):
        store.upsert_document(path='x', root='r', sha256='x', size=1, mtime=0,
                              mime='text/plain', ext='.txt', indexed_ts='now',
                              never_send=0, text_chunks=broken())
    assert store.document_by_path('x') is None
