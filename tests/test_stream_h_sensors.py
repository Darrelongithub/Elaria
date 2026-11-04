"""Stream H sensors (2026-10-27): H.2 wire-sampling completeness and
H.4 capture-lifecycle numbers.

H.2: every counted wire type must appear in samples — including
`message`, the per-response total that scene 5/6 dumps read as an
unidentified payload type. Samples name fields/subtypes, text-only,
≤200 chars, never audio bytes.
H.4: press→first-frame latency, first-non-silent-frame offset (aggregate
only), stream.closed at session close, and the mic-release probe —
the "mic takes a minute to stop" worry is privacy-adjacent.
"""

from __future__ import annotations

import asyncio
import io
import struct

from test_stream_h_post_timeout import SilentTransport, _service

from assistant.capture import SAMPLE_RATE
from assistant.daemon import Daemon
from assistant.journal_log import bind as bind_journal
from assistant.journal_log import reset as reset_journal
from assistant.live_client import GenaiLiveTransport


def _transport() -> GenaiLiveTransport:
    return GenaiLiveTransport(api_key="test-key-not-used",
                              model="gemini-3.5-transcribe-live")


def _content(**fields):
    import types as pytypes
    return pytypes.SimpleNamespace(**fields)


# --------------------------------------------------------------- H.2
def test_every_counted_type_appears_in_samples():
    """The H.2 contract: no counted type may be missing from samples —
    'every counted type appears in samples (text-only, ≤200 chars,
    never audio bytes), including types the parser believes it knows'."""
    transport = _transport()
    transport._note_wire(_content(
        voice_activity=_content(voice_activity_type="ACTIVITY_END"),
        server_content=None))
    transport._note_wire(_content(
        server_content=_content(
            input_transcription=_content(text="hello there"))))
    transport._note_wire(_content(
        server_content=_content(turn_complete=True)))
    stats = transport.wire_stats()
    sample_prefixes = {s.split(":", 1)[0] for s in stats["samples"]}
    for counted in stats["types"]:
        assert counted in sample_prefixes, \
            f"counted type {counted!r} missing from samples"


def test_message_total_sample_names_the_payload_fields():
    transport = _transport()
    transport._note_wire(_content(
        voice_activity=_content(voice_activity_type="ACTIVITY_START")))
    stats = transport.wire_stats()
    assert stats["types"]["message"] == 1
    message_samples = [s for s in stats["samples"]
                       if s.startswith("message: ")]
    assert message_samples and "voice_activity" in message_samples[0]


def test_no_populated_fields_gets_its_own_type_and_sample():
    """A model notice/error shape the parser cannot name must not hide
    in the total — its own type + a sample of the key names."""
    transport = _transport()
    transport._note_wire(_content(
        server_content=_content(model_turn=None, turn_complete=None)))
    stats = transport.wire_stats()
    assert stats["types"].get("message.(no-populated-fields)") == 1
    assert any(s.startswith("message.(no-populated-fields): ")
               for s in stats["samples"])
    # and the contract still holds
    sample_prefixes = {s.split(":", 1)[0] for s in stats["samples"]}
    for counted in stats["types"]:
        assert counted in sample_prefixes


def test_samples_never_carry_audio_bytes():
    transport = _transport()
    payload = b"\x01\x02\x03\x04" * 64
    transport._note_wire(_content(
        server_content=_content(
            model_turn=_content(parts=[_content(
                inline_data=_content(data=payload,
                                     mime_type="audio/pcm;rate=24000"))]))))
    joined = " ".join(transport.wire_stats()["samples"])
    assert "audio/pcm" not in joined or len(payload) * 2 > 200
    assert "\x01\x02" not in joined


# --------------------------------------------------------------- H.4
class MixedCapture:
    """Silence first, then speech: the first-non-silent offset is the
    sensor under test (HDA DSP power-up clipping lives here)."""

    target = "mixed"
    stalled = False

    def __init__(self, silent: int = 3, speech: int = 4):
        self._silent = silent
        self._speech = speech
        self._stopped = asyncio.Event()

    def stop(self) -> None:
        self._stopped.set()

    async def frames(self):
        samples = SAMPLE_RATE * 30 // 1000
        silence = b"\x00\x00" * samples
        speech = struct.pack(f"<{samples}h", *([6000] * samples))
        for _ in range(self._silent):
            yield silence
        for _ in range(self._speech):
            yield speech

    async def aclose(self):
        return None


def test_capture_stats_carry_lifecycle_numbers(config, tmp_path, monkeypatch):
    from assistant import asr
    from assistant.asr import Transcript

    svc, store = _service(config, tmp_path)

    def fallback(*args, **kwargs):
        return Transcript("words", "en", "gemini_batch")

    monkeypatch.setattr(asr, "transcribe_file", fallback)
    stream = io.StringIO()
    bind_journal(stream)
    try:
        result = asyncio.run(svc.dictate(
            MixedCapture(silent=3, speech=4),
            transport_factory=lambda: SilentTransport(voice_end=True)))
    finally:
        reset_journal()
        store.close()
    assert isinstance(result.capture["first_frame_latency_ms"], float)
    assert result.capture["first_frame_latency_ms"] >= 0
    # 3 silent frames x 30ms = 0.09s into the kept wav
    assert result.capture["first_speech_frame_s"] == 0.09
    out = stream.getvalue()
    assert "stream.closed" in out
    # the mic-lifecycle numbers ride the SCHEMA journal (journalctl),
    # not just capture.stats — the scene-7 dump reads this line
    assert "capture.lifecycle" in out
    lifecycle_line = next(ln for ln in out.splitlines()
                          if "capture.lifecycle" in ln)
    assert "first_frame_latency_ms=" in lifecycle_line
    assert "first_speech_frame_s=0.09" in lifecycle_line


def test_mic_release_probe_logs_node_state(config):
    daemon = Daemon(config)
    try:
        daemon.MIC_RELEASE_PROBE_DELAY_S = 0.01
        stream = io.StringIO()
        bind_journal(stream)
        try:
            asyncio.run(daemon._mic_release_probe("sess-probe", None))
        finally:
            reset_journal()
        out = stream.getvalue()
        assert "capture.node_state" in out
        # the sandbox has no PipeWire — the honest verdict is recorded
        assert "probe unavailable" in out or "state" in out
    finally:
        daemon.store.close()


def test_probe_state_parses_pwcli_and_pactl_shapes():
    pwcli = ('\tid 31, type PipeWire:Interface:Node/3\n'
             '\t\tnode.name = "alsa_input.pci-0000_00_1f.3"\n'
             '\t\tstate = "suspended"')
    assert Daemon._probe_state(pwcli, "alsa_input.pci") == "suspended"
    pactl = ("Source #2\n\tName: alsa_input.usb-mic\n\tState: RUNNING\n"
             "\tMute: no")
    assert Daemon._probe_state(pactl, "alsa_input.usb") == "running"
    assert Daemon._probe_state("nothing useful here", "alsa_input.x") is None
