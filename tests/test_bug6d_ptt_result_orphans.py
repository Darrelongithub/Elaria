"""Hardware Bug 6d (report 2026-10-20): `ptt.result` hung past its budget.

Owner repro on hardware (100% there, 0% in mock/tests): ``assist dictate`` →
speak → Enter blocked in ``ptt.result`` (wait_s=60) for over 10 minutes and
needed Ctrl-C. Afterwards the daemon was healthy but ``ptt_session_id`` was
present with ``dictation_active=false``, ``dictation_processing=false``,
``last_capture=null`` and ``last_transcript=null`` — the session existed,
nothing was processing, and no result/capture stats were ever produced. The
BUG 6c ``_ptt_is_dead_state`` fail-fast never fired.

The flagged race: the result event was set ONLY while the finishing session
was still the daemon's *current* session. If anything changed the session id
(a second session, a state restart, stop handling), the finisher completed
silently — result stored under a dead key — and the waiter parked forever on
an orphaned event. Separately, persona step-log lines (``ptt.start.received``
etc.) were unreachable after the fact: not in the journal, and ``assist
events`` is a live stream with no history replay.

What this file pins (real daemon + real Unix socket where it matters):

1. A session that finishes under a CHANGED session id resolves its waiter
   promptly with that session's terminal answer — the waiter is never left
   on an orphaned event past its budget.
2. A session that finished WITHOUT a result (superseded by a new session,
   or its session state reset) answers with an explicit error payload —
   ``finished_without_result`` — promptly and idempotently.
3. An unknown session id answers explicitly too: every terminal state
   resolves; nothing waits unbounded.
4. ``assist events --recent N`` replays the stored persona step-log
   (``ptt.lifecycle`` etc.) from storage after the fact — no live tail.
5. The IPC client's timeout is a TOTAL deadline even while event frames
   trickle on the connection (the mechanism that stretched a 60 s wait
   into a 10-minute CLI block).
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from assistant.ipc import DaemonOutcomeUnknown, call
from assistant.transcribe import SessionResult

REPO = Path(__file__).resolve().parents[1]


def _result(session_id: str, raw_text: str) -> SessionResult:
    return SessionResult(
        session_id=session_id, raw_text=raw_text, cleaned_text=None,
        backend="gemini_live", language="en", audio_path=None,
        inbox_path=None, clipboard={"copied": False, "reason": "none"},
        flagged=False, duration_s=0.5, notes=[])


class SlowDictation:
    """A Live turn whose transcript lands AFTER the release (and after the
    owner has already pressed the hotkey again)."""

    def __init__(self, delay_s: float = 2.0, text: str = "first session"):
        self.delay_s = delay_s
        self.text = text

    async def dictate(self, source, *, mode="narration", sink=None,
                      stop_event=None, is_playback_active=None,
                      session_id=None):
        await stop_event.wait()
        await asyncio.sleep(self.delay_s)
        return _result(session_id or "slow", self.text)


class SelfFinishingDictation:
    """The dictate task completes on its own — no release ever harvests it."""

    async def dictate(self, source, *, mode="narration", sink=None,
                      stop_event=None, is_playback_active=None,
                      session_id=None):
        return _result(session_id or "done", "lost transcript")


# ===========================================================================
# 1. The required race: the session finishes under a changed session id
# ===========================================================================
def test_session_finishing_under_changed_session_id_resolves_waiter_promptly(
        config, running_daemon):
    daemon, _server = running_daemon
    daemon.dictation = SlowDictation(delay_s=2.0, text="first session")

    first = call(config.socket_path, "ptt.start", {"source": "simulated"},
                 timeout=5.0)
    old_id = first["session_id"]
    stopped = call(config.socket_path, "ptt.stop", timeout=5.0)
    assert stopped["session_id"] == old_id
    assert stopped["processing"] is True

    # The owner presses again BEFORE the old transcript lands: the daemon's
    # current session id changes while the old finisher is still in flight.
    second = call(config.socket_path, "ptt.start", {"source": "simulated"},
                  timeout=5.0)
    assert second["session_id"] != old_id
    assert second.get("already_listening") is not True

    # The waiter asks for the OLD session and is willing to wait 30 s. The
    # answer is already on its way — it must arrive in seconds, not budget.
    began = time.monotonic()
    delivered = call(config.socket_path, "ptt.result",
                     {"session_id": old_id, "wait_s": 30.0}, timeout=35.0)
    elapsed = time.monotonic() - began

    assert elapsed < 8.0, (
        f"ptt.result sat {elapsed:.1f}s for a session that finished under a "
        "changed session_id — the waiter must resolve on that session's "
        "terminal answer, never on a possibly-orphaned event")
    assert delivered["processing"] is False
    assert delivered["terminal"] is True
    assert delivered["result"]["text"] == "first session"
    assert delivered["result"]["session_id"] == old_id, (
        "the old session's waiter must get the old session's result, not the "
        "new session's")

    # The new session is untouched by the old finish (generation-safe).
    status = call(config.socket_path, "status", timeout=5.0)
    assert status["ptt_session_id"] == second["session_id"]
    assert status["dictation_active"] is True

    call(config.socket_path, "ptt.stop", timeout=5.0)


# ===========================================================================
# 2. Superseded with NO result: explicit terminal error payload, promptly
# ===========================================================================
def test_superseded_session_finished_without_result_answers_explicitly(
        config, running_daemon):
    daemon, _server = running_daemon
    daemon.dictation = SelfFinishingDictation()

    first = call(config.socket_path, "ptt.start", {"source": "simulated"},
                 timeout=5.0)
    old_id = first["session_id"]
    time.sleep(0.3)  # the dictate task completed on its own; nobody stopped it

    second = call(config.socket_path, "ptt.start", {"source": "simulated"},
                  timeout=5.0)
    assert second["session_id"] != old_id

    began = time.monotonic()
    answered = call(config.socket_path, "ptt.result",
                    {"session_id": old_id, "wait_s": 30.0}, timeout=35.0)
    elapsed = time.monotonic() - began

    assert elapsed < 2.0, (
        f"ptt.result waited {elapsed:.1f}s on a superseded session with no "
        "result — that is a terminal state and must answer at once")
    result = answered["result"]
    assert answered["processing"] is False
    assert answered["terminal"] is True
    assert result["finished_without_result"] is True
    assert result["superseded"] is True
    assert result["session_id"] == old_id
    assert "superseded" in result["error"]
    assert result["narration"]

    # Idempotent: the same explicit answer, not a fresh wait or a silent None.
    again = call(config.socket_path, "ptt.result",
                 {"session_id": old_id, "wait_s": 30.0}, timeout=35.0)
    assert again["result"] == result


# ===========================================================================
# 3. The hardware after-state: session id present, nothing processing,
#    no result anywhere — the waiter must still resolve, explicitly.
# ===========================================================================
def test_session_state_reset_answers_explicitly_and_promptly(
        config, running_daemon):
    daemon, _server = running_daemon
    # Simulate "session state restarted": a session id is current but the
    # task/finisher/result for it are all gone — exactly the status snapshot
    # from the hardware box after Ctrl-C.
    daemon._ptt_session_id = "reset01"
    daemon._dictation_task = None

    status = call(config.socket_path, "status", timeout=5.0)
    assert status["ptt_session_id"] == "reset01"
    assert status["dictation_active"] is False
    assert status["dictation_processing"] is False

    began = time.monotonic()
    answered = call(config.socket_path, "ptt.result",
                    {"session_id": "reset01", "wait_s": 60.0}, timeout=65.0)
    elapsed = time.monotonic() - began

    assert elapsed < 2.0, (
        f"ptt.result sat {elapsed:.1f}s on a reset session state — the old "
        "code waited its full budget on an event nobody would ever set")
    result = answered["result"]
    assert answered["processing"] is False
    assert result["finished_without_result"] is True
    assert result["session_id"] == "reset01"
    assert "finished without a result" in result["error"]

    # The release path reports the same terminal fate (stop handling was one
    # of the hypothesised orphan causes).
    stopped = call(config.socket_path, "ptt.stop", {"wait_s": 5.0}, timeout=10.0)
    assert stopped["result"]["finished_without_result"] is True


# ===========================================================================
# 4. Unknown session: every terminal state resolves
# ===========================================================================
def test_unknown_session_id_answers_explicitly(config, running_daemon):
    began = time.monotonic()
    answered = call(config.socket_path, "ptt.result",
                    {"session_id": "ghost", "wait_s": 30.0}, timeout=35.0)
    elapsed = time.monotonic() - began

    assert elapsed < 2.0
    result = answered["result"]
    assert answered["processing"] is False
    assert result["finished_without_result"] is True
    assert result["session_id"] == "ghost"
    assert "unknown" in result["error"]


# ===========================================================================
# 5. `assist events --recent N` — the persona step-log, after the fact
# ===========================================================================
def _cli_env():
    return {**os.environ, "PYTHONPATH": str(REPO / "src")}


def _events_rows(stdout: str) -> list[dict]:
    return [json.loads(line) for line in stdout.splitlines() if line.strip()]


def test_events_recent_replays_persona_step_log_from_storage(config):
    from assistant.store import Store

    store = Store(config.db_path)
    store.log_persona_event("2026-10-20T10:00:00+03:00", "ptt.lifecycle",
                            json.dumps({"step": "ptt.start.received",
                                        "params": {"mode": "narration"}}))
    store.log_persona_event("2026-10-20T10:00:01+03:00", "ptt.lifecycle",
                            json.dumps({"step": "ptt.start.session_create",
                                        "session_id": "abc123"}))
    store.log_persona_event("2026-10-20T10:00:02+03:00", "capture.stats",
                            json.dumps({"node": "Mic1", "bytes": 0,
                                        "no_speech": True}))
    store.close()

    # No daemon is running: the post-mortem path reads storage directly.
    out = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "events", "--recent", "50"],
        capture_output=True, text=True, env=_cli_env(), timeout=60,
        check=False)
    assert out.returncode == 0, out.stderr
    rows = _events_rows(out.stdout)
    assert [row["kind"] for row in rows] == [
        "ptt.lifecycle", "ptt.lifecycle", "capture.stats"], (
        "replay must be chronological (oldest first)")
    assert rows[0]["detail"]["step"] == "ptt.start.received"
    assert rows[1]["detail"]["session_id"] == "abc123"
    assert rows[2]["detail"]["node"] == "Mic1"

    # --kind narrows to the step-log the hardware run needs.
    out = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "events", "--recent", "50",
         "--kind", "ptt.lifecycle"],
        capture_output=True, text=True, env=_cli_env(), timeout=60,
        check=False)
    assert out.returncode == 0, out.stderr
    rows = _events_rows(out.stdout)
    assert [row["kind"] for row in rows] == ["ptt.lifecycle", "ptt.lifecycle"]

    # --recent N returns the newest N, still oldest-first among themselves.
    out = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "events", "--recent", "2"],
        capture_output=True, text=True, env=_cli_env(), timeout=60,
        check=False)
    rows = _events_rows(out.stdout)
    assert [row["kind"] for row in rows] == ["ptt.lifecycle", "capture.stats"]


# ===========================================================================
# 6. The transport: a trickle of event frames cannot outlive the deadline
# ===========================================================================
def test_call_is_bounded_by_total_deadline_while_events_trickle(tmp_path):
    sock_path = tmp_path / "trickle.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    stop = threading.Event()

    def trickle():
        try:
            conn, _ = server.accept()
        except OSError:
            return
        try:
            conn.recv(4096)          # the request line
            while not stop.is_set():
                conn.sendall(b'{"event": "transcript.interim"}\n')
                time.sleep(0.05)     # every frame < timeout apart
        except OSError:
            pass
        finally:
            conn.close()

    thread = threading.Thread(target=trickle, daemon=True)
    thread.start()
    try:
        began = time.monotonic()
        with pytest.raises(DaemonOutcomeUnknown):
            call(sock_path, "ptt.result", {"session_id": "x", "wait_s": 60.0},
                 timeout=1.0)
        elapsed = time.monotonic() - began
    finally:
        stop.set()
        server.close()

    assert elapsed < 5.0, (
        f"call rode event trickles for {elapsed:.1f}s past its 1 s timeout — "
        "the timeout must be a TOTAL deadline, not a per-recv one")
