"""Voice-chain resilience (window findings order v1, 2026-11-02).

The 2026-11-02 owner window starved: Google's free-tier transcription
returned 200-with-empty-text on both wavs, the local leg was already
dead (PyAV 19 removed `metadata_errors` from av.open), and the failure
journal carried an empty error string. This file pins the three fixes:

F1 — the av dependency pin (PyAV 19.0.0 removed both `metadata_errors`
     and `metadata_encoding` from av.open; faster-whisper 1.2.1 — the
     latest release — passes metadata_errors="ignore", so av>=19 makes
     every local decode raise TypeError).
F2 — quota knowledge (gemini-3.5-transcribe free tier = 3 RPM, from the
     verbatim 429 quotaValue) + the file leg pacing itself under it
     with retry-after honoring.
F3 — empty-leg semantics: per-backend empty/failure class-marks, the
     chain's real failure text on failure events (never an empty error
     string), empty = backend failure = fall through, and whole-chain
     starvation as its own schema event.

Evidence: [TESTED-ONLY] — tonight's shapes replayed from the owner
journal (session 61258b3b343a) with fakes; F1's wall is [PyPI-VERIFIED]
against the av sdists; S1/S2/S3 (scene card) are the owner acceptance.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path

import pytest

from assistant import asr
from assistant.asr import Transcript
from assistant.gemini_client import (
    PerModelLimiter,
    RateLimitError,
    quota_family,
)
from assistant.journal_log import (
    bind as bind_journal,
)
from assistant.journal_log import (
    error_text,
)
from assistant.journal_log import (
    reset as reset_journal,
)

REPO = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------ F1
def test_f1_av_pin_is_present_and_bounded():
    """The dependency wall is load-bearing: av>=19 breaks every local
    decode (metadata_errors removed in 19.0.0 — PyPI sdists verified
    2026-11-02: 18.1.0 core.py carries metadata_errors="strict", 19.0.2
    carries neither kwarg). This pin guards against a tidy-up removing
    it and re-killing the local leg silently."""
    pyproject = (REPO / "pyproject.toml").read_text()
    assert '"av>=15.1,<19"' in pyproject, \
        "the av pin (kwarg wall at 19) must stay in dependencies"
    assert "faster-whisper" in pyproject


def test_f1_the_pinned_av_accepts_the_kwarg_faster_whisper_passes():
    """Behavioral proof on the RESOLVED environment: the W3 compat
    pre-check shape — av.open(..., metadata_errors='ignore') must not
    raise TypeError under the pin."""
    pytest.importorskip("av")
    import inspect

    import faster_whisper.audio as fwa

    assert "metadata_errors" in inspect.getsource(fwa.decode_audio), \
        "faster-whisper's call shape changed — re-evaluate the pin"
    from assistant.asr import _faster_whisper_compat

    ok, reason, diag = _faster_whisper_compat()
    assert ok, f"local ASR compat pre-check must pass under the pin: {reason} ({diag})"


# ------------------------------------------------------------------ F2
class _FakeStore:
    def log_llm_call(self, **kwargs):
        return None


def _client_with_quota(quota_models: dict, *, registry_rpm=None):
    """GeminiClient-shaped rpm resolution without the network: build a
    real GeminiClient in mock mode with a synthetic [quota]."""
    from assistant.config import load_config
    from assistant.gemini_client import GeminiClient

    config = load_config()
    config.raw.setdefault("quota", {})["models"] = dict(quota_models)
    client = GeminiClient(config, _FakeStore())
    return client, config


def test_f2_registry_rpm_is_the_knowledge_of_record_when_config_is_silent():
    """config's transcribe-batch row carries rpm=None (frozen file); the
    REGISTRY's verified figure (3, from the 429 quotaValue) must pace
    the model instead of the flash-derived alias default."""
    from assistant.model_registry import VERIFIED_FREE_TIER_RPM

    assert VERIFIED_FREE_TIER_RPM["gemini-3.5-transcribe"] == 3
    client, _config = _client_with_quota(
        {"transcribe-batch": {"rpm": None, "tpm": None, "rpd": 25}})
    limit = client._limiter._rpm("gemini-3.5-transcribe")
    assert limit == 3, \
        "an rpm-less config row resolves to the registry's verified 3 RPM"


def test_f2_owner_config_rpm_still_wins_and_the_stricter_rule_holds():
    client, _config = _client_with_quota(
        {"transcribe-batch": {"rpm": 3, "tpm": None, "rpd": 25}})
    assert client._limiter._rpm("gemini-3.5-transcribe") == 3


def test_f2_pacing_holds_under_three_rpm():
    """3 RPM = at most 3 sends per 60 s window: the 4th acquire inside
    the window refuses (queued, not sent) rather than sending — tonight's
    429 was the 4th call within ~19 s."""
    calls = []
    limiter = PerModelLimiter(lambda model: 3)
    now = [1000.0]

    def fake_now():
        return now[0]

    limiter.acquire("gemini-3.5-transcribe", sleep=lambda s: calls.append(s),
                    now=fake_now)
    limiter.acquire("gemini-3.5-transcribe", sleep=lambda s: calls.append(s),
                    now=fake_now)
    limiter.acquire("gemini-3.5-transcribe", sleep=lambda s: calls.append(s),
                    now=fake_now)
    with pytest.raises(RateLimitError):
        limiter.acquire("gemini-3.5-transcribe",
                        sleep=lambda s: calls.append(s),
                        now=fake_now, max_wait_s=0.5)
    assert not calls, "a refused acquire never sleeps into the send"


def test_f2_retry_after_429_is_held():
    """A server 429 with retryDelay: the hold is recorded and the next
    acquire honors it (waits it out when budget allows, refuses when
    not) — retry-after honoring, per the order."""
    limiter = PerModelLimiter(lambda model: 3)
    now = [5000.0]

    def fake_now():
        return now[0]

    slept = []
    limiter.hold("gemini-3.5-transcribe", 36.0, now=fake_now)
    with pytest.raises(RateLimitError):
        limiter.acquire("gemini-3.5-transcribe",
                        sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
                        now=fake_now, max_wait_s=5.0)
    # with enough budget the hold is waited out and the send proceeds
    limiter.acquire("gemini-3.5-transcribe",
                    sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)),
                    now=fake_now, max_wait_s=65.0)
    assert slept and slept[0] > 30


def test_f2_file_leg_acquires_the_limiter():
    """The wire seam sends through the pacing gate (it previously bypassed
    the limiter entirely — 4 calls reached the wire within 19 s)."""
    from assistant.gemini_client import _SdkTransport

    client, _config = _client_with_quota(
        {"transcribe-batch": {"rpm": None, "tpm": None, "rpd": 25}})
    acquired = []
    real_acquire = client._limiter.acquire

    def spy(model, **kwargs):
        acquired.append(model)
        return real_acquire(model, **kwargs)

    client._limiter.acquire = spy
    transport = _SdkTransport.__new__(_SdkTransport)
    transport._client = _FakeSdkClient()
    client._transport = transport
    client._sdk_transcribe(_wav_path(), "gemini-3.5-transcribe",
                           "prompt", "corr", 1.0)
    assert "gemini-3.5-transcribe" in acquired


class _FakeResp:
    text = "whole sentence from the wire"


class _FakeModels:
    def generate_content(self, *, model, contents, config=None):
        return _FakeResp()


class _FakeFiles:
    def upload(self, *, file, config=None):
        return object()


class _FakeSdkClient:
    files = _FakeFiles()
    models = _FakeModels()


def test_f2_wire_429_holds_and_surfaces_retry_after():
    """A 429 with retryDelay: the wire seam records the hold (no send
    before it expires) and raises the rate error with its real text —
    retry-after honoring, per the order."""
    from assistant.gemini_client import _SdkTransport

    client, _config = _client_with_quota(
        {"transcribe-batch": {"rpm": None, "tpm": None, "rpd": 25}})

    class _RateModels:
        def generate_content(self, *, model, contents, config=None):
            raise RuntimeError(
                "429 RESOURCE_EXHAUSTED — quotaMetric "
                "generate_content_free_tier_requests, quotaValue 3, "
                "retryDelay 36s")

    class _RateClient:
        files = _FakeFiles()
        models = _RateModels()

    transport = _SdkTransport.__new__(_SdkTransport)
    transport._client = _RateClient()
    client._transport = transport
    with pytest.raises(RateLimitError) as excinfo:
        client._sdk_transcribe(_wav_path(), "gemini-3.5-transcribe",
                               "prompt", "corr", 1.0)
    assert "429" in str(excinfo.value) and "retry-after" in str(excinfo.value)
    held = client._limiter._hold_until.get("gemini-3.5-transcribe", 0.0)
    assert held > 0, "the retryDelay hold is recorded"


def _wav_path():
    import tempfile
    import wave

    path = Path(tempfile.mkdtemp()) / "f2.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x01\x00" * 1600)
    return path


def test_f2_quota_family_maps_the_transcribe_model():
    assert quota_family("gemini-3.5-transcribe") == "transcribe-batch"


# ------------------------------------------------------------------ F3
def test_f3a_error_text_is_never_empty():
    assert error_text(RuntimeError("boom")) == "RuntimeError: boom"
    assert error_text(TimeoutError()) == "TimeoutError", \
        "a message-less TimeoutError (asyncio.wait_for) still names itself"
    assert error_text(ValueError("")) == "ValueError"
    assert error_text(Exception()) not in ("", None)


class _FakeBackend:
    def __init__(self, name, *, text=None, error=None, raise_cls=None):
        self.name = name
        self._text = text
        self._error = error
        self._raise_cls = raise_cls

    def transcribe(self, audio_path, language):
        if self._raise_cls is not None:
            raise self._raise_cls(self._error) if self._error else self._raise_cls()
        return Transcript(text=self._text or "", language=language,
                          backend=self.name)


def _walk(config, backends, tmp_path, monkeypatch, *, session_id="s1"):
    monkeypatch.setattr(asr, "batch_chain",
                        lambda *a, **k: list(backends))
    stream = io.StringIO()
    bind_journal(stream)
    try:
        result = asr.transcribe_file(
            config, None, str(tmp_path / "x.wav"), session_id=session_id)
    except Exception as exc:
        result = exc
    finally:
        reset_journal()
    return result, stream.getvalue()


def test_f3b_empty_falls_through_to_the_next_backend(config, tmp_path,
                                                     monkeypatch):
    """200-with-empty-text counts as that backend FAILING — the next one
    in the chain runs (tonight's shape with F1 landed = local whisper
    instead of silence)."""
    result, lines = _walk(config, [
        _FakeBackend("gemini_batch", text=""),
        _FakeBackend("local", text="Recovered words from the saved audio."),
    ], tmp_path, monkeypatch)
    assert isinstance(result, Transcript)
    assert result.text == "Recovered words from the saved audio."
    assert result.backend == "local"
    assert "transcription.backend" in lines
    assert "empty" in lines and "gemini_batch" in lines


def test_f3b_all_empty_raises_the_chain_failure_text(config, tmp_path,
                                                     monkeypatch):
    """Nothing landed = the chain's REAL failure text rises (F3a's
    surface), carrying per-backend reasons — never a silent empty."""
    result, lines = _walk(config, [
        _FakeBackend("gemini_batch", text=""),
        _FakeBackend("local", raise_cls=RuntimeError,
                     error="local ASR degraded: av broken"),
    ], tmp_path, monkeypatch)
    assert isinstance(result, RuntimeError)
    assert "all ASR backends failed" in str(result)
    assert "gemini_batch: empty transcript" in str(result)
    assert "local ASR degraded: av broken" in str(result), \
        "the chain's real failure text carries the per-backend reasons"
    assert "transcription.backend" in lines


def test_f3c_backend_marks_carry_chars_and_sha16_where_text_exists(
        config, tmp_path, monkeypatch):
    result, lines = _walk(config, [
        _FakeBackend("gemini_batch", text="   "),
        _FakeBackend("local", text="Fine."),
    ], tmp_path, monkeypatch)
    assert result.text == "Fine."
    mark = next(ln for ln in lines.splitlines() if "transcription.backend" in ln)
    assert "chars=3" in mark, "the whitespace text exists — its char count rides"
    assert "sha16=" in mark


def test_f3c_mark_detail_never_carries_the_text():
    from assistant.journal_log import backend_mark_detail

    text = "the secret words"
    detail = backend_mark_detail(text, error="")
    assert f"chars={len(text)}" in detail and "sha16=" in detail
    assert "secret" not in detail and "words" not in detail


def test_f3c_backend_marks_never_carry_text_when_none_exists(
        config, tmp_path, monkeypatch):
    result, lines = _walk(config, [
        _FakeBackend("gemini_batch", text=""),
        _FakeBackend("local", raise_cls=RuntimeError, error="nope"),
    ], tmp_path, monkeypatch)
    assert isinstance(result, RuntimeError)
    failed = next(ln for ln in lines.splitlines()
              if "transcription.backend" in ln and "failed" in ln)
    assert "chars=0" in failed
    assert "sha16=" not in failed, "no text exists — no hash is invented"
    assert "nope" in failed, "the failure's own reason text is diagnostic, kept"


# ------------------------------------------------- tonight's shapes, replayed
class _SilentTransport:
    """The scene-6 wire shape: a healthy Live link that sends zero
    transcript-family messages (live-final-missing, exhibit-2 class)."""

    name = "silent"

    def __init__(self):
        self._queue = asyncio.Queue()
        self._frames = 0
        self.frames_received = 0

    async def send_audio(self, pcm):
        self._frames += 1
        self.frames_received += 1

    async def activity_end(self):
        return None

    async def events(self):
        while True:
            yield await self._queue.get()

    async def close(self):
        return None

    def wire_stats(self):
        return {
            "setup_complete": True, "setup_retries": 0, "voice_end": False,
            "transcript_family": 0, "transcript_parts": 0,
            "transcript_commits": 0, "transcript_dupes": 0,
            "transcript_snapshots": 0, "transcript_commit_reasons": {},
            "types": {}, "samples": [],
            "audio_sent": {"chunks": self._frames,
                           "bytes": self._frames * 960,
                           "format": "audio/pcm", "rate": 16000},
        }


def _dictate(config, tmp_path, monkeypatch, backends, *, slow_leg=None):
    """One full dictate turn over the silent wire with a faked chain."""
    from assistant.store import Store
    from assistant.transcribe import DictationService

    config.raw["cleanup"]["enabled"] = False
    config.raw["transcribe"]["inbox_dir"] = str(tmp_path / "inbox")
    config.raw["transcribe"]["copy_to_clipboard"] = False
    store = Store(tmp_path / "resilience.db")
    svc = DictationService(config, store, None)
    svc.FINAL_TRANSCRIPT_TIMEOUT_S = 0.05
    svc.final_wait_s = 0.5
    svc.final_abandon_grace_s = 0.25
    if slow_leg is not None:
        svc.FALLBACK_TIMEOUT_S = slow_leg
    if backends is not None:
        monkeypatch.setattr(asr, "batch_chain", lambda *a, **k: list(backends))
    else:
        def _timeout_leg(*a, **k):
            raise TimeoutError()   # asyncio.wait_for's message-less shape

        monkeypatch.setattr(asr, "transcribe_file", _timeout_leg)
    from assistant.capture import SimulatedCapture

    stream = io.StringIO()
    logs: dict = {}
    real_log = svc._log

    def spy(_name, /, **fields):
        logs.setdefault(_name, []).append(fields)
        return real_log(_name, **fields)

    svc._log = spy
    bind_journal(stream)
    try:
        result = asyncio.run(svc.dictate(
            SimulatedCapture(speech_frames=100, silent_frames=0),
            transport_factory=lambda: _SilentTransport()))
    finally:
        reset_journal()
        store.close()
    return result, stream.getvalue(), logs


def test_shape_200_empty_then_local_lands(config, tmp_path, monkeypatch):
    """Tonight's shape with F1 alive: Gemini answers 200-empty (class
    mark) and the local whisper carries the turn — landed, no
    starvation."""
    result, lines, _logs = _dictate(config, tmp_path, monkeypatch, [
        _FakeBackend("gemini_batch", text=""),
        _FakeBackend("local", text="Recovered words from the saved audio."),
    ])
    assert result.raw_text == "Recovered words from the saved audio."
    marks = [ln for ln in lines.splitlines() if "transcription.backend" in ln]
    assert marks and "empty" in marks[0] and "gemini_batch" in marks[0]
    assert "fallback.outcome" in lines and "landed" in lines
    assert "transcription.starvation" not in lines
    order = [ln for ln in lines.splitlines()
             if "transcription.backend" in ln or "fallback.outcome" in ln]
    assert "transcription.backend" in order[0], \
        "the per-backend class-mark lands before the outcome line"


def test_shape_429_falls_through_to_local(config, tmp_path, monkeypatch):
    """The 429 class: the rate refusal is class-marked with its reason
    and the chain falls to local (pacing normally prevents the 429)."""
    result, lines, _logs = _dictate(config, tmp_path, monkeypatch, [
        _FakeBackend("gemini_batch", raise_cls=RateLimitError,
                     error="429 RESOURCE_EXHAUSTED quotaValue 3, retryDelay 36s"),
        _FakeBackend("local", text="Whispered after the rate refusal."),
    ])
    assert result.raw_text == "Whispered after the rate refusal."
    mark = next(ln for ln in lines.splitlines() if "transcription.backend" in ln)
    assert "failed" in mark and "429" in mark and "gemini_batch" in mark


def test_shape_all_backends_failed_starves_legibly(config, tmp_path,
                                                   monkeypatch):
    """Tonight's journal was `error: ""`. The legible sequence now:
    per-backend class-marks -> fallback.outcome carrying the chain's
    REAL failure text -> transcription.starvation -> deferred (wav kept)."""
    result, lines, _logs = _dictate(config, tmp_path, monkeypatch, [
        _FakeBackend("gemini_batch", text=""),
        _FakeBackend("local", raise_cls=RuntimeError, error="av 19 broke decode"),
    ])
    assert result.raw_text == ""
    assert "transcription.backend" in lines
    outcome = next(ln for ln in lines.splitlines() if "fallback.outcome" in ln)
    assert "all ASR backends failed" in outcome, \
        "the chain's real failure text surfaces in the event (F3a)"
    assert "gemini_batch: empty transcript" in outcome
    starve = [ln for ln in lines.splitlines()
              if "transcription.starvation" in ln]
    assert starve and "outcome=error" in starve[0]
    assert "wav kept at" in starve[0] and "retained for retry" in starve[0]
    assert "transcription.deferred" in lines, \
        "the deferred contract still owns the wav"
    assert "error: \"\"" not in lines


def test_shape_timeout_replay_names_the_error(config, tmp_path, monkeypatch):
    """The exact tonight mechanism: asyncio.wait_for's message-less
    TimeoutError abandons the leg. The failure line names it (never
    `error ""`), the outcome is classed timeout, starvation fires."""
    result, lines, logs = _dictate(config, tmp_path, monkeypatch, None,
                                   slow_leg=0.05)
    assert result.raw_text == ""
    outcome = next(ln for ln in lines.splitlines() if "fallback.outcome" in ln)
    assert "timeout" in outcome
    starve = [ln for ln in lines.splitlines()
              if "transcription.starvation" in ln]
    assert starve and "outcome=timeout" in starve[0]
    flat = str(logs)
    assert "TimeoutError" in flat, \
        "the lifecycle failure line names the exception class (F3a)"
    assert 'error: \'\'' not in flat and 'error=\'\'' not in flat
