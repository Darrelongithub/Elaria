"""Console document edits are durable and append-safe."""
from pathlib import Path

from assistant.event import EventDocument


def test_console_edit_segment_then_append_keeps_edit_and_order(tmp_path):
    doc = EventDocument(tmp_path / "live.md")
    doc.write_header("Event", "now", {})
    first = "## 10:00 · Amina · seg 001\n\nThe old word.\n\n"
    doc.append_block(first)
    outcome = doc.edit_segment(1, "The old word.", "The corrected word.")
    assert outcome["state"] == "edited"
    doc.append_block("## 10:01 · John · seg 002\n\nNext segment.\n\n")
    text = doc.txt_path.read_text()
    assert "The corrected word." in text
    assert "The old word." not in text
    assert text.index("seg 001") < text.index("The corrected word.")
    assert text.index("The corrected word.") < text.index("seg 002")
    markdown = doc.md_path.read_text()
    assert "The corrected word." in markdown
    assert markdown.index("The corrected word.") < markdown.index("seg 002")


def test_stale_edit_is_appended_instead_of_displacing_owner_changes(tmp_path):
    doc = EventDocument(tmp_path / "live.md")
    doc.write_header("Event", "now", {})
    doc.append_block("## 10:00 · Amina · seg 001\n\nLanded words.\n\n")
    doc.edit_segment(1, "Landed words.", "Owner's first edit.")
    outcome = doc.edit_segment(1, "Landed words.", "Stale second edit.")
    text = doc.txt_path.read_text()
    assert outcome["state"] == "conflict-appended"
    assert "Owner's first edit." in text
    assert "Stale second edit." in text
    assert "edited copy" in text
    markdown = doc.md_path.read_text()
    assert "Owner's first edit." in markdown
    assert "Stale second edit." in markdown


def test_quickshell_event_transcript_is_editable_and_debounced():
    qml = (Path(__file__).parents[1] / "ui/quickshell/console/shell.qml").read_text()
    assert "TextArea" in qml
    assert "editSaveTimer" in qml
    assert '"event", "edit"' in qml


def test_edit_api_is_shared_with_cli_and_daemon():
    from assistant.daemon import Daemon

    assert Daemon._event_edit.__name__ == "_event_edit"
    daemon_source = Path(__file__).parents[1].joinpath("src/assistant/daemon.py").read_text()
    cli_source = Path(__file__).parents[1].joinpath("src/assistant/cli.py").read_text()
    assert '"event.edit": self._event_edit' in daemon_source
    assert 'event_sub.add_parser("edit"' in cli_source
    assert 'call(config.socket_path, "event.edit"' in cli_source
