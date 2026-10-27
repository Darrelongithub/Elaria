"""Stream F wire sensors (scene 3b-REDO follow-up, owner order 2026-10-26).

F.1 raw-wire histogram: every WebSocket message type the Live session
receives is counted (`ws.histogram` at close); unrecognized/unparsed types
are sampled up to 3 times — text fields only, NEVER audio bytes, max
~200 chars. This is the deciding fork: zero transcript-family counts =
the audio never reached the model (or frames were never sent); transcript
deltas with no recognized final = the final arrived in a shape the parser
does not match.

F.3 audio-sent meter: `audio.sent` at close reports what we actually
pushed to the socket (chunks/bytes/format/rate) — the other half of the
fork (five seconds of speech with zero sent chunks, or sent in the wrong
format).
"""

from __future__ import annotations

import asyncio
import io
import struct
import types as pytypes

from assistant.capture import SAMPLE_RATE
from assistant.config import load_config
from assistant.journal_log import bind as bind_journal
from assistant.live_client import DuplexLiveTransport, GenaiLiveTransport
from assistant.store import Store
from assistant.transcribe import DictationService


def _events_named(journal_stream, name: str) -> list[str]:
    return [ln for ln in journal_stream.getvalue().splitlines()
            if ln.split(" ", 6)[2] == name]


class _FakeSession:
    """Captures send_realtime_input kwargs — the wire-level record."""

    def __init__(self):
        self.sent = []

    async def send_realtime_input(self, **kwargs):
        self.sent.append(kwargs)


def _transport() -> GenaiLiveTransport:
    return GenaiLiveTransport(api_key="test-key-not-used",
                              model="gemini-3.5-transcribe-live")


def _resp(**fields):
    """A LiveServerMessage-shaped object (vars()-parsed by _note_wire)."""
    return pytypes.SimpleNamespace(**fields)


# ------------------------------------------------------------------ F.1
def test_histogram_counts_every_message_type_and_field():
    tr = _transport()
    tr._note_wire(_resp(
        server_content=pytypes.SimpleNamespace(
            interim_input_transcription=pytypes.SimpleNamespace(text="he"),
            input_transcription=None,
            turn_complete=False,
        )))
    tr._note_wire(_resp(go_away=pytypes.SimpleNamespace(reason="quota")))
    stats = tr.wire_stats()
    types = stats["types"]
    assert types["message"] == 2
    assert types["server_content.interim_input_transcription"] == 1
    assert types["server_content.turn_complete"] == 1
    assert types["go_away"] == 1
    # G.2 (2026-10-27): sampling covers ALL message types now — the scene
    # dump must show the payloads themselves, parsed or not.
    joined = " ".join(stats["samples"])
    assert "server_content.interim_input_transcription:" in joined
    assert "go_away:" in joined


def test_unparsed_types_are_sampled_text_only_max_three():
    tr = _transport()
    payload = pytypes.SimpleNamespace(
        tool_call=pytypes.SimpleNamespace(
            name="weather", args={"city": "Nairobi"},
            audio=b"\x00\x01\x02\x03" * 8))
    for _ in range(5):
        tr._note_wire(_resp(tool_call=payload.tool_call))
        tr._note_wire(_resp(server_content=pytypes.SimpleNamespace(
            interrupted=pytypes.SimpleNamespace(mystery="opaque"))))
    stats = tr.wire_stats()
    assert stats["types"]["tool_call"] == 5
    assert stats["types"]["server_content.interrupted"] == 5
    samples = stats["samples"]
    # G.2: up to 3 samples PER type (was 3 globally over unparsed only).
    # H.2 (2026-10-27): "message" — the per-response total — is sampled
    # too, naming each payload's fields, so no counted type is missing
    # from samples. Same 3-per-type cap applies.
    assert len(samples) == 9, samples
    assert sum(1 for s in samples if s.startswith("tool_call: ")) == 3
    assert sum(1 for s in samples
               if s.startswith("server_content.interrupted: ")) == 3
    assert sum(1 for s in samples if s.startswith("message: ")) == 3
    assert all(len(s) <= 220 for s in samples)
    joined = " ".join(samples)
    assert "weather" in joined and "Nairobi" in joined   # text fields kept
    assert "\\x00" not in joined and "b'" not in joined  # NEVER audio bytes


def test_model_dump_responses_count_too():
    class _Model:
        def model_dump(self, exclude_none=True):
            return {"serverContent": None,
                    "server_content": {"input_transcription": {"text": "hi"}}}

    tr = _transport()
    tr._note_wire(_Model())
    assert tr.wire_stats()["types"]["server_content.input_transcription"] == 1


# ------------------------------------------------------------------ F.3
def test_send_audio_coalesces_to_documented_100ms_chunks():
    """Capture yields 30ms frames; the documented wire chunk is 100ms
    (1,024-2,048 frames). 10 x 480-sample frames = 3 x 1,600-sample chunks."""
    tr = _transport()
    session = _FakeSession()
    tr._session = session
    frame = b"\x01\x00" * 480            # 30 ms of s16le mono @ 16 kHz

    async def drive():
        await tr.activity_start()
        for _ in range(10):
            await tr.send_audio(frame)
        await tr.activity_end()

    asyncio.run(drive())
    sent = tr.wire_stats()["audio_sent"]
    assert sent["chunks"] == 3
    assert sent["bytes"] == 10 * len(frame)
    assert sent["format"] == "audio/pcm"
    assert sent["rate"] == 16000
    assert sent["chunk_frames_max"] == 1600
    assert tr.wire_stats()["signals"] == {"activity_start": 1, "activity_end": 1}
    # the wire shapes themselves (google-genai converter targets)
    assert "activity_start" in session.sent[0]
    assert "activity_end" in session.sent[-1]
    for call in session.sent[1:-1]:
        assert len(call["audio"].data) == 3200, "100ms = 1,600 samples = 3,200 bytes"
        assert call["audio"].mime_type == "audio/pcm;rate=16000"


def test_activity_end_flushes_tail_before_activity_end():
    """The final partial chunk must not be lost (fail loud: audio never
    lost) and must precede ActivityEnd on the wire."""
    tr = _transport()
    session = _FakeSession()
    tr._session = session
    frame = b"\x01\x00" * 480            # 5 frames = 2,400 samples = 4,800 B

    async def drive():
        await tr.activity_start()
        for _ in range(5):
            await tr.send_audio(frame)
        await tr.activity_end()

    asyncio.run(drive())
    kinds = ["activity_start" if "activity_start" in call else
             "activity_end" if "activity_end" in call else "audio"
             for call in session.sent]
    assert kinds == ["activity_start", "audio", "audio", "activity_end"]
    sizes = [len(call["audio"].data) for call in session.sent[1:-1]]
    assert sizes == [3200, 1600]         # full chunk + flushed tail
    sent = tr.wire_stats()["audio_sent"]
    assert sent["chunks"] == 2
    assert sent["bytes"] == 4800


def test_duplex_forwards_wire_stats():
    class _Inner:
        name = "fake"

        def wire_stats(self):
            return {"types": {"message": 7}}

    stats = DuplexLiveTransport(_Inner()).wire_stats()
    assert stats == {"types": {"message": 7}}


# ------------------------------------------------- close-line emission
def test_flush_emits_ws_histogram_and_audio_sent(tmp_path, monkeypatch):
    from assistant.live_client import LiveEvent, ScriptedLiveTransport

    class _WireTransport(ScriptedLiveTransport):
        async def activity_end(self) -> None:
            await self._queue.put(LiveEvent("final", text="Four."))
            await self._queue.put(LiveEvent("turn_complete"))

        def wire_stats(self):
            return {
                "types": {"message": 9,
                          "server_content.input_transcription": 2},
                "samples": ["tool_call: get the weather"],
                "audio_sent": {"chunks": 20, "bytes": 19200,
                               "format": "audio/pcm", "rate": 16000,
                               "mime": "audio/pcm;rate=16000",
                               "chunk_frames_max": 480},
                "signals": {"activity_start": 1, "activity_end": 1},
            }

    journal = io.StringIO()
    bind_journal(journal)
    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {
        **config.raw.get("transcribe", {}),
        "inbox_dir": str(tmp_path / "inbox"),
        "final_wait_s": 0.5,
    }
    store = Store(tmp_path / "wire.db")
    service = DictationService(config, store, None)

    frame_samples = SAMPLE_RATE * 30 // 1000
    frame = struct.pack(f"<{frame_samples}h", *([6000] * frame_samples))
    source_frames = [frame] * 20

    class _Source:
        async def frames(self):
            for f in source_frames:
                yield f

        async def aclose(self):
            return None

    result = asyncio.run(service.dictate(
        _Source(), transport_factory=_WireTransport, mode="narration"))
    assert "Four." in (result.raw_text or "")

    hist = _events_named(journal, "ws.histogram")
    assert hist, journal.getvalue()
    assert "types=" in hist[0]
    assert '"server_content.input_transcription": 2' in hist[0]
    assert "samples=" in hist[0] and "tool_call" in hist[0]
    sent = _events_named(journal, "audio.sent")
    assert sent, journal.getvalue()
    assert "chunks=20 bytes=19200 format=audio/pcm rate=16000" in sent[0]
    store.close()
