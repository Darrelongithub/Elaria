"""BH-K23: the keyword model was scored on ONE 30 ms frame.

`WakeGuard.feed()` called `score_window(frame)` with the single frame
just received, while the pre-wake ring already held up to 2 s of audio
and the model's contract is a *window*. No real keyword spotter can
recognise a phrase in 30 ms — hardware arming would never fire (or
would need a model trained on single frames, contradicting the
`score_window` name and the ring's existence).

Fix: score the trailing `[hotword] keyword_window_s` (default 1.0 s)
slice of the ring, ending with the frame just fed.
"""

from __future__ import annotations

from assistant.wake_guard import WakeGuard

FRAME = b"\x01\x00" * 480          # 30 ms @ 16 kHz s16le = 960 bytes
LOUD_TAIL = b"\xff\x7f" * 480      # distinctive final frame


class RecordingModel:
    name = "onnx"

    def __init__(self):
        self.windows: list[bytes] = []

    def score_window(self, pcm: bytes) -> float:
        self.windows.append(pcm)
        return 0.0                 # never trigger; just observe


def _armed_guard(model: RecordingModel) -> WakeGuard:
    guard = WakeGuard(settings={"ring_window_s": 2.0,
                                "pending_window_s": 2.5,
                                "keyword_window_s": 1.0})
    guard.arm(keyword_model=model)
    return guard


def test_keyword_scores_a_growing_window_not_one_frame():
    model = RecordingModel()
    guard = _armed_guard(model)
    for _ in range(10):            # 0.3 s of audio
        guard.feed(FRAME)
    lengths = [len(w) for w in model.windows]
    assert lengths[-1] == 10 * len(FRAME), lengths
    assert lengths[0] == len(FRAME)            # window grows from the start
    assert lengths == sorted(lengths)


def test_keyword_window_is_capped_and_trailing():
    model = RecordingModel()
    guard = _armed_guard(model)
    for _ in range(50):            # 1.5 s > 1.0 s window
        guard.feed(FRAME)
    guard.feed(LOUD_TAIL)
    last = model.windows[-1]
    assert len(last) == 32000                  # exactly 1.0 s
    assert last[-len(LOUD_TAIL):] == LOUD_TAIL  # ends with the newest frame
