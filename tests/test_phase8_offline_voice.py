"""Phase 8 (§13.8/§13.9/§18): offline mode + the ONE-VOICE rule.

Proved headlessly with mocked Gemini/local engines:
- detected vs forced offline stay distinct;
- a network drop mid-dictation produces local text + a queued cloud redo;
- forced offline structurally cannot call Gemini/Live/health probes;
- online and offline spoken replies route to the same local TTS voice;
- reconnect drains transcription/judgement while external work stays gated;
- a switch requested during capture is parked until the session finishes.
"""

import asyncio
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant.asr import LocalWhisperBackend, Transcript, transcribe_file
from assistant.capture import SimulatedCapture, write_wav
from assistant.gemini_client import GeminiClient
from assistant.inbox import write_inbox_note
from assistant.live_client import ScriptedLiveTransport
from assistant.modes import FORCED_OFFLINE, OFFLINE, ONLINE, ModeManager, looks_like_network_failure
from assistant.offline_queue import CloudQueue
from assistant.store import Store
from assistant.transcribe import DictationService
from assistant.tts import (
    STANDARD_ACKS,
    MockTtsBackend,
    PiperTtsBackend,
    SpeechService,
    VoiceDescriptor,
)
from assistant.waybar import format_waybar


class Probe:
    def __init__(self, healthy=True):
        self.healthy = healthy
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.healthy


class ScriptedLocal:
    name = "local"

    def __init__(self, text="status", confidence=0.42):
        self.text = text
        self.confidence = confidence
        self.calls = []

    def transcribe(self, audio_path, language):
        self.calls.append((audio_path, language))
        return Transcript(text=self.text, language=language, backend="local",
                          confidence=self.confidence)


class ExplodingTransport:
    def __init__(self):
        self.calls = 0

    def generate(self, model, contents, config):
        self.calls += 1
        raise AssertionError("Gemini transport was called while forced offline")


class TextTransport:
    def __init__(self):
        self.calls = []

    def generate(self, model, contents, config):
        self.calls.append((model, contents))
        if isinstance(contents, dict):  # batch transcription request
            return {"text": "cloud transcript done properly for the full saved recording",
                    "usage": {"tokens_in": 11, "tokens_out": 7}}
        text = str(contents)
        if "repairing a speech-to-text transcript" in text:
            return {"text": "Cloud transcript done properly for the full saved recording.",
                    "usage": {"tokens_in": 12, "tokens_out": 7}}
        return {"text": "queued chat answer", "usage": {"tokens_in": 5, "tokens_out": 4}}


class NetworkDropTransport(ScriptedLiveTransport):
    async def connect(self, resumption_handle=None):
        raise OSError("Network is unreachable")


def make_store(tmp_path):
    return Store(tmp_path / "phase8.db")


# -- mode manager ---------------------------------------------------------------

def test_mode_manager_auto_online_and_forced_are_distinct(config, tmp_path):
    store = make_store(tmp_path)
    probe = Probe(healthy=False)
    manager = ModeManager(config, store, probe=probe, clock=lambda: 100.0)
    assert manager.refresh(force=True).effective_mode == OFFLINE

    probe.healthy = True
    assert manager.refresh(force=True).effective_mode == ONLINE
    calls_before = probe.calls
    forced = manager.request_preference("offline")
    assert forced.effective_mode == FORCED_OFFLINE
    assert manager.status().effective_mode == FORCED_OFFLINE
    assert probe.calls == calls_before  # forced offline does not even probe

    parked = manager.request_preference("online", active_session=True)
    assert parked.switch_parked and parked.effective_mode == FORCED_OFFLINE
    applied = manager.apply_pending_after_session()
    assert applied.preference == "online" and applied.effective_mode == ONLINE


def test_network_classifier_does_not_call_quota_a_dead_router():
    assert looks_like_network_failure(OSError("Network is unreachable")) is True
    assert looks_like_network_failure("503 unavailable") is True
    assert looks_like_network_failure("429 quota exhausted") is False


# -- offline ASR seam --------------------------------------------------------------

def test_faster_whisper_backend_uses_lazy_loader_and_confidence(config):
    segments = [
        SimpleNamespace(text=" file the invoice ", start=0, end=1, avg_logprob=-0.2),
        SimpleNamespace(text=" before Friday", start=1, end=2, avg_logprob=-0.4),
    ]

    class FakeModel:
        def transcribe(self, path, language, task, vad_filter):
            assert language == "en" and task == "transcribe" and vad_filter is True
            return iter(segments), SimpleNamespace(language="en")

    backend = LocalWhisperBackend(config, model_loader=lambda name: FakeModel())
    result = backend.transcribe("note.wav", "en")
    assert result.text == "file the invoice before Friday"
    assert result.backend == "local" and 0.7 < result.confidence < 0.85


def test_whisper_cpp_backend_parses_jsonprobabilities(config):
    config.raw["asr"].update({
        "offline_backend": "whisper.cpp",
        "whisper_cpp_model": "/models/ggml-small.bin",
        "whisper_cpp_command": "whisper-cli",
    })

    def runner(args, **kwargs):
        prefix = Path(args[args.index("-of") + 1])
        prefix.with_suffix(".json").write_text(json.dumps({
            "transcription": [{"text": "hallo from whisper cpp",
                               "tokens": [{"p": 0.8}, {"p": 1.0}]}],
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    result = LocalWhisperBackend(config, runner=runner).transcribe("note.wav", "en")
    assert result.text == "hallo from whisper cpp"
    assert result.confidence == pytest.approx(0.9)


def test_offline_transcribe_chain_cannot_reach_gemini(config, tmp_path):
    store = make_store(tmp_path)
    exploding = ExplodingTransport()
    client = GeminiClient(config, store, transport=exploding, sleep=lambda _: None)
    local = ScriptedLocal("file that invoice", 0.92)
    result = transcribe_file(config, client, "note.wav", offline=True, local_backend=local)
    assert result.backend == "local" and result.confidence == 0.92
    assert exploding.calls == 0 and local.calls


# -- dictation: drop + forced offline ------------------------------------------------

def test_network_drop_mid_dictation_queues_cloud_redo(config, tmp_path):
    store = make_store(tmp_path)
    exploding = ExplodingTransport()
    client = GeminiClient(config, store, transport=exploding, sleep=lambda _: None)
    manager = ModeManager(config, store, probe=Probe(True))
    queue = CloudQueue(config, store, client, manager)
    local = ScriptedLocal(
        "rough offline words about filing the march invoice before friday please", 0.31)
    service = DictationService(config, store, client, mode_manager=manager,
                               offline_queue=queue, local_backend=local)
    events = []

    async def sink(event):
        events.append(event["event"])

    result = asyncio.run(service.dictate(
        SimulatedCapture(speech_frames=12, silent_frames=0),
        transport_factory=NetworkDropTransport, sink=sink))

    assert result.backend == "local"
    assert result.confidence == 0.31
    assert result.cloud_status == "pending_cloud_transcription"
    assert Path(result.audio_path).exists()  # raw audio always saved
    assert result.queued_job_ids
    row = store.get_transcript(result.transcript_id)
    assert row["cloud_status"] == "pending_cloud_transcription"
    assert row["confidence"] == pytest.approx(0.31)
    kinds = [job["kind"] for job in queue.list_jobs()]
    assert "cloud_transcription" in kinds and "transcript_cleanup" in kinds
    assert manager.status(refresh=False).effective_mode == OFFLINE
    assert exploding.calls == 0
    assert events[0] == "session.started" and events[-1] == "session.ended"


def test_forced_offline_dictation_never_builds_live_transport(config, tmp_path):
    store = make_store(tmp_path)
    manager = ModeManager(config, store, probe=Probe(True))
    manager.request_preference("offline")
    client = GeminiClient(config, store, transport=ExplodingTransport(), sleep=lambda _: None)
    service = DictationService(
        config, store, client, mode_manager=manager,
        offline_queue=CloudQueue(config, store, client, manager),
        local_backend=ScriptedLocal("status", 0.4))
    factory_calls = []
    events = []

    def forbidden_factory():
        factory_calls.append(True)
        raise AssertionError("Live transport built while forced offline")

    async def sink(event):
        events.append(event["event"])

    result = asyncio.run(service.dictate(
        SimulatedCapture(speech_frames=5, silent_frames=150),
        transport_factory=forbidden_factory, mode="command", sink=sink))
    assert result.backend == "local"
    assert result.connectivity_mode == FORCED_OFFLINE
    assert factory_calls == []
    assert "session.offline" in events
    assert "session.checkin" in events  # adaptive ladder still applies offline


# -- ONE VOICE --------------------------------------------------------------------------

def test_default_voice_is_the_owner_selected_southern_english_female(config):
    # Owner pick after two audition rounds (Jenny/Lessac/Kathleen rejected;
    # rough edge won). Guards against the canonical voice drifting silently.
    tts = config.section("tts")
    assert tts["voice_id"] == "en_GB-southern_english_female-low"
    assert tts["model"].endswith("en_GB-southern_english_female-low.onnx")
    assert tts["config"].endswith("en_GB-southern_english_female-low.onnx.json")
    candidate_ids = [c["id"] for c in tts["audition_candidates"]]
    assert candidate_ids[0] == "en_GB-southern_english_female-low"
    assert "en_GB-jenny_dioco-medium" not in candidate_ids  # round-1 rejects stay out
    speech = SpeechService(config)
    assert speech.descriptor().voice_id == "en_GB-southern_english_female-low"


def test_speech_cache_audition_and_selection_use_one_local_service(config, tmp_path):
    config.raw["tts"] = {
        **config.raw["tts"], "backend": "mock", "voice_id": "elaria-test",
        "player": "none", "cache_dir": str(tmp_path / "cache"),
        "audition_dir": str(tmp_path / "auditions"),
        "audition_candidates": [
            {"id": "candidate-one", "backend": "mock", "length_scale": 0.92},
            {"id": "candidate-two", "backend": "mock", "length_scale": 0.88},
            {"id": "candidate-three", "backend": "mock", "length_scale": 0.97},
        ],
    }
    store = make_store(tmp_path)
    backend = MockTtsBackend("elaria-test")
    speech = SpeechService(config, store, backend=backend)

    assert speech.play_ack("on_it")["cache_miss"] is True
    warmed = speech.warm_ack_cache()
    assert set(warmed) == set(STANDARD_ACKS)
    assert all(Path(item["audio_path"]).exists() for item in warmed.values())
    assert backend.calls == list(STANDARD_ACKS.values())

    manifest = speech.generate_auditions()
    assert [c["status"] for c in manifest["candidates"]] == ["ready"] * 3
    assert all(Path(c["audio_path"]).exists() for c in manifest["candidates"])
    speech.select_voice("candidate-two")
    assert speech.descriptor().voice_id == "candidate-two"
    status = speech.status()
    assert status["local"] is True and status["cloud_voice"] is False
    assert status["gemini_native_audio"] is False


def test_piper_backend_uses_native_length_scale_only(tmp_path):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"model")
    seen = {}

    def runner(args, **kwargs):
        seen["args"] = args
        seen["input"] = kwargs["input"]
        Path(args[args.index("--output_file") + 1]).write_bytes(b"RIFFfake")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    descriptor = VoiceDescriptor("dry-local", str(model), length_scale=0.91)
    backend = PiperTtsBackend(descriptor, command=sys.executable, runner=runner)
    out = backend.synthesize("On it.", tmp_path / "out.wav")
    assert out.exists() and seen["input"] == "On it."
    assert "--length-scale" in seen["args"] and "0.91" in seen["args"]
    joined = " ".join(seen["args"]).lower()
    assert "atempo" not in joined and "tempo" not in joined and "stretch" not in joined


def test_live_session_disables_gemini_audio_out():
    source = (Path(__file__).parents[1] / "src/assistant/live_client.py").read_text()
    assert "Modality.TEXT" in source
    assert "Modality.AUDIO" not in source


def test_online_and_offline_ask_route_to_same_tts_voice(config, running_daemon):
    from assistant.ipc import call

    daemon, _server = running_daemon
    config.raw["tts"] = {**config.raw["tts"], "player": "none",
                         "cache_dir": str(config.data_dir / "voice-cache-test")}
    backend = MockTtsBackend("one-elaria-voice")
    daemon.speech = SpeechService(config, daemon.store, backend=backend)

    online = call(config.socket_path, "ask", {"text": "status", "speak": True}, timeout=20)
    assert online["connectivity"]["effective_mode"] == ONLINE
    assert online["speech"]["backend"] == "mock-local"
    assert online["speech"]["voice_id"] == "one-elaria-voice"

    call(config.socket_path, "mode.set", {"mode": "offline"}, timeout=10)
    offline = call(config.socket_path, "ask", {"text": "status", "speak": True}, timeout=20)
    assert offline["connectivity"]["effective_mode"] == FORCED_OFFLINE
    assert offline["speech"]["backend"] == online["speech"]["backend"]
    assert offline["speech"]["voice_id"] == online["speech"]["voice_id"]
    assert backend.calls == [online["reply"], offline["reply"]]


# -- queue ------------------------------------------------------------------------------

def test_reconnect_drain_completes_auto_work_but_gates_external(config, tmp_path):
    store = make_store(tmp_path)
    transport = TextTransport()
    client = GeminiClient(config, store, transport=transport, sleep=lambda _: None)
    manager = ModeManager(config, store, probe=Probe(True))
    queue = CloudQueue(config, store, client, manager)

    rate = 16000
    audio = write_wav(tmp_path / "offline.wav", [struct.pack("<h", 7000) * 8000], rate)
    from datetime import datetime

    inbox = write_inbox_note(
        tmp_path / "inbox", when=datetime.now().astimezone(),
        raw="rough offline transcript", cleaned=None, backend="local",
        language="en", audio_path=str(audio), flagged=False, session_id="abc123")
    transcript_id = store.log_transcript(
        ts="2026-10-19T00:00:00+00:00", session_id="abc123", audio_path=str(audio),
        raw_text="rough offline transcript", cleaned_text=None, language="en",
        backend="local", model="small", duration_s=1.0, flagged=0, confidence=0.2,
        cloud_status="pending_cloud_transcription", inbox_path=str(inbox))
    conversation_id = store.get_or_create_conversation("2026-10-19T00:00:00+00:00")
    queue.enqueue_transcription(transcript_id, str(audio), "en")
    queue.enqueue_cleanup(transcript_id)
    queue.enqueue_chat("what should I price this at?", "what should I price this at?",
                       conversation_id)
    external_id = queue.enqueue_external("download", "fetch a large model")

    result = queue.drain()
    assert result["done"] == 3 and result["failed"] == 0
    row = store.get_transcript(transcript_id)
    assert row["raw_text"] == "cloud transcript done properly for the full saved recording"
    assert row["offline_text"] == "rough offline transcript"
    assert row["cloud_status"] == "cloud_complete"
    assert row["cleaned_text"] == "Cloud transcript done properly for the full saved recording."
    assert "Cloud re-transcription" in inbox.read_text()
    assert store.get_cloud_job(external_id)["status"] == "awaiting_approval"
    assert any(m["text"] == "queued chat answer" for m in store.recent_messages())

    queue.approve(external_id)
    approved = queue.drain()
    external = next(j for j in approved["jobs"] if j["id"] == external_id)
    assert external["result"]["approved"] is True
    assert external["result"]["executed"] is False  # approval is not a downloader


def test_drain_network_failure_leaves_job_pending(config, tmp_path):
    store = make_store(tmp_path)

    class DropTransport:
        def generate(self, model, contents, cfg):
            raise ConnectionError("Network is unreachable")

    client = GeminiClient(config, store, transport=DropTransport(), sleep=lambda _: None)
    manager = ModeManager(config, store, probe=Probe(True))
    queue = CloudQueue(config, store, client, manager)
    job_id = queue.enqueue_chat("hello", "hello")
    result = queue.drain()
    assert result["network_stopped"] is True
    assert store.get_cloud_job(job_id)["status"] == "pending"
    assert manager.status(refresh=False).effective_mode == OFFLINE


# -- daemon forced offline / parked switch ------------------------------------------------

def test_mode_switch_is_parked_until_dictation_finishes(config, running_daemon):
    from assistant.ipc import call

    called = call(config.socket_path, "ptt.start", {"source": "simulated"}, timeout=10)
    assert called["connectivity"]["effective_mode"] == ONLINE
    time.sleep(0.25)
    parked = call(config.socket_path, "mode.set", {"mode": "offline"}, timeout=10)
    assert parked["connectivity"]["switch_parked"] is True
    assert parked["connectivity"]["effective_mode"] == ONLINE
    stopped = call(config.socket_path, "ptt.stop", timeout=90)
    assert stopped["result"]["text"]
    assert stopped["connectivity"]["effective_mode"] == FORCED_OFFLINE


def test_forced_offline_daemon_paths_make_zero_gemini_calls(config, tmp_path, running_daemon):
    from assistant.ipc import call

    daemon, _server = running_daemon
    exploding = ExplodingTransport()
    daemon.client._transport = exploding
    daemon.organiser.client = daemon.client
    daemon.cloud_queue.client = daemon.client

    def forbidden_probe():
        raise AssertionError("health probe called while forced offline")

    daemon.mode_manager._probe = forbidden_probe
    daemon.dictation.local_backend = ScriptedLocal("status", 0.3)
    config.raw["tts"] = {**config.raw["tts"], "player": "none"}
    daemon.speech = SpeechService(config, daemon.store,
                                  backend=MockTtsBackend("local-only"))

    # A tiny local root proves Tier 0 + parked Tier 1/2 without cloud.
    root = tmp_path / "root"
    root.mkdir()
    (root / "invoice-march.txt").write_text("invoice")
    config.raw["organise"] = {**config.raw["organise"], "roots": [
        {"path": str(root), "mode": "shadow", "taxonomy": ["Finance"]}]}
    daemon.config = config
    daemon.organiser.config = config

    mode = call(config.socket_path, "mode.set", {"mode": "offline"}, timeout=10)
    assert mode["connectivity"]["effective_mode"] == FORCED_OFFLINE
    status = call(config.socket_path, "status", timeout=10)
    assert status["connectivity_mode"] == FORCED_OFFLINE
    assert status["voice"]["local"] is True

    local_reply = call(config.socket_path, "ask", {"text": "remember that tea is at four"},
                       timeout=20)
    assert local_reply["via"] == "local-intent"
    open_reply = call(config.socket_path, "ask",
                      {"text": "give me nuanced advice on pricing this work"}, timeout=20)
    assert open_reply["via"] == "local-queue" and open_reply["queued_job_id"]

    started = call(config.socket_path, "plan.build", {"tiers": True}, timeout=15)
    assert started["started"][0]["tiers"] == "queued-offline"
    plan_id = started["started"][0]["plan_id"]
    deadline = time.time() + 20
    while time.time() < deadline:
        shown = call(config.socket_path, "plan.show", {"plan_id": plan_id}, timeout=10)
        if shown["plan"]["status"] != "building":
            break
        time.sleep(0.2)
    assert shown["plan"]["status"] == "ready"

    started_ptt = call(config.socket_path, "ptt.start",
                       {"source": "simulated", "mode": "command"}, timeout=10)
    assert started_ptt["connectivity"]["effective_mode"] == FORCED_OFFLINE
    time.sleep(0.3)
    stopped = call(config.socket_path, "ptt.stop", {"speak": True}, timeout=90)
    assert stopped["result"]["backend"] == "local"
    assert stopped["result"]["cloud_status"] == "pending_cloud_transcription"
    assert stopped["result"]["command"]["via"] == "local-intent"

    kinds = [j["kind"] for j in daemon.cloud_queue.list_jobs(limit=50)]
    assert {"chat", "plan_tiers", "cloud_transcription"}.issubset(kinds)
    assert exploding.calls == 0


# -- surfaces / CLI ------------------------------------------------------------------------

def test_waybar_shows_forced_offline_and_css_exists():
    rendered = format_waybar({
        "running": True, "mode": "idle", "gemini_mode": "live", "uptime_s": 9,
        "connectivity_mode": FORCED_OFFLINE,
        "connectivity": {"preference": "offline"},
        "cloud_queue": {"pending": 2},
        "voice": {"backend": "piper", "voice_id": "one-voice"},
    })
    assert "forced offline" in rendered["text"]
    assert "forced-offline" in rendered["class"]
    assert "connectivity: forced offline" in rendered["tooltip"]
    css = (Path(__file__).parents[1] / "ui/waybar/style.css").read_text()
    assert "#custom-elaria.offline" in css and "#custom-elaria.forced-offline" in css


def test_cli_mode_queue_and_voice_local_fallbacks():
    repo = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(repo / "src")}

    def cli(*args):
        return subprocess.run([sys.executable, "-m", "assistant.cli", *args],
                              check=False, capture_output=True, text=True,
                              env=env, timeout=60)

    offline = cli("mode", "offline")
    assert offline.returncode == 0 and FORCED_OFFLINE in offline.stdout
    external = cli("queue", "add-external", "download", "fetch a model")
    assert external.returncode == 0 and "awaiting_approval" in external.stdout
    listed = cli("queue", "list")
    assert listed.returncode == 0 and "external_action" in listed.stdout
    voice = cli("voice", "status")
    assert voice.returncode == 0 and "cloud_voice" in voice.stdout


def test_doctor_reports_phase8_surfaces(config):
    from assistant.cli import run_doctor

    report = run_doctor(config)
    checks = {c["check"]: c for c in report["checks"]}
    assert "connectivity mode" in checks
    assert "one local voice" in checks
    assert "offline ASR" in checks
    assert "Gemini native audio is disabled" in checks["one local voice"]["detail"]
