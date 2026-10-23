"""Console event actions remain a thin door to the daemon's event handlers."""
import subprocess
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
                   "Rename", "MD copy", "TXT copy", "Your event command",
                   "eventTranscript", "speaker next"): 
        assert phrase in qml
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
