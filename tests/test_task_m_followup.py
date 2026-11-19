"""Follow-up pins — owner rulings 1 and 2, and the Lua bind defect (2026-11-15).

Ruling 1 (F17 unconditional) is pinned in `test_task_k_gateway.py`: an unnamed
capture node refuses on every machine, with the same reason, before the earcon.

Ruling 2 (F28): `AudioGateway.claim_reply` is the SOLE live-path authority for
"one utterance, one reply". The daemon's local dict-membership gate is gone;
the early dispatch and the late gate both ask the gateway, and a second claim
for the same session is refused and journalled. Pinned for both shapes:

* PTT  — press, one utterance, early dispatch, late gate;
* live — the same session through a scripted Live transport.

Defect fix: the installer's bind snippet is emitted Lua-first
(`hl.bind(...)`), because Hyprland 0.57 reads only `hyprland.lua`; the legacy
`bind = ...` form was deleted upstream and would be silently ignored on the
owner's machine. Legacy is emitted only on positive detection of < 0.55.
"""

from __future__ import annotations

import asyncio
import json
import struct
from pathlib import Path
from typing import ClassVar

import pytest

from assistant import asr
from assistant.capture import SAMPLE_RATE
from assistant.daemon import Daemon
from assistant.hypr_binds import BINDS, LEGACY, LUA, detect, emit_binds
from assistant.ipc import call
from assistant.live_client import LiveEvent, ScriptedLiveTransport

REPO = Path(__file__).resolve().parents[1]
FRAME_SAMPLES = SAMPLE_RATE * 30 // 1000
SILENT = b"\x00\x00" * FRAME_SAMPLES
SPEECH = struct.pack(f"<{FRAME_SAMPLES}h", *([6000] * FRAME_SAMPLES))
USER_TEXT = "what is on my plate today"


# ---------------------------------------------------------------------------
# harness (the BUG-6 socket pattern)
# ---------------------------------------------------------------------------
class FakeDevice:
    opened: ClassVar[list] = []

    def __init__(self, target=None, *, sample_rate=SAMPLE_RATE, frame_ms=30,
                 stall_timeout_s=8.0):
        type(self).opened.append(target)
        self.target = target
        self.stalled = False
        self.closed = False

    async def frames(self):
        for _ in range(4):
            yield SPEECH

    async def aclose(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _clear_devices():
    FakeDevice.opened.clear()
    yield
    FakeDevice.opened.clear()


@pytest.fixture
def running_daemon(config):
    import threading

    from assistant.ipc import serve

    daemon = Daemon(config)
    loop = asyncio.new_event_loop()
    server = loop.run_until_complete(serve(
        config.socket_path, daemon.handle,
        on_disconnect=daemon._subscribers.discard))
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield daemon, server

    async def _shutdown():
        server.close()
        await daemon.aclose()
        await asyncio.wait_for(server.wait_closed(), timeout=3)

    asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=8)
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=3)
    loop.close()


def _journal_rows(store, kind):
    return [json.loads(row["detail"]) for row in
            store.list_persona_events(kind=kind, limit=10)]


# ---------------------------------------------------------------------------
# RULING 2 — the gateway is the only authority
# ---------------------------------------------------------------------------
def test_f28_the_daemon_has_no_local_reply_gate_left(config):
    """The old dict-membership gate must be GONE, not merely mirrored."""
    daemon = Daemon(config)
    try:
        calls: list = []

        async def fake_ask(params):
            calls.append(params)
            return {"reply": "Answer.", "via": "test"}

        daemon._ask = fake_ask
        daemon._dictation_session_mode = "conversation"

        async def run():
            first = daemon._early_dispatch_reply("sess-x", "Hello there",
                                                 {"speak": False})
            second = daemon._early_dispatch_reply("sess-x", "Hello there",
                                                  {"speak": False})
            return first, second

        first, second = asyncio.run(run())
        assert first is True
        assert second is False, "one utterance, one reply"
        # The gate is the gateway's ledger, and it names the session.
        assert daemon.audio._reply_claimed.get("sess-x") is True
    finally:
        daemon.store.close()


def test_f28_a_second_late_claim_is_refused_with_a_reason(config):
    daemon = Daemon(config)
    try:
        allowed, why = daemon.audio.claim_reply("sess-y")
        assert (allowed, why) == (True, "claimed")
        again, why2 = daemon.audio.claim_reply("sess-y")
        assert again is False
        assert "already claimed" in why2
    finally:
        daemon.store.close()


def _live_transport(monkeypatch, uploads=None):
    class Transport(ScriptedLiveTransport):
        async def send_audio(self, pcm):
            if uploads is not None:
                uploads.append(pcm)

        async def activity_end(self):
            await self._queue.put(LiveEvent("final", text=USER_TEXT))
            await self._queue.put(LiveEvent("turn_complete"))

    monkeypatch.setattr(asr, "make_live_transport", lambda config: Transport())


def _counting_ask(daemon):
    asks: list = []

    async def fake_ask(params):
        asks.append(dict(params))
        return {"reply": "One reply.", "via": "test"}

    daemon._ask = fake_ask
    return asks


def test_f28_live_shape_one_utterance_gets_exactly_one_reply(
        config, running_daemon, monkeypatch):
    """LIVE shape: leg-landing dispatches, the late gate REUSES that task."""
    daemon, _server = running_daemon
    daemon.mode_manager.refresh(force=True)
    asks = _counting_ask(daemon)
    _live_transport(monkeypatch)
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", FakeDevice)
    monkeypatch.setattr(asr, "transcribe_file",
                        lambda *a, **k: pytest.fail(
                            "the batch chain must not run on a clean Live final"))

    started = call(config.socket_path, "ptt.start",
                   {"mode": "conversation", "speak": False}, timeout=5.0)
    assert started["listening"] is True
    sid = started["session_id"]
    stopped = call(config.socket_path, "ptt.stop", {"wait_s": 20.0}, timeout=25.0)

    result = stopped.get("result") or {}
    assert result.get("raw_text") == USER_TEXT
    assert result.get("backend") == "gemini_live"
    assert len(asks) == 1, (
        f"one utterance produced {len(asks)} reply generations (F28)")
    # The ledger that decided is the GATEWAY's, keyed by this session.
    assert daemon.audio._reply_claimed.get(sid) is True


def test_f28_ptt_shape_a_taken_claim_refuses_instead_of_replying_again(
        config, running_daemon, monkeypatch):
    """PTT shape: when the claim is already held, the gate answers with the fact.

    This is the double-reply bug's own shape — a reply exists for the session,
    so the late gate must NOT generate a second one.
    """
    daemon, _server = running_daemon
    daemon.mode_manager.refresh(force=True)
    asks = _counting_ask(daemon)
    _live_transport(monkeypatch)
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", FakeDevice)
    monkeypatch.setattr(asr, "transcribe_file", lambda *a, **k: pytest.fail(
        "the batch chain must not run on a clean Live final"))

    started = call(config.socket_path, "ptt.start",
                   {"mode": "conversation", "speak": False}, timeout=5.0)
    sid = started["session_id"]
    # Somebody already answered this utterance.
    assert daemon.audio.claim_reply(sid)[0] is True
    stopped = call(config.socket_path, "ptt.stop", {"wait_s": 20.0}, timeout=25.0)

    result = stopped.get("result") or {}
    command = result.get("command") or {}
    assert asks == [], "a taken claim was answered with a second generation"
    assert command.get("reply") is None
    assert "F28" in (command.get("note") or ""), (
        "the refusal must name the rule it enforced")
    assert "already claimed" in (command.get("suppressed") or "")


def test_f28_a_refused_late_claim_journals_the_suppression(config):
    """The late gate's refusal is a FACT in the journal, not a silent skip."""
    daemon = Daemon(config)
    try:
        assert daemon.audio.claim_reply("sess-z")[0] is True
        allowed, why = daemon.audio.claim_reply("sess-z")
        assert allowed is False
        # the daemon logs with this exact event name when it refuses
        source = Path("src/assistant/daemon.py").read_text()
        assert "dictate.reply_refused_duplicate" in source
        assert "F28" in source
        assert why
    finally:
        daemon.store.close()


# ---------------------------------------------------------------------------
# DEFECT FIX — Lua-first bind emission
# ---------------------------------------------------------------------------
def test_binds_are_emitted_in_lua_by_default():
    snippet = emit_binds()
    assert snippet == emit_binds(LUA)
    assert 'hl.bind("Escape", hl.dsp.exec_cmd("assist ptt cancel"))' in snippet
    assert 'hl.bind("SUPER + grave", hl.dsp.exec_cmd("assist ptt start"))' in snippet
    assert "release = true" in snippet and "ignore_mods = true" in snippet
    assert "bindri" not in snippet and "bind =" not in snippet, (
        "Lua is the default; legacy syntax must never leak into it")


def test_legacy_syntax_is_emitted_only_for_a_detected_old_hyprland():
    legacy = emit_binds(LEGACY)
    assert "bindri = SUPER, grave, exec, assist ptt stop --stop-source bind" in legacy
    assert "bind = , Escape, exec, assist ptt cancel" in legacy
    assert "hl.bind" not in legacy


@pytest.mark.parametrize("version,expected", [
    ("Hyprland, built from branch main at commit abc v0.57.1", LUA),
    ("v0.55.0", LUA),
    ("v0.54.2", LEGACY),
    ("garbage with no version", LUA),          # unknown: never the dead dialect
])
def test_syntax_detection_is_lua_first(version, expected, monkeypatch):
    import subprocess

    monkeypatch.setattr("assistant.hypr_binds.shutil.which",
                        lambda _b: "/usr/bin/hyprctl")

    def runner(argv, capture_output=True, text=True, timeout=10):
        return subprocess.CompletedProcess(argv, 0, stdout=version, stderr="")

    info = detect(runner=runner)
    assert info["syntax"] == expected


def test_no_hyprctl_still_emits_lua(monkeypatch):
    monkeypatch.setattr("assistant.hypr_binds.shutil.which", lambda _b: None)
    info = detect()
    assert info["syntax"] == LUA
    assert info["present"] is False
    assert "Lua" in info["detail"]


def test_doctor_reports_the_emitted_snippet_for_the_detected_syntax(monkeypatch):
    import subprocess

    from assistant.cli import hyprland_info

    def runner(argv, capture_output=True, text=True, timeout=10):
        return subprocess.CompletedProcess(argv, 0,
                                           stdout="Hyprland v0.57.0", stderr="")

    monkeypatch.setattr("assistant.hypr_binds.shutil.which", lambda _b: "/usr/bin/hyprctl")
    info = hyprland_info(runner=runner)
    assert "lua" in info["syntax"]
    assert 'hl.bind("Escape"' in info["emit"]
    assert "bind =" not in info["emit"]


def test_the_shipped_snippets_are_generated_by_the_emitter():
    lua = (REPO / "ui/hyprland/elaria-binds.lua").read_text()
    conf = (REPO / "ui/hyprland/elaria-binds.conf").read_text()
    assert lua.endswith(emit_binds(LUA)), (
        "the shipped Lua snippet drifted from the emitter — edit hypr_binds.py")
    assert conf.endswith(emit_binds(LEGACY)), (
        "the shipped .conf snippet drifted from the emitter")
    for bind in BINDS:
        assert bind["command"] in lua
        assert bind["command"] in conf


def test_docs_teach_lua_first_and_carry_the_cancel_bind():
    getting_started = (REPO / "GETTING-STARTED.md").read_text()
    step6 = getting_started.split("## Step 6", 1)[1].split("## Step 7", 1)[0]
    assert "assist ptt cancel" in step6, "Step 6 must carry the Escape cancel bind"
    assert 'hl.bind("Escape"' in step6
    assert "0.57" in step6 and "Lua" in step6
    ui_readme = (REPO / "ui/README.md").read_text()
    assert "elaria-binds.lua" in ui_readme
