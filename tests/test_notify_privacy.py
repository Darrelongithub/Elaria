"""NOTIFICATION PRIVACY RULE (owner order, 2026-10-26) — [TESTED-ONLY].

Notifications are signals, not carriers. Doctrine, enforced here:

* title is exactly "Elaria wants to talk" for every knock notification;
* body is one fixed static sentence (or empty), identical for every knock —
  no topic, no reason, no fragment, no dynamic string may reach argv;
* urgency / class-mode variants may change FLAGS only, never content;
* a silent knock (class mode or `knock["silent"]`) emits zero audio AND zero
  subprocess (BH-H9, owner-joined into this stream);
* every other system-notification surface (console fallback script) is
  signal-only too, and the always-visible overlay pill is dot/pulse, never
  text.

Tests are hermetic: the runner is injected and `shutil.which` is stubbed, so
nothing here can touch a real desktop.
"""

from __future__ import annotations

from pathlib import Path

from assistant import initiative as initiative_module
from assistant.initiative import (
    NOTIFY_BODY,
    NOTIFY_IDENTITY,
    NOTIFY_TITLE,
    KnockSignal,
)
from assistant.store import Store

REPO = Path(__file__).resolve().parents[1]

# Distinctive strings: if ANY of these ever appears in a notification argv,
# the privacy rule is broken. They stand for the owner's gym/invoice detail.
SECRET_TOPIC = "gym-leg-day-2026"
SECRET_REASON = "INVOICE-2026-SECRET-7731 the invoice for the gym is overdue"


def _service(tmp_path, config):
    from assistant.initiative import InitiativeService
    from assistant.presence import PresenceService

    store = Store(tmp_path / "privacy.db")
    presence = PresenceService(config, store)
    # presence DISABLED: class_mode() False, so `knock["silent"]` is False
    # and emit() takes the normal notification path (the class-mode test
    # passes class_mode=True explicitly).
    service = InitiativeService(config, store, presence=presence)
    return service, store, presence


def _raise_secret_knock(service, *, urgency: str = "normal",
                        kind: str = "follow-up") -> dict:
    """A knock the real way: a cited commitment + a reason that passes the
    gate. The payload carries distinctive strings for the leak property."""
    commitment = service.create_commitment(
        "watch the gym invoice", origin="user-request")
    return service.raise_knock(
        topic=SECRET_TOPIC, reason=SECRET_REASON, kind=kind,
        urgency=urgency, referent="the gym invoice",
        commitment_id=commitment["commitment_id"])


def _emit_with_capture(config, knock, *, class_mode=False, tmp_path=None):
    """Run KnockSignal.emit with a fake desktop: every subprocess is captured."""
    calls: list[list[str]] = []

    def runner(argv, **kw):
        calls.append(list(argv))

    signal = KnockSignal(config, runner=runner)
    out = signal.emit(knock, class_mode=class_mode)
    return out, calls


def _patch_desktop(monkeypatch, *, with_player=True):
    def which(name):
        if name == "notify-send":
            return "/usr/bin/notify-send"
        if with_player and name in ("pw-play", "paplay", "aplay"):
            return f"/usr/bin/{name}"
        return None

    monkeypatch.setattr(initiative_module.shutil, "which", which)


def test_title_is_exactly_the_one_sentence(config, monkeypatch, tmp_path):
    _patch_desktop(monkeypatch)
    (tmp_path / "knock.wav").write_bytes(b"RIFF")
    config.raw["initiative"] = {**config.raw.get("initiative", {}),
                                "sound": str(tmp_path / "knock.wav"),
                                "notify": True, "play_sound": True}
    service, store, _ = _service(tmp_path, config)
    try:
        knock = _raise_secret_knock(service)
    finally:
        store.close()
    out, calls = _emit_with_capture(config, knock)
    assert out["notification"] is True
    notifications = [c for c in calls if c and c[0] == "notify-send"]
    assert notifications, calls
    for argv in notifications:
        assert NOTIFY_TITLE == "Elaria wants to talk"
        assert argv[-2] == "Elaria wants to talk", argv
        # exact title equality — not a prefix, not a variant
        assert argv[-2] == NOTIFY_TITLE


def test_no_topic_reason_or_fragment_ever_reaches_argv(
        config, monkeypatch, tmp_path):
    """Property: for payloads carrying distinctive topic/reason strings,
    NONE of those strings (or fragments ≥ 4 chars) appears in any argv."""
    _patch_desktop(monkeypatch)
    (tmp_path / "knock.wav").write_bytes(b"RIFF")
    config.raw["initiative"] = {**config.raw.get("initiative", {}),
                                "sound": str(tmp_path / "knock.wav"),
                                "notify": True, "play_sound": True}
    service, store, _ = _service(tmp_path, config)
    try:
        knock = _raise_secret_knock(service)
    finally:
        store.close()
    _out, calls = _emit_with_capture(config, knock)
    assert calls, "nothing ran — the property would be vacuous"
    fragments = {SECRET_TOPIC, SECRET_REASON, "gym", "INVOICE", "2026-SECRET",
                 "7731", "overdue", "invoice for the gym", "leg-day"}
    for argv in calls:
        joined = " ".join(argv)
        for fragment in fragments:
            assert fragment not in joined, (
                f"privacy leak: {fragment!r} in notification argv {argv}")
        assert SECRET_TOPIC not in joined and SECRET_REASON not in joined
    # and the body is the one fixed static sentence, byte-identical
    notifications = [c for c in calls if c and c[0] == "notify-send"]
    for argv in notifications:
        assert argv[-1] == NOTIFY_BODY
        assert argv[-1] == "Open the console when you're free."
        assert argv[argv.index("-a") + 1] == NOTIFY_IDENTITY


def test_urgent_is_a_flag_never_content(config, monkeypatch, tmp_path):
    _patch_desktop(monkeypatch)
    (tmp_path / "knock.wav").write_bytes(b"RIFF")
    config.raw["initiative"] = {**config.raw.get("initiative", {}),
                                "sound": str(tmp_path / "knock.wav"),
                                "notify": True, "play_sound": True}
    service, store, _ = _service(tmp_path, config)
    try:
        knock = _raise_secret_knock(service, kind="urgency", urgency="urgent")
    finally:
        store.close()
    out, calls = _emit_with_capture(config, knock)
    assert out["signal"] == "knock"
    notifications = [c for c in calls if c and c[0] == "notify-send"]
    for argv in notifications:
        assert "-u" in argv and argv[argv.index("-u") + 1] == "urgent"
        # the urgent variant changed a flag — content identical to normal
        assert argv[-2] == NOTIFY_TITLE
        assert argv[-1] == NOTIFY_BODY
        for word in (SECRET_TOPIC, "INVOICE", "gym", "7731"):
            assert word not in " ".join(argv)


def test_class_mode_emits_zero_subprocess_and_zero_audio(
        config, monkeypatch, tmp_path):
    _patch_desktop(monkeypatch)
    (tmp_path / "knock.wav").write_bytes(b"RIFF")
    config.raw["initiative"] = {**config.raw.get("initiative", {}),
                                "sound": str(tmp_path / "knock.wav"),
                                "notify": True, "play_sound": True}
    service, store, _ = _service(tmp_path, config)
    try:
        knock = _raise_secret_knock(service, kind="urgency", urgency="urgent")
    finally:
        store.close()
    out, calls = _emit_with_capture(config, knock, class_mode=True)
    assert out["signal"] == "visual-pulse"
    assert out["notification"] is False and out["sound"] is False
    assert calls == [], f"class-mode knock spawned subprocesses: {calls}"


def test_silent_knock_bh_h9_zero_audio_and_zero_subprocess(
        config, monkeypatch, tmp_path):
    """BH-H9, owner-joined (2026-10-26): a silent knock emits zero audio
    AND zero subprocess — even when the caller passes class_mode=False."""
    _patch_desktop(monkeypatch)
    (tmp_path / "knock.wav").write_bytes(b"RIFF")
    config.raw["initiative"] = {**config.raw.get("initiative", {}),
                                "sound": str(tmp_path / "knock.wav"),
                                "notify": True, "play_sound": True}
    knock = {"topic": SECRET_TOPIC, "reason": SECRET_REASON,
             "urgency": "urgent", "silent": True}
    out, calls = _emit_with_capture(config, knock, class_mode=False)
    assert out["signal"] == "visual-pulse"
    assert out["notification"] is False and out["sound"] is False
    assert calls == [], f"silent knock spawned subprocesses: {calls}"

    # a non-silent knock on the same desktop DOES run (the guard is the flag,
    # not a dead runner) — the contrast makes the assertion above meaningful
    loud = {"topic": SECRET_TOPIC, "reason": SECRET_REASON, "urgency": "normal"}
    out2, calls2 = _emit_with_capture(config, loud, class_mode=False)
    assert calls2, "the non-silent control knock should have notified"
    assert out2["sound"] is False or out2["notification"] is True


def test_content_is_never_configurable(config):
    """No config knob for content: the visible strings live in code only."""
    initiative_defaults = config.section("initiative")
    for key in ("notify_identity", "notify_title", "notify_body",
                "notification_body", "message"):
        assert key not in initiative_defaults, (
            f"[initiative] {key} would make notification content configurable")
    assert NOTIFY_TITLE == "Elaria wants to talk"
    assert NOTIFY_BODY == "Open the console when you're free."


def test_fallback_script_notification_is_signal_only():
    script = (REPO / "scripts" / "event-console-fallback.sh").read_text()
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("notify-send"):
            assert "$txt_path" not in stripped, (
                "the live document path is journal material, not "
                "notification content")
            assert "$message" in stripped or "Elaria" in stripped
    # the message sentences themselves are fixed strings in the script
    assert "The console is unavailable." in script


def test_overlay_pill_is_dot_pulse_never_text():
    qml = (REPO / "ui" / "quickshell" / "shell.qml").read_text()
    assert "state.text" not in qml and "stateText" not in qml
    assert "Text {" not in qml
    # …and the feed text still exists for owner-raised consumers (console):
    reducer = (REPO / "src" / "assistant" / "overlay.py").read_text()
    assert "text" in reducer


def test_every_notification_surface_is_registered_and_audited():
    """Static guard: notify-send in src/ stays confined to the knock path
    (voicetest is a dev tool with static strings) and the shell script."""
    offenders = []
    for path in (REPO / "src" / "assistant").glob("*.py"):
        if path.name in ("voicetest.py", "cli.py"):
            continue
        if "notify-send" in path.read_text() and path.name != "initiative.py":
            offenders.append(path.name)
    assert not offenders, offenders
    voicetest = (REPO / "src" / "assistant" / "voicetest.py").read_text()
    assert '"Keyword + voiceprint matched"' in voicetest  # static, no payload
