"""WATCH ingestion filter — role-before-property, tombstones, caps (design §6).

Daemon-side, pure, testable without a bus. The watcher child (BUILD-3) walks
the AT-SPI tree; this module decides what may enter RAM. Rail 1: a password
field's *existence* (role + rect) is known, its identity/value can never be
stored — the tombstone type has no name field at all.

Rules (design §6 + D1):
- Role is read before any property. PASSWORD_TEXT short-circuits before
  get_name()/get_description()/get_text()/get_value() are ever called.
- SECRET name hits (any role) become tombstones; the name is dropped.
- Names capped at 64 chars (tightening the one-shot helper's 256).
- D1 geometry-only roles (label/static/paragraph/terminal/document) keep
  geometry with name=None; controls keep names.
- Window titles/apps: SECRET-screened, 64-char capped, else "" (§6.5).

Zero cloud API budget: this module makes no provider calls, ever. It imports
only stdlib, disclosure (SECRET patterns) and journal_log (metadata lines).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import journal_log
from .disclosure import SECRET_PATTERNS

# Same construction as observation.SECRET: shared patterns plus the
# observation-only extras. Single source remains disclosure.SECRET_PATTERNS.
SECRET = re.compile(
    "|".join((*SECRET_PATTERNS, r"\b(?:card|otp|ssn|seed|recovery)\b")),
    re.IGNORECASE,
)

MAX_NAME_LEN = 64

# Normalised role names (casefolded, _/- → space, whitespace collapsed).
_SENSITIVE_ROLES = frozenset({"password text"})

# D1: these roles are geometry-only — name is never stored.
_GEOMETRY_ONLY_ROLES = frozenset(
    {"label", "static", "paragraph", "terminal", "document"}
)

Rect = tuple[float, float, float, float]


def normalize_role(role: object) -> str:
    """Canonical role key for policy checks."""
    text = " ".join(str(role or "").casefold().replace("_", " ").replace("-", " ").split())
    return text


def is_sensitive_role(role: object) -> bool:
    return normalize_role(role) in _SENSITIVE_ROLES


def is_geometry_only_role(role: object) -> bool:
    return normalize_role(role) in _GEOMETRY_ONLY_ROLES


def is_secret_text(text: object) -> bool:
    """True when `text` matches the SECRET screen (name or title)."""
    return bool(SECRET.search(str(text or "")))


def cap_name(name: object) -> str:
    """Cap a stored name/title at MAX_NAME_LEN chars."""
    return str(name or "")[:MAX_NAME_LEN]


def filter_title(title: object) -> str:
    """§6.5: SECRET-screened, 64-char capped; "" on hit (ordinal spoken later)."""
    text = str(title or "")
    if is_secret_text(text):
        return ""
    return cap_name(text)


def filter_app(app: object) -> str:
    """App names get the same screen + cap as titles (§5.1)."""
    text = str(app or "")
    if is_secret_text(text):
        return ""
    return cap_name(text)


@dataclass(frozen=True)
class Tombstone:
    """Sensitive geometry only. No name/value field exists by construction."""

    window: str
    parent: int | None
    role: str
    rect: Rect

    @property
    def sensitive(self) -> bool:
        return True

    @property
    def kind(self) -> str:
        return "tombstone"


@dataclass(frozen=True)
class Node:
    """Stored element. name is None for geometry-only roles."""

    window: str
    parent: int | None
    role: str
    rect: Rect
    name: str | None

    @property
    def sensitive(self) -> bool:
        return False

    @property
    def kind(self) -> str:
        return "element"


def _rect_from_node(node, coord_type: str = "window") -> Rect | None:
    """Extract (x, y, w, h) from a node-like object, or None if no geometry.

    Reads extents only — never name/description/text/value. Returns None when
    the node has no component or the extents are invalid, so the caller can
    skip the node (same fail-closed rule as the one-shot helper).
    """
    get_component = getattr(node, "get_component_iface", None)
    if callable(get_component):
        try:
            target = get_component()
        except Exception:
            return None
        if target is None:
            return None  # no component → no geometry (one-shot helper rule)
    else:
        target = node
    get_extents = getattr(target, "get_extents", None)
    if not callable(get_extents):
        return None
    try:
        r = get_extents(coord_type)
    except Exception:
        return None
    try:
        x, y, w, h = float(r.x), float(r.y), float(r.width), float(r.height)
    except (AttributeError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0 or x == -2147483648 or y == -2147483648:
        return None
    return (x, y, w, h)


def ingest_node(node, window_key: str, parent: int | None = None,
                coord_type: str = "window") -> Node | Tombstone | None:
    """Ingest one node-like object. Role first; properties only if allowed.

    - PASSWORD_TEXT → Tombstone (role + rect only; get_name never called).
    - SECRET name hit → Tombstone (name dropped after the test).
    - Geometry-only role → Node(name=None).
    - Otherwise → Node(name=capped).
    Returns None when the node has no valid geometry.
    """
    # 1. Role before any property read (rail 1).
    get_role = getattr(node, "get_role", None)
    if not callable(get_role):
        return None
    try:
        raw_role = get_role()
    except Exception:
        return None
    role = normalize_role(raw_role)

    # 2. Sensitive role short-circuits BEFORE any name/description/text/value.
    if role in _SENSITIVE_ROLES:
        rect = _rect_from_node(node, coord_type)
        if rect is None:
            return None
        journal_log.log_event(
            "watch.ingest", level="info", verdict="tombstone",
            detail=f"window={window_key} role=password text",
        )
        return Tombstone(window=window_key, parent=parent, role="password text", rect=rect)

    # 3. Non-sensitive: name may be read (capped, SECRET-screened).
    get_name = getattr(node, "get_name", None)
    raw_name = ""
    if callable(get_name):
        try:
            raw_name = str(get_name() or "")
        except Exception:
            return None

    # SECRET name hit → tombstone; the name is dropped right after the test.
    if is_secret_text(raw_name):
        rect = _rect_from_node(node, coord_type)
        if rect is None:
            return None
        journal_log.log_event(
            "watch.ingest", level="info", verdict="tombstone",
            detail=f"window={window_key} role={role} reason=secret-name",
        )
        return Tombstone(window=window_key, parent=parent, role=role, rect=rect)

    rect = _rect_from_node(node, coord_type)
    if rect is None:
        return None

    # D1: geometry-only text roles never store a name.
    if role in _GEOMETRY_ONLY_ROLES:
        return Node(window=window_key, parent=parent, role=role, rect=rect, name=None)

    return Node(window=window_key, parent=parent, role=role, rect=rect,
                name=cap_name(raw_name))


def ingest_delta(delta: dict, window_key: str, parent: int | None = None) -> Node | Tombstone | None:
    """Ingest a dict delta (NDJSON row from the watcher child).

    Defence in depth: even though the child should have filtered already,
    the daemon re-applies the SECRET screen and D1 here. The role-before-
    property guarantee cannot be proven for dicts (the name was already
    read), so this path only drops — it never trusts.
    """
    if not isinstance(delta, dict):
        return None
    role = normalize_role(delta.get("role", ""))
    rect_raw = delta.get("rect")
    if not isinstance(rect_raw, (list, tuple)) or len(rect_raw) != 4:
        return None
    try:
        rect = tuple(float(v) for v in rect_raw)  # type: ignore[assignment]
    except (TypeError, ValueError):
        return None
    if rect[2] <= 0 or rect[3] <= 0:  # type: ignore[operator]
        return None

    if role in _SENSITIVE_ROLES:
        journal_log.log_event(
            "watch.ingest", level="info", verdict="tombstone",
            detail=f"window={window_key} role=password text",
        )
        return Tombstone(window=window_key, parent=parent, role="password text", rect=rect)  # type: ignore[arg-type]

    raw_name = str(delta.get("name", "") or "")
    if is_secret_text(raw_name):
        journal_log.log_event(
            "watch.ingest", level="info", verdict="tombstone",
            detail=f"window={window_key} role={role} reason=secret-name",
        )
        return Tombstone(window=window_key, parent=parent, role=role, rect=rect)  # type: ignore[arg-type]

    if role in _GEOMETRY_ONLY_ROLES:
        return Node(window=window_key, parent=parent, role=role, rect=rect, name=None)  # type: ignore[arg-type]

    return Node(window=window_key, parent=parent, role=role, rect=rect,
                name=cap_name(raw_name))  # type: ignore[arg-type]
