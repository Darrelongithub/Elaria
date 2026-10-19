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
import time

from . import __version__
from .asr import local_asr_status
from .capture import PipeWireCapture, SimulatedCapture
from .config import Config, load_config, load_humour_profile
from .cost import day_start_iso, iso_now, month_start_iso
from .gemini_client import GeminiClient
from .ipc import serve
from .modes import ModeManager
from .offline_queue import CloudQueue
from .organiser import OrganiserService
from .persona import PersonaGovernor, TurnContext
from .safety import clear_halt, is_halted, set_halt
from .store import Store
from .transcribe import DictationService
from .tts import STANDARD_ACKS, SpeechService


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
        self.speech = SpeechService(
            config, self.store, client=self.client,
            # INTERIM online voice: Flare speaks only while actually online. Offline
            # turns are text-only (amendment 2026-10-20) - no cloud call, and the
            # dormant local voice does not take them over either.
            is_online=lambda: self.mode_manager.status(refresh=False).effective_mode
            == "ONLINE")
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
        self._load_relationship_state()

    async def broadcast(self, event: dict) -> None:
        line = (json.dumps(event) + "\n").encode()
        dead = []
        for writer in self._subscribers:
            try:
                writer.write(line)
                await writer.drain()
            except (ConnectionResetError, BrokenPipeError, RuntimeError):
                dead.append(writer)
        for writer in dead:
            self._subscribers.discard(writer)

    # -- Phase 8 connectivity / speech helpers --------------------------------
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
        route = self.speech.route(text)
        if not self.config.section("tts").get("enabled", True):
            return {**route, "played": False, "queued": False}

        async def _run():
            try:
                return await asyncio.to_thread(self.speech.speak, text)
            except Exception as exc:
                await self.broadcast({"event": "speech.error", "error": str(exc),
                                      **route})
                return None

        self._track_task(asyncio.create_task(_run()))
        return {**route, "queued": True}

    async def _maybe_speak_reply(self, text: str, params: dict) -> dict:
        route = self.speech.route(text)
        requested = params.get("speak")
        if requested is True:
            try:
                result = await asyncio.to_thread(self.speech.speak, text)
                return result.as_dict()
            except Exception as exc:
                return {**route, "played": False, "error": str(exc)}
        if requested is None and self.config.section("tts").get("speak_replies", False):
            return await self._speak_in_background(text)
        return {**route, "played": False, "queued": False}

    # -- relationship state persists across restarts (§16) -------------------
    def _load_relationship_state(self) -> None:
        raw = self.store.get_state("persona")
        if raw:
            try:
                saved = json.loads(raw)
                self.governor.familiarity = float(saved.get("familiarity", 0.0))
            except (ValueError, TypeError):
                pass

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
            "speech.say": self._speech_say,
            "speech.warm": self._speech_warm,
            "speech.audition": self._speech_audition,
            "speech.select": self._speech_select,
            "queue.list": self._queue_list,
            "queue.drain": self._queue_drain,
            "queue.approve": self._queue_approve,
            "queue.enqueue_external": self._queue_enqueue_external,
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
                               "speech.error", "error"]}
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
            "quota_today_live_calls": self.store.calls_since(day_start_iso()),
            "event_subscribers": len(self._subscribers),
            "connectivity": connectivity.as_dict(),
            "connectivity_mode": connectivity.effective_mode,
            "voice": self.speech.status(),
            "offline_asr": local_asr_status(self.config),
            "cloud_queue": self.store.cloud_job_counts(),
        }

    async def _cost(self, params: dict) -> dict:
        month = self.store.llm_summary(month_start_iso())
        today = self.store.llm_summary(day_start_iso())
        today["live_calls"] = self.store.calls_since(day_start_iso())
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
        should_speak = params.get("speak", self.config.section("tts").get("speak_acks", True))
        if should_speak and cached is None and not route["muted"]:
            await self._await_ack_cache()          # VB-13: boot warming, once
            cached = self.speech.cached_ack(kind)
        ack["speech"] = {**route, "ack_kind": kind, "audio_path": cached,
                         "cached": cached is not None, "played": False,
                         # A miss while she is supposed to speak is a reported
                         # condition (VB-2), not a verdict: the re-warm below is
                         # what makes the next press audible.
                         "cache_miss": cached is None and not route["muted"]}
        if cached is None:
            self._schedule_rewarm_if_requested()   # VB-2: miss -> one warm cycle
        if should_speak and cached:
            self._track_task(asyncio.create_task(
                asyncio.to_thread(self.speech.play_ack, kind)))
            ack["speech"]["queued"] = True
        self.store.log_persona_event(iso_now(), "ack", json.dumps(ack))
        return ack

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

    async def _speech_status(self, params: dict) -> dict:
        return {"voice": self.speech.status()}

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
            return {"listening": True, **await self._ack({"kind": "on_it"}),
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

        self._dictation_task = asyncio.create_task(
            self.dictation.dictate(
                self._capture_source, mode=self._dictation_session_mode,
                sink=dictation_sink, stop_event=self._stop_event))
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
                    # Known grammar climbs the local ladder first; open text
                    # follows the same offline queue policy as `ask`.
                    result["command"] = await self._ask({
                        "text": result["text"],
                        "speak": params.get("speak", True),
                    })
                    result["narration"] = result["command"].get("reply", result["narration"])
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
        self.store.set_item_decision(item_id, "auto" if verdict == "approve" else "rejected")
        return {"item_id": item_id, "decision": "auto" if verdict == "approve" else "rejected"}

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
        decision = self.governor.decide(TurnContext(user_text=text))
        self.store.log_persona_event(
            iso_now(), "decision",
            json.dumps({"register": decision.register,
                        "serious_gate": decision.serious_gate,
                        "pushback": decision.pushback, "reason": decision.reason}))
        conversation_id = self.store.get_or_create_conversation(iso_now())
        self.store.add_message(conversation_id, iso_now(), "user", text)

        reply, via, model, fixture = None, None, None, None
        queued_job_id = None
        connectivity = await self._connectivity_snapshot()
        intent = route(text)
        if intent is not None:
            reply, via = await self._run_intent(intent)

        if reply is None:
            # Rung 5/6: assemble the exact context the cheap model needs.
            hits = await asyncio.to_thread(self.memory.recall, text)
            context = "\n".join(f"- [{h.source} {h.ref}] {h.text}" for h in hits)
            prompt = text
            if context:
                prompt = (f"Context from the user's local memory/index "
                          f"(cite paths plainly):\n{context}\n\nUser: {text}")
            if decision.register == "expressive-allowed":
                prompt += ("\n\nRegister note: the user is bantering; matching "
                           "their playful-teasing register concisely is welcome "
                           "if a genuinely situational line exists — otherwise "
                           "plain. One short line preferred. No canned warmth.")
            if connectivity.is_offline:
                queued_job_id = self.cloud_queue.enqueue_chat(
                    text, prompt, conversation_id)
                reply = (f"Offline — that needs Gemini, so I queued it durably "
                         f"(job #{queued_job_id}). It will drain on reconnect.")
                via = "local-queue"
            else:
                result = await asyncio.to_thread(self.client.generate, "chat", prompt)
                reply, via, model, fixture = result.text, "gemini", result.model, result.fixture
                if reply:
                    self.mode_manager.observe_success("gemini")

        speech = await self._maybe_speak_reply(reply, params)
        self.store.add_message(conversation_id, iso_now(), "assistant", reply, via)
        if params.get("reaction"):
            self.governor.note_user_reaction(str(params["reaction"]))
            self._save_relationship_state()
        return {
            "reply": reply,
            "via": via,  # local-intent | local-memory | local-queue | gemini
            "model": model,
            "register": decision.register,
            "serious_gate": decision.serious_gate,
            "mode": self.config.gemini_mode,
            "fixture": fixture,
            "connectivity": connectivity.as_dict(),
            "queued_job_id": queued_job_id,
            "speech": speech,
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

    async def _connectivity_loop(self) -> None:
        interval = float(self.config.section("connectivity").get(
            "health_check_interval_s", 20))
        while True:
            await asyncio.sleep(max(1.0, interval))
            # refresh() itself returns immediately without probing when the
            # owner forced offline; the socket probe runs off-loop in auto.
            status = await asyncio.to_thread(self.mode_manager.refresh, force=True)
            await self._note_connectivity_transition(status)

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
        self._warm_pending = True
        warm_task = asyncio.create_task(self._warm_speech_cache())
        server = await serve(self.config.socket_path, self.handle)
        connectivity_task = asyncio.create_task(self._connectivity_loop())
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
            for task in (connectivity_task, warm_task, *self._background_tasks):
                task.cancel()
            self.store.close()


def main() -> None:
    config = load_config()
    asyncio.run(Daemon(config).run())


if __name__ == "__main__":
    main()
