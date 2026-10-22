"""Event transcriber — CLI smoke through the real daemon socket (§7).

`assist event start|stop|status|speaker` exercised via cli.main() against the
real Daemon on a real Unix socket. Capture falls back to the simulated source
on a headless box (no PipeWire) — the same fallback `event start` uses in the
container. The daemon-down recovery path is covered with hand-built disk
state, exactly what a killed daemon leaves behind.
"""

from __future__ import annotations

import json
import struct
import time
from pathlib import Path

SPEECH_FRAME = struct.pack("<480h", *([6000] * 480))


def _run_cli(argv: list[str]) -> int:
    from assistant import cli

    return cli.main(argv)


def _wait_segments(service, minimum: int = 2, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    opened = 0
    while time.monotonic() < deadline:
        opened = service.status()["segments"]["opened"]
        if opened >= minimum:
            return opened
        time.sleep(0.05)
    return opened


def test_event_cli_smoke_start_status_speaker_stop(running_daemon, config, capsys):
    daemon, _server = running_daemon

    rc = _run_cli(["event", "start", "--title", "Panel Dry Run",
                   "--speakers", "Amina,John", "--segment-minutes", "0.05",
                   "--battery-ok"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Event capture ON" in out
    assert "Document:" in out

    # status: running state is visible
    rc = _run_cli(["event", "status"])
    out = capsys.readouterr().out
    assert rc == 0
    status = json.loads(out)
    assert status["running"] is True
    assert status["active_speaker"] == "Amina"
    assert status["document"].endswith(".md")

    # speaker: next, named jump, and bare print
    rc = _run_cli(["event", "speaker", "next"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "John" in out

    rc = _run_cli(["event", "speaker", "Amina"])
    out = capsys.readouterr().out
    assert rc == 0

    rc = _run_cli(["event", "speaker"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Amina" in out
    assert "elapsed" in out.lower()

    # let a couple of segments rotate through the simulated capture
    assert _wait_segments(daemon.event_service, minimum=2) >= 2

    rc = _run_cli(["event", "stop"])
    captured = capsys.readouterr().out
    assert rc == 0
    assert "Document:" in captured
    assert "segment" in captured.lower()

    # the document exists and is assembled
    st = daemon.event_service.status()
    doc = Path(st["document"])
    assert doc.exists()
    text = doc.read_text()
    assert "Panel Dry Run" in text
    assert "seg 001" in text
    assert (doc.parent / (doc.stem + ".txt")).exists()   # mirrored .txt
    assert (doc.parent / doc.stem / "labels.json").exists()

    # status after stop is honest
    rc = _run_cli(["event", "status"])
    out = capsys.readouterr().out
    assert json.loads(out)["running"] is False


def test_event_cli_second_start_refused(running_daemon, config, capsys):
    daemon, _server = running_daemon
    rc = _run_cli(["event", "start", "--title", "One", "--battery-ok"])
    assert rc == 0
    capsys.readouterr()
    rc = _run_cli(["event", "start", "--title", "Two", "--battery-ok"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "already" in out.lower()
    st = daemon.event_service.status()
    assert st["running"] is True
    assert "One" in st["title"]
    _run_cli(["event", "stop"])
    capsys.readouterr()


def test_event_cli_stop_without_event_is_honest(running_daemon, config, capsys):
    rc = _run_cli(["event", "stop"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no event" in out.lower() or "not running" in out.lower()


def test_event_cli_status_daemon_down_reads_state_from_disk(config, capsys):
    """Post-mortem status + stop recovery must work with the daemon gone (§5)."""
    from assistant.capture import write_wav

    event_dir = config.data_dir / "events" / "2026-10-22-crash-test"
    seg_dir = event_dir / "segments"
    seg_dir.mkdir(parents=True)
    write_wav(seg_dir / "seg-001.wav", [SPEECH_FRAME])
    write_wav(seg_dir / "seg-002.wav", [SPEECH_FRAME])
    (seg_dir / "seg-001.txt").write_text("survived the crash\n")
    (event_dir / "labels.json").write_text(json.dumps({
        "title": "Crash Test", "roster": ["Amina"],
        "segments": {"001": "Amina", "002": "Amina"}}))
    (event_dir / "state.json").write_text(json.dumps({
        "title": "Crash Test", "status": "running", "route": "batch",
        "segment_minutes": 30, "active_speaker": "Amina", "roster": ["Amina"],
        "segment_index": 3,
        "segments": [
            {"index": 1, "wav": str(seg_dir / "seg-001.wav"), "speaker": "Amina",
             "opened_at": "2026-10-22T09:00:00", "closed_at": "2026-10-22T09:30:00",
             "status": "done", "txt": str(seg_dir / "seg-001.txt"),
             "bytes": 100, "peak": 0.5, "markers": [], "no_signal": False},
            {"index": 2, "wav": str(seg_dir / "seg-002.wav"), "speaker": "Amina",
             "opened_at": "2026-10-22T09:30:00", "closed_at": None,
             "status": "open", "txt": None,
             "bytes": 100, "peak": 0.5, "markers": [], "no_signal": False},
        ]}))

    # status works with no daemon: assembled from disk
    rc = _run_cli(["event", "status"])
    out = capsys.readouterr().out
    assert rc == 0
    status = json.loads(out)
    assert status.get("running") is True or status.get("state") == "running"
    assert "Crash Test" in status.get("title", "")

    # stop with no daemon: recovery assembly — nothing discarded
    rc = _run_cli(["event", "stop"])
    out = capsys.readouterr().out
    assert rc == 0
    doc = config.data_dir / "events" / "2026-10-22-crash-test.md"
    assert doc.exists()
    text = doc.read_text()
    assert "survived the crash" in text
    assert "audio kept" in text                     # seg 002 explicit marker
    state = json.loads((event_dir / "state.json").read_text())
    assert state["status"] in ("recovered", "stopped")


def test_event_cli_start_refuses_on_low_disk(running_daemon, config, capsys,
                                             monkeypatch):
    import assistant.event as event_mod

    daemon, _server = running_daemon
    monkeypatch.setattr(event_mod, "free_disk_bytes", lambda root: 10 * 1024 * 1024)

    rc = _run_cli(["event", "start", "--title", "Tiny Disk", "--battery-ok"])
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert rc != 0
    assert "disk" in out.lower()
    assert daemon.event_service.status()["running"] is False
