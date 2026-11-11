"""Ack playback (scene-3b stream B) — [TESTED-ONLY], invoked-runner only.

Owner evidence 2026-10-26: the ack chain reported `played:false` while the
sink was alive (paplay chime audible). The trace found three swallow
points — a preferred player that exists but fails ends playback outright,
non-zero exits drop their stderr, and the fire-and-forget result is never
reported anywhere. Fixes under test here:

* the player chain tries every available candidate in order (first binary
  is a preference, not a commitment);
* every failure mode records argv/returncode/error — silence with a
  reason, never a bare False;
* `ack.played` / `ack.failed` schema events carry the player argv + error;
* an ack that will never play says so (`speak_suppressed` reasons).

The sandbox has no audio binaries (BH-H9 lesson): assert the CALL SHAPE
with injected runners; hardware confirms in the owner's scene (paplay of
the ack wav is on the checklist).
"""

from __future__ import annotations

import asyncio
import wave
from types import SimpleNamespace

from assistant.daemon import Daemon
from assistant.tts import SESSION_CUE_KIND, SpeechService


def _wav(path, seconds: float = 0.2) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(seconds * 16000))


def _which_factory(installed: set[str]):
    def which(name):
        return f"/usr/bin/{name}" if name in installed else None
    return which


# -- the player chain ---------------------------------------------------------

def test_first_player_failure_falls_through_to_the_next(config, tmp_path,
                                                        monkeypatch):
    """A pw-play that exists but fails must not end playback while paplay
    could still make sound (the owner's paplay worked)."""
    monkeypatch.setattr("assistant.tts.shutil.which",
                        _which_factory({"pw-play", "paplay"}))
    calls: list[list[str]] = []

    def runner(argv, **kw):
        calls.append(list(argv))
        if argv[0].endswith("pw-play"):
            return SimpleNamespace(returncode=1,
                                   stderr=b"pw-play: no sink configured")
        return SimpleNamespace(returncode=0, stderr=b"")

    speech = SpeechService(config, player_runner=runner)
    clip = tmp_path / "ack.wav"
    _wav(clip)
    detail = speech._play_with_detail(clip)
    assert detail["played"] is True
    assert detail["player"] == "paplay"
    assert detail["argv"] == ["paplay", str(clip)]
    assert [c[0].rsplit("/", 1)[-1] for c in calls] == ["pw-play", "paplay"]


def test_every_failure_records_argv_returncode_and_error(config, tmp_path,
                                                         monkeypatch):
    monkeypatch.setattr("assistant.tts.shutil.which",
                        _which_factory({"pw-play", "aplay"}))
    calls: list[list[str]] = []

    def runner(argv, **kw):
        calls.append(list(argv))
        return SimpleNamespace(returncode=3, stderr=b"boom: sink busy")

    speech = SpeechService(config, player_runner=runner)
    clip = tmp_path / "ack.wav"
    _wav(clip)
    detail = speech._play_with_detail(clip)
    assert detail["played"] is False
    assert detail["argv"] == ["aplay", str(clip)]   # the LAST attempt
    assert detail["returncode"] == 3
    assert "aplay exited 3" in detail["error"]
    assert "sink busy" in detail["error"]
    assert "pw-play exited 3" in speech.last_voice_error
    assert len(calls) == 2


def test_spawn_error_falls_through_and_is_recorded(config, tmp_path,
                                                   monkeypatch):
    monkeypatch.setattr("assistant.tts.shutil.which",
                        _which_factory({"pw-play", "paplay"}))

    def runner(argv, **kw):
        if argv[0].endswith("pw-play"):
            raise OSError("player vanished")
        return SimpleNamespace(returncode=0, stderr=b"")

    speech = SpeechService(config, player_runner=runner)
    clip = tmp_path / "ack.wav"
    _wav(clip)
    detail = speech._play_with_detail(clip)
    assert detail["played"] is True and detail["player"] == "paplay"


def test_no_player_available_reports_the_reason(config, tmp_path, monkeypatch):
    monkeypatch.setattr("assistant.tts.shutil.which", _which_factory(set()))
    speech = SpeechService(config, player_runner=lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("no player must not be invoked")))
    detail = speech._play_with_detail(tmp_path / "ack.wav")
    assert detail["played"] is False
    assert detail["argv"] is None
    assert "no audio player available" in detail["error"]
    assert "no audio player available" in speech.last_voice_error


def test_play_ack_carries_player_argv_and_error(config, tmp_path, monkeypatch):
    monkeypatch.setattr("assistant.tts.shutil.which",
                        _which_factory({"pw-play", "paplay"}))
    clip = tmp_path / "on_it.wav"
    _wav(clip)

    def runner(argv, **kw):
        if argv[0] == "pw-play":
            return SimpleNamespace(returncode=1, stderr=b"pw-play: refused")
        return SimpleNamespace(returncode=0, stderr=b"")

    speech = SpeechService(config, player_runner=runner)
    monkeypatch.setattr(speech, "cached_ack", lambda kind: str(clip))
    monkeypatch.setattr(speech, "voice_route", lambda: ("gemini", "gemini"))
    out = speech.play_ack("on_it")
    assert out["played"] is True          # paplay succeeded after pw-play died
    assert out["player"] == "paplay"
    assert out["argv"] == ["paplay", str(clip)]


# -- daemon: the schema events + suppression reasons --------------------------

def _daemon_with_fake_playback(config, result: dict, played_files: list):
    daemon = Daemon(config)

    def play_ack(kind):
        played_files.append(kind)
        return result

    daemon.speech.play_ack = play_ack
    daemon.speech.cached_ack = lambda kind: "/tmp/voice-cache/ack.wav"
    daemon.speech.route = lambda text: {"muted": False, "route": "gemini"}
    return daemon


def test_ack_played_event_carries_the_player_argv(config, journal_stream):
    played: list = []
    daemon = _daemon_with_fake_playback(
        config, {"played": True, "player": "paplay",
                 "argv": ["paplay", "/tmp/voice-cache/ack.wav"], "error": ""},
        played)
    try:
        async def drive():
            out = await daemon._ack({"kind": "on_it"})
            assert out["speech"]["queued"] is True
            await asyncio.sleep(0.05)

        asyncio.run(drive())
        lines = [ln for ln in journal_stream.getvalue().splitlines()
                 if ln.split(" ", 6)[2] == "ack.played"]
        assert lines, journal_stream.getvalue()
        assert lines[0].split(" ", 6)[5] == "played"
        assert "player=paplay" in lines[0]
        assert "argv=paplay /tmp/voice-cache/ack.wav" in lines[0]
    finally:
        daemon.store.close()


def test_ack_failed_event_carries_the_error(config, journal_stream):
    played: list = []
    daemon = _daemon_with_fake_playback(
        config, {"played": False, "player": "pw-play",
                 "argv": ["pw-play", "/tmp/voice-cache/ack.wav"],
                 "returncode": 1, "error": "pw-play exited 1: no sink"},
        played)
    try:
        async def drive():
            await daemon._ack({"kind": "on_it"})
            await asyncio.sleep(0.05)

        asyncio.run(drive())
        lines = [ln for ln in journal_stream.getvalue().splitlines()
                 if ln.split(" ", 6)[2] == "ack.failed"]
        assert lines, journal_stream.getvalue()
        assert lines[0].split(" ", 6)[5] == "failed"
        assert "error=pw-play exited 1: no sink" in lines[0]
    finally:
        daemon.store.close()


def test_release_ack_never_plays_and_says_why(config, journal_stream):
    """The owner's pasted ack (played:false on the stop ack) is by design —
    and now it SAYS so instead of reading like a failure."""
    played: list = []
    daemon = _daemon_with_fake_playback(
        config, {"played": True, "player": "paplay", "argv": ["paplay", "x"],
                 "error": ""}, played)
    try:
        async def drive():
            out = await daemon._ack({"kind": "on_it", "speak": False})
            assert played == [], "a release ack must not spawn a player"
            speech = out["speech"]
            assert speech["played"] is False
            assert speech.get("queued") is not True
            assert "release ack" in (speech["speak_suppressed"] or "")

        asyncio.run(drive())
        assert not [ln for ln in journal_stream.getvalue().splitlines()
                    if ln.split(" ", 6)[2].startswith("ack.")]
    finally:
        daemon.store.close()


def test_earcon_cue_uses_the_same_reported_chain(config, journal_stream):
    """The press earcon (session cue) reports through ack.played too."""
    played: list = []
    daemon = _daemon_with_fake_playback(
        config, {"played": True, "player": "paplay",
                 "argv": ["paplay", "/tmp/voice-cache/cue.wav"], "error": ""},
        played)
    try:
        async def drive():
            out = await daemon._ack({"kind": SESSION_CUE_KIND})
            assert out["speech"]["queued"] is True
            await asyncio.sleep(0.05)

        asyncio.run(drive())
        assert played == ["session_open"]
        lines = [ln for ln in journal_stream.getvalue().splitlines()
                 if ln.split(" ", 6)[2] == "ack.played"]
        assert lines and "ack_kind=session_open" in lines[0]
    finally:
        daemon.store.close()
