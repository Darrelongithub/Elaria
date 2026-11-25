#!/usr/bin/env python3
"""Wake detector benchmark — the D-DETECTOR acceptance is three numbers.

    python3 scripts/wake_bench.py --head models/elaria_head.onnx \
        --melspec models/melspectrogram.onnx \
        --embedding models/embedding_model.onnx [--seconds 60]

Prints exactly: frames/sec, realtime factor, peak RSS (MB). Synthetic
16 kHz PCM in, no mic, no network. Run it on the target laptop; a
sandbox number is not a hardware claim.
"""
import argparse
import resource
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assistant.wake_guard import OpenWakeWordModel  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--head", required=True)
    ap.add_argument("--melspec", required=True)
    ap.add_argument("--embedding", required=True)
    ap.add_argument("--seconds", type=float, default=30.0,
                    help="seconds of synthetic audio to score")
    args = ap.parse_args()

    model = OpenWakeWordModel.load(args.head, args.melspec, args.embedding)
    # 2 s window (the ring cap), loud synthetic speech-like PCM.
    window = b"".join(struct.pack("<h", 8000 if i % 2 else -8000)
                      for i in range(32000))
    frames = 0
    started = time.perf_counter()
    deadline = started + args.seconds
    while time.perf_counter() < deadline:
        model.score_window(window)
        frames += 1
    elapsed = time.perf_counter() - started
    # Each scored window stands for one 30 ms hop of always-on audio in
    # the guard's current window-per-frame contract.
    audio_seconds = frames * 0.03
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    print(f"frames/sec {frames / elapsed:.1f}")
    print(f"realtime_factor {audio_seconds / elapsed:.2f}")
    print(f"peak_rss_mb {peak_mb:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
