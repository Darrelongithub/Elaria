"""Markdown inbox — where dictation lands (§3.5: 'you dictate a note
and it appears'). One .md per dictation session, YAML frontmatter for
provenance, cleaned text as the body and the raw transcript preserved
in a details block whenever cleanup changed anything or was flagged.
Local files only; nothing here touches the network."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .config import ensure_private_dir


def write_private_text(path: Path, text: str, *, append: bool = False,
                       exclusive: bool = False) -> Path:
    """Write an owner-only note, securing existing files before changing bytes (I5)."""
    path = Path(path)
    flags = os.O_WRONLY | os.O_CREAT
    if append:
        flags |= os.O_APPEND
    if exclusive:
        flags |= os.O_EXCL
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        if not append and not exclusive:
            os.ftruncate(fd, 0)
        handle = os.fdopen(fd, "a" if append else "w", encoding="utf-8")
        fd = None
        with handle:
            handle.write(text)
    finally:
        if fd is not None:
            os.close(fd)
    return path


def write_inbox_note(inbox_dir: Path, *, when: datetime, raw: str,
                     cleaned: str | None, backend: str, language: str,
                     audio_path: str | None, flagged: bool,
                     session_id: str) -> Path:
    inbox_dir = ensure_private_dir(Path(inbox_dir).expanduser())
    stamp = when.strftime("%Y%m%d-%H%M%S")
    path = inbox_dir / f"{stamp}-dictation-{session_id[:6]}.md"
    body = cleaned if (cleaned and not flagged) else raw
    lines = [
        "---",
        f"date: {when.isoformat(timespec='seconds')}",
        f"source: dictation ({backend})",
        f"language: {language}",
        f"audio: {audio_path or 'not saved'}",
        f"flagged: {str(flagged).lower()}",
        "---",
        "",
        body.strip(),
        "",
    ]
    if cleaned and cleaned.strip() != raw.strip():
        # Raw is the record (§12.5) — keep it one fold away, always.
        lines += [
            "<details><summary>Raw transcript (the record)</summary>",
            "",
            raw.strip(),
            "",
            "</details>",
            "",
        ]
    if flagged:
        lines.append("> ⚠️ Cleanup was flagged by a safety gate — the text above is the "
                     "raw transcript. See `assist cost`/transcript log for the reason.\n")
    write_private_text(path, "\n".join(lines))
    return path


def append_cloud_transcript(path: Path, *, cloud_text: str,
                            offline_text: str | None) -> Path:
    """Phase 8 reconnect pass: append, never erase the offline placeholder."""
    path = Path(path).expanduser()
    lines = [
        "",
        "## Cloud re-transcription (after reconnect)",
        "",
        cloud_text.strip(),
        "",
    ]
    if offline_text and offline_text.strip() != cloud_text.strip():
        lines += [
            "<details><summary>Offline placeholder (preserved)</summary>",
            "",
            offline_text.strip(),
            "",
            "</details>",
            "",
        ]
    write_private_text(path, "\n".join(lines), append=True)
    return path
