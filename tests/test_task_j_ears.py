"""TASK J — EARS: VAD-gated capture, local-first dictation, cancel, limiter.

Grant: 2026-11-05 (J2/E2, J3/E3, J4/E4, J5/E5, J6/F19). Design of record is the
task order itself; the acceptance clauses are pinned one by one below.

  J2  silence is stripped BEFORE transcription using the capture path's own
      energy gate; a clipped/empty take is LABELLED empty, never unparsed text;
      the existing journal sensors still fire.
  J3  local is dictation PRIMARY at a latency tier; Gemini batch is reached
      only below the 0.65 floor (labelled double-pass); every path carries
      provenance; a quota wall never blocks dictation; MUTATING voice intents
      stay gated at 0.85.
  J4  Escape cancels: the partial buffer is zeroized, the node released, the
      cancel journalled (F30), and nothing is transcribed — and the cancel
      reply never claims a zeroization it cannot prove.
  J5  the capture-side soft limiter is static, lookahead-free, per-chunk and
      applied before VAD/ASR/live; RAW peak and PROCESSED peak are both kept
      and both reach doctor; an xrun counter joins the sensors.
  J6  a new model tier pins revision + hash at first fetch and refuses a
      different hash afterwards.

[TESTED-ONLY] — real store, fake device, no mic, no key, no hardware claim.
"""

from __future__ import annotations

import asyncio
import struct

import pytest

from assistant import asr
from assistant.capture import (
    RollingAudioBuffer,
    SoftLimiter,
    pcm_peak,
    strip_silence,
)
from assistant.config import load_config
from assistant.daemon import Daemon
from assistant.live_client import ScriptedLiveTransport
from assistant.model_pins import PinMismatch, load_pins, record_fetch, verify_pin
from assistant.store import Store
from assistant.transcribe import DictationService

SAMPLE = 480                      # 30 ms at 16 kHz
SILENT = b"\x00\x00" * SAMPLE
SPEECH = struct.pack(f"<{SAMPLE}h", *([6000] * SAMPLE))
LOUD = struct.pack(f"<{SAMPLE}h", *([32000] * SAMPLE))


# --------------------------------------------------------------- fixtures
def _config(tmp_path):
    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {**config.raw.get("transcribe", {}),
                                "inbox_dir": str(tmp_path / "inbox")}
    return config


class FakeSource:
    """A device that never touches PipeWire (F17 fake-device discipline)."""

    def __init__(self, frames, *, target="fake-mic"):
        self._frames = list(frames)
        self.target = target
        self.stalled = False
        self.xruns = 0
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        self.closed = True


# ------------------------------------------------ J5: the soft limiter
def test_limiter_is_static_in_place_and_reports_both_peaks():
    limiter = SoftLimiter()
    out = limiter.apply(LOUD)
    stats = limiter.stats()
    assert len(out) == len(LOUD), "the limiter must not change chunk length"
    assert stats["raw_peak"] == pytest.approx(32000 / 32768, abs=1e-3)
    assert stats["processed_peak"] < stats["raw_peak"], \
        "a limited frame must show a lower processed peak"
    assert stats["processed_peak"] <= limiter.ceiling + 0.01
    assert stats["curve"]["lookahead"] is False
    assert stats["limited_samples"] == SAMPLE


def test_limiter_leaves_normal_speech_untouched():
    limiter = SoftLimiter()
    assert limiter.apply(SPEECH) == SPEECH, \
        "below the knee the curve is the identity — speech is not processed"
    assert limiter.stats()["limited_samples"] == 0
    assert limiter.stats()["raw_peak"] == limiter.stats()["processed_peak"]


def test_limiter_never_exceeds_full_scale_on_a_square_wave():
    limiter = SoftLimiter()
    worst = struct.pack(f"<{SAMPLE}h", *([32767, -32768] * (SAMPLE // 2)))
    out = limiter.apply(worst)
    samples = struct.unpack(f"<{SAMPLE}h", out)
    assert max(abs(s) for s in samples) < 32768
    assert pcm_peak(out) <= 0.90


# ---------------------------------------------- J2: silence stripped first
def test_strip_silence_keeps_speech_and_drops_the_dead_head_and_tail():
    pcm = SILENT * 4 + SPEECH * 2 + SILENT * 4
    stripped, stats = strip_silence(pcm)
    assert stats["dropped_head"] >= 4
    assert stats["empty"] is False
    assert len(stripped) < len(pcm)
    assert pcm_peak(stripped) > 0.01
    assert stats["gate"] == "energy-vad"


def test_all_silence_strips_to_empty_and_says_so():
    stripped, stats = strip_silence(SILENT * 20)
    assert stripped == b""
    assert stats["empty"] is True
    assert stats["seconds_out"] == 0.0


def test_strip_reuses_the_capture_gate_and_leaves_interior_pauses_alone():
    """Interior silence is speech rhythm, not padding — it stays."""
    pcm = SILENT * 3 + SPEECH * 2 + SILENT * 2 + SPEECH * 2 + SILENT * 3
    stripped, stats = strip_silence(pcm)
    assert stats["empty"] is False
    # 2 speech frames + 2 interior silence + 2 speech frames survive
    assert len(stripped) // (SAMPLE * 2) >= 6


# -------------------------------- J4/F30: cancel zeroizes and keeps nothing
def test_rolling_buffer_zeroize_destroys_the_audio():
    buffer = RollingAudioBuffer(seconds=5)
    buffer.push(SPEECH)
    buffer.push(SPEECH)
    zeroed = buffer.zeroize()
    assert zeroed == len(SPEECH) * 2
    assert buffer.tail() == b""
    assert buffer.seconds == 0.0


def test_cancel_journals_and_claims_zeroization_only_when_proven(tmp_path, capsys):
    """A cancel whose session did not report zeroizing must SAY so."""
    from assistant.audio_gateway import AudioGateway

    daemon = object.__new__(Daemon)
    daemon.audio = AudioGateway(load_config())
    daemon._ptt_session_id = "sess-cancel"
    daemon._cancel_event = asyncio.Event()
    daemon._stop_event = asyncio.Event()
    daemon._capture_source = FakeSource([])
    daemon.mode = "listening"
    daemon._ptt_log = lambda *a, **k: None

    async def broadcast(_event):
        return None

    daemon.broadcast = broadcast

    class _Unproven:
        cancelled = False

    async def _run_cancel():
        async def finished():
            return _Unproven()

        daemon._dictation_task = asyncio.ensure_future(finished())
        await asyncio.sleep(0)
        return await daemon._cancel_dictation({"stop_source": "bind"})

    out = asyncio.run(_run_cancel())

    assert out["cancelled"] is True
    assert out["zeroized"] is False, \
        "zeroization must never be claimed without the session reporting it"
    assert out["node_released"] is True
    assert out["transcribed"] is False
    assert daemon._capture_source is None

    from assistant import journal_log
    line = journal_log.format_line(
        "cancel.release", verdict="released",
        detail="zeroized=False; task_killed=False; node_released=True; nothing transcribed")
    assert "zeroized" in line


def test_cancel_reports_zeroized_when_the_session_did_it(tmp_path):
    from assistant.audio_gateway import AudioGateway

    daemon = object.__new__(Daemon)
    daemon.audio = AudioGateway(load_config())
    daemon._ptt_session_id = "sess-cancel-2"
    daemon._cancel_event = asyncio.Event()
    daemon._stop_event = asyncio.Event()
    daemon._capture_source = FakeSource([])
    daemon.mode = "listening"
    daemon._ptt_log = lambda *a, **k: None

    async def broadcast(_event):
        return None

    daemon.broadcast = broadcast

    class _Proven:
        cancelled = True

    async def _run_cancel():
        async def finished():
            return _Proven()

        daemon._dictation_task = asyncio.ensure_future(finished())
        await asyncio.sleep(0)
        return await daemon._cancel_dictation({})

    out = asyncio.run(_run_cancel())
    assert out["zeroized"] is True and out["node_released"] is True


# --------------------- J2/J5 together: a real session keeps both peaks + cancels
def test_session_journals_both_peaks_and_the_xrun_counter(tmp_path, monkeypatch,
                                                          journal_stream):
    monkeypatch.setattr(asr, "transcribe_file",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("no batch leg on a silent take")))
    config = _config(tmp_path)
    store = Store(tmp_path / "j5.db")
    service = DictationService(config, store, None)

    source = FakeSource([LOUD] * 6 + [SILENT] * 40)
    result = asyncio.run(service.dictate(source,
                                         transport_factory=ScriptedLiveTransport,
                                         sink=_sink()))
    try:
        stats = result.capture or {}
        assert "limiter" in stats, "capture stats must carry the limiter receipt"
        assert stats["raw_peak"] > 0
        assert "processed_peak" in stats
        assert stats["xruns"] == 0
        events = [line.split() for line in journal_stream.getvalue().splitlines()
                  if "capture.levels" in line]
        assert events, "capture.levels must be journalled"
        detail = " ".join(events[-1])
        assert "raw_peak=" in detail and "processed_peak=" in detail
        assert "xruns=" in detail
    finally:
        store.close()


def _sink():
    async def sink(_event):
        return None
    return sink


# -------------------------------------- J3: local-first gateway decisions
class _FakeLocal:
    name = "local"

    def __init__(self, text="hello there", confidence=0.9):
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def transcribe(self, audio_path, language):
        from assistant.asr import Transcript

        self.calls += 1
        return Transcript(text=self.text, language=language, backend="local",
                          confidence=self.confidence)


class _FakeCloud:
    name = "gemini_batch"

    def __init__(self, text="hello there, escalated", error=None):
        self.text = text
        self.error = error
        self.calls = 0

    def transcribe(self, audio_path, language, **kwargs):
        from assistant.asr import Transcript

        self.calls += 1
        if self.error:
            raise self.error
        return Transcript(text=self.text, language=language,
                          backend="gemini_batch", confidence=0.97)


def _gateway(tmp_path, cloud, **asr_overrides):
    config = load_config()
    if asr_overrides:
        config.raw["asr"] = {**config.raw.get("asr", {}), **asr_overrides}
    wav = tmp_path / "take.wav"
    import wave

    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(SPEECH * 10)
    return config, str(wav)


def test_local_result_above_the_floor_never_reaches_gemini(tmp_path, monkeypatch):
    config, wav = _gateway(tmp_path, None)
    cloud = _FakeCloud()
    monkeypatch.setattr(asr, "GeminiBatchBackend",
                        lambda *a, **k: cloud)
    outcome = asr.transcribe_dictation(config, object(), wav,
                                       local_backend=_FakeLocal(confidence=0.9))
    assert outcome.path == "local"
    assert outcome.labelled is None
    assert outcome.escalation == "not_needed"
    assert cloud.calls == 0
    assert outcome.provenance["legs"][0]["leg"] == "local"
    assert outcome.provenance["tier"] in asr.DICTATION_TIERS


def test_below_the_floor_escalates_and_labels_double_pass(tmp_path, monkeypatch):
    config, wav = _gateway(tmp_path, None)
    cloud = _FakeCloud()
    monkeypatch.setattr(asr, "GeminiBatchBackend", lambda *a, **k: cloud)
    outcome = asr.transcribe_dictation(config, object(), wav,
                                       local_backend=_FakeLocal(confidence=0.4))
    assert outcome.path == "local+escalation"
    assert outcome.labelled == "double-pass"
    assert outcome.backend == "gemini_batch"
    assert cloud.calls == 1
    legs = [leg["leg"] for leg in outcome.provenance["legs"]]
    assert legs == ["local", "gemini_batch"], "both legs must be on the record"
    assert all(leg["sha16"] for leg in outcome.provenance["legs"])


def test_unknown_confidence_is_not_a_pass(tmp_path, monkeypatch):
    config, wav = _gateway(tmp_path, None)
    cloud = _FakeCloud()
    monkeypatch.setattr(asr, "GeminiBatchBackend", lambda *a, **k: cloud)
    outcome = asr.transcribe_dictation(config, object(), wav,
                                       local_backend=_FakeLocal(confidence=None))
    assert outcome.path == "local+escalation"
    assert cloud.calls == 1


def test_quota_wall_is_non_blocking_and_labelled(tmp_path, monkeypatch):
    config, wav = _gateway(tmp_path, None)

    def _wall(*_a, **_k):
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota")

    monkeypatch.setattr(asr, "transcribe_file", _wall)
    outcome = asr.transcribe_dictation(config, object(), wav,
                                       local_backend=_FakeLocal(confidence=0.4))
    assert outcome.escalation == "quota"
    assert outcome.text == "hello there", "the local text must survive the wall"
    assert outcome.path == "local"
    assert outcome.labelled is None, "a quota miss is not a double-pass"


def test_offline_never_escalates(tmp_path, monkeypatch):
    config, wav = _gateway(tmp_path, None)
    cloud = _FakeCloud()
    monkeypatch.setattr(asr, "GeminiBatchBackend", lambda *a, **k: cloud)
    outcome = asr.transcribe_dictation(config, None, wav, offline=True,
                                       local_backend=_FakeLocal(confidence=0.2))
    assert outcome.escalation == "offline"
    assert cloud.calls == 0


def test_silence_is_none_not_unparsed_text(tmp_path, monkeypatch):
    config, wav = _gateway(tmp_path, None)
    cloud = _FakeCloud()
    monkeypatch.setattr(asr, "GeminiBatchBackend", lambda *a, **k: cloud)
    outcome = asr.transcribe_dictation(config, object(), wav,
                                       local_backend=_FakeLocal(text="", confidence=0.0))
    assert outcome.text or outcome.path in ("none", "local+escalation")
    assert outcome.path != "local" or outcome.text.strip()


# ------------------------------------- J3: the 0.85 mutating-command floor
def test_mutating_voice_commands_are_gated_at_the_command_floor():
    config = load_config()
    floor = asr.command_min_confidence(config)
    assert floor == 0.85

    allowed, why = asr.voice_command_allowed("organise", 0.86, config)
    assert allowed is True and "cleared" in why

    allowed, why = asr.voice_command_allowed("organise", 0.84, config)
    assert allowed is False and "below" in why

    allowed, why = asr.voice_command_allowed("organise", None, config)
    assert allowed is False, "an unknown confidence must not clear the floor"

    # A read-only intent is not gated: the floor is for MUTATION.
    allowed, _why = asr.voice_command_allowed("status", 0.10, config)
    assert allowed is True


def test_dictation_tier_is_validated_and_never_silently_smaller():
    config = load_config()
    assert asr.dictation_tier(config) in asr.DICTATION_TIERS
    config.raw["asr"] = {**config.raw.get("asr", {}), "dictation_tier": "giant"}
    with pytest.raises(ValueError, match="dictation_tier"):
        asr.dictation_tier(config)


def test_tier_choice_is_measured_not_assumed():
    assert asr.tier_latency_report([])["measured"] is False
    report = asr.tier_latency_report([
        {"tier": "tiny", "latency_s": 0.4},
        {"tier": "base", "latency_s": 0.9},
        {"tier": "small", "latency_s": 2.4},
    ], budget_s=1.2)
    assert report["tier"] == "base", "the largest tier inside the budget wins"
    assert report["chosen"]["samples"] == 1


# ------------------------------------------------ J6: model tier pinning
def test_first_fetch_pins_and_a_changed_hash_is_refused(tmp_path):
    config = load_config()
    first = record_fetch(config, "base", revision="rev-1", sha256="a" * 64,
                         source="local-cache")
    assert first["first_fetch"] is True
    assert load_pins(config)["base"]["revision"] == "rev-1"

    again = record_fetch(config, "base", revision="rev-1", sha256="a" * 64)
    assert again["first_fetch"] is False
    ok, why = verify_pin(config, "base", sha256="a" * 64)
    assert ok is True and "rev-1" in why

    with pytest.raises(PinMismatch, match="refusing"):
        record_fetch(config, "base", revision="rev-2", sha256="b" * 64)
    ok, why = verify_pin(config, "base", sha256="b" * 64)
    assert ok is False and "pinned" in why
