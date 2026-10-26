"""WP0 EYES: the §4.8 stdout log schema — [TESTED-ONLY], no hardware.

Schema: `ts level event session_id peak verdict detail`, plain words.
The conftest `journal_stream` fixture captures the lines per test.
"""

from __future__ import annotations

import asyncio

from assistant import journal_log
from assistant.capture import SimulatedCapture
from assistant.daemon import Daemon
from assistant.gemini_client import GeminiClient, QuotaExhausted
from assistant.store import Store


def _line_parts(line: str) -> list[str]:
    return line.split(" ", 6)


def test_schema_line_shape(journal_stream):
    line = journal_log.log_event(
        "session.open", session_id="abc123", peak=0.86,
        verdict="listening", detail="narration session open")
    parts = _line_parts(line)
    assert len(parts) == 7
    ts, level, event, session_id, peak, verdict, detail = parts
    assert level == "info"
    assert event == "session.open"
    assert session_id == "abc123"
    assert peak == "0.86"
    assert verdict == "listening"
    assert detail.startswith("narration session open")
    assert "T" in ts  # ISO-8601
    assert journal_stream.getvalue().endswith(line + "\n")


def test_empty_fields_stay_positional(journal_stream):
    line = journal_log.log_event("tts.failed", level="error",
                                 detail="synthesis failed — reported silence")
    parts = _line_parts(line)
    assert parts[1] == "error"
    assert parts[3] == "-"
    assert parts[4] == "-"
    assert parts[5] == "-"


def test_log_event_never_raises_on_a_broken_stream():
    class Broken:
        def write(self, _text):
            raise OSError("pipe gone")

        def flush(self):
            raise OSError("pipe gone")

    line = journal_log.log_event("quota.counter", stream=Broken())
    assert "quota.counter" in line


def test_detail_whitespace_is_flattened(journal_stream):
    line = journal_log.log_event("session.close", detail="a\nb\tc")
    assert "\n" not in line
    assert "a b c" in line


# -- the daemon's session lifecycle lines ---------------------------------

class _QuietPW(SimulatedCapture):
    def __init__(self, target=None, frame_ms=30, stall_timeout_s=None, **kwargs):
        super().__init__(speech_frames=0, frame_ms=frame_ms, realtime=False)


def _daemon(config):
    daemon = Daemon(config)
    return daemon


def test_ptt_session_emits_open_and_close_lines(config, journal_stream, monkeypatch):
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _QuietPW)
    daemon = _daemon(config)
    try:
        async def drive():
            started = await daemon._ptt_start({})
            assert started["listening"] is True
            await daemon._ptt_stop({"wait_s": 20.0})

        asyncio.run(drive())
    finally:
        daemon.store.close()
    text = journal_stream.getvalue()
    open_lines = [l for l in text.splitlines() if " session.open " in l]
    close_lines = [l for l in text.splitlines() if " session.close " in l]
    assert open_lines, text
    assert close_lines, text
    assert "listening" in open_lines[0]
    started_sid_open = open_lines[0].split(" ")[3]
    assert started_sid_open in close_lines[0]
    # the quota counter rides the session close
    assert any("quota.counter" in l and "counted" in l for l in text.splitlines())


def test_silence_verdict_line_names_the_peak(config, journal_stream, monkeypatch):
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _QuietPW)
    daemon = _daemon(config)
    try:
        async def drive():
            await daemon._ptt_start({})
            await daemon._ptt_stop({"wait_s": 20.0})

        asyncio.run(drive())
    finally:
        daemon.store.close()
    lines = [l for l in journal_stream.getvalue().splitlines()
             if "silence.verdict" in l]
    assert lines, journal_stream.getvalue()
    assert "silence" in lines[0]
    assert "she heard nothing" in lines[0]


# -- TTS lines ------------------------------------------------------------

def test_tts_cache_hit_and_synthesis_lines(config, journal_stream, tmp_path):
    from assistant.tts import MockTtsBackend, SpeechService

    config.raw.setdefault("tts", {})
    config.raw["tts"]["backend"] = "mock"
    config.raw["tts"]["online_voice"] = "local"
    config.raw["tts"]["offline_voice"] = "local"
    speech = SpeechService(config, Store(tmp_path / "t.db"),
                           backend=MockTtsBackend())
    result = speech.synthesize("warm words", dest=None, use_cache=True)
    assert result.cached is False
    assert any("tts.synthesised" in l for l in journal_stream.getvalue().splitlines())
    again = speech.synthesize("warm words", dest=None, use_cache=True)
    assert again.cached is True
    lines = journal_stream.getvalue().splitlines()
    assert any("tts.cached" in l and "cache hit" in l for l in lines)


# -- quota counter line ---------------------------------------------------

def test_quota_refusal_emits_a_counter_line(config, journal_stream, tmp_path):
    store = Store(tmp_path / "q.db")
    try:
        client = GeminiClient(config, store)
        config.raw["quota"]["models"]["flash-lite"]["rpd_cap"] = 1
        config.raw["quota"]["models"]["flash-lite"]["rpd"] = 1
        client._quota_by_family["flash-lite"] = {"model": "flash-lite", "rpm": 15,
                                                 "tpm": None, "rpd": 1,
                                                 "rpd_cap": 1}
        for i in range(1):
            store.log_llm_call(
                ts="2026-10-25T10:00:00", correlation_id=f"c{i}", role="chat",
                model="gemini-3.5-flash-lite", mode="live", tokens_in=1,
                tokens_out=1, tokens_estimated=0, audio_seconds=0, cost_usd=0.0,
                latency_ms=1, ok=1, verified=None, attempt=0, fixture_key=None,
                error=None, purpose="user_turn", is_user_turn=1)
        # ledger rows must be "today" for the counter to see them

        calls = []

        class _Store:
            def calls_since(self, since, model=None):
                calls.append((since, model))
                return 1

        client.store = _Store()
        try:
            raised = False
            try:
                client._check_daily_cap("gemini-3.5-flash-lite")
            except QuotaExhausted:
                raised = True
            assert raised
        finally:
            client.store = store
    finally:
        store.close()
    lines = [l for l in journal_stream.getvalue().splitlines()
             if "quota.counter" in l]
    assert lines and "rejected" in lines[0]
    # Scene-1 merge gate: a model outcome names its model in the line.
    assert "model_version=gemini-3.5-flash-lite" in lines[0]


# -- model_version on the press path (scene-1 merge gate) -------------------

class _SpeechSource:
    """The AsyncFrameSource shape: a few frames of synthetic speech."""

    def __init__(self, frames):
        self._frames = frames
        self.target = "fake-speech-node"
        self.stalled = False
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        self.closed = True


def test_transcription_landed_line_carries_model_version(
        config, journal_stream, tmp_path):
    # The merge gate: a press that lands a transcript produces a schema line
    # with model_version — which model served it, provable from the journal.
    import struct

    from assistant.capture import SAMPLE_RATE
    from assistant.live_client import ScriptedLiveTransport
    from assistant.transcribe import DictationService

    frame_samples = SAMPLE_RATE * 30 // 1000
    speech = struct.pack(f"<{frame_samples}h", *([6000] * frame_samples))
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {**config.raw.get("transcribe", {}),
                                "inbox_dir": str(tmp_path / "inbox")}
    store = Store(tmp_path / "mv.db")
    try:
        service = DictationService(config, store, None)
        source = _SpeechSource([speech for _ in range(40)])
        result = asyncio.run(service.dictate(
            source, transport_factory=ScriptedLiveTransport))
    finally:
        store.close()
    assert result.raw_text.strip()
    landed = [l for l in journal_stream.getvalue().splitlines()
              if "transcription.landed" in l]
    assert landed, journal_stream.getvalue()
    assert "model_version=" in landed[0], landed[0]
    assert (result.model or "unknown") in landed[0], landed[0]
