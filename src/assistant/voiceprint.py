"""Speaker verification seam for the wake-knock model (Stage B).

The production scorer is ECAPA-TDNN. Training one is explicitly OUT of
scope (docs/hotword-training-plan.md), and this repo ships NO fabricated
model: there is no built-in scorer that invents confidence numbers. What is
delivered here is the seam the wake gate consumes:

* `EcapaCommandScorer` — runs an external scoring command (the owner's
  installed ECAPA backend) on a WAV of the wake utterance and reads either a
  JSON `{"embedding": [...]}` (cosine against the enrolled owner reference)
  or a JSON `{"score": 0.0-1.0}` directly. Every failure mode — no command
  configured, binary missing, bad output, missing reference — returns
  `None` (fail closed: the gate may knock, never listen).
* `ScriptedScorer` is NOT here. Test doubles live in the tests, where they
  belong.

The scorer name (not its internals) is what `assist hotword status` exposes
as `scorer`, so the owner can see exactly which verification path is live.
"""

from __future__ import annotations

import json
import math
import os
import struct
import subprocess
import tempfile
from typing import Protocol


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
    """Owner enrollment embedding: a JSON list of floats (or {"embedding": [...]}.)."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if isinstance(payload, dict):
        payload = payload.get("embedding")
    if not isinstance(payload, list) or not payload:
        return None
    try:
        return [float(x) for x in payload]
    except (TypeError, ValueError):
        return None


class EcapaCommandScorer:
    """ECAPA backend as an external command. No command → unavailable → None.

    Contract for `command`: invoked as `command <clip.wav>`; prints one JSON
    object on stdout, either `{"embedding": [floats]}` or `{"score": float}`.
    This is deliberately a subprocess seam: the ECAPA stack (onnxruntime /
    numpy / the trained model) is hardware-side software, not a stdlib
    dependency of the daemon, and no half-working imitation of it ships here.
    """

    name = "ecapa"

    def __init__(self, command: str | None,
                 reference: list[float] | None = None, *,
                 timeout_s: float = 5.0, sample_rate: int = 16000):
        self.command = str(command or "").strip()
        self.reference = reference
        self.timeout_s = float(timeout_s)
        self.sample_rate = sample_rate
        self.last_error: str | None = None

    def available(self) -> bool:
        return bool(self.command)

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

    def score_owner(self, pcm: bytes) -> float | None:
        self.last_error = None
        if not self.command:
            self.last_error = "no ECAPA command configured"
            return None
        if not pcm:
            self.last_error = "empty clip"
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
                return float(payload["score"])
            except (TypeError, ValueError):
                self.last_error = "bad score payload"
                return None
        embedding = payload.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            self.last_error = "no embedding in payload"
            return None
        if self.reference is None:
            self.last_error = "no owner reference embedding enrolled"
            return None
        try:
            return cosine([float(x) for x in embedding], self.reference)
        except (TypeError, ValueError):
            self.last_error = "bad embedding payload"
            return None
