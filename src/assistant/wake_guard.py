"""Wake-knock model — the owner-approved package (2026-10-20).

State machine (§1 of the package spec)::

    idle -> triggered -> verifying -> attending | wake_knock
         -> listening -> endpointing -> closed

The one rule everything else exists to protect: **an acoustic/phrase hit
NEVER grants command authority.** A hit only moves the machine to
`triggered`; authority comes later, from the voiceprint verdict or from a
human accept. Fail closed everywhere: missing embedding, missing scorer,
missing keyword model, stalled capture — none of these lead to listening.

* High-confidence owner -> ATTENDING -> listening. The dual-use pending
  buffer is INHERITED as the head of the command utterance (the owner never
  repeats themselves).
* Uncertain / non-owner / no embedding -> a `wake` knock on the existing
  knock system, with a citable reason ("phrase 'Elaria' detected, voice
  confidence 0.61"). It is an EVENT REPORT — the anti-psychosis clause
  applies in full; there is no simulated emotion anywhere in this file.
  Accept opens listening (fresh capture; a discarded buffer is never
  resurrected). Decline/ignore returns to sleep. In class mode an accept
  opens the CONSOLE, not PTT. Guest conversation is NEVER opened on this
  path — show-off mode stays the only guest door.
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
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .capture import frame_rms
from .cost import iso_now
from .transcribe import SilenceLadder
from .wake_buffers import SAMPLE_RATE, PendingWindow, PreWakeRing

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

STAGE_WAKE_PLUS_POST = "wake_plus_post"
STAGE_WAKE_ONLY = "wake_only_fallback"

DISP_INHERITED = "inherited"
DISP_DISCARDED = "discarded"
DISP_AWAITING = "awaiting_command"

OUTCOME_ATTENDING = "attending"
OUTCOME_WAKE_KNOCK = "wake_knock"
OUTCOME_IGNORED = "ignored"
OUTCOME_REFUSED_ENERGY = "refused_energy_test"
OUTCOME_STALLED = "stalled"

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
                "refused: no keyword model configured ([hotword] keyword_model). "
                "Acoustic arming needs a real .onnx keyword model.")
        if not Path(path).is_file():
            raise KeywordModelUnavailable(
                f"refused: no keyword model (.onnx) at {path!r} — acoustic "
                "arming will not run on an energy/loudness fallback.")
        try:
            import onnxruntime  # noqa: F401  # hardware-side extra
        except ImportError as exc:
            raise KeywordModelUnavailable(
                "refused: onnxruntime is not installed — cannot run the "
                "keyword model; energy fallback is not a wake path") from exc
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
    """confidence: high | uncertain | none. Only high + verified may attend."""

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
    """Metadata only. This is the whole log — no audio, ever."""

    ts: str
    keyword_score: float
    ecapa_score: float | None
    confidence: str
    outcome: str
    knock_id: int | None = None
    stage_b_input: str = STAGE_WAKE_ONLY
    pending_speech_s: float = 0.0
    pending_disposition: str = DISP_DISCARDED
    clip_saved: bool = False
    unsafe_energy: bool = False
    phrase: str = "Elaria"

    def as_dict(self) -> dict:
        return {
            "ts": self.ts,
            "keyword_score": round(float(self.keyword_score), 4),
            "ecapa_score": (None if self.ecapa_score is None
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
    """Wake-knock state machine. Frames in, decisions out, nothing persisted
    but trigger metadata."""

    settings: dict = field(default_factory=dict)
    store: object = None
    initiative: object = None
    class_mode: object = None            # callable -> bool
    showoff: object = None               # .status() -> {"active": bool}
    scorer: object = None                # VoiceScorer
    keyword_model: object = None
    phrase: str = "Elaria"
    now: object = None

    def __post_init__(self):
        if self.now is None:
            self.now = iso_now
        s = self.settings
        self.ring = PreWakeRing(min(2.0, float(s.get("ring_window_s", 2.0))))
        self.pending = PendingWindow(float(s.get("pending_window_s", 2.5)))
        self.gate = AuthorityGate(
            high=float(s.get("ecapa_high", 0.75)),
            uncertain=float(s.get("ecapa_uncertain", 0.5)))
        self.speechful_s = float(s.get("pending_speech_threshold_s", 0.5))
        self.speech_rms = float(s.get("speech_rms", 0.01))
        self.stall_timeout_s = float(s.get("stall_timeout_s", 2.0))
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
        self.session: ListenSession | None = None
        self._hit: dict = {}
        self._wake_clip: bytes = b""
        self._session_head: bytes = b""

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

    # -- frame path --------------------------------------------------------
    def note_frame(self, frame: bytes, now: float | None = None) -> None:
        """Always-on frame: ring + watchdog + (pending window while open)."""
        self.watchdog.note_frame(now)
        self.ring.append(frame)
        if self.state in (TRIGGERED, VERIFYING):
            self.pending.append(frame)

    def feed(self, frame: bytes, *, now: float | None = None) -> dict | None:
        """One always-on frame through ring, watchdog and the keyword model.

        Returns the outcome dict when a hit was triggered and verified, else
        None. The keyword model is consulted only while armed.
        """
        self.note_frame(frame, now)
        if not self.armed or self.keyword_model is None:
            return None
        score = float(self.keyword_model.score_window(frame))
        if isinstance(self.keyword_model, EnergyTestModel):
            threshold = getattr(self.keyword_model, "threshold", 0.05)
        else:
            threshold = float(self.settings.get("keyword_threshold", 0.5))
        if score < threshold:
            return None
        self.trigger(keyword_score=score,
                     unsafe_energy=isinstance(self.keyword_model,
                                              EnergyTestModel))
        return self.verify()

    # -- state machine -----------------------------------------------------
    def trigger(self, *, keyword_score: float,
                wake_clip: bytes | None = None,
                unsafe_energy: bool = False) -> str:
        """Hit -> `triggered`. Still NO authority of any kind."""
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
        return self.state

    def verify(self) -> dict:
        """Stage B on wake clip + pending buffer. Runs BEFORE any routing."""
        if self.state not in (TRIGGERED, VERIFYING):
            raise WakeGuardError(f"cannot verify from state {self.state!r}")
        self.state = VERIFYING
        self.pending.close()
        pending_pcm = self.pending.data()
        pending_speech_s = speech_seconds(pending_pcm,
                                          speech_rms=self.speech_rms)
        use_post = pending_speech_s >= self.speechful_s
        stage = STAGE_WAKE_PLUS_POST if use_post else STAGE_WAKE_ONLY
        stage_pcm = (self._wake_clip + pending_pcm) if use_post else self._wake_clip

        scorer = self.scorer
        score = None
        verified = False
        if scorer is not None and scorer.available():
            score = scorer.score_owner(stage_pcm)
            verified = score is not None

        confidence = self.gate.evaluate(score, verified=verified)
        unsafe = bool(self._hit.get("unsafe_energy"))
        knock_id = None
        clip_path = None

        if confidence == CONF_HIGH and not unsafe:
            disposition = DISP_INHERITED if use_post else DISP_AWAITING
            self.attending_detail = (ATTEND_INHERIT if use_post else ATTEND_AWAIT)
            self._session_head = pending_pcm if use_post else b""
            self.state = ATTENDING
            outcome = OUTCOME_ATTENDING
        elif confidence == CONF_HIGH and unsafe:
            # Plumbing saw a high score; authority still refuses. Energy
            # triggers can never open command listening.
            disposition = DISP_DISCARDED
            self.pending.zero()
            self.state = CLOSED
            outcome = OUTCOME_REFUSED_ENERGY
        else:
            # Uncertain / non-owner / no embedding. Fail closed: the pending
            # buffer is DISCARDED untranscribed — no ASR, no ledger, no
            # transcript row, ever.
            disposition = DISP_DISCARDED
            self.pending.zero()
            pending_pcm = b""
            self._session_head = b""
            self.state = WAKE_KNOCK
            outcome = OUTCOME_WAKE_KNOCK
            if confidence == CONF_NONE and not verified and \
                    self.missing_embedding_action == "ignore":
                self.state = CLOSED
                outcome = OUTCOME_IGNORED
            else:
                knock_id = self._raise_wake_knock(score)

        save_verified = outcome == OUTCOME_ATTENDING
        if self.clips.may_save(verified=save_verified):
            clip_path = self.clips.save(stage_pcm, verified=save_verified)

        record = TriggerRecord(
            ts=str(self.now()),
            keyword_score=float(self._hit.get("keyword_score", 0.0)),
            ecapa_score=score,
            confidence=confidence,
            outcome=outcome,
            knock_id=knock_id,
            stage_b_input=stage,
            pending_speech_s=pending_speech_s,
            pending_disposition=disposition,
            clip_saved=clip_path is not None,
            unsafe_energy=unsafe,
            phrase=self.phrase)
        self.last_trigger = record
        self._log_trigger(record)
        return {"state": self.state, "attending_detail": self.attending_detail,
                "trigger": record.as_dict(), "knock_id": knock_id,
                "head_bytes": len(self._session_head)}

    def _raise_wake_knock(self, score: float | None) -> int | None:
        if self.initiative is None:
            return None
        confidence_text = ("no voice confidence" if score is None
                           else f"voice confidence {score:.2f}")
        reason = f"phrase {self.phrase!r} detected, {confidence_text}"
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
    def authorize_accept(self, *, channel: str,
                         voiceprint_score: float | None = None) -> dict:
        """Who may open listening for a wake-knock.

        voice-accept must ITSELF be voiceprint-verified (high confidence).
        hotkey/console accept counts as owner authentication — the same
        trust as PTT. Everything else fails closed.
        """
        channel = str(channel or "")
        if channel in ("hotkey", "console", "voice_unavailable"):
            return {"authorized": True, "via": channel}
        if channel == "voice":
            ok = (voiceprint_score is not None
                  and self.gate.evaluate(voiceprint_score, verified=True) == CONF_HIGH)
            return {"authorized": ok,
                    "via": "voice",
                    "reason": ("voiceprint verified" if ok else
                               "refused: voice-accept must itself be "
                               "voiceprint-verified (fail closed)")}
        return {"authorized": False, "via": channel,
                "reason": f"refused: unknown accept channel {channel!r}"}

    def wake_knock_accepted(self, *, knock_id: int | None = None,
                            channel: str = "console",
                            voiceprint_score: float | None = None) -> dict:
        if self.state != WAKE_KNOCK:
            raise WakeGuardError(f"no wake-knock pending (state {self.state!r})")
        auth = self.authorize_accept(channel=channel,
                                     voiceprint_score=voiceprint_score)
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
            grace_s=float(self.settings.get("grace_s", 8.0)))
        self.session = ListenSession(
            session_id=f"wake-{int(time.time() * 1000)}",
            head=head, fresh=bool(fresh), ladder=ladder)
        self.state = LISTENING
        # A fresh capture after an accept: the discarded buffer is gone for
        # good — never resurrected.
        self._session_head = b""
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
            return False
        try:
            return bool(self.class_mode())
        except Exception:
            return False

    def _guest_door_blocked(self) -> bool:
        if self.showoff is None:
            return False
        try:
            status = self.showoff.status()
            return bool(status.get("active"))
        except Exception:
            return False

    # -- inspection surface ------------------------------------------------
    def status(self) -> dict:
        last = self.last_trigger.as_dict() if self.last_trigger else None
        scorer_name = getattr(self.scorer, "name", "none") \
            if self.scorer is not None and self.scorer.available() \
            else ("none" if self.scorer is None else
                  f"{getattr(self.scorer, 'name', 'none')}(unavailable)")
        return {
            "armed": self.armed,
            "armed_with": self.armed_with,
            "state": self.state,
            "attending_detail": self.attending_detail,
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
