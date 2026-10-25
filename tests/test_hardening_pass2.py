"""Second full-repo hardening pass — regressions for bugs found on 2026-10-20.

Every test here was written BEFORE its fix and reproduces a state-level bug on
`25179c8` (the merge of the Stage A–D pass). Sandboxes only: temp XDG dirs,
temp SQLite, fake transports. No real folders, keys or voiceprints.

Bug IDs are recorded in `bugs.md` (BH-I1..) and changes in `change.md`.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import socket
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant.config import (
    DEFAULT_VOICE_MODEL,
    load_config,
    validate_config,
    voice_model,
)
from assistant.daemon import Daemon
from assistant.initiative import InitiativeService, NeedinessError, ensure_not_needy
from assistant.ipc import DaemonOutcomeUnknown, call, serve, subscribe_events
from assistant.showoff import ShowoffService
from assistant.store import Store
from assistant.tts import SpeechService
from assistant.voice_catalogue import (
    CATALOGUE_STATE_KEY,
    live_catalogue,
    load_cached,
    resolve_catalogue,
    save_cached,
)

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def _sandbox_config(tmp_path: Path, **overrides):
    cfg = load_config()
    cfg.raw["tts"]["cache_dir"] = str(tmp_path / "data" / "tts_cache")
    cfg.raw["tts"]["audition_dir"] = str(tmp_path / "data" / "auditions")
    cfg.raw["voice_test"]["voiceprint_path"] = str(tmp_path / "data" / "voiceprint.json")
    cfg.raw["voice_test"]["embedding_dim"] = 4
    cfg.raw["showoff"]["sandbox"] = str(tmp_path / "data" / "demo_sandbox")
    for section, values in overrides.items():
        if isinstance(values, dict) and isinstance(cfg.raw.get(section), dict):
            cfg.raw[section].update(values)
        else:
            cfg.raw[section] = values
    cfg.ensure_dirs()
    return cfg


def _write_voiceprint(path: Path) -> list[float]:
    path.parent.mkdir(parents=True, exist_ok=True)
    vec = [1.0, 0.0, 0.0, 0.0]
    path.write_text(json.dumps({"model": "ecapa-tdnn", "dimension": 4,
                                "centroid": vec}), encoding="utf-8")
    path.chmod(0o600)
    return vec


def _fake_server(path: Path, *, reply: bytes, connections: int = 1,
                 hold_open: bool = False):
    """Serve `connections` one-shot clients, sending `reply` to each."""

    ready = threading.Event()

    def run():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
            srv.bind(str(path))
            srv.listen(connections)
            ready.set()
            for _ in range(connections):
                conn, _addr = srv.accept()
                with conn:
                    try:
                        conn.recv(4096)
                        conn.sendall(reply)
                        if hold_open:
                            time.sleep(0.5)
                    except OSError:
                        pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    assert ready.wait(timeout=2.0), "fake Unix-socket server did not start listening"
    return thread


# --------------------------------------------------------------------------
# BH-I1 — deprecated `model_voice` shadowed an explicit `gemini_voice_model`
# --------------------------------------------------------------------------


def test_voice_model_explicit_new_key_wins_over_legacy_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """The legacy alias may fill a gap; it may never overrule the named key."""
    path = _write_config(tmp_path, f"""
[gemini]
gemini_voice_model = "{DEFAULT_VOICE_MODEL}"
model_voice = "gemini-3.1-flash-live-preview"
""")
    monkeypatch.setenv("ASSIST_CONFIG", str(path))
    cfg = load_config()
    assert voice_model(cfg) == DEFAULT_VOICE_MODEL


def test_voice_model_legacy_alias_is_still_read_when_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """An owner file that only has the old key keeps working (BH-H4 contract)."""
    path = _write_config(tmp_path, """
[gemini]
model_voice = "gemini-3.1-flash-live-preview"
""")
    monkeypatch.setenv("ASSIST_CONFIG", str(path))
    cfg = load_config()
    assert voice_model(cfg) == "gemini-3.1-flash-live-preview"


# --------------------------------------------------------------------------
# BH-I2 — config poisoning passed validation and crashed consumers
# --------------------------------------------------------------------------


def test_validate_config_names_poisoned_keys(tmp_path: Path):
    cfg = _sandbox_config(tmp_path)
    cfg.raw["gemini"]["mode"] = "bogus"
    cfg.raw["gemini"]["allowed_voices"] = 5
    cfg.raw["tts"]["speaker"] = "loud"
    cfg.raw["tts"]["length_scale"] = "fast"
    cfg.raw["console"]["history_limit"] = 0
    cfg.raw["organise"]["roots"] = [{"mode": "liv"}]
    result = validate_config(cfg)
    joined = " | ".join(result["errors"])
    for key in ("[gemini] mode", "[gemini] allowed_voices", "[tts] speaker",
                "[tts] length_scale", "[console] history_limit",
                "[organise.roots]"):
        assert key in joined, f"{key} not named in: {joined}"
    assert result["ok"] is False


def test_doctor_survives_poisoned_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    """`assist doctor` must report a broken key, not traceback on it."""
    from assistant.cli import run_doctor

    path = _write_config(tmp_path, """
[gemini]
allowed_voices = 5
[tts]
speaker = "loud"
[organise.roots]
mode = "liv"
""")
    monkeypatch.setenv("ASSIST_CONFIG", str(path))
    cfg = load_config()
    report = run_doctor(cfg)
    schema = next(c for c in report["checks"] if c["check"] == "config schema")
    assert schema["status"] == "fail"
    doctored = " ".join(c["detail"] for c in report["checks"])
    assert "allowed_voices" in doctored or "config schema" in doctored


def test_speech_status_survives_poisoned_tts_values(tmp_path: Path):
    cfg = _sandbox_config(tmp_path)
    cfg.raw["gemini"]["allowed_voices"] = 5
    cfg.raw["tts"]["speaker"] = "loud"
    cfg.raw["tts"]["length_scale"] = "fast"
    status = SpeechService(cfg).status()  # must not raise
    assert status["available"] is True
    assert status["voice_identity"]["allowed"] is True


def test_organise_roots_rejects_bad_entries(tmp_path: Path):
    cfg = _sandbox_config(tmp_path)
    cfg.raw["organise"]["roots"] = [{"mode": "shadow"}]
    with pytest.raises(ValueError, match=r"organise\.roots.*path"):
        cfg.organise_roots()

    cfg.raw["organise"]["roots"] = [{"path": "/tmp/x", "mode": "liv"}]
    with pytest.raises(ValueError, match=r"organise\.roots.*mode"):
        cfg.organise_roots()

    # Wrong *shape* is a TypeError (ruff TRY004); wrong *value* is ValueError.
    cfg.raw["organise"]["roots"] = ["not-a-table"]
    with pytest.raises((TypeError, ValueError), match=r"organise\.roots"):
        cfg.organise_roots()


# --------------------------------------------------------------------------
# BH-I3 — `[console] history_limit` was ignored by the daemon's session
# --------------------------------------------------------------------------


def test_daemon_uses_console_history_limit(tmp_path: Path):
    cfg = _sandbox_config(tmp_path, console={"history_limit": 1})
    daemon = Daemon(cfg)
    try:
        assert daemon.sessions.history_limit == 1
        daemon.sessions.append("user", "one")
        daemon.sessions.append("user", "two")
        assert len(daemon.sessions.history()["messages"]) == 1
    finally:
        daemon.store.close()


# --------------------------------------------------------------------------
# BH-I4 — a timed-out reply was spoken a second time, overlapping the first
# --------------------------------------------------------------------------


class _SlowSpeech:
    def __init__(self, delay: float = 1.7):
        self.delay = delay
        self.calls: list[str] = []

    def route(self, text: str) -> dict:
        return {"backend": "mock", "voice_id": "mock", "voice_mode": "mock",
                "muted": False, "local": False, "cloud_voice": False}

    def status(self) -> dict:
        return {"muted": False}

    def speak(self, text: str, play: bool = True):
        self.calls.append(text)
        time.sleep(self.delay)
        return SimpleNamespace(error=None, as_dict=lambda: {
            "text": text, "backend": "mock", "voice_id": "mock",
            "audio_path": None, "played": False, "muted": False, "error": None,
        })


def test_timed_out_reply_is_spoken_once(tmp_path: Path):
    cfg = _sandbox_config(tmp_path)
    daemon = Daemon(cfg)
    daemon.speech = _SlowSpeech()
    try:
        async def run():
            out = await daemon._maybe_speak_reply("hello there", {"speak": True})
            pending = list(daemon._background_tasks)
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            return out

        out = asyncio.run(run())
        assert out["queued"] is True
        assert daemon.speech.calls == ["hello there"], (
            "a timed-out reply must not be synthesised and played twice"
        )
    finally:
        daemon.store.close()


# --------------------------------------------------------------------------
# BH-I5 — post-guard substring echo check swallowed real short user replies
# --------------------------------------------------------------------------


def test_short_user_reply_is_not_echo_after_guard(tmp_path: Path):
    cfg = _sandbox_config(tmp_path)
    daemon = Daemon(cfg)
    try:
        daemon._set_speaking(True, text="No. Not at this hour.")
        daemon._speaking_until = 0.0          # guard has elapsed
        assert daemon._is_echo("No.") is False, (
            "a one-word user reply must not be eaten because she said it first"
        )
        assert daemon._is_echo("No. Not at this hour.") is True
    finally:
        daemon.store.close()


# --------------------------------------------------------------------------
# BH-I6 — crash-exit of show-off deleted EVERY dictation/meeting recording
# --------------------------------------------------------------------------


def test_showoff_crash_recovery_never_deletes_dictation_or_meeting_audio(
    tmp_path: Path,
):
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        emb = _write_voiceprint(Path(cfg.section("voice_test")["voiceprint_path"]))
        first = ShowoffService(cfg, store)
        first.enter(command="Elaria, show off", embedding=emb, owner_present=True)

        audio_dir = cfg.data_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        meeting = audio_dir / "meeting-2026-10-20-101010-mic.wav"
        dictation = audio_dir / "20261020-101010-abcdef.wav"
        meeting.write_bytes(b"RIFF-meeting")
        dictation.write_bytes(b"RIFF-dictation")

        sandbox = first.sandbox_path()
        sandbox.mkdir(parents=True, exist_ok=True)
        demo_residue = sandbox / "guest-demo.wav"
        demo_residue.write_bytes(b"RIFF-demo")

        ShowoffService(cfg, store)          # the restart after `kill -9`

        assert meeting.exists(), "crash recovery deleted a meeting recording"
        assert dictation.exists(), "crash recovery deleted a dictation recording"
        assert not demo_residue.exists(), "demo-sandbox audio survived recovery"
    finally:
        store.close()


# --------------------------------------------------------------------------
# BH-I7 — `initiative.status()["latest"]` returned the OLDEST pending knock
# --------------------------------------------------------------------------


def test_initiative_latest_is_newest_pending(tmp_path: Path):
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        svc = InitiativeService(cfg, store)
        svc.raise_knock(topic="invoice", reason="You asked me to chase the invoice.",
                        kind="checkin", referent="invoice")
        newest = svc.raise_knock(topic="tax", reason="You asked me to chase the tax office.",
                                 kind="checkin", referent="tax office")
        assert svc.status()["latest"]["id"] == newest["id"]
    finally:
        store.close()


def test_due_loop_refusal_is_logged_not_swallowed(tmp_path: Path):
    """A snooze that can never be re-raised must leave a reason, not silence."""
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        svc = InitiativeService(cfg, store)
        commitment = svc.create_commitment("chase the invoice", origin="user-request")
        knock = svc.raise_knock(topic="invoice", reason="You asked me to chase the invoice.",
                                kind="checkin", referent="invoice")
        store.update_knock(knock["id"], status="snoozed",
                           snooze_until="2020-01-01T00:00:00",
                           commitment_id=commitment["commitment_id"])
        # Poison the reason so raise_knock must refuse on the due loop.
        with store._lock:
            store._conn.execute("UPDATE knocks SET reason = ? WHERE id = ?",
                                ("I've been waiting for you", knock["id"]))
            store._conn.commit()

        assert svc.check_due() == []
        events = store.list_persona_events(kind="knock_due_refused", limit=5)
        assert events, "a refused due knock was silently dropped forever"
        assert "refused" in events[0]["detail"]
    finally:
        store.close()


# --------------------------------------------------------------------------
# BH-I8 — two daemons could still race the check-unlink-bind window
# --------------------------------------------------------------------------


def test_ipc_serve_refuses_when_daemon_lock_is_held(tmp_path: Path):
    socket_path = tmp_path / "assistant.sock"
    lock_path = socket_path.with_name(socket_path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("", encoding="utf-8")
    with open(lock_path, "r+", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        async def handler(method, params):
            return {}

        with pytest.raises(RuntimeError, match="already running"):
            asyncio.run(serve(socket_path, handler))
        fcntl.flock(held.fileno(), fcntl.LOCK_UN)


def test_ipc_serve_reclaims_stale_lock(tmp_path: Path):
    socket_path = tmp_path / "assistant.sock"
    (tmp_path / "assistant.sock.lock").write_text("", encoding="utf-8")

    async def handler(method, params):
        return {"ok": True}

    async def once():
        server = await serve(socket_path, handler)
        server.close()
        await server.wait_closed()

    asyncio.run(once())
    # The lock must be released with the server, or the next daemon is locked
    # out forever by a dead one.
    asyncio.run(once())


# --------------------------------------------------------------------------
# BH-I9 — malformed IPC frames crashed the CLI instead of reporting the daemon
# --------------------------------------------------------------------------


def test_ipc_call_malformed_reply_has_unknown_outcome_after_send(tmp_path: Path):
    path = tmp_path / "fake.sock"
    _fake_server(path, reply=b"{not json}\n")
    with pytest.raises(DaemonOutcomeUnknown, match="may have processed"):
        call(path, "ping", timeout=2.0)


def test_ipc_call_empty_reply_after_send_has_unknown_outcome(tmp_path: Path):
    path = tmp_path / "empty.sock"
    thread = _fake_server(path, reply=b"")
    with pytest.raises(DaemonOutcomeUnknown, match="closed without replying"):
        call(path, "queue.enqueue_external", {"action": "download"}, timeout=2.0)
    thread.join(timeout=2.0)


def test_subscribe_events_skips_malformed_lines(tmp_path: Path):
    path = tmp_path / "events.sock"
    _fake_server(path, reply=b'not json\n{"event": "x", "id": 1, "ok": true}\n')
    events = list(subscribe_events(path))
    assert any(e.get("event") == "x" for e in events)


def test_play_audio_timeout_is_reported(tmp_path: Path):
    import subprocess

    cfg = _sandbox_config(tmp_path)
    cfg.raw["tts"]["player"] = "cat"

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=120)

    speech = SpeechService(cfg, player_runner=boom)
    assert speech.play_audio(tmp_path / "x.wav") is False
    assert "timeout" in (speech.last_voice_error or "").lower()


# --------------------------------------------------------------------------
# BH-I10 — a failed catalogue refresh threw away a good verified cache
# --------------------------------------------------------------------------


def test_catalogue_refresh_falls_back_to_verified_cache(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    try:
        save_cached(store, live_catalogue("m", ["Flare"]))
        out = resolve_catalogue("m", store=store, refresh=True, fetched=None)
        assert out["source"] == "live-api" and out["verified"] is True
    finally:
        store.close()


def test_catalogue_refresh_uses_stale_verified_cache_before_baseline(tmp_path: Path):
    """A verified-but-stale cache still beats a baseline nobody ever checked."""
    store = Store(tmp_path / "db.sqlite")
    try:
        stale = live_catalogue("m", ["Flare"])
        stale["retrieved"] = "2020-01-01T00:00:00+00:00"
        save_cached(store, stale)
        out = resolve_catalogue("m", store=store, refresh=True, fetched=None)
        assert out["source"] == "live-api" and out["verified"] is True
        assert "older than" in out["reason"]
    finally:
        store.close()


def test_catalogue_cache_without_timestamp_is_not_trusted(tmp_path: Path):
    store = Store(tmp_path / "db.sqlite")
    try:
        store.set_state(CATALOGUE_STATE_KEY,
                        json.dumps({"model": "m", "verified": True,
                                    "voices": ["Flare"]}))
        assert load_cached(store, "m") is None
    finally:
        store.close()


# --------------------------------------------------------------------------
# BH-I11 — needy framing survived paraphrases
# --------------------------------------------------------------------------


@pytest.mark.parametrize("phrase", [
    "it's been quiet lately",
    "just checking you still want me",
    "hope you're doing okay without me",
    "it feels empty here",
    "where have you been?",
    "you've been away",
    "nothing but silence around here",
])
def test_needy_paraphrases_rejected(phrase: str):
    with pytest.raises(NeedinessError):
        ensure_not_needy(phrase, where="fuzz")


# --------------------------------------------------------------------------
# BH-I12 — a guest turn had no network timeout at all
# --------------------------------------------------------------------------


class _SleepyClient:
    mode = "live"
    calls = 0

    def can_speak(self) -> bool:
        return False

    def generate(self, *args, **kwargs):
        type(self).calls += 1
        time.sleep(0.2)
        return SimpleNamespace(text="guest answer", model="fake", fixture=None)

    def voice_request(self, text, *, voice=None):
        return {"model": "fake", "voice_name": voice or "Flare", "text": text,
                "response_modalities": ["AUDIO"]}


def test_guest_turn_is_time_bounded(tmp_path: Path):
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        emb = _write_voiceprint(Path(cfg.section("voice_test")["voiceprint_path"]))
        showoff = ShowoffService(cfg, store)
        showoff.enter(command="Elaria, show off", embedding=emb, owner_present=True)

        daemon = Daemon(cfg)
        daemon.showoff = showoff
        daemon.client = _SleepyClient()
        daemon._chat_timeout_s = 0.02
        try:
            out = asyncio.run(daemon._guest_turn(
                "what can you do", {"channel": "voice"}, showoff.status()))
            assert out["reply"] != "guest answer"
            assert "stall" in out["reply"].lower() or "slow" in out["reply"].lower()
        finally:
            daemon.store.close()
    finally:
        store.close()


# --------------------------------------------------------------------------
# BH-I13 — one malformed event line killed the Waybar/console event stream
# --------------------------------------------------------------------------


def test_waybar_stream_survives_malformed_event_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    from assistant import waybar

    path = tmp_path / "events.sock"
    # The stream asks for a snapshot first; stub it so only the event socket is
    # exercised here (`_safe_status` has its own daemon-down fallback).
    monkeypatch.setattr(waybar, "_safe_status", lambda _p: {"running": True})
    _fake_server(path, reply=b'not json\n{"event": "x"}\n', hold_open=True)

    stream = waybar.stream_waybar(path, interval_s=0.2)
    try:
        first = next(stream)
        assert first["text"].startswith("○") or first["text"].startswith("●")
        second = next(stream)
        assert "Elaria" in second["text"]
    finally:
        stream.close()
        path.unlink(missing_ok=True)
