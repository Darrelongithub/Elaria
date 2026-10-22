"""I5 regression: sensitive local artifacts are private under umask 0022."""

from __future__ import annotations

import os
import stat
from datetime import UTC, datetime

from assistant.capture import WavSink, write_wav
from assistant.config import load_config
from assistant.diarize import Turn
from assistant.inbox import write_inbox_note
from assistant.meeting import MeetingService
from assistant.store import Store


def test_bug_i5_sensitive_storage_is_owner_only_under_umask_0022(
        tmp_path, monkeypatch):
    """I5: data, state, SQLite sidecars, WAVs, and notes are not world-readable."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    config = load_config()
    old_umask = os.umask(0o022)
    store = None
    wav = None
    try:
        for directory in (config.data_dir, config.state_dir):
            directory.mkdir(parents=True, exist_ok=True, mode=0o755)
            directory.chmod(0o755)
        config.ensure_dirs()
        config.db_path.write_bytes(b"")
        config.db_path.chmod(0o644)
        store = Store(config.db_path)
        store._conn.execute("BEGIN IMMEDIATE")
        store._conn.execute(
            "INSERT INTO state(key,value) VALUES('permission-probe','active')")
        wav_path = config.data_dir / "audio" / "permission-probe.wav"
        wav = WavSink(wav_path)
        wav.write(b"\x01\x00\x02\x00")
        wav.close()
        wav = None
        note = write_inbox_note(
            config.inbox_dir, when=datetime(2026, 10, 22, tzinfo=UTC),
            raw="A private test transcript.", cleaned=None, backend="test",
            language="en", audio_path=None, flagged=False,
            session_id="private1")

        mic_source = write_wav(tmp_path / "source-mic.wav", [b"\x10\x00" * 16000])
        system_source = write_wav(tmp_path / "source-system.wav", [b"\x20\x00" * 16000])
        meeting = MeetingService(config, store, client=None)
        monkeypatch.setattr(
            meeting, "_transcribe_channel",
            lambda _path, speaker, _work, *, deadline=None: [
                Turn(speaker, 0.0, 1.0, f"{speaker} test")])
        meeting_result = meeting.transcribe_dual(
            mic_source, system_source, title="Private test")

        observed = {
            "data_dir": stat.S_IMODE(config.data_dir.stat().st_mode),
            "state_dir": stat.S_IMODE(config.state_dir.stat().st_mode),
            "audio_dir": stat.S_IMODE((config.data_dir / "audio").stat().st_mode),
            "inbox_dir": stat.S_IMODE(config.inbox_dir.stat().st_mode),
            "assistant.db": stat.S_IMODE(config.db_path.stat().st_mode),
            "assistant.db-wal": stat.S_IMODE(
                config.db_path.with_name(config.db_path.name + "-wal").stat().st_mode),
            "assistant.db-shm": stat.S_IMODE(
                config.db_path.with_name(config.db_path.name + "-shm").stat().st_mode),
            "audio.wav": stat.S_IMODE(wav_path.stat().st_mode),
            "meeting-mic.wav": stat.S_IMODE(meeting_result.mic_wav.stat().st_mode),
            "meeting-system.wav": stat.S_IMODE(meeting_result.system_wav.stat().st_mode),
            "dictation.md": stat.S_IMODE(note.stat().st_mode),
            "meeting.md": stat.S_IMODE(meeting_result.note_path.stat().st_mode),
        }
        expected = {name: 0o700 for name in (
            "data_dir", "state_dir", "audio_dir", "inbox_dir")}
        expected.update({name: 0o600 for name in (
            "assistant.db", "assistant.db-wal", "assistant.db-shm",
            "audio.wav", "meeting-mic.wav", "meeting-system.wav",
            "dictation.md", "meeting.md")})
        assert observed == expected, observed
    finally:
        if wav is not None:
            wav.close()
        if store is not None:
            store.close()
        os.umask(old_umask)
