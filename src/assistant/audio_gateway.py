"""The daemon's audio gateway (TASK K, G1) — one owner for capture and playback.

Why this exists: capture was created in three places and playback in four, so
"who holds the microphone" and "who is making noise" were answers each caller
guessed for itself. The gateway makes them one state machine with one owner.

What it owns
------------
* **Capture** for PTT/dictation — the source is created here, from the node
  this deployment is *configured* for (F17). A real device is never opened
  against the default source by accident: with no configured node the gateway
  refuses instead of grabbing whatever the system picked.
* **Playback** — whole replies, one queue, daemon-side (F16). Streaming
  playback is deliberately NOT here: the live conversation stream keeps its
  own path in `live_client.py` until a quoted grant migrates it.
* **Arbitration** (F28) — one utterance never produces two replies, PTT is
  inert while a live session runs, and a live session cannot start while PTT
  holds the mic.
* **Cancel** (F30) — Escape is answered here, and the session it stops is the
  session this gateway opened.

What it does not own: the streaming Live transport (protected), the TTS
synthesis itself (`tts.SpeechService` still renders voice), or any policy
about *what* to say. It decides who may use the audio hardware, and records
what it decided.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field

from .capture import (
    PipeWireCapture,
    SimulatedCapture,
    tool_available,
)


class GatewayRefused(RuntimeError):
    """The gateway declined to open a device or start a mode, with a reason.

    `refusal` says which question was answered, because the caller must treat
    them differently: `policy` means this deployment may not capture at all
    (F17 — no configured node on a machine that could open one), and the
    session must be refused; `device` means the named node would not open
    here, and the existing no-device fallback may answer instead.
    """

    def __init__(self, message: str, *, refusal: str = "device") -> None:
        super().__init__(message)
        self.refusal = refusal


@dataclass
class Arbitration:
    """The answer to "may this start?", plus the state it was answered in."""

    allowed: bool
    reason: str
    state: str

    def as_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "state": self.state}


@dataclass
class AudioGateway:
    """One owner for capture, playback and the state between them (G1/F17/F28)."""

    config: object
    #: Injected by the daemon: (target, frame_ms, stall_timeout_s) -> source.
    #: A callable rather than a class so a monkeypatched seam in `daemon` stays
    #: live (the existing fake-device pins patch `assistant.daemon.PipeWireCapture`).
    capture_factory: object | None = None
    #: Injected by the daemon: (frame_ms) -> simulated source.
    simulated_factory: object | None = None
    #: Injected in tests: async callable that performs one whole-reply playback.
    playback: object | None = None
    clock: object = None

    STATE_IDLE: str = "idle"
    STATE_PTT: str = "ptt"
    STATE_LIVE: str = "live"
    STATE_SPEAKING: str = "speaking"

    _state: str = field(default="idle", init=False)
    _source: object | None = field(default=None, init=False)
    _live_sessions: int = field(default=0, init=False)
    _playback_tasks: set = field(default_factory=set, init=False)
    _reply_claimed: object = field(default_factory=OrderedDict, init=False)
    _transitions: list = field(default_factory=list, init=False)
    _cancels: int = field(default=0, init=False)

    # ---------------------------------------------------------------- state
    @property
    def state(self) -> str:
        if self._state == self.STATE_IDLE and self._playback_tasks:
            return self.STATE_SPEAKING
        return self._state

    def _move(self, new: str, why: str) -> None:
        old = self._state
        self._state = new
        # A bounded, content-free transition log: the gateway's own testimony
        # about what it allowed, small enough to keep forever.
        self._transitions.append({"from": old, "to": new, "why": why})
        if len(self._transitions) > 64:
            del self._transitions[:-64]

    def status(self) -> dict:
        return {"state": self.state, "live_sessions": self._live_sessions,
                "playbacks": len(self._playback_tasks),
                "cancels": self._cancels,
                "transitions": list(self._transitions[-8:]),
                "pw_record": tool_available("pw-record"),
                "streaming_playback": "deferred (F16) — replies play whole"}

    # --------------------------------------------------- F17: the node policy
    def resolve_target(self, param_target: str | None = None) -> tuple[str | None, str]:
        """The node this capture must use, or a refusal.

        Order: explicit parameter → `[capture] mic_target` → `[meeting]
        mic_target`. There is deliberately no "default source" fallback for a
        REAL device: the doctor reports a Mic1 policy, and a capture that
        quietly opened the system default would record a different microphone
        than the one that was measured.
        """
        section = getattr(self.config, "section", lambda _n: {})
        target = (param_target
                  or section("capture").get("mic_target")
                  or section("meeting").get("mic_target"))
        if target:
            return str(target), "configured"
        # F17: on a machine that CAN open a device, an unnamed node is a
        # refusal — never "whatever the system picked". Where no device can be
        # opened at all (no pw-record: containers, CI, fake-device pins) the
        # question does not arise and the caller's existing no-device fallback
        # answers, with its reason logged.
        if tool_available("pw-record"):
            raise GatewayRefused(
                "no capture node configured — default-device grabbing is "
                "forbidden (F17); set [capture] mic_target to the node the "
                "doctor reports", refusal="policy")
        return None, "unconfigured (no device can be opened here)"

    def open_capture(self, *, params: dict | None = None, source_kind: str = "mic",
                     frame_ms: int = 30, stall_timeout_s: float = 8.0) -> dict:
        """Create the capture source for a PTT session and record how.

        A simulated source is not a device and needs no node. A real one must
        resolve a configured target; when PipeWire is absent the caller's
        existing fallback (simulated) applies, and the receipt says so.
        """
        params = params or {}
        if source_kind == "simulated":
            make = self.simulated_factory or (
                lambda ms: SimulatedCapture(speech_frames=100_000, frame_ms=ms,
                                            realtime=True))
            source = make(frame_ms)
            self._source = source
            return {"source": source, "simulated": True, "target": "simulated",
                    "node_policy": "simulated — no device opened"}
        target, provenance = self.resolve_target(params.get("target"))
        factory = self.capture_factory or (
            lambda t, ms, stall: PipeWireCapture(t, frame_ms=ms,
                                                 stall_timeout_s=stall))
        try:
            source = factory(target, frame_ms, stall_timeout_s)
        except RuntimeError as exc:
            # The node exists in config but not on this machine: refused, and
            # the caller decides whether simulated frames keep it exercisable.
            raise GatewayRefused(
                f"capture node {target!r} could not be opened: {exc}") from exc
        self._source = source
        return {"source": source, "simulated": False, "target": target,
                "node_policy": f"{provenance}: {target}"}

    def release_capture(self) -> dict:
        """Drop our reference. The caller owns `aclose()` (it awaits)."""
        source, self._source = self._source, None
        return {"released": source is not None,
                "target": str(getattr(source, "target", None) or "")}

    # ------------------------------------------------------ F28 arbitration
    def request_ptt(self, session_id: str | None = None) -> Arbitration:
        """May a PTT session start now?

        Refused while a LIVE session runs (one microphone, one owner, and a
        live stream already has it). Allowed while she is speaking: pressing
        the key is how the owner interrupts her.
        """
        state = self.state
        if state == self.STATE_LIVE:
            return Arbitration(False, "live session active — PTT is inert", state)
        # A second press while already listening is the daemon's own case
        # ("already listening", no second ack) and a supersede is legitimate
        # when the previous task has finished — so the gateway answers only
        # the question it owns: may the microphone be taken at all?
        return Arbitration(True, ("interrupts playback" if state == self.STATE_SPEAKING
                                 else "idle"), state)

    def begin_ptt(self) -> None:
        self._move(self.STATE_PTT, "ptt accepted")

    def end_ptt(self, *, cancelled: bool = False) -> None:
        if cancelled:
            self._cancels += 1
        if self._state == self.STATE_PTT:
            self._move(self.STATE_IDLE, "cancel" if cancelled else "release")

    def request_live(self) -> Arbitration:
        """May a LIVE conversation session start now?"""
        if self._state == self.STATE_PTT:
            return Arbitration(False, "PTT holds the microphone — live suppressed",
                               self.state)
        return Arbitration(True, "no capture in progress", self.state)

    def begin_live(self) -> None:
        self._live_sessions += 1
        self._move(self.STATE_LIVE, "live session started")

    def end_live(self) -> None:
        self._live_sessions = max(0, self._live_sessions - 1)
        if self._state == self.STATE_LIVE and not self._live_sessions:
            self._move(self.STATE_IDLE, "live session ended")

    # ------------------------------- F28: one utterance, exactly one reply
    def claim_reply(self, session_id: str) -> tuple[bool, str]:
        """First caller for a session id wins; every later one is refused.

        This is the invariant that stops one utterance producing two answers
        when an early dispatch and the late gate both reach for the same turn.
        """
        sid = str(session_id or "")
        if not sid:
            return False, "no session id — a reply cannot be attributed"
        if sid in self._reply_claimed:
            return False, "a reply was already claimed for this session"
        self._reply_claimed[sid] = True
        while len(self._reply_claimed) > 256:         # bounded: forget the oldest
            self._reply_claimed.popitem(last=False)
        return True, "claimed"

    # ------------------------------------------- F16: whole-reply playback
    def start_playback(self, task: asyncio.Task) -> None:
        """Track a playback task so `state` can report speaking honestly."""
        self._playback_tasks.add(task)

        def _done(finished: asyncio.Task) -> None:
            self._playback_tasks.discard(finished)
            if not self._playback_tasks and self._state == self.STATE_SPEAKING:
                self._move(self.STATE_IDLE, "playback finished")

        task.add_done_callback(_done)
        if self._state == self.STATE_IDLE:
            self._move(self.STATE_SPEAKING, "whole-reply playback")

    def is_playing(self) -> bool:
        return bool(self._playback_tasks)

    async def stop_playback(self) -> int:
        """Interrupt whatever is playing (used by halt/knock paths)."""
        stopped = 0
        for task in list(self._playback_tasks):
            if not task.done():
                task.cancel()
                stopped += 1
        if stopped:
            await asyncio.gather(*list(self._playback_tasks), return_exceptions=True)
        return stopped
