"""Indexer (§3.7) — walk whitelisted roots, extract text, hash everything.

Guardrails are structural, not polite suggestions:
- Only roots the owner named in config are walked. Default: none.
- Protected paths (§4.1), `.assistant-ignore` directories, hidden dirs and
  temp/partial downloads (.part/.crdownload/.tmp, §3.7 watcher rules)
  are skipped and counted, never silently included.
- never_send_to_cloud (§10.7) documents ARE indexed locally (search must
  work offline) but flagged, so no later LLM tier may ship their content.
- A file whose sha256/mtime changed since indexing is re-extracted and
  marked fresh; the planner re-checks identity at plan time too —
  'never act on a changed file' starts here (§4.1).

Extraction is stdlib-first: text/code directly, OOXML (docx/xlsx/pptx)
via zip+XML, PDF via `pdftotext` if present else PyMuPDF if installed
else no-text (counted, honest). Images contribute metadata only — OCR/
vision happens only when asked and costs quota (§3.7), so not here.
"""

# ruff: noqa: B023 -- XML callbacks and chunk generators are consumed synchronously in-loop.
from __future__ import annotations

import codecs
import hashlib
import io
import mimetypes
import os
import re
import selectors
import shutil
import stat as stat_mod
import subprocess
import time
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from xml.parsers import expat

from .cost import iso_now
from .safety import expand, is_protected, open_readonly_nofollow

TEMP_SUFFIXES = (".part", ".crdownload", ".tmp", ".swp", ".download")
#: F33: rendered speech is regenerable output, never a document. If a data dir
#: ever sits inside a whitelisted root, this name is still never tiered.
EXCLUDED_DIRNAMES = ("voice-cache",)
TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".toml", ".yaml",
    ".yml", ".ini", ".cfg", ".py", ".js", ".ts", ".rs", ".go", ".c", ".h",
    ".cpp", ".sh", ".html", ".xml", ".tex", ".org",
}
CHUNK_CHARS = 1000


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    text = text.strip()
    if not text:
        return []
    return [text[i:i + size] for i in range(0, len(text), size)]


def _ooxml_text(path: Path, member_patterns: tuple[str, ...]) -> str:
    parts: list[str] = []
    try:
        with open_readonly_nofollow(path) as file_handle, zipfile.ZipFile(file_handle) as archive:
            for name in archive.namelist():
                if any(re.search(pattern, name) for pattern in member_patterns):
                    info = archive.getinfo(name)
                    if info.file_size > 4_000_000 or info.file_size / max(1, info.compress_size) > 100:
                        raise ValueError("structured document member exceeds safety limit")
                    root = ElementTree.fromstring(archive.read(info))
                    parts.extend(node.text for node in root.iter()
                                 if node.text and node.tag.endswith("}t"))
    except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ValueError(f"invalid structured document: {exc}") from exc
    return " ".join(parts)


def _pdf_text(path: Path, max_chars: int) -> str:
    """Capture bounded pdftotext output without holding its entire output in RAM."""
    with open_readonly_nofollow(path) as source, subprocess.Popen(
            ["pdftotext", "-layout", f"/proc/self/fd/{source.fileno()}", "-"],
            pass_fds=(source.fileno(),), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        assert proc.stdout is not None
        deadline = time.monotonic() + 60
        data = bytearray()
        # UTF-8 takes at most four bytes per character. An overflow is an error,
        # not a partially indexed document.
        cap = max_chars * 4 + 4
        selector = selectors.DefaultSelector()
        try:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("pdftotext timed out")
                block = os.read(proc.stdout.fileno(), min(65536, cap + 1 - len(data)))
                if not block:
                    break
                data.extend(block)
                if len(data) > cap:
                    raise ValueError("PDF extraction exceeds output limit")
            if proc.wait(timeout=max(0.01, deadline - time.monotonic())):
                raise ValueError("pdftotext failed to parse PDF")
        finally:
            selector.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        text = data.decode("utf-8", errors="replace")
        if len(text) > max_chars:
            raise ValueError(f"extraction exceeds {max_chars} characters")
        return text


def _stream_pdf(path: Path):
    """Yield bounded decoded output; an error rolls back the indexing transaction."""
    if not shutil.which("pdftotext"):
        raise ValueError("pdftotext unavailable")
    with open_readonly_nofollow(path) as source, subprocess.Popen(
            ["pdftotext", "-layout", f"/proc/self/fd/{source.fileno()}", "-"],
            pass_fds=(source.fileno(),), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        before = os.fstat(source.fileno())
        deadline = time.monotonic() + 120
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        selector = selectors.DefaultSelector()
        try:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError("pdftotext timed out")
                block = os.read(proc.stdout.fileno(), 65536)
                if not block:
                    break
                text = decoder.decode(block)
                for i in range(0, len(text), CHUNK_CHARS):
                    yield text[i:i + CHUNK_CHARS]
            tail = decoder.decode(b"", final=True)
            if tail:
                yield tail
            if proc.wait(timeout=max(0.01, deadline - time.monotonic())):
                raise ValueError("pdftotext failed to parse PDF")
            after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("PDF changed during extraction")
        finally:
            selector.close()
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def _stream_ooxml(path: Path, patterns: tuple[str, ...]):
    """Read selected XML members incrementally, never extract to disk."""
    with open_readonly_nofollow(path) as raw, zipfile.ZipFile(raw) as archive:
        before = os.fstat(raw.fileno())
        matched = False
        for info in archive.infolist():
            if not any(re.fullmatch(pattern, info.filename) for pattern in patterns):
                continue
            matched = True
            if info.file_size > 1_000_000_000 or info.file_size / max(1, info.compress_size) > 100:
                raise ValueError("structured document member exceeds safety limit")
            with archive.open(info) as member:
                parser = expat.ParserCreate(namespace_separator="}")
                stack = []
                pieces = []
                pending = 0
                def start(name, _attrs):
                    stack.append(name)
                def end(name):
                    nonlocal pending
                    if (name.endswith("}t") or (info.filename.startswith("xl/worksheets/") and name.endswith("}v")) or (info.filename == "content.xml" and name.endswith("}p"))):
                        pieces.append(" ")
                        pending += 1
                    stack.pop()
                def data(text):
                    nonlocal pending
                    if stack and (stack[-1].endswith("}t") or
                                  (info.filename.startswith("xl/worksheets/") and stack[-1].endswith("}v")) or
                                  info.filename == "content.xml"):
                        pending += len(text)
                        if pending > 2_000_000:
                            raise ValueError("XML expansion exceeds chunk limit")
                        pieces.append(text)
                def reject_doctype(*_args):
                    raise ValueError("XML DTD is not supported")
                parser.StartElementHandler = start
                parser.EndElementHandler = end
                parser.CharacterDataHandler = data
                parser.StartDoctypeDeclHandler = reject_doctype
                while True:
                    block = member.read(65536)
                    parser.Parse(block, not block)
                    if pieces:
                        text = "".join(pieces)
                        pieces.clear()
                        pending = 0
                        for i in range(0, len(text), CHUNK_CHARS):
                            yield text[i:i + CHUNK_CHARS]
                    if not block:
                        break
        if not matched:
            raise ValueError("structured document has no supported text member")
        after = os.fstat(raw.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError("document changed during extraction")


def extract_text(path: Path, max_chars: int = 200_000) -> tuple[str, str]:
    """Return (text, extractor_name). Extractor name keeps coverage honest
    in index stats — 'no-text' is a fact to surface, not hide."""
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_EXTENSIONS:
            with open_readonly_nofollow(path) as raw, io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as handle:
                text = handle.read(max_chars + 1)
            if len(text) > max_chars:
                raise ValueError(f"extraction exceeds {max_chars} characters")
            return text, "text"
        if suffix == ".pdf":
            if shutil.which("pdftotext"):
                return _pdf_text(path, max_chars), "pdftotext"
            return "", "no-text (install poppler-utils)"
        if suffix == ".docx":
            text = _ooxml_text(path, (r"word/document\.xml",))
            if len(text) > max_chars:
                raise ValueError(f"extraction exceeds {max_chars} characters")
            return text, "docx"
        if suffix == ".pptx":
            text = _ooxml_text(path, (r"ppt/slides/slide\d+\.xml",))
            if len(text) > max_chars:
                raise ValueError(f"extraction exceeds {max_chars} characters")
            return text, "pptx"
        if suffix == ".xlsx":
            text = _ooxml_text(path, (r"xl/sharedStrings\.xml",))
            if len(text) > max_chars:
                raise ValueError(f"extraction exceeds {max_chars} characters")
            return text, "xlsx"
        if suffix == ".odt":
            text = _ooxml_text(path, (r"content\.xml",))
            if len(text) > max_chars:
                raise ValueError(f"extraction exceeds {max_chars} characters")
            return text, "odt"
    except Exception as exc:
        return "", f"error: {type(exc).__name__}: {exc}"
    return "", "no-text"  # binaries/images: metadata only (vision is opt-in)


def extract_with_provenance(path: Path, max_chars: int = 200_000) -> dict:
    """Bound indexed text while recording every cap/error; full reads use streamread."""
    from .streamread import StreamError, detect_format, iter_batches

    cap = max(1, int(max_chars))
    fmt = detect_format(str(path))
    parts = []
    count = 0
    truncated = False
    error = None
    extractor = fmt
    try:
        if path.suffix.lower() in TEXT_EXTENSIONS and fmt not in (
                "json", "jsonl", "csv", "tsv"):
            # Read characters, not bytes: UTF-8 boundaries remain intact.
            with path.open(encoding="utf-8", errors="strict") as stream:
                text = stream.read(cap + 1)
            truncated = len(text) > cap
            parts = [text[:cap]]
        elif fmt in ("json", "jsonl", "ndjson", "csv", "tsv", "sqlite",
                     "docx", "xlsx", "pptx", "odt"):
            for batch in iter_batches(path, byte_budget=65536, record_limit=200):
                for record in batch.records:
                    if record.get("parse_error"):
                        raise StreamError("parse", record["parse_error"], target=str(path))
                    if "fields" in record:
                        rendered = str(record["fields"])
                    elif "value" in record:
                        import json

                        value = ({record["key"]: record["value"]}
                                 if record.get("kind") == "field" else record["value"])
                        rendered = json.dumps(value, ensure_ascii=False)
                    else:
                        rendered = str(record.get("text", ""))
                    remaining = cap - count
                    piece = rendered[:remaining]
                    parts.append(piece)
                    count += len(piece) + 1
                    if len(rendered) > remaining or count >= cap:
                        truncated = True
                        break
                if truncated:
                    break
        else:
            text, extractor = extract_text(path, cap + 1)
            truncated = len(text) > cap
            parts = [text[:cap]]
            if extractor.startswith("error:"):
                error = extractor
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    text = "\n".join(parts)[:cap]
    return {"text": text, "extractor": extractor, "extracted_chars": len(text),
            "truncated": truncated, "parse_error": error}


class Indexer:
    def __init__(self, config, store):
        self.config = config
        self.store = store
        organise = config.section("organise")
        policy = config.section("policy")
        self.protected = policy.get("protected") or []
        self.max_extract_chars = int(organise.get("max_extract_chars", 200_000))
        self.never_send_roots = [
            str(expand(p)) for p in
            (config.section("privacy").get("never_send_to_cloud") or [])]

    def _refresh_policy(self) -> None:
        organise = self.config.section("organise")
        policy = self.config.section("policy")
        self.protected = policy.get("protected") or []
        self.max_extract_chars = int(organise.get("max_extract_chars", 200_000))
        self.never_send_roots = [
            str(expand(p)) for p in
            (self.config.section("privacy").get("never_send_to_cloud") or [])]

    def _never_send(self, path: Path) -> bool:
        return is_protected(path, self.never_send_roots) if self.never_send_roots else False

    def iter_files(self, root: Path, walk_errors: list[tuple[str, str]] | None = None):
        """Yield (path, skip_reason|None). Dirs pruned in-place so ignored
        trees are never descended (a 40GB node_modules shouldn't even be
        stat-walked)."""
        self._refresh_policy()

        def _on_error(exc: OSError) -> None:
            if walk_errors is not None:
                bad_path = str(getattr(exc, "filename", "") or root)
                walk_errors.append((bad_path, f"{type(exc).__name__}: {exc}"))

        for dirpath, dirnames, filenames in os.walk(root, onerror=_on_error):
            directory = Path(dirpath)
            if (directory / ".assistant-ignore").exists():
                dirnames[:] = []
                yield directory, ".assistant-ignore"
                continue
            kept_dirs: list[str] = []
            for d in dirnames:
                sub = directory / d
                if sub.is_symlink():
                    yield sub, "symlink"
                    continue
                if d.startswith(".") or d in ("_Conflicts",):
                    continue
                if d in EXCLUDED_DIRNAMES:
                    yield sub, d        # counted, never descended
                    continue
                if is_protected(sub, self.protected):
                    continue
                kept_dirs.append(d)
            dirnames[:] = kept_dirs
            for name in filenames:
                path = directory / name
                if path.is_symlink():
                    yield path, "symlink"
                elif name.startswith(".") or name.endswith(TEMP_SUFFIXES):
                    yield path, "temp/hidden"
                elif is_protected(path, self.protected):
                    yield path, "protected"
                else:
                    yield path, None

    def index_root(self, root_spec: dict) -> dict:
        self._refresh_policy()
        root = Path(root_spec["path"])
        stats = {"root": str(root), "indexed": 0, "unchanged": 0, "changed": 0,
                 "missing_marked": 0, "skipped": {}, "no_text": 0,
                 "never_send": 0, "extractors": {}}
        if is_protected(root, self.protected) or root.is_symlink():
            stats["error"] = f"protected or symlink root refused: {root}"
            return stats
        if not root.exists():
            stats["error"] = f"root does not exist: {root}"
            return stats
        seen: set[str] = set()
        walk_errors: list[tuple[str, str]] = []
        for path, skip_reason in self.iter_files(root, walk_errors=walk_errors):
            if skip_reason:
                stats["skipped"][skip_reason] = stats["skipped"].get(skip_reason, 0) + 1
                continue
            try:
                stat = path.lstat()
            except OSError as exc:
                walk_errors.append((str(path), f"{type(exc).__name__}: {exc}"))
                continue
            if stat_mod.S_ISLNK(stat.st_mode):
                stats["skipped"]["symlink"] = stats["skipped"].get("symlink", 0) + 1
                continue
            if not stat_mod.S_ISREG(stat.st_mode):
                stats["skipped"]["special"] = stats["skipped"].get("special", 0) + 1
                continue
            seen.add(str(path))
            never_send = self._never_send(path)
            existing = self.store.document_by_path(str(path))
            if (existing and existing["status"] == "indexed"
                    and existing.get("extraction_version", 0) == 1
                    and existing.get("extractor") is not None
                    and existing["size"] == stat.st_size
                    and abs(existing["mtime"] - stat.st_mtime) < 1e-6):
                if int(existing["never_send"]) != int(never_send):
                    with self.store._lock:
                        self.store._conn.execute(
                            "UPDATE documents SET never_send = ? WHERE id = ?",
                            (int(never_send), existing["id"]))
                        self.store._conn.commit()
                stats["never_send"] += int(never_send)
                stats["unchanged"] += 1
                continue
            try:
                data_hash = self._hash_large(path)
                if path.suffix.lower() in (".json", ".jsonl", ".ndjson", ".csv", ".tsv"):
                    from .streamread import validate

                    validate(str(path), protected=self.protected,
                             never_send_roots=self.never_send_roots)
                if path.suffix.lower() in TEXT_EXTENSIONS:
                    extractor = "text-stream"
                    def chunks():
                        with open_readonly_nofollow(path) as raw, io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as handle:
                            before = os.fstat(raw.fileno())
                            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
                                raise OSError("file changed before indexing")
                            while True:
                                block = handle.read(CHUNK_CHARS)
                                if not block:
                                    break
                                yield block
                            after = os.fstat(raw.fileno())
                            if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                                raise OSError("file changed during indexing")
                    text_chunks = chunks()
                elif path.suffix.lower() in (".docx", ".pptx", ".xlsx", ".odt"):
                    patterns = {
                        ".docx": (r"word/document\.xml",),
                        ".pptx": (r"ppt/slides/slide\d+\.xml",),
                        ".xlsx": (r"xl/sharedStrings\.xml", r"xl/worksheets/sheet\d+\.xml"),
                        ".odt": (r"content\.xml",),
                    }
                    extractor = "ooxml-stream"
                    text_chunks = _stream_ooxml(path, patterns[path.suffix.lower()])
                elif path.suffix.lower() == ".pdf" and shutil.which("pdftotext"):
                    extractor = "pdf-stream"
                    text_chunks = _stream_pdf(path)
                else:
                    text, extractor = extract_text(path, self.max_extract_chars)
                    if extractor.startswith("error:"):
                        raise ValueError(extractor)
                    if not text:
                        stats["no_text"] += 1
                    text_chunks = chunk_text(text)
                self.store.upsert_document(
                    path=str(path), root=str(root), sha256=data_hash,
                    size=stat.st_size, mtime=stat.st_mtime,
                    mime=mimetypes.guess_type(path.name)[0], ext=path.suffix.lower(),
                    indexed_ts=iso_now(), never_send=int(never_send),
                    text_chunks=text_chunks, extractor=extractor)
            except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError, expat.ExpatError, subprocess.SubprocessError) as exc:
                self.store.mark_document_error(
                    str(path), f"{type(exc).__name__}: {exc}", root=str(root),
                    size=stat.st_size, mtime=stat.st_mtime, ext=path.suffix.lower(),
                    never_send=int(never_send))
                walk_errors.append((str(path), f"{path}: {type(exc).__name__}: {exc}"))
                continue
            stats["extractors"][extractor] = stats["extractors"].get(extractor, 0) + 1
            stats["never_send"] += int(never_send)
            stats["changed" if existing else "indexed"] += 1
        if walk_errors:
            stats["error"] = "; ".join(msg for _, msg in walk_errors)
        # Files in the index but gone from disk: mark, never delete records —
        # the journal of what was known is part of the safety story.
        unreadable_prefixes = tuple(
            p.rstrip(os.sep) + os.sep for p, _ in walk_errors if p
        )
        known = {d["path"] for d in self.store.documents_in_root(str(root))}
        missing = sorted(
            p for p in (known - seen)
            if not (unreadable_prefixes and p.startswith(unreadable_prefixes))
        )
        if missing:
            self.store.mark_missing(missing)
            stats["missing_marked"] = len(missing)
        return stats

    @staticmethod
    def _hash_large(path: Path) -> str:
        digest = hashlib.sha256()
        with open_readonly_nofollow(path) as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
