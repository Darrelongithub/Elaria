"""Wake audio uses the hotkey batch gateway and the hotkey result finisher.

No devices, models, or network. The positive control is in the same test as
all refusals so removing the wiring cannot make the refusal checks pass alone.
"""
import asyncio
import wave
from types import SimpleNamespace

from assistant import asr
from assistant.daemon import Daemon
from assistant.wake_guard import MIN_WINDOW_S, SAMPLE_RATE
from test_z_hotword_listen_wiring import ScriptedScorer, ScriptedSttModel, speech_frame


async def test_verified_wake_dictation_and_fail_closed_cases(config, monkeypatch):
    daemon = Daemon(config)
    guard = daemon.wake_guard
    calls, replies, events = [], [], []
    mode = {"failure": False, "callback_failure": False, "confidence": .98}
    stop_loop = asyncio.Event()
    loop_frames = asyncio.Queue()

    class Capture:
        async def frames(self):
            while not stop_loop.is_set():
                yield await loop_frames.get()
        async def aclose(self):
            pass

    async def broadcast(event):
        events.append(event)
        if event.get("event") == "ptt.result" and mode["callback_failure"]:
            raise RuntimeError("broken subscriber")

    async def ask(params):
        replies.append(params)
        return {"reply": "ok"}

    def fake_asr(config, client, path, **kwargs):
        with wave.open(path, 'rb') as f:
            assert (f.getnchannels(), f.getsampwidth(), f.getframerate()) == (1, 2, SAMPLE_RATE)
            calls.append((f.readframes(f.getnframes()), kwargs))
        if mode["failure"]:
            raise RuntimeError("ASR failure")
        return asr.DictationOutcome(text="what time is it", language="en", backend="local",
                                   confidence=mode["confidence"], path="local", labelled=None,
                                   escalation="not_needed", provenance={})

    monkeypatch.setattr(asr, "transcribe_dictation", fake_asr)
    monkeypatch.setattr(asr, "LocalWhisperBackend", lambda *a, **k: (_ for _ in ()).throw(AssertionError("backend constructed")))
    monkeypatch.setattr(daemon.dictation, "_connectivity", lambda: SimpleNamespace(is_offline=True, effective_mode="OFFLINE"))
    monkeypatch.setattr(daemon, "_ask", ask)
    monkeypatch.setattr(daemon, "broadcast", broadcast)
    monkeypatch.setattr(daemon, "_hotword_capture_factory", Capture)
    monkeypatch.setattr(daemon, "_wake_listen_ceiling_s", lambda: 2.6)
    guard.scorer = ScriptedScorer()
    guard.arm(keyword_model=ScriptedSttModel(hits=0))
    loop_task = asyncio.create_task(daemon._hotword_loop())
    await asyncio.sleep(0)

    async def settle(score, seconds=2.5, **kwargs):
        guard.scorer = ScriptedScorer(score)
        guard.trigger(keyword_score=0.99, wake_clip=b'')
        frames = [speech_frame() for _ in range(int(seconds / .03))]
        for frame in frames:
            guard.note_frame(frame)
        verdict = guard.verify(**kwargs)
        await daemon._wake_listen_after_feed(verdict)
        return verdict

    async def wait_background():
        # _wake_listen_session schedules the ASR after releasing the guard.
        for _ in range(500):
            pending = [t for t in daemon._background_tasks if not t.done()]
            if not pending:
                return
            await asyncio.sleep(.002)
        raise AssertionError("background work did not finish")

    async def verified():
        await asyncio.sleep(.003)  # distinct guard session IDs
        verdict = await settle(.92)
        assert verdict['trigger']['outcome'] == 'attending'
        head = guard.session.head
        source = daemon._wake_listen_source
        assert source is not None
        tail = [speech_frame() for _ in range(4)]
        for frame in tail:
            assert source.offer(frame)
        await asyncio.wait_for(daemon._wake_listen_task, 2)
        await wait_background()
        return head + b''.join(tail)

    try:
        # Every refusal is driven through the real verifier and daemon seam.
        for score, seconds, kwargs in [(.1, 2.5, {}), (.6, 2.5, {}),
                                       (.92, MIN_WINDOW_S - .1, {}),
                                       (.92, 2.5, {'replayed': True})]:
            before = len(calls)
            await settle(score, seconds, **kwargs)
            assert daemon._wake_listen_source is None
            assert len(calls) == before == 0

        expected = await verified()
        assert len(calls) == 1 and calls[0][0] == expected
        assert len(replies) == 1 and replies[0]['text'] == 'what time is it'
        assert any(e.get('event') == 'ptt.result' and e['result']['text'] == 'what time is it' for e in events)

        mode['failure'] = True
        before_events = len([e for e in events if e.get('event') == 'ptt.result'])
        before_results = dict(daemon._ptt_results)
        await verified()
        assert len(calls) == 2 and len(replies) == 1
        assert dict(daemon._ptt_results) == before_results
        assert len([e for e in events if e.get('event') == 'ptt.result']) == before_events
        assert not loop_task.done()

        mode['failure'] = False
        mode['callback_failure'] = True
        await verified()
        assert len(calls) == 3 and len(replies) == 2
        assert len([e for e in events if e.get('event') == 'ptt.result']) == before_events + 1
        assert not loop_task.done()
        # The always-on capture still consumes frames after a broken callback.
        previous = guard.keyword_model.calls
        await loop_frames.put(speech_frame())
        for _ in range(100):
            if guard.keyword_model.calls > previous:
                break
            await asyncio.sleep(.002)
        assert guard.keyword_model.calls > previous and not loop_task.done()

        # A verified speaker does not bypass the existing command confidence
        # gate: a low-confidence transcription never reaches the reply path.
        mode['callback_failure'] = False
        mode['confidence'] = .1
        await verified()
        assert len(calls) == 4 and len(replies) == 2
        last = [e for e in events if e.get('event') == 'ptt.result'][-1]
        assert last['result']['command']['via'] == 'refused'
    finally:
        stop_loop.set()
        loop_task.cancel()
        await asyncio.gather(loop_task, return_exceptions=True)
        await wait_background()
        daemon.store.close()
