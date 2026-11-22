"""Speaker verification seam and pinned ONNX ECAPA-TDNN backend (Stage B).

The production scorer is WeSpeaker ECAPA-TDNN (`voxceleb_ECAPA512_LM.onnx`),
pinned by artifact ID, upstream revision, and SHA-256 in `model_registry.py`
and verified on load by `model_pins.resolve_pinned_artifact("speaker")`.

Two execution modes share `EcapaCommandScorer` so existing `[hotword]
ecapa_cmd` wiring and subprocess tests keep working unchanged:

* **Pinned ONNX mode** (`command="onnx"` / `"pinned"` / `"onnx:<path>"` /
  `"<path>.onnx"`, or `model_path=...`): resolves the `"speaker"` artifact via
  `model_pins.resolve_pinned_artifact`, verifies SHA-256 on load from memory,
  extracts 80-bin Kaldi Hamming log-Mel filterbanks with per-utterance cepstral
  mean subtraction (`16 kHz` `s16le`), runs `onnxruntime` (`CPUExecutionProvider`),
  and returns cosine similarity against the enrolled 192-d owner reference.
* **External command mode** (`command="<binary> [args]"`): passes the utterance
  in an anonymous RAM `memfd` (`/proc/self/fd/N`) and parses JSON
  `{"embedding": [...]}` or `{"score": float}`.

Fail-closed invariants:
* `available()` is `True` in ONNX mode ONLY when the artifact resolves, its
  SHA-256 matches the registry pin, and `onnxruntime` loads the verified graph.
* `score_owner()` returns `None` — never a default, never `1.0`, never "assume
  owner" — whenever anything is missing, unverified, silent, malformed, or
  marked non-live/replayed.
"""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Protocol

from .model_pins import PinMismatch, resolve_pinned_artifact

ONNX_COMMANDS: frozenset[str] = frozenset({"onnx", "pinned", "builtin", "wespeaker"})
_LIVE_SOURCES: frozenset[str] = frozenset({"mic", "pipewire", "live"})

_ECAPA_SAMPLE_RATE = 16000
_FRAME_LENGTH_SAMPLES = 400   # 25 ms @ 16 kHz
_FRAME_SHIFT_SAMPLES = 160    # 10 ms @ 16 kHz
_FFT_SIZE = 512
_NUM_MEL_BINS = 80
_PREEMPH_COEFF = 0.97
_KALDI_EPS = 1.1920929e-07

_FBANK_CACHE: tuple[object, object] | None = None


class VoiceprintUnavailable(RuntimeError):
    """No usable verification path — fail closed (knock, never listen)."""


class VoiceScorer(Protocol):
    name: str

    def available(self) -> bool: ...

    def score_owner(self, pcm: bytes) -> float | None: ...


def _wav_s16(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw s16le mono PCM in a minimal WAV container for the backend."""
    data_size = len(pcm)
    header = (
        b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVE"
        + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1,
                                sample_rate, sample_rate * 2, 2, 16)
        + b"data" + struct.pack("<I", data_size)
    )
    return header + pcm


def _valid_vector(values: object) -> list[float] | None:
    if not isinstance(values, (list, tuple)) or not values:
        return None
    out: list[float] = []
    for item in values:
        if isinstance(item, bool):
            return None
        try:
            val = float(item)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(val):
            return None
        out.append(val)
    return out


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def load_reference(path: str | os.PathLike | None) -> list[float] | None:
    """Owner enrollment embedding: JSON list, `{"embedding": [...]}`, or `{"centroid": [...]}`."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if isinstance(payload, dict):
        payload = (
            payload.get("embedding")
            if "embedding" in payload
            else payload.get("centroid")
        )
    return _valid_vector(payload)


def _fbank_constants():
    """Lazily build and cache the Kaldi Hamming window and 80-bin Mel matrix."""
    global _FBANK_CACHE
    if _FBANK_CACHE is not None:
        return _FBANK_CACHE
    import numpy as np

    idx = np.arange(_FRAME_LENGTH_SAMPLES, dtype=np.float32)
    hamming = (
        0.54 - 0.46 * np.cos(2.0 * np.pi * idx / (_FRAME_LENGTH_SAMPLES - 1))
    ).astype(np.float32)

    num_fft_bins = _FFT_SIZE // 2
    nyquist = 0.5 * _ECAPA_SAMPLE_RATE
    mel_low = 1127.0 * math.log(1.0 + 20.0 / 700.0)
    mel_high = 1127.0 * math.log(1.0 + nyquist / 700.0)
    mel_delta = (mel_high - mel_low) / (_NUM_MEL_BINS + 1)

    bins = np.arange(_NUM_MEL_BINS, dtype=np.float32)[:, None]
    left_mel = mel_low + bins * mel_delta
    center_mel = mel_low + (bins + 1.0) * mel_delta
    right_mel = mel_low + (bins + 2.0) * mel_delta

    fft_bin_width = float(_ECAPA_SAMPLE_RATE) / float(_FFT_SIZE)
    freq = fft_bin_width * np.arange(num_fft_bins, dtype=np.float32)[None, :]
    mel = 1127.0 * np.log(1.0 + freq / 700.0)

    up_slope = (mel - left_mel) / (center_mel - left_mel)
    down_slope = (right_mel - mel) / (right_mel - center_mel)
    mel_bins = np.maximum(
        np.float32(0.0), np.minimum(up_slope, down_slope)
    ).astype(np.float32)
    # Pad Nyquist bin (index 256) with zeros to match Kaldi / torchaudio.compliance.kaldi.
    mel_padded = np.pad(mel_bins, ((0, 0), (0, 1)), mode="constant").T.copy()
    _FBANK_CACHE = (hamming, mel_padded)
    return _FBANK_CACHE


def kaldi_fbank_80(pcm: bytes, *, sample_rate: int = _ECAPA_SAMPLE_RATE):
    """Compute WeSpeaker-compatible `(T, 80)` Kaldi log-Mel fbank + CMN features.

    Matches `wenet-e2e/wespeaker` (`int16`-scaled waveform, 25 ms Hamming
    window, 10 ms shift, `snip_edges=True`, DC removal, 0.97 pre-emphasis,
    80 triangular Mel bins `20..8000 Hz`, natural log, per-utterance mean
    subtraction `norm_mean=True, norm_var=False`).
    """
    import numpy as np
    from numpy.lib.stride_tricks import as_strided

    if sample_rate != _ECAPA_SAMPLE_RATE:
        raise VoiceprintUnavailable(
            f"ECAPA ONNX frontend requires {_ECAPA_SAMPLE_RATE} Hz audio, got {sample_rate} Hz"
        )
    raw = memoryview(pcm)
    if len(raw) == 0 or (len(raw) % 2) != 0:
        raise VoiceprintUnavailable("PCM buffer must be non-empty s16le bytes")
    n_samples = len(raw) // 2
    if n_samples < _FRAME_LENGTH_SAMPLES:
        raise VoiceprintUnavailable(
            f"clip too short for a 25 ms ECAPA frame ({n_samples} < {_FRAME_LENGTH_SAMPLES} samples)"
        )

    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32)
    if not bool(np.any(samples != 0.0)):
        raise VoiceprintUnavailable("silent clip (all-zero PCM)")

    num_frames = 1 + (n_samples - _FRAME_LENGTH_SAMPLES) // _FRAME_SHIFT_SAMPLES
    itemsize = samples.strides[0]
    frames = as_strided(
        samples,
        shape=(num_frames, _FRAME_LENGTH_SAMPLES),
        strides=(_FRAME_SHIFT_SAMPLES * itemsize, itemsize),
    ).copy()

    # 1. Remove per-frame DC offset, then pre-emphasise (replicate left pad), then window.
    hamming, mel_matrix = _fbank_constants()
    frames -= frames.mean(axis=1, keepdims=True)
    frames[:, 1:] -= np.float32(_PREEMPH_COEFF) * frames[:, :-1]
    frames[:, 0] *= np.float32(1.0 - _PREEMPH_COEFF)
    frames *= hamming

    # 2. Power spectrum via 512-point real FFT -> 80-bin Mel energies -> natural log.
    spec = np.fft.rfft(frames, n=_FFT_SIZE, axis=1)
    power = (spec.real.astype(np.float32) ** 2) + (spec.imag.astype(np.float32) ** 2)
    mel_energy = np.maximum(power @ mel_matrix, np.float32(_KALDI_EPS))
    feats = np.log(mel_energy).astype(np.float32)

    # 3. Per-utterance cepstral mean normalisation (WeSpeaker CMN: mean only).
    feats -= feats.mean(axis=0, keepdims=True)
    return feats


def _parse_onnx_target(
    command: str,
    model_path: str | os.PathLike | None,
) -> tuple[bool, Path | None]:
    """Return `(is_onnx_mode, explicit_path_or_None)`."""
    if model_path is not None:
        return True, Path(model_path)
    if not command:
        return False, None
    lowered = command.lower()
    if lowered in ONNX_COMMANDS:
        return True, None
    if lowered.startswith("onnx:"):
        target = command[5:].strip()
        return True, (Path(target) if target else None)
    if not any(ch.isspace() for ch in command) and lowered.endswith(".onnx"):
        return True, Path(command)
    return False, None


class EcapaCommandScorer:
    """ECAPA speaker scorer supporting pinned ONNX inference and subprocess commands.

    No command / missing or corrupt ONNX artifact / wrong SHA-256 ->
    `available() == False` and `score_owner() -> None` (fail closed).
    """

    name = "ecapa"

    def __init__(
        self,
        command: str | None = None,
        reference: list[float] | None = None,
        *,
        timeout_s: float = 5.0,
        sample_rate: int = _ECAPA_SAMPLE_RATE,
        model_path: str | os.PathLike | None = None,
        expected_sha256: str | None = None,
        repo_root: str | os.PathLike | None = None,
        config=None,
    ):
        self.command = str(command or "").strip()
        self.reference = reference
        self.timeout_s = float(timeout_s)
        self.sample_rate = int(sample_rate)
        self.last_error: str | None = None

        self._onnx_mode, self._onnx_path = _parse_onnx_target(
            self.command, model_path
        )
        self._expected_sha256 = expected_sha256
        self._repo_root = repo_root
        self._config = config
        self._session: object | None = None
        self._loaded_sha256: str | None = None
        self._input_name: str = "feats"
        self._output_name: str = "embs"

    def _ensure_onnx_session(self):
        """Verify the pinned ONNX artifact on disk and return a CPU InferenceSession."""
        if self.sample_rate != _ECAPA_SAMPLE_RATE:
            self._session = None
            self._loaded_sha256 = None
            self.last_error = (
                f"ONNX ECAPA requires {_ECAPA_SAMPLE_RATE} Hz audio, "
                f"got {self.sample_rate} Hz"
            )
            return None
        try:
            verified = resolve_pinned_artifact(
                "speaker",
                path=self._onnx_path,
                repo_root=self._repo_root,
                expected_sha256=self._expected_sha256,
                config=self._config,
            )
        except PinMismatch as exc:
            self._session = None
            self._loaded_sha256 = None
            self.last_error = str(exc)
            return None

        if self._session is not None and self._loaded_sha256 == verified.sha256:
            return self._session

        try:
            import numpy as _np  # noqa: F401
            import onnxruntime as ort
        except ImportError as exc:
            self._session = None
            self._loaded_sha256 = None
            self.last_error = f"onnxruntime unavailable: {exc}"
            return None

        try:
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            session = ort.InferenceSession(
                verified.data,
                sess_options=opts,
                providers=["CPUExecutionProvider"],
            )
            inputs = session.get_inputs()
            outputs = session.get_outputs()
            if not inputs or not outputs:
                raise VoiceprintUnavailable("ONNX graph has no inputs/outputs")
            in_shape = inputs[0].shape
            out_shape = outputs[0].shape
            if len(in_shape) != 3 or in_shape[2] != _NUM_MEL_BINS:
                raise VoiceprintUnavailable(
                    f"unexpected ECAPA input shape {in_shape!r}"
                )
            if len(out_shape) != 2 or out_shape[1] != 192:
                raise VoiceprintUnavailable(
                    f"unexpected ECAPA embedding shape {out_shape!r}"
                )
            self._input_name = inputs[0].name
            self._output_name = outputs[0].name
            self._session = session
            self._loaded_sha256 = verified.sha256
            return session
        except Exception as exc:
            self._session = None
            self._loaded_sha256 = None
            self.last_error = f"failed to load verified ONNX speaker model: {exc}"
            return None

    def available(self) -> bool:
        self.last_error = None
        if self._onnx_mode:
            return self._ensure_onnx_session() is not None
        if not self.command:
            self.last_error = "no ECAPA command configured"
            return False
        return True

    def embed_pcm(self, pcm: bytes) -> list[float] | None:
        """Extract a 192-d speaker embedding from 16 kHz mono s16le PCM, or `None`."""
        self.last_error = None
        if not self._onnx_mode:
            self.last_error = "embed_pcm requires ONNX ECAPA mode"
            return None
        if not pcm:
            self.last_error = "empty clip"
            return None
        session = self._ensure_onnx_session()
        if session is None:
            return None
        try:
            import numpy as np

            feats = kaldi_fbank_80(pcm, sample_rate=self.sample_rate)
            raw_out = session.run(
                [self._output_name], {self._input_name: feats[None, :, :]}
            )[0]
            emb_arr = np.asarray(raw_out, dtype=np.float64).reshape(-1)
            if emb_arr.size != 192 or not bool(np.all(np.isfinite(emb_arr))):
                self.last_error = "non-finite or invalid ONNX embedding"
                return None
            norm = float(np.linalg.norm(emb_arr))
            if norm <= 0.0 or not math.isfinite(norm):
                self.last_error = "zero-norm ONNX embedding"
                return None
            return [float(x) for x in emb_arr.tolist()]
        except VoiceprintUnavailable as exc:
            self.last_error = str(exc)
            return None
        except Exception as exc:
            self.last_error = f"ONNX ECAPA inference failed: {exc}"
            return None

    def embed_wav(self, wav_path: str | os.PathLike) -> list[float] | None:
        """Read a 16 kHz mono 16-bit PCM WAV file and return its 192-d embedding."""
        self.last_error = None
        try:
            with wave.open(str(wav_path), "rb") as handle:
                if (
                    handle.getnchannels() != 1
                    or handle.getsampwidth() != 2
                    or handle.getframerate() != _ECAPA_SAMPLE_RATE
                ):
                    self.last_error = (
                        "WAV must be 16000 Hz mono 16-bit PCM for ECAPA embedding"
                    )
                    return None
                pcm = handle.readframes(handle.getnframes())
        except (OSError, wave.Error) as exc:
            self.last_error = f"cannot read WAV {wav_path}: {exc}"
            return None
        return self.embed_pcm(pcm)

    def _run_backend(self, wav: bytes) -> subprocess.CompletedProcess:
        """Invoke the backend with the clip in RAM only (BH-K27).

        Wake audio must never touch a persistent filesystem (the ring is
        anonymous mmap for the same reason). The clip travels in a
        memfd the child inherits and opens as /proc/self/fd/N; the
        /dev/shm named file is only a non-Linux fallback.
        """
        argv = self.command.split()
        if hasattr(os, "memfd_create"):
            fd = os.memfd_create("elaria-wake-clip")
            try:
                os.write(fd, wav)
                os.lseek(fd, 0, os.SEEK_SET)
                return subprocess.run(
                    [*argv, f"/proc/self/fd/{fd}"],
                    capture_output=True, text=True, timeout=self.timeout_s,
                    check=False, pass_fds=(fd,))
            finally:
                os.close(fd)
        shm = "/dev/shm" if os.path.isdir("/dev/shm") else None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                         dir=shm) as tmp:
            tmp.write(wav)
            wav_path = tmp.name
        try:
            return subprocess.run(
                [*argv, wav_path],
                capture_output=True, text=True, timeout=self.timeout_s,
                check=False)
        finally:
            os.unlink(wav_path)

    def _score_against_reference(self, embedding: object) -> float | None:
        emb = _valid_vector(embedding)
        if emb is None:
            self.last_error = "no valid embedding in payload"
            return None
        ref = _valid_vector(self.reference)
        if ref is None:
            self.last_error = "no owner reference embedding enrolled"
            return None
        if len(emb) != len(ref):
            self.last_error = (
                f"reference dimension mismatch: embedding={len(emb)}, "
                f"reference={len(ref)}"
            )
            return None
        na = math.sqrt(sum(x * x for x in emb))
        nb = math.sqrt(sum(y * y for y in ref))
        if na == 0.0 or nb == 0.0:
            self.last_error = "zero-norm speaker embedding"
            return None
        score = sum(x * y for x, y in zip(emb, ref)) / (na * nb)
        if not math.isfinite(score):
            self.last_error = "non-finite cosine score"
            return None
        return float(score)

    def score_owner(
        self,
        pcm: bytes,
        *,
        source: str = "mic",
        replayed: bool = False,
        live_mic: bool = True,
    ) -> float | None:
        self.last_error = None
        src = str(source or "").strip().lower()
        if replayed or not live_mic or src not in _LIVE_SOURCES:
            self.last_error = (
                f"recorded or replayed audio rejected (source={src!r}, "
                f"live_mic={live_mic}, replayed={replayed})"
            )
            return None
        if not pcm:
            self.last_error = "empty clip"
            return None

        if self._onnx_mode:
            ref = _valid_vector(self.reference)
            if ref is None:
                # Still verify model availability so last_error reflects pin failures first.
                if self._ensure_onnx_session() is None:
                    return None
                self.last_error = "no owner reference embedding enrolled"
                return None
            emb = self.embed_pcm(pcm)
            if emb is None:
                return None
            return self._score_against_reference(emb)

        if not self.command:
            self.last_error = "no ECAPA command configured"
            return None
        try:
            proc = self._run_backend(_wav_s16(pcm, self.sample_rate))
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_error = f"scoring command failed: {exc}"
            return None
        if proc.returncode != 0:
            self.last_error = (proc.stderr or "scoring command error")[:200]
            return None
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            self.last_error = "scoring command printed no JSON"
            return None
        if not isinstance(payload, dict):
            self.last_error = "scoring command printed non-object JSON"
            return None
        if "score" in payload:
            try:
                score = float(payload["score"])
            except (TypeError, ValueError):
                self.last_error = "bad score payload"
                return None
            if isinstance(payload["score"], bool) or not math.isfinite(score):
                self.last_error = "bad score payload"
                return None
            return score
        if "embedding" not in payload:
            self.last_error = "no embedding in payload"
            return None
        return self._score_against_reference(payload.get("embedding"))
