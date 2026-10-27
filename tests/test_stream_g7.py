"""Stream G.7 (2026-10-27): pre-scene guard + audit triage.

G.7.1 — transcript-shape sensors first (this commit) and delta
accumulation second. The third-party audit (CODE-READ, ideas only)
reports input_transcription as client-side DELTAS finalized at
turn_complete; the transcribe-live docs describe one finalized envelope
per speech turn; the SDK `Transcription` type carries `finished`
("indicates the end of the transcription") so multi-message shapes are
type-legal. The sensors make the actual shape visible at scene 6:
wire delivers N parts, we commit M finals — N > M means accumulation
happened (delta shape), N == M means one-shot segments.
"""

from __future__ import annotations

import asyncio
import types as pytypes

from assistant.live_client import GenaiLiveTransport


def _transport(model: str = "gemini-3.5-transcribe-live") -> GenaiLiveTransport:
    return GenaiLiveTransport(api_key="test-key-not-used", model=model)


def _content(**fields):
    return pytypes.SimpleNamespace(**fields)


class _RecordingSession:
    """Minimal queue-backed session: receive() yields scripted messages."""

    def __init__(self, messages):
        self._messages = list(messages)
        self.queue = asyncio.Queue()
        self.sent = []

    async def send_realtime_input(self, **kwargs):
        self.sent.append(kwargs)

    async def receive(self):
        while self._messages:
            yield self._messages.pop(0)


def _run(messages, drive):
    transport = _transport()
    session = _RecordingSession(messages)
    transport._session = session

    async def main():
        transport._receiver = asyncio.create_task(transport._receive_loop())
        try:
            return await drive(transport)
        finally:
            transport._receiver.cancel()
            await asyncio.gather(transport._receiver, return_exceptions=True)

    return asyncio.run(main())


async def _drain(transport, n, timeout=1.0):
    events = []

    async def pull():
        while len(events) < n:
            events.append(await transport._queue.get())

    await asyncio.wait_for(pull(), timeout=timeout)
    return events


# ------------------------------------------------------- G.7.1 sensors
def test_shape_counters_count_parts_and_commits_one_to_one_today():
    """Before the accumulation fix each envelope commits exactly one
    final (the 6f contract) — parts == commits is the one-shot shape."""
    def drive(transport):
        async def inner():
            events = await _drain(transport, 1)
            stats = transport.wire_stats()
            return events, stats
        return inner()

    events, stats = _run(
        [pytypes.SimpleNamespace(server_content=_content(
            input_transcription=pytypes.SimpleNamespace(text="Hello there.")))],
        drive)
    assert [e.type for e in events] == ["final"]
    assert stats["transcript_parts"] == 1
    assert stats["transcript_commits"] == 1
    assert stats["transcript_dupes"] == 0
    assert stats["transcript_snapshots"] == 0


def test_shape_counters_ride_the_histogram_line():
    from assistant.transcribe import DictationService  # noqa: F401  (shape pin)
    # the emission detail is built in transcribe.py; pin the wire_stats
    # keys it reads so the line cannot silently lose the shape numbers.
    stats = _transport().wire_stats()
    for key in ("transcript_parts", "transcript_commits",
                "transcript_dupes", "transcript_snapshots"):
        assert key in stats, key
