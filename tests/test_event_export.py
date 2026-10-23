"""Speaker rename/export operate on copies, not the live document."""
import json

from assistant.event import export_event_document, rename_event_speaker


def test_rename_running_updates_labels_but_not_live_document_bytes(tmp_path):
    event_dir = tmp_path / "events" / "sample-event"
    (event_dir / "segments").mkdir(parents=True)
    live = tmp_path / "events" / "sample-event.md"
    txt = live.with_suffix(".txt")
    live_bytes = ("# Forum\n\n## 09:00 · Judge Two · seg 001\n\nWords.\n\n").encode()
    live.write_bytes(live_bytes)
    txt.write_bytes(live_bytes)
    (event_dir / "labels.json").write_text(json.dumps({
        "title": "Forum", "roster": ["Judge One", "Judge Two"],
        "segments": {"001": "Judge Two"},
    }))
    (event_dir / "state.json").write_text(json.dumps({
        "status": "running", "active_speaker": "Judge Two",
        "roster": ["Judge One", "Judge Two"],
        "segments": [{"index": 1, "speaker": "Judge Two"}],
    }))

    result = rename_event_speaker(event_dir, "S2", "Amina")
    assert result["old_name"] == "Judge Two"
    assert live.read_bytes() == live_bytes
    assert txt.read_bytes() == live_bytes
    labels = json.loads((event_dir / "labels.json").read_text())
    assert labels["segments"]["001"] == "Amina"
    exported = export_event_document(event_dir, "md")
    assert "Amina · seg 001" in exported.read_text()
    assert "Judge Two · seg 001" not in exported.read_text()
    assert live.read_bytes() == live_bytes
    assert txt.read_bytes() == live_bytes


def test_export_txt_is_a_new_copy_and_leaves_source_untouched(tmp_path):
    event_dir = tmp_path / "events" / "copy-event"
    event_dir.mkdir(parents=True)
    live = tmp_path / "events" / "copy-event.md"
    txt = live.with_suffix(".txt")
    live_bytes = b"live markdown"
    txt_bytes = b"owner-edited live text"
    live.write_bytes(live_bytes)
    txt.write_bytes(txt_bytes)
    (event_dir / "labels.json").write_text(json.dumps({"speaker_aliases": {}}))
    output = export_event_document(event_dir, "txt")
    assert output != txt
    assert output.read_bytes() == txt_bytes
    assert live.read_bytes() == live_bytes
    assert txt.read_bytes() == txt_bytes
