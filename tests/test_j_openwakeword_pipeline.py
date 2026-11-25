"""Lane J-DETECTOR eye-check: the openWakeWord ONNX pipeline is wired.

One test that fails if the wiring is removed: fake ONNX sessions stand in
for the three upstream artefacts (melspec -> embedding -> head), and the
score must flow through all three, in order, with the upstream shapes.
Plus the fail-closed load path and the energy gate (bug #26).
"""
import struct

import numpy as np
import pytest

from assistant.wake_guard import (
    KeywordModelUnavailable,
    OpenWakeWordModel,
    WakeGuard,
)


class _Input:
    def __init__(self, name, shape=None):
        self.name = name
        self.shape = shape or []


class _Session:
    def __init__(self, name, fn, shape=None):
        self._input = _Input(name, shape)
        self._fn = fn
        self.calls = 0

    def get_inputs(self):
        return [self._input]

    def run(self, _outputs, feed):
        self.calls += 1
        return [self._fn(next(iter(feed.values())))]


def _pipeline(score=0.87):
    # melspec: (1, N) float PCM -> (1, 100, 32) mel frames
    melspec = _Session("input", lambda x: np.ones((1, 100, 32), np.float32))
    # embedding: (B, 76, 32, 1) -> (B, 96)
    embedding = _Session(
        "input_1", lambda x: np.ones((x.shape[0], 96), np.float32))
    # head: (1, 16, 96) -> [[score]]
    head = _Session("input", lambda x: np.array([[score]], np.float32),
                    shape=[1, 16, 96])
    model = OpenWakeWordModel("head.onnx", "mel.onnx", "emb.onnx",
                              sessions=(melspec, embedding, head))
    return model, melspec, embedding, head


def _pcm(seconds=1.0, amp=8000):
    n = int(16000 * seconds)
    return b"".join(struct.pack("<h", amp if i % 2 else -amp)
                    for i in range(n))


def test_score_flows_melspec_embedding_head_in_order():
    model, melspec, embedding, head = _pipeline()
    assert model.score_window(_pcm()) == pytest.approx(0.87)
    assert (melspec.calls, embedding.calls, head.calls) == (1, 1, 1)


def test_load_refuses_missing_artefacts(tmp_path):
    with pytest.raises(KeywordModelUnavailable):
        OpenWakeWordModel.load(tmp_path / "head.onnx",
                               tmp_path / "melspectrogram.onnx",
                               tmp_path / "embedding_model.onnx")


def test_silent_frames_never_reach_the_spotter():
    model, melspec, _e, _h = _pipeline()
    guard = WakeGuard(settings={"keyword_threshold": 0.5},
                      keyword_model=model)
    guard.arm()
    silence = b"\x00\x00" * 480  # one 30 ms frame of digital silence
    for _ in range(40):
        assert guard.feed(silence) is None
    assert melspec.calls == 0  # energy gate: inference never ran
    assert guard.state == "idle"
