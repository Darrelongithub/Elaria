"""Planner Tier 0 — deterministic rules cascade (§3.7). ZERO API calls.

Most personal collections are far more deterministic than they look:
invoices say 'invoice', screenshots have predictable names, dated files
carry their date. Tier 0 places that majority locally; the LLM tiers
(Phase 4) only ever see the genuinely ambiguous tail. Rules may only
propose destinations INSIDE the frozen taxonomy (+ _Unsorted) — the
planner cannot invent folders (§3.7), and in Phase 3 cannot write at
all: proposals go to the shadow log for the owner's judgement.

Every proposal carries its rule + reason + confidence so shadow logs
are arguable-with — that's how honest thresholds get set (§4.3).
Decision mapping is §4.4: >=0.90 auto · 0.60–0.89 review · <0.60
_Unsorted · no rule at all = abstain (would escalate to Tier 1).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

# Keyword seeds → substrings looked for in TAXONOMY FOLDER NAMES. A seed
# only fires if a matching folder actually exists in the frozen taxonomy.
KEYWORD_TO_FOLDER_HINTS: dict[str, tuple[str, ...]] = {
    "invoice": ("financ", "invoice", "billing"),
    "receipt": ("financ", "receipt"),
    "payslip": ("financ", "payroll", "salary"),
    "statement": ("financ", "bank"),
    "tax": ("financ", "tax"),
    "bank": ("financ", "bank"),
    "contract": ("legal", "contract", "work"),
    "resume": ("career", "personal", "work"),
    "cv": ("career", "personal", "work"),
    "screenshot": ("screenshot", "image", "picture", "photo"),
    "photo": ("photo", "image", "picture"),
    "lecture": ("school", "study", "lecture", "course"),
    "assignment": ("school", "study", "course"),
    "notes": ("note", "study", "school"),
    "recipe": ("recipe", "food", "cooking"),
    "passport": ("personal", "id", "document"),
    "certificate": ("personal", "certificat"),
}

EXTENSION_TO_FOLDER_HINTS: dict[str, tuple[str, ...]] = {
    ".png": ("image", "photo", "picture", "screenshot"),
    ".jpg": ("image", "photo", "picture"),
    ".jpeg": ("image", "photo", "picture"),
    ".gif": ("image", "photo", "picture"),
    ".mp3": ("music", "audio"),
    ".wav": ("audio", "music"),
    ".opus": ("audio", "voice"),
    ".mp4": ("video", "movie"),
    ".mkv": ("video", "movie"),
    ".zip": ("archive",),
    ".tar": ("archive",),
    ".gz": ("archive",),
    ".7z": ("archive",),
    ".py": ("code", "dev", "project"),
    ".js": ("code", "dev", "project"),
    ".rs": ("code", "dev", "project"),
    ".pdf": ("document", "reference"),
    ".docx": ("document",),
    ".xlsx": ("document", "financ"),
    ".csv": ("data", "document", "financ"),
}

DATE_PREFIX = re.compile(r"^(\d{4})[-_]?(\d{2})[-_]?(\d{2})\b")
YEAR_PREFIX = re.compile(r"^(\d{4})\b")
SCREENSHOT_NAME = re.compile(r"(screenshot|screen[_ ]shot|img_\d{4}|pxl_\d{8})", re.IGNORECASE)


@dataclass
class Proposal:
    src: str
    dest: str | None          # taxonomy folder name (None when abstaining)
    new_name: str | None
    confidence: float
    tier: int
    rule: str
    reason: str
    decision: str             # auto | review | unsorted | abstain
    doc_id: int | None = None

    def as_item(self) -> dict:
        return {"doc_id": self.doc_id, "src": self.src, "dest": self.dest,
                "new_name": self.new_name, "confidence": self.confidence,
                "tier": self.tier, "rule": self.rule, "reason": self.reason,
                "decision": self.decision}


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _folder_matching(hints: tuple[str, ...], taxonomy: list[str]) -> str | None:
    for folder in taxonomy:
        lowered = folder.lower()
        if any(hint in lowered for hint in hints):
            return folder
    return None


def decide(confidence: float, *, auto: float = 0.90, review: float = 0.60) -> str:
    if confidence >= auto:
        return "auto"
    if confidence >= review:
        return "review"
    return "unsorted"


def tier0_propose(path: str, preview: str, taxonomy: list[str], *,
                  doc_id: int | None = None) -> Proposal:
    """Run the deterministic cascade over one indexed document.

    Already filed correctly (parent dir IS a taxonomy folder while the
    document sits at root level)? Tier 0 says so at high confidence —
    most of a tidy archive is verify-in-place, not move work.
    """
    name = Path(path).name
    stem_tokens = _tokens(Path(path).stem)
    suffix = Path(path).suffix.lower()

    # Rule: existing folder token appears in the filename («keyword match
    # against existing folder names», §3.7) — the taxonomy defines the words.
    for folder in taxonomy:
        if folder.startswith("_"):
            continue
        folder_tokens = [t for t in _tokens(folder) if len(t) >= 3]
        if any(t in stem_tokens for t in folder_tokens):
            return Proposal(path, folder, name, 0.92, 0, "folder-keyword",
                            f"filename names taxonomy folder '{folder}'",
                            decide(0.92), doc_id)

    # Rule: seeded keyword in filename → matching existing folder.
    for token in stem_tokens:
        hints = KEYWORD_TO_FOLDER_HINTS.get(token)
        if hints:
            folder = _folder_matching(hints, taxonomy)
            if folder:
                return Proposal(path, folder, name, 0.90, 0, "keyword-seed",
                                f"'{token}' is a known {folder} marker",
                                decide(0.90), doc_id)

    # Rule: screenshot-shaped filenames are unambiguous.
    if SCREENSHOT_NAME.search(name):
        folder = _folder_matching(("screenshot", "image", "photo", "picture"), taxonomy)
        if folder:
            return Proposal(path, folder, name, 0.91, 0, "screenshot-name",
                            "predictable screenshot filename", decide(0.91), doc_id)

    # Rule: date prefix → dated/year/archive folder (§3.7: '2026-03-15_*').
    date_match = DATE_PREFIX.match(name) or YEAR_PREFIX.match(name)
    if date_match:
        year = date_match.group(1)
        folder = next((f for f in taxonomy if year in f), None) or \
            _folder_matching(("archive", "dated"), taxonomy)
        if folder:
            return Proposal(path, folder, name, 0.86, 0, "date-prefix",
                            f"filename is date-prefixed ({year})", decide(0.86), doc_id)

    # Rule: content preview keyword (local text only — still zero quota).
    if preview:
        preview_tokens = set(_tokens(preview[:600]))
        for token, hints in KEYWORD_TO_FOLDER_HINTS.items():
            if token in preview_tokens:
                folder = _folder_matching(hints, taxonomy)
                if folder:
                    return Proposal(path, folder, name, 0.80, 0, "content-keyword",
                                    f"content mentions '{token}' early",
                                    decide(0.80), doc_id)

    # Rule: extension class — weakest signal, review-grade by design.
    hints = EXTENSION_TO_FOLDER_HINTS.get(suffix)
    if hints:
        folder = _folder_matching(hints, taxonomy)
        if folder:
            return Proposal(path, folder, name, 0.70, 0, "extension-class",
                            f"{suffix} files belong with {folder}",
                            decide(0.70), doc_id)

    return Proposal(path, None, None, 0.0, 0, "abstain",
                    "no deterministic rule fired — genuinely ambiguous, "
                    "belongs to Tier 1/2 judgement (Phase 4), never a guess",
                    "abstain", doc_id)


def already_filed(path: str, root: str, taxonomy: list[str]) -> str | None:
    """If the file already sits inside a taxonomy folder under the root,
    the correct proposal is 'leave it' — returned as that folder."""
    try:
        relative = Path(path).relative_to(root)
    except ValueError:
        return None
    if len(relative.parts) >= 2 and relative.parts[0] in taxonomy:
        return relative.parts[0]
    return None


def suggest_taxonomy(root: Path, max_folders: int = 24) -> list[dict]:
    """§10.2 bootstrap: cluster the EXISTING top-level folders, propose
    them (with counts) for the owner to approve + freeze in config.
    Proposal only — nothing here writes config or moves a file."""
    suggestions = []
    if not root.exists():
        return suggestions
    for entry in sorted(os.scandir(root), key=lambda e: e.name):
        if entry.is_dir() and not entry.name.startswith("."):
            count = sum(1 for _, _, files in os.walk(entry.path) for _ in files)
            suggestions.append({"folder": entry.name, "files_below": count})
    suggestions.sort(key=lambda s: -s["files_below"])
    for required in ("_Unsorted", "_Conflicts"):
        if not any(s["folder"] == required for s in suggestions):
            suggestions.append({"folder": required, "files_below": 0,
                                "note": "system folder, always present"})
    return suggestions[:max_folders]
