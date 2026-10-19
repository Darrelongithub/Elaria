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
from .capture import PipeWireCapture, SimulatedCapture
from .config import Config, load_config, load_humour_profile
from .cost import day_start_iso, iso_now, month_start_iso
from .gemini_client import GeminiClient
from .ipc import serve
from .persona import PersonaGovernor, TurnContext
from .safety import clear_halt, is_halted, set_halt
from .store import Store
from .transcribe import DictationService


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
        self.dictation = DictationService(config, self.store, self.client)
        self._subscribers: set = set()          # event-stream writers (§3.1)
        self._dictation_task: asyncio.Task | None = None
        self._capture_source = None
        self._stop_event: asyncio.Event | None = None
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
            "ask": self._ask,
        }
        if method == "events.subscribe":
            if writer is not None:
                self._subscribers.add(writer)
            return {"subscribed": True,
                    "events": ["session.started", "transcript.interim",
                               "session.checkin", "transcript.final",
                               "session.ended", "error"]}
        handler = handlers.get(method)
        if handler is None:
            raise ValueError(f"unknown method '{method}' — supported: "
                             f"{', '.join(sorted(handlers))}, events.subscribe")
        return await handler(params)

    async def _ping(self, params: dict) -> dict:
        return {"pong": True, "version": __version__}

    async def _status(self, params: dict) -> dict:
        runtime = self.config.socket_path.parent
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
        handler cannot reach GeminiClient by construction."""
        ack = self.governor.ack()
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

    async def _ptt_start(self, params: dict) -> dict:
        # §18: ack RETURNS immediately; capture + Live session spin up in a
        # background task behind it. The user is already talking while the
        # socket opens — parse-while-you-speak starts here (§18 rule 3).
        if self._dictation_task and not self._dictation_task.done():
            return {"listening": True, **self.governor.ack(), "note": "already listening"}
        ack = self.governor.ack()
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
        self.mode = "listening"
        await self.broadcast({"event": "status.changed", "mode": self.mode})
        self._dictation_task = asyncio.create_task(
            self.dictation.dictate(
                self._capture_source, mode=params.get("mode", "narration"),
                sink=self.broadcast, stop_event=self._stop_event))
        return {"listening": True, **ack, "simulated_capture": simulated}

    async def _ptt_stop(self, params: dict) -> dict:
        ack = self.governor.ack()  # release acknowledged locally, instantly
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
                    "notes": session.notes,
                    # Factual narration from real state (§13.1) — no model call.
                    "narration": self.governor.narrate_fact(
                        "transcribe.done",
                        {"words": len(session.raw_text.split()),
                         "seconds": session.duration_s}),
                }
            except Exception as exc:
                result = {"error": f"dictation did not finish cleanly: {exc}"}
            self._dictation_task = None
        self.mode = "idle"
        await self.broadcast({"event": "status.changed", "mode": self.mode})
        return {"listening": False, **ack, "result": result}

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
                "clipboard": session.clipboard}

    async def _ask(self, params: dict) -> dict:
        """Conversational turn: governor first (local), harness second (§17).

        The governor may only *permit* expressive register; the words come
        from the model call that was happening anyway — never from a
        template bank (§13.2). In mock mode this returns the replayed or
        synthetic fixture, so the full path is testable with no key.
        """
        text = str(params.get("text", "")).strip()
        if not text:
            raise ValueError("ask needs params.text")
        decision = self.governor.decide(TurnContext(user_text=text))
        self.store.log_persona_event(
            iso_now(), "decision",
            json.dumps({"register": decision.register,
                        "serious_gate": decision.serious_gate,
                        "pushback": decision.pushback,
                        "reason": decision.reason}),
        )
        result = self.client.generate("chat", text)
        if params.get("reaction"):
            self.governor.note_user_reaction(str(params["reaction"]))
            self._save_relationship_state()
        return {
            "reply": result.text,
            "model": result.model,
            "register": decision.register,
            "serious_gate": decision.serious_gate,
            "mode": self.config.gemini_mode,
            "fixture": result.fixture,
        }

    # -- lifecycle ---------------------------------------------------------------
    async def run(self) -> None:
        outstanding = self.store.outstanding_intents()
        if outstanding:
            # §4.2 recovery: surface, never silently drop. Repair/quarantine
            # tooling ships with the executor (Phase 4); Phase 0 reports.
            print(f"[assistd] WARNING: {len(outstanding)} uncommitted journal "
                  f"intent(s) from a previous run — inspect before enabling "
                  f"the executor.", flush=True)
        server = await serve(self.config.socket_path, self.handle)
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
        async with server:
            await stop.wait()
        self.store.close()


def main() -> None:
    config = load_config()
    asyncio.run(Daemon(config).run())


if __name__ == "__main__":
    main()
