"""Event live-document durability and stop guarantees."""
import asyncio
import json
import struct
import time
from pathlib import Path

from assistant.event import EventDocument, EventService


def test_document_header_refuses_to_overwrite_existing_editor_file(tmp_path):
    md = tmp_path / "safe.md"
    txt = tmp_path / "safe.txt"
    md.write_text("Owner's existing notes.\n")
    doc = EventDocument(md, txt)
    try:
        doc.write_header("Accidental overwrite", "now", {})
    except FileExistsError:
        pass
    else:
        raise AssertionError("header write replaced an existing live document")
    assert md.read_text() == "Owner's existing notes.\n"


def test_live_append_does_not_rewrite_editor_changes(tmp_path):
    doc = EventDocument(tmp_path / "notes.md")
    doc.write_header("Meeting", "now", {})
    with doc.txt_path.open("a", encoding="utf-8") as stream:
        stream.write("Owner corrected this word.\n")
    doc.append_block("## 10:02 · Amina · seg 002\n\nNew words.\n\n")
    text = doc.txt_path.read_text()
    assert "Owner corrected this word." in text
    assert text.endswith("New words.\n\n")


def test_stop_marks_audio_before_clearing_without_waiting_for_transcriber(config):
    from assistant.capture import SimulatedCapture

    async def scenario():
        async def never(path):
            await asyncio.Event().wait()

        service = EventService(config, None, transcribe_fn=never,
                               stop_grace_s=0.01)
        service._inhibit_enabled = False
        started = await service.start(title="Quick stop", source=SimulatedCapture(),
                                      battery_ok=True)
        assert started["state"] == "event"
        frame = struct.pack("<480h", *([6000] * 480))
        service._current_sink.write(frame)
        service._current["bytes"] += len(frame)
        service._current["peak"] = 0.5
        service._rotate()
        wav = Path(service._segments[1]["wav"])
        assert wav.exists() and wav.stat().st_size > 44
        begin = time.monotonic()
        result = await asyncio.wait_for(service.stop(), timeout=1.5)
        assert time.monotonic() - begin < 1.5
        body = Path(result["txt_document"]).read_text(encoding="utf-8")
        assert "audio kept:" in body
        assert str(wav) in body
        state = json.loads((service._event_dir / "state.json").read_text())
        assert state["status"] == "stopped"
        if service._queue_task and not service._queue_task.done():
            service._queue_task.cancel()
            try:
                await service._queue_task
            except asyncio.CancelledError:
                pass

    asyncio.run(scenario())


def test_stop_returns_with_marker_then_background_transcript_lands(config):
    from assistant.capture import SimulatedCapture

    async def scenario():
        release = asyncio.Event()

        async def delayed(path):
            await release.wait()
            return "The delayed words arrived."

        service = EventService(config, None, transcribe_fn=delayed,
                               stop_grace_s=0.01)
        service._inhibit_enabled = False
        await service.start(title="Late text", source=SimulatedCapture(),
                            battery_ok=True)
        service._rotate()
        result = await asyncio.wait_for(service.stop(), timeout=1.5)
        path = Path(result["txt_document"])
        before = path.read_text(encoding="utf-8")
        assert "audio kept:" in before
        edited = before.replace("transcription failed/deferred", "owner's note")
        path.write_text(edited, encoding="utf-8")
        release.set()
        await asyncio.wait_for(service._queue_task, timeout=1)
        after = path.read_text(encoding="utf-8")
        assert "audio kept:" in after
        assert "The delayed words arrived." in after
        assert "earlier live text was preserved" in after
        assert after.startswith(edited)

    asyncio.run(scenario())


def test_recovery_appends_missing_segment_without_rewriting_existing_edits(tmp_path):
    from assistant.event import assemble_event_document

    root = tmp_path / "events"
    event_dir = root / "recovery-case"
    seg_dir = event_dir / "segments"
    seg_dir.mkdir(parents=True)
    (event_dir / "state.json").write_text(json.dumps({
        "title": "Recovery", "status": "stopping", "started_at": "2026-10-22T10:00:00",
        "route": "batch", "segment_minutes": 30,
        "segments": [{"index": 1, "wav": str(seg_dir / "seg-001.wav"),
                      "speaker": "Amina", "opened_at": "2026-10-22T10:00:00",
                      "markers": [], "no_signal": False}],
    }))
    (seg_dir / "seg-001.txt").write_text("Transcript recovered.")
    initial = "# Recovery\n\nMy hand-edited opening.\n"
    (root / "recovery-case.md").write_text(initial)
    (root / "recovery-case.txt").write_text(initial + "TXT-only edit.\n")

    assemble_event_document(event_dir)
    md = (root / "recovery-case.md").read_text()
    txt = (root / "recovery-case.txt").read_text()
    assert md.startswith(initial)
    assert txt.startswith(initial + "TXT-only edit.\n")
    assert "Transcript recovered." in md and "Transcript recovered." in txt
    assemble_event_document(event_dir)
    assert (root / "recovery-case.md").read_text() == md
    assert (root / "recovery-case.txt").read_text() == txt


def test_late_queue_results_stay_with_their_event_after_next_start(config):
    from assistant.capture import SimulatedCapture

    async def scenario():
        release = asyncio.Event()

        async def delayed(path):
            await release.wait()
            return Path(path).parent.parent.name

        service = EventService(config, None, transcribe_fn=delayed,
                               stop_grace_s=0.01)
        service._inhibit_enabled = False
        first = await service.start(title="First room", source=SimulatedCapture(),
                                    battery_ok=True)
        service._rotate()
        await service.stop()
        first_task = service._queue_task

        second = await service.start(title="Second room", source=SimulatedCapture(),
                                     battery_ok=True)
        service._rotate()
        await service.stop()
        second_task = service._queue_task

        release.set()
        await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=2)
        first_text = Path(first["txt_document"]).read_text()
        second_text = Path(second["txt_document"]).read_text()
        first_name = Path(first["event_dir"]).name
        second_name = Path(second["event_dir"]).name
        assert first_name in first_text and second_name not in first_text
        assert second_name in second_text and first_name not in second_text

    asyncio.run(scenario())
