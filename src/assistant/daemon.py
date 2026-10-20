"""Daemon — the product (§1.1). All state and policy live here; clients
are dumb and disposable. Single asyncio process, systemd --user.

Phase 0 handlers: ping, status, cost, doctor (via CLI-local checks),
halt/resume, ack (the §18 <300ms local acknowledgement — pure in-process
code, zero network), ptt.start/stop (acknowledged immediately and
locally; capture+Live streaming is Phase 1), ask (governor + cheapest-
first harness; fully functional in mock mode).

Startup recovery (§4.2): outstanding journal intents are reported, never
silently dropped. Cold starts are a Phase-0 bug (§18.6): config, store,
governor and client are resident from boot.
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket as socket_mod
import sys
import time

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
from .ipc import serve
from .modes import ModeManager
from .offline_queue import CloudQueue
from .organiser import OrganiserService
from .persona import (
    PersonaGovernor,
    TurnContext,
    build_chat_prompt,
    is_valid_chat_reply,
)
from .presence import PresenceService
from .safety import clear_halt, is_halted, set_halt
from .showoff import ShowoffError, ShowoffService
from .store import Store
from .transcribe import DictationService
from .tts import STANDARD_ACKS, SpeechResult, SpeechService


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


class Daemon:
    def __init__(self, config: Config):
        self.config = config
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
        from .meeting import MeetingService
        self.meetings = MeetingService(
            config, self.store, self.client, mode_manager=self.mode_manager)
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
        self.console = ConsoleService(
            config, self.store, presence=self.presence, sessions=self.sessions,
            initiative=self.initiative, showoff=self.showoff,
            disclosure=self.disclosure)
        self._meeting: dict | None = None  # {task, dual, mic_frames, sys_frames}
        self._meeting_processing = False
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
        self._last_connectivity_mode = self.mode_manager.status(refresh=False).effective_mode
        self._background_tasks: set[asyncio.Task] = set()
        # One bound for every chat call (owner turns and guest turns): a
        # stalled transport must return a spoken fact, never freeze the
        # console (BH-I12).
        # BUG5 half-duplex: capture muted while she is speaking (+ guard)
        self._speaking_until: float = 0.0
        self._speaking_text: str | None = None
        self._chat_timeout_s = 4.0
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
            self._speaking_text = text
        else:
            # Keep guard interval even after speak completes
            guard_s = 0.4
            self._speaking_until = __import__("time").monotonic() + guard_s
            # Don't clear text immediately; let guard expire

    def is_speaking(self) -> bool:
        return __import__("time").monotonic() < self._speaking_until

    def speaking_guard_remaining(self) -> float:
        return max(0.0, self._speaking_until - __import__("time").monotonic())

    # -- Phase 8 connectivity / speech helpers --------------------------------
    # BUG5: capture wrapper that mutes while she is speaking + guard
    class _MutedCapture:
        """Wraps a capture source, dropping frames while speaking."""
        def __init__(self, inner, daemon):
            self._inner = inner
            self._daemon = daemon
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

    def _is_echo(self, transcript_text: str) -> bool:
        """BUG5: own TTS output must never enter transcript."""
        if not transcript_text or not self._speaking_text:
            return False
        # If speaking recently, check transcript matches spoken text
        if self.is_speaking() or self.speaking_guard_remaining() > 0:
            return True
        # Also check textual similarity to last spoken text (echo captured)
        norm_spoken = " ".join(self._speaking_text.lower().split())
        norm_trans = " ".join(transcript_text.lower().split())
        if norm_spoken and norm_spoken in norm_trans:
            return True
        # Reverse containment needs substance: "No." is a legitimate answer
        # even when her last sentence contained the word (BH-I5). Two words
        # are still ambiguous, three words of her own sentence are not.
        if len(norm_trans.split()) >= 3 and norm_trans in norm_spoken:
            return True
        # Filter the filler even without timing match
        from .persona import FILLER_PHRASES
        for phrase in FILLER_PHRASES:
            if phrase in norm_trans:
                return True
        return False

    def _track_task(self, task: asyncio.Task) -> asyncio.Task:
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    def _session_active(self) -> bool:
        return bool((self._dictation_task and not self._dictation_task.done())
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
    async def handle(self, method: str, params: dict, writer=None) -> dict:
        handlers = {
            "ping": self._ping,
            "status": self._status,
            "cost": self._cost,
            "ack": self._ack,
            "halt": self._halt,
            "resume": self._resume,
            "ptt.start": self._ptt_start,
            "ptt.stop": self._ptt_stop,
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
        if method == "events.subscribe":
            if writer is not None:
                self._subscribers.add(writer)
            return {"subscribed": True,
                    "events": ["session.started", "transcript.interim",
                               "session.checkin", "session.offline",
                               "transcript.final", "session.ended",
                               "mode.changed", "offline.drained",
                               "speech.error", "conversation.message",
                               "class.changed", "knock.raised",
                               "knock.accepted", "knock.changed", "error"]}
        handler = handlers.get(method)
        if handler is None:
            raise ValueError(f"unknown method '{method}' — supported: "
                             f"{', '.join(sorted(handlers))}, events.subscribe")
        return await handler(params)

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
        if self._capture_source is not None:
            capture = type(self._capture_source).__name__.replace("Capture", "").lower()
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
            "capture": capture,
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
            self._track_task(asyncio.create_task(
                asyncio.to_thread(self.speech.play_ack, kind)))
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
                commitment_id=(int(params["commitment_id"])
                               if params.get("commitment_id") is not None
                               else None))
        except InitiativeError as exc:
            raise ValueError(str(exc)) from exc
        signal = self.knock_signal.emit(
            knock, class_mode=self.presence.status().enabled)
        knock = self._knock_dict(knock)
        await self.broadcast({"event": "knock.raised", "knock": knock,
                              "signal": signal})
        return {"knock": knock, "signal": signal}

    async def _knock_accept(self, params: dict) -> dict:
        knock_id = int(params.get("id"))
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

    async def _knock_decline(self, params: dict) -> dict:
        try:
            result = self.initiative.decline(int(params.get("id")))
        except InitiativeError as exc:
            raise ValueError(str(exc)) from exc
        await self.broadcast({"event": "knock.changed", "knock": result["knock"],
                              "action": "declined"})
        return result

    async def _knock_later(self, params: dict) -> dict:
        try:
            result = self.initiative.later(
                int(params.get("id")), hours=params.get("hours"))
        except InitiativeError as exc:
            raise ValueError(str(exc)) from exc
        await self.broadcast({"event": "knock.changed", "knock": result["knock"],
                              "action": "snoozed"})
        return result

    async def _knock_ignore(self, params: dict) -> dict:
        try:
            result = self.initiative.ignore(int(params.get("id")))
        except InitiativeError as exc:
            raise ValueError(str(exc)) from exc
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
            signal = self.knock_signal.emit(
                knock, class_mode=self.presence.status().enabled)
            knock = self._knock_dict(knock)
            raised.append(knock)
            await self.broadcast({"event": "knock.raised", "knock": knock,
                                  "signal": signal})
        return {"raised": raised, "count": len(raised)}

    async def _initiative_status(self, params: dict) -> dict:
        return {"initiative": self.initiative.status(),
                "class_mode": self.presence.status().as_dict()}

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
        job = self.cloud_queue.approve(int(params["job_id"]))
        return {"job": job, "note": "approved; run queue.drain to process it"}

    async def _queue_enqueue_external(self, params: dict) -> dict:
        job_id = self.cloud_queue.enqueue_external(
            str(params.get("action") or "external"),
            str(params.get("description") or ""),
            dict(params.get("payload") or {}))
        return {"job_id": job_id, "status": "awaiting_approval"}

    async def _ptt_start(self, params: dict) -> dict:
        # §18: ack RETURNS immediately; capture + Live session spin up in a
        # background task behind it. The user is already talking while the
        # socket opens — parse-while-you-speak starts here (§18 rule 3).
        if self._dictation_task and not self._dictation_task.done():
            # VB-11: the loser of the race is refused, and a refusal is not a
            # request to be acknowledged. She is already listening; saying "On it."
            # again is a second voice event for one press (and double audio when the
            # user mashes the hotkey). No ack is played and none is queued.
            route = self.speech.route(STANDARD_ACKS["on_it"])
            return {"listening": True, "already_listening": True, "ack": None,
                    "speech": {**route, "ack_kind": "on_it", "audio_path": None,
                               "cached": False, "played": False,
                               "suppressed": "already listening — no second ack"},
                    "note": "already listening"}
        ack = await self._ack({"kind": "on_it"})
        capture_cfg = self.config.section("capture")
        frame_ms = int(capture_cfg.get("chunk_ms", 30))
        source_kind = params.get("source") or capture_cfg.get("source", "mic")
        simulated = False
        if source_kind == "simulated":
            self._capture_source = SimulatedCapture(speech_frames=100_000,
                                                    frame_ms=frame_ms, realtime=True)
            simulated = True
        else:
            try:
                self._capture_source = PipeWireCapture(
                    params.get("target"), frame_ms=frame_ms)
            except RuntimeError:
                # No PipeWire (headless/containers): simulated frames keep
                # the full pipeline exercisable; status reports it honestly.
                self._capture_source = SimulatedCapture(speech_frames=100_000,
                                                        frame_ms=frame_ms, realtime=True)
                simulated = True
        self._stop_event = asyncio.Event()
        self._dictation_session_mode = str(params.get("mode") or "narration")
        self.mode = "listening"
        # Hotkey path: use the monitor's latest snapshot, never probe here.
        connectivity = await self._connectivity_snapshot(refresh=False)
        await self.broadcast({"event": "status.changed", "mode": self.mode,
                              "connectivity": connectivity.as_dict()})

        async def dictation_sink(event: dict) -> None:
            # Cached audio only: the soft check-in must never wait on TTS.
            if event.get("event") == "session.checkin" and self.speech.cached_ack("checkin"):
                self._track_task(asyncio.create_task(
                    asyncio.to_thread(self.speech.play_ack, "checkin")))
            await self.broadcast(event)

        # BUG5: wrap source to mute while speaking
        muted_source = self._wrap_muted(self._capture_source)
        self._dictation_task = self._track_task(asyncio.create_task(
            self.dictation.dictate(
                muted_source, mode=self._dictation_session_mode,
                sink=dictation_sink, stop_event=self._stop_event)))
        return {"listening": True, **ack, "simulated_capture": simulated,
                "session_mode": self._dictation_session_mode,
                "connectivity": connectivity.as_dict()}

    async def _ptt_stop(self, params: dict) -> dict:
        ack = await self._ack({"kind": "on_it"})  # release acked locally, instantly
        if self.mode == "listening":
            self.mode = "transcribing"  # waiting on final + cleanup (§3.9 states)
            await self.broadcast({"event": "status.changed", "mode": self.mode})
        if self._stop_event:
            self._stop_event.set()
        result = None
        if self._dictation_task:
            try:
                session = await asyncio.wait_for(self._dictation_task, timeout=60)
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
                    # Factual narration from real state (§13.1) — no model call.
                    "narration": self.governor.narrate_fact(
                        "transcribe.done",
                        {"words": len(session.raw_text.split()),
                         "seconds": session.duration_s}),
                }
                if self._dictation_session_mode == "command" and result["text"].strip():
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
                        # BUG5: drop echo of own TTS before routing to ask
                        if self._is_echo(result["text"]):
                            result["command"] = None
                            result["narration"] = "echo suppressed — own TTS captured as input"
                        else:
                            result["command"] = await self._ask({
                                "text": result["text"],
                                "speak": params.get("speak", True),
                            })
                    result["narration"] = result["command"].get("reply", result["narration"])
                # BUG5: general echo suppression for any ptt result
                if result and result.get("text") and self._is_echo(result["text"]):
                    result["text"] = ""
                    result["raw_text"] = ""
                    result["flagged"] = False
                    result["narration"] = "echo suppressed — own TTS captured as input"
                    result["echo_suppressed"] = True
            except Exception as exc:
                result = {"error": f"dictation did not finish cleanly: {exc}"}
            self._dictation_task = None
        self.mode = "idle"
        await self.broadcast({"event": "status.changed", "mode": self.mode})
        await self._apply_pending_mode_switch()
        return {"listening": False, **ack, "result": result,
                "connectivity": self.mode_manager.status(refresh=False).as_dict()}

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
                    await self.broadcast({"event": "error", "error": str(exc),
                                          "plan_id": plan_id})

            self._plan_tasks[plan_id] = asyncio.create_task(_run())
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
        item_id = int(params["item_id"])
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

        mic = make_source(meeting_cfg.get("mic_target") or None)
        system = make_source(meeting_cfg.get("system_target") or None)
        dual = DualCapture(mic, system)
        frames: dict[str, list[bytes]] = {"mic": [], "sys": []}

        async def collect():
            async for mic_frame, sys_frame in dual.frames():
                frames["mic"].append(mic_frame)
                frames["sys"].append(sys_frame)

        self.mode = "meeting"
        await self.broadcast({"event": "status.changed", "mode": self.mode})
        self._meeting = {"dual": dual, "frames": frames,
                         "task": asyncio.create_task(collect())}
        return {"state": "meeting"}

    async def _meeting_stop(self, params: dict) -> dict:
        if self._meeting is None:
            return {"state": "idle", "note": "no meeting in progress"}
        meeting, self._meeting = self._meeting, None
        await meeting["dual"].aclose()
        meeting["task"].cancel()
        try:
            await meeting["task"]
        except asyncio.CancelledError:
            pass  # expected: we just cancelled it
        from datetime import datetime

        from .capture import write_wav

        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        rate = int(self.config.section("capture").get("sample_rate", 16000))
        mic_wav = write_wav(self.config.data_dir / "audio" / f"meeting-{stamp}-mic.wav",
                            meeting["frames"]["mic"], rate)
        sys_wav = write_wav(self.config.data_dir / "audio" / f"meeting-{stamp}-system.wav",
                            meeting["frames"]["sys"], rate)
        self.mode = "processing"
        self._meeting_processing = True
        await self.broadcast({"event": "status.changed", "mode": self.mode})
        try:
            result = await asyncio.to_thread(
                self.meetings.transcribe_dual, mic_wav, sys_wav,
                title=params.get("title"),
                pyannote_refine=bool(self.config.section("meeting").get("pyannote_refine")))
        finally:
            self._meeting_processing = False
        self.mode = "idle"
        await self.broadcast({"event": "status.changed", "mode": self.mode})
        await self._apply_pending_mode_switch()
        return {"state": "idle", "note_path": str(result.note_path),
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
        try:
            result = self.showoff.enter(
                command=str(params.get("command") or ""),
                embedding=params.get("embedding"),
                owner_present=bool(params.get("owner_present", False)),
                source=str(params.get("source") or "mic"),
                replayed=bool(params.get("replayed", False)),
                live_mic=bool(params.get("live_mic", True)),
                audio_sha256=params.get("audio_sha256"))
        except ShowoffError as exc:
            raise ValueError(str(exc)) from exc
        speech = await self._maybe_speak_reply(
            result["announcement"], {"speak": params.get("speak", True)})
        await self.broadcast({"event": "showoff.entered",
                              "session_id": result["session_id"],
                              "announcement": result["announcement"]})
        return {**result, "speech": speech}

    async def _showoff_exit(self, params: dict) -> dict:
        try:
            if params.get("command") or params.get("reason") == "owner_stop":
                summary = self.showoff.exit_owner(
                    command=str(params.get("command") or ""),
                    embedding=params.get("embedding"))
            elif params.get("reason") == "owner_hotkey" or not params.get("reason"):
                summary = self.showoff.exit_hotkey()
            else:
                raise ValueError(
                    "show-off exits only by owner stop command, owner hotkey, "
                    "timeout, or a never-list attempt")
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
        if leak is not None:
            self.disclosure.log("leak_blocked", {
                "kind": leak["kind"], "why": leak["why"],
                "fact_id": leak.get("fact_id"), "channel": channel,
                "speaker": "guest", "context": "showoff"})
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
            "speech": speech, "fixture": None,
            "serious_gate": None, "mode": self.config.gemini_mode,
        }

    async def _generate(self, prompt: str, *, gen_config=None, verify=None,
                        purpose: str = "user_turn", is_user_turn=True):
        """One bounded chat call. The test-double fallback lives here only.

        `asyncio.to_thread(...)` cannot raise `TypeError` while the coroutine is
        being built, so the previous nested try/except could only observe the
        error after awaiting - and then duplicated the whole timeout path for
        the retry. One helper, one behaviour, one bound (BH-I12).
        """
        timeout = self._chat_timeout_s
        kwargs = {"gen_config": gen_config, "verify": verify,
                  "purpose": purpose, "is_user_turn": is_user_turn}
        try:
            coro = asyncio.to_thread(self.client.generate, "chat", prompt, **kwargs)
            return await asyncio.wait_for(coro, timeout=timeout)
        except TypeError as exc:
            # Only a test double with an older signature is retried; a genuine
            # TypeError raised inside the client must surface.
            if "unexpected keyword" not in str(exc):
                raise
        coro = asyncio.to_thread(self.client.generate, "chat", prompt)
        return await asyncio.wait_for(coro, timeout=timeout)

    async def _ask(self, params: dict) -> dict:
        """Conversational turn on the §13.4 ladder: governor (local) →
        exact/grammar intents (local) → memory recall (local) → and only
        then the cheapest-first harness with assembled context (§17).
        Offline, that final rung becomes a durable queue entry instead of
        a network attempt. Any spoken form is local TTS only (§13.8)."""
        from .intents import route

        text = str(params.get("text", "")).strip()
        if not text:
            raise ValueError("ask needs params.text")
        speaker = str(params.get("speaker") or "owner").lower()
        channel = str(params.get("channel") or "voice")
        showoff_now = self.showoff.status()
        # Speaker verification, when the caller supplies a verdict, is authority
        # here too: a voice that is not the owner never sees owner memory.
        # During show-off mode, the room has guests by definition — any voice
        # turn claiming to be the owner must pass voiceprint verification.
        verified = params.get("owner_verified")
        if verified is None and showoff_now.get("active") and speaker == "owner" and channel == "voice":
            verdict = self.showoff.verify_owner(params.get("embedding"))
            verified = bool(verdict.get("verified"))
        if verified is False:
            speaker = "guest"
        if speaker != "owner":
            if showoff_now.get("active"):
                return await self._guest_turn(text, params, showoff_now)
            return await self._guest_turn_normal(text, params)

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
        channel = str(params.get("channel") or "voice")
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
        intent = None if company_command is not None else route(text)
        if intent is not None:
            reply, via = await self._run_intent(intent)

        if reply is None:
            # Rung 5/6: assemble the exact context the cheap model needs.
            hits = await asyncio.to_thread(self.memory.recall, text)
            restricted = self.disclosure.company() or speaker != "owner"
            kept = self.disclosure.filter_hits(hits, guest=speaker != "owner")
            context = "\n".join(f"- [{h.source} {h.ref}] {h.text}" for h in kept)
            history_lines = ""
            if prior_turns:
                safe_turns = [
                    m for m in prior_turns[-6:]
                    if m.get("text") and (
                        not restricted
                        or self.disclosure.leak_in(
                            str(m["text"]), guest=speaker != "owner",
                            company=self.disclosure.company()) is None
                    )
                ]
                if safe_turns:
                    history_lines = "\n".join(
                        f"- {m['role']}: {m['text']}" for m in safe_turns
                    )
            # Build user-facing prompt body (context + history + user text)
            body = text
            if history_lines and context:
                body = (f"Context from the user's local memory/index "
                          f"(cite paths plainly):\n{context}\n\n"
                          f"Recent conversation in this session:\n{history_lines}\n\n"
                          f"User: {text}")
            elif context:
                body = (f"Context from the user's local memory/index "
                          f"(cite paths plainly):\n{context}\n\nUser: {text}")
            elif history_lines:
                body = (f"Recent conversation in this session:\n{history_lines}\n\n"
                          f"User: {text}")
            # System prompt carries the persona governor: no roleplay, terse, no asterisks
            disclosure_note = (self.disclosure.prompt_note(guest=speaker != "owner")
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
                # Verify that the reply respects delivery spec: no asterisk narration,
                # terse for simple turns. A violation is a harness failure that earns
                # a retry with feedback (and escalation if needed).
                def _verify(reply_text: str) -> bool:
                    return is_valid_chat_reply(reply_text, original_user_text=text)
                # Bounded Live work: console.say must return within N seconds
                # even with a slow transport (BUG1).
                try:
                    result = await self._generate(
                        full_prompt, gen_config=gen_config, verify=_verify,
                        purpose="user_turn", is_user_turn=True)
                    reply, via, model, fixture = (result.text, "gemini",
                                                  result.model, result.fixture)
                    if reply:
                        self.mode_manager.observe_success("gemini")
                except TimeoutError:
                    # Live transport hung — return a terse fallback promptly,
                    # never hang the caller. The turn is still persisted as
                    # completed; speech (if any) is async.
                    reply = "I am now. What do you need?"
                    via = "local-timeout-fallback"
                    model = None
                    fixture = None
                    await self.broadcast({"event": "live.timeout", "text": text[:40]})

        # The outgoing guard: a model that ignores the prompt still cannot read a
        # stored secret, plan or owner fact back to the room.
        leak = self.disclosure.leak_in(
            reply, guest=speaker != "owner",
            company=self.disclosure.company())
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
        server = await serve(self.config.socket_path, self.handle)
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
        tasks = [
            t for t in (*extra_tasks, self._dictation_task, *self._background_tasks)
            if t is not None
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.store.close()


def main() -> None:
    config = load_config()
    try:
        asyncio.run(Daemon(config).run())
    except RuntimeError as exc:
        # Two-daemon refusal is a normal startup outcome, not a crash (BH-J4).
        print(f"assistd: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
