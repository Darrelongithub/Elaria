"""TASK L (MOUTH) pins — a reply that is spoken, or honestly labelled text.

Landed here:
  F33  cache key = text + voice + settings hash; lives in `voice-cache/`,
       permanently outside tiering, regenerable, LRU-capped
  F21  consent is READ: no voiced Yes/No prompt exists anywhere, and the No
       persona line stays text
  L3   a 429 / TTS failure renders LABELLED text — never silence, never a
       claim of speech
  L1   `speak=true` runs through the existing TTS route and the audio stays on
       the daemon side: no console snapshot carries an audio field

[TESTED-ONLY] — the mock backend writes real WAV bytes; audibility on the
owner's hardware remains the only audio acceptance for this task.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path

from assistant import asr  # noqa: F401  (import parity with the other voice pins)
from assistant.config import load_config
from assistant.console import ConsoleService, SessionService
from assistant.daemon import Daemon
from assistant.tts import (
    DEFAULT_CACHE_MAX_FILES,
    VOICE_CACHE_DIRNAME,
    MockTtsBackend,
    SpeechService,
    TtsUnavailable,
)


def _config(tmp_path, **overrides):
    config = load_config()
    config.raw["tts"] = {
        **config.raw["tts"], "backend": "mock", "voice_id": "elaria-test",
        "online_voice": "local", "offline_voice": "local", "player": "none",
        "cache_dir": str(tmp_path / "cache"), **overrides,
    }
    return config


def _service(tmp_path, **overrides):
    config = _config(tmp_path, **overrides)
    return SpeechService(config, None, backend=MockTtsBackend("elaria-test")), config


# ---------------------------------------------------------------------------
# F33 — the key, the directory, the cap
# ---------------------------------------------------------------------------
def test_f33_key_is_text_plus_voice_plus_settings_hash(tmp_path):
    speech, config = _service(tmp_path)

    first = speech._route_cache_path("Good evening.")
    same = speech._route_cache_path("Good evening.")
    other_text = speech._route_cache_path("Good morning.")

    assert first == same, "the same words and settings must hit the same file"
    assert first != other_text, "different words are different audio"
    assert speech.settings_hash() and len(speech.settings_hash()) == 12

    # A settings change that alters how she sounds must make a NEW key.
    cloud_before = speech.settings_hash("gemini")
    config.raw["tts"]["length_scale"] = 1.4
    changed = speech._route_cache_path("Good evening.")
    assert changed != first, "pace changed — replaying the old render would lie"
    # VB-2 still holds: the dormant path's pace has nothing to do with Flare.
    assert speech.settings_hash("gemini") == cloud_before


def test_f33_voice_change_invalidates_the_key(tmp_path):
    speech, config = _service(tmp_path)
    before = speech._route_cache_path("Good evening.")
    config.raw["tts"]["voice_id"] = "elaria-other"
    config.raw["tts"]["speaker"] = 3
    assert speech._route_cache_path("Good evening." ) != before


def test_f33_renders_live_in_voice_cache_and_the_indexer_never_tiers_them(tmp_path):
    from assistant.indexer import EXCLUDED_DIRNAMES

    config = load_config()
    speech = SpeechService(config, None, backend=MockTtsBackend("elaria-test"))
    assert speech.cache_dir.name == VOICE_CACHE_DIRNAME == "voice-cache"
    assert speech.cache_dir.parent == config.data_dir
    assert VOICE_CACHE_DIRNAME in EXCLUDED_DIRNAMES

    # Even with the data dir inside a whitelisted root, the tree is counted
    # and pruned, never descended.
    from assistant.indexer import Indexer
    from assistant.store import Store

    root = tmp_path / "root"
    (root / VOICE_CACHE_DIRNAME).mkdir(parents=True, exist_ok=True)
    (root / VOICE_CACHE_DIRNAME / "speech-deadbeef.wav").write_bytes(b"RIFF")
    (root / "notes.md").write_text("a real document", encoding="utf-8")
    store = Store(tmp_path / "indexer.db")
    try:
        indexer = Indexer(config, store)
        seen = list(indexer.iter_files(root))
        skipped = {reason for _path, reason in seen}
        assert VOICE_CACHE_DIRNAME in skipped, "voice-cache must be excluded"
        indexed = [p.name for p, reason in seen if reason is None]
        assert "speech-deadbeef.wav" not in indexed
        assert "notes.md" in indexed
    finally:
        store.close()


def test_f33_lru_cap_evicts_the_oldest_and_keeps_the_new_render(tmp_path):
    speech = _service(tmp_path, cache_max_files=5)[0]
    speech.cache_dir.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for index in range(8):
        path = speech.cache_dir / f"speech-{index:020d}.wav"
        path.write_bytes(b"RIFF")
        stamp = now - (8 - index) * 10
        import os as _os
        _os.utime(path, (stamp, stamp))
    newest = speech.cache_dir / "speech-newest.wav"
    newest.write_bytes(b"RIFF")
    import os as _os
    _os.utime(newest, (now, now))

    report = speech.enforce_cache_cap(keep=newest)

    assert report["cap"] == 5
    assert report["deleted"] == 4
    kept = sorted(p.name for p in speech.cache_dir.glob("speech-*.wav"))
    assert len(kept) == 5
    assert newest.exists(), "the render this call produced is never evicted"
    assert "speech-00000000000000000000.wav" not in kept, "oldest went first"
    assert speech.cache_report()["policy"].startswith("regenerable")


def test_f33_eviction_is_journalled_and_a_lost_file_just_re_renders(tmp_path):
    speech = _service(tmp_path, cache_max_files=1)[0]
    speech.speak("First line.", play=False)
    oldest = speech._route_cache_path("First line.")
    assert oldest.exists()

    time.sleep(0.01)
    speech.speak("Second line.", play=False)
    assert oldest.exists() is False, "cap 1 keeps only the newest render"

    # Regenerable: saying the evicted line again simply renders again.
    again = speech.speak("First line.", play=False)
    assert again.audio_path and Path(again.audio_path).exists()
    assert again.cached is False


def test_f33_cap_is_declared_in_defaults_and_the_example_config():
    from assistant.config import DEFAULTS

    assert DEFAULTS["tts"]["cache_max_files"] == DEFAULT_CACHE_MAX_FILES == 120
    example = (Path(__file__).resolve().parents[1] / "config.toml.example").read_text()
    assert "cache_max_files" in example
    assert "voice-cache" in example


# ---------------------------------------------------------------------------
# a failed render is labelled text — never silence, never a speech claim
# ---------------------------------------------------------------------------
class _QuotaWall:
    """The 429 shape: the renderer refuses, the words still have to arrive."""

    name = "gemini-native-audio"
    voice_id = "flare"

    def synthesize(self, text, dest):
        raise TtsUnavailable("429 RESOURCE_EXHAUSTED — quota wall")


def test_tts_429_renders_labelled_text_and_never_claims_speech(tmp_path):
    config = _config(tmp_path)
    speech = SpeechService(config, None, backend=_QuotaWall())
    result = speech.speak("The plan is ready.", play=True)

    assert result.played is False
    assert result.muted is True
    assert "429" in (result.error or ""), "the reason must survive, not be tidied"
    assert speech.last_voice_error and "429" in speech.last_voice_error


def test_reply_carries_speech_status_so_a_client_cannot_invent_voice(tmp_path):
    config = _config(tmp_path)
    daemon = Daemon(config)

    async def run():
        def failing_speak(text, *, play=True, session_id=None):
            from assistant.tts import SpeechResult
            return SpeechResult(text=text, backend="none", voice_id="none",
                                played=False, muted=True,
                                error="429 RESOURCE_EXHAUSTED — quota wall")

        daemon.speech.speak = failing_speak
        payload = await daemon._maybe_speak_reply("The plan is ready.",
                                                  {"speak": True})
        await daemon.aclose()
        return payload

    payload = asyncio.run(run())
    assert payload["speech_status"] == "text-only"
    assert payload["played"] is False
    assert "429" in payload["error"]
    assert "as text" in payload["speech_reason"]
    assert payload.get("text", "The plan is ready.")


def test_consent_ask_can_never_be_spoken_and_the_handlers_cannot_speak():
    assert "speak" not in inspect.getsource(Daemon._undo_prepare)
    assert "speak" not in inspect.getsource(Daemon._undo_apply)
    assert "speak" not in inspect.getsource(Daemon._undo_drift)


def test_f21_a_consent_reply_is_refused_voice_and_labelled(tmp_path):
    config = _config(tmp_path)
    daemon = Daemon(config)
    calls: list = []

    async def run():
        daemon.speech.speak = lambda text, **kwargs: calls.append(text)
        payload = await daemon._maybe_speak_reply("Undo invoice-march.txt?",
                                                  {"speak": True, "consent": True})
        both = await daemon._maybe_speak_reply("No. Nothing was undone.",
                                               {"speak": True, "no_speech": True})
        await daemon.aclose()
        return payload, both

    payload, both = asyncio.run(run())
    assert calls == [], "a consent ask reached TTS"
    for item in (payload, both):
        assert item["played"] is False
        assert item["speech_status"] == "text-only"
        assert "F21" in item["speech_suppressed"]


def test_f21_no_audible_prompt_and_the_no_line_is_text_only(tmp_path):
    """The consent seam end to end: prepare and decline, with TTS spied."""
    import os
    from contextvars import ContextVar

    from assistant.executor import Executor
    from assistant.ipc import IpcPrincipal
    from assistant.organiser import OrganiserService
    from assistant.store import Store

    root = tmp_path / "docs"
    root.mkdir()
    (root / "Finance").mkdir()
    old = time.time() - 86400 * 3
    for name, data in (("invoice-march.txt", b"invoice due"),
                       ("holiday-photo.jpg", b"jpeg-ish")):
        path = root / name
        path.write_bytes(data)
        os.utime(path, (old, old))
    config = _config(tmp_path)
    config.raw["organise"] = {**config.raw["organise"],
                              "roots": [{"path": str(root), "mode": "live",
                                         "taxonomy": ["Finance", "_Unsorted"]}]}
    config.raw["policy"] = {**config.raw["policy"],
                            "recently_modified_guard_minutes": 15}
    store = Store(tmp_path / "mouth.db")
    try:
        organiser = OrganiserService(config, store)
        executor = Executor(config, store)
        plan = organiser.build_plan(config.organise_roots()[0])
        executor.apply_plan(plan["plan_id"], config.organise_roots()[0],
                            allow_tripwire=True)

        daemon = object.__new__(Daemon)
        daemon.store = store
        daemon.executor = executor
        daemon._undo_asks = {}
        principal = IpcPrincipal(pid=os.getpid(), uid=os.getuid(), gid=os.getgid())
        var: ContextVar = ContextVar("mouth_principal", default=None)
        var.set(principal)
        daemon._ipc_principal = var

        async def run():
            prepared = await daemon._undo_prepare({"plan_id": plan["plan_id"]})
            declined = await daemon._undo_apply({"token": prepared["token"],
                                                 "decision": "no"})
            return prepared, declined

        prepared, declined = asyncio.run(run())

        assert prepared["spoken"] is False and "F21" in prepared["speech_suppressed"]
        assert declined["decision"] == "no" and declined["undone"] == 0
        assert declined["spoken"] is False
        lines = [json.loads(row["detail"]) for row in
                 store.list_persona_events(kind="ack", limit=5)]
        assert lines and lines[0]["ack"] == "declined"
        assert "src" not in lines[0] and "dst" not in lines[0], (
            "a No echoes no reviewed content")
    finally:
        store.close()


def test_speak_true_audio_stays_daemon_side_and_the_console_never_carries_it(tmp_path):
    config = _config(tmp_path)
    from assistant.store import Store

    store = Store(tmp_path / "console.db")
    try:
        daemon = Daemon(config)

        async def run():
            payload = await daemon._maybe_speak_reply("Supper is at seven.",
                                                      {"speak": True, "session_id": "s1"})
            await daemon.aclose()
            return payload

        payload = asyncio.run(run())
        # The reply owns the audio path (the daemon plays it) ...
        assert payload["audio_path"] or payload["played"] is False
        assert payload["speech_status"] in ("spoken", "text-only")

        # ... and the console snapshot is text-only by construction.
        sessions = SessionService(store)
        console = ConsoleService(config, store, sessions=sessions)
        snapshot = console.snapshot()
        blob = json.dumps(snapshot, default=str)
        assert "audio_path" not in blob
        assert "voice-cache" not in blob
    finally:
        store.close()
