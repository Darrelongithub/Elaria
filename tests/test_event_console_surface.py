"""Console event actions remain a thin door to the daemon's event handlers."""
import os
import subprocess
import time
from pathlib import Path


def test_console_event_methods_are_the_cli_daemon_methods(running_daemon):
    daemon, _server = running_daemon
    handlers = daemon._handlers()
    assert handlers["event.start"].__func__ is type(daemon)._event_start
    assert handlers["event.stop"].__func__ is type(daemon)._event_stop
    assert handlers["event.status"].__func__ is type(daemon)._event_status
    assert handlers["event.edit"].__func__ is type(daemon)._event_edit
    assert handlers["event.rename"].__func__ is type(daemon)._event_rename
    assert handlers["event.export"].__func__ is type(daemon)._event_export
    assert handlers["event.speaker"].__func__ is type(daemon)._event_speaker


def test_quickshell_has_real_event_controls_and_notebook_surface():
    qml = (Path(__file__).parents[1] / "ui/quickshell/console/shell.qml").read_text()
    for phrase in ("Start event", "Stop event", "Next speaker", "Open .txt",
                   "Rename", "MD copy", "TXT copy", "eventTranscript", "speaker next"):
        assert phrase in qml
    # Console-home round (2026-10-25): the same three words are still the only
    # ones that input accepts, but they are offered as a note to her rather
    # than a command prompt. Behaviour pins live in tests/test_console_home.py.
    assert 'placeholderText: "write to her — status, speaker next, stop event"' in qml
    assert 'Your event command' not in qml
    assert 'eventProcess.command = ["assist"].concat(args)' in qml


def test_console_crash_fallback_notifies_and_opens_document_without_stopping_capture():
    root = Path(__file__).parents[1]
    script = root / "scripts/event-console-fallback.sh"
    result = subprocess.run(["bash", "-n", str(script)], check=False)
    assert result.returncode == 0
    content = script.read_text()
    assert 'assist event status' in content
    assert 'notify-send' in content and 'xdg-open' in content
    assert 'assist event stop' not in content


def _make_stub_bin(tmp_path: Path, doc_md: Path) -> tuple[Path, Path, Path]:
    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    notify_log = tmp_path / "notify.log"
    open_log = tmp_path / "open.log"

    assist = stub_bin / "assist"
    assist.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "if sys.argv[1:3] == ['event', 'status']:\n"
        f"    print(json.dumps({{'running': True, 'document': {str(doc_md)!r}}}))\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    assist.chmod(0o755)

    notify = stub_bin / "notify-send"
    notify.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {str(notify_log)!r}\n",
        encoding="utf-8",
    )
    notify.chmod(0o755)

    xdg_open = stub_bin / "xdg-open"
    xdg_open.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {str(open_log)!r}\n",
        encoding="utf-8",
    )
    xdg_open.chmod(0o755)
    return stub_bin, notify_log, open_log


def test_fallback_script_enforces_signal_only_notification_and_600s_rate_limit(tmp_path):
    script = Path(__file__).parents[1] / "scripts/event-console-fallback.sh"
    doc_md = tmp_path / "2026-11-19-secret-board-meeting.md"
    doc_txt = tmp_path / "2026-11-19-secret-board-meeting.txt"
    doc_md.write_text("# Secret\n", encoding="utf-8")
    doc_txt.write_text("# Secret\n", encoding="utf-8")
    runtime = tmp_path / "rt"
    runtime.mkdir()
    stub_bin, notify_log, open_log = _make_stub_bin(tmp_path, doc_md)
    env = {
        **os.environ,
        "PATH": f"{stub_bin}:{os.environ.get('PATH', '')}",
        "XDG_RUNTIME_DIR": str(runtime),
        "SERVICE_RESULT": "exit-code",
    }

    first = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=False)
    assert first.returncode == 0
    assert str(doc_txt) in first.stderr

    deadline = time.monotonic() + 3.0
    while not open_log.exists() and time.monotonic() < deadline:
        time.sleep(0.02)

    notified = notify_log.read_text(encoding="utf-8").splitlines()
    assert len(notified) == 1
    assert "secret-board-meeting" not in notified[0]
    assert str(doc_txt) not in notified[0]
    assert "The console is unavailable. Elaria is still listening" in notified[0]
    opened = open_log.read_text(encoding="utf-8").splitlines()
    assert opened == [str(doc_txt)]

    # Second run inside the 600s window is rate-limited silently (no notification storm).
    second = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=False)
    assert second.returncode == 0
    assert len(notify_log.read_text(encoding="utf-8").splitlines()) == 1
    assert len(open_log.read_text(encoding="utf-8").splitlines()) == 1

    # Once the 600s window expires, notifications resume.
    stamps = list(runtime.glob("elaria-event-console-fallback-*"))
    assert len(stamps) == 1
    stamps[0].write_text(str(int(time.time()) - 605), encoding="utf-8")
    third = subprocess.run([str(script)], env=env, capture_output=True, text=True, check=False)
    assert third.returncode == 0
    assert len(notify_log.read_text(encoding="utf-8").splitlines()) == 2
