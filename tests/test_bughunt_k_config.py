"""BH-K20/K21/K24 — config surface honesty.

K20: keys the code reads but DEFAULTS/example never declared
    ([organise] tier1_batch_size/tier2_batch_size, [hotword] sample_rate,
    unit_path) — doctor called them "unknown" when owners set them, and
    nobody could discover them.
K21: meeting.start ignored [capture] mic_target although the example
    documents it as the mic node (dictate/hotword honoured it).
K24: a malformed config.toml produced a raw traceback from every CLI
    invocation (load_config ran before main's try, unwrapped).
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import ClassVar

from assistant import capture as capture_mod
from assistant.capture import SimulatedCapture
from assistant.cli import main
from assistant.config import DEFAULTS
from assistant.daemon import Daemon

REPO = Path(__file__).resolve().parents[1]


def test_keys_the_code_reads_are_declared_and_documented():
    example = (REPO / "config.toml.example").read_text()
    for section, key, default in (
            ("organise", "tier1_batch_size", 50),
            ("organise", "tier2_batch_size", 10),
            ("hotword", "sample_rate", 16000)):
        assert DEFAULTS[section][key] == default, f"[{section}] {key} undeclared"
        assert key in example, f"[{section}] {key} undocumented"
    assert DEFAULTS["hotword"]["unit_path"] == ""
    assert "unit_path" in example


class _RecordingCapture(SimulatedCapture):
    seen: ClassVar[list] = []

    def __init__(self, target=None, **kwargs):
        type(self).seen.append(target)
        super().__init__(speech_frames=100_000, frame_ms=30, realtime=True)


def _meeting_targets(config, monkeypatch) -> list:
    _RecordingCapture.seen = []
    monkeypatch.setattr(capture_mod, "PipeWireCapture", _RecordingCapture)
    daemon = Daemon(config)
    try:
        async def drive():
            await daemon._meeting_start({})
            task = daemon._meeting["task"]
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            daemon._meeting = None

        asyncio.run(drive())
    finally:
        daemon.store.close()
    return _RecordingCapture.seen


def test_meeting_mic_falls_back_to_capture_mic_target(config, monkeypatch):
    config.raw["capture"]["mic_target"] = "alsa_input.usb-mic"
    config.raw["meeting"]["mic_target"] = ""
    seen = _meeting_targets(config, monkeypatch)
    assert seen[0] == "alsa_input.usb-mic", (
        "the documented [capture] mic must serve meetings too, not the "
        "PipeWire default")


def test_meeting_mic_target_overrides_capture(config, monkeypatch):
    config.raw["capture"]["mic_target"] = "alsa_input.usb-mic"
    config.raw["meeting"]["mic_target"] = "alsa_input.builtin"
    seen = _meeting_targets(config, monkeypatch)
    assert seen[0] == "alsa_input.builtin"


def test_malformed_config_is_a_one_line_error_exit_2(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "config.toml"
    bad.write_text("[gemini\nmode = ")
    monkeypatch.setenv("ASSIST_CONFIG", str(bad))
    rc = main(["status"])
    err = capsys.readouterr().err
    assert rc == 2
    assert str(bad) in err, f"the error must name the file; got: {err!r}"
    assert "Traceback" not in err
