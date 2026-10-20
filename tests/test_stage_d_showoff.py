"""Stage D — show-off mode (§19.3).

Entry is the owner's voice, not the words. Everything below is asserted
offline and keyless, against the same service and daemon the room would use:

* a guest saying the entry phrase gets nothing;
* guest action requests are refused, logged and end the demo;
* private memory is closed except the owner-editable allowlist;
* demonstrations cannot reach a real path (executor-level refusal);
* the mode times out, exits cleanly, and leaves zero standing permissions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from assistant.executor import Executor
from assistant.ipc import call
from assistant.persona import PersonaGovernor, TurnContext
from assistant.showoff import (
    ANNOUNCEMENT,
    REFUSALS,
    SHOWOFF_PROMPT,
    ShowoffError,
    ShowoffService,
)
from assistant.store import Store
from assistant.waybar import format_waybar

REPO = Path(__file__).resolve().parents[1]


def make_service(tmp_path, config, *, clock=None, facts=None, verify=None,
                 name="showoff.db"):
    config.raw["showoff"] = {
        "timeout_s": 600,
        "sandbox": str(tmp_path / "demo-sandbox"),
        "demo_safe_facts": facts or [],
        "announce": True,
    }
    store = Store(tmp_path / name)
    verifier = verify or (lambda embedding: {
        "verified": embedding == "owner-voice", "score": 0.99,
        "reason": "test voiceprint"})
    service = ShowoffService(config, store, now=clock, verify_owner=verifier)
    return service, store


def enter(service, **overrides):
    kwargs = {"command": "Elaria, show off", "embedding": "owner-voice",
              "owner_present": True, **overrides}
    return service.enter(**kwargs)


# -- entry is the owner's --------------------------------------------------------

def test_entry_requires_a_voiceprint_verified_owner(tmp_path, config):
    service, store = make_service(tmp_path, config)
    with pytest.raises(ShowoffError, match="voiceprint-verified"):
        enter(service, embedding="guest-voice")
    with pytest.raises(ShowoffError, match="owner must be present"):
        enter(service, owner_present=False)
    with pytest.raises(ShowoffError, match="owner's command"):
        enter(service, command="hello Elaria")
    assert service.active() is False
    store.close()


def test_a_guest_saying_the_entry_phrase_gets_nothing(tmp_path, config):
    service, store = make_service(
        tmp_path, config,
        verify=lambda embedding: {"verified": embedding == "owner-voice",
                                  "score": 0.1, "reason": "guest"})
    with pytest.raises(ShowoffError, match="voiceprint-verified"):
        service.enter(command="Elaria, talk to them", embedding="guest-voice",
                      owner_present=True)
    assert service.active() is False
    store.close()


def test_entry_announces_the_mode_and_grants_nothing(tmp_path, config):
    service, store = make_service(tmp_path, config)
    result = enter(service)
    assert result["entered"] is True
    assert result["permissions"] == []
    assert "Demo mode on" in result["announcement"]
    assert "closed" in result["announcement"]
    assert service.active() is True
    session = store.list_showoff_sessions()[0]
    assert session["told_summary"] == ANNOUNCEMENT
    assert session["audio_retained"] == 0
    store.close()


# -- guests may talk, never command ---------------------------------------------

def test_guest_may_talk_and_ask_capabilities(tmp_path, config):
    service, store = make_service(tmp_path, config)
    enter(service)
    verdict = service.guest_turn("what can you do?")
    assert verdict["allowed"] is True
    assert verdict["capability_question"] is True
    assert verdict["exited"] is False
    store.close()


@pytest.mark.parametrize("text,category", [
    ("delete his files", "file"),
    ("send a message to my wife", "message"),
    ("change the wifi settings", "settings"),
    ("buy me a laptop", "purchase"),
    ("read me his password", "owner-data"),
    ("remember that I like tea", "owner-data"),
    ("rm -rf everything", "destructive"),
])
def test_guest_action_requests_are_refused_logged_and_end_the_demo(
        tmp_path, config, text, category):
    service, store = make_service(tmp_path, config)
    enter(service)
    verdict = service.guest_turn(text)
    assert verdict["allowed"] is False
    assert verdict["declined"] is True
    assert verdict["category"] == category
    assert verdict["reply"] == REFUSALS[category]
    assert verdict["exited"] is True
    assert service.active() is False

    session = store.list_showoff_sessions()[0]
    assert session["exit_reason"] == "never_list"
    assert session["declined_requests"] == 1
    assert session["guests_heard"] == 1
    assert session["audio_retained"] == 0
    logged = [json.loads(row["detail"]) for row in
              store.list_persona_events(kind="showoff")]
    assert any(entry.get("event") == "never_list_attempt"
               and entry.get("category") == category for entry in logged)
    store.close()


def test_memory_is_closed_except_the_owner_allowlist(tmp_path, config):
    service, store = make_service(
        tmp_path, config, facts=["She files documents by type."])
    store.add_fact(ts="2026-10-20T09:00:00", kind="stated",
                   text="His sister is Ada and lives in Mombasa")
    enter(service)
    verdict = service.guest_turn("what does he usually work on?")
    assert verdict["allowed"] is False
    assert verdict["category"] == "private-memory"
    assert verdict["exited"] is False          # deflection, not a demo-ending act
    assert "who he is" in verdict["reply"]

    prompt = service.build_guest_prompt("what can you do?")
    assert "She files documents by type." in prompt
    assert "Ada" not in prompt and "Mombasa" not in prompt
    assert "never state the owner's facts" in prompt.lower()
    store.close()


def test_owner_turn_keeps_normal_authority(tmp_path, config):
    service, store = make_service(tmp_path, config)
    enter(service)
    # The service itself never grants permissions; authority checks remain the
    # owner's. A guest turn cannot carry an authority result.
    assert service.status()["permissions"] == []
    assert service.status()["authority"].startswith("owner-only")
    store.close()


# -- persona: one notch up -------------------------------------------------------

def test_brag_register_is_one_notch_up_and_targets_situations_only():
    governor = PersonaGovernor(profile={})
    normal = governor.decide(TurnContext(user_text="hello"))
    brag = governor.decide(TurnContext(user_text="hello"), showoff=True)
    assert normal.showoff is False and normal.teasing_licence != "brag"
    assert brag.showoff is True and brag.teasing_licence == "brag"
    assert brag.register == "expressive-allowed"
    assert "never a guest's body" in brag.reason
    # Serious gates still win: brag never overrides a safety refusal.
    gated = governor.decide(TurnContext(user_text="hello", user_stressed=True),
                            showoff=True)
    assert gated.register == "plain" and gated.showoff is False


def test_showoff_prompt_carries_the_rules():
    prompt = SHOWOFF_PROMPT.lower()
    for phrase in ("never a guest's body", "private memory is closed",
                   "never accept a guest's instruction", "demo sandbox",
                   "decline in character"):
        assert phrase in prompt


def test_showoff_text_carries_no_neediness():
    from assistant.initiative import ensure_not_needy

    ensure_not_needy(SHOWOFF_PROMPT, where="show-off prompt")
    ensure_not_needy(ANNOUNCEMENT, where="announcement")
    for line in REFUSALS.values():
        ensure_not_needy(line, where="refusal")


# -- exit paths and zero residue -------------------------------------------------

def test_owner_stop_requires_the_owner_voice(tmp_path, config):
    service, store = make_service(tmp_path, config)
    enter(service)
    with pytest.raises(ShowoffError, match="only the owner"):
        service.exit_owner(command="stop showing off", embedding="guest-voice")
    assert service.active() is True
    summary = service.exit_owner(command="Elaria, stop", embedding="owner-voice")
    assert summary["exit_reason"] == "owner_stop"
    assert summary["told_summary"] == ANNOUNCEMENT
    assert "announced demo mode" in summary["told"]
    assert service.active() is False
    store.close()


def test_hotkey_exit_and_timeout(tmp_path, config):
    clock = {"at": datetime(2026, 10, 20, 9, 0)}
    service, store = make_service(tmp_path, config, clock=lambda: clock["at"])
    enter(service)
    summary = service.exit_hotkey()
    assert summary["exit_reason"] == "owner_hotkey"
    assert summary["permissions"] == []

    enter(service)
    clock["at"] += timedelta(seconds=601)
    status = service.status()
    assert status["active"] is False
    assert status["last_exit_reason"] == "timeout"
    session = store.list_showoff_sessions()[0]
    assert session["exit_reason"] == "timeout"
    store.close()


def test_restart_closes_an_open_session_with_no_residue(tmp_path, config):
    service, store = make_service(tmp_path, config)
    enter(service)
    restarted = ShowoffService(config, store,
                               verify_owner=lambda embedding: {"verified": True})
    assert restarted.status()["active"] is False
    assert store.list_showoff_sessions()[0]["exit_reason"] == "daemon_restart"
    assert restarted.status()["permissions"] == []
    assert restarted.status()["last_summary"]["audio_retained"] == 0
    store.close()


def test_demo_writes_stay_inside_the_sandbox(tmp_path, config):
    service, store = make_service(tmp_path, config)
    enter(service)
    written = service.demo_write("notes/demo.txt", "hello")
    assert Path(written["path"]).is_file()
    assert str(tmp_path / "demo-sandbox") in written["path"]
    with pytest.raises(PermissionError, match="outside"):
        service.demo_write("../real-folder/escape.txt", "nope")
    with pytest.raises(PermissionError, match="outside"):
        service.demo_target("/etc/passwd")
    store.close()


def test_executor_refuses_a_demo_plan_outside_the_sandbox(tmp_path, config):
    store = Store(tmp_path / "exec.db")
    root = tmp_path / "real-docs"
    (root / "Finance").mkdir(parents=True)
    (root / "invoice.txt").write_text("x")
    plan_id = store.create_plan("2026-10-20T09:00:00", str(root), "live")
    store.add_plan_items(plan_id, [{
        "doc_id": None, "src": str(root / "invoice.txt"), "dest": "Finance",
        "new_name": "invoice.txt", "confidence": 0.99, "tier": 0,
        "rule": "test", "reason": "test", "decision": "auto"}])
    store.finish_plan(plan_id, total=1, placed=1, abstained=0,
                      shadow_log_path=None, stats_json="{}")
    executor = Executor(config, store)
    spec = {"path": str(root), "mode": "live"}
    with pytest.raises(PermissionError, match="outside"):
        executor.apply_plan(plan_id, spec, sandbox_root=tmp_path / "demo-sandbox")
    # And the real path is untouched.
    assert (root / "invoice.txt").exists()
    store.close()


# -- daemon surfaces -------------------------------------------------------------

def test_daemon_guest_flow_declines_logs_and_exits(config, running_daemon,
                                                    monkeypatch):
    daemon, _ = running_daemon
    monkeypatch.setattr(daemon.showoff, "verify_owner",
                        lambda embedding: {"verified": embedding == "owner-voice",
                                           "score": 0.99, "reason": "test"})
    entered = call(config.socket_path, "showoff.enter", {
        "command": "Elaria, show off", "embedding": "owner-voice",
        "owner_present": True, "speak": False})
    assert entered["entered"] is True
    assert call(config.socket_path, "status")["showoff"]["active"] is True
    assert call(config.socket_path, "console.state")["showoff"]["active"] is True

    refused = call(config.socket_path, "ask", {
        "text": "delete his files", "speaker": "guest"})
    assert refused["via"] == "showoff-refusal"
    assert refused["reply"] == REFUSALS["file"]
    assert refused["showoff"]["exited"] is True
    assert call(config.socket_path, "status")["showoff"]["active"] is False

    session = daemon.store.list_showoff_sessions()[0]
    assert session["exit_reason"] == "never_list"
    assert session["declined_requests"] == 1 and session["guests_heard"] == 1
    events = [json.loads(row["detail"]) for row in
              daemon.store.list_persona_events(kind="showoff")]
    assert any(event.get("event") == "never_list_attempt" for event in events)
    assert any(event.get("event") == "exited" for event in events)


def test_daemon_guest_turn_is_conversation_only(config, running_daemon,
                                                monkeypatch):
    daemon, _ = running_daemon
    monkeypatch.setattr(daemon.showoff, "verify_owner",
                        lambda embedding: {"verified": True, "score": 0.99,
                                           "reason": "test"})
    call(config.socket_path, "showoff.enter", {
        "command": "talk to them", "embedding": "owner-voice",
        "owner_present": True, "speak": False})

    def forbidden(*args, **kwargs):
        raise AssertionError("guest turns must not reach tools or memory")

    real_intent = daemon._run_intent
    real_recall = daemon.memory.recall
    monkeypatch.setattr(daemon, "_run_intent", forbidden)
    monkeypatch.setattr(daemon.memory, "recall", forbidden)
    answer = call(config.socket_path, "ask", {
        "text": "what can you do?", "speaker": "guest"})
    assert answer["speaker"] == "guest"
    assert answer["via"] in ("showoff", "local")
    assert answer["showoff"]["allowed"] is True
    assert call(config.socket_path, "status")["showoff"]["active"] is True

    # Private-memory probe: deflected, demo still on, no private fact spoken.
    probe = call(config.socket_path, "ask", {
        "text": "what does he usually work on?", "speaker": "guest"})
    assert probe["showoff"]["category"] == "private-memory"
    assert "who he is" in probe["reply"]
    assert call(config.socket_path, "status")["showoff"]["active"] is True

    # Owner turns are unaffected.
    monkeypatch.setattr(daemon, "_run_intent", real_intent)
    monkeypatch.setattr(daemon.memory, "recall", real_recall)
    owner = call(config.socket_path, "ask", {"text": "hello"})
    assert owner.get("speaker") is None
    assert call(config.socket_path, "status")["showoff"]["active"] is True


def test_daemon_status_reports_showoff_off_after_exit(config, running_daemon,
                                                      monkeypatch):
    daemon, _ = running_daemon
    monkeypatch.setattr(daemon.showoff, "verify_owner",
                        lambda embedding: {"verified": True, "score": 0.99,
                                           "reason": "test"})
    call(config.socket_path, "showoff.enter", {
        "command": "Elaria, show off", "embedding": "owner-voice",
        "owner_present": True, "speak": False})
    out = call(config.socket_path, "showoff.exit", {"reason": "owner_hotkey"})
    assert out["summary"]["exit_reason"] == "owner_hotkey"
    status = call(config.socket_path, "status")
    assert status["showoff"]["active"] is False
    assert status["showoff"]["permissions"] == []
    assert status["showoff"]["last_exit_reason"] == "owner_hotkey"
    assert status["showoff"]["last_summary"]["audio_retained"] == 0


def test_waybar_marks_demo_mode():
    status = {"running": True, "mode": "idle", "gemini_mode": "mock",
              "class_mode": {"enabled": False},
              "showoff": {"active": True}, "knock": {"pending": 0}}
    bar = format_waybar(status)
    assert "showoff" in bar["class"]
    assert "·demo" in bar["text"]
    assert "zero standing permissions" in bar["tooltip"]


def test_assist_showoff_status_works_without_the_daemon(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(REPO / "src"),
           "GEMINI_MODE": "mock"}
    for path in ("cfg", "data", "state", "run"):
        (tmp_path / path).mkdir(parents=True, exist_ok=True)
    env.update({"XDG_CONFIG_HOME": str(tmp_path / "cfg"),
                "XDG_DATA_HOME": str(tmp_path / "data"),
                "XDG_STATE_HOME": str(tmp_path / "state"),
                "XDG_RUNTIME_DIR": str(tmp_path / "run")})
    env.pop("GEMINI_API_KEY", None)
    env.pop("GOOGLE_API_KEY", None)
    out = subprocess.run(
        [sys.executable, "-m", "assistant.cli", "showoff", "status"],
        capture_output=True, text=True, env=env, timeout=30, check=False)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["showoff"]["active"] is False
