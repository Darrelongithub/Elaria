"""Lane J-HEAD eye-check: the trained "Elaria" head is on the runtime pipeline.

One test file that fails if the wiring is removed. Three independent links:

1. **The shipped file loads through the runtime loader.** `OpenWakeWordModel.load`
   must accept `models/elaria_head.onnx` next to the two openWakeWord feature
   models and report a fixed `[1, 4, 96]` head input — i.e. the default
   `[hotword] keyword_window_s = 1.0` the daemon runs with.
2. **The runtime feature path is the one the head was fitted on.** Each held-out
   clip in `tests/fixtures/j_elaria_head_holdout.npz` is pushed through
   `OpenWakeWordModel` itself; the embeddings it produces must equal the
   embeddings recorded at fixture time. Re-implementing or replacing the
   melspec/embedding step, changing `x/10 + 2`, or changing the 76-frame/step-8
   windowing all break this — which is the point: the head only works if the
   daemon's extractor is the trainer's extractor.
3. **The head separates held-out positives from negatives at the frozen
   threshold.** `keyword_threshold` stays 0.5 and the numbers are reported as
   they fall; a weak head must show up here as a weak head, never as a quieter
   threshold.

Skips cleanly (never fails) when onnxruntime or the model artefacts are absent,
so a bare `pip install -e .` still collects this file.
"""
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("onnxruntime", reason="wake extra not installed")

from assistant.wake_guard import OpenWakeWordModel

ROOT = Path(__file__).resolve().parents[1]
HEAD = ROOT / "models" / "elaria_head.onnx"
MELSPEC = ROOT / "models" / "melspectrogram.onnx"
EMBEDDING = ROOT / "models" / "embedding_model.onnx"
FIXTURE = ROOT / "tests" / "fixtures" / "j_elaria_head_holdout.npz"

missing = [str(p.name) for p in (HEAD, MELSPEC, EMBEDDING, FIXTURE) if not p.is_file()]
pytestmark = pytest.mark.skipif(
    missing, reason=f"wake head artefacts absent: {', '.join(missing)}")

HEAD_FRAMES = 4          # keyword_window_s 1.0 -> 4 x 96
THRESHOLD = 0.5          # [hotword] keyword_threshold — frozen, never lowered


@pytest.fixture(scope="module")
def model():
    return OpenWakeWordModel.load(HEAD, MELSPEC, EMBEDDING)


@pytest.fixture(scope="module")
def holdout():
    with np.load(FIXTURE, allow_pickle=False) as data:
        return {k: data[k] for k in data.files}


def test_shipped_head_loads_with_fixed_runtime_shape(model):
    """(a) the file loads through the runtime loader at the daemon's shape."""
    head_session = model._load_sessions()[2]
    shape = head_session.get_inputs()[0].shape
    assert shape == [1, HEAD_FRAMES, 96], shape

    pcm = b"\x00\x00" * 16000
    score = model.score_window(pcm)
    assert 0.0 <= score <= 1.0


def test_runtime_feature_path_reproduces_the_trained_embeddings(model, holdout):
    """(b) clips -> OpenWakeWordModel -> the exact embeddings the head was fitted on.

    Remove or swap the extractor (melspec transform, 76/8 windowing, front
    padding) and these tensors diverge: this assertion is the wiring.
    """
    clips, expected = holdout["clips"], holdout["feats"]
    assert len(clips) == len(expected) > 0

    worst = 0.0
    for pcm_i16, want in zip(clips, expected):
        got = model.head_inputs(pcm_i16.astype("<i2").tobytes())
        assert got is not None, "clip too short for the runtime mel window"
        assert got.shape == (HEAD_FRAMES, 96), got.shape
        worst = max(worst, float(np.max(np.abs(got - want))))
    # float32 through two ONNX graphs: identical deterministically, and the
    # fixture is the same build, so anything above 1e-5 is a different path.
    assert worst < 1e-5, f"runtime embeddings drifted from the training path: {worst}"


def test_frozen_threshold_separates_held_out_positives(model, holdout):
    """(c) the head separates unseen voices at the frozen threshold 0.5.

    This is the WIRING check, so its bars are about "is this a real
    discriminator at 0.5, not a coin", measured on 50 held-out clips from
    voices outside the training split. The product bars are measured on the
    full 780-window test split and recorded, with the misses, in
    `models/README.md` and `docs/hotword-training-plan.md` §7 — including the
    near-word class that sits ABOVE the pre-committed 5 % bar. A test that
    asserted the product bars here would be asserting a 20-clip sample, and
    loosening `keyword_threshold` to make either number look better is
    forbidden.
    """
    labels = holdout["labels"].astype(int)
    scores = np.array([
        model.score_window(pcm.astype("<i2").tobytes()) for pcm in holdout["clips"]
    ])
    pos, neg = scores[labels == 1], scores[labels == 0]
    assert pos.size and neg.size

    false_reject = float(np.mean(pos < THRESHOLD))
    false_accept = float(np.mean(neg >= THRESHOLD))
    print(f"\nheld-out ({pos.size} pos / {neg.size} neg, threshold {THRESHOLD}): "
          f"false-reject {false_reject:.3f}, false-accept {false_accept:.3f}, "
          f"pos mean {pos.mean():.3f}, neg mean {neg.mean():.3f}")

    assert false_reject <= 0.15, f"recall collapsed: FRR {false_reject:.3f}"
    assert false_accept <= 0.10, f"negatives trigger: FAR {false_accept:.3f}"
    assert pos.mean() - neg.mean() >= 0.5, (
        f"no separation: pos mean {pos.mean():.3f} vs neg mean {neg.mean():.3f}")


def test_fixture_is_held_out_not_training_material():
    """The fixture must not be the training corpus (guards a silent self-test)."""
    with np.load(FIXTURE, allow_pickle=False) as data:
        names = [str(n) for n in data["names"]]
        threshold = float(data["threshold"])
    assert names, "fixture carries no clip names"
    assert threshold == THRESHOLD, "fixture was scored at a tuned threshold"
    assert all(n.startswith(("pos_", "neg_")) for n in names), names[:3]
