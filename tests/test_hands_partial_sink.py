"""Thin telemetry framing/inertness only, NOT event-registry or executor tests."""

import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from assistant.hands.sink import ThinSink, format_line


@pytest.fixture
def fields():
    return {"ts": "2026-10-31T12:00:00+00:00", "level": "INFO", "event": "hands.gate",
            "session_id": "012345abcdef", "peak": "-", "verdict": "refused"}


def test_seven_fields_and_metadata_only(fields):
    output = io.StringIO()
    sink = ThinSink(output)
    assert sink.emit(**fields, paths=["synthetic/a.txt"], hashes=["a" * 64],
                     counts={"steps": 0})
    line = output.getvalue()
    tokens = line.rstrip("\n").split(" ", 6)
    assert len(tokens) == 7
    assert tokens[:6] == list(fields.values())
    assert json.loads(tokens[6]) == {
        "paths": ["synthetic/a.txt"], "hashes": ["a" * 64], "counts": {"steps": 0}}
    assert line.count("\n") == 1
    assert (sink.written, sink.dropped) == (1, 0)


@pytest.mark.parametrize("session", ["-", "a" * 12, "b" * 32, "ABCDEF012345"])
def test_session_shapes(fields, session):
    fields["session_id"] = session
    assert format_line(**fields).split(" ", 6)[3] == session


@pytest.mark.parametrize("session", ["", "a" * 11, "b" * 13, "g" * 12, "a" * 64, "-\n"])
def test_bad_session_normalizes_without_regex_gating_event(fields, session):
    fields["session_id"] = session
    output = io.StringIO()
    sink = ThinSink(output)
    assert sink.emit(**fields)
    assert output.getvalue().split(" ", 6)[3] == "-"
    assert sink.dropped == 0


@pytest.mark.parametrize("field", ["ts", "level", "event", "session_id", "peak", "verdict"])
@pytest.mark.parametrize("payload", ["x\ny", "x\ry", "x\ty", "x y", "\x1b[31m"])
def test_header_cannot_forge_frames(fields, field, payload):
    fields[field] = payload
    output = io.StringIO()
    if field == "session_id":
        assert ThinSink(output).emit(**fields)
        assert output.getvalue().split(" ", 6)[3] == "-"
        assert len(output.getvalue().splitlines()) == 1
    else:
        assert not ThinSink(output).emit(**fields)
        assert output.getvalue() == ""


def test_path_controls_are_data_not_journal_frames(fields):
    path = 'synthetic/"\nERROR hands.exec\r\t\x1b\u2028.txt'
    line = format_line(**fields, paths=[path])
    assert len(line.splitlines()) == 1
    assert "\x1b" not in line
    assert json.loads(line.rstrip("\n").split(" ", 6)[6])["paths"] == [path]


@pytest.mark.parametrize("extra", [
    {"detail": "private command or output"},
    {"command": "private command"},
    {"contents": "private contents"},
    {"counts": {"steps": -1}},
    {"counts": {"steps": True}},
    {"counts": {"steps": 1.2}},
    {"counts": {"steps": float("nan")}},
    {"counts": {"private content": 1}},
    {"hashes": ["not-a-hash"]},
    {"paths": "not-a-list"},
    {"paths": [object()]},
])
def test_rejects_raw_detail_and_malformed_metadata(fields, extra):
    output = io.StringIO()
    sink = ThinSink(output)
    assert not sink.emit(**fields, **extra)
    assert output.getvalue() == ""


def test_sink_rejects_unregistered_events_after_r4_upgrade(fields):
    # R4 now authorizes exhaustive membership validation.
    fields["event"] = "hands.synthetic_test_only"
    with pytest.raises(ValueError):
        format_line(**fields)
    fields["event"] = "other.synthetic_test_only"
    with pytest.raises(ValueError):
        format_line(**fields)


@pytest.mark.parametrize("failure", ["write", "flush", "short"])
def test_io_failure_inert_no_retry_or_exception_text(fields, failure):
    class FaultyStream:
        writes = 0
        flushes = 0

        def write(self, line):
            self.writes += 1
            if failure == "write":
                raise OSError("private diagnostic must not be forwarded")
            return len(line) - 1 if failure == "short" else len(line)

        def flush(self):
            self.flushes += 1
            raise OSError("private diagnostic must not be forwarded")

    stream = FaultyStream()
    sink = ThinSink(stream)
    assert not sink.emit(**fields)
    assert stream.writes == 1
    assert stream.flushes == (1 if failure == "flush" else 0)
    assert (sink.written, sink.dropped) == (0, 1)


def test_closed_stream_is_an_observable_drop(fields):
    stream = io.StringIO()
    stream.close()
    sink = ThinSink(stream)
    assert not sink.emit(**fields)
    assert sink.dropped == 1


def test_concurrent_lines_stay_whole(fields):
    output = io.StringIO()
    sink = ThinSink(output)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda i: sink.emit(**fields, counts={"index": i}), range(100)))
    assert all(results)
    lines = output.getvalue().splitlines()
    assert len(lines) == 100
    assert {json.loads(line.split(" ", 6)[6])["counts"]["index"] for line in lines} == set(range(100))
    assert (sink.written, sink.dropped) == (100, 0)
