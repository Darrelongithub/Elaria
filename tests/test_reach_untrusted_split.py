"""Eye-check 3: IF-6 untrusted structural split, import graph, and armed traps."""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from assistant.hands.injection import DataInput, load_observation, suspected
from assistant.reach import FetchedDoc, ReachConfig, fetch
from assistant.safety_journal import JournalLog

ROOT = Path(__file__).resolve().parents[1]
REACH_DIR = ROOT / "src" / "assistant" / "reach"
FORBIDDEN_IMPORTS = ("hands.plan", "hands.runner", "hands.executor", "intents", "planner", "executor")


def test_reach_import_graph_forbids_action_and_intent_modules():
    for py_file in REACH_DIR.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in FORBIDDEN_IMPORTS:
                        assert forbidden not in alias.name, f"{py_file.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                for forbidden in FORBIDDEN_IMPORTS:
                    assert forbidden not in mod, f"{py_file.name} imports from {mod}"


def test_fetched_doc_is_always_untrusted_and_exits_as_data_input():
    doc = FetchedDoc(
        url="https://example.com",
        final_url="https://example.com/",
        channel="web",
        status_code=200,
        content_type="text/plain",
        title="Example",
        text="hello",
        excerpt="hello",
    )
    assert doc.trusted is False
    with pytest.raises(AttributeError):
        doc.trusted = True  # type: ignore[misc]

    data = doc.to_data_input("web")
    assert isinstance(data, DataInput)
    assert data.origin == "web"

    mem = doc.as_memory_kwargs(confidence=0.99)
    assert mem["source"] == "inferred"
    assert mem["kind"] == "finding"
    assert mem["confidence"] <= 0.5
    assert "https://example.com/" in mem["evidence"]


def test_armed_web_trap_fixture_is_refused_by_injection_rail(tmp_path):
    trap_path = ROOT / "fixtures" / "hands" / "traps" / "web.txt"
    trap_body = trap_path.read_text(encoding="utf-8")
    journal = JournalLog(tmp_path / "journal.jsonl")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, headers={"content-type": "text/plain"}, text=trap_body)

    res = fetch(
        "https://example.com/trap",
        journal=journal,
        config=ReachConfig(enabled=True),
        resolver=lambda _h, _p: ["93.184.216.34"],
        transport=httpx.MockTransport(handler),
    )
    assert res.ok is True and res.doc is not None
    data = res.doc.to_data_input("web")
    assert suspected(data) is True

    recorded: list[tuple[str, str, str]] = []
    out = load_observation(data, record=lambda o, d, v: recorded.append((o, d, v)))
    assert out is data
    assert recorded and recorded[0][2] == "refused"
