"""Shared containment for discovery / streaming entry points (BUG-A2).

Every file-reading surface — the daemon's ``fs.locate``, ``file.inspect``
and ``file.read`` IPC handlers, and the errand ``fs.locate`` /
``file.read_batch`` / ``file.read`` / ``file.inspect`` steps — draws its
read scope from this one helper instead of re-implementing root rules per
handler:

* the outer authority is the configured ``[discovery] roots`` (plus
  ``[[organise.roots]]``), exactly what ``config.discovery_roots()`` reports;
* caller-supplied roots may **narrow** that scope, never widen it — any
  caller root outside the configured scope fails closed with
  ``PermissionError``;
* archive members (``zip://<archive>#<member>`` / ``tar://``) are contained
  by their **archive** path, never by the member name;
* protected-path and ``never_send_to_cloud`` rules stay in force inside the
  readers (``streamread`` / ``skill_file_*``) — this helper never relaxes
  them, and empty authorized scope denies every read (fail closed);
* errand read steps inherit owner authorization and show-off refusal from
  ``errand.start`` (the authenticated boundary that opened the errand), so
  the per-step containment here is scope + protected + journal, identical
  for all read steps. The daemon IPC handlers additionally gate on
  ``_require_ipc_owner()`` and an active show-off session.
"""

from __future__ import annotations

from pathlib import Path

from .safety import expand, is_protected

_ARCHIVE_PREFIXES = ("zip://", "tar://")


def configured_discovery_roots(config) -> list[str]:
    """The configured ``[discovery]``/``[[organise.roots]]`` scope (absolute-ish paths)."""
    if config is None:
        return []
    getter = getattr(config, "discovery_roots", None)
    if not callable(getter):
        return []
    try:
        entries = getter() or []
    except Exception:
        return []
    roots: list[str] = []
    for entry in entries:
        raw = entry.get("path") if isinstance(entry, dict) else entry
        text = str(raw or "").strip()
        if text:
            roots.append(str(expand(text)))
    return roots


def target_scope_path(target: str | Path) -> Path:
    """The filesystem path a target must be contained by.

    Archive members are contained by their archive file; plain paths are
    contained as themselves. Always ``expand()``-ed (``~``/env vars resolved).
    """
    text = str(target)
    for prefix in _ARCHIVE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].split("#", 1)[0]
            break
    return expand(text)


def within_roots(target: str | Path, roots: list[str] | tuple[str, ...] | None) -> bool:
    """True when `target` (archive members included) lies inside `roots`."""
    base = [str(expand(r)) for r in (roots or []) if str(r).strip()]
    if not base:
        return False
    try:
        return bool(is_protected(target_scope_path(target), base))
    except Exception:
        return False


def narrow_roots(
    requested: list | None,
    base_roots: list[str] | tuple[str, ...] | None,
    *,
    subject: str = "discovery root",
) -> list[str]:
    """Caller-supplied roots may narrow `base_roots`, never widen it (BUG-A2).

    ``requested=None`` selects the full configured scope. Any requested root
    not contained in `base_roots` fails closed with `PermissionError`.
    """
    base = [str(expand(r)) for r in (base_roots or []) if str(r).strip()]
    if requested is None:
        return base
    narrowed: list[str] = []
    for raw in list(requested):
        text = str(raw).strip()
        if not text:
            continue
        candidate = str(expand(text))
        if not base or not is_protected(candidate, base):
            raise PermissionError(f"{subject} outside authorized scope: {candidate}")
        narrowed.append(candidate)
    return narrowed


def require_within_roots(
    target: str | Path,
    roots: list[str] | tuple[str, ...] | None,
    *,
    subject: str = "source",
) -> Path:
    """Fail closed unless `target` lies inside `roots` (BUG-A2)."""
    scoped = target_scope_path(target)
    if not within_roots(target, roots):
        raise PermissionError(f"{subject} outside authorized discovery roots")
    return scoped
