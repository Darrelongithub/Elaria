"""BUG-HW6B: large HTML inspection and per-candidate survey isolation."""

import time

import pytest

from assistant import streamread
from assistant.errand import skill_fs_survey
from assistant.ipc import call


def _wait_for_terminal(socket_path, errand_id):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = call(socket_path, "errand.status", {"errand_id": errand_id}, timeout=5)
        if result["status"] in {"completed", "failed", "budget_exhausted"}:
            return result
        time.sleep(0.03)
    raise AssertionError("survey did not finish")


def _start_survey(config, root):
    started = call(config.socket_path, "errand.start", {
        "instruction": "Tell me what's there, and group it by what it seems to be for",
        "roots": [str(root)],
        "budget": {"max_api_calls": 0},
    }, timeout=5)
    return _wait_for_terminal(config.socket_path, started["errand_id"])


@pytest.mark.parametrize("extension", ["html", "xml"])
def test_large_markup_inspects_without_inventing_record_estimate(tmp_path, extension):
    path = tmp_path / f"large.{extension}"
    path.write_text("<body>" + "<p>hello</p>" * 600 + "</body>", encoding="utf-8")
    result = streamread.inspect(path, skeleton_bytes=4096)
    assert result.skeleton["sample_bytes"] == 4096
    assert result.skeleton["elements"]
    assert "estimate" not in result.skeleton


def test_large_line_skeleton_still_marks_estimate_inexact(tmp_path):
    path = tmp_path / "large.txt"
    path.write_text("a line of text\n" * 500, encoding="utf-8")
    result = streamread.inspect(path, skeleton_bytes=4096)
    assert result.skeleton["estimate"]["exact"] is False


def test_large_html_survey_errand_completes(tmp_path, config, running_daemon):
    root = tmp_path / "downloads"
    root.mkdir()
    html = root / "large.html"
    html.write_text("<p>hello world</p>" * 500, encoding="utf-8")
    (root / "note.txt").write_text("a readable note\n", encoding="utf-8")

    done = _start_survey(config, root)
    assert done["status"] == "completed", done
    survey = next(s for s in done["steps"] if s["skill"] == "fs.survey")
    assert survey["status"] == "ok", survey
    assert survey["result"]["metadata_covered"] == 2
    assert survey["result"]["survey_errors"] == 0
    assert done["report"]["coverage"]["metadata_covered"] == 2


def test_unexpected_inspection_error_is_named_and_siblings_complete(
    tmp_path, config, running_daemon, monkeypatch,
):
    root = tmp_path / "downloads"
    root.mkdir()
    bad = root / "bad.txt"
    good = root / "good.txt"
    bad.write_text("failure fixture\n", encoding="utf-8")
    good.write_text("readable sibling\n", encoding="utf-8")
    original = streamread.inspect

    def flaky_inspect(target, **kwargs):
        if str(target) == str(bad):
            raise KeyError("unexpected inspection failure")
        return original(target, **kwargs)

    monkeypatch.setattr(streamread, "inspect", flaky_inspect)
    sweep = skill_fs_survey(
        [{"target": str(bad)}, {"target": str(good)}],
        roots=[str(root)], protected=[], never_send_roots=[],
    )
    assert sweep["covered"] == 1
    assert sweep["errors"] == 1
    assert sweep["records"][0]["target"] == str(bad)
    assert "KeyError" in sweep["records"][0]["error"]
    assert "unexpected inspection failure" in sweep["records"][0]["error"]
    assert sweep["records"][1]["digest"]

    done = _start_survey(config, root)
    assert done["status"] == "completed", done
    survey = next(s for s in done["steps"] if s["skill"] == "fs.survey")
    assert survey["status"] == "ok"
    assert survey["result"]["metadata_covered"] == 1
    assert survey["result"]["survey_errors"] == 1
    coverage = done["report"]["coverage"]
    assert coverage["metadata_covered"] == 1
    assert coverage["content_read"] == 1
    assert any(skip["target"] == str(bad) and "KeyError" in skip["reason"]
               and "unexpected inspection failure" in skip["reason"]
               for skip in coverage["skipped"])


def test_stream_error_is_not_counted_as_metadata_coverage(tmp_path):
    missing = tmp_path / "missing.txt"
    good = tmp_path / "good.txt"
    good.write_text("readable\n", encoding="utf-8")
    sweep = skill_fs_survey(
        [{"target": str(missing)}, {"target": str(good)}],
        roots=[str(tmp_path)], protected=[], never_send_roots=[],
    )
    assert sweep["covered"] == 1
    assert sweep["errors"] == 1
    assert "StreamError" in sweep["records"][0]["error"]
    assert sweep["records"][1]["digest"]
