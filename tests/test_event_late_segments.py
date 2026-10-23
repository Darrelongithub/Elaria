"""Late results may only occupy an unchanged, known segment position."""
from assistant.event import EventDocument


def _fixture(tmp_path):
    doc = EventDocument(tmp_path / "live.md")
    doc.write_header("Late event", "now", {})
    deferred = "## 10:00 · Amina · seg 001\n\n[seg 001 transcription failed/deferred — audio kept: seg-001.wav]\n\n"
    second = "## 10:30 · John · seg 002\n\nSecond landed block.\n\n"
    doc.append_block(deferred + second)
    replacement = "## 10:00 · Amina · seg 001\n\nRecovered first transcript.\n\n"
    return doc, deferred, second, replacement


def test_late_result_inserts_at_untouched_segment_position(tmp_path):
    doc, deferred, second, replacement = _fixture(tmp_path)
    outcome = doc.resolve_late(1, deferred, replacement, second)
    text = doc.txt_path.read_text()
    assert outcome[doc.txt_path] is True
    assert text.index("Recovered first transcript") < text.index("seg 002")
    assert "audio kept:" not in text


def test_edited_target_region_is_never_displaced(tmp_path):
    doc, deferred, second, replacement = _fixture(tmp_path)
    original = doc.txt_path.read_text()
    edited = original.replace("transcription failed/deferred", "owner changed marker")
    doc.txt_path.write_text(edited)
    outcome = doc.resolve_late(1, deferred, replacement, second)
    text = doc.txt_path.read_text()
    assert outcome[doc.txt_path] is False
    assert "owner changed marker" in text
    assert text.index("seg 002") < text.rindex("seg 001")
    assert "late transcript appended" in text
    assert "Recovered first transcript" in text


def test_edited_displaced_suffix_forces_tail_fallback(tmp_path):
    doc, deferred, second, replacement = _fixture(tmp_path)
    original = doc.txt_path.read_text()
    doc.txt_path.write_text(original.replace("Second landed block.", "Owner edited second."))
    outcome = doc.resolve_late(1, deferred, replacement, second)
    text = doc.txt_path.read_text()
    assert outcome[doc.txt_path] is False
    assert "Owner edited second." in text
    assert text.index("seg 002") < text.rindex("seg 001")
    assert "late transcript appended" in text
