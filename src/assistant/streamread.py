"""Bounded streaming reads & structural inspection of large/structured files.

GAP-3 (`reports/RPT-B-scavenger-gaps-20261125T161536Z.md` §1.3): the old reader
did `path.read_text(...)[:200_000]` — it loaded a whole multi-hundred-MB file
into RAM and then *silently* discarded everything past character 200,000 while
recording `status='indexed'`. A 150 MB ledger, a 500 MB JSON export, or a log
tail was therefore unusable, and the loss was invisible (violating `I1`).

This module replaces "read the file and slice the string" with three
primitives that every reader in the tree can share:

* ``inspect(target)`` — a **structural skeleton** in under ~2 KB: container
  type, record count (exact when cheap, otherwise labelled an estimate),
  recurring field paths with their value types, and one bounded sample
  record. Zero model tokens; it is how a caller decides *whether* to read.
* ``read_batch(target, cursor, byte_budget)`` — **bounded record streaming**:
  parses whole records (JSON values, JSONL lines, CSV rows, prose lines,
  archive members, SQLite rows) until the byte budget is spent, returning
  ``(records, next_cursor, bytes_read, eof)``. Memory stays proportional to
  one record, never to the file. A cursor is opaque JSON and round-trips
  through SQLite, so a read can pause and resume without re-reading prefix
  bytes.
* ``read_window(...)`` — the same stream rendered as human/LLM text, aligned
  to record boundaries so a window never ends mid-value or mid-CSV-row.

Failure is loud (`StreamError`, naming the stage and byte offset). Nothing is
silently truncated: a batch that stops early says so, and `eof` is only true
when the stream really ended.

Everything here reads **untrusted data**. `trusted` is pinned `False` on every
envelope, `[policy] protected` paths and symlinked paths are refused before a
byte is read, and `[privacy] never_send_to_cloud` travels with the envelope so
no cloud caller can forget it (§10.7 / `IF-6`).

Formats: text/Markdown/log, JSON, JSONL/NDJSON, CSV/TSV, HTML/XML, SQLite
(read-only URI), OOXML (docx/xlsx/pptx/odt), and members of zip/tar archives
read through ``ZipExtFile``/``ExFileObject`` without extraction. PDF is
inspected for metadata but refused for streaming (page-aware extraction is a
different, larger build) — refused loudly, never faked.
"""

from __future__ import annotations

import codecs
import contextlib
import csv
import hashlib
import io
import json
import re
import sqlite3
import stat as stat_mod
import tarfile
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .discovery import (
    STRUCTURED_SUFFIXES,
    _has_symlink_component,
    _safe_member_name,
    archive_kind,
    expand,
    is_never_send,
)
from .safety import is_protected

# -- code-level caps (never silent, always reported) ------------------------
MAX_RECORD_CHARS: int = 4 * 1024 * 1024      # one record may not exceed this
MAX_SKELETON_BYTES: int = 4096               # inspect() never buffers more
MAX_SKELETON_FIELDS: int = 16
MAX_SKELETON_DEPTH: int = 4
MAX_SAMPLE_RECORDS: int = 40

TEXT_FORMATS: frozenset[str] = frozenset({"text", "markdown", "log", "code"})
LINE_FORMATS: frozenset[str] = frozenset({"jsonl", "ndjson"})

_OOXML_PRIMARY: dict[str, tuple[str, ...]] = {
    ".docx": ("word/document.xml",),
    ".odt": ("content.xml",),
    ".pptx": ("ppt/slides/",),
    ".xlsx": ("xl/sharedStrings.xml", "xl/worksheets/sheet1.xml"),
}

#: Key names whose *values* are masked in skeletons and batches unless the
#: caller explicitly opts out. Untrusted files routinely contain credentials;
#: a structural preview must not become a credential exfiltration path.
SENSITIVE_KEY_RE = re.compile(
    r"(?:pass(?:word|phrase)?|secret|token|api[_-]?key|apikey|private[_-]?key|"
    r"credential|auth|cookie|session[_-]?id|salt|otp|pin|cvv|cvc|card[_-]?number|"
    r"account[_-]?number|iban|ssn|routing[_-]?number)",
    re.IGNORECASE,
)
REDACTED = "[redacted]"

_TAG_RE = re.compile(r"<[^>]{0,4000}>")
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"[ \t\r\f\v]+")


class StreamError(RuntimeError):
    """A read failed at a named stage and byte offset. Never silent (I1)."""

    def __init__(self, stage: str, message: str, *, offset: int | None = None,
                 target: str | None = None):
        self.stage = stage
        self.message = message
        self.offset = offset
        self.target = target
        parts = [stage]
        if target:
            parts.append(f"target={target}")
        if offset is not None:
            parts.append(f"offset={offset}")
        parts.append(message)
        super().__init__(": ".join(parts))

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "message": self.message,
            "offset": self.offset,
            "target": self.target,
        }


# ---------------------------------------------------------------------------
# Target grammar & the single read gate
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Target:
    """A resolved read target: a path, or a member inside an archive."""

    path: Path
    member: str | None = None
    archive_kind: str | None = None

    @property
    def is_member(self) -> bool:
        return self.member is not None

    @property
    def label(self) -> str:
        return f"zip://{self.path}#{self.member}" if self.is_member else str(self.path)

    @property
    def suffix(self) -> str:
        return Path(self.member or self.path).suffix.lower()


def parse_target(raw: str | Path) -> Target:
    """Parse `path` or `zip://archive#member` into a Target (validated)."""
    text = str(raw)
    if text.startswith("zip://"):
        rest = text[len("zip://"):]
        if "#" not in rest:
            raise StreamError(
                "parse", "archive target must be zip://<archive>#<member>", target=text)
        archive, member = rest.split("#", 1)
        safe = _safe_member_name(member)
        if safe is None:
            raise StreamError(
                "parse", f"refused unsafe archive member name {member!r}", target=text)
        path = expand(archive)
        return Target(path=path, member=safe, archive_kind=archive_kind(path) or "zip")
    return Target(path=expand(text))


def file_size(target: Target) -> int:
    """Size of the target itself (member size for archive members)."""
    if target.is_member:
        if target.archive_kind == "tar":
            import tarfile

            with tarfile.open(target.path, mode="r|*") as tf:
                for info in tf:
                    if _safe_member_name(info.name) == target.member and info.isfile():
                        return int(info.size)
            raise StreamError("stat", "member not found in tar", target=target.label)
        with zipfile.ZipFile(target.path, "r") as zf:
            try:
                return int(zf.getinfo(target.member).file_size)
            except KeyError as exc:
                raise StreamError("stat", "member not found in archive",
                                  target=target.label) from exc
    try:
        return int(target.path.lstat().st_size)
    except OSError as exc:
        raise StreamError("stat", f"{type(exc).__name__}: {exc}",
                          target=target.label) from exc


def _check_policy(target: Target, protected: Iterable[str],
                  never_send_roots: Iterable[str]) -> bool:
    """Refuse protected/symlinked/irregular targets before reading a byte.

    Returns whether the target is inside `never_send_to_cloud`.
    """
    protected_list = list(protected)
    if _has_symlink_component(target.path):
        raise StreamError("policy", "refused: symlink in target path",
                          target=target.label)
    if is_protected(target.path, protected_list):
        raise StreamError("policy", "refused: protected path", target=target.label)
    try:
        st = target.path.lstat()
    except OSError as exc:
        raise StreamError("policy", f"{type(exc).__name__}: {exc}",
                          target=target.label) from exc
    if not stat_mod.S_ISREG(st.st_mode):
        raise StreamError("policy", "refused: not a regular file",
                          target=target.label)
    if target.is_member:
        if target.archive_kind == "zip":
            try:
                with zipfile.ZipFile(target.path, "r") as zf:
                    zf.getinfo(target.member)
            except KeyError as exc:
                raise StreamError("policy", "member not found",
                                  target=target.label) from exc
            except (zipfile.BadZipFile, OSError) as exc:
                raise StreamError("policy", f"{type(exc).__name__}: {exc}",
                                  target=target.label) from exc
        elif target.archive_kind == "tar":
            try:
                with tarfile.open(target.path, mode="r|*") as tf:
                    found = any(
                        _safe_member_name(i.name) == target.member and i.isfile()
                        for i in tf
                    )
            except (tarfile.TarError, OSError) as exc:
                raise StreamError("policy", f"{type(exc).__name__}: {exc}",
                                  target=target.label) from exc
            if not found:
                raise StreamError("policy", "member not found", target=target.label)
    return is_never_send(target.path, never_send_roots)


@contextlib.contextmanager
def open_target(target: Target, *, protected: Iterable[str] = (),
                never_send_roots: Iterable[str] = ()) -> Iterator[io.BufferedIOBase]:
    """Open one readable binary stream — the only place this module opens files.

    Archive members stream straight out of the container (`ZipExtFile` /
    `ExFileObject`); nothing is ever written to disk.
    """
    _check_policy(target, protected, never_send_roots)
    if target.is_member:
        if target.archive_kind == "tar":
            import tarfile

            tf = tarfile.open(target.path, mode="r|*")  # noqa: SIM115 -- closed in finally
            try:
                for info in tf:
                    if _safe_member_name(info.name) == target.member and info.isfile():
                        extracted = tf.extractfile(info)
                        if extracted is None:
                            raise StreamError(
                                "open", "tar member has no readable body",
                                target=target.label)
                        try:
                            yield extracted  # type: ignore[misc]
                        finally:
                            extracted.close()
                        return
            finally:
                tf.close()
            raise StreamError("open", "member not found", target=target.label)
        zf = zipfile.ZipFile(target.path, "r")
        try:
            try:
                info = zf.getinfo(target.member)
            except KeyError as exc:
                raise StreamError("open", "member not found",
                                  target=target.label) from exc
            if info.file_size > 0 and info.compress_size > 0:
                ratio = info.file_size / max(1, info.compress_size)
                if ratio > 100.0:
                    raise StreamError(
                        "open",
                        f"refused: compression ratio {ratio:.0f}x exceeds guard "
                        "(zip-bomb posture)", target=target.label)
            with zf.open(info, "r") as stream:
                yield stream  # type: ignore[misc]
        finally:
            zf.close()
        return
    try:
        handle = target.path.open("rb")
    except OSError as exc:
        raise StreamError("open", f"{type(exc).__name__}: {exc}",
                          target=target.label) from exc
    try:
        yield handle
    finally:
        handle.close()


def target_digest(target: Target, *, protected: Iterable[str] = (),
                  never_send_roots: Iterable[str] = (),
                  head_bytes: int = 1 << 20) -> tuple[str, str]:
    """`(digest, scope)` for a target. `scope` is `full` or `head:<n>+size`."""
    with open_target(target, protected=protected,
                     never_send_roots=never_send_roots) as stream:
        digest = hashlib.sha256()
        total = 0
        scoped = False
        while True:
            block = stream.read(1 << 20)
            if not block:
                break
            total += len(block)
            if total <= head_bytes:
                digest.update(block)
            else:
                scoped = True
                remaining = head_bytes - (total - len(block))
                if remaining > 0:
                    digest.update(block[:remaining])
                break
        if scoped:
            # Identity is prefix + true size; the scope string says so.
            try:
                size = file_size(target)
            except StreamError:
                size = total
            digest.update(f"|size={size}".encode())
            return digest.hexdigest(), f"head:{head_bytes}+size"
        return digest.hexdigest(), "full"


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------
def detect_format(label: str | Path) -> str:
    """Map a name to a reader format. Pure string logic, no I/O."""
    text = str(label)
    if text.startswith("zip://"):
        text = text.split("#", 1)[-1]
    path = Path(text)
    suffix = path.suffix.lower()
    name = path.name.lower()
    if suffix == ".zip" or suffix in (".jar", ".whl", ".epub"):
        return "zip"
    if archive_kind(text) == "tar":
        return "tar"
    if suffix in (".json",):
        return "json"
    if suffix in (".jsonl", ".ndjson"):
        return "jsonl"
    if suffix in (".csv",):
        return "csv"
    if suffix in (".tsv", ".tab"):
        return "tsv"
    if suffix in (".html", ".htm", ".xhtml"):
        return "html"
    if suffix == ".xml":
        return "xml"
    if suffix in (".sqlite", ".sqlite3", ".db"):
        return "sqlite"
    if suffix in _OOXML_PRIMARY:
        return suffix.lstrip(".")
    if suffix == ".pdf":
        return "pdf"
    if suffix in (".md", ".markdown", ".rst", ".org"):
        return "markdown"
    if suffix in (".log",):
        return "log"
    if suffix == ".txt":
        return "text"
    if name.endswith((".log", ".log.gz")):
        return "log"
    if suffix in STRUCTURED_SUFFIXES:
        return "text"
    return "text"


# ---------------------------------------------------------------------------
# Redaction & projection (applied before any record leaves this module)
# ---------------------------------------------------------------------------
def _redact_value(value: Any, key: str | None = None) -> Any:
    if key is not None and SENSITIVE_KEY_RE.search(str(key)):
        return REDACTED
    if isinstance(value, dict):
        return {k: _redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


def _project_value(value: Any, projection: list[str] | None) -> Any:
    """Keep only the top-level fields a caller asked for (schema projection)."""
    if not projection or not isinstance(value, dict):
        return value
    kept: dict[str, Any] = {}
    for path in projection:
        head = path.split(".", 1)[0].split("[", 1)[0]
        if head in value:
            kept[head] = value[head]
    return kept or value


# ---------------------------------------------------------------------------
# Bounded text feeder (JSON parsing over a byte stream)
# ---------------------------------------------------------------------------
class _TextFeeder:
    """Decodes a binary stream incrementally, tracking exact byte offsets.

    Strict UTF-8: a malformed byte is a corrupt structured file and raises
    loudly with its offset — never a silent replacement character (I1).
    """

    def __init__(self, stream, *, chunk: int = 65536):
        self._stream = stream
        self._decoder = codecs.getincrementaldecoder("utf-8")("strict")
        self._chunk = chunk
        self.text = ""
        self.base = 0          # byte offset of text[0]
        self.read_bytes = 0    # bytes pulled from the stream
        self.eof = False

    def _pull(self) -> bool:
        if self.eof:
            return False
        try:
            raw = self._stream.read(self._chunk)
        except OSError as exc:
            raise StreamError("read", f"{type(exc).__name__}: {exc}",
                              offset=self.base + len(self.text)) from exc
        if not raw:
            try:
                tail = self._decoder.decode(b"", final=True)
            except UnicodeDecodeError as exc:
                raise StreamError(
                    "decode", f"invalid UTF-8 at offset {self.base + len(self.text)}: "
                    f"{exc.reason}", offset=self.base + len(self.text)) from exc
            self.text += tail
            self.eof = True
            return False
        self.read_bytes += len(raw)
        try:
            self.text += self._decoder.decode(raw)
        except UnicodeDecodeError as exc:
            raise StreamError(
                "decode", f"invalid UTF-8 near offset "
                f"{self.base + len(self.text)}: {exc.reason}",
                offset=self.base + len(self.text)) from exc
        return True

    def byte_pos(self, char_index: int) -> int:
        return self.base + len(self.text[:char_index].encode("utf-8"))

    def ensure(self, chars: int) -> bool:
        while len(self.text) < chars and not self.eof:
            if not self._pull():
                break
        return len(self.text) >= chars or self.eof

    def consume(self, char_index: int) -> None:
        if char_index <= 0:
            return
        self.base = self.byte_pos(char_index)
        self.text = self.text[char_index:]

    def fill_more(self) -> bool:
        return self._pull()


# ---------------------------------------------------------------------------
# JSON record iteration (array elements / object entries / one scalar)
# ---------------------------------------------------------------------------
class _JSONRecordStream:
    """Stream whole JSON values from a binary reader with byte-accurate cursors.

    Supports the three shapes a real export takes: a top-level array of
    records, a top-level object of records, or one scalar value. Nested
    structures are handed over whole (bounded by ``MAX_RECORD_CHARS``).
    """

    def __init__(self, stream, *, container: str | None = None,
                 start_offset: int = 0, allow_leading_comma: bool = False):
        self.feeder = _TextFeeder(stream)
        self.container = container
        self.allow_leading_comma = allow_leading_comma
        self._index = 0
        self._opened = False
        if start_offset:
            self._seek_to(start_offset)

    def _seek_to(self, offset: int) -> None:
        stream = self.feeder._stream
        try:
            stream.seek(offset)  # type: ignore[attr-defined]
        except (AttributeError, OSError, io.UnsupportedOperation):
            # Non-seekable member stream: consume forward, byte-exactly.
            remaining = offset
            while remaining > 0:
                block = stream.read(min(65536, remaining))
                if not block:
                    raise StreamError(
                        "seek", f"stream ended before offset {offset}",
                        offset=offset)
                remaining -= len(block)
            self.feeder.base = offset
            self.feeder.read_bytes = offset
        else:
            self.feeder.base = offset
            self.feeder.read_bytes = offset
        self.feeder.text = ""

    # -- low level ---------------------------------------------------------
    def _skip_ws(self, idx: int = 0, *, allow_comma: bool = False) -> int:
        while True:
            self.feeder.ensure(idx + 1)
            n = len(self.feeder.text)
            while idx < n and self.feeder.text[idx] in " \t\r\n":
                idx += 1
            if idx < n:
                if allow_comma and self.feeder.text[idx] == ",":
                    idx += 1
                    allow_comma = False
                    continue
                return idx
            if self.feeder.eof:
                return idx
            self.feeder.fill_more()

    def _decode_value(self, idx: int) -> tuple[Any, int]:
        decoder = json.JSONDecoder()
        while True:
            try:
                return decoder.raw_decode(self.feeder.text, idx)
            except json.JSONDecodeError as exc:
                incomplete = exc.msg.startswith("Unterminated") or (
                    exc.pos >= len(self.feeder.text) - 2)
                if not incomplete:
                    raise StreamError(
                        "parse",
                        f"invalid JSON ({exc.msg}) at offset "
                        f"{self.feeder.byte_pos(exc.pos)}",
                        offset=self.feeder.byte_pos(exc.pos)) from exc
                if self.feeder.eof:
                    raise StreamError(
                        "parse",
                        f"truncated JSON ({exc.msg}) at end of stream "
                        f"(offset {self.feeder.byte_pos(exc.pos)})",
                        offset=self.feeder.byte_pos(exc.pos)) from exc
                if len(self.feeder.text) - idx > MAX_RECORD_CHARS:
                    raise StreamError(
                        "parse",
                        f"one JSON record exceeds the {MAX_RECORD_CHARS}-char "
                        "cap; split the file or raise the cap deliberately",
                        offset=self.feeder.byte_pos(idx)) from exc
                if not self.feeder.fill_more():
                    raise StreamError(
                        "parse", "truncated JSON at end of stream",
                        offset=self.feeder.byte_pos(exc.pos)) from exc

    def _open_container(self) -> None:
        idx = self._skip_ws(0)
        if idx >= len(self.feeder.text):
            self.container = "empty"
            self._opened = True
            return
        self.feeder.consume(idx)
        self.container = "scalar"
        self.feeder.ensure(1)
        self._opened = True
        first = self.feeder.text[:1]
        if first == "[":
            self.container = "array"
            self.feeder.consume(1)
        elif first == "{":
            self.container = "object"
            self.feeder.consume(1)

    def close_container(self) -> None:
        """Reject trailing content instead of certifying a valid prefix as EOF."""
        idx = self._skip_ws(0)
        if idx < len(self.feeder.text):
            raise StreamError("parse", "trailing content after JSON document",
                              offset=self.feeder.byte_pos(idx))
        self.feeder.consume(idx)

    # -- public ------------------------------------------------------------
    def records(self, *, byte_budget: int, record_limit: int,
                allow_partial: bool = False) -> tuple[
            list[dict[str, Any]], int, bool]:
        """Read up to `record_limit` whole records within `byte_budget` bytes.

        Returns `(records, next_offset, eof)`. At least one record is always
        attempted so a record larger than the budget still makes progress
        (and is reported, not dropped). `allow_partial=True` keeps the records
        that parsed before a truncated sample ended mid-value (used by
        `inspect()`); a real read never passes it, so corruption stays loud.
        """
        # A fresh stream starts at byte 0 with its opening bracket unread; a
        # resumed cursor starts *after* a record, so the shape comes from the
        # cursor instead (re-reading it would mis-parse the bracket).
        if not self._opened and self.feeder.base == 0:
            self._open_container()
        out: list[dict[str, Any]] = []
        budget = max(1, int(byte_budget))
        consumed_start = self.feeder.base
        eof = False

        if self.container in ("empty", "scalar"):
            idx = self._skip_ws(0)
            if self.container == "empty" or idx >= len(self.feeder.text):
                return out, self.feeder.byte_pos(len(self.feeder.text)), True
            value, end = self._decode_value(idx)
            offset = self.feeder.byte_pos(end)
            self.feeder.consume(end)
            self.close_container()
            offset = self.feeder.byte_pos(0)
            out.append({"kind": "value", "index": 0, "value": value,
                        "text": _record_text(value)})
            return out, offset, True

        skip_comma = self.allow_leading_comma
        limit = max(1, int(record_limit))
        while len(out) < limit:
            try:
                idx = self._skip_ws(0)
                closing = "]" if self.container == "array" else "}"
                if idx < len(self.feeder.text) and self.feeder.text[idx] == closing:
                    self.feeder.consume(idx + 1)
                    self.close_container()
                    eof = True
                    break
                if skip_comma:
                    if self.feeder.text[idx:idx + 1] != ",":
                        raise StreamError("parse", "expected comma between JSON records",
                                          offset=self.feeder.byte_pos(idx))
                    idx = self._skip_ws(idx + 1)
                    if self.feeder.text[idx:idx + 1] == closing:
                        raise StreamError("parse", "trailing comma in JSON container",
                                          offset=self.feeder.byte_pos(idx))
                skip_comma = False
                if idx >= len(self.feeder.text):
                    # Whitespace to EOF: a container that never closed.
                    if self.feeder.eof:
                        raise StreamError(
                            "parse",
                            f"unterminated JSON {self.container}: no closing bracket",
                            offset=self.feeder.byte_pos(idx))
                    self.feeder.fill_more()
                    continue
                if self.container == "object":
                    if self.feeder.text[idx] != '"':
                        raise StreamError(
                            "parse", "object member must start with a quoted key",
                            offset=self.feeder.byte_pos(idx))
                    key, key_end = self._decode_value(idx)
                    idx = self._skip_ws(key_end)
                    if idx >= len(self.feeder.text):
                        raise StreamError(
                            "parse", "object member missing value",
                            offset=self.feeder.byte_pos(key_end))
                    if self.feeder.text[idx] != ":":
                        raise StreamError(
                            "parse", "object member missing ':'",
                            offset=self.feeder.byte_pos(idx))
                    value, end = self._decode_value(self._skip_ws(idx + 1))
                    record = {"kind": "field", "index": self._index, "key": key,
                              "value": value, "text": _record_text({key: value})}
                else:
                    value, end = self._decode_value(idx)
                    record = {"kind": "item", "index": self._index, "value": value,
                              "text": _record_text(value)}
            except StreamError:
                if allow_partial and out:
                    break
                raise
            self._index += 1
            offset = self.feeder.byte_pos(end)
            self.feeder.consume(end)
            out.append(record)
            if offset - consumed_start >= budget:
                # Budget spent exactly at a record boundary: clean pause point.
                nxt = self._skip_ws(0)
                self.feeder.consume(nxt)
                return out, self.feeder.byte_pos(0), False
            skip_comma = True

        # The record limit stopped us, not the container: park the cursor
        # exactly after the last whole record (never mid-value).
        nxt = self._skip_ws(0)
        self.feeder.consume(nxt)
        closing = "]" if self.container == "array" else "}"
        if not eof and self.feeder.text[:1] == closing:
            self.feeder.consume(1)
            self.close_container()
            eof = True
        return out, self.feeder.byte_pos(0), eof


#: How many chars of one record reach a reader/prompt. `record_limit` bounds
#: how many records a batch holds; this bounds how big any one of them is, so
#: a single 300 KB JSON record cannot blow a prompt budget (GAP-4 packing).
RECORD_TEXT_LIMIT: int = 2000


def _record_text(value: Any, *, limit: int | None = None) -> str:
    if limit is None:
        limit = RECORD_TEXT_LIMIT
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=False, default=str)
    except (TypeError, ValueError):
        text = repr(value)
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------------------------------------------------------------------
# Skeleton builders
# ---------------------------------------------------------------------------
def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "map"
    return type(value).__name__


def _walk_fields(value: Any, prefix: str = "$", depth: int = 0,
                 acc: dict[str, dict[str, Any]] | None = None,
                 redact: bool = True) -> dict[str, dict[str, Any]]:
    """Collect recurring field paths + value types from one sample record."""
    if acc is None:
        acc = {}
    if depth > MAX_SKELETON_DEPTH:
        return acc
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}"
            shown = REDACTED if (redact and SENSITIVE_KEY_RE.search(str(key))) else child
            entry = acc.setdefault(path, {"path": path, "types": set(), "count": 0})
            entry["types"].add(_type_name(shown))
            entry["count"] += 1
            _walk_fields(shown, path, depth + 1, acc, redact)
    elif isinstance(value, list):
        path = f"{prefix}[]"
        entry = acc.setdefault(path, {"path": path, "types": set(), "count": 0})
        entry["types"].add(_type_name(value))
        entry["count"] += 1
        for child in value[:3]:
            _walk_fields(child, path, depth + 1, acc, redact)
    return acc


def _finish_fields(acc: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(acc.values(), key=lambda e: (-e["count"], e["path"]))
    return [
        {"path": e["path"], "types": sorted(e["types"]), "count": e["count"]}
        for e in ordered[:MAX_SKELETON_FIELDS]
    ]


def _skeleton_json(stream, *, sample_bytes: int, redact: bool) -> dict[str, Any]:
    sample = stream.read(sample_bytes)
    truncated_sample = len(sample) >= sample_bytes
    meta: dict[str, Any] = {
        "format": "json",
        "sample_bytes": len(sample),
        "sample_truncated": truncated_sample,
    }
    try:
        text = sample.decode("utf-8")
    except UnicodeDecodeError as exc:
        meta["parse_error"] = f"invalid UTF-8 near byte {exc.start}: {exc.reason}"
        meta["container"] = "unknown"
        return meta
    lead = text.lstrip()
    container = (
        "array" if lead.startswith("[") else
        "object" if lead.startswith("{") else
        "empty" if not lead else "scalar"
    )
    meta["container"] = container
    if container == "empty":
        meta["estimate"] = {"records_min": 0}
        return meta

    # Parse as many whole records as the sample allows — never more.
    feeder_stream = io.BytesIO(sample)
    reader = _JSONRecordStream(feeder_stream)
    try:
        records, _next, _eof = reader.records(
            byte_budget=sample_bytes, record_limit=MAX_SAMPLE_RECORDS,
            allow_partial=True)
    except StreamError as exc:
        meta["parse_error"] = exc.message
        meta["parse_error_offset"] = exc.offset
        return meta
    if truncated_sample:
        meta["note"] = "sample ends mid-record; counts are a lower bound"
    acc: dict[str, dict[str, Any]] = {}
    sample_record: Any = None
    for record in records:
        if record["kind"] == "field":
            acc.setdefault("$", {"path": "$", "types": {"map"}, "count": 0})["count"] += 1
            _walk_fields({record["key"]: record["value"]}, "$", 0, acc, redact)
            if sample_record is None:
                sample_record = {record["key"]: record["value"]}
        else:
            _walk_fields(record["value"], "$", 0, acc, redact)
            if sample_record is None:
                sample_record = record["value"]
    meta["fields"] = _finish_fields(acc)
    meta["records_in_sample"] = len(records)
    meta["estimate"] = {
        "records_min": len(records),
        "exact": False if truncated_sample else None,
    }
    if sample_record is not None:
        shown = _redact_value(sample_record) if redact else sample_record
        meta["sample"] = _record_text(shown, limit=400)
    return meta


def _skeleton_lines(text: str, *, fmt: str, redact: bool,
                    sample_rows: int = 3) -> dict[str, Any]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    meta: dict[str, Any] = {
        "format": fmt,
        "records_in_sample": len(lines),
        "estimate": {"records_min": len(lines)},
    }
    if fmt in ("jsonl", "ndjson"):
        acc: dict[str, dict[str, Any]] = {}
        parsed = 0
        for line in lines[:MAX_SAMPLE_RECORDS]:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                meta.setdefault("bad_lines_in_sample", 0)
                meta["bad_lines_in_sample"] += 1
                continue
            parsed += 1
            _walk_fields(value, "$", 0, acc, redact)
            if "sample" not in meta:
                shown = _redact_value(value) if redact else value
                meta["sample"] = _record_text(shown, limit=400)
        meta["parsed_in_sample"] = parsed
        meta["fields"] = _finish_fields(acc)
        return meta
    if fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            meta["columns"] = []
            return meta
        rows = []
        ragged = 0
        for row in reader:
            if len(row) != len(header):
                ragged += 1
            rows.append(row)
            if len(rows) >= sample_rows:
                break
        meta["columns"] = list(header)
        meta["sensitive_columns"] = [
            c for c in header if redact and SENSITIVE_KEY_RE.search(c)
        ]
        meta["rows_in_sample"] = len(rows)
        meta["ragged_rows_in_sample"] = ragged
        meta["sample"] = (
            {
                c: (REDACTED if (redact and SENSITIVE_KEY_RE.search(c)) else rows[0][i])
                for i, c in enumerate(header)
                if i < len(rows[0])
            }
            if rows else None
        )
        return meta
    meta["sample"] = "\n".join(lines[:3])[:400]
    meta["line_lengths"] = {
        "max": max((len(ln) for ln in lines[:1000]), default=0),
        "avg": round(sum(len(ln) for ln in lines[:1000]) / max(1, len(lines[:1000])), 1),
    }
    return meta


def _skeleton_html(text: str) -> dict[str, Any]:
    stripped = _SCRIPT_RE.sub(" ", text)
    body = _TAG_RE.sub(" ", stripped)
    body = _WS_RE.sub(" ", body).strip()
    counts: dict[str, int] = {}
    for match in re.finditer(r"<([A-Za-z][A-Za-z0-9]*)\b", text):
        tag = match.group(1).lower()
        counts[tag] = counts.get(tag, 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    return {
        "format": "html",
        "elements": {f"<{tag}>": n for tag, n in top},
        "text_chars_in_sample": len(body),
        "sample": body[:400],
    }


def _skeleton_sqlite(path: Path) -> dict[str, Any]:
    uri = f"file:{path}?mode=ro&immutable=1"
    tables: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        return {"format": "sqlite", "parse_error": f"{type(exc).__name__}: {exc}"}
    try:
        names = [
            str(r[0]) for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 64")
        ]
        for name in names:
            try:
                cols = [str(r[1]) for r in conn.execute(
                    f'PRAGMA table_info("{name.replace(chr(34), "")}")')]
                rows = int(conn.execute(
                    f'SELECT COUNT(*) FROM "{name.replace(chr(34), "")}"'
                ).fetchone()[0])
            except sqlite3.Error:
                cols, rows = [], -1
            tables.append({"table": name, "columns": cols[:32], "rows": rows})
    except sqlite3.Error as exc:
        return {"format": "sqlite", "parse_error": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()
    return {"format": "sqlite", "tables": tables, "read_only": True}


def _ooxml_member(target: Target) -> tuple[Path, str] | None:
    """Resolve the primary XML member of an OOXML target."""
    suffix = target.suffix
    patterns = _OOXML_PRIMARY.get(suffix)
    if not patterns:
        return None
    if target.is_member:
        return target.path, target.member
    try:
        with zipfile.ZipFile(target.path, "r") as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError) as exc:
        raise StreamError("open", f"{type(exc).__name__}: {exc}",
                          target=target.label) from exc
    for pattern in patterns:
        if pattern.endswith("/"):
            for name in names:
                if name.startswith(pattern) and name.endswith(".xml"):
                    return target.path, name
        elif pattern in names:
            return target.path, pattern
    return None


# ---------------------------------------------------------------------------
# inspect()
# ---------------------------------------------------------------------------
@dataclass
class Inspection:
    target: str
    format: str
    size: int
    never_send: bool
    digest: str
    digest_scope: str
    skeleton: dict[str, Any] = field(default_factory=dict)
    parse_error: str | None = None
    notes: list[str] = field(default_factory=list)
    trusted: bool = False

    def __post_init__(self) -> None:
        if self.trusted is not False:
            raise ValueError("IF-6 violation: Inspection.trusted must always be False")

    def as_dict(self) -> dict[str, Any]:
        out = {
            "target": self.target,
            "format": self.format,
            "size": self.size,
            "never_send": self.never_send,
            "digest": self.digest,
            "digest_scope": self.digest_scope,
            "skeleton": self.skeleton,
            "parse_error": self.parse_error,
            "notes": self.notes,
            "trusted": False,
        }
        return out


def inspect(target: str | Path, *, protected: Iterable[str] = (),
            never_send_roots: Iterable[str] = (),
            redact: bool = True,
            skeleton_bytes: int = MAX_SKELETON_BYTES) -> Inspection:
    """Structural skeleton of any target in bounded memory. Zero tokens."""
    parsed = parse_target(target)
    never_send = _check_policy(parsed, protected, never_send_roots)
    fmt = detect_format(parsed.label)
    size = file_size(parsed)
    digest, scope = target_digest(parsed, protected=protected,
                                  never_send_roots=never_send_roots)
    result = Inspection(target=parsed.label, format=fmt, size=size,
                        never_send=never_send, digest=digest,
                        digest_scope=scope)
    budget = max(1024, min(int(skeleton_bytes), MAX_SKELETON_BYTES))

    if fmt == "zip":
        from .discovery import Policy, scan_archive

        policy = Policy(roots=(str(parsed.path),),
                        protected=tuple(protected),
                        never_send_roots=tuple(never_send_roots))
        manifest = scan_archive(parsed.path, policy)
        result.skeleton = {
            "format": "zip",
            "members": manifest.as_dict(),
            "sample_members": [m.target for m in manifest.members[:8]],
        }
        if manifest.error:
            result.parse_error = manifest.error
        return result

    if fmt == "tar":
        from .discovery import Policy, scan_archive

        policy = Policy(roots=(str(parsed.path),),
                        protected=tuple(protected),
                        never_send_roots=tuple(never_send_roots))
        manifest = scan_archive(parsed.path, policy)
        result.skeleton = {
            "format": "tar",
            "members": manifest.as_dict(),
            "sample_members": [m.target for m in manifest.members[:8]],
        }
        if manifest.error:
            result.parse_error = manifest.error
        return result

    if fmt == "sqlite" and not parsed.is_member:
        result.skeleton = _skeleton_sqlite(parsed.path)
        result.parse_error = result.skeleton.get("parse_error")
        return result

    if fmt == "pdf":
        result.skeleton = {"format": "pdf", "streamable": False}
        result.notes.append(
            "PDF is inspected for metadata only; page-aware extraction is a "
            "separate build. Streaming this target will fail loudly.")
        return result

    ooxml_member = None
    if fmt in ("docx", "xlsx", "pptx", "odt"):
        try:
            ooxml_member = _ooxml_member(parsed)
        except StreamError as exc:
            result.skeleton = {"format": fmt}
            result.parse_error = exc.message
            return result
        if ooxml_member is None:
            result.skeleton = {"format": fmt}
            result.parse_error = "no primary XML member found"
            return result

    read_target = (
        Target(path=ooxml_member[0], member=ooxml_member[1], archive_kind="zip")
        if ooxml_member else parsed
    )
    with open_target(read_target, protected=protected,
                     never_send_roots=never_send_roots) as stream:
        head = stream.read(budget)
    if ooxml_member is not None:
        text = _strip_xml_runs(head.decode("utf-8", errors="replace"))
        result.skeleton = {
            "format": fmt,
            "member": ooxml_member[1],
            "paragraphs_in_sample": text.count("\n") + 1 if text else 0,
            "text_chars_in_sample": len(text),
            "sample": text[:400],
        }
        return result

    if fmt == "json":
        result.skeleton = _skeleton_json(_BytesReader(head, stream_len=size),
                                         sample_bytes=budget, redact=redact)
        result.parse_error = result.skeleton.get("parse_error")
        return result

    text_sample = head.decode("utf-8", errors="replace")
    if fmt in ("html", "xml"):
        result.skeleton = _skeleton_html(text_sample)
    elif fmt in ("csv", "tsv", "jsonl", "ndjson"):
        result.skeleton = _skeleton_lines(text_sample, fmt=fmt, redact=redact)
    else:
        result.skeleton = _skeleton_lines(
            text_sample, fmt="text", redact=redact)
        result.skeleton["format"] = fmt
    if size > budget:
        result.skeleton["sample_bytes"] = budget
        result.skeleton["estimate"]["exact"] = False
    return result


class _BytesReader:
    """Minimal read-only stream over an already-buffered head plus the rest."""

    def __init__(self, head: bytes, *, stream_len: int = 0):
        self._head = head
        self._pos = 0
        self._len = stream_len

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = len(self._head) - self._pos
        chunk = self._head[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def seek(self, offset: int, whence: int = 0) -> int:
        self._pos = max(0, min(offset, len(self._head)))
        return self._pos


# ---------------------------------------------------------------------------
# read_batch()
# ---------------------------------------------------------------------------
@dataclass
class Batch:
    records: list[dict[str, Any]]
    next_cursor: dict[str, Any]
    bytes_read: int
    eof: bool
    format: str
    total_size: int
    byte_start: int
    byte_end: int
    never_send: bool
    parse_error: str | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "records": self.records,
            "next_cursor": self.next_cursor,
            "bytes_read": self.bytes_read,
            "eof": self.eof,
            "format": self.format,
            "total_size": self.total_size,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "never_send": self.never_send,
            "parse_error": self.parse_error,
            "notes": self.notes,
        }


def _normalise_cursor(cursor: dict[str, Any] | None) -> dict[str, Any]:
    if cursor is None:
        return {}
    if not isinstance(cursor, dict):
        raise StreamError("cursor", f"cursor must be a mapping, got {type(cursor).__name__}")
    offset = cursor.get("offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise StreamError("cursor", f"cursor offset must be a non-negative int, got {offset!r}")
    return cursor


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _line_records(text: str, *, start_line: int = 0) -> list[dict[str, Any]]:
    out = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        out.append({"kind": "line", "index": start_line + i, "text": line})
    return out


def _complete_lines(text: str, *, eof: bool) -> list[str]:
    """Split a byte window into whole lines, discarding a truncated tail.

    The window boundary is a byte offset, so the last line is usually cut in
    half. Emitting that fragment would duplicate it on the next batch (and
    corrupt any CSV/JSONL row it belongs to), so it is held back until the
    window in which it is complete.
    """
    lines = text.splitlines(keepends=True)
    if not eof and lines and not text.endswith(("\n", "\r")):
        return lines[:-1]
    return lines


def _window_line_trim(text: str, raw: bytes) -> tuple[str, int, bool]:
    """Trim a byte window to whole lines; return (text, bytes_kept, split)."""
    if not text.endswith("\n"):
        cut = raw.rfind(b"\n")
        if cut >= 0:
            return _decode(raw[:cut + 1]), cut + 1, False
        return text, len(raw), True
    return text, len(raw), False


def _read_text_style(target: Target, fmt: str, cursor: dict[str, Any], *,
                     byte_budget: int, record_limit: int, projection, redact: bool,
                     protected, never_send_roots) -> Batch:
    offset = int(cursor.get("offset", 0))
    header = cursor.get("header")
    with open_target(target, protected=protected,
                     never_send_roots=never_send_roots) as stream:
        total = file_size(target)
        try:
            stream.seek(offset)  # type: ignore[attr-defined]
        except (AttributeError, OSError, io.UnsupportedOperation):
            remaining = offset
            while remaining > 0:
                block = stream.read(min(65536, remaining))
                if not block:
                    raise StreamError("seek", f"stream ended before offset {offset}",
                                      offset=offset, target=target.label)
                remaining -= len(block)
        raw = stream.read(byte_budget + 1)
    eof_by_read = len(raw) <= byte_budget
    raw = raw[:byte_budget] if not eof_by_read else raw
    text = _decode(raw)
    notes: list[str] = []

    if fmt in ("csv", "tsv"):
        delimiter = "\t" if fmt == "tsv" else ","
        lines = _complete_lines(text, eof=eof_by_read)
        records: list[dict[str, Any]] = []
        consumed = 0
        index = 0
        limit = max(1, record_limit)
        notes_local: list[str] = []
        start_row = int(cursor.get("row", 0))

        def _take_row() -> list[str] | None:
            nonlocal consumed, index
            if index >= len(lines) or (consumed >= byte_budget and consumed > 0):
                return None
            reader = csv.reader(io.StringIO("".join(lines[index:])),
                                delimiter=delimiter, strict=True)
            try:
                row = next(reader)
            except StopIteration:
                return None
            except csv.Error as exc:
                raise StreamError("parse", "CSV row incomplete or malformed; "
                                  "increase byte_budget if it spans the window: " + str(exc),
                                  offset=offset + consumed, target=target.label) from exc
            count = reader.line_num
            consumed += len("".join(lines[index:index + count]).encode("utf-8"))
            index += count
            return row

        if header is None and offset == 0:
            header = _take_row()
            if header is None:
                if not eof_by_read:
                    raise StreamError("read", "CSV header exceeds byte budget",
                                      target=target.label)
                return Batch([], {"offset": total, "header": []}, total, True, fmt,
                             total, 0, total, False)
        header = list(header or [])
        while len(records) < limit:
            row = _take_row()
            if row is None:
                break
            if not any(str(cell).strip() for cell in row):
                continue
            fields = {
                (str(header[j]) if j < len(header) else f"col{j}"): (
                    REDACTED if (redact and j < len(header)
                                 and SENSITIVE_KEY_RE.search(str(header[j])))
                    else cell)
                for j, cell in enumerate(row)
            }
            projected = _project_value(fields, projection)
            records.append({
                "kind": "row",
                "index": start_row + len(records),
                "fields": projected,
                "text": "; ".join(f"{k}={v}" for k, v in projected.items()),
                "ragged": len(row) != len(header),
            })
        eof = eof_by_read and index >= len(lines)
        if index >= len(lines) and not eof_by_read:
            eof = False
        return Batch(records,
                     {"offset": offset + consumed, "header": header,
                      "row": start_row + len(records)},
                     consumed, eof, fmt, total, offset, offset + consumed,
                     False, notes=notes_local)

    if fmt in ("jsonl", "ndjson"):
        lines = _complete_lines(text, eof=eof_by_read)
        records = []
        bad = 0
        consumed = 0
        limit = max(1, record_limit)
        index = 0
        start_line = int(cursor.get("line", 0))
        while index < len(lines) and len(records) < limit:
            if consumed >= byte_budget and consumed > 0:
                break
            line = lines[index]
            consumed += len(line.encode("utf-8"))
            index += 1
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                bad += 1
                records.append({"kind": "line", "index": start_line + index - 1,
                                "text": stripped,
                                "parse_error": f"line {start_line + index - 1}: {exc.msg}"})
                continue
            if redact:
                value = _redact_value(value)
            value = _project_value(value, projection)
            records.append({"kind": "row", "index": start_line + index - 1,
                            "value": value, "text": _record_text(value)})
        eof = eof_by_read and index >= len(lines)
        if bad:
            notes.append(f"{bad} line(s) in this window were not valid JSON")
        return Batch(records, {"offset": offset + consumed,
                               "line": start_line + index}, consumed,
                     eof, fmt, total, offset, offset + consumed, False,
                     notes=notes)

    if fmt in ("html", "xml"):
        kept_text, kept_bytes = text, len(raw)
        if not eof_by_read:
            last = raw.rfind(b">")
            if last >= 0:
                kept_text, kept_bytes = _decode(raw[:last + 1]), last + 1
            else:
                notes.append("no tag boundary inside the byte budget; split markup")
        body = _SCRIPT_RE.sub(" ", kept_text)
        body = _TAG_RE.sub("\n", body)
        body = _WS_RE.sub(" ", body)
        records = [
            {"kind": "text", "index": i, "text": chunk.strip()}
            for i, chunk in enumerate(body.splitlines()) if chunk.strip()
        ][:max(1, record_limit)]
        return Batch(records, {"offset": offset + kept_bytes}, kept_bytes,
                     eof_by_read, fmt, total, offset, offset + kept_bytes, False,
                     notes=notes)

    lines = _complete_lines(text, eof=eof_by_read)
    records = []
    consumed = 0
    index = 0
    limit = max(1, record_limit)
    start_line = int(cursor.get("line", 0))
    while index < len(lines) and len(records) < limit:
        if consumed >= byte_budget and consumed > 0:
            break
        line = lines[index]
        consumed += len(line.encode("utf-8"))
        index += 1
        body = line.rstrip("\r\n")
        if not body.strip():
            continue
        records.append({"kind": "line", "index": start_line + len(records),
                        "text": body})
    if index == 0 and not lines and not eof_by_read and text:
        # One line bigger than the whole budget: emit the fragment (with a
        # note) so the reader still makes progress instead of stalling.
        lines = text.splitlines(keepends=True)
        line = lines[0]
        consumed = len(line.encode("utf-8"))
        records.append({"kind": "line", "index": start_line,
                        "text": line.rstrip("\r\n")})
        index = 1
        notes.append(
            "a single line exceeds the byte budget; emitted whole so the "
            "cursor can advance")
    eof = eof_by_read and index >= len(lines)
    return Batch(records, {"offset": offset + consumed,
                           "line": start_line + len(records)},
                 consumed, eof, fmt, total, offset, offset + consumed,
                 False, notes=notes)


def _strip_xml_runs(xml_text: str) -> str:
    """Text of OOXML/ODF runs, one paragraph per line (bounded)."""
    paragraphs: list[str] = []
    for block in re.split(r"</(?:w|a|text):p>|</text:p>", xml_text):
        runs = re.findall(r"<(?:w|a|text):t(?:\s[^>]*)?>(.*?)</(?:w|a|text):t>",
                          block, flags=re.DOTALL)
        if runs:
            paragraphs.append("".join(runs))
        elif block.strip():
            text = _TAG_RE.sub(" ", block)
            text = _WS_RE.sub(" ", text).strip()
            if text:
                paragraphs.append(text)
    return "\n".join(p for p in paragraphs if p.strip())


def _read_ooxml(target: Target, fmt: str, cursor: dict[str, Any], *,
                byte_budget: int, record_limit: int, redact: bool) -> Batch:
    resolved = _ooxml_member(target)
    if resolved is None:
        raise StreamError("open", f"no primary XML member for {fmt}",
                          target=target.label)
    member_target = Target(path=resolved[0], member=resolved[1], archive_kind="zip")
    offset = int(cursor.get("offset", 0))
    with open_target(member_target) as stream:
        try:
            stream.seek(offset)  # type: ignore[attr-defined]
        except (AttributeError, OSError, io.UnsupportedOperation):
            remaining = offset
            while remaining > 0:
                block = stream.read(min(65536, remaining))
                if not block:
                    raise StreamError("seek", "stream ended before offset",
                                      offset=offset, target=target.label)
                remaining -= len(block)
        # Read a bounded amount, then cut at the last paragraph boundary.
        raw = stream.read(byte_budget * 2 + 1)
        more = stream.read(1)
    eof = not more
    window = raw
    if not eof:
        cut = max(window.rfind(b"</w:p>"), window.rfind(b"</text:p>"),
                  window.rfind(b"</a:p>"))
        if cut >= 0:
            window = window[:cut + 8]
        else:
            window = window[:byte_budget]
    text = _strip_xml_runs(window.decode("utf-8", errors="replace"))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    records = [
        {"kind": "paragraph", "index": i, "text": ln}
        for i, ln in enumerate(lines[:max(1, record_limit)])
    ]
    return Batch(records, {"offset": offset + len(window)}, len(window), eof,
                 fmt, file_size(member_target), offset, offset + len(window),
                 False)


def _read_sqlite(target: Target, cursor: dict[str, Any], *,
                 byte_budget: int, record_limit: int, redact: bool,
                 projection) -> Batch:
    table = cursor.get("table")
    offset = int(cursor.get("offset", 0))
    uri = f"file:{target.path}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    try:
        if not table:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 1").fetchone()
            if row is None:
                return Batch([], {}, 0, True, "sqlite", file_size(target),
                             0, 0, False)
            table = str(row["name"])
        safe = str(table).replace('"', "")
        records: list[dict[str, Any]] = []
        consumed = 0
        eof = False
        query = f'SELECT * FROM "{safe}" LIMIT ? OFFSET ?'
        while len(records) < max(1, record_limit):
            rows = conn.execute(query, (record_limit, offset)).fetchall()
            if not rows:
                eof = True
                break
            for row in rows:
                if len(records) >= max(1, record_limit):
                    break
                mapping = dict(row)
                if redact:
                    mapping = _redact_value(mapping)
                mapping = _project_value(mapping, projection)
                rendered = _record_text(mapping)
                consumed += len(rendered.encode("utf-8"))
                records.append({"kind": "row", "index": offset + len(records),
                                "value": mapping, "text": rendered})
                if consumed >= byte_budget:
                    eof = False
                    break
            offset += len(rows)
            if consumed >= byte_budget or len(rows) < record_limit:
                if consumed < byte_budget and len(rows) < record_limit:
                    eof = True
                break
        return Batch(records, {"table": safe, "offset": offset}, consumed, eof,
                     "sqlite", file_size(target), 0, consumed, False,
                     notes=[f"table={safe} (read-only immutable URI)"])
    except sqlite3.Error as exc:
        raise StreamError("read", f"sqlite: {exc}", target=target.label) from exc
    finally:
        conn.close()


def read_batch(target: str | Path, cursor: dict[str, Any] | None = None, *,
               byte_budget: int = 65536,
               record_limit: int = 200,
               projection: Iterable[str] | None = None,
               redact: bool = True,
               protected: Iterable[str] = (),
               never_send_roots: Iterable[str] = ()) -> Batch:
    """Stream whole records within a bounded byte budget. Never loads the file.

    ``cursor`` is opaque and comes from a previous batch's ``next_cursor``;
    ``None`` starts at the beginning. The returned ``eof`` is true only when
    the stream truly ended — a budget stop is `eof=False` with a cursor.
    """
    parsed = parse_target(target)
    never_send = _check_policy(parsed, protected, never_send_roots)
    fmt = detect_format(parsed.label)
    cur = _normalise_cursor(cursor)
    proj = list(projection or [])
    budget = max(256, int(byte_budget))
    limit = max(1, int(record_limit))

    if fmt == "zip":
        raise StreamError(
            "read", "a zip container is not readable as records; pick a member "
            "(discovery lists them as zip://archive#member)", target=parsed.label)
    if fmt == "pdf":
        raise StreamError(
            "read", "PDF streaming is not built (page-aware extraction is a "
            "separate build); inspect() gives metadata only", target=parsed.label)
    if fmt == "sqlite" and not parsed.is_member:
        return _read_sqlite(parsed, cur, byte_budget=budget,
                            record_limit=limit, redact=redact, projection=proj)
    if fmt in ("docx", "xlsx", "pptx", "odt"):
        return _read_ooxml(parsed, fmt, cur, byte_budget=budget,
                           record_limit=limit, redact=redact)

    if fmt == "json":
        offset = int(cur.get("offset", 0))
        container = cur.get("container")
        if offset > 0 and not container:
            raise StreamError(
                "cursor",
                "resumed cursor is missing the container shape; pass the "
                "previous batch's next_cursor unchanged", target=parsed.label)
        with open_target(parsed, protected=protected,
                         never_send_roots=never_send_roots) as stream:
            reader = _JSONRecordStream(
                stream,
                # A resumed cursor sits *between* records, so the container
                # shape is already known; a fresh cursor reads it from the file.
                container=container if offset > 0 else None,
                start_offset=offset,
                allow_leading_comma=offset > 0,
            )
            try:
                records, next_offset, eof = reader.records(
                    byte_budget=budget, record_limit=limit)
            except StreamError as exc:
                raise StreamError(exc.stage, exc.message,
                                  offset=exc.offset, target=parsed.label) from exc
            detected_container = reader.container or container or "scalar"
        for record in records:
            if redact:
                if "value" in record:
                    record["value"] = (
                        REDACTED if record.get("kind") == "field" and
                        SENSITIVE_KEY_RE.search(str(record.get("key", "")))
                        else _redact_value(record["value"]))
                record["text"] = _record_text(
                    {record["key"]: record["value"]} if record.get("kind") == "field"
                    else record.get("value"), limit=4000)
                if len(record["text"]) > RECORD_TEXT_LIMIT:
                    record["text"] = record["text"][:RECORD_TEXT_LIMIT] + "…"
            if proj and record.get("kind") != "field":
                record["value"] = _project_value(record.get("value"), proj)
                record["text"] = _record_text(record["value"])
        return Batch(records,
                     {"offset": next_offset, "container": detected_container},
                     max(0, next_offset - offset), eof, "json",
                     file_size(parsed), offset, next_offset, never_send)

    batch = _read_text_style(parsed, fmt, cur, byte_budget=budget,
                             record_limit=limit, projection=proj, redact=redact,
                             protected=protected,
                             never_send_roots=never_send_roots)
    batch.never_send = never_send
    if not batch.eof and batch.byte_end <= batch.byte_start:
        raise StreamError("read", "record exceeds byte budget; increase byte_budget",
                          offset=batch.byte_start, target=parsed.label)
    return batch


# ---------------------------------------------------------------------------
# read_window(): text rendering of one bounded batch
# ---------------------------------------------------------------------------
@dataclass
class Window:
    target: str
    format: str
    text: str
    byte_start: int
    byte_end: int
    total_size: int
    eof: bool
    truncated: bool
    never_send: bool
    next_cursor: dict[str, Any]
    digest: str
    digest_scope: str
    records: int = 0
    parse_error: str | None = None
    notes: list[str] = field(default_factory=list)
    trusted: bool = False

    def __post_init__(self) -> None:
        if self.trusted is not False:
            raise ValueError("IF-6 violation: Window.trusted must always be False")

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "format": self.format,
            "text": self.text,
            "byte_start": self.byte_start,
            "byte_end": self.byte_end,
            "total_size": self.total_size,
            "eof": self.eof,
            "truncated": self.truncated,
            "never_send": self.never_send,
            "next_cursor": self.next_cursor,
            "digest": self.digest,
            "digest_scope": self.digest_scope,
            "records": self.records,
            "parse_error": self.parse_error,
            "notes": self.notes,
            "trusted": False,
        }


def render_records(records: list[dict[str, Any]], *,
                   record_chars: int | None = None) -> str:
    """One record per line, structure preserved for a reader."""
    cap = RECORD_TEXT_LIMIT if record_chars is None else max(80, int(record_chars))
    lines = []
    for record in records:
        text = str(record.get("text", ""))
        if len(text) > cap:
            text = text[:cap] + "…"
        lines.append(text)
    return "\n".join(lines)


def read_window(target: str | Path, cursor: dict[str, Any] | None = None, *,
                byte_budget: int = 65536,
                record_limit: int = 200,
                projection: Iterable[str] | None = None,
                redact: bool = True,
                protected: Iterable[str] = (),
                never_send_roots: Iterable[str] = (),
                digest: str | None = None,
                digest_scope: str | None = None,
                record_chars: int | None = None) -> Window:
    """A bounded, record-aligned text window of any readable target."""
    batch = read_batch(target, cursor, byte_budget=byte_budget,
                       record_limit=record_limit, projection=projection,
                       redact=redact, protected=protected,
                       never_send_roots=never_send_roots)
    if digest is None:
        parsed = parse_target(target)
        digest, digest_scope = target_digest(
            parsed, protected=protected, never_send_roots=never_send_roots)
    rendering_loss = any(
        str(r.get("text", "")).endswith("…") or
        len(str(r.get("text", ""))) >
        (RECORD_TEXT_LIMIT if record_chars is None else max(80, int(record_chars)))
        for r in batch.records)
    return Window(
        target=batch_target_label(target),
        format=batch.format,
        text=render_records(batch.records, record_chars=record_chars),
        byte_start=batch.byte_start,
        byte_end=batch.byte_end,
        total_size=batch.total_size,
        eof=batch.eof,
        truncated=not batch.eof or rendering_loss,
        never_send=batch.never_send,
        next_cursor=batch.next_cursor,
        digest=digest,
        digest_scope=digest_scope or "full",
        records=len(batch.records),
        parse_error=batch.parse_error,
        notes=batch.notes + (["record rendering capped; use read_batch records for full values"]
                             if rendering_loss else []),
    )


def batch_target_label(target: str | Path) -> str:
    parsed = parse_target(target)
    return parsed.label


def iter_batches(target: str | Path, *, byte_budget: int = 65536,
                 record_limit: int = 200, max_batches: int = 1000,
                 **kwargs) -> Iterator[Batch]:
    """Convenience generator over batches (tests + offline tooling)."""
    cursor: dict[str, Any] | None = None
    for _ in range(max_batches):
        batch = read_batch(target, cursor, byte_budget=byte_budget,
                           record_limit=record_limit, **kwargs)
        yield batch
        if batch.eof:
            return
        cursor = batch.next_cursor
    raise StreamError("budget", f"max_batches={max_batches} reached before EOF",
                      target=str(target))


def iter_rows(target: str | Path, *, max_bytes: int | None = None,
              **kwargs) -> Iterator[dict[str, Any]]:
    """Flatten every record of a target, bounded by `max_bytes` when given."""
    consumed = 0
    for batch in iter_batches(target, **kwargs):
        yield from batch.records
        consumed += batch.bytes_read
        if max_bytes is not None and consumed >= max_bytes:
            return


def record_count(target: str | Path, *, max_bytes: int = 8 << 20,
                 **kwargs) -> tuple[int, bool]:
    """`(records_counted, exact)` — exact only if the whole file was streamed."""
    total = 0
    consumed = 0
    for batch in iter_batches(target, **kwargs):
        total += len(batch.records)
        consumed += batch.bytes_read
        if batch.eof:
            return total, True
        if consumed >= max_bytes:
            return total, False
    return total, True


__all__ = [
    "Batch",
    "Inspection",
    "StreamError",
    "Target",
    "Window",
    "detect_format",
    "file_size",
    "inspect",
    "iter_batches",
    "iter_rows",
    "open_target",
    "parse_target",
    "read_batch",
    "read_window",
    "record_count",
    "render_records",
    "target_digest",
]
