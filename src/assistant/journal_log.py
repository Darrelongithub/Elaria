"""Structured plain-language daemon log lines on stdout (§4.8, WP0 EYES).

Schema, one line per event, space-separated:

    ts level event session_id peak verdict detail

- `ts`      ISO-8601 local time with offset.
- `level`   info | warn | error.
- `event`   dotted name from the §4.8 list (session.open, session.close,
            silence.verdict, transcription.landed, transcription.deferred,
            transcription.rejected, tts.cached, tts.synthesised, tts.failed,
            quota.counter, watchdog.close, goaway.close — and the stream-F/G
            sensors ws.histogram, audio.sent, audio.first_byte, latency.table,
            final.wait, final.received, final.timeout).
- `session_id`  the ptt/dictation/session id, or `-`.
- `peak`    the measured input peak for the session, or `-`.
- `verdict` one plain word (listening, silence, landed, deferred, rejected,
            cached, synthesised, failed, counted, closed, …), or `-`.
- `detail`  the rest of the line, plain words — the recording path on any
            failure (prime directive: audio is never lost).

Plain words on stdout — journald (StandardOutput=journal) captures them, so
the assistant journal becomes a real sensor instead of an empty file. These
lines are the live window only; the durable record is the store's journal
(persona events, llm_calls, transcripts). Nothing in this module can lose
audio or raise into a caller's path.

Wiring note (WP0): the daemon binds stdout at startup (`assistd`); tests bind
a StringIO per test via the `journal_stream` fixture, so schema lines never
interleave with a CLI's JSON on stdout.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime

_LEVELS = ("info", "warn", "error")
_EMPTY = "-"
_LOCK = threading.Lock()
_STREAM = None  # None -> sys.stdout at write time (bind() overrides)


def bind(stream) -> None:
    """Send schema lines to `stream` (sys.stdout for the daemon)."""
    global _STREAM
    with _LOCK:
        _STREAM = stream


def reset() -> None:
    """Back to the default (sys.stdout at write time)."""
    bind(None)


def current_stream():
    with _LOCK:
        return _STREAM if _STREAM is not None else sys.stdout


def _ts() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _flat(value, *, dash: bool = True) -> str:
    text = " ".join(str(value if value is not None else "").split())
    return text if text else (_EMPTY if dash else "")


def format_line(event: str, *, level: str = "info", session_id: str = "",
                peak=None, verdict: str = "", detail: str = "") -> str:
    """Build one schema line (no I/O) — `event` is the caller's naming."""
    level = str(level).lower()
    if level not in _LEVELS:
        level = "info"
    peak_s = _EMPTY if peak is None or peak == "" else _flat(peak)
    return (f"{_ts()} {level} {_flat(event, dash=False) or 'event'} "
            f"{_flat(session_id)} {peak_s} {_flat(verdict)} "
            f"{_flat(detail, dash=False)}").rstrip()


def log_event(event: str, *, level: str = "info", session_id: str = "",
              peak=None, verdict: str = "", detail: str = "",
              stream=None) -> str:
    """Emit one schema line. Returns the line (for tests/journal mirroring).

    Never raises: a broken log stream must not take a session down.
    """
    line = format_line(event, level=level, session_id=session_id, peak=peak,
                       verdict=verdict, detail=detail)
    try:
        out = stream if stream is not None else current_stream()
        with _LOCK:
            out.write(line + "\n")
            flush = getattr(out, "flush", None)
            if callable(flush):
                flush()
    except Exception:  # noqa: S110 - a broken log stream must not take a session down
        pass
    return line
