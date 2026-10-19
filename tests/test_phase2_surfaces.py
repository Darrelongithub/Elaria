"""Phase 2 surfaces (§3.9): Waybar formatter, overlay reducer, feed
contracts, and static Wayland safety guards on the QML/binds. The QML
itself can't execute headless — so the *logic* is tested here in the
Python reducer it renders, and the QML is guarded for the properties
that would make it dangerous (keyboard focus, layer)."""

import json
import re
from pathlib import Path

from assistant.overlay import OverlayReducer, OverlayState
from assistant.waybar import format_waybar

REPO = Path(__file__).resolve().parents[1]


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


# -- Waybar formatter -------------------------------------------------------------
def test_waybar_down_shape():
    out = format_waybar({"running": False})
    assert out["class"] == "down" and "down" in out["text"]


def test_waybar_states_and_mock_glyph():
    base = {"running": True, "gemini_mode": "mock", "uptime_s": 61,
            "quota_today_live_calls": 3, "halted": False,
            "last_transcript": {"snippet": "file the invoice", "ts": "t", "backend": "x"}}
    listening = format_waybar({**base, "mode": "listening"})
    assert "listening" in listening["class"] and "mock" in listening["class"]
    assert listening["text"].startswith("●")
    assert "file the invoice" in listening["tooltip"]
    transcribing = format_waybar({**base, "mode": "transcribing", "gemini_mode": "live"})
    assert transcribing["class"] == ["transcribing"]
    assert transcribing["text"].startswith("◐")
    halted = format_waybar({**base, "mode": "idle", "halted": True})
    assert halted["class"][0] == "halted" and halted["alt"] == "halted"


def test_waybar_json_is_single_line_serializable():
    out = format_waybar({"running": True, "mode": "idle", "gemini_mode": "live"})
    assert json.loads(json.dumps(out))["alt"] == "idle"


# -- Overlay reducer ---------------------------------------------------------------
def test_overlay_listening_to_final_linger_to_hide():
    clock = FakeClock()
    reducer = OverlayReducer(now=clock)
    state = reducer.apply({"event": "session.started"})
    assert state.visible and state.kind == "listening" and state.pulsing
    state = reducer.apply({"event": "transcript.interim", "text": "partial words"})
    assert state.text == "partial words"
    state = reducer.apply({"event": "transcript.final", "text": "final words."})
    assert state.kind == "final" and not state.pulsing
    reducer.apply({"event": "session.ended"})
    clock.advance(3.9)
    assert reducer.tick().visible  # still lingering, readable
    clock.advance(0.2)
    assert reducer.tick() == OverlayState()  # hidden


def test_overlay_checkin_is_its_own_quiet_state():
    reducer = OverlayReducer(now=FakeClock())
    reducer.apply({"event": "session.started"})
    state = reducer.apply({"event": "session.checkin", "prompt": "Is that all?"})
    assert state.kind == "checkin" and state.text == "Is that all?"


def test_overlay_error_lingers_longer_than_final():
    clock = FakeClock()
    reducer = OverlayReducer(now=clock)
    state = reducer.apply({"event": "error", "error": "live session died"})
    assert state.kind == "error"
    clock.advance(5.0)  # beyond final linger, inside error linger
    assert reducer.tick().visible
    clock.advance(3.1)
    assert not reducer.tick().visible


def test_overlay_ignores_unknown_events():
    reducer = OverlayReducer(now=FakeClock())
    reducer.apply({"event": "session.started"})
    before = reducer.state
    assert reducer.apply({"event": "plan.proposed", "ops": 9}) == before
    assert reducer.apply({"event": "status.changed", "mode": "idle"}) == before


def test_overlay_state_json_contract():
    payload = OverlayState(True, "listening", "hi", True).to_json()
    # The exact keys shell.qml binds — changing them breaks the renderer.
    assert set(payload) == {"visible", "kind", "text", "pulsing", "class"}


# -- Daemon integration: status fields + streams ------------------------------------
def test_daemon_status_feeds_waybar(config, running_daemon):
    from assistant.ipc import call

    status = call(config.socket_path, "status")
    for field in ("dictation_active", "capture", "last_transcript",
                  "quota_today_live_calls", "event_subscribers"):
        assert field in status
    rendered = format_waybar(status)
    assert rendered["alt"] == "idle"


def test_overlay_stream_over_real_daemon(config, running_daemon):
    import threading
    import time

    from assistant.ipc import call
    from assistant.overlay import stream_overlay_states

    states: list[dict] = []

    def consume():
        for state in stream_overlay_states(config.socket_path):
            states.append(state)
            if len(states) > 40:
                return

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    time.sleep(0.3)
    call(config.socket_path, "ptt.start", {"source": "simulated"})
    time.sleep(0.4)
    call(config.socket_path, "ptt.stop", timeout=30.0)
    time.sleep(0.5)
    kinds = [s["kind"] for s in states]
    assert "listening" in kinds and "final" in kinds


def test_waybar_follow_reacts_to_status_changed(config, running_daemon):
    import threading
    import time

    from assistant.ipc import call
    from assistant.waybar import stream_waybar

    lines: list[dict] = []

    def consume():
        for line in stream_waybar(config.socket_path, interval_s=30):
            lines.append(line)
            if len(lines) > 12:
                return

    threading.Thread(target=consume, daemon=True).start()
    time.sleep(0.3)
    call(config.socket_path, "ptt.start", {"source": "simulated"})
    time.sleep(0.5)
    call(config.socket_path, "ptt.stop", timeout=30.0)
    time.sleep(0.5)
    alts = [line.get("alt") for line in lines]
    assert "listening" in alts  # event-driven: no 30s poll could produce this


# -- Static guards on the shipped surface files ---------------------------------------
def test_qml_cannot_steal_keyboard_focus():
    qml = (REPO / "ui/quickshell/shell.qml").read_text()
    assert "WlrKeyboardFocus.None" in qml          # the §3.3 non-negotiable
    assert "WlrLayer.Overlay" in qml
    assert 'namespace: "elaria-overlay"' in qml
    assert not re.search(r"keyboardFocus:\s*WlrKeyboardFocus\.(Exclusive|OnDemand)", qml)
    assert '"assist", "events", "--overlay"' in qml  # consumes the tested feed


def test_qml_binds_exactly_the_reducer_contract():
    qml = (REPO / "ui/quickshell/shell.qml").read_text()
    for key in ("state.visible", "state.kind", "state.text", "state.pulsing"):
        assert key in qml


def test_waybar_module_is_valid_json_and_uses_follow():
    module = json.loads((REPO / "ui/waybar/module.json").read_text())
    elaria = module["custom/elaria"]
    assert elaria["exec"] == "assist status --waybar --follow"
    assert elaria["on-click"] == "assist ptt toggle"
    assert elaria["on-click-right"] == "assist halt"  # panic within reach (§4.4)
    assert "custom/elaria-voicetest" in module       # the §13.10 LED


def test_waybar_css_covers_every_emitted_class():
    css = (REPO / "ui/waybar/style.css").read_text()
    for cls in ("listening", "transcribing", "halted", "down", "mock",
                "voice-test-lit", "voice-test-idle"):
        assert f".{cls}" in css


def test_hyprland_binds_both_syntaxes_press_and_release():
    lua = (REPO / "ui/hyprland/elaria-binds.lua").read_text()
    conf = (REPO / "ui/hyprland/elaria-binds.conf").read_text()
    assert "assist ptt start" in lua and "release = true" in lua
    assert "bindr" in conf and "assist ptt stop" in conf
    assert "assist halt" in lua and "assist halt" in conf


def test_overlay_systemd_unit_is_graphical_session_scoped():
    unit = (REPO / "systemd/elaria-overlay.service").read_text()
    assert "quickshell" in unit and "graphical-session.target" in unit
