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


# ------------------------------------------------- G.7.1 accumulation
class _BlockingSession(_RecordingSession):
    """A live session that stays open after the script (receive() parks)
    — the geometry where the debounce gap is the commit trigger."""

    async def receive(self):
        while self._messages:
            yield self._messages.pop(0)
        await asyncio.Event().wait()


def _run_blocking(messages, drive):
    transport = _transport()
    session = _BlockingSession(messages)
    transport._session = session

    async def main():
        transport._receiver = asyncio.create_task(transport._receive_loop())
        try:
            return await drive(transport)
        finally:
            transport._receiver.cancel()
            await asyncio.gather(transport._receiver, return_exceptions=True)

    return asyncio.run(main())


def _envelope(text, finished=pytypes._undefined if False else None):
    transcription = pytypes.SimpleNamespace(text=text)
    if finished is not None:
        transcription.finished = finished
    return pytypes.SimpleNamespace(
        server_content=_content(input_transcription=transcription))


def _boundary():
    return pytypes.SimpleNamespace(server_content=_content(turn_complete=True))


def test_delta_envelopes_accumulate_into_one_final():
    """The third-party shape: input_transcription deltas, finalized at the
    turn boundary — one clean final, never a space-joined garble."""
    def drive(transport):
        async def inner():
            events = await _drain(transport, 1, timeout=1.5)
            return events, transport.wire_stats()
        return inner()

    events, stats = _run_blocking(
        [_envelope("Please "), _envelope("save the user's "),
         _envelope("complete sentence."), _boundary()],
        drive)
    assert [e.type for e in events] == ["final"]
    assert events[0].text == "Please save the user's complete sentence."
    assert stats["transcript_parts"] == 3
    assert stats["transcript_commits"] == 1
    # the sentence-final piece ends the segment itself
    assert stats["transcript_commit_reasons"] == {"segment": 1}


def test_standalone_envelope_commits_on_the_debounce_gap():
    """The 6f geometry at unit level: one envelope, finished omitted,
    connection stays open — the debounce gap alone must commit."""
    def drive(transport):
        async def inner():
            events = await _drain(transport, 1, timeout=1.5)
            return events, transport.wire_stats()
        return inner()

    events, stats = _run_blocking(
        [_envelope("just words no punctuation")], drive)
    assert [e.type for e in events] == ["final"]
    assert events[0].text == "just words no punctuation"
    assert stats["transcript_commit_reasons"] == {"debounce": 1}


def test_finished_marker_commits_immediately():
    def drive(transport):
        async def inner():
            events = await _drain(transport, 1, timeout=1.5)
            return events, transport.wire_stats()
        return inner()

    events, stats = _run_blocking(
        [_envelope("Hello there", finished=True)], drive)
    assert events[0].text == "Hello there"
    assert stats["transcript_commit_reasons"] == {"finished": 1}


def test_snapshot_hypotheses_supersede_not_append():
    def drive(transport):
        async def inner():
            events = await _drain(transport, 1, timeout=1.5)
            return events, transport.wire_stats()
        return inner()

    events, stats = _run_blocking(
        [_envelope("Hel"), _envelope("Hell"), _envelope("Hello there.")],
        drive)
    assert events[0].text == "Hello there."      # newest snapshot wins
    assert stats["transcript_snapshots"] == 2
    assert stats["transcript_commits"] == 1


def test_consecutive_identical_deltas_deduped():
    def drive(transport):
        async def inner():
            events = await _drain(transport, 1, timeout=1.5)
            return events, transport.wire_stats()
        return inner()

    events, stats = _run_blocking(
        [_envelope("Hi "), _envelope("Hi "), _envelope("there."), _boundary()],
        drive)
    assert events[0].text == "Hi there."
    assert stats["transcript_dupes"] == 1


def test_control_tokens_and_control_chars_stripped():
    def drive(transport):
        async def inner():
            events = await _drain(transport, 1, timeout=1.5)
            return events, transport.wire_stats()
        return inner()

    events, stats = _run_blocking(
        [_envelope("<ctrl:0>Hel<ctrl-token:7>lo\x07 there\x1f."), _boundary()],
        drive)
    assert events[0].text == "Hello there."
    assert stats["transcript_commits"] == 1


def test_loop_exit_commits_pending_before_the_error():
    """A dead link must not eat the words: EOF commits the accumulator,
    THEN reports the failure."""
    def drive(transport):
        async def inner():
            first = await transport._queue.get()
            second = await transport._queue.get()
            return first, second, transport.wire_stats()
        return inner()

    first, second, stats = _run([_envelope("just words")], drive)
    assert first.type == "final" and first.text == "just words"
    assert second.type == "error"
    assert stats["transcript_commit_reasons"] == {"loop_exit": 1}


def test_join_rules_whitespace_raw_boundary_space():
    join = GenaiLiveTransport._join_transcript_pending
    assert join(["Hello ", "world."]) == "Hello world."     # delta whitespace
    assert join(["Hello there.", "How are you?"]) == "Hello there. How are you?"
    # pinned residual: sub-word deltas without whitespace join with a space
    assert join(["Hel", "lo"]) == "Hel lo"


def test_multi_segment_turns_commit_separately_and_join_at_flush():
    """Two documented segments (two commits) — the flush space-joins
    finals, so the spoken sentence stays intact."""
    def drive(transport):
        async def inner():
            events = await _drain(transport, 2, timeout=1.5)
            return events, transport.wire_stats()
        return inner()

    events, stats = _run_blocking(
        [_envelope("First segment.", finished=True),
         _envelope("Second segment.", finished=True)], drive)
    assert [e.text for e in events] == ["First segment.", "Second segment."]
    assert stats["transcript_commits"] == 2
    from assistant.transcribe import _final_texts
    assert " ".join(_final_texts(events)) == "First segment. Second segment."



# ------------------------------------------------------- G.7.4 reset
def test_session_open_prunes_crashed_session_transients(config):
    """A crashed session's per-session state must not survive into new
    sessions (or grow without bound). The 6d reset block already handles
    the ptt flags; the G.6 stage tables are the G.7.4 pin target."""
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    try:
        for i in range(10):
            daemon._stage(f"old-{i}", "release", float(i))
            daemon._latency_emitted.add(f"old-{i}")
        assert len(daemon._stage_marks) == 10

        async def drive():
            assert (await daemon._ptt_start({}))["listening"] is True
            return daemon._ptt_session_id

        sid = asyncio.run(drive())
        # the last 4 stage tables survive (an in-flight reply owes its
        # table) — the older crash leftovers are gone
        assert len(daemon._stage_marks) <= 4
        assert "old-0" not in daemon._stage_marks
        assert daemon._ptt_session_id == sid
        # ptt flags are the 6d contract: fresh session state
        assert daemon._ptt_released_at is None
        assert daemon._ptt_results.get(sid) is None
    finally:
        daemon.store.close()
