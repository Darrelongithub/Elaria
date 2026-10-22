"""Adversarial bug-hunt corpus for Areas D–G.

D: planner/intent/config parsing. E: store/memory/queue/Gemini harness.
F: ASR/capture/meeting/TTS. G: IPC/daemon/persona/voice-test surfaces.

Known bugs are strict-xfail and cross-referenced in bugs.md. Assertions are
about persisted state, routing state, or exact returned records.
"""

from __future__ import annotations

import asyncio
import json
import struct
import threading
from datetime import datetime
from pathlib import Path

import pytest

from assistant.asr import Transcript, transcribe_file
from assistant.capture import SimulatedCapture, WavSink, pw_record_pcm_stream_command, write_wav
from assistant.config import _deep_merge, load_config, load_humour_profile
from assistant.diarize import Turn
from assistant.embeddings import HashingEmbedder
from assistant.gemini_client import GeminiClient
from assistant.intents import route
from assistant.ipc import call as ipc_call
from assistant.ipc import serve as ipc_serve
from assistant.live_client import ScriptedLiveTransport
from assistant.meeting import MeetingService
from assistant.memory import Memory
from assistant.modes import ModeManager, looks_like_network_failure
from assistant.offline_queue import CloudQueue
from assistant.planner_llm import _parse_batch
from assistant.store import Store
from assistant.transcribe import DictationService
from assistant.tts import MockTtsBackend, PiperTtsBackend, SpeechService, VoiceDescriptor
from assistant.voicetest import suggest_threshold
from assistant.watcher import PollingWatcher

FIXTURES = json.loads(
    (Path(__file__).parent / "bughunt_fixtures" / "evil_inputs.json").read_text())


# -- D: planner / intents / config -------------------------------------------

@pytest.mark.parametrize("phrase", FIXTURES["intent_must_not_act"])
def test_must_not_act_phrases_do_not_route_to_local_actions(phrase):
    assert route(phrase) is None


def test_llm_batch_with_duplicate_path_and_missing_file_is_invalid():
    payload = json.dumps([
        {"path": "/r/a.txt", "dest": "Finance", "confidence": 0.99},
        {"path": "/r/a.txt", "dest": "Finance", "confidence": 0.98},
    ])
    assert _parse_batch(payload, {"Finance"}, {"/r/a.txt", "/r/b.txt"}) is None


def test_llm_batch_boolean_confidence_is_invalid():
    payload = json.dumps([
        {"path": "/r/a.txt", "dest": "Finance", "confidence": True},
    ])
    assert _parse_batch(payload, {"Finance"}, {"/r/a.txt"}) is None


@pytest.mark.parametrize("phrase", [
    "cost of living in Nairobi",
    "usage of the word serendipity",
    "quota for fishing boats",
])
def test_ordinary_cost_words_are_not_the_api_cost_intent(phrase):
    assert route(phrase) is None


@pytest.mark.parametrize("phrase", ["halt please", "stop everything now", "panic stop now"])
def test_natural_halt_variants_route_to_halt(phrase):
    intent = route(phrase)
    assert intent is not None and intent.kind == "halt"


def test_string_taxonomy_and_languages_are_rejected_or_wrapped(config):
    config.raw["organise"] = {
        **config.raw["organise"],
        "roots": [{"path": "/tmp", "taxonomy": "Finance"}],
    }
    config.raw["asr"] = {**config.raw["asr"], "languages": "sw"}

    from assistant.asr import configured_languages

    assert config.organise_roots()[0]["taxonomy"][:1] == ["Finance"]
    assert configured_languages(config) == ["sw"]


def test_mutating_loaded_config_does_not_pollute_next_load():
    first = load_config()
    original = first.raw["persona"]["name"]
    try:
        first.raw["persona"]["name"] = "POLLUTED-BY-PREVIOUS-LOAD"
        assert load_config().raw["persona"]["name"] == original
    finally:
        # Same object today: restore it so the xfail itself cannot poison
        # later tests in the same pytest process.
        first.raw["persona"]["name"] = original


def test_malformed_humour_profile_degrades_to_empty_profile(config, tmp_path):
    bad = tmp_path / "humour.toml"
    bad.write_text("[not valid toml", encoding="utf-8")
    config.raw["persona"] = {**config.raw["persona"], "humour_profile": str(bad)}
    assert load_humour_profile(config) == {}


def test_deep_merge_replaces_scalars_but_merges_sections():
    merged = _deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"y": 3}})
    assert merged == {"a": {"x": 1, "y": 3}}


# -- E: store / memory / queue / harness --------------------------------------

def test_forget_percent_is_a_literal_topic_not_a_wildcard(tmp_path):
    store = Store(tmp_path / "memory.db")
    memory = Memory(store, HashingEmbedder())
    memory.remember("alpha fact")
    memory.remember("100% certain")
    assert memory.forget("%") == 1
    assert [fact["text"] for fact in memory.beliefs()] == ["alpha fact"]


def test_forget_underscore_is_a_literal_topic_not_a_wildcard(tmp_path):
    store = Store(tmp_path / "memory.db")
    memory = Memory(store, HashingEmbedder())
    memory.remember("alpha fact")
    memory.remember("snake_case fact")
    assert memory.forget("_") == 1
    assert [fact["text"] for fact in memory.beliefs()] == ["alpha fact"]


# BH-E2 (fixed): `search_documents()` used to hand raw user text to FTS5
# `MATCH`, so `"`, `NEAR(`, `invoice OR`, `(invoice` and `invoice)` raised
# sqlite3.OperationalError. These tests run against a *populated* index: an
# empty one lets SQLite skip MATCH evaluation entirely, which is how the
# bug hid as an XPASS on some SQLite builds.
BH_E2_QUERIES = ['"', "NEAR(", "invoice OR", "(invoice", "invoice)"]


def _indexed_store(tmp_path) -> Store:
    """A populated index — FTS5 really has to parse MATCH against rows."""
    store = Store(tmp_path / "search.db")

    def index(path, *chunks):
        store.upsert_document(
            path=path, root="/docs", sha256="0" * 64, size=1, mtime=1.0,
            mime="text/plain", ext=".txt", indexed_ts="2026-01-01T00:00:00+00:00",
            never_send=0, text_chunks=list(chunks))

    index("/docs/invoice-2026.txt",
          "invoice total for the march shipment",
          "paid by bank transfer on monday")
    index("/docs/notes.txt", "meeting notes about compilers and the budget")
    assert store.search_documents("invoice"), "fixture index must be searchable"
    return store


@pytest.mark.parametrize("query", BH_E2_QUERIES)
def test_search_documents_treats_user_text_as_text_not_fts_syntax(tmp_path, query):
    store = _indexed_store(tmp_path)
    assert isinstance(store.search_documents(query), list)   # no OperationalError


@pytest.mark.parametrize("query,expected", [
    ('"', []),                                   # punctuation only: no terms
    ("NEAR(", []),                               # operator keyword read as a word
    ("***", []),
    ("     ", []),
    ("(invoice", ["/docs/invoice-2026.txt"]),    # parens are text, term still found
    ("invoice)", ["/docs/invoice-2026.txt"]),
])
def test_search_documents_punctuation_is_text_not_operator(tmp_path, query, expected):
    store = _indexed_store(tmp_path)
    assert [hit["path"] for hit in store.search_documents(query)] == expected


def test_search_documents_still_finds_plain_keywords(tmp_path):
    """The BH-E2 fix must not blunt ordinary keyword search."""
    store = _indexed_store(tmp_path)
    assert [h["path"] for h in store.search_documents("budget")] == ["/docs/notes.txt"]
    assert [h["path"] for h in store.search_documents("invoice total")] == [
        "/docs/invoice-2026.txt"]
    assert {h["path"] for h in store.search_documents_any(["budget", "bank"])} == {
        "/docs/invoice-2026.txt", "/docs/notes.txt"}
    if store.fts5_available:
        # `snippet()` is FTS5-only: these brackets prove the MATCH arm ran.
        assert "[" in store.search_documents("invoice")[0]["snip"]


def test_fts5_match_expression_is_always_well_formed(tmp_path):
    """The real BH-E2 repro: feed the generated MATCH to a populated FTS5
    index. The old raw pass-through raised OperationalError right here."""
    from assistant.store import _fts_match_expression, _search_terms

    store = _indexed_store(tmp_path)
    if not store.fts5_available:
        pytest.skip("this SQLite build has no FTS5")
    for query in [*BH_E2_QUERIES, "*", "-", "NOT", "NEAR/a b/", "col:invoice",
                  '"a""b"', "%%%", "a" * 300]:
        expression = _fts_match_expression(_search_terms(query))
        if expression is None:
            continue
        for term in expression.split(" OR "):
            assert term.startswith('"') and term.endswith('"'), expression
        store._conn.execute(
            "SELECT count(*) FROM doc_chunks_fts WHERE doc_chunks_fts MATCH ?",
            (expression,)).fetchone()          # must not raise


def test_like_fallback_is_literal_and_wildcard_safe(tmp_path):
    """BH-E2 fallback path: builds without FTS5 must be just as safe."""
    from assistant.store import _like_patterns

    assert _like_patterns(["a%b", "c_d", "e\\f"]) == [
        "%a\\%b%", "%c\\_d%", "%e\\\\f%"]
    store = _indexed_store(tmp_path)
    store.fts5_available = False               # force the LIKE arm
    assert [h["path"] for h in store.search_documents("invoice")] == [
        "/docs/invoice-2026.txt"]
    for query in BH_E2_QUERIES:
        assert isinstance(store.search_documents(query), list)
    assert store.search_documents("invoice total")[0]["snip"].startswith("invoice total")


@pytest.mark.parametrize("error", [
    FileNotFoundError("saved audio is missing"),
    PermissionError("audio is not readable"),
    OSError(28, "No space left on device"),
])
def test_local_filesystem_errors_are_not_network_failures(error):
    assert looks_like_network_failure(error) is False


def test_queue_drain_reaches_pending_job_after_500_finished_jobs(config, tmp_path):
    store = Store(tmp_path / "queue.db")
    with store._lock:
        store._conn.executemany(
            "INSERT INTO cloud_jobs (ts, kind, payload_json, status) VALUES (?, ?, ?, ?)",
            [("2026-01-01T00:00:00+00:00", "chat", "{}", "done")] * 500)
        store._conn.commit()
    queue = CloudQueue(config, store, client=None)
    job_id = queue.enqueue_chat("hello", "hello")
    seen = []
    queue._handle = lambda kind, payload, approved=False: seen.append(kind) or {"ok": True}

    result = queue.drain(limit=10)
    assert result["done"] == 1 and seen == ["chat"]
    assert store.get_cloud_job(job_id)["status"] == "done"


def test_queue_recovers_a_job_left_running_by_a_crash(config, tmp_path):
    store = Store(tmp_path / "queue.db")
    queue = CloudQueue(config, store, client=None)
    job_id = queue.enqueue_chat("hello", "hello")
    store.update_cloud_job(job_id, status="running", increment_attempts=True)

    queue._handle = lambda kind, payload, approved=False: {"ok": True}
    queue.drain(limit=10)
    assert store.get_cloud_job(job_id)["status"] == "done"


def test_mode_manager_without_store_remembers_requested_preference(config):
    manager = ModeManager(config, None, probe=lambda: True)
    status = manager.request_preference("offline")
    assert status.preference == "offline" and status.effective_mode == "FORCED_OFFLINE"


class _ScriptedTransport:
    def __init__(self, answers):
        self.answers = list(answers)

    def generate(self, model, contents, config):
        return {"text": self.answers.pop(0),
                "usage": {"tokens_in": 3, "tokens_out": 2}}


def test_verified_outcome_is_recorded_in_the_ledger(config, tmp_path):
    store = Store(tmp_path / "ledger.db")
    client = GeminiClient(
        config, store, transport=_ScriptedTransport(["bad", "good"]),
        sleep=lambda _: None)
    result = client.generate("organise", "classify", verify=lambda text: text == "good")
    assert result.verified is True
    with store._lock:
        rows = store._conn.execute(
            "SELECT verified FROM llm_calls ORDER BY id").fetchall()
    assert [row[0] for row in rows] == [0, 1]


def test_concurrent_queue_drains_claim_a_job_once(config, tmp_path):
    """BH-C3 (fixed): claiming a job is ONE conditional UPDATE.

    The old code selected candidates and then updated the winner to
    `running` as two separate steps, so two drains that listed the same
    pending job both ran it. This test removes the scheduler luck: both
    drains are forced to finish listing candidates before either may claim,
    so they always compete for the same job.
    """
    store = Store(tmp_path / "queue.db")
    queue = CloudQueue(config, store, client=None)
    job_id = queue.enqueue_chat("once", "once")

    contested = threading.Barrier(2)
    real_list = store.list_cloud_jobs

    def contested_list(*args, **kwargs):
        jobs = real_list(*args, **kwargs)
        contested.wait(timeout=10)   # both drains now hold the same candidate
        return jobs

    store.list_cloud_jobs = contested_list

    calls = []
    results = []
    lock = threading.Lock()
    release = threading.Barrier(2)

    def handle(kind, payload, approved=False):
        with lock:
            calls.append(kind)
        return {"ok": True}

    queue._handle = handle

    def run():
        release.wait(timeout=10)
        result = queue.drain()
        with lock:
            results.append(result)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not [t for t in threads if t.is_alive()], "a drain deadlocked"

    assert calls == ["chat"]                        # handled exactly once
    assert len(results) == 2
    assert sum(r["done"] for r in results) == 1
    assert sorted(r["processed"] for r in results) == [0, 1]
    job = store.get_cloud_job(job_id)
    assert job["status"] == "done"                  # coherent final state
    assert job["attempts"] == 1                     # only the claimant counted


def test_claim_cloud_job_lets_exactly_one_caller_win(config, tmp_path):
    """The atomic primitive behind the BH-C3 fix, without the threads."""
    store = Store(tmp_path / "queue.db")
    queue = CloudQueue(config, store, client=None)
    job_id = queue.enqueue_chat("once", "once")

    assert store.claim_cloud_job(job_id) is True
    assert store.claim_cloud_job(job_id) is False   # already running
    assert store.get_cloud_job(job_id)["attempts"] == 1
    store.update_cloud_job(job_id, status="done")
    assert store.claim_cloud_job(job_id) is False   # done is not claimable

    approved = queue.enqueue_external("download", "fetch a model")
    store.update_cloud_job(approved, status="approved")
    assert store.claim_cloud_job(approved) is True  # approved -> running
    assert store.get_cloud_job(approved)["status"] == "running"


# -- F: ASR / capture / TTS ----------------------------------------------------

class _EmptyBackend:
    name = "empty-local"

    def transcribe(self, audio_path, language):
        return Transcript("", language, self.name, confidence=0.0)


def test_asr_fallback_chain_continues_after_empty_text(config, tmp_path):
    config.raw["asr"] = {**config.raw["asr"], "fallback": ["local", "mock"]}
    result = transcribe_file(
        config, client=None, audio_path=str(tmp_path / "x.wav"),
        local_backend=_EmptyBackend())
    assert result.backend == "mock" and result.text


def test_wav_sink_reports_duration_at_its_configured_sample_rate(tmp_path):
    sink = WavSink(tmp_path / "eight-k.wav", sample_rate=8000)
    sink.write(b"\x00\x00" * 8000)
    assert sink.close() == pytest.approx(1.0)


def test_pw_record_stream_rejects_short_numeric_object_id_targets():
    with pytest.raises(ValueError, match="object\\.serial|node\\.name"):
        pw_record_pcm_stream_command("42")


def _meeting_wav(path: Path, sample: int) -> Path:
    return write_wav(path, [struct.pack("<16000h", *([sample] * 16000))])


def test_same_minute_meetings_never_overwrite_raw_audio_or_notes(
        config, tmp_path, monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 19, 12, 34, 56)

    monkeypatch.setattr("assistant.meeting.datetime", FrozenDateTime)
    monkeypatch.setattr(
        MeetingService, "_transcribe_channel",
        lambda self, wav, speaker, work: [Turn(speaker, 0.0, 1.0, speaker)])
    store = Store(tmp_path / "meeting.db")
    service = MeetingService(config, store, client=None)

    first_mic = _meeting_wav(tmp_path / "first-mic.wav", 1000)
    first_sys = _meeting_wav(tmp_path / "first-sys.wav", 2000)
    first = service.transcribe_dual(first_mic, first_sys, title="First")
    first_state = {
        "mic": first.mic_wav.read_bytes(),
        "system": first.system_wav.read_bytes(),
        "note": first.note_path.read_bytes(),
    }

    second_mic = _meeting_wav(tmp_path / "second-mic.wav", 3000)
    second_sys = _meeting_wav(tmp_path / "second-sys.wav", 4000)
    second = service.transcribe_dual(second_mic, second_sys, title="Second")

    assert second.mic_wav != first.mic_wav
    assert second.system_wav != first.system_wav
    assert second.note_path != first.note_path
    assert first.mic_wav.read_bytes() == first_state["mic"]
    assert first.system_wav.read_bytes() == first_state["system"]
    assert first.note_path.read_bytes() == first_state["note"]
    assert second.mic_wav.read_bytes() == second_mic.read_bytes()
    assert second.system_wav.read_bytes() == second_sys.read_bytes()


def test_meeting_system_channel_is_copied_even_when_mic_is_canonical(
        config, tmp_path, monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 19, 12, 35, 56)

    monkeypatch.setattr("assistant.meeting.datetime", FrozenDateTime)
    monkeypatch.setattr(
        MeetingService, "_transcribe_channel",
        lambda self, wav, speaker, work: [Turn(speaker, 0.0, 1.0, speaker)])
    store = Store(tmp_path / "meeting.db")
    service = MeetingService(config, store, client=None)
    first = service.transcribe_dual(
        _meeting_wav(tmp_path / "mic.wav", 1000),
        _meeting_wav(tmp_path / "sys-a.wav", 2000), title="First")
    replacement_sys = _meeting_wav(tmp_path / "sys-b.wav", 4000)

    second = service.transcribe_dual(first.mic_wav, replacement_sys, title="Second")
    assert second.system_wav.read_bytes() == replacement_sys.read_bytes()
    assert first.system_wav.read_bytes() != replacement_sys.read_bytes()


def test_piper_availability_requires_the_json_config(tmp_path, monkeypatch):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    descriptor = VoiceDescriptor(
        voice_id="voice", model=str(model), config=str(tmp_path / "missing.json"))
    backend = PiperTtsBackend(descriptor, command="piper")
    monkeypatch.setattr("assistant.tts.shutil.which", lambda _: "/usr/bin/piper")
    assert "config" in (backend.availability_error() or "").lower()


def test_tts_explicit_destination_is_not_reused_for_different_text(config, tmp_path):
    config.raw["tts"] = {**config.raw["tts"], "cache_dir": str(tmp_path / "cache")}
    backend = MockTtsBackend("one-voice")
    service = SpeechService(config, backend=backend)
    dest = tmp_path / "speech.wav"
    service.synthesize("first text", dest)
    service.synthesize("second text", dest)
    assert backend.calls == ["first text", "second text"]


def test_live_age_rotation_does_not_reconnect_on_every_frame(config, tmp_path):
    store = Store(tmp_path / "dictation.db")
    service = DictationService(config, store, GeminiClient(config, store))
    service.session_max_s = -1  # every transport is instantly "too old"
    transports = []

    def factory():
        transport = ScriptedLiveTransport()
        transports.append(transport)
        return transport

    result = asyncio.run(service.dictate(
        SimulatedCapture(speech_frames=20, silent_frames=0),
        transport_factory=factory))
    assert result.raw_text
    assert len(transports) <= 2


def test_cleanup_failure_still_persists_raw_transcript(config, tmp_path):
    store = Store(tmp_path / "dictation.db")
    service = DictationService(config, store, GeminiClient(config, store))

    def explode(raw):
        raise RuntimeError("cleanup quota exploded")

    service.cleanup.run = explode
    audio = _meeting_wav(tmp_path / "dictation.wav", 6000)
    result = asyncio.run(service.transcribe_file(audio))
    assert result.raw_text
    assert result.inbox_path and Path(result.inbox_path).exists()
    assert store.recent_transcripts(1)[0]["raw_text"] == result.raw_text


def test_ipc_call_skips_event_lines_until_the_matching_reply(tmp_path):
    async def handler(method, params, writer=None):
        writer.write(b'{"event":"transcript.interim","text":"partial"}\n')
        await writer.drain()
        return {"answer": 42}

    loop = asyncio.new_event_loop()
    socket_path = tmp_path / "assistant.sock"
    server = loop.run_until_complete(ipc_serve(socket_path, handler))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        assert ipc_call(socket_path, "ask", timeout=3) == {"answer": 42}
    finally:
        async def _shutdown():
            server.close()
            await asyncio.wait_for(server.wait_closed(), timeout=3)

        asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=3)
        loop.close()


# -- G: watcher / voice-test / daemon review ----------------------------------

def test_watcher_debounce_restarts_when_a_file_changes_again(tmp_path):
    import os
    import time

    root = tmp_path / "watched"
    root.mkdir()
    target = root / "download.bin"
    target.write_bytes(b"one")
    old = time.time() - 10_000
    os.utime(target, (old, old))
    clock = [old]
    watcher = PollingWatcher(root, debounce_s=10, now=lambda: clock[0])

    target.write_bytes(b"two!")
    os.utime(target, (old, old))
    watcher.scan()  # first change at old

    clock[0] = old + 9
    target.write_bytes(b"three!")
    os.utime(target, (old, old))
    watcher.scan()  # changed again at old+9; must restart the 10s clock

    clock[0] = old + 11
    events = watcher.scan()
    assert events.settled_changed == []


def test_suggested_speaker_threshold_uses_the_separation_gap_midpoint():
    result = suggest_threshold([
        {"label": "correct", "speaker_score": 0.90},
        {"label": "false-trigger", "speaker_score": 0.10},
    ])
    assert result["suggested"] == pytest.approx(0.50, abs=0.05)


def test_review_decide_rejects_a_nonexistent_item(config):
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    with pytest.raises(ValueError, match="no review item|does not exist"):
        asyncio.run(daemon._review_decide({"item_id": 999999, "verdict": "approve"}))
