"""Markdown inbox — where dictation lands (§3.5: 'you dictate a note
and it appears'). One .md per dictation session, YAML frontmatter for
provenance, cleaned text as the body and the raw transcript preserved
in a details block whenever cleanup changed anything or was flagged.
Local files only; nothing here touches the network."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def write_inbox_note(inbox_dir: Path, *, when: datetime, raw: str,
                     cleaned: str | None, backend: str, language: str,
                     audio_path: str | None, flagged: bool,
                     session_id: str) -> Path:
    inbox_dir = Path(inbox_dir).expanduser()
    inbox_dir.mkdir(parents=True, exist_ok=True)
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
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
