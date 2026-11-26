"""BUILD-11: unrelated domains, bounded reads, refusal and failure honesty."""
import io
import json
import tarfile
import zipfile
from itertools import pairwise

import pytest

from assistant.discovery import Policy, locate
from assistant.streamread import StreamError, inspect, iter_batches, read_batch, read_window


@pytest.mark.parametrize("domain,extension", [("orchard", ".json"), ("machine_shop", ".jsonl")])
def test_large_records_reach_tail_without_loss(tmp_path, domain, extension):
    root = tmp_path / domain
    root.mkdir()
    path = root / ("measurements" + extension)
    rows = [{"seq": n, "measurement": "x" * 150} for n in range(1800)]
    rows.append({"seq": 1800, "measurement": "TAIL_SENTINEL"})
    path.write_text(json.dumps(rows) if extension == ".json" else
                    "\n".join(json.dumps(row) for row in rows))
    assert path.stat().st_size > 200_000
    result = locate(Policy((str(root),), (), ()), "measurements")
    assert len(result.matches) == 1
    batches = list(iter_batches(path, byte_budget=8192, record_limit=25))
    assert batches[-1].eof
    assert sum(len(batch.records) for batch in batches) == len(rows)
    assert "TAIL_SENTINEL" in batches[-1].records[-1]["text"]
    assert all(a.byte_end == b.byte_start for a, b in pairwise(batches))
    assert inspect(path).as_dict()["trusted"] is False
    assert read_window(path).trusted is False


def test_protected_symlink_vendor_and_archive_manifest(tmp_path):
    (tmp_path / "private").mkdir()
    secret = tmp_path / "private" / "invoice.json"
    secret.write_text('{"secret": "must_not_read"}')
    (tmp_path / "link.json").symlink_to(secret)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "invoice.txt").write_text("vendor")
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("inventory/invoice.csv", "item,count\napple,7\n")
        zf.writestr("../invoice.txt", "hostile")
    policy = Policy((str(tmp_path),), (str(secret.parent),), ())
    result = locate(policy, "invoice")
    assert len(result.matches) == 1
    assert "#inventory/invoice.csv" in result.matches[0].target
    window = read_window(result.matches[0].target)
    assert "apple" in window.text
    assert not (tmp_path / "inventory").exists()
    for path in (secret, tmp_path / "link.json"):
        with pytest.raises(StreamError):
            read_batch(path, protected=[str(secret.parent)])


def test_tar_member_read_is_read_only(tmp_path):
    archive = tmp_path / "bundle.tar"
    with tarfile.open(archive, "w") as tf:
        data = b'{"measurement": 7}\n'
        info = tarfile.TarInfo("data.jsonl")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    batch = read_batch(f"zip://{archive}#data.jsonl")
    assert batch.eof and len(batch.records) == 1
    assert not (tmp_path / "data.jsonl").exists()


def test_redaction_never_send_and_parse_failure(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('{"password": "TOP_SECRET", "value": 3}\n')
    assert "TOP_SECRET" not in json.dumps(inspect(path).as_dict())
    window = read_window(path, never_send_roots=[str(tmp_path)])
    assert window.never_send and not window.trusted
    assert "TOP_SECRET" not in window.text
    path.write_text('{broken}\n')
    batch = read_batch(path)
    assert batch.parse_error or any(r.get("parse_error") for r in batch.records)


def test_budget_exhaustion_is_not_eof(tmp_path):
    path = tmp_path / "records.jsonl"
    path.write_text('\n'.join(json.dumps({"n": n}) for n in range(100)))
    first = read_batch(path, record_limit=2)
    assert not first.eof
    with pytest.raises(StreamError, match="max_batches"):
        list(iter_batches(path, record_limit=2, max_batches=1))
    path.write_text(json.dumps({"long": "x" * 2000}) + '\n')
    with pytest.raises(StreamError, match="budget"):
        read_batch(path, byte_budget=256)


@pytest.mark.parametrize("text", ['[1 2]', '[1,]', '[}', '[1] trailing', '{"a": 1,}'])
def test_corrupt_json_never_certified_as_eof(tmp_path, text):
    path = tmp_path / "bad.json"
    path.write_text(text)
    with pytest.raises(StreamError):
        list(iter_batches(path, record_limit=1))


def test_top_level_sensitive_field_and_render_loss(tmp_path):
    path = tmp_path / "object.json"
    path.write_text('{"password": "TOP_SECRET", "long": "' + 'x' * 3000 + '"}')
    batch = read_batch(path)
    assert "TOP_SECRET" not in json.dumps(batch.as_dict())
    window = read_window(path)
    assert window.eof and window.truncated and window.notes


def test_multiline_csv_preserves_logical_rows(tmp_path):
    path = tmp_path / "inventory.csv"
    path.write_text('item,description\napple,"first line\nsecond line"\npear,simple\n')
    batches = list(iter_batches(path, record_limit=1))
    assert sum(len(b.records) for b in batches) == 2
    assert batches[0].records[0]["fields"]["description"] == "first line\nsecond line"
    assert batches[-1].eof


def test_indexer_persists_truncation_and_parse_failures(config, tmp_path):
    from assistant.indexer import Indexer, extract_text
    from assistant.store import Store

    root = tmp_path / "indexed"
    root.mkdir()
    large = root / "large.txt"
    large.write_text("measurement " * 30000)
    broken = root / "broken.json"
    broken.write_text('[{"n": 1}, BROKEN]')
    config.raw["organise"]["max_extract_chars"] = 200000
    store = Store(tmp_path / "index.db")
    try:
        stats = Indexer(config, store).index_root({"path": str(root)})
        large_doc = store.document_by_path(str(large))
        bad_doc = store.document_by_path(str(broken))
        assert large_doc["truncated"] == 1
        assert large_doc["extracted_chars"] == 200000
        assert bad_doc["status"] == "error" and bad_doc["parse_error"]
        assert stats["truncated"] == stats["parse_errors"] == 1
        assert store.extraction_report()
        assert "truncated" in extract_text(large)[1]
        # Migration of pre-provenance indexed rows must not skip re-extraction.
        with store._lock:
            store._conn.execute("UPDATE documents SET extractor=NULL WHERE path=?", (str(large),))
            store._conn.commit()
        Indexer(config, store).index_root({"path": str(root)})
        assert store.document_by_path(str(large))["truncated"] == 1
    finally:
        store.close()


def test_index_metadata_hits_are_root_policy_filtered_and_deduplicated(tmp_path):
    from assistant.store import Store

    root = tmp_path / "allowed"
    root.mkdir()
    good = root / "invoice.dat"
    good.write_bytes(b"binary")
    private = root / "private"
    private.mkdir()
    secret = private / "invoice.dat"
    secret.write_bytes(b"secret")
    outside = tmp_path / "invoice.dat"
    outside.write_bytes(b"outside")
    store = Store(tmp_path / "metadata.db")
    try:
        for path in (good, secret, outside, root / "missing-invoice.dat"):
            store.upsert_document(path=str(path), root=str(root), sha256="a" * 64,
                                  size=6, mtime=0, mime=None, ext=".dat",
                                  indexed_ts="2026-11-26", never_send=0, text_chunks=[])
        policy = Policy((str(root),), (str(private),), ())
        # No walk entries: this result can only originate in metadata SQL.
        result = locate(policy, "invoice", store=store, entries=[])
        assert [entry.target for entry in result.matches] == [str(good)]
        # Combining live and cached entries does not double count.
        result = locate(policy, "invoice", store=store)
        assert result.total_matched == 1
    finally:
        store.close()


def test_structured_index_cap_is_recorded(tmp_path):
    from assistant.indexer import extract_with_provenance

    path = tmp_path / "ledger.jsonl"
    path.write_text('\n'.join(json.dumps({"n": n, "padding": "x" * 100}) for n in range(3000)))
    result = extract_with_provenance(path, 200000)
    assert result["truncated"] and not result["parse_error"]
    assert result["extracted_chars"] <= 200000
