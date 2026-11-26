"""Bounded, local-only structured record reader. All returned data is untrusted.

Cursors are record ordinals plus a content hash, not executable instructions.
A record larger than the configured limit is rejected, never silently cut.
Pagination replays earlier records to validate structure and preserve CSV state.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import os
from html.parser import HTMLParser
from contextlib import contextmanager
from pathlib import Path
import zipfile

from .errand import (_check_zip_ratio, _has_symlink_to_root, _is_never_send,
                     _parse_zip_target, _parse_tar_target, _open_tar_member)
from .safety import expand, is_protected, open_readonly_nofollow


class StructuredReadError(ValueError):
    """A source cannot be completely and safely parsed at the reported stage."""


@contextmanager
def _source(target, protected, never_send_roots, cloud_bound):
    spec = _parse_zip_target(target)
    tar_spec = _parse_tar_target(target)
    path = (spec or tar_spec)[0] if (spec or tar_spec) else expand(target)
    if is_protected(path, protected) or _has_symlink_to_root(path):
        raise PermissionError(f"protected or symlink source: {path}")
    if cloud_bound and _is_never_send(path, never_send_roots):
        raise PermissionError("source is never_send_to_cloud")
    if tar_spec:
        with _open_tar_member(path, tar_spec[1]) as (stream, _):
            yield stream
        return
    with open_readonly_nofollow(path) as raw:
        if spec:
            with zipfile.ZipFile(raw) as archive:
                info = archive.getinfo(spec[1])
                _check_zip_ratio(info)
                with archive.open(info) as stream:
                    yield stream
        else:
            yield raw


def _hash(target, protected, never_send_roots, cloud_bound):
    digest = hashlib.sha256()
    with _source(target, protected, never_send_roots, cloud_bound) as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


class _BoundedLines:
    def __init__(self, text, limit):
        self.text, self.limit = text, limit
        self.record_chars = 0
    def __iter__(self):
        return self
    def __next__(self):
        line = self.text.readline(self.limit + 1)
        if not line:
            raise StopIteration
        self.record_chars += len(line)
        if self.record_chars > self.limit:
            raise StructuredReadError('record exceeds limit')
        return line


def _json_records(text, limit):
    """Incremental top-level array/object reader; bounded individual values."""
    buffer = ''
    eof = False
    decoder = json.JSONDecoder()
    def fill():
        nonlocal buffer, eof
        part = text.read(min(8192, limit + 1 - len(buffer)))
        if not part:
            eof = True
        buffer += part
    def whitespace():
        nonlocal buffer
        while True:
            buffer = buffer.lstrip()
            if buffer or eof:
                return
            fill()
    def value():
        nonlocal buffer
        while True:
            whitespace()
            try:
                item, end = decoder.raw_decode(buffer)
                # Numbers can end at a buffer boundary and continue next read.
                if not eof and (end == len(buffer) or buffer[end] not in ' \t\r\n,]}:'):
                    if len(buffer) >= limit:
                        raise StructuredReadError('JSON value exceeds limit or is malformed')
                    fill()
                    continue
                if end > limit:
                    raise StructuredReadError('JSON value exceeds limit')
                buffer = buffer[end:]
                return item
            except json.JSONDecodeError as exc:
                if eof:
                    raise StructuredReadError(f'JSON parse error: {exc}') from exc
                if len(buffer) >= limit:
                    raise StructuredReadError('JSON value exceeds limit') from exc
                fill()
    whitespace()
    if not buffer:
        raise StructuredReadError('empty JSON document')
    opener = buffer[0]
    if opener not in '[{':
        yield value()
    else:
        buffer = buffer[1:]
        close = ']' if opener == '[' else '}'
        first = True
        while True:
            whitespace()
            if not buffer:
                raise StructuredReadError('unexpected EOF in JSON container')
            if buffer[0] == close:
                buffer = buffer[1:]
                break
            if not first:
                if buffer[0] != ',':
                    raise StructuredReadError('expected comma in JSON container')
                buffer = buffer[1:]
                whitespace()
                if buffer.startswith(close):
                    raise StructuredReadError('trailing comma in JSON container')
            if opener == '{':
                key = value()
                if not isinstance(key, str):
                    raise StructuredReadError('JSON object key must be a string')
                whitespace()
                if not buffer.startswith(':'):
                    raise StructuredReadError('expected colon after JSON key')
                buffer = buffer[1:]
                yield {'key': key, 'value': value()}
            else:
                yield value()
            first = False
    whitespace()
    if buffer:
        raise StructuredReadError('trailing data after JSON document')


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        if data:
            self.parts.append(data)


def _html_records(text, limit):
    parser = _HTMLText()
    while True:
        block = text.read(min(8192, limit))
        if not block:
            parser.close()
            yield from parser.parts
            break
        parser.feed(block)
        if len(parser.rawdata) > limit:
            raise StructuredReadError('HTML token exceeds limit')
        yield from parser.parts
        parser.parts.clear()


def _sqlite_records(binary, limit):
    """Inspect an immutable private snapshot, never execute SQL from the database.

    WAL-mode databases are refused: copying the main file alone is not a
    reliable snapshot. The private temporary directory is removed on exit.
    """
    header = binary.read(100)
    if len(header) < 100 or not header.startswith(b"SQLite format 3\x00"):
        raise StructuredReadError("invalid SQLite header")
    if header[18] != 1 or header[19] != 1:
        raise StructuredReadError("SQLite WAL-mode snapshot refused; checkpoint and use a rollback-mode copy")
    with tempfile.TemporaryDirectory(prefix="elaria-read-") as directory:
        filename = Path(directory) / "snapshot.sqlite"
        total = len(header)
        with open(filename, "xb") as out:
            os.chmod(filename, 0o600)
            out.write(header)
            for block in iter(lambda: binary.read(65536), b""):
                total += len(block)
                if total > 1_000_000_000:
                    raise StructuredReadError("SQLite snapshot exceeds disk budget")
                out.write(block)
        uri = filename.as_uri() + "?mode=ro&immutable=1"
        try:
            connection = sqlite3.connect(uri, uri=True)
            try:
                connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, max(limit, 10000))
                connection.execute("PRAGMA query_only=ON")
                connection.execute("PRAGMA trusted_schema=OFF")
                tables = connection.execute(
                    "SELECT name, sql FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
                for name, definition in tables:
                    if not definition or definition.lstrip().upper().startswith("CREATE VIRTUAL TABLE"):
                        raise StructuredReadError("SQLite virtual tables are not inspectable")
                    identifier = '"' + name.replace('"', '""') + '"'
                    rows = connection.execute("SELECT * FROM " + identifier)
                    columns = [item[0] for item in rows.description]
                    for row in rows:
                        values = [({'blob_hex': item.hex()} if isinstance(item, bytes) else item)
                                  for item in row]
                        yield {'table': name, 'columns': columns, 'values': values}
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise StructuredReadError(f"SQLite inspection failed: {exc}") from exc


def _records(binary, fmt, limit):
    if fmt in ('.sqlite', '.sqlite3', '.db'):
        yield from _sqlite_records(binary, limit)
        return
    text = io.TextIOWrapper(binary, encoding='utf-8-sig', errors='strict', newline='')
    try:
        if fmt in ('.html', '.htm'):
            yield from _html_records(text, limit)
        elif fmt == '.json':
            yield from _json_records(text, limit)
        elif fmt in ('.jsonl', '.ndjson'):
            lines = _BoundedLines(text, limit)
            for number, line in enumerate(lines, 1):
                lines.record_chars = 0
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except (ValueError, RecursionError) as exc:
                    raise StructuredReadError(f'JSONL line {number}: {exc}') from exc
        elif fmt in ('.csv', '.tsv'):
            lines = _BoundedLines(text, limit)
            reader = csv.reader(lines, delimiter='\t' if fmt == '.tsv' else ',', strict=True)
            for row in reader:
                lines.record_chars = 0
                if sum(len(field) for field in row) > limit:
                    raise StructuredReadError('CSV record exceeds limit')
                yield row
        else:
            raise StructuredReadError(f'unsupported structured format: {fmt}')
    except (UnicodeError, csv.Error, RecursionError) as exc:
        raise StructuredReadError(f'{fmt} parse error: {exc}') from exc
    finally:
        text.detach()


_DOCUMENT_PATTERNS = {
    '.docx': (r'word/document\.xml',),
    '.pptx': (r'ppt/slides/slide\d+\.xml',),
    '.xlsx': (r'xl/sharedStrings\.xml', r'xl/worksheets/sheet\d+\.xml'),
    '.odt': (r'content\.xml',),
}


def _target_records(target, stream, fmt, limit):
    if fmt in _DOCUMENT_PATTERNS or fmt == '.pdf':
        if _parse_zip_target(target) or _parse_tar_target(target):
            raise StructuredReadError('nested document extraction is not supported')
        from .indexer import _stream_ooxml, _stream_pdf
        path = expand(target)
        try:
            yield from _stream_pdf(path) if fmt == '.pdf' else _stream_ooxml(path, _DOCUMENT_PATTERNS[fmt])
        except (OSError, ValueError) as exc:
            raise StructuredReadError(f'document extraction failed: {exc}') from exc
    else:
        yield from _records(stream, fmt, limit)


def read_batch(target: str, *, cursor: dict | None = None, max_records: int = 100,
               max_record_chars: int = 1_000_000, protected: list[str],
               never_send_roots: list[str], cloud_bound: bool = False) -> dict:
    """Read a bounded page. EOF means parsing and trailing-data validation succeeded."""
    if not 1 <= max_records <= 1000 or not 256 <= max_record_chars <= 2_000_000:
        raise ValueError('invalid record bounds')
    cursor = cursor or {}
    offset = cursor.get('record', 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError('invalid cursor')
    sha = _hash(target, protected, never_send_roots, cloud_bound)
    if cursor and cursor.get('sha256') != sha:
        raise StructuredReadError('source changed since previous batch')
    fmt = Path(target.split('#')[-1]).suffix.lower()
    page = []
    page_chars = 0
    eof = True
    with _source(target, protected, never_send_roots, cloud_bound) as stream:
        for index, record in enumerate(_target_records(target, stream, fmt, max_record_chars)):
            if index < offset:
                continue
            record_chars = len(json.dumps(record, ensure_ascii=False))
            if record_chars > max_record_chars:
                raise StructuredReadError('record exceeds limit')
            if len(page) == max_records or (page and page_chars + record_chars > max_record_chars):
                eof = False
                break
            page.append(record)
            page_chars += record_chars
    if _hash(target, protected, never_send_roots, cloud_bound) != sha:
        raise StructuredReadError('source changed during read')
    return {'records': page, 'next_cursor': None if eof else {'record': offset + len(page), 'sha256': sha},
            'eof': eof, 'sha256': sha, 'format': fmt.lstrip('.'), 'trusted': False}


def inspect(target: str, **kwargs) -> dict:
    """Inspect a sample without pretending a partial file is fully validated."""
    batch = read_batch(target, max_records=1, **kwargs)
    sample = batch['records'][0] if batch['records'] else None
    return {'format': batch['format'], 'sha256': batch['sha256'], 'trusted': False,
            'complete': batch['eof'], 'sample_type': type(sample).__name__,
            'sample': repr(sample)[:512] if sample is not None else None}


def validate(target: str, *, protected: list[str], never_send_roots: list[str],
             cloud_bound: bool = False, max_record_chars: int = 1_000_000,
             expected_sha256: str | None = None) -> dict:
    """Validate every record in one streaming pass, without collecting values."""
    if not 256 <= max_record_chars <= 2_000_000:
        raise ValueError('invalid record bound')
    sha = _hash(target, protected, never_send_roots, cloud_bound)
    if expected_sha256 and sha != expected_sha256:
        raise StructuredReadError('source changed since read')
    fmt = Path(target.split('#')[-1]).suffix.lower()
    count = 0
    with _source(target, protected, never_send_roots, cloud_bound) as stream:
        for _ in _target_records(target, stream, fmt, max_record_chars):
            count += 1
    if _hash(target, protected, never_send_roots, cloud_bound) != sha:
        raise StructuredReadError('source changed during validation')
    return {'format': fmt.lstrip('.'), 'records': count, 'sha256': sha,
            'complete': True, 'trusted': False}
