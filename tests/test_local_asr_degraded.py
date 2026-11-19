"""W3 named-degradation pins (scene-7 work order, 2026-10-31).

The owner runtime (Fedora 44 / Python 3.14.8) killed every local ASR
attempt with `open() got an unexpected keyword argument 'metadata_errors'`
— a raw TypeError out of faster-whisper's `av.open(..., metadata_errors=)`
call against a non-conforming `av` resolution. Contract now: the local
leg either transcribes or fails with a NAMED, LOGGED, non-traceback
error (LocalAsrDegraded + `local_asr.degraded` schema line + a
diagnostic that names the exact `av`), and the doctor view says so.
"""

from __future__ import annotations

import io
import sys

import pytest

from assistant import asr
from assistant.asr import LocalAsrDegraded, LocalWhisperBackend
from assistant.journal_log import bind as bind_journal
from assistant.journal_log import reset as reset_journal


class _FakeAvGood:
    """Conforming PyAV: open() accepts metadata_errors."""
    __version__ = "14.4.0"
    __file__ = "/fake/av/__init__.py"

    @staticmethod
    def open(file, mode=None, metadata_errors="strict"):
        raise RuntimeError("not used in these tests")


class _FakeAvBad:
    """The 3.14-era resolution: open() rejects metadata_errors."""
    __version__ = "0.0-broken"
    __file__ = "/fake/av/broken.py"

    @staticmethod
    def open(file, mode=None):
        raise RuntimeError("not used in these tests")


def test_compat_names_a_bad_av_resolution(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", _FakeAvBad())
    ok, reason, diag = asr._faster_whisper_compat()
    assert ok is False
    assert "metadata_errors" in reason
    assert "broken.py" in diag
    assert "open_params" in diag


def test_compat_passes_a_conforming_av(monkeypatch):
    monkeypatch.setitem(sys.modules, "av", _FakeAvGood())
    ok, reason, _diag = asr._faster_whisper_compat()
    assert ok is True
    assert reason == ""


def test_local_leg_degrades_by_name_not_traceback(config, monkeypatch):
    monkeypatch.setitem(sys.modules, "av", _FakeAvBad())
    config.raw.setdefault("asr", {})["offline_backend"] = "faster-whisper"
    backend = LocalWhisperBackend(config)
    stream = io.StringIO()
    bind_journal(stream)
    try:
        with pytest.raises(LocalAsrDegraded) as excinfo:
            backend.transcribe("/tmp/anything.wav", "en")
    finally:
        reset_journal()
    message = str(excinfo.value)
    assert message.startswith("local ASR degraded:")
    assert "metadata_errors" in message
    assert "remote fallback continues" in message
    assert type(excinfo.value) is LocalAsrDegraded, \
        "the failure must surface as the named error, not a raw TypeError"
    lines = stream.getvalue()
    assert "local_asr.degraded" in lines
    assert "av_file=" in lines, "the schema line must name the exact av"


def test_type_error_belt_catches_the_call_site(config, monkeypatch):
    """Even when introspection passes, a decode-time TypeError from the
    same call site degrades by name."""
    monkeypatch.setitem(sys.modules, "av", _FakeAvGood())

    class _ExplodingModel:
        def transcribe(self, *args, **kwargs):
            raise TypeError(
                "open() got an unexpected keyword argument 'metadata_errors'")

    config.raw.setdefault("asr", {})["offline_backend"] = "faster-whisper"
    backend = LocalWhisperBackend(config,
                                  model_loader=lambda name: _ExplodingModel())
    with pytest.raises(LocalAsrDegraded):
        backend.transcribe("/tmp/anything.wav", "en")


def test_doctor_view_names_the_degradation(config, monkeypatch):
    monkeypatch.setitem(sys.modules, "av", _FakeAvBad())
    monkeypatch.setattr(
        asr.importlib.util, "find_spec",
        lambda name: object() if name == "faster_whisper" else None)
    config.raw.setdefault("asr", {})["offline_backend"] = "faster-whisper"
    status = asr.local_asr_status(config)
    assert status["available"] is False
    assert "metadata_errors" in status["reason"]
    assert "degraded" in status["reason"]
