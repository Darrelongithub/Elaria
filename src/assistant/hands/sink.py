"""R4 inert telemetry; explicit stream only, not the operation Journal.

Fixed registry, six fields when detail is omitted, seven otherwise. Local
metadata JSON escapes framing controls. No content/command/output argument.
Invalid session atoms normalize to '-' rather than regex-gating events.
Partial I/O may have emitted bytes: failure is observable, never retried.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping, Sequence
from typing import TextIO

from .registry import EVENTS

_ATOM = re.compile(r"[!-~]+\Z")
_HASH = re.compile(r"[a-fA-F0-9]{64}\Z")
_COUNT_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")


def _atom(value: str) -> str:
    if not isinstance(value, str) or not _ATOM.fullmatch(value):
        raise ValueError("journal header must be a nonempty printable ASCII atom")
    return value


def _strings(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (tuple, list)):
        raise TypeError("metadata requires a list or tuple of strings")
    if any(not isinstance(value, str) for value in values):
        raise ValueError("metadata requires strings")
    return tuple(values)


def format_line(*, ts: str, level: str, event: str, session_id: str, peak: str,
                verdict: str, paths: Sequence[str] | None = None,
                hashes: Sequence[str] | None = None, counts: Mapping[str, int] | None = None,
                argv_sha: str | None = None, reason: str | None = None) -> str:
    """Format only ruled metadata, with two fixed R3 diagnostic exceptions."""
    for value in (ts, level, event, peak, verdict):
        _atom(value)
    if event not in EVENTS or verdict not in EVENTS[event] or "=" in verdict:
        raise ValueError("event/verdict outside R4 registry")
    if peak != "-":
        raise ValueError("hands events have no audio peak")
    # Never use a session regex as an event/log admission gate.
    if session_id != "-" and (not isinstance(session_id, str) or len(session_id) not in (12, 32)
                              or any(c not in "0123456789abcdefABCDEF" for c in session_id)):
        session_id = "-"
    header = f"{ts} {level} {event} {session_id} {peak} {verdict}"
    detail = {}
    if paths is not None:
        detail["paths"] = _strings(paths)
    if hashes is not None:
        values = _strings(hashes)
        if any(not _HASH.fullmatch(value) for value in values):
            raise ValueError("hash metadata must be SHA-256 hex")
        detail["hashes"] = values
    if argv_sha is not None:
        if not isinstance(argv_sha, str) or not _HASH.fullmatch(argv_sha):
            raise ValueError("invalid argv-sha")
        detail["argv-sha"] = argv_sha
    if counts is not None:
        if not isinstance(counts, Mapping):
            raise ValueError("counts must be a mapping")
        for key, value in counts.items():
            if not isinstance(key, str) or not _COUNT_KEY.fullmatch(key):
                raise ValueError("count name must be an identifier")
            if type(value) is not int or value < 0:
                raise ValueError("count must be a nonnegative integer")
        detail["counts"] = dict(counts)
    if reason is not None:
        if (event != "hands.gate" or verdict != "refused" or detail
                or reason not in ("unadjudicable", "two-mismatch-halt")):
            raise ValueError("only fixed R3 refusal diagnostics are allowed")
        return header + " " + ("reason=unadjudicable" if reason == "unadjudicable"
                               else reason) + "\n"
    if not detail:
        return header + "\n"
    encoded = json.dumps(detail, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), allow_nan=False)
    # JSON's short escapes for CR/backspace/formfeed become the R4 unicode
    # spelling. Walk pairs so literal backslashes in paths are not rewritten.
    out, i = [], 0
    controls = {"r": r"\u000d", "b": r"\u0008", "f": r"\u000c"}
    while i < len(encoded):
        if encoded[i] == "\\" and i + 1 < len(encoded):
            out.append(controls.get(encoded[i + 1], encoded[i:i + 2]))
            i += 2
        else:
            out.append(encoded[i])
            i += 1
    return header + " " + "".join(out) + "\n"


class ThinSink:
    """Explicit-stream telemetry, inert on malformed data or ordinary I/O errors.

    A failed write/flush may have emitted partial or complete bytes. False means
    unconfirmed telemetry, NOT proof of no write. There is no retry (which could
    duplicate a line). Counters are process-local sensors, not durable receipts.
    """

    def __init__(self, stream: TextIO):
        self._stream = stream
        self._lock = threading.Lock()
        self.written = 0
        self.dropped = 0

    def emit(self, **fields) -> bool:
        with self._lock:
            try:
                line = format_line(**fields)
                if self._stream.write(line) != len(line):
                    raise OSError("short telemetry write")
                self._stream.flush()
            except Exception:
                # Do not log the exception: it could contain private content.
                self.dropped += 1
                return False
            self.written += 1
            return True
