"""Bounded local content extraction (0 model calls, 0 tokens/day)."""

from __future__ import annotations

import html
import json
import re
import xml.etree.ElementTree as ET

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|svg)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_LOGIN_FORM_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_PASSWORD_INPUT_RE = re.compile(r'type\s*=\s*["\']?password["\']?', re.IGNORECASE)
_LOGIN_PHRASE_RE = re.compile(
    r"\b(sign\s+in|log\s+in|login|enter\s+your\s+password|create\s+an\s+account)\b",
    re.IGNORECASE,
)


def is_soft_login_wall(body_text: str, status_code: int) -> bool:
    """Detect a 200 OK page that is actually a login wall."""
    if status_code != 200:
        return False
    if _PASSWORD_INPUT_RE.search(body_text) and _LOGIN_FORM_RE.search(body_text):
        return True
    stripped = _TAG_RE.sub(" ", body_text)
    stripped = _WS_RE.sub(" ", stripped).strip()
    if len(stripped) < 600 and _LOGIN_PHRASE_RE.search(stripped) and _LOGIN_FORM_RE.search(body_text):
        return True
    return False


def extract_content(
    raw_bytes: bytes,
    *,
    content_type: str,
    max_chars: int = 16_000,
) -> tuple[str, str, str]:
    """Return ``(title, text, excerpt)`` bounded to ``max_chars``."""
    decoded = raw_bytes.decode("utf-8", errors="replace")
    ctype = content_type.split(";", 1)[0].strip().lower()

    if ctype == "text/html":
        title_match = _TITLE_RE.search(decoded)
        title = html.unescape(_WS_RE.sub(" ", title_match.group(1)).strip()) if title_match else ""
        cleaned = _SCRIPT_STYLE_RE.sub(" ", decoded)
        text = html.unescape(_TAG_RE.sub(" ", cleaned))
        text = _WS_RE.sub(" ", text).strip()[:max_chars]
        excerpt = text[:280]
        return title, text, excerpt

    if ctype == "application/json":
        try:
            parsed = json.loads(decoded)
            text = json.dumps(parsed, ensure_ascii=False, indent=2)[:max_chars]
        except ValueError:
            text = decoded[:max_chars]
        return "", text, text[:280]

    if ctype in ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml"):
        try:
            root = ET.fromstring(decoded)
            items: list[str] = []
            feed_title = ""
            # RSS 2.0
            channel = root.find("channel")
            if channel is not None:
                t = channel.findtext("title")
                if t:
                    feed_title = t.strip()
                for item in channel.findall("item")[:20]:
                    it_title = (item.findtext("title") or "").strip()
                    it_link = (item.findtext("link") or "").strip()
                    if it_title or it_link:
                        items.append(f"- {it_title} ({it_link})".strip())
            else:
                # Atom
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                t = root.findtext("atom:title", namespaces=ns) or root.findtext("title")
                if t:
                    feed_title = t.strip()
                for entry in (root.findall("atom:entry", namespaces=ns) or root.findall("entry"))[:20]:
                    et_title = (
                        entry.findtext("atom:title", namespaces=ns)
                        or entry.findtext("title")
                        or ""
                    ).strip()
                    if et_title:
                        items.append(f"- {et_title}")
            text = "\n".join(items)[:max_chars] if items else decoded[:max_chars]
            return feed_title, text, text[:280]
        except ET.ParseError:
            text = decoded[:max_chars]
            return "", text, text[:280]

    # text/plain, text/markdown, etc.
    text = _WS_RE.sub(" ", decoded).strip()[:max_chars]
    return "", text, text[:280]
