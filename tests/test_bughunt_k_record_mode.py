"""BH-K4 — GEMINI_MODE=record must record Live session sequences.

§12.9 contract: record = real API + fixtures saved. The text path honoured
it (harness), but `make_live_transport` returned the bare GenaiLiveTransport
for both live and record mode — so the documented way to capture the real
Live message sequence (the evidence needed for the hardware "no final after
activity_end" bug) produced no `seq-live.jsonl` at all.
"""

from __future__ import annotations

from assistant import asr
from assistant.live_client import RecordingTransport


class _FakeGenaiTransport:
    """Stand-in so the factory test needs no SDK, key, or network."""

    def __init__(self, api_key, model, language="en"):
        self.api_key = api_key
        self.model = model
        self.language = language


def test_record_mode_wraps_live_transport_for_sequence_capture(config, monkeypatch):
    monkeypatch.setattr(asr, "GenaiLiveTransport", _FakeGenaiTransport)
    config.gemini_mode = "record"
    transport = asr.make_live_transport(config)
    assert isinstance(transport, RecordingTransport), (
        "record mode must wrap the real transport so the session sequence "
        "is saved as a fixture on close")
    assert isinstance(transport._inner, _FakeGenaiTransport)
    assert transport._name == "live"
    assert transport._store.directory == config.fixtures_dir


def test_live_mode_stays_bare(config, monkeypatch):
    monkeypatch.setattr(asr, "GenaiLiveTransport", _FakeGenaiTransport)
    config.gemini_mode = "live"
    transport = asr.make_live_transport(config)
    assert isinstance(transport, _FakeGenaiTransport)
    assert not isinstance(transport, RecordingTransport)


def test_mock_mode_stays_scripted(config, monkeypatch):
    monkeypatch.setattr(asr, "GenaiLiveTransport", _FakeGenaiTransport)
    config.gemini_mode = "mock"
    transport = asr.make_live_transport(config)
    assert type(transport).__name__ == "ScriptedLiveTransport"
