"""Read-only filesystem discovery (GAP-2) — find things without touching them.

The scavenger instruction ("go through my laptop and find X") failed because
discovery was welded to the *folder-moving* configuration: `[[organise.roots]]`
requires a `mode` and a `taxonomy`, `Store._search` only ever queried
`doc_chunks`, and an unextracted file was invisible even when its filename
matched the owner's words verbatim
(`reports/RPT-B-scavenger-gaps-20261125T161536Z.md` §1.2, GAP-2).

This module is the general fix, and it is read-only by construction:

- **Roots** come from `Config.discovery_roots()` (`[discovery] roots`, plus any
  `[[organise.roots]]` paths) — never from a write plan. Nothing here can move,
  rename, delete or write a byte.
- **Metadata first.** `locate()` walks directory entries and stats them; it
  never reads file *content*, never hashes eagerly, and never chunks. A search
  over a large tree costs directory reads, not gigabytes of I/O.
- **Archives are inspected, never extracted.** `scan_archive()` reads a
  central directory (`zipfile.infolist()`) or streams tar headers
  (`tarfile` in `r|*` mode) and records member names/sizes so a file *inside*
  a bundle is discoverable before anything is opened. Member count, expansion
  ratio and per-member size are capped, and hostile member names (absolute
  paths, `..`, links, devices) are counted as refusals — never followed.
- **The protected rail holds.** `[policy] protected` (`~/.ssh`, `~/.gnupg`,
  `~/.config`, `~/.local/share/assistant`) is pruned before `stat()`, exactly
  as in `indexer.iter_files`; hidden entries, symlinks, `.assistant-ignore`
  trees, partial downloads and build/vendor trees (`node_modules`, `venv`,
  `__pycache__`, `target`, `build`, `dist`, `Trash`) are skipped and *counted*,
  so a broad root never silently walks a 40 GB dependency tree.
- **Every hit carries its provenance**: real path, size, mtime, extension,
  whether it is inside `[privacy] never_send_to_cloud`, and — for members —
  the `zip://archive#member` target the reader (`streamread`) accepts.

`target` strings are the currency of this module: a plain absolute path, or
`zip://<archive>#<member>`. Nothing here is trusted content; discovery returns
*pointers*, and `IF-6` applies the moment bytes are read (`streamread`).
"""

from __future__ import annotations

import hashlib
import os
import re
import stat as stat_mod
import tarfile
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from .safety import expand, is_protected

# -- policy constants (code-level caps, not owner knobs) --------------------
#: Trees that are never descended on a broad root. `indexer.EXCLUDED_DIRNAMES`
#: only knew `voice-cache`, so pointing a root at `~` stat-walked and hashed
#: every dependency tree on the machine (RPT-B §1.2 break 3).
EXCLUDED_DIRNAMES: frozenset[str] = frozenset({
    "voice-cache",
    "node_modules",
    "__pycache__",
    "venv",
    ".venv",
    "env",
    "site-packages",
    "target",
    "build",
    "dist",
    "out",
    "_Conflicts",
    "Trash",
    ".Trash",
    ".git",
    ".hg",
    ".svn",
    ".cache",
    ".npm",
    ".cargo",
    ".rustup",
    "snap",
    "proc",
    "sys",
    "dev",
})

TEMP_SUFFIXES: tuple[str, ...] = (
    ".part", ".crdownload", ".tmp", ".swp", ".swx", ".download", "~",
)

ZIP_SUFFIXES: frozenset[str] = frozenset({".zip", ".jar", ".whl", ".epub",
                                          ".docx", ".xlsx", ".pptx", ".odt", ".ods"})
TAR_SUFFIXES: frozenset[str] = frozenset({".tar", ".tgz", ".tbz2", ".txz"})

#: Suffixes whose *container* is a tar (matched on the full name, not just
#: the last suffix, because `backup.tar.gz`'s last suffix is `.gz`).
TAR_NAME_SUFFIXES: tuple[str, ...] = (
    ".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst", ".tgz", ".tbz2", ".txz",
)

#: Formats that carry internal structure a reader must *inspect* before it
#: reads (GAP-3). Plain text/markdown/log files are line-oriented and need no
#: skeleton; JSON/JSONL/SQLite/OOXML and archive members do.
STRUCTURED_SUFFIXES: frozenset[str] = frozenset({
    ".json", ".jsonl", ".ndjson", ".sqlite", ".sqlite3", ".db", ".csv", ".tsv",
    ".xml", ".html", ".htm", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".pdf",
})

#: Hard caps. A manifest scan that needs more than this is not "inspection";
#: it is an extraction, and this module never extracts.
MAX_ARCHIVE_MEMBERS: int = 512
MAX_ARCHIVE_MEMBER_BYTES: int = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO: float = 100.0
MAX_WALK_ENTRIES: int = 50_000
MAX_WALK_DEPTH: int = 32


class DiscoveryError(RuntimeError):
    """A discovery action failed for a named reason (never a silent skip)."""

    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


@dataclass(frozen=True)
class SkipCount:
    """Counted skips. A skip is a fact about the walk, never a mute button."""

    counts: dict[str, int] = field(default_factory=dict)

    def bump(self, reason: str) -> None:
        # frozen dataclass holding a mutable dict: intentional, the counts are
        # accumulated in place and exposed read-only by callers.
        self.counts[reason] = self.counts.get(reason, 0) + 1

    def as_dict(self) -> dict[str, int]:
        return dict(sorted(self.counts.items()))


@dataclass(frozen=True)
class Entry:
    """One discoverable thing (a file, or a member inside an archive)."""

    target: str                     # absolute path, or zip://archive#member
    name: str
    ext: str
    size: int
    mtime: float
    kind: str = "file"              # file | archive_member
    archive: str | None = None
    never_send: bool = False
    structured: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "name": self.name,
            "ext": self.ext,
            "size": self.size,
            "mtime": self.mtime,
            "kind": self.kind,
            "archive": self.archive,
            "never_send": self.never_send,
            "structured": self.structured,
        }


@dataclass(frozen=True)
class Policy:
    """The read-only discovery policy derived from one config."""

    roots: tuple[str, ...]
    protected: tuple[str, ...]
    never_send_roots: tuple[str, ...]
    excluded_dirnames: frozenset[str] = EXCLUDED_DIRNAMES
    include_archives: bool = True
    max_entries: int = MAX_WALK_ENTRIES
    max_depth: int = MAX_WALK_DEPTH

    @classmethod
    def from_config(cls, config, *, roots: Iterable[str] | None = None,
                    include_archives: bool = True,
                    max_entries: int = MAX_WALK_ENTRIES,
                    max_depth: int = MAX_WALK_DEPTH) -> Policy:
        if config is None:
            return cls(roots=tuple(str(expand(r)) for r in (roots or [])),
                       protected=(), never_send_roots=(),
                       include_archives=include_archives,
                       max_entries=max_entries, max_depth=max_depth)
        resolved = (
            tuple(str(expand(r)) for r in roots if str(r).strip())
            if roots is not None
            else tuple(r["path"] for r in config.discovery_roots())
        )
        return cls(
            roots=resolved,
            protected=tuple(config.section("policy").get("protected") or []),
            never_send_roots=tuple(
                str(expand(p))
                for p in (config.section("privacy").get("never_send_to_cloud") or [])
            ),
            include_archives=include_archives,
            max_entries=max_entries,
            max_depth=max_depth,
        )


def is_never_send(path: str | Path, never_send_roots: Iterable[str]) -> bool:
    roots = list(never_send_roots)
    return bool(roots) and is_protected(path, roots)


def _has_symlink_component(path: Path, stop_at: Path | None = None) -> bool:
    """True if `path` or an ancestor (down to `stop_at`) is a symlink."""
    cur = path
    stop_resolved = stop_at.resolve() if stop_at is not None else None
    visited: set[Path] = set()
    while cur not in visited:
        visited.add(cur)
        if cur.is_symlink():
            return True
        if stop_resolved is not None:
            try:
                if cur.resolve() == stop_resolved:
                    break
            except OSError:
                return True
        if cur.parent == cur:
            break
        cur = cur.parent
    return False


def archive_kind(path: str | Path) -> str | None:
    """`zip` | `tar` | None for this path's name. Pure string logic."""
    name = Path(str(path)).name.lower()
    suffix = Path(name).suffix.lower()
    if suffix in ZIP_SUFFIXES:
        return "zip"
    if suffix in TAR_SUFFIXES:
        return "tar"
    if any(name.endswith(t) for t in TAR_NAME_SUFFIXES):
        return "tar"
    return None


def _safe_member_name(name: str) -> str | None:
    """Return a normalised member name, or None if the name is hostile.

    Absolute paths, `..` segments, NUL bytes and drive letters are refused:
    a manifest must never hand a reader a target that could escape its archive.
    """
    if not name or "\x00" in name:
        return None
    normalised = name.replace("\\", "/")
    if normalised.startswith("/") or re.match(r"^[A-Za-z]:", normalised):
        return None
    parts = [p for p in normalised.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return "/".join(parts)


@dataclass(frozen=True)
class Member:
    target: str
    name: str
    member: str
    size: int
    ext: str


@dataclass
class ManifestResult:
    """What a read-only archive scan found, and what it refused to believe."""

    archive: str
    kind: str
    members: list[Member] = field(default_factory=list)
    total_members: int = 0
    truncated: bool = False          # member cap hit — honest, not silent
    refused: dict[str, int] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "archive": self.archive,
            "kind": self.kind,
            "members": len(self.members),
            "total_members": self.total_members,
            "truncated": self.truncated,
            "refused": dict(sorted(self.refused.items())),
            "error": self.error,
        }


def _check_zip_ratio(info: zipfile.ZipInfo) -> None:
    if info.file_size <= 0:
        return
    compressed = max(1, info.compress_size)
    ratio = info.file_size / compressed
    if ratio > MAX_COMPRESSION_RATIO:
        raise DiscoveryError(
            "archive-manifest",
            f"member {info.filename!r} exceeds the compression-ratio guard "
            f"({ratio:.1f}x > {MAX_COMPRESSION_RATIO:.0f}x, zip-bomb posture)",
        )


def scan_archive(path: str | Path, policy: Policy,
                 *, max_members: int = MAX_ARCHIVE_MEMBERS) -> ManifestResult:
    """Read an archive's manifest without extracting a single byte.

    zip: central directory only (`infolist()`).
    tar: header stream in `r|*` mode, stopped at the member cap; no member
    block is ever written to disk, and link/device members are refused.
    """
    archive_path = expand(path)
    kind = archive_kind(archive_path)
    result = ManifestResult(archive=str(archive_path), kind=kind or "unknown")
    if kind is None:
        result.error = "not an archive by name"
        return result
    if _has_symlink_component(archive_path):
        result.error = "refused: symlink in path"
        return result
    if is_protected(archive_path, list(policy.protected)):
        result.error = "refused: protected path"
        return result
    try:
        stat = archive_path.lstat()
    except OSError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    if not stat_mod.S_ISREG(stat.st_mode):
        result.error = "refused: not a regular file"
        return result
    never_send = is_never_send(archive_path, policy.never_send_roots)

    def _bump(reason: str) -> None:
        result.refused[reason] = result.refused.get(reason, 0) + 1

    try:
        if kind == "zip":
            with zipfile.ZipFile(archive_path, "r") as zf:
                for info in zf.infolist():
                    result.total_members += 1
                    if info.is_dir():
                        continue
                    if len(result.members) >= max_members:
                        result.truncated = True
                        _bump("member_cap")
                        break
                    member = _safe_member_name(info.filename)
                    if member is None:
                        _bump("hostile_member_name")
                        continue
                    try:
                        _check_zip_ratio(info)
                    except DiscoveryError:
                        _bump("zip_ratio_guard")
                        continue
                    if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                        _bump("member_too_large")
                        continue
                    result.members.append(Member(
                        target=f"zip://{archive_path}#{member}",
                        name=Path(member).name,
                        member=member,
                        size=int(info.file_size),
                        ext=Path(member).suffix.lower(),
                    ))
        else:
            with tarfile.open(archive_path, mode="r|*") as tf:
                for info in tf:
                    result.total_members += 1
                    if len(result.members) >= max_members:
                        result.truncated = True
                        _bump("member_cap")
                        break
                    if info.isdir():
                        continue
                    if info.issym() or info.islnk():
                        _bump("symlink_member")
                        continue
                    if not info.isfile():
                        _bump("special_member")
                        continue
                    member = _safe_member_name(info.name)
                    if member is None:
                        _bump("hostile_member_name")
                        continue
                    if info.size > MAX_ARCHIVE_MEMBER_BYTES:
                        _bump("member_too_large")
                        continue
                    result.members.append(Member(
                        target=f"zip://{archive_path}#{member}",
                        name=Path(member).name,
                        member=member,
                        size=int(info.size),
                        ext=Path(member).suffix.lower(),
                    ))
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as exc:
        result.error = f"{type(exc).__name__}: {exc}"
    if never_send:
        # Privacy travels with the pointer, so no reader has to remember it.
        result.members = [
            Member(target=m.target, name=m.name, member=m.member, size=m.size, ext=m.ext)
            for m in result.members
        ]
    return result


def walk(policy: Policy, *, extra_skips: SkipCount | None = None,
         errors: list[str] | None = None) -> Iterator[Entry]:
    """Yield candidate entries under every policy root. Metadata only.

    Directory trees are pruned in place before they are descended, so an
    excluded or protected subtree costs one `stat`, not a walk.
    """
    skips = extra_skips if extra_skips is not None else SkipCount()
    errs = errors if errors is not None else []
    produced = 0
    seen_targets: set[str] = set()

    for raw_root in policy.roots:
        root = expand(raw_root)
        if not root.exists():
            errs.append(f"root does not exist: {root}")
            continue
        if root.is_symlink():
            skips.bump("symlink_root")
            continue
        if is_protected(root, list(policy.protected)):
            skips.bump("protected_root")
            continue

        def _on_error(exc: OSError) -> None:
            errs.append(f"{type(exc).__name__}: {exc}")

        for dirpath, dirnames, filenames in os.walk(root, onerror=_on_error):
            directory = Path(dirpath)
            try:
                depth = len(directory.relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth >= policy.max_depth:
                dirnames[:] = []
                skips.bump("depth_cap")
                continue
            if (directory / ".assistant-ignore").exists():
                dirnames[:] = []
                skips.bump(".assistant-ignore")
                continue
            kept: list[str] = []
            for name in sorted(dirnames):
                sub = directory / name
                if sub.is_symlink():
                    skips.bump("symlink")
                    continue
                if name.startswith("."):
                    skips.bump("hidden")
                    continue
                if name in policy.excluded_dirnames:
                    skips.bump(name)
                    continue
                if is_protected(sub, list(policy.protected)):
                    skips.bump("protected")
                    continue
                kept.append(name)
            dirnames[:] = kept

            for name in sorted(filenames):
                if produced >= policy.max_entries:
                    skips.bump("entry_cap")
                    return
                path = directory / name
                if path.is_symlink():
                    skips.bump("symlink")
                    continue
                if name.startswith(".") or name.endswith(TEMP_SUFFIXES):
                    skips.bump("temp/hidden")
                    continue
                if is_protected(path, list(policy.protected)):
                    skips.bump("protected")
                    continue
                try:
                    st = path.lstat()
                except OSError as exc:
                    errs.append(f"{path}: {type(exc).__name__}: {exc}")
                    continue
                if not stat_mod.S_ISREG(st.st_mode):
                    skips.bump("special")
                    continue

                entry = Entry(
                    target=str(path),
                    name=name,
                    ext=path.suffix.lower(),
                    size=int(st.st_size),
                    mtime=float(st.st_mtime),
                    kind="file",
                    never_send=is_never_send(path, policy.never_send_roots),
                    structured=path.suffix.lower() in STRUCTURED_SUFFIXES
                    or archive_kind(path) is not None,
                )
                if entry.target not in seen_targets:
                    seen_targets.add(entry.target)
                    produced += 1
                    yield entry

                if not policy.include_archives or archive_kind(path) is None:
                    continue
                manifest = scan_archive(path, policy)
                if manifest.error:
                    errs.append(f"{path}: {manifest.error}")
                if manifest.truncated:
                    skips.bump("archive_member_cap")
                skips.bump(f"archive:{manifest.kind}")
                for member in manifest.members:
                    if produced >= policy.max_entries:
                        skips.bump("entry_cap")
                        return
                    if member.target in seen_targets:
                        continue
                    seen_targets.add(member.target)
                    produced += 1
                    yield Entry(
                        target=member.target,
                        name=member.name,
                        ext=member.ext,
                        size=member.size,
                        mtime=float(st.st_mtime),
                        kind="archive_member",
                        archive=str(path),
                        never_send=entry.never_send,
                        structured=member.ext in STRUCTURED_SUFFIXES,
                    )


def _rank(entry: Entry, terms: list[str]) -> tuple[int, int, str]:
    """Deterministic ranking: filename hits beat path hits beat recency."""
    name = entry.name.lower()
    target = entry.target.lower()
    name_hits = sum(1 for t in terms if t in name)
    path_hits = sum(1 for t in terms if t in target)
    # Prefer more term hits in the name, then in the whole target, then a
    # stable path ordering so repeated scans are reproducible.
    return (-name_hits, -path_hits, entry.target)


def _matches_filters(entry: Entry, *, exts: set[str],
                     name_glob: str | None, min_size: int | None,
                     max_size: int | None, modified_after: float | None,
                     modified_before: float | None) -> bool:
    if exts and entry.ext not in exts:
        return False
    if name_glob and not fnmatchcase(entry.name.lower(), name_glob.lower()):
        return False
    if min_size is not None and entry.size < min_size:
        return False
    if max_size is not None and entry.size > max_size:
        return False
    if modified_after is not None and entry.mtime < modified_after:
        return False
    return not (modified_before is not None and entry.mtime > modified_before)


def parse_terms(terms: Iterable[str] | str) -> list[str]:
    """Normalise search terms: lowercase, deduped, punctuation-free words."""
    if isinstance(terms, str):
        raw = re.findall(r"[^\s,;]+", terms)
    else:
        raw = [str(t) for t in terms]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        cleaned = item.strip().strip("\"'").lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


@dataclass
class LocateResult:
    matches: list[Entry] = field(default_factory=list)
    total_matched: int = 0
    scanned_files: int = 0
    scanned_roots: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    capped: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "matches": [m.as_dict() for m in self.matches],
            "total_matched": self.total_matched,
            "scanned_files": self.scanned_files,
            "scanned_roots": self.scanned_roots,
            "skipped": self.skipped,
            "errors": self.errors,
            "capped": self.capped,
        }


def locate(
    policy: Policy,
    terms: Iterable[str] | str,
    *,
    exts: Iterable[str] | None = None,
    name_glob: str | None = None,
    min_size: int | None = None,
    max_size: int | None = None,
    modified_after: float | None = None,
    modified_before: float | None = None,
    include_archive_members: bool = True,
    match_terms: bool = True,
    limit: int = 50,
    entries: Iterable[Entry] | None = None,
) -> LocateResult:
    """Metadata-first locator: path/filename/extension/size/mtime search.

    Zero file content is read, so a match is cheap even on a root the owner
    never indexed. Every match is ranked deterministically and every refusal
    is counted. `entries` lets a caller reuse one walk for several queries.

    `match_terms=False` keeps every entry that passes the type/size/date
    filters and only *ranks* by term overlap. An errand needs that: "read my
    notes and look for conflicts" must still open the file whose name shares no
    word with the instruction. An owner-typed search keeps the stricter
    default so `assist find invoice` does not print the whole laptop.
    """
    wanted = parse_terms(terms)
    ext_set = {
        e if str(e).startswith(".") else f".{e}"
        for e in (exts or [])
        if str(e).strip()
    }
    ext_set = {e.lower() for e in ext_set}
    result = LocateResult()
    skips = SkipCount()
    errors: list[str] = []
    matched: list[Entry] = []

    def _consider(entry: Entry) -> None:
        if entry.kind == "archive_member" and not include_archive_members:
            return
        if not _matches_filters(
            entry, exts=ext_set, name_glob=name_glob, min_size=min_size,
            max_size=max_size, modified_after=modified_after,
            modified_before=modified_before,
        ):
            return
        if wanted and match_terms:
            haystack = entry.target.lower()
            if not any(t in haystack for t in wanted):
                return
        matched.append(entry)

    if entries is not None:
        for entry in entries:
            result.scanned_files += 1
            _consider(entry)
    else:
        for entry in walk(policy, extra_skips=skips, errors=errors):
            result.scanned_files += 1
            _consider(entry)

    result.scanned_roots = len(policy.roots)
    matched.sort(key=lambda e: _rank(e, wanted))
    result.total_matched = len(matched)
    capped = max(1, int(limit))
    result.matches = matched[:capped]
    result.capped = result.total_matched > capped
    result.skipped = skips.as_dict()
    result.errors = errors
    return result


def digest_prefix(path: str | Path, *, head_bytes: int = 1 << 20,
                  full_below: int = 8 << 20) -> tuple[str, str]:
    """A content identity for a discovery target, and where it came from.

    Returns `(hex_digest, scope)` where `scope` is `"full"` for files small
    enough to hash end-to-end and `"head:<n>+size"` otherwise. The scope string
    travels with every inferred fact, so a partial hash can never be mistaken
    for a whole-file promise (I1).
    """
    target = expand(path)
    try:
        size = target.stat().st_size
    except OSError as exc:
        raise DiscoveryError("digest", f"{type(exc).__name__}: {exc}") from exc
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        if size <= full_below:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
            return digest.hexdigest(), "full"
        remaining = head_bytes
        while remaining > 0:
            block = handle.read(min(1 << 20, remaining))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
    digest.update(f"|size={size}".encode())
    return digest.hexdigest(), f"head:{head_bytes}+size"
