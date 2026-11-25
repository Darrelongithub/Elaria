"""Wake-knock model — the owner-approved package (2026-10-20).

State machine (§1 of the package spec)::

    idle -> triggered -> verifying -> attending | wake_knock
         -> listening -> endpointing -> closed

The one rule everything else exists to protect: **an acoustic/phrase hit
NEVER grants command authority.** A hit only moves the machine to
`triggered`; authority comes later, from the voiceprint verdict or from a
human accept. Fail closed everywhere: missing embedding, missing scorer,
missing keyword model, stalled capture — none of these lead to listening.

VERIFY THE COMMAND, NEVER THE WAKE WORD (round J, 2026-11-22). Measured on
the real pinned ECAPA model: a ~0.6 s wake-length window scores 0.341 /
0.588 for the enrolled speaker (0/12 sliding windows reach 0.75), while a
2.5 s command window scores 0.793 / 0.842; impostors score 0.043 / 0.013.
A wake-length window therefore CANNOT be a verification unit.

* The wake hit ANSWERS NOTHING, SAYS NOTHING, VERIFIES NOTHING. It opens
  the ring and arms the pending window. The scorer runs only on command
  audio after that window closes, and only if it holds at least
  `MIN_WINDOW_S` (1.75 s) of command audio. Below that there is **no
  scoring call at all** — not a low score, no call.
* High-confidence owner -> ATTENDING -> listening. The dual-use pending
  buffer is INHERITED as the head of the command utterance (the owner never
  repeats themselves).
* Fewer than 1.75 s of command audio -> SILENT DISCARD and idle. Nothing is
  scored, and nothing opens the microphone: a window too short to verify is
  too short to listen on.
* Uncertain / non-owner / no embedding on a REAL command window -> SILENT
  DISCARD. No knock, no reply, no acknowledgement, no speech of any kind;
  the pending buffer is zeroed, one metadata-only record is written, and
  the machine returns to idle. This is a security rule: an impostor must
  not be able to tell they were heard. `ecapa_uncertain` is a reporting
  band only — anything below `ecapa_high` is NO authority.
* Replayed / recorded / non-live windows (the `showoff.py` BH-H15 rule)
  are rejected exactly like an impostor: silence, no knock, buffer zeroed.
* Acoustic arming REFUSES without a real keyword model (.onnx). The
  `--unsafe-energy-test` flag exists for plumbing tests only and can never
  open command listening.

Endpointing for this path is the SAME `SilenceLadder` dictation uses
(transcribe.py) — one ladder, no second drifting copy.

Privacy: pre-wake ring <= 2.0 s and the pending window are RAM-only
(wake_buffers.py, MADV_DONTDUMP). No pre-wake audio in any log. Wake clips
are OFF by default; opt-in saves are <= 5 s, 0700, 24 h purged, and
failed-verify audio is never saved unless the explicit debug flag is set.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .capture import frame_rms
from .config import DEFAULTS
from .cost import iso_now
from .ipc import IpcPrincipal
from .transcribe import SilenceLadder
from .wake_buffers import SAMPLE_RATE, PendingWindow, PreWakeRing, bytes_for

# -- states ----------------------------------------------------------------
IDLE = "idle"
TRIGGERED = "triggered"
VERIFYING = "verifying"
ATTENDING = "attending"
WAKE_KNOCK = "wake_knock"
LISTENING = "listening"
ENDPOINTING = "endpointing"
CLOSED = "closed"
STALLED = "stalled"

ATTEND_INHERIT = "command_head"        # sub-state detail: pending inherited
ATTEND_AWAIT = "awaiting_command"      # sub-state detail: fresh capture coming

# -- verdicts / dispositions ----------------------------------------------
CONF_HIGH = "high"
CONF_UNCERTAIN = "uncertain"
CONF_NONE = "none"

# Stage B input. Round J: the ONLY verified input is COMMAND audio captured
# after the wake hit. A wake-length clip is never scored (`wake_too_short`).
STAGE_COMMAND = "command_window"        # >= MIN_WINDOW_S of post-wake command audio
STAGE_UNVERIFIED = "wake_too_short"     # < MIN_WINDOW_S: NO scoring call was made
STAGE_REJECTED = "replay_refused"       # replayed / recorded / non-live

DISP_INHERITED = "inherited"
DISP_DISCARDED = "discarded"

OUTCOME_ATTENDING = "attending"
OUTCOME_WAKE_KNOCK = "wake_knock"
OUTCOME_DISCARDED = "discarded"
OUTCOME_IGNORED = "ignored"
OUTCOME_REFUSED_ENERGY = "refused_energy_test"
OUTCOME_STALLED = "stalled"

# Round J defect 1: the minimum command window that may be scored at all.
#
# MEASURED, not guessed (2026-11-22, pinned voxceleb_ECAPA512_LM.onnx,
# reference = centroid of spk1_snt1..3, post-wake windows = the clip from
# 0.6 s onward — which is exactly what verify() scores):
#
#   window   spk1_snt4   spk1_snt5 (held out)   margin over 0.75   impostors
#   0.60 s     0.5456        0.6240                -0.126            0.152
#   0.80 s     0.5600        0.6682                -0.082            0.165
#   1.00 s     0.6591        0.7200                -0.030            0.159
#   1.25 s     0.6942        0.7460                -0.004            0.137
#   1.50 s     0.7608        0.7815                +0.032            0.074
#   1.60 s     0.7812        0.8083                +0.058            0.075
#   2.00 s      n/a          0.8364                +0.086            0.053
#
# The round-3 order asked for "the shortest duration that clears 0.75 with
# >= 0.05 margin on the held-out owner utterance, and < 0.50 on every
# impostor". Measured, that literal minimum is ~1.56 s (spk1_snt5 crosses
# +0.05 there on a 0.02 s grid; impostors never exceed 0.166 at any
# duration, so their half of the criterion holds everywhere).
#
# 1.75 s is chosen ABOVE that, for one measured reason: at 1.50 / 1.60 /
# 1.70 s one or two of the 5–11 OWNER windows in a 0.1 s sliding sweep still
# land at 0.736–0.744 — below the 0.75 gate. A floor that clears its margin
# only at one fixed offset is a coincidence of where the utterance was cut.
# 1.75 s is the shortest duration at which EVERY owner window measured (both
# utterances, every 0.1 s start) clears 0.75.
#
# Known limitation, stated rather than hidden: spk1_snt4 never reaches +0.05
# of margin at ANY duration its 1.93 s of post-wake audio allows (1.75 s:
# 0.7795, +0.0295). The floor was not tuned to flatter that utterance. It
# clears the gate, it does not clear the margin target, and
# test_j_min_window_is_the_measured_sweep_minimum asserts exactly that.
#
# Direction of the change: UP (1.5 -> 1.75). Fail closed. At 1.5 s the
# held-out margin was +0.032 — a coin flip on the next utterance.
MIN_WINDOW_S = 1.75

# Round J defect 3: the BH-H15 replay rule, applied to the closed command
# window. `showoff.py` refuses `source != mic` / `live_mic=False` /
# `replayed=True` / a previously accepted `audio_sha256`; WakeGuard refuses
# the same window here before any scoring call.
LIVE_SOURCES = frozenset({"mic", "pipewire", "live"})

TRIGGER_EVENT = "wake_trigger"


class WakeGuardError(RuntimeError):
    """Refusal: the requested transition is not allowed (fail closed)."""


# -- keyword model seam ----------------------------------------------------
class KeywordModelUnavailable(RuntimeError):
    pass


class OnnxKeywordModel:
    """A REAL keyword spotter backed by an .onnx model file.

    No model ships in this repo (training is out of scope). The class loads
    the owner's model through onnxruntime if installed; anything missing is
    an honest refusal, never a silent energy fallback.
    """

    name = "onnx"

    def __init__(self, path: str):
        self.path = path

    @classmethod
    def load(cls, path: str | os.PathLike | None) -> OnnxKeywordModel:
        path = str(path or "").strip()
        if not path:
            raise KeywordModelUnavailable(
                "wake word paused: no keyword model configured ([hotword] keyword_model). "
                "Acoustic arming needs a real .onnx keyword model.")
        if not Path(path).is_file():
            raise KeywordModelUnavailable(
                f"wake word paused: no keyword model (.onnx) at {path!r} — acoustic "
                "arming will not run on an energy/loudness fallback.")
        try:
            import onnxruntime  # noqa: F401  # hardware-side extra
        except (ImportError, OSError) as exc:
            raise KeywordModelUnavailable(
                "wake word paused: onnxruntime is unavailable — "
                "run `uv sync --extra voice` before loading the .onnx keyword "
                "model; energy fallback is not a wake path") from exc
        return cls(path)

    def score_window(self, pcm: bytes) -> float:
        """Keyword confidence for a PCM window (0..1)."""
        import onnxruntime

        session = getattr(self, "_session", None)
        if session is None:
            session = onnxruntime.InferenceSession(
                self.path, providers=["CPUExecutionProvider"])
            self._session = session
        # Feature contract belongs to the owner's model; the honest default
        # is raw s16 -> float32 frames, shape (1, N). A model that needs
        # mel features must ship with its own extractor (hardware check).
        import array

        samples = array.array("h")
        samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
        feed = [s / 32768.0 for s in samples]
        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: [feed]})
        flat = outputs[0]
        try:
            while isinstance(flat, list) and flat and isinstance(flat[0], list):
                flat = flat[0]
            return max(0.0, min(1.0, float(flat[0])))
        except (TypeError, ValueError, IndexError) as exc:
            raise KeywordModelUnavailable(
                f"keyword model output unusable: {exc}") from exc


class OpenWakeWordModel:
    """openWakeWord v0.5.1 ONNX pipeline: melspec -> embedding -> head.

    This is NOT the `openwakeword` Python package (which hard-requires
    tflite-runtime — killed on evidence, see HANDOFF). It runs the three
    upstream ONNX artefacts directly on onnxruntime, CPU only, no network:

      1. ``melspectrogram.onnx``  raw float32 PCM (1, N) -> mel frames
         (upstream transform ``x / 10 + 2`` applied to the output);
      2. ``embedding_model.onnx`` windows of 76 mel frames, step 8,
         -> 96-dim speech embeddings;
      3. the trained head (``keyword_model``) over the last N embeddings
         (N from the head's fixed input shape, else 16) -> score 0..1.

    A hit from this model grants nothing: it only opens the pending
    command window, which ECAPA verifies exactly as before. Short
    embedding contexts are front-padded by repeating the first embedding
    (the upstream feature buffer is likewise pre-filled, never zeros of
    authority). Sessions are injectable for tests; production loads real
    files or refuses honestly — never an energy fallback.
    """

    name = "openwakeword-onnx"
    MEL_WINDOW = 76
    MEL_STEP = 8
    DEFAULT_HEAD_FRAMES = 16

    def __init__(self, head_path, melspec_path, embedding_path,
                 sessions=None):
        self.path = str(head_path)
        self.melspec_path = str(melspec_path)
        self.embedding_path = str(embedding_path)
        self._sessions = sessions  # (melspec, embedding, head) for tests

    @classmethod
    def load(cls, head_path, melspec_path, embedding_path):
        for label, raw in (("keyword_model", head_path),
                           ("keyword_melspec_model", melspec_path),
                           ("keyword_embedding_model", embedding_path)):
            path = str(raw or "").strip()
            if not path or not Path(path).is_file():
                raise KeywordModelUnavailable(
                    f"wake word paused: no {label} (.onnx) at {path!r} — "
                    "openWakeWord arming needs melspectrogram.onnx + "
                    "embedding_model.onnx + a trained head; energy "
                    "fallback is not a wake path")
        try:
            import onnxruntime  # noqa: F401
        except (ImportError, OSError) as exc:
            raise KeywordModelUnavailable(
                "wake word paused: onnxruntime is unavailable — run "
                "`uv sync --extra voice`; energy fallback is not a wake "
                "path") from exc
        return cls(head_path, melspec_path, embedding_path)

    def _load_sessions(self):
        if self._sessions is None:
            import onnxruntime

            def make(path):
                return onnxruntime.InferenceSession(
                    str(path), providers=["CPUExecutionProvider"])

            self._sessions = (make(self.melspec_path),
                              make(self.embedding_path),
                              make(self.path))
        return self._sessions

    @staticmethod
    def _input_name(session, fallback):
        try:
            return session.get_inputs()[0].name
        except Exception:
            return fallback

    @staticmethod
    def _head_frames(head_session, np):
        try:
            shape = head_session.get_inputs()[0].shape
            if len(shape) >= 2 and isinstance(shape[1], int) and shape[1] > 0:
                return int(shape[1])
        except Exception:
            pass
        return OpenWakeWordModel.DEFAULT_HEAD_FRAMES

    def _melspec_frames(self, samples, np):
        """PCM float32 (N,) -> mel frames (T, 32), upstream `x/10 + 2` applied.

        Public to the trainer through `embedding_frames` so training and
        inference share ONE feature path — a head fitted on a second,
        re-implemented extractor is a green test on a dead product.
        None when the window is too short to hold a single mel window.
        """
        melspec_s = self._load_sessions()[0]
        spec = melspec_s.run(
            None, {self._input_name(melspec_s, "input"):
                   np.asarray(samples, np.float32)[None, :]})[0]
        spec = np.squeeze(spec) / 10.0 + 2.0
        if spec.ndim != 2 or spec.shape[0] < self.MEL_WINDOW:
            return None
        return spec

    def _embedding_frames(self, samples, np):
        """PCM float32 (N,) -> speech embeddings (K, 96); None if too short."""
        spec = self._melspec_frames(samples, np)
        if spec is None:
            return None
        windows = [spec[i:i + self.MEL_WINDOW]
                   for i in range(0, spec.shape[0] - self.MEL_WINDOW + 1,
                                  self.MEL_STEP)]
        batch = np.array(windows, dtype=np.float32)[..., None]
        embedding_s = self._load_sessions()[1]
        embeddings = np.squeeze(embedding_s.run(
            None, {self._input_name(embedding_s, "input_1"): batch})[0])
        return np.atleast_2d(embeddings).astype(np.float32)

    def embedding_frames(self, pcm: bytes):
        """The trainer's view of the runtime feature path (no head involved).

        `scripts/train_elaria_head.py` calls exactly this, so the embeddings
        it fits a head on are the embeddings the daemon will feed that head.
        """
        import numpy as np

        samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2],
                                dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return None
        return self._embedding_frames(samples, np)

    def head_inputs(self, pcm: bytes):
        """PCM window -> the (N, 96) head input, front-padded like inference."""
        import numpy as np

        samples = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2],
                                dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return None
        embeddings = self._embedding_frames(samples, np)
        if embeddings is None:
            return None
        head_s = self._load_sessions()[2]
        n = self._head_frames(head_s, np)
        if embeddings.shape[0] < n:
            pad = np.repeat(embeddings[:1], n - embeddings.shape[0], axis=0)
            embeddings = np.concatenate([pad, embeddings], axis=0)
        return embeddings[-n:].astype(np.float32)

    def score_window(self, pcm: bytes) -> float:
        """Keyword confidence for a PCM window (0..1)."""
        import numpy as np

        feed_in = self.head_inputs(pcm)
        if feed_in is None:
            return 0.0
        head_s = self._load_sessions()[2]
        feed = feed_in[None, :, :].astype(np.float32)
        out = head_s.run(
            None, {self._input_name(head_s, "input"): feed})[0]
        try:
            return max(0.0, min(1.0, float(np.asarray(out).flatten()[0])))
        except (TypeError, ValueError, IndexError) as exc:
            raise KeywordModelUnavailable(
                f"keyword model output unusable: {exc}") from exc


class EnergyTestModel:
    """Plumbing-only stand-in behind `--unsafe-energy-test`.

    It can move the pipeline for tests. It is NOT a wake path: every trigger
    it raises is tagged `unsafe_energy`, and the guard refuses to open
    command listening for such triggers — directly or via knock accept.
    """

    name = "unsafe-energy-test"

    def __init__(self, threshold: float = 0.05):
        self.threshold = float(threshold)

    def score_window(self, pcm: bytes) -> float:
        return frame_rms(pcm)


# -- authority gate --------------------------------------------------------
class AuthorityGate:
    """confidence: high | uncertain | none. Only high + verified may attend.

    Round J defect 4: `uncertain` is a REPORTING band, never a permission.
    The two thresholds keep their meanings (`ecapa_high` = authority,
    `ecapa_uncertain` = the lower edge of the ambiguous band) and neither is
    lowered here. `may_attend()` is the only authority question the guard
    asks, and it answers True for exactly one band.
    """

    def __init__(self, high: float = 0.75, uncertain: float = 0.5):
        self.high = float(high)
        self.uncertain = float(uncertain)

    def evaluate(self, score: float | None, *, verified: bool) -> str:
        if score is None or not verified:
            return CONF_NONE
        if score >= self.high:
            return CONF_HIGH
        if score >= self.uncertain:
            return CONF_UNCERTAIN
        return CONF_NONE

    def may_attend(self, score: float | None, *, verified: bool) -> bool:
        """True iff this is authority. Ambiguity is not a weak yes."""
        return self.evaluate(score, verified=verified) == CONF_HIGH


# -- replay guard (BH-H15, applied to the wake path) -----------------------
class ReplayGuard:
    """The `showoff.py` BH-H15 rule for the closed command window.

    A window is live only if the capture stack says so (`source` in
    `mic`/`pipewire`/`live`, `live_mic=True`, `replayed=False`) AND its exact
    bytes have not already been accepted as a live command window. Both
    checks are cheap and deterministic; the store-backed variant
    (`set_state`/`get_state`) survives a daemon restart.

    A replay is not an error and not a knock: it is silence, exactly like an
    impostor (defect 3).
    """

    STATE_KEY = "wake_guard.accepted_window_hashes"

    def __init__(self, store=None, *, keep: int = 100):
        self.store = store
        self.keep = int(keep)

    @staticmethod
    def window_hash(pcm: bytes) -> str:
        return hashlib.sha256(bytes(pcm or b"")).hexdigest()

    def _accepted(self) -> list[str]:
        if self.store is None:
            return getattr(self, "_memory", [])
        raw = self.store.get_state(self.STATE_KEY) or "[]"
        try:
            values = json.loads(raw)
        except ValueError:
            return []
        return [v for v in values if isinstance(v, str)] if isinstance(values, list) else []

    def _remember(self, digest: str) -> None:
        values = (self._accepted() + [digest])[-self.keep:]
        if self.store is None:
            self._memory = values
            return
        self.store.set_state(self.STATE_KEY, json.dumps(values))

    def refusal(self, pcm: bytes, *, source: str = "mic",
                replayed: bool = False, live_mic: bool = True,
                audio_sha256: str | None = None) -> str | None:
        """`None` = live and fresh; otherwise the refusal reason (metadata only)."""
        src = str(source or "").strip().lower()
        if replayed or not live_mic or src not in LIVE_SOURCES:
            return (f"recorded or replayed audio rejected (source={src!r}, "
                    f"live_mic={live_mic}, replayed={replayed})")
        digest = str(audio_sha256 or "").strip() or self.window_hash(pcm)
        if digest in self._accepted():
            return "replayed audio clip detected — a used window is not fresh speech"
        return None

    def remember(self, pcm: bytes, *, audio_sha256: str | None = None) -> str:
        """Record a window as accepted-live. Returns the digest used."""
        digest = str(audio_sha256 or "").strip() or self.window_hash(pcm)
        self._remember(digest)
        return digest


class OutboundSink:
    """Every user-visible emission point for a wake decision, in one object.

    The guard's silence contract (defect 2) is only checkable if there is one
    place to look: a reply, an acknowledgement, speech and the knock all
    arrive here. Nothing in `verify()`/`_settle()` writes to it on any
    outcome — the only writer is `_raise_wake_knock`, the owner-prompt path —
    so a test can assert that an unrecognised voice leaves it empty.
    """

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def reply(self, text: str, **meta) -> None:
        self.events.append(("reply", {"text": text, **meta}))

    def ack(self, text: str = "", **meta) -> None:
        self.events.append(("ack", {"text": text, **meta}))

    def speak(self, text: str, **meta) -> None:
        self.events.append(("speech", {"text": text, **meta}))

    def knock(self, **meta) -> None:
        self.events.append(("knock", dict(meta)))

    def bytes_out(self) -> int:
        """Bytes a real speaker/console would have produced. Zero or bust."""
        return sum(len(str(payload.get("text", ""))) for _, payload in self.events)

    def __len__(self) -> int:
        return len(self.events)


# -- watchdog --------------------------------------------------------------
class Watchdog:
    """A silent forever-recording is forbidden. Stall -> disarm + visible state."""

    def __init__(self, stall_timeout_s: float = 2.0):
        self.stall_timeout_s = float(stall_timeout_s)
        self.last_frame_at: float | None = None
        self.state = "ok"

    def note_frame(self, now: float | None = None) -> None:
        self.last_frame_at = time.monotonic() if now is None else float(now)
        if self.state != "stalled":
            self.state = "ok"

    def last_frame_age_ms(self, now: float | None = None) -> float | None:
        if self.last_frame_at is None:
            return None
        ref = time.monotonic() if now is None else float(now)
        return round(max(0.0, (ref - self.last_frame_at) * 1000.0), 1)

    def check(self, now: float | None = None) -> bool:
        """True exactly once per stall: the caller must disarm."""
        if self.last_frame_at is None:
            return False
        ref = time.monotonic() if now is None else float(now)
        if ref - self.last_frame_at > self.stall_timeout_s:
            if self.state != "stalled":
                self.state = "stalled"
                return True
            return False
        return False


# -- wake clips (opt-in) ---------------------------------------------------
class WakeClipStore:
    """Opt-in wake-clip saving. OFF by default. Failed-verify audio is never
    saved unless `debug_save_failed` is set explicitly."""

    def __init__(self, directory: str | os.PathLike | None, *,
                 enabled: bool = False, retention_h: float = 24.0,
                 max_s: float = 5.0, debug_save_failed: bool = False,
                 sample_rate: int = SAMPLE_RATE, now=None):
        self.directory = Path(directory).expanduser() if directory else None
        self.enabled = bool(enabled)
        self.retention_h = float(retention_h)
        self.max_s = float(max_s)
        self.debug_save_failed = bool(debug_save_failed)
        self.sample_rate = sample_rate
        self.now = now or time.time

    def _ensure_dir(self) -> Path | None:
        if self.directory is None:
            return None
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, 0o700)
        except OSError:
            pass
        return self.directory

    def may_save(self, *, verified: bool) -> bool:
        return self.enabled and (verified or self.debug_save_failed)

    def save(self, pcm: bytes, *, verified: bool) -> str | None:
        if not self.may_save(verified=verified):
            return None
        directory = self._ensure_dir()
        if directory is None:
            return None
        clip = pcm[: int(self.max_s * self.sample_rate) * 2]
        name = f"wake-{int(self.now() * 1000)}.pcm"
        path = directory / name
        path.write_bytes(clip)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self.purge_expired()
        return str(path)

    def purge_expired(self) -> int:
        if self.directory is None or not self.directory.is_dir():
            return 0
        cutoff = self.now() - self.retention_h * 3600.0
        removed = 0
        for path in self.directory.glob("wake-*.*"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                continue
        return removed

    def purge(self) -> int:
        """`assist hotword purge` — everything, now."""
        if self.directory is None or not self.directory.is_dir():
            return 0
        removed = 0
        for path in self.directory.glob("wake-*.*"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed


# -- listen session --------------------------------------------------------
@dataclass
class ListenSession:
    """An opened command-listening window.

    `head` is the inherited pending buffer (verified owner, speechful branch)
    or empty (fresh capture). `source(inner)` wraps the live capture so the
    head is the FIRST frames of the utterance and live audio continues
    seamlessly after it; endpointing is one SilenceLadder over the whole.
    """

    session_id: str
    head: bytes
    fresh: bool
    ladder: SilenceLadder
    state: str = LISTENING

    def source(self, inner):
        return PrefilledSource(self.head, inner)


class PrefilledSource:
    """Head-first frame iterator over a live capture (see ListenSession)."""

    def __init__(self, head: bytes, inner, *, frame_bytes: int = 960):
        self.head = bytes(head or b"")
        self.inner = inner
        self.frame_bytes = int(frame_bytes)

    @property
    def target(self):
        return getattr(self.inner, "target", None)

    async def frames(self):
        for start in range(0, len(self.head), self.frame_bytes):
            yield self.head[start:start + self.frame_bytes]
        if self.inner is not None:
            async for frame in self.inner.frames():
                yield frame


@dataclass
class TriggerRecord:
    """Metadata only. This is the whole log — no audio, ever.

    Round J defect 2: a discarded window's ECAPA score stays on the record
    object for an operator/debugger, but is NOT in `as_dict()` — the copy
    that reaches `status()`, the console or any user-visible channel carries
    no score for a security-silent decision.
    """

    ts: str
    keyword_score: float
    ecapa_score: float | None
    confidence: str
    outcome: str
    knock_id: int | None = None
    stage_b_input: str = STAGE_UNVERIFIED
    pending_speech_s: float = 0.0
    pending_disposition: str = DISP_DISCARDED
    clip_saved: bool = False
    unsafe_energy: bool = False
    phrase: str = "Elaria"

    @property
    def discarded(self) -> bool:
        return self.outcome in (OUTCOME_DISCARDED, OUTCOME_IGNORED)

    def as_dict(self) -> dict:
        return {
            "ts": self.ts,
            "keyword_score": round(float(self.keyword_score), 4),
            "ecapa_score": (None if self.discarded or self.ecapa_score is None
                            else round(float(self.ecapa_score), 4)),
            "confidence": self.confidence,
            "outcome": self.outcome,
            "knock_id": self.knock_id,
            "stage_b_input": self.stage_b_input,
            "pending_speech_s": round(float(self.pending_speech_s), 3),
            "pending_disposition": self.pending_disposition,
            "clip_saved": bool(self.clip_saved),
            "unsafe_energy": bool(self.unsafe_energy),
            "phrase": self.phrase,
        }


def speech_seconds(pcm: bytes, *, speech_rms: float = 0.01,
                   sample_rate: int = SAMPLE_RATE, frame_s: float = 0.03) -> float:
    """Speechful duration of a PCM blob (the insufficient-speech branch)."""
    frame_bytes = max(1, int(sample_rate * frame_s) * 2)
    total = 0.0
    for start in range(0, len(pcm), frame_bytes):
        chunk = pcm[start:start + frame_bytes]
        if chunk and frame_rms(chunk) >= speech_rms:
            total += frame_s
    return total


def crash_safety_report(unit_path: str | os.PathLike | None = None) -> dict:
    """limit_core + madv_dontdump, exposed so 'crash leaves nothing' is
    checkable, not believed."""
    candidates = [unit_path] if unit_path else []
    candidates += [
        Path(__file__).resolve().parents[2] / "systemd" / "assistant.service",
        Path.home() / ".config" / "systemd" / "user" / "assistant.service",
    ]
    limit_core = False
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                text = Path(candidate).read_text(encoding="utf-8")
            except OSError:
                continue
            if any(line.strip() == "LimitCORE=0" for line in text.splitlines()):
                limit_core = True
                break
    ring = PreWakeRing(0.01)
    madv = ring.madv_dontdump
    ring.zero()
    return {
        "limit_core": limit_core,
        "limit_core_runtime": _runtime_core_limit(),
        "madv_dontdump": madv,
    }


def _runtime_core_limit() -> str:
    try:
        import resource

        soft, _hard = resource.getrlimit(resource.RLIMIT_CORE)
        return "0" if soft == 0 else ("unlimited" if soft < 0 else str(soft))
    except Exception:
        return "unknown"


# -- the guard -------------------------------------------------------------
@dataclass
class WakeGuard:
    """Wake-authority state machine. Frames in, decisions out, nothing
    persisted but trigger metadata.

    Round J: a hit grants nothing and answers nothing; authority comes only
    from a command window of >= 1.5 s that scores >= `ecapa_high` on the
    real scorer. Below that, or replayed, or unscoreable: silence, zeroized
    buffers, one metadata record, back to idle.
    """

    settings: dict = field(default_factory=dict)
    store: object = None
    initiative: object = None
    class_mode: object = None            # callable -> bool
    showoff: object = None               # .status() -> {"active": bool}
    scorer: object = None                # VoiceScorer
    keyword_model: object = None
    phrase: str = "Elaria"
    now: object = None
    # SILENCE HOTFIX rule 2/3: the energy floor below which audio is silence
    # ([voice] silence_floor). The wake path's endpointing is the SAME shared
    # SilenceLadder, so it gets the same floor: below-floor room/call noise
    # earns no check-in, and an unspoken-into listen window closes silently.
    silence_floor: float = DEFAULTS["voice"]["silence_floor"]

    def __post_init__(self):
        if self.now is None:
            self.now = iso_now
        s = self.settings
        self.ring = PreWakeRing(min(2.0, float(s.get("ring_window_s", 2.0))))
        # BH-K23: the keyword model scores a trailing WINDOW of the ring,
        # not the single 30 ms frame just received (no spotter can hear a
        # phrase in one frame). Capped by the ring residence (<= 2.0 s).
        self.keyword_window_bytes = bytes_for(min(
            2.0, max(0.05, float(s.get("keyword_window_s", 1.0)))))
        self.pending = PendingWindow(float(s.get("pending_window_s", 2.5)))
        # Round J r3: the command window's close condition, named.
        #
        # HONEST SCOPE, because this is easy to overclaim: measured on a
        # 30 ms-frame stream, the old `pending.full` check already closed the
        # window on the filling frame — 84 frames = 2.52 s of audio, of which
        # exactly 2.50 s (80000 bytes) was scored. It did NOT capture past the
        # buffer, and it was not late by a frame. What was missing was a
        # CONDITION: the close was an emergent property of buffer rounding
        # plus a frame that happens to straddle the capacity, and there was no
        # way to ask "is this window due?".
        #
        # `window_close_s` is `pending.seconds` BY CONSTRUCTION — not the raw
        # config value — so the timer and the buffer can never disagree about
        # how long the window is (`PendingWindow` clamps its input to 2.0–3.0 s;
        # reading the unclamped config here would let a 1.0 s "window" close
        # before the buffer was ever full).
        #
        # It is audio time (sum of frame durations), not wall-clock: a stalled
        # capture must not age a window shut while holding no audio — the
        # watchdog owns stalls.
        self.window_close_s = float(self.pending.seconds)
        self._window_elapsed_s = 0.0
        self.gate = AuthorityGate(
            high=float(s.get("ecapa_high", 0.75)),
            uncertain=float(s.get("ecapa_uncertain", 0.5)))
        # Round J defect 1: `[hotword] pending_speech_threshold_s` no longer
        # selects a wake-audio verification stage; it only labels a short
        # command window (`pending_speech_s`) in the record. The hard floor
        # for ANY scoring call is MIN_WINDOW_S, in code, not in config.
        self.speechful_s = float(s.get("pending_speech_threshold_s", 0.5))
        self.speech_rms = float(s.get("speech_rms", 0.01))
        self.stall_timeout_s = float(s.get("stall_timeout_s", 2.0))
        # Round J defect 2: `[hotword] missing_embedding_action` used to be
        # able to raise a knock for an unrecognised voice. There is no
        # configuration that makes an impostor audible: the key is accepted
        # for config compatibility and never acts.
        self.missing_embedding_action = str(
            s.get("missing_embedding_action", "wake_knock"))
        self.clips = WakeClipStore(
            s.get("clip_dir"),
            enabled=bool(s.get("save_wake_clips", False)),
            retention_h=float(s.get("clip_retention_h", 24.0)),
            max_s=float(s.get("clip_max_s", 5.0)),
            debug_save_failed=bool(s.get("debug_save_failed", False)))
        self.watchdog = Watchdog(self.stall_timeout_s)
        self.state = IDLE
        self.attending_detail: str | None = None
        self.armed = False
        self.armed_with = "none"          # onnx | unsafe-energy-test | none
        self.last_trigger: TriggerRecord | None = None
        self.posture_error: str | None = None  # BH-K10: last failed posture probe
        self.session: ListenSession | None = None
        self._hit: dict = {}
        self._wake_clip: bytes = b""
        self._session_head: bytes = b""
        self._replay_guard = ReplayGuard(
            self.store if hasattr(self.store, "get_state")
            and hasattr(self.store, "set_state") else None)
        # Round J: silence for anything the guard decides not to answer.
        # Tests and the daemon may inject a recorder here; production never
        # writes to it, so every sentence below is a statement about the
        # code path, not about a mock.
        self.outbound = OutboundSink()

    # -- arming ------------------------------------------------------------
    def arm(self, *, unsafe_energy_test: bool = False,
            keyword_model=None) -> dict:
        """Arm the always-on path. Refuses without a real keyword model."""
        if unsafe_energy_test:
            self.keyword_model = keyword_model or EnergyTestModel()
            self.armed_with = EnergyTestModel.name
        else:
            model = keyword_model or self.keyword_model
            if model is None:
                # Lane J (2026-11-25): the 3-model openWakeWord pipeline is the
                # arming path when `[hotword] keyword_melspec_model` is set.
                # Before this, `arm()` only ever built `OnnxKeywordModel`, so
                # the documented melspec/embedding keys were read by nothing
                # and an OpenWakeWord head fed a *raw PCM* loader — the lane
                # was documented, tested in isolation, and unreachable here.
                melspec = str(self.settings.get("keyword_melspec_model") or "").strip()
                embedding = str(
                    self.settings.get("keyword_embedding_model") or "").strip()
                head = str(self.settings.get("keyword_model") or "").strip()
                if melspec or embedding:
                    if not (melspec and embedding and head):
                        missing = [name for name, value in (
                            ("keyword_melspec_model", melspec),
                            ("keyword_embedding_model", embedding),
                            ("keyword_model", head)) if not value]
                        raise KeywordModelUnavailable(
                            "wake word paused: the openWakeWord pipeline needs "
                            "all three model paths; missing "
                            + ", ".join(missing)
                            + ". There is no energy fallback and no half-armed "
                            "pipeline.")
                    model = OpenWakeWordModel.load(head, melspec, embedding)
                else:
                    model = OnnxKeywordModel.load(self.settings.get("keyword_model"))
            if not isinstance(model, OnnxKeywordModel) and \
                    getattr(model, "name", "") == EnergyTestModel.name:
                raise KeywordModelUnavailable(
                    "refused: energy scorer may not arm the wake path without "
                    "--unsafe-energy-test (and even then it can never open "
                    "command listening)")
            self.keyword_model = model
            self.armed_with = getattr(model, "name", "onnx")
        self.armed = True
        self.watchdog = Watchdog(self.stall_timeout_s)
        self.state = IDLE
        return self.status()

    def disarm(self, *, reason: str = "manual") -> dict:
        self.armed = False
        self._zero_buffers()
        self.state = STALLED if reason == "stalled" else CLOSED
        self.attending_detail = None
        self.session = None
        return self.status()

    def _zero_buffers(self) -> None:
        self.ring.zero()
        self.pending.zero()
        self._wake_clip = b""
        self._session_head = b""
        self._hit = {}
        self._window_elapsed_s = 0.0

    # -- frame path --------------------------------------------------------
    def _track_window_clock(self, frame: bytes) -> None:
        """Advance the command-window clock by the FRAME's duration.

        Audio time, not wall time: a 30 ms frame is 30 ms of window however
        long the capture took to deliver it, so a stalled source cannot age a
        window shut while holding no audio (the watchdog owns stalls).
        """
        if self.state in (TRIGGERED, VERIFYING):
            self._window_elapsed_s += len(frame) / float(SAMPLE_RATE * 2)
        else:
            self._window_elapsed_s = 0.0

    def window_due(self) -> bool:
        """True once the command window has been open for `window_close_s`.

        Round J r3: this is the close condition, and it is checked AFTER the
        frame is in the buffer, so the closing frame is part of the window.

        `pending.full` is kept as the backstop for the case where a single
        frame is longer than the remaining room and the clock is somehow
        behind the bytes. With the shipped config the two coincide (elapsed
        audio == buffer bytes); the timer exists so the condition is named
        and testable rather than emergent from buffer rounding.
        """
        if self.state not in (TRIGGERED, VERIFYING):
            return False
        return (self._window_elapsed_s >= self.window_close_s
                or self.pending.full)

    def note_frame(self, frame: bytes, now: float | None = None) -> None:
        """Always-on frame: ring + watchdog + (pending window while open)."""
        self.watchdog.note_frame(now)
        self.ring.append(frame)
        if self.state in (TRIGGERED, VERIFYING):
            self.pending.append(frame)
        self._track_window_clock(frame)

    def feed(self, frame: bytes, *, now: float | None = None) -> dict | None:
        """One always-on frame through ring, watchdog and the keyword model.

        A hit only OPENS the ring and arms the pending window (defect 1): the
        scorer is never consulted here — not on the frame, not on the wake
        clip, not on the trailing keyword window. After a hit, frames
        accumulate into the pending window; when the window TIMER expires
        (`window_close_s`, 2.5 s of audio) the command window closes and is
        verified. A hit whose stream ends first closes at whatever `verify()`
        finds, and a short window is never scored.

        Returns the `verify()` result dict on the frame that closes a window,
        so the daemon can act on ATTENDING; `None` on every other frame.

        The keyword model is consulted only while armed and never raises into
        the capture loop: a broken spotter is an honest no-hit.
        """
        self.note_frame(frame, now)
        if not self.armed or self.keyword_model is None:
            return None
        if self.state in (ATTENDING, LISTENING, ENDPOINTING):
            # The window is closed for good; a second hit may not reopen it
            # while listening is on offer.
            return None
        if self.state in (TRIGGERED, VERIFYING):
            if self.window_due():
                return self.verify()
            return None
        # Energy gate (bug #26): silence never reaches the spotter. The
        # frame is already in the ring, so a phrase that starts loud is
        # not clipped — only the inference is skipped.
        if frame_rms(frame) < self.speech_rms:
            return None
        window = self.ring.snapshot()[-self.keyword_window_bytes:] or frame
        try:
            score = float(self.keyword_model.score_window(window))
        except Exception:
            return None
        if isinstance(self.keyword_model, EnergyTestModel):
            threshold = getattr(self.keyword_model, "threshold", 0.05)
        else:
            threshold = float(self.settings.get("keyword_threshold", 0.5))
        if score < threshold:
            return None
        self.trigger(keyword_score=score,
                     unsafe_energy=isinstance(self.keyword_model,
                                              EnergyTestModel))
        if self.window_due():
            return self.verify()
        return None

    # -- state machine -----------------------------------------------------
    def trigger(self, *, keyword_score: float,
                wake_clip: bytes | None = None,
                unsafe_energy: bool = False) -> str:
        """Hit -> `triggered`. Still NO authority of any kind.

        Opens the ring and arms the pending window. It answers nothing, says
        nothing and verifies nothing. `wake_clip` is retained only so the
        existing call surface keeps working — no code path below ever scores
        it (defect 1).
        """
        if self.state in (TRIGGERED, VERIFYING):
            raise WakeGuardError(f"already {self.state}")
        self.state = TRIGGERED
        self.attending_detail = None
        self.session = None
        self._hit = {"keyword_score": float(keyword_score),
                     "unsafe_energy": bool(unsafe_energy)}
        self._wake_clip = (self.ring.snapshot() if wake_clip is None
                           else bytes(wake_clip))
        self.pending = PendingWindow(self.pending.seconds)
        # Round J r3: the window clock starts at the hit, not at the first
        # post-hit frame — a hit whose stream dies immediately is a window
        # that expires empty (and is then never scored), not one that hangs.
        self._window_elapsed_s = 0.0
        return self.state

    def verify(self, *, source: str = "mic", replayed: bool = False,
               live_mic: bool = True,
               audio_sha256: str | None = None) -> dict:
        """Verify the COMMAND window. Runs BEFORE any routing.

        Round J contract, in order:

        1. The wake clip is never scored (defect 1): the scorer sees the
           command window only, exactly as it was captured.
        2. A replayed / recorded / non-live window is a silent discard,
           exactly like an impostor (defect 3) — checked before any scoring
           call is even considered.
        3. Fewer than `MIN_WINDOW_S` (1.75 s) of command audio: **no scoring
           call at all**. Not a low score — no call. And no listening either:
           a window too short to verify is too short to open the microphone
           for, so this is a silent discard, not an invitation.
        4. Otherwise the scorer sees the command audio. `ecapa_high` grants
           ATTENDING; anything below it — including the `uncertain` band — is
           a silent discard (defects 2 and 4): no knock, no reply, no ack, no
           speech, pending buffer zeroed, one metadata record.
        """
        if self.state not in (TRIGGERED, VERIFYING):
            raise WakeGuardError(f"cannot verify from state {self.state!r}")
        self.state = VERIFYING
        self.pending.close()
        pending_pcm = self.pending.data()
        pending_speech_s = speech_seconds(pending_pcm,
                                          speech_rms=self.speech_rms)
        unsafe = bool(self._hit.get("unsafe_energy"))
        score: float | None = None

        # -- defect 3: BH-H15 replay rule, before any scoring call ----------
        refusal = self._replay_guard.refusal(
            pending_pcm, source=source, replayed=replayed, live_mic=live_mic,
            audio_sha256=audio_sha256)
        if refusal is not None:
            return self._settle(
                confidence=CONF_NONE, score=None, stage=STAGE_REJECTED,
                pending_speech_s=pending_speech_s, unsafe=unsafe,
                outcome=OUTCOME_DISCARDED, detail=refusal)

        # -- defect 1: the minimum window is a hard floor -------------------
        if len(pending_pcm) < bytes_for(MIN_WINDOW_S):
            return self._settle(
                confidence=CONF_NONE, score=None, stage=STAGE_UNVERIFIED,
                pending_speech_s=pending_speech_s, unsafe=unsafe,
                outcome=(OUTCOME_REFUSED_ENERGY if unsafe
                         else OUTCOME_DISCARDED),
                detail="no command window: nothing was scored")

        # -- the one verification: command audio, never the wake word -------
        scout = self.scorer
        try:
            available = bool(scout is not None and scout.available())
        except Exception:
            available = False
        if available:
            try:
                value = scout.score_owner(pending_pcm)
            except Exception:
                value = None
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(float(value))):
                score = float(value)
        verified = score is not None
        confidence = self.gate.evaluate(score, verified=verified)

        if unsafe:
            # The plumbing flag may score, but it can never open listening.
            return self._settle(
                confidence=confidence, score=score, stage=STAGE_COMMAND,
                pending_speech_s=pending_speech_s, unsafe=True,
                outcome=OUTCOME_REFUSED_ENERGY,
                detail="energy trigger: ceiling is console, never voice")

        # -- authority is CONF_HIGH only; uncertain is NOT a weak yes -------
        if self.gate.may_attend(score, verified=verified):
            self._replay_guard.remember(pending_pcm, audio_sha256=audio_sha256)
            self.attending_detail = ATTEND_INHERIT
            self._session_head = pending_pcm
            return self._settle(
                confidence=confidence, score=score, stage=STAGE_COMMAND,
                pending_speech_s=pending_speech_s, unsafe=False,
                outcome=OUTCOME_ATTENDING,
                detail="owner verified on the command window")

        # -- defects 2 + 4: an unrecognised voice gets silence --------------
        return self._settle(
            confidence=confidence, score=score, stage=STAGE_COMMAND,
            pending_speech_s=pending_speech_s, unsafe=False,
            outcome=OUTCOME_DISCARDED, detail="not the owner: discarded silently")

    def _settle(self, *, confidence: str, score: float | None, stage: str,
                pending_speech_s: float, unsafe: bool, outcome: str,
                detail: str) -> dict:
        """One exit path: decide, zero, record metadata, answer nothing.

        Every branch of `verify()` lands here, so the silence contract lives
        in one place. Only `OUTCOME_ATTENDING` keeps audio (`_session_head`,
        and an opt-in wake clip for the owner's own verified speech); every
        other outcome zeroes the pending buffer and the wake clip, and emits
        **nothing** — no knock, no reply, no acknowledgement, no speech. The
        knock (`_raise_wake_knock`) is an owner-authentication prompt and has
        no call site from an unrecognised voice (defect 2).
        """
        if outcome == OUTCOME_ATTENDING:
            self.state = ATTENDING
            self.attending_detail = ATTEND_INHERIT
        elif outcome == OUTCOME_REFUSED_ENERGY:
            self.state = CLOSED
            self.attending_detail = None
            self.pending.zero()
            self._wake_clip = b""
            self._session_head = b""
        else:
            # Silent discard: zeroize, return to idle, emit metadata only.
            self.state = IDLE
            self.attending_detail = None
            self.session = None
            self.pending.zero()
            self._wake_clip = b""
            self._session_head = b""
            self._hit = {"keyword_score": self._hit.get("keyword_score", 0.0),
                         "unsafe_energy": unsafe}

        # The transition and any zeroing are complete before the opt-in clip
        # write: a save failure can never leave audio resident in a state that
        # was supposed to be silent.
        clip_path = None
        if outcome == OUTCOME_ATTENDING and self.clips.may_save(verified=True):
            clip_path = self.clips.save(self._session_head, verified=True)

        record = TriggerRecord(
            ts=str(self.now()),
            keyword_score=float(self._hit.get("keyword_score", 0.0)),
            ecapa_score=score,
            confidence=confidence,
            outcome=outcome,
            knock_id=None,
            stage_b_input=stage,
            pending_speech_s=pending_speech_s,
            pending_disposition=(DISP_INHERITED if outcome == OUTCOME_ATTENDING
                                 else DISP_DISCARDED),
            clip_saved=clip_path is not None,
            unsafe_energy=unsafe,
            phrase=self.phrase)
        self.last_trigger = record
        self._log_trigger(record)
        return {"state": self.state, "attending_detail": self.attending_detail,
                "trigger": record.as_dict(), "knock_id": None,
                "head_bytes": len(self._session_head), "detail": detail}

    def _raise_wake_knock(self, score: float | None) -> int | None:
        """OWNER-AUTHENTICATION PROMPT — never an impostor reply.

        Round J defect 2 removed its only call site: a voice the daemon did
        not recognise produces silence, never a knock. The method stays for
        an explicit owner-initiated prompt and records through `outbound`, so
        a test can prove the unrecognised-voice path never reaches it.
        """
        if self.initiative is None:
            return None
        confidence_text = ("no voice confidence" if score is None
                           else f"voice confidence {score:.2f}")
        reason = f"phrase {self.phrase!r} detected, {confidence_text}"
        self.outbound.knock(reason=reason)
        try:
            knock = self.initiative.raise_knock(
                topic=f"wake phrase {self.phrase!r}",
                reason=reason,
                kind="wake")
        except Exception:
            return None
        return int(knock.get("id")) if isinstance(knock, dict) else None

    def _log_trigger(self, record: TriggerRecord) -> None:
        if self.store is None:
            return
        with contextlib.suppress(Exception):
            self.store.log_persona_event(str(self.now()), TRIGGER_EVENT,
                                         json.dumps(record.as_dict(),
                                                    sort_keys=True))

    # -- accept paths ------------------------------------------------------
    def authorize_accept(self, *, principal: IpcPrincipal | None) -> dict:
        """Only the kernel-authenticated local owner may accept a knock (I5).

        A channel label or confidence number from an IPC payload is not proof.
        Voice acceptance would require fresh daemon-captured evidence; this
        package currently exposes only the explicit owner-console action.
        """
        if (not isinstance(principal, IpcPrincipal)
                or principal.pid <= 0 or principal.uid != os.getuid()):
            return {
                "authorized": False,
                "via": "none",
                "reason": "refused: wake-knock accept requires a "
                          "daemon-authenticated local owner (I5)",
            }
        return {"authorized": True, "via": "authenticated-local-owner"}

    def wake_knock_accepted(self, *, knock_id: int | None = None,
                            principal: IpcPrincipal | None = None) -> dict:
        if self.state != WAKE_KNOCK:
            raise WakeGuardError(f"no wake-knock pending (state {self.state!r})")
        auth = self.authorize_accept(principal=principal)
        if not auth.get("authorized"):
            raise WakeGuardError(str(auth.get("reason")))
        if self._guest_door_blocked():
            raise WakeGuardError(
                "refused: show-off is active — the guest door is show-off "
                "only; the wake path never opens guest conversation")
        if self._in_class_mode():
            # Class mode: an accepted wake-knock opens the CONSOLE, not PTT.
            self.state = CLOSED
            return {"open": "console", "reason": "class mode: console, not PTT",
                    "knock_id": knock_id, "fresh_capture": True}
        return self._open_listening(knock_id=knock_id, fresh=True)

    def wake_knock_denied(self, *, knock_id: int | None = None,
                          action: str = "declined") -> dict:
        self.state = CLOSED
        self.attending_detail = None
        self.session = None
        self._zero_buffers()
        return {"state": self.state, "action": action, "knock_id": knock_id}



    def open_listening(self, *, knock_id: int | None = None,
                       fresh: bool = False) -> dict:
        """Direct (attending) path into listening.

        The wake-knock path does NOT come through here — it goes through
        `wake_knock_accepted`, which enforces accept authentication. A hit
        alone can never reach listening.
        """
        if self._hit.get("unsafe_energy") or (
                self.last_trigger and self.last_trigger.unsafe_energy):
            raise WakeGuardError(
                "refused: unsafe energy trigger may never open command "
                "listening (plumbing flag only)")
        if self.state == ATTENDING and not fresh:
            return self._open_listening(knock_id=knock_id, fresh=False)
        raise WakeGuardError(
            f"refused: listening is not on offer from state {self.state!r} "
            "(a hit alone never opens command listening)")

    def _open_listening(self, *, knock_id: int | None, fresh: bool) -> dict:
        if self._hit.get("unsafe_energy") or (
                self.last_trigger and self.last_trigger.unsafe_energy):
            raise WakeGuardError(
                "refused: unsafe energy trigger may never open command "
                "listening (plumbing flag only)")
        if self._guest_door_blocked():
            raise WakeGuardError(
                "refused: show-off is active — the guest door is show-off only")
        if self._in_class_mode():
            self.state = CLOSED
            return {"open": "console", "reason": "class mode: console, not PTT",
                    "knock_id": knock_id}
        head = b"" if fresh else self._session_head
        ladder = SilenceLadder(
            checkin_after_s=float(self.settings.get("checkin_after_s", 30.0)),
            speech_rms=self.speech_rms,
            resume_s=float(self.settings.get("resume_s", 0.4)),
            grace_s=float(self.settings.get("grace_s", 8.0)),
            floor_peak=float(self.silence_floor))
        self.session = ListenSession(
            session_id=f"wake-{int(time.time() * 1000)}",
            head=head, fresh=bool(fresh), ladder=ladder)
        self.state = LISTENING
        # A fresh capture after an accept: the discarded buffer is gone for
        # good — never resurrected.
        self._session_head = b""
        self._wake_clip = b""
        return {"open": "listening", "knock_id": knock_id,
                "session_id": self.session.session_id,
                "head_bytes": len(self.session.head),
                "fresh_capture": bool(fresh)}

    def endpoint_closed(self) -> dict:
        """SilenceLadder closed the utterance -> endpointing -> closed."""
        self.state = CLOSED
        self.attending_detail = None
        self.session = None
        self._zero_buffers()
        return self.status()

    def _in_class_mode(self) -> bool:
        if self.class_mode is None:
            return False  # not wired (headless/tests): no class-mode concept
        try:
            result = bool(self.class_mode())
        except Exception as exc:
            # BH-K10: fail CLOSED. A wired-but-broken presence probe used
            # to read as "not in class" — an accepted wake-knock then
            # opened voice listening in a classroom. Unknown posture is
            # restrictive posture (WakeGuardError's own contract).
            self.posture_error = f"class_mode: {type(exc).__name__}: {exc}"
            return True
        self.posture_error = None
        return result

    def _guest_door_blocked(self) -> bool:
        if self.showoff is None:
            return False  # not wired: no show-off concept
        try:
            status = self.showoff.status()
            result = bool(status.get("active"))
        except Exception as exc:
            # BH-K10: fail CLOSED — a broken showoff probe must block the
            # guest door, never wave a wake accept through it.
            self.posture_error = f"showoff: {type(exc).__name__}: {exc}"
            return True
        self.posture_error = None
        return result

    # -- inspection surface ------------------------------------------------
    def status(self) -> dict:
        last = self.last_trigger.as_dict() if self.last_trigger else None
        scorer_name = getattr(self.scorer, "name", "none") \
            if self.scorer is not None and self.scorer.available() \
            else ("none" if self.scorer is None else
                  f"{getattr(self.scorer, 'name', 'none')}(unavailable)")
        return {
            "armed": self.armed,
            "posture_error": self.posture_error,
            "armed_with": self.armed_with,
            "state": self.state,
            "attending_detail": self.attending_detail,
            # Round J: the numbers that make the silence contract
            # checkable from outside — no score below ecapa_high, and no
            # scoring call at all for a window under MIN_WINDOW_S.
            "min_window_s": MIN_WINDOW_S,
            "window_close_s": self.window_close_s,
            "window_elapsed_s": round(self._window_elapsed_s, 3),
            "ecapa_high": self.gate.high,
            "ecapa_uncertain": self.gate.uncertain,
            "ring": {
                "capacity_s": round(self.ring.seconds, 3),
                "residence_s": round(self.ring.residence_s(), 3),
                "path": None,
            },
            "scorer": scorer_name,
            "keyword_model": getattr(self.keyword_model, "name",
                                     None if self.keyword_model is None else "onnx"),
            "last_trigger": last,
            "pending_speech_s": (last or {}).get("pending_speech_s"),
            "stage_b_input": (last or {}).get("stage_b_input"),
            "pending_disposition": (last or {}).get("pending_disposition"),
            "watchdog": {
                "last_frame_age_ms": self.watchdog.last_frame_age_ms(),
                "state": self.watchdog.state,
            },
            "crash_safety": crash_safety_report(
                self.settings.get("unit_path")),
        }
