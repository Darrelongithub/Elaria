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
from .config import Config, load_config, load_humour_profile
from .cost import day_start_iso, iso_now, month_start_iso
from .gemini_client import GeminiClient
from .ipc import serve
from .persona import PersonaGovernor, TurnContext
from .safety import clear_halt, is_halted, set_halt
from .store import Store


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
        self._load_relationship_state()

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
    async def handle(self, method: str, params: dict) -> dict:
        handlers = {
            "ping": self._ping,
            "status": self._status,
            "cost": self._cost,
            "ack": self._ack,
            "halt": self._halt,
            "resume": self._resume,
            "ptt.start": self._ptt_start,
            "ptt.stop": self._ptt_stop,
            "ask": self._ask,
        }
        handler = handlers.get(method)
        if handler is None:
            raise ValueError(f"unknown method '{method}' — Phase 0 supports: "
                             f"{', '.join(sorted(handlers))}")
        return await handler(params)

    async def _ping(self, params: dict) -> dict:
        return {"pong": True, "version": __version__}

    async def _status(self, params: dict) -> dict:
        runtime = self.config.socket_path.parent
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
        return {"halted": True, "note": "executor checks this flag between every op (§4.4)"}

    async def _resume(self, params: dict) -> dict:
        clear_halt(self.config.socket_path.parent)
        if self.mode == "halted":
            self.mode = "idle"
        return {"halted": False}

    async def _ptt_start(self, params: dict) -> dict:
        # Local ack NOW (<300ms budget); capture + Live session join behind
        # it in Phase 1 (§18 rule 1-2). The socket opens after the user
        # already knows it's listening.
        self.mode = "listening"
        return {"listening": True, **self.governor.ack(),
                "phase": "capture/ASR streaming lands in Phase 1 (§9)"}

    async def _ptt_stop(self, params: dict) -> dict:
        self.mode = "idle"
        return {"listening": False, **self.governor.ack()}

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
        print(f"[assistd] Elaria Phase 0 up · mode={self.config.gemini_mode} "
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
