"""BUG 6 [I1, I2, I3, I4] consolidated capture regressions (hardware report 2026-10-20).

The proven-working microphone never reached the transcript: `ptt.start` spawned
pw-record with NO `--target` (params["target"] was never set by `assist
dictate`) while the owner's node sat unused in config `mic_target`; captured
bytes/RMS were logged nowhere; and a wedged capture left `readexactly` hanging
so `stop_event` was never observed — `ptt.result` sat its full 60 s on a dead
session and reported nothing.

Required fixes, pinned here (dictate-shaped sessions, real service + real
socket):

1. Dictate sessions capture from the configured/default mic and produce a
   transcript in live mode (real-signal source).
2. Diagnostics: capture node, bytes captured and peak level per session —
   visible in the result, in `status`, and in the persona event log.
3. `ptt.result` fails fast with a clear "no speech captured" on ~zero audio
   (fake/silent source, dead capture) — never the full wait.
4. Regression tests against a fake/silent AND a real-signal capture source.
"""

from __future__ import annotations

import asyncio
import struct
import subprocess
import time
from types import SimpleNamespace

import pytest

from assistant import asr
from assistant.capture import (
    BYTES_PER_SAMPLE,
    SAMPLE_RATE,
    list_pw_nodes,
    live_level_check,
    pcm_peak,
)
from assistant.ipc import call
from assistant.store import Store
from assistant.transcribe import DictationService

FRAME_SAMPLES = SAMPLE_RATE * 30 // 1000


@pytest.fixture(autouse=True)
def _force_simulated_capture(monkeypatch):
    """No bug6-class test may open the real mic (owner order 2026-10-26).

    The bug6 suite failed on the laptop where the CLI-subprocess dictate
    test opened the REAL microphone (~0 s of room audio → "no speech
    captured" instead of the scripted mock transcript) while the headless
    sandbox silently fell back to SimulatedCapture. Tests that
    deliberately exercise capture-selection (target wiring) opt out with
    monkeypatch.delenv("ASSIST_CAPTURE").
    """
    monkeypatch.setenv("ASSIST_CAPTURE", "simulated")


def speech_frame() -> bytes:
    return struct.pack(f"<{FRAME_SAMPLES}h", *([6000] * FRAME_SAMPLES))


def silence_frame() -> bytes:
    return b"\x00\x00" * FRAME_SAMPLES


class FakeSource:
    """A capture source in the AsyncFrameSource shape."""

    def __init__(self, frames, *, target="fake-node", stalled=False):
        self._frames = frames
        self.target = target
        self.stalled = stalled
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        self.closed = True


class HangingSource:
    """Dead capture: delivers absolutely nothing, ever (wedged pw-record)."""

    def __init__(self, *, target="dead-node"):
        self.target = target
        self.stalled = False
        self.closed = False
        self._never = asyncio.Event()

    async def frames(self):
        await self._never.wait()          # never yields, never returns
        yield silence_frame()             # unreachable: makes this a generator

    async def aclose(self):
        self.closed = True


# The shipped `[voice] silence_floor` default (config.DEFAULTS). Config
# hygiene for these tests: verdict-affecting knobs are pinned to shipped
# semantics, never the machine's live tuning. NOTE (2026-10-26, owner
# correction): this pin did NOT fix the laptop failure — the live config
# contains no silence_floor at all, so the earlier mechanism claim is
# retracted. The real leak was the CLI-subprocess dictate opening the REAL
# mic (~0 s captured → below any floor → "no speech captured"); the fix is
# the env-forced simulated capture seam (ASSIST_CAPTURE=simulated, autouse
# below). Status remains [BROKEN-laptop] until the owner's re-run.
_SHIPPED_SILENCE_FLOOR = 0.05


def _service_config(tmp_path):
    from assistant.config import load_config

    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {**config.raw.get("transcribe", {}),
                                "inbox_dir": str(tmp_path / "inbox")}
    config.raw["voice"] = {**config.raw.get("voice", {}),
                           "silence_floor": _SHIPPED_SILENCE_FLOOR}
    return config


@pytest.fixture(autouse=True)
def _pin_ambient_voice_config(config):
    """Pin the verdict-affecting knobs before any daemon/service is built.

    The `config` fixture is `load_config()` — on the owner's laptop that
    merges ~/.config/assistant/config.toml. Autouse so daemon-based tests
    (which build DictationService at init, reading silence_floor once) are
    hermetic too.
    """
    config.raw.setdefault("voice", {})["silence_floor"] = _SHIPPED_SILENCE_FLOOR


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# 1/4. Fake/silent source: "no speech captured", fast, no fallback call
# ===========================================================================
def test_silent_capture_source_reports_no_speech_and_skips_fallback(
        tmp_path, monkeypatch):
    config = _service_config(tmp_path)
    store = Store(tmp_path / "bug6.db")
    service = DictationService(config, store, None)

    def _fallback_must_not_run(*args, **kwargs):
        raise AssertionError(
            "fallback transcription ran on a silent session — §8: never "
            "hallucinate on silence")

    monkeypatch.setattr(asr, "transcribe_file", _fallback_must_not_run)

    from assistant.live_client import ScriptedLiveTransport

    events: list[dict] = []

    async def sink(event):
        events.append(event)

    source = FakeSource([silence_frame() for _ in range(40)],
                        target="fake-silent")
    began = time.monotonic()
    result = _run(service.dictate(
        source, transport_factory=ScriptedLiveTransport, sink=sink))
    elapsed = time.monotonic() - began

    assert elapsed < 5.0, f"a dead session took {elapsed:.1f}s — must fail fast"
    assert result.no_speech is True
    assert result.raw_text == ""
    assert source.closed is True
    # Diagnostics: node, bytes, peak — the facts the owner asked for.
    stats = result.capture
    assert stats["node"] == "fake-silent"
    assert stats["bytes"] == 40 * FRAME_SAMPLES * BYTES_PER_SAMPLE
    assert stats["peak_rms"] == 0.0
    assert stats["no_speech"] is True
    assert any("no speech captured" in n for n in result.notes)
    # The verdict is emitted, not just stored.
    assert any(e.get("event") == "capture.stats" and e["node"] == "fake-silent"
               for e in events)


# ===========================================================================
# 1/4. Real-signal source: a transcript, in live mode
# ===========================================================================
def test_real_signal_capture_source_produces_a_live_transcript(tmp_path):
    config = _service_config(tmp_path)
    store = Store(tmp_path / "bug6.db")
    service = DictationService(config, store, None)

    from assistant.live_client import ScriptedLiveTransport

    source = FakeSource([speech_frame() for _ in range(40)],
                        target="alsa_input.test.Mic1__source")
    result = _run(service.dictate(
        source, transport_factory=ScriptedLiveTransport))

    assert result.no_speech is False
    assert result.raw_text.strip(), "a live session on real signal said nothing"
    assert "mock transcript" in result.raw_text.lower()
    assert result.backend == "gemini_live"
    stats = result.capture
    assert stats["node"] == "alsa_input.test.Mic1__source"
    assert stats["bytes"] == 40 * FRAME_SAMPLES * BYTES_PER_SAMPLE
    assert stats["peak_rms"] == pytest.approx(6000 / 32768, abs=0.01)


# ===========================================================================
# 3. PTT release beats a dead capture — the session cannot hang
# ===========================================================================
def test_release_ends_a_dead_session_with_no_speech(tmp_path):
    config = _service_config(tmp_path)
    store = Store(tmp_path / "bug6.db")
    service = DictationService(config, store, None)

    from assistant.live_client import ScriptedLiveTransport

    stop_event = asyncio.Event()

    async def run():
        async def release():
            await asyncio.sleep(0.2)
            stop_event.set()

        asyncio.ensure_future(release())
        return await service.dictate(
            HangingSource(), transport_factory=ScriptedLiveTransport,
            stop_event=stop_event)

    began = time.monotonic()
    result = _run(run())
    elapsed = time.monotonic() - began

    assert elapsed < 3.0, (
        f"PTT release waited {elapsed:.1f}s behind a wedged capture — "
        "the read must lose to the release")
    assert result.no_speech is True
    assert result.raw_text == ""
    assert result.capture["bytes"] == 0
    assert result.capture["node"] == "dead-node"


# ===========================================================================
# 2/3. Daemon over the real socket: mic_target wiring + fail-fast + status
# ===========================================================================
def test_daemon_dictate_uses_configured_mic_target_and_fails_fast_on_silence(
        config, running_daemon, monkeypatch):
    # this test exercises capture SELECTION (target wiring): un-force
    # simulated capture so the (monkeypatched) PipeWireCapture is constructed
    monkeypatch.delenv("ASSIST_CAPTURE", raising=False)
    daemon, _server = running_daemon
    # Exactly what the owner did on hardware: set mic_target by hand.
    daemon.config.raw.setdefault("capture", {})["mic_target"] = \
        "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source"

    created: dict = {}

    class SilentPW:
        def __init__(self, target=None, *, sample_rate=SAMPLE_RATE,
                     frame_ms=30, stall_timeout_s=8.0):
            created["target"] = target
            self.target = target
            self.stalled = False

        async def frames(self):
            for _ in range(25):
                yield silence_frame()

        async def aclose(self):
            created["closed"] = True

    monkeypatch.setattr("assistant.daemon.PipeWireCapture", SilentPW)

    started = call(config.socket_path, "ptt.start", {}, timeout=5.0)
    expected = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source"
    assert started["capture_target"] == expected
    assert created["target"] == expected, (
        "pw-record must be spawned with the configured node as --target")
    time.sleep(0.2)

    began = time.monotonic()
    stopped = call(config.socket_path, "ptt.stop",
                   {"wait_s": 30.0}, timeout=35.0)
    elapsed = time.monotonic() - began

    assert elapsed < 10.0, (
        f"ptt.result sat {elapsed:.1f}s on a dead session — must fail fast")
    result = stopped["result"]
    assert result["no_speech"] is True
    assert result["narration"] == "no speech captured"
    assert result["text"] == ""
    # Diagnostics ride on the result the CLI prints from.
    assert result["capture"]["node"] == expected
    assert result["capture"]["bytes"] > 0
    assert result["capture"]["peak_rms"] == 0.0

    # …and they are visible after the fact via `assist status`.
    status = call(config.socket_path, "status", timeout=3.0)
    assert status["capture_target"] == expected
    assert status["last_capture"]["node"] == expected
    assert status["last_capture"]["no_speech"] is True


def test_mic_target_precedence_param_beats_config_beats_meeting(
        config, running_daemon, monkeypatch):
    # this test exercises capture SELECTION (target wiring): un-force
    # simulated capture so the (monkeypatched) PipeWireCapture is constructed
    monkeypatch.delenv("ASSIST_CAPTURE", raising=False)
    daemon, _server = running_daemon
    daemon.config.raw.setdefault("capture", {})["mic_target"] = "from-capture"
    daemon.config.raw.setdefault("meeting", {})["mic_target"] = "from-meeting"
    created: list = []

    class SpyPW:
        def __init__(self, target=None, **kwargs):
            created.append(target)
            self.target = target
            self.stalled = False

        async def frames(self):
            yield silence_frame()

        async def aclose(self):
            pass

    monkeypatch.setattr("assistant.daemon.PipeWireCapture", SpyPW)

    call(config.socket_path, "ptt.start", {"target": "explicit"}, timeout=5.0)
    call(config.socket_path, "ptt.stop", {"wait_s": 10.0}, timeout=15.0)
    call(config.socket_path, "ptt.start", {}, timeout=5.0)
    call(config.socket_path, "ptt.stop", {"wait_s": 10.0}, timeout=15.0)
    daemon.config.raw["capture"]["mic_target"] = ""
    call(config.socket_path, "ptt.start", {}, timeout=5.0)
    call(config.socket_path, "ptt.stop", {"wait_s": 10.0}, timeout=15.0)

    assert created == ["explicit", "from-capture", "from-meeting"]


# ===========================================================================
# 2. Doctor's live level check — bytes + peak, honest off-Fedora
# ===========================================================================
def test_pcm_peak_and_live_level_check_report_signal_and_silence(monkeypatch):
    peaky = struct.pack(f"<{SAMPLE_RATE}h", *([16000] * SAMPLE_RATE))
    assert pcm_peak(b"") == 0.0
    assert pcm_peak(peaky) == pytest.approx(16000 / 32768, abs=0.001)

    monkeypatch.setattr("assistant.capture.tool_available", lambda name: True)

    def noisy_runner(cmd, capture_output=False, timeout=None):
        return SimpleNamespace(returncode=0, stdout=peaky, stderr=b"")

    level = live_level_check("alsa_input.test.Mic1__source", seconds=1.0,
                             runner=noisy_runner)
    assert level["available"] is True
    assert level["target"] == "alsa_input.test.Mic1__source"
    assert level["bytes"] == len(peaky)
    assert level["peak"] > 0.4
    assert level["signal"] is True

    def silent_runner(cmd, capture_output=False, timeout=None):
        return SimpleNamespace(returncode=0, stdout=b"\x00\x00" * 16000,
                               stderr=b"")

    level = live_level_check(None, seconds=1.0, runner=silent_runner)
    assert level["signal"] is False, "digital silence must not read as signal"
    assert level["peak"] == 0.0

    def dead_runner(cmd, capture_output=False, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout)

    level = live_level_check(None, seconds=1.0, runner=dead_runner)
    assert level["available"] is True
    assert level["bytes"] == 0
    assert level["signal"] is False


def test_live_level_check_is_honest_without_pw_record():
    level = live_level_check(None, seconds=0.1)
    # This sandbox has no pw-record: the probe must say so, never guess.
    if level.get("available"):
        assert level["bytes"] >= 0
    else:
        assert "pw-record" in level["reason"]


# ===========================================================================
# Bug 7 helper used by `assist meeting setup` — node discovery shape
# ===========================================================================
WPCTL_SAMPLE = """\
PipeWire 'pipewire-0' [0.3.80, user@fedora, cookie:123]
 └─ Clients:
Audio
 ├─ Devices:
 │      46. Built-in Audio                    
 ├─ Sinks:
 │  *   53. Built-in Audio Analog Stereo       [vol: 0.50]
 │      71. HDMI / DisplayPort                 
 └─ Sources:
 │  *   54. Digital Microphone (Digital Microphone) [vol: 0.80]
 │      55. Built-in Audio Analog Stereo       
"""


def test_list_pw_nodes_parses_wpctl_status(monkeypatch):
    monkeypatch.setattr("assistant.capture.tool_available", lambda name: True)

    def runner(cmd, capture_output=False, text=False, timeout=None):
        return SimpleNamespace(returncode=0, stdout=WPCTL_SAMPLE, stderr="")

    nodes = list_pw_nodes(runner=runner)
    sources = [n for n in nodes if n["kind"] == "source"]
    sinks = [n for n in nodes if n["kind"] == "sink"]
    assert {"id": 54, "name": "Digital Microphone (Digital Microphone)",
            "kind": "source", "is_default": True} in sources
    assert any(n["id"] == 53 and n["is_default"] for n in sinks)
    assert all(set(n) == {"id", "name", "kind", "is_default"} for n in nodes)


def test_list_pw_nodes_is_empty_not_broken_off_fedora():
    # No wpctl in this sandbox: an honest empty list, never an exception
    # (the BUG 7 crash was exactly an exception here).
    assert list_pw_nodes(runner=lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not run"))) == []
