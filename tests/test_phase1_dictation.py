"""Phase 1: hotkey → mic → live transcription → inbox + clipboard (§3.5).

Everything headless: SimulatedCapture + ScriptedLiveTransport stand in
for PipeWire + Gemini Live; the REAL pipeline (rolling buffer, WAV sink,
VAD, reconnect/replay, cleanup gates, store, inbox, clipboard argv,
daemon IPC + event stream) is exercised end-to-end with no key.
"""

import asyncio
import json
import socket
import struct
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import pytest

from assistant.capture import (
    FrameGate,
    RollingAudioBuffer,
    SimulatedCapture,
    WavSink,
    frame_rms,
    wav_duration_s,
)
from assistant.cleanup import CleanupPass, divergence_pct, language_mix_preserved
from assistant.clipboard import copy_text
from assistant.fixtures import FixtureStore
from assistant.gemini_client import GeminiClient
from assistant.inbox import write_inbox_note
from assistant.live_client import FixtureLiveTransport, RecordingTransport, ScriptedLiveTransport
from assistant.store import Store
from assistant.transcribe import DictationService, SilenceLadder

REPO = Path(__file__).resolve().parents[1]
SPEECH = struct.pack("<480h", *([6000] * 480))   # 30ms @16kHz, clear energy
SILENCE = b"\x00\x00" * 480


def make_wav(path: Path, seconds: float = 1.0, amplitude: int = 6000) -> Path:
    frames = int(seconds * 16000)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(struct.pack(f"<{frames}h",
                                    *([amplitude] * frames)))
    return path


def service(config, tmp_path, client=None):
    store = Store(tmp_path / "t.db")
    return DictationService(config, store, client or GeminiClient(config, store)), store


# -- capture primitives ---------------------------------------------------------
def test_rolling_buffer_keeps_only_the_tail():
    buf = RollingAudioBuffer(seconds=1.0)  # 32000 bytes max
    for _ in range(100):
        buf.push(b"x" * 960)
    assert len(buf.tail()) <= 32000
    assert buf.seconds <= 1.0


def test_wav_sink_round_trip(tmp_path):
    sink = WavSink(tmp_path / "a.wav")
    for _ in range(33):
        sink.write(SPEECH)
    duration = sink.close()
    assert duration == pytest.approx(0.99, abs=0.02)
    assert wav_duration_s(tmp_path / "a.wav") == pytest.approx(duration)


def test_vad_gate_never_streams_silence():
    gate = FrameGate(rms_threshold=0.01, hangover_frames=2)
    assert frame_rms(SPEECH) > 0.01 and frame_rms(SILENCE) == 0.0
    assert gate.allows(SPEECH)
    assert gate.allows(SILENCE) and gate.allows(SILENCE)  # hangover
    assert not gate.allows(SILENCE)                        # dropped now
    assert gate.dropped_silent == 1


def test_silence_ladder_asks_once_per_segment():
    ladder = SilenceLadder(checkin_after_s=0.09)  # 3 silent frames
    # SILENCE HOTFIX rule 3: the check-in is a mid-conversation nudge — the
    # FIRST ask is earned by a landed utterance (sustained speech), never by
    # silence at session start. Silence-from-start closes silently instead
    # (pinned in tests/test_silence_hotfix.py).
    assert not any(ladder.observe(SILENCE, 0.03) for _ in range(10)), \
        "silence at session start produced a ladder line"
    for _ in range(int(ladder.resume_s / 0.03) + 1):   # a real utterance lands
        assert ladder.observe(SPEECH, 0.03) is False
    asks = [ladder.observe(SILENCE, 0.03) for _ in range(10)]
    assert asks.count(True) == 1  # never nagged twice (§13.8)
    # VB-5 (voice hunt): re-arming takes SUSTAINED speech, not one frame over the
    # RMS gate — a breath or a key click used to earn a second nag mid-thought.
    assert ladder.observe(SPEECH, 0.03) is False
    assert [ladder.observe(SILENCE, 0.03) for _ in range(10)].count(True) == 0, (
        "a single blip re-armed the ladder inside the same pause")
    for _ in range(int(ladder.resume_s / 0.03) + 1):   # real speech resumes
        assert ladder.observe(SPEECH, 0.03) is False
    asks2 = [ladder.observe(SILENCE, 0.03) for _ in range(4)]
    assert asks2.count(True) == 1


# -- cleanup gates (§12.5) --------------------------------------------------------
class FixedTransport:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    def generate(self, model, contents, config):
        self.calls += 1
        return {"text": self.text, "usage": {"tokens_in": 10, "tokens_out": 10}}


def _cleanup(config, tmp_path, reply):
    client = GeminiClient(config, Store(tmp_path / "t.db"),
                          transport=FixedTransport(reply), sleep=lambda _: None)
    return CleanupPass(config, client)


def test_cleanup_prompt_forbids_translation(config, tmp_path):
    from assistant.cleanup import CLEANUP_PROMPT
    assert "Do NOT translate" in CLEANUP_PROMPT
    assert "code-switched" in CLEANUP_PROMPT  # armed from day one (§12.5)


def test_cleanup_short_utterance_skips_model(config, tmp_path):
    cleanup = _cleanup(config, tmp_path, "whatever")
    result = cleanup.run("short note")
    assert result.cleaned is None and "not worth a model call" in result.reason


def test_diff_gate_flags_a_rewrite(config, tmp_path):
    raw = "please file the march invoice from kamau under finance before friday ends"
    rewrite = "Here is a helpful summary of your entirely different message about cats."
    result = _cleanup(config, tmp_path, rewrite).run(raw)
    assert result.flagged and "diff-gate" in result.reason
    assert divergence_pct(raw, rewrite) > 35


def test_language_gate_catches_vanished_codeswitching(config, tmp_path):
    raw = "sasa file that invoice alafu remind me friday, mbona downloads is chaos again"
    cleaned = "File that invoice and remind me Friday. The downloads folder is chaotic."
    # Phase 7 proportional gate: 3 raw markers (sasa/alafu/mbona) — keeping
    # 2 of 3 passes, keeping only 1 (token 'sasa') is normalisation, fails.
    assert language_mix_preserved(raw, "sasa file that invoice, alafu remind me") is True
    assert language_mix_preserved(raw, "sasa file that invoice") is False
    assert language_mix_preserved(raw, cleaned) is False
    result = _cleanup(config, tmp_path, cleaned).run(raw)
    assert result.flagged and "language gate" in result.reason


def test_cleanup_within_gates_passes(config, tmp_path):
    raw = "please file the march invoice from kamau under finance before friday"
    result = _cleanup(config, tmp_path,
                       "Please file the March invoice from Kamau under Finance before Friday.").run(raw)
    assert not result.flagged and result.cleaned and result.divergence_pct < 35


def test_mock_cleanup_without_fixture_keeps_raw_unflagged(config, tmp_path):
    # No recorded fixture => no real cleanup happened. Must not present the
    # synthetic placeholder as a flagged rewrite.
    store = Store(tmp_path / "t.db")
    cleanup = CleanupPass(config, GeminiClient(config, store))
    result = cleanup.run("please file the march invoice from kamau under finance soon")
    assert result.cleaned is None and result.flagged is False
    assert "no recorded cleanup fixture" in result.reason


# -- inbox + clipboard -------------------------------------------------------------
def test_inbox_note_keeps_raw_one_fold_away(tmp_path):
    from datetime import datetime
    path = write_inbox_note(tmp_path, when=datetime.now().astimezone(),
                            raw="raw words here", cleaned="Cleaned words here.",
                            backend="gemini_live", language="en",
                            audio_path="/audio/x.wav", flagged=False, session_id="abc123")
    text = path.read_text()
    assert "Cleaned words here." in text and "Raw transcript (the record)" in text
    assert "audio: /audio/x.wav" in text


def test_inbox_flagged_shows_raw_as_body(tmp_path):
    from datetime import datetime
    path = write_inbox_note(tmp_path, when=datetime.now().astimezone(),
                            raw="the raw truth", cleaned="a suspicious rewrite",
                            backend="gemini_live", language="en",
                            audio_path=None, flagged=True, session_id="abc123")
    body = path.read_text().split("---", 2)[-1]
    assert body.strip().startswith("the raw truth")


def test_clipboard_uses_wl_copy_only(monkeypatch):
    seen = {}

    def runner(argv, **kwargs):
        seen["argv"] = argv

    monkeypatch.setattr("assistant.clipboard.shutil.which", lambda _: "/usr/bin/wl-copy")
    result = copy_text("hello", runner=runner)
    assert result["copied"] and seen["argv"][0] == "wl-copy"
    monkeypatch.setattr("assistant.clipboard.shutil.which", lambda _: None)
    assert copy_text("hello", runner=runner)["copied"] is False  # reported, not raised


# -- dictation service end-to-end (mock live) ---------------------------------------
def test_dictation_happy_path(config, tmp_path):
    svc, store = service(config, tmp_path)
    events = []

    async def sink(event):
        events.append(event["event"])

    result = asyncio.run(svc.dictate(
        SimulatedCapture(speech_frames=40, silent_frames=3),
        transport_factory=ScriptedLiveTransport, sink=sink))
    assert result.backend == "gemini_live"
    assert "mock transcript" in result.raw_text
    assert Path(result.audio_path).exists()          # raw audio always saved
    assert Path(result.inbox_path).exists()          # note appears (§9 done-when)
    assert store.recent_transcripts(1)[0]["raw_text"] == result.raw_text
    assert events[0] == "session.started" and events[-1] == "session.ended"
    assert "transcript.interim" in events and "transcript.final" in events
    # Live session hit the cost ledger with audio seconds (§3.2/§7).
    live_rows = [r for r in store.llm_summary()["by_model"] if "transcribe-live" in r["model"]]
    assert live_rows and store.llm_summary()["audio_seconds"] > 0


def test_disconnect_replays_buffered_tail(config, tmp_path):
    svc, _store = service(config, tmp_path)
    transports = []

    def factory():
        transport = (ScriptedLiveTransport(drop_after_frames=6) if not transports
                     else ScriptedLiveTransport())
        transports.append(transport)
        return transport

    result = asyncio.run(svc.dictate(
        SimulatedCapture(speech_frames=40, silent_frames=0), transport_factory=factory))
    assert result.backend == "gemini_live" and result.raw_text
    assert len(transports) == 2  # rotated once
    # Second session received the replayed tail PLUS the remaining frames.
    assert transports[1].frames_received > 40 - 6
    assert any("replayed" in n for n in result.notes)


def test_live_failure_falls_back_to_batch(config, tmp_path):
    svc, _store = service(config, tmp_path)
    result = asyncio.run(svc.dictate(
        SimulatedCapture(speech_frames=20, silent_frames=0),
        transport_factory=lambda: ScriptedLiveTransport(fail_connect=True)))
    # §12.7: quota-shaped failure degrades to batch on the saved WAV.
    assert result.backend == "gemini_batch"
    assert result.raw_text  # mock batch fixture/synthetic still yields text
    assert Path(result.inbox_path).exists()


def test_goaway_rotates_with_resumption_handle(config, tmp_path):
    svc, _store = service(config, tmp_path)
    transports = []

    def factory():
        transport = (ScriptedLiveTransport(go_away_after_frames=8) if not transports
                     else ScriptedLiveTransport())
        transports.append(transport)
        return transport

    result = asyncio.run(svc.dictate(
        SimulatedCapture(speech_frames=40, silent_frames=0), transport_factory=factory))
    assert result.raw_text and len(transports) == 2
    assert transports[1].connected_with_handle == "mock-handle-1"


# -- live fixture sequences (§12.9) ---------------------------------------------------
def test_live_sequence_record_and_replay(config, tmp_path):
    store = FixtureStore(tmp_path / "fx")

    async def run_recording():
        recorder = RecordingTransport(ScriptedLiveTransport(), store, "demo")
        await recorder.connect()
        await recorder.activity_start()
        for _ in range(20):
            await recorder.send_audio(SPEECH)
        await recorder.activity_end()
        finals = [e.text async for e in recorder.events() if e.type == "final"]
        await recorder.close()
        return finals

    recorded = asyncio.run(run_recording())
    sequence = store.replay_sequence("demo")
    audio_entries = [m for m in sequence if m["type"] == "audio"]
    assert audio_entries and all("sha256" in m and "data" not in m
                                 for m in audio_entries)  # no raw audio in fixtures

    async def run_replay():
        transport = FixtureLiveTransport(store, "demo")
        await transport.connect()
        await transport.activity_end()
        return [e.text async for e in transport.events() if e.type == "final"]

    assert asyncio.run(run_replay()) == recorded  # exact scripted replay


# -- daemon: PTT round trip + event stream ---------------------------------------------
def test_daemon_ptt_round_trip_and_events(config):
    from assistant.daemon import Daemon
    from assistant.ipc import call, serve

    daemon = Daemon(config)
    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(serve(config.socket_path, daemon.handle))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    sock = None
    drainer = None
    try:
        received: list[dict] = []
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(8)
        sock.connect(str(config.socket_path))
        sock.sendall(b'{"id": 1, "method": "events.subscribe", "params": {}}\n')

        def drain():
            buffer = b""
            try:
                while True:
                    data = sock.recv(65536)
                    if not data:
                        return
                    buffer += data
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        if line.strip():
                            received.append(json.loads(line))
            except (TimeoutError, OSError):
                return

        drainer = threading.Thread(target=drain, daemon=True)
        drainer.start()
        time.sleep(0.2)  # subscription registered

        started = call(config.socket_path, "ptt.start", {"source": "simulated"})
        assert started["listening"] and started["network"] is False  # ack stayed local
        assert started["simulated_capture"] is True
        time.sleep(0.4)  # ~13 frames of 'speech'
        # BUG6: the release acks immediately; `wait_s` is the explicit
        # scripted opt-in that still returns the transcript in one call.
        stopped = call(config.socket_path, "ptt.stop", {"wait_s": 30.0}, timeout=30.0)
        result = stopped["result"]
        assert result["inbox_path"] and Path(result["inbox_path"]).exists()
        assert "Transcript saved" in result["narration"]  # factual, governor-made
        drainer.join(timeout=3)
        kinds = [e.get("event") for e in received if "event" in e]
        assert "session.started" in kinds and "transcript.final" in kinds
        assert "session.ended" in kinds
    finally:
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        if drainer is not None:
            drainer.join(timeout=3)

        async def _shutdown():
            server.close()
            await server.wait_closed()
            await daemon.aclose()

        asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=3)
        loop.close()


def test_cli_transcribe_file_local_fallback(tmp_path):
    import os
    wav = make_wav(tmp_path / "note.wav", seconds=1.0)
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    out = subprocess.run([sys.executable, "-m", "assistant.cli", "transcribe", str(wav)],
                         check=False, capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "inbox:" in out.stderr
    # inbox note really landed under the temp HOME from conftest
    inbox = Path(os.environ["HOME"]) / ".local/share/assistant/inbox"
    assert list(inbox.glob("*-dictation-*.md"))
