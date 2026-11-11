"""Scene-3b-REDO (owner order 2026-10-26): streams D + E, gate-blocking.

STREAM D — release trigger (WP3-binds pull-forward):
  * `bindri` (release + ignore_mods) is the order-robust release bind; the
    ladder must read the ignore_mods truth from the dump OR the config
    text — 0.56.2's `hyprctl -j binds` omits the field (HyprCtl.cpp binds
    serializer) while the legacy parser honours the `i` flag letter
    (legacy/ConfigManager.cpp handleBind: `case 'i': ignoreMods = true`).
  * A double-fired stop (Win-first release fires both release binds) is a
    clean idempotent no-op WITH its own schema line (`stop.noop`).

STREAM E — final flush ("the last code wall before her voice"):
  * schema events `final.wait` (always at flush), `final.received`,
    `final.timeout` naming the dead collector honestly.
  * a clean stop with real text completes the turn: reply invocation →
    (quota user-turn on the live path) → spoken reply — in EVERY session
    mode, with the silence-hotfix rules untouched.
  * session.close detail reports honest text_chars + transcript state,
    never the length of the fallback narration (the "67 chars" lie).
"""

from __future__ import annotations

import asyncio
import json

from assistant import asr
from assistant.capture import SAMPLE_RATE, SimulatedCapture
from assistant.config import DEFAULTS, load_config
from assistant.daemon import Daemon
from assistant.ladder import Ladder
from assistant.live_client import LiveEvent, ScriptedLiveTransport
from assistant.store import Store
from assistant.transcribe import DictationService

REPO_BIND_FLAGS = {"l", "r", "e", "m", "n", "a", "t", "i", "s", "o",
                   "d", "p", "c", "g", "u", "k", "x"}


# ---------------------------------------------------------------- helpers
def _events_named(journal_stream, name: str) -> list[str]:
    return [ln for ln in journal_stream.getvalue().splitlines()
            if ln.split(" ", 6)[2] == name]


class _FakeRunner:
    """The subprocess.run shape the Ladder runner contract expects."""

    def __init__(self, binds_json: str | None, binds_error: str = ""):
        self.binds_json = binds_json
        self.binds_error = binds_error

    def __call__(self, argv, capture_output=True, text=True, timeout=10):
        import subprocess
        joined = " ".join(argv)
        if "binds" in joined:
            if self.binds_json is None:
                return subprocess.CompletedProcess(
                    argv, 1, "", self.binds_error or "hyprctl: cannot open socket")
            return subprocess.CompletedProcess(argv, 0, self.binds_json, "")
        return subprocess.CompletedProcess(argv, 1, "", "not stubbed")


def _ladder_for(config, binds_json: str | None, conf_text: str,
                tmp_path) -> Ladder:
    conf = tmp_path / "hyprland.conf"
    conf.write_text(conf_text, encoding="utf-8")
    return Ladder(config,
                  runner=_FakeRunner(binds_json),
                  which=lambda name: f"/usr/bin/{name}",
                  hypr_config=conf,
                  status=lambda: {
                      "dictation_active": False, "ptt_session_id": None,
                      "session_holders": [], "hotword": {"armed": False},
                      "session_ceiling_s": 300.0, "gemini_mode": "mock",
                      "voice": {"voice_mode": "gemini-interim",
                                "cached_acks": ["on_it"],
                                "voice_identity": {"allowed": True},
                                "reason": "ok"},
                  })


# The owner's real 0.56.2 dump shape (2026-10-26, hyprctl -j binds):
# exactly the serializer's fields — NO `ignore_mods` key exists there.
DUMP_0562 = json.dumps([
    {"locked": False, "mouse": False, "release": False, "repeat": False,
     "longPress": False, "non_consuming": False, "auto_consuming": False,
     "has_description": False, "modmask": 64, "submap": "",
     "submap_universal": False, "key": "F2", "keycode": 0,
     "catch_all": False, "description": "",
     "allow_input_capture": False,
     "dispatcher": "exec", "arg": "assist ptt start"},
    {"locked": False, "mouse": False, "release": True, "repeat": False,
     "longPress": False, "non_consuming": False, "auto_consuming": False,
     "has_description": False, "modmask": 0, "submap": "",
     "submap_universal": False, "key": "F2", "keycode": 0,
     "catch_all": False, "description": "",
     "allow_input_capture": False,
     "dispatcher": "exec", "arg": "assist ptt stop --stop-source bind"},
    {"locked": False, "mouse": False, "release": False, "repeat": False,
     "longPress": False, "non_consuming": False, "auto_consuming": False,
     "has_description": False, "modmask": 65, "submap": "",
     "submap_universal": False, "key": "F12", "keycode": 0,
     "catch_all": False, "description": "",
     "allow_input_capture": False,
     "dispatcher": "exec", "arg": "assist halt"},
])

# A future-compositor dump that DOES expose the field.
DUMP_WITH_IGNORE = json.dumps([
    {"modmask": 64, "key": "F2", "release": False, "ignore_mods": False,
     "locked": False, "mouse": False, "repeat": False, "longPress": False,
     "non_consuming": False, "auto_consuming": False,
     "has_description": False, "submap": "", "submap_universal": False,
     "keycode": 0, "catch_all": False, "description": "",
     "allow_input_capture": False,
     "dispatcher": "exec", "arg": "assist ptt start"},
    {"modmask": 0, "key": "F2", "release": True, "ignore_mods": True,
     "locked": False, "mouse": False, "repeat": False, "longPress": False,
     "non_consuming": False, "auto_consuming": False,
     "has_description": False, "submap": "", "submap_universal": False,
     "keycode": 0, "catch_all": False, "description": "",
     "allow_input_capture": False,
     "dispatcher": "exec", "arg": "assist ptt stop --stop-source bind"},
])

CONF_BASE = """\
$mainMod = SUPER
bind = $mainMod, F2, exec, assist ptt start
bind = $mainMod SHIFT, F12, exec, assist halt
"""


def _f2_evidence(ladder: Ladder) -> str:
    entries, why = ladder._bind_entries()
    press, release = Ladder._bare_f2(entries)
    return ladder._bare_f2_evidence(press, release, why, entries)


# ============================================================== STREAM D.4
# Ladder: flag-combined keywords + ignore_mods truth from dump OR config.

def test_bindri_conf_line_reads_ignore_mods_from_config_text(config, tmp_path):
    """The owner's appended `bindri = , F2` line is the WP3 form: the
    evidence names it and never WARNs legacy for it (scene 4 reads the
    config truth when the dump omits the field)."""
    ladder = _ladder_for(
        config, DUMP_0562,
        CONF_BASE + "bindri = , F2, exec, assist ptt stop --stop-source bind\n",
        tmp_path)
    text = _f2_evidence(ladder)
    assert "bare-F2 press bind=absent" in text          # pinned substring
    assert "ignore_mods present (bindri flag" in text
    assert "WARN legacy release-stop bind" not in text


def test_legacy_bindr_alone_keeps_the_pinned_warn(config, tmp_path):
    """A bare legacy `bindr = , F2` release (scene-1 ruling) still WARNs
    legacy-tolerated until replaced — the pinned substring stands."""
    ladder = _ladder_for(
        config, DUMP_0562,
        CONF_BASE + "bindr = , F2, exec, assist ptt stop --stop-source bind\n",
        tmp_path)
    text = _f2_evidence(ladder)
    assert "bare-F2 press bind=absent" in text
    assert "WARN legacy release-stop bind (WP3 replaces)" in text
    assert "ignore_mods present" not in text


def test_both_release_forms_are_named_together(config, tmp_path):
    """The owner's post-append state keeps line 213 (`bindr`) AND gains
    `bindri` — both facts are reported, WARN and WP3 form together."""
    ladder = _ladder_for(
        config, DUMP_0562,
        CONF_BASE
        + "bindr = , F2, exec, assist ptt stop --stop-source bind\n"
        + "bindri = , F2, exec, assist ptt stop --stop-source bind\n",
        tmp_path)
    text = _f2_evidence(ladder)
    assert "WARN legacy release-stop bind (WP3 replaces)" in text
    assert "ignore_mods present (bindri flag" in text


def test_dump_ignore_mods_field_is_authority_when_exposed(config, tmp_path):
    """When the JSON exposes `ignore_mods` (future compositor), the dump is
    authority — no config text needed."""
    ladder = _ladder_for(config, DUMP_WITH_IGNORE, CONF_BASE, tmp_path)
    entries, _why = ladder._bind_entries()
    release = next(e for e in entries if e.key == "f2" and e.release)
    assert release.ignore_mods is True
    text = _f2_evidence(ladder)
    assert "ignore_mods present (bindri flag" in text
    assert "WARN legacy" not in text

    legacy_dump = DUMP_WITH_IGNORE.replace(
        '"ignore_mods": true', '"ignore_mods": false')
    ladder2 = _ladder_for(config, legacy_dump, CONF_BASE, tmp_path)
    text2 = _f2_evidence(ladder2)
    assert "WARN legacy release-stop bind (WP3 replaces)" in text2
    assert "ignore_mods present" not in text2


def test_config_text_is_truth_when_hyprctl_is_unavailable(config, tmp_path):
    """Scene 4 reads the truth from the dump OR the config either way: with
    no readable dump the conf lines still teach the rungs — flag letters,
    variable expansion, bare-F2 detection included."""
    ladder = _ladder_for(
        config, None,
        CONF_BASE + "bindri = , F2, exec, assist ptt stop --stop-source bind\n",
        tmp_path)
    entries, why = ladder._bind_entries()
    assert entries and "from config text" in why
    tokens = [e.token for e in entries]
    assert Ladder._bind_matches(tokens, "SUPER", "F2")          # $mainMod expanded
    assert Ladder._bind_matches(tokens, "SUPER", "SHIFT", "F12")
    press, release = Ladder._bare_f2(entries)
    assert press is False and release is True
    text = ladder._bare_f2_evidence(press, release, why, entries)
    assert "bare-F2 press bind=absent" in text
    assert "ignore_mods present (bindri flag" in text


def test_conf_flag_letters_cover_the_verified_parser_table():
    """The teaching table is the v0.56.2 parser table — every letter the
    source switch knows is mapped, and the release-implicits ('c', 'g')
    are release flags exactly as handleBind treats them."""
    from assistant.ladder import _BIND_FLAGS, _RELEASE_IMPLYING_FLAGS
    assert set(_BIND_FLAGS) == REPO_BIND_FLAGS
    assert _RELEASE_IMPLYING_FLAGS == frozenset("rcg")
    assert _BIND_FLAGS["i"] == "ignore_mods"
    assert _BIND_FLAGS["r"] == "release"


# ============================================================== STREAM D.2
# Double-stop idempotency: clean no-op + its own schema line.

class _HoldOpenCapture(SimulatedCapture):
    def __init__(self, target=None, frame_ms=30, stall_timeout_s=None, **kwargs):
        super().__init__(speech_frames=100_000, frame_ms=frame_ms,
                         realtime=True)


class _QuietCapture(SimulatedCapture):
    def __init__(self, target=None, frame_ms=30, stall_timeout_s=None, **kwargs):
        super().__init__(speech_frames=0, frame_ms=frame_ms, realtime=False)


class _SpeechCapture(SimulatedCapture):
    def __init__(self, target=None, frame_ms=30, stall_timeout_s=None, **kwargs):
        super().__init__(speech_frames=30, frame_ms=frame_ms, realtime=False)


def test_cold_stop_is_a_noop_with_its_own_schema_line(config, journal_stream):
    daemon = Daemon(config)
    try:
        response = asyncio.run(daemon._ptt_stop({"wait_s": 0}))
        assert response["listening"] is False
        assert response["noop"] is True
        assert response["result"] is None
        lines = _events_named(journal_stream, "stop.noop")
        assert lines, journal_stream.getvalue()
        assert "no-active-session" in lines[0]
        assert "idempotent no-op" in lines[0]
        # its own entry line too — a stop is never invisible
        assert _events_named(journal_stream, "stop.requested")
    finally:
        daemon.store.close()


def test_double_stop_is_a_clean_noop_and_finishes_once(
        config, journal_stream, monkeypatch):
    """Win-first release fires BOTH release binds (bindr + bindri match):
    the second stop must be a clean idempotent no-op — no error, no second
    finisher, its own stop.noop schema line."""
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _HoldOpenCapture)
    daemon = Daemon(config)
    try:
        async def drive():
            assert (await daemon._ptt_start({}))["listening"] is True
            sid = daemon._ptt_session_id
            first = await daemon._ptt_stop(
                {"wait_s": 0, "stop_source": "bind"})
            second = await daemon._ptt_stop(
                {"wait_s": 0, "stop_source": "bind"})
            answer = await daemon._ptt_wait_for(sid, 20.0)
            return first, second, answer

        first, second, answer = asyncio.run(drive())
        assert first["noop"] is False
        assert second["noop"] is True
        assert second["result"] is None
        assert second["listening"] is False
        # one finisher, one terminal answer — the double-fire corrupted nothing
        assert answer is not None
        noop = _events_named(journal_stream, "stop.noop")
        assert noop, journal_stream.getvalue()
        assert any("finish-in-flight" in ln or
                   "already-closed" in ln or
                   "no-active-session" in ln for ln in noop)
        requested = _events_named(journal_stream, "stop.requested")
        assert len(requested) == 2, requested
    finally:
        daemon.store.close()


# ============================================================== STREAM E.2
# Schema events: final.wait (always at flush) / final.received / final.timeout.

class _SpeechSource:
    """The AsyncFrameSource shape: loud frames then end-of-stream."""

    def __init__(self, frames):
        self._frames = frames
        self.closed = False

    async def frames(self):
        for frame in self._frames:
            yield frame

    async def aclose(self):
        self.closed = True


def _loud(n: int) -> list[bytes]:
    frame_samples = SAMPLE_RATE * 30 // 1000
    import struct
    return [struct.pack(f"<{frame_samples}h", *([6000] * frame_samples))
            for _ in range(n)]


def _service(tmp_path, **transcribe_overrides):
    config = load_config()
    config.raw["cleanup"] = {**config.raw.get("cleanup", {}), "enabled": False}
    config.raw["transcribe"] = {
        **config.raw.get("transcribe", {}),
        "inbox_dir": str(tmp_path / "inbox"),
        "final_wait_s": 0.5,
        **transcribe_overrides,
    }
    store = Store(tmp_path / "scene3b.db")
    return config, store, DictationService(config, store, None)


def test_final_wait_and_final_received_at_a_clean_flush(
        tmp_path, journal_stream):
    _config, store, service = _service(tmp_path)
    events = []

    async def sink(event):
        events.append(event)

    result = asyncio.run(service.dictate(
        _SpeechSource(_loud(20)),
        transport_factory=ScriptedLiveTransport,
        sink=sink, mode="narration"))
    assert "mock transcript" in (result.raw_text or "")
    wait = _events_named(journal_stream, "final.wait")
    received = _events_named(journal_stream, "final.received")
    timed_out = _events_named(journal_stream, "final.timeout")
    assert wait, journal_stream.getvalue()
    assert "budget_s=0.5" in wait[0]
    assert "collector=" in wait[0]
    assert received and "text_chars=" in received[0]
    assert not timed_out, timed_out
    store.close()


class _SeveredTransport(ScriptedLiveTransport):
    """The sever geometry the reply regression died behind: the live link
    died mid-utterance — no final ever comes and the collector is already
    finished when the flush runs."""

    async def events(self):
        return
        yield  # pragma: no cover - async generator shape only

    async def activity_end(self) -> None:
        return None


def test_final_timeout_names_the_dead_collector_honestly(
        tmp_path, journal_stream, monkeypatch):
    """Speech, then a severed link: the journal must SAY so from text
    alone — collector state, waited budget, and the deferred decision."""

    def _no_fallback(*args, **kwargs):
        return None

    monkeypatch.setattr(asr, "transcribe_file", _no_fallback)
    _config, store, service = _service(tmp_path)
    events = []

    async def sink(event):
        events.append(event)

    result = asyncio.run(service.dictate(
        _SpeechSource(_loud(20)),
        transport_factory=_SeveredTransport,
        sink=sink, mode="narration"))
    assert result.no_final is True
    wait = _events_named(journal_stream, "final.wait")
    timed_out = _events_named(journal_stream, "final.timeout")
    received = _events_named(journal_stream, "final.received")
    assert wait, journal_stream.getvalue()
    assert timed_out, journal_stream.getvalue()
    detail = timed_out[0]
    assert "waited_s=" in detail
    assert "collector=done" in detail, detail   # the dead collector, named
    assert "collector ended with no final" in detail
    assert not received, received
    # the deferred decision is still logged downstream (§6.8 contract)
    deferred = _events_named(journal_stream, "transcription.deferred")
    assert deferred, journal_stream.getvalue()
    store.close()


def test_final_wait_budget_is_configurable_not_a_magic_constant():
    config = load_config()
    assert config.section("transcribe").get("final_wait_s") == 12.0
    assert DEFAULTS["transcribe"]["final_wait_s"] == 12.0


# ============================================================== STREAM E.3
# The reply completes every real-text voice turn (silence rules untouched).

class _OneWordTransport(ScriptedLiveTransport):
    """The proven `Four.` case: one real word over healthy audio."""

    async def activity_end(self) -> None:
        await self._queue.put(LiveEvent("final", text="Four."))
        await self._queue.put(LiveEvent("turn_complete"))


def _daemon_turn(config, journal_stream, monkeypatch, mode: str):
    """One real-text voice turn through the real daemon + real flush."""
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _SpeechCapture)
    monkeypatch.setattr(asr, "make_live_transport",
                        lambda cfg, **kw: _OneWordTransport())
    daemon = Daemon(config)
    asked = []

    async def _spy(params):
        asked.append(dict(params))
        return {"reply": "Six.", "via": "test"}

    monkeypatch.setattr(daemon, "_ask", _spy)
    try:
        async def drive():
            assert (await daemon._ptt_start({"mode": mode}))["listening"] is True
            # let the capture actually deliver frames before the release
            await asyncio.sleep(0.4)
            return await daemon._ptt_stop(
                {"wait_s": 30.0, "speak": True, "stop_source": "bind"})

        response = asyncio.run(drive())
        return response, asked
    finally:
        daemon.store.close()


def test_conversation_turn_replies_and_close_detail_is_honest(
        config, journal_stream, monkeypatch):
    response, asked = _daemon_turn(
        config, journal_stream, monkeypatch, "conversation")
    result = response.get("result") or {}
    assert (result.get("text") or "").strip() == "Four."
    assert len(asked) == 1, "a real-text conversation turn lost its reply"
    assert asked[0]["text"] == "Four."
    assert asked[0]["speak"] is True
    assert "unparsed_command" not in asked[0]
    # the reply is the narration in conversation mode
    assert result.get("narration") == "Six."
    invocation = _events_named(journal_stream, "reply.invocation")
    assert invocation, journal_stream.getvalue()
    assert "mode=conversation" in invocation[0]
    assert "text_chars=5" in invocation[0]
    close = _events_named(journal_stream, "session.close")
    assert close, journal_stream.getvalue()
    assert "text_chars=5 (final)" in close[0]
    assert "67 chars" not in close[0]


def test_narration_turn_replies_but_keeps_the_factual_narration(
        config, journal_stream, monkeypatch):
    """The dictation pillar still reports the fact as its narration line;
    her spoken answer rides in the reply — the natural Win+F2 cycle ends
    in her voice either way."""
    response, asked = _daemon_turn(
        config, journal_stream, monkeypatch, "narration")
    result = response.get("result") or {}
    assert len(asked) == 1
    assert "unparsed_command" not in asked[0]
    assert "Transcript saved" in (result.get("narration") or "")
    assert (result.get("command") or {}).get("reply") == "Six."
    invocation = _events_named(journal_stream, "reply.invocation")
    assert invocation and "mode=narration" in invocation[0]
    close = _events_named(journal_stream, "session.close")
    assert close and "text_chars=5 (final)" in close[0]


def test_silence_still_never_reaches_the_reply_path(
        config, journal_stream, monkeypatch):
    """SILENCE HOTFIX rule 4 preserved: a no-speech session answers with
    nothing — no reply invocation, no _ask, honest close detail."""
    monkeypatch.setattr("assistant.daemon.PipeWireCapture", _QuietCapture)
    daemon = Daemon(config)
    asked = []

    async def _spy(params):
        asked.append(dict(params))
        return {"reply": "must never be reached", "via": "test"}

    monkeypatch.setattr(daemon, "_ask", _spy)
    try:
        async def drive():
            assert (await daemon._ptt_start({"mode": "command"}))["listening"]
            return await daemon._ptt_stop(
                {"wait_s": 30.0, "speak": True, "stop_source": "bind"})

        response = asyncio.run(drive())
        result = response.get("result") or {}
        assert result.get("no_speech") is True
        assert not asked
        assert not _events_named(journal_stream, "reply.invocation")
        close = _events_named(journal_stream, "session.close")
        assert close and "text_chars=0 (no_speech)" in close[0]
    finally:
        daemon.store.close()
