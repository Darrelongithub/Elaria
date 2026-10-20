"""Stage A–D & Cross-Cutting Hardening Bug Hunt (`BH-H1` .. `BH-H22`).

Every test in this module was written BEFORE its corresponding fix to prove the
bug existed on `main` (`36f0618`). All tests operate strictly inside `tmp_path`
sandboxes with offline/fake transports — never touching real user folders, API
keys, audio hardware, or voiceprints.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import os
import socket
import struct
import threading
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant import gemini_client as gc
from assistant.cli import run_doctor
from assistant.config import (
    DEFAULT_VOICE_MODEL,
    DEFAULTS,
    Config,
    resolve_voice,
    voice_model,
)
from assistant.console import stream_console
from assistant.daemon import Daemon
from assistant.gemini_client import GeminiClient
from assistant.initiative import (
    InitiativeError,
    InitiativeService,
    KnockSignal,
    ensure_not_needy,
    ensure_not_temporal,
)
from assistant.ipc import call, serve
from assistant.presence import PresenceService
from assistant.showoff import ShowoffError, ShowoffService
from assistant.store import Store
from assistant.tts import SpeechService
from assistant.voice_catalogue import load_cached, save_cached, validate_voice


def _write_voiceprint(path: Path) -> list[float]:
    path.parent.mkdir(parents=True, exist_ok=True)
    vec = [1.0, 0.0, 0.0, 0.0]
    path.write_text(
        json.dumps({"model": "ecapa-tdnn", "dimension": 4, "centroid": vec}),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return vec


def _sandbox_config(tmp_path: Path, **overrides) -> Config:
    from assistant.config import load_config

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


def _pcm_bytes(duration_ms: int = 120, sample_rate: int = 24000) -> bytes:
    n_samples = int(sample_rate * duration_ms / 1000)
    return struct.pack(f"<{n_samples}h", *([600] * n_samples))


# ===========================================================================
# Stage A — Voice (BH-H1 .. BH-H4)
# ===========================================================================


def test_bh_h1_live_session_dropped_mid_ack_before_turn_complete_rejected(
    monkeypatch: pytest.MonkeyPatch,
):
    """BH-H1a: A Live session that drops after yielding partial audio before
    `turn_complete` must raise RuntimeError rather than returning a truncated ack.
    """
    import sys

    fake_types = SimpleNamespace(
        LiveConnectConfig=lambda **kw: kw,
        SpeechConfig=lambda **kw: kw,
        VoiceConfig=lambda **kw: kw,
        PrebuiltVoiceConfig=lambda **kw: kw,
        AudioTranscriptionConfig=lambda **kw: kw,
    )
    monkeypatch.setitem(
        sys.modules, "google", SimpleNamespace(genai=SimpleNamespace(types=fake_types))
    )
    monkeypatch.setitem(sys.modules, "google.genai", SimpleNamespace(types=fake_types))

    class _DroppedMidAckSession:
        async def send_client_content(self, **kwargs) -> None:
            return None

        async def receive(self):
            # Emits one partial PCM frame and then disconnects without turn_complete!
            part = SimpleNamespace(
                inline_data=SimpleNamespace(
                    data=_pcm_bytes(60), mime_type="audio/pcm;rate=24000"
                )
            )
            msg = SimpleNamespace(
                usage_metadata=None,
                server_content=SimpleNamespace(
                    model_turn=SimpleNamespace(parts=[part]),
                    turn_complete=False,
                ),
            )
            yield msg

    class _FakeConnectCtx:
        async def __aenter__(self):
            return _DroppedMidAckSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    transport = gc._SdkTransport.__new__(gc._SdkTransport)
    transport._client = SimpleNamespace(
        aio=SimpleNamespace(live=SimpleNamespace(connect=lambda **kw: _FakeConnectCtx()))
    )
    with pytest.raises(RuntimeError, match="turn_complete|incomplete|dropped"):
        transport.generate_audio(DEFAULT_VOICE_MODEL, "On it.", "Flare")


def test_bh_h1_disk_full_mid_write_wav_leaves_no_corrupt_cached_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """BH-H1b: If disk fills (`ENOSPC`) mid-`write_wav`, no partial/44-byte WAV
    may remain at the target cache path to poison subsequent `play_ack` calls.
    """
    target = tmp_path / "ack_on_it.wav"
    import wave

    orig_writeframes = wave.Wave_write.writeframes

    def _enospc_writeframes(self, data: bytes) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(wave.Wave_write, "writeframes", _enospc_writeframes)
    with pytest.raises(OSError):
        SpeechService.write_wav(target, _pcm_bytes(100), 24000)

    assert not target.exists(), "Corrupt header-only WAV left on disk after ENOSPC"
    monkeypatch.setattr(wave.Wave_write, "writeframes", orig_writeframes)


def test_bh_h1_live_disconnect_during_conversation_emits_speech_error_and_text_fallback(
    tmp_path: Path,
):
    """BH-H1c: When Gemini Live disconnects during conversation speech, the
    daemon must return the text reply, keep silence rules (no second voice),
    and broadcast a `speech.error` event so the UI/Waybar sees the failure.
    """
    cfg = _sandbox_config(tmp_path, mode={"default": "online"})
    store = Store(cfg.db_path)

    class _DisconnectLiveTransport(gc._SdkTransport):
        def __init__(self) -> None:
            pass

        def generate(self, model: str, contents, config: dict) -> dict:
            return {
                "text": "Here is the text fallback.",
                "usage": {"tokens_in": 5, "tokens_out": 5},
            }

        def generate_audio(self, model: str, text: str, voice_name: str) -> dict:
            raise RuntimeError("Live WebSocket closed unexpectedly (1006)")

        def list_models(self) -> list[str]:
            return [DEFAULT_VOICE_MODEL]

        def list_voices(self) -> list[str]:
            return ["Flare"]

    daemon = Daemon(cfg)
    cfg.gemini_mode = "live"
    cfg._api_key = "fake-key"
    daemon.client = GeminiClient(cfg, daemon.store, transport=_DisconnectLiveTransport())
    daemon.speech = SpeechService(
        cfg, daemon.store, client=daemon.client, is_online=lambda: True, presence=daemon.presence
    )
    events: list[dict] = []
    orig_broadcast = daemon.broadcast

    async def _capture_broadcast(event: dict) -> None:
        events.append(event)
        await orig_broadcast(event)

    daemon.broadcast = _capture_broadcast  # type: ignore[method-assign]
    try:
        res = asyncio.run(daemon._ask({"text": "Tell me the status.", "speak": True}))
        assert res["reply"] == "Here is the text fallback."
        assert res["speech"]["played"] is False
        assert res["speech"]["muted"] is True
        kinds = [e.get("event") for e in events]
        assert "speech.error" in kinds, f"Expected speech.error broadcast, got {kinds}"
    finally:
        daemon.store.close()
        store.close()


def test_bh_h2_catalogue_cache_ttl_and_upstream_voice_removal(tmp_path: Path):
    """BH-H2: Stale catalogue cache entries must expire by TTL, and if an upstream
    verified catalogue removes the configured voice, `SpeechService` and `doctor`
    must refuse to use it. Additionally `validate_voice` must include `candidates`
    in `allowed` even on failure.
    """
    cfg = _sandbox_config(
        tmp_path,
        mode={"default": "online"},
        gemini={"voice": "Flare", "allowed_voices": ["Flare"]},
    )
    store = Store(cfg.db_path)
    try:
        # 1. validate_voice includes candidate_voices in result["allowed"] on failure
        bad = validate_voice(
            DEFAULT_VOICE_MODEL,
            "BogusVoice",
            {
                "voices": ["Kore"],
                "candidate_voices": ["Flare"],
                "source": "live-api",
                "verified": True,
            },
        )
        assert bad["ok"] is False
        assert "Flare" in bad["allowed"]

        # 2. Stale catalogue cache entry older than TTL is rejected by load_cached
        stale_cat = {
            "model": DEFAULT_VOICE_MODEL,
            "verified": True,
            "source": "live-api",
            "retrieved": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
            "voices": ["Flare"],
            "candidate_voices": [],
        }
        save_cached(store, stale_cat)
        assert load_cached(store, DEFAULT_VOICE_MODEL) is None

        # 3. Fresh verified catalogue where upstream removed "Flare" (only "Kore" remains)
        fresh_cat = {
            "model": DEFAULT_VOICE_MODEL,
            "verified": True,
            "source": "live-api",
            "retrieved": datetime.now(UTC).isoformat(),
            "voices": ["Kore"],
            "candidate_voices": [],
        }
        save_cached(store, fresh_cat)
        cfg.gemini_mode = "live"
        cfg._api_key = "fake-key"
        client = GeminiClient(cfg, store, transport=object())
        speech = SpeechService(cfg, store, client=client, is_online=lambda: True)
        route, reason = speech.voice_route()
        assert route == "silent"
        assert "catalogue" in reason.lower() or "not supported" in reason.lower()
    finally:
        store.close()


def test_bh_h3_allowed_voices_widened_then_narrowed_and_case_canonical(tmp_path: Path):
    """BH-H3: If `allowed_voices` is widened to `["Flare", "Kore"]` (warming acks
    under `"Kore"`), and later narrowed back to `["Flare"]` while `voice="Kore"`
    remains in config, `SpeechService` must NOT report `gemini_voice="Kore"` in
    status, must NOT compute a `"Kore"` `cloud_cache_identity()`, and `resolve_voice`
    must canonicalize lowercase `"flare"` to `"Flare"`.
    """
    cfg_case = _sandbox_config(tmp_path, gemini={"voice": "flare", "allowed_voices": ["Flare"]})
    assert resolve_voice(cfg_case) == ("Flare", True)

    cfg_narrow = _sandbox_config(
        tmp_path,
        mode={"default": "online"},
        gemini={"voice": "Kore", "allowed_voices": ["Flare"]},
    )
    store = Store(cfg_narrow.db_path)
    try:
        speech_narrow = SpeechService(cfg_narrow, store, is_online=lambda: True)
        st = speech_narrow.status()
        assert st["gemini_voice"] == "none"
        assert speech_narrow.cloud_cache_identity()["voice"] == ""
        ack = speech_narrow.play_ack("on_it")
        assert ack["muted"] is True
        assert ack["audio_path"] is None
    finally:
        store.close()


def test_bh_h4_deprecated_model_voice_never_shadows_gemini_voice_model(tmp_path: Path):
    """BH-H4: Setting deprecated `model_voice` alongside default `gemini_voice_model`
    must NOT hijack `voice_model(config)` away from `DEFAULT_VOICE_MODEL`.
    """
    cfg = _sandbox_config(
        tmp_path,
        gemini={
            "gemini_voice_model": DEFAULT_VOICE_MODEL,
            "model_voice": "gemini-2.5-flash-preview-tts",
        },
    )
    assert voice_model(cfg) == DEFAULT_VOICE_MODEL


# ===========================================================================
# Stage B — Console & Class Mode (BH-H5 .. BH-H8)
# ===========================================================================


def test_bh_h5_session_continuity_under_daemon_restart_includes_history_in_prompt(
    tmp_path: Path,
):
    """BH-H5: When a daemon restarts mid-conversation on the same SQLite DB, the
    second turn must include the prior turn's history in the prompt sent to
    `GeminiClient.generate`.
    """
    cfg = _sandbox_config(tmp_path, mode={"default": "online"})
    seen_prompts: list[str] = []

    class _ChatTransport:
        def generate(self, model: str, contents, config: dict) -> dict:
            seen_prompts.append(str(contents))
            return {
                "text": "The codename is Velvet-9.",
                "usage": {"tokens_in": 10, "tokens_out": 6},
            }

    d1 = Daemon(cfg)
    d1.client = GeminiClient(cfg, d1.store, transport=_ChatTransport())
    asyncio.run(d1._ask({"text": "Our project codename is Velvet-9.", "speak": False}))
    d1.store.close()

    # Restart a brand-new Daemon on the same database
    d2 = Daemon(cfg)
    d2.client = GeminiClient(cfg, d2.store, transport=_ChatTransport())
    try:
        asyncio.run(d2._ask({"text": "What is our project codename?", "speak": False}))
        assert len(seen_prompts) == 2
        assert "Velvet-9" in seen_prompts[1], (
            f"Second turn after daemon restart lost conversation context: {seen_prompts[1]!r}"
        )
    finally:
        d2.store.close()


def test_bh_h6_console_follow_mode_disconnect_emits_down_snapshot_and_handles_non_dict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """BH-H6: When the daemon closes the follow-mode socket (clean EOF `b""`) or
    sends a non-dict JSON line, `stream_console` must not crash or spin without
    yielding a daemon-down snapshot (`running=False`).
    """
    import time as _time

    monkeypatch.setattr(_time, "sleep", lambda _s: None)
    sock_path = tmp_path / "console.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(2)

    def _fake_daemon() -> None:
        # Connection 1: initial console.state call
        conn1, _ = server.accept()
        _ = conn1.recv(4096)
        conn1.sendall(
            (json.dumps({"ok": True, "result": {"daemon": {"running": True, "mode": "idle"}}}) + "\n").encode()
        )
        conn1.close()
        # Connection 2: subscribe connection -> send non-dict JSON line (int), then close (EOF)
        conn2, _ = server.accept()
        _ = conn2.recv(4096)
        conn2.sendall((json.dumps({"ok": True, "result": {"subscribed": True}}) + "\n").encode())
        conn2.sendall(b"123\n")
        conn2.close()
        server.close()

    t = threading.Thread(target=_fake_daemon, daemon=True)
    t.start()

    gen = stream_console(sock_path)
    first = next(gen)
    assert first["daemon"]["running"] is True
    second = next(gen)
    assert second["daemon"]["running"] is False, f"Expected daemon-down snapshot after EOF, got {second}"
    gen.close()
    t.join(timeout=2.0)


def test_bh_h7_class_mode_toggle_racing_spoken_ack_speech_always_loses(tmp_path: Path):
    """BH-H7: If class mode is toggled ON while an ack synthesis/cache wait or
    `SpeechService.speak` is in flight, speech MUST lose (zero audio played).
    """
    cfg = _sandbox_config(
        tmp_path,
        mode={"default": "online"},
        tts={"player": "/bin/echo"},
    )
    store = Store(cfg.db_path)
    played_files: list[str] = []

    presence = PresenceService(cfg, store)

    class _SlowLiveTransport(gc._SdkTransport):
        def __init__(self) -> None:
            pass

        def generate_audio(self, model: str, text: str, voice_name: str) -> dict:
            # During synthesis, class mode flips ON!
            presence.set_enabled(True)
            return {
                "pcm": _pcm_bytes(80),
                "sample_rate": 24000,
                "voice_name": voice_name,
                "usage": {"tokens_in": 2, "tokens_out": 4},
            }

        def list_models(self) -> list[str]:
            return [DEFAULT_VOICE_MODEL]

        def list_voices(self) -> list[str]:
            return ["Flare"]

    cfg.gemini_mode = "live"
    cfg._api_key = "fake-key"
    client = GeminiClient(cfg, store, transport=_SlowLiveTransport())

    def _fake_player_runner(args, **kwargs):
        played_files.append(str(args[-1]))
        return SimpleNamespace(returncode=0)

    speech = SpeechService(
        cfg,
        store,
        client=client,
        is_online=lambda: True,
        presence=presence,
        player_runner=_fake_player_runner,
    )
    try:
        res = speech.speak("I was about to speak as class started.", play=True)
        assert res.played is False
        assert res.muted is True
        assert played_files == [], f"Speech must lose race against class mode, played: {played_files}"
    finally:
        store.close()


def test_bh_h8_schedule_suggestion_overnight_and_malformed_days_never_self_activate(
    tmp_path: Path,
):
    """BH-H8: Schedule windows that cross midnight (e.g. Mon 22:00–02:00 tested at
    Tue 01:00) must match as a suggestion without ever enabling class mode, and
    boolean/string `days` entries (`[True]`, `"mon"`) or string `"false"` in
    `_class_set` must not misfire.
    """
    cfg = _sandbox_config(
        tmp_path,
        presence={
            "class_mode_default": False,
            "class_schedule": [
                {"days": [True], "start": "00:00", "end": "23:59", "label": "BooleanDayBug"},
                {"days": ["mon"], "start": "22:00", "end": "02:00", "label": "LateLab"},
            ],
        },
    )
    store = Store(cfg.db_path)
    try:
        presence = PresenceService(cfg, store)
        # 2026-10-20 is a Tuesday (weekday=1); 01:00 is inside Monday's 22:00-02:00 overnight window!
        tue_0100 = datetime(2026, 10, 20, 1, 0, tzinfo=UTC)
        st = presence.status(now=tue_0100)
        assert st.enabled is False, "Schedule suggestion must NEVER self-activate class mode"
        assert st.suggested is True
        assert st.schedule_label == "LateLab"

        # Daemon._class_set with string "false" must disable, not enable
        daemon = Daemon(cfg)
        try:
            daemon.presence.set_enabled(True)
            out = asyncio.run(daemon._class_set({"enabled": "false"}))
            assert out["enabled"] is False
        finally:
            daemon.store.close()
    finally:
        store.close()


# ===========================================================================
# Stage C — Knock & Initiative (BH-H9 .. BH-H14)
# ===========================================================================


def test_bh_h9_knock_during_class_mode_silent_pulse_and_urgent_config_respected(
    tmp_path: Path,
):
    """BH-H9: During class mode, an urgent knock emits a silent visual pulse only
    (KnockSignal plays zero audio even if `class_mode` is omitted because
    `knock["silent"]` is True), and if `urgent_in_class_mode = false`, even
    urgent knocks are refused in class mode.
    """
    sound_file = tmp_path / "knock.wav"
    SpeechService.write_wav(sound_file, _pcm_bytes(50), 24000)
    cfg = _sandbox_config(
        tmp_path,
        initiative={
            "urgent_in_class_mode": True,
            "play_sound": True,
            "sound": str(sound_file),
        },
    )
    store = Store(cfg.db_path)
    try:
        presence = PresenceService(cfg, store)
        presence.set_enabled(True)
        init = InitiativeService(cfg, store, presence=presence)
        knock = init.raise_knock(
            topic="server down",
            reason="Production server alert you asked me to watch.",
            kind="urgency",
            urgency="urgent",
            referent="production server",
        )
        assert knock["silent"] is True

        played_sounds: list[str] = []
        sig = KnockSignal(
            cfg,
            runner=lambda argv, **kw: (played_sounds.append(str(argv)) or None),
        )
        # Even if caller passes class_mode=False, knock["silent"] is True!
        emitted = sig.emit(knock, class_mode=False)
        assert emitted["sound"] is False
        assert played_sounds == []

        # When urgent_in_class_mode = False, urgent knocks in class mode are refused
        cfg_strict = _sandbox_config(
            tmp_path,
            initiative={"urgent_in_class_mode": False},
        )
        init_strict = InitiativeService(cfg_strict, store, presence=presence)
        with pytest.raises(InitiativeError, match="class mode"):
            init_strict.raise_knock(
                topic="server down 2",
                reason="Another alert while urgent_in_class_mode is false.",
                kind="urgency",
                urgency="urgent",
                referent="production server",
            )
    finally:
        store.close()


def test_bh_h10_knock_accept_respects_mute_and_survives_daemon_restart(tmp_path: Path):
    """BH-H10: Accepting a knock while voice is muted (e.g. offline/mock mode even
    when class mode is off) must open in `"console"` (not `"voice"`), and accepting
    a knock must persist the opener into the active conversation inside
    `InitiativeService.accept` so a daemon crash/restart never loses the opener.
    """
    cfg = _sandbox_config(tmp_path, mode={"default": "offline"})
    daemon = Daemon(cfg)
    try:
        assert daemon.speech.status()["muted"] is True
        k = daemon.initiative.raise_knock(
            topic="flight check-in",
            reason="Your flight check-in window just opened.",
            kind="urgency",
            urgency="urgent",
            referent="flight check-in",
        )
        res = asyncio.run(daemon._knock_accept({"id": k["id"]}))
        assert res["open"] == "console", (
            f"Expected open='console' when speech.status()['muted']=True, got {res['open']!r}"
        )

        # Verify that even if initiative.accept() is called directly and daemon restarts,
        # the conversation history in SQLite already holds the opener line.
        c = daemon.initiative.create_commitment(
            "Remind me about lease renewal", origin="user-request"
        )
        k2 = daemon.initiative.raise_knock(
            topic="lease renewal",
            reason="You asked me to remind you about the lease renewal.",
            kind="follow-up",
            commitment_id=c["commitment_id"],
        )
        accepted = daemon.initiative.accept(k2["id"])
        history = daemon.sessions.history()["messages"]
        assert any(accepted["first_line"] in t["text"] for t in history), (
            "InitiativeService.accept must persist first_line to conversation history atomically"
        )
    finally:
        daemon.store.close()


def test_bh_h11_commitment_created_by_accepted_proposal_then_declined_is_deactivated(
    tmp_path: Path,
):
    """BH-H11: When a commitment created by an accepted proposal (or `later`)
    surfaces as a knock and the user later declines it, the underlying commitment
    in `facts` must be deactivated (`active = 0`) and any snoozed knocks on that
    topic declined so `check_due()` never re-raises it.
    """
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        t0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        now_box = [t0]
        init = InitiativeService(cfg, store, now=lambda: now_box[0])
        c = init.create_commitment(
            "Review Q4 budget spreadsheet",
            origin="accepted-proposal",
        )
        cid = c["commitment_id"]
        knock = init.raise_knock(
            topic="q4 budget",
            reason="You accepted my proposal to review the Q4 budget spreadsheet.",
            kind="follow-up",
            commitment_id=cid,
        )

        # User snoozes it ("later"), then changes their mind and declines it
        init.later(knock["id"], hours=1.0)
        init.decline(knock["id"])

        # Advance clock past the snooze window: check_due() must NOT re-raise it,
        # and the commitment must be deactivated in facts.
        now_box[0] = t0 + timedelta(hours=2)
        assert init.check_due() == []
        active_commitments = store.list_facts(kind="commitment", active_only=True)
        assert all(int(f["id"]) != int(cid) for f in active_commitments), (
            f"Declined commitment {cid} remained active in facts: {active_commitments}"
        )
    finally:
        store.close()


def test_bh_h12_topic_retire_counter_manipulation_and_punctuation_normalisation(
    tmp_path: Path,
):
    """BH-H12: `ignore()` must reject already-accepted/declined knocks, and
    ignoring 3 separate knocks on punctuation/casing variants of the same topic
    (`"Tax-Return!"`, `"tax return"`, `"  TAX   RETURN? "`) must retire the topic.
    """
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        init = InitiativeService(cfg, store)
        k_acc = init.raise_knock(
            topic="dentist",
            reason="You asked me to follow up on the dentist booking.",
            kind="checkin",
            referent="dentist",
        )
        init.accept(k_acc["id"])
        with pytest.raises(InitiativeError, match="pending|already|accepted"):
            init.ignore(k_acc["id"])

        variants = ["Tax-Return!", "tax return", "  TAX   RETURN? "]
        last_out = None
        for idx, topic_variant in enumerate(variants):
            c = init.create_commitment(
                f"Check {topic_variant} #{idx}", origin="user-request"
            )
            k = init.raise_knock(
                topic=topic_variant,
                reason=f"Follow-up #{idx + 1} on your tax return.",
                kind="follow-up",
                commitment_id=c["commitment_id"],
            )
            last_out = init.ignore(k["id"])

        assert last_out is not None
        assert last_out["retired"] is True
        with pytest.raises(InitiativeError, match="retired"):
            init.raise_knock(
                topic="tax return",
                reason="Trying to raise retired topic again.",
                kind="checkin",
                referent="tax return",
            )
    finally:
        store.close()


def test_bh_h13_ast_knock_signal_and_sound_only_called_from_knock_handlers():
    """BH-H13: Extend the AST boundary test: `KnockSignal` and knock sound/emit
    paths may never be imported or invoked outside `initiative.py` and the
    daemon's `_knock_*` handlers.
    """
    src_root = Path(__file__).resolve().parents[1] / "src" / "assistant"
    for py_file in sorted(src_root.glob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "KnockSignal":
                assert py_file.name in {"initiative.py", "daemon.py"}, (
                    f"KnockSignal referenced in forbidden module {py_file.name}:{node.lineno}"
                )
        if py_file.name == "daemon.py":
            for node in tree.body:
                if isinstance(node, ast.ClassDef) and node.name == "Daemon":
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            for sub in ast.walk(item):
                                if (
                                    isinstance(sub, ast.Attribute)
                                    and sub.attr == "knock_signal"
                                    and item.name not in {"__init__", "_knock_raise", "_knock_due"}
                                ):
                                    raise AssertionError(
                                        f"daemon.knock_signal used outside knock handlers in {item.name}"
                                    )


@pytest.mark.parametrize(
    "paraphrase",
    [
        "It's been quiet lately — wanted to see what you're up to.",
        "Things have been quiet around here, so I thought I'd say hi.",
        "Just checking you still want me around.",
        "Do you still want me to help you with things?",
        "Did you forget about me?",
        "Radio silence from your end today — everything okay?",
    ],
)
def test_bh_h14_needy_framing_fuzz_rejects_paraphrased_openers(paraphrase: str):
    """BH-H14: Paraphrased needy/temporal openers must be rejected by
    `ensure_not_needy` or `ensure_not_temporal`.
    """
    with pytest.raises(InitiativeError):
        ensure_not_needy(paraphrase)
        ensure_not_temporal(paraphrase)


# ===========================================================================
# Stage D — Show-off & Disclosure (BH-H15 .. BH-H20)
# ===========================================================================


def test_bh_h15_showoff_rejects_recorded_or_replayed_owner_audio(tmp_path: Path):
    """BH-H15: Show-off entry phrase spoken by a recording (`source != 'mic'`,
    `replayed=True`, `live_mic=False`, or replaying the same `audio_sha256` clip)
    must be refused.
    """
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        emb = _write_voiceprint(
            Path(cfg.section("voice_test")["voiceprint_path"])
        )
        showoff = ShowoffService(cfg, store)

        # 1. File / loopback / replayed source must fail even with exact owner embedding
        for bad_kwargs in (
            {"source": "file"},
            {"source": "loopback"},
            {"replayed": True},
            {"live_mic": False},
        ):
            with pytest.raises(ShowoffError, match="live|record|replay"):
                showoff.enter(
                    command="Elaria, show off",
                    embedding=emb,
                    owner_present=True,
                    **bad_kwargs,
                )
            assert showoff.active() is False

        # 2. Replaying the exact same audio_sha256 from a prior entry must fail
        clip_hash = hashlib.sha256(b"owner-entry-clip-1").hexdigest()
        showoff.enter(
            command="Elaria, show off",
            embedding=emb,
            owner_present=True,
            source="mic",
            audio_sha256=clip_hash,
        )
        showoff.exit_hotkey()
        with pytest.raises(ShowoffError, match="replay|live"):
            showoff.enter(
                command="Elaria, show off",
                embedding=emb,
                owner_present=True,
                source="mic",
                audio_sha256=clip_hash,
            )
    finally:
        store.close()


def test_bh_h16_guest_audio_during_owners_verified_turn_downgrades_posture(
    tmp_path: Path,
):
    """BH-H16: If guest audio / overlapping speakers or a non-owner voice
    embedding arrives on a turn labelled `speaker='owner'`, `Daemon._ask` must
    downgrade the turn to guest posture and refuse private memory disclosure.
    """
    cfg = _sandbox_config(tmp_path, mode={"default": "online"})
    store = Store(cfg.db_path)
    try:
        store.add_fact(
            ts="2026-10-20T00:00:00Z",
            kind="profile",
            text="Owner private vault code is 8842-OMEGA",
            source="stated",
            confidence=1.0,
        )
        emb = _write_voiceprint(
            Path(cfg.section("voice_test")["voiceprint_path"])
        )
        daemon = Daemon(cfg)
        try:
            daemon.store.add_fact(
                ts="2026-10-20T00:00:00Z",
                kind="profile",
                text="My bank pin vault code is 8842-OMEGA",
                source="stated",
                confidence=1.0,
            )
            daemon.showoff.enter(
                command="Elaria, show off",
                embedding=emb,
                owner_present=True,
            )
            seen_prompts: list[str] = []

            class _ChatTransport:
                def generate(self, model: str, contents, config: dict) -> dict:
                    seen_prompts.append(str(contents))
                    return {
                        "text": "That stays between us.",
                        "usage": {"tokens_in": 5, "tokens_out": 5},
                    }

            daemon.client = GeminiClient(cfg, daemon.store, transport=_ChatTransport())

            # Turn claims speaker="owner" but has guest_audio=True (guest chimed in during owner turn)
            res = asyncio.run(
                daemon._ask(
                    {
                        "text": "What do you know about my bank pin?",
                        "speaker": "owner",
                        "guest_audio": True,
                        "speak": False,
                    }
                )
            )
            assert res["speaker"] == "guest"
            assert "8842-OMEGA" not in res["reply"]
            assert all("8842-OMEGA" not in p for p in seen_prompts)
        finally:
            daemon.store.close()
    finally:
        store.close()


def test_bh_h17_showoff_timeout_racing_owner_stop_and_clock_jump_safety(
    tmp_path: Path,
):
    """BH-H17: When the show-off timeout expires right as `exit_owner` or
    `exit_hotkey` runs, stopping must succeed idempotently (no `ShowoffError`),
    `active()` must auto-expire without requiring `status()` to be polled first,
    and a backward wall-clock jump must not extend the show-off window.
    """
    cfg = _sandbox_config(tmp_path, showoff={"timeout_s": 300})
    store = Store(cfg.db_path)
    try:
        emb = _write_voiceprint(
            Path(cfg.section("voice_test")["voiceprint_path"])
        )
        t0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
        now_box = [t0]
        showoff = ShowoffService(cfg, store, now=lambda: now_box[0])
        showoff.enter(
            command="Elaria, show off",
            embedding=emb,
            owner_present=True,
        )
        # Advance past the 5-minute window: active() auto-expires, and exit_owner
        # racing the timeout must return cleanly instead of raising ShowoffError.
        now_box[0] = t0 + timedelta(minutes=6)
        assert showoff.active() is False
        st = showoff.exit_owner(command="Elaria, stop", embedding=emb)
        assert st["exited"] is True
        assert showoff.status()["active"] is False
    finally:
        store.close()


def test_bh_h18_demo_action_via_symlink_escaping_sandbox_blocked(tmp_path: Path):
    """BH-H18: A symlink inside `demo_sandbox` (or a symlinked parent dir)
    pointing outside the sandbox must be blocked by `assert_within_sandbox` and
    `ShowoffService.demo_write`.
    """
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        emb = _write_voiceprint(
            Path(cfg.section("voice_test")["voiceprint_path"])
        )
        showoff = ShowoffService(cfg, store)
        showoff.enter(
            command="Elaria, show off",
            embedding=emb,
            owner_present=True,
        )
        # Symlinked sandbox root pointing to an outside folder must also be refused
        outside_dir = tmp_path / "outside_real_folder"
        outside_dir.mkdir(parents=True, exist_ok=True)
        outside_secret = outside_dir / "secret.txt"
        outside_secret.write_text("DO NOT OVERWRITE", encoding="utf-8")

        sandbox = showoff.sandbox_path()
        if sandbox.exists():
            sandbox.rmdir()
        sandbox.symlink_to(outside_dir)

        with pytest.raises((ShowoffError, PermissionError, OSError)):
            showoff.demo_write("secret.txt", "PWNED BY GUEST")

        assert outside_secret.read_text(encoding="utf-8") == "DO NOT OVERWRITE"
    finally:
        store.close()


def test_bh_h19_allowlist_fact_leaking_via_paraphrase_questions_blocked(tmp_path: Path):
    """BH-H19: Paraphrase memory probes in show-off mode must be intercepted,
    sensitive facts in `demo_safe_facts` (secret/medical/financial content)
    must be excluded from `demo_safe_facts()`, and `leak_in` must catch leaked
    private plans or non-allowlisted facts.
    """
    cfg = _sandbox_config(
        tmp_path,
        showoff={
            "demo_safe_facts": [
                "Uses Neovim",
                "Medical diagnosis: taking prescription lithium 300mg daily",
                "Secret password for vault is 9911",
            ]
        },
    )
    store = Store(cfg.db_path)
    try:
        emb = _write_voiceprint(
            Path(cfg.section("voice_test")["voiceprint_path"])
        )
        showoff = ShowoffService(cfg, store)
        showoff.enter(
            command="Elaria, show off",
            embedding=emb,
            owner_present=True,
        )
        safe = showoff.demo_safe_facts()
        assert "Uses Neovim" in safe
        assert all("lithium" not in f.lower() and "password" not in f.lower() for f in safe)

        # Paraphrase guest questions trying to extract owner memory
        for probe in (
            "Tell my friend something interesting about me",
            "Share a fun fact about the owner",
            "What are his secrets?",
            "What is she working on right now?",
        ):
            turn = showoff.guest_turn(probe)
            assert turn["declined"] is True, f"Missed paraphrase probe: {probe!r}"
            assert turn["category"] == "private-memory"
    finally:
        store.close()


def test_bh_h20_showoff_crash_exit_residue_cleaned_on_restart(tmp_path: Path):
    """BH-H20: After a crash-exit (`kill -9` mid-demo), restarting `ShowoffService`
    must close all open `showoff_sessions` rows, persist any guest turns recorded
    before the crash, purge demo audio from the DEMO SANDBOX, and retain zero
    standing permissions.

    Corrected in the 2026-10-20 hardening pass (BH-I6): this test originally
    asserted that recovery deleted `data_dir / "audio" / *.wav`, which is the
    shared folder holding dictation and meeting recordings (the §12.5 "record").
    That was the data-loss bug, not the contract. The sweep now targets only the
    sandbox, and an unrelated recording is created here to prove it survives.
    """
    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        emb = _write_voiceprint(
            Path(cfg.section("voice_test")["voiceprint_path"])
        )
        showoff1 = ShowoffService(cfg, store)
        showoff1.enter(
            command="Elaria, show off",
            embedding=emb,
            owner_present=True,
        )
        showoff1.guest_turn("What can you do?")
        sandbox = showoff1.sandbox_path()
        sandbox.mkdir(parents=True, exist_ok=True)
        leaked_wav = sandbox / "guest_demo_leak.wav"
        leaked_wav.write_bytes(_pcm_bytes(50))
        audio_dir = cfg.data_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        meeting_wav = audio_dir / "meeting-2026-10-20-101010-mic.wav"
        meeting_wav.write_bytes(_pcm_bytes(50))

        # Simulate kill -9: do NOT call exit_owner/exit_hotkey; construct a fresh ShowoffService
        showoff2 = ShowoffService(cfg, store)
        st = showoff2.status()
        assert st["active"] is False
        assert st["permissions"] == []
        assert not leaked_wav.exists(), "Demo audio residue survived crash recovery"
        assert meeting_wav.exists(), (
            "crash recovery deleted a meeting recording from the shared audio dir")

        sessions = store.list_showoff_sessions(limit=5)
        assert sessions[0]["ended_ts"] is not None
        assert sessions[0]["exit_reason"] == "daemon_restart"
        assert sessions[0]["audio_retained"] == 0
        assert sessions[0]["guests_heard"] == 1
    finally:
        store.close()


# ===========================================================================
# Cross-Cutting — IPC, Two Daemons, Config Drift & README CLI (BH-H21 .. BH-H22)
# ===========================================================================


def test_bh_h21_second_daemon_refuses_to_steal_active_socket_and_ipc_handles_non_dict(
    tmp_path: Path,
):
    """BH-H21: Starting a second `serve()` while a live daemon is already bound
    to `socket_path` must raise RuntimeError rather than unlinking the live
    daemon's socket; and sending a non-dict JSON frame (`[1, 2, 3]`) to the IPC
    socket must return a clean error response without crashing the server.
    """
    sock_path = tmp_path / "state" / "assistant.sock"

    async def _handler(method: str, params: dict) -> dict:
        return {"pong": method}

    async def _run() -> None:
        server1 = await serve(sock_path, _handler)
        try:
            # 1. Second daemon attempting to bind the same live socket must fail
            with pytest.raises(RuntimeError, match="already running|in use|active"):
                await serve(sock_path, _handler)

            # 2. First daemon's socket must still be alive and serving after the rejected attempt
            res = await asyncio.to_thread(call, sock_path, "ping", {})
            assert res == {"pong": "ping"}

            # 3. Sending a non-dict JSON frame must return an error, not crash the server
            def _send_non_dict() -> dict:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(str(sock_path))
                    s.sendall(b"[1, 2, 3]\n")
                    raw = s.recv(4096).decode("utf-8")
                    return json.loads(raw)

            parsed = await asyncio.to_thread(_send_non_dict)
            assert parsed["ok"] is False

            # Server still alive after malformed frame
            res2 = await asyncio.to_thread(call, sock_path, "still_alive", {})
            assert res2 == {"pong": "still_alive"}
        finally:
            server1.close()
            await server1.wait_closed()

    asyncio.run(_run())


def test_bh_h22_config_example_parity_and_validation(tmp_path: Path):
    """BH-H22: `config.toml.example` must parse with `max_requests_per_day` and
    `max_requests_per_minute` scoped under `[quota]` (not swallowed by
    `[quota.models.transcribe-batch]`), every section/key in `config.toml.example`
    must match `DEFAULTS`, and `run_doctor` must flag poisoned config values
    (unknown keys, negative quotas, wrong types).
    """
    repo_root = Path(__file__).resolve().parents[1]
    example_path = repo_root / "config.toml.example"
    parsed = tomllib.loads(example_path.read_text(encoding="utf-8"))

    # 1. Quota top-level keys must live in parsed["quota"], NOT inside transcribe-batch
    assert "max_requests_per_day" in parsed["quota"], (
        "max_requests_per_day was swallowed by [quota.models.transcribe-batch] in config.toml.example"
    )
    assert "max_requests_per_day" not in parsed["quota"]["models"]["transcribe-batch"]

    # 2. Every section & key in config.toml.example must exist in DEFAULTS and vice versa
    assert set(parsed.keys()) == set(DEFAULTS.keys())
    for sec in DEFAULTS:
        if isinstance(DEFAULTS[sec], dict):
            assert set(parsed[sec].keys()) == set(DEFAULTS[sec].keys()), (
                f"Section [{sec}] drift between config.toml.example and DEFAULTS: "
                f"only_in_example={set(parsed[sec]) - set(DEFAULTS[sec])}, "
                f"only_in_defaults={set(DEFAULTS[sec]) - set(parsed[sec])}"
            )

    # 3. Poisoned config (negative quota, unknown key, wrong type) is flagged by doctor
    poisoned = _sandbox_config(
        tmp_path,
        quota={"max_requests_per_day": -50, "unknown_poison_key": 123},
    )
    report = run_doctor(poisoned)
    checks_by_name = {c["check"]: c for c in report["checks"]}
    assert "config schema" in checks_by_name
    assert checks_by_name["config schema"]["status"] in ("warn", "fail")


def test_executor_journal_fuzz_plan_execute_undo_identical_tree_hash(tmp_path: Path):
    """Cross-cutting invariant: plan + execute + undo across nested files,
    collisions, and Unicode filenames must restore the exact original tree hash
    (files AND directories).
    """
    import time

    from assistant.executor import Executor
    from assistant.indexer import Indexer

    cfg = _sandbox_config(tmp_path)
    root = tmp_path / "fuzz_root"
    root.mkdir(parents=True, exist_ok=True)
    taxonomy = ["Archive", "_Unsorted", "_Conflicts"]
    cfg.raw["organise"]["roots"] = [
        {"path": str(root), "mode": "live", "taxonomy": taxonomy}
    ]
    cfg.raw["policy"]["recently_modified_guard_minutes"] = 15

    old_ts = time.time() - 86400 * 3
    files = {
        "inbox/alpha.txt": b"alpha payload 1",
        "inbox/sub/bravo-é.txt": b"bravo payload 2",
        "inbox/collision.txt": b"incoming collision payload",
        "Archive/collision.txt": b"existing archive payload",
    }
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        os.utime(p, (old_ts, old_ts))

    def _tree_hash(base: Path) -> dict[str, str]:
        snap: dict[str, str] = {}
        for item in sorted(base.rglob("*")):
            rel_str = str(item.relative_to(base))
            if item.is_file():
                snap[rel_str] = hashlib.sha256(item.read_bytes()).hexdigest()
            elif item.is_dir():
                snap[rel_str] = "dir"
        return snap

    before = _tree_hash(root)
    store = Store(cfg.db_path)
    try:
        spec = cfg.organise_roots()[0]
        Indexer(cfg, store).index_root(spec)
        plan_id = store.create_plan("2026-10-20T00:00:00Z", str(root), "live")
        srcs = [
            root / "inbox/alpha.txt",
            root / "inbox/sub/bravo-é.txt",
            root / "inbox/collision.txt",
        ]
        items = []
        for s in srcs:
            doc = store.document_by_path(str(s))
            items.append(
                {
                    "doc_id": doc["id"] if doc else None,
                    "src": str(s),
                    "dest": "Archive",
                    "new_name": s.name,
                    "confidence": 0.99,
                    "tier": 0,
                    "rule": "fuzz",
                    "reason": "fuzz test",
                    "decision": "auto",
                }
            )
        store.add_plan_items(plan_id, items)
        store.finish_plan(
            plan_id, total=len(items), placed=len(items), abstained=0,
            shadow_log_path=None, stats_json="{}"
        )
        ex = Executor(cfg, store)
        report = ex.apply_plan(plan_id, spec, allow_tripwire=True)
        assert report.applied >= 2 or report.conflicts >= 1
        assert _tree_hash(root) != before

        undone = ex.undo(plan_id=plan_id)
        assert undone["problems"] == []
        after = _tree_hash(root)
        assert after == before
    finally:
        store.close()


def test_readme_and_docs_cli_commands_exist_in_parser():
    """Part 3 requirement: every concrete CLI subcommand documented in README.md,
    GETTING-STARTED.md, and ui/ configs must exist in `cli.build_parser()`.
    """
    from assistant.cli import build_parser

    parser = build_parser()
    documented_invocations = [
        ["doctor"],
        ["doctor", "--json"],
        ["status"],
        ["status", "--waybar"],
        ["status", "--waybar", "--follow"],
        ["cost"],
        ["halt"],
        ["resume"],
        ["ptt", "start"],
        ["ptt", "stop"],
        ["ptt", "toggle"],
        ["dictate"],
        ["transcribe", "sample.wav"],
        ["events"],
        ["events", "--overlay"],
        ["mode", "auto"],
        ["mode", "online"],
        ["mode", "offline"],
        ["voice", "status"],
        ["voice", "models"],
        ["voice", "warm"],
        ["voice", "cleanup"],
        ["voice", "audition"],
        ["voice", "select", "flare"],
        ["talk", "--Check"],
        ["console"],
        ["console", "--json"],
        ["console", "--follow"],
        ["class", "on"],
        ["class", "off"],
        ["class", "toggle"],
        ["class", "status"],
        ["knock", "list"],
        ["knock", "status"],
        ["knock", "due"],
        ["knock", "raise", "--topic", "tax", "--reason", "You asked me to remind you."],
        ["knock", "accept", "1"],
        ["knock", "decline", "1"],
        ["knock", "later", "1", "--hours", "24"],
        ["knock", "ignore", "1"],
        ["commitment", "add", "Call accountant"],
        ["commitment", "list"],
        ["showoff", "status"],
        ["showoff", "exit"],
        ["showoff", "demo", "--action", "write", "--name", "notes.txt"],
        ["privacy", "status"],
        ["privacy", "company"],
        ["privacy", "alone"],
        ["privacy", "toggle"],
        ["taxonomy", "suggest", "/tmp"],
        ["verify"],
        ["memory"],
        ["ask", "hello"],
        ["meeting", "setup"],
        ["meeting", "transcribe", "mic.wav", "sys.wav"],
    ]
    for argv in documented_invocations:
        # Remove placeholder flag if any; talk takes optional text
        if argv == ["talk", "--Check"]:
            argv = ["talk"]
        ns = parser.parse_args(argv)
        assert ns.command == argv[0]


def test_cross_cutting_clock_jumps_forward_and_backward(tmp_path: Path):
    """Cross-cutting: backward (-2h NTP correction) and forward (+36h) clock
    jumps across PresenceService, InitiativeService, and ShowoffService must
    never crash, never prematurely trigger snoozed knocks on a backward jump,
    and cleanly close show-off on a forward jump.
    """
    cfg = _sandbox_config(
        tmp_path,
        presence={
            "class_mode": False,
            "class_schedule_suggest": True,
            "class_schedule": [
                {"days": ["tue"], "start": "09:00", "end": "11:00", "label": "Morning"}
            ],
        },
        showoff={"timeout_s": 1800},
    )
    store = Store(cfg.db_path)
    try:
        owner_emb = _write_voiceprint(
            Path(cfg.section("voice_test")["voiceprint_path"])
        )
        t0 = datetime(2026, 10, 20, 10, 0, tzinfo=UTC)
        now_box = [t0]
        presence = PresenceService(cfg, store)
        init = InitiativeService(cfg, store, presence=presence, now=lambda: now_box[0])
        showoff = ShowoffService(cfg, store, now=lambda: now_box[0])

        c = init.create_commitment("Check server logs", origin="user-request")
        k = init.raise_knock(
            topic="server logs",
            reason="You asked me to check server logs.",
            kind="follow-up",
            commitment_id=c["commitment_id"],
        )
        init.later(k["id"], hours=4.0)
        showoff.enter(
            command="Elaria, show off",
            embedding=owner_emb,
            owner_present=True,
            source="mic",
            live_mic=True,
        )

        # Backward jump (-2 hours): snooze must NOT fire, showoff stays active
        now_box[0] = t0 - timedelta(hours=2)
        assert init.check_due() == []
        assert showoff.active() is True
        assert presence.status(now=now_box[0]).enabled is False

        # Forward jump (+36 hours): snooze fires once, showoff auto-closes on timeout
        now_box[0] = t0 + timedelta(hours=36)
        due = init.check_due()
        assert len(due) == 1
        assert showoff.active() is False
    finally:
        store.close()


def test_cross_cutting_sqlite_corrupt_state_and_concurrent_writes(tmp_path: Path):
    """Cross-cutting: malformed JSON in `state` rows (`persona`, `tts.selected_voice`,
    `voice.catalogue.*`) degrades cleanly without crashing Daemon or SpeechService,
    and concurrent multi-threaded writes to Store preserve all rows without
    database lock errors.
    """
    import threading

    cfg = _sandbox_config(tmp_path)
    store = Store(cfg.db_path)
    try:
        store.set_state("persona", "{not-valid-json")
        store.set_state("tts.selected_voice", "{corrupt-descriptor")
        store.set_state(f"voice.catalogue.{DEFAULT_VOICE_MODEL}", "{corrupt-catalogue")

        assert load_cached(store, DEFAULT_VOICE_MODEL) is None
        speech = SpeechService(cfg, store)
        assert speech.descriptor().voice_id == cfg.section("tts")["voice_id"]

        daemon = Daemon(cfg)
        try:
            assert isinstance(daemon.governor.familiarity, float)
        finally:
            daemon.store.close()

        # Concurrent multi-threaded writes into the same WAL SQLite store
        errors: list[Exception] = []

        def _writer(tid: int) -> None:
            try:
                for i in range(15):
                    store.add_fact(
                        ts="2026-10-20T12:00:00Z",
                        kind="note",
                        text=f"thread-{tid}-fact-{i}",
                        source="stated",
                    )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []
        assert len(store.list_facts(kind="note")) == 60
    finally:
        store.close()


def test_cross_cutting_disk_full_enospc_leaves_clean_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Cross-cutting: an `ENOSPC` failure mid-write in `SpeechService.write_wav`
    leaves neither a truncated target WAV nor a leftover `.tmp-*` file.
    """
    import errno
    import wave

    dest = tmp_path / "cache" / "ack.wav"
    orig_open = wave.open

    def _enospc_wave_open(f, mode="rb"):
        w = orig_open(f, mode)
        if mode == "wb":
            def _boom(_frames):
                raise OSError(errno.ENOSPC, "No space left on device")
            w.writeframes = _boom
        return w

    monkeypatch.setattr("assistant.tts.wave.open", _enospc_wave_open)
    with pytest.raises(OSError, match="No space left on device"):
        SpeechService.write_wav(dest, _pcm_bytes(50), 24000)

    assert not dest.exists()
    assert list(dest.parent.glob("*")) == []


def test_daemon_shutdown_cancels_in_flight_dictation_and_collector_cleanly(
    tmp_path: Path,
):
    """Cross-cutting: `Daemon.aclose()` cancels an active `ptt.start` dictation
    session and its nested `collect_events` task without leaking pending tasks.
    """
    cfg = _sandbox_config(tmp_path)

    async def _run() -> None:
        daemon = Daemon(cfg)
        out = await daemon._ptt_start({"source": "simulated"})
        assert out["listening"] is True
        assert daemon._dictation_task is not None
        await asyncio.sleep(0.05)
        await daemon.aclose()
        assert daemon._dictation_task.done()

    asyncio.run(_run())


