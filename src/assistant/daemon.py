"""Daemon — the product (§1.1). All state and policy live here; clients
are dumb and disposable. Single asyncio process, systemd --user.

Phase 0 handlers: ping, status, cost, doctor (via CLI-local checks),
halt/resume, ack (the §18 <300ms local acknowledgement — pure in-process
code, zero network), ptt.start/stop/result (the release is acknowledged
immediately; the transcript finishes in the background and is fetched with
ptt.result — BUG 6; ptt.result resolves on ANY terminal state of the
requested session, including "superseded / finished without a result",
with an explicit error payload — BUG 6d), ask (governor + cheapest-first
harness; fully functional in mock mode).

Startup recovery (§4.2): outstanding journal intents are reported, never
silently dropped. Cold starts are a Phase-0 bug (§18.6): config, store,
governor and client are resident from boot.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import signal
import socket as socket_mod
import sys
import time
import uuid
from contextvars import ContextVar

from . import __version__
from .asr import local_asr_status
from .capture import PipeWireCapture, SimulatedCapture
from .config import Config, load_config, load_humour_profile
from .console import ConsoleService, SessionService
from .cost import day_start_iso, iso_now, month_start_iso
from .disclosure import (
    DisclosureService,
    detect_company_command,
    is_instruction,
)
from .gemini_client import GeminiClient
from .initiative import InitiativeError, InitiativeService, KnockSignal
from .ipc import IpcPrincipal, ipc_peer_principal, serve
from .modes import ModeManager
from .offline_queue import CloudQueue
from .organiser import OrganiserService
from .persona import (
    PersonaGovernor,
    TurnContext,
    build_chat_prompt,
    chat_reply_violation,
    checkin_reply,
    timeout_fallback_reply,
)
from .presence import PresenceService
from .safety import clear_halt, is_halted, set_halt
from .showoff import ShowoffError, ShowoffService
from .store import Store
from .transcribe import DictationService
from .tts import STANDARD_ACKS, SpeechResult, SpeechService

MAX_PTT_WAIT_S = 90.0


class ChatTimeout(TimeoutError):
    """A chat turn that hit a deadline — with WHICH deadline attached.

    BUG F / Bug 8: the fallback path must be able to say why it fired, and a
    logged substitution must name the deadline kind ('first_token' = the
    transport produced nothing; 'total' = the generation started but did not
    finish). A TimeoutError without this shape is treated as 'total'.
    """

    def __init__(self, reason: str, waited_s: float):
        super().__init__(f"chat {reason} deadline after {waited_s:.1f}s")
        self.reason = reason
        self.waited_s = waited_s


def _sd_notify(message: str) -> None:
    """Best-effort systemd readiness/watchdog ping (stdlib only)."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_DGRAM) as sock:
            sock.sendto(message.encode(), address)
    except OSError:
        pass


def _int_param(params: dict, name: str) -> int:
    """Coerce a required integer IPC param (BH-K29).

    Bare ``int(params.get(...))`` / ``int(params[...])`` turned a
    client's missing or mistyped id into TypeError/KeyError text on the
    wire. ValueError is the daemon's refusal type — it reaches the user
    as an actionable message and the CLI's exit-2 path.
    """
    value = params.get(name)
    if value is None:
        raise ValueError(f"parameter {name!r} is required (integer)")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"parameter {name!r} must be an integer, got {value!r}") from exc


class Daemon:
    def __init__(self, config: Config):
        self.config = config
        # Request identity is task-local: concurrent IPC clients must never
        # inherit one another's principal or method. Peer credentials are
        # installed by handle() from SO_PEERCRED, not request params (I5).
        self._ipc_principal: ContextVar[IpcPrincipal | None] = ContextVar(
            f"elaria_ipc_principal_{id(self)}", default=None)
        self._ipc_method: ContextVar[str | None] = ContextVar(
            f"elaria_ipc_method_{id(self)}", default=None)
        config.ensure_dirs()
        self.store = Store(config.db_path)
        self.governor = PersonaGovernor.from_config(config, load_humour_profile(config))
        self.client = GeminiClient(config, self.store)
        self.started_at = iso_now()
        self.started_monotonic = time.monotonic()
        self.mode = "idle"
        # Phase 8 resident hot paths: connectivity, ONE local voice, queue.
        self.mode_manager = ModeManager(config, self.store)
        # Stage B: class mode + the one shared conversation.
        self.presence = PresenceService(config, self.store)
        # `[console] history_limit` is a real setting, not a doc string: the
        # daemon owns the one conversation service and must honour it (BH-I3).
        # A poisoned value falls back here; `validate_config()` names the key.
        history_setting = config.section("console").get("history_limit", 200)
        try:
            history_limit = max(1, int(history_setting))
        except (TypeError, ValueError):
            history_limit = 200
        self.sessions = SessionService(self.store, history_limit=history_limit)
        self.speech = SpeechService(
            config, self.store, client=self.client,
            # INTERIM online voice: Flare speaks only while actually online. Offline
            # turns are text-only (amendment 2026-10-20) - no cloud call, and the
            # dormant local voice does not take them over either.
            is_online=lambda: self.mode_manager.status(refresh=False).effective_mode
            == "ONLINE",
            presence=self.presence)
        self.cloud_queue = CloudQueue(config, self.store, self.client, self.mode_manager)
        self.dictation = DictationService(
            config, self.store, self.client,
            mode_manager=self.mode_manager, offline_queue=self.cloud_queue)
        self.organiser = OrganiserService(config, self.store, self.client)
        from .executor import Executor
        self.executor = Executor(config, self.store)
        from .embeddings import make_embedder
        from .memory import Memory
        self.memory = Memory(self.store, make_embedder(config))
        from .meeting import MEETING_TRANSCRIPTION_TIMEOUT_S, MeetingService
        self.meetings = MeetingService(
            config, self.store, self.client, mode_manager=self.mode_manager)
        self._meeting_stop_timeout_s = MEETING_TRANSCRIPTION_TIMEOUT_S
        # Disclosure awareness: memory may be used, secrets/plans never spoken
        # while company is present, and no owner memory to a guest voice.
        self.disclosure = DisclosureService(config, self.store)
        # Stage D: show-off is the owner's, voiceprint-verified, and grants
        # nothing that survives it. Demo actions are sandboxed at the executor.
        self.showoff = ShowoffService(
            config, self.store, presence=self.presence, sessions=self.sessions)
        # Stage C: the knock. Class mode restricts it to urgent-only; the
        # reason gate — not a budget — decides whether she may speak at all.
        self.initiative = InitiativeService(
            config, self.store, presence=self.presence,
            disclosure=self.disclosure, sessions=self.sessions)
        self.knock_signal = KnockSignal(config)
        # Wake-knock package: the always-on gate. A phrase hit NEVER grants
        # command authority; the guard holds that line (wake_guard.py). The
        # scorer is the hardware-side ECAPA seam; missing = fail closed.
        from .voiceprint import EcapaCommandScorer, load_reference
        from .wake_guard import WakeGuard
        self.wake_guard = WakeGuard(
            settings=config.section("hotword"),
            store=self.store,
            initiative=self.initiative,
            class_mode=lambda: self.presence.status().enabled,
            showoff=self.showoff,
            scorer=EcapaCommandScorer(
                config.section("hotword").get("ecapa_cmd"),
                load_reference(config.section("hotword").get("ecapa_reference")),
                sample_rate=int(config.section("hotword").get("sample_rate", 16000))),
            phrase=str(config.section("hotword").get("phrase", "Elaria")))
        self._hotword_task: asyncio.Task | None = None
        self.console = ConsoleService(
            config, self.store, presence=self.presence, sessions=self.sessions,
            initiative=self.initiative, showoff=self.showoff,
            disclosure=self.disclosure)
        self._meeting: dict | None = None  # {session_id, task, dual, frames}
        # A stopped meeting can still be transcribing while the next meeting
        # is captured; track every in-flight worker rather than one shared bool.
        self._meeting_processing: set[str] = set()
        self._meeting_stop_tasks: set[asyncio.Task] = set()
        self._plan_tasks: dict[int, asyncio.Task] = {}
        # VB-13: early acks wait for the boot warm instead of being silent. The
        # event is set as soon as a warm cycle ends (success, failure, or a
        # posture that never speaks), so it can only ever delay a handler briefly.
        self._ack_cache_ready = asyncio.Event()
        self._warm_running = False
        # True from the moment run() schedules the boot warm until that cycle
        # ends: it covers the instant before the task first runs, so an ack
        # landing there queues behind the warm instead of answering from a cold
        # cache. A daemon driven without run() never sets it and never waits.
        self._warm_pending = False
        self._subscribers: set = set()          # event-stream writers (§3.1)
        self._dictation_task: asyncio.Task | None = None
        self._dictation_session_mode = "narration"
        self._capture_source = None
        self._stop_event: asyncio.Event | None = None
        # BUG6: ptt.stop answers on the release and the session finishes in the
        # background. Processing state is observable through ptt.result/status.
        # BUG 6d (hardware report 2026-10-20): result state is PER SESSION —
        # one terminal event per session id and one slot in _ptt_results. The
        # old single global event was set only while the finishing session was
        # still the daemon's current one, so a finish landing under a changed
        # session id completed silently and its ptt.result waiter parked on an
        # orphaned event (the hardware hang). `_ptt_processing` is derived:
        # True exactly while some released session still has a finisher.
        self._ptt_session_id: str | None = None
        self._ptt_last_session_id: str | None = None
        self._ptt_last_result: dict | None = None
        self._ptt_results: dict[str, dict] = {}
        self._ptt_result_events: dict[str, asyncio.Event] = {}
        self._ptt_finishing: set[str] = set()
        self._ptt_started_at: float | None = None
        self._ptt_released_at: float | None = None
        self._ptt_capture_target: str | None = None
        self._last_connectivity_mode = self.mode_manager.status(refresh=False).effective_mode
        self._background_tasks: set[asyncio.Task] = set()
        # One bound for every chat call (owner turns and guest turns): a
        # stalled transport must return a spoken fact, never freeze the
        # console (BH-I12).
        # BUG5 half-duplex: capture muted while she is speaking (+ guard)
        self._speaking_until: float = 0.0
        self._speaking_text: str | None = None
        # BUG 6f: cached acks are real playback too. Reserve the gate before
        # scheduling them, and hold it for the actual player's lifetime (not a
        # text-duration estimate). Separate workers survive waiter cancellation:
        # cancelling to_thread cannot stop audio already playing in that thread.
        self._ack_playbacks: set[asyncio.Task] = set()
        # BUG F / Bug 8 (2026-10-20): the single 4 s total-turn bound is gone.
        # Two deadlines from [gemini]: a streaming first-token deadline (a
        # transport with no first token is dead) and a generous total bound (a
        # generation that started is delivered VERBATIM). Overridable per
        # instance by tests.
        _gem = config.section("gemini")
        self._chat_timeout_s = float(_gem.get("chat_timeout_s", 30.0))
        self._chat_first_token_s = float(_gem.get("chat_first_token_s", 5.0))
        self._load_relationship_state()

    async def broadcast(self, event: dict) -> None:
        line = (json.dumps(event) + "\n").encode()
        # Snapshot subscribers to avoid mutation during iteration
        for writer in list(self._subscribers):
            try:
                writer.write(line)
            except (ConnectionResetError, BrokenPipeError, RuntimeError, OSError):
                # Immediate write failure = real disconnect, prune
                self._subscribers.discard(writer)
                continue
            # Drain in background with timeout; prune only on real disconnect,
            # NOT on silence or slow peer. A slow peer stays subscribed.
            async def _drain(w=writer):
                try:
                    await asyncio.wait_for(w.drain(), timeout=1.0)
                except (ConnectionResetError, BrokenPipeError, RuntimeError, OSError):
                    self._subscribers.discard(w)
                except TimeoutError:
                    # Timeout is NOT a disconnect — keep subscriber for think-time
                    pass
                except Exception as exc:
                    # A drain that fails for any other reason is a real
                    # subscriber failure: drop it and say why, never `pass`.
                    self._subscribers.discard(w)
                    print(f"[assistd] event subscriber dropped: "
                          f"{type(exc).__name__}: {exc}", flush=True)
            self._track_task(asyncio.create_task(_drain()))

    # -- half-duplex: capture muted while speaking (BUG5) -----------------
    def _set_speaking(self, speaking: bool, *, text: str | None = None) -> None:
        if speaking:
            # Estimate duration from text length: ~150 wpm = 2.5 wps
            words = len((text or "").split())
            est_s = max(0.5, min(10.0, words / 2.5 + 0.3))
            # Guard interval after playback before mic reopens
            guard_s = 0.4
            self._speaking_until = __import__("time").monotonic() + est_s + guard_s
            # text=None means "non-speech output" (e.g. the knock sound):
            # hold the gate without clobbering the last spoken text that
            # _strip_self_echo compares against.
            if text is not None:
                self._speaking_text = text
        else:
            # Keep guard interval even after speak completes
            guard_s = 0.4
            self._speaking_until = __import__("time").monotonic() + guard_s
            # Don't clear text immediately; let guard expire

    def is_speaking(self) -> bool:
        return bool(self._ack_playbacks) or time.monotonic() < self._speaking_until

    def speaking_guard_remaining(self) -> float:
        return max(0.4 if self._ack_playbacks else 0.0,
                   self._speaking_until - time.monotonic())

    def _queue_ack_playback(self, kind: str) -> asyncio.Task:
        """Queue cached audio behind the SAME gate as capture and Live uplink.

        Close synchronously, before the playback worker or a newly started mic
        can run. Only actual worker completion opens the 400 ms tail guard;
        cancelling a fire-and-forget waiter must not reopen the mic while its
        uncancellable thread is still sending audio to the speakers.
        """
        text = STANDARD_ACKS.get(kind, "")
        self._set_speaking(True, text=text)
        playback = asyncio.create_task(asyncio.to_thread(self.speech.play_ack, kind))
        self._ack_playbacks.add(playback)

        def finished(task: asyncio.Task) -> None:
            self._ack_playbacks.discard(task)
            self._set_speaking(False, text=text)
            self._consume_task_result(task)

        playback.add_done_callback(finished)

        async def wait_for_playback():
            try:
                return await asyncio.shield(playback)
            except Exception as exc:
                await self.broadcast({"event": "speech.error", "ack_kind": kind,
                                      "error": str(exc)})
                return {"played": False, "error": str(exc)}

        return self._track_task(asyncio.create_task(wait_for_playback()))

    # -- Phase 8 connectivity / speech helpers --------------------------------
    # BUG5: capture wrapper that mutes while she is speaking + guard
    class _MutedCapture:
        """Wraps a capture source, dropping frames while speaking."""
        def __init__(self, inner, daemon):
            self._inner = inner
            self._daemon = daemon

        def __getattr__(self, name):
            # Diagnostics see through the wrapper (BUG 6): `.target`,
            # `.stalled` and friends describe the REAL capture process.
            if name.startswith("_"):
                raise AttributeError(name)
            return getattr(self._inner, name)

        async def frames(self):
            async for frame in self._inner.frames():
                # Half-duplex: mic muted while she speaks + guard after
                if self._daemon.is_speaking():
                    continue
                yield frame
        async def aclose(self):
            await self._inner.aclose()

    def _wrap_muted(self, source):
        return self._MutedCapture(source, self)

    @staticmethod
    def _echo_words(text: str) -> list[str]:
        """Comparison form for echo matching: lowercase, punctuation-free."""
        words = []
        for word in text.split():
            cleaned = "".join(
                ch for ch in word.lower() if ch.isalnum() or ch == "'")
            if cleaned:
                words.append(cleaned)
        return words

    def _strip_self_echo(self, transcript_text: str) -> str:
        """Remove HER OWN WORDS from a transcript; never remove the user's.

        BH-K2: the old _is_echo judged by TIMING (a transcript landing
        inside the ack window was "echo" whatever it said) or by
        filler-phrase resemblance, and _finish_dictation wiped the whole
        text on that basis — real dictation finished within ~1.5 s of an
        ack, or merely containing "how can i help", vanished. Echo is a
        textual claim: the mic heard the words she actually spoke
        (`_speaking_text`). Compare words instead: an exact match or a
        >=2-word contiguous run of her sentence is hers; her words as a
        PREFIX are excised and the user's remainder kept. Timing is not
        consulted: frame-level gating means her audio should never reach
        ASR at all, and when it leaks, the words themselves prove it.
        """
        spoken = self._speaking_text
        if not transcript_text or not spoken:
            return transcript_text
        t_norm = self._echo_words(transcript_text)
        s_norm = self._echo_words(spoken)
        if not t_norm or not s_norm:
            return transcript_text
        if t_norm == s_norm:
            return ""
        if len(t_norm) > len(s_norm) and t_norm[:len(s_norm)] == s_norm:
            # Her sentence, then the user's: walk the raw words, dropping
            # the first len(s_norm) comparable ones, keep the rest verbatim.
            kept: list[str] = []
            seen = 0
            for word in transcript_text.split():
                if seen < len(s_norm):
                    if self._echo_words(word):
                        seen += 1
                    continue
                kept.append(word)
            return " ".join(kept).strip(" .,!?")
        if len(t_norm) >= 2 and any(
                s_norm[i:i + len(t_norm)] == t_norm
                for i in range(len(s_norm) - len(t_norm) + 1)):
            # A fragment of her sentence (mic opened mid-playback). The
            # >=2-word floor keeps BH-I5: "No." answered after she said
            # "No. Not at this hour." is the USER's one-word reply.
            return ""
        return transcript_text

    def _is_echo(self, transcript_text: str) -> bool:
        """True when the transcript is ENTIRELY her own recent speech."""
        return bool(transcript_text) and not self._strip_self_echo(transcript_text)

    def _track_task(self, task: asyncio.Task) -> asyncio.Task:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _meeting_mode(self) -> str:
        if self._meeting is not None:
            return "meeting"
        if self._meeting_processing:
            return "processing"
        return "idle"

    def _session_active(self) -> bool:
        return bool((self._dictation_task and not self._dictation_task.done())
                    or self._ptt_processing
                    or self._meeting is not None or self._meeting_processing)

    async def _note_connectivity_transition(self, status) -> None:
        previous = self._last_connectivity_mode
        current = status.effective_mode
        if current == previous:
            return
        self._last_connectivity_mode = current
        await self.broadcast({
            "event": "mode.changed", "from": previous, "to": current,
            "connectivity": status.as_dict(),
        })
        if (status.is_online and previous != "ONLINE"
                and self.config.section("connectivity").get("drain_on_reconnect", True)):
            self._track_task(asyncio.create_task(self._drain_queue_and_announce()))

    async def _connectivity_snapshot(self, *, refresh: bool = True):
        """Connectivity status without letting a TCP health probe block the
        event loop (and therefore the ack/PTT latency path)."""
        if refresh:
            status = await asyncio.to_thread(self.mode_manager.status)
        else:
            status = self.mode_manager.status(refresh=False)
        await self._note_connectivity_transition(status)
        return status

    async def _apply_pending_mode_switch(self) -> None:
        if self._session_active() or self.mode_manager.pending_preference is None:
            return
        status = await asyncio.to_thread(self.mode_manager.apply_pending_after_session)
        await self._note_connectivity_transition(status)
        await self.broadcast({"event": "status.changed", "mode": self.mode,
                              "connectivity": status.as_dict()})

    async def _drain_queue_and_announce(self) -> dict:
        result = await asyncio.to_thread(self.cloud_queue.drain)
        await self.broadcast({"event": "offline.drained", **result})
        if result.get("done") or result.get("failed") or result.get("awaiting_approval"):
            await self._speak_in_background(result["summary"])
        return result

    async def _speak_in_background(self, text: str) -> dict:
        """Fire-and-forget speech; returns at once with the route metadata."""
        route = self.speech.route(text)
        if not self.config.section("tts").get("enabled", True):
            return {**route, "played": False, "queued": False}
        self._set_speaking(True, text=text)
        self._track_task(asyncio.create_task(self._speak_once(text, route)))
        return {**route, "queued": True}

    async def _speak_once(self, text: str, route: dict):
        """Speak one utterance off-loop; failures become events, never raises.

        ONE implementation for every fire-and-forget speech path. It owns the
        half-duplex flag and clears it in `finally`, so a caller that times out
        can keep waiting on the SAME task instead of starting a second
        synthesis of the same text (BH-I4).
        """
        try:
            result = await asyncio.to_thread(self.speech.speak, text)
            if result.error and not route.get("muted"):
                await self.broadcast({"event": "speech.error", "error": result.error,
                                      **route})
            return result
        except Exception as exc:
            await self.broadcast({"event": "speech.error", "error": str(exc), **route})
            return SpeechResult(text=text.strip(), backend="none", voice_id="none",
                                muted=True, error=str(exc))
        finally:
            self._set_speaking(False, text=text)

    async def _maybe_speak_reply(self, text: str, params: dict) -> dict:
        # Hybrid: try blocking with a short timeout so a fast local render can
        # return its real audio path, but never hang a handler on slow Live TTS
        # (BUG1). On timeout the SAME task keeps running in the background - a
        # second `speak()` would double the audio (BH-I4).
        route = self.speech.route(text)
        requested = params.get("speak")
        auto = (requested is None
                and self.config.section("tts").get("speak_replies", False))
        if requested is not True and not auto:
            return {**route, "played": False, "queued": False}
        self._set_speaking(True, text=text)
        task = self._track_task(asyncio.create_task(self._speak_once(text, route)))
        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=1.5)
        except TimeoutError:
            # Live TTS is slow; the task already owns the speaking flag and
            # will clear it when the real playback finishes.
            return {**route, "played": False, "queued": True,
                    "note": "speech continues in the background (timeout)"}
        return result.as_dict()

    # -- relationship state persists across restarts (§16) -------------------
    def _load_relationship_state(self) -> None:
        raw = self.store.get_state("persona")
        if raw:
            try:
                saved = json.loads(raw)
                self.governor.familiarity = float(saved.get("familiarity", 0.0))
            except (ValueError, TypeError) as exc:
                # A corrupt row is not fatal, but silence would hide it forever.
                print(f"[assistd] relationship state unreadable: "
                      f"{type(exc).__name__}: {exc}", flush=True)

    def _save_relationship_state(self) -> None:
        self.store.set_state(
            "persona", json.dumps({"familiarity": self.governor.familiarity})
        )

    # -- handlers --------------------------------------------------------------
    def _handlers(self) -> dict:
        """The real IPC dispatch table — one place, inspectable by tests.

        BUG A (external submission, 2026-10-20): an instance attribute with
        the same name as a handler method (their `self._hotword_stop` Event
        shadowing `_hotword_stop`) silently resolved `hotword.stop` to a
        non-callable and died with TypeError at dispatch. Every entry here
        must be a *bound method of this instance*; the integrity test calls
        each one by name and fails on exactly that collision.
        """
        return {
            "ping": self._ping,
            "status": self._status,
            "cost": self._cost,
            "ack": self._ack,
            "halt": self._halt,
            "resume": self._resume,
            "ptt.start": self._ptt_start,
            "ptt.stop": self._ptt_stop,
            "ptt.result": self._ptt_result,
            "transcribe.file": self._transcribe_file,
            "index.run": self._index_run,
            "plan.build": self._plan_build,
            "plan.show": self._plan_show,
            "plan.list": self._plan_list,
            "docs.search": self._docs_search,
            "plan.apply": self._plan_apply,
            "review.list": self._review_list,
            "review.decide": self._review_decide,
            "undo": self._undo,
            "verify": self._verify,
            "memory.remember": self._memory_remember,
            "memory.list": self._memory_list,
            "memory.forget": self._memory_forget,
            "memory.recall": self._memory_recall,
            "embed.run": self._embed_run,
            "meeting.start": self._meeting_start,
            "meeting.stop": self._meeting_stop,
            "mode.status": self._mode_status,
            "mode.set": self._mode_set,
            "mode.refresh": self._mode_refresh,
            "speech.status": self._speech_status,
            "speech.models": self._speech_models,
            "speech.say": self._speech_say,
            "speech.warm": self._speech_warm,
            "speech.audition": self._speech_audition,
            "speech.select": self._speech_select,
            "queue.list": self._queue_list,
            "queue.drain": self._queue_drain,
            "queue.approve": self._queue_approve,
            "queue.enqueue_external": self._queue_enqueue_external,
            "console.state": self._console_state,
            "knock.list": self._knock_list,
            "knock.raise": self._knock_raise,
            "knock.accept": self._knock_accept,
            "knock.decline": self._knock_decline,
            "knock.later": self._knock_later,
            "knock.ignore": self._knock_ignore,
            "knock.due": self._knock_due,
            "initiative.status": self._initiative_status,
            "hotword.status": self._hotword_status,
            "hotword.start": self._hotword_start,
            "hotword.stop": self._hotword_stop,
            "hotword.purge": self._hotword_purge,
            "privacy.status": self._privacy_status,
            "privacy.set": self._privacy_set,
            "privacy.toggle": self._privacy_toggle,
            "showoff.status": self._showoff_status,
            "showoff.enter": self._showoff_enter,
            "showoff.exit": self._showoff_exit,
            "showoff.demo": self._showoff_demo,
            "console.say": self._console_say,
            "class.status": self._class_status,
            "class.set": self._class_set,
            "class.toggle": self._class_toggle,
            "ask": self._ask,
        }

    def _require_ipc_owner(self) -> IpcPrincipal:
        """Return this request's kernel-authenticated local owner principal (I5)."""
        principal = self._ipc_principal.get()
        if principal is None or principal.uid != os.getuid():
            raise PermissionError(
                "state-changing IPC requires the daemon's authenticated local owner")
        return principal

    async def handle(self, method: str, params: dict, writer=None) -> dict:
        principal_token = method_token = None
        if writer is not None:
            principal = ipc_peer_principal(writer)
            if principal.uid != os.getuid():
                raise PermissionError(
                    "IPC peer UID does not match the daemon's local owner")
            principal_token = self._ipc_principal.set(principal)
            method_token = self._ipc_method.set(method)
        try:
            handlers = self._handlers()
            if method == "events.subscribe":
                if writer is not None:
                    self._subscribers.add(writer)
                return {"subscribed": True,
                        "events": ["session.started", "transcript.interim",
                                   "session.checkin", "session.offline",
                                   "transcript.final", "session.ended",
                                   "transcript.echo_suppressed",
                                   "live.uplink_gated", "live.output_audio",
                                   "live.output_transcript", "live.duplex",
                                   "ptt.result",
                                   "mode.changed", "offline.drained",
                                   "speech.error", "conversation.message",
                                   "class.changed", "knock.raised",
                                   "knock.accepted", "knock.changed", "error"]}
            handler = handlers.get(method)
            if handler is None:
                raise ValueError(f"unknown method '{method}' — supported: "
                                 f"{', '.join(sorted(handlers))}, events.subscribe")
            return await handler(params)
        finally:
            if method_token is not None:
                self._ipc_method.reset(method_token)
            if principal_token is not None:
                self._ipc_principal.reset(principal_token)

    async def _ping(self, params: dict) -> dict:
        return {"pong": True, "version": __version__}

    async def _status(self, params: dict) -> dict:
        runtime = self.config.socket_path.parent
        connectivity = await self._connectivity_snapshot()
        recent = self.store.recent_transcripts(1)
        last = None
        if recent:
            snippet = (recent[0]["cleaned_text"] or recent[0]["raw_text"] or "").strip()
            last = {"snippet": snippet[:80] + ("…" if len(snippet) > 80 else ""),
                    "ts": recent[0]["ts"], "backend": recent[0]["backend"]}
        capture = None
        capture_target = None
        if self._capture_source is not None:
            capture = type(self._capture_source).__name__.replace("Capture", "").lower()
            capture_target = str(getattr(self._capture_source, "target", None)
                                 or "default")
        # BUG 6: the last session's capture facts (node/bytes/peak) and the
        # resolved mic node — "it captured nothing" must be visible here.
        last_capture = None
        try:
            for event in self.store.list_persona_events(kind="capture.stats", limit=1):
                last_capture = json.loads(event.get("detail") or "{}")
                last_capture["ts"] = event.get("ts")
                break
        except Exception as exc:  # BH-K31: a broken diagnostics read must
            # be visible in status, not indistinguishable from "never happened"
            last_capture = {"error": f"{type(exc).__name__}: {exc}"}
        return {
            "running": True,
            "name": self.config.section("persona").get("name", "Elaria"),
            "version": __version__,
            "mode": self.mode,
            "halted": is_halted(runtime),
            "gemini_mode": self.config.gemini_mode,
            "started_at": self.started_at,
            "uptime_s": round(time.monotonic() - self.started_monotonic, 1),
            "outstanding_intents": len(self.store.outstanding_intents()),
            "dictation_active": bool(self._dictation_task and not self._dictation_task.done()),
            "dictation_processing": self._ptt_processing,
            "ptt_session_id": self._ptt_session_id,
            "capture": capture,
            "capture_target": capture_target,
            "last_capture": last_capture,
            "reply_substitutions": self._reply_substitution_records(limit=5),
            "hotword": {"armed": self.wake_guard.armed,
                        "state": self.wake_guard.state,
                        "watchdog": self.wake_guard.watchdog.state},
            "last_transcript": last,
            "quota_today_live_calls": self.store.user_turn_calls_since(day_start_iso()),
            "quota_today_housekeeping": self.store.housekeeping_calls_since(day_start_iso()),
            "quota_by_purpose": self.store.calls_by_purpose_since(day_start_iso()),
            "event_subscribers": len(self._subscribers),
            "connectivity": connectivity.as_dict(),
            "connectivity_mode": connectivity.effective_mode,
            "voice": self.speech.status(),
            "class_mode": self.presence.status().as_dict(),
            "knock": self.initiative.status(),
            "showoff": self.showoff.status(),
            "company": self.disclosure.status(),
            "console": {
                "conversation_id": (self.sessions.history()["id"]),
                "messages": len(self.sessions.history()["messages"]),
                "holding": len(self.store.list_holdings("active")),
            },
            "offline_asr": local_asr_status(self.config),
            "cloud_queue": self.store.cloud_job_counts(),
        }

    async def _cost(self, params: dict) -> dict:
        month = self.store.llm_summary(month_start_iso())
        today = self.store.llm_summary(day_start_iso())
        today["live_calls"] = self.store.calls_since(day_start_iso())
        # BUG3: quota counts only user turns; housekeeping is reported separately
        today["user_turn_calls"] = self.store.user_turn_calls_since(day_start_iso())
        today["housekeeping_calls"] = self.store.housekeeping_calls_since(day_start_iso())
        today["by_purpose"] = self.store.calls_by_purpose_since(day_start_iso())
        # Keep live_calls as user_turn_calls for quota semantics (the bug was 10 counted as 10 quota)
        today["quota_calls"] = today["user_turn_calls"]
        month["by_purpose"] = month.get("by_purpose", [])
        # BUG6 cost audit: the count alone cannot distinguish the known
        # key/voice errors from a silent Live failure. Every failed row is
        # listed with its purpose and error.
        month["failures_detail"] = self.store.failure_summary_since(month_start_iso())
        # Bug 8: generated replies that never reached the user — the ledger
        # must show the discards too, or a working ledger hides them.
        today["reply_substitutions"] = self._reply_substitution_records(limit=10)
        return {"month": month, "today": today,
                "quota": self.config.section("quota"),
                "tier": self.config.section("privacy").get("tier", "free")}

    async def _ack(self, params: dict) -> dict:
        """§18: acknowledge first, think second. Pure local code — this
        handler cannot reach GeminiClient by construction. Speech is a
        cache lookup only here; synthesis happens at startup/warm time."""
        ack = self.governor.ack()
        kind = str(params.get("kind") or "on_it")
        route = self.speech.route(STANDARD_ACKS.get(kind, "On it."))
        cached = self.speech.cached_ack(kind)
        class_mode = self.presence.status().enabled
        should_speak = bool(params.get("speak",
                                      self.config.section("tts").get("speak_acks", True)))
        if class_mode:
            should_speak = False       # spoken acks OFF in class mode
        if should_speak and cached is None and not route["muted"]:
            await self._await_ack_cache()          # VB-13: boot warming, once
            cached = self.speech.cached_ack(kind)
        ack["speech"] = {**route, "ack_kind": kind, "audio_path": cached,
                         "cached": cached is not None, "played": False,
                         # A miss while she is supposed to speak is a reported
                         # condition (VB-2), not a verdict: the re-warm below is
                         # what makes the next press audible.
                         "cache_miss": cached is None and not route["muted"],
                         "class_mode": class_mode,
                         "speak_suppressed": ("class mode: spoken acks OFF"
                                              if class_mode else None)}
        if cached is None:
            self._schedule_rewarm_if_requested()   # VB-2: miss -> one warm cycle
        if should_speak and cached:
            self._queue_ack_playback(kind)
            ack["speech"]["queued"] = True
        self.store.log_persona_event(iso_now(), "ack", json.dumps(ack))
        return ack

    # Intents that change the user's files. Reached from a dictation transcript,
    # they get the strict gate; read-only intents keep their normal behaviour.
    MUTATING_INTENTS = ("undo",)

    def _command_gate(self, result: dict) -> dict | None:
        """VB-8: no intent executes from a transcript she is not sure about.

        Command mode and dictation share one microphone, so background speech (a
        TV saying "undo.") lands in the same buffer as a deliberate command and the
        same buffer used to feed the intent ladder directly. Two facts decide it,
        both already computed: cleanup's `flagged` (the transcript is unreliable and
        kept for review) and ASR's `confidence`. A veto is silent about actions and
        loud about state: the text, the numbers, and the fact that nothing ran.
        """
        from .intents import route as route_intent

        text = str(result.get("text") or "").strip()
        confidence = result.get("confidence")
        flagged = bool(result.get("flagged"))
        threshold = float(self.config.section("transcribe").get("command_min_confidence",
                                                                 0.85))
        try:
            intent = route_intent(text)
        except Exception:            # a router that cannot parse cannot act either
            intent = None
        mutating = bool(intent is not None and str(getattr(intent, "kind", ""))
                        in self.MUTATING_INTENTS)
        low = confidence is not None and float(confidence) < threshold
        unknown = confidence is None
        # Flagged or below-threshold: nothing is routed, because the words
        # themselves are in doubt. Known-confident, or unknown-but-harmless
        # (a read-only intent): the ladder runs, as it did before. `mutating`
        # is the line a mumble can never cross on an unverifiable transcript.
        if not (flagged or low or (unknown and mutating)):
            return None
        reasons = []
        if flagged:
            reasons.append("cleanup flagged this transcript as unreliable")
        if low:
            reasons.append(f"ASR confidence {float(confidence):.2f} is below "
                           f"{threshold:.2f}")
        if unknown and mutating:
            reasons.append("confidence is unknown and the intent would change files")
        return {
            "via": "refused",
            "executed": False,
            "intent": (getattr(intent, "kind", None) if intent is not None else None),
            "text": text,
            "confidence": confidence,
            "flagged": flagged,
            "threshold": threshold,
            "reason": "; ".join(reasons) or "gated",
            "note": ("Not executed — " + "; ".join(reasons)
                      + ". Repeat it clearly, or run the command deliberately "
                        "(`assist undo`, `assist remember ...`)."),
        }

    async def _halt(self, params: dict) -> dict:
        set_halt(self.config.socket_path.parent)
        self.mode = "halted"
        await self.broadcast({"event": "status.changed", "mode": self.mode, "halted": True})
        return {"halted": True, "note": "executor checks this flag between every op (§4.4)"}

    async def _resume(self, params: dict) -> dict:
        clear_halt(self.config.socket_path.parent)
        if self.mode == "halted":
            self.mode = "idle"
        await self.broadcast({"event": "status.changed", "mode": self.mode, "halted": False})
        return {"halted": False}

    async def _mode_status(self, params: dict) -> dict:
        status = await self._connectivity_snapshot(
            refresh=bool(params.get("refresh", True)))
        return {"connectivity": status.as_dict(),
                "cloud_queue": self.store.cloud_job_counts(),
                "session_active": self._session_active()}

    async def _mode_set(self, params: dict) -> dict:
        value = str(params.get("mode") or params.get("preference") or "")
        if not value:
            raise ValueError("mode.set needs params.mode = auto|online|offline")
        status = await asyncio.to_thread(
            self.mode_manager.request_preference,
            value, active_session=self._session_active())
        await self._note_connectivity_transition(status)
        await self.broadcast({"event": "status.changed", "mode": self.mode,
                              "connectivity": status.as_dict()})
        return {"connectivity": status.as_dict(),
                "session_active": self._session_active(),
                "note": ("switch parked until the active session finishes"
                         if status.switch_parked else "mode applied")}

    async def _mode_refresh(self, params: dict) -> dict:
        status = await asyncio.to_thread(self.mode_manager.refresh, force=True)
        await self._note_connectivity_transition(status)
        return {"connectivity": status.as_dict()}

    async def _console_state(self, params: dict) -> dict:
        return self.console.snapshot()

    async def _console_say(self, params: dict) -> dict:
        """A text turn in the SAME conversation a voice turn writes to."""
        text = str(params.get("text") or "").strip()
        if not text:
            raise ValueError("console.say needs params.text")
        result = await self._ask({
            "text": text, "speak": bool(params.get("speak", False)),
            "channel": "console",
        })
        return {**result, "channel": "console",
                "conversation": self.sessions.history(limit=int(
                    params.get("history_limit", 40)))}

    # -- the knock (§19.2 as amended) ----------------------------------------
    def _knock_dict(self, knock: dict) -> dict:
        return {**knock, "silent": self.presence.status().enabled,
                "first_line": knock.get("reason")}

    async def _knock_list(self, params: dict) -> dict:
        status = params.get("status", "pending")
        limit = int(params.get("limit", 50))
        knocks = ([self._knock_dict(k)
                   for k in self.store.list_knocks(status, limit=limit)]
                  if status else
                  [self._knock_dict(k)
                   for k in self.store.list_knocks(None, limit=limit)])
        return {"knocks": knocks, "status": self.initiative.status(),
                "class_mode": self.presence.status().as_dict()}

    async def _knock_raise(self, params: dict) -> dict:
        try:
            knock = self.initiative.raise_knock(
                topic=str(params.get("topic") or ""),
                reason=str(params.get("reason") or ""),
                kind=str(params.get("kind") or "follow-up"),
                urgency=str(params.get("urgency") or "normal"),
                referent=params.get("referent"),
                commitment_id=(_int_param(params, "commitment_id")
                               if params.get("commitment_id") is not None
                               else None))
        except InitiativeError as exc:
            raise ValueError(str(exc)) from exc
        # BH-K9: delivering the knock runs subprocesses (desktop
        # notification + player, up to 5s each) — on this event loop it
        # froze every IPC call, ptt.stop included, and the knock played
        # outside the speaking gate into any open capture. Thread + gate;
        # class mode is a silent pulse (BH-H13: emit stays in-handler).
        knock_emit = self.knock_signal.emit
        if self.presence.status().enabled:
            signal = knock_emit(knock, class_mode=True)
        else:
            self._set_speaking(True)
            try:
                signal = await asyncio.to_thread(
                    knock_emit, knock, class_mode=False)
            finally:
                self._set_speaking(False)
        knock = self._knock_dict(knock)
        await self.broadcast({"event": "knock.raised", "knock": knock,
                              "signal": signal})
        return {"knock": knock, "signal": signal}

    async def _knock_accept(self, params: dict) -> dict:
        # The request method plus the kernel-authenticated socket peer is the
        # owner's explicit accept. Serialized channel/score claims are not
        # authority, on either the wake-knock or initiative path (I5).
        if "channel" in params or "voiceprint_score" in params:
            raise ValueError(
                "refused: knock.accept does not accept caller-supplied "
                "channel or voiceprint_score; use the authenticated owner action")
        knock_id = _int_param(params, "id")
        knock_row = self.store.get_knock(knock_id)
        if knock_row is not None and knock_row.get("kind") == "wake":
            return await self._wake_knock_accept(knock_id, params)
        class_now = self.presence.status().enabled
        speech_status = self.speech.status()
        voice_muted = bool(
            speech_status.get("muted")
            if "muted" in speech_status
            else (speech_status.get("voice") or {}).get("muted")
        )
        try:
            result = self.initiative.accept(
                knock_id, class_mode=class_now,
                voice_available=not voice_muted)
        except InitiativeError as exc:
            existing = self.store.get_knock(knock_id)
            existing_msgs = self.sessions.history(limit=40).get("messages") or []
            already_appended = any(
                m.get("via") == "knock" and m.get("text") == (existing or {}).get("reason")
                for m in existing_msgs
            )
            if existing and existing.get("status") == "accepted" and not already_appended:
                mode = "console" if class_now or voice_muted else "voice"
                result = {
                    "knock": existing,
                    "open": mode,
                    "first_line": existing["reason"],
                    "class_mode": class_now,
                }
            else:
                raise ValueError(str(exc)) from exc
        opened = result["open"]
        # Her REASON is the first line of the turn, whichever surface opened.
        if self.initiative.sessions is None:
            self.sessions.append("assistant", result["first_line"],
                                 channel=opened, via="knock", ts=iso_now())
        conversation_id = self.sessions.history()["id"]
        payload = {**result, "conversation_id": conversation_id,
                   "conversation": self.sessions.history(
                       limit=int(params.get("history_limit", 40)))}
        await self.broadcast({"event": "knock.accepted",
                              "knock": result["knock"],
                              "open": opened, "first_line": result["first_line"],
                              "conversation_id": conversation_id})
        await self.broadcast({"event": "conversation.message",
                              "conversation_id": conversation_id,
                              "channel": opened, "role": "assistant"})
        return payload

    async def _wake_knock_accept(self, knock_id: int, params: dict) -> dict:
        """Accept a wake-knock only for the authenticated local IPC owner (I5).

        Voice accept is unavailable until fresh accept audio is captured and
        scored inside the daemon; the request body cannot choose a channel or
        supply a confidence score. The guest door stays show-off's alone.
        """
        from .wake_guard import WakeGuardError

        principal = self._require_ipc_owner()
        try:
            gate = self.wake_guard.wake_knock_accepted(
                knock_id=knock_id, principal=principal)
        except WakeGuardError as exc:
            raise ValueError(str(exc)) from exc
        class_now = self.presence.status().enabled
        result = self.initiative.accept(
            knock_id, class_mode=class_now,
            voice_available=(gate.get("open") == "listening"))
        opened = gate.get("open", result.get("open"))
        payload = {**result, "open": opened, "wake": gate}
        await self.broadcast({"event": "knock.accepted",
                              "knock": result["knock"],
                              "open": opened, "first_line": result["first_line"]})
        return payload

    async def _knock_decline(self, params: dict) -> dict:
        knock_id = _int_param(params, "id")
        try:
            result = self.initiative.decline(knock_id)
        except InitiativeError as exc:
            raise ValueError(str(exc)) from exc
        self._wake_knock_denied(knock_id, "declined")
        await self.broadcast({"event": "knock.changed", "knock": result["knock"],
                              "action": "declined"})
        return result

    def _wake_knock_denied(self, knock_id: int, action: str) -> None:
        """Decline/ignore of a wake-knock returns the gate to sleep."""
        row = self.store.get_knock(knock_id)
        if (row is not None and row.get("kind") == "wake"
                and self.wake_guard.state == "wake_knock"):
            self.wake_guard.wake_knock_denied(knock_id=knock_id, action=action)

    async def _knock_later(self, params: dict) -> dict:
        try:
            result = self.initiative.later(
                _int_param(params, "id"), hours=params.get("hours"))
        except InitiativeError as exc:
            raise ValueError(str(exc)) from exc
        await self.broadcast({"event": "knock.changed", "knock": result["knock"],
                              "action": "snoozed"})
        return result

    async def _knock_ignore(self, params: dict) -> dict:
        knock_id = _int_param(params, "id")
        try:
            result = self.initiative.ignore(knock_id)
        except InitiativeError as exc:
            raise ValueError(str(exc)) from exc
        self._wake_knock_denied(knock_id, "ignored")
        await self.broadcast({"event": "knock.changed", "knock": result["knock"],
                              "action": "retired" if result["retired"] else "ignored"})
        return result

    async def _knock_due_loop(self) -> None:
        """Wake the user's own commitments when they come due (§19.2).

        This is NOT time-based initiative: the loop only re-reads snoozes the
        user created via "later". A topic she invented has no row to wake.
        """
        while True:
            try:
                await self._knock_due({})
            except Exception as exc:      # a bad row must not kill the loop
                print(f"[assistd] knock due-check failed: {exc}", flush=True)
            await asyncio.sleep(60)

    async def _knock_due(self, params: dict) -> dict:
        raised = []
        for knock in self.initiative.check_due():
            # BH-K9: see _knock_raise — knock delivery runs subprocesses;
            # never on this event loop, never outside the speaking gate.
            knock_emit = self.knock_signal.emit
            if self.presence.status().enabled:
                signal = knock_emit(knock, class_mode=True)
            else:
                self._set_speaking(True)
                try:
                    signal = await asyncio.to_thread(
                        knock_emit, knock, class_mode=False)
                finally:
                    self._set_speaking(False)
            knock = self._knock_dict(knock)
            raised.append(knock)
            await self.broadcast({"event": "knock.raised", "knock": knock,
                                  "signal": signal})
        return {"raised": raised, "count": len(raised)}

    async def _initiative_status(self, params: dict) -> dict:
        return {"initiative": self.initiative.status(),
                "class_mode": self.presence.status().as_dict()}

    # -- hotword: wake-knock model (never straight hit->listening) ----------
    def _hotword_capture_factory(self):
        """Always-on capture for the wake path (production mic path)."""
        from .capture import PipeWireCapture

        capture_cfg = self.config.section("capture")
        target = (capture_cfg.get("mic_target")
                  or self.config.section("meeting").get("mic_target") or None)
        # BH-K7: the constructor takes frame_ms (this said chunk_ms — a
        # TypeError on every real hotword start, invisible to tests that
        # replace the factory), and the [hotword] stall timeout must reach
        # the capture or a wedged pw-record streams for the 8s default.
        return PipeWireCapture(
            target=target or None,
            sample_rate=int(capture_cfg.get("sample_rate", 16000)),
            frame_ms=int(capture_cfg.get("chunk_ms", 30)),
            stall_timeout_s=float(
                self.config.section("hotword").get("stall_timeout_s", 2.0)))

    async def _hotword_loop(self) -> None:
        """Feed always-on frames through the guard + watchdog.

        Stall semantics: no frames for `stall_timeout_s` disarms, zeroes both
        RAM buffers and leaves a visible "stalled" state. Never a silent
        forever-recording.
        """
        guard = self.wake_guard
        source = None
        try:
            source = self._hotword_capture_factory()
            async for frame in source.frames():
                if not guard.armed:
                    break
                guard.feed(frame)
                if guard.watchdog.check():
                    guard.disarm(reason="stalled")
                    await self.broadcast({"event": "hotword.stalled",
                                          "state": "stalled"})
                    break
            # BH-K7: the stream ending underneath an armed guard IS the
            # stall (PipeWireCapture ends frames() at its stall deadline).
            # The old loop just fell out, leaving status claiming "armed"
            # over a dead capture — and its finally called a sync close()
            # PipeWireCapture does not have, leaking the pw-record process.
            if guard.armed:
                guard.disarm(reason="stalled")
                await self.broadcast({"event": "hotword.stalled",
                                      "state": "stalled"})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            guard.disarm(reason="error")
            await self.broadcast({"event": "hotword.stalled",
                                  "state": "stalled", "error": str(exc)[:200]})
        finally:
            if source is not None:
                aclose = getattr(source, "aclose", None)
                if callable(aclose):
                    # Shielded: hotword.stop cancels this task, and the
                    # capture must still be reaped (K6 escalates inside).
                    close_task = asyncio.ensure_future(aclose())
                    try:
                        await asyncio.wait_for(
                            asyncio.shield(close_task), timeout=3.0)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        print(f"[assistd] hotword capture close failed: "
                              f"{type(exc).__name__}: {exc}", flush=True)
                else:
                    close = getattr(source, "close", None)
                    if callable(close):
                        close()

    async def _hotword_start(self, params: dict) -> dict:
        from .wake_guard import KeywordModelUnavailable

        unsafe = bool(params.get("unsafe_energy_test"))
        try:
            status = self.wake_guard.arm(unsafe_energy_test=unsafe)
        except KeywordModelUnavailable as exc:
            raise ValueError(str(exc)) from exc
        if self._hotword_task is None or self._hotword_task.done():
            self._hotword_task = asyncio.create_task(self._hotword_loop())
        return {"hotword": status,
                "note": ("UNSAFE ENERGY TEST — plumbing only; this trigger "
                         "can never open command listening"
                         if unsafe else "armed with the real keyword model")}

    async def _hotword_stop(self, params: dict) -> dict:
        task = self._hotword_task
        self._hotword_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        return {"hotword": self.wake_guard.disarm(reason="manual")}

    async def _hotword_status(self, params: dict) -> dict:
        return {"hotword": self.wake_guard.status()}

    async def _hotword_purge(self, params: dict) -> dict:
        removed = self.wake_guard.clips.purge()
        return {"purged": removed}

    async def _class_status(self, params: dict) -> dict:
        return {"class_mode": self.presence.status().as_dict()}

    async def _class_set(self, params: dict) -> dict:
        if "enabled" in params:
            raw_enabled = params["enabled"]
            enabled = (
                raw_enabled.strip().lower() in ("1", "true", "yes", "on")
                if isinstance(raw_enabled, str)
                else bool(raw_enabled)
            )
            status = self.presence.set_enabled(enabled)
        elif str(params.get("action") or "").lower() == "toggle":
            status = self.presence.toggle()
        else:
            raise ValueError("class.set needs params.enabled (bool) or action=toggle")
        await self.broadcast({"event": "class.changed",
                              "class_mode": status.as_dict()})
        return {"class_mode": status.as_dict(), "enabled": status.enabled}

    async def _class_toggle(self, params: dict) -> dict:
        status = self.presence.toggle()
        await self.broadcast({"event": "class.changed",
                              "class_mode": status.as_dict()})
        return {"class_mode": status.as_dict()}

    async def _speech_status(self, params: dict) -> dict:
        return {"voice": self.speech.status()}

    async def _speech_models(self, params: dict) -> dict:
        """`assist voice models`: the real list, never a remembered model name."""
        return await asyncio.to_thread(self.client.list_models)

    async def _speech_say(self, params: dict) -> dict:
        text = str(params.get("text") or "").strip()
        if not text:
            raise ValueError("speech.say needs params.text")
        result = await asyncio.to_thread(
            self.speech.speak, text, play=bool(params.get("play", True)))
        return {"speech": result.as_dict()}

    async def _speech_warm(self, params: dict) -> dict:
        """`speech.warm`: an explicit warm cycle (also `assist voice warm`).

        Opening the ack gate here is what makes `assist voice warm` the documented
        cure for a cold cache: from now on the hot path is allowed to answer.
        """
        warmed = await asyncio.to_thread(self.speech.warm_ack_cache)
        if self.speech.ack_cache_state()["complete"]:
            self._ack_cache_ready.set()
        return {"warmed": warmed, "voice": self.speech.status()}

    async def _speech_audition(self, params: dict) -> dict:
        manifest = await asyncio.to_thread(
            self.speech.generate_auditions, params.get("text"))
        return {"audition": manifest}

    async def _speech_select(self, params: dict) -> dict:
        candidate = self.speech.select_voice(str(params.get("candidate") or ""))
        return {"selected": candidate.as_dict(), "voice": self.speech.status()}

    async def _queue_list(self, params: dict) -> dict:
        return {"jobs": self.cloud_queue.list_jobs(params.get("status"),
                                                  int(params.get("limit", 100))),
                "counts": self.store.cloud_job_counts()}

    async def _queue_drain(self, params: dict) -> dict:
        return await self._drain_queue_and_announce()

    async def _queue_approve(self, params: dict) -> dict:
        job = self.cloud_queue.approve(_int_param(params, "job_id"))
        return {"job": job, "note": "approved; run queue.drain to process it"}

    async def _queue_enqueue_external(self, params: dict) -> dict:
        job_id = self.cloud_queue.enqueue_external(
            str(params.get("action") or "external"),
            str(params.get("description") or ""),
            dict(params.get("payload") or {}))
        return {"job_id": job_id, "status": "awaiting_approval"}

    @property
    def _ptt_processing(self) -> bool:
        """True while any released session still has its finisher in flight.

        Derived (BUG 6d) so a superseded session's late finish can never
        clear — or fail to clear — another session's processing state.
        """
        return bool(self._ptt_finishing)

    def _ptt_log(self, step: str, **fields) -> None:
        """BUG 6c instrumentation: ptt.start -> session create -> capture spawn.

        Each step is a persona event so the next hardware run shows exactly
        where it stops — "capture_target" in status alone is not enough when
        last_capture stays null and the journal has no capture/dictate lines.
        """
        try:
            self.store.log_persona_event(
                iso_now(), "ptt.lifecycle", json.dumps({"step": step, **fields}))
        except Exception:
            return

    def _dictate_log(self, step: str, **fields) -> None:
        """Lifecycle markers for work after the dictation task returns."""
        try:
            self.store.log_persona_event(
                iso_now(), "dictate.lifecycle", json.dumps({"step": step, **fields}))
        except Exception:
            return

    @staticmethod
    def _consume_task_result(task: asyncio.Future) -> None:
        if task.cancelled():
            return
        try:
            task.exception()
        except BaseException:
            return

    async def _await_dictate_step(self, step: str, awaitable, *,
                                  session_id: str | None,
                                  timeout_s: float):
        """Bound and journal post-dictation daemon work."""
        timeout_s = max(0.0, float(timeout_s))
        started = time.monotonic()
        self._dictate_log(f"{step}_start", session_id=str(session_id or ""),
                          timeout_s=timeout_s)
        task = asyncio.ensure_future(awaitable)
        try:
            done, _pending = await asyncio.wait(
                {task}, timeout=timeout_s,
                return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
                task.add_done_callback(self._consume_task_result)
            self._dictate_log(f"{step}_cancelled",
                              session_id=str(session_id or ""),
                              elapsed_s=round(time.monotonic() - started, 3))
            raise
        if not done:
            task.cancel()
            task.add_done_callback(self._consume_task_result)
            self._dictate_log(
                f"{step}_timeout", session_id=str(session_id or ""),
                timeout_s=timeout_s,
                elapsed_s=round(time.monotonic() - started, 3))
            raise TimeoutError(f"{step} timed out after {timeout_s:.1f}s")
        try:
            result = task.result()
        except Exception as exc:
            self._dictate_log(
                f"{step}_failed", session_id=str(session_id or ""),
                elapsed_s=round(time.monotonic() - started, 3),
                error=f"{type(exc).__name__}: {exc}"[:200])
            raise
        self._dictate_log(f"{step}_done", session_id=str(session_id or ""),
                          elapsed_s=round(time.monotonic() - started, 3))
        return result

    async def _ptt_start(self, params: dict) -> dict:
        # §18: ack RETURNS immediately; capture + Live session spin up in a
        # background task behind it. The user is already talking while the
        # socket opens — parse-while-you-speak starts here (§18 rule 3).
        self._ptt_log("ptt.start.received", params={k: str(v)[:80] for k, v in params.items()})
        if self._dictation_task and not self._dictation_task.done():
            # VB-11: the loser of the race is refused, and a refusal is not a
            # request to be acknowledged. She is already listening; saying "On it."
            # again is a second voice event for one press (and double audio when the
            # user mashes the hotkey). No ack is played and none is queued.
            route = self.speech.route(STANDARD_ACKS["on_it"])
            self._ptt_log("ptt.start.refused_already_listening")
            return {"listening": True, "already_listening": True, "ack": None,
                    "speech": {**route, "ack_kind": "on_it", "audio_path": None,
                               "cached": False, "played": False,
                               "suppressed": "already listening — no second ack"},
                    "note": "already listening"}
        ack = await self._ack({"kind": "on_it"})
        self._ptt_log("ptt.start.ack_done")
        capture_cfg = self.config.section("capture")
        frame_ms = int(capture_cfg.get("chunk_ms", 30))
        source_kind = params.get("source") or capture_cfg.get("source", "mic")
        # BUG 6 (2026-10-20): dictate used to spawn pw-record with NO --target
        # (params["target"] was never set by `assist dictate`) while the owner's
        # working microphone sat in config. Resolution order: explicit param →
        # [capture] mic_target → [meeting] mic_target → default source. The
        # resolved node is reported and logged — never a mystery capture.
        target = (params.get("target")
                  or capture_cfg.get("mic_target")
                  or self.config.section("meeting").get("mic_target")
                  or None)
        stall_timeout_s = float(capture_cfg.get("stall_timeout_s", 8.0))
        self._ptt_log("ptt.start.target_resolved", target=str(target or "default"), source_kind=str(source_kind))
        simulated = False
        if source_kind == "simulated":
            self._capture_source = SimulatedCapture(speech_frames=100_000,
                                                    frame_ms=frame_ms, realtime=True)
            simulated = True
            self._ptt_log("ptt.start.capture_spawn", target="simulated", simulated=True, kind="SimulatedCapture")
        else:
            try:
                self._capture_source = PipeWireCapture(
                    target, frame_ms=frame_ms, stall_timeout_s=stall_timeout_s)
                self._ptt_log("ptt.start.capture_spawn", target=str(target or "default"), simulated=False, kind="PipeWireCapture", stall_timeout_s=stall_timeout_s)
            except RuntimeError as exc:
                # No PipeWire (headless/containers): simulated frames keep
                # the full pipeline exercisable; status reports it honestly.
                self._capture_source = SimulatedCapture(speech_frames=100_000,
                                                        frame_ms=frame_ms, realtime=True)
                simulated = True
                self._ptt_log("ptt.start.capture_spawn_fallback", target=str(target or "default"), reason=str(exc)[:120], kind="SimulatedCapture")
        self._stop_event = asyncio.Event()
        self._dictation_session_mode = str(params.get("mode") or "narration")
        self.mode = "listening"
        self._ptt_log("ptt.start.mode_listening", mode=self.mode)
        # Hotkey path: use the monitor's latest snapshot, never probe here.
        connectivity = await self._connectivity_snapshot(refresh=False)
        await self.broadcast({"event": "status.changed", "mode": self.mode,
                              "connectivity": connectivity.as_dict()})

        async def dictation_sink(event: dict) -> None:
            # Cached audio only: the soft check-in must never wait on TTS.
            if event.get("event") == "session.checkin" and self.speech.cached_ack("checkin"):
                self._queue_ack_playback("checkin")
            await self.broadcast(event)

        # BUG5: wrap source to mute while speaking. BUG6: the Live transport
        # gets the same playback probe so its own uplink gate agrees with the
        # daemon's half-duplex state, instead of relying on the wrapper alone.
        muted_source = self._wrap_muted(self._capture_source)
        session_id = uuid.uuid4().hex[:12]
        old_session_id = self._ptt_session_id
        self._ptt_session_id = session_id
        self._ptt_last_session_id = session_id
        self._ptt_last_result = None
        self._ptt_results.pop(session_id, None)
        self._ptt_result_events.pop(session_id, None)
        self._ptt_finishing.discard(session_id)
        self._ptt_started_at = time.monotonic()
        self._ptt_released_at = None
        self._ptt_capture_target = str(getattr(self._capture_source, "target", None) or "default")
        # BUG 6d: a session replaced before it produced a result is TERMINAL.
        # Mark it now — "superseded, finished without a result" — so any
        # ptt.result waiter on the old id resolves at once instead of parking
        # on an event only a matching session id would ever set. A session
        # that is still finishing keeps its real result coming (its finisher
        # resolves its own waiters unconditionally).
        if (old_session_id is not None and old_session_id != session_id
                and old_session_id not in self._ptt_finishing
                and old_session_id not in self._ptt_results):
            self._ptt_log("ptt.start.superseded_without_result",
                          session_id=session_id,
                          superseded_session_id=old_session_id)
            self._ptt_mark_terminal(
                old_session_id,
                self._ptt_unfinished_payload(old_session_id,
                                             superseded_by=session_id))
        self._ptt_log("ptt.start.session_create", session_id=session_id, capture_target=self._ptt_capture_target, mode=self._dictation_session_mode)
        try:
            self._dictation_task = self._track_task(asyncio.create_task(
                self.dictation.dictate(
                    muted_source, mode=self._dictation_session_mode,
                    sink=dictation_sink, stop_event=self._stop_event,
                    is_playback_active=self.is_speaking,
                    session_id=session_id)))
            self._ptt_log("ptt.start.dictate_spawned", session_id=session_id)
        except Exception as exc:
            self._ptt_log("ptt.start.dictate_spawn_failed", session_id=session_id, error=f"{type(exc).__name__}: {exc}"[:200])
            raise
        return {"listening": True, **ack, "simulated_capture": simulated,
                "session_mode": self._dictation_session_mode,
                "session_id": session_id,
                # BUG 6 diagnostics: which node this session captures from.
                "capture_target": str(getattr(self._capture_source, "target", None)
                                      or "default"),
                "connectivity": connectivity.as_dict()}

    @staticmethod
    def _ptt_wait_budget(params: dict) -> float:
        """Validate the caller's optional PTT wait before allocating a waiter."""
        raw = params.get("wait_s", 0)
        if raw is None:
            return 0.0
        if isinstance(raw, bool):
            raise TypeError("parameter 'wait_s' must be a finite number of seconds")
        try:
            wait_s = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "parameter 'wait_s' must be a finite number of seconds") from exc
        if not math.isfinite(wait_s):
            raise ValueError("parameter 'wait_s' must be finite")
        if wait_s < 0:
            raise ValueError("parameter 'wait_s' must be non-negative")
        if wait_s > MAX_PTT_WAIT_S:
            raise ValueError(
                f"parameter 'wait_s' must not exceed {MAX_PTT_WAIT_S:g} seconds")
        return wait_s

    async def _ptt_stop(self, params: dict) -> dict:
        """Release: acknowledge in-process, finish the session in the background.

        BUG 6 (owner repro 2026-10-20): this used to await the dictation task
        here, so the IPC reply (and therefore `assist dictate`) blocked behind
        the Live activity_end, the final transcript, cleanup and any command
        routing — up to the client's 90 s timeout, with Ctrl-C the only way
        out. A stop that queues behind transcription is not a stop. The reply
        now carries the session id; `ptt.result` (or the `ptt.result` event)
        delivers the transcript when it exists.

        No spoken ack is emitted on release: the caller asked to stop, and a
        fresh "On it." from the speakers is both noise and, if the mic is still
        open for a moment, more of her own audio to transcribe. `speak=False`
        also means the reply cannot wait on the boot-time ack cache warm.
        """
        wait_s = self._ptt_wait_budget(params)
        self._ptt_log("ptt.stop.received", session_id=str(self._ptt_session_id or ""))
        ack = await self._ack({"kind": "on_it", "speak": False})
        task = self._dictation_task
        session_id = self._ptt_session_id
        if self.mode == "listening":
            self.mode = "transcribing"  # waiting on final + cleanup (§3.9 states)
            await self.broadcast({"event": "status.changed", "mode": self.mode})
            self._ptt_log("ptt.stop.mode_transcribing", session_id=str(session_id or ""))
        if self._stop_event:
            self._stop_event.set()
            self._ptt_log("ptt.stop.stop_event_set", session_id=str(session_id or ""))
        self._dictation_task = None

        if task is not None:
            self._ptt_released_at = time.monotonic()
            self._ptt_log("ptt.stop.finish_spawn", session_id=str(session_id or ""))
            if session_id is not None:
                self._ptt_finishing.add(session_id)
                self._ptt_event_for(session_id)  # waiters can park before the finish
            self._track_task(asyncio.create_task(
                self._finish_dictation(task, params, session_id,
                                       self._dictation_session_mode)))
        elif not self._ptt_processing:
            # No release in flight: a second release is a no-op, and must not
            # clear the mode or release a parked switch while the first
            # session is still being transcribed.
            self.mode = "idle"
            await self.broadcast({"event": "status.changed", "mode": self.mode})
            await self._apply_pending_mode_switch()
            self._ptt_log("ptt.stop.no_task_idle", session_id=str(session_id or ""))
            # BUG 6d: a release with no task and nothing finishing means the
            # session state ended without a result (state reset, restart).
            # That is a terminal state — answer it explicitly from now on.
            if (session_id is not None and session_id not in self._ptt_results
                    and session_id not in self._ptt_finishing):
                self._ptt_log("ptt.stop.finished_without_result",
                              session_id=str(session_id or ""))
                self._ptt_mark_terminal(
                    session_id, self._ptt_unfinished_payload(session_id))

        response = {"listening": False, **ack, "result": None,
                    "processing": task is not None or self._ptt_processing,
                    "session_id": session_id,
                    "connectivity": self.mode_manager.status(refresh=False).as_dict()}
        # Explicit opt-in for scripts/tests that want the old one-shot shape.
        # The hotkey path never sets it; nothing here waits by default.
        if wait_s > 0:
            # BUG 6c/6d: bounded wait for THIS session's terminal answer —
            # the real result, a fail-fast dead capture, or an explicit
            # "finished without a result". Never an orphaned-event wait.
            answer = await self._ptt_wait_for(session_id, wait_s)
            if answer is not None:
                response["result"] = answer
                response["processing"] = False
                if answer.get("dead_fast"):
                    response["dead_fast"] = True
            else:
                # Budget spent with the finisher still in flight: report the
                # pre-stored result if one exists, honestly processing=True.
                response["result"] = self._ptt_results.get(session_id)
                response["processing"] = (session_id is not None
                                          and session_id in self._ptt_finishing)
            response["connectivity"] = self.mode_manager.status(refresh=False).as_dict()
        return response

    def _ptt_event_for(self, session_id: str | None) -> asyncio.Event:
        """The terminal event for ONE session (BUG 6d: per session, never a
        single global event a finishing-but-superseded session forgets to set)."""
        if session_id is None:  # pragma: no cover - defensive
            session_id = ""
        ev = self._ptt_result_events.get(session_id)
        if ev is None:
            ev = asyncio.Event()
            self._ptt_result_events[session_id] = ev
        return ev

    def _ptt_mark_terminal(self, session_id: str | None,
                           result: dict | None = None) -> dict | None:
        """Record the terminal state of a session and wake EVERY waiter.

        BUG 6d: terminal is per session and unconditional. The finisher of a
        session that was superseded mid-flight still resolves its waiters.
        When `result` is None the session already has a pre-stored result and
        only the terminal transition (finishing cleared, event set) remains.
        """
        if session_id is None:
            return result
        if result is not None:
            self._ptt_results[session_id] = result
            while len(self._ptt_results) > 8:
                evicted = next(iter(self._ptt_results))
                self._ptt_results.pop(evicted, None)
                self._ptt_result_events.pop(evicted, None)
        self._ptt_finishing.discard(session_id)
        self._ptt_event_for(session_id).set()
        return result

    def _ptt_unfinished_payload(self, session_id: str | None, *,
                                superseded_by: str | None = None) -> dict:
        """The explicit terminal answer for a session that ended with NO
        result (BUG 6d): superseded by a newer session, or its session state
        reset before a transcript existed. ptt.result must say so — never a
        silent None and never an unbounded wait for an event nobody will set.
        """
        if superseded_by is not None:
            error = (f"session {session_id} was superseded by session "
                     f"{superseded_by} and finished without a result")
        elif session_id == self._ptt_session_id:
            error = (f"session {session_id} finished without a result "
                     "(session state ended before a transcript was stored)")
        else:
            error = (f"session {session_id} finished without a result "
                     "(superseded, or unknown to this daemon)")
        return {"error": error,
                "session_id": session_id,
                "terminal": True,
                "finished_without_result": True,
                "superseded": superseded_by is not None,
                "text": "", "raw_text": "",
                "no_speech": False,
                "narration": "session finished without a result"}

    def _ptt_terminal_result(self, session_id: str | None) -> dict | None:
        """The terminal answer for a session, or None while one can still come.

        BUG 6d: terminal means either (a) a stored result — real, fail-fast
        dead-capture, or synthesized — or (b) a session that can no longer
        produce one (superseded / state reset / unknown), which answers with
        an explicit error payload. A session whose dictate task is still
        alive (listening, or a completed dictate awaiting release) is NOT
        terminal: `ptt.stop` can still harvest its real result.
        """
        if session_id is None:
            return None
        if session_id in self._ptt_finishing:
            return None
        if session_id in self._ptt_results:
            return self._ptt_results[session_id]
        if session_id == self._ptt_session_id and self._dictation_task is not None:
            return None
        self._ptt_log("ptt.result.finished_without_result",
                      session_id=str(session_id or ""))
        return self._ptt_mark_terminal(
            session_id, self._ptt_unfinished_payload(session_id))

    async def _ptt_wait_for(self, session_id: str | None,
                            wait_s: float) -> dict | None:
        """Wait for ONE session's terminal answer, bounded by wait_s.

        BUG 6d: waits on that session's own terminal event and re-checks
        terminal state on every wake — a real finish (even under a changed
        session id), a fail-fast dead capture, a supersede and a session
        state reset all resolve the waiter. An orphaned or missed signal can
        never park it past its budget.
        """
        deadline = time.monotonic() + max(wait_s, 0.0)
        while True:
            terminal = self._ptt_terminal_result(session_id)
            if terminal is not None:
                return terminal
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            if session_id is not None and session_id == self._ptt_session_id:
                dead = self._ptt_is_dead_state(session_id)
                if dead.get("dead"):
                    self._ptt_log("ptt.result.dead_fast",
                                  session_id=str(session_id or ""),
                                  reason=dead.get("reason"))
                    fast = {"error": dead["reason"], "session_id": session_id,
                            "no_speech": True, "terminal": True,
                            "dead_fast": True,
                            "capture": {"node": self._ptt_capture_target or "unknown",
                                        "bytes": 0, "peak_rms": 0.0,
                                        "no_speech": True, "stalled": True},
                            "narration": "no speech captured",
                            "text": "", "raw_text": ""}
                    return self._ptt_mark_terminal(session_id, fast)
            ev = (self._ptt_result_events.get(session_id)
                  if session_id is not None else None)
            if ev is not None and not ev.is_set():
                try:
                    await asyncio.wait_for(ev.wait(), timeout=remaining)
                except TimeoutError:
                    return self._ptt_terminal_result(session_id)
                continue
            await asyncio.sleep(min(0.25, remaining))

    def _ptt_is_dead_state(self, session_id: str | None) -> dict:
        """BUG 6c: a released session whose capture will never produce stats.

        Fail-fast only — BUG 6d's terminal machinery owns every other outcome.
        The verdict is scoped to the daemon's *current* capture (the one
        `_capture_source` describes) and is measured from RELEASE: a long
        dictation is not a dead capture. This used to also run a synchronous
        store query on the event loop (and its result was never used).
        """
        if session_id is None or session_id != self._ptt_session_id:
            return {"dead": False}
        if session_id not in self._ptt_finishing:
            return {"dead": False}
        src = getattr(self, "_capture_source", None)
        if src is not None and getattr(src, "stalled", False):
            return {"dead": True,
                    "reason": "capture stalled — no bytes within stall timeout"}
        released_at = self._ptt_released_at or self._ptt_started_at
        if released_at is not None:
            stall = float(self.config.section("capture").get("stall_timeout_s", 8.0))
            if (time.monotonic() - released_at) > (stall + 3.0):
                return {"dead": True,
                        "reason": (f"capture dead — no stats {stall + 3:.0f}s "
                                   f"after release (target={self._ptt_capture_target})")}
        return {"dead": False}

    async def _finish_dictation(self, task: asyncio.Task, params: dict,
                                session_id: str | None,
                                session_mode: str = "narration") -> None:
        """The part of a release that is slow: final, cleanup, routing.

        Runs as its own tracked task. Broadcasts `ptt.result` and always clears
        the processing flag, so a failure here is reported rather than leaving
        ptt.result waiting forever.
        """
        self._ptt_log("ptt.finish.enter", session_id=str(session_id or ""), mode=session_mode)
        result: dict | None = None
        try:
            self._ptt_log("ptt.finish.await_task", session_id=str(session_id or ""), timeout=60)
            session = await asyncio.wait_for(task, timeout=60)
            self._ptt_log("ptt.finish.task_done", session_id=str(session_id or ""), no_speech=str(getattr(session, "no_speech", False)))
            no_speech = bool(getattr(session, "no_speech", False))
            no_final = bool(getattr(session, "no_final", False))
            result = {
                "text": (session.cleaned_text
                         if (session.cleaned_text and not session.flagged)
                         else session.raw_text),
                "raw_text": session.raw_text,
                "backend": session.backend,
                "inbox_path": session.inbox_path,
                "audio_path": session.audio_path,
                "clipboard": session.clipboard,
                "flagged": session.flagged,
                "confidence": session.confidence,
                "cloud_status": session.cloud_status,
                "queued_job_ids": session.queued_job_ids,
                "connectivity_mode": session.connectivity_mode,
                "notes": session.notes,
                "session_id": session.session_id,
                # BUG 6: the capture facts for this session (node/bytes/peak)
                # and the fail-fast verdict — ptt.result callers see WHY a
                # session is empty instead of waiting out their full budget.
                "capture": getattr(session, "capture", None),
                "no_speech": no_speech,
                "no_final": no_final,
                # Factual narration from real state (§13.1) — no model call.
                "narration": ("no speech captured" if no_speech else
                              "No final transcript received; captured audio is "
                              "retained for retry." if no_final else
                              self.governor.narrate_fact(
                                  "transcribe.done",
                                  {"words": len(session.raw_text.split()),
                                   "seconds": session.duration_s})),
            }
            # BH-K2: excise her own words if the mic caught them — a textual
            # match against what she actually said, never timing and never
            # filler resemblance. raw_text stays the ASR record (it matches
            # the stored transcript row); only the shown/routed text loses
            # her words, and the user's remainder is always kept.
            stripped = self._strip_self_echo(result["text"])
            if stripped != result["text"]:
                result["text"] = stripped
                result["echo_suppressed"] = True
                if not stripped:
                    result["narration"] = "echo suppressed — own TTS captured as input"
                    if session_mode == "command":
                        result["command"] = None
            # The mode is captured at release time: a new dictation started
            # while this one is finishing must not reroute these words.
            if session_mode == "command" and result["text"].strip():
                veto = self._command_gate(result)
                if veto is not None:
                    # Nothing was routed, so nothing was executed. The words are
                    # still reported (they are the user's dictation, kept in the
                    # transcript row) and the reason is stated as a fact.
                    result["command"] = veto
                    result["narration"] = veto["note"]
                else:
                    # Known grammar climbs the local ladder first; open text
                    # follows the same offline queue policy as `ask`.
                    # Her own words were already stripped from result["text"]
                    # above (BH-K2); what remains is the user's and may route.
                    reply_timeout_s = max(
                        0.1, min(10.0, float(self._chat_timeout_s)))
                    self._dictate_log(
                        "dictate.reply_generation_start",
                        session_id=str(session_id or ""),
                        timeout_s=reply_timeout_s)
                    reply_started = time.monotonic()
                    reply_task = asyncio.create_task(self._ask({
                        "text": result["text"],
                        "speak": params.get("speak", True),
                    }))
                    try:
                        done, _pending = await asyncio.wait(
                            {reply_task}, timeout=reply_timeout_s,
                            return_when=asyncio.FIRST_COMPLETED)
                        if not done:
                            reply_task.cancel()
                            reply_task.add_done_callback(self._consume_task_result)
                            self._dictate_log(
                                "dictate.reply_generation_timeout",
                                session_id=str(session_id or ""),
                                timeout_s=reply_timeout_s,
                                elapsed_s=round(time.monotonic() - reply_started, 3))
                            result["command"] = {
                                "reply": ("Dictation saved, but reply generation "
                                          "timed out."),
                                "error": "reply generation timed out",
                            }
                        else:
                            result["command"] = reply_task.result()
                            self._dictate_log(
                                "dictate.reply_generation_done",
                                session_id=str(session_id or ""),
                                elapsed_s=round(time.monotonic() - reply_started, 3))
                    except asyncio.CancelledError:
                        if not reply_task.done():
                            reply_task.cancel()
                            reply_task.add_done_callback(self._consume_task_result)
                        self._dictate_log(
                            "dictate.reply_generation_cancelled",
                            session_id=str(session_id or ""))
                        raise
                    except Exception as exc:
                        self._dictate_log(
                            "dictate.reply_generation_failed",
                            session_id=str(session_id or ""),
                            error=f"{type(exc).__name__}: {exc}"[:200])
                        result["command"] = {
                            "reply": ("Dictation saved, but reply generation "
                                      "failed."),
                            "error": str(exc)[:200],
                        }
                if isinstance(result.get("command"), dict):
                    result["narration"] = result["command"].get(
                        "reply", result["narration"])
        except Exception as exc:
            timed_out = isinstance(exc, TimeoutError)
            error = ("session never finished — treating as no speech captured"
                     if timed_out else f"dictation did not finish cleanly: {exc}")
            self._ptt_log("ptt.finish.exception", session_id=str(session_id or ""), error=error[:200], timed_out=str(timed_out))
            result = {"error": error,
                      "session_id": session_id,
                      # BUG 6: a session that cannot even finish is a dead
                      # session. ptt.result must say so NOW, not after the
                      # caller's wait budget expires.
                      "no_speech": True,
                      "capture": {"node": self._ptt_capture_target or "unknown", "bytes": 0, "peak_rms": 0.0, "no_speech": True, "stalled": True} if timed_out else None,
                      "narration": "no speech captured"}
        finally:
            self._ptt_log("ptt.finish.finally", session_id=str(session_id or ""), has_result=str(result is not None))
            if session_id is not None:
                self._ptt_last_result = result
                self._ptt_last_session_id = session_id
                self._ptt_results[session_id] = result
                while len(self._ptt_results) > 8:
                    evicted = next(iter(self._ptt_results))
                    self._ptt_results.pop(evicted, None)
                    self._ptt_result_events.pop(evicted, None)
                # The session is OVER here — which is exactly what lets a
                # parked mode switch apply below (_session_active consults
                # _ptt_processing). The result is already retrievable by
                # session id; the terminal event comes after the switch.
                self._ptt_finishing.discard(session_id)
            # A result may finish after the owner has already started the next
            # dictation. It is still retrievable by session id, but it must not
            # set the mode to idle or release a parked mode switch under the
            # new session's feet.
            if session_id is not None and self._ptt_session_id == session_id:
                self.mode = "idle"
                # Ordering matters: the session is over (so a parked mode
                # switch may apply), and only then is its waiter released —
                # a waiter that woke before the switch would report the
                # pre-switch connectivity and look like the parked switch was
                # lost.
                try:
                    await self._await_dictate_step(
                        "dictate.pending_mode_switch",
                        self._apply_pending_mode_switch(),
                        session_id=session_id, timeout_s=1.0)
                except Exception as exc:
                    # A switch never blocks the already-stored dictation result.
                    self._dictate_log(
                        "dictate.pending_mode_switch_ignored",
                        session_id=str(session_id or ""),
                        error=f"{type(exc).__name__}: {exc}"[:200])
            if session_id is not None:
                # BUG 6d: unconditional. The old code set the (single, global)
                # result event only while this session was still the daemon's
                # current one — a finish landing under a changed session id
                # completed silently and its ptt.result waiter hung on an
                # orphaned event. Every session's waiters wake on its own
                # terminal transition, superseded or not.
                self._ptt_event_for(session_id).set()
            async def _broadcast_result_events():
                await self.broadcast({"event": "ptt.result",
                                      "session_id": session_id,
                                      "result": result})
                if self._ptt_session_id == session_id:
                    await self.broadcast({"event": "status.changed",
                                          "mode": self.mode})

            try:
                await self._await_dictate_step(
                    "dictate.result_broadcast", _broadcast_result_events(),
                    session_id=session_id, timeout_s=1.0)
            except Exception as exc:
                self._dictate_log(
                    "dictate.result_broadcast_ignored",
                    session_id=str(session_id or ""),
                    error=f"{type(exc).__name__}: {exc}"[:200])

    async def _ptt_result(self, params: dict) -> dict:
        """Fetch the terminal answer for ONE session, optionally waiting.

        BUG 6d (hardware report 2026-10-20): this resolves on ANY terminal
        state of the requested session — the real transcript, a fail-fast
        dead capture, or an explicit "finished without a result" payload when
        the session was superseded or its state restarted. The old code
        waited on one global event that only the *current* session's finish
        ever set, so a finish landing under a changed session id orphaned the
        waiter (the hardware hang); a session that ended without a result
        just returned a silent None. Both now answer explicitly and promptly.
        """
        requested = params.get("session_id") or None
        if requested is None:
            requested = self._ptt_session_id or self._ptt_last_session_id
        wait_s = self._ptt_wait_budget(params)
        answer = None
        if requested is not None and wait_s > 0:
            answer = await self._ptt_wait_for(requested, wait_s)
        if answer is None:
            answer = self._ptt_terminal_result(requested)
        response = {
            "session_id": requested,
            "processing": (requested is not None
                           and requested in self._ptt_finishing),
            "result": answer,
            "found": (answer is not None or requested is None
                      or requested == self._ptt_last_session_id
                      or requested == self._ptt_session_id),
            "connectivity": self.mode_manager.status(refresh=False).as_dict(),
        }
        if answer is not None:
            response["terminal"] = True
            if answer.get("dead_fast"):
                response["dead_fast"] = True
        return response

    async def _transcribe_file(self, params: dict) -> dict:
        from pathlib import Path

        path = Path(str(params.get("path", ""))).expanduser()
        if not path.exists():
            raise ValueError(f"no such audio file: {path}")
        session = await self.dictation.transcribe_file(path)
        return {"text": (session.cleaned_text
                         if (session.cleaned_text and not session.flagged)
                         else session.raw_text),
                "raw_text": session.raw_text, "backend": session.backend,
                "inbox_path": session.inbox_path, "flagged": session.flagged,
                "clipboard": session.clipboard, "confidence": session.confidence,
                "cloud_status": session.cloud_status,
                "queued_job_ids": session.queued_job_ids,
                "connectivity_mode": session.connectivity_mode}

    # -- organiser (Phase 3: shadow only — these handlers cannot move files) --
    async def _index_run(self, params: dict) -> dict:
        results = await asyncio.to_thread(self.organiser.index_roots)
        return {"roots": results,
                "note": "local indexing only; never_send content stays on this machine"}

    async def _plan_build(self, params: dict) -> dict:
        """Long work goes async immediately (§18 rule 5): return at once
        with the plan id; progress + completion ride the event stream."""
        roots = self.config.organise_roots()
        if params.get("root"):
            roots = [r for r in roots if r["path"] == str(params["root"])]
        if not roots:
            raise ValueError("no organise roots configured — add [[organise.roots]] "
                             "to config.toml (roots start in shadow mode, §4.3)")
        connectivity = await self._connectivity_snapshot()
        wants_tiers = bool(params.get("tiers"))
        queue_tiers = wants_tiers and connectivity.is_offline
        started = []
        for spec in roots:
            # Reserve the plan row on the loop thread so plan.show works
            # from the first millisecond; heavy lifting runs to_thread.
            plan_id = self.store.create_plan(iso_now(), spec["path"],
                                             spec.get("mode", "shadow"))
            loop = asyncio.get_running_loop()

            def progress(event, _loop=loop):
                _loop.call_soon_threadsafe(
                    lambda e=event: asyncio.create_task(self.broadcast(e)))

            async def _run(spec=spec, plan_id=plan_id, progress=progress):
                try:
                    await asyncio.to_thread(
                        self.organiser.build_plan, spec,
                        progress=progress, plan_id=plan_id,
                        with_llm_tiers=wants_tiers and not queue_tiers)
                    if queue_tiers:
                        job_id = self.cloud_queue.enqueue_plan_tiers(
                            spec["path"], source_plan_id=plan_id)
                        await self.broadcast({
                            "event": "plan.tiers_queued", "plan_id": plan_id,
                            "job_id": job_id,
                            "note": "Tier 0 is local; Tier 1/2 judgement is parked",
                        })
                except Exception as exc:
                    # BH-K30: build_plan marks its own failures, but a
                    # failure before its try (bad root mode) or after it
                    # (tier enqueue) left this row 'building' forever.
                    plan = self.store.get_plan(plan_id)
                    if plan is not None and plan.get("status") == "building":
                        self.store.finish_plan(
                            plan_id, total=0, placed=0, abstained=0,
                            shadow_log_path=None, stats_json="{}",
                            error=f"{type(exc).__name__}: {exc}")
                    await self.broadcast({"event": "error", "error": str(exc),
                                          "plan_id": plan_id})

            task = asyncio.create_task(_run())
            self._plan_tasks[plan_id] = task
            task.add_done_callback(
                lambda _t, pid=plan_id: self._plan_tasks.pop(pid, None))
            started.append({"plan_id": plan_id, "root": spec["path"], "status": "building",
                            "tiers": "queued-offline" if queue_tiers else (
                                "enabled" if wants_tiers else "tier0-only")})
        return {"started": started, **await self._ack({"kind": "on_it"}),
                "connectivity": connectivity.as_dict()}

    async def _plan_show(self, params: dict) -> dict:
        plan_id = int(params.get("plan_id", 0))
        plan = self.store.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"no plan {plan_id} — see plan.list")
        return {"plan": plan,
                "items": self.store.plan_items(plan_id, params.get("decision"))}

    async def _plan_list(self, params: dict) -> dict:
        return {"plans": self.store.list_plans(int(params.get("limit", 20)))}

    async def _docs_search(self, params: dict) -> dict:
        query = str(params.get("query", "")).strip()
        if not query:
            raise ValueError("docs.search needs params.query")
        return {"results": self.store.search_documents(query), "engine":
                "fts5" if self.store.fts5_available else "like-fallback"}

    def _root_spec_for_plan(self, plan_id: int) -> dict:
        plan = self.store.get_plan(plan_id)
        if plan is None:
            raise ValueError(f"no plan {plan_id}")
        for spec in self.config.organise_roots():
            if spec["path"] == plan["root"]:
                return spec
        raise ValueError(f"plan {plan_id} root {plan['root']} no longer configured")

    async def _plan_apply(self, params: dict) -> dict:
        """THE write path (Phase 4). Refuses shadow roots in Executor."""
        from dataclasses import asdict

        plan_id = int(params["plan_id"])
        spec = self._root_spec_for_plan(plan_id)
        report = await asyncio.to_thread(
            self.executor.apply_plan, plan_id, spec,
            include_review=bool(params.get("include_review")),
            allow_tripwire=bool(params.get("allow_tripwire")))
        await self.broadcast({"event": "op.applied", "plan_id": plan_id,
                              "applied": report.applied, "conflicts": report.conflicts})
        narration = self.governor.narrate_fact(
            "organise.summary",
            {"filed": report.applied, "review": len(report.refused),
             "unsorted": report.conflicts})
        return {**asdict(report), "narration": narration}

    async def _review_list(self, params: dict) -> dict:
        plan_id = params.get("plan_id")
        plans = [int(plan_id)] if plan_id else [p["id"] for p in self.store.list_plans(5)]
        items = []
        for pid in plans:
            items.extend(self.store.plan_items(pid, "review"))
        return {"review_items": items}

    async def _review_decide(self, params: dict) -> dict:
        item_id = _int_param(params, "item_id")
        verdict = params.get("verdict")
        if verdict not in ("approve", "reject"):
            raise ValueError("verdict must be approve|reject")
        decision = "auto" if verdict == "approve" else "rejected"
        if not self.store.set_item_decision(item_id, decision):
            raise ValueError(f"no review item {item_id}")
        return {"item_id": item_id, "decision": decision}

    async def _undo(self, params: dict) -> dict:
        from .executor import parse_since

        since = parse_since(str(params["since"])) if params.get("since") else None
        return await asyncio.to_thread(
            self.executor.undo, op_id=params.get("op_id"),
            plan_id=params.get("plan_id"), since_iso=since)

    async def _verify(self, params: dict) -> dict:
        from .executor import parse_since

        since = parse_since(str(params["since"])) if params.get("since") else None
        return await asyncio.to_thread(self.executor.verify, since_iso=since)

    async def _memory_remember(self, params: dict) -> dict:
        fact_id = self.memory.remember(str(params["text"]),
                                       kind=str(params.get("kind", "profile")))
        return {"fact_id": fact_id, "stored": "stated — inspect anytime: assist memory"}

    async def _memory_list(self, params: dict) -> dict:
        return {"facts": self.memory.beliefs(params.get("kind"))}

    async def _memory_forget(self, params: dict) -> dict:
        return {"forgotten": self.memory.forget(str(params["topic"]))}

    async def _memory_recall(self, params: dict) -> dict:
        hits = await asyncio.to_thread(self.memory.recall, str(params["query"]))
        return {"hits": [{"source": h.source, "ref": h.ref, "text": h.text,
                          "score": round(h.score, 4)} for h in hits]}

    async def _embed_run(self, params: dict) -> dict:
        count = await asyncio.to_thread(self.organiser._embed_new_chunks)
        return {"embedded": count, "embedder": self.memory.embedder.name}

    async def _meeting_start(self, params: dict) -> dict:
        """Dual-channel capture (Phase 6). Channels stay separate so
        diarization is exact. Same idle-safe rules as ptt."""
        if self._meeting is not None:
            return {"state": "already-meeting"}
        from .capture import DualCapture, PipeWireCapture, SimulatedCapture

        meeting_cfg = self.config.section("meeting")

        def make_source(target: str | None):
            if params.get("source") == "simulated" or params.get("simulation"):
                return SimulatedCapture(speech_frames=100_000, frame_ms=30, realtime=True)
            try:
                return PipeWireCapture(target, frame_ms=30)
            except RuntimeError:  # headless: simulated keeps pipeline exercisable
                return SimulatedCapture(speech_frames=100_000, frame_ms=30, realtime=True)

        # BH-K21: [meeting] mic_target overrides, but the documented
        # [capture] mic_target is the fallback (dictate/hotword resolve
        # capture -> meeting; meeting used to ignore [capture] entirely
        # and silently record the PipeWire default).
        mic = make_source(meeting_cfg.get("mic_target")
                          or self.config.section("capture").get("mic_target")
                          or None)
        system = make_source(meeting_cfg.get("system_target") or None)
        dual = DualCapture(mic, system)
        frames: dict[str, list[bytes]] = {"mic": [], "sys": []}

        async def collect():
            async for mic_frame, sys_frame in dual.frames():
                frames["mic"].append(mic_frame)
                frames["sys"].append(sys_frame)

        session_id = uuid.uuid4().hex
        self.mode = "meeting"
        await self.broadcast({"event": "status.changed", "mode": self.mode})
        self._meeting = {"session_id": session_id, "dual": dual, "frames": frames,
                         "task": asyncio.create_task(collect())}
        return {"state": "meeting"}

    async def _meeting_stop(self, params: dict) -> dict:
        task = asyncio.current_task()
        if task is not None:
            self._meeting_stop_tasks.add(task)
        try:
            return await self._meeting_stop_impl(params)
        finally:
            if task is not None:
                self._meeting_stop_tasks.discard(task)
            if self._meeting is None and self.mode == "meeting":
                self.mode = self._meeting_mode()

    async def _meeting_stop_impl(self, request: dict) -> dict:
        if self._meeting is None:
            return {"state": "idle", "note": "no meeting in progress"}
        deadline = time.monotonic() + self._meeting_stop_timeout_s
        meeting, self._meeting = self._meeting, None
        capture_close = asyncio.create_task(meeting["dual"].aclose())
        capture_error = None
        try:
            try:
                await asyncio.shield(capture_close)
            except asyncio.CancelledError:
                close_result, = await asyncio.gather(
                    capture_close, return_exceptions=True)
                if isinstance(close_result, BaseException):
                    print("[assistd] meeting capture cleanup failed during stop "
                          f"cancellation: {type(close_result).__name__}: {close_result}",
                          file=sys.stderr, flush=True)
                raise
            except Exception as exc:
                capture_error = exc
        finally:
            meeting["task"].cancel()
            await asyncio.gather(meeting["task"], return_exceptions=True)
        from datetime import datetime

        from .capture import write_wav

        session_id = str(meeting.get("session_id") or uuid.uuid4().hex)
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        raw_stem = f"meeting-{stamp}-{session_id}"
        rate = int(self.config.section("capture").get("sample_rate", 16000))
        mic_wav = write_wav(self.config.data_dir / "audio" / f"{raw_stem}-mic.wav",
                            meeting["frames"]["mic"], rate)
        sys_wav = write_wav(self.config.data_dir / "audio" / f"{raw_stem}-system.wav",
                            meeting["frames"]["sys"], rate)
        self._meeting_processing.add(session_id)
        self.mode = self._meeting_mode()
        await self.broadcast({"event": "status.changed", "mode": self.mode})
        try:
            if capture_error is not None:
                raise RuntimeError(
                    "meeting capture close failed; raw audio retained "
                    f"at {mic_wav} and {sys_wav}") from capture_error
            try:
                title = request.get("title")
                pyannote_refine = bool(self.config.section("meeting").get(
                    "pyannote_refine"))
                if self.client.mode != "mock":
                    result = await self.meetings.transcribe_dual_async(
                        mic_wav, sys_wav, title=title,
                        pyannote_refine=pyannote_refine, deadline=deadline)
                else:
                    result = await asyncio.to_thread(
                        self.meetings.transcribe_dual, mic_wav, sys_wav,
                        title=title, pyannote_refine=pyannote_refine,
                        deadline=deadline)
            except TimeoutError as exc:
                raise TimeoutError(
                    "meeting transcription deadline expired; raw audio retained "
                    f"at {mic_wav} and {sys_wav}") from exc
        finally:
            self._meeting_processing.discard(session_id)
            self.mode = self._meeting_mode()
            await self.broadcast({"event": "status.changed", "mode": self.mode})
            await self._apply_pending_mode_switch()
        return {"state": self.mode, "note_path": str(result.note_path),
                "turns": len(result.turns), "backend": result.backend,
                "transcript_preview": result.transcript[:400],
                "connectivity": self.mode_manager.status(refresh=False).as_dict()}

    # -- disclosure awareness (owner rule 2026-10-20) ------------------------
    async def _privacy_status(self, params: dict) -> dict:
        return {"company": self.disclosure.status()}

    async def _privacy_set(self, params: dict) -> dict:
        if "company" not in params:
            raise ValueError("privacy.set needs params.company (bool)")
        status = self.disclosure.set_company(bool(params["company"]),
                                             source="owner command")
        await self.broadcast({"event": "privacy.changed", "company": status})
        return {"company": status}

    async def _privacy_toggle(self, params: dict) -> dict:
        status = self.disclosure.toggle(source="owner command")
        await self.broadcast({"event": "privacy.changed", "company": status})
        return {"company": status}

    async def _guest_turn_normal(self, text: str, params: dict) -> dict:
        """A non-owner voice outside show-off: no memory, deflection in character.

        A guest turn is NOT part of the owner's conversation (BH-J1). Writing it
        there made the room's words her "user" history: visible in the console,
        fed back as context on the owner's next turn, and durable in SQLite.
        The guest audit trail belongs to `disclosure.log_guest`, not to §16.
        """
        channel = str(params.get("channel") or "voice")
        reply = self.disclosure.deflection(guest=True,
                                           action=is_instruction(text))
        decision = self.governor.decide(TurnContext(user_text=text))
        self.disclosure.log_guest("guest_turn", category="non-owner voice",
                                  chars=len(text))
        speech = await self._maybe_speak_reply(reply, params)
        await self.broadcast({"event": "conversation.message",
                              "conversation_id": None,
                              "channel": channel, "role": "guest"})
        return {
            "reply": reply, "speaker": "guest", "via": "guest-deflection",
            "channel": channel, "conversation_id": None,
            "model": None, "register": decision.register, "serious_gate": None,
            "mode": self.config.gemini_mode, "fixture": None,
            "speech": speech, "memory_closed": True, "withheld": None,
            "company": self.disclosure.status(),
        }

    # -- show-off (§19.3) ----------------------------------------------------
    async def _showoff_status(self, params: dict) -> dict:
        return {"showoff": self.showoff.status()}

    async def _showoff_enter(self, params: dict) -> dict:
        """Fail closed until entry is wired to daemon-captured live audio (I5)."""
        self._require_ipc_owner()
        raise ValueError(
            "refused: show-off entry has no daemon-side fresh-capture path; "
            "caller-supplied embedding, presence, source, and live-mic flags "
            "are not authentication")

    async def _showoff_exit(self, params: dict) -> dict:
        """The authenticated owner IPC action closes show-off; params do not."""
        self._require_ipc_owner()
        try:
            # The CLI/local owner action itself is the authenticated principal.
            # `reason`, command text, and embeddings are not caller authority.
            summary = self.showoff.exit_hotkey()
        except ShowoffError as exc:
            raise ValueError(str(exc)) from exc
        await self.broadcast({"event": "showoff.exited", "summary": summary})
        return {"showoff": self.showoff.status(), "summary": summary}

    async def _showoff_demo(self, params: dict) -> dict:
        if not self.showoff.active():
            raise ValueError("show-off mode is not on")
        if str(params.get("action") or "list") == "write":
            return self.showoff.demo_write(str(params.get("name") or "demo.txt"),
                                           str(params.get("content") or ""))
        return {"sandbox": str(self.showoff.sandbox_path()),
                "target": str(self.showoff.demo_target(
                    str(params.get("name") or "")))}

    async def _guest_turn(self, text: str, params: dict,
                          status: dict) -> dict:
        """A guest turn in show-off mode: conversation only, authority none."""
        channel = str(params.get("channel") or "voice")
        verdict = self.showoff.guest_turn(text)
        # Same boundary in show-off: the demo is not the owner's history
        # (BH-J1), and every guest turn leaves an audit row.
        self.disclosure.log_guest("guest_turn", category="show-off",
                                  chars=len(text))
        model = None
        if verdict.get("allowed"):
            prompt = self.showoff.build_guest_prompt(text)
            connectivity = await self._connectivity_snapshot()
            if connectivity.is_offline:
                reply = ("I'm offline, so the demo is text-only right now — "
                         "the good answers are on hold.")
                via = "local"
            else:
                try:
                    result = await self._generate(
                        prompt, purpose="housekeeping:guest_turn", is_user_turn=0)
                    reply, model = result.text, result.model
                    via = "showoff"
                except TimeoutError:
                    # A stalled transport must not freeze the demo (BH-I12).
                    reply = ("That one stalled on the network. Ask me again in a "
                             "moment.")
                    via = "local-timeout-fallback"
                    model = None
        else:
            reply, via = verdict["reply"], "showoff-refusal"
        leak = self.disclosure.leak_in(reply, guest=True) if verdict.get("allowed") else None
        withheld = None
        if leak is not None:
            self.disclosure.log("leak_blocked", {
                "kind": leak["kind"], "why": leak["why"],
                "fact_id": leak.get("fact_id"), "channel": channel,
                "speaker": "guest", "context": "showoff"})
            withheld = {"kind": leak["kind"], "why": leak["why"],
                        "note": "the show-off reply named owner information"}
            reply, via = self.disclosure.deflection(guest=True), "withheld"
        speech = await self._maybe_speak_reply(reply, params)
        await self.broadcast({"event": "conversation.message",
                              "conversation_id": None,
                              "channel": channel, "role": "guest"})
        if verdict.get("exited"):
            await self.broadcast({"event": "showoff.exited",
                                  "summary": verdict.get("summary")})
        return {
            "reply": reply, "speaker": "guest", "via": via,
            "channel": channel, "conversation_id": None,
            "model": model, "register": "expressive-allowed",
            "showoff": verdict, "memory_closed": True,
            "speech": speech, "fixture": None, "withheld": withheld,
            "serious_gate": None, "mode": self.config.gemini_mode,
        }

    # -- Bug 8: every reply that is NOT delivered is recorded --------------------
    def _log_reply_substitution(self, *, reason: str,
                                original_len: int | None = None,
                                rule: str | None = None,
                                replacement: str | None = None,
                                turn: str | None = None) -> dict:
        """Record a generated reply being replaced or discarded (Bug 8).

        Silent replacement is how the canned-fallback bug hid behind a working
        ledger — the calls landed, the answers never reached the user. Every
        substitution carries WHY (validator rule hit / deadline kind), the
        original text length (None = the abandoned generation has not resolved
        yet; the late-completion record fills it in) and what stood in for it.
        Surfaced by `assist cost` and `status`.
        """
        record = {
            "ts": iso_now(),
            "reason": reason,
            "original_len": original_len,
            "rule": rule,
            "replacement_len": len(replacement or ""),
            "turn": (turn or "")[:60],
        }
        try:
            self.store.log_persona_event(
                record["ts"], "reply_substituted", json.dumps(record))
        except Exception:  # noqa: S110 - diagnostics never break the turn
            pass
        return record

    def _log_reply_late(self, *, original_len: int, turn: str | None = None) -> None:
        """Generation delivered after first-token deadline but within total.

        BUG 8b (2026-10-20 hardware): a blocking transport that completes at
        ~8s was logged as NOT delivered because the first-token callback never
        fired mid-generation. The reply WAS delivered; this record marks it
        late in the log without counting as a substitution (cost shows only
        NOT delivered)."""
        record = {
            "ts": iso_now(),
            "reason": "deadline:first_token:late_delivered",
            "original_len": original_len,
            "turn": (turn or "")[:60],
        }
        try:
            self.store.log_persona_event(
                record["ts"], "reply_late", json.dumps(record))
        except Exception:
            return

    def _reply_substitution_records(self, limit: int = 20) -> list[dict]:
        try:
            rows = self.store.list_persona_events(kind="reply_substituted",
                                                  limit=limit)
        except Exception:
            return []
        out = []
        for row in rows:
            try:
                detail = json.loads(row.get("detail") or "{}")
            except ValueError:
                detail = {"reason": "unreadable", "detail": row.get("detail")}
            detail["ts"] = row.get("ts")
            out.append(detail)
        return out

    async def _generate(self, prompt: str, *, gen_config=None, verify=None,
                        purpose: str = "user_turn", is_user_turn=True):
        """One bounded chat call. The test-double fallback lives here only.

        BUG F / Bug 8 (2026-10-20): the old single 4 s total bound cancelled
        the `asyncio.to_thread(...)` await — which does NOT stop the worker
        thread. Live chat now uses the SDK's native async HTTP stream, which is
        cancelled at the total deadline; only finite fixture/legacy transports
        retain the thread-backed compatibility path. Deadlines are split:

        * first-token deadline — a transport that has produced NOTHING by
          then is dead (streaming transports signal `on_first_token`; a
          non-streaming double counts only its completion as progress);
        * total bound — a generation that finishes in time is delivered
          verbatim; an unfinished live async request is cancelled at the bound.

        BUG 8b (2026-10-20 hardware): the real SDK transport never fires
        mid-generation, so the first-token deadline acted as a hard 5s total
        deadline for blocking transports. Fix: first-token deadline applies
        ONLY to streaming transports; blocking transports use the total bound
        alone, and a generation completing after the first-token deadline
        but within the total bound is DELIVERED (marked late, not substituted).

        A deadline raise is an actual failure (ChatTimeout with `.reason`),
        and any generation that completes after we gave up is logged as a
        discarded reply with its real text length — never silently lost.
        """
        first_token_s = min(float(self._chat_first_token_s),
                            float(self._chat_timeout_s))
        total_s = float(self._chat_timeout_s)
        deadline = time.monotonic() + total_s
        first_token = asyncio.Event()
        signalled = {"done": False}

        def _on_first_token() -> None:
            if not signalled["done"]:
                signalled["done"] = True
                first_token.set()

        base_kwargs = {"gen_config": gen_config, "verify": verify,
                       "purpose": purpose, "is_user_turn": is_user_turn,
                       "max_attempts": 2}   # REJECT-2: regenerate once, best attempt
        full_kwargs = {**base_kwargs, "on_first_token": _on_first_token}

        def run():
            # Older doubles predate on_first_token / max_attempts; retry with
            # fewer kwargs (BH-I12: one helper, one behaviour). A genuine
            # TypeError raised inside the client must surface.
            attempts = (full_kwargs, base_kwargs,
                        {"gen_config": gen_config}, {})
            for i, kwargs in enumerate(attempts):
                try:
                    return self.client.generate("chat", prompt, **kwargs)
                except TypeError as exc:
                    if "unexpected keyword" not in str(exc) or i == len(attempts) - 1:
                        raise
            raise AssertionError("unreachable")  # pragma: no cover

        async_generate = getattr(self.client, "generate_async", None)
        async_support = getattr(self.client, "supports_cancellable_async", None)
        use_async = callable(async_generate) and async_support is not False

        async def run_async():
            # The live SDK path is natively async: cancelling it closes the
            # request instead of abandoning a synchronous worker thread.
            attempts = ({**full_kwargs, "deadline": deadline}, full_kwargs,
                        base_kwargs, {"gen_config": gen_config}, {})
            for i, kwargs in enumerate(attempts):
                try:
                    return await async_generate("chat", prompt, **kwargs)
                except TypeError as exc:
                    if "unexpected keyword" not in str(exc) or i == len(attempts) - 1:
                        raise
            raise AssertionError("unreachable")  # pragma: no cover

        abandoned = {"flag": False, "reason": "first_token"}

        def _late_completion(done_task: asyncio.Task) -> None:
            # The generation we gave up on may still succeed in its thread.
            # Its text is the original that was replaced — record its length
            # so the discard is auditable (Bug 8).
            if not abandoned["flag"] or done_task.cancelled():
                return
            try:
                result = done_task.result()
                text = getattr(result, "text", "") or ""
            except Exception:
                return
            self._log_reply_substitution(
                reason=f"deadline:{abandoned['reason']}:late",
                original_len=len(text), replacement="",
                turn=prompt[-60:])

        generation = run_async() if use_async else asyncio.to_thread(run)
        task = self._track_task(asyncio.ensure_future(generation))
        task.add_done_callback(_late_completion)

        async def _await_generation(timeout: float):
            awaited = task if use_async else asyncio.shield(task)
            result = await asyncio.wait_for(awaited, timeout=timeout)
            if time.monotonic() >= deadline:
                raise TimeoutError("chat total deadline expired")
            return result

        progress = asyncio.ensure_future(first_token.wait())
        try:
            done, _pending = await asyncio.wait(
                {task, progress}, timeout=first_token_s,
                return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                if time.monotonic() >= deadline:
                    abandoned["flag"] = True
                    abandoned["reason"] = "total"
                    raise ChatTimeout("total", total_s)
                return task.result()      # success: delivered verbatim
            if progress in done:
                # Streaming: first token arrived within deadline — generous total.
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    return await _await_generation(remaining)
                except TimeoutError as exc:
                    abandoned["flag"] = True
                    abandoned["reason"] = "total"
                    raise ChatTimeout("total", total_s) from exc
            # Neither completed nor signaled within first-token deadline.
            # A legacy non-streaming transport is not dead just because it
            # missed the first-token threshold: it may still finish inside the
            # total bound and must be DELIVERED (marked late, not substituted).
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                abandoned["flag"] = True
                abandoned["reason"] = "first_token"
                raise ChatTimeout("first_token", first_token_s)
            try:
                result = await _await_generation(remaining)
                # Delivered late but within total — mark late, don't substitute.
                try:
                    text = getattr(result, "text", "") or ""
                    self._log_reply_late(original_len=len(text), turn=prompt[-60:])
                except Exception:
                    return result
                return result
            except TimeoutError as exc:
                abandoned["flag"] = True
                abandoned["reason"] = "total"
                raise ChatTimeout("total", total_s) from exc
        except TimeoutError as exc:
            # Already a ChatTimeout (first_token case with no remaining) — re-raise.
            if isinstance(exc, ChatTimeout):
                raise
            abandoned["flag"] = True
            abandoned["reason"] = "total"
            raise ChatTimeout("total", total_s) from exc
        finally:
            if not progress.done():
                progress.cancel()
                await asyncio.gather(progress, return_exceptions=True)
            if use_async and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if task.done():
                self._background_tasks.discard(task)

    async def _ask(self, params: dict) -> dict:
        """Conversational turn on the §13.4 ladder: governor (local) →
        exact/grammar intents (local) → memory recall (local) → and only
        then the cheapest-first harness with assembled context (§17).
        Offline, that final rung becomes a durable queue entry instead of
        a network attempt. Any spoken form is local TTS only (§13.8)."""
        from .hotword import match_wake
        from .intents import route

        text = str(params.get("text", "")).strip()
        if not text:
            raise ValueError("ask needs params.text")
        # ADOPT-1 phrase hotword (start-anchored): the wake phrase ADDRESSES
        # her, it is not content. "Elaria, status" routes as "status" — a
        # local intent, zero Gemini calls. "Elaria" alone is a check-in.
        # Mid-sentence mentions never match (match_wake is start-anchored).
        wake = match_wake(text)
        route_text = wake.remainder if wake is not None else text
        request_method = self._ipc_method.get()
        # Channel is derived from the registered handler, never from a JSON
        # claim. A generic `ask` cannot turn itself into a console/owner path.
        channel = "console" if request_method == "console.say" else "voice"
        request_params = {"speak": bool(params.get("speak", False)),
                          "channel": channel}
        showoff_now = self.showoff.status()
        # Every turn while the public demo is active is a guest turn, including
        # console.say. Owner flags, speaker labels, and copied embeddings in the
        # request are not speaker evidence (I5); show-off only exposes its
        # explicit demo-safe allowlist.
        if showoff_now.get("active"):
            return await self._guest_turn(text, request_params, showoff_now)
        # The kernel-authenticated local owner is the default principal. A
        # caller may voluntarily downgrade its own turn to guest, but cannot
        # promote itself with `speaker=owner` or `owner_verified=True`.
        speaker_claim = str(params.get("speaker") or "").lower()
        speaker = ("guest" if speaker_claim in ("guest", "non-owner")
                   or params.get("owner_verified") is False else "owner")
        if speaker != "owner":
            return await self._guest_turn_normal(text, request_params)

        # The owner can tell her the room has company. That is awareness, not a
        # mode: nothing about voice, class mode or surfacing changes.
        company_command = detect_company_command(text)
        if company_command is not None:
            self.disclosure.set_company(company_command, source="owner speech")

        decision = self.governor.decide(TurnContext(user_text=text))
        self.store.log_persona_event(
            iso_now(), "decision",
            json.dumps({"register": decision.register,
                        "serious_gate": decision.serious_gate,
                        "pushback": decision.pushback, "reason": decision.reason}))
        conversation_id = self.sessions.active_id(iso_now())
        prior_turns = self.sessions.history(limit=8).get("messages") or []
        self.sessions.append("user", text, channel=channel, ts=iso_now())

        reply, via, model, fixture = None, None, None, None
        queued_job_id = None
        connectivity = await self._connectivity_snapshot()
        if company_command is not None:
            # An awareness command answers locally and never reaches a model.
            reply = ("Noted — company present. Secrets and private plans stay "
                     "unsaid; habits and ordinary memory are still fine."
                     if company_command else
                     "Noted — alone again. Secrets and private plans are back "
                     "on the table.")
            via = "local-awareness"
        intent = None if company_command is not None else route(route_text)
        if intent is not None:
            reply, via = await self._run_intent(intent)
        if reply is None and wake is not None and wake.is_checkin:
            # "Elaria" / "hey Elaria" alone: a check-in. The settled terse line
            # IS the turn-aware answer — zero Gemini calls (ADOPT-1).
            reply, via = checkin_reply(), "local-hotword-checkin"

        if reply is None:
            # Rung 5/6: assemble the exact context the cheap model needs.
            hits = await asyncio.to_thread(self.memory.recall, route_text)
            public_demo = bool(self.showoff.status().get("active"))
            restricted = (self.disclosure.company() or public_demo
                          or speaker != "owner")
            kept = self.disclosure.filter_hits(
                hits, guest=(speaker != "owner" or public_demo))
            context = "\n".join(f"- [{h.source} {h.ref}] {h.text}" for h in kept)
            history_lines = ""
            if prior_turns:
                safe_turns = [
                    m for m in prior_turns[-6:]
                    if m.get("text") and (
                        not restricted
                        or self.disclosure.leak_in(
                            str(m["text"]),
                            guest=(speaker != "owner" or public_demo),
                            company=(self.disclosure.company() or public_demo)) is None
                    )
                ]
                if safe_turns:
                    history_lines = "\n".join(
                        f"- {m['role']}: {m['text']}" for m in safe_turns
                    )
            # Build user-facing prompt body (context + history + user text).
            # route_text: the wake phrase addresses her and is stripped before
            # the model sees the turn ("Elaria, …" is not content).
            body = route_text
            if history_lines and context:
                body = (f"Context from the user's local memory/index "
                          f"(cite paths plainly):\n{context}\n\n"
                          f"Recent conversation in this session:\n{history_lines}\n\n"
                          f"User: {route_text}")
            elif context:
                body = (f"Context from the user's local memory/index "
                          f"(cite paths plainly):\n{context}\n\nUser: {route_text}")
            elif history_lines:
                body = (f"Recent conversation in this session:\n{history_lines}\n\n"
                          f"User: {route_text}")
            # System prompt carries the persona governor: no roleplay, terse, no asterisks
            disclosure_note = (self.disclosure.prompt_note(
                guest=(speaker != "owner" or public_demo))
                if restricted else None)
            full_prompt, gen_config = build_chat_prompt(
                body, decision=decision, restricted=restricted,
                disclosure_note=disclosure_note)
            # For offline we still queue the full prompt (system + body) so
            # replay on reconnect is faithful
            if connectivity.is_offline:
                queued_job_id = self.cloud_queue.enqueue_chat(
                    text, full_prompt, conversation_id)
                reply = (f"Offline — that needs Gemini, so I queued it durably "
                         f"(job #{queued_job_id}). It will drain on reconnect.")
                via = "local-queue"
            else:
                # Verify that the reply respects delivery spec: no asterisk
                # narration, terse for simple turns. A rejection is regenerated
                # ONCE (max_attempts=2), and the best attempt is DELIVERED —
                # never silently binned (REJECT-2 / Bug 8). Every rejection is
                # logged with the rule that hit, so a substitution is auditable.
                def _verify(reply_text: str) -> bool:
                    rule = chat_reply_violation(reply_text,
                                                original_user_text=route_text)
                    if rule is not None:
                        self._log_reply_substitution(
                            reason=f"validator:{rule}", rule=rule,
                            original_len=len(reply_text), replacement="",
                            turn=route_text)
                    return rule is None

                # Bounded Live work: first-token deadline for a dead transport,
                # generous total bound for one that started (BUG F / Bug 8).
                try:
                    result = await self._generate(
                        full_prompt, gen_config=gen_config, verify=_verify,
                        purpose="user_turn", is_user_turn=True)
                    reply, via, model, fixture = (result.text, "gemini",
                                                  result.model, result.fixture)
                    if reply:
                        self.mode_manager.observe_success("gemini")
                except TimeoutError as exc:
                    # A timed-out turn gets a TURN-AWARE fallback (Bug 8): it
                    # must never answer a different question than the one
                    # asked. The substitution is logged with the deadline kind.
                    reply = timeout_fallback_reply(route_text)
                    via = "local-timeout-fallback"
                    model = None
                    fixture = None
                    self._log_reply_substitution(
                        reason=f"deadline:{getattr(exc, 'reason', 'total')}",
                        original_len=None, replacement=reply, turn=route_text)
                    await self.broadcast({"event": "live.timeout", "text": text[:40]})
                # Bug 8: a successful generation is delivered VERBATIM — but an
                # empty one is a failure, not a reply. Fall back turn-aware.
                if reply is not None and not str(reply).strip():
                    self._log_reply_substitution(
                        reason="empty-generation", original_len=0,
                        replacement="", turn=route_text)
                    reply = timeout_fallback_reply(route_text)
                    via = "local-timeout-fallback"

        # The outgoing guard: a model that ignores the prompt still cannot read a
        # stored secret, plan or owner fact back to the room.
        public_demo = bool(self.showoff.status().get("active"))
        leak = self.disclosure.leak_in(
            reply, guest=(speaker != "owner" or public_demo),
            company=(self.disclosure.company() or public_demo))
        withheld = None
        if leak is not None:
            self.disclosure.log("leak_blocked", {
                "kind": leak["kind"], "why": leak["why"],
                "fact_id": leak.get("fact_id"), "channel": channel,
                "speaker": speaker})
            withheld = {"kind": leak["kind"], "why": leak["why"],
                        "note": "the reply named something she may not say aloud"}
            if speaker != "owner":
                reply = self.disclosure.deflection(guest=True)
            else:
                reply = (f"{self.disclosure.deflection(guest=False)} "
                         "Ask me again when we're alone and I'll tell you plainly.")
            via = "withheld"

        # Persist before any speech: a completed turn with hung caller is a failure (BUG1)
        self.sessions.append("assistant", reply, channel=channel, via=via,
                             ts=iso_now())
        # Broadcast without blocking the IPC response (BUG1/BUG4: prune only on real disconnect)
        # We await the quick write; drain is background with timeout
        await self.broadcast({"event": "conversation.message",
                              "conversation_id": conversation_id,
                              "channel": channel, "role": "assistant"})
        # Speech is async after response: return promptly, synthesize in background (BUG1)
        # This bounds Live work and prevents console.say hanging on slow TTS
        speech = await self._maybe_speak_reply(reply, params)
        if params.get("reaction"):
            self.governor.note_user_reaction(str(params["reaction"]))
            self._save_relationship_state()
        return {
            "reply": reply,
            "channel": channel,
            "conversation_id": conversation_id,
            "via": via,  # local-intent | local-memory | local-queue | gemini
            "model": model,
            "register": decision.register,
            "serious_gate": decision.serious_gate,
            "mode": self.config.gemini_mode,
            "fixture": fixture,
            "connectivity": connectivity.as_dict(),
            "queued_job_id": queued_job_id,
            "speech": speech,
            "speaker": speaker,
            "company": self.disclosure.status(),
            "withheld": withheld,
        }

    async def _run_intent(self, intent) -> tuple[str | None, str]:
        """Execute a local intent. (None, ...) = fall through to the model."""
        if intent.kind == "halt":
            await self._halt({})
            return ("Halted. Nothing will move until you say resume.", "local-intent")
        if intent.kind == "status":
            status = await self._status({})
            return ((f"Running ({status['mode']}), connectivity "
                    f"{status['connectivity_mode']}, gemini mode "
                    f"{status['gemini_mode']}, uptime {status['uptime_s']:.0f}s."),
                    "local-intent")
        if intent.kind in ("mode_offline", "mode_online", "mode_auto"):
            value = intent.kind.rsplit("_", 1)[1]
            result = await self._mode_set({"mode": value})
            connectivity = result["connectivity"]
            suffix = " Switch parked until this session finishes." if connectivity["switch_parked"] else ""
            return (f"Connectivity preference: {value}; effective {connectivity['effective_mode']}.{suffix}",
                    "local-intent")
        if intent.kind == "queue_status":
            counts = self.store.cloud_job_counts()
            detail = ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "empty"
            return (f"Cloud queue: {detail}.", "local-intent")
        if intent.kind == "queue_drain":
            result = await self._queue_drain({})
            return (result["summary"], "local-intent")
        if intent.kind == "cost":
            from .cost import format_cost_report

            data = await self._cost({})
            return (format_cost_report(data["month"], data["today"],
                                       data["quota"], data["tier"]), "local-intent")
        if intent.kind == "remember" and intent.argument:
            await self._memory_remember({"text": intent.argument})
            return (f"Remembered (stated fact): {intent.argument}", "local-intent")
        if intent.kind == "forget" and intent.argument:
            count = self.memory.forget(intent.argument)
            return (f"Forgotten ({count} fact(s) deactivated).", "local-intent")
        if intent.kind == "where":
            answer = await asyncio.to_thread(self.memory.answer_where, intent.argument)
            if answer:
                return (answer, "local-memory")
            return (None, "local-memory")  # weak recall: escalate, never bluff
        if intent.kind == "search" and intent.argument:
            hits = await asyncio.to_thread(self.memory.recall, intent.argument)
            if hits:
                lines = [f"- [{h.source}] {h.ref}: {h.text[:100]}" for h in hits]
                return ("Local matches:\n" + "\n".join(lines), "local-memory")
            return (None, "local-memory")
        if intent.kind == "undo":
            result = await self._undo({"since": intent.argument} if intent.argument else {})
            return ((f"Undone {result['undone']} op(s); "
                    f"{len(result['problems'])} problem(s)."), "local-intent")
        if intent.kind == "organise":
            # Plans are cheap and write-free to BUILD — do that, then talk.
            started = await self._plan_build({})
            ids = ", ".join(f"#{s['plan_id']}" for s in started["started"])
            return ((f"Shadow plan(s) {ids} building — nothing moves without "
                    "your review + apply. Watch `assist events`."), "local-intent")
        return (None, "local-intent")

    async def _connectivity_tick(self) -> None:
        # refresh() itself returns immediately without probing when the owner
        # forced offline; the socket probe runs off-loop in auto.
        status = await asyncio.to_thread(self.mode_manager.refresh, force=True)
        await self._note_connectivity_transition(status)

    async def _connectivity_loop(self) -> None:
        """Background posture checks; one failure is logged, never fatal.

        A bare `while True` around an unguarded probe meant any single exception
        ended the loop silently: the daemon kept running with a frozen
        connectivity state, never transitioning to/from offline again (BH-J2).
        """
        interval = float(self.config.section("connectivity").get(
            "health_check_interval_s", 20))
        while True:
            await asyncio.sleep(max(1.0, interval))
            try:
                await self._connectivity_tick()
            except Exception as exc:
                print(f"[assistd] connectivity check failed: "
                      f"{type(exc).__name__}: {exc}", flush=True)

    async def _warm_speech_cache(self) -> None:
        """One warm cycle for the active voice, off the hot path (§18).

        Single-flight and repeatable: boot calls it before the socket serves, and
        a cold-cache ack (VB-2) schedules it again so the next press is audible.
        The ack gate opens when the cycle ends, however it ends - a cloud that
        cannot render must not park every future ack behind a timeout.
        """
        if self._warm_running:
            return
        self._warm_running = True
        self._warm_pending = True
        try:
            if not self.config.section("tts").get("enabled", True):
                return
            try:
                await asyncio.to_thread(self.speech.warm_due)
            except Exception as exc:
                # Text/UI ack still works; status/doctor carry the reason.
                self._ack_cache_ready.clear()   # a failed warm is not a ready cache
                await self.broadcast({"event": "speech.error", "error": str(exc),
                                      **self.speech.route("On it.")})
                return
            if self.speech.ack_cache_state()["complete"]:
                self._ack_cache_ready.set()
        finally:
            self._warm_running = False
            self._warm_pending = False

    async def _await_ack_cache(self, timeout: float = 2.0) -> None:
        """Queue the first acks after boot behind the warm (VB-13).

        Bounded on purpose: the hot path keeps its 300 ms promise even when the
        warm is still rendering, and a silent ack with a reason in `status` beats
        a hung handler.
        """
        if self._ack_cache_ready.is_set() or not (self._warm_pending or self._warm_running):
            return
        try:
            await asyncio.wait_for(asyncio.shield(self._ack_cache_ready.wait()), timeout)
        except TimeoutError:      # asyncio.TimeoutError is this alias since 3.11
            pass

    def _schedule_rewarm_if_requested(self) -> None:
        """VB-2: a `cache_miss` on the speaking route is the trigger, not a verdict."""
        if self.speech.take_rewarm_request():
            self._ack_cache_ready.clear()
            self._track_task(asyncio.create_task(self._warm_speech_cache()))

    # -- lifecycle ---------------------------------------------------------------
    async def run(self) -> None:
        outstanding = self.store.outstanding_intents()
        if outstanding:
            # §4.2 recovery: surface, never silently drop. Repair/quarantine
            # tooling ships with the executor (Phase 4); Phase 0 reports.
            print(f"[assistd] WARNING: {len(outstanding)} uncommitted journal "
                  f"intent(s) from a previous run — inspect before enabling "
                  f"the executor.", flush=True)
        # VB-13: the ack cache starts warming BEFORE anything can ask for an ack,
        # and `_ack` queues behind it, so the first hotkey press after boot finds
        # audio instead of silence. Everything else on the socket is unaffected.
        # VB-10: if a previous run was SIGKILLed mid-playback (or mid-recording),
        # its audio children are still holding the sink and the microphone, and a
        # fresh daemon must not inherit that. pdeathsig covers the normal case;
        # this covers the kernel/thread arrangements where it does not fire.
        try:
            from .proc import audio_child_names, reap_orphans

            reaped = await asyncio.to_thread(
                lambda: reap_orphans(names=audio_child_names(self.config)))
            if reaped["killed"]:
                print(f"[assistd] released {len(reaped['killed'])} orphaned audio "
                      f"process(es) from a previous run: "
                      f"{', '.join(reaped['detail'])}", flush=True)
        except Exception as exc:            # never a reason to refuse to start
            print(f"[assistd] audio-orphan sweep failed: {exc}", flush=True)
        self._warm_pending = True
        warm_task = asyncio.create_task(self._warm_speech_cache())
        server = await serve(self.config.socket_path, self.handle,
                             on_disconnect=self._subscribers.discard)
        connectivity_task = asyncio.create_task(self._connectivity_loop())
        knock_task = asyncio.create_task(self._knock_due_loop())
        _sd_notify("READY=1")
        print(f"[assistd] Elaria up · mode={self.config.gemini_mode} "
              f"· socket={self.config.socket_path}", flush=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # non-Unix fallback
                pass
        try:
            async with server:
                await stop.wait()
        finally:
            await self.aclose(extra_tasks=(connectivity_task, warm_task, knock_task))

    async def aclose(self, *, extra_tasks=()) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        meeting, self._meeting = self._meeting, None
        meeting_task = meeting.get("task") if meeting is not None else None
        capture_error = None
        if meeting is not None:
            if meeting_task is not None:
                meeting_task.cancel()
            try:
                await meeting["dual"].aclose()
            except Exception as exc:
                capture_error = exc
        tasks = [
            t for t in (*extra_tasks, self._dictation_task, meeting_task,
                        *self._meeting_stop_tasks, *self._background_tasks)
            if t is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if meeting is not None:
            self.mode = self._meeting_mode()
        self.store.close()
        if capture_error is not None:
            print(f"[assistd] meeting capture cleanup failed: "
                  f"{type(capture_error).__name__}: {capture_error}",
                  file=sys.stderr, flush=True)


def main() -> None:
    try:
        config = load_config()
    except ValueError as exc:
        # BH-K24: a malformed config must be one readable line in the
        # journal, not a traceback on every restart attempt.
        print(f"assistd: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from None
    try:
        asyncio.run(Daemon(config).run())
    except RuntimeError as exc:
        # Two-daemon refusal is a normal startup outcome, not a crash (BH-J4).
        print(f"assistd: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
