"""Stage B — her console (§19.1) and class mode.

Offline, keyless, fixture-backed. The console is tested through the daemon the
QML panel talks to, not through a widget tree we cannot render here.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from assistant.console import ConsoleService, SessionService
from assistant.ipc import call
from assistant.presence import PresenceService
from assistant.store import Store
from assistant.waybar import format_waybar

REPO = Path(__file__).resolve().parents[1]


def make_store(tmp_path, name="console.db"):
    return Store(tmp_path / name)


def test_empty_console_snapshot_is_honest(tmp_path, config):
    store = make_store(tmp_path)
    snapshot = ConsoleService(config, store).snapshot()
    assert snapshot["conversation"] == {"id": None, "started": None, "messages": []}
    assert snapshot["counts"] == {"pending_plans": 0, "parked": 0, "queue": 0,
                                  "holding": 0, "knocks": 0}
    assert snapshot["class_mode"]["enabled"] is False
    store.close()


def test_voice_then_console_is_one_conversation(config, running_daemon):
    """Start by voice, continue in the console: same id, no fork."""
    first = call(config.socket_path, "ask",
                 {"text": "what is on my plate?", "channel": "voice"})
    second = call(config.socket_path, "console.say",
                  {"text": "and what did I ask you to chase?"})

    assert first["conversation_id"] == second["conversation_id"]
    messages = second["conversation"]["messages"]
    assert [m["channel"] for m in messages] == ["voice", "voice", "console", "console"]
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert all(m["text"].strip() for m in messages)

    state = call(config.socket_path, "console.state")
    assert state["conversation"]["id"] == first["conversation_id"]
    assert len(state["conversation"]["messages"]) == 4


def test_session_service_never_forks(tmp_path):
    store = make_store(tmp_path, "fork.db")
    sessions = SessionService(store)
    one = sessions.append("user", "first", channel="voice")
    two = sessions.append("user", "second", channel="console")
    assert one["conversation_id"] == two["conversation_id"]
    assert store.latest_conversation()["id"] == one["conversation_id"]
    assert len(store.conversation_messages(one["conversation_id"])) == 2
    store.close()


def test_class_mode_silences_voice_and_acks_but_console_works(config, running_daemon):
    enabled = call(config.socket_path, "class.set", {"enabled": True})["class_mode"]
    assert enabled["enabled"] is True
    assert enabled["voice_out"] is False
    assert enabled["spoken_acks"] is False
    assert enabled["knock_style"] == "silent-visual"
    assert enabled["initiative"] == "urgent-only"

    voice = call(config.socket_path, "speech.status")["voice"]
    assert voice["muted"] is True
    assert "class mode" in voice["reason"]
    assert voice["ack_cache"]["speaks"] is False

    ack = call(config.socket_path, "ack", {"kind": "on_it", "speak": True})
    assert ack["speech"]["played"] is False
    assert ack["speech"]["audio_path"] is None
    assert ack["speech"]["class_mode"] is True
    assert "class mode" in (ack["speech"]["speak_suppressed"] or "")

    said = call(config.socket_path, "speech.say", {"text": "On it.", "play": False})
    assert said["speech"]["muted"] is True
    assert said["speech"]["audio_path"] is None

    # The console remains fully usable: this is text, not a second voice.
    reply = call(config.socket_path, "console.say", {"text": "still there?"})
    assert reply["reply"].strip()
    assert reply["speech"]["muted"] is True
    state = call(config.socket_path, "console.state")
    assert state["class_mode"]["enabled"] is True
    assert state["conversation"]["messages"][-2]["channel"] == "console"

    status = call(config.socket_path, "status")
    assert status["class_mode"]["enabled"] is True
    assert status["voice"]["muted"] is True

    # And the toggle goes back off, with voice restored.
    call(config.socket_path, "class.toggle")
    assert call(config.socket_path, "speech.status")["voice"]["voice_mode"] != \
        "text-only-class-mode"


def test_class_mode_persists_across_store_reopen(tmp_path, config):
    store = make_store(tmp_path, "persist.db")
    presence = PresenceService(config, store)
    presence.set_enabled(True)
    store.close()
    reopened = make_store(tmp_path, "persist.db")
    assert PresenceService(config, reopened).status().enabled is True
    PresenceService(config, reopened).set_enabled(False)
    reopened.close()


def test_schedule_suggests_but_never_switches_by_itself(tmp_path, config):
    config.raw["presence"] = {
        **config.section("presence"),
        "class_schedule": [{"days": ["mon", "tue", "wed", "thu", "fri"],
                            "start": "08:00", "end": "15:00",
                            "label": "lecture block"}],
    }
    tuesday_10am = datetime(2026, 10, 20, 10, 0)   # Tuesday
    store = make_store(tmp_path, "schedule.db")
    presence = PresenceService(config, store, now=lambda: tuesday_10am)

    status = presence.status()
    assert status.enabled is False
    assert status.suggested is True
    assert "lecture block" in status.suggestion
    assert status.voice_out is True          # a suggestion changes nothing

    outside = presence.status(datetime(2026, 10, 20, 18, 0))
    assert outside.suggested is False

    manual = presence.set_enabled(True)
    assert manual.enabled is True and manual.source.startswith("manual")
    assert manual.voice_out is False and manual.initiative == "urgent-only"
    store.close()


def test_waybar_shows_class_mode_and_suggestion():
    base = {"running": True, "mode": "idle", "gemini_mode": "mock",
            "quota_today_live_calls": 0, "uptime_s": 10, "cloud_queue": {},
            "connectivity_mode": "ONLINE", "connectivity": {"preference": "auto"}}
    on = format_waybar({**base, "class_mode": {"enabled": True, "suggested": False}})
    assert "class-mode" in on["class"]
    assert "·class" in on["text"]
    assert any("class mode" in line for line in on["tooltip"].splitlines())

    suggested = format_waybar({
        **base, "class_mode": {"enabled": False, "suggested": True,
                               "suggestion": "Class hours (lecture) — toggle me"}})
    assert "class-suggested" in suggested["class"]
    assert not suggested["text"].endswith("·class")
    assert any("class suggestion" in line for line in suggested["tooltip"].splitlines())


def test_console_snapshot_carries_the_whole_room(tmp_path, config):
    store = make_store(tmp_path, "room.db")
    from assistant.cost import iso_now

    plan_id = store.create_plan(iso_now(), "/tmp/root", "shadow")
    store.finish_plan(plan_id, total=10, placed=7, abstained=1,
                      shadow_log_path=None, stats_json="{}")
    store.add_plan_items(plan_id, [
        {"src": "/tmp/root/a.pdf", "dest": "Finance", "confidence": 0.71,
         "tier": 0, "rule": "keyword", "reason": "invoice", "decision": "review"},
        {"src": "/tmp/root/b.pdf", "dest": "_Unsorted", "confidence": 0.2,
         "tier": 0, "rule": "none", "reason": "unknown", "decision": "unsorted"},
    ])
    store.enqueue_cloud_job(ts=iso_now(), kind="transcript_cleanup",
                            payload_json="{}")
    holding_id = store.add_holding(ts=iso_now(), kind="follow-up",
                                   title="Chase the March invoice",
                                   detail="you asked me to chase it",
                                   source="user-request", ref="commitment:1")

    snapshot = ConsoleService(config, store).snapshot()
    assert snapshot["counts"]["pending_plans"] == 1          # ready, not applied
    assert snapshot["counts"]["parked"] == 2
    assert snapshot["counts"]["queue"] == 1
    assert snapshot["counts"]["holding"] == 1
    assert snapshot["holding"][0]["id"] == holding_id
    assert snapshot["pending_plans"][0]["placed"] == 7
    assert any(item["decision"] == "review" for item in snapshot["parked_items"])
    assert snapshot["offline_queue"]["counts"] == {"pending": 1}
    store.close()


def test_assist_status_and_console_cli_without_the_daemon(tmp_path, config):
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"),
           "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
           "XDG_DATA_HOME": str(tmp_path / "data"),
           "XDG_STATE_HOME": str(tmp_path / "state"),
           "XDG_RUNTIME_DIR": str(tmp_path / "run"),
           "GEMINI_MODE": "mock"}
    for path in ("cfg", "data", "state", "run"):
        (tmp_path / path).mkdir(parents=True, exist_ok=True)
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_API_KEY", None)

    class_run = subprocess.run([sys.executable, "-m", "assistant.cli", "class", "on"],
                               capture_output=True, text=True, env=env, timeout=30, check=False)
    assert class_run.returncode == 0, class_run.stdout + class_run.stderr
    assert "Class mode: ON" in class_run.stdout

    status = subprocess.run([sys.executable, "-m", "assistant.cli", "class", "status"],
                            capture_output=True, text=True, env=env, timeout=30, check=False)
    assert status.returncode == 0
    assert json.loads(status.stdout)["class_mode"]["enabled"] is True

    console = subprocess.run([sys.executable, "-m", "assistant.cli", "console", "--json"],
                             capture_output=True, text=True, env=env, timeout=30, check=False)
    assert console.returncode == 0, console.stderr
    snapshot = json.loads(console.stdout)
    assert snapshot["class_mode"]["enabled"] is True
    assert snapshot["daemon"]["running"] is False


def test_quickshell_console_is_a_dumb_renderer_on_the_shared_feed():
    qml = (REPO / "ui" / "quickshell" / "console" / "shell.qml").read_text()
    assert '"assist", "console", "--follow"' in qml
    assert '"assist", "talk", text' in qml
    assert "console.say" not in qml              # talks to the CLI, not a second store
    assert "WlrKeyboardFocus.OnDemand" in qml    # focus only when clicked
    assert "class_mode.enabled" in qml
    assert "knocks" in qml and "holding" in qml
    unit = (REPO / "systemd" / "elaria-console.service").read_text()
    assert "ui/quickshell/console" in unit


def test_assist_talk_cli_continues_the_same_conversation(config, running_daemon):
    """`assist talk` is CLI parity: the same daemon handler, the same store."""
    first = call(config.socket_path, "ask",
                 {"text": "start by voice", "channel": "voice"})
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    out = subprocess.run([sys.executable, "-m", "assistant.cli", "talk",
                          "continue in the console"],
                         capture_output=True, text=True, env=env, timeout=60, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.strip()

    state = call(config.socket_path, "console.state")
    assert state["conversation"]["id"] == first["conversation_id"]
    assert [m["channel"] for m in state["conversation"]["messages"]] == [
        "voice", "voice", "console", "console"]


def test_assist_console_json_matches_the_panel_feed(config, running_daemon):
    call(config.socket_path, "console.say", {"text": "hello console"})
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    out = subprocess.run([sys.executable, "-m", "assistant.cli", "console", "--json"],
                         capture_output=True, text=True, env=env, timeout=30, check=False)
    assert out.returncode == 0, out.stderr
    snapshot = json.loads(out.stdout)
    assert snapshot["conversation"]["id"] is not None
    assert "class_mode" in snapshot and "knocks" in snapshot
