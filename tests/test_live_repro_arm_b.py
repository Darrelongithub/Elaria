"""W2 arm tests (scene-7 work order, 2026-10-31).

Arm B is rebuilt from the conversational docs example (capabilities
guide "Audio transcriptions" input shape: response_modalities AUDIO +
input_audio_transcription side-channel). Pins: the docs config shape
reaches connect() verbatim, the SPOKE/SILENT verdicts, safe sends on a
closed socket (no traceback — the old arm B crashed), and the summary
counter fix (voice_activity counted from every location — the old
counter reported 0 while dumping two voice-activity messages).
"""

from __future__ import annotations

import asyncio
import importlib.util
import wave
from pathlib import Path
from types import SimpleNamespace as NS

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "live_repro.py"
_spec = importlib.util.spec_from_file_location("live_repro", _SCRIPT)
repro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repro)


def _write_wav(path: Path, frames: int = 1600 * 4) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x01\x00" * frames)
    return path


class FakeSession:
    def __init__(self, messages, *, refuse_after=None):
        self.sent = []
        self._messages = list(messages)
        self._refuse_after = refuse_after

    async def send_realtime_input(self, **kwargs):
        if (self._refuse_after is not None
                and len(self.sent) >= self._refuse_after):
            raise RuntimeError("connection closed (WS 1007)")
        self.sent.append(kwargs)

    async def receive(self):
        for message in self._messages:
            yield message


def _factory(session, captured):
    class _Live:
        def connect(self, *, model, config):
            captured["model"] = model
            captured["config"] = config
            return _CM(session)

    class _CM:
        def __init__(self, sess):
            self._sess = sess

        async def __aenter__(self):
            return self._sess

        async def __aexit__(self, *exc):
            return False

    class _Aio:
        live = _Live()

    class _Client:
        aio = _Aio()

    return lambda: _Client()


def _run(arm, tmp_path, messages, **session_kwargs):
    wav = _write_wav(tmp_path / "kept.wav")
    session = FakeSession(messages, **session_kwargs)
    captured = {}
    rc = asyncio.run(repro._run(
        arm, repro.ARM_MODELS[arm], str(wav), 0.01, "burst",
        client_factory=_factory(session, captured)))
    return rc, session, captured


# ------------------------------------------------- arm B, the docs shape
def test_arm_b_connects_with_the_docs_config_verbatim(tmp_path, capsys):
    rc, session, captured = _run("B", tmp_path, [])
    out = capsys.readouterr().out
    assert rc == 0
    assert captured["model"] == "gemini-3.8-live"
    assert captured["config"] == {"response_modalities": ["AUDIO"],
                                  "input_audio_transcription": {}}, \
        "arm B must carry the conversational modality shape, not TEXT"
    assert session.sent, "the wav must be streamed"
    assert "ARM B VERDICT: SILENT" in out


def test_arm_b_spoke_reads_the_side_channel(tmp_path, capsys):
    messages = [
        NS(server_content=NS(input_transcription=NS(text="hello there"))),
        NS(server_content=NS(interim_input_transcription=NS(text="hel"))),
    ]
    rc, _session, _captured = _run("B", tmp_path, messages)
    out = capsys.readouterr().out
    assert rc == 0
    assert "ARM B VERDICT: SPOKE" in out
    assert "'hello there'" in out
    assert "input_final: 1" in out
    assert "interim: 1" in out


def test_arm_b_silent_means_connected_and_acked_with_zero_text(tmp_path,
                                                              capsys):
    messages = [NS(server_content=NS(turn_complete=True))]
    rc, _session, _captured = _run("B", tmp_path, messages)
    out = capsys.readouterr().out
    assert rc == 0
    assert "ARM B VERDICT: SILENT" in out
    assert "audio_acked: True" in out


# ------------------------------------------------- robustness + counters
def test_send_after_closed_socket_is_a_result_not_a_traceback(tmp_path,
                                                              capsys):
    rc, session, _captured = _run("B", tmp_path, [],
                                  refuse_after=2)
    out = capsys.readouterr().out
    assert rc == 0, "a refused send must not crash the run"
    assert len(session.sent) == 2
    assert "send refused" in out
    assert "ARM B VERDICT: NO-RUN" in out
    assert "Traceback" not in out


def test_connect_failure_completes_and_reports_no_run(tmp_path, capsys):
    class _Exploding:
        def connect(self, *, model, config):
            raise RuntimeError("WS 1007 response modalities not supported")

    class _Aio:
        live = _Exploding()

    class _Client:
        aio = _Aio()

    wav = _write_wav(tmp_path / "kept.wav")
    rc = asyncio.run(repro._run(
        "B", "gemini-3.8-live", str(wav), 0.01, "burst",
        client_factory=lambda: _Client()))
    out = capsys.readouterr().out
    assert rc == 0
    assert "ARM B VERDICT: NO-RUN" in out
    assert "WS 1007" in out
    assert "Traceback" not in out


def test_voice_activity_counted_from_every_location(tmp_path, capsys):
    """The counter-bug regression pin: two voice-activity messages at two
    different attribute locations must count 2, never 0."""
    messages = [
        NS(voice_activity=NS()),                          # message-level
        NS(server_content=NS(activity_start=NS())),       # content-level
    ]
    rc, _session, _captured = _run("B", tmp_path, messages)
    out = capsys.readouterr().out
    assert rc == 0
    assert "voice_activity: 2" in out, \
        "the summary must count what the dump shows (was 0 while 2 dumped)"


def test_arm_a_summary_and_verdict_use_the_fixed_counters(tmp_path, capsys):
    messages = [
        NS(server_content=NS(input_transcription=NS(text="the words"))),
        NS(server_content=NS(interim_input_transcription=NS(text="the"))),
        NS(voice_activity=NS()),
        NS(server_content=NS(turn_complete=True)),
    ]
    rc, session, captured = _run("A", tmp_path, messages)
    out = capsys.readouterr().out
    assert rc == 0
    assert captured["config"] != {"response_modalities": ["AUDIO"]}, \
        "arm A keeps its own Manual-VAD transcription-model shape"
    assert "input_final: 1" in out
    assert "voice_activity: 1" in out
    assert "turn_complete: 1" in out
    assert "VERDICT (i): ARM A spoke" in out
    kinds = [next(iter(k)) for k in session.sent]
    assert "activity_start" in kinds and "activity_end" in kinds
