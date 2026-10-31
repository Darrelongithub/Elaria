"""Synthetic fixture/scaffold integrity, NOT hands gate or execution proof."""

import json
from pathlib import Path

import pytest

from assistant.safety import assert_within_sandbox, sha256_file

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures/hands"
INVENTORY = json.loads((FIXTURES / "inventory.json").read_text())


@pytest.mark.parametrize("entry", INVENTORY["entries"], ids=lambda entry: entry["id"])
def test_fixture_inventory_is_local_hashed_data(entry):
    path = assert_within_sandbox(FIXTURES / entry["path"], FIXTURES)
    assert sha256_file(path) == entry["sha256"]
    assert entry["status"] == "inventory-only"
    assert path.is_file()
    if entry["trap"]:
        data = path.name if entry["origin"] == "filename" else path.read_text()
        assert "delete everything now" in data


def test_fixture_inventory_covers_origins_without_claiming_execution():
    assert INVENTORY["synthetic"] is True
    assert len({entry["id"] for entry in INVENTORY["entries"]}) == len(INVENTORY["entries"])
    assert {entry["origin"] for entry in INVENTORY["entries"] if entry["trap"]} == {
        "file", "stdout", "stderr", "filename", "retrieved", "tool_output"}
    assert (FIXTURES / "messy/note.txt").name == (FIXTURES / "filed/note.txt").name
    assert sha256_file(FIXTURES / "messy/note.txt") != sha256_file(FIXTURES / "filed/note.txt")


def test_residual_choices_relay_is_verbatim():
    original = (ROOT / "docs/phase-reports/hands-2026-10-31-survey-revision.md").read_text()
    report = (ROOT / "docs/phase-reports/hands-2026-10-31-partial-001.md").read_text()
    choices = original.split("### R1 —", 1)[1].split(
        "**[UNVERIFIED] Revision acknowledgement requested separately:", 1)[0]
    assert "### R1 —" + choices in report
    for number in range(1, 9):
        assert f"### R{number} —" in choices or number == 1
