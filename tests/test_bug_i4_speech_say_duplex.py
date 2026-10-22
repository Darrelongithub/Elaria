"""I4 regressions: local TTS synthesis and playback stay inside the duplex gate."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from assistant.daemon import Daemon
from assistant.ipc import call
from assistant.tts import SpeechResult


def test_bug_i4_speech_say_gate_survives_synthesis_and_delayed_playback(
        config, running_daemon, monkeypatch):
    """I4: speech.say cannot reopen the mic when synthesis outlasts its estimate."""
    daemon, _server = running_daemon
    synthesis_started = Event()
    allow_playback = Event()
    playback_started = Event()
    finish_playback = Event()
    observed = {}

    def delayed_speak(text, *, play=True):
        observed["during_synthesis"] = daemon.is_speaking()
        synthesis_started.set()
        if not allow_playback.wait(timeout=3.0):
            raise TimeoutError("test did not release delayed speech synthesis")
        observed["before_playback"] = daemon.is_speaking()
        playback_started.set()
        if not finish_playback.wait(timeout=3.0):
            raise TimeoutError("test did not release fake playback")
        observed["during_playback"] = daemon.is_speaking()
        return SpeechResult(text=text, backend="test", voice_id="test",
                            played=play)

    monkeypatch.setattr(daemon.speech, "speak", delayed_speak)
    with ThreadPoolExecutor(max_workers=1) as pool:
        request = pool.submit(
            call, config.socket_path, "speech.say",
            {"text": "On it.", "play": True}, timeout=5.0)
        try:
            assert synthesis_started.wait(timeout=1.0)
            # Simulate synthesis taking longer than the text-derived reservation.
            daemon._speaking_until = 0.0
            allow_playback.set()
            assert playback_started.wait(timeout=1.0)
            # The estimate remains expired while the player is still active.
            daemon._speaking_until = 0.0
        finally:
            allow_playback.set()
            finish_playback.set()
        result = request.result(timeout=6.0)

    assert result["speech"]["played"] is True
    assert daemon.is_speaking()  # Real worker ended; only the 400 ms tail remains.
    assert 0 < daemon.speaking_guard_remaining() <= 0.4
    daemon._speaking_until = 0.0
    assert not daemon.is_speaking()
    assert observed == {
        "during_synthesis": True,
        "before_playback": True,
        "during_playback": True,
    }


def test_bug_i4_reply_playback_gate_survives_synthesis_longer_than_estimate(
        config, monkeypatch):
    """I4: a slow synthesis cannot outlive the owner-reply duplex reservation."""
    daemon = Daemon(config)
    synthesis_started = Event()
    finish_synthesis = Event()

    def delayed_speak(text, *, play=True):
        synthesis_started.set()
        if not finish_synthesis.wait(timeout=3.0):
            raise TimeoutError("test did not release reply synthesis")
        return SpeechResult(text=text, backend="test", voice_id="test",
                            played=play)

    monkeypatch.setattr(daemon.speech, "speak", delayed_speak)

    async def run():
        try:
            reply = asyncio.create_task(
                daemon._maybe_speak_reply("On it.", {"speak": True}))
            assert await asyncio.to_thread(synthesis_started.wait, 1.0)
            # Force the text-duration estimate to expire while TTS is still busy.
            daemon._speaking_until = 0.0
            observed = daemon.is_speaking()
            finish_synthesis.set()
            await asyncio.wait_for(reply, timeout=2.0)
            assert observed is True
            assert daemon.is_speaking()  # Worker completion leaves only the tail guard.
            assert 0 < daemon.speaking_guard_remaining() <= 0.4
            daemon._speaking_until = 0.0
            assert not daemon.is_speaking()
        finally:
            finish_synthesis.set()
            await daemon.aclose()

    asyncio.run(run())
