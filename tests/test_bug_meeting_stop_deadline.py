"""A stalled Gemini file upload must respect meeting.stop's total budget."""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from assistant.gemini_client import _SdkTransport
from assistant.ipc import DaemonError, call


class _BlockingUpload:
    def __init__(self, release: threading.Event, entered: threading.Event,
                 finished: threading.Event):
        self.release = release
        self.entered = entered
        self.finished = finished

    def upload(self, *, file, config=None):
        self.entered.set()
        timeout_ms = ((config or {}).get("http_options") or {}).get("timeout")
        try:
            if timeout_ms is None:
                self.release.wait(5)
            else:
                self.release.wait(timeout_ms / 1000)
            raise TimeoutError("controlled upload deadline")
        finally:
            self.finished.set()


class _AsyncBlockingUpload:
    def __init__(self, stage, entered, finished):
        self.stage = stage
        self.entered = entered
        self.finished = finished

    async def upload(self, *, file, config=None):
        if self.stage == "upload":
            self.entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.finished.set()
        return object()


class _AsyncBlockingModels:
    def __init__(self, stage, entered, finished):
        self.stage = stage
        self.entered = entered
        self.finished = finished

    async def generate_content(self, **_kwargs):
        if self.stage != "generation":
            raise AssertionError("generation must not start during upload test")
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.finished.set()


class _UnusedModels:
    def generate_content(self, **_kwargs):
        raise AssertionError("the upload must time out before model generation")


@pytest.mark.parametrize("stage", ["upload", "generation"])
def test_bug_meeting_stop_bounds_live_request_and_retains_raw_audio(
        config, running_daemon, stage):
    daemon, server = running_daemon
    loop = server.get_loop()
    session_id = f"meeting-deadline-{uuid.uuid4().hex}"
    release = threading.Event()
    upload_entered = threading.Event()
    upload_finished = threading.Event()
    files = _BlockingUpload(release, upload_entered, upload_finished)
    daemon.client.mode = "live"
    transport = _SdkTransport.__new__(_SdkTransport)
    transport._client = SimpleNamespace(
        files=files, models=_UnusedModels(),
        aio=SimpleNamespace(
            files=_AsyncBlockingUpload(stage, upload_entered, upload_finished),
            models=_AsyncBlockingModels(stage, upload_entered, upload_finished)))
    daemon.client._transport = transport
    daemon.meetings.mode_manager = SimpleNamespace(
        status=lambda refresh=False: SimpleNamespace(is_offline=False))
    daemon._meeting_stop_timeout_s = 0.2

    class Dual:
        async def aclose(self):
            return None

    async def prepare_meeting():
        frame = b"\x70\x17" * 480
        daemon._meeting = {
            "session_id": session_id,
            "dual": Dual(),
            "frames": {"mic": [frame] * 20, "sys": [frame] * 20},
            "task": asyncio.create_task(asyncio.sleep(3600)),
        }
        daemon.mode = "meeting"

    asyncio.run_coroutine_threadsafe(prepare_meeting(), loop).result(timeout=1)
    try:
        with pytest.raises(DaemonError, match="raw audio retained") as caught:
            call(config.socket_path, "meeting.stop", {"title": "deadline"},
                 timeout=1.0)
        assert upload_entered.is_set(), f"the live {stage} request was not reached"
        assert upload_finished.wait(1), f"the async {stage} request did not cancel on deadline"
        message = str(caught.value)
        retained_paths = [Path(word) for word in message.split()
                          if word.endswith(".wav")]
        assert len(retained_paths) == 2
        assert all(path.is_file() for path in retained_paths)
        assert daemon.mode == "idle"
        assert not daemon._meeting_processing
        assert not daemon._meeting_stop_tasks
    finally:
        release.set()
        if upload_entered.is_set():
            assert upload_finished.wait(1), "test cleanup could not release the upload"
        asyncio.run_coroutine_threadsafe(asyncio.sleep(0.05), loop).result(timeout=1)


def test_bug_meeting_sdk_requests_receive_remaining_deadline(
        config, running_daemon, tmp_path):
    from assistant.capture import write_wav

    daemon, _server = running_daemon
    upload_configs = []
    generation_configs = []

    class Files:
        async def upload(self, *, file, config=None):
            upload_configs.append(config)
            await asyncio.sleep(0.05)
            return object()

    class Models:
        async def generate_content(self, *, model, contents, config=None):
            generation_configs.append(config)
            return SimpleNamespace(text="meeting transcript")

    transport = _SdkTransport.__new__(_SdkTransport)
    transport._client = SimpleNamespace(
        aio=SimpleNamespace(files=Files(), models=Models()))
    daemon.client.mode = "live"
    daemon.client._transport = transport
    wav = write_wav(tmp_path / "utterance.wav", [b"\x70\x17" * 480], 16000)

    result = asyncio.run(daemon.client.transcribe_batch_async(
        wav, deadline=time.monotonic() + 30.0))

    assert result["text"] == "meeting transcript"
    assert len(upload_configs) == len(generation_configs) == 1
    upload_timeout = upload_configs[0]["http_options"]["timeout"]
    generation_timeout = generation_configs[0]["http_options"]["timeout"]
    assert 20_000 <= generation_timeout < upload_timeout <= 30_000


def test_bug_meeting_live_async_success_persists_note_and_ledger(
        config, running_daemon, tmp_path):
    from assistant.capture import write_wav

    daemon, _server = running_daemon
    uploads = []
    generations = []

    class Files:
        async def upload(self, *, file, config=None):
            uploads.append((file, config))
            return object()

    class Models:
        async def generate_content(self, *, model, contents, config=None):
            generations.append((model, config))
            return SimpleNamespace(text=f"async transcript {len(generations)}")

    transport = _SdkTransport.__new__(_SdkTransport)
    transport._client = SimpleNamespace(
        aio=SimpleNamespace(files=Files(), models=Models()))
    daemon.client.mode = "live"
    daemon.client._transport = transport
    daemon.meetings.mode_manager = SimpleNamespace(
        status=lambda refresh=False: SimpleNamespace(is_offline=False))
    frame = b"\x70\x17" * 480
    mic = write_wav(tmp_path / "live-mic.wav", [frame] * 20, 16000)
    system = write_wav(tmp_path / "live-system.wav", [frame] * 20, 16000)

    result = asyncio.run(daemon.meetings.transcribe_dual_async(
        mic, system, title="live async success",
        deadline=time.monotonic() + 30.0))

    assert len(uploads) == len(generations) == 2
    assert len(result.turns) == 2
    assert "You: async transcript 1" in result.transcript
    assert "Them: async transcript 2" in result.transcript
    assert result.mic_wav.is_file() and result.system_wav.is_file()
    note = result.note_path.read_text(encoding="utf-8")
    assert "title: live async success" in note
    assert "You: async transcript 1" in note
    row = next(item for item in daemon.store.recent_transcripts(limit=10)
               if item["session_id"] == f"meeting-{result.note_path.stem.removeprefix('meeting-')}" )
    assert row["audio_path"] == str(result.mic_wav)
    assert row["inbox_path"] == str(result.note_path)
    assert "Them: async transcript 2" in row["raw_text"]


def test_bug_daemon_aclose_cancels_pending_live_meeting_stop(config):
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    started = asyncio.Event()
    cancelled = asyncio.Event()
    logged_calls = []

    class Files:
        async def upload(self, *, file, config=None):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    class Models:
        async def generate_content(self, **_kwargs):
            raise AssertionError("generation must not start")

    class Dual:
        async def aclose(self):
            return None

    async def run():
        transport = _SdkTransport.__new__(_SdkTransport)
        transport._client = SimpleNamespace(
            aio=SimpleNamespace(files=Files(), models=Models()))
        daemon.client.mode = "live"
        daemon.client._transport = transport
        daemon.store.log_llm_call = lambda **fields: logged_calls.append(fields)
        daemon.meetings.mode_manager = SimpleNamespace(
            status=lambda refresh=False: SimpleNamespace(is_offline=False))
        daemon._meeting_stop_timeout_s = 30.0
        frame = b"\x70\x17" * 480
        daemon._meeting = {
            "session_id": "shutdown-during-meeting-stop",
            "dual": Dual(),
            "frames": {"mic": [frame] * 20, "sys": [frame] * 20},
            "task": asyncio.create_task(asyncio.sleep(3600)),
        }
        daemon.mode = "meeting"
        stop_task = asyncio.create_task(daemon._meeting_stop({}))
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            assert stop_task in daemon._meeting_stop_tasks
            await daemon.aclose()
            assert stop_task.done()
            assert stop_task.cancelled()
            assert cancelled.is_set()
            assert len(logged_calls) == 1
            assert logged_calls[0]["ok"] == 0
            assert logged_calls[0]["error"].startswith("CancelledError")
            assert not daemon._meeting_processing
            assert not daemon._meeting_stop_tasks
        finally:
            if not stop_task.done():
                stop_task.cancel()
                await asyncio.gather(stop_task, return_exceptions=True)
            if daemon._background_tasks:
                await asyncio.gather(*daemon._background_tasks, return_exceptions=True)

    asyncio.run(run())


def test_bug_meeting_stop_capture_close_failure_closes_peer_and_keeps_raw(config):
    from assistant.capture import DualCapture
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    mic_attempted = asyncio.Event()
    system_started = asyncio.Event()
    release_system_close = asyncio.Event()
    system_closed = asyncio.Event()
    collector_cancelled = asyncio.Event()
    session_id = f"close-failure-{uuid.uuid4().hex}"

    class Mic:
        async def aclose(self):
            mic_attempted.set()
            raise RuntimeError("controlled mic close failure")

    class System:
        async def aclose(self):
            system_started.set()
            await release_system_close.wait()
            system_closed.set()

    async def collect():
        try:
            await asyncio.sleep(3600)
        finally:
            collector_cancelled.set()

    async def run():
        frame = b"\x70\x17" * 480
        collector = asyncio.create_task(collect())
        daemon._meeting = {
            "session_id": session_id,
            "dual": DualCapture(Mic(), System()),
            "frames": {"mic": [frame] * 20, "sys": [frame] * 20},
            "task": collector,
        }
        daemon.mode = "meeting"
        stop_task = asyncio.create_task(daemon._meeting_stop({}))
        try:
            await asyncio.wait_for(system_started.wait(), timeout=1)
            await asyncio.sleep(0.02)
            assert not stop_task.done(), "stop returned before peer capture close finished"
            release_system_close.set()
            with pytest.raises(RuntimeError, match="meeting capture close failed") as caught:
                await stop_task
            assert isinstance(caught.value.__cause__, RuntimeError)
            assert "controlled mic close failure" in str(caught.value.__cause__)
            assert mic_attempted.is_set()
            assert system_closed.is_set()
            assert collector.done() and collector_cancelled.is_set()
            raw = list((config.data_dir / "audio").glob(
                f"meeting-*-{session_id}-*.wav"))
            assert len(raw) == 2 and all(path.is_file() for path in raw)
            assert daemon.mode == "idle"
        finally:
            release_system_close.set()
            if not collector.done():
                collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
            if not stop_task.done():
                stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
            await daemon.aclose()

    asyncio.run(run())


def test_bug_meeting_stop_capture_source_cancel_keeps_raw_audio(config):
    from assistant.capture import DualCapture
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    system_closed = asyncio.Event()
    collector_cancelled = asyncio.Event()
    session_id = f"source-cancel-{uuid.uuid4().hex}"

    class Mic:
        async def aclose(self):
            raise asyncio.CancelledError

    class System:
        async def aclose(self):
            system_closed.set()
            raise RuntimeError("controlled system close failure")

    async def collect():
        try:
            await asyncio.sleep(3600)
        finally:
            collector_cancelled.set()

    async def run():
        frame = b"\x70\x17" * 480
        collector = asyncio.create_task(collect())
        daemon._meeting = {
            "session_id": session_id,
            "dual": DualCapture(Mic(), System()),
            "frames": {"mic": [frame] * 20, "sys": [frame] * 20},
            "task": collector,
        }
        daemon.mode = "meeting"
        try:
            with pytest.raises(RuntimeError, match="meeting capture close failed") as caught:
                await daemon._meeting_stop({})
            capture_error = caught.value.__cause__
            assert isinstance(capture_error, RuntimeError)
            assert isinstance(capture_error.__cause__, asyncio.CancelledError)
            assert "controlled system close failure" in " ".join(
                getattr(capture_error, "__notes__", []))
            assert system_closed.is_set()
            assert collector.done() and collector_cancelled.is_set()
            raw = list((config.data_dir / "audio").glob(
                f"meeting-*-{session_id}-*.wav"))
            assert len(raw) == 2 and all(path.is_file() for path in raw)
            assert daemon.mode == "idle"
        finally:
            if not collector.done():
                collector.cancel()
                await asyncio.gather(collector, return_exceptions=True)
            await daemon.aclose()

    asyncio.run(run())


def test_bug_meeting_stop_shutdown_finishes_both_capture_closes(config):
    from assistant.capture import DualCapture
    from assistant.daemon import Daemon

    daemon = Daemon(config)
    mic_started = asyncio.Event()
    release_mic_close = asyncio.Event()
    system_closed = asyncio.Event()
    mic_closed = asyncio.Event()

    class Capture:
        def __init__(self, *, wait_for_release=False):
            self.wait_for_release = wait_for_release

        async def aclose(self):
            if self.wait_for_release:
                mic_started.set()
                await release_mic_close.wait()
                mic_closed.set()
            else:
                system_closed.set()

    async def run():
        dual = DualCapture(Capture(wait_for_release=True), Capture())
        daemon._meeting = {
            "session_id": "shutdown-during-capture-close",
            "dual": dual,
            "frames": {"mic": [], "sys": []},
            "task": asyncio.create_task(asyncio.sleep(3600)),
        }
        daemon.mode = "meeting"
        stop_task = asyncio.create_task(daemon._meeting_stop({}))
        await asyncio.wait_for(mic_started.wait(), timeout=1)
        shutdown_task = asyncio.create_task(daemon.aclose())
        await asyncio.sleep(0)
        release_mic_close.set()
        await shutdown_task
        assert stop_task.cancelled()
        assert mic_closed.is_set()
        assert system_closed.is_set()
        assert daemon.mode == "idle"

    asyncio.run(run())


def test_bug_meeting_persists_a_completed_transcript_after_budget(config, tmp_path):
    from assistant.capture import write_wav
    from assistant.diarize import Turn
    from assistant.meeting import MeetingService
    from assistant.store import Store

    store = Store(config.db_path)
    service = MeetingService(config, store, client=None)
    mic = write_wav(tmp_path / "mic.wav", [b"\x70\x17" * 480], 16000)
    system = write_wav(tmp_path / "system.wav", [b"\x70\x17" * 480], 16000)

    def complete_transcript(_wav, speaker, _work, *, deadline):
        time.sleep(0.005)
        return [Turn(speaker, 0.0, 0.5, f"{speaker} complete")]

    original_log = store.log_transcript

    def delayed_log(**kwargs):
        time.sleep(0.07)
        return original_log(**kwargs)

    service._transcribe_channel = complete_transcript
    store.log_transcript = delayed_log
    try:
        result = service.transcribe_dual(
            mic, system, title="deadline completion",
            deadline=time.monotonic() + 0.05)
        assert "You: You complete" in result.transcript
        assert "Them: Them complete" in result.transcript
        assert "You: You complete" in result.note_path.read_text(encoding="utf-8")
    finally:
        store.close()
