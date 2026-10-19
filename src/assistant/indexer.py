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

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .cost import iso_now
from .safety import expand, is_protected

TEMP_SUFFIXES = (".part", ".crdownload", ".tmp", ".swp", ".download")
TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".log", ".csv", ".tsv", ".json", ".toml", ".yaml",
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
        with zipfile.ZipFile(path) as archive:
            for name in archive.namelist():
                if any(re.search(pattern, name) for pattern in member_patterns):
                    root = ElementTree.fromstring(archive.read(name))
                    parts.extend(node.text for node in root.iter()
                                 if node.text and node.tag.endswith("}t"))
    except Exception:
        return ""
    return " ".join(parts)


def extract_text(path: Path, max_chars: int = 200_000) -> tuple[str, str]:
    """Return (text, extractor_name). Extractor name keeps coverage honest
    in index stats — 'no-text' is a fact to surface, not hide."""
    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_EXTENSIONS:
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars], "text"
        if suffix == ".pdf":
            if shutil.which("pdftotext"):
                out = subprocess.run(["pdftotext", "-layout", str(path), "-"],
                                     capture_output=True, text=True, timeout=60,
                                     check=False)
                if out.returncode == 0:
                    return out.stdout[:max_chars], "pdftotext"
            try:  # pragma: no cover - optional dependency
                import fitz

                with fitz.open(path) as doc:
                    return "\n".join(p.get_text() for p in doc)[:max_chars], "pymupdf"
            except ImportError:
                return "", "no-text (install poppler-utils or pymupdf)"
        if suffix == ".docx":
            return _ooxml_text(path, (r"word/document\.xml",))[:max_chars], "docx"
        if suffix == ".pptx":
            return _ooxml_text(path, (r"ppt/slides/slide\d+\.xml",))[:max_chars], "pptx"
        if suffix == ".xlsx":
            return _ooxml_text(path, (r"xl/sharedStrings\.xml",))[:max_chars], "xlsx"
        if suffix == ".odt":
            return _ooxml_text(path, (r"content\.xml",))[:max_chars], "odt"
    except Exception as exc:
        return "", f"error: {type(exc).__name__}"
    return "", "no-text"  # binaries/images: metadata only (vision is opt-in)


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

    def _never_send(self, path: Path) -> bool:
        return is_protected(path, self.never_send_roots) if self.never_send_roots else False

    def iter_files(self, root: Path):
        """Yield (path, skip_reason|None). Dirs pruned in-place so ignored
        trees are never descended (a 40GB node_modules shouldn't even be
        stat-walked)."""
        import os

        for dirpath, dirnames, filenames in os.walk(root):
            directory = Path(dirpath)
            if (directory / ".assistant-ignore").exists():
                dirnames[:] = []
                yield directory, ".assistant-ignore"
                continue
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and d not in ("_Conflicts",)
                and not is_protected(directory / d, self.protected)
            ]
            for name in filenames:
                path = directory / name
                if name.startswith(".") or name.endswith(TEMP_SUFFIXES):
                    yield path, "temp/hidden"
                elif is_protected(path, self.protected):
                    yield path, "protected"
                else:
                    yield path, None

    def index_root(self, root_spec: dict) -> dict:
        root = Path(root_spec["path"])
        stats = {"root": str(root), "indexed": 0, "unchanged": 0, "changed": 0,
                 "missing_marked": 0, "skipped": {}, "no_text": 0,
                 "never_send": 0, "extractors": {}}
        if not root.exists():
            stats["error"] = f"root does not exist: {root}"
            return stats
        seen: set[str] = set()
        for path, skip_reason in self.iter_files(root):
            if skip_reason:
                stats["skipped"][skip_reason] = stats["skipped"].get(skip_reason, 0) + 1
                continue
            seen.add(str(path))
            stat = path.stat()
            existing = self.store.document_by_path(str(path))
            if (existing and existing["status"] == "indexed"
                    and existing["size"] == stat.st_size
                    and abs(existing["mtime"] - stat.st_mtime) < 1e-6):
                stats["unchanged"] += 1
                continue
            data_hash = sha256_bytes(path.read_bytes()) if stat.st_size <= 64_000_000 \
                else self._hash_large(path)
            text, extractor = extract_text(path, self.max_extract_chars)
            stats["extractors"][extractor] = stats["extractors"].get(extractor, 0) + 1
            if not text:
                stats["no_text"] += 1
            never_send = self._never_send(path)
            stats["never_send"] += int(never_send)
            self.store.upsert_document(
                path=str(path), root=str(root), sha256=data_hash,
                size=stat.st_size, mtime=stat.st_mtime,
                mime=mimetypes.guess_type(path.name)[0], ext=path.suffix.lower(),
                indexed_ts=iso_now(), never_send=int(never_send),
                text_chunks=chunk_text(text))
            stats["changed" if existing else "indexed"] += 1
        # Files in the index but gone from disk: mark, never delete records —
        # the journal of what was known is part of the safety story.
        known = {d["path"] for d in self.store.documents_in_root(str(root))}
        missing = sorted(known - seen)
        if missing:
            self.store.mark_missing(missing)
            stats["missing_marked"] = len(missing)
        return stats

    @staticmethod
    def _hash_large(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
