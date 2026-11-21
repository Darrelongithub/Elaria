import struct
import tempfile
import unittest
from pathlib import Path

from assistant.capture import SoftLimiter, pcm_peak, write_wav


class TestSoftLimiter(unittest.TestCase):
    def test_full_scale_is_limited_before_wav_write(self):
        import wave

        raw = struct.pack('<4h', -32768, 32767, 100, -100)
        limiter = SoftLimiter()
        processed = limiter.apply(raw)
        levels = limiter.last_frame_levels
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'take.wav'
            write_wav(path, [processed])
            with wave.open(str(path), 'rb') as take:
                saved = take.readframes(4)
        self.assertEqual(levels['raw_peak'], 1.0)
        self.assertEqual(levels['limited_samples'], 2)
        self.assertEqual(levels['processed_peak'], pcm_peak(saved))
        self.assertLessEqual(pcm_peak(saved), 0.89)
        self.assertEqual(saved[4:], raw[4:])

    def test_quiet_pcm_is_unchanged(self):
        raw = struct.pack('<3h', -100, 0, 100)
        limiter = SoftLimiter()
        processed = limiter.apply(raw)
        levels = limiter.last_frame_levels
        self.assertEqual(processed, raw)
        self.assertEqual(levels, {
            'raw_peak': 100 / 32768,
            'processed_peak': 100 / 32768,
            'limited_samples': 0,
        })
