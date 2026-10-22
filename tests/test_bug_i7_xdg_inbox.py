"""I7 regression: the default transcript inbox follows XDG_DATA_HOME."""

from __future__ import annotations

from datetime import UTC, datetime

from assistant.config import load_config
from assistant.inbox import write_inbox_note
from assistant.meeting import MeetingService
from assistant.transcribe import DictationService


def test_bug_i7_default_transcript_inboxes_follow_xdg_data_home(
        tmp_path, monkeypatch):
    """I7: dictation and meeting notes share the configured XDG data root."""
    data_home = tmp_path / "alternate-xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.delenv("ASSIST_CONFIG", raising=False)
    config = load_config()
    expected = data_home / "assistant" / "inbox"

    dictation = DictationService(config, store=None, client=None)
    meeting = MeetingService(config, store=None, client=None)

    assert config.data_dir == data_home / "assistant"
    assert (dictation.inbox_dir, meeting.inbox_dir) == (expected, expected)
    note = write_inbox_note(
        dictation.inbox_dir, when=datetime(2026, 10, 22, tzinfo=UTC),
        raw="A short test note.", cleaned=None, backend="test", language="en",
        audio_path=None, flagged=False, session_id="abcdef012345")
    assert note.parent == expected
    assert note.is_file()


def test_bug_i7_explicit_transcript_inbox_override_is_preserved(config, tmp_path):
    """I7: a configured inbox still overrides the XDG-derived default."""
    explicit = tmp_path / "custom-inbox"
    config.raw["transcribe"]["inbox_dir"] = str(explicit)
    assert DictationService(config, store=None, client=None).inbox_dir == explicit
    assert MeetingService(config, store=None, client=None).inbox_dir == explicit
